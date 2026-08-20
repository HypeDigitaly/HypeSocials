"""The lifecycle conductor — one run, stage by stage, in the order the PRD diagram draws them.

Module contract
---------------
Purpose: sequence a whole run and own everything that is true of the run rather than of one
creative — the run folder and its logs, the Confirm gate, the deadline, the spend summary, the
exit code, and the guarantee that every exit path leaves the disk, the pointers and the
subprocess tree in a defensible state.

Public API: `await run(opts, control)` · `await list_monitors(opts)` · `Control` ·
`decide_exit_code()` · the five `EXIT_*` codes.

Stage order is BINDING (00-overview §1, v2.0.0) and any reorder is a PRD conflict:

    Config → plan expansion → pre-flight → cost estimate → **Confirm** → Collect (Virlo MCP,
    text-only topics) → topic filter (`_screen_topics`, FR-294) → Select + assign → honesty
    restatement → style + branding rotation (FR-291) → Write (verbatim copy) → Create → Package.

Collect, the filter and Select all run *after* the confirmation, which is exactly why FR-8's
one-line restatement exists: topic supply can shrink a plan the operator already approved, and
they are told before generation proceeds rather than after delivery. The console narrates every
stage per §1.10 (D45, FR-296–300): numbered headers with in → out counts, the topics table as
the visible sort proof, the post roster, the provenance block, and silence-breaker heartbeats.

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
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hypesocials import (
    cli, copywrite, generate, menu, plan, preflight, render, sources, styles, topic_filter)
from hypesocials.budget import Budget, Estimate, SpendCategory, SpendSummary, estimate, format_usd
from hypesocials.config import LOGS_DIR, Config, ConfigError, load_config
from hypesocials.llm import CREDITS_EXHAUSTED_REASON, LLMClient, RoleSettings
from hypesocials.models import (
    AssetRecord, Brief, CopySet, DegradationTag, ParsedResult, PlanEntry, PlanEntryStatus,
    SourcePost, TrendItem)
from hypesocials.outputs import (
    Ledger,
    LogWriter,
    close_downloads,
    create_run_folder,
    read_gauntlet_report,
    read_history,
    record_use,
    save_reference,
    set_latest,
    used_posts,
    write_gallery,
)
from hypesocials.prompts_engine import PROMPTS_DIR, PromptEngine
from hypesocials.util import Deadline, Pulse, Stopwatch, fit, new_run_id, wrapped

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
class _RoleUsage:
    """One LLM role's whole run: how many calls, how many tokens each way, and what it cost."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, result: ParsedResult) -> None:
        self.calls += 1
        self.prompt_tokens += int(result.prompt_tokens or 0)
        self.completion_tokens += int(result.completion_tokens or 0)
        self.cost_usd += float(result.cost_usd or 0.0)


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
    campaign_briefs: dict[str, Brief] = field(default_factory=dict)  # D26, by brief name
    brand: sources.BrandContext = field(default_factory=sources.BrandContext)  # FR-34/36
    # --- §1.10 (D45, FR-296–300) console state, all set once by `_pipeline`/`_open`:
    verbose: bool = False  # `--verbose` OR `output.console_verbosity: verbose` — console tier ONLY
    pulse: Pulse = field(default_factory=Pulse)  # FR-299 silence-breaker; every say()/note() stamps
    stages: list[str] = field(default_factory=list)  # the LIVE stage list — [n/N] is computed off it
    stage_watch: Stopwatch = field(default_factory=Stopwatch)  # elapsed for the current stage header
    registry: Any = None  # styles.StyleRegistry, loaded once post-Confirm (FR-290; hash logged)
    #: FR-294/M6: the filter's `strip` verdicts, re-keyed trend_key -> brands. `_write` hands them
    #: to copywrite, and the SAME mapping rides `generate.Env` so LLM-discovered brands reach every
    #: render prompt's `competitor_strings`, not only the CopySet (Session-C obligation 2).
    strip_brands: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: FR-307: the burnt post-id union read before Collect — the fetch gate consumes it there,
    #: and `_write` hands the SAME set to copywrite's pick-time guard (belt-and-braces; one
    #: read, two enforcement points, zero drift).
    used_post_ids: frozenset[str] = frozenset()
    #: FR-84/FR-326 (v2.2.0): `role -> _RoleUsage` — what every metered LLM call actually cost,
    #: accumulated at the ONE seam every call passes through (`_metered`). It exists because the
    #: gauntlet made LLM spend the larger half of a run's bill at worst case (spec §5), and a
    #: single `llm $0.42` line can no longer answer "which role, and how many tokens".
    llm_usage: dict[str, _RoleUsage] = field(default_factory=dict)
    #: FR-306: `post_id -> SlideIntel` from the INTEL stage — `_write` derives `merged_panels`
    #: from it and `_create` rides it onto `generate.Env.slide_intel` for the per-slide briefs.
    slide_intel: dict[str, Any] = field(default_factory=dict)

    def say(self, text: str) -> None:
        """Print one operator-facing block and put the identical (redacted) text in run.log."""
        print(self.log.narrative(text))
        self.pulse.stamp()  # FR-299: ANY printed line resets the heartbeat's quiet clock

    def note(self, text: str) -> None:
        """FR-299's verbosity seam: run.log ALWAYS, console only when verbose.

        events.jsonl and run.log are UNCHANGED by verbosity — only the console tier moves
        (contracts item 16). A note that does print counts as console output and stamps the
        heartbeat clock exactly as `say` does.
        """
        line = self.log.narrative(text)
        if self.verbose:
            print(line)
            self.pulse.stamp()

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

    `0` every planned creative delivered · `1` completed with losses (skipped, failed, trimmed,
    abandoned, or BLOCKED by the post-render gate) · `2` pre-flight refusal or config error,
    nothing spent · `3` fatal after Collect
    began — zero usable trends for a plan that needed them, or a transport-dead source · `4`
    interrupted by SIGINT.

    The brief-only carve-out lives in the `trend_supply_failed` branch: a trend famine is fatal
    only when it left nothing deliverable. If override-brief creatives shipped anyway the run is
    a partial success (`1`), and a brief-only plan that delivered everything is a plain `0`.

    **`degradations` is the FR-73 tag list per asset id** — `generate.Report.records` mapped to
    `AssetRecord.degradations` — and it is passed rather than re-derived because one of FR-202's
    code-1 clauses is simply not visible on a `PlanEntry`:

    - *"or a delivered carousel shipped incomplete (missing slides, FR-20/§10 — a lost slide is a
      loss even when the deck ships; v1.6.7)"*. A partial deck ends `SUCCESS` with **no**
      `skip_reason`: `carousel.package()` marks `incomplete` on the folder and logs the missing
      numbers, because the deck DID ship and `skip_reason` means "this creative did not". The live
      run of 2026-08-11 (`20260811_233910_wikf`) proved the gap — one deck lost slide 2 to a Kie
      timeout, wrote `slide_count: 4`, `missing_slide_numbers: [2]`, `degradations:
      ['text_trimmed', 'incomplete']`, and the run still exited 0 saying "everything planned was
      delivered". `_DELIVERED_LOSS_TAGS` is what closes it; a `skip_reason` on a delivered creative
      (FR-248's credits latch stamps one) remains a loss exactly as before.

    The pre-pivot fully-degraded-analysis clause died with the
    analysis stage itself (v2.0.0 — FR-202's analyzed clause deleted; there is no analyzed/direct
    split to degrade between). `COPY_DEGRADED` remains a code-1 loss through the FR-248 latch and
    the `llm_starved` set — an explicit D42 decision: a failed copy call is still a loss to
    surface, even though the fallback content (the top post's caption verbatim) is legitimate.

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
    # FR-325 (v2.2.0, D49): ANY blocked creative is a code-1 run, stated as its own branch rather
    # than left to fall out of the `whole` arithmetic below. It would fall out of it today — a
    # BLOCKED entry is not SUCCESS — but "a deck the quality gate refused makes the run exit 1" is
    # a contract a scheduler reads, and a contract that holds by accident is a contract one
    # refactor away from not holding. The creative rendered and was paid for; it is not published.
    if any(entry.status is PlanEntryStatus.BLOCKED for entry in entries):
        return EXIT_PARTIAL
    whole = [entry for entry in delivered
             if not entry.skip_reason
             and not _DELIVERED_LOSS_TAGS.intersection(tags.get(entry.asset_id, ()))]
    if len(whole) != len(entries) or plan_reduced:
        return EXIT_PARTIAL
    return EXIT_OK


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
    # FR-299: the console tier and the heartbeat cadence, resolved once. run.log/events.jsonl
    # are untouched by either — verbosity moves ONLY what reaches the screen (item 16).
    session.verbose = bool(getattr(opts, "verbose", False)) \
        or config.output.console_verbosity == "verbose"
    session.pulse.interval_s = 15.0 if session.verbose else (90.0 if opts.yes else 30.0)
    session.registry = _load_registry(session)  # FR-290: once, hash logged; None = FR-295 pending
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
    # (FR-144), so Collect opens no Virlo session and a trend famine can never abort it. The
    # stage list is computed HERE — [n/N] is a property of the resolved plan (FR-296).
    brief_only = all(entry.brief_influence == "override" for entry in resolved.entries)
    session.stages = _live_stages(config, brief_only=brief_only)
    trends = await _collect(session, fetch_trends=not brief_only)
    verdicts = await _screen_topics(session, trends) if trends else {}
    if trends:  # FR-297a: the sort proof, once, right after FILTER — previews share this block
        session.say(_topics_table(trends, verdicts,
                                 window_days=session.config.sources.max_post_age_days))
    # A filter `skip` never reaches Select: the topic is dropped here, before any render spend,
    # and the table row + FILTER detail line above are its whole story (§1.5).
    kept = [topic for ordinal, topic in enumerate(trends, start=1)
            if (verdicts.get(ordinal) is None or verdicts[ordinal].verdict != "skip")]
    assignment = _select(session, kept, resolved.entries)
    # Re-priced with the topics actually assigned: the shared filter/copy calls of FR-107/FR-99
    # are per distinct topic, so the per-entry shares only become real once assignment has run.
    plan_estimate = estimate(config, resolved.entries)
    _restate(session, assignment, plan_estimate)
    live = [entry for entry in live if entry.status is PlanEntryStatus.PENDING]

    by_key = {topic.history_key: topic for topic in kept}
    _assign_visuals(session, live, by_key, brief_only=brief_only)  # ASSIGN: FR-291 rotation
    # FR-155's forecast end: after assign, before any spend — the last moment Ctrl+C is free.
    _record_style_forecast(session, live, session.registry, dropped=len(assignment.dropped))
    if kept and not brief_only:  # FR-297b: WHICH posts, and who quotes them — after assignment
        # W5 live finding (2026-08-13): the roster must receive the SAME sequence the screen
        # numbered — `verdicts` keys on ordinals over `trends`, and passing the post-filter
        # `kept` list re-numbered it, so every topic after a skip printed its predecessor's
        # verdict (the paid run showed `skip:PROMO` on a kept-and-quoted topic). The roster's
        # own `chosen` filter keeps unassigned (hence skipped) topics out of the printout.
        session.say(_post_roster(
            trends, verdicts, live,
            topics_limit=None if session.verbose else _DETAIL_TRENDS,
            posts_limit=None if session.verbose else _DETAIL_TRENDS))
    _store_references(session, live)
    await _slide_intel(session, live, by_key)  # FR-306: post-Confirm, before COPY
    copy_result = await _write(session, live, by_key, session.strip_brands)
    report, attached = await _create(session, resolved.entries, live, by_key, copy_result)

    # The brief-only carve-out (10 §10): a topic famine is fatal only when nothing was deliverable,
    # and a brief-only plan never had a topic supply to fail — its losses are ordinary (exit 1).
    return await _package(session, resolved.entries, plan_estimate, report, attached, copy_result,
                          trend_supply_failed=not brief_only
                          and not any(e.trend_key for e in resolved.entries),
                          plan_notes=resolved.notes)  # FR-252: pre-expansion drops exit 1


def _load_registry(session: _Session) -> Any:
    """The run's ONE registry load (FR-290) — origin + hash logged per FR-184.

    `None` when the registry is missing or unusable: the launch block says so and pre-flight's
    FR-295 check is the authority that turns it into an exit-2 refusal a few lines later; loading
    twice (here and in `preflight.check`) is two reads of one file, not two sources of truth.
    """
    config = session.config
    try:
        registry = styles.load_registry([config.prompts_dir, PROMPTS_DIR])
    except styles.StyleRegistryError as exc:
        session.log.warn("style_registry_unavailable", str(exc))
        return None
    session.log.event("style_registry", f"registry v{registry.version} from {registry.origin}",
                      version=registry.version, origin=registry.origin,
                      content_hash=registry.content_hash, styles=[s.key for s in registry.styles])
    return registry


def _assign_visuals(session: _Session, live: Sequence[PlanEntry],
                    topics: Mapping[str, TrendItem], *, brief_only: bool) -> None:
    """ASSIGN (FR-291): deterministic style + branding rotation, narrated as receipts.

    `assign_styles` sees only the entries that follow the registry — an `override` brief
    suppresses the style channel entirely (M14; its `style_key` stays "" and meta.yaml records
    `brief_override`). `assign_branding` covers EVERY entry: a brief creative can still be
    branded. One detail line per creative is the determinism receipt (§1.10).

    FR-318's master switch rides both calls. With `branding.enabled` false the pool loses its
    `brand_slot` house cards and the rotation predicate never runs, so the receipt below prints
    `plain` on every line and the ASSIGN header prints `0 branded` — the switch is visible in the
    same place the rotation always was, rather than in a separate announcement.
    """
    branding = session.config.branding
    styled = [entry for entry in live if entry.brief_influence != "override"]
    if session.registry is not None and styled:
        styles.assign_styles(styled, session.registry, branding.brand,
                             enabled=session.config.styles.enabled,  # FR-314 selector
                             branding_enabled=branding.enabled,  # FR-318 master switch
                             # v2.2.0: the rotation's per-run offset. The run id is the seed, so
                             # two runs of one config no longer open with the same style; the
                             # receipt lines below still show exactly what was assigned.
                             run_id=session.run_id,
                             rotation=session.config.styles.rotation)
    styles.assign_branding(live, branding.brand_ratio, enabled=branding.enabled)
    topic_count = len({entry.trend_key for entry in live if entry.trend_key})
    used = len({entry.style_key for entry in live if entry.style_key})
    branded = sum(1 for entry in live if entry.branded)
    _stage(session, "ASSIGN", f"{len(live)} creative(s) <- {topic_count} topic(s), "
                              f"{used} style(s), {branded} branded", elapsed_s=0.0)
    for entry in sorted(live, key=lambda e: e.order):
        topic = topics.get(entry.trend_key or "")
        subject = topic.name if topic is not None else (entry.brief_name or "-")
        session.say(f"          {entry.asset_id.rsplit('_', 1)[-1]:>2} {entry.creative_format:<9}"
                    f" {fit(subject, 24):<24} "
                    f"{fit(entry.style_key or 'brief_override', 19):<19} "
                    f"{'brand' if entry.branded else 'plain'}")
        session.log.event("visuals_assigned", f"{entry.asset_id}: {entry.style_key or 'override'}",
                          asset_id=entry.asset_id, style_key=entry.style_key,
                          branded=entry.branded, order=entry.order)
    if brief_only:
        session.note("brief-only plan: styles suppressed for override briefs (M14); branding "
                     "rotation still applies")


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
        edit_model_ids={config.models.image_profile: config.models.image_edit},
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
        # v2.2.0 (D49): `critic` joins the roster. `llm.py:169` RAISES on an unregistered role, so
        # a critic call would take the whole gate down rather than degrade it — registration is
        # what makes `models.critic or models.analysis` a runtime fact instead of a config comment.
        {role: _role_settings(config, role) for role in _live_roles(config)},
        max_inflight_llm_calls=config.models.max_inflight_llm_calls,
        http_max_attempts=config.models.http_max_attempts,
        on_warning=session.log.warn)


#: Which model each LLM role rides. A DICT rather than the two-way ternary this was, because
#: v2.2.0 added a third role and a ternary cannot grow a third arm without silently mis-answering
#: for the one it does not name (an unknown role would have resolved to `models.copy`, so every
#: critic call would have gone out on Luna at Luna's token cap). `critic` resolves at REGISTRATION,
#: not at the call site: `models.StructuredCall` takes a role NAME and never a model id, and
#: `models.critic or models.analysis` is spec §4's stated fallback for a config that never set it.
_ROLE_MODEL = {
    "analysis": lambda models: models.analysis,
    "copy": lambda models: models.copy,
    "critic": lambda models: models.critic or models.analysis,
}

#: Which `models.*` knob bounds each role's REASONING — same dict shape as `_ROLE_MODEL`, and a
#: dict for the same reason. A role absent from this map sends no `reasoning` field at all, and on
#: a thinking model that is not "no thinking": it is the model's own full effort, billed inside
#: `completion_tokens` where no per-role cap of ours can see it. That omission is exactly what made
#: the Session 5 acceptance run spend $1.30 on critic calls (F5) — `critic` is bounded at `low` by
#: default here, and the per-critic `critic:<name>` overrides inherit it because they are a choice
#: of MODEL, never a second thinking budget. `analysis` is deliberately still absent: its 12,000
#: token cap was sized around the unbidden reasoning it already bills (30 §2), and bounding it is a
#: separate measurement, not a free ride on this one.
_ROLE_EFFORT = {
    "copy": lambda models: models.reasoning_effort,
    "critic": lambda models: models.critic_reasoning_effort,
}


def _live_roles(config: Config) -> list[str]:
    """Every LLM role THIS run may call, including the per-critic overrides (spec §1/§4).

    `critic:<name>` exists only when that critic carries its own `model:` in config. The gauntlet
    asks for that role by name and falls back to the plain `critic` role when it is not registered
    (`gauntlet._invoke`), so an unregistered override costs a per-critic model and never a critic —
    but registering the ones that ARE configured is what makes the override work at all.
    """
    critics = getattr(config.run.gauntlet, "critics", {}) or {}
    return ["analysis", "copy", "critic",
            *(f"critic:{name}" for name, critic in sorted(critics.items())
              if getattr(critic, "model", None))]


def _role_settings(config: Config, role: str) -> RoleSettings:
    """One LLM role from config. `temperature` stays opt-in — RESULTS.md §E: neither shipped
    model advertises it, and sending it under `require_parameters` is a 404 (FR-129 conflict).

    A `critic:<name>` role is the shared `critic` role with ONE field replaced — the model. Its
    token caps, floors, reasoning effort and temperature support are the critic role's, because a
    per-critic override is a choice of model and never a second budget: `max_tokens.critic` sizes a
    critic's answer (spec §4), and a defect report is the same shape whichever model writes it.

    `reasoning_effort` comes from `_ROLE_EFFORT` and is `None` only for a role that has no knob —
    see that map for why "no knob" is the expensive answer rather than the free one (F5).
    """
    models = config.models
    base, _, critic_name = role.partition(":")
    override = ((getattr(config.run.gauntlet, "critics", {}) or {}).get(critic_name)
                if base == "critic" and critic_name else None)
    effort = _ROLE_EFFORT.get(base)
    return RoleSettings(
        model=(getattr(override, "model", None)
               or _ROLE_MODEL.get(base, _ROLE_MODEL["analysis"])(models)),
        max_tokens=config.max_tokens_for(base),
        max_tokens_floor=models.max_tokens_floor.get(base, 0),
        reasoning_effort=effort(models) if effort else None,
        temperature=models.temperature.get(base),
        temperature_supported=base in models.temperature)


# --------------------------------------------------------------------------- stages


async def _collect(session: _Session, *, fetch_trends: bool = True) -> sources.TrendFeed:
    """Collect: every active adapter through the bounded Virlo MCP session pool (20 §3), plus the
    Notion brand channel riding this stage (FR-34/36, fetched once; `notion_influence: off`
    opens no session, and under `full` its snapshot folds into the ACTIVE branding profile via
    `apply_brand_overrides` — dormant until a NOTION_TOKEN exists, D43). `fetch_trends=False` is
    10 §10's brief-only carve-out — a pure-override plan needs no topic, so no Virlo session is
    opened at all and no COLLECT/TOPICS stage exists (FR-296).

    Narration (FR-296): the `collecting…` opener is the liveness line, the COLLECT header closes
    with monitors → posts, and the TOPICS header states the FR-293 split — posts → topics with
    the per-monitor cap and the synthesized count. Both read the funnel `Counters`, so a number
    here never has a second source.
    """
    watch = Stopwatch()
    session.brand = await sources.fetch_brand_context(session.config, log=session.log)
    if session.config.run.notion_influence == "full":
        for line in sources.apply_brand_overrides(session.brand, session.config.branding):
            session.note(f"notion override: {line}")
    if not fetch_trends:
        session.say("brief-only plan: every creative is an override brief, so no topic\n"
                    "is consumed and no Virlo session is opened")
        return sources.TrendFeed()
    # FR-7/FR-153: the used-post window is read BEFORE Collect so the adapter can annotate what
    # Select will exclude. Post ids are globally unique — one flat union, no per-topic split.
    window = session.config.run.trend_history_days
    fresh_against = {post for posts in used_posts(read_history(LOGS_DIR, session.log),
                                                  within_days=window).values() for post in posts}
    session.used_post_ids = frozenset(fresh_against)  # FR-307: one read, two enforcement points
    session.virlo_contacted = "virlo" in session.config.sources.active
    monitors = len([m for m in session.config.sources.virlo_monitor_ids if str(m).strip()])
    # FR-296 (v2.1.0): the header states the recency window in force, so a stale-looking topic
    # list is arguable from the console alone — `0` prints as `off` because an operator who
    # disabled the cap should read that back, not a zero that looks like a bug.
    age = session.config.sources.max_post_age_days
    descriptor = f"window <={age}d" if age else "window off"
    _stage(session, "COLLECT",
           f"collecting trends from {monitors} monitor(s) ({descriptor})", opening=True)
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
    tally = session.counters
    _stage(session, "COLLECT",
           f"{tally.monitors_asked} monitor(s) asked -> {tally.posts_kept} post(s), "
           f"{tally.monitors_failed} failed", elapsed_s=watch.elapsed_s)
    cap = session.config.sources.virlo_topics_per_monitor
    _stage(session, "TOPICS",
           f"{tally.posts_in} post(s) -> {tally.topics_out} topic(s), "
           f"cap {cap}/monitor, {tally.topics_synthesized} synth", elapsed_s=0.0)
    session.log.event("collect_complete", f"{len(trends)} topic(s) collected",
                      duration_ms=watch.elapsed_ms, trends=[t.history_key for t in trends])
    return trends


def _select(session: _Session, trends: list[TrendItem],
            entries: list[PlanEntry]) -> plan.Assignment:
    """Select + assign, then the FR-8 ceiling check and 10 §10's four-cause abort message.

    FR-296 narration: the SELECT header states topics in → the three verdict buckets, and every
    NON-eligible verdict is echoed with its cause (`<name> [excluded: …]`) — a drop is a decision
    with a cause, and those are exactly the lines the default console tier shows.
    """
    config = session.config
    watch = Stopwatch()
    selection = plan.select(trends, config, read_history(LOGS_DIR, session.log))
    # FR-155: Select owns these three buckets, so Select is where the funnel learns them. The
    # adapter can count material; only this stage can count verdicts.
    session.counters.record_selection(eligible=len(selection.eligible),
                                      excluded=len(selection.excluded),
                                      unusable=len(selection.unusable))
    _stage(session, "SELECT",
           f"{len(trends)} topic(s) -> {len(selection.eligible)} eligible, "
           f"{len(selection.excluded)} seen lately, {len(selection.unusable)} unusable",
           elapsed_s=watch.elapsed_s)
    eligible_keys = {trend.history_key for trend in selection.eligible}
    for verdict in selection.verdicts:
        session.log.event("trend_verdict", f"{verdict.trend.name}: {verdict.label}",
                          trend=verdict.trend.history_key, strength=verdict.trend.strength,
                          components=verdict.trend.strength_components)
        if verdict.trend.history_key not in eligible_keys:
            session.say(f"          {fit(verdict.trend.name, 24):<24} [{fit(verdict.label, 38)}]")
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
    # FR-307's supply arithmetic, printed the moment a carousel starves rather than only inside the
    # abort path: the plan may still ship its other decks, and "3 carousels found no unused source
    # slideshow" with no numbers beside it reads as a bug rather than as a cadence fact. `plan` owns
    # the counts (including the per-platform floor they were screened at); this stage owns the
    # wording and says which way the remedy points.
    if assignment.no_fresh_post_skips:
        supply = assignment.fresh_post_line
        session.log.event("carousel_supply", supply,
                          available=assignment.carousel_posts_available,
                          bound=assignment.carousel_posts_bound,
                          floor=assignment.carousel_floor,
                          skipped=assignment.no_fresh_post_skips)
        session.say("\n".join(part for _, part in wrapped(
            supply + " — run less often or add monitors; widening --history-days makes this worse",
            76)))
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
    """FR-8 / 30 §4's honesty rule: say out loud when Select shrank an approved plan.

    Wrapped, not truncated (FR-286): the summary line names counts the operator approved money
    against, and `assignment.summary_line` can legitimately exceed one console line post-pivot.
    """
    line = (f"{assignment.summary_line} — proceeding with "
            f"{len(assignment.decisions) - len(assignment.dropped)} creative group(s), revised "
            f"estimate {format_usd(plan_estimate.expected_usd)}")
    session.log.event("plan_restated", line, dropped=len(assignment.dropped))
    if assignment.dropped or session.opts.interactive:
        session.say("\n".join(part for _, part in wrapped(line, 76)))


def _store_references(session: _Session, live: Sequence[PlanEntry]) -> None:
    """Copy every BRIEF reference image this run attaches into `refs/`, keyed by brief (FR-71).

    D46 excised the style picture channel (F3): a meta-style is words, so the run-level `refs/`
    store holds brief reference images ONLY — `refs/<brief_name>/image_<index>` — deduplicated
    across the entries that share a brief. The per-asset copy (`AssetFolder.add_reference`, D26)
    still ships beside each creative; this run-level folder is the one place a reviewer can see
    a brief's own photos without opening asset folders. Entries without a brief contribute
    nothing, which post-pivot makes an empty `refs/` the normal case.
    """
    stored: dict[str, list[Path]] = {}
    for entry in live:
        brief = session.campaign_briefs.get(entry.brief_name or "")
        if brief is None:
            continue
        paths = stored.setdefault(entry.brief_name or "", [])
        for raw in brief.reference_image_paths:
            if (path := Path(raw)) not in paths:
                paths.append(path)
    for key, paths in stored.items():
        for index, path in enumerate(paths, start=1):
            try:
                save_reference(session.run_dir, key, path.read_bytes(), index=index,
                               suffix=path.suffix)
            except OSError as exc:
                session.log.warn("reference_copy_failed", f"{key}: {exc}", brief=key)
            else:
                session.note(f"          brief ref stored  {key}  {path.name}")


async def _write(session: _Session, live: Sequence[PlanEntry], trends: dict[str, TrendItem],
                 strip_brands: Mapping[str, Sequence[str]]) -> copywrite.CopyResult:
    """WRITE: one Luna call per (topic × language), split on failure, never per creative (FR-99).

    Verbatim reference selection (§1.7): the styles view supplies each creative's on-image
    budgets, `competitors` is the fail-closed blocklist, and `strip_brands` carries the filter's
    guarded LLM verdicts re-keyed by trend_key (the runner passes `session.strip_brands`;
    previews pass their own — the parameter is the pinned seam, contracts W3). FR-299: the COPY
    wait gets a silence-breaker heartbeat reading the module's live progress tally.
    """
    if not live or _halt(session, "copywriting"):
        return copywrite.CopyResult()
    config = session.config
    watch = Stopwatch()
    groups = len({(entry.trend_key or f"brief:{entry.brief_name}", entry.language)
                  for entry in live})
    _stage(session, "COPY", f"{groups} call(s) for {len(live)} creative(s)", opening=True)
    progress: dict[str, int] = {}
    styles_by_key = ({style.key: style for style in session.registry.styles}
                     if session.registry is not None else {})

    def heartbeat() -> str:
        return (f"          copy {progress.get('done', 0)}/{progress.get('total', groups)} done, "
                f"{progress.get('in_flight', 0)} in flight ... {_dur(watch.elapsed_s)}")

    result = await _with_pulse(session, copywrite.write_copy(
        live, trends=trends, styles=styles_by_key, call=_metered(session), engine=session.engine,
        campaign_briefs=session.campaign_briefs,  # FR-146: the brief's directives steer the copy
        # FR-109: Notion text reaches the copywriter only — and FR-318 gates it here, at the one
        # place that holds both the config and the call: with `branding.enabled` false the copy
        # LLM is given no brand facts at all, so nothing it writes can be about us. The gate is a
        # caller's job because `copywrite` receives a plain string and has no config to consult.
        brand_context=session.brand.text if config.branding.enabled else "",
        text_budgets=config.run.text_budgets,
        conventions={name: config.platform(name).conventions for name in config.run.platforms},
        onimage_languages={entry.asset_id: config.onimage_language_for(entry.platform)
                           for entry in live},
        competitors=tuple(config.branding.competitors),  # §1.5 layer 1, fail-closed
        strip_brands=dict(strip_brands),  # the filter's guarded LLM strips (M6)
        # FR-306/FR-307 (D46): the INTEL stage's merged per-slide readings (post_id-keyed —
        # siblings on one post see one reading) and the burnt set for the pick-time guard.
        merged_panels={pid: list(intel.panel_texts)
                       for pid, intel in session.slide_intel.items()} or None,
        # FR-312 (§1.5 layer 3): the same decks' CHROME, per post — watermarks, counters and
        # swipe cues the vision pass kept out of the panel words. A panel line that merely
        # echoes one of them is the creator's furniture, and copywrite drops it.
        chrome_lines={pid: [slide.chrome_text for slide in intel.slides
                            if str(slide.chrome_text or "").strip()]
                      for pid, intel in session.slide_intel.items()} or None,
        burnt_post_ids=sorted(session.used_post_ids),
        # D54/FR-331: the operator's copy contract for BOUND carousel decks. This is the single
        # production call site, so it is also the only place the key is read for copy — previews
        # reach the same function through this one (`--preview-analysis` included), which is what
        # makes the preview an honest rehearsal of the paid run's words.
        carousel_copy_mode=config.run.carousel_copy_mode,
        progress=progress,
        niche_descriptor=config.niche.as_text(), log=session.log), heartbeat, suppress_s=10.0)
    session.log.event("copy_complete", f"copy for {len(result.copy)} creative(s)",
                      duration_ms=watch.elapsed_ms, degraded=sorted(result.degraded),
                      trimmed=sorted(result.trimmed),
                      tags={asset_id: [tag.value for tag in tags]
                            for asset_id, tags in sorted(result.tags.items())})
    # FR-296 + D54: the closing line names the contract the words actually shipped under, counted
    # off the per-asset receipt rather than off `config.run.carousel_copy_mode`. The two differ
    # exactly where it matters — a compress-mode run whose call failed shipped the verbatim mapped
    # deck, and a line claiming "compressed" over it would hide the degradation.
    compressed = sum(1 for prov in result.provenance.values()
                     if prov.copy_mode == copywrite.MODE_COMPRESS)
    _stage(session, "COPY",
           f"{groups} call(s) -> {len(result.copy)} creative(s) quoted verbatim" if not compressed
           else f"{groups} call(s) -> {len(result.copy)} creative(s), {compressed} compressed",
           elapsed_s=watch.elapsed_s)
    return result


async def _slide_intel(session: _Session, live: Sequence[PlanEntry],
                       by_key: Mapping[str, TrendItem]) -> None:
    """INTEL (FR-306, D46): read every bound source deck ONCE — download, transcribe, brief.

    Post-Confirm by construction (this runs after the gate), before COPY by necessity (the
    vision transcription fills panel slots the offer needs). One deck = one analysis call;
    siblings quoting the same post share the reading. The $0 path (`vision_transcribe: false`
    or no LLM) still downloads the slides — the FR-309 gallery shows the source deck either
    way. Results land on `session.slide_intel`, and the operator sees one line per deck: how
    many slides, whose words (Virlo vs vision), how many briefs and brand marks, and what it
    cost — the D45 posture that every AI step prints its result, not just its happening.

    No stage-list guard here, deliberately: previews run this pass with an EMPTY stage list
    (their headers no-op through `_stage` per D19, the per-deck lines still print), and on a
    paid run every shape that removes INTEL from the list also leaves `bound` empty — no
    carousels means no bound post, brief-only means no topic at all.
    """
    bound: dict[str, Any] = {}
    for entry in live:
        if (entry.creative_format == "carousel" and entry.source_post_id
                and entry.brief_influence != "override"):
            topic = by_key.get(entry.trend_key or "")
            post = next((p for p in getattr(topic, "posts", ())
                         if str(p.post_id) == entry.source_post_id), None)
            if post is not None:
                bound.setdefault(str(post.post_id), post)
    watch = Stopwatch()
    _stage(session, "INTEL",
           f"{len(bound)} source deck(s) to read (analysis-only)", opening=True)
    if _halt(session, "slide intelligence") or not bound:
        _stage(session, "INTEL", f"{len(bound)} deck(s) -> 0 read", elapsed_s=watch.elapsed_s)
        return
    call = (_metered(session)
            if session.config.sources.vision_transcribe and session.llm is not None else None)
    intels = await _with_pulse(
        session,
        sources.slide_intel.enrich(list(bound.values()), run_dir=session.run_dir, call=call,
                                   engine=session.engine, cfg=session.config, log=session.log),
        lambda: f"          reading {len(bound)} source deck(s) ... {_dur(watch.elapsed_s)}",
        suppress_s=10.0)
    session.slide_intel = dict(intels)
    lines, read = [], 0
    for post_id, intel in intels.items():
        slides = list(getattr(intel, "slides", ()))
        virlo = sum(1 for s in slides if getattr(s, "text_source", "") == "virlo")
        vision = sum(1 for s in slides
                     if getattr(s, "text_source", "") == "vision_transcribed")
        briefs = sum(1 for s in slides if str(getattr(s, "visual_brief", "")).strip())
        marks = sum(len(getattr(s, "brand_marks", ()) or ()) for s in slides)
        status = str(getattr(intel, "status", ""))
        read += status == "ok"
        note = "" if status == "ok" else f"  [{status}]"
        lines.append(f"  {post_id[:12]:<12} {len(slides)} slide(s): {virlo} virlo + "
                     f"{vision} vision, {briefs} brief(s), {marks} mark(s), "
                     f"{_money(float(getattr(intel, 'cost_usd', 0.0) or 0.0))}{note}")
    if lines:
        session.say("\n".join(lines))
    session.log.event(
        "slide_intel_complete", f"{read}/{len(bound)} source deck(s) read",
        duration_ms=watch.elapsed_ms,
        decks={pid: str(getattr(intel, "status", "")) for pid, intel in intels.items()})
    _stage(session, "INTEL", f"{len(bound)} deck(s) -> {read} read, "
                             f"{len(bound) - read} degraded", elapsed_s=watch.elapsed_s)


async def _with_pulse(session: _Session, awaitable: Any, line: Any, *,
                      suppress_s: float) -> Any:
    """Await `awaitable` while honouring FR-299: when the console has been silent past the
    heartbeat cadence (and the wait is past its suppression window), print `line()` — which
    re-stamps the clock through `say`, so the volume is bounded by construction."""
    task = asyncio.ensure_future(awaitable)
    started = time.monotonic()
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=1.0)
            if not task.done() and session.pulse.due(wait_started=started,
                                                     suppress_s=suppress_s):
                session.say(line())
    except asyncio.CancelledError:
        task.cancel()
        raise
    return task.result()


