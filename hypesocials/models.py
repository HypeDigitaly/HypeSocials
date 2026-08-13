"""Shared contracts — the Wave-1 barrier artifact every other module imports.

Dataclasses, enums, type aliases and pinned call signatures only, so modules agree on shape
without importing each other. FR references are the spec (`prds/`), not decoration. NOT here:
logic, I/O, provider field names, config defaults, non-stdlib imports. Additions via the
conductor only (plan §3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Literal, Protocol

# Closed vocabularies that are config strings, not enums.
CreativeFormat = Literal["image", "carousel", "reel"]  # 10 FR-1
InfluenceMode = Literal["override", "blend"]  # 10 FR-144/145, D26
Platform = str  # platform names are config keys (30 §2), never hardcoded


class DegradationTag(str, Enum):
    """FR-73's `degradations` vocabulary — SINGLE source for meta.yaml and gallery badges.
    Clean asset = empty list; each tag's behaviour is owned by the FR that emits it, this enum
    owns only the spelling, so a new tag needs no schema change (the gallery loops over them).
    """

    COPY_DEGRADED = "copy_degraded"  # FR-99 (Notion absence is a warning, never a tag)
    # KEPT, REDEFINED at W2 (v2.0.0, contracts item 7): "no source string fits this style's
    # on-image budget — caption-only creative." Under the §1.7 verbatim contract an over-budget
    # string is never offered, so an empty frame is a legitimate degrade, not a failure; the tag
    # tells the operator WHY the frame is wordless. Still also set by `_fallback_copy` beside
    # COPY_DEGRADED (a failed copy call ships the top post's caption verbatim + no on-image
    # text): the first is an LLM outcome the run summary counts (FR-248's `llm_starved` set),
    # the second is what the operator will actually see in the frame.
    NO_ONIMAGE_TEXT = "no_onimage_text"
    # FR-100/101 (v2.0.0) — the verifier's polarity flip: post-pivot every on-image string must be
    # a byte-substring of the quoted `SourcePost`, so this marks the one case where a rendered
    # string drifted from its source. Audit signal only; it NEVER fails the creative — the
    # creative is already made, and the operator needs to know which card to distrust, not to be
    # handed fewer cards.
    COPY_NOT_VERBATIM = "copy_not_verbatim"
    # FR-294 — a competitor brand name was removed from this creative's text (blocklist or the
    # filter's `strip` verdict). The copy is still sourced; it is simply no longer byte-identical,
    # which is exactly what the verifier above would otherwise report as a deviation.
    COMPETITOR_STRIPPED = "competitor_stripped"
    # FR-295 — the assigned meta-style's `reference_images` were missing or failed the magic-byte
    # check, so the style shipped as text-only (its prose still steers the render, its pictures do
    # not). A warning at pre-flight, never an error: a style without its files is still a style.
    STYLE_REFS_MISSING = "style_refs_missing"
    # --- D46 / v2.1.0 (FR-73's amended vocabulary, four new spellings) ---
    # FR-306 — the slide-intelligence pass supplied on-image text Virlo had not transcribed: at
    # least one of this deck's slides carries the VISION reading of the source panel rather than
    # Virlo's own `panel_texts[i]`. Still verbatim (it is the words that were on that slide) and
    # still position-preserving; the tag says which reading the operator is looking at, because a
    # transcription can misread a glyph in a way a Virlo panel cannot.
    VISION_TRANSCRIBED = "vision_transcribed"
    # FR-306 — the vision call failed, timed out or had nothing readable to send, so the deck kept
    # the Virlo panels it already had and rendered without visual briefs. Fail-open by contract
    # (§0.14c): a source deck we could not read is never a reason to lose a creative the operator
    # has already approved spending on.
    VISION_UNAVAILABLE = "vision_unavailable"
    # FR-304/§0.4′ — the source deck was LONGER than the platform's carousel ceiling, so only its
    # first N panels were rendered. Indices are preserved (slide i is still source panel i); what
    # is lost is the tail, and the tag is what tells the operator the deck they see is a prefix of
    # the deck that was analysed. Emitted by `generate/carousel.py` against `source_panel_count`.
    PANELS_TRUNCATED = "panels_truncated"
    # FR-307/§0.10 — no unused source post was left for this creative. Emitted in two places, both
    # meaning the same thing: `plan.assign` skips a creative group outright when a topic's fresh
    # slideshow posts are exhausted, and `copywrite` refuses (belt-and-braces behind the fetch
    # gate) when the post the plan bound turns out to be burnt after all — that creative still
    # ships, with our own assembled caption and no on-image text. Famine over silent repeats: a
    # post an earlier run quoted is never quoted again, and no neighbour is substituted for it.
    NO_FRESH_POST_AVAILABLE = "no_fresh_post_available"
    REFERENCE_FREE = "reference_free"  # FR-18
    REFS_DROPPED_MODERATION = "refs_dropped_moderation"  # FR-97
    TEXT_TRIMMED = "text_trimmed"  # FR-101
    INCOMPLETE = "incomplete"  # partial carousel, FR-20/95
    SKIPPED_BUDGET = "skipped_budget"  # FR-106
    ABANDONED = "abandoned"  # FR-108 deadline / FR-201 interrupt
    SEED_FRAME_RENDER_FAILED = "seed_frame_render_failed"  # FR-24
    SEED_FRAME_URL_UNREACHABLE = "seed_frame_url_unreachable"  # FR-24
    AUDIO_DROPPED_CONTENT_AUDIT = "audio_dropped_content_audit"  # FR-141 content-audit degrade
    #   (v1.6.6): clip re-submitted once with generate_audio=false; references kept


class PlanEntryStatus(str, Enum):
    """Run-side lifecycle of a plan entry (FR-4: nothing ever leaves the plan). Wider than
    `AssetStatus`, which is what meta.yaml persists — SKIPPED/SKIPPED_BUDGET/ABANDONED map to
    AssetStatus.FAILED plus the matching DegradationTag and a `skip_reason` line.
    """

    PENDING = "pending"
    SUBMITTED = "submitted"  # money has moved — spend tallies on submission (FR-106)
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"  # dropped for a non-budget reason (10 §10)
    SKIPPED_BUDGET = "skipped_budget"  # trimmed or cap-blocked (FR-28/106)
    ABANDONED = "abandoned"  # left in flight by deadline or Ctrl+C (FR-108/201)


class AssetStatus(str, Enum):
    """meta.yaml `status` (FR-73). PENDING only between folder creation and rewrite (NFR-21)."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class VisionCheckResult(str, Enum):
    """FR-27's four states — three cannot express "retried"."""

    PASSED = "passed"
    RETRIED_PASSED = "retried_passed"
    RETRIED_FAILED = "retried_failed"
    NOT_CHECKED = "not_checked"


