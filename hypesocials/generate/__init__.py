"""CREATE — plan entries in, finished asset folders out. **All three formats, two waves.**

Module contract
---------------
Purpose: own everything between "this creative was approved" and "this creative is on disk" —
format dispatch, prompt assembly, reference attachment, the money around every submission, the
FR-203 ledger, the deadline's grace window, and packaging. The runner hands over entries and gets
back records; it never touches a template, a reference URL, a render body or a meta.yaml key.

Public API: `create(entries, env)` · `Env` · `Report` · `ledger_hooks(ledger)` · `GRACE_S`.

Invariants:
- **One money path.** Every submission — image, carousel slide, reel seed frame, Seedance clip —
  goes through the single `submit` callable built here, which owns FR-106 a/b/c (`projected` and
  `precommitted` `commit()`, `discretionary` `reserve()`), the profile lookup, the per-job
  projection (`budget.job_projection`) and exactly one `ledger.terminal()` line per submission.
  `carousel.py` and `reel.py` price nothing and write no ledger line.
- **Spend tallies on submission, failures included** — a reservation that reached the provider is
  reconciled, never released; only a submission that never happened is released (20 §8).
- **A folder never holds media without meta** — `AssetFolder` writes `pending` meta at creation
  and rewrites it terminally, so every exit path (success, skip, interrupt, abandonment) leaves
  one whole state (NFR-21). A failed creative keeps its paid caption (FR-74).
- **Nothing new is ordered once `env.halted` is true**, and what is already in flight gets ONE
  ~30 s grace window before it is abandoned honestly, with its taskId in the ledger (FR-108/201).
- **References are the FR-91 coherent set already built by `sources/virlo.py`** — one group, one
  source, panels preferred, capped by `reference_images_per_job`. This module attaches them, it
  does not re-select them; `sources.reference_group()` decides WHICH group by the entry's
  `trend_reuse_index`, so siblings on one trend attach different winning posts. Local files
  (Inspiration, brief images) go through `render.upload_file()` first (FR-200) and a failed
  upload drops that one reference, never the job.
- **A creative's style brief is looked up by its (trend, reference group) PAIR** — `env.brief_for`,
  never `style_briefs[trend_key]` — so the forensic description always describes the pictures this
  creative attaches (FR-9/12, amended 2026-08-11).
- **An unresolved placeholder fails the creative BEFORE submission** (FR-260) — nothing malformed
  is ever paid for.
- **Kie's 402 is a whole-run condition** (FR-167): it is latched once and every remaining
  creative is skipped with "top up your Kie.ai credits" rather than each retrying a certainty.
- **A full disk stops downloading, run-wide** (10 §10): `env.disk_full` latches on the first
  `disk_full` packaging error and every later creative skips its download instead of thrashing
  the volume; the runner reads it back off `Report.disk_full`.

Do not: call Kie directly, name a Kie field, spell an asset path, re-derive a price, or let a
`CancelledError` escape `create()`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from hypesocials import render, vision_check
from hypesocials.budget import Budget, SpendCategory, job_projection
from hypesocials.config import Config
from hypesocials.models import (
    AssetRecord,
    Brief,
    CopySet,
    DegradationTag,
    PlanEntry,
    PlanEntryStatus,
    RenderOutcome,
    RenderOutcomeKind,
    RenderFailCause,
    RenderParams,
    RenderPriority,
    RenderRefs,
    StyleBrief,
    TrendItem,
    VisionCheckResult,
)
from hypesocials.outputs import AssetFolder, Ledger, LogWriter, PackagingError, write_gallery
from hypesocials.prompts_engine import (
    MissingTemplateError,
    PromptEngine,
    UnresolvedPlaceholderError,
    build_context,
    style_brief_line,
)
from hypesocials.sources import brief_key
from hypesocials.util import Deadline

# Both format modules back-import this package under TYPE_CHECKING only, so importing them here
# is safe and keeps the dispatch a plain name lookup (which is also what makes it fakeable).
from hypesocials.generate.refs import Reference, attach, role_lines
from hypesocials.generate.carousel import render_carousel
from hypesocials.generate.reel import render_reel

#: Which template role an image creative uses. `analyzed` without a style brief is FR-12's
#: degrade: it runs the direct scaffold and carries `analysis_missing`.
ROLE_ANALYZED = "image_single_post.md"
ROLE_DIRECT = "image_direct.md"

#: FR-108's "one short grace poll (~30 s)": at the deadline — or at the first Ctrl+C (FR-201) —
#: outstanding jobs get exactly this long to land, because work seconds from completing is work
#: already paid for. Whatever is still running afterwards is abandoned and left unclaimed at Kie,
#: which is the accepted, stated cost. Never a resubmission, never a second window.
GRACE_S = 30.0
#: How often `_drain` re-reads `env.halted` while creatives run; the deadline is a soft ceiling
#: (FR-108), so half a second of slack costs nothing and a timer beats a busy loop.
_HALT_POLL_S = 0.5

#: Set for the duration of one creative's submission so the FR-203 ledger hooks — which the
#: render seam calls with a request token and nothing else — can name the asset the token bought.
_CURRENT_ASSET: ContextVar[str] = ContextVar("_hypesocials_current_asset", default="")
#: asset_id -> the taskId of its latest submission that has not yet reached a terminal line. It
#: exists for one reason: an abandoned creative's ledger line can name the job that is still
#: running at Kie (FR-108/203). Cleared per run by `ledger_hooks()`.
_OPEN_TASKS: dict[str, str] = {}

_HALTED = "halted — the run stopped ordering new work (FR-108/201)"
_CREDITS = "kie_credits_exhausted — top up your Kie.ai credits (FR-167)"


@dataclass(slots=True)
class Env:
    """Everything constant across one run's creatives, threaded once instead of per call."""

    config: Config
    run_dir: Path
    engine: PromptEngine
    budget: Budget
    log: LogWriter
    ledger: Ledger
    trends: Mapping[str, TrendItem] = field(default_factory=dict)
    style_briefs: Mapping[str, StyleBrief] = field(default_factory=dict)
    copy: Mapping[str, CopySet] = field(default_factory=dict)
    #: `CopyResult.tags` — `asset_id -> the DegradationTags the copy stage earned this creative`
    #: (FR-99's `copy_degraded`, FR-101's `text_trimmed`, A20's `no_onimage_text`, A21's
    #: `hook_pattern_generic`). ONE field rather than one frozenset per tag: the copy stage is
    #: free to grow a new degradation without a new field here and a new branch in `_record`.
    copy_tags: Mapping[str, Sequence[DegradationTag]] = field(default_factory=dict)
    #: FR-200/191: `asset_id -> ((path, kind), …)`, kind in {"brief", "inspiration"} — the
    #: provenance that picks each attachment's role line (`refs.py`).
    local_refs: Mapping[str, Sequence[tuple[Path, str]]] = field(default_factory=dict)
    campaign_briefs: Mapping[str, Brief] = field(default_factory=dict)  # FR-144/145, by name
    brand_accent: str = ""  # FR-109 `full` only: one accent colour inside the trend's own palette
    brand_product_nouns: Sequence[str] = ()  # FR-109 `full` only: nouns for the on-image text
    niche_descriptor: str = ""  # copy-side (audience included): the analyst and copywriter only
    niche_visual_world: str = ""  # A15: `niche.visual_world` alone — the four gpt-image-2 roles
    llm_call: Any = None  # metered `StructuredCall` for the FR-27 vision check; None = off
    video_refs: Any = None  # `video_ref.Prefetch` for the D23 motion reference, or None
    stop: asyncio.Event | None = None  # Ctrl+C: stop ORDERING new work (FR-201)
    deadline: Deadline | None = None  # the run's soft monotonic ceiling (FR-108/243)
    credits_exhausted: bool = False  # FR-167, latched once
    disk_full: bool = False  # 10 §10, latched once: further downloads stop run-wide

    def brief_for(self, entry: PlanEntry) -> StyleBrief | None:
        """This creative's style brief, or None when its own pair has none (FR-9/12, amended today).

        Briefs are keyed by the `(trend, reference group)` PAIR, because the brief must describe
        the pictures the creative actually attaches — and `refs.attach()` rotates the group per
        `trend_reuse_index`. Looking a brief up by trend key alone would hand the k-th sibling a
        forensic description of group 0's images while it renders group k's: the analysed variant
        would be steered *away* from its own references. None is FR-12's degrade signal, not an
        error — the creative runs the direct scaffold and carries `analysis_missing`.
        """
        key = entry.trend_key or ""
        return self.style_briefs.get(brief_key(key, self.trends.get(key), entry.trend_reuse_index))

    @property
    def halted(self) -> bool:
        """True once Ctrl+C landed or the run deadline elapsed — every module re-reads this
        before each submission, so an interrupt costs at most one in-flight job."""
        return bool(self.stop is not None and self.stop.is_set()) or bool(
            self.deadline is not None and self.deadline.expired)


