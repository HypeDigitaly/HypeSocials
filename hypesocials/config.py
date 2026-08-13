"""Config loading — the one door between `configs/*.yaml` and every other module.

Public API: `load_config(name) -> Config`, `list_configs()`, `Config`, `ConfigError`.
30-configuration-and-run.md §2 owns every key name and default; the dataclasses below ARE that
schema, so a new key is one annotated field plus a line in the shipped YAML.

Invariants: absent keys default and land in `defaults_applied` for the run log, never erroring
(FR-50, NFR-19); a malformed value raises ONE plain-English line — file, key, value, expected
shape (FR-51/69); unknown keys warn; a `${VAR}` placeholder is a hard error, because config
loading has no interpolation and that absence is what makes a config file secret-free (D30,
FR-130/177); `max_tokens` under its floor is clamped up with a warning (NFR-111). Two CROSS-KEY
pairs are refused rather than clamped, each naming both keys and both values: the no-repeat history
window against the fetch window (FR-307) and the image/reel counts against slideshow-only sourcing
(D46 §0.14e) — see `_validate_windows` and `_validate_formats_sourcing`.

Do not: read env vars or `.env` here (config names variables, never values); clamp
`reel_duration_s` here (pre-flight owns that, FR-103/138); import project modules besides `util`.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import UnionType
from typing import Any, Literal, NoReturn, Union, get_args, get_origin, get_type_hints

import yaml

from .util import read_text

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = ROOT / "configs"
#: Run-log folder (`trend_history.json`). ONE definition, and it lives here rather than beside its
#: readers because `preflight` needs it and cannot import `runner` — `runner` imports `preflight`.
LOGS_DIR = ROOT / "logs"
DEFAULT_CONFIG_NAME = "default"

_INTERPOLATION = re.compile(r"\$\{")
#: FR-292: a brand profile's colours are quoted into render prompts verbatim, so a typo'd hex is a
#: wrong colour in a paid render rather than a load error — unless it is caught here.
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_SOURCES = ("virlo", "google_trends", "hacker_news")  # last two: named in the picker, not built
_FORMATS = ("image", "carousel", "reel")
_LANGUAGES = ("en", "cs")  # D6
#: D6's fixed platform set. PUBLIC because `--platforms` must refuse the same vocabulary at the
#: flag boundary (cli.py) — one list, two doors; a typo'd platform silently plans nothing for
#: itself and still spends on its siblings (FR-51/69/137).
PLATFORMS = ("linkedin", "instagram", "tiktok")
_REEL_PLATFORMS = ("tiktok",)  # 30 §2: reel is allowlisted on TikTok only by default
#: `Config` fields that come from the filesystem, not from YAML — writing them in a file is as
#: meaningless as any other unknown key.
_META = frozenset({"name", "path", "description", "defaults_applied", "warnings"})
#: `Config` fields with their own builder (per-platform defaults; the timeout/server split).
_HANDLED = frozenset({"platforms", "mcp_servers"})


class ConfigError(Exception):
    """One malformed value or unusable config file. `str(e)` is the whole operator-facing line."""


# --------------------------------------------------------------------------- schema


@dataclass(slots=True)
class TextBudgets:
    """On-image character ceilings, enforced before submission — not prompt hints (FR-101/259).

    Raised across the board at v2.1.0 (D46 §0.5, FR-259). The pre-pivot numbers were sized for text
    the copy model WROTE and could be asked to write shorter; D46 makes every on-image string a
    verbatim quote of a source panel, hook or overlay, which nobody may retype or trim (FR-304). A
    ceiling under a real panel's length therefore does not shorten anything — it makes the string
    unofferable, and the creative ships with no on-image text at all, which is exactly what the
    first paid run did on six of eight creatives. A style's own `max_onimage_chars` may still only
    LOWER these global ceilings, never raise them (FR-259), so the raise becomes fully effective
    only once the registry's per-style caps are re-authored to match.
    """

    image_headline: int = 90  # v2.1.0: was 42
    image_subline: int = 160  # v2.1.0: was 60
    #: Per-slide deck text under panel-mapped carousels (FR-304) — a source panel carries a whole
    #: thought, not a headline, which is why it is four slides' worth of a pre-pivot headline.
    slide: int = 300
    reel_seed_headline: int = 60  # v2.1.0: was 32
    retry_reduction_pct: int = 40  # budgets are cut by this % on a vision-check retry


@dataclass(slots=True)
class RunConfig:
    """`run:` — scope, spend and per-format behaviour."""

    # All-carousels since 2026-08-13 (D46 §0.3, operator decision; was 4/2/0). v1 of the slideshow
    # pivot sources SLIDESHOWS only (`sources.include_videos: false`), so every topic in the pool is
    # slideshow-majority and a carousel is the only format that can quote it panel for panel. Image
    # and reel counts are not forbidden — they are refused *together with* slideshow-only sourcing
    # by `_validate` (§0.14e), so turning them on is one deliberate pair of edits, never a silent
    # rank-fallback onto a post the run was never meant to use.
    formats: dict[str, int] = field(default_factory=lambda: {"image": 0, "carousel": 6, "reel": 0})
    platforms: list[str] = field(default_factory=lambda: ["linkedin", "instagram", "tiktok"])
    languages: dict[str, str] = field(
        default_factory=lambda: {"linkedin": "en", "instagram": "en", "tiktok": "en"})
    notion_influence: Literal["off", "copy", "full"] = "off"
    vision_check: bool = False
    spend_cap_usd: float = 10.00
    # 30 since 2026-08-13 (D46/FR-307, was 7). The window is the no-repeat memory, and post-pivot
    # the fetch reaches back `sources.max_post_age_days` (30) — a 7-day memory over a 30-day fetch
    # window means a post quoted three weeks ago is fetched again, forgotten, and quoted again. The
    # two keys are therefore tied by the FR-307 invariant checked in `_validate`. `0` disables the
    # window entirely and is the operator's explicit opt-out, so it is exempt from that invariant.
    trend_history_days: int = 30
    # 6 since 2026-08-11 (was 2). D36 moved recency to the POST, so reuse stopped being a
    # throughput ceiling, and FR-91's per-reuse rotation gives each of the 6 a different one of
    # the trend's downloaded reference groups plus its own style brief (FR-9/FR-12). A config
    # that does not set the key falls back to HERE, so this is the value the shipped niche
    # configs actually run at — `configs/default.yaml` alone would not have changed them.
    max_trend_reuses_per_run: int = 6
    carousel_anchor: bool = True
    reel_overlay_text: Literal["seed_frame", "in_model", "none"] = "seed_frame"
    reel_audio: bool = True
    reel_duration_s: int = 5  # 4–30; out of range is CLAMPED at pre-flight, never rejected here
    reel_resolution: Literal["480p", "720p"] = "720p"
    nsfw_checker: bool = True  # provider knob, always sent (its own default is false)
    onimage_text_language: dict[str, str] = field(default_factory=dict)
    text_budgets: TextBudgets = field(default_factory=TextBudgets)
    # Soft ceiling, monotonic clock (FR-108/243). DEPENDS ON models.video_job_timeout_s: a reel
    # reaches its own timeout only while this exceeds it plus the analyze/copy/image stages. 25
    # stands because the default ships reels OFF; reel-capable configs use 45 and `_validate` warns.
    run_deadline_min: int = 25


@dataclass(slots=True)
class SourcesConfig:
    """`sources:` — which adapters feed the run and how much media they may pull."""

    active: list[str] = field(default_factory=lambda: ["virlo"])
    virlo_monitor_ids: list[str] = field(default_factory=list)
    virlo_session_pool: int = 3  # bounded wrapper sessions; never one subprocess per monitor
    # FR-293: one monitor's analysis yields several THEMES, and post-pivot each theme becomes its
    # own topic with its own posts and its own strength. This caps how many a monitor may
    # contribute, so one prolific monitor cannot flood the candidate pool it is ranked in. `-1` is
    # the kill switch — one topic per monitor, i.e. the pre-pivot cardinality; `0` would mean "this
    # monitor contributes nothing", which is a config error, not a setting (`_validate`).
    virlo_topics_per_monitor: int = 9
    # FR-301 (D46 §0.2): `false` makes the fetch gate skip Virlo's video rows entirely and yield
    # SLIDESHOWS only. v1 ships slideshow-first because a slideshow's panels are the thing the
    # engine now reproduces panel for panel (FR-304); a video row carries no panels and would only
    # ever be quoted by its caption. Turning it on is also what unlocks image/reel counts (§0.14e).
    include_videos: bool = False
    # FR-301: how many result pages the fetch pulls per monitor at `created_at desc`. One page is
    # ~100 posts; 3 pages is roughly the last week of a normally active monitor, which is the
    # cadence the run is designed around (FR-307). Out-of-bounds is REFUSED, never clamped — a
    # silently corrected typo hides the operator mistake the refusal exists to surface (FR-285).
    fetch_pages: int = 3
    # FR-301/FR-305: posts older than this are dropped pre-rank as stale, measured on the post's
    # own `publish_date`. This is the fix for the first paid run, which ranked by views over ALL
    # TIME and quoted posts from 2023. `0` disables the staleness cap; the FR-307 invariant ties
    # this key to `run.trend_history_days`, which must cover at least this window.
    max_post_age_days: int = 30
    # FR-306 (D46 §0.11): when true, the post-Confirm slide-intelligence call downloads the
    # assigned carousel source posts' slides and has the analysis model transcribe their on-image
    # text and describe their visuals, so our render prompts reproduce the CONTENT in our own
    # style. `false` falls back to Virlo's own `panel_texts` alone — cheaper, and blind wherever
    # that field is empty (many fresh rows have it empty). Paid LLM spend, so it is estimated
    # before the Confirm gate and never runs ahead of it.
    vision_transcribe: bool = True


@dataclass(slots=True)
class PlatformConfig:
    """One `platforms.<name>` entry; `formats` is the allowlist FR-132 requires."""

    formats: list[str] = field(default_factory=lambda: ["image", "carousel"])
    carousel_slides: int = 5  # FR-257: the ONE slide-count key — deck ceiling AND estimate basis
    aspect_ratios: dict[str, str] = field(default_factory=dict)  # OVERRIDE only; defaults 10 FR-21
    conventions: dict[str, str] = field(default_factory=dict)  # length/tone/hashtag prompt hints


@dataclass(slots=True)
class PriceTable:
    """`models.price_per_unit` — estimator inputs only, never billing-authoritative (D11/FR-258).

    Three shapes because three different units are bought. Prices belong to whichever model was
    configured when they were typed in; a swap never clears or adjusts them (FR-282). `null` means
    *unpriced* and prints as such — it is never treated as free.
    """

    llm: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "sonnet": {"input_per_mtok": 2.00, "output_per_mtok": 10.00},
        "luna": {"input_per_mtok": 0.10, "output_per_mtok": 0.60, "reasoning_per_mtok": 0.60}})
    # THREE tiers per FR-258, measured exactly in spikes/RESULTS.md §B (6/10/16 credits).
    # 30 §2's prose still says two tiers — stale; editorial D15 fix pending (plan §6).
    image: dict[str, float | None] = field(
        default_factory=lambda: {"1k": 0.03, "2k": 0.05, "4k": 0.08})
    # Per OUTPUT second, per resolution. Unset for the run's `reel_resolution` = reels are not
    # planned at all (FR-131) — the one unpriced line that blocks instead of merely reporting.
    reel_second: dict[str, float | None] = field(
        default_factory=lambda: {"480p": None, "720p": None})


@dataclass(slots=True)
class ModelsConfig:
    """`models:` — ids, profiles, sampling knobs, prices, provider timing and concurrency.

    Every id is a plain string (FR-270/280): a same-family swap is that one line and nothing else.
    """

    analysis: str = "anthropic/claude-sonnet-5"
    copy: str = "openai/gpt-5.6-luna"
    # FR-280 (amended v2.1.0): the TEXT-TO-IMAGE route is the default now (was
    # `gpt-image-2-image-to-image`). D46 took the style registry's reference images out of every
    # render job, so the common job carries no reference at all and the reference-bearing sibling
    # is reserved for the jobs that genuinely have one — a brief image, a carousel anchor, a reel
    # seed frame (20 §8c/FR-241). The profile dual-routes either way, so this only decides which
    # route a REFERENCE-FREE job takes; pointing it at the i2i sibling is what made the first paid
    # run clone its Inspiration files ~1:1.
    image: str = "gpt-image-2-text-to-image"
    video: str = "bytedance/seedance-2-5"
    image_profile: str = "gpt-image-2"  # FR-281 — changes only on a model FAMILY change
    video_profile: str = "seedance-2-5"
    reasoning_effort: Literal["low", "medium", "high"] = "low"  # `copy` role only (Luna)
    # DELIBERATELY EMPTY (spikes/RESULTS.md §E): neither shipped model advertises `temperature`,
    # and sending it under `provider.require_parameters` returns HTTP 404. The key survives for a
    # model that does support it; FR-129 as written needs a D15 amendment.
    temperature: dict[str, float] = field(default_factory=dict)
    # `analysis` is the VISION-CHECK role's budget post-pivot (v2.0.0/D41 — the style-brief calls
    # that originally sized it at 12000 are gone; FR-27 keeps the role for the check). The value
    # stays: `reasoning_effort` is None for this role yet OpenRouter still bills 0–3,057 Sonnet-5
    # reasoning tokens INSIDE `completion_tokens`, so even a short verdict needs real headroom.
    max_tokens: dict[str, int] = field(default_factory=lambda: {"analysis": 12000, "copy": 3000})
    # NFR-111 floors: below this a cap buys truncation retries as the normal path rather than
    # saving money, so a smaller value is clamped up and warned about. `copy` sits at a third of
    # its default; `analysis` at half its cap, because the floor has to clear the unbidden
    # reasoning tokens billed inside `completion_tokens`, not merely clear zero.
    max_tokens_floor: dict[str, int] = field(
        default_factory=lambda: {"analysis": 6000, "copy": 1000})
    price_per_unit: PriceTable = field(default_factory=PriceTable)
    image_job_timeout_s: int = 180
    # 1800 (operator decision 2026-08-10, was 600): W6's run 20260809_221816_0316 failed a Seedance
    # reel at the 600 s ceiling and wasted ~$4.78 — a timed-out job is paid and never resubmitted
    # (20 §8). Live renders measured 302 s and 378 s; 1800 s is headroom, not an expected wait.
    video_job_timeout_s: int = 1800
    poll_interval_s: int = 3
    http_max_attempts: int = 3  # EVERY bounded-retry path in the engine (NFR-14)
    max_inflight_llm_calls: int = 8
    max_inflight_render_jobs: int = 8


@dataclass(slots=True)
class McpConfig:
    """`mcp_servers:` — the two timeouts, plus one opaque entry per server (FR-130).

    Entries stay raw mappings because `mcp_client.ServerConfig.from_mapping` owns their shape.
    They carry transport/launch data and env-var NAMES only — never a value, never a placeholder.
    """

    startup_timeout_s: int = 20
    call_timeout_s: int = 30
    servers: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(slots=True)
class GalleryConfig:
    """`title` is the only gallery key (FR-134 withdrawn with A/B mode, v2.0.0)."""

    title: str = "HypeSocials Run"


@dataclass(slots=True)
class OutputConfig:
    """`output:` — consumed by 40-outputs-and-logging.md's writers."""

    dir: str = "output/"
    gallery: GalleryConfig = field(default_factory=GalleryConfig)
    log_verbosity: Literal["normal", "verbose"] = "normal"
    #: FR-299 (D45): the CONSOLE tier only. run.log and events.jsonl are unchanged by this —
    #: `log_verbosity` above governs events.jsonl detail, this key (or `--verbose`) only decides
    #: whether `_Session.note()` lines reach the screen. Sibling by design, never merged.
    console_verbosity: Literal["normal", "verbose"] = "normal"


