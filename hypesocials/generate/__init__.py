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
  does not re-select them. Local files (Inspiration, brief images) go through
  `render.upload_file()` first (FR-200) and a failed upload drops that one reference, never the
  job.
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

from hypesocials import render
from hypesocials.budget import Budget, SpendCategory, job_projection
from hypesocials.config import Config
from hypesocials.models import (
    AssetRecord,
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
)
from hypesocials.outputs import AssetFolder, Ledger, LogWriter, PackagingError
from hypesocials.prompts_engine import (
    MissingTemplateError,
    PromptEngine,
    UnresolvedPlaceholderError,
    build_context,
)
from hypesocials.util import Deadline

# Both format modules back-import this package under TYPE_CHECKING only, so importing them here
# is safe and keeps the dispatch a plain name lookup (which is also what makes it fakeable).
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
    copy_degraded: frozenset[str] = frozenset()
    copy_trimmed: frozenset[str] = frozenset()
    local_refs: Mapping[str, Sequence[Path]] = field(default_factory=dict)  # FR-200 upload path
    niche_descriptor: str = ""
    llm_call: Any = None  # metered `StructuredCall` for the FR-27 vision check; None = off
    video_refs: Any = None  # `video_ref.Prefetch` for the D23 motion reference, or None
    stop: asyncio.Event | None = None  # Ctrl+C: stop ORDERING new work (FR-201)
    deadline: Deadline | None = None  # the run's soft monotonic ceiling (FR-108/243)
    credits_exhausted: bool = False  # FR-167, latched once
    disk_full: bool = False  # 10 §10, latched once: further downloads stop run-wide

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
    while pending and not env.halted:
        _, pending = await asyncio.wait(pending, timeout=_HALT_POLL_S)
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
        return _fail(entry, folder, _CREDITS)
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
    """One standalone image: assemble, submit, apply FR-97's single retry, package the bytes."""
    urls = await _reference_urls(entry, env, folder)
    prompt = _assemble(entry, env, urls)
    if prompt is None:
        return _fail(entry, folder, "prompt_assembly_failed — unresolved placeholder (FR-260)")
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
        return _fail(entry, folder, f"{_CREDITS} ({exc})")
    if outcome is None:
        return _fail(entry, folder, "skipped_budget — the cap declined this submission",
                     DegradationTag.SKIPPED_BUDGET)
    if outcome.kind is not RenderOutcomeKind.SUCCESS or not outcome.result_urls:
        # FR-242: a `success` with no usable result is a failure that lies — treated as a failure.
        cause = (outcome.fail_cause.value if outcome.fail_cause else outcome.kind.value)
        env.log.error("render_failed", f"{entry.asset_id}: {cause} — "
                      f"{outcome.fail_message or 'no usable result'}", asset_id=entry.asset_id,
                      task_id=outcome.task_id, cost_usd=round(outcome.cost_usd, 6))
        return _fail(entry, folder, f"{cause}: {outcome.fail_message or 'no usable result'}"
                     f" (job {outcome.task_id or 'unknown'})", cost=outcome.cost_usd,
                     outcome=outcome)
    if env.disk_full:  # 10 §10: downloads stopped run-wide rather than thrash a full disk
        return _fail(entry, folder, "disk_full: downloads stopped for this run",
                     cost=outcome.cost_usd, outcome=outcome)
    try:  # the bytes stop being a borrowed 24 h URL and become the operator's file
        await folder.store_render(outcome.result_urls[0])
    except PackagingError as exc:
        if exc.reason == "disk_full":  # the one failure that outlives this creative
            env.disk_full = True
        return _fail(entry, folder, f"{exc.reason}: {exc}", cost=outcome.cost_usd, outcome=outcome)

    entry.status = PlanEntryStatus.SUCCESS
    return folder.finish(
        actual_cost_usd=round(outcome.cost_usd, 6),
        model_ids=[env.config.models.image, env.config.models.image_profile],
        kie_job_ids=[outcome.task_id] if outcome.task_id else [],
        job_submission_timestamp=outcome.submitted_at,
        job_completion_timestamp=outcome.completed_at,
        native_size_rendered=entry.aspect_ratio,  # FR-98: shipped exactly as it came back
        event_id=env.log.event("creative_delivered", f"{entry.asset_id} rendered",
                               asset_id=entry.asset_id, task_id=outcome.task_id,
                               cost_usd=round(outcome.cost_usd, 6),
                               duration_ms=int(outcome.elapsed_s * 1000)))


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