@dataclass(slots=True)
class Report:
    """What landed on disk: one record per entry plus the trends that earned a history line."""

    records: dict[str, AssetRecord] = field(default_factory=dict)
    packaged_trends: set[str] = field(default_factory=set)  # FR-82: packaged creatives only
    disk_full: bool = False  # 10 §10: further downloads stop rather than thrash a full disk


def ledger_hooks(ledger: Ledger) -> tuple[Any, Any]:
    """FR-203's intent-before-call hooks, bound to this run's ledger.

    The render seam deliberately knows nothing about asset ids, so the asset travels in a
    context variable set around each submission; a token whose response is lost still gets its
    `submit_unknown` line, which is the exact case the ledger exists for.
    """
    _OPEN_TASKS.clear()

    def on_intent(request_token: str) -> None:
        ledger.intent(_CURRENT_ASSET.get() or "unknown", request_token)

    def on_submitted(request_token: str, task_id: str | None) -> None:
        asset = _CURRENT_ASSET.get() or "unknown"
        if task_id:  # remembered until its terminal line, so an abandon can still name the job
            _OPEN_TASKS[asset] = task_id
        ledger.submitted(asset, request_token, task_id)

    return on_intent, on_submitted


async def create(entries: Sequence[PlanEntry], env: Env) -> Report:
    """Build every approved creative concurrently and package the rest honestly.

    Concurrency is bounded inside `render.run()` by the priority permit gate, so every entry
    starts at once and the gate decides how many jobs are actually in flight (FR-25). Nothing
    raised — or cancelled — inside one creative can reach another: each returns a terminal record.
    """
    report = Report()
    if not entries:
        return report
    tasks = [asyncio.create_task(_one(entry, env, report), name=f"create:{entry.asset_id}")
             for entry in entries]
    for record in await _drain(tasks, env):
        report.records[record.asset_id] = record
    report.disk_full = env.disk_full
    return report


