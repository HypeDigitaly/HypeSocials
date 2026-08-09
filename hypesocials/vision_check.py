"""Optional vision check — one narrow question about a finished image (FR-27, FR-105).

Module contract
---------------
Purpose: ask ONE Sonnet 5 vision pass whether rendered images carry broken text or fake platform
UI, hand back per-image verdicts, and own the arithmetic of FR-105's single −40% retry. Callers
decide what to ship — a check never blocks a ship (D3, 10 §10 "a broken checker must never block
delivery").

Public API:
    await check(images, call=..., engine=...) -> CheckReport     — one call, N images, N verdicts
    retry_plan(copy, creative_format, budgets, slide_text=...) -> RetryPlan
    verdict_result(first, after_retry=None, retried=...) -> VisionCheckResult   (FR-27's 4 states)
    CheckReport · ImageVerdict · RetryPlan · VISION_CHECK_ROLE · RETRY_INSTRUCTION

Invariants enforced here, once, for every caller:
- **Check inputs are NEVER downscaled (FR-105).** FR-93's ~1024 px re-encode is analysis-only: a
  42-character headline on a 1024 px JPEG is where a model stops telling a malformed glyph from
  compression, and Czech diacritics are the first casualty. Bytes go out exactly as rendered.
- **One call per deck (FR-105/107).** A carousel's slides are checked together and come back with
  per-slide verdicts; N slides never cost N calls, and the estimator prices it the same way.
  Verdict indices are the CALLER's positions — an unreadable input is skipped, never a shift.
- **Ship either way (FR-27).** Nothing raises. Transport failure, unreadable input, bad template
  and malformed answer all come back as `checked=False`, which is `NOT_CHECKED`.
- **The retry changes the INPUT, not the plea (FR-105).** `retry_plan()` cuts the on-image text
  at a word boundary to −`retry_reduction_pct`% of the budget in force and drops the optional
  block. Re-sending the same prompt with "please fix the text" is what this avoids. One retry
  (NFR-4), then ship.

Do not: downscale a check input; call the LLM without the `StructuredCall` seam; write the
question by hand (it is `prompts/vision_check_question.md`, FR-181); retry more than once; check
a finished video clip (FR-105 excludes it — frame extraction would mean ffmpeg, D10).
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

_FETCH_TIMEOUT_S = 60.0
_MIN_SCALE = 0.05  # a reduction may shrink the budget, never erase it
_DETAIL_MAX = 200
#: Fixed, data-free carrier turn — the images attach to the LAST user turn (FR-40), and all
#: question wording lives in the template (FR-180).
_CARRIER = "Return the verdict JSON for the {count} attached image(s), in the order attached."

#: Strict-mode schema (RESULTS.md §E: every property required, `additionalProperties: false`).
#: The CALLER owns the schema — `llm.py` stays schema-agnostic by contract, and booleans are why
#: this is written out rather than generated from a dataclass (that generator emits strings).
_VERDICT: dict[str, Any] = {
    "type": "object",
    "properties": {"image": {"type": "integer"}, "text_broken": {"type": "boolean"},
                   "fake_ui": {"type": "boolean"}, "detail": {"type": "string"}},
    "required": ["image", "text_broken", "fake_ui", "detail"], "additionalProperties": False,
}
_SCHEMA: dict[str, Any] = {
    "name": "vision_check",
    "schema": {"type": "object", "properties": {"verdicts": {"type": "array", "items": _VERDICT}},
               "required": ["verdicts"], "additionalProperties": False},
}


@dataclass(slots=True)
class ImageVerdict:
    """One image's answer to FR-105's two questions. `index` is 1-based in the caller's list."""

    index: int
    text_broken: bool = False
    fake_ui: bool = False
    detail: str = ""

    @property
    def flagged(self) -> bool:
        """True when either defect is present — the only thing that earns the one retry."""
        return self.text_broken or self.fake_ui


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

    copy: CopySet  # a clone: shortened on-image text, optional block dropped
    slide_text: str = ""  # the flagged carousel slide's own line, shortened the same way
    budget_scale: float = 1.0  # pass to `prompts_engine.build_context(budget_scale=...)`
    instruction: str = RETRY_INSTRUCTION  # append to the assembled prompt (FR-105/180)


async def check(
    images: Sequence[bytes | Path | str],
    *,
    call: StructuredCall,
    engine: PromptEngine,
    log: Any = None,
) -> CheckReport:
    """Check one image, or a whole deck, in a single vision call (FR-27/105).

    Args:
        images: the finished renders at NATIVE resolution — already-held bytes, local paths, or
            result URLs (fetched here, concurrently). Never downscaled. One carousel's slides go
            in ONE list, so the deck costs one call.
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
         {"role": "user", "content": _CARRIER.format(count=len(blobs))}],
        _SCHEMA,
        blobs,
    )
    report = CheckReport(cost_usd=result.cost_usd, prompt_tokens=result.prompt_tokens,
                         completion_tokens=result.completion_tokens)
    if result.degraded or not isinstance(result.parsed, Mapping):
        report.checked = False
        report.reason = (result.raw_text or "vision check returned nothing usable")[:_DETAIL_MAX]
        _warn(log, "vision_check_unavailable",
              f"vision check did not run for {len(blobs)} image(s): {report.reason}",
              images=len(blobs))
        return report
    report.verdicts = _verdicts(result.parsed, positions)
    return report


def retry_plan(
    copy: CopySet,
    creative_format: str,
    budgets: TextBudgets | None = None,
    *,
    slide_text: str = "",
) -> RetryPlan:
    """FR-105's retry, computed once: −`retry_reduction_pct`% text, one block, larger type.

    The reduction is a fixed percentage of the budget **in force for that asset** (FR-101), cut at
    a word boundary — never mid-word, which is the very defect the check exists to catch. The
    optional block (an image's subline) is dropped outright, because fewer blocks render more
    reliably than shorter ones. Callers pass `budget_scale` into `build_context()` so the prompt's
    stated budget matches the text it carries, and append `instruction` to the assembled prompt.
    """
    limits = budgets or TextBudgets()
    scale = max(_MIN_SCALE, 1.0 - limits.retry_reduction_pct / 100.0)
    headline_limit = max(1, int(limits.image_headline * scale))
    hook_limit = max(1, int(limits.reel_seed_headline * scale))
    if creative_format == "reel":
        shortened = replace(
            copy,
            overlay_text=trim_words(copy.overlay_text, hook_limit)[0],
            headline=trim_words(copy.headline, hook_limit)[0],
            subline="",
        )
        return RetryPlan(copy=shortened, budget_scale=scale)
    shortened = replace(
        copy,
        headline=trim_words(copy.headline, headline_limit)[0],
        subline="",  # "fewer text blocks" — the subline is the optional one
    )
    return RetryPlan(copy=shortened, slide_text=trim_words(slide_text, headline_limit)[0],
                     budget_scale=scale)


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
            detail=str(row.get("detail") or "")[:_DETAIL_MAX],
        ))
    return out


def _warn(log: Any, event_type: str, message: str, **data: Any) -> None:
    logger.warning("%s: %s", event_type, message)
    if log is not None:
        log.warn(event_type, message, **data)


__all__ = [
    "CheckReport", "ImageVerdict", "QUESTION_TEMPLATE", "RETRY_INSTRUCTION", "RetryPlan",
    "VISION_CHECK_ROLE", "check", "retry_plan", "verdict_result",
]
