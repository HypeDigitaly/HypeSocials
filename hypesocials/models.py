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
Variant = Literal["analyzed", "direct"]  # 10 FR-22 — no other variant tokens exist
GenerationMode = Literal["analyzed", "direct", "both"]  # 10 FR-3
InfluenceMode = Literal["override", "blend"]  # 10 FR-144/145, D26
Platform = str  # platform names are config keys (30 §2), never hardcoded


class DegradationTag(str, Enum):
    """FR-73's `degradations` vocabulary — SINGLE source for meta.yaml and gallery badges.
    Clean asset = empty list; each tag's behaviour is owned by the FR that emits it, this enum
    owns only the spelling, so a new tag needs no schema change (the gallery loops over them).
    """

    ANALYSIS_MISSING = "analysis_missing"  # FR-12
    COPY_DEGRADED = "copy_degraded"  # FR-99 (Notion absence is a warning, never a tag)
    # A20 (2026-08-11, operator's "no plagiarism" mandate). COPY_DEGRADED says the copy call
    # produced nothing usable; this says what the engine did about it — shipped the creative with
    # NO on-image words at all. The two travel together on today's only fallback path and are
    # still two facts: the first is an LLM outcome the run summary counts (FR-248's `llm_starved`
    # set), the second is what the operator will actually see in the frame. Before A20 the answer
    # to the second was "the competitor's headline, rendered verbatim", which is why it needed
    # saying out loud rather than being folded into `copy_degraded`.
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
    # A21 — `hook_pattern_used` came back generic twice (the value the copywriter template itself
    # calls a failed answer). Never fails the creative; it marks the audit trail as weak so a
    # reviewer knows the pattern line on this card was not earned.
    HOOK_PATTERN_GENERIC = "hook_pattern_generic"
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
    PROBE_FAILED = "probe_failed"  # video-ref chain, FR-142 / 20 FR-160
    NO_QUALIFYING_VIDEO = "no_qualifying_video"
    DOWNLOAD_FAILED = "download_failed"
    UPLOAD_FAILED = "upload_failed"
    MALFORMED_METADATA = "malformed_metadata"


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
class ReferenceSet:
    """ONE coherent reference set and every field derived from it — chosen as a single unit.

    A candidate is all panels of one slideshow, or one creator's video thumbnails (FR-91 forbids
    mixing sources inside a job's reference set). Its urls, the posts they came from and the panel
    metadata the style brief and copy read are ONE decision, so no caller ever aligns a url list
    against an id list by hand — that invariant reappearing means the sets have desynchronised.
    `post_ids` is what FR-7's post-level window is checked against and what history records once
    the set was actually attached; `author` is the handle the reel's motion reference prefers, so a
    slideshow's copy is not animated by a stranger's clip.
    """

    urls: list[str] = field(default_factory=list)  # CDN image urls, in panel order
    post_ids: tuple[str, ...] = ()  # stable Virlo ids of the posts these urls came from
    is_slideshow: bool = False  # drives format affinity (FR-90) for the item that picks this set
    panel_texts: list[str] = field(default_factory=list)  # per-slide word-count rhythm (FR-13)
    narrative_arc: str = ""
    text_density: str = ""
    source_url: str | None = None  # this set's own Virlo permalink
    author: str | None = None  # creator handle, for motion-reference coherence


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
    panel_texts: list[str] = field(default_factory=list)  # per-slide words, in panel order
    description: str = ""
    views: int = 0
    # FR-297b's roster prints an age column and a type tag per post, and neither is derivable from
    # the fields above. `is_slideshow` additionally re-derives `TrendItem.is_slideshow` as the
    # majority over the topic's posts (§1.6), so format affinity stops being a per-monitor guess.
    published_at: datetime | None = None
    is_slideshow: bool = False


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
    # gallery receipt all read; the flat `hook_texts`/`panel_texts` lists further down are the
    # pre-pivot, post-less shape and die at W3.5.
    posts: list[SourcePost] = field(default_factory=list)
    source: str = "virlo"  # adapter id (20 FR-121)
    strength: float = 0.0  # 0–1, computed by the adapter — the one cross-source contract (FR-5)
    strength_components: dict[str, float] = field(default_factory=dict)  # logged verbatim (FR-5)
    text_only: bool = False  # item-level: no usable image (FR-6; last resort per FR-90)
    is_slideshow: bool = False  # drives format affinity (FR-90)
    confidence: float | None = None
    why_it_works: str = ""
    tactics: list[str] = field(default_factory=list)
    hook_texts: list[str] = field(default_factory=list)  # few-shot exemplars for FR-100
    text_overlay_contents: list[str] = field(default_factory=list)
    panel_texts: list[str] = field(default_factory=list)  # per-slide word-count rhythm (FR-13)
    narrative_arc: str = ""
    text_density: str = ""
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
    # Each group is ONE coherent source (all panels of a single slideshow, or one creator's
    # thumbnails). FR-91 forbids mixing groups inside a job's reference set; panels lead.
    reference_groups: list[list[str]] = field(default_factory=list)  # CDN URLs
    winning_video_url: str | None = None  # yt-dlp motion-reference candidate (FR-142)
    virlo_url: str | None = None
    total_views: int = 0
    median_views: int = 0
    newest_published_at: datetime | None = None  # velocity/momentum input (FR-5)
    engagement: dict[str, int] = field(default_factory=dict)  # likes/shares/comments/bookmarks
    cross_monitor_context: str = ""  # digest timing analysis + connecting threads (20 §3)
    # FR-7 at post granularity: the posts the CHOSEN `ReferenceSet` came from, so freshness is
    # already enforced when this is non-empty. Empty on a `text_only` item — it has no post
    # identity at all — and then the monitor-level window applies exactly as before.
    chosen_post_ids: tuple[str, ...] = ()
    winning_video_post_id: str | None = None  # the motion reference's own post id, for history