def _job_forecast(live: Sequence[PlanEntry]) -> tuple[int, int]:
    """`(wave1, wave2)` planned submissions — the RENDER header's and heartbeat's denominator.

    Per FR-25's two waves: an image is one wave-1 job; a carousel is one wave-1 anchor plus
    `slide_count − 1` wave-2 slides; a reel is a wave-1 seed frame plus one wave-2 Seedance
    clip. Retries (moderation, vision) are extras this forecast cannot know — the heartbeat
    therefore prints `max(expected, submitted)` and stays honest either way.
    """
    wave1 = wave2 = 0
    for entry in live:
        if entry.creative_format == "carousel":
            wave1 += 1
            wave2 += max(0, int(entry.slide_count or 1) - 1)
        elif entry.creative_format == "reel":
            wave1 += 1
            wave2 += 1
        else:
            wave1 += 1
    return wave1, wave2


async def _create(session: _Session, entries: Sequence[PlanEntry], live: Sequence[PlanEntry],
                  trends: dict[str, TrendItem], copy_result: copywrite.CopyResult
                  ) -> tuple[generate.Report, Mapping[str, TrendItem]]:
    """CREATE: images, carousels and reels in two waves. Terminal entries package as honest skips.

    Returns the report **and** the topics the render side saw, because FR-153 records the posts a
    creative actually quoted. The GAUNTLET is wired in here and nowhere else: `llm_call` is
    the same metered wrapper the filter and Write stages use, so every critic call lands in the
    FR-84 tally and in the per-role usage table — `None` whenever the gate is off (D49). `deadline` gives the modules FR-108's
    `env.halted` without a runner callback. RENDER narration (FR-296/299) rides the Env's `say`/
    `pulse` seams: the opening header here, per-job terminal lines and the silence-breaker
    heartbeat inside `generate`, the closing header back here with the real ok/failed split.
    """
    if _halt(session, "generation"):  # FR-4/FR-108: nothing leaves the plan, it goes terminal
        for entry in entries:
            if entry.status is PlanEntryStatus.PENDING:
                entry.status = PlanEntryStatus.ABANDONED
                entry.skip_reason = "run deadline elapsed or interrupted before submission"
    gated = bool(session.config.run.gauntlet.enabled) and session.llm is not None
    wave1, wave2 = _job_forecast(live)
    _stage(session, "RENDER",
           f"{wave1 + wave2} job(s) submitted ({wave1} wave-1, {wave2} wave-2)", opening=True)
    env = generate.Env(
        config=session.config, run_dir=session.run_dir, engine=session.engine,
        budget=session.budget, log=session.log, ledger=session.ledger, trends=trends,
        copy=copy_result.copy, copy_tags=copy_result.tags,
        copy_provenance=copy_result.provenance,  # FR-298: post + ref labels onto meta.yaml
        niche_descriptor=session.config.niche.as_text(),
        # A15: `visual_world` ALONE, for the gpt-image-2 roles. `niche_descriptor` above is
        # copy-side (it names the audience); this is the render-side half.
        niche_visual_world=session.config.niche.visual_world,
        local_refs=_local_refs(session, live),
        campaign_briefs=session.campaign_briefs,
        styles=session.registry, branding=session.config.branding,  # FR-290/292
        strip_brands=dict(session.strip_brands),  # M6: LLM-discovered brands reach every prompt
        slide_intel=dict(session.slide_intel),  # FR-306/308: per-slide briefs for the deck
        llm_call=_metered(session) if gated else None,
        stop=session.control.stop, deadline=session.deadline,
        say=session.say, pulse=session.pulse, heartbeat_s=session.pulse.interval_s,
        jobs_expected=wave1 + wave2)
    watch = Stopwatch()
    report = await generate.create(entries, env)
    _stage(session, "RENDER",
           f"{env.jobs_submitted} job(s) -> {env.jobs_ok} ok, "
           f"{env.jobs_submitted - env.jobs_ok} failed ({wave1} wave-1, {wave2} wave-2)",
           elapsed_s=watch.elapsed_s)
    _gauntlet_rollup(session, report)
    session.log.event("generation_complete",
                      f"{len(report.packaged_trends)} topic(s) produced packaged creatives",
                      duration_ms=watch.elapsed_ms, disk_full=report.disk_full)
    return report, trends


