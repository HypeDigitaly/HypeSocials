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
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hypesocials import analyze, cli, copywrite, generate, menu, plan, preflight, render, sources
from hypesocials.budget import Budget, Estimate, SpendCategory, SpendSummary, estimate, format_usd
from hypesocials.config import LOGS_DIR, Config, ConfigError, load_config
from hypesocials.generate import video_ref
from hypesocials.llm import CREDITS_EXHAUSTED_REASON, LLMClient, RoleSettings
from hypesocials.models import (
    Brief, DegradationTag, ParsedResult, PlanEntry, PlanEntryStatus, StyleBrief, TrendItem)
from hypesocials.outputs import (
    Ledger,
    LogWriter,
    close_downloads,
    create_run_folder,
    read_history,
    read_meta,
    record_use,
    save_reference,
    set_latest,
    used_posts,
    write_gallery,
)
from hypesocials.prompts_engine import PromptEngine
from hypesocials.util import Deadline, Stopwatch, fit, new_run_id, wrapped

logger = logging.getLogger(__name__)

# FR-202 — the whole contract, spelled once.
EXIT_OK = 0  # every planned creative was delivered
EXIT_PARTIAL = 1  # completed with at least one skip, failure, trim or abandonment
EXIT_PREFLIGHT = 2  # pre-flight refusal or config error, incl. a missing key — nothing spent
EXIT_NOTHING_USABLE = 3  # fatal after Collect began: no usable trend, or a transport-dead source
EXIT_INTERRUPTED = 4  # SIGINT (FR-201)

#: `LOGS_DIR` is defined in `config.py` (one definition, reachable from `preflight` without a
#: cycle) and re-exported here because `previews.py` reads it as `runner.LOGS_DIR`.
_PROVISIONAL = "provisional-trend-"

#: What `decide_exit_code()` reads off `generate.Report.records`: asset id -> its FR-73
#: `degradations` tags. A plain mapping rather than the `Report` itself, so the exit-code contract
#: stays a pure function of two facts (the plan, the tags) and can be exercised without a run.
DegradationMap = Mapping[str, Sequence[DegradationTag]]

#: FR-202 code 1's *"a delivered carousel shipped incomplete"*: the only degradation tag that, on
#: its own, turns a delivered creative into a loss. Deliberately NOT the whole FR-73 vocabulary —
#: the 2026-08-11 live run shipped `['text_trimmed', 'incomplete']` on one deck, and `text_trimmed`
#: is a character budget being honoured (FR-101), not a creative that lost what it was asked for.
_DELIVERED_LOSS_TAGS = frozenset({DegradationTag.INCOMPLETE})

#: FR-286: the closing line spells its own exit code, so an operator never has to look one up.
_EXIT_LEGEND = {
    EXIT_OK: "everything planned was delivered",
    EXIT_PARTIAL: "delivered with losses",
    EXIT_PREFLIGHT: "refused before spending, nothing was billed",
    EXIT_NOTHING_USABLE: "no usable trend after the source answered",
    EXIT_INTERRUPTED: "interrupted with Ctrl+C",
}


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
    virlo_contacted: bool = False  # FR-286: Virlo meters separately, so the total must say so
    counters: sources.Counters = field(default_factory=sources.Counters)  # FR-155's funnel
    video_refs: video_ref.Prefetch | None = None  # D23 chain, launched alongside Analyze
    campaign_briefs: dict[str, Brief] = field(default_factory=dict)  # D26, by brief name
    brand: sources.BrandContext = field(default_factory=sources.BrandContext)  # FR-34/36
    pool: sources.InspirationPool = field(default_factory=sources.InspirationPool)  # D13

    def say(self, text: str) -> None:
        """Print one operator-facing block and put the identical (redacted) text in run.log."""
        print(self.log.narrative(text))

    @property
    def halted(self) -> bool:
        """True once Ctrl+C landed or the soft run deadline elapsed (FR-108/201)."""
        return self.control.stop.is_set() or self.deadline.expired


# --------------------------------------------------------------------------- public actions


async def run(opts: cli.Options, control: Control | None = None, *,
              config: Config | None = None) -> int:
    """Execute one full run and return its FR-202 exit code. Never raises for a run outcome.

    `config` is the file the interactive wizard already loaded and mutated (`menu.MenuResult`),
    passed rather than re-loaded so the wizard's answers cost nothing to carry. Re-applying the
    overrides below is idempotent: every answer — the source pick included, since `--sources`
    landed (30 §5, FR-65/135) — travels in `opts` as the flag value it is equivalent to.
    """
    control = control or Control()
    try:
        config = load_config(opts.config_name) if config is None else config
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
        # FR-232/FR-84: an abort still closes with the status line — nobody should have to infer
        # the outcome. No spend table: an abort has no creative rows, and its (usually zero)
        # spend is in this line already.
        session.say(_final_line(session, (), session.budget.summary(()), abort.code))
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
    print(f"{len(rows)} Virlo monitor(s). Copy the block below into your config file under")
    print("sources:, replacing the virlo_monitor_ids line. Keep the two-space indent.")
    print("")
    print("  virlo_monitor_ids:")
    for monitor_id, name in rows:
        print(f"    - {monitor_id}  # {fit(name, 30)}")
    return EXIT_OK


def decide_exit_code(
    entries: Sequence[PlanEntry],
    *,
    interrupted: bool = False,
    preflight_refused: bool = False,
    trend_supply_failed: bool = False,
    plan_reduced: bool = False,
    degradations: DegradationMap | None = None,
) -> int:
    """FR-202's five codes, in one place, so a scheduler reads the same meaning every time.

    `0` every planned creative delivered · `1` completed with losses (skipped, failed, trimmed or
    abandoned) · `2` pre-flight refusal or config error, nothing spent · `3` fatal after Collect
    began — zero usable trends for a plan that needed them, or a transport-dead source · `4`
    interrupted by SIGINT.

    The brief-only carve-out lives in the `trend_supply_failed` branch: a trend famine is fatal
    only when it left nothing deliverable. If override-brief creatives shipped anyway the run is
    a partial success (`1`), and a brief-only plan that delivered everything is a plain `0`.

    **`degradations` is the FR-73 tag list per asset id** — `generate.Report.records` mapped to
    `AssetRecord.degradations` — and it is passed rather than re-derived because two of FR-202's
    code-1 clauses are simply not visible on a `PlanEntry`:

    - *"or a delivered carousel shipped incomplete (missing slides, FR-20/§10 — a lost slide is a
      loss even when the deck ships; v1.6.7)"*. A partial deck ends `SUCCESS` with **no**
      `skip_reason`: `carousel.package()` marks `incomplete` on the folder and logs the missing
      numbers, because the deck DID ship and `skip_reason` means "this creative did not". The live
      run of 2026-08-11 (`20260811_233910_wikf`) proved the gap — one deck lost slide 2 to a Kie
      timeout, wrote `slide_count: 4`, `missing_slide_numbers: [2]`, `degradations:
      ['text_trimmed', 'incomplete']`, and the run still exited 0 saying "everything planned was
      delivered". `_DELIVERED_LOSS_TAGS` is what closes it; a `skip_reason` on a delivered creative
      (FR-248's credits latch stamps one) remains a loss exactly as before.
    - *"or every analyzed creative delivered carries `analysis_missing`"* (amended 2026-08-11).
      **EVERY, never "at least one".** An earlier draft said "at least one"; with six analysis
      calls at the observed ~1-in-7 degrade rate that is P ≈ 60 %, so exit 0 would be unreachable
      on a majority of healthy runs and the code would stop carrying information. Fully-degraded
      only — the FR-252 run that shipped direct-mode creatives end to end.

    Zero analyzed creatives is **not** "every analyzed creative degraded": a direct-mode or
    brief-only plan (FR-144's override briefs are always `direct`) has nothing for the clause to
    speak about, and reading vacuous truth here would make exit 0 unreachable in reverse.

    `plan_reduced` (`plan.Plan.notes`) is why this decision cannot be read off the entries alone:
    a count dropped *before* expansion — unpriced reels (FR-131), a format no platform allows
    (FR-132), a brief that resolved to nothing under `--yes` (FR-172) — never becomes a `PlanEntry`,
    so every surviving entry can succeed while the run delivered less than it was asked for. 30 §5:
    "a trimmed, reduced, or partially-dropped unattended run … never a silent full-success exit".
    """
    if preflight_refused:
        return EXIT_PREFLIGHT
    if interrupted:
        return EXIT_INTERRUPTED
    tags: DegradationMap = degradations if degradations is not None else {}
    delivered = [entry for entry in entries if entry.status is PlanEntryStatus.SUCCESS]
    if trend_supply_failed and not delivered:
        return EXIT_NOTHING_USABLE
    if not entries:
        return EXIT_PREFLIGHT  # a zero-creative plan never starts (FR-64)
    whole = [entry for entry in delivered
             if not entry.skip_reason
             and not _DELIVERED_LOSS_TAGS.intersection(tags.get(entry.asset_id, ()))]
    analyzed, analysis_degraded = _analysis_degrade_counts(delivered, tags)
    fully_degraded = analyzed > 0 and analysis_degraded == analyzed
    if len(whole) != len(entries) or plan_reduced or fully_degraded:
        return EXIT_PARTIAL
    return EXIT_OK