async def _drain(tasks: list[asyncio.Task[AssetRecord]], env: Env) -> list[AssetRecord]:
    """Wait for every creative, then honour FR-108's single grace window.

    Ordering already stops the moment `env.halted` flips — every module re-reads it before each
    submission. What is left is the in-flight work, and it gets exactly one ~30 s window to land
    before it is cancelled: the entry goes terminal as `abandoned` with its taskId in the ledger,
    and the job is left to complete unclaimed at Kie (FR-108's stated cost). Never resubmitted,
    never awaited past the grace, and cancellation never escapes this function.
    """
    pending: set[asyncio.Task[AssetRecord]] = set(tasks)
    shown = False
    while pending and not env.halted:
        done, pending = await asyncio.wait(pending, timeout=_HALT_POLL_S)
        if done and not shown:  # FR-76: the first creatives are reviewable while reels still run
            shown = True  # NFR-22 is inside `write_gallery` — it returns None, it never raises
            write_gallery(env.run_dir, title=env.config.output.gallery.title, log=env.log)
    if pending:
        env.log.warn("grace_poll",
                     f"{len(pending)} creative(s) still in flight — one {GRACE_S:.0f}s grace "
                     "window, then they are abandoned and left unclaimed at Kie (FR-108)",
                     in_flight=len(pending))
        _, pending = await asyncio.wait(pending, timeout=GRACE_S)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.wait(pending)  # each wrapper answers a cancellation with a terminal record
    return [task.result() for task in tasks if not task.cancelled()]


# --------------------------------------------------------------------------- one creative


