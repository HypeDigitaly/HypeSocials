"""Visual analysis — one style brief per (trend, reference group) pair (FR-9–12, 92, 93, 147).

Module contract
---------------
Purpose: turn the selected (trend, reference group) pairs plus that group's downloaded reference
images into structured `StyleBrief` objects, all calls concurrent, degrading a failed pair to *no
brief* rather than failing the run.

Public API:
    await style_briefs(subjects, images, call=..., engine=...) -> dict[brief_key, StyleBrief]
    downscale_for_analysis(images, max_images=6)               -> list[bytes]   (FR-93, NFR-25)
    ANALYSIS_ROLE

Invariants:
- **One call per DISTINCT (trend, reference group) PAIR, never per creative (FR-9/12, amended
  2026-08-11).** Duplicates collapse on `sources.brief_key()` exactly as they used to collapse on
  `history_key`: two creatives that share a trend AND the group it rotated to share one brief and
  one call, while a sibling that attached a different group gets its own. The bound is
  `max_trend_reuses_per_run` calls per trend, and no call is ever made for a group no creative
  will attach.
- **A brief sees only the pictures its own creatives attach.** Pooling every group into one call
  — which is what one-brief-per-trend had to do — reintroduces exactly the blur the pair key
  exists to remove: a brief that describes six posts steers a render conditioned on three of
  them. FR-93's "about six images maximum per call" is a ceiling, not a floor.
- **Absence is the degrade signal (FR-12).** A pair missing from the returned mapping failed its
  call after `llm.py`'s internal retry; its creatives fall back to direct-mode behaviour and the
  caller attaches `DegradationTag.ANALYSIS_MISSING`. Nothing raises, nothing is skipped.
- **FR-93 downscale lives HERE and nowhere else (NFR-25).** ~1024 px long edge, JPEG, ≤ 6 images
  per call, done in a worker thread so Pillow never blocks the event loop. Vision-check inputs
  are explicitly NOT downscaled (FR-105) and are not this module's business.
- **FR-92's schema and the `{{output_format}}` field list come from ONE generator** in
  `prompts_engine`, both derived from `StyleBrief`'s own fields — they cannot drift apart.
- The prompt is the `style_brief_system.md` template in full; this module adds one fixed,
  data-free carrier turn so the images have a user message to attach to (FR-180: all trend text
  travels inside the template's fenced blocks, never in engine-authored prose).

Do not: call the LLM directly (go through the `StructuredCall` seam), downscale anything for a
vision check, or import config.
"""

from __future__ import annotations

import asyncio
import io
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hypesocials.models import LayoutZone, StructuredCall, StyleBrief, TrendItem
from hypesocials.prompts_engine import PromptEngine, build_context, style_brief_schema
from hypesocials.sources import brief_key, reference_group_index

logger = logging.getLogger(__name__)

#: `models.analysis` / `max_tokens.analysis` — the role name every config key already uses.
ANALYSIS_ROLE = "analysis"
ANALYSIS_LONG_EDGE = 1024  # FR-93
ANALYSIS_MAX_IMAGES = 6  # FR-93 / `media_download_cap` default
_JPEG_QUALITY = 85
#: Fixed, data-free carrier for the image parts (FR-40 attaches them to the last user turn).
_CARRIER_TURN = "Return the style brief JSON for the delimited material now."