def _analysis_degrade_counts(delivered: Sequence[PlanEntry],
                             degradations: DegradationMap) -> tuple[int, int]:
    """`(analyzed creatives delivered, how many of them carry analysis_missing)` — FR-252's count.

    One helper, two callers, so the exit code and the summary line that explains it can never
    disagree about what "every analyzed creative" meant on this run.

    `variant` is the whole test of "analyzed": FR-3's both-mode pairs deliberately ship a `direct`
    sibling that never had an analysis call to lose, and an `override` brief (FR-144) is emitted
    `direct` for the same reason. Neither belongs in the denominator. An analyzed entry with no
    record in the map counts as clean rather than degraded — the safe direction, since a missing
    record is a bookkeeping gap, not evidence that the analysis call failed.
    """
    analyzed = [entry for entry in delivered if entry.variant == "analyzed"]
    degraded = sum(1 for entry in analyzed
                   if DegradationTag.ANALYSIS_MISSING in degradations.get(entry.asset_id, ()))
    return len(analyzed), degraded


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
    session.campaign_briefs = {request.brief.name: request.brief for request in briefs}

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

    # 10 §10's brief-only carve-out: a plan of pure override briefs consumes no trend at all
    # (FR-144), so Collect opens no Virlo session and a trend famine can never abort it.
    brief_only = all(entry.brief_influence == "override" for entry in resolved.entries)
    trends = await _collect(session, fetch_trends=not brief_only)
    assignment = _select(session, trends, resolved.entries)
    # Re-priced with the trends actually assigned: the shared analysis/copy calls of FR-12/FR-99
    # are per distinct trend, so the per-entry shares only become real once assignment has run.
    plan_estimate = estimate(config, resolved.entries)
    _restate(session, assignment, plan_estimate)
    live = [entry for entry in live if entry.status is PlanEntryStatus.PENDING]

    by_key = {trend.history_key: trend for trend in trends}
    # FR-155, §10 rule 2 place 1: after Select, before Analyze — the last moment Ctrl+C is free.
    # Unconditional, unlike `_restate`: "everything worked" is the answer the operator came for.
    _record_render_forecast(session, live, by_key, dropped=len(assignment.dropped))
    session.say(_funnel_block(session.counters))
    # A24: the funnel says how much material there was; this says WHICH posts it is. Same place,
    # same reason — the last moment Ctrl+C is free — and gated to the strongest three so
    # Increment B's 9–22 trends cannot bury the rollup above it.
    if inventory := _sources_block(_assigned_trends(live, by_key)):
        session.say(inventory)
    _launch_video_refs(session, live, by_key)  # D23: overlaps Analyze, never the reel's critical path
    _store_references(session, by_key, live)
    briefs_by_trend = await _analyze(session, live, by_key)
    if analysis := _brief_block(briefs_by_trend, by_key):  # A24: what our AI made of them
        session.say(analysis)
    copy_result = await _write(session, live, by_key, briefs_by_trend)
    report, attached = await _create(session, resolved.entries, live, by_key, briefs_by_trend,
                                     copy_result)

    # The brief-only carve-out (10 §10): a trend famine is fatal only when nothing was deliverable,
    # and a brief-only plan never had a trend supply to fail — its losses are ordinary (exit 1).
    return await _package(session, resolved.entries, plan_estimate, report, attached,
                          trend_supply_failed=not brief_only
                          and not any(e.trend_key for e in resolved.entries),
                          plan_notes=resolved.notes)  # FR-252: pre-expansion drops exit 1


async def _confirm(session: _Session, entries: list[PlanEntry]) -> tuple[list[PlanEntry], Estimate]:
    """FR-58/59 + FR-282: show the priced plan, then take the answer. Money waits for it.

    The estimate runs *before* Collect, so no trend is assigned yet — and FR-107's analysis and
    copy lines are per distinct trend, not per creative. Provisional keys model the worst case
    FR-8's assignment can produce (one distinct trend per atomic group, `_stamp_provisional`), so
    the operator sees the call count they can really be billed for; they are cleared again before
    `assign()` runs.
    """
    _stamp_provisional(entries)
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
    if not outcome.approved and outcome.exit_code == EXIT_PREFLIGHT and session.opts.interactive:
        outcome = await _offer_reduced(session, entries, outcome)  # FR-28's interactive half
    if not outcome.approved:
        raise _Abort(outcome.exit_code, outcome.reason)
    session.log.event("confirmed", "spend approved", expected_usd=outcome.estimate.expected_usd,
                      cap_usd=session.config.run.spend_cap_usd, unattended=session.opts.yes)
    return list(outcome.entries), outcome.estimate


async def _offer_reduced(session: _Session, entries: Sequence[PlanEntry],
                         outcome: cli.ConfirmOutcome) -> cli.ConfirmOutcome:
    """FR-28: an interactive run refuses over cap — but OFFERS the plan `--yes` would have run.

    `menu.offer_reduced_plan()` shows `budget.trim()`'s deterministic result (reverse plan order,
    atomic groups never split): the same rule, shown instead of silently applied. Accepted, the
    kept entries proceed and the trimmed ones stay in the plan as `skipped_budget` (FR-4), so the
    run exits 1; declined, the untouched refusal stands and nothing was spent (exit 2).
    """
    kept = await menu.offer_reduced_plan(session.config, entries,
                                         console=menu.Console(say=session.say))
    if kept is None:
        return outcome
    for entry in entries:
        if entry.status is PlanEntryStatus.SKIPPED_BUDGET:
            session.log.warn("skipped_budget", f"{entry.asset_id}: {entry.skip_reason}",
                             asset_id=entry.asset_id, estimated_usd=entry.estimated_cost_usd)
    return cli.ConfirmOutcome(True, tuple(kept), estimate(session.config, kept))


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
        on_intent=on_intent, on_submitted=on_submitted),
        log=session.log)  # FR-77: submit/poll/download narrate into the run's own log
    session.render_ready = True
    _configure_llm(session)


def _configure_llm(session: _Session) -> None:
    """The LLM seam alone — the only provider a preview may build (FR-140, previews.py).

    Split out of `_configure_providers()` so `--preview-analysis` reuses the paid run's own
    construction verbatim (D19) instead of a second one that would drift.
    """
    config = session.config
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