async def _reference_urls(entry: PlanEntry, env: Env, folder: AssetFolder) -> list[str]:
    """The FR-91 coherent set as public URLs, with FR-200's upload for anything local.

    Virlo CDN URLs are passed straight through (RESULTS.md §B: Kie accepts them, webp included).
    Local files — Inspiration images, a brief's own references — become URLs through the render
    seam's upload op; a per-file failure drops that reference by name and the job proceeds with
    whatever survived, because a curated picture is an input, not a prerequisite.
    """
    trend = env.trends.get(entry.trend_key or "")
    urls = list(trend.reference_groups[0]) if trend and trend.reference_groups else []
    for path in env.local_refs.get(entry.asset_id, ()):  # W3: empty; W5 briefs/inspiration fill it
        try:
            urls.append(await render.upload_file(path))
        except Exception as exc:  # noqa: BLE001 - any upload failure degrades to "one fewer ref"
            env.log.warn("reference_upload_failed",
                         f"{entry.asset_id}: {Path(path).name} could not be uploaded ({exc}); "
                         "the job proceeds with its remaining references (FR-200)",
                         asset_id=entry.asset_id, reference=Path(path).name)
    limit = render.get_profile(env.config.models.image_profile).limits.max_image_urls
    if not urls:
        folder.mark(DegradationTag.REFERENCE_FREE)
    return urls[:limit] if limit else urls


def _assemble(entry: PlanEntry, env: Env, urls: Sequence[str]) -> str | None:
    """The finished render prompt, or `None` when it cannot be filled (FR-17/94/96, FR-260)."""
    brief = env.style_briefs.get(entry.trend_key or "") if entry.variant == "analyzed" else None
    role = ROLE_ANALYZED if brief is not None else ROLE_DIRECT
    # FR-191/91: one line per attachment saying what it contributes and what it never does — the
    # RESULTS.md §B defence against GPT Image 2 cloning a reference's wordmark.
    roles = [f"Image {index}: trend reference — layout, palette, typography and treatment only; "
             "no words, no logo, no chrome, no person's identity"
             for index, _ in enumerate(urls, start=1)]
    context = build_context(
        trend=env.trends.get(entry.trend_key or ""),
        style_brief=brief,
        copy=env.copy.get(entry.asset_id),
        creative_format="image",
        niche_descriptor=env.niche_descriptor,
        text_budgets=env.config.run.text_budgets,
        reference_roles=roles,
        reference_image_count=len(urls),
    )
    try:
        prompt = env.engine.render(role, context, profile=env.config.models.image_profile)
    except (UnresolvedPlaceholderError, MissingTemplateError, ValueError, LookupError) as exc:
        env.log.error("prompt_assembly_failed", f"{entry.asset_id}: {exc}",
                      asset_id=entry.asset_id, role=role)
        return None
    env.log.event("render_prompt_assembled", f"{entry.asset_id} prompt ready", verbose_only=True,
                  asset_id=entry.asset_id, role=role, references=len(urls), prompt=prompt)
    return prompt


def _record(entry: PlanEntry, env: Env) -> AssetRecord:
    """The `pending` meta.yaml this creative starts life with — FR-73 field for field."""
    trend = env.trends.get(entry.trend_key or "")
    copyset = env.copy.get(entry.asset_id)
    degradations: list[DegradationTag] = []
    if entry.variant == "analyzed" and entry.trend_key not in env.style_briefs:
        degradations.append(DegradationTag.ANALYSIS_MISSING)  # FR-12: renders direct-mode instead
    if entry.asset_id in env.copy_degraded:
        degradations.append(DegradationTag.COPY_DEGRADED)
    if entry.asset_id in env.copy_trimmed:
        degradations.append(DegradationTag.TEXT_TRIMMED)
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
        ref_source="virlo" if trend else ("brief" if entry.brief_name else ""),
        degradations=degradations,
        brief_name=entry.brief_name,
        brief_influence_mode=entry.brief_influence,
        aspect_ratio_requested=entry.aspect_ratio,
        estimated_cost_usd=round(entry.estimated_cost_usd, 6),
        slide_count=entry.slide_count,
        virlo_url=trend.virlo_url if trend else None,
    )


# --------------------------------------------------------------------------- small helpers


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
    env.log.warn("abandoned", f"{entry.asset_id}: {reason}", asset_id=entry.asset_id,
                 task_id=task_id or "")
    return folder.skip(reason, DegradationTag.ABANDONED)


def _fail(entry: PlanEntry, folder: AssetFolder, reason: str,
          tag: DegradationTag | None = None, *, cost: float = 0.0,
          outcome: RenderOutcome | None = None) -> AssetRecord:
    """Terminal failure that keeps its paid artifacts (FR-74) and stays in the plan (FR-4)."""
    if entry.status is PlanEntryStatus.PENDING:
        entry.status = PlanEntryStatus.FAILED
    entry.skip_reason = entry.skip_reason or reason
    extra: dict[str, Any] = {"actual_cost_usd": round(cost, 6)}
    if outcome is not None:
        extra["kie_job_ids"] = [outcome.task_id] if outcome.task_id else []
        extra["job_submission_timestamp"] = outcome.submitted_at
        extra["job_completion_timestamp"] = outcome.completed_at
    return folder.skip(reason, tag, **extra)


__all__ = ["Env", "GRACE_S", "Report", "ROLE_ANALYZED", "ROLE_DIRECT", "create", "ledger_hooks"]