async def style_briefs(
    subjects: Sequence[tuple[TrendItem, int]],
    images: Mapping[str, Sequence[bytes | Path | str]] | None = None,
    *,
    call: StructuredCall,
    engine: PromptEngine,
    niche_descriptor: str = "",
    max_images: int = ANALYSIS_MAX_IMAGES,
    log: Any = None,
) -> dict[str, StyleBrief]:
    """One style brief per distinct (trend, reference group) pair, all calls issued at once (FR-9).

    Args:
        subjects: `(trend, reuse_index)` pairs — one per creative is fine and expected, because
            duplicates collapse HERE on `sources.brief_key()`. `reuse_index` is the creative's
            `PlanEntry.trend_reuse_index`, and `sources` resolves it to the group the creative
            actually attaches, wrap-around included.
        images: `brief_key -> that group's downloaded reference images`, either raw bytes or the
            local paths `sources.reference_paths()` returns (the adapter owns the download,
            FR-32/33). Files are read inside the downscale worker thread, so nothing blocks the
            loop. Missing or empty means a text-only trend: the call runs on its text alone.
        call: `llm.structured_call` (`models.StructuredCall`).
        engine: the run's `PromptEngine`; supplies `style_brief_system.md`.
        niche_descriptor: FR-147's standing context, injected verbatim.
        max_images: FR-93's per-call ceiling.
        log: anything with `.warn(event_type, message, **data)`.

    Returns:
        `{brief_key: StyleBrief}` for the pairs that answered, each carrying its own
        `reference_group_index`. A missing key is FR-12's degrade — the creatives on that pair
        run direct-mode and are marked `analysis_missing`. The mapping is a `BriefBook`, so a
        caller that only knows a trend key still resolves to that trend's brief.
    """
    distinct: dict[str, tuple[TrendItem, int]] = {}
    for trend, reuse_index in subjects:
        key = brief_key(trend.history_key, trend, reuse_index)
        distinct.setdefault(key, (trend, reference_group_index(trend, reuse_index)))
    if not distinct:
        return BriefBook()
    pool = images or {}
    results = await asyncio.gather(*(
        _one_brief(trend, pool.get(key, ()), key=key, group_index=group_index, call=call,
                   engine=engine, niche_descriptor=niche_descriptor, max_images=max_images, log=log)
        for key, (trend, group_index) in distinct.items()))
    return BriefBook((key, brief) for key, brief in zip(distinct, results) if brief is not None)


class BriefBook(dict[str, StyleBrief]):
    """`{brief_key: StyleBrief}` — and, for a caller holding only a trend key, that trend's brief.

    WHY the second door exists: FR-9's unit is the (trend, reference group) pair, but FR-99's copy
    call is grouped per trend, and a caller that legitimately has no rotation index in hand — the
    copywriter, a console block naming a trend — would otherwise get `None` where it used to get a
    brief, silently losing style context that is not actually pair-specific to it.

    Containment stays EXACT (`"t1#3" in book` is a real dictionary lookup) because that is what
    FR-12's `analysis_missing` verdict is decided on: a creative whose own pair's call failed must
    be marked degraded even when a sibling group's brief exists. The lenient path is `get()` with
    a bare trend key, which resolves to that trend's lowest-numbered brief — deterministic
    regardless of the order the concurrent calls answered in.
    """

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        brief = super().get(key)
        if brief is not None:
            return brief
        for_trend = [item for item in self.values() if item.trend_key == key]
        return min(for_trend, key=lambda b: b.reference_group_index) if for_trend else default


async def _one_brief(
    trend: TrendItem,
    references: Sequence[bytes | Path | str],
    *,
    key: str,
    group_index: int,
    call: StructuredCall,
    engine: PromptEngine,
    niche_descriptor: str,
    max_images: int,
    log: Any,
) -> StyleBrief | None:
    """One pair's vision call. Returns None on any failure — never raises (FR-12)."""
    payload = (await asyncio.to_thread(downscale_for_analysis, references, max_images)
               if references else [])
    context = build_context(
        trend=trend, niche_descriptor=niche_descriptor, reference_image_count=len(payload))
    try:
        system = engine.render("style_brief_system.md", context)
    except (ValueError, LookupError) as exc:  # unresolved placeholder / missing template
        _warn(log, "analysis_prompt_failed", f"{key}: {exc}",
              trend=trend.name, reference_group=group_index)
        return None
    result = await call(
        ANALYSIS_ROLE,
        [{"role": "system", "content": system}, {"role": "user", "content": _CARRIER_TURN}],
        style_brief_schema(),
        payload or None,
    )
    if result.degraded or not isinstance(result.parsed, Mapping):
        # `reason` first: on a truncated call `raw_text` is a slab of half-finished JSON, and an
        # operator reading it cannot tell "the model was cut off" from "the model returned
        # garbage". The body stays as the fallback for a degrade that arrived without a reason.
        _warn(log, "analysis_missing",
              f"style brief unavailable for {trend.name} (reference group {group_index}): "
              f"{(result.reason or result.raw_text)[:200]}",
              trend=trend.name, trend_key=trend.history_key, reference_group=group_index)
        return None
    return _to_brief(trend.history_key, group_index, result.parsed)


