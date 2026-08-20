"""What a finished frame was ORDERED to carry, and how to load it — the gauntlet's two inputs.

Module contract
---------------
Purpose: three pure helpers that describe a rendered asset's *referent* and fetch its *bytes*.
Everything that used to ASK a model about those bytes is gone (v2.2.0, D49): `check()`, its strict
schema, its carrier turn, its verdict parser and `prompts/vision_check_question.md` were the FR-105
single-shot gate, and the three-critic gauntlet (`hypesocials/gauntlet.py`) replaces that gate
outright. What survives is what the gauntlet — and nothing else — still needs from here.

Public API:
    await load_images(sources, log=None) -> (blobs, positions)   (the gauntlet's frame loader)
    expected_text(copy, creative_format, slide_text=..., wordmark=..., slide_counter=...) -> str
    retry_plan(copy, creative_format, budgets, slide_text=..., verbatim=..., verdict=...)
        -> RetryPlan
    verdict_result(first, after_retry=None, retried=...) -> VisionCheckResult   (FR-27's 4 states)
    ImageVerdict · RetryPlan · RETRY_INSTRUCTION · VERBATIM_RETRY_INSTRUCTION

Invariants enforced here, once, for every caller:
- **Frame inputs are NEVER downscaled (FR-105/FR-322).** FR-93's ~1024 px re-encode is
  analysis-only: a 42-character headline on a 1024 px JPEG is where a model stops telling a
  malformed glyph from compression, and Czech diacritics are the first casualty. Bytes go out
  exactly as rendered — `load_images` is the one door, so both readers inherit the rule.
- **An unreadable input is DROPPED, never SHIFTED.** `load_images` returns `positions` beside the
  blobs — the 1-based caller index each attachment came from — so a critic's answer about
  attachment 3 can never be re-mapped onto the wrong slide. `gauntlet._parse` reuses that contract
  rather than re-implementing it.
- **`expected_text` mirrors `prompts_engine._onimage_text`.** The words a frame is judged against
  must be the words the render was told to draw, or a verdict is an opinion about a prompt nobody
  sent. One function, so "what did we order" has a single implementation on the verdict side.
- **A mapped panel's text is never trimmed (FR-304 > FR-105).** Under a panel map our slide *i* IS
  source panel *i*, and its text is a LOCKED CONTRACT STRING — a verbatim quote of that panel, or
  its D54-compressed text (FR-331). Either way cutting it to 60% of a budget produces a
  mid-sentence stub, the very defect the gate exists to catch, applied by us on purpose. Compress
  mode does not soften this: a compressed line was already cut to the style's budget by the copy
  model, before any render, so a second cut here is pure loss. `retry_plan(verbatim=True)` changes
  the LAYOUT only and hands the text back byte for byte, in both modes.

Do not: downscale a frame; add a second image loader; trim a locked contract string (a verbatim
quote or a compressed line); re-introduce a model call here — judging a rendered frame is
`gauntlet.py`'s single responsibility now.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import httpx

from hypesocials.config import TextBudgets
from hypesocials.models import CopySet, VisionCheckResult
from hypesocials.prompts_engine import trim_words

logger = logging.getLogger(__name__)

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
#:
#: **Its bytes are deliberately UNCHANGED by D54 (v2.3.0), unlike the doctrinal comments around
#: it.** This constant is a PROMPT, not documentation: it is sent to the render model on every
#: verbatim-mode re-render, and editing "a verbatim quote" into "a locked contract string" would
#: change what every existing run says to the provider in order to make a comment read better.
#: The operative half — "are LOCKED: reproduce every character of them, shortening nothing and
#: rewording nothing" — is already exactly right for a D54-compressed line, which was cut to the
#: style's budget by the copy model before this stage ever saw it. If the wording is ever revisited
#: it is a prompt change, owned by the prompt task and re-measured, never a comment tidy-up.
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
class RetryPlan:
    """Everything a caller needs to re-render one flagged asset ONCE (FR-105, FR-193)."""

    copy: CopySet  # a clone: shortened on-image text, optional block dropped — or `copy` itself
    #: The flagged carousel slide's own line: shortened against the `slide` budget when it is text
    #: we composed, and BYTE-IDENTICAL to the original when it is a mapped panel (FR-304 carve-out).
    slide_text: str = ""
    budget_scale: float = 1.0  # pass to `prompts_engine.build_context(budget_scale=...)`; 1.0 when
    #: nothing was cut, so the prompt never restates a budget the text did not move under.
    instruction: str = RETRY_INSTRUCTION  # append to the assembled prompt (FR-105/180)


def expected_text(
    copy: CopySet | None,
    creative_format: str,
    *,
    slide_text: str = "",
    wordmark: str = "",
    slide_counter: str = "",
) -> str:
    """The words this asset was ORDERED to carry — the gate's referent (FR-105/FR-322, v2.1.1).

    This mirrors `prompts_engine._onimage_text`, which builds the render prompt's TEXT block: the
    gate must judge the same strings the render was told to draw, or a mismatch verdict is
    an opinion about a prompt nobody sent. Kept as one function here, called by every contract
    builder, so "what did we order" has a single implementation on the verdict side.

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
    by design", which the gauntlet's expected block states as `(none)` — a real claim ("nothing may
    be readable here"), never an absence of one.
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


async def load_images(
    sources: Sequence[bytes | Path | str], log: Any = None
) -> tuple[list[bytes], list[int]]:
    """Native-resolution bytes plus the caller-side 1-based position each one came from.

    Public since v2.2.0 (D49) and, since the FR-105 check was deleted, the ONLY frame loader in
    the product: every gauntlet critic call loads its frames through this exact function, so "a
    frame is never downscaled" and "an unreadable input is DROPPED, never shifted" have one
    implementation. `sources` may mix already-held bytes, local paths and result URLs (a reel's
    seed frame is a Kie URL) — fetched here, concurrently, and the client is closed either way.

    Returns `(blobs, positions)` where `positions[i]` is the 1-based index in `sources` that
    `blobs[i]` came from — the mapping a caller needs to turn a model's 1-based ATTACHMENT slot
    back into its own numbering. Never raises: an unreadable source is logged and left out.
    """
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
    """One input. An unreadable one is dropped, never raised — a thin gate beats a dead one."""
    try:
        if isinstance(source, bytes):
            return source
        if _is_url(source) and client is not None:
            response = await client.get(str(source))
            response.raise_for_status()
            return response.content
        return await asyncio.to_thread(Path(source).read_bytes)
    except (OSError, httpx.HTTPError, ValueError) as exc:
        _warn(log, "frame_input_unreadable",
              f"frame not loaded for the gauntlet: {type(exc).__name__}",
              source=str(source)[:_DETAIL_MAX])
        return b""


def _is_url(source: bytes | Path | str) -> bool:
    return isinstance(source, str) and source.startswith(("http://", "https://"))


def _warn(log: Any, event_type: str, message: str, **data: Any) -> None:
    logger.warning("%s: %s", event_type, message)
    if log is not None:
        log.warn(event_type, message, **data)


__all__ = [
    "ImageVerdict", "RETRY_INSTRUCTION", "RetryPlan", "VERBATIM_RETRY_INSTRUCTION",
    "expected_text", "load_images", "retry_plan", "verdict_result",
]