@dataclass(slots=True)
class SourcePost:
    """One winning post inside a topic item — the unit verbatim copy quotes (§1.6/FR-293).

    Post-pivot the source posts ARE the asset: FR-99/100 number these fields as offerable
    candidates, the copy model returns REFERENCES into that numbering (`CopySelection`), and the
    engine resolves the reference back to these bytes. Everything here is therefore stored exactly
    as Virlo returned it — never translated, never retyped, never trimmed outside a word boundary
    — because a string that was edited on the way in can no longer be quoted verbatim on the way
    out. `views` is what ranks the list, and the rank is what the `P<n>` ref labels count over.
    """

    post_id: str
    url: str = ""  # permalink; goes to the roster line and to trend_history (FR-297b/FR-298)
    author: str = ""
    caption: str = ""
    hooks: list[str] = field(default_factory=list)
    text_overlays: list[str] = field(default_factory=list)  # absorbs `text_overlay_contents`
    #: Per-slide words, INDEX-ALIGNED to `panel_count` (FR-293/FR-304, §0.14a of the D46 plan): slot
    #: *i* holds the text of source slide *i+1*, and a slide Virlo transcribed nothing for holds an
    #: empty string rather than closing the gap. The alignment is the contract — FR-304 renders OUR
    #: slide *i* from SOURCE panel *i*, so a compacted list would silently re-map slide 3's words
    #: onto slide 2 and produce a deck that reads as the source's with two slides swapped.
    panel_texts: list[str] = field(default_factory=list)
    description: str = ""
    views: int = 0
    # FR-297b's roster prints an age column and a type tag per post, and neither is derivable from
    # the fields above. `is_slideshow` additionally re-derives `TrendItem.is_slideshow` as the
    # majority over the topic's posts (§1.6), so format affinity stops being a per-monitor guess.
    published_at: datetime | None = None
    is_slideshow: bool = False
    # --- slideshow shape (v2.1.0, FR-293/FR-301): the three fields the adapter used to drop.
    #: How many slides the source deck has, per Virlo's own position-sorted image list. FREE and
    #: known at fetch, which is what lets ASSIGN fix the deck length before the Confirm gate
    #: (§0.4′) instead of discovering it after money moved. Zero on a video row, and zero on a
    #: slideshow row Virlo shipped without images — which is one of FR-305's drop reasons.
    panel_count: int = 0
    #: The slide image URLs, in panel order (the wrapper sorts them by Virlo's `position`), so
    #: `image_urls[i]` is the picture whose words are `panel_texts[i]`. ANALYSIS AND DISPLAY ONLY
    #: (D41 carve-out, FR-306): slide intelligence downloads them into `output/<run>/source/` and
    #: the gallery shows the local copies — a Virlo URL or byte never enters a render payload.
    image_urls: list[str] = field(default_factory=list)
    #: Virlo's own enrichment marker for this row (`"ready"` when its `intelligence` block is
    #: populated). Read as vision-eligibility evidence and logged on `topic_posts`; never a gate on
    #: its own, because rows enriched before a monitor's `data_intelligence_enabled` flipped still
    #: carry populated intelligence while the agent reports `false`.
    intelligence_status: str = ""