@dataclass(slots=True)
class NicheConfig:
    """The optional `niche:` descriptor (D27), injected into Analyze and Write (FR-147)."""

    audience: str = ""
    vibe: str = ""
    visual_world: str = ""

    def as_text(self) -> str:
        """One compact line for the `{{niche_descriptor}}` placeholder; empty when unset.

        `brand` is deliberately absent. This text feeds `{{niche_descriptor}}`, which is a COPY-side
        placeholder (the analyst and the copywriter allowlist it, no render role does); the brand
        accent is render-side and travels in the branding block (FR-292). Folding one into the other would
        put brand text into copy prompts and drag the audience line into render prompts — exactly
        the leak the per-role allowlists exist to prevent (FR-261/109).
        """
        labels = (("Audience", self.audience), ("Vibe", self.vibe),
                  ("Visual world", self.visual_world))
        return " · ".join(f"{label}: {value}" for label, value in labels if value)


@dataclass(slots=True)
class BrandProfile:
    """One brand system (FR-292): everything a branded render may know about a brand.

    Compiled defaults ship for both house brands (`_default_profiles`), and a config file
    overrides any of it. Two `never:` lists rather than one, because they have different scopes
    (M6): `never_always` are COLOUR guards — the other brand's hexes, the web-only orange — and go
    into every branded prompt; `never_style` are MEDIUM guards ("no photography", "no serif") and
    go in only when the assigned meta-style is brand-affine. Six of the seven neutral styles are
    legitimately photographic or hand-drawn, so injecting the medium guards everywhere would
    quietly ban most of the registry the moment a creative got a wordmark.
    """

    wordmark: str = ""  # rendered verbatim through the TEXT block only, never composited (B1)
    colors: dict[str, Any] = field(default_factory=dict)  # hexes, and one gradient list
    fonts: dict[str, str] = field(default_factory=dict)
    font_character: str = ""  # what the typeface LOOKS like — a model cannot install a font (F21)
    background_hint: str = ""  # `background_tint` mode only
    never_always: list[str] = field(default_factory=list)  # colour guards — every branded prompt
    never_style: list[str] = field(default_factory=list)  # medium guards — brand-affine styles only
    # Product names the copy and on-image text may use. Doubles as a strip guard: the topic
    # filter must never "remove a competitor brand" that is one of our own product nouns (M15).
    product_nouns: list[str] = field(default_factory=list)


