"""Optional vision check — one narrow question about a finished image (FR-27, FR-105).

Module contract
---------------
Purpose: ask ONE Sonnet 5 vision pass whether rendered images carry broken text, fake platform UI
or text that does not match what the asset was ordered to say, hand back per-image verdicts, and
own the arithmetic of FR-105's single retry. Callers decide what to ship — a check never blocks a
ship (D3, 10 §10 "a broken checker must never block delivery").

Public API:
    await check(images, expected=..., sanctioned_marks=..., call=..., engine=...) -> CheckReport
    expected_text(copy, creative_format, slide_text=..., wordmark=..., slide_counter=...) -> str
    retry_plan(copy, creative_format, budgets, slide_text=..., verbatim=..., verdict=...)
        -> RetryPlan
    verdict_result(first, after_retry=None, retried=...) -> VisionCheckResult   (FR-27's 4 states)
    CheckReport · ImageVerdict · RetryPlan · VISION_CHECK_ROLE · RETRY_INSTRUCTION
    VERBATIM_RETRY_INSTRUCTION

Invariants enforced here, once, for every caller:
- **Check inputs are NEVER downscaled (FR-105).** FR-93's ~1024 px re-encode is analysis-only: a
  42-character headline on a 1024 px JPEG is where a model stops telling a malformed glyph from
  compression, and Czech diacritics are the first casualty. Bytes go out exactly as rendered.
- **The check CARRIES the expected text (FR-105, v2.1.1).** Three defects are asked about, and the
  third — *do the rendered words match the words this asset was ordered to carry?* — is
  unanswerable without a referent. The 2026-08-13 audit shipped a slide whose source panel said
  "CLAUDE + OBSIDIAN = 71.5X FEWER TOKENS" and whose render carried unrelated invented copy, clean
  and legible and therefore unflagged. `expected` travels per image, in caller order, and an EMPTY
  expected string is a real statement, not an absence: that image is wordless by design, so any
  readable words invented on it are a flag.
- **One call per deck (FR-105/107).** A carousel's slides are checked together and come back with
  per-slide verdicts; N slides never cost N calls, and the estimator prices it the same way.
  Verdict indices are the CALLER's positions — an unreadable input is skipped, never a shift.
- **Ship either way (FR-27).** Nothing raises. Transport failure, unreadable input, bad template
  and malformed answer all come back as `checked=False`, which is `NOT_CHECKED`.
- **The retry changes the INPUT, not the plea (FR-105).** `retry_plan()` cuts free-composed
  on-image text at a word boundary to −`retry_reduction_pct`% of the budget in force and drops the
  optional block. Re-sending the same prompt with "please fix the text" is what this avoids. One
  retry (NFR-4), then ship.
- **The retry is told WHICH defect was seen (D-F, v2.1.2).** Three defects earn the one re-render
  and they need three different remedies: less text and larger type fixes broken glyphs, and does
  nothing at all for a render that invented words or drew a fake interface. The verdict's own
  `detail` is quoted into the instruction and the offending thing is forbidden by name, so the
  second attempt is a different REQUEST rather than a second roll of the same dice.
- **A mapped panel's text is never trimmed, retry included (FR-304 > FR-105, v2.1.1).** Under a
  panel map our slide *i* IS source panel *i*, verbatim; cutting it to 60% of a budget produces a
  mid-sentence stub — the very defect this module exists to catch, applied by us on purpose. For
  those slides `retry_plan(verbatim=True)` changes the LAYOUT only (fewer decorative elements,
  larger type) and hands the text back byte for byte. The cut that remains is measured against the
  slot that actually governs the asset — `slide` for a deck, never `image_headline`.

Do not: downscale a check input; call the LLM without the `StructuredCall` seam; write the
question by hand (it is `prompts/vision_check_question.md`, FR-181); retry more than once; trim a
verbatim quote; check a finished video clip (FR-105 excludes it — frame extraction would mean
ffmpeg, D10).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import httpx

from hypesocials.config import TextBudgets
from hypesocials.models import CopySet, StructuredCall, VisionCheckResult
from hypesocials.prompts_engine import PromptEngine, trim_words

logger = logging.getLogger(__name__)

#: FR-27 makes the check a Claude Sonnet 5 pass, so it rides the `analysis` role — `models.analysis`
#: and `max_tokens.analysis` already point at that model. Config defines no separate vision-check
#: model key, and inventing one would be a config change, not a module decision.
VISION_CHECK_ROLE = "analysis"
QUESTION_TEMPLATE = "vision_check_question.md"  # FR-181: a GLOBAL role template, flat in prompts/

#: FR-105's third retry lever, stated in 10-pipeline and therefore a mandatory clause under
#: FR-180. The −40% text and the dropped block travel in the prompt's own text slot; this line is
#: what the re-render adds on top. W4 callers append it to the assembled render prompt.
RETRY_INSTRUCTION = (
    "This is a re-render of an image whose text came back broken. Set the remaining text "
    "noticeably larger and heavier than a normal layout would: one text block only, maximum "
    "legible size inside the safe zone."
)

#: The same lever for an asset whose words may not be touched (FR-304 > FR-105, v2.1.1). Every
#: difference this retry can make is layout-side, so it says so — and it says the text is locked
#: out loud, because the render model reading it is the one being asked not to "helpfully" shorten
#: a long panel to make it fit.
VERBATIM_RETRY_INSTRUCTION = (
    "This is a re-render of an image whose text came back broken. The words are a verbatim quote "
    "and are LOCKED: reproduce every character of them, shortening nothing and rewording nothing. "
    "Change the layout instead — fewer decorative elements, a simpler background, one text block "
    "only, and the largest legible type that fits the safe zone at that length."
)

#: D-F's defect clauses, appended to whichever base instruction is in force. Each one names the
#: thing the previous render actually did (the verdict's `detail`, quoted) and then forbids it —
#: "shorter and larger" is a remedy for a garbled glyph and a no-op for invented copy.
_MISMATCH_CLAUSE = (
    "The previous render invented or altered words — {detail}. Render the invented words nowhere: "
    "the TEXT block is complete and exhaustive, and every character in the frame comes from it.")
_FAKE_UI_CLAUSE = (
    "The previous render drew platform interface chrome — {detail}. Draw none of it: no app or "
    "social interface, no watermark, no username or @handle, no profile picture, no follower, "
    "like, view or comment counter, no play button and no progress bar, neither copied from a "
    "reference nor invented to look native.")
#: What a defect clause says when the model returned no detail at all. The clause is still worth
#: sending — "you invented words" is actionable on its own — and a dangling em dash is not.
_NO_DETAIL = "no further detail was given"

_FETCH_TIMEOUT_S = 60.0
_MIN_SCALE = 0.05  # a reduction may shrink the budget, never erase it
_DETAIL_MAX = 200
#: One string per expected text, capped: a source panel is sanity-limited to 1500 characters
#: upstream (FR-304) and this is the check's own belt on top of it, so a malformed caller cannot
#: turn one verdict call into a megabyte of prompt.
_EXPECTED_MAX = 2000
#: The carrier turn — the images attach to the LAST user turn (FR-40), and all question WORDING
#: lives in the template (FR-180). What rides here is DATA: how many images, and (v2.1.1) the
#: locked text each one was ordered to carry, which is the referent the mismatch question needs.
_CARRIER = "Return the verdict JSON for the {count} attached image(s), in the order attached."
_EXPECTED_HEADER = ("EXPECTED TEXT — the exact words each attached image was ordered to carry, "
                    "in the order attached:")
#: What a wordless-by-design asset's expected text looks like on the wire. The template names this
#: literal token, so the two must be read together.
_EXPECTED_NONE = "(none)"
#: D-A (v2.1.2): the marks an image was SANCTIONED to draw for real — the second referent the
#: question needs, and pure data like the expected text. A Notion logo on a slide is intended
#: content, not fake UI, and the lettering inside it is not invented copy; without this line the
#: check flags exactly the fidelity D-A exists to buy. An image with no marks gets no row, which
#: is the default reading the template already states (every logo is then unsanctioned).
_MARKS_HEADER = ("SANCTIONED MARKS — real product or company logos each attached image was "
                 "allowed to draw, in the order attached:")
_MARK_MAX = 60  # one mark is a NAME ("Notion"), never a sentence
_MARKS_PER_IMAGE = 8

#: Strict-mode schema (RESULTS.md §E: every property required, `additionalProperties: false`).
#: The CALLER owns the schema — `llm.py` stays schema-agnostic by contract, and booleans are why
#: this is written out rather than generated from a dataclass (that generator emits strings).
_VERDICT: dict[str, Any] = {
    "type": "object",
    "properties": {"image": {"type": "integer"}, "text_broken": {"type": "boolean"},
                   "fake_ui": {"type": "boolean"}, "text_mismatch": {"type": "boolean"},
                   "detail": {"type": "string"}},
    "required": ["image", "text_broken", "fake_ui", "text_mismatch", "detail"],
    "additionalProperties": False,
}
_SCHEMA: dict[str, Any] = {
    "name": "vision_check",
    "schema": {"type": "object", "properties": {"verdicts": {"type": "array", "items": _VERDICT}},
               "required": ["verdicts"], "additionalProperties": False},
}


@dataclass(slots=True)
class ImageVerdict:
    """One image's answer to FR-105's three questions. `index` is 1-based in the caller's list."""

    index: int
    text_broken: bool = False
    fake_ui: bool = False
    #: v2.1.1's third defect: the words are legible and there is no fake UI, but they are not the
    #: words this asset was ordered to carry (or there are words at all on a wordless slide).
    text_mismatch: bool = False
    detail: str = ""

    @property
    def flagged(self) -> bool:
        """True when ANY of the three defects is present — what earns the one retry."""
        return self.text_broken or self.fake_ui or self.text_mismatch


