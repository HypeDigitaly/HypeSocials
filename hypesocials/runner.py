"""The lifecycle conductor — one run, stage by stage, in the order the PRD diagram draws them.

Module contract
---------------
Purpose: sequence a whole run and own everything that is true of the run rather than of one
creative — the run folder and its logs, the Confirm gate, the deadline, the spend summary, the
exit code, and the guarantee that every exit path leaves the disk, the pointers and the
subprocess tree in a defensible state.

Public API: `await run(opts, control)` · `await list_monitors(opts)` · `Control` ·
`decide_exit_code()` · the five `EXIT_*` codes.

Stage order is BINDING (00-overview §1, plan §0) and any reorder is a PRD conflict:

    Config → plan expansion → pre-flight → cost estimate → **Confirm** → Collect (Virlo MCP)
    → Select + assign → honesty restatement → Analyze → Write → Create → Package.

Collect and Select run *after* the confirmation, which is exactly why FR-8's one-line
restatement exists: trend supply can shrink a plan the operator already approved, and they are
told before generation proceeds rather than after delivery.

Invariants:
- **Money moves only after the gate.** Nothing before `cli.confirm_spend()` contacts a provider;
  `render.configure()` and the LLM client are built after it, so a decline costs $0 (FR-59).
- **Every timer is monotonic** (FR-243/108): the run deadline is `util.Deadline`, never a
  wall clock — this workstation sleeps and NTP steps its clock.
- **Cleanup runs on every exit path** (FR-249): scratch references, the render client, the
  download client, the LLM client and both log handles are released in a `finally`, and every
  subprocess kill tolerates `ProcessLookupError` — a real Ctrl+C is a console-wide event, so some
  children are already dead by the time cleanup runs (spikes/RESULTS.md §F).
- **Exit codes are a contract** (FR-202) and live in one function, `decide_exit_code()`.
- **The latest-pointer is only claimed by a run that packaged an asset** (FR-254/NFR-20).

Do not: render anything here (`generate/` owns that), price anything (`budget.py`), or reorder,
merge or re-gate a stage.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hypesocials import analyze, cli, copywrite, generate, plan, preflight, render, sources
from hypesocials.budget import Budget, Estimate, SpendCategory, SpendSummary, estimate, format_usd
from hypesocials.config import CONFIGS_DIR, Config, ConfigError, load_config
from hypesocials.llm import LLMClient, RoleSettings
from hypesocials.models import ParsedResult, PlanEntry, PlanEntryStatus, StyleBrief, TrendItem
from hypesocials.outputs import (
    Ledger,
    LogWriter,
    close_downloads,
    create_run_folder,
    read_history,
    record_trends,
    save_reference,
    set_latest,
    write_gallery,
)
from hypesocials.prompts_engine import PromptEngine
from hypesocials.util import Deadline, Stopwatch, new_run_id

logger = logging.getLogger(__name__)

# FR-202 — the whole contract, spelled once.
EXIT_OK = 0  # every planned creative was delivered
EXIT_PARTIAL = 1  # completed with at least one skip, failure, trim or abandonment
EXIT_PREFLIGHT = 2  # pre-flight refusal or config error, incl. a missing key — nothing spent
EXIT_NOTHING_USABLE = 3  # fatal after Collect began: no usable trend, or a transport-dead source
EXIT_INTERRUPTED = 4  # SIGINT (FR-201)

#: `logs/trend_history.json` is repo-global, not per run folder (40 §6, NFR-23).
LOGS_DIR = CONFIGS_DIR.parent / "logs"
_PROVISIONAL = "provisional-trend-"


@dataclass(slots=True)
class Control:
    """The two-stage Ctrl+C flags `__main__` owns and every stage checks (FR-201).

    `stop` means *stop ordering new work and package what exists*; `hard` is the second press,
    which `__main__` turns into an immediate exit. Nothing here waits on either — they are read
    between stages and before each submission, so an interrupt costs at most one in-flight job.
    """

    stop: asyncio.Event = field(default_factory=asyncio.Event)
    hard: asyncio.Event = field(default_factory=asyncio.Event)


class _Abort(Exception):
    """A run that ends before packaging: pre-flight refusal, decline, or a dead source."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class _Session:
    """One run's mutable context — built once, threaded everywhere, never global."""

    config: Config
    opts: cli.Options
    control: Control
    run_id: str
    run_dir: Path
    log: LogWriter
    ledger: Ledger
    deadline: Deadline
    clock: Stopwatch
    budget: Budget
    engine: PromptEngine
    llm: LLMClient | None = None
    render_ready: bool = False

    def say(self, text: str) -> None:
        """Print one operator-facing block and put the identical (redacted) text in run.log."""
        print(self.log.narrative(text))

    @property
    def halted(self) -> bool:
        """True once Ctrl+C landed or the soft run deadline elapsed (FR-108/201)."""
        return self.control.stop.is_set() or self.deadline.expired


