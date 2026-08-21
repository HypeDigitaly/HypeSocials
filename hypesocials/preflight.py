"""Everything that must be true before a single cent can move — the exit-2 producer.

Module contract
---------------
Purpose: one pass, run before any MCP session and any billable call, that either clears the run
or refuses it with plain lines an operator can act on (FR-45–47, FR-117, FR-135, FR-138, FR-255,
FR-281, FR-263, FR-283, FR-292, FR-295, FR-103, 30 §8). Callers get a verdict object, never a
scattering of booleans.

Public API: `check()` · `Preflight` · `collect_secrets()` · `resolve_briefs()` ·
`ensure_backends()` · `codex_needed()` · `provider_summary()` · `EXIT_PREFLIGHT`.

Invariants:
- **Refusal is free** (FR-202 code 2): every check here is local — env vars, config arithmetic,
  a template listing, one test file inside `output.dir`. Nothing external is contacted, and
  nothing is BILLED on any path; the one thing that leaves this process is D64's proxy start,
  which spends no money and talks only to 127.0.0.1.
- **`check()` is synchronous and stays synchronous.** It runs inside the event loop, so it may
  never wait on a socket or a subprocess. D64's Codex proxy needs 10–25 s to start, so the wait
  lives in `ensure_backends()` — an `async` sibling the caller awaits IMMEDIATELY BEFORE `check()`
  — and `check()` reads only the result (`codex_proxy.current_handle()`). One rule, two calls:
  anything that can block goes in the coroutine, every VERDICT is reached in `check()`.
- **A key is required only when its door is the one this run uses (D64).** `OPENROUTER_API_KEY`
  is a refusal under `llm_backend: openrouter` and irrelevant under `codex`; `KIE_API_KEY` the
  same for `render_provider`. Redaction is untouched by that gating — `collect_secrets()` still
  masks every secret present in the environment, used or not.
- **Two failure grades, deliberately.** An *error* refuses the run; a *warning* or *hint* lets it
  proceed. Missing `NOTION_TOKEN` is the canonical warning (FR-47: influence drops to `off`), an
  out-of-range `reel_duration_s` the canonical clamp (FR-103) — nothing is silently sent to a
  provider to fail after payment.
- **The config is normalized here, in place, and says so**: the FR-103 clamp and FR-47's forced
  `notion_influence: off` are written onto the `Config` the rest of the run reads, so no later
  stage re-derives them.
- **Profiles, styles and the cross-key config pairs are checked through their owners** —
  `render.get_profile()` for FR-281, `prompts_engine.validate_template_set()` for FR-263,
  `styles.load_registry()` + `styles.validate()` for FR-295, and `config.windows_violation()` +
  `config.formats_sourcing_violation()` for FR-307/§0.14e. This module never re-derives a required
  template name, a registry rule or a refusal sentence; a second copy is how they drift. What it
  DOES own is the grading: an error from any of those owners is a refusal here, a warning is
  printed and the run proceeds.
- **The two config PAIRS are re-checked here because flags mutate the config after it loaded.**
  `config._validate` runs at LOAD time; `--history-days 7` and `--images 4` are applied afterwards
  (`cli.apply_overrides`), so a flag can walk a legal file into an illegal pair that the loader
  has already waved through. FR-138 lists both among the things pre-flight validates before the
  confirm prompt, and this is the only door left that both of them pass through.
- **The style registry has no fallback tier** (D41/FR-295, unlike every other prompt artifact):
  missing, unreadable or unparseable is the same refusal as invalid, because the registry is the
  run's visual authority and a built-in copy would be silent drift against the file being edited.
- **Secrets are read, never returned to a prompt.** `collect_secrets()` hands the *values* to
  `LogWriter`'s redaction set and to nothing else (D30).

Do not: open a session, call a provider, load a config file (the caller owns that), or turn a
warning into an abort — a run that can still deliver something must be allowed to.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from hypesocials import briefs, codex_proxy, styles
from hypesocials.budget import critic_price_gap
from hypesocials.gauntlet import CRITIC_TEMPLATES as _CRITIC_TEMPLATES
from hypesocials.util import read_text, wrapped
from hypesocials.config import Config, formats_sourcing_violation, windows_violation
from hypesocials.models import PlanEntry
from hypesocials.plan import BriefRequest
from hypesocials.prompts_engine import PROMPTS_DIR, PromptEngine, validate_template_set
from hypesocials.render import UnknownProfileError, get_profile
from hypesocials.sources import SOURCE_STATUS

EXIT_PREFLIGHT = 2

#: The three keys FR-46 can refuse on, plus FR-47's optional one. Values never leave this module
#: except through `collect_secrets()`, which feeds the logger's redaction set (D30). Two of the
#: three are now CONDITIONAL (SESSION O/D64): a key is only required when the door it opens is the
#: one this run leaves through — see `_needed_secrets()`. The descriptions say which door.
REQUIRED_SECRETS: dict[str, str] = {
    "VIRLO_API_KEY": "Virlo trend discovery",
    # `analysis` is the VISION CHECK's role post-pivot (D41): the style-brief call is gone, the
    # Sonnet key is not. D64: this is the OPENROUTER door's key — under `llm_backend: codex` the
    # same three roles ride the local proxy on the operator's subscription and need no key at all.
    "OPENROUTER_API_KEY": "the OpenRouter door every LLM role rides (models.llm_backend: openrouter)",
    "KIE_API_KEY": "the Kie.ai render door (models.render_provider: kie) — images and reels",
}
OPTIONAL_SECRETS: tuple[str, ...] = ("NOTION_TOKEN", "POSTIZ_API_KEY", "HANDLE_HASH_KEY")

#: Which secrets each action can actually spend against — `--list-monitors` needs one key and no
#: plan at all (FR-251), a source preview never reaches an LLM, a full run needs all three. This is
#: the ACTION half of the answer; `_needed_secrets()` then drops whichever keys this config's
#: backend choices make irrelevant.
_NEEDED: dict[str, tuple[str, ...]] = {
    "run": ("VIRLO_API_KEY", "OPENROUTER_API_KEY", "KIE_API_KEY"),
    "preview-analysis": ("VIRLO_API_KEY", "OPENROUTER_API_KEY"),
    "preview-sources": ("VIRLO_API_KEY",),
    "list-monitors": ("VIRLO_API_KEY",),
}
#: Which config choice makes each metered key required (D64). A key absent from this map — Virlo's
#: — is required on every path that lists it, because there is no second door to trends.
_SECRET_DOOR: dict[str, tuple[str, str]] = {
    "OPENROUTER_API_KEY": ("llm_backend", "openrouter"),
    "KIE_API_KEY": ("render_provider", "kie"),
}
#: The one image model the Codex proxy renders with (D64). Named here rather than read off
#: `models.image`, which carries Kie's ROUTE names (`gpt-image-2-text-to-image`) and not a proxy id.
CODEX_IMAGE_MODEL = "gpt-image-2"
#: What the proxy actually returns, measured 2026-08-21. `platforms.<name>.image_resolution` is a
#: Kie knob (FR-342) and the proxy honours no tier at all, so a `2k` config renders at this and the
#: operator is told so before the gate rather than after the download.
CODEX_IMAGE_PX = 1254

MIN_PYTHON = (3, 12)
REEL_DURATION_RANGE = (4, 30)  # FR-103 / 20 FR-164 — the provider's verified continuous range
#: 40 FR-86's per-asset figures, used only to size the FR-255 free-space comparison. PER SLIDE for
#: `carousel` — the footprint sum multiplies this by `slide_count`, so a per-deck figure here
#: over-estimated a five-slide deck five-fold.
_ASSET_BYTES = {"image": 300_000, "carousel": 300_000, "reel": 20_000_000}
#: run.log + events.jsonl are ≈50–200 KB (40 FR-86); the rest is the gallery and the run-level
#: refs/ folder. Deliberately not generous: an over-estimate refuses a run that would have fit.
_RUN_OVERHEAD_BYTES = 2_000_000
_PROBE_FILE = ".hypesocials-disk-probe"
#: `sources/notion.py`'s `SERVER_NAME` and the command inside its private `_DEFAULT_SERVER` — the
#: entry used when a config names no `notion:` server at all. Replicated rather than imported
#: because that default is private to its module; if it changes there, change it here (FR-117).
_NOTION_SERVER = "notion"
_NOTION_DEFAULT_COMMAND = "npx --no-install @notionhq/notion-mcp-server"
#: Mirrors `config._HEX` — same reason as the two lines above: it is private to its module, and
#: this is the backstop for a `Config` the loader never validated (`_check_branding`).
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
#: FR-292: `#F97316` is the WEB palette's orange and ships in neither brand profile. It is a
#: warning rather than a refusal — a wrong-but-renderable colour, not a broken run.
_WEB_ONLY_ORANGE = "#F97316"
#: The one template whose `prompts_dir` override can degrade a run in silence, and the slot that
#: says whether the copy is current (v2.2.0). Named here rather than imported: `topic_filter` owns
#: the role name for its own call and `prompts_engine` owns the vocabulary, but neither exports a
#: "which override is stale" list, and inventing one for a single row would be a registry.
_SCREEN_TEMPLATE = "topic_filter_system.md"
_AUDIENCE_SLOT = "audience_profile"


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
        """Everything worth printing, in refusal-first order; empty when the run is clean.

        Wrapped at the printer (FR-286): several hints run to sentence length, and this property
        is the one place every grade passes through — wrapping in the data would put layout into
        strings that also land in events.jsonl.
        """
        lines: list[str] = []
        for prefix, group in (("pre-flight refused: ", self.errors),
                              ("warning: ", self.warnings), ("hint: ", self.hints)):
            for item in group:
                lines += [part if first else f"  {part}"
                          for first, part in wrapped(f"{prefix}{item}", 76)]
        return "\n".join(lines)


#: Why the last `ensure_backends()` could not produce a proxy — one sentence, or empty. A module
#: cell for the same reason `codex_proxy` keeps its handle in one: the awaited starter and the
#: synchronous check that reports its failure are two calls at two different points of the run, and
#: the operator needs the REASON ("Node/npx was not found on PATH") and not just the symptom.
_PROXY_FAILURE: str = ""


def codex_needed(config: Config, action: str = "run") -> bool:
    """Does this action, on this config, need the local Codex proxy running? (D64)

    The runner's gate for whether to await `ensure_backends()` at all — and the same predicate
    `_check_codex` uses to decide whether it has anything to say, so the starter and the checker
    can never disagree about which runs need a proxy.

    The two doors have DIFFERENT reaches, which is the whole content of this function.
    `--preview-analysis` really does make LLM calls (that is what it previews), so the LLM door
    needs its proxy there. It renders nothing at all, so the RENDER door does not — refusing a $0
    preview because no image endpoint is up would break the cheapest way to check a config, which
    is FR-251's posture. `--list-monitors` and `--preview-sources` reach neither.
    """
    return ((action in ("run", "preview-analysis") and str(config.models.llm_backend) == "codex")
            or (action == "run" and str(config.models.render_provider) == "codex"))


async def ensure_backends(config: Config, *, action: str = "run", log: Any = None) -> str:
    """Start (or find) the Codex proxy this run needs. Await this IMMEDIATELY BEFORE `check()`.

    The one asynchronous thing pre-flight does, and it is deliberately not inside `check()`:
    `check()` is synchronous, is called from inside the running event loop, and is documented as
    local and instant. Starting `npx openai-oauth@latest` takes 10–25 s. So the two are split —
    this coroutine does the waiting, records its outcome, and `check()` reads the result out of
    `codex_proxy.current_handle()` in the same breath as every other refusal.

    Never raises, deliberately. A failure here is not an exception the caller has to catch and
    translate: it is a pre-flight FINDING, and `_check_codex` writes it as one, at exit 2 with $0
    spent, alongside anything else that is also wrong with this run. Calling `check()` without
    calling this first is safe too — it simply refuses, because there is no handle.

    A no-op (returns `""`) on any run whose doors are both metered, and on `--list-monitors` /
    `--preview-sources`, which never reach an LLM.

    Args:
        config: the loaded, flag-overridden config. `models.llm_base_url` is the endpoint.
        action: the same action string `check()` will be given.
        log: the run's `LogWriter`, when one exists; the proxy's start/ready lines go there.

    Returns:
        `""` when a proxy is ready (or none was needed), otherwise the one-sentence reason it is
        not — already recorded for `check()`, so most callers can ignore the return value.
    """
    global _PROXY_FAILURE
    _PROXY_FAILURE = ""
    if not codex_needed(config, action):
        return ""
    try:
        await codex_proxy.ensure_proxy(config.models.llm_base_url, log=log)
    except (codex_proxy.ProxyUnavailable, ValueError) as exc:
        _PROXY_FAILURE = str(exc)
    except Exception as exc:  # noqa: BLE001 — a starter that raises must not crash a pre-flight
        _PROXY_FAILURE = f"{type(exc).__name__}: {exc}"
    return _PROXY_FAILURE


def provider_summary(config: Config) -> tuple[str, ...]:
    """The console lines naming the DOORS this run leaves through — LLM first, renders second.

    Written for the launch block rather than as a finding: it is not a problem, it is the single
    most consequential fact about what a run will cost, and after D64 it is no longer inferable
    from the config's model ids alone (`gpt-image-2` is a Kie route name AND a proxy id). An
    operator reading `codex gpt-image-2 ($0, subscription)` knows why the estimate is small; the
    same operator reading a $6 estimate knows the pivot did not take.

    Laid out on `_launch_summary`'s own 14-character label column and wrapped to FR-286's 78
    columns, so the caller can drop the lines straight into that block. That is why the return is
    a variable-length tuple rather than exactly two strings: a run with three critic ids on the
    subscription door needs a continuation line, and truncating it would hide the id that is
    wrong on exactly the run where somebody is looking for it.

    No secret, no key, no token — not even a masked one. The lines name a provider, a loopback
    host and model ids, all of which are already written in the config file (D30).
    """
    models = config.models
    if str(models.llm_backend) == "codex":
        host = urlsplit(models.llm_base_url).netloc or models.llm_base_url
        llm = f"codex via {host} · $0, subscription · " + _role_clause(config)
    else:
        llm = "openrouter · " + _role_clause(config)
    if str(models.render_provider) == "codex":
        render = (f"codex {CODEX_IMAGE_MODEL} · $0, subscription · fixed ~{CODEX_IMAGE_PX} px · "
                  "no video")
    else:
        render = f"kie · {models.image_profile} images · {models.video_profile} video"
    return (*_summary_lines("llm", llm), *_summary_lines("render", render))


def _role_clause(config: Config) -> str:
    """`analysis <id> · copy <id> · critic <id>` — the roles that will really be called.

    Role names rather than config keys, because this line is read as prose ("what is doing the
    thinking") and not as an edit target; the refusals in `_check_codex` are where a key belongs.
    The critic is named only when the gauntlet is on, for the same reason it is only CHECKED then.
    """
    models = config.models
    clauses = [f"analysis {models.analysis}", f"copy {models.copy}"]
    if config.run.gauntlet.enabled:
        clauses.append(f"critic {models.critic or models.analysis}")
    return " · ".join(clauses)


def _summary_lines(label: str, text: str) -> list[str]:
    """One labelled fact, packed onto as many ≤78-column lines as it needs (FR-286)."""
    return [f"  {label if first else '':<10}  {part}" for first, part in wrapped(text, 64)]


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
    entries: Sequence[PlanEntry] = (),
    briefs_errors: Sequence[str] = (),
) -> Preflight:
    """The whole pre-flight pass. Mutates `config` where the PRD says to normalize, not refuse.

    Args:
        config: the loaded, flag-overridden run config. `run.reel_duration_s` is clamped into
            4–30 (FR-103) and `run.notion_influence` is forced to `off` when `NOTION_TOKEN` is
            absent (FR-47) — both in place, both reported as warnings.
        action: `run` | `preview-analysis` | `preview-sources` | `list-monitors`; picks which
            secrets are genuinely required (FR-46, FR-202's `--list-monitors` row) and which
            checks apply at all — the style registry (FR-295) and the branding block (FR-292) are
            read only on the paths that actually assign a style, and D64's Codex proxy check only
            on the two that reach an LLM.
        entries: the expanded plan — sizes FR-255's disk footprint and tells FR-283's supply
            check which creatives need a trend at all.
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
    _check_sources(config, errors, warnings)
    _check_config_pairs(config, action, entries, errors)
    _check_supply(config, action, entries, errors, warnings)
    _check_profiles(config, action, errors)
    _check_prompt_overrides(config, action, warnings)
    _check_gauntlet(config, action, errors, warnings)
    _check_codex(config, action, entries, errors, warnings, hints)
    _check_styles(config, action, errors, warnings)
    _check_branding(config, action, errors, warnings)
    _check_node(config, errors)
    _clamp_reel_duration(config, warnings)
    _check_prices(config, errors, warnings)
    _check_language_mode(config, entries, warnings)
    _check_language_hint(config, entries, hints)
    footprint = _check_disk(config, entries, errors)

    return Preflight(
        ok=not errors, errors=tuple(errors), warnings=tuple(warnings), hints=tuple(hints),
        secrets=collect_secrets(), estimated_bytes=footprint)


# --------------------------------------------------------------------------- individual checks


def _needed_secrets(config: Config, action: str) -> tuple[str, ...]:
    """Which env vars THIS action, on THIS config, genuinely cannot run without (FR-46 + D64).

    Two questions, answered in order. First the action: `--list-monitors` needs one key and no plan
    at all (FR-251), a source preview never reaches an LLM. Then the DOOR each key opens — SESSION
    O gave both metered providers a subscription twin, and a key for a provider this run will never
    contact is not a missing requirement, it is an irrelevant one. Under `llm_backend: codex` every
    LLM role rides the local proxy on the operator's ChatGPT sign-in, so `OPENROUTER_API_KEY` is not
    consulted; under `render_provider: codex` the same is true of `KIE_API_KEY`. Refusing on either
    would make the whole point of the pivot unreachable — a workstation with no metered keys at all
    is exactly the configuration D64 exists to serve.

    `VIRLO_API_KEY` is in no door map and is therefore unconditional: there is one source of trends
    and no subscription substitutes for it.

    Note what this does NOT touch: `collect_secrets()` still hands the logger every secret VALUE
    present in the environment (D30). Gating changes what is REQUIRED, never what is REDACTED — a
    key left in `.env` from last week must still be masked in this week's logs whether or not this
    run has any use for it.
    """
    doors = {"llm_backend": str(config.models.llm_backend),
             "render_provider": str(config.models.render_provider)}
    return tuple(name for name in _NEEDED.get(action, _NEEDED["run"])
                 if name not in _SECRET_DOOR
                 or doors[_SECRET_DOOR[name][0]] == _SECRET_DOOR[name][1])


def _check_secrets(config: Config, action: str, errors: list[str], warnings: list[str]) -> None:
    """FR-45/46: refuse on a missing required key, naming the variable. FR-47: Notion degrades."""
    for name in _needed_secrets(config, action):
        if not os.environ.get(name, "").strip():
            errors.append(f"{name} is not set — {REQUIRED_SECRETS[name]} cannot run without it. "
                          "Put it in .env in the repo root (FR-46)")
    if config.run.notion_influence != "off" and not os.environ.get("NOTION_TOKEN", "").strip():
        warnings.append(f"NOTION_TOKEN is not set — notion_influence "
                        f"{config.run.notion_influence!r} drops to 'off' for this run (FR-47)")
        config.run.notion_influence = "off"  # type: ignore[assignment]


def _check_sources(config: Config, errors: list[str], warnings: list[str]) -> None:
    """FR-135: a named-but-unbuilt adapter refuses HERE, not with a warning after the confirm gate.

    `SOURCE_STATUS` is the one registry of what exists (FR-121) — never a second list. The wording
    mirrors the menu picker's refusal, which is the same verdict reached one step earlier.
    """
    active = list(dict.fromkeys(config.sources.active))
    unbuilt = [name for name in active if not SOURCE_STATUS.get(name, False)]
    if not unbuilt:
        return
    named = ", ".join(unbuilt)
    if len(unbuilt) < len(active):  # something built remains: the run can still deliver
        warnings.append(f"sources.active names {named}, which is not built yet — dropped for this "
                        "run (FR-135)")
        return
    errors.append(f"sources.active: {named} is named for a future adapter and is not built yet — "
                  "pick virlo (D20/FR-135)")


def _check_config_pairs(config: Config, action: str, entries: Sequence[PlanEntry],
                        errors: list[str]) -> None:
    """FR-138/FR-307/§0.14e: re-run the two CROSS-KEY refusals against the FLAG-OVERRIDDEN config.

    Both pairs are validated when the file loads, and both can be broken afterwards: `cli.py`
    applies `--history-days`, `--images`, `--reels` and friends onto the `Config` object *after*
    `load_config` returned, and nothing re-validates it. `--history-days 7` against a 30-day fetch
    window is exactly the repeat FR-307 exists to prevent, and it would have loaded clean. So the
    same two predicates run again here, on the object the run will actually use, and their wording
    comes from `config.py` — one sentence, two doors.

    The §0.14d carve-out for the formats guard: at LOAD time no plan exists, so the guard reads
    `run.formats`; at PRE-FLIGHT the expanded plan is in hand, and an image or reel entry running
    under an `override`-influence brief binds no source post at all (FR-144) — it needs no video
    sourcing and must not refuse a run. So the counts handed to the predicate are the entries that
    will really draw on the Virlo pool. An EMPTY `entries` (a caller that has no plan yet) falls
    back to the raw config counts, which is exactly the load-time question.

    Scope: `run` and `preview-analysis`. `--preview-analysis` reaches both stages the pairs govern
    — the fetch gate's used-post drop (FR-305/307) and the affinity assignment §0.14e is about —
    and it spends real OpenRouter money doing it, so it is not a free cure path. `--list-monitors`
    and `--preview-sources` are exempt on FR-251's precedent: they are $0 diagnostics an operator
    runs to FIX a config, and a config error must never disarm its own cure.
    """
    if action not in ("run", "preview-analysis"):
        return
    for violation in (windows_violation(config),
                      formats_sourcing_violation(config, counts=_sourced_counts(entries))):
        if violation:
            errors.append(violation)


def _sourced_counts(entries: Sequence[PlanEntry]) -> dict[str, int] | None:
    """Image/reel creatives in this plan that will actually consume a topic — or `None`.

    `None` means "no plan to speak of", and the formats guard then judges `run.formats` exactly as
    the loader does. Override-brief entries are excluded per §0.14d/FR-144: they bind no source
    post, so slideshow-only sourcing cannot starve them.
    """
    if not entries:
        return None
    counts = {"image": 0, "reel": 0}
    for entry in entries:
        if entry.creative_format in counts and entry.brief_influence != "override":
            counts[entry.creative_format] += 1
    return counts


def _check_supply(config: Config, action: str, entries: Sequence[PlanEntry],
                  errors: list[str], warnings: list[str]) -> None:
    """FR-283: an active source that cannot supply one trend refuses HERE, before the money gate.

    Empty `virlo_monitor_ids` makes Virlo arithmetically incapable of returning a trend (20 §3),
    and that is knowable from the config alone — so it must never be discovered after the
    operator has approved a spend. Grade follows what the run can still deliver: nothing at all
    is an error; briefs plus dropped trend creatives is a warning, because 10 §10 ships those
    briefs and exits 1. Two carve-outs are load-bearing: `--list-monitors` is the cure and must
    keep working with no runnable plan at all (FR-251), and an all-override plan needs no trend
    and is never refused (FR-144). `blend` briefs still need a trend, so only `override` exempts.
    """
    if action != "run" or "virlo" not in config.sources.active:
        return
    if any(str(monitor_id).strip() for monitor_id in config.sources.virlo_monitor_ids):
        return
    dropped = [entry.asset_id for entry in entries if entry.brief_influence != "override"]
    if entries and not dropped:  # brief-only: no trend consumed, no Virlo session, nothing to refuse
        return  # an EMPTY plan is not brief-only and falls through: it cannot deliver either
    if len(dropped) < len(entries):  # some override brief survives: exit 1 with briefs, not exit 2
        named = ", ".join(dropped[:3]) + (f" +{len(dropped) - 3} more" if len(dropped) > 3 else "")
        warnings.append(f"sources.virlo_monitor_ids is empty, so {len(dropped)} creative(s) that "
                        f"need a trend will be dropped and only your briefs ship: {named} — run "
                        "run.bat --list-monitors to get your monitor ids")
        return
    errors.append("sources.virlo_monitor_ids is empty, so virlo cannot return a single trend and "
                  "not one planned creative can be made — run run.bat --list-monitors to print "
                  "your monitor ids, then paste them into your config")


def _check_profiles(config: Config, action: str, errors: list[str]) -> None:
    """FR-281/FR-272 + FR-263: an unknown profile, or one with no template set, is exit 2."""
    if action in ("list-monitors", "preview-sources"):
        return  # no render model is reached on these paths
    overrides = [config.prompts_dir] if config.prompts_dir else []
    for key, name, model in (("models.image_profile", config.models.image_profile,
                              config.models.image),
                             ("models.video_profile", config.models.video_profile,
                              config.models.video)):
        try:
            profile = get_profile(name)
        except UnknownProfileError as exc:
            # FR-272 wants all three named: the key, the model id, the missing profile.
            errors.append(f"{key}: {exc} — a model FAMILY change needs its profile implemented "
                          f"before the run; the configured model is {model!r} (FR-281/FR-272)")
            continue
        missing = validate_template_set(profile.name, override_dirs=overrides)
        if missing:
            errors.append(f"{key}: profile {profile.name!r} is missing its prompt template set — "
                          f"{', '.join(missing)} (FR-263); add them under prompts/")


def _check_prompt_overrides(config: Config, action: str, warnings: list[str]) -> None:
    """FR-174 seam hygiene: a `prompts_dir` override that predates a slot the engine now fills.

    One warning, and deliberately only one, because only one override can degrade a run SILENTLY.
    The screen's system prompt (`topic_filter_system.md`) gained `{{audience_profile}}` in v2.2.0 —
    the run's own audience, which is what lets the model report a topic's `language` and its
    `audience_fit`. An override copied before that slot existed still renders, still screens, and
    still answers: it simply answers those two fields from nothing, so `_apply` degrades exactly as
    it does for an unavailable model (`filter_degraded`, fail-open per §1.5) and off-language,
    off-audience topics start passing the screen again. Nothing errors, nothing is logged as
    broken, and the operator's own file is the cause — which is precisely the shape a pre-flight
    warning exists for.

    A WARNING, never a refusal: the screen is fail-open by contract, the run still ships, and
    refusing here would let a stale prompt file cost a scheduled batch (FR-252's posture).

    Only `config.prompts_dir` is inspected. The shipped `prompts/` tree is this repo's own artifact
    and is versioned with the code that reads it; if IT lacked the slot, the cure is a commit, not
    an operator warning. Unreadable is silence too — `PromptEngine` already warns about that on the
    FR-183 fallback path, and a second line about the same file helps nobody.
    """
    if action in ("list-monitors", "preview-sources") or not config.prompts_dir:
        return
    path = Path(config.prompts_dir) / _SCREEN_TEMPLATE
    if not path.is_file():
        return  # no override for this role: the shipped template is in force, and it is current
    try:
        text = read_text(path)
    except OSError:
        return
    if f"{{{{{_AUDIENCE_SLOT}}}}}" in text:
        return
    warnings.append(
        f"{path} is a prompts_dir override that never names {{{{{_AUDIENCE_SLOT}}}}} — it predates "
        "the v2.2.0 topic screen, so the model is not shown who this run writes for and its "
        "language / audience_fit answers degrade to permissive defaults (off-language and "
        "off-audience topics can pass). The run still screens and still ships; to restore the "
        f"full screen, copy the current prompts/{_SCREEN_TEMPLATE} and re-apply your edits")


def _check_gauntlet(config: Config, action: str, errors: list[str],
                    warnings: list[str]) -> None:
    """D49/FR-322–330: can the post-render gate actually RUN, and can its spend be quoted?

    Three findings, graded the way the rest of this module grades: a gate that cannot render its
    own prompt is a REFUSAL (the run would pay for renders and then drop every critic as
    unavailable, shipping unjudged work while the estimate promised a gate); a gate with every
    critic switched off is a refusal for the same reason stated more plainly — `enabled: true` with
    nothing enabled describes a run that will spend nothing on the thing it says it does, and the
    honest spelling of that is `enabled: false`; an unpriced `models.critic` is a WARNING and never
    a refusal (FR-282), because the run can still deliver — it just cannot quote its critic spend,
    and `budget.critic_price_gap` writes that whole sentence itself.

    Numeric bounds are `config._BOUNDS`' job and are already a load-time `ConfigError`, so nothing
    is re-checked here. Prompt files are resolved through the ENGINE, which means a `prompts_dir`
    override is honoured and an FR-183 built-in counts as present — a missing FILE is not a finding
    when the shipped fallback is byte-identical to it.

    Skipped where no render ever happens: `--list-monitors` (FR-251's cure for a broken config)
    and `--preview-sources` (FR-139's $0 blocklist preview) judge nothing and pay for nothing.
    """
    if action in ("list-monitors", "preview-sources"):
        return
    gate = config.run.gauntlet
    if not gate.enabled:
        return
    if not [name for name, critic in gate.critics.items() if critic.enabled]:
        errors.append("run.gauntlet.enabled is true but every critic under run.gauntlet.critics "
                      "is disabled — the gate would judge nothing while the estimate quotes it. "
                      "Enable at least one of brief/system/craft, or set gauntlet.enabled: false "
                      "(D49/FR-322)")
        return
    engine = PromptEngine(prompts_dir=config.prompts_dir)
    for name, critic in sorted(gate.critics.items()):
        if not critic.enabled:
            continue
        role = _CRITIC_TEMPLATES.get(name, "")
        try:
            engine.template(role)
        except (LookupError, OSError, ValueError) as exc:
            errors.append(f"run.gauntlet.critics.{name} is enabled but its prompt {role} cannot be "
                          f"resolved ({exc}) — the critic would be dropped on every deck and the "
                          "gate would ship unjudged work it was priced for (FR-183/FR-322)")
    if gap := critic_price_gap(config):
        warnings.append(gap)


def _check_codex(config: Config, action: str, entries: Sequence[PlanEntry],
                 errors: list[str], warnings: list[str], hints: list[str]) -> None:
    """D64: when either door is `codex`, prove the local proxy can serve THIS run — or exit 2.

    Three findings, and the order is the order an operator can act on them.

    1. **Is there a proxy at all?** This function is SYNCHRONOUS, like every other check here, so
       it does not start anything — `ensure_backends()` above did that, before `check()` was
       called, and left its handle in `codex_proxy.current_handle()`. No handle (or a handle with
       an empty model list) means the endpoint is not there and could not be made to be, which is
       an FR-295-shaped refusal: exit 2, $0 spent, and the cure printed rather than implied. The
       whole point of starting the proxy from pre-flight is the unattended run — a scheduled
       `--yes` batch has nobody at the keyboard to notice a missing window.

    2. **Are the configured model ids ids the proxy actually has?** This is the misconfiguration
       that D64 will produce over and over: `models.analysis` still says
       `anthropic/claude-sonnet-5`, which is an OpenRouter id and means nothing to the proxy. It
       is a refusal rather than a warning because there is no degraded version of it — the call
       would 404 at the first analysis and every stage after it would run on nothing. The refusal
       names the key, the id, and the ids that DO exist, because "unknown model" without the list
       is a search, not a fix.

       Only the roles this run can really call are judged. `analysis` and `copy` always run; the
       critic ids are judged only when the gauntlet is on and that critic is enabled, since a
       switched-off critic's model is never resolved and refusing on it would refuse a run for a
       call that cannot happen.

    3. **Reels.** There is no subscription path for video: the proxy renders `gpt-image-2` and
       nothing else. A plan that wants a reel under `render_provider: codex` is refused here
       rather than half-delivered, and the cure is in the sentence.

    4. **Shape.** The proxy answers ~1254x1254 to every `size` it is sent, so a creative planned
       at FR-21's 4:5 (Instagram/LinkedIn images) ships SQUARE. That is a WARNING, not a refusal:
       a square post is a real, publishable creative and refusing the run would be worse than
       delivering it — but it changes what the operator gets, and silence would let them find out
       from the folder. One line per distinct ratio, counted, so a mixed plan says which part of
       it is affected. Reels are excluded because arm 3 already refused them outright, and one
       event should produce one finding.

    Plus one informational line, never a finding's grade: the proxy returns a fixed ~1254 px frame
    whatever `platforms.<name>.image_resolution` says (FR-342 is a Kie knob). The operator approves
    a plan at the Confirm gate; they should know what size the pixels will be before they do,
    not after they open the folder.

    Scope is per DOOR, not per action: the LLM door is judged on `run` and `--preview-analysis`
    (both make LLM calls), the render door on `run` alone (a preview renders nothing).
    `--list-monitors` and `--preview-sources` reach neither and must never be refused by a door
    they never open — the FR-251 posture, applied to a new provider.
    """
    llm_codex = (action in ("run", "preview-analysis")
                 and str(config.models.llm_backend) == "codex")
    render_codex = action == "run" and str(config.models.render_provider) == "codex"
    if not (llm_codex or render_codex):
        return  # `codex_needed()` is the same predicate — see its docstring for the two reaches

    handle = codex_proxy.current_handle()
    if handle is None or not handle.models:
        detail = f" ({_PROXY_FAILURE})" if _PROXY_FAILURE else ""
        errors.append(f"Codex proxy not reachable at {config.models.llm_base_url} and could not be "
                      f"started{detail} — run `npx openai-oauth@latest` and sign in once with "
                      "`codex login` (D64)")
        return
    available = list(handle.models)
    listed = ", ".join(available)

    if llm_codex:
        for key, model in _codex_llm_models(config):
            if model not in available:
                errors.append(f"{key} is {model!r}, which this proxy does not serve — "
                              f"{config.models.llm_base_url} offers {listed}. An id with a vendor "
                              "prefix is the OpenRouter name and never reaches the subscription "
                              "door (D64)")
    if render_codex:
        if CODEX_IMAGE_MODEL not in available:
            errors.append(f"models.render_provider is 'codex' but the proxy does not serve "
                          f"{CODEX_IMAGE_MODEL!r} — it offers {listed}; nothing in this run could "
                          "be rendered (D64)")
        # `entries` is the expanded plan when the caller has one; an empty plan falls back to
        # the configured counts, which is the same question asked one step earlier.
        reels = (sum(1 for entry in entries if str(entry.creative_format) == "reel")
                 if entries else int(config.run.formats.get("reel", 0)))
        if reels:
            errors.append(f"{reels} reel(s) are planned but reels need the kie provider — no "
                          "subscription path renders video; set models.render_provider: kie, or "
                          "run with --reels 0 (D64)")
        else:
            hints.append(f"render_provider: codex renders every image at the proxy's fixed "
                         f"~{CODEX_IMAGE_PX} px whatever platforms.<name>.image_resolution asks "
                         "for, and bills $0 against the subscription rather than the spend cap "
                         "(D64/FR-342)")
        for ratio, count in _non_square_ratios(entries):
            warnings.append(f"codex renders square ~{CODEX_IMAGE_PX} px; {count} creative(s) "
                            f"asked for {ratio} and will ship 1:1")


def _non_square_ratios(entries: Sequence[PlanEntry]) -> list[tuple[str, int]]:
    """`(aspect ratio, how many creatives asked for it)` for every planned non-1:1 IMAGE shape.

    Read off `PlanEntry.aspect_ratio`, which is `plan._aspect_ratio`'s FR-21 answer (platform x
    format, config-overridable) and the same string the render payload carries — so this counts
    what was really ordered rather than re-deriving it from `config.platforms`. Carousels are 1:1
    and never appear; reels are dropped because `_check_codex` refuses them one arm earlier.
    Sorted by ratio so two identical plans report identically.
    """
    counts: dict[str, int] = {}
    for entry in entries:
        if str(entry.creative_format) == "reel":
            continue
        ratio = str(entry.aspect_ratio or "").strip()
        if ratio and ratio != "1:1":
            counts[ratio] = counts.get(ratio, 0) + 1
    return sorted(counts.items())


def _codex_llm_models(config: Config) -> list[tuple[str, str]]:
    """Every `(config key, model id)` pair this run can really send to the proxy.

    The critic rows follow the gauntlet's own resolution order (`critic.model or models.critic or
    models.analysis`) so the id checked here is the id the call would carry — checking
    `models.critic` while a per-critic override was in force would validate a string nobody sends.
    """
    models = config.models
    pairs = [("models.analysis", models.analysis), ("models.copy", models.copy)]
    gate = config.run.gauntlet
    if gate.enabled:
        for name, critic in sorted(gate.critics.items()):
            if not critic.enabled:
                continue
            resolved = str(critic.model or models.critic or models.analysis)
            key = f"run.gauntlet.critics.{name}.model" if critic.model else "models.critic"
            pairs.append((key, resolved))
    seen: dict[str, str] = {}
    for key, model in pairs:  # one row per distinct id: three critics on one model is one finding
        seen.setdefault(str(model), key)
    return [(key, model) for model, key in seen.items()]


def _check_styles(config: Config, action: str, errors: list[str], warnings: list[str]) -> None:
    """FR-295: the meta-style registry must load and must be able to dress this run, or exit 2.

    The registry is the post-pivot visual authority (D41), so this is the same posture FR-281 takes
    with a render profile: a run that cannot dress a requested format has nothing to render, and
    discovering it after the confirm gate would cost the operator money for nothing. There is no
    built-in tier, so "no `styles.yaml` anywhere" is a refusal, not a degradation — `load_registry`
    writes that whole line itself, naming every folder it looked in.

    Grading is `styles.validate()`'s, not this module's (10 §FR-290's validation table): zero
    usable styles under the active brand or a requested format with no affine style are errors;
    fewer than three usable styles, an over-long `render_prompt`, a `list_mode` whose triggers are
    both off and an unresolved "either/or" choice are warnings. A MALFORMED `list_mode` (FR-304b,
    v2.2.0) arrives through the `StyleRegistryError` branch above rather than the findings list —
    it is a shape the loader cannot turn into an object at all — and lands at the same exit 2 with
    $0 spent, which is the whole point of both routes. Post-D46 there is no reference-image finding at all — a meta-style is
    text-only DNA (FR-17/18), declares no pictures, and therefore has none that can be missing.

    The `config` handed over is the one CLI overrides already mutated (`cli.apply_overrides` runs
    before `check`), so `--styles` is graded here too: FR-314's unknown-key refusal and its
    "selection emptied this format's pool" refusal both arrive through this same call, at exit 2
    with $0 spent. That ordering is load-bearing — a selector checked at config LOAD time would
    never see the flag.

    Skipped where no style is ever assigned: `--list-monitors` prints monitor ids (FR-251) and
    `--preview-sources` is the $0 blocklist preview (FR-139) — refusing either on a registry they
    do not read would break the very commands an operator uses to fix a config.
    """
    if action in ("list-monitors", "preview-sources"):
        return
    try:
        registry = styles.load_registry([config.prompts_dir, PROMPTS_DIR])
    except styles.StyleRegistryError as exc:
        errors.append(str(exc))
        return
    registry_errors, registry_warnings = styles.validate(registry, config)
    errors.extend(registry_errors)
    warnings.extend(registry_warnings)


def _check_branding(config: Config, action: str, errors: list[str],
                    warnings: list[str]) -> None:
    """FR-292/FR-138: the brand selector resolves, its colours are colours, its ratio is a ratio.

    Mostly a BACKSTOP, deliberately: `config._validate` already fails the LOAD on a `brand` with no
    matching profile and on any malformed hex in any profile, and `_BOUNDS` rejects a `brand_ratio`
    outside 0–1 when the file names the key. Every one of those paths raises `ConfigError` before
    this module runs — for a config that came from a file. A `Config` built in code (a preview
    harness, a future flag, the menu handing back an edited object) never met that validator, and
    the first place a bad brand would otherwise surface is a paid render with the wrong colours or
    a blank signature. So the same three invariants are re-asserted here, scoped to the ACTIVE
    profile, and the operator gets the key to edit rather than a `KeyError` in the prompt engine.

    Two findings are genuinely new here, because they are runtime facts the loader cannot judge:
    a branded run whose profile carries no `wordmark` (nothing to sign with), and FR-292's
    web-only orange — a warning, since it is a colour choice the operator typed, not a broken run.
    The first of those is skipped outright while FR-318's `branding.enabled` is false; the
    invariants above it are still asserted, because a profile that is wrong stays wrong and the
    switch is one config edit away from making it billable.
    `--list-monitors` is exempt for FR-251's reason: it is the cure for a broken config and must
    never be refused by one.
    """
    if action == "list-monitors":
        return
    branding = config.branding
    if branding.brand not in branding.profiles:
        known = ", ".join(sorted(branding.profiles)) or "nothing — branding.profiles is empty"
        errors.append(f"branding.brand is {branding.brand!r} but branding.profiles defines "
                      f"{known} — the run cannot pick colours, a wordmark or a font for a brand "
                      "that is not described (FR-292)")
        return
    if not 0.0 <= branding.brand_ratio <= 1.0:
        errors.append(f"branding.brand_ratio is {branding.brand_ratio} — it is the FRACTION of "
                      "creatives that carry the wordmark, so it must sit between 0 and 1 (FR-292)")
    profile = branding.profiles[branding.brand]
    for key, value in profile.colors.items():
        listed = value if isinstance(value, list) else [value]
        for index, item in enumerate(listed):
            where = f"branding.profiles.{branding.brand}.colors.{key}"
            if isinstance(item, str) and not _HEX.match(item):
                errors.append(f"{where}{f'[{index}]' if isinstance(value, list) else ''} is "
                              f"{item!r}, which is not a hex colour like #34288B — a render prompt "
                              "quotes it verbatim, so this would be paid for and wrong (FR-292)")
            elif isinstance(item, str) and item.upper() == _WEB_ONLY_ORANGE:
                warnings.append(f"{where} is {item} — that orange is WEB-ONLY and belongs in no "
                                "brand asset; renders carrying it will not match the brand kit "
                                "(FR-292)")
    # FR-318: with the master switch off the wordmark is never rendered and `brand_ratio` never
    # evaluated, so an empty wordmark beside a non-zero ratio describes nothing this run will do.
    # Warning about it anyway would train the operator to ignore the branding warnings that DO
    # mean something the day they flip the switch back on. No new refusal is added here: the
    # switch removes work, it can never make a config unrunnable that was runnable before.
    if branding.enabled and branding.brand_ratio > 0 and not profile.wordmark.strip():
        warnings.append(f"branding.profiles.{branding.brand}.wordmark is empty but brand_ratio is "
                        f"{branding.brand_ratio} — those creatives would be 'branded' with nothing "
                        "to sign them; set the wordmark or set brand_ratio to 0 (FR-292)")


def _check_node(config: Config, errors: list[str]) -> None:
    """FR-117/138: Node is checked ONLY for a server this run will actually launch.

    Nothing outside the MCP commands is checked here, and post-pivot nothing else could be: the
    motion-reference download chain is withdrawn (v2.0.0/D41, D23 withdrawn with it), so the last
    non-MCP external binary this run might have wanted is gone. A Node-free workstation is a
    perfectly healthy one unless a configured MCP command literally invokes npx/node.

    A config that omits its `notion:` entry still launches Node: `sources/notion.py` falls back to
    its own default command. That command is checked too, so "not configured" never means
    "not checked" while `notion_influence` is on.
    """
    launched = [(name, str(entry.get("command", ""))) for name, entry
                in config.mcp_servers.servers.items()
                if not (name == _NOTION_SERVER and config.run.notion_influence == "off")]
    if config.run.notion_influence != "off" and _NOTION_SERVER not in config.mcp_servers.servers:
        launched.append((_NOTION_SERVER, _NOTION_DEFAULT_COMMAND))
    for name, raw_command in launched:
        command = raw_command.strip().lower()
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
    floor = config.min_single_creative_usd  # ONE derivation: the wizard warns with this same number
    if floor and config.run.spend_cap_usd < floor:
        errors.append(f"spend cap ${config.run.spend_cap_usd:.2f} is below the minimum "
                      f"single-creative cost of ${floor:.2f}, derived from "
                      "models.price_per_unit.image in your config — raise --budget or "
                      "spend_cap_usd (30 §8)")
    if config.run.formats.get("reel", 0) > 0 and not config.reels_plannable:
        warnings.append(f"reels were requested but {config.reel_price_key} is unset — the run "
                        "proceeds without reels (FR-131/FR-252); Seedance pricing is unpublished "
                        "(OQ-2)")


def _check_language_mode(config: Config, entries: Sequence[PlanEntry],
                         warnings: list[str]) -> None:
    """FR-345: under `target`, name the creatives translation cannot reach — once, as a warning.

    Translation is scoped to BOUND carousel decks (FR-343): the deck has a source post, that post
    has a language, and the panels are mapped one to one, which is what makes "translate these
    exact lines" a well-formed request. Nothing else in a run has that shape. An image or a reel
    quotes a hook or a caption through the ordinary selection path, and an override brief writes
    its own words from the brief file — so those creatives ship whatever language their material
    was in, on a run whose config says `target`.

    That gap is invisible everywhere else. The launch summary says "bound decks translated to en",
    the confirm screen says the same, and an operator reading either on a 4-image plan would
    reasonably expect four English images. Hence ONE warning, counted rather than listed: on a
    nine-creative plan the asset ids would run past the width and the number is the decision.

    Silent under `source`, which promises nothing to break, and silent under `target` when every
    creative in the plan is a bound deck — a warning that fires on the configuration rather than
    on the gap is the kind an operator learns to skip past.
    """
    if str(config.run.copy_language_mode) != "target":
        return
    unreached = sum(1 for entry in entries
                    if str(entry.creative_format) in ("image", "reel")
                    or entry.brief_influence == "override")
    if not unreached:
        return
    warnings.append(
        f"copy_language_mode: target reaches bound carousel decks only — {unreached} "
        "image/reel/override creative(s) ship their source language (FR-345)")


def _check_language_hint(config: Config, entries: Sequence[PlanEntry], hints: list[str]) -> None:
    """30 §2's diacritics hint, re-based for verbatim copy (§1.7 F22): recommend the check when
    this run may put accented glyphs on an image and nothing is looking at the result.

    Pre-pivot the rendered language WAS config's, so `cs` in `run.languages` was the whole trigger.
    Post-pivot on-image text is quoted verbatim from the source post, in the post's own language
    and never translated (FR-294/D42) — so at pre-flight nobody knows which alphabet this run will
    render, and an `en`-configured run that quotes a Czech post is the normal case, not an edge
    one. `config.languages` still decides brief-override creatives and the degrade paths, so a
    configured `cs` is a certainty where a verbatim creative is only a possibility: both earn the
    same hint, worded for which one fired.

    D54/FR-333: when `run.carousel_copy_mode` is `compress` and this plan has carousels, the hint
    states the compress contract instead — the same warning about unread accented glyphs, and the
    mode named where the operator is already reading about what this run will put on a frame.
    Compress makes the language question SHARPER, not softer: a compressed line is written by a
    model rather than copied byte for byte, so drifting out of the source's language is a failure
    mode verbatim mode simply does not have.

    D62/FR-353 adds `auto` to the same arm, because it raises the same question for the same
    reason: some of this run's slides will carry a model's line rather than the source's bytes. The
    hint names the MODE IN FORCE rather than saying "compress" for both, and for `auto` it says
    which panels are affected — only the ones over the assigned style's budget — because that is
    the difference an operator reading this line before the Confirm gate is actually deciding on.

    D63/FR-345 adds a clause rather than an arm. `copy_language_mode: target` does not change
    WHICH creatives may carry accented glyphs — the answer was already "possibly all of them,
    whatever run.languages says" — but it changes WHOSE glyphs they are: a translated slide is the
    copy model's own string, chosen for a language the source never wrote in, so a run configured
    `en` may now deliberately render Czech diacritics rather than only stumble into them. It is
    its OWN hint line, printed in addition to whichever of the three arms below fires, rather than
    a fourth arm in the `elif` chain: the three arms are mutually exclusive because they are three
    answers to "where does this run's on-image text come from", and translation is a second
    question about the same text. Making it an arm would have silenced the Czech line on exactly
    the run that needs it most — a `cs` config translating English posts into Czech.
    """
    if config.run.gauntlet.enabled:
        return
    czech = sorted({p for p in config.run.platforms
                    if "cs" in (config.language_for(p), config.onimage_language_for(p))})
    verbatim = any(entry.brief_influence != "override" for entry in entries)
    mode = str(config.run.carousel_copy_mode)
    compressing = (mode in ("compress", "auto")
                   and any(str(entry.creative_format) == "carousel"
                           and entry.brief_influence != "override" for entry in entries))
    translating = (str(config.run.copy_language_mode) == "target"
                   and any(str(entry.creative_format) == "carousel"
                           and entry.brief_influence != "override" for entry in entries))
    if translating:  # its own line, beside whichever arm fires below (see the docstring)
        hints.append("copy_language_mode: target translates a bound deck whose post is in "
                     "another language, so those slides carry the copy model's own words in "
                     "this run's language (FR-343) — a glyph the source never rendered is a "
                     "glyph nothing has proved renderable, and the gauntlet is off "
                     "(30 §2; a hint, never a gate)")
    if czech:
        hints.append(f"{', '.join(czech)} render Czech text and the gauntlet is off — Czech "
                     "diacritics are where GPT Image 2 struggles most; consider --gauntlet "
                     "(30 §2; a hint, never a gate)")
    elif compressing:
        contract = ("carousel_copy_mode: auto — only the panels over the style's budget are "
                    "compressed and the rest ship verbatim, FR-353" if mode == "auto"
                    else "carousel_copy_mode: compress, FR-331")
        hints.append("carousel on-image text is compressed from the source post's panels to the "
                     f"style's budget, in the post's own language ({contract}), so this run may "
                     "render accented glyphs whatever run.languages says "
                     "— with the gauntlet off nothing will read them back; consider --gauntlet "
                     "(30 §2; a hint, never a gate)")
    elif verbatim:
        hints.append("on-image text is quoted verbatim from the source post, in that post's own "
                     "language (FR-294), so this run may render accented glyphs whatever "
                     "run.languages says — with the gauntlet off nothing will read them back; "
                     "consider --gauntlet (30 §2; a hint, never a gate)")


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
    "CODEX_IMAGE_MODEL", "CODEX_IMAGE_PX", "EXIT_PREFLIGHT", "MIN_PYTHON", "OPTIONAL_SECRETS",
    "Preflight", "REEL_DURATION_RANGE", "REQUIRED_SECRETS", "check", "codex_needed",
    "collect_secrets", "ensure_backends", "provider_summary", "resolve_briefs",
]
