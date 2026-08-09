"""Config loading — the one door between `configs/*.yaml` and every other module.

Public API: `load_config(name) -> Config`, `list_configs()`, `Config`, `ConfigError`.
30-configuration-and-run.md §2 owns every key name and default; the dataclasses below ARE that
schema, so a new key is one annotated field plus a line in the shipped YAML.

Invariants: absent keys default and land in `defaults_applied` for the run log, never erroring
(FR-50, NFR-19); a malformed value raises ONE plain-English line — file, key, value, expected
shape (FR-51/69); unknown keys warn; a `${VAR}` placeholder is a hard error, because config
loading has no interpolation and that absence is what makes a config file secret-free (D30,
FR-130/177); `max_tokens` under its floor is clamped up with a warning (NFR-111).

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
DEFAULT_CONFIG_NAME = "default"

_INTERPOLATION = re.compile(r"\$\{")
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
    """On-image character ceilings, enforced before submission — not prompt hints (FR-101/259)."""

    image_headline: int = 42
    image_subline: int = 60
    reel_seed_headline: int = 32
    retry_reduction_pct: int = 40  # budgets are cut by this % on a vision-check retry


@dataclass(slots=True)
class RunConfig:
    """`run:` — scope, spend and per-format behaviour."""

    formats: dict[str, int] = field(default_factory=lambda: {"image": 4, "carousel": 2, "reel": 0})
    platforms: list[str] = field(default_factory=lambda: ["linkedin", "instagram", "tiktok"])
    languages: dict[str, str] = field(
        default_factory=lambda: {"linkedin": "en", "instagram": "en", "tiktok": "en"})
    generation_mode: Literal["analyzed", "direct", "both"] = "analyzed"
    notion_influence: Literal["off", "copy", "full"] = "off"
    vision_check: bool = False
    spend_cap_usd: float = 10.00
    trend_history_days: int = 7  # 0 disables the repeat-prevention window
    max_trend_reuses_per_run: int = 2
    carousel_anchor: bool = True
    reel_overlay_text: Literal["seed_frame", "in_model", "none"] = "seed_frame"
    reel_audio: bool = True
    reel_video_reference: bool = True
    reel_reference_max_s: int = 28  # the reference's seconds are BILLED — see RESULTS.md §C
    reel_duration_s: int = 5  # 4–30; out of range is CLAMPED at pre-flight, never rejected here
    reel_resolution: Literal["480p", "720p"] = "720p"
    nsfw_checker: bool = True  # provider knob, always sent (its own default is false)
    require_reference_image: bool = True
    onimage_text_language: dict[str, str] = field(default_factory=dict)
    text_budgets: TextBudgets = field(default_factory=TextBudgets)
    run_deadline_min: int = 25  # soft ceiling on the monotonic clock (FR-108/243)


@dataclass(slots=True)
class SourcesConfig:
    """`sources:` — which adapters feed the run and how much media they may pull."""

    active: list[str] = field(default_factory=lambda: ["virlo"])
    virlo_monitor_ids: list[str] = field(default_factory=list)
    virlo_session_pool: int = 3  # bounded wrapper sessions; never one subprocess per monitor
    media_download_cap: int = 6  # reference IMAGES per trend; the video ref is bounded separately
    reference_images_per_job: int = 3
    inspiration_folders: list[str] = field(default_factory=list)  # flat global pool (D13)
    inspiration_mix: Literal["off", "minority", "exclusive"] = "minority"


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
    image: str = "gpt-image-2-image-to-image"  # reference-bearing route; profile picks the sibling
    video: str = "bytedance/seedance-2-5"
    image_profile: str = "gpt-image-2"  # FR-281 — changes only on a model FAMILY change
    video_profile: str = "seedance-2-5"
    reasoning_effort: Literal["low", "medium", "high"] = "low"  # `copy` role only (Luna)
    # DELIBERATELY EMPTY (spikes/RESULTS.md §E): neither shipped model advertises `temperature`,
    # and sending it under `provider.require_parameters` returns HTTP 404. The key survives for a
    # model that does support it; FR-129 as written needs a D15 amendment.
    temperature: dict[str, float] = field(default_factory=dict)
    max_tokens: dict[str, int] = field(default_factory=lambda: {"analysis": 2000, "copy": 3000})
    # NFR-111 floors, set at a third of each default: below this a cap buys truncation retries as
    # the normal path rather than saving money, so a smaller value is clamped up and warned about.
    max_tokens_floor: dict[str, int] = field(
        default_factory=lambda: {"analysis": 600, "copy": 1000})
    price_per_unit: PriceTable = field(default_factory=PriceTable)
    image_job_timeout_s: int = 180
    video_job_timeout_s: int = 600  # PRD canonical (FR-259, v1.6.7); measured renders ran 302–378 s
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
    """FR-134: `title` is the only gallery key — A/B pairing is automatic, driven by `pair_id`."""

    title: str = "HypeSocials Run"


@dataclass(slots=True)
class OutputConfig:
    """`output:` — consumed by 40-outputs-and-logging.md's writers."""

    dir: str = "output/"
    gallery: GalleryConfig = field(default_factory=GalleryConfig)
    log_verbosity: Literal["normal", "verbose"] = "normal"