@dataclass(slots=True)
class PlanEntry:
    """One planned creative — the unit of accounting (FR-4) and of trimming. Trimming removes
    entries from the END in reverse plan order (FR-106), so expansion emits brief entries FIRST;
    `atomic_group` makes that one rule sufficient — entries sharing a group trim together and
    never split (a both-mode A/B pair, FR-3/22, and a carousel's slides are each one unit, D31).
    """

    order: int  # 0-based plan position; trim order is descending
    asset_id: str  # stable id and asset folder name incl. ordinal (40 FR-73)
    creative_format: CreativeFormat
    platform: Platform
    language: str
    aspect_ratio: str  # from platform+format (FR-21); an API param, never prompt text
    variant: Variant = "direct"
    pair_id: str | None = None  # shared by the analyzed/direct siblings of one creative (FR-3/22)
    atomic_group: str = ""  # trim unit; defaults to the entry's own id when it stands alone
    slide_count: int | None = None  # carousels; config ceiling = estimate basis (FR-95)
    brief_name: str | None = None  # campaign brief (FR-143)
    brief_influence: InfluenceMode | None = None  # per-entry mode override (D26)
    trend_key: str | None = None  # assigned trend's history_key; None for override briefs (FR-144)
    # FR-91's rotation index: this creative's 0-based position among the creatives sharing its
    # trend, set by `plan.assign` from the `use_index` it already counts. It selects the reference
    # group (`reference_groups[i % len]`) AND the style brief, because FR-9/FR-12 analyse one
    # (trend, reference group) pair — a creative steered by a brief describing pictures it is not
    # attaching is the defect this index exists to prevent. Every member of an atomic group shares
    # one value: a both-mode A/B pair must compare like with like, and a carousel's slides must
    # come from one coherent set. 0 for override briefs, which attach no trend group at all.
    trend_reuse_index: int = 0
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

    Replaces the per-trend `StyleBrief` as the source of a creative's look: styles are authored
    once in `prompts/styles.yaml` (FR-290, loaded through the FR-174 `prompts_dir` seam) and
    ASSIGNED to entries by a deterministic order-indexed rotation (FR-291), instead of being
    re-derived by an LLM from whatever pictures a trend happened to carry. That is why there is no
    built-in fallback tier — an unusable registry is a pre-flight exit 2 (FR-295), not a degrade.

    `render_prompt` is the executable instruction (a variant left unresolved here reaches the image
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
    # Free prose under `carousel_cover` / `carousel_slide` (M9's variant-resolution home), plus the
    # one marker key `carousel_role` with value "cover_only" or "slides_only": a slides-only style
    # can never anchor a deck, and under anchor-chaining that means it never takes a carousel entry
    # at all. `styles.fmt_affine` owns that reading — no caller re-implements it.
    per_format_guidance: dict[str, str] = field(default_factory=dict)
    exclusions: list[str] = field(default_factory=list)  # LITERAL strings from the refs (M8)
    reference_images: list[str] = field(default_factory=list)  # REPO-ROOT-relative paths (§1.3)


@dataclass(slots=True)
class StyleBrief:
    """Structured trend analysis, one per selected trend per run (FR-9/11/12/92). Forensic
    description only, vague adjectives banned (FR-10). The FULL brief is logged; only
    `render_prompt` and `layout_zones` are ever injected into a render prompt (FR-94).
    """

    trend_key: str
    # Which of the trend's reference groups this brief actually looked at (FR-9/FR-12, amended
    # 2026-08-11). The brief is keyed by the (trend, group) PAIR, not by the trend alone; this
    # field keeps the group visible on the object itself so a logged brief can be matched to the
    # pictures it describes without reconstructing the dictionary key.
    reference_group_index: int = 0
    layout_zones: list[LayoutZone] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)  # UI chrome, watermarks, counters
    render_prompt: str = ""  # compact <=120 words, alone fit to send to the image model
    palette: list[str] = field(default_factory=list)  # approximate values
    typography: str = ""
    text_placement: str = ""  # placement zones + density
    image_treatment: str = ""  # photo vs graphic vs screenshot, filters, borders, crops
    visual_pacing: str = ""
    hook_pattern: str = ""
    content_angle: str = ""
    per_format_guidance: dict[str, str] = field(default_factory=dict)  # image/carousel/reel
    raw: dict[str, Any] = field(default_factory=dict)  # exactly what the model returned, logged