async def _one(entry: PlanEntry, env: Env, report: Report) -> AssetRecord:
    """One plan entry, from folder creation to terminal meta. Never raises, never cancels out."""
    folder = AssetFolder(env.run_dir, _record(entry, env))
    copyset = env.copy.get(entry.asset_id)
    if copyset is not None:
        try:  # the copy was already paid for; a failed write must not cost the whole creative
            folder.write_caption(copyset.caption, copyset.hashtags)
        except PackagingError as exc:
            env.log.error("caption_write_failed", f"{entry.asset_id}: {exc}",
                          asset_id=entry.asset_id)
    brief = env.campaign_briefs.get(entry.brief_name or "")
    for path in (brief.reference_image_paths if brief else ()):
        try:  # FR-71: a brief's own pictures ship in the asset's `refs/`, beside what they made
            folder.add_reference(path)
        except PackagingError as exc:
            env.log.warn("reference_copy_failed",
                         f"{entry.asset_id}: {Path(path).name} not copied into refs/ ({exc})",
                         asset_id=entry.asset_id, reference=Path(path).name)
    try:
        return await _dispatch(entry, env, folder, report)
    except asyncio.CancelledError:
        # The grace window closed on an in-flight job. Every write in `_abandon` is synchronous,
        # so this folder still lands terminal while the task unwinds (NFR-21, FR-108).
        return _abandon(entry, env, folder)


async def _dispatch(entry: PlanEntry, env: Env, folder: AssetFolder,
                    report: Report) -> AssetRecord:
    """Pre-checks, then the one branch by format. Each module owns its own chain from there."""
    if entry.status is PlanEntryStatus.SKIPPED_BUDGET:
        return folder.skip(entry.skip_reason or "trimmed to fit the spend cap (FR-28/FR-106)",
                           DegradationTag.SKIPPED_BUDGET)
    if entry.status is not PlanEntryStatus.PENDING:
        return folder.skip(entry.skip_reason or f"not generated ({entry.status.value})")
    if env.credits_exhausted:
        return _fail(entry, env, folder, _CREDITS)
    if env.halted:
        entry.status = PlanEntryStatus.ABANDONED
        entry.skip_reason = "interrupted_before_submission"
        return folder.skip("interrupted before submission — nothing was ordered for this creative",
                           DegradationTag.ABANDONED)

    submit = _submitter(env)
    if entry.creative_format == "carousel":
        record = await render_carousel(entry, env, folder, submit=submit)
    elif entry.creative_format == "reel":
        record = await render_reel(entry, env, folder, submit=submit)
    else:
        record = await _image(entry, env, folder, submit)
    if entry.status is PlanEntryStatus.SUCCESS and entry.trend_key:
        report.packaged_trends.add(entry.trend_key)  # FR-82: packaged creatives only
    return record