async def _collect(session: _Session, *, fetch_trends: bool = True) -> sources.TrendFeed:
    """Collect: every active adapter through the bounded Virlo MCP session pool (20 §3), plus the
    two optional channels riding this stage — the local Inspiration pool (D13) and Notion brand
    context (FR-34/36, fetched once). Each gates itself: no folders scans nothing, and
    `notion_influence: off` opens no session. `fetch_trends=False` is 10 §10's brief-only
    carve-out — a pure-override plan needs no trend, so no Virlo session is opened at all.
    """
    watch = Stopwatch()
    session.pool = await sources.load_pool(session.config, log=session.log)
    session.brand = await sources.fetch_brand_context(session.config, log=session.log)
    if not fetch_trends:
        session.say("brief-only plan: every creative is an override brief, so no trend\n"
                    "is consumed and no Virlo session is opened")
        return sources.TrendFeed()
    # FR-7/FR-153: the adapter, not Select, chooses which reference set a trend arrives with, so
    # the used-post map has to be read BEFORE Collect. Post ids are globally unique, so one flat
    # union over the window is the whole input — no per-trend split.
    window = session.config.run.trend_history_days
    fresh_against = {post for posts in used_posts(read_history(LOGS_DIR, session.log),
                                                  within_days=window).values() for post in posts}
    session.virlo_contacted = "virlo" in session.config.sources.active
    try:
        trends = await sources.fetch(session.config, log=session.log,
                                     used_posts=fresh_against, say=session.say)
    except Exception as exc:  # noqa: BLE001 — 10 §10 row 1: a dead source is exit 3, not a crash
        session.log.error("collect_failed", f"{type(exc).__name__}: {exc}")
        raise _Abort(EXIT_NOTHING_USABLE,
                     f"the trend source could not be reached ({type(exc).__name__}: {exc}) — "
                     "nothing was asked for, so no window change can help. Check VIRLO_API_KEY "
                     "and that `python -m hypesocials.virlo_mcp` starts") from exc
    session.counters = trends.counters  # FR-155: the funnel travels on the fetch, not on a global
    session.log.event("collect_complete", f"{len(trends)} trend(s) collected",
                      duration_ms=watch.elapsed_ms, trends=[t.history_key for t in trends])
    return trends


def _select(session: _Session, trends: list[TrendItem],
            entries: list[PlanEntry]) -> plan.Assignment:
    """Select + assign, then the FR-8 ceiling check and 10 §10's four-cause abort message."""
    config = session.config
    selection = plan.select(trends, config, read_history(LOGS_DIR, session.log))
    # FR-155: Select owns these three buckets, so Select is where the funnel learns them. The
    # adapter can count material; only this stage can count verdicts.
    session.counters.record_selection(eligible=len(selection.eligible),
                                      excluded=len(selection.excluded),
                                      unusable=len(selection.unusable))
    for verdict in selection.verdicts:
        session.log.event("trend_verdict", f"{verdict.trend.name}: {verdict.label}",
                          trend=verdict.trend.history_key, strength=verdict.trend.strength,
                          components=verdict.trend.strength_components)
    assignment = plan.assign(entries, selection, config)
    for decision in assignment.decisions:
        session.log.event("trend_assigned",
                          f"{'/'.join(decision.asset_ids)} ← {decision.trend_key or 'no trend'} "
                          f"({decision.reason})", detail=decision.detail)
        if decision.reason == "reuse":  # FR-8: a reuse is a fact, with the count that bounds it
            session.log.event("trend_reused",
                              f"{decision.trend_key} reused for {'/'.join(decision.asset_ids)} — "
                              f"use #{decision.use_index} of "
                              f"{config.run.max_trend_reuses_per_run} (FR-8)",
                              trend=decision.trend_key, use_index=decision.use_index,
                              max_reuses=config.run.max_trend_reuses_per_run)
    if not any(entry.trend_key or entry.brief_influence == "override" for entry in entries):
        raise _Abort(EXIT_NOTHING_USABLE, _famine_message(selection, config))
    return assignment


def _famine_message(selection: plan.Selection, config: Config) -> str:
    """10 §10: name the cause that actually applies, and only suggest the remedy that fits."""
    excluded, unusable = len(selection.excluded), len(selection.unusable)
    ids = [str(i).strip() for i in config.sources.virlo_monitor_ids if str(i).strip()]
    if not selection.verdicts:
        if not ids:  # FR-283 refuses this before the money gate; kept as a safety net only
            return ("no Virlo monitor ids are configured, so Virlo was never asked for anything"
                    " — run run.bat --list-monitors and paste the ids into your config")
        return (f"Virlo was asked about {len(ids)} monitor(s) and returned nothing usable — the"
                " ids may name monitors this key cannot see; run run.bat --list-monitors to"
                " print the ids it can")
    if excluded and not unusable:
        return (f"every usable trend ({excluded}) has no unused reference set left inside the"
                f" last {config.run.trend_history_days} day(s) — use --history-days to widen or"
                " disable the window, or wait for the monitors to surface new posts")
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


def _launch_video_refs(session: _Session, live: Sequence[PlanEntry],
                       trends: dict[str, TrendItem]) -> None:
    """D23/FR-142: start the yt-dlp → Kie chain the moment trends are assigned, not at Seedance.

    It depends only on assignment, so its 15–60 s of probe/download/upload overlaps Analyze and
    Write instead of extending a reel's critical path; `reel.py` awaits it under a short bounded
    wait and ships seed-frame-only if it is not ready. Nothing starts when reels are off, when
    `reel_video_reference` is false, or when no assigned trend carries a winning video — the
    handle simply stays `None` and no yt-dlp process is ever spawned (FR-139/140 stay $0).
    """
    if not session.config.run.reel_video_reference:
        return
    keys = {entry.trend_key for entry in live
            if entry.creative_format == "reel" and entry.trend_key}
    candidates = {key: url for key in keys
                  if (trend := trends.get(key or "")) and (url := trend.winning_video_url)}
    if not candidates:
        return
    session.video_refs = video_ref.prefetch(
        candidates, max_duration_s=session.config.run.reel_reference_max_s,
        profile_name=session.config.models.video_profile,  # FR-273: the profile decides the probe
        log=session.log)


def _store_references(session: _Session, trends: dict[str, TrendItem],
                      live: Sequence[PlanEntry]) -> None:
    """Copy every reference set this run ATTACHES into `refs/`, so the gallery can compare (FR-71/150).

    Since FR-91's rotation (amended 2026-08-11) sibling creatives on one trend attach *different*
    groups, so copying `reference_groups[0]` alone would show the operator one set while six
    creatives rendered from six — the comparison FR-71/150 exists for would be wrong for five of
    them. Every distinct (trend, group) pair the plan actually uses is copied.

    The index runs CONTINUOUSLY across a trend's groups rather than restarting per group.
    `packager.save_reference` names files `image_<index>` inside a per-trend folder, so a
    per-group restart would have each group overwrite the previous one's `image_1` and leave only
    the last set on disk — a silent data loss dressed as a working gallery.
    """
    used: dict[str, list[int]] = {}
    for entry in live:
        if entry.trend_key:
            groups = used.setdefault(entry.trend_key, [])
            index = sources.reference_group_index(trends.get(entry.trend_key), entry.trend_reuse_index)
            if index not in groups:
                groups.append(index)
    for key, group_indexes in used.items():
        trend = trends.get(key)
        index = 0
        for group_index in sorted(group_indexes):
            for path in sources.reference_paths(sources.reference_group(trend, group_index)):
                index += 1
                try:
                    save_reference(session.run_dir, key, path.read_bytes(), index=index,
                                   suffix=path.suffix if path.suffix != ".img" else ".jpg")
                except OSError as exc:
                    session.log.warn("reference_copy_failed", f"{key}: {exc}", trend=key)