def _to_brief(trend_key: str, group_index: int, parsed: Mapping[str, Any]) -> StyleBrief:
    """Map the validated JSON onto `StyleBrief`; the whole payload is kept in `raw` (FR-92).

    `reference_group_index` is stamped by the engine, never asked of the model — it is not in
    `style_brief_schema()`'s generated field list — so a logged brief can be matched to the
    pictures it describes without reconstructing the dictionary key.
    """
    zones = [
        LayoutZone(position=str(zone.get("position", "")), content=str(zone.get("content", "")),
                   text_treatment=str(zone.get("text_treatment", "")))
        for zone in parsed.get("layout_zones") or [] if isinstance(zone, Mapping)
    ]
    guidance = parsed.get("per_format_guidance")
    return StyleBrief(
        trend_key=trend_key,
        reference_group_index=group_index,
        layout_zones=zones,
        exclusions=_strings(parsed.get("exclusions")),
        render_prompt=str(parsed.get("render_prompt") or ""),
        palette=_strings(parsed.get("palette")),
        typography=str(parsed.get("typography") or ""),
        text_placement=str(parsed.get("text_placement") or ""),
        image_treatment=str(parsed.get("image_treatment") or ""),
        visual_pacing=str(parsed.get("visual_pacing") or ""),
        hook_pattern=str(parsed.get("hook_pattern") or ""),
        content_angle=str(parsed.get("content_angle") or ""),
        per_format_guidance={str(k): str(v) for k, v in guidance.items()}
        if isinstance(guidance, Mapping) else {},
        raw=dict(parsed),
    )


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Sequence):
        return [str(item) for item in value if str(item).strip()]
    return []


def downscale_for_analysis(
    images: Sequence[bytes | Path | str], max_images: int = ANALYSIS_MAX_IMAGES
) -> list[bytes]:
    """FR-93 — the project's ONE permitted imaging operation (NFR-25).

    Caps the set at `max_images`, scales each image to ~1024 px on the long edge and re-encodes
    it as JPEG. The analyst needs layout and palette, not pixels, and image tokens are a real
    cost line. Full-resolution originals stay on disk and are what render jobs reference.
    Blocking work — file reads included: call it from a worker thread. An unreadable or
    undecodable image is passed through or dropped rather than raising; a thinner reference set
    beats a dead analysis call.
    """
    return [blob for blob in (_downscale(image) for image in images[:max_images]) if blob]


def _downscale(image: bytes | Path | str) -> bytes:
    if not isinstance(image, bytes):
        try:
            blob = Path(image).read_bytes()
        except OSError as exc:
            logger.warning("analysis reference unreadable (%s): %s", image, exc)
            return b""
    else:
        blob = image
    if not blob:
        return b""
    try:
        from PIL import Image  # local import: the one imaging use, kept visible (NFR-25)

        with Image.open(io.BytesIO(blob)) as image:
            image = image.convert("RGB")
            image.thumbnail((ANALYSIS_LONG_EDGE, ANALYSIS_LONG_EDGE), Image.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
            return buffer.getvalue()
    except Exception as exc:  # decode failure, truncated download, exotic format
        logger.warning("analysis downscale skipped (%s): %s", type(exc).__name__, exc)
        return blob


def _warn(log: Any, event_type: str, message: str, **data: Any) -> None:
    logger.warning("%s: %s", event_type, message)
    if log is not None:
        log.warn(event_type, message, **data)


__all__ = ["ANALYSIS_ROLE", "BriefBook", "downscale_for_analysis", "style_briefs"]
