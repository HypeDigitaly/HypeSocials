"""Slide intelligence — one vision pass over the slides a carousel was sourced FROM (FR-306, F6).

Module contract
---------------
Purpose: for each carousel source post the plan actually bound, put the source deck on disk once
and read it once — so OUR slide *i* can carry the words that were on THEIR slide *i*, and our
render prompt can describe the same content (chart, grid, checklist) in our own house style.

Public API:
    await enrich(posts, run_dir=..., call=..., engine=..., cfg=..., log=...) -> {post_id: SlideIntel}
    SlideIntel · SourceSlide · SLIDE_INTEL_ROLE · QUESTION_TEMPLATE
    STATUS_OK / STATUS_UNAVAILABLE / STATUS_DISABLED
    TEXT_SOURCE_VIRLO / TEXT_SOURCE_VISION / TEXT_SOURCE_NONE

Where it sits: **after the Confirm gate, before COPY** (D46 §0.11). It is paid LLM spend, so it
may not run on a preview path or before the operator approved the estimate (rule 7); the estimator
prices it pre-Confirm from panel counts as its own `slide_intel` line. The caller passes ONLY the
assigned carousels' source posts (≤ `run.formats.carousel` per run, typically 1–2) — this module
does not re-select, re-rank or re-filter anything, and a post handed to it twice by two sibling
creatives is analysed once.

Invariants enforced here, once, for every caller:
- **HARD BOUNDARY — nothing produced or stored here may reach a render payload (D41 as amended by
  D46, FR-244/FR-306).** Virlo URLs and Virlo bytes live in exactly two places: this module, and
  `output/<run>/source/<post_id>/` for the offline gallery. They are never uploaded to Kie, never
  handed to `generate/refs.py`, never passed to the `render.upload_file` seam, and never quoted
  into a prompt as a URL. What crosses into rendering is TEXT the copy stage resolves — the merged
  on-image words — and the English `visual_brief`, which is a description of content, not a
  reference image. This module therefore imports nothing from `render` or `generate`, and a test
  pins that (`tests/test_slide_intel.py`).
- **One download per distinct slide, two readers.** `packager.store_source()` fetches each slide
  once into the run-level store; the vision call reads those local bytes, and the gallery shows
  the very same files after the CDN URL has expired (~hours). Nothing re-fetches.
- **One call per POST (FR-306).** All of a post's slides are attached to a single analysis-role
  Sonnet 5 call and come back with per-slide answers; an eight-slide deck never costs eight calls.
  Answer slots map back onto the caller's slide positions, so an unreadable slide is a gap, not a
  shift.
- **Virlo panel text wins, verbatim (D46 §0.11).** A non-empty `panel_texts[i]` IS the slide's
  text and is provenance `virlo`; vision transcription fills only the empty slots and is
  provenance `vision_transcribed`. Vision never overwrites, corrects or re-punctuates a panel
  Virlo already gave us — that string is what the verbatim contract quotes.
- **Fail-open, always (D46 §0.14c).** Nothing here raises to the caller. The call fails or times
  out → `status = vision_unavailable` and the Virlo panels stand; one slide 404s → that slide has
  `image_file = None` and no brief while its siblings proceed; fewer answers than slides → they
  align by position and the missing ones are simply absent. Every degrade writes ONE warn under a
  stable key: `slide_intel_no_slides`, `slide_intel_download_failed`,
  `slide_intel_input_unreadable`, `slide_intel_slides_capped`, `slide_intel_unavailable`,
  `slide_intel_brief_missing`, `slide_intel_store_failed`.
- **`source.yaml` is provenance, not pixels (FR-71).** It records what the source deck actually
  said — untouched by the competitor blocklist, which is applied where text becomes pixels (the
  copy stage's strip pass and its verbatim verifier, §1.5/§0.12). Sanitizing the archive would
  make the archive lie about the source it exists to document.

Do not: call this before Confirm; call it for images, reels or override-brief carousels (they bind
no source post, §0.14d); download a slide twice; let a vision transcription overwrite a Virlo
panel; raise out of here; write `run.log`/`events.jsonl` from here (that is `log.warn`'s job).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from hypesocials.config import Config
from hypesocials.models import SourcePost, StructuredCall
# Imported as a MODULE, not through `hypesocials.outputs`, because the store seam
# (`store_source` / `write_source_yaml`) is new in this wave and the domain facade is not in this
# task's file set. W2 re-exports both names from `hypesocials.outputs.__init__` and this import
# becomes `from hypesocials.outputs import store_source, write_source_yaml` (guidelines §3a/§18).
from hypesocials.outputs import packager
from hypesocials.prompts_engine import PromptEngine

logger = logging.getLogger(__name__)

#: FR-306 pins the analysis role — `models.analysis` (Claude Sonnet 5) and `max_tokens.analysis`.
#: The same role the vision check rides; config defines no separate slide-intelligence model key,
#: and inventing one would be a config change, not a module decision.
SLIDE_INTEL_ROLE = "analysis"
QUESTION_TEMPLATE = "slide_intel_question.md"  # FR-174/181 — a GLOBAL role template, flat in prompts/

#: `SlideIntel.status`, and the `vision.status` line in `source.yaml` (FR-71).
STATUS_OK = "ok"
STATUS_UNAVAILABLE = "vision_unavailable"  # FR-73's degradation tag, verbatim
STATUS_DISABLED = "vision_disabled"  # `sources.vision_transcribe: false`, or a $0 path with no call

#: Per-slide text provenance. `vision_transcribed` is also FR-73's degradation tag.
TEXT_SOURCE_VIRLO = "virlo"
TEXT_SOURCE_VISION = "vision_transcribed"
TEXT_SOURCE_NONE = "none"

#: Fixed, data-free carrier turn — the images attach to the LAST user turn (FR-40) and every word
#: of the question lives in the template (FR-180).
_CARRIER = "Return the slide JSON for the {count} attached slide image(s), in the order attached."

#: Cost fence. A slideshow's `image_urls` is source-controlled, and attaching sixty images to one
#: analysis call is real money the Confirm-gate estimate never quoted (rule 7). Slides past the cap
#: keep their Virlo panel text and their position; they get no local image and no brief, and the
#: cut is warned. Platform carousel ceilings (`platforms.<p>.carousel_slides`) sit far below this.
_MAX_ANALYSED_SLIDES = 20
_DETAIL_MAX = 200  # operator-facing reason strings; never a payload dump
_MAX_BRAND_MARKS = 10
_MARK_MAX = 120

#: Strict-mode schema (RESULTS.md §E: every property required, `additionalProperties: false`). The
#: CALLER owns the schema — `llm.py` is schema-agnostic by contract. `slide` is the 1-based
#: attachment slot, mapped back onto the caller's own positions in `_answers()`.
_SLIDE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "slide": {"type": "integer"},
        "onimage_text": {"type": "string"},
        "visual_brief": {"type": "string"},
        "brand_marks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["slide", "onimage_text", "visual_brief", "brand_marks"],
    "additionalProperties": False,
}
_SCHEMA: dict[str, Any] = {
    "name": "slide_intelligence",
    "schema": {"type": "object", "properties": {"slides": {"type": "array", "items": _SLIDE}},
               "required": ["slides"], "additionalProperties": False},
}


@dataclass(slots=True)
class SourceSlide:
    """One slide of the SOURCE deck: what it said, what it showed, and where its copy lives.

    `position` is the source panel position — 1-based, index-aligned to the deck's own
    `panel_count`, never compacted (D46 §0.14a). An empty panel keeps its slot, because slot 3
    being blank is information the deck mapping needs.
    """

    position: int
    virlo_text: str = ""  # `panel_texts[position - 1]`, exactly as Virlo returned it
    vision_text: str = ""  # the transcription; used only where `virlo_text` is empty
    visual_brief: str = ""  # English, content-not-style, drives the render prompt (FR-308)
    brand_marks: list[str] = field(default_factory=list)  # what the slide shows, for §0.12 safety
    image_file: str | None = None  # `slide_01.jpg` inside `source/<post_id>/`; None when unfetched

    @property
    def text(self) -> str:
        """The slide's on-image words: Virlo's panel if it has one, else the transcription."""
        return self.virlo_text or self.vision_text

    @property
    def text_source(self) -> str:
        """Provenance of `text` — `virlo`, `vision_transcribed`, or `none` for a blank slot."""
        if self.virlo_text:
            return TEXT_SOURCE_VIRLO
        return TEXT_SOURCE_VISION if self.vision_text else TEXT_SOURCE_NONE


@dataclass(slots=True)
class SlideIntel:
    """One source post, read: its slides, how the reading went, and what the reading cost."""

    post_id: str
    slides: list[SourceSlide] = field(default_factory=list)
    status: str = STATUS_OK
    reason: str = ""  # why it is not `ok`; operator-facing, never a secret (D30)
    folder: str = ""  # `source/<post_id>` relative to the run folder — the gallery's href root
    cost_usd: float = 0.0  # feeds FR-106c's reserve/reconcile, like every other paid call
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def slide(self, position: int) -> SourceSlide | None:
        """That source position's slide, or None — positions are the deck's, not list indices."""
        return next((item for item in self.slides if item.position == position), None)

    @property
    def panel_texts(self) -> list[str]:
        """The merged on-image words in panel order — what OUR deck quotes, slot for slot."""
        return [item.text for item in self.slides]

    @property
    def usable_panels(self) -> int:
        """Slots that carry words after the merge — FR-304's ≥2 deck-eligibility predicate."""
        return sum(1 for item in self.slides if item.text.strip())

    @property
    def degradations(self) -> list[str]:
        """FR-73 tags this analysis earned, in the vocabulary `meta.yaml` already speaks."""
        tags: list[str] = []
        if self.status != STATUS_OK:
            tags.append(STATUS_UNAVAILABLE)
        if any(item.text_source == TEXT_SOURCE_VISION for item in self.slides):
            tags.append(TEXT_SOURCE_VISION)
        return tags

    def relative_image(self, position: int) -> str | None:
        """`source/<post_id>/slide_NN.jpg` for the gallery and `panel_map`, or None (FR-75/FR-309).

        Relative to the run folder and forward-slashed: FR-75 forbids hotlinks and absolute paths,
        and a browser reads `./source/…` the same way on any drive the operator moves the run to.
        """
        found = self.slide(position)
        return f"{self.folder}/{found.image_file}" if found and found.image_file else None