async def _analyze(session: _Session, live: Sequence[PlanEntry],
                   trends: dict[str, TrendItem]) -> dict[str, StyleBrief]:
    """ANALYZE: one Sonnet 5 vision call per distinct (trend, reference group) pair (FR-9/FR-12).

    **Each brief sees only the group its creatives attach** (amended 2026-08-11). The previous
    rule pooled every downloaded group into one call, on the argument that group 0 alone would
    show the analyst 3 images where `media_download_cap` allows 6. That argument was written when
    there was ONE brief per trend; under FR-91's rotation it inverts — pooling six groups produces
    a brief describing pictures the creative is not attaching, which is precisely the mismatch
    FR-9's amended unit exists to remove. FR-93's "about six images maximum per call" is a
    ceiling, not a floor.

    The pairs are read off the live plan, so a group no creative will attach is never analysed and
    never billed.
    """
    wanted = {(entry.trend_key, entry.trend_reuse_index) for entry in live
              if entry.variant == "analyzed" and entry.trend_key in trends}
    if not wanted or _halt(session, "analysis"):
        return analyze.BriefBook()
    # FR-93 bounds ONE analysis call at ~6 images; `media_download_cap` bounds the whole trend's
    # DOWNLOAD (18 since 2026-08-11, so rotation has a group per reuse). Those were the same
    # number until the cap was raised, and conflating them now would send an 18-panel deck to a
    # single vision call.
    per_call = max(1, min(session.config.sources.media_download_cap, analyze.ANALYSIS_MAX_IMAGES))
    subjects = [(trends[key], reuse) for key, reuse in sorted(wanted) if key]
    images = {
        sources.brief_key(trend.history_key, trend, reuse):
            sources.reference_paths(sources.reference_group(trend, reuse))[:per_call]
        for trend, reuse in subjects}
    watch = Stopwatch()
    briefs = await analyze.style_briefs(
        subjects, images, call=_metered(session), engine=session.engine,
        niche_descriptor=session.config.niche.as_text(),
        max_images=per_call, log=session.log)
    for key, brief in briefs.items():  # NFR-5/FR-92: the FULL brief is logged, never injected
        session.log.event("style_brief", f"style brief for {key} (FR-92)", verbose_only=True,
                          trend=brief.trend_key, reference_group=brief.reference_group_index,
                          hook_pattern=brief.hook_pattern, brief=asdict(brief))
    session.log.event("analysis_complete",
                      f"{len(briefs)} of {len(subjects)} style brief(s) "
                      f"across {len({t.history_key for t, _ in subjects})} trend(s)",
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
        campaign_briefs=session.campaign_briefs,  # FR-146: the brief's directives steer the copy
        brand_context=session.brand.text,  # FR-109: Notion text reaches the copywriter only
        text_budgets=config.run.text_budgets,
        conventions={name: config.platform(name).conventions for name in config.run.platforms},
        onimage_languages={entry.asset_id: config.onimage_language_for(entry.platform)
                           for entry in live},
        # A16: the `.txt` files paired with the operator's own Inspiration images — proven,
        # human-written posts. `session.pool` is loaded a full stage earlier (Collect), which is
        # why the channel rides the pool rather than `apply_mix`'s render-side decision. Copy call
        # only: no render role can resolve `{{inspiration_exemplars}}` (FR-261's allowlist).
        copy_exemplars=session.pool.exemplar_texts,
        niche_descriptor=config.niche.as_text(), log=session.log)
    session.log.event("copy_complete", f"copy for {len(result.copy)} creative(s)",
                      duration_ms=watch.elapsed_ms, degraded=sorted(result.degraded),
                      trimmed=sorted(result.trimmed),
                      tags={asset_id: [tag.value for tag in tags]
                            for asset_id, tags in sorted(result.tags.items())})
    return result


async def _create(session: _Session, entries: Sequence[PlanEntry], live: Sequence[PlanEntry],
                  trends: dict[str, TrendItem], briefs: dict[str, StyleBrief],
                  copy_result: copywrite.CopyResult
                  ) -> tuple[generate.Report, Mapping[str, TrendItem]]:
    """CREATE: images, carousels and reels in two waves. Terminal entries package as honest skips.

    Returns the report **and** `mix.trends` — the render-side view — because FR-153 records the post
    ids a creative actually attached, which is only knowable after the mix has trimmed them.

    The vision check is wired in here and nowhere else: `llm_call` is the same metered wrapper the
    Analyze and Write stages use, so every check call lands in the FR-84 tally — and it is `None`
    whenever the check is off, which is what `generate/`, `carousel.py` and `reel.py` read as
    `not_checked` (FR-27). `deadline` gives them FR-108's `env.halted` without a runner callback.
    """
    if _halt(session, "generation"):  # FR-4/FR-108: nothing leaves the plan, it goes terminal
        for entry in entries:
            if entry.status is PlanEntryStatus.PENDING:
                entry.status = PlanEntryStatus.ABANDONED
                entry.skip_reason = "run deadline elapsed or interrupted before submission"
    checking = bool(session.config.run.vision_check) and session.llm is not None
    # FR-91: `mix.trends` is the RENDER-side view of Collect — trend references trimmed to make
    # room for an inspiration image. The originals stay bound to Select, Analyze and the gallery.
    mix = sources.apply_mix(live, trends, session.pool, session.config, log=session.log)
    env = generate.Env(
        config=session.config, run_dir=session.run_dir, engine=session.engine,
        budget=session.budget, log=session.log, ledger=session.ledger, trends=mix.trends,
        style_briefs=briefs, copy=copy_result.copy, copy_tags=copy_result.tags,
        niche_descriptor=session.config.niche.as_text(),
        # A15: `visual_world` ALONE, for the four gpt-image-2 roles. `niche_descriptor` above is
        # copy-side (it names the audience); this is the render-side half, and without it the
        # operator's standing art direction reached `direct`-mode images not at all.
        niche_visual_world=session.config.niche.visual_world,
        local_refs=_local_refs(session, live, mix.local_refs),
        campaign_briefs=session.campaign_briefs,
        # FR-109/A11: Notion wins when it is energised; the config's own `niche.brand` is the
        # fallback, and on this workstation it is the only source that ever fires — Notion is
        # `off` in every shipped config, so `{{brand_accent}}` had been blank on every run made.
        brand_accent=session.brand.accent or session.config.niche.brand.accent,
        brand_product_nouns=(session.brand.product_nouns
                             or session.config.niche.brand.product_nouns),
        llm_call=_metered(session) if checking else None, video_refs=session.video_refs,
        stop=session.control.stop, deadline=session.deadline)
    watch = Stopwatch()
    report = await generate.create(entries, env)
    session.log.event("generation_complete",
                      f"{len(report.packaged_trends)} trend(s) produced packaged creatives",
                      duration_ms=watch.elapsed_ms, disk_full=report.disk_full)
    return report, mix.trends


def _posts_used(session: _Session, report: generate.Report, attached: Mapping[str, TrendItem],
                entries: Sequence[PlanEntry]) -> dict[str, list[str]]:
    """FR-153: the post ids a packaged creative really ATTACHED, never merely the ones chosen.

    Two ways a chosen post can end up unused, and burning its id either way would be a lie that
    costs the operator a fresh reference set for nothing. Images: under `inspiration_mix:
    exclusive` the mix attaches no trend image at all, which is why this reads the render-side
    `attached` view rather than Collect's items. Motion: a reel keeps its reference through a
    seed-frame degrade but loses it to a failed yt-dlp probe or download, so the truth is the
    `reel_video_reference_url` the packager actually wrote — not the fact that a reel succeeded.
    """
    uses = {key: list(attached[key].chosen_post_ids) if key in attached else []
            for key in report.packaged_trends}
    for entry in entries:
        trend = attached.get(entry.trend_key or "")
        if (entry.status is not PlanEntryStatus.SUCCESS or trend is None
                or not trend.winning_video_post_id or entry.trend_key not in uses):
            continue
        if read_meta(session.run_dir / entry.asset_id).get("reel_video_reference_url"):
            uses[entry.trend_key].append(trend.winning_video_post_id)
    return uses