# --------------------------------------------------------------------------- public actions


async def run(opts: cli.Options, control: Control | None = None) -> int:
    """Execute one full run and return its FR-202 exit code. Never raises for a run outcome."""
    control = control or Control()
    try:
        config = load_config(opts.config_name)
    except ConfigError as exc:  # one plain line, before any run_id exists (FR-69, 30 §8)
        print(f"config error: {exc}")
        return EXIT_PREFLIGHT
    overrides = cli.apply_overrides(config, opts)
    if refusal := cli.console_refusal(opts):
        print(refusal)
        return EXIT_PREFLIGHT

    session = _open(config, opts, control)
    try:
        return await _pipeline(session, overrides)
    except _Abort as abort:
        session.say(str(abort))
        return abort.code
    except Exception as exc:  # noqa: BLE001 — NFR-9: no unhandled crash; the log keeps the cause
        logger.exception("run failed")
        session.log.error("run_failed", f"unhandled error: {type(exc).__name__}: {exc}")
        session.say(f"run failed: {type(exc).__name__}: {exc} — see {session.run_dir}/run.log")
        return EXIT_PARTIAL
    finally:
        await _cleanup(session)


async def list_monitors(opts: cli.Options) -> int:
    """`--list-monitors` (FR-251): open one Virlo session, print id + name, exit. $0, no run folder."""
    try:
        config = load_config(opts.config_name)
    except ConfigError as exc:
        print(f"config error: {exc}")
        return EXIT_PREFLIGHT
    verdict = preflight.check(config, action="list-monitors")
    if verdict.report:
        print(verdict.report)
    if not verdict.ok:
        return EXIT_PREFLIGHT
    try:
        rows = await sources.list_monitors(config)
    except Exception as exc:  # noqa: BLE001 — a dead source is exit 3, same as in a run
        print(f"Virlo is unreachable ({type(exc).__name__}: {exc}) — check VIRLO_API_KEY and "
              "that the wrapper starts: python -m hypesocials.virlo_mcp")
        return EXIT_NOTHING_USABLE
    if not rows:
        print("no monitors are visible to this VIRLO_API_KEY — create one in the Virlo dashboard")
        return EXIT_NOTHING_USABLE
    print(f"{len(rows)} Virlo monitor(s) — paste the ids into sources.virlo_monitor_ids:")
    for monitor_id, name in rows:
        print(f'  {monitor_id}  {name}')
    return EXIT_OK