async def enrich(
    posts: Sequence[SourcePost],
    *,
    run_dir: str | Path,
    call: StructuredCall | None,
    engine: PromptEngine,
    cfg: Config | None = None,
    log: Any = None,
) -> dict[str, SlideIntel]:
    """Read every assigned carousel's source deck: download it, transcribe it, describe it.

    Args:
        posts: the ASSIGNED carousels' source posts (`models.SourcePost`), one per bound entry;
            duplicates are analysed once and returned under one key. Filtering, ranking and
            binding all happened upstream — a post handed here is a post the run already paid to
            build on.
        run_dir: this run's `output/<run_id>/`; the store lands in its `source/` subfolder.
        call: `llm.structured_call` (`models.StructuredCall`); `None` runs the download-and-record
            half alone and reports `vision_disabled` (no LLM spend, so no Confirm-gate exposure).
        engine: the run's `PromptEngine` — supplies `slide_intel_question.md` through the FR-174
            prompts-dir seam, so a niche pack can override the question like any other template.
        cfg: the run config. `sources.vision_transcribe` (default on, D46 §0.6) is the operator's
            off switch, and `models.analysis` is recorded as `source.yaml`'s vision provenance.
        log: anything with `.warn(event_type, message, **data)` — the run's `LogWriter`.

    Returns:
        `{post_id: SlideIntel}`, one entry per distinct post, ALWAYS total over the posts given:
        an entry whose analysis failed comes back with the Virlo panels it already had and a
        non-`ok` status. Never raises — a source deck we could not read is not a reason to lose
        creatives the operator has already approved spending on (D46 §0.14c).
    """
    unique: dict[str, SourcePost] = {}
    for post in posts:
        post_id = str(post.post_id or "").strip()
        if post_id and post_id not in unique:
            unique[post_id] = post
    if not unique:
        return {}
    enabled = call is not None and _vision_enabled(cfg)
    results = await asyncio.gather(*(
        _one_post(post_id, post, run_dir=Path(run_dir), call=call, engine=engine, cfg=cfg,
                  enabled=enabled, log=log)
        for post_id, post in unique.items()))
    return {intel.post_id: intel for intel in results}