@dataclass(slots=True)
class CheckReport:
    """The result of one check call: verdicts, whether it happened at all, and what it cost."""

    verdicts: list[ImageVerdict] = field(default_factory=list)
    checked: bool = True  # False ⇒ every image is NOT_CHECKED and ships unchanged (10 §10)
    reason: str = ""  # why it did not happen; safe to log, never a secret (D30)
    cost_usd: float = 0.0  # feeds FR-106c's reserve/reconcile
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def flagged(self) -> list[ImageVerdict]:
        """The images that need FR-105's single re-render, in caller order."""
        return [verdict for verdict in self.verdicts if verdict.flagged]

    def verdict_for(self, index: int) -> ImageVerdict | None:
        """This image's verdict, or None when it was not checked (unreadable, or no answer)."""
        return next((v for v in self.verdicts if v.index == index), None)

    @classmethod
    def not_checked(cls, reason: str) -> CheckReport:
        """The ship-anyway report — also what callers return when `run.vision_check` is off."""
        return cls(checked=False, reason=reason)


@dataclass(slots=True)
class RetryPlan:
    """Everything a caller needs to re-render one flagged asset ONCE (FR-105, FR-193)."""

    copy: CopySet  # a clone: shortened on-image text, optional block dropped — or `copy` itself
    #: The flagged carousel slide's own line: shortened against the `slide` budget when it is text
    #: we composed, and BYTE-IDENTICAL to the original when it is a mapped panel (FR-304 carve-out).
    slide_text: str = ""
    budget_scale: float = 1.0  # pass to `prompts_engine.build_context(budget_scale=...)`; 1.0 when
    #: nothing was cut, so the prompt never restates a budget the text did not move under.
    instruction: str = RETRY_INSTRUCTION  # append to the assembled prompt (FR-105/180)