def decide_exit_code(
    entries: Sequence[PlanEntry],
    *,
    interrupted: bool = False,
    preflight_refused: bool = False,
    trend_supply_failed: bool = False,
) -> int:
    """FR-202's five codes, in one place, so a scheduler reads the same meaning every time.

    `0` every planned creative delivered · `1` completed with losses (skipped, failed, trimmed or
    abandoned) · `2` pre-flight refusal or config error, nothing spent · `3` fatal after Collect
    began — zero usable trends for a plan that needed them, or a transport-dead source · `4`
    interrupted by SIGINT.

    The brief-only carve-out lives in the `trend_supply_failed` branch: a trend famine is fatal
    only when it left nothing deliverable. If override-brief creatives shipped anyway the run is
    a partial success (`1`), and a brief-only plan that delivered everything is a plain `0`.
    """
    if preflight_refused:
        return EXIT_PREFLIGHT
    if interrupted:
        return EXIT_INTERRUPTED
    delivered = sum(1 for entry in entries if entry.status is PlanEntryStatus.SUCCESS)
    if trend_supply_failed and not delivered:
        return EXIT_NOTHING_USABLE
    if not entries:
        return EXIT_PREFLIGHT  # a zero-creative plan never starts (FR-64)
    return EXIT_OK if delivered == len(entries) else EXIT_PARTIAL


# --------------------------------------------------------------------------- the pipeline


def _open(config: Config, opts: cli.Options, control: Control) -> _Session:
    """Create the run folder and its logs before anything else can fail (FR-70, 30 §8)."""
    run_id = new_run_id()
    run_dir = create_run_folder(config.output.dir, run_id)
    log = LogWriter(run_dir, preflight.collect_secrets(),
                    verbose=config.output.log_verbosity == "verbose")
    return _Session(
        config=config, opts=opts, control=control, run_id=run_id, run_dir=run_dir, log=log,
        ledger=Ledger(run_dir), deadline=Deadline.from_minutes(config.run.run_deadline_min),
        clock=Stopwatch(), budget=Budget(config.run.spend_cap_usd),
        engine=PromptEngine(override_dirs=[config.prompts_dir] if config.prompts_dir else [],
                            log=log))


async def _pipeline(session: _Session, overrides: Sequence[str]) -> int:
    config, opts = session.config, session.opts
    session.say(_launch_summary(session, overrides))

    briefs, brief_errors, brief_warnings = preflight.resolve_briefs(
        opts.briefs, config, assume_yes=opts.yes)
    for line in brief_warnings:
        session.log.warn("brief_dropped", line)

    resolved = plan.build_plan(config, briefs=briefs)
    for note in resolved.notes:
        session.log.warn("plan_note", note)
        session.say(f"note: {note}")
    if not resolved.entries:
        raise _Abort(EXIT_PREFLIGHT, "this plan requests zero creatives — raise a count with "
                                     "--images/--carousels/--reels or check each platform's "
                                     "formats allowlist (FR-64)")

    verdict = preflight.check(config, action="run", entries=resolved.entries,
                              briefs_errors=brief_errors)
    if verdict.report:
        session.say(verdict.report)
    session.log.event("preflight", "pre-flight complete", ok=verdict.ok,
                      errors=list(verdict.errors), warnings=list(verdict.warnings))
    if not verdict.ok:
        raise _Abort(EXIT_PREFLIGHT, "nothing was spent — fix the lines above and re-run (FR-202)")

    live, _pre_confirm_estimate = await _confirm(session, resolved.entries)
    _configure_providers(session)

    trends = await _collect(session)
    assignment = _select(session, trends, resolved.entries)
    # Re-priced with the trends actually assigned: the shared analysis/copy calls of FR-12/FR-99
    # are per distinct trend, so the per-entry shares only become real once assignment has run.
    plan_estimate = estimate(config, resolved.entries)
    _restate(session, assignment, plan_estimate)
    live = [entry for entry in live if entry.status is PlanEntryStatus.PENDING]

    by_key = {trend.history_key: trend for trend in trends}
    _store_references(session, by_key, live)
    briefs_by_trend = await _analyze(session, live, by_key)
    copy_result = await _write(session, live, by_key, briefs_by_trend)
    report = await _create(session, resolved.entries, live, by_key, briefs_by_trend, copy_result)

    # The brief-only carve-out (10 §10): a trend famine is fatal only when nothing was deliverable.
    return await _package(session, resolved.entries, plan_estimate, report,
                          trend_supply_failed=not any(e.trend_key for e in resolved.entries))


