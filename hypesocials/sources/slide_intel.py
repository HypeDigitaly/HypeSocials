"""Slide intelligence — one vision pass over the slides a carousel was sourced FROM (FR-306, F6).

Module contract
---------------
Purpose: for each carousel source post the plan actually bound, put the source deck on disk once
and read it once — so OUR slide *i* can carry the words that were on THEIR slide *i*, and our
render prompt can describe the same content (chart, grid, checklist) in our own house style.

Public API:
    await enrich(posts, run_dir=..., call=..., engine=..., cfg=..., log=...) -> {post_id: SlideIntel}
    SlideIntel · SourceSlide · MarkBox · SLIDE_INTEL_ROLE · QUESTION_TEMPLATE
    MARK_KINDS · MARK_KIND_TOOL
    detect_counter(chrome_lines, panel_texts, panel_count) -> CounterSpec | None  ·  CounterSpec
    counter_line(text) -> bool — is that line ONLY a page counter (chrome, not copy)?
    STATUS_OK / STATUS_UNAVAILABLE / STATUS_DISABLED
    TEXT_SOURCE_VIRLO / TEXT_SOURCE_VISION / TEXT_SOURCE_NONE

Where it sits: **after the Confirm gate, before COPY** (D46 §0.11). It is paid LLM spend, so it
may not run on a preview path or before the operator approved the estimate (rule 7); the estimator
prices it pre-Confirm from panel counts as its own `slide_intel` line. The caller passes ONLY the
assigned carousels' source posts (≤ `run.formats.carousel` per run, typically 1–2) — this module
does not re-select, re-rank or re-filter anything, and a post handed to it twice by two sibling
creatives is analysed once.

Invariants enforced here, once, for every caller:
- **HARD BOUNDARY — no Virlo URL, and no whole slide, may reach a render payload (D41 as amended
  by D46 and D48, FR-244/FR-306).** Virlo URLs and Virlo bytes live in exactly two places: this
  module, and `output/<run>/source/<post_id>/` for the offline gallery. A Virlo CDN URL is never
  uploaded, never handed to `generate/refs.py`, never passed to the `render.upload_file` seam and
  never quoted into a prompt. What crosses into rendering is TEXT the copy stage resolves — the
  merged on-image words — and the English `visual_brief`, which is a description of content, not a
  reference image. **One narrow exception, added v2.1.3/D48:** a small LOGO PATCH cropped from a
  stored slide by `sources.logo_crops` (FR-315) may be uploaded as a render reference, because a
  name alone makes an obscure mark hallucinate. This module produces the RECTANGLE (`MarkBox`) and
  nothing else — it never crops, never uploads, and still imports nothing from `render` or
  `generate`; a test pins that (`tests/test_slide_intel.py`). Full slides, panels and any other
  crop remain forbidden, which is what `_box()`'s span ceiling enforces at the source.
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
- **The transcription — and ONLY the transcription — is OCR-repaired at admission (v2.2.0).**
  `ocr_repair.repair_confusables` runs once, here, on `vision_text`, because this is the sanctioned
  admission boundary for a string the vision pass invented the bytes of; the unrepaired reading is
  kept as `vision_text_original` and every correction is logged (`ocr_repaired`). A Virlo panel
  never goes through it. Truncation is FLAGGED (`SourceSlide.truncation_suspect`) and never acted
  on: a panel that looks cut keeps its bytes and its position, because dropping it would re-map the
  whole deck (FR-304).
- **Only TOOL marks get boxes (v2.2.0, FR-306 amendment).** `mark_boxes` rows carry a `kind`, and
  `_mark_boxes` keeps `tool` alone — apparel, platform chrome, the creator's own identity and
  anything the model could not place are dropped at the parse boundary, before a rectangle exists
  for FR-315 to crop. Run `…_m39f` cropped and uploaded a patch of a creator's Nike hoodie; the
  narrowest place to end that is here, where the box is born.
- **Creator chrome is transcribed apart from the words (`chrome_text`).** @handles, URLs,
  watermarks, account names, page counters ("3/6"), swipe/follow CTAs and platform UI are the
  creator's signature, not the slide's content, so the question puts them in their own field and
  `onimage_text` carries only what the slide is actually saying. This is a correctness rule, not
  tidiness: §0.12 safety rejects a panel containing a handle or a URL, so a footer watermark
  transcribed into the words used to blank the whole panel — one real deck shipped 100% wordless
  because every slide ended "@theromanknox | skool.com/knox | 3/6 | swipe". Chrome is kept
  (provenance and the gallery show it) and never rendered.
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
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from hypesocials.config import Config
from hypesocials.models import SourcePost, StructuredCall
from hypesocials.ocr_repair import repair_confusables, truncation_suspect
from hypesocials.sources.mark_names import collapse, mark_name
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
#: How many individual OCR repairs a single `ocr_repaired` line spells out. The full list still
#: rides in the event's structured `corrections` field; the prose is for a human reading `run.log`.
_MAX_LOGGED_REPAIRS = 5
#: Bounding boxes kept per DECK, not per slide (FR-306 amendment, v2.1.3/D48). Each one becomes a
#: cropped patch and a Kie upload downstream (FR-315), so the cap is a cost fence — but it is a
#: fence on UPLOADS, not on a deck's ambition, and at 10 it was cutting real marks off real decks.
#: RAISED to 24 after the glz0 audit (v2.1.4): deck 01 was a tool round-up whose panels carried 21
#: distinct product logos, so eleven of them lost their pixels to the cap and rendered from their
#: names alone — which is exactly the invented-logo failure FR-315 exists to end. A tool round-up
#: IS the format this product renders, so the cap has to hold one: 24 covers a 20-panel deck with
#: a mark on every panel plus a cover lockup, and each patch is a ~10 kB crop and one upload the
#: run memo does exactly once (FR-200/244), so the marginal cost of the raise is small and paid
#: only by the decks that actually carry that many marks.
_MAX_MARK_BOXES = 24
#: A "logo" wider or taller than this fraction of the slide is a misdetection — the model boxed the
#: whole panel, a screenshot, or the background. Cropping it would upload the source slide itself,
#: which is exactly what FR-244's narrow carve-out does NOT sanction.
_MARK_BOX_MAX_SPAN = 0.9

#: What a boxed mark IS (v2.2.0, FR-306 amendment). The vocabulary is the model's, the consequence
#: is ours: only `tool` is croppable (FR-315), because only a tool logo is a thing one of our
#: slides might legitimately draw.
#:
#: - `tool` — a software/product logo the slide is TALKING ABOUT (Notion, Claude, Figma, Murf).
#: - `apparel` — a brand on clothing, a bottle, a wall, a car. The 08-14 audit's own case: a
#:   creator's Nike hoodie became a cropped, uploaded "logo patch" on run `…_m39f`.
#: - `chrome` — platform UI and the creator's own signature: a TikTok watermark, an Instagram
#:   glyph, an @handle lockup, a follow button. §0.11 already splits chrome OUT of the words; this
#:   splits it out of the pixels.
#: - `other` — anything the model cannot place. Not croppable, because "I am not sure what this is"
#:   is not a reason to spend an upload on it.
MARK_KINDS = ("tool", "apparel", "chrome", "other")
#: The parser's default when a row names no `kind` — an older cached answer, a truncated row, or
#: (until the wave-1d prompt update lands) every answer the current question produces. `tool`
#: preserves exactly today's behaviour for those payloads, so the schema and the prompt can move in
#: different waves without a deck silently losing every patch in between (§0.14c).
_DEFAULT_MARK_KIND = "tool"
MARK_KIND_TOOL = "tool"

#: Collapsed names that are PLATFORM CHROME whatever the model called them. A box on one of these
#: is a watermark or a UI affordance — the creator's signature or the app's, never the slide's
#: subject — and FR-310 would refuse to let our deck draw it anyway. Matched on
#: `mark_names.collapse(mark_name(...))`, so "TikTok logo", "tiktok" and "TikTok watermark" are one
#: entry. Deliberately platforms only: Canva, CapCut and Figma are tools a round-up really does
#: name, and they are not in here.
_CHROME_MARKS = frozenset({
    "tiktok", "instagram", "ig", "reels", "facebook", "meta", "youtube", "youtubeshorts",
    "shorts", "threads", "twitter", "x", "snapchat", "pinterest", "linkedin", "whatsapp",
    "telegram", "douyin", "xiaohongshu", "rednote"})

#: Strict-mode schema (RESULTS.md §E: every property required, `additionalProperties: false`). The
#: CALLER owns the schema — `llm.py` is schema-agnostic by contract. `slide` is the 1-based
#: attachment slot, mapped back onto the caller's own positions in `_answers()`.
_SLIDE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "slide": {"type": "integer"},
        "onimage_text": {"type": "string"},
        # The creator's own chrome — @handles, URLs, watermarks, page counters ("3/6"), swipe and
        # follow CTAs, platform UI — split OUT of `onimage_text` at the source. It used to ride
        # along with the slide's real words, and downstream §0.12 safety rejects any panel carrying
        # a handle or a URL, so one footer watermark blanked a whole panel (a shipped deck came
        # back 100% wordless). Transcribed verbatim, kept for provenance, never rendered.
        "chrome_text": {"type": "string"},
        "visual_brief": {"type": "string"},
        "brand_marks": {"type": "array", "items": {"type": "string"}},
        # v2.1.3/D48 (FR-306 amendment): where each named mark actually SITS, as a fractional
        # `[x, y, w, h]` box in 0–1 image coordinates with the origin top-left. `brand_marks` gives
        # the render prompt a NAME, and a name is what the model hallucinates from — an obscure
        # mark (Higgsfield, Flodesk, Murf) comes back invented. The box lets FR-315 crop the mark's
        # own pixels out of the stored slide and attach the patch, which is the only thing that
        # makes an unfamiliar logo render as itself. An empty array means "none seen": detection is
        # fail-open, and no box is always a legal answer.
        "mark_boxes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "slide": {"type": "integer"},
                    "box": {"type": "array", "items": {"type": "number"}},
                    # v2.2.0: WHAT the mark is, which decides whether its pixels may be cropped at
                    # all. A vision pass asked only to box "brand marks" boxes everything branded
                    # it can see — the creator's Nike hoodie (run `…_m39f`, cropped and uploaded),
                    # the TikTok watermark, the @handle lockup — and each of those is an upload
                    # bought for a mark no slide of ours will ever draw. Only `tool` survives
                    # `_mark_boxes`; the other three are kept in the vocabulary so the model has
                    # somewhere honest to put them instead of calling a hoodie a logo.
                    "kind": {"type": "string", "enum": list(MARK_KINDS)},
                },
                "required": ["name", "slide", "box", "kind"],
                "additionalProperties": False,
            },
        },
    },
    # Strict mode requires every declared property here (`llm._response_format` always sends
    # `strict: true`), so `mark_boxes` is REQUIRED of the model and OPTIONAL of the parser: an
    # answer that omits it — an older cached payload, a truncated row — is a slide with no boxes,
    # never a failed read (§0.14c).
    "required": ["slide", "onimage_text", "chrome_text", "visual_brief", "brand_marks",
                 "mark_boxes"],
    "additionalProperties": False,
}
_SCHEMA: dict[str, Any] = {
    "name": "slide_intelligence",
    "schema": {"type": "object", "properties": {"slides": {"type": "array", "items": _SLIDE}},
               "required": ["slides"], "additionalProperties": False},
}


@dataclass(frozen=True, slots=True)
class MarkBox:
    """Where one named tool mark sits on one source slide (FR-306 amendment, FR-315).

    Frozen because it is detected once and read many times — the crop step, the render prompt and
    `source.yaml` must all be describing the same rectangle, and a mutable box is a patch that
    stops matching the pixels it was cut from.

    `box` is `(x, y, w, h)` as FRACTIONS of the slide, origin top-left, every value already clamped
    into `[0, 1]` by `_mark_boxes()`. Fractions rather than pixels because the stored slide's
    resolution is the CDN's business, not ours: the same box crops correctly whether the file came
    back 1080 px or 1440 px wide.

    `slide` is the SOURCE deck's 1-based panel position — the same numbering `SourceSlide.position`
    uses, so `source_dir / slide_NN.<ext>` is the file this box cuts from.

    `kind` is one of `MARK_KINDS`, and only `tool` boxes are ever built: `_mark_boxes()` drops the
    rest at the parse boundary, so a `MarkBox` in hand is already a croppable one. It is kept on
    the record (and in `source.yaml`) rather than discarded because the whole point of the field is
    to be auditable — "why did this deck upload three patches and not eleven" is a question the
    provenance file should answer without re-running the vision pass.
    """

    name: str
    slide: int
    box: tuple[float, float, float, float]
    kind: str = MARK_KIND_TOOL


@dataclass(slots=True)
class SourceSlide:
    """One slide of the SOURCE deck: what it said, what it showed, and where its copy lives.

    `position` is the source panel position — 1-based, index-aligned to the deck's own
    `panel_count`, never compacted (D46 §0.14a). An empty panel keeps its slot, because slot 3
    being blank is information the deck mapping needs.
    """

    position: int
    virlo_text: str = ""  # `panel_texts[position - 1]`, exactly as Virlo returned it
    #: The transcription; used only where `virlo_text` is empty. OCR-REPAIRED at admission
    #: (`ocr_repair.repair_confusables`, v2.2.0): "Al agents" transcribed off a slide reading "AI
    #: agents" was reaching paid pixels verbatim, because verbatim is exactly what this pipeline
    #: promises. The repair happens HERE, once, at the sanctioned admission boundary, so the same
    #: bytes feed the panel map, the prompt and FR-100's verifier pool.
    vision_text: str = ""
    #: What the model actually wrote, kept whenever the repair changed anything (else `""`). A
    #: repair that cannot be pointed at afterwards is indistinguishable from drift.
    vision_text_original: str = ""
    #: The creator's chrome, transcribed separately and never merged into `text`: @handles, URLs,
    #: watermarks, page counters, swipe/follow CTAs, platform UI. Provenance and gallery material
    #: only — it is deliberately NOT part of the words our deck quotes, because it is their
    #: signature, not their content, and §0.12 safety rejects a panel that carries it.
    chrome_text: str = ""
    visual_brief: str = ""  # English, content-not-style, drives the render prompt (FR-308)
    brand_marks: list[str] = field(default_factory=list)  # what the slide shows, for §0.12 safety
    image_file: str | None = None  # `slide_01.jpg` inside `source/<post_id>/`; None when unfetched

    @property
    def text(self) -> str:
        """The slide's on-image words: Virlo's panel if it has one, else the transcription."""
        return self.virlo_text or self.vision_text

    @property
    def truncation_suspect(self) -> bool:
        """Does this slot's merged text look CUT rather than finished (`ocr_repair`, FR-304c)?

        A FLAG and nothing more. The panel keeps its bytes and its position whatever this says —
        blanking a suspect panel would silently re-map the whole deck (FR-304), which is worse than
        any transcription defect. The consumer is contract data for the gauntlet's `brief` critic,
        which is looking at the rendered frame and can tell an authored cliff-hanger from a
        clipped container.
        """
        return truncation_suspect(self.text)

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
    #: Every mark box the vision pass placed anywhere on this deck, capped at `_MAX_MARK_BOXES`
    #: (FR-306 amendment). Deck-level rather than per-slide because the cap is per deck and because
    #: the same mark usually recurs on every panel — FR-315 crops it once and the patch is reused.
    mark_boxes: list[MarkBox] = field(default_factory=list)
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

    def boxes_on(self, position: int) -> list[MarkBox]:
        """The mark boxes the vision pass placed on THAT source slide, in detection order.

        The lookup FR-315's crop step asks: a patch is cut from the slide the box was seen on, and
        a box carried over from a neighbouring panel would cut the wrong pixels.
        """
        return [box for box in self.mark_boxes if box.slide == position]

    def relative_image(self, position: int) -> str | None:
        """`source/<post_id>/slide_NN.jpg` for the gallery and `panel_map`, or None (FR-75/FR-309).

        Relative to the run folder and forward-slashed: FR-75 forbids hotlinks and absolute paths,
        and a browser reads `./source/…` the same way on any drive the operator moves the run to.
        """
        found = self.slide(position)
        return f"{self.folder}/{found.image_file}" if found and found.image_file else None


# --------------------------------------------------------------------------------------------
# The source deck's counter convention (D-D, v2.1.2)
# --------------------------------------------------------------------------------------------

#: One counted token inside a line of creator chrome — `3/6`, `01 / 06`, `2 of 7`, `4 · 9`.
#: The two lookbehinds and the two lookaheads are what keep a DATE out (`12/08/2026`): a number
#: glued to another number, or to a second separator, is part of a longer run and not a counter.
#: Both are fixed width, which Python's lookbehind requires.
_COUNTER_TOKEN = re.compile(
    r"(?<!\d)(?<![\d][/.\-])(\d{1,3})(\s*/\s*|\s+of\s+|\s*·\s*)(\d{1,3})(?!\d)(?![/.\-]\d)",
    re.IGNORECASE)
#: The other convention a slideshow counts with: a prefix on the panel's own words, `// 01`.
#: It names no total, so only the position rule below can ever accept it.
_PREFIX_TOKEN = re.compile(r"^\s*(//+\s*)(\d{1,3})(?!\d)")
#: Sanity fence on both numbers. A counter counts a deck, and a deck is not 400 panels long; a
#: bigger number in a chrome line is a price, a year, a view count or a statistic.
_MAX_COUNT = 99


def counter_line(text: str) -> bool:
    """Is this line NOTHING BUT a page counter — the source deck's chrome rather than its words?

    The admission-time half of the counter story (F2, Session 5.5). `detect_counter` below reads
    the same two shapes to LEARN the source's convention so we can re-base it onto our own deck;
    this helper answers the narrower question `copywrite._offer_for` asks of every panel line
    before it may become pixels: are these bytes furniture? They arrive as copy because Virlo's
    adapter has no `chrome_text` field — the vision pass is the only producer of one — so a badge
    that the creator typeset as chrome rides into `panel_texts` with the slide's real words, and
    from there into the panel map, the render prompt and the gauntlet's expected-line contract,
    where a render that correctly left the badge out is BLOCKED for `missing_text`.

    **Full-line only, and that is the whole safety argument.** The line is judged after `strip()`
    and has to be counter-shaped edge to edge, so `3/4 of teams fail at this` is content and ships
    byte-verbatim, and so does `// 01 THE HOOK` — a prefix counter typeset as part of the panel's
    own copy is the source's typography, not a separate badge. Both conventions this module
    already models are accepted on their own line: the paired form (`01 / 06`, `1/6`, `2 of 7`,
    `4 · 9`) and the total-less prefix (`// 01`), each under the same `_MAX_COUNT` fence and the
    same `number <= total` rule the candidate scanners use — which is why `24/7` on a slide of its
    own is a slogan and survives.

    Args:
        text: one line of a source panel. Position in the strip chain does not matter: no strip
            layer edits digits, so the verdict is the same before and after.

    Returns:
        True when the entire line is a counter and may be dropped at admission; False for
        everything else, blank lines included (a blank line is not chrome, and it is not this
        helper's to remove).
    """
    line = str(text or "").strip()
    if not line:
        return False
    paired = _COUNTER_TOKEN.fullmatch(line)
    if paired is not None:
        return 1 <= int(paired.group(1)) <= int(paired.group(3)) <= _MAX_COUNT
    prefix = _PREFIX_TOKEN.match(line)
    return (prefix is not None and prefix.end() == len(line)
            and 1 <= int(prefix.group(2)) <= _MAX_COUNT)


@dataclass(frozen=True, slots=True)
class CounterSpec:
    """The SOURCE deck's counting convention, re-basable onto ours (D-D).

    What the source did — zero-padding, the separator with its exact spacing, an `// ` prefix
    style, whether a total was shown at all — is a design decision of the deck we are mirroring,
    so it is captured rather than normalised. What it counted is NOT kept: the numbers are always
    re-based onto our own deck by `format()`, because our deck may be shorter than theirs (the
    platform ceiling truncates, §0.4′) and a badge reading "4/9" on a five-slide deck is a lie the
    operator sees before anything else.
    """

    #: Digits the numerator was padded to — 2 for `01`, 1 for a bare `3`.
    pad: int = 1
    #: Exactly what sat between the two numbers, spacing included: `/`, ` / `, ` of `, ` · `.
    separator: str = "/"
    #: Digits the denominator was padded to; independent of `pad`, because `01 / 6` exists.
    total_pad: int = 1
    #: The leading marker of a prefix-style counter, spacing included (`"// "`), else empty.
    prefix: str = ""
    #: True for `// 01`: the source showed a position and no total, so neither do we.
    numerator_only: bool = False

    def format(self, n: int, total: int) -> str:
        """This deck's badge for slide `n` of `total`, in the source's own hand.

        `""` for a nonsensical request (a zero or negative position, an empty deck) — a caller
        threading that string into a prompt gets the "no counter" branch, which is the safe one.
        """
        if n < 1 or total < 1:
            return ""
        head = f"{n:0{max(self.pad, 1)}d}"
        if self.numerator_only:
            return f"{self.prefix}{head}"
        return f"{self.prefix}{head}{self.separator}{total:0{max(self.total_pad, 1)}d}"


def detect_counter(
    chrome_lines: Sequence[Sequence[str]], panel_texts: Sequence[str], panel_count: int
) -> CounterSpec | None:
    """Did the source deck number its slides, and if so, how (D-D)?

    Args:
        chrome_lines: per SOURCE slide position (index 0 is slide 1), that slide's creator-chrome
            lines as transcribed by `SourceSlide.chrome_text` — where a page counter lives, since
            the vision question splits chrome away from the slide's words on purpose.
        panel_texts: per slide position, the slide's own words — scanned only for the prefix
            convention (`// 01 THE HOOK`), which is typeset as part of the copy rather than as
            chrome.
        panel_count: the SOURCE deck's length, which is the denominator a real counter agrees
            with.

    Returns:
        The convention to re-base onto our deck, or `None` — and `None` is the answer whenever the
        evidence is thin. Four accept rules, tried in this order (FR-313, detection amended
        v2.1.3/D48):

        1. Some slide's denominator equals `panel_count` — `3/6` on a six-panel deck. The deck's
           own length, written on it: the strongest evidence there is.
        2. At least two slides carry their own position as the numerator (`01`, `02`, …). One
           slide alone proves nothing, which is why the rule counts to two.
        3. **Unnumbered leading slides.** A cover that carries no badge shifts every later one by
           a constant `k ≥ 1`: `1/ 6` on panel 2 … `6/ 6` on panel 7 of a SEVEN-panel deck. Accept
           when the offset `position − number` is the same on every numbered candidate AND the
           denominator equals `panel_count − k` — the deck's length minus its unnumbered covers.
           This is the shape rules 1 and 2 both miss, and it is common enough that a live run
           (`20260813_161444_r9pz`) shipped a numbered deck with no badge because of it.
        4. **Constant positional offset, uncorroborated.** The same positive offset on ≥2 slides
           with no contradicting candidate anywhere in the deck — a 0-indexed or cover-shifted
           system whose denominator we cannot check (the source truncated, or the badge names no
           total). Weaker than rule 3, so it is last, and one candidate disagreeing kills it.

        Everything else is rejected by construction — `24/7` (a numerator above its denominator,
        and a denominator that is not the deck), `12/08/2026` (a run of numbers, not a pair),
        `16:9`, prices, view counts. The cost of a false positive is a badge printed on every slide
        of a deck that never had one; the cost of a false negative is a deck that renders without a
        badge and is told so explicitly. The second is cheap, so the tie still goes to `None`.
    """
    found = [*_chrome_candidates(chrome_lines), *_prefix_candidates(panel_texts)]
    if not found:
        return None
    if panel_count > 0:
        for candidate in found:
            if candidate.total == panel_count:
                return candidate.spec  # the strongest evidence: the deck's length, written on it
    # Second rule: the same badge on ≥2 slides, each stating the place it actually sits in. One
    # slide alone proves nothing — `1/2` in a caption, `5 of 7` inside a statistic — so a single
    # positional hit is dropped rather than believed.
    positional = [item for item in found if item.number == item.position]
    if len({item.position for item in positional}) >= 2:
        return positional[0].spec
    # Third rule (D48): the badges agree with each other but start late. `numbered` only, because
    # the test is on the DENOMINATOR — a prefix counter names none and can never corroborate a
    # cover count, though it is still allowed to contradict the offset under rule 4.
    numbered = [item for item in found if item.total >= 1]
    offset = _constant_offset(numbered)
    totals = {item.total for item in numbered}
    if (offset is not None and offset >= 1 and panel_count > 0 and len(totals) == 1
            and totals.pop() == panel_count - offset):
        return numbered[0].spec
    # Fourth rule (D48): the offset alone, and only when the WHOLE deck agrees with it. Computed
    # over every candidate, prefix ones included, so a single stray token that counts something
    # else refuses the badge rather than being outvoted.
    offset = _constant_offset(found)
    return found[0].spec if offset is not None and offset >= 1 else None


def _constant_offset(candidates: Sequence[_Candidate]) -> int | None:
    """The one `position − number` shared by every candidate on ≥2 distinct slides, else `None`.

    `None` covers both ways the evidence can fail: fewer than two slides carrying a badge (a lone
    token is a coincidence, D-D's standing rule), or two that disagree about the shift, which means
    at least one of them is not counting this deck.
    """
    offsets = {item.position - item.number for item in candidates}
    if len(offsets) != 1 or len({item.position for item in candidates}) < 2:
        return None
    return offsets.pop()


@dataclass(frozen=True, slots=True)
class _Candidate:
    """One counted-looking token, with the two facts the accept rules test it against.

    `spec` is the shape (padding, separator, prefix); `number` and `total` are what THIS slide's
    token read, which never leaves this module — the caller gets a convention, and the numbers are
    always re-based onto our deck.
    """

    position: int  # the SOURCE slide this token sat on, 1-based
    spec: CounterSpec
    number: int
    total: int = -1  # -1 when the convention writes no denominator (`// 01`)


def _chrome_candidates(chrome_lines: Sequence[Sequence[str]]) -> list[_Candidate]:
    """Every `n <sep> m` token in the deck's chrome, in slide order."""
    out: list[_Candidate] = []
    for position, lines in enumerate(chrome_lines, start=1):
        for line in lines or ():
            for match in _COUNTER_TOKEN.finditer(str(line or "")):
                head, separator, tail = match.group(1), match.group(2), match.group(3)
                number, total = int(head), int(tail)
                # A counter never counts past its own deck, and a deck is not 99 panels long:
                # `24/7`, `16/9` and a view count are all excluded here rather than by the rules.
                if not 1 <= number <= total <= _MAX_COUNT:
                    continue
                out.append(_Candidate(
                    position=position, number=number, total=total,
                    spec=CounterSpec(pad=_pad(head), separator=separator, total_pad=_pad(tail))))
    return out


def _prefix_candidates(panel_texts: Sequence[str]) -> list[_Candidate]:
    """`// 01`-style prefixes on the panels' own words — a position with no total to check."""
    out: list[_Candidate] = []
    for position, text in enumerate(panel_texts, start=1):
        match = _PREFIX_TOKEN.match(str(text or ""))
        if match is None or not 1 <= int(match.group(2)) <= _MAX_COUNT:
            continue
        out.append(_Candidate(
            position=position, number=int(match.group(2)),
            spec=CounterSpec(pad=_pad(match.group(2)), prefix=match.group(1),
                             numerator_only=True)))
    return out


def _pad(digits: str) -> int:
    """`01` -> 2, `3` -> 1. A leading zero is the source's padding; its absence is no padding."""
    return len(digits) if digits.startswith("0") else 1


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
        await _read_slides(intel, call=call, engine=engine, run_dir=run_dir,
                           identity=_identity(post), log=log)
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
    intel: SlideIntel, *, call: StructuredCall, engine: PromptEngine, run_dir: Path,
    identity: frozenset[str], log: Any,
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
    _apply(intel, result.parsed, positions, identity, log)


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


def _apply(intel: SlideIntel, parsed: Mapping[str, Any], positions: Sequence[int],
           identity: frozenset[str], log: Any) -> None:
    """Merge the model's answers onto the slides, by POSITION, and count what never came back."""
    answered: set[int] = set()
    boxes: list[MarkBox] = []
    for slot, row in _answers(parsed, positions):
        slide = intel.slide(slot)
        if slide is None:
            continue
        answered.add(slot)
        # Virlo's panel is the verbatim source of record; the transcription is kept beside it as
        # provenance either way, so `source.yaml` can show both and the merge stays inspectable.
        # The transcription is OCR-repaired on the way in (the sanctioned admission boundary — see
        # `ocr_repair`), and only where Virlo left the slot empty does it become anything's text;
        # a populated Virlo panel is never touched by any of this (§0.11).
        slide.vision_text = _transcribed(str(row.get("onimage_text") or ""), intel.post_id, slot,
                                         slide, log)
        # Fail-open on the field too: an older model, a cached answer or a truncated row that
        # names no `chrome_text` is a slide with no chrome, not a failed read (§0.14c).
        slide.chrome_text = str(row.get("chrome_text") or "")
        slide.visual_brief = " ".join(str(row.get("visual_brief") or "").split())
        slide.brand_marks = _marks(row.get("brand_marks"))
        # Deck-level, and capped as a deck (FR-306 amendment): the boxes name their own slide, so
        # an answer that mislabels one is caught by the range test rather than trusted because of
        # where it arrived. `slot` is the fallback for a row that names no slide at all.
        boxes.extend(_mark_boxes(row.get("mark_boxes"), len(intel.slides), slot, identity))
    intel.mark_boxes = boxes[:_MAX_MARK_BOXES]
    if missing := [position for position in positions if position not in answered]:
        _warn(log, "slide_intel_brief_missing",
              f"the analysis returned no answer for slide(s) {missing} of post {intel.post_id} — "
              "they keep their panel text and render without a visual brief",
              post_id=intel.post_id, slides=missing)


def _transcribed(text: str, post_id: str, position: int, slide: SourceSlide, log: Any) -> str:
    """One slide's transcription, OCR-repaired at admission — with the raw bytes kept beside it.

    The defect this exists for is small and expensive: a vision pass reads "AI agents" off a slide
    and writes "Al agents", the panel is empty on Virlo's side so the transcription IS the slide's
    text, and the pipeline then renders it verbatim onto a paid frame — correctly, by its own
    rules, which is what makes it hard to see. `ocr_repair` fixes exactly that class (uppercase-
    scoped confusables) and nothing else.

    Applied HERE, once, at the boundary where the string is admitted into the run, so every
    downstream reader — the panel map, the prompt, FR-100's verbatim verifier pool — sees the same
    bytes. `vision_text_original` keeps what the model actually wrote whenever anything changed,
    and every correction is logged under `ocr_repaired`. A Virlo panel is not touched by any of
    this: it is the source of record, and repairing it would move the bytes the verifier compares
    against (§0.11).
    """
    repaired, corrections = repair_confusables(text)
    if not corrections:
        return text
    slide.vision_text_original = text
    _event(log, "ocr_repaired",
           f"slide {position} of post {post_id}: {len(corrections)} OCR confusable(s) repaired in "
           f"the transcription (" + ", ".join(f"{item.before!r}->{item.after!r}"
                                              for item in corrections[:_MAX_LOGGED_REPAIRS])
           + ") — the raw reading is kept in source.yaml as vision_text_original",
           post_id=post_id, position=position,
           corrections=[{"before": item.before, "after": item.after, "index": item.index}
                        for item in corrections])
    return repaired


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
            # The unrepaired reading, present only when the OCR repair actually changed something
            # (`""` otherwise). Doctrine, not decoration: a repair that cannot be pointed at
            # afterwards is indistinguishable from the drift the verbatim contract exists to stop.
            "vision_text_original": slide.vision_text_original,
            # A FLAG on the merged text, never a licence to blank it (`ocr_repair`, FR-304c).
            "truncation_suspect": slide.truncation_suspect,
            # Recorded beside the words, never inside them: the archive documents that the source
            # slide was signed "@creator | site.com | 3/6" without that signature ever becoming
            # text our deck could quote (FR-71 is provenance, not pixels).
            "chrome_text": slide.chrome_text,
            "visual_brief": slide.visual_brief,
            "brand_marks": list(slide.brand_marks),
            "vision_transcribed": slide.text_source == TEXT_SOURCE_VISION,
            "image_file": slide.image_file,
        } for slide in intel.slides],
        # Deck-level beside the per-slide `brand_marks` rows, because the cap is per deck and a
        # mark recurs across panels (FR-306 amendment). Provenance, like everything else in this
        # file: it records WHERE the pixels FR-315 cropped came from, so a patch that renders wrong
        # can be traced back to the rectangle that produced it without re-running the vision pass.
        "mark_boxes": [{"name": box.name, "slide": box.slide, "box": list(box.box),
                        "kind": box.kind}
                       for box in intel.mark_boxes],
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