@dataclass(slots=True)
class NicheConfig:
    """The optional `niche:` descriptor (D27), injected into Analyze and Write (FR-147)."""

    audience: str = ""
    vibe: str = ""
    visual_world: str = ""

    def as_text(self) -> str:
        """One compact line for the `{{niche_descriptor}}` placeholder; empty when unset."""
        labels = (("Audience", self.audience), ("Vibe", self.vibe),
                  ("Visual world", self.visual_world))
        return " · ".join(f"{label}: {value}" for label, value in labels if value)


@dataclass(slots=True)
class Config:
    """One fully-resolved run configuration. Built only by `load_config`."""

    name: str = DEFAULT_CONFIG_NAME
    path: Path = field(default_factory=lambda: CONFIGS_DIR / "default.yaml")
    description: str = ""  # niche descriptor, else the line-1 comment (FR-56/173)
    run: RunConfig = field(default_factory=RunConfig)
    sources: SourcesConfig = field(default_factory=SourcesConfig)
    models: ModelsConfig = field(default_factory=ModelsConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    niche: NicheConfig = field(default_factory=NicheConfig)
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


@dataclass(slots=True)
class ConfigSummary:
    """One row of the menu's config picker (FR-56/173)."""

    name: str
    path: Path
    description: str


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
        summaries.append(ConfigSummary(path.stem, path, _describe(text, raw)))
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


def _describe(text: str, raw: Any) -> str:
    """The picker line: the niche descriptor when there is one, else line 1's comment (FR-173)."""
    niche = raw.get("niche") if isinstance(raw, Mapping) else None
    if isinstance(niche, Mapping):
        parts = [str(niche.get(k, "")).strip() for k in ("audience", "vibe", "visual_world")]
        if joined := " · ".join(p for p in parts if p):
            return joined
    first = text.splitlines()[0].strip() if text.strip() else ""
    return first.lstrip("#").strip() if first.startswith("#") else ""


# --------------------------------------------------------------------------- building


@dataclass(slots=True)
class _Ctx:
    """Load-time accumulator: file name for messages, keys that defaulted, warnings raised."""

    file: str
    defaults: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fail(self, key: str, value: Any, expected: str) -> NoReturn:
        raise ConfigError(f"{self.file}: {key}: {value!r} — expected {expected}")

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
    "run.reel_reference_max_s": (1, 30, "a whole number of seconds, 1–30"),
    "run.run_deadline_min": (1, 720, "a whole number of minutes, 1–720"),
    "run.text_budgets.image_headline": (1, 400, "a character count, 1–400"),
    "run.text_budgets.image_subline": (1, 400, "a character count, 1–400"),
    "run.text_budgets.reel_seed_headline": (1, 400, "a character count, 1–400"),
    "run.text_budgets.retry_reduction_pct": (1, 90, "a percentage, 1–90"),
    "sources.virlo_session_pool": (1, 8, "a whole number of MCP sessions, 1–8"),
    "sources.media_download_cap": (1, 50, "a whole number of images per trend, 1–50"),
    "sources.reference_images_per_job": (1, 16, "a whole number of references per job, 1–16"),
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
    """Key-by-key defaulting inside mappings — 30 §1: a variant lists only what it overrides."""
    if isinstance(default, Mapping) and isinstance(provided, Mapping):
        out = dict(default)
        for key, value in provided.items():
            out[key] = _merged(default.get(key), value) if key in default else value
        return out
    return provided


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
    "CONFIGS_DIR", "DEFAULT_CONFIG_NAME", "Config", "ConfigError", "ConfigSummary",
    "GalleryConfig", "McpConfig", "ModelsConfig", "NicheConfig", "OutputConfig", "PLATFORMS",
    "PlatformConfig", "PriceTable", "RunConfig", "SourcesConfig", "TextBudgets", "list_configs",
    "load_config",
]