@dataclass(slots=True)
class TrendItem:
    """One normalized trend item, assembled per configured monitor id (20 §3 join rule):
    `get_monitor_analysis` gives theme/confidence/why_it_works/tactics, `get_top_videos` +
    `get_top_slideshows` give media/hooks/panel texts/engagement for that same monitor, and the
    global `get_trends` digest only enriches `cross_monitor_context` — it creates no items.

    Post-pivot (v2.0.0) this is a TOPIC item: one topic per theme per monitor, carrying its own
    view-ranked `posts` (FR-293). The name is kept to bound the blast radius, and the media-side
    fields below stay until the W3.5 excision.
    """

    history_key: str  # dedupe + trend_history key: agent id, else normalized name slug
    monitor_id: str
    name: str
    # --- topic-item identity (v2.0.0, FR-293) ---
    # `topic_key` is the stable slug of the theme name and the second half of the post-pivot
    # `history_key` (`"<monitor_id>::<topic_key>"`, §1.6): one monitor now yields several topics,
    # so the monitor id alone can no longer key the repeat-prevention window.
    topic_key: str = ""
    # The topic's own winning posts, view-ranked. This list is the ONLY source of quotable text
    # post-pivot (FR-99/100) and the provenance the history record, the FR-297b roster and the
    # gallery receipt all read; the flat `hook_texts`/`panel_texts` lists further down
    # remain as deduped monitor-level views the prompt engine and previews read.
    posts: list[SourcePost] = field(default_factory=list)
    source: str = "virlo"  # adapter id (20 FR-121)
    strength: float = 0.0  # 0–1, computed by the adapter — the one cross-source contract (FR-5)
    strength_components: dict[str, float] = field(default_factory=dict)  # logged verbatim (FR-5)
    is_slideshow: bool = False  # drives format affinity (FR-90): the topic's view-ranked posts
    #   are majority-slideshow (§1.6 re-derivation — every post-pivot item is text-only by design)
    confidence: float | None = None
    why_it_works: str = ""
    tactics: list[str] = field(default_factory=list)
    hook_texts: list[str] = field(default_factory=list)  # few-shot exemplars for FR-100
    text_overlay_contents: list[str] = field(default_factory=list)
    panel_texts: list[str] = field(default_factory=list)  # per-slide word-count rhythm (FR-13)
    video_descriptions: list[str] = field(default_factory=list)  # feeds FR-96 content sentence
    # Virlo's own `intelligence` labels for the winning posts, deduped and view-ranked like the
    # exemplar lists above. FR-100 currently asks the copywriter to DERIVE a hook pattern in prose
    # that Virlo has already classified (`story_tease`, `question`, measured live), so these
    # replace guesswork with the source's own vocabulary. Absent until a row's
    # `intelligence_status == "ready"`, and the sorted fetch is what makes them common: coverage
    # roughly doubles when the winners lead (17/50 -> 34/50 on videos), because Virlo enriches
    # its best rows first.
    hook_types: list[str] = field(default_factory=list)
    visual_hook_types: list[str] = field(default_factory=list)
    emotional_tones: list[str] = field(default_factory=list)
    # The winning posts' REAL hashtags. The wrapper has always extracted these and nothing read
    # them, while `copywrite._hashtags()` invented tags from the trend-name slug on the FR-99
    # fallback path. Reference material for the copy call only — the model still chooses.
    hashtags: list[str] = field(default_factory=list)
    virlo_url: str | None = None
    total_views: int = 0
    median_views: int = 0
    newest_published_at: datetime | None = None  # velocity/momentum input (FR-5)
    engagement: dict[str, int] = field(default_factory=dict)  # likes/shares/comments/bookmarks
    cross_monitor_context: str = ""  # digest timing analysis + connecting threads (20 §3)


@dataclass(slots=True)
class PlanEntry:
    """One planned creative — the unit of accounting (FR-4) and of trimming. Trimming removes
    entries from the END in reverse plan order (FR-106), so expansion emits brief entries FIRST;
    `atomic_group` makes that one rule sufficient — entries sharing a group trim together and
    never split (a carousel and its slides are one unit, D31).
    """

    order: int  # 0-based plan position; trim order is descending
    asset_id: str  # stable id and asset folder name incl. ordinal (40 FR-73)
    creative_format: CreativeFormat
    platform: Platform
    language: str
    aspect_ratio: str  # from platform+format (FR-21); an API param, never prompt text
    atomic_group: str = ""  # trim unit; defaults to the entry's own id when it stands alone
    slide_count: int | None = None  # carousels; config ceiling = estimate basis (FR-95)
    brief_name: str | None = None  # campaign brief (FR-143)
    brief_influence: InfluenceMode | None = None  # per-entry mode override (D26)
    trend_key: str | None = None  # assigned trend's history_key; None for override briefs (FR-144)
    # §1.6's rotation index, re-scoped by the pivot: this creative's 0-based position among the
    # creatives sharing its topic, set by `plan.assign` from the `use_index` it already counts.
    # It turns the style reference window (`styles.pick_reference_window`) — sibling divergence on
    # one topic is this one number. Every member of an atomic group shares one value: a carousel's
    # slides must quote one post. 0 for override briefs, which quote nothing at all.
    #
    # **DEPRECATED as a post picker (v2.1.0, D46 §0.10).** It used to ALSO choose which
    # `SourcePost` a sibling quoted (`posts[i % len(posts)]`), and that modulo is what let a topic
    # with one fresh post re-quote yesterday's exact post: a rotation over a list cannot know which
    # of its members are burnt. `source_post_id` below replaces it — the plan binds a specific
    # fresh post at ASSIGN and `copywrite` quotes THAT one. The field itself survives because
    # `generate/refs.py` and `styles.pick_reference_window` still turn on it (retired in W3).
    trend_reuse_index: int = 0
    # FR-304/FR-307 (v2.1.0) — the post this creative quotes, bound at ASSIGN by `plan.assign`
    # from the topic's FRESH posts (never a post `trend_history` records as used). It is the whole
    # no-repeat guarantee at pick time: a stable post id, chosen once, carried through copy
    # (`copywrite._offer_for` builds the candidate table from THIS post and refuses a burnt one),
    # provenance (`meta.yaml.copy_source_post_id`) and history. `None` is the legacy/unbound shape
    # — override briefs, which quote nothing, and any entry a caller built before ASSIGN ran.
    # A carousel additionally binds a SLIDESHOW post with ≥2 usable panel slots (§0.14a), because
    # FR-304 renders our slide *i* from that post's panel *i*.
    source_post_id: str | None = None
    # --- style + branding assignment (v2.0.0, FR-290/291/292) ---
    # Written by `styles.assign_styles` / `styles.assign_branding` right after `plan.assign`, both
    # pure functions of `order` over the registry: the style this creative renders in, and whether
    # it carries the wordmark. They live on the entry (not in a side table) because they are
    # persisted to meta.yaml and because trimming must never re-assign a surviving creative.
    style_key: str = ""
    branded: bool = False
    # The topic this entry quotes (§1.6). Sits beside `trend_key`, which stays the history key:
    # one monitor yields many topics, so the history key alone no longer names the material.
    topic_key: str = ""
    status: PlanEntryStatus = PlanEntryStatus.PENDING
    skip_reason: str | None = None  # one line, machine-readable cause (FR-74)
    estimated_cost_usd: float = 0.0  # logged with every trim decision (FR-106)