async def check(
    images: Sequence[bytes | Path | str],
    *,
    expected: Sequence[str] | None = None,
    sanctioned_marks: Sequence[Sequence[str]] | None = None,
    call: StructuredCall,
    engine: PromptEngine,
    log: Any = None,
) -> CheckReport:
    """Check one image, or a whole deck, in a single vision call (FR-27/105).

    Args:
        images: the finished renders at NATIVE resolution — already-held bytes, local paths, or
            result URLs (fetched here, concurrently). Never downscaled. One carousel's slides go
            in ONE list, so the deck costs one call.
        expected: the LOCKED text each image was ordered to carry, positionally aligned with
            `images` (v2.1.1, FR-105). An empty string is a statement — "this one is wordless by
            design, invented words are a defect" — so it is sent as such, not omitted. `None`
            means the caller offered no referent at all and the mismatch question is answered
            `false` by the template; a SHORT list leaves its tail with no row at all, which is
            that same "nothing to compare against" and NOT an empty expectation.
        sanctioned_marks: D-A (v2.1.2) — per image, in caller order, the real product/company
            marks that image was ALLOWED to draw (`["Notion", "Obsidian"]`). They ride as data
            beside the expected text and travel through the same drop table, and the question
            template owns every word about what they mean: a sanctioned logo is not fake UI, and
            its own lettering is not a text mismatch. An empty list (or no list at all) is the
            default and the strict reading — every logo on that image is unsanctioned chrome.
        call: `llm.structured_call` (`models.StructuredCall`); the role is `analysis` (Sonnet 5).
        engine: the run's `PromptEngine`; supplies `vision_check_question.md`.
        log: anything with `.warn(event_type, message, **data)`.

    Returns:
        A `CheckReport`; `checked=False` means the check did not happen and the assets ship as
        `VisionCheckResult.NOT_CHECKED`. Never raises.
    """
    sources = list(images)
    if not sources:
        return CheckReport.not_checked("no images to check")
    blobs, positions = await _load(sources, log)
    if not blobs:
        return CheckReport.not_checked("no check input could be read")
    try:
        question = engine.render(QUESTION_TEMPLATE, {})
    except (ValueError, LookupError) as exc:  # unresolved placeholder / no template at all
        return CheckReport.not_checked(f"vision-check template unusable: {exc}")
    result = await call(
        VISION_CHECK_ROLE,
        [{"role": "system", "content": question},
         # The expected text follows the SAME drop rule as the images: an unreadable input is not
         # attached, so its locked string is not listed either. `positions` is the one place that
         # renumbering is known, so the carrier is built from it and the two lists cannot shift
         # apart — a mismatch verdict against the wrong slide's text is worse than no verdict.
         {"role": "user", "content": _carrier(len(blobs), expected, positions, sanctioned_marks)}],
        _SCHEMA,
        blobs,
    )
    report = CheckReport(cost_usd=result.cost_usd, prompt_tokens=result.prompt_tokens,
                         completion_tokens=result.completion_tokens)
    if result.degraded or not isinstance(result.parsed, Mapping):
        report.checked = False
        # `reason` first — a truncated call's `raw_text` is unfinished JSON, which tells the
        # operator nothing about WHY the check did not run. The body is the fallback.
        report.reason = (
            result.reason or result.raw_text or "vision check returned nothing usable")[:_DETAIL_MAX]
        _warn(log, "vision_check_unavailable",
              f"vision check did not run for {len(blobs)} image(s): {report.reason}",
              images=len(blobs))
        return report
    report.verdicts = _verdicts(result.parsed, positions)
    return report