def _default_profiles() -> dict[str, BrandProfile]:
    """The two house brand systems, compiled from the v2 brand artifact (plan §1.4, FR-292).

    Defaults rather than a shipped YAML block because they are facts about the business, not run
    settings: a niche config that says nothing about branding still has to render a correct
    wordmark. Orange `#F97316` is deliberately in NEITHER profile — it is a web-only accent, and
    both profiles name it in `never_always` so a render cannot reintroduce it.
    """
    return {
        "hypedigitaly": BrandProfile(
            wordmark="HypeDigitaly",
            colors={"indigo": "#34288B", "teal": "#00A59A",
                    "gradient": ["#34288B", "#2B3F8E", "#0C8897", "#00A59A"]},
            fonts={"brand": "Montserrat", "web": "Geist"},
            font_character="Montserrat — geometric grotesque, near-circular bowls, medium "
                           "x-height, uniform stroke",
            background_hint="flat royal-indigo field, gradient arrow glyphs sweeping the right "
                            "half, vast negative space",
            never_always=["no teal pill highlights", "no dot-grid ground",
                          "no orange #F97316 (web-only)"],
            never_style=[],
            product_nouns=["AI Audit", "HypeLead", "AI Chatbot", "AI Voicebot", "AI Agent",
                           "AI Automatizace"]),
        "hypelead": BrandProfile(
            wordmark="HypeLead",
            colors={"teal_bright": "#0FCFC4", "teal_mid": "#57E6DC", "teal_deep": "#0A7F78",
                    "teal_light": "#8BF2E9", "dark": "#14130F", "offwhite": "#FAFAF7"},
            fonts={"primary": "Geist", "mono": "Geist Mono"},
            font_character="Geist — clean grotesque, tight tracking, even color",
            # W3 conductor decision (M9 — no unresolved variants anywhere a model might read):
            # the light surface is THE hypelead ground. The artifact's ", or charcoal-green dark
            # mode with teal glow" alternative is a config-file swap, not a compiled default.
            background_hint="off-white ground with faint dot-grid and soft teal bloom",
            never_always=["no indigo or violet", "no orange #F97316"],
            never_style=["no photography/stock/3D", "no serif or handwritten type",
                         "teal is accent only, never full-bleed canvas"],
            product_nouns=["HypeLead"]),
    }