@dataclass(slots=True)
class LayoutZone:
    """One ordered frame region of FR-92's `layout_zones`."""

    position: str  # e.g. "upper third", "left gutter"
    content: str  # headline, subline, focal subject, negative space, badge
    text_treatment: str  # case, weight, relative size, outline/shadow
    # §1.3/FR-292: `role: "brand_slot"` marks the signature zone. Emitted into `{{layout_zones}}`
    # only when the entry is branded — an unbranded creative gets the zone omitted plus one line
    # saying the lower margin is empty, because a described-but-empty brand slot is the single
    # biggest hallucination site the render models have (M11). Last field and defaulted, so every
    # positional `LayoutZone(position, content, treatment)` construction still holds.
    role: str = ""


@dataclass(slots=True)
class MetaStyle:
    """One meta-style registry entry (§1.3) — the post-pivot visual authority.

    Replaces the per-trend vision analysis as the source of a creative's look: styles are authored
    once in `prompts/styles.yaml` (FR-290, loaded through the FR-174 `prompts_dir` seam) and
    ASSIGNED to entries by a deterministic order-indexed rotation (FR-291), instead of being
    re-derived by an LLM from whatever pictures a trend happened to carry. That is why there is no
    built-in fallback tier — an unusable registry is a pre-flight exit 2 (FR-295), not a degrade.

    `render_prompt` is the executable instruction (an either/or left unresolved here reaches the image
    model as a choice it will make differently on every slide, so M9 forbids it); the five DNA
    fields feed `style_dna` byte-identically across a deck; `exclusions` are LITERAL strings quoted
    from the reference files, because a described wordmark is a string nothing downstream can block.
    """

    key: str
    render_prompt: str = ""  # <=120 words, executable, no unresolved variants (M9)
    subject_mode: str = "scene_open"  # "scene_fixed" | "scene_open" — is the subject the style's?
    layout_zones: list[LayoutZone] = field(default_factory=list)
    format_affinity: list[str] = field(default_factory=list)  # ⊆ {image, carousel, reel}, non-empty
    brand_affinity: list[str] = field(default_factory=list)  # [] = brand-neutral
    # "This style IS a brand": under its matching brand the branding block collapses to nothing
    # extra, the wordmark alone remains. Data-driven on purpose — an override registry with its own
    # keys must not silently lose the rule, which key-matching a name would do (B3).
    brand_slot: bool = False
    text_density: str = "minimal"  # minimal | moderate | high
    max_onimage_chars: dict[str, int] = field(default_factory=dict)  # headline/subline/slide
    motion_profile: str = "photographic"  # photographic | graphic (F24) — reel motion grammar
    palette: list[str] = field(default_factory=list)  # --- the five DNA fields (FR-189) ---
    typography: str = ""
    text_placement: str = ""
    image_treatment: str = ""
    visual_pacing: str = ""
    # Free prose under `carousel_cover` / `carousel_slide` (M9's either/or-resolution home), plus the
    # one marker key `carousel_role` with value "cover_only" or "slides_only": a slides-only style
    # can never anchor a deck, and under anchor-chaining that means it never takes a carousel entry
    # at all. `styles.fmt_affine` owns that reading — no caller re-implements it.
    per_format_guidance: dict[str, str] = field(default_factory=dict)
    exclusions: list[str] = field(default_factory=list)  # LITERAL strings from the refs (M8)
    reference_images: list[str] = field(default_factory=list)  # REPO-ROOT-relative paths (§1.3)