async def _image(entry: PlanEntry, env: Env, folder: AssetFolder, submit: Any) -> AssetRecord:
    """One standalone image: assemble, submit, FR-97's retry, FR-27's check, package the bytes."""
    attached = await attach(entry, env, folder)
    urls = [ref.url for ref in attached]
    prompt = _assemble(entry, env, attached)
    if prompt is None:
        return _fail(entry, env, folder, "prompt_assembly_failed — unresolved placeholder (FR-260)")
    params = RenderParams(prompt=prompt, aspect_ratio=entry.aspect_ratio)
    try:
        outcome = await submit(entry, params, RenderRefs(image_urls=urls), job="image",
                               priority=RenderPriority.WAVE1, kind="projected",
                               label=f"image render · {entry.asset_id}")
        if (outcome is not None and outcome.kind is not RenderOutcomeKind.SUCCESS
                and outcome.fail_cause is RenderFailCause.MODERATION and urls):
            env.log.warn("moderation_retry",
                         f"{entry.asset_id}: content-policy refusal; one reference-free retry "
                         "(FR-97)", asset_id=entry.asset_id, detail=outcome.fail_message)
            # The refused job was billed on submission and already has its own terminal ledger
            # line from `submit` — the ledger shows both taskIds, not only the one that survived.
            retry = await submit(entry, params, RenderRefs(), job="image",
                                 priority=RenderPriority.WAVE1, kind="discretionary",
                                 label=f"moderation retry · {entry.asset_id}")
            if retry is not None:
                folder.mark(DegradationTag.REFS_DROPPED_MODERATION)
                outcome = retry
    except render.KieOutOfCredits as exc:
        env.credits_exhausted = True
        return _fail(entry, env, folder, f"{_CREDITS} ({exc})")
    if outcome is None:
        return _fail(entry, env, folder, "skipped_budget — the cap declined this submission",
                     DegradationTag.SKIPPED_BUDGET)
    if outcome.kind is not RenderOutcomeKind.SUCCESS or not outcome.result_urls:
        # FR-242: a `success` with no usable result is a failure that lies — treated as a failure.
        cause = (outcome.fail_cause.value if outcome.fail_cause else outcome.kind.value)
        env.log.error("render_failed", f"{entry.asset_id}: {cause} — "
                      f"{outcome.fail_message or 'no usable result'}", asset_id=entry.asset_id,
                      task_id=outcome.task_id, cost_usd=round(outcome.cost_usd, 6))
        return _fail(entry, env, folder, f"{cause}: {outcome.fail_message or 'no usable result'}"
                     f" (job {outcome.task_id or 'unknown'})", cost=outcome.cost_usd,
                     outcome=outcome)
    if env.disk_full:  # 10 §10: downloads stopped run-wide rather than thrash a full disk
        return _fail(entry, env, folder, "disk_full: downloads stopped for this run",
                     cost=outcome.cost_usd, outcome=outcome)
    try:  # the bytes stop being a borrowed 24 h URL and become the operator's file
        stored = await folder.store_render(outcome.result_urls[0])
    except PackagingError as exc:
        if exc.reason == "disk_full":  # the one failure that outlives this creative
            env.disk_full = True
        return _fail(entry, env, folder, f"{exc.reason}: {exc}", cost=outcome.cost_usd,
                     outcome=outcome)
    verdict, retry = await _vision(entry, env, folder, submit, attached, stored)

    entry.status = PlanEntryStatus.SUCCESS
    cost = outcome.cost_usd + (retry.cost_usd if retry is not None else 0.0)
    return folder.finish(
        actual_cost_usd=round(cost, 6),
        model_ids=[env.config.models.image, env.config.models.image_profile],
        kie_job_ids=[job.task_id for job in (outcome, retry) if job is not None and job.task_id],
        job_submission_timestamp=outcome.submitted_at,
        job_completion_timestamp=(retry.completed_at if retry else "") or outcome.completed_at,
        native_size_rendered=entry.aspect_ratio,  # FR-98: shipped exactly as it came back
        vision_check_result=verdict,
        event_id=env.log.event("creative_delivered", f"{entry.asset_id} rendered",
                               asset_id=entry.asset_id, task_id=outcome.task_id,
                               cost_usd=round(cost, 6), vision_check=verdict.value,
                               duration_ms=int(outcome.elapsed_s * 1000)))


async def _vision(
    entry: PlanEntry, env: Env, folder: AssetFolder, submit: Any,
    attached: Sequence[Reference], stored: Path,
) -> tuple[VisionCheckResult, RenderOutcome | None]:
    """FR-27/105 for a standalone image: one check, ONE re-render, one re-check, then it ships.

    The estimator prices exactly this pair per image (`budget.py`'s `checked_images` plus the
    `vision_retry_allowance`), so an image the operator was billed a check for gets one. The
    re-render is discretionary (FR-106c) — a declined or failed one is `retried_failed`, never
    laundered into `passed`. Returns the verdict and the retry's outcome, for cost and job ids.
    """
    if not env.config.run.vision_check or env.llm_call is None:
        return VisionCheckResult.NOT_CHECKED, None
    first = (await vision_check.check([stored], call=env.llm_call, engine=env.engine,
                                      log=env.log)).verdict_for(1)
    if first is None or not first.flagged or env.halted:
        return vision_check.verdict_result(first), None
    env.log.warn("vision_check_flagged",
                 f"{entry.asset_id} flagged ({first.detail}); one re-render with shorter, larger "
                 "text (FR-105)", asset_id=entry.asset_id)
    plan = vision_check.retry_plan(
        env.copy.get(entry.asset_id) or CopySet(asset_id=entry.asset_id, language=entry.language),
        "image", env.config.run.text_budgets)
    prompt = _assemble(entry, env, attached, copyset=plan.copy, budget_scale=plan.budget_scale,
                       extra=plan.instruction)
    if prompt is None:
        return VisionCheckResult.RETRIED_FAILED, None
    try:
        retry = await submit(entry, RenderParams(prompt=prompt, aspect_ratio=entry.aspect_ratio),
                             RenderRefs(image_urls=[ref.url for ref in attached]), job="image",
                             priority=RenderPriority.WAVE1, kind="discretionary",
                             label=f"vision re-render · {entry.asset_id}")
    except render.KieOutOfCredits:
        env.credits_exhausted = True  # FR-167: the flagged image ships exactly as rendered
        return VisionCheckResult.RETRIED_FAILED, None
    if retry is None or retry.kind is not RenderOutcomeKind.SUCCESS or not retry.result_urls:
        env.log.warn("vision_retry_unavailable",
                     f"{entry.asset_id}: the flagged image ships as rendered "
                     f"({'declined by the cap' if retry is None else 'the re-render failed'})",
                     asset_id=entry.asset_id)
        return VisionCheckResult.RETRIED_FAILED, retry
    try:  # the re-render REPLACES the delivered file, then earns its one second verdict
        replaced = await folder.store_render(retry.result_urls[0])
    except PackagingError as exc:
        if exc.reason == "disk_full":
            env.disk_full = True
        return VisionCheckResult.RETRIED_FAILED, retry
    after = (await vision_check.check([replaced], call=env.llm_call, engine=env.engine,
                                      log=env.log)).verdict_for(1)
    return vision_check.verdict_result(first, after, retried=True), retry