@dataclass(slots=True)
class BrandingConfig:
    """`branding:` — which brand a run signs with, how often, and in what shape (FR-292).

    `brand` is a SELECTOR, never a mix: one run is one brand, and it also filters the style
    rotation (a `hypelead` style cannot be assigned under `hypedigitaly` — B3). `brand_ratio` is
    the fraction of creatives that carry the wordmark, applied as the deterministic floor
    predicate on `entry.order` (FR-291) so the count is `floor(N x ratio)` over the emitted plan
    and a later trim never re-brands a surviving creative.

    `competitors` is the filter's layer-1 blocklist and is deliberately deterministic and
    fail-closed: it applies even when the LLM screen degrades, because "the model was unavailable"
    must never be the reason a competitor's name ships in our pixels (FR-294).
    """

    brand: Literal["hypedigitaly", "hypelead"] = "hypedigitaly"
    brand_ratio: float = 0.5  # 0..1 — fraction of creatives signed with the wordmark
    mode: Literal["background_tint", "overlay", "both"] = "overlay"
    placement: str = "bottom-center"  # wordmark placement hint
    competitors: list[str] = field(default_factory=list)  # deterministic blocklist, fail-closed
    profiles: dict[str, BrandProfile] = field(default_factory=_default_profiles)


@dataclass(slots=True)
class StylesConfig:
    """`styles:` — run-side knobs for the meta-style registry (FR-290); the registry itself is a
    prompt artifact (`prompts/styles.yaml`), never config.

    One key so far: how many of a style's own reference images ride along with each render job.
    The A17 window rotation picks WHICH ones (`styles.pick_reference_window`), so this is only how
    wide that window is — and it is the multiplier on every job's upload and reference budget,
    which is why it is a config key rather than a constant.
    """

    refs_per_job: int = 2


