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
    REFERENCE_FREE = "reference_free"  # FR-18
    REFS_DROPPED_MODERATION = "refs_dropped_moderation"  # FR-97
    TEXT_TRIMMED = "text_trimmed"  # FR-101
    INCOMPLETE = "incomplete"  # partial carousel, FR-20/95
    SKIPPED_BUDGET = "skipped_budget"  # FR-106
    ABANDONED = "abandoned"  # FR-108 deadline / FR-201 interrupt
    SEED_FRAME_RENDER_FAILED = "seed_frame_render_failed"  # FR-24
    SEED_FRAME_URL_UNREACHABLE = "seed_frame_url_unreachable"  # FR-24
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
class TrendItem:
    """One normalized trend item, assembled per configured monitor id (20 §3 join rule):
    `get_monitor_analysis` gives theme/confidence/why_it_works/tactics, `get_top_videos` +
    `get_top_slideshows` give media/hooks/panel texts/engagement for that same monitor, and the
    global `get_trends` digest only enriches `cross_monitor_context` — it creates no items.
    """

    history_key: str  # dedupe + trend_history key: agent id, else normalized name slug
    monitor_id: str
    name: str
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
    status: PlanEntryStatus = PlanEntryStatus.PENDING
    skip_reason: str | None = None  # one line, machine-readable cause (FR-74)
    estimated_cost_usd: float = 0.0  # logged with every trim decision (FR-106)


@dataclass(slots=True)
class LayoutZone:
    """One ordered frame region of FR-92's `layout_zones`."""

    position: str  # e.g. "upper third", "left gutter"
    content: str  # headline, subline, focal subject, negative space, badge
    text_treatment: str  # case, weight, relative size, outline/shadow


@dataclass(slots=True)
class StyleBrief:
    """Structured trend analysis, one per selected trend per run (FR-9/11/12/92). Forensic
    description only, vague adjectives banned (FR-10). The FULL brief is logged; only
    `render_prompt` and `layout_zones` are ever injected into a render prompt (FR-94).
    """

    trend_key: str
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
    }
)