# --------------------------------------------------------------------------------------------
# One post: store, read, record
# --------------------------------------------------------------------------------------------


async def _one_post(
    post_id: str,
    post: SourcePost,
    *,
    run_dir: Path,
    call: StructuredCall | None,
    engine: PromptEngine,
    cfg: Config | None,
    enabled: bool,
    log: Any,
) -> SlideIntel:
    """The whole per-post pipeline, every step of which may fail without failing the post."""
    intel = SlideIntel(
        post_id=post_id,
        slides=_skeleton(post),
        folder=f"{packager.SOURCE_DIR}/{packager.source_dir(run_dir, post_id).name}",
    )
    if not intel.slides:
        intel.status, intel.reason = STATUS_UNAVAILABLE, "the post carries no panels and no slides"
        _warn(log, "slide_intel_no_slides",
              f"source post {post_id} has neither panel texts nor slide images — "
              "this carousel renders from its topic context alone", post_id=post_id)
        _record(intel, post, run_dir=run_dir, cfg=cfg, log=log)
        return intel
    await _store_slides(intel, _image_urls(post), run_dir=run_dir, log=log)
    if enabled and call is not None:
        await _read_slides(intel, call=call, engine=engine, run_dir=run_dir, log=log)
    else:
        intel.status = STATUS_DISABLED
        intel.reason = ("no model call available" if call is None
                        else "sources.vision_transcribe is off")
    _record(intel, post, run_dir=run_dir, cfg=cfg, log=log)
    return intel