async def _confirm(session: _Session, entries: list[PlanEntry]) -> tuple[list[PlanEntry], Estimate]:
    """FR-58/59 + FR-282: show the priced plan, then take the answer. Money waits for it.

    The estimate runs *before* Collect, so no trend is assigned yet — and FR-107's analysis and
    copy lines are per distinct trend, not per creative. Provisional keys model FR-8's assignment
    exactly (one trend per `max_trend_reuses_per_run` creatives) so the operator sees the call
    count they will actually be billed for, and are cleared again before `assign()` runs.
    """
    _stamp_provisional(entries, session.config.run.max_trend_reuses_per_run)
    outcome = await cli.confirm_spend(session.config, entries, assume_yes=session.opts.yes,
                                      emit=session.say)
    for entry in entries:  # cleared again: `assign()` binds the real trends, nothing inherits these
        entry.trend_key = None if str(entry.trend_key or "").startswith(_PROVISIONAL) \
            else entry.trend_key
    if outcome.trimmed is not None:
        for trimmed in outcome.trimmed.trimmed:
            session.log.warn("skipped_budget", f"{trimmed.asset_id}: {trimmed.skip_reason}",
                             asset_id=trimmed.asset_id,
                             estimated_usd=trimmed.estimated_cost_usd)
    if not outcome.approved:
        raise _Abort(outcome.exit_code, outcome.reason)
    session.log.event("confirmed", "spend approved", expected_usd=outcome.estimate.expected_usd,
                      cap_usd=session.config.run.spend_cap_usd, unattended=session.opts.yes)
    return list(outcome.entries), outcome.estimate


def _configure_providers(session: _Session) -> None:
    """Build the paid seams — after the gate, deliberately (FR-59: a decline contacts nobody)."""
    config = session.config
    on_intent, on_submitted = generate.ledger_hooks(session.ledger)
    render.configure(render.RenderSettings(
        max_inflight_render_jobs=config.models.max_inflight_render_jobs,
        poll_interval_s=float(config.models.poll_interval_s),
        image_job_timeout_s=float(config.models.image_job_timeout_s),
        video_job_timeout_s=float(config.models.video_job_timeout_s),
        http_max_attempts=config.models.http_max_attempts,
        model_ids={config.models.image_profile: config.models.image,
                   config.models.video_profile: config.models.video},
        on_intent=on_intent, on_submitted=on_submitted))
    session.render_ready = True
    session.llm = LLMClient(
        {role: _role_settings(config, role) for role in ("analysis", "copy")},
        max_inflight_llm_calls=config.models.max_inflight_llm_calls,
        http_max_attempts=config.models.http_max_attempts,
        on_warning=session.log.warn)


def _role_settings(config: Config, role: str) -> RoleSettings:
    """One LLM role from config. `temperature` stays opt-in — RESULTS.md §E: neither shipped
    model advertises it, and sending it under `require_parameters` is a 404 (FR-129 conflict)."""
    return RoleSettings(
        model=config.models.analysis if role == "analysis" else config.models.copy,
        max_tokens=config.max_tokens_for(role),
        max_tokens_floor=config.models.max_tokens_floor.get(role, 0),
        reasoning_effort=config.models.reasoning_effort if role == "copy" else None,
        temperature=config.models.temperature.get(role),
        temperature_supported=role in config.models.temperature)


# --------------------------------------------------------------------------- stages


async def _collect(session: _Session) -> list[TrendItem]:
    """Collect: every active adapter, through the bounded Virlo MCP session pool (20 §3)."""
    watch = Stopwatch()
    try:
        trends = await sources.fetch(session.config, log=session.log)
    except Exception as exc:  # noqa: BLE001 — 10 §10 row 1: a dead source is exit 3, not a crash
        session.log.error("collect_failed", f"{type(exc).__name__}: {exc}")
        raise _Abort(EXIT_NOTHING_USABLE,
                     f"the trend source could not be reached ({type(exc).__name__}: {exc}) — "
                     "nothing was asked for, so no window change can help. Check VIRLO_API_KEY "
                     "and that `python -m hypesocials.virlo_mcp` starts") from exc
    session.log.event("collect_complete", f"{len(trends)} trend(s) collected",
                      duration_ms=watch.elapsed_ms, trends=[t.history_key for t in trends])
    return trends