def _mark_boxes(value: Any, slide_count: int, default_slide: int,
                identity: frozenset[str]) -> list[MarkBox]:
    """The CROPPABLE mark boxes in one answer row — sanitised hard, per entry, never raising.

    Every rejection here is silent and local, which is the whole posture of this module (§0.14c):
    a box FR-315 cannot crop from costs its mark a pixel reference and nothing else — the mark
    still renders from its name and its written description. So a malformed entry is dropped where
    it is found rather than degrading the deck or, worse, reaching Pillow as a bad rectangle.

    Three filters, in order of how much they cost to get wrong:

    1. **Shape** — a name, a rectangle `_box()` trusts, a slide inside the deck.
    2. **Kind** (v2.2.0) — only `tool`. The 08-14 audit measured what "every branded thing the
       model can see" actually costs: run `…_m39f` cropped and uploaded a patch of the creator's
       Nike hoodie. Apparel, platform chrome and "not sure" are marks no slide of ours will draw,
       so their pixels are never bought. `kind` is REQUIRED of the model and optional of the
       parser, defaulting to `tool` — until the wave-1d prompt teaches the classification, every
       answer parses exactly as it does today.
    3. **Identity** — a box on the CREATOR's own mark (their @handle, their account name, their
       page's wordmark) or on platform chrome, matched by collapsed name. FR-312 strips the
       creator's identity out of the words; a deck that then uploads their logo as a reference and
       renders it onto slide 1 has published their signature anyway, by a different door.

    Args:
        value: the model's `mark_boxes` array, or anything at all — `None`, a string and a dict all
            read as "no boxes", because an older or truncated payload has no boxes, not an error.
        slide_count: the SOURCE deck's length; a box naming a slide outside it named nothing.
        default_slide: the position of the answer row these boxes arrived on, used when an entry
            names no slide of its own.
        identity: this post's own collapsed identity keys (`_identity`) — never croppable.
    """
    out: list[MarkBox] = []
    for raw in _sequence(value):
        if not isinstance(raw, Mapping):
            continue
        name = " ".join(str(raw.get("name") or "").split())[:_MARK_MAX]
        slide = _int(raw.get("slide")) or default_slide
        box = _box(raw.get("box"))
        kind = str(raw.get("kind") or _DEFAULT_MARK_KIND).strip().casefold()
        if not name or box is None or not 1 <= slide <= slide_count:
            continue
        if kind not in MARK_KINDS:
            kind = _DEFAULT_MARK_KIND  # an unknown label is an unclassified TOOL, not a new class
        if kind != MARK_KIND_TOOL:
            logger.debug("mark_box_dropped: %r is %s, not a tool logo — never cropped", name, kind)
            continue
        key = collapse(mark_name(name))
        if not key or key in identity or key in _CHROME_MARKS:
            logger.debug("mark_box_dropped: %r is the creator's own identity or platform chrome",
                         name)
            continue
        out.append(MarkBox(name=name, slide=slide, box=box, kind=kind))
    return out