async def _package(session: _Session, entries: Sequence[PlanEntry], plan_estimate: Estimate,
                   report: generate.Report, attached: Mapping[str, TrendItem],
                   *, trend_supply_failed: bool,
                   plan_notes: Sequence[str] = ()) -> int:
    """PACKAGE: gallery, history, latest-pointer, spend summary, exit code (FR-75/82/84/232)."""
    _log_template_attribution(session)
    credits_line = _credits_exhausted_line(session, entries, report)  # FR-248, before the counts
    write_gallery(session.run_dir, title=session.config.output.gallery.title, log=session.log)
    if report.packaged_trends:  # FR-82: only trends that actually produced a packaged creative
        await record_use(LOGS_DIR, _posts_used(session, report, attached, entries), session.run_id,
                         history_days=session.config.run.trend_history_days, log=session.log)
    if any(entry.status is PlanEntryStatus.SUCCESS for entry in entries):
        await set_latest(session.config.output.dir, session.run_id, log=session.log)  # FR-254

    # FR-202/FR-252 both read the FR-73 tags, not the plan alone: a partial carousel ships SUCCESS
    # with no `skip_reason` (the deck DID ship — `carousel.package()` marks `incomplete` instead),
    # and `analysis_missing` lives only on the record. Mapped once, used by the line and the code.
    degradations: DegradationMap = {asset_id: record.degradations
                                    for asset_id, record in report.records.items()}
    summary = session.budget.summary(entries, plan_estimate)
    session.say(_spend_table(summary, session.counters))
    if credits_line:
        session.say(credits_line)
    if degraded_line := _analysis_degraded_line(entries, degradations):  # FR-252's named count
        session.say(degraded_line)
    for note in plan_notes:  # FR-252: what was dropped is repeated in the end-of-run summary
        session.say(f"dropped before generation: {note}")
    code = decide_exit_code(entries, interrupted=session.control.stop.is_set(),
                            trend_supply_failed=trend_supply_failed,
                            plan_reduced=bool(plan_notes), degradations=degradations)
    session.say(_final_line(session, entries, summary, code))
    # FR-232: one optional 1–3 rating per run, asked after the summary. `menu` suppresses it under
    # `--yes` and with no console attached, so nothing unattended ever waits on it.
    if (rating := await menu.ask_fidelity_rating(session.opts)) is not None:
        session.log.event("fidelity_rating", f"operator fidelity rating {rating}/3 (FR-232)",
                          rating=rating)
    return code


# --------------------------------------------------------------------------- helpers


def _local_refs(session: _Session, live: Sequence[PlanEntry],
                mix_refs: Any) -> dict[str, tuple[tuple[Path, str], ...]]:
    """Every local file a job uploads before it can reference it (FR-200), in FR-91's order: a
    brief's own images FIRST (they are what an `override` creative is about), the inspiration
    image `apply_mix()` picked LAST — which is exactly the `minority` rule.

    Each file travels WITH its kind (`brief` / `inspiration`), because position alone stops being
    readable once a prompt must NAME what each reference is (50 §3's `reference_roles`) — and a
    `Path` carries no provenance for a consumer to re-derive.
    """
    refs: dict[str, tuple[tuple[Path, str], ...]] = {}
    for entry in live:
        brief = session.campaign_briefs.get(entry.brief_name or "")
        merged = (*((path, "brief") for path in (brief.reference_image_paths if brief else ())),
                  *((path, "inspiration") for path in mix_refs.get(entry.asset_id, ())))
        if merged:
            refs[entry.asset_id] = merged
    return refs


def _log_template_attribution(session: _Session) -> None:
    """FR-184: one line per template role the run actually filled — file name, origin, hash.

    Logged at Package rather than at construction because `PromptEngine` resolves lazily: FR-184
    is "once per template role actually USED", and before Create runs the cache is empty.
    """
    rows = session.engine.attribution()
    session.log.event(
        "prompt_templates",
        "templates used: " + (", ".join(f"{row['role']}@{row['hash'][:8]}" for row in rows)
                              or "none (no prompt was assembled)"),
        templates=rows)


def _credits_exhausted_line(session: _Session, entries: Sequence[PlanEntry],
                            report: generate.Report) -> str:
    """FR-248: OpenRouter's 402 named once, distinctly from a Kie 402, and charged to what it cost.

    The latch is run-scoped and one-way (`llm.py`), so after it trips, a creative that ended with
    no cause of its own — or shipped on degraded copy / no style brief — ended that way *because of
    it*. Stamping the reason puts them in FR-84's counts and off a clean exit 0: a batch that
    silently shipped fallback copy is not a full success. `""` when credits were never the story.
    """
    if session.llm is None or not session.llm.credits_exhausted:
        return ""
    llm_starved = {DegradationTag.ANALYSIS_MISSING, DegradationTag.COPY_DEGRADED}
    degraded = {asset_id for asset_id, record in report.records.items()
                if llm_starved.intersection(record.degradations)}
    hit = [entry for entry in entries if not entry.skip_reason
           and (entry.status is not PlanEntryStatus.SUCCESS or entry.asset_id in degraded)]
    for entry in hit:
        entry.skip_reason = f"{CREDITS_EXHAUSTED_REASON} (FR-248)"
    return (f"OpenRouter returned 402 — {CREDITS_EXHAUSTED_REASON}. Every later LLM call was "
            f"skipped rather than retried (FR-248); {len(hit)} creative(s) were lost or shipped "
            "degraded under it. This is NOT a Kie.ai render 402 (FR-167) — top up OpenRouter.")


def _analysis_degraded_line(entries: Sequence[PlanEntry], degradations: DegradationMap) -> str:
    """FR-252: when EVERY analysis call failed, the summary says so and names the count. `""` else.

    30 §5's row reads: *"The run ships direct-mode creatives per FR-12 — all creatives degrade to
    analyzed→direct fallback and are marked `analysis_missing`. The summary line names the count of
    degraded creatives … Exit code 1 (partial success)."* The count is the point: `analysis_missing`
    is a per-asset badge in the gallery and a tag in `meta.yaml`, so without this line an operator
    reading the console sees six delivered creatives and no hint that not one of them was steered
    by a style brief — the analyzed half of the run silently became the direct half.

    Same trigger as `decide_exit_code`'s clause, from the same helper, so the sentence and the exit
    code can never disagree. Nothing is printed on the far more common partial degrade: that run is
    already a `1` for whatever else it lost, and a line about "3 of 6" would compete with the spend
    table for the operator's attention while naming a condition FR-252 does not legislate.

    FR-286: every line ≤78 columns, ASCII plus the `—` that `util.fit` proves safe on conhost.
    """
    delivered = [entry for entry in entries if entry.status is PlanEntryStatus.SUCCESS]
    analyzed, degraded = _analysis_degrade_counts(delivered, degradations)
    if not analyzed or degraded != analyzed:
        return ""
    return "\n".join([
        f"all {degraded} analyzed creative(s) shipped in direct mode — every",
        "  analysis call failed, so each one carries analysis_missing (FR-12);",
        "  fully-degraded analysis is a run failure, so this run exits 1 (FR-252)",
    ])


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
        watch = Stopwatch()
        result = await client.structured_call(role, messages, json_schema, images)
        held = await session.budget.commit(result.cost_usd, label=f"llm {role}",
                                           category=SpendCategory.LLM, kind="projected")
        await session.budget.reconcile(held, result.cost_usd or None)
        # NFR-5: model, duration and the prompt IN FULL. `messages` is a `_FULL_ONLY_KEYS` name, so
        # events.jsonl keeps the whole payload and run.log gets its size — 40 §4's split, verbatim.
        extra: dict[str, Any] = {"messages": messages}
        if hooks := _hook_patterns(result.parsed):
            extra["hook_pattern_used"] = hooks
        session.log.event("llm_call", f"{role} call complete", duration_ms=watch.elapsed_ms,
                          role=role, model=_role_settings(session.config, role).model,
                          image_count=len(images or ()),  # not `images`: that key is prompt-sized
                          prompt_tokens=result.prompt_tokens,
                          completion_tokens=result.completion_tokens,
                          reasoning_tokens=result.reasoning_tokens,
                          cost_usd=round(result.cost_usd, 6), degraded=result.degraded, **extra)
        return result

    return call