def expected_text(
    copy: CopySet | None,
    creative_format: str,
    *,
    slide_text: str = "",
    wordmark: str = "",
    slide_counter: str = "",
) -> str:
    """The words this asset was ORDERED to carry — the check's referent (FR-105, v2.1.1).

    This mirrors `prompts_engine._onimage_text`, which builds the render prompt's TEXT block: the
    check must ask about the same strings the render was told to draw, or a mismatch verdict is
    an opinion about a prompt nobody sent. Kept as one function here, called by all three check
    sites, so "what did we order" has a single implementation on the verdict side.

    One deliberate divergence, and it is not drift: a carousel's expected text is the SLIDE text
    alone, with no `headline` fallback. `generate/carousel.py` blanks `copy.headline` for a slide
    whose source panel carried no words (FR-304 — a wordless panel renders wordless), so a deck's
    rendered words are its own slide texts and nothing else.

    The slide COUNTER is part of the referent for the same reason the wordmark is (D-D, v2.1.2):
    a counted deck orders its badge as a locked TEXT-block string, so "3/7" is a string the render
    was told to draw. Unlisted, it reads to the checker as three invented characters on every
    slide of the deck — and the deck that carries no counter lists none, which keeps the opposite
    case just as sharp.

    Returns one string per rendered text block, newline-joined; `""` means "this asset is wordless
    by design", which `check()` sends as a real statement rather than as an absence.
    """
    blocks: list[str] = []
    if creative_format == "carousel":
        blocks = [slide_text]
    elif creative_format == "reel":
        blocks = [(copy.overlay_text if copy else "") or (copy.headline if copy else "")]
    elif copy is not None:
        blocks = [copy.headline, copy.subline]
    # The order mirrors `prompts_engine._onimage_text` exactly — the creative's own words, then
    # the counter, then the signature — because that is the order the render was told to draw in.
    blocks.append(slide_counter)  # D-D: a counted deck's badge is ordered text, not an invention
    blocks.append(wordmark)  # FR-292 channel 1: the wordmark renders THROUGH the text block (B1)
    return "\n".join(block.strip() for block in blocks if block and block.strip())