@dataclass(slots=True)
class Config:
    """One fully-resolved run configuration. Built only by `load_config`."""

    name: str = DEFAULT_CONFIG_NAME
    path: Path = field(default_factory=lambda: CONFIGS_DIR / "default.yaml")
    description: str = ""  # resolved picker line: `label`, else niche, else line 1 (FR-56/173)
    label: str = ""  # optional one-line self-description a file writes for the picker (FR-173)
    run: RunConfig = field(default_factory=RunConfig)
    sources: SourcesConfig = field(default_factory=SourcesConfig)
    models: ModelsConfig = field(default_factory=ModelsConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    niche: NicheConfig = field(default_factory=NicheConfig)
    branding: BrandingConfig = field(default_factory=BrandingConfig)  # FR-292
    styles: StylesConfig = field(default_factory=StylesConfig)  # FR-290
    platforms: dict[str, PlatformConfig] = field(default_factory=dict)
    mcp_servers: McpConfig = field(default_factory=McpConfig)
    briefs_dir: str = "briefs"  # D26/D27; a niche config points this at its own folder
    prompts_dir: str | None = None  # D27: checked BEFORE the global prompts/ folder (FR-174)
    # FR-124 — the brand-context block is truncated to these fixed per-context-type budgets; a
    # plain cut, no summarization call. KEY NAME IS THE PLAN §6 D15 ADDITION to 30 §2 (conductor-
    # approved): `notion_char_budgets`, keyed by FR-35's four context types.
    notion_char_budgets: dict[str, int] = field(default_factory=lambda: {
        "brand_voice": 2000, "offers": 1500, "icp": 1500, "topics": 1000})
    notion_pages: dict[str, list[str]] = field(default_factory=lambda: {
        "brand_voice": [], "offers": [], "icp": [], "topics": []})
    # Phase 2 (FR-176): parsed, stored, UNUSED in the MVP. Kept opaque because
    # 60-publishing-postiz.md §6 owns its shape — validating it here would fork that spec.
    postiz: dict[str, Any] = field(default_factory=dict)
    defaults_applied: tuple[str, ...] = ()  # FR-50: goes to run.log, never to the menu
    warnings: tuple[str, ...] = ()  # unknown keys, clamps, advisory range hits

    def platform(self, name: str) -> PlatformConfig:
        """That platform's entry, defaulted if the file never mentioned it (FR-132)."""
        return self.platforms.get(name) or _default_platform(name)

    def language_for(self, platform: str) -> str:
        return self.run.languages.get(platform, "en")

    def onimage_language_for(self, platform: str) -> str:
        """On-image text language, defaulting to that platform's caption language (30 §2)."""
        return self.run.onimage_text_language.get(platform) or self.language_for(platform)

    def max_tokens_for(self, role: str) -> int:
        """The per-role token cap, already floor-clamped at load time (NFR-111)."""
        return self.models.max_tokens.get(role, 2000)

    @property
    def reel_price_key(self) -> str:
        """The exact key an unpriced-reel message must name (FR-131)."""
        return f"models.price_per_unit.reel_second.{self.run.reel_resolution}"

    @property
    def reel_price_per_second(self) -> float | None:
        """The configured resolution's rate; `None` means reels cannot be planned at all."""
        return self.models.price_per_unit.reel_second.get(self.run.reel_resolution)

    @property
    def reels_plannable(self) -> bool:
        """FR-131: reels are planned only once a real per-second rate exists for the resolution."""
        price = self.reel_price_per_second
        return price is not None and price > 0

    @property
    def min_single_creative_usd(self) -> float:
        """The cheapest creative this config could buy — the ONE price floor (30 §8).

        The lowest priced image tier, because every creative renders at least one image. `0.0` =
        no image tier is priced, and the floor stops applying rather than refusing every cap.
        Pre-flight and the wizard's cap step both READ this, so the number the wizard warns with
        is the number that refuses.
        """
        priced = [price for price in self.models.price_per_unit.image.values() if price and price > 0]
        return min(priced) if priced else 0.0


@dataclass(slots=True)
class ConfigSummary:
    """One row of the menu's config picker (FR-56/173).

    `description` is the resolved line (`label:`, else the niche join, else line 1's comment);
    `label` is non-empty only when the file wrote one, so the picker can tell an author's own
    one-liner from a derived string it must truncate. The scalars are the row's readiness facts.
    """

    name: str
    path: Path
    description: str
    label: str = ""
    language: str = "en"  # caption languages in force, joined when one file mixes them
    monitor_count: int = 0  # `len(sources.virlo_monitor_ids)`; 0 means the config cannot run
    formats: dict[str, int] = field(default_factory=lambda: dict(RunConfig().formats))


# --------------------------------------------------------------------------- public API


def load_config(name: str | Path | None = None, *, configs_dir: Path | None = None) -> Config:
    """Load, validate and default one config file — the single entry point of this module.

    Args:
        name: a config name (`hypedigitaly`, `hypedigitaly.yaml`) resolved inside `configs/`, or an
            explicit path. `None` loads `default.yaml`.
        configs_dir: override the config folder (tests).

    Returns:
        A `Config` with every key present, `defaults_applied` naming the keys that fell back and
        `warnings` naming unknown keys, clamps and advisory range hits.

    Raises:
        ConfigError: file missing/unreadable, invalid YAML, not a mapping, a `${VAR}` placeholder,
            or one malformed value — always exactly one operator-facing line.
    """
    path = _resolve_path(name, configs_dir or CONFIGS_DIR)
    try:
        text = read_text(path)
    except OSError as exc:
        raise ConfigError(f"config file {path} could not be read: {exc.strerror}") from exc
    raw = _parse(text, path)
    _reject_interpolation(raw, path.name, "")

    ctx = _Ctx(file=path.name)
    cfg: Config = _build(Config, raw, "", ctx)
    cfg.name, cfg.path, cfg.description = path.stem, path, _describe(text, raw)
    cfg.platforms = _build_platforms(raw.get("platforms"), cfg.run.platforms, ctx)
    cfg.mcp_servers = _build_mcp(raw.get("mcp_servers"), ctx)
    _validate(cfg, ctx)
    cfg.defaults_applied, cfg.warnings = tuple(ctx.defaults), tuple(ctx.warnings)
    return cfg


def list_configs(configs_dir: Path | None = None) -> list[ConfigSummary]:
    """Every `*.yaml` in `configs/` with its picker description (FR-56/173).

    Deliberately does not validate: one broken sibling must never blank the whole picker.
    """
    summaries = []
    for path in sorted((configs_dir or CONFIGS_DIR).glob("*.yaml")):
        try:
            text = read_text(path)
            raw = yaml.safe_load(text)
        except (OSError, yaml.YAMLError):
            summaries.append(ConfigSummary(path.stem, path, ""))
            continue
        summaries.append(_summarize(path, text, raw))
    return summaries


# --------------------------------------------------------------------------- file handling


def _resolve_path(name: str | Path | None, folder: Path) -> Path:
    """Find the requested config, or fail naming what was sought and what exists (30 §1/§8)."""
    candidate = Path(name if name is not None else DEFAULT_CONFIG_NAME)
    if candidate.suffix not in (".yaml", ".yml"):
        candidate = candidate.with_name(candidate.name + ".yaml")
    path = candidate if candidate.parent != Path(".") else folder / candidate.name
    if path.is_file():
        return path
    available = sorted(p.name for p in folder.glob("*.y*ml")) if folder.is_dir() else []
    found = ", ".join(available) or f"none — a healthy checkout has {folder.name}/default.yaml"
    raise ConfigError(f"config file not found: {path} — available in {folder}: {found}")


def _parse(text: str, path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark else ""
        detail = " ".join(str(getattr(exc, "problem", None) or exc).split())
        raise ConfigError(f"{path.name} is not valid YAML{where} — {detail}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{path.name}: expected a mapping of settings at the top level")
    return dict(raw)


def _reject_interpolation(node: Any, file: str, key: str) -> None:
    """D30: a config YAML cannot carry a secret even in placeholder form — there is no expansion."""
    if isinstance(node, str) and _INTERPOLATION.search(node):
        raise ConfigError(
            f"{file}: {key or 'a value'} contains '${{...}}' — config loading has no variable "
            "interpolation; put the secret in .env and name the variable instead")
    if isinstance(node, Mapping):
        for sub, value in node.items():
            _reject_interpolation(value, file, f"{key}.{sub}" if key else str(sub))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _reject_interpolation(value, file, f"{key}[{index}]")


def _section(node: Any, key: str) -> Mapping[str, Any]:
    """One block of an UNVALIDATED parse, or an empty mapping — the picker never raises (FR-56)."""
    block = node.get(key) if isinstance(node, Mapping) else None
    return block if isinstance(block, Mapping) else {}


def _describe(text: str, raw: Any) -> str:
    """The picker line: the file's own `label:`, else the niche descriptor, else line 1 (FR-173).

    `label:` leads because a niche join is three sentences long and two sibling niches can share a
    byte-identical `niche:` block, so no truncation width can tell them apart. Naming itself is the
    file's job.
    """
    if isinstance(raw, Mapping) and (label := str(raw.get("label") or "").strip()):
        return label
    niche = _section(raw, "niche")
    parts = [str(niche.get(k, "")).strip() for k in ("audience", "vibe", "visual_world")]
    if joined := " · ".join(p for p in parts if p):
        return joined
    first = text.splitlines()[0].strip() if text.strip() else ""
    return first.lstrip("#").strip() if first.startswith("#") else ""


def _summarize(path: Path, text: str, raw: Any) -> ConfigSummary:
    """One picker row off the already-parsed file — no validation, no `Config` build.

    Every scalar falls back to its schema dataclass, never to a second literal, so a row and the
    `Config` the run then loads cannot disagree about what an absent key means.
    """
    run, sources = _section(raw, "run"), _section(raw, "sources")
    formats = {**RunConfig().formats, **{key: value for key, value in _section(run, "formats").items()
                                         if isinstance(value, int) and not isinstance(value, bool)}}
    languages = {**RunConfig().languages, **_section(run, "languages")}
    ids = sources.get("virlo_monitor_ids")
    return ConfigSummary(
        path.stem, path, _describe(text, raw),
        label=str(raw.get("label") or "").strip() if isinstance(raw, Mapping) else "",
        language="/".join(sorted({str(value) for value in languages.values()})),
        monitor_count=len(ids) if isinstance(ids, list) else 0, formats=formats)


# --------------------------------------------------------------------------- building


@dataclass(slots=True)
class _Ctx:
    """Load-time accumulator: file name for messages, keys that defaulted, warnings raised."""

    file: str
    defaults: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fail(self, key: str, value: Any, expected: str) -> NoReturn:
        raise ConfigError(f"{self.file}: {key}: {value!r} — expected {expected}")

    def refuse(self, message: str) -> NoReturn:
        """A CROSS-KEY refusal: one whole sentence, still one line, still prefixed by the file.

        `fail` is shaped for one key that holds a wrong value (`key: value — expected shape`). Two
        keys that are each individually legal and illegal together (FR-307's history/fetch windows,
        §0.14e's formats/sourcing pair) have no single offending key and no "expected shape" — the
        operator needs both names, both values, and which way to move them, so those refusals write
        their own sentence instead of being bent into a shape that would name only half the problem.
        """
        raise ConfigError(f"{self.file}: {message}")

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        logger.warning("config: %s", message)


#: Inclusive bounds for scalars whose out-of-range value is genuinely malformed. Deliberately
#: absent: `run.reel_duration_s` (clamped at pre-flight, FR-103/138) and every price (`null` is a
#: legitimate "unpriced", so `_validate_prices` handles them).
_BOUNDS: dict[str, tuple[float, float, str]] = {
    "run.spend_cap_usd": (0.01, 1e6, "a positive number of dollars"),
    "run.trend_history_days": (0, 365, "a whole number of days, 0–365 (0 disables the window)"),
    "run.max_trend_reuses_per_run": (1, 50, "a whole number of creatives per trend, 1–50"),
    "run.run_deadline_min": (1, 720, "a whole number of minutes, 1–720"),
    "run.text_budgets.image_headline": (1, 400, "a character count, 1–400"),
    "run.text_budgets.image_subline": (1, 400, "a character count, 1–400"),
    "run.text_budgets.slide": (1, 400, "a character count, 1–400"),
    "run.text_budgets.reel_seed_headline": (1, 400, "a character count, 1–400"),
    "run.text_budgets.retry_reduction_pct": (1, 90, "a percentage, 1–90"),
    "branding.brand_ratio": (0.0, 1.0, "a ratio between 0 and 1"),
    "styles.refs_per_job": (1, 16, "a whole number of references per job, 1–16"),
    "sources.virlo_session_pool": (1, 8, "a whole number of MCP sessions, 1–8"),
    # 0 is inside these bounds and is rejected by `_validate` instead, so the operator gets the
    # "-1 is the kill switch you meant" line rather than a bare range message.
    "sources.virlo_topics_per_monitor": (
        -1, 50, "a whole number of topics per monitor, 1–50, or -1 (one topic per monitor)"),
    # FR-301/FR-138: both are refused out of range rather than clamped into it, because a fetch
    # window is the one setting where a silently corrected typo changes which posts a paid run
    # quotes without ever saying so.
    "sources.fetch_pages": (1, 10, "a whole number of result pages per monitor, 1–10"),
    "sources.max_post_age_days": (
        0, 365, "a whole number of days, 0–365 (0 disables the staleness cap)"),
    "models.image_job_timeout_s": (5, 3600, "a whole number of seconds, 5–3600"),
    "models.video_job_timeout_s": (5, 3600, "a whole number of seconds, 5–3600"),
    "models.poll_interval_s": (1, 60, "a whole number of seconds, 1–60"),
    "models.http_max_attempts": (1, 10, "a whole number of attempts, 1–10"),
    "models.max_inflight_llm_calls": (1, 64, "a whole number of concurrent calls, 1–64"),
    "models.max_inflight_render_jobs": (1, 64, "a whole number of concurrent jobs, 1–64"),
    "mcp_servers.mcp_startup_timeout_s": (1, 600, "a whole number of seconds, 1–600"),
    "mcp_servers.mcp_call_timeout_s": (1, 600, "a whole number of seconds, 1–600"),
}


def _build(cls: type, raw: Any, prefix: str, ctx: _Ctx) -> Any:
    """Build one schema dataclass: coerce what is present, default what is not, warn on strays."""
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        ctx.fail(prefix.rstrip(".") or "the config", raw, "a mapping of key: value pairs")
    hints = get_type_hints(cls)
    fields = {f.name: f for f in dataclasses.fields(cls)}
    skip = (_META | _HANDLED) if cls is Config else frozenset()
    for key in raw:
        if key not in fields or key in _META:
            ctx.warn(f"unknown config key {prefix}{key} — ignored")
    values: dict[str, Any] = {}
    for name, spec in fields.items():
        if name in skip:
            continue
        key = f"{prefix}{name}"
        if raw.get(name) is None:
            ctx.defaults.append(key)
            continue
        values[name] = _coerce(_merged(_default_of(spec), raw[name]), hints[name], key, ctx)
    return cls(**values)


def _default_of(spec: dataclasses.Field) -> Any:  # type: ignore[type-arg]
    if spec.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
        return spec.default_factory()  # type: ignore[misc]
    return None if spec.default is dataclasses.MISSING else spec.default


def _merged(default: Any, provided: Any) -> Any:
    """Key-by-key defaulting inside mappings — 30 §1: an override lists only what it changes."""
    if isinstance(default, Mapping) and isinstance(provided, Mapping):
        out = dict(default)
        for key, value in provided.items():
            out[key] = _merged(_unpacked(default.get(key)), value) if key in default else value
        return out
    return provided


def _unpacked(default: Any) -> Any:
    """A dataclass INSTANCE standing as a mapping's default VALUE, seen as the mapping it is.

    Only `branding.profiles` is shaped that way today (`dict[str, BrandProfile]` with compiled
    entries, FR-292), and without this a file overriding one colour would drop the rest of that
    profile — its wordmark, fonts and `never:` lines — to `BrandProfile()` blanks, because the
    override mapping would replace the whole entry rather than merge into it. Plan §1.4 promises
    the compiled profiles are "all overridable", one key at a time, exactly like every other
    nested mapping in this schema.

    Deliberately scoped to mapping VALUES rather than to `_merged`'s entry: a schema FIELD whose
    default is a dataclass instance (`run:`, `sources:`, every section) must keep arriving at
    `_build` as the file wrote it, because `_build` is what records the absent keys in
    `defaults_applied` (FR-50/NFR-19). Unpacking there instead would hand `_build` a complete
    mapping and the run log would stop naming a single defaulted key.
    """
    if dataclasses.is_dataclass(default) and not isinstance(default, type):
        return dataclasses.asdict(default)
    return default


def _coerce(value: Any, tp: Any, key: str, ctx: _Ctx) -> Any:
    """Validate one value against its annotation, or fail naming the expected shape (FR-69)."""
    origin = get_origin(tp)
    if tp is Any:
        return value
    if origin is Literal:
        options = get_args(tp)
        value = _unyaml_bool(value, options)
        if value not in options:
            ctx.fail(key, value, "one of: " + " | ".join(str(o) for o in options))
        return value
    if origin in (Union, UnionType):
        inner = [a for a in get_args(tp) if a is not type(None)]
        return None if value is None else _coerce(value, inner[0], key, ctx)
    if dataclasses.is_dataclass(tp):
        # A `dict[str, <dataclass>]` field whose default factory ships built entries (`branding.
        # profiles`) reaches here with those entries intact: `_merged` replaces only the keys the
        # file names, so every sibling arrives already built. It is a default this module made, not
        # user input, so it is passed through rather than re-parsed as a mapping.
        if isinstance(value, tp):
            return value
        return _build(tp, value, f"{key}.", ctx)
    if origin is list or tp is list:
        if not isinstance(value, list):
            ctx.fail(key, value, "a list")
        item = (get_args(tp) or (Any,))[0]
        return [_coerce(v, item, f"{key}[{i}]", ctx) for i, v in enumerate(value)]
    if origin is dict or tp is dict:
        if not isinstance(value, Mapping):
            ctx.fail(key, value, "a mapping of key: value pairs")
        args = get_args(tp)
        item = args[1] if len(args) == 2 else Any
        return {str(k): _coerce(v, item, f"{key}.{k}", ctx) for k, v in value.items()}
    if tp is bool:
        if not isinstance(value, bool):
            ctx.fail(key, value, "true or false")
        return value
    if tp in (int, float):
        numeric = isinstance(value, int if tp is int else (int, float))
        if isinstance(value, bool) or not numeric:
            ctx.fail(key, value, _BOUNDS.get(key, (0, 0, "a whole number" if tp is int
                                                  else "a number"))[2])
        return _bounded(tp(value), key, ctx)
    if tp is str:
        if not isinstance(value, str):
            ctx.fail(key, value, "text")
        return value
    return Path(str(value)) if tp is Path else value


def _unyaml_bool(value: Any, options: Sequence[Any]) -> Any:
    """Give `off`/`on`/`no`/`yes` back to a text enum that wants them.

    YAML 1.1 resolves those bare words to booleans, so the PRD's own `notion_influence: off` would
    otherwise be rejected as `False`. Applied only when the enum offers the matching word, so a
    genuine boolean key is untouched.
    """
    if not isinstance(value, bool):
        return value
    for word in ("on", "yes", "true") if value else ("off", "no", "false"):
        if word in options:
            return word
    return value


def _bounded(value: Any, key: str, ctx: _Ctx) -> Any:
    bounds = _BOUNDS.get(key)
    if bounds and not bounds[0] <= value <= bounds[1]:
        ctx.fail(key, value, bounds[2])
    return value


def _default_platform(name: str) -> PlatformConfig:
    """30 §2: image + carousel everywhere, reel on TikTok only, 5 slides (FR-132/257)."""
    formats = ["image", "carousel", "reel"] if name in _REEL_PLATFORMS else ["image", "carousel"]
    return PlatformConfig(formats=formats)


def _build_platforms(raw: Any, active: Sequence[str], ctx: _Ctx) -> dict[str, PlatformConfig]:
    """One entry per platform named in `run.platforms` or in the `platforms:` block itself."""
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        ctx.fail("platforms", raw, "a mapping of platform name to settings")
    built: dict[str, PlatformConfig] = {}
    for name in dict.fromkeys([*active, *raw.keys()]):
        entry = raw.get(name)
        if entry is None:
            ctx.defaults.append(f"platforms.{name}")
            built[name] = _default_platform(name)
            continue
        if not isinstance(entry, Mapping):
            ctx.fail(f"platforms.{name}", entry, "a mapping of platform settings")
        entry = dict(entry)
        if entry.get("formats") is None:  # the allowlist default is per-platform, not shared
            ctx.defaults.append(f"platforms.{name}.formats")
            entry["formats"] = _default_platform(name).formats
        built[name] = _build(PlatformConfig, entry, f"platforms.{name}.", ctx)
    return built


def _build_mcp(raw: Any, ctx: _Ctx) -> McpConfig:
    """Split the two timing keys from the per-server entries, which stay opaque (FR-130)."""
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        ctx.fail("mcp_servers", raw, "a mapping of timeouts and server entries")
    cfg = McpConfig()
    for key, attr in (("mcp_startup_timeout_s", "startup_timeout_s"),
                      ("mcp_call_timeout_s", "call_timeout_s")):
        if raw.get(key) is None:
            ctx.defaults.append(f"mcp_servers.{key}")
        else:
            setattr(cfg, attr, _coerce(raw[key], int, f"mcp_servers.{key}", ctx))
    for name, entry in raw.items():
        if name in ("mcp_startup_timeout_s", "mcp_call_timeout_s"):
            continue
        if not isinstance(entry, Mapping):
            ctx.fail(f"mcp_servers.{name}", entry, "a mapping with transport/command or url")
        cfg.servers[str(name)] = dict(entry)
    return cfg


# --------------------------------------------------------------------------- validation


def _validate(cfg: Config, ctx: _Ctx) -> None:
    """Cross-key checks annotations cannot express. One error line each (FR-69)."""
    for name, count in cfg.run.formats.items():
        if name not in _FORMATS:
            ctx.fail("run.formats", name, "one of: " + " | ".join(_FORMATS))
        if count < 0:
            ctx.fail(f"run.formats.{name}", count, "a whole number of creatives, 0 or more")
    for source in cfg.sources.active:
        if source not in _SOURCES:
            ctx.fail("sources.active", source, "one of: " + " | ".join(_SOURCES))
    if cfg.sources.virlo_topics_per_monitor == 0:  # in range, but it means "collect nothing"
        ctx.fail("sources.virlo_topics_per_monitor", 0,
                 _BOUNDS["sources.virlo_topics_per_monitor"][2])
    _validate_windows(cfg, ctx)
    _validate_formats_sourcing(cfg, ctx)
    languages = list(cfg.run.languages.items()) + list(cfg.run.onimage_text_language.items())
    for platform, language in languages:
        if language not in _LANGUAGES:
            ctx.fail(f"language for {platform}", language, "one of: " + " | ".join(_LANGUAGES))
    for platform in cfg.run.platforms:
        if platform not in PLATFORMS:  # `linkedn` used to load clean and cost real money
            ctx.fail("run.platforms", platform, "one of: " + " | ".join(PLATFORMS))
        if platform not in cfg.run.languages:
            ctx.defaults.append(f"run.languages.{platform} (en)")
            cfg.run.languages[platform] = "en"

    for name, entry in cfg.platforms.items():
        for fmt in list(entry.formats) + list(entry.aspect_ratios):
            if fmt not in _FORMATS:
                ctx.fail(f"platforms.{name}", fmt, "one of: " + " | ".join(_FORMATS))
        if not 1 <= entry.carousel_slides <= 20:
            ctx.fail(f"platforms.{name}.carousel_slides", entry.carousel_slides,
                     "a whole number of slides, 1–20")
        if name == "instagram" and not 2 <= entry.carousel_slides <= 10:
            ctx.warn(  # SHOULD, not SHALL — Instagram's own ceiling (FR-257, 60 FR-221)
                f"platforms.instagram.carousel_slides is {entry.carousel_slides}; Instagram "
                "accepts 2–10, so a Phase 2 publish could drop slides")

    _validate_branding(cfg, ctx)

    prices = cfg.models.price_per_unit
    tables: list[tuple[str, Mapping[str, float | None]]] = [
        ("image", prices.image), ("reel_second", prices.reel_second),
        *((f"llm.{model}", rates) for model, rates in prices.llm.items())]
    for group, table in tables:  # `null` is a legitimate "unpriced"; negative never is (FR-282)
        for tier, price in table.items():
            if price is not None and price < 0:
                ctx.fail(f"models.price_per_unit.{group}.{tier}", price, "a non-negative price")
    _clamp_token_limits(cfg.models, ctx)

    if cfg.run.formats.get("reel", 0) > 0 and not cfg.reels_plannable:
        ctx.warn(  # never an error: FR-131/252 drop reels at pre-flight, they never fail the load
            f"reels requested but {cfg.reel_price_key} is unset — reels will not be planned "
            "until a real per-second rate is entered (FR-131, OQ-2)")
    # Reel-capable = priced (so `--reels N` can turn them on later too) or already requested.
    reel_capable = cfg.reels_plannable or cfg.run.formats.get("reel", 0) > 0
    if reel_capable and cfg.run.run_deadline_min * 60 < cfg.models.video_job_timeout_s:
        ctx.warn(  # warn, not fail: this combination silently WASTES reel money (20 §8, FR-108)
            f"run.run_deadline_min {cfg.run.run_deadline_min} min is under "
            f"models.video_job_timeout_s {cfg.models.video_job_timeout_s} s — the deadline "
            "abandons the run before a slow reel can reach its own timeout, and that reel is "
            "paid for and never resubmitted; raise run_deadline_min above the job timeout plus "
            "the analyze/copy/image stages")


def _validate_windows(cfg: Config, ctx: _Ctx) -> None:
    """FR-307: the no-repeat memory must cover at least the window the fetch reaches back over.

    Both keys are individually legal at any value in their bounds; only the PAIR can be wrong. When
    the history window is narrower than the fetch window there is a band of days in which a post is
    old enough to have been forgotten by the history file and young enough to be fetched again —
    and the run re-quotes, word for word, something it already published. That is the exact defect
    D46 was written for, so it is refused rather than clamped: raising one key or lowering the other
    are different decisions with different costs (memory size vs. supply), and the engine has no
    business picking one on the operator's behalf.

    `trend_history_days: 0` is the deliberate opt-out — the window is switched off entirely, the
    operator has said out loud that repeats are acceptable, and there is no half-covered band to
    warn about. It is exempt, not a violation.
    """
    history, fetch = cfg.run.trend_history_days, cfg.sources.max_post_age_days
    if history != 0 and history < fetch:
        ctx.refuse(
            f"run.trend_history_days is {history} but sources.max_post_age_days is {fetch} — the "
            "no-repeat history window must be at least as wide as the fetch window, or a post the "
            "run already used drops out of history while it is still being fetched and gets "
            f"quoted twice; raise run.trend_history_days to {fetch} or more, lower "
            "sources.max_post_age_days, or set run.trend_history_days to 0 to turn the window off "
            "on purpose (FR-307)")


def _validate_formats_sourcing(cfg: Config, ctx: _Ctx) -> None:
    """§0.14e: image and reel counts need video sourcing, because v1 fetches slideshows only.

    With `sources.include_videos: false` every topic in the pool is slideshow-majority, and a
    slideshow is a deck — the thing a CAROUSEL reproduces panel for panel (FR-304). An image or a
    reel planned against that pool cannot use the panels, so it falls back to a lower-ranked field
    of a post the run was never meant to quote that way, forever and silently. Refusing the pair
    makes that a visible either/or: turn video sourcing on, or plan carousels.
    """
    if cfg.sources.include_videos:
        return
    images, reels = cfg.run.formats.get("image", 0), cfg.run.formats.get("reel", 0)
    if images + reels <= 0:
        return
    wanted = " + ".join(f"{count} {name}" for name, count in
                        (("image", images), ("reel", reels)) if count)
    ctx.refuse(
        f"run.formats asks for {wanted} while sources.include_videos is false — slideshow-first "
        "sourcing makes every topic slideshow-majority, so image and reel creatives would "
        "silently rank-fallback onto posts they cannot quote properly; set "
        "sources.include_videos: true or set those counts to 0 (§0.14e, FR-132)")


def _validate_branding(cfg: Config, ctx: _Ctx) -> None:
    """FR-292: the selected brand must exist, and every colour must be a real hex.

    Both checks are here rather than in the annotations because neither is expressible there: the
    valid values of `brand` are whatever `profiles` defines (a config may add a third brand), and
    `colors` is `dict[str, Any]` precisely so one entry can be a gradient LIST. A wrong value in
    either would otherwise surface as a wrong colour or a blank wordmark in a paid render.
    """
    branding = cfg.branding
    for name, profile in branding.profiles.items():
        for key, value in profile.colors.items():
            is_list = isinstance(value, list)  # a gradient is a list of hexes; check element-wise
            for index, item in enumerate(value if is_list else [value]):
                if isinstance(item, str) and not _HEX.match(item):
                    where = f"branding.profiles.{name}.colors.{key}"
                    ctx.fail(f"{where}[{index}]" if is_list else where, item,
                             "a hex colour like #34288B")
    if branding.brand not in branding.profiles:
        known = " | ".join(sorted(branding.profiles)) or "none — branding.profiles is empty"
        ctx.fail("branding.brand", branding.brand,
                 f"a brand defined under branding.profiles: {known}")


def _clamp_token_limits(models: ModelsConfig, ctx: _Ctx) -> None:
    """NFR-111: a per-role cap below its floor is raised to the floor and the run is told."""
    for role, floor in models.max_tokens_floor.items():
        if floor < 1:
            ctx.fail(f"models.max_tokens_floor.{role}", floor, "a positive whole number of tokens")
        if models.max_tokens.get(role, floor) < floor:
            was = models.max_tokens[role]
            models.max_tokens[role] = floor
            ctx.warn(f"models.max_tokens.{role} was {was}, below the configured floor {floor} — "
                     f"clamped up to {floor} so the call cannot silently truncate (NFR-111)")
    for role, limit in models.max_tokens.items():
        if limit < 1:
            ctx.fail(f"models.max_tokens.{role}", limit, "a positive whole number of tokens")


__all__ = [
    "CONFIGS_DIR", "DEFAULT_CONFIG_NAME", "LOGS_DIR", "BrandConfig", "BrandProfile",
    "BrandingConfig", "Config", "ConfigError", "ConfigSummary",
    "GalleryConfig", "McpConfig", "ModelsConfig", "NicheConfig", "OutputConfig", "PLATFORMS",
    "PlatformConfig", "PriceTable", "RunConfig", "SourcesConfig", "StylesConfig", "TextBudgets",
    "list_configs", "load_config",
]
