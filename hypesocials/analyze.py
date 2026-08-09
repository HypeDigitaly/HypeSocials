"""Visual analysis — one Sonnet 5 style brief per selected trend (FR-9–12, 92, 93, 147).

Module contract
---------------
Purpose: turn selected trends plus their downloaded reference images into structured
`StyleBrief` objects, all calls concurrent, degrading a failed trend to *no brief* rather than
failing the run.

Public API:
    await style_briefs(trends, images, call=..., engine=...) -> dict[trend_key, StyleBrief]
    downscale_for_analysis(images, max_images=6)             -> list[bytes]   (FR-93, NFR-25)
    ANALYSIS_ROLE

Invariants:
- **One call per DISTINCT trend, never per creative (FR-9/12).** Duplicates collapse on
  `history_key`; every creative on that trend shares the brief.
- **Absence is the degrade signal (FR-12).** A trend missing from the returned mapping failed
  its call after `llm.py`'s internal retry; its creatives fall back to direct-mode behaviour and
  the caller attaches `DegradationTag.ANALYSIS_MISSING`. Nothing raises, nothing is skipped.
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

logger = logging.getLogger(__name__)

#: `models.analysis` / `max_tokens.analysis` — the role name every config key already uses.
ANALYSIS_ROLE = "analysis"
ANALYSIS_LONG_EDGE = 1024  # FR-93
ANALYSIS_MAX_IMAGES = 6  # FR-93 / `media_download_cap` default
_JPEG_QUALITY = 85
#: Fixed, data-free carrier for the image parts (FR-40 attaches them to the last user turn).
_CARRIER_TURN = "Return the style brief JSON for the delimited material now."


async def style_briefs(
    trends: Sequence[TrendItem],
    images: Mapping[str, Sequence[bytes | Path | str]] | None = None,
    *,
    call: StructuredCall,
    engine: PromptEngine,
    niche_descriptor: str = "",
    max_images: int = ANALYSIS_MAX_IMAGES,
    log: Any = None,
) -> dict[str, StyleBrief]:
    """One style brief per distinct trend, all calls issued at once (FR-9).

    Args:
        trends: the selected trends; duplicates collapse on `history_key`.
        images: `history_key -> downloaded reference images`, either raw bytes or the local paths
            `sources.reference_paths()` returns (the adapter owns the download, FR-32/33). Files
            are read inside the downscale worker thread, so nothing blocks the loop. Missing or
            empty means a text-only trend: the call runs on its text material alone.
        call: `llm.structured_call` (`models.StructuredCall`).
        engine: the run's `PromptEngine`; supplies `style_brief_system.md`.
        niche_descriptor: FR-147's standing context, injected verbatim.
        max_images: FR-93's per-call ceiling.
        log: anything with `.warn(event_type, message, **data)`.

    Returns:
        `{trend_key: StyleBrief}` for the trends that answered. A missing key is FR-12's
        degrade — that trend's creatives run direct-mode and are marked `analysis_missing`.
    """
    distinct = {trend.history_key: trend for trend in trends}
    if not distinct:
        return {}
    pool = images or {}
    results = await asyncio.gather(*(
        _one_brief(trend, pool.get(key, ()), call=call, engine=engine,
                   niche_descriptor=niche_descriptor, max_images=max_images, log=log)
        for key, trend in distinct.items()))
    return {key: brief for key, brief in zip(distinct, results) if brief is not None}


async def _one_brief(
    trend: TrendItem,
    references: Sequence[bytes | Path | str],
    *,
    call: StructuredCall,
    engine: PromptEngine,
    niche_descriptor: str,
    max_images: int,
    log: Any,
) -> StyleBrief | None:
    """One trend's vision call. Returns None on any failure — never raises (FR-12)."""
    payload = (await asyncio.to_thread(downscale_for_analysis, references, max_images)
               if references else [])
    context = build_context(
        trend=trend, niche_descriptor=niche_descriptor, reference_image_count=len(payload))
    try:
        system = engine.render("style_brief_system.md", context)
    except (ValueError, LookupError) as exc:  # unresolved placeholder / missing template
        _warn(log, "analysis_prompt_failed", f"{trend.history_key}: {exc}", trend=trend.name)
        return None
    result = await call(
        ANALYSIS_ROLE,
        [{"role": "system", "content": system}, {"role": "user", "content": _CARRIER_TURN}],
        style_brief_schema(),
        payload or None,
    )
    if result.degraded or not isinstance(result.parsed, Mapping):
        _warn(log, "analysis_missing",
              f"style brief unavailable for {trend.name}: {result.raw_text[:200]}",
              trend=trend.name, trend_key=trend.history_key)
        return None
    return _to_brief(trend.history_key, result.parsed)


def _to_brief(trend_key: str, parsed: Mapping[str, Any]) -> StyleBrief:
    """Map the validated JSON onto `StyleBrief`; the whole payload is kept in `raw` (FR-92)."""
    zones = [
        LayoutZone(position=str(zone.get("position", "")), content=str(zone.get("content", "")),
                   text_treatment=str(zone.get("text_treatment", "")))
        for zone in parsed.get("layout_zones") or [] if isinstance(zone, Mapping)
    ]
    guidance = parsed.get("per_format_guidance")
    return StyleBrief(
        trend_key=trend_key,
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


__all__ = ["ANALYSIS_ROLE", "downscale_for_analysis", "style_briefs"]