def _skeleton(post: SourcePost) -> list[SourceSlide]:
    """One `SourceSlide` per SOURCE panel position, pre-filled with Virlo's own panel text.

    The deck's length is the widest thing the post knows about itself — its declared
    `panel_count`, the panel texts it carried, or the slide images it listed — because a post that
    declares 8 panels and ships 8 images but only 3 non-empty texts still has 8 slides, and slot 4
    being empty is exactly the gap vision is here to fill (D46 §0.14a: padded, never compacted).
    """
    panels = [str(text or "") for text in post.panel_texts]
    images = _image_urls(post)
    count = max(_int(post.panel_count), len(panels), len(images))
    return [SourceSlide(position=position,
                        virlo_text=panels[position - 1] if position <= len(panels) else "")
            for position in range(1, count + 1)]


async def _store_slides(intel: SlideIntel, urls: list[str], *, run_dir: Path, log: Any) -> None:
    """Download this post's slides into `source/<post_id>/`, concurrently, once each."""
    if len(urls) > _MAX_ANALYSED_SLIDES:
        _warn(log, "slide_intel_slides_capped",
              f"source post {intel.post_id} lists {len(urls)} slide images; only the first "
              f"{_MAX_ANALYSED_SLIDES} are downloaded and analysed (cost fence) — later slides "
              "keep their panel text and their position", post_id=intel.post_id,
              listed=len(urls), analysed=_MAX_ANALYSED_SLIDES)
    await asyncio.gather(*(
        _store_one(intel, position, url, run_dir=run_dir, log=log)
        for position, url in enumerate(urls[:_MAX_ANALYSED_SLIDES], start=1)))


async def _store_one(
    intel: SlideIntel, position: int, url: str, *, run_dir: Path, log: Any
) -> None:
    """One slide. A 404 (or a full disk) costs that slide its image and nothing else (§0.14c)."""
    slide = intel.slide(position)
    if slide is None or not str(url or "").strip():
        return
    try:
        path = await packager.store_source(run_dir, intel.post_id, position, str(url))
    except (packager.PackagingError, OSError) as exc:
        _warn(log, "slide_intel_download_failed",
              f"source slide {position} of post {intel.post_id} could not be stored: "
              f"{str(exc)[:_DETAIL_MAX]} — the gallery shows no image for it and it gets no "
              "visual brief", post_id=intel.post_id, position=position)
        return
    slide.image_file = path.name