@dataclass(slots=True)
class CopySelection:
    """The copy call's per-creative answer under the §1.7 verbatim contract: references into the
    engine-numbered candidate list where the text becomes pixels or caption, free text only where
    nothing does. Feeds `json_schema_for(CopySelection, exclude={"asset_id"})`.

    The split from `CopySet` is the whole point of FR-99/100: the model CHOOSES (a label), the
    engine RESOLVES (the bytes). A model that answers with prose can drift, translate or invent;
    a model that answers with `P1.hook.2` cannot, and the resolution step can never fail the
    verbatim check because it copies from the source it is checked against. Ref-label grammar
    (FR-302, v2.1.0): `P<n>.<kind>[.<i>]` — `n` = 1-based post ordinal in the topic's view-ranked
    `posts`, `kind` ∈ {panel, overlay, hook, caption}, `i` = 1-based index into that post's list
    field (`caption` is a scalar and carries none). E.g. `P1.hook.2`, `P3.panel.1`. A `panel`
    index is a SOURCE SLIDE POSITION and is position-preserving. `description` is NOT a kind:
    Virlo's AI summary is fenced context only and is never offered, quoted or rendered (FR-303).

    `slide_refs` is answered only by a carousel that bound no source post. A carousel bound to a
    slideshow post has its slides mapped deterministically by the engine (source panel i → slide i,
    FR-304), so the model chooses that deck's cover headline, caption and hashtags and leaves
    `slide_refs` empty; anything it returns there is ignored and logged.
    """

    asset_id: str
    headline_ref: str = ""  # ref label, or "" = nothing fits the budget (NO_ONIMAGE_TEXT path)
    subline_ref: str = ""
    overlay_ref: str = ""  # reel seed-frame hook
    slide_refs: list[str] = field(default_factory=list)  # carousel, one label per slide
    caption_ref: str = ""
    through_line: str = ""  # free text — never pixels
    narrative_arc: str = ""  # free text — carousel arc
    motion_beat: str = ""  # free text — ONE named physical action, reel Stage 2 (F24)


@dataclass(slots=True)
class CopySet:
    """Copy for ONE creative, produced by the per-(trend x language) call of FR-99. On-image
    text arrives already trimmed at the last word boundary under the FR-101 budget — mid-word
    cuts are forbidden, and any trim emits `text_trimmed`.
    """

    asset_id: str
    language: str
    trend_key: str | None = None  # None for override briefs (grouped by brief x language)
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    hook_line: str = ""
    headline: str = ""  # on-image text block (image / every carousel slide)
    subline: str = ""
    slide_texts: list[str] = field(default_factory=list)  # carousel, one coherent sequence (FR-13)
    narrative_arc: str = ""  # carousel: hook -> escalation -> payoff -> close
    overlay_text: str = ""  # reel: burned into the seed frame (FR-24)
    through_line: str = ""  # reel: one-line content through-line for the video prompt
    motion_beat: str = ""  # reel: ONE named physical action for Stage 2 (F24) — resolved from
    #   `CopySelection.motion_beat`; free text because it never becomes pixels (§1.7)


@dataclass(slots=True)
class AssetRecord:
    """Mirrors meta.yaml field for field (FR-73); written `pending` at folder creation and
    rewritten to terminal status by temp+rename (NFR-21)."""

    asset_id: str  # --- identity & sourcing ---
    source: str  # trend key, or "brief/<name>"
    source_name: str
    platform: Platform
    creative_format: CreativeFormat
    # --- provenance & degradations ---
    source_hook: str = ""  # the topic's original hook line, verbatim — gallery card (FR-76, v1.6.4)
    ref_source: str = ""  # "style" | "brief" (contracts item 8 — what the references came FROM)
    # FR-73 (v2.0.0) — post-pivot identity: the assigned meta-style, the brand system and the
    # branding-rotation outcome, and the topic this creative came from (gallery + provenance
    # block read all four; T3.2's gallery re-base is their first consumer).
    style_key: str = ""  # registry key, or "brief_override" under an override brief (M14)
    brand: str = ""  # active branding.brand at render time — never mixed (D43)
    branded: bool = False  # FR-292 floor-predicate outcome for this entry
    topic_key: str = ""  # stable slug of the topic name (FR-293)
    # FR-298 (v2.3) — the verbatim receipt: WHICH post this creative quoted, and WHICH string.
    # `copy_source_refs` maps CopySet slot -> ref label per the §1.7 grammar, e.g.
    # {"headline": "P1.hook.2", "caption": "P1.caption"}; slot names are the CopySet field the
    # ref resolved into (`headline`, `subline`, `overlay_text`, `slide_1`…`slide_N`, `caption`).
    # Empty for override briefs and degrade paths — there was nothing quoted.
    copy_source_post_id: str = ""
    copy_source_refs: dict[str, str] = field(default_factory=dict)
    # FR-73 (v2.1.0) — the slideshow receipt, beside the refs it explains. `copy_source_post_id`
    # says WHICH post; these three say what that post WAS and how its deck maps onto ours, which is
    # what FR-309's three-part gallery card needs to lay the source strip beside our slides.
    #
    # `source_post` is nested provenance of the bound post — `{post_id, url, author, views,
    # published_at, caption}` with ISO strings, never `datetime` objects, because meta.yaml is a
    # plain YAML document a human reads and a Phase-2 publisher parses. `None` when nothing was
    # bound: an override-brief carousel (§0.14d), an image, a reel, a degrade path.
    #
    # `source_panel_count` is the SOURCE deck's own length (not ours) — the number the gallery
    # needs to say "their 7 slides, our 5" and the number `panels_truncated` is measured against.
    # 0 on every non-carousel and on override briefs.
    #
    # `panel_map` is one row per OUR slide, in slide order and position-preserving:
    # `{slide, source_position, source_text, ref_label, visual_brief, source_image}`. The first
    # four are the copy stage's (`copywrite.CopyProvenance.panel_map`), the last two are joined in
    # by `generate.__init__._record()` from the slide-intelligence result (FR-306/FR-308). A slide
    # whose source panel was empty, unusable or over budget keeps its row with an empty
    # `source_text` and an empty `ref_label` — the row is the alignment, so dropping it would
    # silently re-map slide 3's words onto slide 2, which is exactly the defect FR-304 exists to
    # prevent. Empty list for override-brief carousels and for everything that is not a deck.
    source_post: dict | None = None
    source_panel_count: int = 0
    panel_map: list = field(default_factory=list)
    degradations: list[DegradationTag] = field(default_factory=list)
    brief_name: str | None = None  # --- brief overrides (D26) ---
    brief_influence_mode: InfluenceMode | None = None
    model_ids: list[str] = field(default_factory=list)  # --- model & generation (FR-270) ---
    render_not_reproducible: bool = True  # Kie exposes no seeds (FR-109/OQ-4): no seed field
    aspect_ratio_requested: str = ""  # FR-21
    native_size_rendered: str = ""  # what came back; shipped as-is, no crop/pad (FR-98)
    estimated_cost_usd: float = 0.0  # --- cost & timing ---
    actual_cost_usd: float = 0.0
    estimated_tokens: int = 0
    actual_tokens: int = 0
    job_submission_timestamp: str | None = None  # ISO 8601
    job_completion_timestamp: str | None = None  # ISO 8601
    kie_job_ids: list[str] = field(default_factory=list)
    vision_check_result: VisionCheckResult = VisionCheckResult.NOT_CHECKED  # --- quality/skip ---
    status: AssetStatus = AssetStatus.PENDING
    skip_reason: str | None = None  # also appears as a DegradationTag
    slide_count: int | None = None  # --- format-specific: carousel slides delivered ---
    missing_slide_numbers: list[int] = field(default_factory=list)  # 1-indexed; marks `incomplete`
    reel_audio: bool | None = None
    reel_video_reference_url: str | None = None
    postiz_draft_id: str | None = None  # --- posting (Phase 2; inert in MVP, schema stays fixed) ---
    postiz_post_id: str | None = None
    postiz_state: str | None = None
    postiz_media_ids: list[str] = field(default_factory=list)
    event_id: str | None = None  # --- logging & audit: pointer into events.jsonl ---
    virlo_url: str | None = None