def _hook_patterns(parsed: Any) -> list[str]:
    """NFR-5's `hook_pattern_used`, when the answer carries one — the copy call's creatives do."""
    creatives = parsed.get("creatives") if isinstance(parsed, Mapping) else None
    return sorted({str(item.get("hook_pattern_used") or "").strip()
                   for item in creatives or () if isinstance(item, Mapping)} - {""})


def _halt(session: _Session, stage: str) -> bool:
    """Deadline/interrupt check between stages — soft by contract (FR-108: it stops ORDERING)."""
    if not session.halted:
        return False
    reason = ("Ctrl+C" if session.control.stop.is_set()
              else f"the {session.config.run.run_deadline_min}-minute run deadline")
    session.log.warn("stage_skipped", f"{stage} skipped: {reason} (FR-108/FR-201)", stage=stage)
    session.say(f"{reason} — skipping {stage} and packaging what exists")
    return True


def _stamp_provisional(entries: Sequence[PlanEntry]) -> None:
    """Give each atomic group its own provisional trend key, so the pre-Collect estimate counts
    the analysis (FR-9) and copy (FR-99) calls the operator can really be billed for.

    **Worst-case-honest, per the v1.6.5 estimator fidelity fix.** `plan.assign()` binds trends per
    *atomic group* and `_pick()` prefers the least-used trend, so a group gets a DISTINCT trend
    whenever the pool allows — up to one per group. `max_trend_reuses_per_run` only ever *reduces*
    that count, when the pool is short. Modelling the reuse ceiling here (as the M1 run did) priced
    one analysis call while two distinct trends were assigned, and understating is the one
    unacceptable estimator error (D11/FR-282). Override briefs consume no trend at all (FR-144).
    """
    for entry in entries:
        if entry.brief_influence != "override":
            entry.trend_key = f"{_PROVISIONAL}{entry.atomic_group or entry.asset_id}"


def _launch_summary(session: _Session, overrides: Sequence[str]) -> str:
    """FR-77's opening block: what this run is, resolved, before anything can change it."""
    config = session.config
    return "\n".join([
        f"HypeSocials run {session.run_id}",
        # FR-286: the niche descriptor behind `description` ran to 400 chars and produced a
        # 557-char line that conhost mangled. Path and label each get their own bounded line.
        f"  config      {fit(str(config.path), 64)}",
        f"              {fit(config.description or 'no description', 60)}",
        f"  formats     " + ", ".join(f"{name}={count}" for name, count in config.run.formats.items()),
        f"  platforms   " + ", ".join(
            f"{name}/{config.language_for(name)}" for name in config.run.platforms),
        f"  mode        {config.run.generation_mode} · notion {config.run.notion_influence} · "
        f"vision_check {str(config.run.vision_check).lower()}",
        f"  spend cap   {format_usd(config.run.spend_cap_usd)} · deadline "
        f"{config.run.run_deadline_min} min · output {session.run_dir}",
        # FR-286: an override list grows without bound, so it wraps onto its own indented lines.
        "\n".join(f"  {'overrides' if first else '         '}   {part}"
                  for first, part in wrapped(
                      ", ".join(overrides) or "none (config values as written)", 62)),
    ])


def _record_render_forecast(session: _Session, live: Sequence[PlanEntry],
                            trends: Mapping[str, TrendItem], *, dropped: int) -> None:
    """The render end of FR-155's funnel: how much Virlo material the planned jobs will attach.

    Computed here rather than read back from Create, because the funnel prints BEFORE any spend —
    its job is to let an operator abort a bad one. It mirrors `inspiration.apply_mix()`'s own rule
    (FR-91): `exclusive` replaces the trend set outright, `minority` keeps one slot for the
    inspiration image, `off` leaves the trend set whole. One count per creative, so the block can
    say "3 trend ref(s)" when they agree and "2-3" when they do not, rather than an average
    nobody could act on.

    A creative is counted as one job. A deck's later slides and a reel's clip are extra
    submissions this stage cannot know about yet, so the number is the floor, not the ceiling.
    """
    pool, config = session.pool, session.config
    per_job = max(1, config.sources.reference_images_per_job)
    exclusive = pool.active and pool.mix == "exclusive"
    inspiration = (per_job if exclusive else 1) if pool.active else 0
    keep = 0 if exclusive else max(0, per_job - (1 if pool.active else 0))
    counts = [min(len(sources.reference_group(trends.get(entry.trend_key or ""),
                                              entry.trend_reuse_index)), keep)
              for entry in live]
    session.counters.record_render(
        jobs=len(live), dropped=dropped, trend_refs=counts, inspiration_each=inspiration,
        trends_used=len({entry.trend_key for entry in live if entry.trend_key}))


#: FR-286's console width, and the label column every funnel row is laid out on.
_FUNNEL_WIDTH, _FUNNEL_LABEL = 78, 8


def _funnel_row(label: str, *clauses: str, sep: str = "; ") -> list[str]:
    """One funnel row, packed onto as many ≤78-char lines as its clauses need.

    `sep` is the join between clauses that share a line: `; ` reads as "and also" for the funnel's
    independent counts, `·` as "the same thing, described further" for A24's per-trend detail
    rows. Both are on `util.fit`'s proven-safe glyph list; `→` is NOT, and must never be emitted.

    Trend names never reach this block — they are the one unbounded token — so in practice every
    row is a single line and the wrap never fires. It exists for the arithmetic edge: a monitor
    that returns five-digit counts, or a motion clause carrying a third tier, would otherwise push
    the plan's own 76-char example past FR-286's limit. A clause is never split, so a wrapped row
    reads as its own continuation rather than as a cut sentence, and `fit()` is the last resort
    for a single clause that cannot fit at all.
    """
    head = f"  {label:<{_FUNNEL_LABEL}}"
    room = _FUNNEL_WIDTH - len(head)
    packed: list[str] = []
    for clause in (text for text in clauses if text):
        if packed and len(packed[-1]) + len(sep) + len(clause) <= room:
            packed[-1] = f"{packed[-1]}{sep}{clause}"
        else:
            packed.append(clause)
    return [f"{head if index == 0 else ' ' * len(head)}{fit(line, room)}"
            for index, line in enumerate(packed)]