def _gauntlet_rollup(session: _Session, report: generate.Report) -> None:
    """GAUNTLET (FR-296/FR-328): a rollup header plus one line per round that found something.

    The gate runs INSIDE each creative — one call per critic per round, concurrently with every
    other creative — so this stage has no elapsed of its own (`-`) and narrates what the rounds
    already recorded in each `meta.yaml.gauntlet`. Reading the records rather than a live callback
    is deliberate: the records are what the operator can go back and check, and a console line that
    could disagree with them would be the only unverifiable number on the page.

    The per-round line is spec §6's format, verbatim:

        GAUNTLET deck Li_car_03 round 2/3 — 2 frame(s) failed (brief: invented_text s4; craft:
        contrast s2) — re-rendering 2

    Defect CODES only, never a critic's `detail` string: D30 keeps full detail in events.jsonl, and
    a `detail` is model-written free text that has no business on a console line or in run.log.
    """
    if "GAUNTLET" not in session.stages:
        return
    gates = {asset_id: record.gauntlet for asset_id, record in sorted(report.records.items())
             if isinstance(getattr(record, "gauntlet", None), dict)}
    if not gates:
        _stage(session, "GAUNTLET", "no creative reached the gate", elapsed_s=None)
        return
    tally = Counter(str(gate.get("result") or "skipped") for gate in gates.values())
    rerenders = sum(int(gate.get("rerenders") or 0) for gate in gates.values())
    spend = sum(float(gate.get("critic_cost_usd") or 0.0)
                + float(gate.get("rerender_cost_usd") or 0.0) for gate in gates.values())
    blocked = tally.get("blocked", 0)
    # FR-286: this body has ~54 columns to live in, so it carries the three counts an operator
    # acts on plus the money, and nothing else. Fix counts are per creative and are on the rows
    # below; the whole gate's spend also appears in the LLM-usage table at DONE.
    _stage(session, "GAUNTLET",
           f"{len(gates)} judged -> {tally.get('pass', 0)} pass, {blocked} blocked, "
           f"{len(gates) - tally.get('pass', 0) - blocked} stopped · {_money(spend)}",
           elapsed_s=None)
    session.log.event("gauntlet_rollup", f"{len(gates)} creative(s) judged",
                      results=dict(tally), rerenders=rerenders, spend_usd=round(spend, 6))
    for asset_id, gate in gates.items():
        # The DEFECTS come from the asset's own `GAUNTLET_REPORT.yaml` rather than from memory, so
        # the console line and the file an operator opens afterwards cannot disagree — and so a
        # `meta.yaml.gauntlet` that only carries per-critic COUNTS (spec §6's shape) can still be
        # narrated with the codes spec §6's console line names.
        for line in _gauntlet_lines(asset_id, gate,
                                    read_gauntlet_report(session.run_dir / asset_id)):
            session.say(line)