def _select(session: _Session, trends: list[TrendItem],
            entries: list[PlanEntry]) -> plan.Assignment:
    """Select + assign, then the FR-8 ceiling check and 10 §10's four-cause abort message."""
    config = session.config
    selection = plan.select(trends, config, read_history(LOGS_DIR, session.log))
    for verdict in selection.verdicts:
        session.log.event("trend_verdict", f"{verdict.trend.name}: {verdict.label}",
                          trend=verdict.trend.history_key, strength=verdict.trend.strength,
                          components=verdict.trend.strength_components)
    assignment = plan.assign(entries, selection, config)
    for decision in assignment.decisions:
        session.log.event("trend_assigned",
                          f"{'/'.join(decision.asset_ids)} ← {decision.trend_key or 'no trend'} "
                          f"({decision.reason})", detail=decision.detail)
    if not any(entry.trend_key or entry.brief_influence == "override" for entry in entries):
        raise _Abort(EXIT_NOTHING_USABLE, _famine_message(selection, config))
    return assignment


def _famine_message(selection: plan.Selection, config: Config) -> str:
    """10 §10: name the cause that actually applies, and only suggest the remedy that fits."""
    excluded, unusable = len(selection.excluded), len(selection.unusable)
    if not selection.verdicts:
        return ("Virlo returned no trends at all — check that sources.virlo_monitor_ids names "
                f"monitors this key can see ({', '.join(config.sources.virlo_monitor_ids) or 'none configured'}); "
                "run --list-monitors to print the real ids")
    if excluded and not unusable:
        return (f"every usable trend ({excluded}) was used within the last "
                f"{config.run.trend_history_days} day(s) — widen or disable trend_history_days, "
                "or wait for the monitors to surface new material (FR-7)")
    reasons = "; ".join(sorted({v.reason for v in selection.unusable})) or "no usable material"
    return (f"no trend survived filtering: {unusable} rejected as unusable ({reasons})"
            + (f" and {excluded} excluded by the {config.run.trend_history_days}-day history "
               "window" if excluded else "")
            + " — nothing was spent on analysis or rendering (FR-6/FR-7)")


def _restate(session: _Session, assignment: plan.Assignment, plan_estimate: Estimate) -> None:
    """FR-8 / 30 §4's honesty rule: say out loud when Select shrank an approved plan."""
    line = (f"{assignment.summary_line} — proceeding with "
            f"{len(assignment.decisions) - len(assignment.dropped)} creative group(s), revised "
            f"estimate {format_usd(plan_estimate.expected_usd)}")
    session.log.event("plan_restated", line, dropped=len(assignment.dropped))
    if assignment.dropped or session.opts.interactive:
        session.say(line)


def _store_references(session: _Session, trends: dict[str, TrendItem],
                      live: Sequence[PlanEntry]) -> None:
    """Copy each assigned trend's reference set into `refs/` so the gallery can compare (FR-71/150)."""
    for key in dict.fromkeys(entry.trend_key for entry in live if entry.trend_key):
        trend = trends.get(key or "")
        urls = trend.reference_groups[0] if trend and trend.reference_groups else []
        for index, path in enumerate(sources.reference_paths(urls), start=1):
            try:
                save_reference(session.run_dir, key or "", path.read_bytes(), index=index,
                               suffix=path.suffix if path.suffix != ".img" else ".jpg")
            except OSError as exc:
                session.log.warn("reference_copy_failed", f"{key}: {exc}", trend=key)