def _funnel_block(counters: sources.Counters) -> str:
    """FR-155's Virlo funnel — one run-wide rollup, printed unconditionally in three places.

    Input volume, qualification, choice, downloads, Select's verdicts and what the planned jobs
    will attach, as six labelled rows under one header. A pure function of `Counters` so the paid
    run and both preview modes print the identical block from the identical numbers (FR-139),
    with no second implementation to drift.

    Two rules are load-bearing rather than cosmetic:

    - **Zero prints.** Every stage appears whether or not it lost anything, because the four
      degradation events this replaces fired in none of the archived runs and an operator cannot
      tell a healthy zero from a dead counter. The one exception is the shape below, where Virlo
      returned nothing at all: printing "0 video(s) + 0 slideshow(s); 0 duplicate row(s) dropped"
      would dress a failed fetch as a clean funnel, so that case says so in words.
    - **The vocabularies do not mix.** Input words (video, slideshow, panel, frame, post, set) sit
      on `input`/`sets`/`chosen`/`images`; output words (job) appear only on `render`. There is no
      arrow from an input word to an output word anywhere in this block, because no Virlo
      slideshow is ever rendered — it lends the trend carousel *affinity* (FR-90) and nothing more.

    ASCII only apart from the header's em-dash: `util.fit` names `·`, `—`, `…` and `←` as the
    glyphs proven safe on legacy conhost, and `→` is not one of them.
    """
    tally = counters
    # ⚠️ KNOWN, DELIBERATELY UNFIXED (2026-08-11, found by the A3 test wave): on a brief-only plan
    # `_collect(fetch_trends=False)` returns before `session.counters` is bound, so this prints the
    # zero-material sentence "Virlo returned no video and no slideshow" for a run where Virlo was
    # never contacted at all. Cosmetic — the header directly above already reads `0 monitor(s)
    # asked` — but it does assert something that did not happen. The clean fix is at the CALL SITE
    # (a brief-only run should skip the block or pass a flag), not a `monitors_asked == 0` guard
    # here: an untouched `Counters` is indistinguishable from a populated one whose caller never
    # set that field, and guarding on it silently blanks legitimate blocks.
    lines = [f"Virlo funnel — {tally.monitors_asked} monitor(s) asked, "
             f"{tally.rows_per_call} row(s) per call, {tally.monitors_failed} failed"]
    if tally.posts_raw == 0:
        lines += _funnel_row("input", "Virlo returned no video and no slideshow — "
                                      "no trend material")
    else:
        motion = tally.motion
        motion_clause = (f"motion {motion['fresh_same_creator']} same-creator, "
                         f"{motion['fresh']} fresh"
                         + (f", {motion['repeat']} repeated" if motion["repeat"] else "")
                         + (f", {motion['none']} without" if motion["none"] else ""))
        lines += _funnel_row(
            "input", f"{tally.videos_raw} video(s) + {tally.slideshows_raw} slideshow(s)",
            f"{tally.duplicates_dropped} duplicate row(s) dropped")
        lines += _funnel_row(
            "sets", f"{tally.sets_qualified} coherent set(s) qualified",
            f"{tally.sets_thin} too thin (<{tally.min_panels} panels / <{tally.min_frames} frames)")
        lines += _funnel_row(
            "chosen", f"{tally.chosen_fresh} fresh, {tally.chosen_repeated} repeated, "
                      f"{tally.chosen_last_resort} last-resort", motion_clause)
        lines += _funnel_row(
            "images", f"{tally.images_downloaded} of {tally.images_attempted} downloaded, "
                      f"{tally.images_dead} dead URL",
            (f"{tally.trends_text_only} trend{'' if tally.trends_text_only == 1 else 's'} "
             "fell to text-only" if tally.trends_text_only
             else f"cap {tally.download_cap} per trend"))
    if tally.verdict_seen:
        lines += _funnel_row(
            "verdict", f"{tally.eligible} eligible, {tally.excluded_by_history} excluded by "
                       f"history, {tally.unusable} unusable, {tally.trends_text_only} without images")
    if tally.render_seen:
        lines += _funnel_row("render", _funnel_attachment(tally),
                             (f"{tally.jobs_dropped} dropped, no trend left"
                              if tally.jobs_dropped else ""))
    return "\n".join(lines)


def _funnel_attachment(tally: sources.Counters) -> str:
    """The `render` row's first clause: jobs, and what each of them will attach."""
    refs = (str(tally.trend_refs_min) if tally.trend_refs_min == tally.trend_refs_max
            else f"{tally.trend_refs_min}-{tally.trend_refs_max}")
    return (f"{tally.jobs} job(s) will attach {refs} trend ref(s)"
            + (f" + {tally.inspiration_each} inspiration" if tally.inspiration_each else "")
            + (" each" if tally.jobs > 1 else ""))


#: A24's volume guard. Increment B splits one agent into 9 themes, so a per-trend detail section
#: would print 9–22 blocks and bury the rollup an operator reads first. A paid run gets full
#: detail for the strongest three and a one-line count of the rest; the two preview modes pass
#: `limit=None`, because printing every returned trend IS what they exist for (FR-139/140).
_DETAIL_TRENDS = 3
#: The column A24's rows and their bare-URL continuations align on — the same head `_funnel_row`
#: builds, so a URL line sits under its row's text rather than under the label.
_DETAIL_INDENT = " " * (2 + _FUNNEL_LABEL)


def _detail_head(kind: str, name: str) -> str:
    """`Sources — <trend>` / `Brief — <trend>`, bounded to FR-286's 78 columns."""
    return f"{kind} — {fit(name, _FUNNEL_WIDTH - len(kind) - 3)}"


def _assigned_trends(live: Sequence[PlanEntry],
                     trends: Mapping[str, TrendItem]) -> list[TrendItem]:
    """The trends this plan will actually spend on, deduplicated in plan order (A24).

    Deliberately not every collected trend: the detail section answers "which posts are behind
    the creatives I am about to pay for", and a trend Select judged eligible but assignment never
    used is not behind any of them. `_sources_block` re-orders by strength.
    """
    keys = dict.fromkeys(entry.trend_key for entry in live if entry.trend_key)
    return [trends[key] for key in keys if key in trends]


def _sources_block(trends: Sequence[TrendItem], *,
                   limit: int | None = _DETAIL_TRENDS) -> str:
    """A24, half one: WHICH posts these are — one block per trend, strongest first.

    The operator asked to see the inventory behind a run: what kind of post won, how big it was,
    what the source's own analyser called it, and the permalink to go and look. None of it is
    visible today without reading `events.jsonl`.

    **Printing the competitor's hooks here is deliberate and is not what A20 forbids.** A20 stops
    the ENGINE reproducing those strings into a creative; showing them to the operator is the
    entire point of "which posts these are". They are quoted so it is unambiguous that they are
    someone else's words being reported, not ours being proposed.

    Rows are emitted only when their fields carry something, so a text-only trend or a monitor
    whose rows arrived without Virlo's `intelligence` block simply prints fewer lines rather than
    a row with nothing after the label.
    """
    ordered = sorted(trends, key=lambda item: (-item.strength, item.name))
    shown = ordered if limit is None else ordered[:limit]
    lines: list[str] = []
    for trend in shown:
        if lines:  # one blank line between blocks — at 3+ trends they run together otherwise
            lines.append("")
        lines.append(_detail_head("Sources", trend.name))
        lines += _funnel_row("chosen", *_chosen_clauses(trend), sep=" · ")
        if trend.virlo_url:  # FR-286 carve-out (a): a permalink has no word boundary to wrap on
            lines.append(f"{_DETAIL_INDENT}{trend.virlo_url}")
        lines += _funnel_row("about", fit(trend.why_it_works, 60),
                             _join(trend.emotional_tones), _join(trend.tactics), sep=" · ")
        lines += _funnel_row("winners", f"{trend.total_views:,} views total",
                             f"median {trend.median_views:,}" if trend.median_views else "",
                             f"{len(trend.chosen_post_ids)} post(s) chosen"
                             if trend.chosen_post_ids else "", sep=" · ")
        lines += _funnel_row("hooks", *(f'"{fit(hook, 56)}"' for hook in _detail_hooks(trend)),
                             _join(trend.hook_types), _join(trend.visual_hook_types), sep=" · ")
        if trend.winning_video_url:  # absence is already a run-wide clause on the funnel's
            lines += _funnel_row(     # `chosen` row; repeating it per trend is noise on an
                "motion", _motion_clause(trend), sep=" · ")  # image-only plan
    if limit is not None and len(ordered) > limit:
        lines.append("")
        lines.append(f"  + {len(ordered) - limit} more trend(s), see events.jsonl")
    return "\n".join(lines)


