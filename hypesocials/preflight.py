"""Everything that must be true before a single cent can move — the exit-2 producer.

Module contract
---------------
Purpose: one pass, run before any MCP session and any billable call, that either clears the run
or refuses it with plain lines an operator can act on (FR-45–47, FR-138, FR-255, FR-281, FR-263,
FR-103, 30 §8). Callers get a verdict object, never a scattering of booleans.

Public API: `check()` · `Preflight` · `collect_secrets()` · `resolve_briefs()` ·
`EXIT_PREFLIGHT`.

Invariants:
- **Refusal is free** (FR-202 code 2): every check here is local — env vars, config arithmetic,
  a template listing, one test file inside `output.dir`. Nothing external is contacted.
- **Two failure grades, deliberately.** An *error* refuses the run; a *warning* or *hint* lets it
  proceed. Missing `NOTION_TOKEN` is the canonical warning (FR-47: influence drops to `off`), an
  out-of-range `reel_duration_s` the canonical clamp (FR-103) — nothing is silently sent to a
  provider to fail after payment.
- **The config is normalized here, in place, and says so**: the FR-103 clamp and FR-47's forced
  `notion_influence: off` are written onto the `Config` the rest of the run reads, so no later
  stage re-derives them.
- **Profiles are checked through their owners** — `render.get_profile()` for FR-281 and
  `prompts_engine.validate_template_set()` for FR-263. This module never re-derives a required
  template name; a second registry is how they drift.
- **Secrets are read, never returned to a prompt.** `collect_secrets()` hands the *values* to
  `LogWriter`'s redaction set and to nothing else (D30).

Do not: open a session, call a provider, load a config file (the caller owns that), or turn a
warning into an abort — a run that can still deliver something must be allowed to.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from hypesocials import briefs
from hypesocials.config import Config
from hypesocials.plan import BriefRequest
from hypesocials.prompts_engine import validate_template_set
from hypesocials.render import UnknownProfileError, get_profile

EXIT_PREFLIGHT = 2

#: The three keys FR-46 refuses on, plus FR-47's optional one. Values never leave this module
#: except through `collect_secrets()`, which feeds the logger's redaction set (D30).
REQUIRED_SECRETS: dict[str, str] = {
    "VIRLO_API_KEY": "Virlo trend discovery",
    "OPENROUTER_API_KEY": "Sonnet 5 analysis and GPT 5.6 Luna copy",
    "KIE_API_KEY": "GPT Image 2 and Seedance 2.5 renders",
}
OPTIONAL_SECRETS: tuple[str, ...] = ("NOTION_TOKEN", "POSTIZ_API_KEY", "HANDLE_HASH_KEY")

#: Which secrets each action can actually spend against — `--list-monitors` needs one key and no
#: plan at all (FR-251), a source preview never reaches an LLM, a full run needs all three.
_NEEDED: dict[str, tuple[str, ...]] = {
    "run": ("VIRLO_API_KEY", "OPENROUTER_API_KEY", "KIE_API_KEY"),
    "preview-analysis": ("VIRLO_API_KEY", "OPENROUTER_API_KEY"),
    "preview-sources": ("VIRLO_API_KEY",),
    "list-monitors": ("VIRLO_API_KEY",),
}

MIN_PYTHON = (3, 12)
REEL_DURATION_RANGE = (4, 30)  # FR-103 / 20 FR-164 — the provider's verified continuous range
#: 40 FR-86's per-asset figures, used only to size the FR-255 free-space comparison.
_ASSET_BYTES = {"image": 300_000, "carousel": 800_000, "reel": 20_000_000}
_RUN_OVERHEAD_BYTES = 8_000_000  # logs, gallery, the run-level refs/ folder
_PROBE_FILE = ".hypesocials-disk-probe"


@dataclass(slots=True)
class Preflight:
    """One verdict. `ok` is the gate; everything else is what the operator should be told."""

    ok: bool = True
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    hints: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()  # present secret VALUES, for the log redaction set only
    estimated_bytes: int = 0

    @property
    def report(self) -> str:
        """Everything worth printing, in refusal-first order; empty when the run is clean."""
        lines = [f"pre-flight refused: {line}" for line in self.errors]
        lines += [f"warning: {line}" for line in self.warnings]
        lines += [f"hint: {line}" for line in self.hints]
        return "\n".join(lines)


def collect_secrets() -> tuple[str, ...]:
    """Every secret VALUE present in the environment — the `LogWriter` redaction set (FR-152).

    Values only, never names paired to values in a log line; the writer masks each occurrence
    wherever it appears in a message or a payload. Missing variables simply do not contribute.
    """
    names = (*REQUIRED_SECRETS, *OPTIONAL_SECRETS)
    return tuple(sorted({value for value in (os.environ.get(n, "").strip() for n in names) if value}))


def resolve_briefs(
    requests: Sequence[tuple[str, int]], config: Config, *, assume_yes: bool = False
) -> tuple[list[BriefRequest], list[str], list[str]]:
    """Resolve every `--brief <name>:<count>` request against the active config's `briefs_dir`.

    `briefs.load()` owns the whole FR-172 shape check, so a missing or malformed brief arrives
    here as one operator-facing line naming the exact file. Interactively that line is an *error*
    and refuses the run before any billable call; under `--yes` it is a *warning* and only that
    brief's creatives are dropped, so one stale file never costs a scheduled batch (FR-252).

    Returns `(resolved, errors, warnings)` — `resolved` feeds `plan.build_plan(briefs=...)`.
    """
    resolved: list[BriefRequest] = []
    lines: list[str] = []
    folder = Path(config.briefs_dir)
    for name, count in requests:
        try:
            resolved.append(BriefRequest(brief=briefs.load(name, folder), count=int(count)))
        except briefs.BriefError as exc:
            lines.append(str(exc))
    return (resolved, [], lines) if assume_yes else (resolved, lines, [])


def check(
    config: Config,
    *,
    action: str = "run",
    entries: Sequence[object] = (),
    briefs_errors: Sequence[str] = (),
) -> Preflight:
    """The whole pre-flight pass. Mutates `config` where the PRD says to normalize, not refuse.

    Args:
        config: the loaded, flag-overridden run config. `run.reel_duration_s` is clamped into
            4–30 (FR-103) and `run.notion_influence` is forced to `off` when `NOTION_TOKEN` is
            absent (FR-47) — both in place, both reported as warnings.
        action: `run` | `preview-analysis` | `preview-sources` | `list-monitors`; picks which
            secrets are genuinely required (FR-46, FR-202's `--list-monitors` row).
        entries: the expanded plan, used only to size FR-255's disk footprint.
        briefs_errors: unresolved-brief lines from `resolve_briefs()`, folded in so a caller
            reports one verdict rather than two.

    Returns:
        `Preflight`. `ok=False` means exit `2` before any external call — nothing was spent.
    """
    errors: list[str] = [str(line) for line in briefs_errors]
    warnings: list[str] = []
    hints: list[str] = []

    if sys.version_info < MIN_PYTHON:
        errors.append(f"Python {'.'.join(map(str, MIN_PYTHON))}+ is required; this interpreter is "
                      f"{sys.version.split()[0]} (FR-138) — delete .venv and re-run run.bat")

    _check_secrets(config, action, errors, warnings)
    _check_profiles(config, action, errors)
    _check_node(config, errors)
    _clamp_reel_duration(config, warnings)
    _check_prices(config, errors, warnings)
    _check_language_hint(config, hints)
    footprint = _check_disk(config, entries, errors)

    return Preflight(
        ok=not errors, errors=tuple(errors), warnings=tuple(warnings), hints=tuple(hints),
        secrets=collect_secrets(), estimated_bytes=footprint)


# --------------------------------------------------------------------------- individual checks


def _check_secrets(config: Config, action: str, errors: list[str], warnings: list[str]) -> None:
    """FR-45/46: refuse on a missing required key, naming the variable. FR-47: Notion degrades."""
    for name in _NEEDED.get(action, _NEEDED["run"]):
        if not os.environ.get(name, "").strip():
            errors.append(f"{name} is not set — {REQUIRED_SECRETS[name]} cannot run without it. "
                          "Put it in .env in the repo root (FR-46)")
    if config.run.notion_influence != "off" and not os.environ.get("NOTION_TOKEN", "").strip():
        warnings.append(f"NOTION_TOKEN is not set — notion_influence "
                        f"{config.run.notion_influence!r} drops to 'off' for this run (FR-47)")
        config.run.notion_influence = "off"  # type: ignore[assignment]


def _check_profiles(config: Config, action: str, errors: list[str]) -> None:
    """FR-281 + FR-263: an unknown profile, or a new profile with no template set, is exit 2."""
    if action in ("list-monitors", "preview-sources"):
        return  # no render model is reached on these paths
    overrides = [config.prompts_dir] if config.prompts_dir else []
    for key, name in (("models.image_profile", config.models.image_profile),
                      ("models.video_profile", config.models.video_profile)):
        try:
            profile = get_profile(name)
        except UnknownProfileError as exc:
            errors.append(f"{key}: {exc} — a model FAMILY change needs its profile implemented "
                          "before the run (FR-281)")
            continue
        missing = validate_template_set(profile.name, override_dirs=overrides)
        if missing:
            errors.append(f"{key}: profile {profile.name!r} is missing its prompt template set — "
                          f"{', '.join(missing)} (FR-263); add them under prompts/")


def _check_node(config: Config, errors: list[str]) -> None:
    """FR-117/138: Node is checked ONLY for a server this run will actually launch.

    `yt-dlp` never counts — it is a Python package in the venv (D23), so a Node-free workstation
    is a perfectly healthy one unless a configured MCP command literally invokes npx/node.
    """
    for name, entry in config.mcp_servers.servers.items():
        if name == "notion" and config.run.notion_influence == "off":
            continue  # not launched this run, so its toolchain is not this run's problem
        command = str(entry.get("command", "")).strip().lower()
        head = command.split()[0].rsplit("\\", 1)[-1] if command else ""
        if head.startswith(("npx", "node")) and not shutil.which(head.split(".")[0]):
            errors.append(f"mcp_servers.{name} launches {head!r} but Node/npx was not found on "
                          "PATH — install Node.js, or set notion_influence: off (FR-117/138)")


def _clamp_reel_duration(config: Config, warnings: list[str]) -> None:
    """FR-103: clamp to the provider's verified 4–30 s range with a warning, never refuse."""
    low, high = REEL_DURATION_RANGE
    requested = int(config.run.reel_duration_s)
    clamped = max(low, min(high, requested))
    if clamped != requested:
        config.run.reel_duration_s = clamped
        warnings.append(f"run.reel_duration_s {requested} is outside {low}–{high} s — clamped to "
                        f"{clamped} (FR-103); nothing was sent to the provider to fail after payment")


def _check_prices(config: Config, errors: list[str], warnings: list[str]) -> None:
    """The cap floor (30 §8) and FR-131's unpriced-reel report."""
    prices = [price for price in config.models.price_per_unit.image.values() if price and price > 0]
    floor = min(prices) if prices else 0.0
    if floor and config.run.spend_cap_usd < floor:
        errors.append(f"spend cap ${config.run.spend_cap_usd:.2f} is below the minimum "
                      f"single-creative cost of ${floor:.2f}, derived from "
                      "models.price_per_unit.image in your config — raise --budget or "
                      "spend_cap_usd (30 §8)")
    if config.run.formats.get("reel", 0) > 0 and not config.reels_plannable:
        warnings.append(f"reels were requested but {config.reel_price_key} is unset — the run "
                        "proceeds without reels (FR-131/FR-252); Seedance pricing is unpublished "
                        "(OQ-2)")


def _check_language_hint(config: Config, hints: list[str]) -> None:
    """30 §2's Czech hint: diacritics are where render models visibly fail, so recommend the check."""
    if config.run.vision_check:
        return
    czech = sorted({p for p in config.run.platforms
                    if "cs" in (config.language_for(p), config.onimage_language_for(p))})
    if czech:
        hints.append(f"{', '.join(czech)} render Czech text and vision_check is off — Czech "
                     "diacritics are where GPT Image 2 struggles most; consider --vision-check "
                     "(30 §2; a hint, never a gate)")


def _check_disk(config: Config, entries: Sequence[object], errors: list[str]) -> int:
    """FR-255: probe INSIDE `output.dir` — %TEMP% is routinely another volume and proves nothing."""
    footprint = _RUN_OVERHEAD_BYTES + sum(
        _ASSET_BYTES.get(str(getattr(entry, "creative_format", "image")), 300_000)
        * max(1, int(getattr(entry, "slide_count", None) or 1))
        for entry in entries)
    out = Path(config.output.dir)
    try:
        out.mkdir(parents=True, exist_ok=True)
        probe = out / _PROBE_FILE
        probe.write_bytes(b"hypesocials")
        probe.unlink()
        free = shutil.disk_usage(out).free
    except OSError as exc:
        errors.append(f"output directory {out.resolve()} is not writable ({exc.strerror or exc}) "
                      "— the run would have nowhere to land (FR-255)")
        return footprint
    if free < footprint:
        errors.append(f"not enough free space in {out.resolve()}: this run needs about "
                      f"{footprint / 1_048_576:.0f} MB and {free / 1_048_576:.0f} MB are free "
                      "(FR-255)")
    return footprint


__all__ = [
    "EXIT_PREFLIGHT", "MIN_PYTHON", "OPTIONAL_SECRETS", "Preflight", "REEL_DURATION_RANGE",
    "REQUIRED_SECRETS", "check", "collect_secrets", "resolve_briefs",
]
