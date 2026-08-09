"""CREATE — plan entries in, finished asset folders out. **Wave 3 scope: wave-1 images.**

Module contract
---------------
Purpose: own everything between "this creative was approved" and "this creative is on disk" —
prompt assembly, reference attachment, the money reservation around each submission, the
moderation fallback, and packaging. The runner hands over entries and gets back records; it
never touches a template, a reference URL, a render body or a meta.yaml key.

Public API: `create(entries, env)` · `Env` · `Report` · `ledger_hooks(ledger)`.

Invariants:
- **Money is reserved before a job is submitted and reconciled to the provider's own figure**
  afterwards (FR-106). Wave-1 renders `commit()` (already inside the approved projection);
  FR-97's moderation retry is the discretionary tail and `reserve()`s — a `None` there means the
  cap declined it and the creative is a logged `skipped_budget`, never an unbudgeted submission.
- **Spend tallies on submission, failures included** — a reservation that reached the provider is
  reconciled, never released; only a submission that never happened is released (20 §8).
- **A folder never holds media without meta** — `AssetFolder` writes `pending` meta at creation
  and rewrites it terminally, so every exit path (success, skip, interrupt) leaves one whole
  state (NFR-21). A failed creative keeps its paid caption (FR-74).
- **References are the FR-91 coherent set already built by `sources/virlo.py`** — one group, one
  source, panels preferred, capped by `reference_images_per_job`. This module attaches them, it
  does not re-select them. Local files (Inspiration, brief images) go through
  `render.upload_file()` first (FR-200) and a failed upload drops that one reference, never the
  job.
- **An unresolved placeholder fails the creative BEFORE submission** (FR-260) — nothing malformed
  is ever paid for.
- **Kie's 402 is a whole-run condition** (FR-167): it is latched once and every remaining
  creative is skipped with "top up your Kie.ai credits" rather than each retrying a certainty.

W4 extension seam (plan §2 T4.3): `create()` submits one wave. The two-wave engine, the carousel
anchor chain, the reel seed-frame chain and the vision-check wiring hang off `_render_creative()`
and the `RenderPriority` argument — carousels and reels are packaged here today as honest logged
skips rather than half-built folders.

Do not: call Kie directly, name a Kie field, spell an asset path, or re-derive a price.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hypesocials import render
from hypesocials.budget import Budget, SpendCategory
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

#: Which template role an image creative uses. `analyzed` without a style brief is FR-12's
#: degrade: it runs the direct scaffold and carries `analysis_missing`.
ROLE_ANALYZED = "image_single_post.md"
ROLE_DIRECT = "image_direct.md"

#: Set for the duration of one creative's submission so the FR-203 ledger hooks — which the
#: render seam calls with a request token and nothing else — can name the asset the token bought.
_CURRENT_ASSET: ContextVar[str] = ContextVar("_hypesocials_current_asset", default="")


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
    stop: asyncio.Event | None = None  # Ctrl+C / deadline: stop ORDERING new work (FR-201/108)
    credits_exhausted: bool = False  # FR-167, latched once


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

    def on_intent(request_token: str) -> None:
        ledger.intent(_CURRENT_ASSET.get() or "unknown", request_token)

    def on_submitted(request_token: str, task_id: str | None) -> None:
        ledger.submitted(_CURRENT_ASSET.get() or "unknown", request_token, task_id)

    return on_intent, on_submitted


async def create(entries: Sequence[PlanEntry], env: Env) -> Report:
    """Build every approved creative concurrently and package the rest honestly.

    Concurrency is bounded inside `render.run()` by the permit gate, so every entry starts at
    once and the gate decides how many jobs are actually in flight (FR-25). Nothing raised by one
    creative can reach another: each returns a terminal record.
    """
    report = Report()
    if not entries:
        return report
    for record in await asyncio.gather(*(_one(entry, env, report) for entry in entries)):
        report.records[record.asset_id] = record
    return report


# --------------------------------------------------------------------------- one creative


async def _one(entry: PlanEntry, env: Env, report: Report) -> AssetRecord:
    """One plan entry, from folder creation to terminal meta. Never raises."""
    folder = AssetFolder(env.run_dir, _record(entry, env))
    copyset = env.copy.get(entry.asset_id)
    if copyset is not None:
        try:  # the copy was already paid for; a failed write must not cost the whole creative
            folder.write_caption(copyset.caption, copyset.hashtags)
        except PackagingError as exc:
            env.log.error("caption_write_failed", f"{entry.asset_id}: {exc}",
                          asset_id=entry.asset_id)

    if entry.status is PlanEntryStatus.SKIPPED_BUDGET:
        return folder.skip(entry.skip_reason or "trimmed to fit the spend cap (FR-28/FR-106)",
                           DegradationTag.SKIPPED_BUDGET)
    if entry.status is not PlanEntryStatus.PENDING:
        return folder.skip(entry.skip_reason or f"not generated ({entry.status.value})")
    if entry.creative_format != "image":
        env.log.warn("format_not_built",
                     f"{entry.asset_id}: {entry.creative_format} generation lands in Wave 4",
                     asset_id=entry.asset_id, creative_format=entry.creative_format)
        entry.status = PlanEntryStatus.SKIPPED
        entry.skip_reason = "format_not_built_yet"
        return folder.skip(f"{entry.creative_format}_generation_lands_in_wave_4 (plan §2 T4.1/T4.2)")
    if env.credits_exhausted:
        return _fail(entry, folder, "kie_credits_exhausted — top up your Kie.ai credits (FR-167)")
    if env.stop is not None and env.stop.is_set():
        entry.status = PlanEntryStatus.ABANDONED
        entry.skip_reason = "interrupted_before_submission"
        return folder.skip("interrupted before submission — nothing was ordered for this creative",
                           DegradationTag.ABANDONED)

    urls = await _reference_urls(entry, env, folder)
    prompt = _assemble(entry, env, urls)
    if prompt is None:
        return _fail(entry, folder, "prompt_assembly_failed — unresolved placeholder (FR-260)")
    return await _render_creative(entry, env, folder, prompt, urls, report)


async def _render_creative(
    entry: PlanEntry, env: Env, folder: AssetFolder, prompt: str,
    urls: list[str], report: Report,
) -> AssetRecord:
    """Submit, reconcile, apply FR-97's single moderation retry, then package the bytes."""
    profile_name = env.config.models.image_profile
    params = RenderParams(prompt=prompt, aspect_ratio=entry.aspect_ratio)
    token = _CURRENT_ASSET.set(entry.asset_id)
    try:
        outcome = await _submit(entry, env, profile_name, params, RenderRefs(image_urls=urls))
        if outcome is None:
            return _fail(entry, folder, "skipped_budget — the cap declined this submission",
                         DegradationTag.SKIPPED_BUDGET)
        if outcome.kind is not RenderOutcomeKind.SUCCESS and \
                outcome.fail_cause is RenderFailCause.MODERATION and urls:
            env.log.warn("moderation_retry",
                         f"{entry.asset_id}: content-policy refusal; one reference-free retry (FR-97)",
                         asset_id=entry.asset_id, detail=outcome.fail_message)
            # The refused job was billed on submission, so its own terminal line lands before the
            # retry's — the ledger must show both taskIds, not only the one that survived (FR-203).
            env.ledger.terminal(entry.asset_id, outcome.request_token or "", outcome.task_id,
                                RenderFailCause.MODERATION.value)
            retry = await _submit(entry, env, profile_name, params, RenderRefs(), discretionary=True)
            if retry is not None:
                folder.mark(DegradationTag.REFS_DROPPED_MODERATION)
                outcome = retry
    except render.KieOutOfCredits as exc:
        env.credits_exhausted = True
        return _fail(entry, folder, f"kie_credits_exhausted — top up your Kie.ai credits ({exc})")
    finally:
        _CURRENT_ASSET.reset(token)

    env.ledger.terminal(entry.asset_id, outcome.request_token or "", outcome.task_id,
                        outcome.kind.value)
    if outcome.kind is not RenderOutcomeKind.SUCCESS or not outcome.result_urls:
        # FR-242: a `success` with no usable result is a failure that lies — treated as a failure.
        cause = (outcome.fail_cause.value if outcome.fail_cause else outcome.kind.value)
        env.log.error("render_failed", f"{entry.asset_id}: {cause} — "
                      f"{outcome.fail_message or 'no usable result'}", asset_id=entry.asset_id,
                      task_id=outcome.task_id, cost_usd=round(outcome.cost_usd, 6))
        return _fail(entry, folder, f"{cause}: {outcome.fail_message or 'no usable result'}"
                     f" (job {outcome.task_id or 'unknown'})", cost=outcome.cost_usd,
                     outcome=outcome)

    try:  # the bytes stop being a borrowed 24 h URL and become the operator's file
        await folder.store_render(outcome.result_urls[0])
    except PackagingError as exc:
        report.disk_full = report.disk_full or exc.reason == "disk_full"
        return _fail(entry, folder, f"{exc.reason}: {exc}", cost=outcome.cost_usd, outcome=outcome)

    entry.status = PlanEntryStatus.SUCCESS
    if entry.trend_key:
        report.packaged_trends.add(entry.trend_key)
    return folder.finish(
        actual_cost_usd=round(outcome.cost_usd, 6),
        model_ids=[env.config.models.image, profile_name],
        kie_job_ids=[outcome.task_id] if outcome.task_id else [],
        job_submission_timestamp=outcome.submitted_at,
        job_completion_timestamp=outcome.completed_at,
        native_size_rendered=entry.aspect_ratio,  # FR-98: shipped exactly as it came back
        event_id=env.log.event("creative_delivered", f"{entry.asset_id} rendered",
                               asset_id=entry.asset_id, task_id=outcome.task_id,
                               cost_usd=round(outcome.cost_usd, 6),
                               duration_ms=int(outcome.elapsed_s * 1000)))