@dataclass(slots=True)
class ParsedResult:
    """Return of `llm.structured_call()`; usage feeds the FR-106c reconcile step."""

    parsed: Any  # object validated against the CALLER's json_schema — schema-agnostic
    raw_text: str  # exactly what came back, logged to events.jsonl
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0  # Luna bills these on top of output (20 §7, FR-107)
    cost_usd: float = 0.0
    retried: bool = False  # the single FR-41 content retry was spent
    tolerant_parsed: bool = False  # strict parse failed; FR-126 local parse rescued it
    truncated: bool = False  # finish/stop reason said token limit (FR-127)
    degraded: bool = False  # caller must fall back (copy_degraded, or fail open at the filter)
    # WHY this exists next to `raw_text`: on a truncated call `raw_text` is a slab of unfinished
    # JSON, so an operator warning built from it cannot tell "the model was cut off" apart from
    # "the model returned garbage". `reason` is the short, operator-facing cause and is set on
    # EVERY degrade path in llm.py; `raw_text` keeps carrying the body for events.jsonl.
    reason: str = ""


class StructuredCall(Protocol):
    """PINNED SIGNATURE — `llm.structured_call()` (FR-39–41, 125–129, 248).

        async def structured_call(role, messages, json_schema, images=None) -> ParsedResult

    Schema-agnostic by contract: `role` picks model/temperature/token limits from config and
    `json_schema` is whatever the CALLER needs — later schema needs go in callers, never here.
    Behind the seam: strict schema mode, tolerant parse before the one retry, truncation retry
    with a changed request, run-scoped 402. `images` are already-downloaded local bytes sent
    base64 (FR-40). The `max_inflight_llm_calls` semaphore lives in llm.py, NOT here.
    """

    async def __call__(
        self,
        role: str,
        messages: list[dict[str, Any]],
        json_schema: dict[str, Any],
        images: list[bytes] | None = None,
    ) -> ParsedResult: ...


class RenderPriority(IntEnum):
    """Tier for the render permit gate; higher value is served first.

    **2-tier priority permit gate spec (FR-25 permit-granularity rule).** A permit is acquired
    INSIDE submit-and-poll, per submitted job, released the moment that job is terminal. No task
    may hold a permit while awaiting a dependency — one coroutine per creative holding a permit
    across its anchor await deadlocks at `max_inflight_render_jobs` carousels. A plain FIFO
    `asyncio.Semaphore` is INSUFFICIENT: pre-committed wave-2 work (slides 2–N, Seedance clips,
    FR-106b) queued behind a burst of wave-1 acquisitions is starved, and half-built decks are
    exactly what FR-106b forbids. So the allocator hands every released permit to a waiting
    WAVE2 acquirer before ANY queued WAVE1 acquirer, FIFO within each tier; priority applies to
    the QUEUE, never preempting a held permit. Named starvation test = W4 barrier item.
    """

    WAVE1 = 1  # standalone images, carousel anchor slide 1, reel seed frames
    WAVE2 = 2  # carousel slides 2–N, Seedance clips — pre-committed, must not be starved