# --------------------------------------------------------------------------- the money door


def _submitter(env: Env) -> Any:
    """This run's `submit` callable, matching `carousel.Submit` field for field."""
    return partial(_submit, env=env)


async def _submit(
    entry: PlanEntry, params: RenderParams, refs: RenderRefs, *, env: Env, job: str,
    priority: RenderPriority, kind: str, label: str,
) -> RenderOutcome | None:
    """The run's ONE metered door to `render.run` — money, profile and ledger, in that order.

    Owns FR-106 a/b/c: `projected` work `commit()`s inside the approved wave-1 projection,
    `precommitted` work (slides 2–N, the Seedance clip) `commit()`s unconditionally so cap
    bookkeeping can never split a deck, and `discretionary` work (moderation retries,
    vision-check re-renders) `reserve()`s and returns `None` when the cap declines it. Spend
    tallies on submission — a job that reached the provider is reconciled to its own reported
    cost, failures included; only a submission that never happened is released (20 §8).

    Also owns the profile (`clip` → `models.video_profile`, everything else →
    `models.image_profile`), the per-job projection (`budget.job_projection` — no caller prices
    anything), and exactly one FR-203 `terminal` ledger line per submission, including the
    moderation-refused and content-audit-failed attempts a caller then retries.

    `render.KieOutOfCredits` is re-raised after the reservation is released — callers latch
    `env.credits_exhausted` and package what they hold (FR-167). A halt is belt and braces: every
    caller pre-checks `env.halted`, so this only catches the race, and it returns a FAIL outcome
    without holding or spending anything.
    """
    if env.credits_exhausted:
        raise render.KieOutOfCredits(_CREDITS)
    if env.halted:
        return RenderOutcome(kind=RenderOutcomeKind.FAIL, fail_message=_HALTED)
    profile = (env.config.models.video_profile if job == "clip"
               else env.config.models.image_profile)
    projected = job_projection(env.config, entry, job)
    if kind == "discretionary":  # FR-106c — the only spend the cap can still decline
        held = await env.budget.reserve(projected, label=label, category=SpendCategory.RENDER,
                                        asset_id=entry.asset_id)
        if held is None:
            env.log.warn("skipped_budget", f"{entry.asset_id}: {label} declined by the spend cap",
                         asset_id=entry.asset_id, projected_usd=projected)
            return None
    else:  # FR-106a/b — projected and pre-committed work is never refused here
        held = await env.budget.commit(projected, label=label, category=SpendCategory.RENDER,
                                       asset_id=entry.asset_id, kind=kind)
    token = _CURRENT_ASSET.set(entry.asset_id)
    try:
        outcome = await render.run(profile, params, refs, priority)
    except render.KieOutOfCredits:
        await env.budget.release(held)  # nothing was submitted, so nothing was billed
        raise
    except render.RenderError as exc:  # seam misuse or an unknown profile: no job ever left
        await env.budget.release(held)
        env.log.error("render_seam_error", f"{entry.asset_id}: {exc}", asset_id=entry.asset_id)
        return RenderOutcome(kind=RenderOutcomeKind.FAIL, fail_message=str(exc))
    finally:
        _CURRENT_ASSET.reset(token)
    await env.budget.reconcile(held, outcome.cost_usd if outcome.cost_usd else None)
    _OPEN_TASKS.pop(entry.asset_id, None)  # it reached a terminal state: nothing to abandon
    env.ledger.terminal(entry.asset_id, outcome.request_token or "", outcome.task_id,
                        outcome.fail_cause.value if outcome.fail_cause else outcome.kind.value)
    return outcome