def retry_plan(
    copy: CopySet,
    creative_format: str,
    budgets: TextBudgets | None = None,
    *,
    slide_text: str = "",
    verbatim: bool = False,
    verdict: ImageVerdict | None = None,
) -> RetryPlan:
    """FR-105's retry, computed once: −`retry_reduction_pct`% text, one block, larger type.

    The reduction is a fixed percentage of the budget **in force for that asset** (FR-101), cut at
    a word boundary — never mid-word, which is the very defect the check exists to catch. The
    optional block (an image's subline) is dropped outright, because fewer blocks render more
    reliably than shorter ones. Callers pass `budget_scale` into `build_context()` so the prompt's
    stated budget matches the text it carries, and append `instruction` to the assembled prompt.

    Each format is cut against the slot that GOVERNS it (v2.1.1): a reel's hook against
    `reel_seed_headline`, an image's headline against `image_headline`, and a deck's per-slide
    text against `slide` — never against `image_headline`, which is four times smaller and turned
    a 131-character panel into a 53-character mid-sentence stub in the 2026-08-13 audit.

    `verbatim=True` is the FR-304 carve-out: this slide's text IS source panel *i*, quoted, and it
    passes through byte for byte. Nothing is trimmed, no budget is restated (`budget_scale` stays
    1.0, because nothing was reduced), and the difference the re-render makes is layout-side —
    `VERBATIM_RETRY_INSTRUCTION`. A verbatim retry that changed the text would be this module
    committing the exact defect it exists to detect.

    `verdict` is D-F (v2.1.2): the FIRST verdict, so the instruction can name the defect that was
    actually seen. `text_broken` keeps the base wording it always had — shorter text, larger type
    — while `text_mismatch` and `fake_ui` append a clause quoting the model's own `detail` and
    forbidding the thing by name. Omitting it (the default) reproduces the pre-D-F instruction
    byte for byte, which is what every caller with no verdict in scope gets.
    """
    limits = budgets or TextBudgets()
    instruction = _instruction(VERBATIM_RETRY_INSTRUCTION if verbatim else RETRY_INSTRUCTION,
                               verdict)
    scale = max(_MIN_SCALE, 1.0 - limits.retry_reduction_pct / 100.0)
    headline_limit = max(1, int(limits.image_headline * scale))
    hook_limit = max(1, int(limits.reel_seed_headline * scale))
    slide_limit = max(1, int(limits.slide * scale))
    if creative_format == "reel":
        shortened = replace(
            copy,
            overlay_text=trim_words(copy.overlay_text, hook_limit)[0],
            headline=trim_words(copy.headline, hook_limit)[0],
            subline="",
        )
        return RetryPlan(copy=shortened, budget_scale=scale, instruction=instruction)
    if verbatim:
        # The copy is handed back untouched: a mapped deck's slide never renders `headline` or
        # `subline` (the panel text is the whole TEXT block), so there is nothing here to drop
        # that would change the picture — and cutting the headline anyway would only make the
        # caption-side copy and the retry plan disagree about what this creative says.
        return RetryPlan(copy=copy, slide_text=slide_text, budget_scale=1.0,
                         instruction=instruction)
    shortened = replace(
        copy,
        headline=trim_words(copy.headline, headline_limit)[0],
        subline="",  # "fewer text blocks" — the subline is the optional one
    )
    limit = slide_limit if creative_format == "carousel" else headline_limit
    return RetryPlan(copy=shortened, slide_text=trim_words(slide_text, limit)[0],
                     budget_scale=scale, instruction=instruction)