async def _read_slides(
    intel: SlideIntel, *, call: StructuredCall, engine: PromptEngine, run_dir: Path, log: Any
) -> None:
    """The one paid call: every stored slide of this post, one question, per-slide answers."""
    blobs, positions = await _load(intel, run_dir=run_dir, log=log)
    if not blobs:
        _unavailable(intel, "no source slide could be read", log)
        return
    try:
        question = engine.render(QUESTION_TEMPLATE, {})
    except (ValueError, LookupError) as exc:  # unresolved placeholder / no template at all
        _unavailable(intel, f"slide-intelligence template unusable: {exc}", log)
        return
    try:
        result = await call(
            SLIDE_INTEL_ROLE,
            [{"role": "system", "content": question},
             {"role": "user", "content": _CARRIER.format(count=len(blobs))}],
            _SCHEMA,
            blobs,
        )
    except Exception as exc:  # noqa: BLE001 — fail-open by contract (§0.14c). The class NAME only:
        # a provider error body can carry a URL or a payload, and this string reaches the operator
        # and the log (D30).
        logger.warning("slide_intel: analysis call failed (%s)", type(exc).__name__)
        _unavailable(intel, f"the analysis call raised {type(exc).__name__}", log)
        return
    # Usage is recorded even on a degraded answer: a truncated call was billed, and FR-106c
    # reconciles against what was spent, not against what was usable.
    intel.cost_usd = result.cost_usd
    intel.prompt_tokens = result.prompt_tokens
    intel.completion_tokens = result.completion_tokens
    if result.degraded or not isinstance(result.parsed, Mapping):
        # `reason` first — a truncated call's `raw_text` is unfinished JSON, which tells the
        # operator nothing about WHY the read did not happen. The body is the fallback.
        _unavailable(intel, result.reason or result.raw_text or "the analysis returned nothing "
                     "usable", log)
        return
    _apply(intel, result.parsed, positions, log)


async def _load(intel: SlideIntel, *, run_dir: Path, log: Any) -> tuple[list[bytes], list[int]]:
    """The stored bytes plus the slide POSITION each attachment came from (no second download).

    Reading back from disk rather than keeping the download in memory is deliberate: it makes the
    deduplicated path — a sibling creative on the same post, whose slides were already on disk —
    take the identical code path as a fresh fetch, with no network either way.
    """
    stored = [item for item in intel.slides if item.image_file]
    if not stored:
        return [], []
    folder = packager.source_dir(run_dir, intel.post_id)
    blobs = await asyncio.gather(*(
        _load_one(folder / str(item.image_file), intel.post_id, item.position, log)
        for item in stored))
    return ([blob for blob in blobs if blob],
            [item.position for item, blob in zip(stored, blobs) if blob])


async def _load_one(path: Path, post_id: str, position: int, log: Any) -> bytes:
    """One stored slide's bytes. An unreadable file is dropped, never raised."""
    try:
        return await asyncio.to_thread(path.read_bytes)
    except OSError as exc:
        _warn(log, "slide_intel_input_unreadable",
              f"stored source slide {position} of post {post_id} could not be read back: "
              f"{type(exc).__name__}", post_id=post_id, position=position)
        return b""


def _apply(intel: SlideIntel, parsed: Mapping[str, Any], positions: Sequence[int], log: Any) -> None:
    """Merge the model's answers onto the slides, by POSITION, and count what never came back."""
    answered: set[int] = set()
    for slot, row in _answers(parsed, positions):
        slide = intel.slide(slot)
        if slide is None:
            continue
        answered.add(slot)
        # Virlo's panel is the verbatim source of record; the transcription is kept beside it as
        # provenance either way, so `source.yaml` can show both and the merge stays inspectable.
        slide.vision_text = str(row.get("onimage_text") or "")
        slide.visual_brief = " ".join(str(row.get("visual_brief") or "").split())
        slide.brand_marks = _marks(row.get("brand_marks"))
    if missing := [position for position in positions if position not in answered]:
        _warn(log, "slide_intel_brief_missing",
              f"the analysis returned no answer for slide(s) {missing} of post {intel.post_id} — "
              "they keep their panel text and render without a visual brief",
              post_id=intel.post_id, slides=missing)


def _answers(
    parsed: Mapping[str, Any], positions: Sequence[int]
) -> list[tuple[int, Mapping[str, Any]]]:
    """Map the model's 1-based attachment slots back onto the caller's own slide positions.

    Answers arrive numbered over the ATTACHMENTS, and a slide that 404'd was never attached, so
    slot 3 of four attachments may be source position 5. An out-of-range slot is dropped rather
    than clamped: a wrong answer put on a real slide is worse than a missing one (§0.14c aligns by
    position, and missing means absent).
    """
    out: list[tuple[int, Mapping[str, Any]]] = []
    for order, row in enumerate(parsed.get("slides") or [], start=1):
        if not isinstance(row, Mapping):
            continue
        try:
            slot = int(row.get("slide") or order)
        except (TypeError, ValueError):
            slot = order
        if 1 <= slot <= len(positions):
            out.append((positions[slot - 1], row))
    return out