@dataclass(slots=True)
class CopySelection:
    """The copy call's per-creative answer under the §1.7 verbatim contract: references into the
    engine-numbered candidate list where the text becomes pixels or caption, free text only where
    nothing does. Feeds `json_schema_for(CopySelection, exclude={"asset_id"})`.

    The split from `CopySet` is the whole point of FR-99/100: the model CHOOSES (a label), the
    engine RESOLVES (the bytes). A model that answers with prose can drift, translate or invent;
    a model that answers with `P1.hook.2` cannot, and the resolution step can never fail the
    verbatim check because it copies from the source it is checked against. Ref-label grammar:
    `P<n>.<kind>[.<i>]` — `n` = 1-based post ordinal in the topic's view-ranked `posts`, `kind` ∈
    {hook, overlay, panel, caption, description}, `i` = 1-based index into that post's list field
    (`caption`/`description` are scalars and carry none). E.g. `P1.hook.2`, `P3.panel.1`.
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
    hook_pattern_used: str = ""  # FR-100/146 — string, auditable, logged and written to meta


@dataclass(slots=True)
class AssetRecord:
    """Mirrors meta.yaml field for field (FR-73); written `pending` at folder creation and
    rewritten to terminal status by temp+rename (NFR-21)."""

    asset_id: str  # --- identity & sourcing ---
    source: str  # trend key, or "brief/<name>"
    source_name: str
    platform: Platform
    creative_format: CreativeFormat
    variant: Variant = "direct"
    pair_id: str | None = None
    generation_mode: Variant = "direct"  # --- provenance & degradations ---
    hook_pattern_used: str = ""
    source_hook: str = ""  # the trend's original hook line, verbatim — gallery card (FR-76, v1.6.4)
    # A24 — what the style brief ASKED FOR, in one line: pattern · angle · palette. The full
    # `StyleBrief` is logged to events.jsonl under `verbose_only` and nowhere else, so an operator
    # judging a finished creative could not see the instruction it was judged against without
    # opening a JSONL file with verbose logging already switched on. Empty in direct mode and
    # after FR-12's degrade, which is itself the answer: there was no brief.
    style_brief_summary: str = ""
    ref_source: str = ""  # "virlo" | "brief" | "inspiration"
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
    degraded: bool = False  # caller must fall back (analysis_missing / copy_degraded)
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
    "style_brief_system.md", "copywriter_system.md", "vision_check_question.md",
)

#: Level 2: per-profile render sets under `prompts/<profile>/` (FR-181/262). A new profile ships
#: its own complete set in its own subfolder; shipped profiles have built-in defaults (FR-183),
#: a new profile's set is validated at pre-flight instead (FR-263).
PROFILE_TEMPLATES: dict[str, tuple[str, ...]] = {
    "gpt-image-2": (
        "image_single_post.md", "carousel_slide.md", "carousel_anchor_instruction.md",
        "image_direct.md", "reel_seed_frame.md",
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
        "sibling_list", "source_hooks", "style_brief_summary", "platform_conventions",
        "brand_context",  # copywriter_system.md
        "reference_image_count", "trend_texts", "engagement_numbers", "output_format",
        "niche_descriptor", "brief_directives", "content_sentence",  # pipeline-required slots
        # W1 barrier review additions (2026-08-09):
        "text_budgets",  # in-force on-image text budgets line (FR-101/105/188) — config-sourced,
        #   re-computed on the −40% vision-check retry; templates never hardcode the numbers
        "through_line",  # CopySet.through_line → reel_director.md (FR-13/23); content_sentence
        #   stays reserved for FR-96's deterministic direct-mode/reference-free sentence
        "reference_roles",  # one engine-emitted line per attached reference: index · source kind ·
        #   contribution · exclusions (FR-191/91) — carries the RESULTS.md §B wordmark defense
        # W2 barrier operator decision (v1.6.4, 2026-08-09):
        "brand_accent",  # FR-109's ONLY brand slot in render templates: one engine-built line of
        #   accent colour + product nouns under Notion `full` influence — never fonts/layouts;
        #   empty when influence is off. Dedicated so render-side allowlists stay narrow.
        # A15 steering fix (2026-08-11):
        # A16 wire-in (2026-08-11):
        "inspiration_exemplars",  # the `.txt` files paired with the configured Inspiration images
        #   (`01.jpg` + `01.txt`) — whole posts a human wrote and an audience rewarded, pooled on
        #   `InspirationPool.exemplar_texts`. FORM material for the COPY call and for nothing else:
        #   allowlisted for `copywriter_system.md` alone, because an Inspiration image already
        #   reaches a render under an explicit "no words" role line and handing an image model
        #   proven copy is how that copy ends up baked into pixels. The same two-step discipline
        #   A20 exists to protect — a pattern to abstract, never a string to reuse.
        "niche_visual_world",  # `niche.visual_world` ALONE — the operator's standing art direction
        #   in the only shape a render prompt may carry it. Deliberately NOT `niche_descriptor`,
        #   which also carries `audience`: copy-side context must not leak into a render prompt,
        #   and the per-role allowlist exists to enforce exactly that (FR-261/109). Allowlisted for
        #   the four gpt-image-2 roles, so `direct` mode finally sees the art direction too.
    }
)