def verdict_result(
    first: ImageVerdict | None,
    after_retry: ImageVerdict | None = None,
    *,
    retried: bool = False,
) -> VisionCheckResult:
    """FR-27's four states for one asset, from the at-most-two passes over it.

    A flagged image that was never re-rendered — the budget declined the discretionary retry
    (FR-106c), or the re-render itself failed — is `retried_failed`, not `passed`: a defect the
    operator can see must never be laundered into a clean verdict.
    """
    if first is None:
        return VisionCheckResult.NOT_CHECKED
    if not first.flagged:
        return VisionCheckResult.PASSED
    if not retried or after_retry is None or after_retry.flagged:
        return VisionCheckResult.RETRIED_FAILED
    return VisionCheckResult.RETRIED_PASSED


# --------------------------------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------------------------------


def _instruction(base: str, verdict: ImageVerdict | None) -> str:
    """The retry's plea, composed from the base lever plus the defects actually seen (D-F).

    The base is the text/layout lever the caller already chose (free-composed or verbatim); what
    is appended is the diagnosis. `text_broken` adds nothing, because the base IS its remedy —
    duplicating it would only dilute the two clauses that carry new information. A verdict with no
    flags, or none at all, returns the base unchanged, so a caller that has no verdict in scope
    sends exactly the string it sent before this parameter existed.
    """
    if verdict is None:
        return base
    detail = " ".join(str(verdict.detail or "").split())[:_DETAIL_MAX] or _NO_DETAIL
    clauses = [clause.format(detail=detail) for flag, clause in
               ((verdict.text_mismatch, _MISMATCH_CLAUSE), (verdict.fake_ui, _FAKE_UI_CLAUSE))
               if flag]
    return " ".join([base, *clauses]) if clauses else base


def _carrier(count: int, expected: Sequence[str] | None, positions: Sequence[int],
             marks: Sequence[Sequence[str]] | None = None) -> str:
    """The user turn: how many images, what each was ordered to say, what each may draw for real.

    `positions` maps attachment slot -> the caller's own index, so an image dropped as unreadable
    takes its expected string AND its sanctioned marks with it. A caller that offered no
    `expected` at all gets the bare count line and the template's "nothing to compare against"
    branch.

    An image past the end of a SHORT `expected` list gets no row rather than an empty one: an
    empty expectation is the strong claim "this image must carry no words", and inferring it from
    a caller's omission would flag every legitimate line on it. The marks block follows the
    opposite rule and it is not an inconsistency: a missing marks row is the STRICT reading (every
    logo unsanctioned), so an image with nothing to sanction is simply left out.
    """
    line = _CARRIER.format(count=count)
    blocks = [line]
    if expected is not None:
        rows = [f"image {slot}: "
                + (f'"{text[:_EXPECTED_MAX]}"' if (text := expected[position - 1].strip())
                   else _EXPECTED_NONE)
                for slot, position in enumerate(positions, start=1) if position <= len(expected)]
        if rows:
            blocks.append(f"{_EXPECTED_HEADER}\n" + "\n".join(rows))
    if marks is not None:
        rows = [f"image {slot}: " + names
                for slot, position in enumerate(positions, start=1) if position <= len(marks)
                and (names := _mark_line(marks[position - 1]))]
        if rows:
            blocks.append(f"{_MARKS_HEADER}\n" + "\n".join(rows))
    return "\n\n".join(blocks)