def _record(
    intel: SlideIntel, post: SourcePost, *, run_dir: Path, cfg: Config | None, log: Any
) -> None:
    """Write `source.yaml` — FR-71's post provenance, per-slide rows and vision provenance.

    A store that cannot be written is warned and dropped: the run has the intelligence in memory
    either way, and losing the gallery's provenance file is not worth losing the creative.
    """
    try:
        packager.write_source_yaml(run_dir, intel.post_id, _payload(intel, post, cfg))
    except (packager.PackagingError, OSError) as exc:
        _warn(log, "slide_intel_store_failed",
              f"source.yaml for post {intel.post_id} could not be written: "
              f"{str(exc)[:_DETAIL_MAX]} — the gallery falls back to meta.yaml's panel map",
              post_id=intel.post_id)


def _payload(intel: SlideIntel, post: SourcePost, cfg: Config | None) -> dict[str, Any]:
    """FR-71's `source.yaml` schema, in its declared order — one producer, one key list."""
    return {
        "post_id": intel.post_id,
        "url": str(post.url or ""),
        "author": str(post.author or ""),
        "views": _int(post.views),
        "published_at": _iso(post.published_at),
        "caption": str(post.caption or ""),
        "panel_count": len(intel.slides),
        "slides": [{
            "position": slide.position,
            "virlo_text": slide.virlo_text,
            "vision_text": slide.vision_text,
            "visual_brief": slide.visual_brief,
            "brand_marks": list(slide.brand_marks),
            "vision_transcribed": slide.text_source == TEXT_SOURCE_VISION,
            "image_file": slide.image_file,
        } for slide in intel.slides],
        "vision": {
            "model_role": SLIDE_INTEL_ROLE,
            "model_id": cfg.models.analysis if cfg is not None else "",
            "status": intel.status,
            "reason": intel.reason,
        },
    }


# --------------------------------------------------------------------------------------------
# Small internals
# --------------------------------------------------------------------------------------------


def _vision_enabled(cfg: Config | None) -> bool:
    """`sources.vision_transcribe` — the operator's off switch, ON by default (D46 §0.6).

    No config at all (a caller building one post's intelligence in isolation) reads as ON, which
    matches the config default: the two can never disagree about the posture.
    """
    return cfg is None or bool(cfg.sources.vision_transcribe)


def _image_urls(post: SourcePost) -> list[str]:
    """The post's slide images in PANEL ORDER (`image_urls`, position-sorted by the wrapper).

    `image_urls[i]` is the picture whose words are `panel_texts[i]` (FR-293), which is the whole
    reason the download loop can name its files after source positions.
    """
    return [str(url) for url in post.image_urls if str(url or "").strip()]


def _sequence(value: Any) -> list[Any]:
    """A list from anything list-shaped; a string or None is not a sequence of items here."""
    return list(value) if isinstance(value, (list, tuple)) else []


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _iso(value: Any) -> str | None:
    """ISO 8601 for `source.yaml`, or None — FR-71 stores strings, not datetime objects."""
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value or "").strip()
    return text or None


def _marks(value: Any) -> list[str]:
    """The brand marks the model named, bounded — a list is evidence, not free-form prose."""
    return [str(mark).strip()[:_MARK_MAX]
            for mark in _sequence(value) if str(mark or "").strip()][:_MAX_BRAND_MARKS]


def _unavailable(intel: SlideIntel, reason: str, log: Any) -> None:
    """The one degrade that covers a whole post: Virlo panels stand, tagged `vision_unavailable`."""
    intel.status = STATUS_UNAVAILABLE
    intel.reason = reason[:_DETAIL_MAX]
    _warn(log, "slide_intel_unavailable",
          f"slide intelligence did not run for post {intel.post_id} ({len(intel.slides)} slide(s)): "
          f"{intel.reason} — the deck keeps its Virlo panel texts and renders without visual briefs",
          post_id=intel.post_id, slides=len(intel.slides))


def _warn(log: Any, event_type: str, message: str, **data: Any) -> None:
    logger.warning("%s: %s", event_type, message)
    if log is not None:
        log.warn(event_type, message, **data)


__all__ = [
    "QUESTION_TEMPLATE", "SLIDE_INTEL_ROLE", "STATUS_DISABLED", "STATUS_OK", "STATUS_UNAVAILABLE",
    "TEXT_SOURCE_NONE", "TEXT_SOURCE_VIRLO", "TEXT_SOURCE_VISION", "SlideIntel", "SourceSlide",
    "enrich",
]