async def _analyze(session: _Session, live: Sequence[PlanEntry],
                   trends: dict[str, TrendItem]) -> dict[str, StyleBrief]:
    """ANALYZE: one Sonnet 5 vision call per distinct assigned trend, all concurrent (FR-9)."""
    wanted = {entry.trend_key for entry in live
              if entry.variant == "analyzed" and entry.trend_key in trends}
    if not wanted or _halt(session, "analysis"):
        return {}
    subjects = [trends[key] for key in wanted if key]
    images = {t.history_key: sources.reference_paths(t.reference_groups[0] if t.reference_groups
                                                     else []) for t in subjects}
    watch = Stopwatch()
    briefs = await analyze.style_briefs(
        subjects, images, call=_metered(session), engine=session.engine,
        niche_descriptor=session.config.niche.as_text(),
        max_images=session.config.sources.media_download_cap, log=session.log)
    session.log.event("analysis_complete", f"{len(briefs)} of {len(subjects)} style brief(s)",
                      duration_ms=watch.elapsed_ms, briefs=sorted(briefs))
    return briefs


async def _write(session: _Session, live: Sequence[PlanEntry], trends: dict[str, TrendItem],
                 briefs: dict[str, StyleBrief]) -> copywrite.CopyResult:
    """WRITE: one Luna call per (trend × language), split on failure, never per creative (FR-99)."""
    if not live or _halt(session, "copywriting"):
        return copywrite.CopyResult()
    config = session.config
    watch = Stopwatch()
    result = await copywrite.write_copy(
        live, trends=trends, style_briefs=briefs, call=_metered(session), engine=session.engine,
        text_budgets=config.run.text_budgets,
        conventions={name: config.platform(name).conventions for name in config.run.platforms},
        onimage_languages={entry.asset_id: config.onimage_language_for(entry.platform)
                           for entry in live},
        niche_descriptor=config.niche.as_text(), log=session.log)
    session.log.event("copy_complete", f"copy for {len(result.copy)} creative(s)",
                      duration_ms=watch.elapsed_ms, degraded=sorted(result.degraded),
                      trimmed=sorted(result.trimmed))
    return result


async def _create(session: _Session, entries: Sequence[PlanEntry], live: Sequence[PlanEntry],
                  trends: dict[str, TrendItem], briefs: dict[str, StyleBrief],
                  copy_result: copywrite.CopyResult) -> generate.Report:
    """CREATE: wave-1 images (W3 scope). Entries already terminal are packaged as honest skips."""
    if _halt(session, "generation"):  # FR-4/FR-108: nothing leaves the plan, it goes terminal
        for entry in entries:
            if entry.status is PlanEntryStatus.PENDING:
                entry.status = PlanEntryStatus.ABANDONED
                entry.skip_reason = "run deadline elapsed or interrupted before submission"
    env = generate.Env(
        config=session.config, run_dir=session.run_dir, engine=session.engine,
        budget=session.budget, log=session.log, ledger=session.ledger, trends=trends,
        style_briefs=briefs, copy=copy_result.copy, copy_degraded=copy_result.degraded,
        copy_trimmed=copy_result.trimmed, niche_descriptor=session.config.niche.as_text(),
        stop=session.control.stop)
    watch = Stopwatch()
    report = await generate.create(entries, env)
    session.log.event("generation_complete",
                      f"{len(report.packaged_trends)} trend(s) produced packaged creatives",
                      duration_ms=watch.elapsed_ms, disk_full=report.disk_full)
    return report