def _defect_codes(report: Mapping[str, Any] | None) -> dict[int, str]:
    """`round -> "brief: invented_text s4; craft: contrast s2"` — spec §6's console clause.

    Built from `GAUNTLET_REPORT.yaml`'s per-round defect rows. CODES and frame numbers only: a
    critic's `detail` is model-written free text and belongs in events.jsonl and in that file,
    never on a console line or in run.log (D30's split, applied to model output rather than to
    secrets). Deduped, so three frames failing the same code read as one clause with three slides.
    """
    out: dict[int, str] = {}
    for row in (report or {}).get("rounds") or ():
        if not isinstance(row, Mapping):
            continue
        per_critic: dict[str, list[str]] = {}
        for defect in row.get("defects") or ():
            if isinstance(defect, Mapping) and defect.get("code"):
                per_critic.setdefault(str(defect.get("critic") or "?"), []).append(
                    f"{defect['code']} s{defect.get('frame')}")
        if per_critic:
            out[int(row.get("round") or 0)] = "; ".join(
                f"{name}: {', '.join(sorted(set(found)))}"
                for name, found in sorted(per_critic.items()))
    return out


def _gauntlet_lines(asset_id: str, gate: Mapping[str, Any],
                    report: Mapping[str, Any] | None = None) -> list[str]:
    """Spec §6's per-round console lines for ONE creative — only the rounds that found something.

    A clean round is silence by design: the stage header already says how many creatives passed,
    and a line per passing round would bury the two decks that did not. `degraded` and `blocked`
    each add their own closing sentence, because both are decisions the operator has to act on.

    `report` is that creative's `GAUNTLET_REPORT.yaml`, when it has one; it supplies the defect
    CODES the line names. Without it the line degrades to per-critic counts, which is still true
    and still useful — a rollup must never depend on a file that may not have been written.
    """
    rounds = [row for row in (gate.get("rounds") or ()) if isinstance(row, Mapping)]
    codes = _defect_codes(report)
    total = len(rounds)
    result = str(gate.get("result") or "")
    body: list[str] = []
    for row in rounds:
        failed = list(row.get("failed_frames") or ())
        if not failed:
            continue
        detail = codes.get(int(row.get("round") or 0), "") or "; ".join(
            f"{name}: {count} frame(s)"
            for name, count in sorted((row.get("critics") or {}).items()) if count)
        rerendered = list(row.get("rerendered") or ())
        body.append(fit(
            f"            round {row.get('round')}/{total} — {len(failed)} failed "
            f"({detail or 'no critic named a defect'})"
            + (f" — {len(rerendered)} fix" if rerendered else ""), 78))
    if gate.get("degraded_gate"):
        # Causes share the flag: critics dropped as unavailable (D3), a standing cosmetic defect
        # (FR-325's cosmetic tier, Session 5.6/F7) and a standing low-confidence system verdict
        # (Session 5.7/F8). The dropped set tells the D3 case from the other two, and the other
        # two share a sentence because they share an ANSWER — the gate saw everything, judged the
        # remaining defect too weak to bin a paid deck for, and shipped it tagged. Which of the
        # two it was is in the round lines above (the codes) and in GAUNTLET_REPORT.yaml (their
        # confidence); splitting the sentence would spend a scarce console line on a distinction
        # the operator acts on identically.
        dropped = sorted({name for row in rounds for name in (row.get("unavailable") or ())})
        if dropped:
            body.append(fit(f"            gate DEGRADED — {', '.join(dropped)} could "
                            "not be read; judged by the survivors (D3)", 78))
        else:
            body.append(fit("            gate DEGRADED — cosmetic/low-confidence defect(s) "
                            "stand and ship (FR-325)", 78))
    if result == "blocked":
        # TWO lines, deliberately: this is the one thing on the page that means "do not publish
        # this", and the file names are what the operator does next. Fitting both into 78 columns
        # would truncate exactly the half that says where to look.
        body.append("            BLOCKED — not published; every paid slide is kept on disk")
        body.append("            read BLOCKED.txt and GAUNTLET_REPORT.yaml in its folder")
    elif result in ("budget_stop", "deadline_stop"):
        body.append(fit(f"            {result.replace('_', ' ')} — the fix loop stopped early; "
                        "the creative ships with its last verdict standing", 78))
    # The asset id gets its OWN line rather than a prefix on every row: ids run to ~46 characters
    # (FR-71's `<Pl>_<fmt>_<slug>_<NN>`), and repeating one on each round line left FR-286's 78
    # columns with no room for the defect codes — which are the only part of the line worth
    # reading. Silence when nothing happened: a clean creative is the stage header's business.
    return [fit(f"          {asset_id}  {result}", 78), *body] if body else []