# --------------------------------------------------------------------------- inputs


def _assemble(entry: PlanEntry, env: Env, attached: Sequence[Reference], *,
              copyset: CopySet | None = None, budget_scale: float = 1.0,
              extra: str = "") -> str | None:
    """The finished render prompt, or `None` when it cannot be filled (FR-17/94/96, FR-260)."""
    brief = env.brief_for(entry) if entry.variant == "analyzed" else None
    role = ROLE_ANALYZED if brief is not None else ROLE_DIRECT
    profile = render.get_profile(env.config.models.image_profile)
    context = build_context(
        trend=env.trends.get(entry.trend_key or ""),
        style_brief=brief,
        copy=copyset or env.copy.get(entry.asset_id),
        budget_scale=budget_scale,  # FR-105's −40% retry states the budget it actually carries
        # FR-144/145: `override` visual directives REPLACE render_prompt/layout_zones; `blend`
        # states the precedence — trend wins visuals, brief wins message and CTA.
        campaign_brief=env.campaign_briefs.get(entry.brief_name or ""),
        creative_format="image",
        niche_descriptor=env.niche_descriptor,
        niche_visual_world=env.niche_visual_world,  # A15: render-side art direction, `direct` too
        brand_accent=env.brand_accent,  # FR-109's only render-side brand influence, `full` only
        brand_product_nouns=env.brand_product_nouns,
        text_budgets=env.config.run.text_budgets,
        reference_roles=role_lines(attached),  # FR-191: one line per attachment, by provenance
        reference_image_count=len(attached),
    )
    if brief is not None and not attached:
        # FR-18/96: a reference-free job keeps its written style description AND gains the
        # deterministic content sentence — with no pixels, style alone renders nothing in
        # particular. (`image_single_post.md` has no content_sentence slot; this is the same
        # substitution `reel_seed_frame.md` makes, 50 §3.)
        context["render_prompt"] = f"{context['content_sentence']} {context['render_prompt']}".strip()
    try:
        prompt = env.engine.render(role, context, profile=profile.name,
                                   max_chars=profile.limits.max_prompt_chars)  # 50 §7
    except (UnresolvedPlaceholderError, MissingTemplateError, ValueError, LookupError) as exc:
        env.log.error("prompt_assembly_failed", f"{entry.asset_id}: {exc}",
                      asset_id=entry.asset_id, role=role)
        return None
    if extra:  # FR-193: the vision retry repeats the preserve list and adds one line
        prompt = f"{prompt}\n\n{extra}"
    env.log.event("render_prompt_assembled", f"{entry.asset_id} prompt ready", verbose_only=True,
                  asset_id=entry.asset_id, role=role, references=len(attached), prompt=prompt)
    return prompt