async def _submit(
    entry: PlanEntry, env: Env, profile: str, params: RenderParams, refs: RenderRefs,
    *, discretionary: bool = False,
) -> RenderOutcome | None:
    """One reserved submission. `None` means the cap declined a discretionary retry (FR-106c)."""
    projected = max(entry.estimated_cost_usd, 0.0)
    label = f"{'moderation retry' if discretionary else 'image render'} · {entry.asset_id}"
    if discretionary:
        held = await env.budget.reserve(projected, label=label, category=SpendCategory.RENDER,
                                        asset_id=entry.asset_id)
        if held is None:
            env.log.warn("skipped_budget", f"{entry.asset_id}: {label} declined by the spend cap",
                         asset_id=entry.asset_id, projected_usd=projected)
            return None
    else:
        held = await env.budget.commit(projected, label=label, category=SpendCategory.RENDER,
                                       asset_id=entry.asset_id, kind="projected")
    try:
        outcome = await render.run(profile, params, refs, RenderPriority.WAVE1)
    except render.KieOutOfCredits:
        await env.budget.release(held)  # nothing was submitted, so nothing was billed
        raise
    except render.RenderError as exc:
        await env.budget.release(held)
        env.log.error("render_seam_error", f"{entry.asset_id}: {exc}", asset_id=entry.asset_id)
        return RenderOutcome(kind=RenderOutcomeKind.FAIL, fail_message=str(exc))
    # Tally on submission: a job that reached the provider is billed even when it then fails.
    await env.budget.reconcile(held, outcome.cost_usd if outcome.cost_usd else None)
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


__all__ = ["Env", "Report", "ROLE_ANALYZED", "ROLE_DIRECT", "create", "ledger_hooks"]