def _chosen_clauses(trend: TrendItem) -> tuple[str, ...]:
    """The `chosen` row: what kind of post, how much material came with it, how strong it scored."""
    images = sum(len(group) for group in trend.reference_groups)
    return (
        "slideshow" if trend.is_slideshow else "video",
        f"{len(trend.reference_groups)} set(s), {images} image(s)" if images
        else "text_only — this trend arrived with no pictures",
        f"strength {trend.strength:.3f}",
    )


def _detail_hooks(trend: TrendItem, want: int = 2) -> list[str]:
    """The source's own words, in the precedence `prompts_engine._source_hooks` already uses."""
    seen = [text for text in (*trend.hook_texts, *trend.text_overlay_contents,
                              *trend.panel_texts) if text.strip()]
    return list(dict.fromkeys(seen))[:want]


def _motion_clause(trend: TrendItem) -> str:
    """The `motion` row: the reel's video reference, named by host only — the URL carries a
    token-length tail and would blow FR-286's width for no operator benefit."""
    host = trend.winning_video_url.split("//", 1)[-1].split("/", 1)[0].removeprefix("www.") \
        if trend.winning_video_url else ""
    return f"{host} (reel only)"


def _brief_block(briefs: Mapping[str, StyleBrief], trends: Mapping[str, TrendItem], *,
                 limit: int | None = _DETAIL_TRENDS) -> str:
    """A24, half two: HOW our AI analysed them — the style brief, in four rows.

    `hook_pattern`, `content_angle`, the palette and the exclusion count are the four things an
    operator judging a creative wants from the brief, and none of them is visible today outside
    `events.jsonl` with `verbose_only` enabled (`_analyze` logs the full brief there). Printed
    after Analyze rather than after Select, because until Analyze has run there is no brief.

    Briefs are keyed by the (trend, reference group) PAIR since FR-91's rotation, so one trend can
    produce several — the group is named when it does, and the strongest trends lead.
    """
    def rank(brief: StyleBrief) -> tuple[float, str, int]:
        trend = trends.get(brief.trend_key)
        return (-(trend.strength if trend else 0.0), brief.trend_key,
                brief.reference_group_index)

    ordered = sorted(briefs.values(), key=rank)
    shown = ordered if limit is None else ordered[:limit]
    per_trend = Counter(brief.trend_key for brief in ordered)
    lines: list[str] = []
    for brief in shown:
        if lines:
            lines.append("")
        trend = trends.get(brief.trend_key)
        name = trend.name if trend is not None else brief.trend_key
        if per_trend[brief.trend_key] > 1:
            name = f"{name} [reference group {brief.reference_group_index + 1}]"
        lines.append(_detail_head("Brief", name))
        lines += _funnel_row("pattern", fit(brief.hook_pattern, 66), sep=" · ")
        lines += _funnel_row("angle", fit(brief.content_angle, 66), sep=" · ")
        lines += _funnel_row("palette", *brief.palette[:4], sep=" · ")
        lines += _funnel_row("forbids", f"{len(brief.exclusions)} observed string(s) blocked "
                                        "from the frame" if brief.exclusions else "", sep=" · ")
    if limit is not None and len(ordered) > limit:
        lines.append("")
        lines.append(f"  + {len(ordered) - limit} more brief(s), see events.jsonl")
    return "\n".join(lines)


def _join(values: Sequence[str], sep: str = ", ") -> str:
    return sep.join(str(value) for value in values if str(value).strip())


def _money(amount: float) -> str:
    """Cents normally, four decimals below one cent — an LLM line that really cost $0.0024 must
    not print as the `$0.00` an unpriced line prints (FR-85's *estimated* honesty, same idea)."""
    return f"${amount:.4f}" if 0 < amount < 0.01 else format_usd(amount)


def _spend_table(summary: SpendSummary, counters: sources.Counters | None = None) -> str:
    """FR-84's ONE spend table: per creative, per format, then the grand total and cap status.

    FR-155 adds one row directly under the headline — the whole Virlo funnel as a single chain,
    so a run "shrunk by trend supply" is legible beside the headline that says it delivered less
    than it was asked for. The chain is post-dedupe throughout (the posts the pipeline read, not
    the rows Virlo shipped) and it is the FORECAST end at its right-hand side: the funnel block
    printed before Analyze already showed those numbers, and re-deriving "refs actually attached"
    from delivered assets here would answer a different question in the same shape.
    """
    # FR-286: asset ids run to ~46 chars, so a fixed 40-wide column both overflowed 78 AND ran
    # into the format column with no space (`..._04image`). Fit the one variable column instead.
    lines = [summary.headline]
    if counters is not None and counters.posts_kept:
        lines += _funnel_row("virlo", f"{counters.posts_kept} post(s) -> "
                                      f"{counters.sets_qualified} set(s) -> "
                                      f"{counters.trends_used} trend(s) -> "
                                      f"{counters.refs_total} ref(s) on {counters.jobs} job(s)")
    lines.append(f"  {'asset':<38} {'format':<9}{'est':>9}{'billed':>10} ok")
    for row in summary.rows:
        mark = "yes" if row.delivered else "no"
        billed = format_usd(row.billed_usd) + (" est" if row.estimated_only else "")
        lines.append(f"  {fit(row.asset_id, 38):<38} {row.creative_format:<9}"
                     f"{format_usd(row.estimated_usd):>9}{billed:>10} {mark}")
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
    detail = f" ({fit(', '.join(reasons), 40)})" if reasons else ""
    # FR-286: `total` covers Kie and OpenRouter only. Virlo's own calls meter against the Virlo
    # deposit, so an unqualified `total $0.00` on a run that opened a session was a false statement.
    metered = " + Virlo metering" if session.virlo_contacted else ""
    return "\n".join([
        f"run {session.run_id} · total {_money(summary.total_usd)} (Kie/OpenRouter){metered}",
        f"  {session.clock.elapsed_s:.1f}s · generated {delivered} · skipped {skipped}{detail}",
        f"  status {status} · exit code {code} ({_EXIT_LEGEND[code]})",
        f"  folder {fit(str(session.run_dir), 68)}",
    ])


async def _cleanup(session: _Session) -> None:
    """FR-249: scratch, clients and log handles released on EVERY exit path, in a safe order.

    Every step is independent and swallowed: a run that already failed must not fail again on the
    way out, and a real Ctrl+C reaches the MCP wrapper and yt-dlp too, so some children are
    already gone before we get here (spikes/RESULTS.md §F — `ProcessLookupError` is expected).
    """
    steps = [close_downloads()]
    if session.video_refs is not None:  # cancels outstanding yt-dlp chains, sweeps their scratch
        steps.insert(0, session.video_refs.aclose())
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
    for sweep in (sources.cleanup, video_ref.cleanup):  # scratch downloads (FR-249), idempotent
        try:
            sweep()
        except OSError as exc:
            logger.warning("scratch cleanup failed: %s", exc)
    session.log.close()


__all__ = [
    "Control", "EXIT_INTERRUPTED", "EXIT_NOTHING_USABLE", "EXIT_OK", "EXIT_PARTIAL",
    "EXIT_PREFLIGHT", "LOGS_DIR", "DegradationMap", "decide_exit_code", "list_monitors", "run",
]