class RenderOutcomeKind(str, Enum):
    """FR-242's three outcomes. Success-with-unusable-result folds into FAIL with a sub-cause,
    never laundered into a success."""

    SUCCESS = "success"
    FAIL = "fail"
    STUCK = "stuck"  # no terminal state within the per-job timeout; never resubmitted (20 §8)


class RenderFailCause(str, Enum):
    """Sub-cause carried out of the seam so callers never re-derive it from provider JSON."""

    PROVIDER_FAIL = "provider_fail"  # state: fail, transient/unclassified
    MODERATION = "moderation"  # policy refusal — own class, drives FR-97's single retry
    CONTENT_AUDIT = "content_audit"  # content-security/copyright audit fail (RESULTS.md §C) —
    #   distinct remedy from MODERATION: silence the clip, don't strip references (W4 degrade path)
    EMPTY_RESULT_URLS = "empty_result_urls"  # FR-242
    RESULT_URL_UNREACHABLE = "result_url_unreachable"  # FR-242 (404, dead host, wrong content)
    TIMEOUT = "timeout"  # per-job timeout exceeded (pairs with STUCK)
    CREDITS_EXHAUSTED = "credits_exhausted"  # HTTP 402 — whole-run condition (FR-167)


@dataclass(slots=True)
class RenderParams:
    """The engine's standard render inputs; the PROFILE renames them per provider (FR-272), so
    no caller ever speaks a provider field name."""

    prompt: str  # fully assembled; an unresolved placeholder never reaches here (FR-260)
    aspect_ratio: str  # API parameter, never prompt text (FR-94 clause 4)
    resolution: str | None = None  # 1K/2K/4K images, 480p/720p reels (NFR-13)
    duration_s: int | None = None  # reels 4–30, clamped at pre-flight (FR-103/164)
    generate_audio: bool | None = None  # reels, from `reel_audio` (FR-141/165)
    output_format: str | None = None  # e.g. "mp4"
    moderation_enabled: bool | None = None  # provider knob, forwarded uninterpreted (FR-166)


@dataclass(slots=True)
class RenderRefs:
    """Reference media as PUBLIC URLs only (base64 is an OpenRouter-vision convention, FR-40);
    local bytes arrive here only after the upload seam op (FR-200/244). The profile's declared
    limits cap these lists — excess is dropped and logged, never sent. Order matters: a chained
    artifact (carousel anchor, reel seed frame) is PRIMARY and leads `image_urls` (FR-95/24).
    """

    image_urls: list[str] = field(default_factory=list)
    video_urls: list[str] = field(default_factory=list)  # Seedance motion reference (FR-142)


@dataclass(slots=True)
class RenderOutcome:
    """One terminal render result, classified by the seam (FR-242/271)."""

    kind: RenderOutcomeKind
    task_id: str | None = None  # provider job id; the ledger's terminal field (FR-203)
    request_token: str | None = None  # client-generated, written BEFORE createTask (FR-203)
    result_urls: list[str] = field(default_factory=list)  # empty unless kind is SUCCESS
    fail_cause: RenderFailCause | None = None
    fail_message: str = ""  # provider reason carried through intact, safe to log
    cost_usd: float = 0.0  # tallied on submission — failures included (FR-106)
    submitted_at: str | None = None  # ISO 8601, for meta.yaml
    completed_at: str | None = None  # ISO 8601, for meta.yaml
    elapsed_s: float = 0.0  # measured on the MONOTONIC clock (FR-243), never wall-clock


class RenderRun(Protocol):
    """PINNED SIGNATURE — `render.run()` (20 §12 D34, plan §1 render/).

        async def run(profile, params, refs, priority) -> RenderOutcome

    ONE deep call: submit -> poll -> classify -> result URLs, permit acquired inside it (see
    RenderPriority). The four-op provider protocol, Kie's field names, five poll states and
    status codes stay BEHIND this seam. An unknown `profile` is a pre-flight refusal (exit 2,
    FR-272), never a runtime surprise; a timed-out job is a failed job, never resubmitted.
    """

    async def __call__(
        self,
        profile: str,
        params: RenderParams,
        refs: RenderRefs,
        priority: RenderPriority,
    ) -> RenderOutcome: ...


@dataclass(slots=True)
class Brief:
    """A campaign brief: a small named file, or a folder when it ships its own images (FR-172)."""

    name: str  # folder/file name, and the value `--brief <name>:<count>` takes
    description: str  # one line, shown wherever briefs are listed
    influence: InfluenceMode  # override = consumes no trend (FR-144); blend = trend wins visuals
    formats: list[CreativeFormat] = field(default_factory=list)
    copy_directives: dict[str, str] = field(default_factory=dict)  # message, cta, structure
    visual_directives: dict[str, str] = field(default_factory=dict)  # replace render_prompt on
    reference_image_paths: list[Path] = field(default_factory=list)  # uploaded per FR-200


class BriefLoader(Protocol):
    """PINNED SIGNATURE — `briefs.load()`, implemented in W5.

        def load(name: str, briefs_dir: Path) -> Brief

    Resolves from `briefs_dir` ONLY (no cross-folder collision rules). Missing or malformed
    raises naming the exact file — a pre-flight error before any billable call, dropping only
    that brief's creatives under `--yes` (FR-172/252).
    """

    def __call__(self, name: str, briefs_dir: Path) -> Brief: ...