def _posts_used(session: _Session, report: generate.Report, attached: Mapping[str, TrendItem],
                entries: Sequence[PlanEntry]) -> dict[str, list[tuple[str, str]]]:
    """FR-153/FR-298: the posts a packaged creative really QUOTED, as `(post_id, url)` pairs.

    Post-pivot the history's job is verbatim-copy freshness — a post whose text this run shipped
    must not be quoted again inside the window — so the record is `copy_source_post_id` off each
    delivered creative's meta record, never the whole topic's post list: a topic contributes only
    the posts that actually became pixels or captions. The URL rides along so a history entry is
    auditable without re-fetching (item 14; `state.record_use` consumes exactly this shape).

    `SUCCESS` is the whole test, and v2.2.0's `BLOCKED` is deliberately not it: a deck the quality
    gate refused was never published, so its source post's text never shipped and burning that post
    for the next 30 days would cost the run its best material for a creative nobody will ever see.
    Every non-SUCCESS status — skipped, failed, abandoned, blocked — is excluded by the same
    identity check below; the status enum grew, the rule did not.
    """
    uses: dict[str, list[tuple[str, str]]] = {key: [] for key in report.packaged_trends}
    for entry in entries:
        record = report.records.get(entry.asset_id)
        key = entry.trend_key or ""
        if (entry.status is not PlanEntryStatus.SUCCESS or record is None
                or not record.copy_source_post_id or key not in uses):
            continue
        topic = attached.get(key)
        url = next((post.url for post in (topic.posts if topic is not None else [])
                    if post.post_id == record.copy_source_post_id), "")
        pair = (record.copy_source_post_id, url)
        if pair not in uses[key]:
            uses[key].append(pair)
    return uses


async def _package(session: _Session, entries: Sequence[PlanEntry], plan_estimate: Estimate,
                   report: generate.Report, attached: Mapping[str, TrendItem],
                   copy_result: copywrite.CopyResult, *, trend_supply_failed: bool,
                   plan_notes: Sequence[str] = ()) -> int:
    """PACKAGE/DONE: gallery, history, latest-pointer, provenance, funnel, spend, exit code.

    §1.10's DONE-stage order is deliberate: the DONE header answers "what happened", the
    provenance block answers "where did each creative come from" (FR-297c), the funnel prints its
    ONE appearance (FR-155 re-placed — the stage headers carried its numbers as they became
    true), then the spend table, any loss lines, and the closing status with folder + gallery
    paths. Each number appears in exactly one of those surfaces.
    """
    _log_template_attribution(session)
    credits_line = _credits_exhausted_line(session, entries, report)  # FR-248, before the counts
    write_gallery(session.run_dir, title=session.config.output.gallery.title, log=session.log)
    if report.packaged_trends:  # FR-82: only topics that actually produced a packaged creative
        await record_use(LOGS_DIR, _posts_used(session, report, attached, entries), session.run_id,
                         history_days=session.config.run.trend_history_days, log=session.log)
    # FR-254: `latest` points at the newest run that actually DELIVERED something. SUCCESS is the
    # only status that qualifies, and v2.2.0's BLOCKED explicitly does not (D49): a run whose every
    # deck was refused by the quality gate must leave the previous run's pointer standing, or the
    # operator's `output/latest/` shortcut opens onto a folder with nothing publishable in it.
    if any(entry.status is PlanEntryStatus.SUCCESS for entry in entries):
        await set_latest(session.config.output.dir, session.run_id, log=session.log)

    # FR-202 reads the FR-73 tags, not the plan alone: a partial carousel ships SUCCESS with no
    # `skip_reason` (the deck DID ship — `carousel.package()` marks `incomplete` instead).
    degradations: DegradationMap = {asset_id: record.degradations
                                    for asset_id, record in report.records.items()}
    # FR-321: the records carry `slide_count`/`slides_ordered`, so the spend table can say `7/8`
    # where it used to say `yes`. They are passed rather than merged into the plan because
    # delivery completeness is a packaging fact — `budget` reports it, `carousel.package()` owns it.
    summary = session.budget.summary(entries, plan_estimate, records=report.records)
    delivered = sum(1 for row in summary.rows if row.delivered)
    _stage(session, "DONE",
           f"{delivered} delivered, {len(summary.rows) - delivered} skipped, "
           f"{_money(summary.total_usd)} of the "
           f"{format_usd(session.config.run.spend_cap_usd)} cap",
           elapsed_s=session.clock.elapsed_s)
    if provenance := _provenance_block(entries, report.records, attached, copy_result.copy):
        session.say(provenance)
    session.say(_funnel_block(session.counters))  # FR-155: ONCE, at DONE — nowhere else
    session.say(_spend_table(summary, _gate_column(report)))
    session.say(_llm_usage_table(session, summary))  # FR-84/FR-326: tokens and $ per LLM role
    if credits_line:
        session.say(credits_line)
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


# ----------------------------------------------- §1.10 console surfaces (D45, FR-296–300)
#
# House rules, verified and binding (contracts item 16): every block below is a PURE function
# printed via one `say()`; identical bytes reach console and run.log, so no spinners, no `\r`,
# no ANSI; FR-286's 78-column ceiling holds line by line; safe glyphs are `util.fit`'s set
# (`·`, `—`, `…`, `←`) plus the two-character `->` — the `→` glyph is FORBIDDEN (FR-155).
# A number appears in exactly ONE of {stage header, table, funnel, spend row}.

#: FR-296's stage vocabulary, in pipeline order. The LIVE list is computed per run by
#: `_live_stages()` — `[n/N]` is derived from it and is never hardcoded anywhere.
_STAGE_ORDER = ("COLLECT", "TOPICS", "FILTER", "SELECT", "ASSIGN", "INTEL", "COPY", "RENDER",
                "GAUNTLET", "DONE")


def _live_stages(config: Config, *, brief_only: bool) -> list[str]:
    """The stages THIS run will actually pass — N is computed from the resolved plan (FR-296).

    A brief-only plan consumes no trend, so COLLECT/TOPICS/FILTER/SELECT do not exist for it
    (10 §10's carve-out made visible); `gauntlet.enabled: false` has no GAUNTLET. DONE always
    exists —
    the closing header is the one line every run owes the operator.
    """
    stages = list(_STAGE_ORDER)
    if brief_only:
        stages = [s for s in stages if s not in ("COLLECT", "TOPICS", "FILTER", "SELECT")]
    if not config.run.gauntlet.enabled:
        stages = [s for s in stages if s != "GAUNTLET"]
    # FR-306: INTEL exists only when a source deck could be read — a brief-only plan binds no
    # post, and a plan with no carousels has no deck. `vision_transcribe: false` KEEPS the
    # stage: the $0 path still downloads the source slides for the gallery (FR-309), and a
    # stage that silently vanished would hide that work from the [n/N] arithmetic.
    if brief_only or not config.run.formats.get("carousel", 0):
        stages = [s for s in stages if s != "INTEL"]
    return stages


def _dur(seconds: float) -> str:
    """`5.2s` under a minute, `3m41s` above — the stage headers' right-hand column."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}m{rest:02d}s"


def _compact(value: int) -> str:
    """`12.4M` / `980K` / `412` — FR-297's compact numbers, never thousands separators."""
    number = float(max(int(value), 0))
    for cut, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if number >= cut:
            scaled = number / cut
            # One decimal only while it carries information (`12.4M`, `1.9M`); `41K`, `980K`
            # and an exact `8M` print whole — the mockup's shapes, byte for byte.
            if scaled < 100 and round(scaled, 1) != round(scaled):
                return f"{scaled:.1f}{suffix}"
            return f"{scaled:.0f}{suffix}"
    return str(int(number))


def _stage(session: _Session, stage: str, body: str, *,
           opening: bool = False, elapsed_s: float | None = None) -> None:
    """One FR-296 header: `[n/N] STAGE  in -> out  elapsed`, computed off the live stage list.

    Stages with waits print twice — the opening `...` form on submit, the closing form with the
    elapsed; GAUNTLET is a rollup and closes with `-` (`elapsed_s=None`). A stage not in
    `session.stages` prints nothing — that is how previews (which set no stage list) reuse the
    stage helpers verbatim without narrating a pipeline they do not run (D19).
    """
    if stage not in session.stages:
        return
    position, total = session.stages.index(stage) + 1, len(session.stages)
    tag = f"[{position}/{total}]"
    # FR-286: 78 columns TOTAL. The body width flexes with the tag — a ten-stage run's tag is
    # two characters wider than a nine-stage run's, and a fixed 53 was one character of silent
    # overflow away the day INTEL made the stage count double-digit.
    width = 78 - len(tag) - 1 - 8 - 2 - 8  # tag + space + stage column + gutter + elapsed
    if opening:
        session.stage_watch.reset()
        session.say(f"{tag} {stage:<8}  {fit(body, width)} ...")
        return
    right = "-" if elapsed_s is None else _dur(elapsed_s)
    session.say(f"{tag} {stage:<8}  {fit(body, width):<{width}}{right:>8}")
    session.log.event("stage_complete", f"{stage}: {body}", stage=stage, position=position,
                      total=total,
                      elapsed_s=None if elapsed_s is None else round(elapsed_s, 3))


def _mon_codes(topics: Sequence[TrendItem]) -> dict[str, str]:
    """Monitor ids -> `m1`/`m2` display codes, in first-seen topic order — a raw monitor id is an
    unbounded token and would blow every column it sits in (FR-286)."""
    codes: dict[str, str] = {}
    for topic in topics:
        monitor = str(getattr(topic, "monitor_id", "") or "")
        if monitor not in codes:
            codes[monitor] = f"m{len(codes) + 1}"
    return codes


def _verdict_cell(verdict: topic_filter.Verdict | None) -> str:
    """`keep en/fit` / `strip:2 cs/fit` / `skip:LANG de/fit` — the verdict column (FR-297a).

    Two facts in one cell since v2.2.0, because the screen now decides on three grounds and a bare
    `skip:LANG` is unreadable without the language it objected to. The tail is always printed, on
    keeps as much as on skips: seeing `en/fit` on eleven rows and `de/unfit` on the twelfth is what
    makes the twelfth row's drop obvious. A screen that could not answer prints `?` rather than
    guessing — an unknown language is a fail-open keep, not an English one.
    """
    if verdict is None:  # never screened (a $0 preview, an ordinal the model skipped): still a keep
        verdict = topic_filter.Verdict(ordinal=0)
    if verdict.verdict == "strip":
        head = f"strip:{len(verdict.brands_to_strip)}"
    elif verdict.verdict == "skip":
        head = f"skip:{verdict.skip_code or topic_filter.SKIP_PROMO}"
    else:
        head = "keep"
    return f"{head} {verdict.language or '?'}/{'fit' if verdict.audience_fit else 'unfit'}"