async def _package(session: _Session, entries: Sequence[PlanEntry], plan_estimate: Estimate,
                   report: generate.Report, *, trend_supply_failed: bool) -> int:
    """PACKAGE: gallery, history, latest-pointer, spend summary, exit code (FR-75/82/84/232)."""
    write_gallery(session.run_dir, title=session.config.output.gallery.title, log=session.log)
    if report.packaged_trends:  # FR-82: only trends that actually produced a packaged creative
        await record_trends(LOGS_DIR, sorted(report.packaged_trends), session.run_id,
                            history_days=session.config.run.trend_history_days, log=session.log)
    if any(entry.status is PlanEntryStatus.SUCCESS for entry in entries):
        await set_latest(session.config.output.dir, session.run_id, log=session.log)  # FR-254

    summary = session.budget.summary(entries, plan_estimate)
    session.say(_spend_table(summary))
    code = decide_exit_code(entries, interrupted=session.control.stop.is_set(),
                            trend_supply_failed=trend_supply_failed)
    session.say(_final_line(session, entries, summary, code))
    return code


# --------------------------------------------------------------------------- helpers


def _metered(session: _Session) -> Any:
    """Wrap `llm.structured_call` so every LLM call lands in the run's tally (FR-84's split).

    LLM spend is known only after the call — nothing can decline it retroactively — so it is
    committed and reconciled to OpenRouter's own `usage.cost` in one step, and a call the
    provider reported no cost for is marked *estimated* rather than invented (FR-85).
    """
    client = session.llm
    if client is None:  # programmer error: providers are built right after the confirm gate
        raise RuntimeError("LLM client is not configured for this run")

    async def call(role: str, messages: list[dict[str, Any]], json_schema: dict[str, Any],
                   images: list[bytes] | None = None) -> ParsedResult:
        result = await client.structured_call(role, messages, json_schema, images)
        held = await session.budget.commit(result.cost_usd, label=f"llm {role}",
                                           category=SpendCategory.LLM, kind="projected")
        await session.budget.reconcile(held, result.cost_usd or None)
        session.log.event("llm_call", f"{role} call complete", role=role,
                          prompt_tokens=result.prompt_tokens,
                          completion_tokens=result.completion_tokens,
                          reasoning_tokens=result.reasoning_tokens,
                          cost_usd=round(result.cost_usd, 6), degraded=result.degraded)
        return result

    return call


def _halt(session: _Session, stage: str) -> bool:
    """Deadline/interrupt check between stages — soft by contract (FR-108: it stops ORDERING)."""
    if not session.halted:
        return False
    reason = ("Ctrl+C" if session.control.stop.is_set()
              else f"the {session.config.run.run_deadline_min}-minute run deadline")
    session.log.warn("stage_skipped", f"{stage} skipped: {reason} (FR-108/FR-201)", stage=stage)
    session.say(f"{reason} — skipping {stage} and packaging what exists")
    return True


def _stamp_provisional(entries: Sequence[PlanEntry], max_reuses: int) -> None:
    """Give each atomic group the trend key FR-8 would give it, so the pre-Collect estimate
    counts the analysis and copy calls the operator will really be billed for."""
    groups = list(dict.fromkeys(entry.atomic_group or entry.asset_id for entry in entries
                                if entry.brief_influence != "override"))
    keys = {group: f"{_PROVISIONAL}{index // max(1, int(max_reuses))}"
            for index, group in enumerate(groups)}
    for entry in entries:
        if entry.brief_influence != "override":
            entry.trend_key = keys[entry.atomic_group or entry.asset_id]


def _launch_summary(session: _Session, overrides: Sequence[str]) -> str:
    """FR-77's opening block: what this run is, resolved, before anything can change it."""
    config = session.config
    return "\n".join([
        f"HypeSocials run {session.run_id}",
        f"  config      {config.path} — {config.description or 'no description'}",
        f"  formats     " + ", ".join(f"{name}={count}" for name, count in config.run.formats.items()),
        f"  platforms   " + ", ".join(
            f"{name}/{config.language_for(name)}" for name in config.run.platforms),
        f"  mode        {config.run.generation_mode} · notion {config.run.notion_influence} · "
        f"vision_check {str(config.run.vision_check).lower()}",
        f"  spend cap   {format_usd(config.run.spend_cap_usd)} · deadline "
        f"{config.run.run_deadline_min} min · output {session.run_dir}",
        f"  overrides   " + (", ".join(overrides) or "none (config values as written)"),
    ])