#: FR-181 two-level template layout, level 1: the three GLOBAL role templates sit FLAT in
#: `prompts/`. They belong to the OpenRouter roles, not to any render profile, and exist once.
GLOBAL_TEMPLATES: tuple[str, ...] = (
    # Post-pivot trio (W3.5, contracts item 4) — the copywriter, the vision check and the
    # FR-294 topic filter — plus D46's slide-intelligence question (FR-306, v2.1.0), which is
    # global for the same reason the vision check is: it belongs to the analysis role, not to
    # any render profile, and must read identically for every post it is asked about.
    "copywriter_system.md", "vision_check_question.md", "topic_filter_system.md",
    "slide_intel_question.md",
)

#: Level 2: per-profile render sets under `prompts/<profile>/` (FR-181/262). A new profile ships
#: its own complete set in its own subfolder; shipped profiles have built-in defaults (FR-183),
#: a new profile's set is validated at pre-flight instead (FR-263).
PROFILE_TEMPLATES: dict[str, tuple[str, ...]] = {
    "gpt-image-2": (
        # Post-W3.5 set: the merged `image_post.md` (F16) is the ONE image role — the two files
        # it merged left every surface with the excision.
        "image_post.md", "carousel_slide.md", "carousel_anchor_instruction.md",
        "reel_seed_frame.md",
    ),
    "seedance-2-5": ("reel_director.md",),
}

#: FR-182 placeholder vocabulary — plain `{{name}}` substitution: no expressions, conditionals
#: or loops. Assembly fills these from the style brief, the copy output and an allowlisted,
#: secret-free context object (FR-261); anything unresolved fails the creative BEFORE submission
#: (FR-260). Names are from 50 §2 (render scaffolds) and 50 §5 (the two LLM system templates),
#: plus the slots the pipeline's own FRs require: niche descriptor (FR-147), brief directives
#: (FR-144/145) and the deterministic direct-mode content sentence (FR-96).
PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "render_prompt", "layout_zones", "onimage_text", "exclusions", "style_dna",
        "slide_index", "seed_frame_ref", "audio_cue",  # render scaffolds
        "sibling_list", "source_hooks", "platform_conventions",
        "brand_context",  # copywriter_system.md — `source_hooks` is the §1.7 candidate table,
        #   OVERWRITTEN by copywrite after build_context returns (W2 addendum item 4)
        "trend_texts",
        "niche_descriptor", "brief_directives", "content_sentence",  # pipeline-required slots
        # W1 barrier review additions (2026-08-09):
        "text_budgets",  # in-force on-image text budgets line (FR-101/105/188) — config-sourced,
        #   re-computed on the −40% vision-check retry; templates never hardcode the numbers
        "through_line",  # CopySet.through_line → reel_director.md (FR-13/23); content_sentence
        #   stays reserved for FR-96's deterministic direct-mode/reference-free sentence
        "reference_roles",  # one engine-emitted line per attached reference: index · source kind ·
        #   contribution · exclusions (FR-191/91) — carries the RESULTS.md §B wordmark defense
        # A15 steering fix (2026-08-11):
        # D46 (v2.1.0) slideshow-fidelity slots — carousel_slide.md only (FR-304/FR-308):
        "visual_brief",  # the slide's English content directive from slide intelligence (FR-306):
        #   WHAT the source slide shows (chart, icon grid, numbered list), rendered in OUR style —
        #   never a style command, never competitor marks (§0.12). Empty when vision degraded.
        "slide_panel_source",  # the FR-304 position line — "source panel i of N" — so the model
        #   knows this slide mirrors one specific slide of the source deck, not a free layout.
        "niche_visual_world",  # `niche.visual_world` ALONE — the operator's standing art direction
        #   in the only shape a render prompt may carry it. Deliberately NOT `niche_descriptor`,
        #   which also carries `audience`: copy-side context must not leak into a render prompt,
        #   and the per-role allowlist exists to enforce exactly that (FR-261/109). Allowlisted for
        #   the four gpt-image-2 roles, so `direct` mode finally sees the art direction too.
        # Topic-first pivot (v2.0.0, contracts item 2 — final 25-name vocabulary; the six
        # pre-pivot orphans left with the W3.5 excision):
        "branding_block",  # FR-292's second channel: accent colours, font letterforms, placement
        #   hint and the profile's `never:` lines, pre-rendered by prompts_engine._branding_block();
        #   empty when unbranded. The wordmark NEVER travels here — it is a TEXT-block entry (B1).
        "topic_items",  # FR-294: the engine-numbered topic blocks for the filter call — ordinals
        #   1..N assigned by _topic_items(), never raw topic_key (a crafted name must not spoof
        #   another topic's verdict). Allowlisted for topic_filter_system.md ALONE.
        "competitor_list",  # FR-294: branding.competitors for the same call, same single role.
        "motion_profile",  # F24: the registry's photographic|graphic switch — selects the reel
        #   director's LOOK/CAMERA paragraph. reel_director.md only.
        "motion_beat",  # F24: CopySelection.motion_beat — ONE named physical action for the
        #   reel's Stage 2. reel_director.md only; free text that never becomes pixels.
    }
)