def _topics_table(topics: Sequence[TrendItem],
                  verdicts: Mapping[int, topic_filter.Verdict],
                  window_days: int = 0) -> str:
    """FR-297a — ALL topics, one line each, strongest first: the visible sort proof.

    The monotonically non-increasing `strn` column IS the proof; the caption states the strength
    formula (read off the adapter's own weights, so this sentence cannot drift from the code) and
    that views/median are each topic's OWN posts, min-maxed across the pool (§1.6). Verdict keys
    are the ENGINE-assigned ordinals — 1-based INPUT order of `topics`, per contracts item 6 —
    while display order is strength rank; the two orders travel together row by row.
    """
    if not topics:
        return ""
    weights = sources.STRENGTH_WEIGHTS
    codes = _mon_codes(topics)
    ordinal_of = {id(topic): index for index, topic in enumerate(topics, start=1)}
    ranked = sorted(topics, key=lambda item: (-item.strength, item.name))
    lines = [
        f"Topics -- {len(topics)} from {len(codes)} monitor(s), sorted by strength, "
        "strongest first",
        f"  strength = {weights['total_views']:.2f} views + {weights['median_views']:.2f} median"
        f" + {weights['velocity']:.2f} velocity + {weights['engagement']:.2f} engage,",
        f"  min-maxed across all {len(topics)} topics; every figure is that topic's own posts",
        # FR-297a (v2.1.0): the caption names the recency window in force, because every
        # views/median figure above is computed over the WINDOWED survivors (FR-301/305) and a
        # reader comparing against Virlo's all-time UI numbers must see why they differ.
        (f"  counted over posts <={window_days}d old (sources.max_post_age_days)"
         if window_days else "  counted with the post-age window off"),
        f"{'rk':>5}  {'topic':<22}  {'mon':>3} {'posts':>6} {'views':>8} {'median':>8}  "
        f"{'strn':<5}  verdict",
    ]
    for rank, topic in enumerate(ranked, start=1):
        verdict = verdicts.get(ordinal_of[id(topic)])
        lines.append(
            f"{rank:>5}  {fit(topic.name, 22):<22}  {codes.get(str(topic.monitor_id or ''), '-'):>3}"
            f" {len(topic.posts):>6} {_compact(topic.total_views):>8}"
            f" {_compact(topic.median_views):>8}  {topic.strength:.3f}  {_verdict_cell(verdict)}")
    lines += [
        "  verdict  keep = usable as-is; strip:N = N competitor name(s) removed;",
        "           skip:CODE = dropped before any render spend, CODE says why",
        "  codes    PROMO competitor promo; LANG source language we do not write;",
        "           AUDIENCE not our audience (blocklist strips count as strip:N)",
        "  tail     <lang>/fit|unfit = screened source language and audience fit;",
        "           ? = the screen gave no usable answer, so the topic was kept",
    ]
    return "\n".join(lines)