def _money(amount: float) -> str:
    """Cents normally, four decimals below one cent — an LLM line that really cost $0.0024 must
    not print as the `$0.00` an unpriced line prints (FR-85's *estimated* honesty, same idea)."""
    return f"${amount:.4f}" if 0 < amount < 0.01 else format_usd(amount)


def _spend_table(summary: SpendSummary) -> str:
    """FR-84's ONE spend table: per creative, per format, then the grand total and cap status."""
    lines = [summary.headline,
             f"  {'asset':<40}{'format':<10}{'est':>9}{'billed':>10}  delivered"]
    for row in summary.rows:
        mark = "yes" if row.delivered else "no"
        billed = format_usd(row.billed_usd) + (" est" if row.estimated_only else "")
        lines.append(f"  {row.asset_id:<40}{row.creative_format:<10}"
                     f"{format_usd(row.estimated_usd):>9}{billed:>10}  {mark}")
    for name, amount in summary.by_format.items():
        lines.append(f"  subtotal {name:<47}{_money(amount):>10}")
    lines.append(f"  TOTAL  llm {_money(summary.llm_usd)} + render "
                 f"{_money(summary.render_usd)} = {_money(summary.total_usd)}")
    lines.append(f"  {summary.cap_status}")
    if summary.skipped_budget or summary.skipped_other:
        lines.append(f"  skipped: {summary.skipped_budget} by budget, "
                     f"{summary.skipped_other} for other reasons")
    if summary.banner:
        lines.append(f"  {summary.banner}")
    return "\n".join(lines)


def _final_line(session: _Session, entries: Sequence[PlanEntry], summary: SpendSummary,
                code: int) -> str:
    """FR-232's one-line close: cost, wall clock, counts, skip reasons, status and the exit code."""
    status = {EXIT_OK: "success", EXIT_PARTIAL: "partial-success",
              EXIT_INTERRUPTED: "interrupted"}.get(code, "failed")
    delivered = sum(1 for row in summary.rows if row.delivered)
    reasons = sorted({str(entry.skip_reason).split(":", 1)[0].split(" ", 1)[0]
                      for entry in entries if entry.skip_reason})
    skipped = len(summary.rows) - delivered
    detail = f" ({', '.join(reasons)})" if reasons else ""
    return (f"run {session.run_id} · total {_money(summary.total_usd)} · "
            f"{session.clock.elapsed_s:.1f}s · generated {delivered} · skipped {skipped}{detail} · "
            f"status {status} · exit code {code} · folder {session.run_dir}")


async def _cleanup(session: _Session) -> None:
    """FR-249: scratch, clients and log handles released on EVERY exit path, in a safe order.

    Every step is independent and swallowed: a run that already failed must not fail again on the
    way out, and a real Ctrl+C reaches the MCP wrapper and yt-dlp too, so some children are
    already gone before we get here (spikes/RESULTS.md §F — `ProcessLookupError` is expected).
    """
    steps = [close_downloads()]
    if session.render_ready:
        steps.insert(0, render.aclose())
    if session.llm is not None:
        steps.insert(0, session.llm.aclose())
    for step in steps:
        try:
            await step
        except ProcessLookupError:
            pass  # the child died with the console before cleanup ran (RESULTS.md §F)
        except Exception as exc:  # noqa: BLE001 — cleanup never re-raises
            logger.warning("cleanup step failed: %s: %s", type(exc).__name__, exc)
    try:
        sources.cleanup()  # the run's scratch reference downloads (FR-249)
    except OSError as exc:
        logger.warning("scratch cleanup failed: %s", exc)
    session.log.close()


__all__ = [
    "Control", "EXIT_INTERRUPTED", "EXIT_NOTHING_USABLE", "EXIT_OK", "EXIT_PARTIAL",
    "EXIT_PREFLIGHT", "LOGS_DIR", "decide_exit_code", "list_monitors", "run",
]