def _record(entry: PlanEntry, env: Env) -> AssetRecord:
    """The `pending` meta.yaml this creative starts life with — FR-73 field for field."""
    trend = env.trends.get(entry.trend_key or "")
    copyset = env.copy.get(entry.asset_id)
    brief = env.brief_for(entry)
    degradations: list[DegradationTag] = []
    if entry.variant == "analyzed" and brief is None:
        # FR-12: renders direct-mode instead. Decided on the SAME (trend, group) pair `_assemble`
        # renders with — a trend-level check would leave a creative whose own pair's call failed
        # silently unmarked whenever any sibling group's call succeeded.
        degradations.append(DegradationTag.ANALYSIS_MISSING)
    degradations.extend(env.copy_tags.get(entry.asset_id, ()))
    return AssetRecord(
        asset_id=entry.asset_id,
        source=entry.trend_key or (f"brief/{entry.brief_name}" if entry.brief_name else "none"),
        source_name=trend.name if trend else (entry.brief_name or ""),
        platform=entry.platform,
        creative_format=entry.creative_format,
        variant=entry.variant,
        pair_id=entry.pair_id,
        generation_mode=entry.variant,
        hook_pattern_used=copyset.hook_pattern_used if copyset else "",
        source_hook=next((hook for hook in (trend.hook_texts if trend else ()) if hook), ""),
        style_brief_summary=style_brief_line(brief),  # A24: what the brief asked for, in one line
        ref_source=_ref_source(entry, env, trend),
        degradations=degradations,
        brief_name=entry.brief_name,
        brief_influence_mode=entry.brief_influence,
        aspect_ratio_requested=entry.aspect_ratio,
        estimated_cost_usd=round(entry.estimated_cost_usd, 6),
        slide_count=entry.slide_count,
        virlo_url=trend.virlo_url if trend else None,
    )


# --------------------------------------------------------------------------- small helpers


def _ref_source(entry: PlanEntry, env: Env, trend: TrendItem | None) -> str:
    """FR-73's honest provenance: what this job's references actually came FROM.

    Under `inspiration_mix: exclusive` the trend keeps its metadata but `sources.apply_mix()` has
    already emptied its reference groups, so "virlo" would be a lie — the pictures are the pool's.
    """
    kinds = {kind for _, kind in env.local_refs.get(entry.asset_id, ())}
    if trend is not None and trend.reference_groups:
        return "virlo"
    if "inspiration" in kinds:
        return "inspiration"
    return "brief" if entry.brief_name else ""


def _abandon(entry: PlanEntry, env: Env, folder: AssetFolder) -> AssetRecord:
    """FR-108/201/203: terminal folder, `abandoned` status, one ledger line naming the taskId.

    The job itself is neither cancelled at Kie nor resubmitted — it was billed at submission and
    may still complete unclaimed. Saying so, with the id, is the whole point of the ledger.
    """
    task_id = _OPEN_TASKS.pop(entry.asset_id, None)
    reason = (f"abandoned after the {GRACE_S:.0f}s grace window (job {task_id or 'unknown'}) — "
              "it was billed at submission and may still complete unclaimed at Kie (FR-108/203)")
    entry.status = PlanEntryStatus.ABANDONED
    entry.skip_reason = entry.skip_reason or reason
    env.ledger.terminal(entry.asset_id, "", task_id, "abandoned")
    # FR-73: `event_id` points at the line that explains this asset — never null on a terminal.
    event_id = env.log.warn("abandoned", f"{entry.asset_id}: {reason}", asset_id=entry.asset_id,
                            task_id=task_id or "")
    return folder.skip(reason, DegradationTag.ABANDONED, event_id=event_id)


def _fail(entry: PlanEntry, env: Env, folder: AssetFolder, reason: str,
          tag: DegradationTag | None = None, *, cost: float = 0.0,
          outcome: RenderOutcome | None = None) -> AssetRecord:
    """Terminal failure that keeps its paid artifacts (FR-74) and stays in the plan (FR-4)."""
    if entry.status is PlanEntryStatus.PENDING:
        entry.status = PlanEntryStatus.FAILED
    entry.skip_reason = entry.skip_reason or reason
    extra: dict[str, Any] = {  # FR-73: the run-log line this meta.yaml points back at
        "actual_cost_usd": round(cost, 6),
        "event_id": env.log.error("creative_failed", f"{entry.asset_id}: {reason}",
                                  asset_id=entry.asset_id, cost_usd=round(cost, 6)),
    }
    if outcome is not None:
        extra["kie_job_ids"] = [outcome.task_id] if outcome.task_id else []
        extra["job_submission_timestamp"] = outcome.submitted_at
        extra["job_completion_timestamp"] = outcome.completed_at
    return folder.skip(reason, tag, **extra)


__all__ = ["Env", "GRACE_S", "Report", "ROLE_ANALYZED", "ROLE_DIRECT", "create", "ledger_hooks"]