def _identity(post: SourcePost) -> frozenset[str]:
    """This post's own collapsed identity keys — the creator's handle and their display name.

    Both forms, because the two are transcribed interchangeably: one slide's watermark is
    "@theromanknox" and the next slide's footer is "The Roman Knox", and `collapse` is what makes
    them the same key. `author_name` is empty on today's Virlo payloads (the API exposes no display
    name — see `virlo._author_name`), so the set is usually the handle alone; the display-name
    entry costs nothing and starts working the day the field is populated.
    """
    return frozenset(key for value in (getattr(post, "author", ""),
                                       getattr(post, "author_name", ""))
                     if (key := collapse(mark_name(value))))


def _box(value: Any) -> tuple[float, float, float, float] | None:
    """`[x, y, w, h]` as clamped fractions, or `None` when the rectangle is not one.

    Clamped rather than rejected on range, because a model that says `1.02` means the slide's edge
    and a crop that stops at the edge is the right crop. Rejected on SHAPE: a zero-area box crops
    nothing, and a box spanning more than `_MARK_BOX_MAX_SPAN` of the slide is the model boxing the
    panel instead of the logo — uploading that patch would smuggle the source slide itself past
    FR-244's narrow carve-out, which sanctions logo patches and only logo patches.
    """
    values = _sequence(value)
    if len(values) != 4:
        return None
    try:
        x, y, width, height = (min(1.0, max(0.0, float(item))) for item in values)
    except (TypeError, ValueError):
        return None
    if not 0.0 < width <= _MARK_BOX_MAX_SPAN or not 0.0 < height <= _MARK_BOX_MAX_SPAN:
        return None
    return (x, y, width, height)


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


def _event(log: Any, event_type: str, message: str, **data: Any) -> None:
    """An INFO-level run event, for the things that are worth seeing but are not degradations.

    Read through `getattr` because this module's `log` is duck-typed on `.warn` alone (its tests
    pass a two-method stub, and a $0 path passes `None`). An OCR repair is not a degrade — nothing
    was lost and nothing fell back — so it may not land in the warning ledger the operator reads as
    "what went wrong on this run".
    """
    logger.info("%s: %s", event_type, message)
    emit = getattr(log, "event", None) if log is not None else None
    if callable(emit):
        emit(event_type, message, **data)


__all__ = [
    "MARK_KINDS", "MARK_KIND_TOOL", "QUESTION_TEMPLATE", "SLIDE_INTEL_ROLE", "STATUS_DISABLED",
    "STATUS_OK", "STATUS_UNAVAILABLE", "TEXT_SOURCE_NONE", "TEXT_SOURCE_VIRLO",
    "TEXT_SOURCE_VISION", "CounterSpec", "MarkBox", "SlideIntel", "SourceSlide", "counter_line",
    "detect_counter", "enrich",
]