def _post_age(post: SourcePost) -> str:
    """`2d` / `7h` / `-` — the roster's age column, tolerant of a missing or naive timestamp."""
    stamp = post.published_at
    if stamp is None:
        return "-"
    try:
        now = datetime.now(timezone.utc)
        delta = now - (stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=timezone.utc))
        hours = max(0, int(delta.total_seconds() // 3600))
    except (TypeError, ValueError, OverflowError):
        return "-"
    return f"{hours // 24}d" if hours >= 24 else f"{hours}h"


def _post_roster(topics: Sequence[TrendItem], verdicts: Mapping[int, topic_filter.Verdict],
                 live: Sequence[PlanEntry], *, topics_limit: int | None = 3,
                 posts_limit: int | None = 3) -> str:
    """FR-297b — the per-topic post roster: WHICH posts, ranked by views, and who quoted them.

    The `P` ordinals are EXACTLY the §1.7 reference labels the copy LLM is offered (`P1.hook.2`
    in events.jsonl finds its post here), and `-> NN` names the creative that quoted that post —
    §1.6's sibling divergence made observable. On a paid run the roster covers the ASSIGNED topics
    (strongest first, top `topics_limit` × `posts_limit`); previews pass both limits as `None`
    with their dry-assigned `live`, so every topic prints and `-> NN` is populated exactly as the
    paid run would populate it (an empty `live` degrades to all topics, all `unused`). The
    permalink is an unbounded token and stands alone on its own line (FR-286 carve-out).
    """
    codes = _mon_codes(topics)
    ordinal_of = {id(topic): index for index, topic in enumerate(topics, start=1)}
    assigned = {entry.trend_key for entry in live if entry.trend_key}
    chosen = [topic for topic in sorted(topics, key=lambda item: (-item.strength, item.name))
              if not assigned or topic.history_key in assigned]
    if topics_limit is not None:
        chosen = chosen[:topics_limit]
    quoted: dict[tuple[str, int], list[str]] = {}
    for entry in live:
        topic = next((t for t in topics if t.history_key == entry.trend_key), None)
        if topic is None or not topic.posts:
            continue
        # D46 §0.10: the plan binds a specific fresh post at ASSIGN, so `-> NN` points at THAT
        # row. An unbound entry (override brief never reaches here; a degrade path can) keeps
        # the pre-D46 modulo so the roster still says who drew on the topic.
        if entry.source_post_id:
            index = next((i for i, post in enumerate(topic.posts)
                          if str(post.post_id or "") == entry.source_post_id), None)
            if index is None:
                continue  # bound to a post outside the printed roster: claiming a row would lie
        else:
            index = max(int(entry.trend_reuse_index), 0) % len(topic.posts)
        quoted.setdefault((topic.history_key, index), []).append(
            entry.asset_id.rsplit("_", 1)[-1])
    lines: list[str] = []
    for rank, topic in enumerate(chosen, start=1):
        if lines:
            lines.append("")
        verdict = _verdict_cell(verdicts.get(ordinal_of.get(id(topic), -1)))
        head = f"Topic {rank} -- {fit(topic.name, 36)}"
        lines.append(f"{head:<48} {codes.get(str(topic.monitor_id or ''), '-')} - "
                     f"strn {topic.strength:.3f} - {verdict}")
        lines.append('          posts ranked by views; "-> NN" names the creative that quoted it')
        posts = topic.posts if posts_limit is None else topic.posts[:posts_limit]
        for index, post in enumerate(posts):
            users = quoted.get((topic.history_key, index))
            tail = f"-> {','.join(sorted(users))}" if users else "unused"
            handle = f"@{post.author}" if post.author else "-"
            # Column padding is layout, and `fit()` normalizes whitespace — so it wraps the
            # VARIABLE tokens (handle, id) only, never the assembled line.
            lines.append(
                f"          P{index + 1:<2} {fit(handle, 15):<15} {_compact(post.views):>5} "
                f"{_post_age(post):>3}  {fit(post.post_id, 16):<16}  "
                f"{'slideshow' if post.is_slideshow else 'video':<9}  {fit(tail, 9)}".rstrip())
        if topic.virlo_url:
            lines.append(f"          {topic.virlo_url}")
    return "\n".join(lines)


#: The provenance receipt's slot precedence: the first slot a creative filled is the one whose
#: bytes the receipt quotes — headline first (it is the frame's loudest string), caption last.
#: SAME order as gallery.py's `_RECEIPT_SLOTS` (T3.2) so console and gallery quote one string.
_RECEIPT_SLOTS = ("headline", "overlay_text", "subline", "caption")


def _quoted_bytes(record: AssetRecord, copyset: CopySet | None) -> tuple[str, str]:
    """`(ref_label, quoted_text)` for the receipt line — `("", "")` when nothing was quoted."""
    if copyset is None or not record.copy_source_refs:
        return "", ""
    for slot in _RECEIPT_SLOTS:
        if slot in record.copy_source_refs:
            return record.copy_source_refs[slot], str(getattr(copyset, slot, "") or "")
    slot, label = next(iter(sorted(record.copy_source_refs.items())))
    if slot.startswith("slide_") and copyset.slide_texts:
        index = max(int(slot.rsplit("_", 1)[-1] or 1) - 1, 0)
        if index < len(copyset.slide_texts):
            return label, copyset.slide_texts[index]
    return label, ""


def _provenance_block(entries: Sequence[PlanEntry], records: Mapping[str, AssetRecord],
                      trends: Mapping[str, TrendItem],
                      copy: Mapping[str, CopySet]) -> str:
    """FR-297c — at DONE, before the spend table: every creative mapped back to its origins.

    Line 1 per creative: id · format · topic · style · sig(branded) · cost · ok. Line 2 is the
    verbatim receipt — WHICH post (author, views, id) and the first ~24 chars of the exact string
    quoted. Line 3 appears only on a loss and names the cause. `id` is the asset id's trailing
    ordinal; `sig` is per-creative (the brand itself is run-wide — launch block + DONE header).

    **A COMPRESSED deck (D54/FR-331) gets a different line 2, because it quoted nothing.** Its
    slides are the copy model's compressions of that post's panels, so there is no "exact string
    quoted" to print and `copy_source_refs` is empty by contract (FR-302 as amended). Printing the
    verbatim receipt with an empty quote would read as "this creative quoted nothing from a post it
    names", which is the opposite of what happened. The compress line names the same post — the
    provenance claim is unchanged, only the transform is — and points at `meta.yaml`'s `panel_map`,
    where every row carries the source panel beside what shipped.
    """
    rows = [(entry, records[entry.asset_id]) for entry in entries
            if entry.asset_id in records]
    if not rows:
        return ""
    lines = ["Provenance -- where each delivered creative came from",
             f"   {'id':>2}  {'format':<8}  {'topic':<20}  {'style':<18}  sig    cost  ok"]
    for entry, record in rows:
        ok = "yes" if entry.status is PlanEntryStatus.SUCCESS else "no"
        sig = "yes" if record.branded else "-"
        lines.append(
            f"   {entry.asset_id.rsplit('_', 1)[-1]:>2}  {record.creative_format:<8}  "
            f"{fit(record.source_name or record.topic_key, 20):<20}  "
            f"{fit(record.style_key or '-', 18):<18}  {sig:<3} {_money(record.actual_cost_usd):>7}"
            f"  {ok}")
        if record.copy_source_post_id:
            trend = trends.get(entry.trend_key or "")
            posts = trend.posts if trend is not None else []
            index = next((i for i, post in enumerate(posts)
                          if post.post_id == record.copy_source_post_id), None)
            post = posts[index] if index is not None else None
            label, text = _quoted_bytes(record, copy.get(entry.asset_id))
            ordinal = f"P{index + 1}" if index is not None else (label.split(".", 1)[0] or "P?")
            handle = f"@{post.author}" if post is not None and post.author else "-"
            views = _compact(post.views) if post is not None else "-"
            lines.append(
                f'       compressed {ordinal} {fit(handle, 13)} {views} '
                f'{fit(record.copy_source_post_id, 14)} -> panel_map'
                if record.copy_mode == copywrite.MODE_COMPRESS else
                f'       quoted {ordinal} {fit(handle, 15)} {views} '
                f'{fit(record.copy_source_post_id, 16)} "{fit(text, 24)}"')
        if ok == "no":
            lines.append(f"       {fit(str(entry.skip_reason or 'no cause recorded'), 68)}")
    return "\n".join(lines)


async def _screen_topics(session: _Session, trends: Sequence[TrendItem]
                         ) -> dict[int, topic_filter.Verdict]:
    """FILTER (FR-294, contracts item 9): one batched screen, narrated and recorded.

    Named so previews reuse the IDENTICAL path (arch #4). Wraps `topic_filter.screen` (blocklist
    fail-closed, LLM fail-open), prints the FR-296 stage lines with per-verdict detail for every
    non-`keep`, emits the FR-298 `topic_filter_verdict` events, folds the tallies into the funnel
    (`Counters.record_filter`), fills `session.strip_brands` for the copy AND render paths (M6),
    and surfaces the single `filter_degraded` warning when the LLM layer failed open. The LLM
    call rides `_metered`, so the spend lands in FR-84's tally like every other model call.
    """
    if not trends:
        return {}
    watch = Stopwatch()
    _stage(session, "FILTER", f"{len(trends)} topic(s)", opening=True)
    call = _metered(session) if session.llm is not None else None
    verdicts = await topic_filter.screen(list(trends), session.config, call)
    session.counters.record_filter(verdicts)
    kept = sum(1 for v in verdicts.values() if v.verdict == "keep")
    stripped = sum(1 for v in verdicts.values() if v.verdict == "strip")
    skipped = sum(1 for v in verdicts.values() if v.verdict == "skip")
    session.strip_brands = {
        trends[ordinal - 1].history_key: tuple(verdict.brands_to_strip)
        for ordinal, verdict in verdicts.items()
        if verdict.brands_to_strip and 1 <= ordinal <= len(trends)}
    for ordinal, verdict in sorted(verdicts.items()):
        topic = trends[ordinal - 1] if 1 <= ordinal <= len(trends) else None
        session.log.event(
            "topic_filter_verdict",
            f"{topic.name if topic else ordinal}: {verdict.verdict}",
            ordinal=ordinal, topic_key=topic.topic_key if topic else "",
            verdict=verdict.verdict, brands_to_strip=list(verdict.brands_to_strip),
            reason=verdict.reason,
            # v2.2.0: the two screened facts and the skip's code, so a run's drops are queryable
            # in events.jsonl without re-reading the reason sentences (FR-298).
            language=verdict.language, audience_fit=verdict.audience_fit,
            skip_code=verdict.skip_code)
    # The skip tally is broken down by cause on the stage line itself (v2.2.0): three causes now
    # produce one word, and "2 skip" hides whether the screen removed two competitor promos or
    # decided the whole monitor speaks the wrong language.
    causes = Counter(v.skip_code or topic_filter.SKIP_PROMO
                     for v in verdicts.values() if v.verdict == "skip")
    _stage(session, "FILTER",
           f"{len(trends)} topic(s) -> {kept} keep, {stripped} strip, {skipped} skip"
           + (" (" + ", ".join(f"{count} {code}" for code, count in sorted(causes.items())) + ")"
              if causes else ""),
           elapsed_s=watch.elapsed_s)
    for ordinal, verdict in sorted(verdicts.items()):
        topic = trends[ordinal - 1] if 1 <= ordinal <= len(trends) else None
        name = fit(topic.name, 24) if topic else f"topic {ordinal}"
        if verdict.verdict == "strip":
            removed = ", ".join(f'"{brand}"' for brand in verdict.brands_to_strip)
            session.say(f"          strip  {fit(f'{name} -- removed {removed}', 61)}")
        elif verdict.verdict == "skip":
            # The CODE leads, because the three causes have three different remedies: a promo skip
            # is the blocklist working, a LANG skip means the monitor feeds a language this run
            # does not write, and an AUDIENCE skip means the monitor and the niche disagree.
            code = verdict.skip_code or topic_filter.SKIP_PROMO
            session.say(f"          skip   {fit(f'{name} -- {code}: {verdict.reason}', 61)}")
        else:  # FR-299 verbose tier: keeps + their reasons move to the console only on demand
            session.note(f"          keep   {name} [{verdict.language or '?'}"
                         f"/{'fit' if verdict.audience_fit else 'unfit'}]"
                         + (f" -- {fit(verdict.reason, 40)}" if verdict.reason else ""))
    if any(str(v.reason).startswith("filter_degraded") for v in verdicts.values()):
        cause = next(str(v.reason) for v in verdicts.values()
                     if str(v.reason).startswith("filter_degraded"))
        session.log.warn("filter_degraded", cause)
        session.say(f"  {fit(cause + ' — blocklist verdicts stand, no topic was dropped', 74)}")
    return verdicts


def _record_style_forecast(session: _Session, live: Sequence[PlanEntry], registry: Any, *,
                           dropped: int) -> None:
    """The forecast end of FR-155's funnel, re-based for text-only styles (D46/F3).

    The style reference-image window is excised, so the render forecast no longer counts
    attachments — it states coverage: how many jobs render, over how many topics, wearing how
    many distinct styles. `registry` stays in the signature because coverage is only meaningful
    once assignment has run against one; a registry-less preview records zeros honestly.
    """
    session.counters.record_render(
        jobs=len(live), dropped=dropped,
        topics_used=len({entry.trend_key for entry in live if entry.trend_key}),
        styles_used=len({entry.style_key for entry in live if entry.style_key}))


# --------------------------------------------------------------------------- helpers


def _local_refs(session: _Session,
                live: Sequence[PlanEntry]) -> dict[str, tuple[tuple[Path, str], ...]]:
    """Every BRIEF-owned file a job uploads before it can reference it (FR-200, kind `"brief"`).

    Post-D46 this is the ONLY channel that travels to `refs.attach()`: a meta-style is words
    (F3), so a job's uploads are a brief's own photos — nothing else. Each file still travels
    WITH its kind, because the prompt names what each reference is (50 §3's `reference_roles`).
    """
    refs: dict[str, tuple[tuple[Path, str], ...]] = {}
    for entry in live:
        brief = session.campaign_briefs.get(entry.brief_name or "")
        merged = tuple((path, "brief")
                       for path in (brief.reference_image_paths if brief else ()))
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
    # v2.0.0: the analysis tag left the set with its stage; a failed copy call is
    # still the loss FR-248 charges to the latch (COPY_DEGRADED keeps its exit-1 semantics).
    llm_starved = {DegradationTag.COPY_DEGRADED}
    degraded = {asset_id for asset_id, record in report.records.items()
                if llm_starved.intersection(record.degradations)}
    hit = [entry for entry in entries if not entry.skip_reason
           and (entry.status is not PlanEntryStatus.SUCCESS or entry.asset_id in degraded)]
    for entry in hit:
        entry.skip_reason = f"{CREDITS_EXHAUSTED_REASON} (FR-248)"
    return (f"OpenRouter returned 402 — {CREDITS_EXHAUSTED_REASON}. Every later LLM call was "
            f"skipped rather than retried (FR-248); {len(hit)} creative(s) were lost or shipped "
            "degraded under it. This is NOT a Kie.ai render 402 (FR-167) — top up OpenRouter.")


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
        # The one seam every metered call passes through, so the per-role usage table below can
        # never disagree with the spend table beside it (§1.10: one number, one source).
        session.llm_usage.setdefault(role, _RoleUsage()).add(result)
        held = await session.budget.commit(result.cost_usd, label=f"llm {role}",
                                           category=SpendCategory.LLM, kind="projected")
        await session.budget.reconcile(held, result.cost_usd or None)
        # NFR-5: model, duration and the prompt IN FULL. `messages` is a `_FULL_ONLY_KEYS` name, so
        # events.jsonl keeps the whole payload and run.log gets its size — 40 §4's split, verbatim.
        # (The pre-pivot A21 audit extra died with its validator — NFR-5 v2.0.0 logs style key,
        # registry hash and filter verdicts instead, each at its own site.)
        extra: dict[str, Any] = {"messages": messages}
        session.log.event("llm_call", f"{role} call complete", duration_ms=watch.elapsed_ms,
                          role=role, model=_role_settings(session.config, role).model,
                          image_count=len(images or ()),  # not `images`: that key is prompt-sized
                          prompt_tokens=result.prompt_tokens,
                          completion_tokens=result.completion_tokens,
                          reasoning_tokens=result.reasoning_tokens,
                          cost_usd=round(result.cost_usd, 6), degraded=result.degraded, **extra)
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


def _stamp_provisional(entries: Sequence[PlanEntry]) -> None:
    """Give each atomic group its own provisional trend key, so the pre-Collect estimate counts
    the copy calls (FR-99/107) the operator can really be billed for.

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
    """FR-77's opening block: what this run is, resolved, before anything can change it.

    §1.10 added the two fact lines that now decide a run's shape: the registry (version, style
    count, hash, how many styles the active brand can use — FR-290/295) and the branding dial
    (selector, ratio, mode, placement — FR-292). The pre-pivot `mode` clause died with A/B.

    FR-318 rewrites the branding line rather than qualifying it: with the master switch off, the
    brand, the ratio, the mode and the placement are all inert, and printing four settings that
    do nothing is how an operator concludes the run WILL sign its creatives. What the line states
    instead is the switch, the key that flips it, and the one thing the switch does NOT touch —
    the competitor blocklist, which is safety and stays on.
    """
    config = session.config
    registry = session.registry
    branding = config.branding
    if registry is None:
        styles_line = "  styles      registry unavailable — pre-flight will refuse (FR-295)"
    else:
        usable = sum(1 for style in registry.styles
                     if styles.brand_ok(style, branding.brand,
                                        branding_enabled=branding.enabled))
        styles_line = (f"  styles      registry v{registry.version} · {len(registry.styles)} "
                       f"styles · sha {registry.content_hash[:8]} · {usable} usable here")
    return "\n".join([
        f"HypeSocials run {session.run_id}",
        # FR-286: the niche descriptor behind `description` ran to 400 chars and produced a
        # 557-char line that conhost mangled. Path and label each get their own bounded line.
        f"  config      {fit(str(config.path), 64)}",
        f"              {fit(config.description or 'no description', 60)}",
        f"  formats     " + ", ".join(f"{name}={count}" for name, count in config.run.formats.items()),
        f"  platforms   " + ", ".join(
            f"{name}/{config.language_for(name)}" for name in config.run.platforms),
        styles_line,
        (f"  branding    {branding.brand} · brand_ratio {branding.brand_ratio:.2f} · "
         f"{branding.mode} · {branding.placement}" if branding.enabled else
         # 72 chars — FR-286's 78-column ceiling holds; the two facts that fit are the ones the
         # operator needs: the switch (with its key) and the carve-out that safety is still on.
         "  branding    off (branding.enabled: false) · competitor filter still on"),
        f"  checks      notion {config.run.notion_influence} · gauntlet "
        + (", ".join(name for name, critic in config.run.gauntlet.critics.items()
                     if critic.enabled) + f" x{config.run.gauntlet.rounds_max}"
           if config.run.gauntlet.enabled else "off"),
        f"  spend cap   {format_usd(config.run.spend_cap_usd)} · deadline "
        f"{config.run.run_deadline_min} min",
        f"  output      {fit(str(session.run_dir), 64)}",
        # FR-286: an override list grows without bound, so it wraps onto its own indented lines.
        "\n".join(f"  {'overrides' if first else '         '}   {part}"
                  for first, part in wrapped(
                      ", ".join(overrides) or "none (config values as written)", 62)),
    ])


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
    """FR-155's funnel, re-shaped for the topic pipeline and printed ONCE, at DONE (v2.0.0).

    Its old three stage-gate placements are superseded by the FR-296 stage headers, which carry
    the same counts the moment they become true; this block is the end-of-run reconciliation —
    input → topics → filter → Select's verdicts → the style-forecast render row. A pure function
    of `Counters` so the paid run and both preview modes print the identical block (FR-139).

    Two rules survive from the old shape:

    - **Zero prints.** Every stage appears whether or not it lost anything — an operator cannot
      tell a healthy zero from a dead counter. The exception stays: Virlo returning nothing at
      all says so in words, never as a clean row of zeros.
    - **The vocabularies do not mix.** Input words (video, slideshow, post) sit on `input`/
      `topics`; output words (job, style ref) appear only on `render`. A Virlo slideshow is
      evidence — it lends the topic carousel *affinity* (FR-90) and is never itself rendered.

    The media rows (`sets`/`chosen`/`images`) died with the reference funnel; `total_available`
    is promoted into the header (FR-297d), so the operator can see how deep the one page each
    call asked for reaches into Virlo's own row total.
    """
    tally = counters
    # FR-286 at real-corpus scale: `total_available` SUMS across monitors (absorb) and reaches
    # seven digits, so the header uses FR-297's compact numbers and wraps as a last resort —
    # T3.5's corpus test pinned the overflow before this shipped.
    header = (f"Virlo funnel — {tally.monitors_asked} monitor(s) asked · "
              f"{tally.rows_per_call} rows/call · {tally.monitors_failed} failed · "
              f"{_compact(tally.total_available)} available")
    lines = [part if first else f"  {part}"
             for first, part in wrapped(header, _FUNNEL_WIDTH)]
    if tally.posts_raw == 0:
        lines += _funnel_row("input", "Virlo returned no video and no slideshow — "
                                      "no topic material")
        # The drop rows still print (zeros included) — with the videos ask disabled, the row
        # that says "not called" is exactly what distinguishes an empty monitor from an
        # unasked one (FR-305/FR-307, v2.1.0; wording owned by the adapter's `drop_rows`).
        for label, clauses in tally.drop_rows():
            lines += _funnel_row(label, *clauses)
    else:
        lines += _funnel_row(
            "input", f"{tally.videos_raw} video(s) + {tally.slideshows_raw} slideshow(s)",
            f"{tally.duplicates_dropped} duplicate row(s) dropped")
        # FR-305/FR-307 gate losses sit between input and topics because that is where they
        # happen: rows are judged after the dedupe and before the split, so `topics`' posts_in
        # already counts only survivors. Words come from `Counters.drop_rows` (FR-155 one-place
        # rule); this block owns only the 78-column packing.
        for label, clauses in tally.drop_rows():
            lines += _funnel_row(label, *clauses)
        lines += _funnel_row(
            "topics", f"{tally.posts_in} post(s) split into {tally.topics_out} topic(s)",
            f"{tally.topics_synthesized} synthesized")
    if tally.filter_kept or tally.filter_stripped or tally.filter_skipped:
        lines += _funnel_row(
            "filter", f"{tally.filter_kept} kept, {tally.filter_stripped} stripped, "
                      f"{tally.filter_skipped} skipped",
            "LLM layer degraded — blocklist only" if tally.filter_degraded else "")
    if tally.verdict_seen:
        lines += _funnel_row(
            "verdict", f"{tally.eligible} eligible, {tally.excluded_by_history} excluded by "
                       f"history, {tally.unusable} unusable")
    if tally.render_seen:
        lines += _funnel_row(
            "render", f"{tally.jobs} job(s) will render",
            f"{tally.styles_used} style(s) over {tally.topics_used} topic(s)",
            f"{tally.jobs_dropped} dropped, no topic left" if tally.jobs_dropped else "")
    return "\n".join(lines)


#: FR-297b's volume guard: the paid-run post roster covers the strongest three assigned topics ×
#: three posts each; `--verbose` and both preview modes pass `None` (uncapped), because printing
#: every post of every topic IS what those exist for (FR-139/140/299).
_DETAIL_TRENDS = 3


def _money(amount: float) -> str:
    """Cents normally, four decimals below one cent — an LLM line that really cost $0.0024 must
    not print as the `$0.00` an unpriced line prints (FR-85's *estimated* honesty, same idea)."""
    return f"${amount:.4f}" if 0 < amount < 0.01 else format_usd(amount)


def _spend_table(summary: SpendSummary, gates: Mapping[str, str] | None = None) -> str:
    """FR-84's ONE spend table: per creative, per format, then the grand total and cap status.

    The pre-pivot single-chain `virlo` row is gone (§1.10 rule: a number appears in exactly ONE
    of {stage header, table, funnel, spend row} — the funnel now prints directly above this
    table at DONE, so repeating its chain here would double every count it carries).

    FR-321 gives the `ok` column a third value. A deck that shipped seven of the eight slides it
    was ordered to have prints `7/8` where a complete one prints `yes`: this table is where the
    operator first scans the result, and a missing slide that reads as an unqualified success is
    a loss they only find by opening the folder. `no` still means nothing shipped at all.

    v2.2.0 adds the `gate` column (FR-328): what the post-render critic panel said about each
    creative, read off `meta.yaml.gauntlet.result`. It belongs HERE rather than in a table of its
    own because `blocked` is a spend outcome as much as a quality one — the money was spent, the
    creative is not published, and those two facts have to be readable on one row. `-` means the
    gate did not run for that creative (disabled, nothing delivered, an unsalvageable deck).
    """
    gates = gates or {}
    # FR-286: asset ids run to ~46 chars, so a fixed 40-wide column both overflowed 78 AND ran
    # into the format column with no space (`..._04image`). Fit the one variable column instead.
    lines = [summary.headline]
    lines.append(f"  {'asset':<30} {'format':<9}{'est':>9}{'billed':>10} {'ok':<4} gate")
    for row in summary.rows:
        mark = (f"{row.slides_delivered or 0}/{row.slides_ordered}" if row.partial
                else "yes" if row.delivered else "no")
        billed = format_usd(row.billed_usd) + (" est" if row.estimated_only else "")
        lines.append(f"  {fit(row.asset_id, 30):<30} {row.creative_format:<9}"
                     f"{format_usd(row.estimated_usd):>9}{billed:>10} {mark:<4} "
                     f"{gates.get(row.asset_id, '-')}")
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


def _gate_column(report: generate.Report) -> dict[str, str]:
    """`asset_id -> the gate's verdict`, for the spend table's `gate` column (FR-328).

    Read off each record's `meta.yaml.gauntlet` dict rather than recomputed, so the console, the
    meta document and `GAUNTLET_REPORT.yaml` can never say three different things. A creative the
    gate never touched is absent from the mapping and prints as `-`.
    """
    column: dict[str, str] = {}
    for asset_id, record in report.records.items():
        gate = getattr(record, "gauntlet", None)
        if isinstance(gate, dict) and gate.get("result"):
            column[asset_id] = str(gate["result"]) + ("*" if gate.get("degraded_gate") else "")
    return column


#: FR-84/FR-326: which LLM roles a run can spend on, in pipeline order, so the usage table below
#: reads top to bottom the way the run happened. `critic:<name>` overrides are folded into their
#: base role — an operator reading a cost table wants "the critics cost $0.31", not three rows.
_LLM_ROLE_ORDER = ("analysis", "copy", "critic")


def _llm_usage_table(session: _Session, summary: SpendSummary) -> str:
    """FR-84/FR-326's per-role LLM usage block: calls, tokens both ways, dollars — plus render.

    New in v2.2.0 and new for a reason: the gauntlet made LLM spend the LARGER half of a run's bill
    at worst case (spec §5 — three critics x three rounds is comparable to the whole re-render
    budget), and until now the operator's only view of it was one `llm $0.42` figure inside the
    spend total. Token counts are what actually move that number, so they are what this prints.

    Every row is read off `session.llm_usage`, which is written at the single metered seam
    (`_metered`), so this table and the spend table are two views of one accumulation rather than
    two counts that can drift. The render row comes from the same `SpendSummary` the table above
    printed, for the same reason.
    """
    rows: dict[str, _RoleUsage] = {}
    for role, usage in session.llm_usage.items():
        base = role.partition(":")[0]  # `critic:brief` folds into `critic`
        into = rows.setdefault(base, _RoleUsage())
        into.calls += usage.calls
        into.prompt_tokens += usage.prompt_tokens
        into.completion_tokens += usage.completion_tokens
        into.cost_usd += usage.cost_usd
    if not rows:
        return "  LLM usage   no metered LLM call was made this run"
    order = [name for name in _LLM_ROLE_ORDER if name in rows]
    order += [name for name in sorted(rows) if name not in order]  # never silently drop a role
    lines = ["  LLM usage",
             f"  {'role':<12}{'calls':>7}{'in tok':>10}{'out tok':>10}{'usd':>10}"]
    for name in order:
        usage = rows[name]
        lines.append(f"  {name:<12}{usage.calls:>7}{usage.prompt_tokens:>10}"
                     f"{usage.completion_tokens:>10}{_money(usage.cost_usd):>10}")
    total = sum(usage.cost_usd for usage in rows.values())
    lines.append(f"  {'llm total':<12}{sum(u.calls for u in rows.values()):>7}"
                 f"{sum(u.prompt_tokens for u in rows.values()):>10}"
                 f"{sum(u.completion_tokens for u in rows.values()):>10}{_money(total):>10}")
    # The render row carries no tokens by nature — it is priced per job, not per token — and it is
    # here anyway, because "what did this run spend, and on what" is one question.
    lines.append(f"  {'render':<12}{'':>7}{'':>10}{'':>10}{_money(summary.render_usd):>10}")
    return "\n".join(lines)


def _final_line(session: _Session, entries: Sequence[PlanEntry], summary: SpendSummary,
                code: int) -> str:
    """FR-232's one-line close: cost, wall clock, counts, skip reasons, status and the exit code.

    FR-321: `generated` counts the creatives that shipped, and a deck that shipped SHORT is named
    separately (`generated 6 · 1 partial`). Folding partial decks into `generated` would make the
    closing line the one surface that still calls a truncated deck a whole one, right after the
    spend table above it said `7/8`.
    """
    status = {EXIT_OK: "success", EXIT_PARTIAL: "partial-success",
              EXIT_INTERRUPTED: "interrupted"}.get(code, "failed")
    delivered = sum(1 for row in summary.rows if row.delivered)
    partial = f" · {summary.partial} partial" if summary.partial else ""
    reasons = sorted({str(entry.skip_reason).split(":", 1)[0].split(" ", 1)[0]
                      for entry in entries if entry.skip_reason})
    skipped = len(summary.rows) - delivered
    detail = f" ({fit(', '.join(reasons), 40)})" if reasons else ""
    # FR-286: `total` covers Kie and OpenRouter only. Virlo's own calls meter against the Virlo
    # deposit, so an unqualified `total $0.00` on a run that opened a session was a false statement.
    metered = " + Virlo metering" if session.virlo_contacted else ""
    return "\n".join([
        f"run {session.run_id} · total {_money(summary.total_usd)} (Kie/OpenRouter){metered}",
        f"  {session.clock.elapsed_s:.1f}s · generated {delivered}{partial} · "
        f"skipped {skipped}{detail}",
        f"  status {status} · exit code {code} ({_EXIT_LEGEND[code]})",
        f"  folder    {fit(str(session.run_dir), 65)}",
        # FR-297f: the gallery path in the exit block — until now it was never printed at all.
        f"  gallery   {fit(str(session.run_dir / 'gallery.html'), 65)}",
    ])


async def _cleanup(session: _Session) -> None:
    """FR-249: scratch, clients and log handles released on EVERY exit path, in a safe order.

    Every step is independent and swallowed: a run that already failed must not fail again on the
    way out, and a real Ctrl+C reaches the MCP wrapper too, so some children are already gone
    before we get here (spikes/RESULTS.md §F — `ProcessLookupError` is expected).
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
    session.log.close()


__all__ = [
    "Control", "EXIT_INTERRUPTED", "EXIT_NOTHING_USABLE", "EXIT_OK", "EXIT_PARTIAL",
    "EXIT_PREFLIGHT", "LOGS_DIR", "DegradationMap", "decide_exit_code", "list_monitors", "run",
]