def _mark_line(names: Sequence[str]) -> str:
    """One image's sanctioned marks as the model reads them: `Notion, Obsidian`, bounded.

    Names only, comma-joined — the caller has already stripped the "logo"/"icon" descriptors and
    filtered competitors, handles and platform chrome out. The caps are this module's own belt: a
    mark is a NAME, and a malformed caller may not turn one verdict call into a prompt of prose.
    """
    return ", ".join(str(name).strip()[:_MARK_MAX]
                     for name in list(names)[:_MARKS_PER_IMAGE] if str(name or "").strip())


async def _load(
    sources: Sequence[bytes | Path | str], log: Any
) -> tuple[list[bytes], list[int]]:
    """Native-resolution bytes plus the caller-side 1-based position each one came from."""
    client = (httpx.AsyncClient(timeout=_FETCH_TIMEOUT_S, follow_redirects=True)
              if any(_is_url(source) for source in sources) else None)
    try:
        blobs = await asyncio.gather(*(_load_one(source, client, log) for source in sources))
    finally:
        if client is not None:
            await client.aclose()
    return ([blob for blob in blobs if blob],
            [position for position, blob in enumerate(blobs, start=1) if blob])


async def _load_one(source: bytes | Path | str, client: httpx.AsyncClient | None, log: Any) -> bytes:
    """One input. An unreadable one is dropped, never raised — a thin check beats a dead one."""
    try:
        if isinstance(source, bytes):
            return source
        if _is_url(source) and client is not None:
            response = await client.get(str(source))
            response.raise_for_status()
            return response.content
        return await asyncio.to_thread(Path(source).read_bytes)
    except (OSError, httpx.HTTPError, ValueError) as exc:
        _warn(log, "vision_check_input_unreadable",
              f"vision-check input skipped: {type(exc).__name__}", source=str(source)[:_DETAIL_MAX])
        return b""


def _is_url(source: bytes | Path | str) -> bool:
    return isinstance(source, str) and source.startswith(("http://", "https://"))


def _verdicts(parsed: Mapping[str, Any], positions: Sequence[int]) -> list[ImageVerdict]:
    """Map the model's 1-based attachment slots back onto the caller's own positions."""
    out: list[ImageVerdict] = []
    for order, row in enumerate(parsed.get("verdicts") or [], start=1):
        if not isinstance(row, Mapping):
            continue
        try:
            slot = int(row.get("image") or order)
        except (TypeError, ValueError):
            slot = order
        if not 1 <= slot <= len(positions):
            continue
        out.append(ImageVerdict(
            index=positions[slot - 1],
            text_broken=bool(row.get("text_broken")),
            fake_ui=bool(row.get("fake_ui")),
            text_mismatch=bool(row.get("text_mismatch")),
            detail=str(row.get("detail") or "")[:_DETAIL_MAX],
        ))
    return out


def _warn(log: Any, event_type: str, message: str, **data: Any) -> None:
    logger.warning("%s: %s", event_type, message)
    if log is not None:
        log.warn(event_type, message, **data)


__all__ = [
    "CheckReport", "ImageVerdict", "QUESTION_TEMPLATE", "RETRY_INSTRUCTION", "RetryPlan",
    "VERBATIM_RETRY_INSTRUCTION", "VISION_CHECK_ROLE", "check", "expected_text", "retry_plan",
    "verdict_result",
]
