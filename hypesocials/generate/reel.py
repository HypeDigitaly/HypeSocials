"""Reels — the seed-frame chain, the motion reference, and one Seedance clip (FR-23/24/141/142).

Module contract
---------------
Purpose: turn one approved reel plan entry into a packaged `reel.mp4`, plus the paid
`seed_frame.jpg` the gallery uses as its poster (FR-72/76). This module owns the CHAIN — its
order, its checks and its degrades. It owns no money, no profile choice and no ledger line: the
injected `submit` does all three (FR-106 a/b/c, FR-203).

Public API: `await render_reel(entry, env, folder, submit=...) -> AssetRecord`.

Invariants enforced here, once:
- **A reel is delivered or honestly skipped, never half-built.** Losing the seed frame costs
  legibility, not a clip (FR-24): `seed_frame_render_failed` (never rendered) and
  `seed_frame_url_unreachable` (rendered, then rejected at Seedance submission) both degrade to
  `in_model` overlay text, KEEP the motion reference, and still count as delivered.
- **The seed frame is checked BEFORE the clip is submitted (FR-105).** A re-render has to replace
  the frame the video is built from, not arrive after the clip is paid for. A successful re-render
  is checked once more — the estimator's `vision_retry_allowance` prices that pair, "render +
  re-check" — so FR-27's `retried_passed` is genuinely reachable; a declined or failed re-render
  is `retried_failed` and is never re-checked. The finished CLIP is never checked at all: frame
  extraction would mean ffmpeg, which this project does not carry (D10).
- **The motion reference is an upgrade, never a dependency (FR-142).** Any chain failure marks its
  own tag and the clip goes out seed-frame-only.
- **A content-security audit failure is not a moderation refusal (FR-141, v1.6.6).** Its remedy is
  silencing the clip, never stripping references — one retry with `generate_audio: false` plus the
  explicit silent-clip clause, same references, the failed attempt billed $0 (RESULTS.md §C).
- **One retry per class (NFR-4).** Four separate single retries live here and none of them stacks:
  the seed frame's moderation retry (FR-97), its vision-check re-render (FR-105), the clip's
  content-audit silent retry, and the clip's seed-URL-rejected resubmission.
- **9:16 always.** A reel's seed frame inherits the reel's ratio, never the platform's image ratio
  (FR-21), and the clip passes 9:16 explicitly — the provider's `adaptive` is never used.

Do not: call `render.run`, price anything, touch `env.budget` / `env.ledger`, vision-check the
finished clip, trim a reference video, or re-upload the Kie-hosted seed frame (D18: it is a URL
already, so the chain has no upload step and no local file handling).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hypesocials import render, vision_check
from hypesocials.models import (
    AssetRecord, CopySet, DegradationTag, PlanEntry, PlanEntryStatus, RenderFailCause,
    RenderOutcome, RenderOutcomeKind, RenderParams, RenderPriority, RenderRefs, VisionCheckResult,
)
from hypesocials.outputs import AssetFolder, PackagingError, save_reference
from hypesocials.generate.refs import Reference, attach, role_lines
from hypesocials.prompts_engine import (
    MissingTemplateError, UnresolvedPlaceholderError, build_context,
)

if TYPE_CHECKING:  # never at runtime — `generate/__init__.py` imports this module (circular)
    from hypesocials.generate import Env

SEED_TEMPLATE = "reel_seed_frame.md"
CLIP_TEMPLATE = "reel_director.md"
#: FR-21 — the ratio belongs to the FORMAT, so the seed frame inherits it too.
ASPECT_9_16 = "9:16"
#: FR-142's "short bounded wait": the chain started at Analyze and the seed frame has since been
#: rendered and checked, so anything still unfinished is slow, not merely late — and waiting longer
#: would put the reel's own critical path behind an upgrade it is allowed to ship without.
VIDEO_REF_WAIT_S = 20.0
#: RESULTS.md §C, verbatim: the clause that turned a content-audit failure into a $2.85 success.
SILENT_CLIP_CLAUSE = (
    "Silent clip — no music, no song, no melody, no vocals, no soundtrack of any kind."
)
#: The whole AUDIO body of the director prompt (50 §4 bracket taxonomy: `( )` and `< >` only).
_AUDIO_CUE = ("(music or ambience matched to the trend's vibe — instrumental, no lyrics)\n"
              "  <at most one short sound effect, on the clip's main action>")
_SEED_REF_LINE = ("It is the 9:16 still hook frame rendered for this reel, with the hook text "
                  "already burnt into the picture.")
_IN_MODEL_REF_LINE = ("No seed frame is attached to this job. Render the hook text below yourself "
                      "as one static graphic layer in the upper third, and hold it fixed, legible "
                      "and unchanged for the whole clip.")
_CLEAN_CLIP_REF_LINE = ("No seed frame is attached to this job, and this clip carries no on-screen "
                        "text at all: open on the scene described below and keep every frame free "
                        "of lettering.")
#: A task-creation / reference-validation failure whose message implicates the seed-frame URL
#: (20 §10 `seed_frame_url_unreachable`). Deliberately narrow: an unmatched message is an ordinary
#: failed render, and one wrong resubmission costs a whole clip.
_SEED_URL_HINTS = ("reference", "input url", "image url", "invalid url", "unreachable",
                   "not accessible", "download", "fetch", "expired", "404")


@dataclass(slots=True)
class _Spend:
    """What the chain bought, accumulated across every submission incl. the failed audit attempt."""

    cost: float = 0.0
    job_ids: list[str] = field(default_factory=list)
    submitted_at: str | None = None
    completed_at: str | None = None

    def add(self, outcome: RenderOutcome | None) -> RenderOutcome | None:
        if outcome is not None:
            self.cost += outcome.cost_usd
            if outcome.task_id:
                self.job_ids.append(outcome.task_id)
            self.submitted_at = self.submitted_at or outcome.submitted_at
            self.completed_at = outcome.completed_at or self.completed_at
        return outcome

    def meta(self) -> dict[str, Any]:
        """The FR-73 cost/timing block, whatever the chain's ending was."""
        return {"actual_cost_usd": round(self.cost, 6), "kie_job_ids": list(self.job_ids),
                "job_submission_timestamp": self.submitted_at,
                "job_completion_timestamp": self.completed_at}


async def render_reel(
    entry: PlanEntry, env: Env, folder: AssetFolder, *, submit: Any
) -> AssetRecord:
    """Generate one reel end to end and return its terminal record. Never raises.

    `entry` is an approved reel plan entry and `folder` its already-created asset folder (pending
    meta and caption written). `env` supplies config, prompt engine, log, trend material, plus the
    optional `llm_call` (vision check) and `video_refs` (the D23 prefetch). `submit` is the wave
    engine's money-owning submitter: it picks the profile from `job`, reserves and reconciles,
    writes the FR-203 ledger lines, and returns `None` only when the cap declined a discretionary
    submission.
    """
    spend = _Spend()
    try:
        return await _chain(entry, env, folder, submit, spend)
    except render.KieOutOfCredits as exc:
        env.credits_exhausted = True  # FR-167: latched once, every later creative skips
        return _skip(entry, folder, spend,
                     f"kie_credits_exhausted — top up your Kie.ai credits ({exc})")
    except Exception as exc:  # noqa: BLE001 — one creative may never take the batch down (10 §10)
        env.log.error("reel_chain_error", f"{entry.asset_id}: {type(exc).__name__}: {exc}",
                      asset_id=entry.asset_id)
        return _skip(entry, folder, spend, f"reel_chain_error: {type(exc).__name__}: {exc}")


async def _chain(
    entry: PlanEntry, env: Env, folder: AssetFolder, submit: Any, spend: _Spend
) -> AssetRecord:
    """Seed frame → check → motion reference → clip, with each degrade scoped to its own step."""
    run = env.config.run
    copyset = env.copy.get(entry.asset_id)
    seed_url: str | None = None
    verdict = VisionCheckResult.NOT_CHECKED
    mode = run.reel_overlay_text
    if mode == "seed_frame":  # `in_model` / `none` skip the chain entirely (FR-24)
        seed_url, verdict = await _seed_frame(entry, env, folder, submit, spend, copyset)
        mode = "seed_frame" if seed_url else "in_model"  # FR-24's degrade, either failure shape
    seed_rendered = seed_url is not None  # paid for, so it stays in `model_ids` even if dropped

    video_url = await _motion_reference(entry, env, folder)
    audio_on = bool(run.reel_audio)
    outcome = await _submit_clip(entry, env, submit, spend, copyset, seed_url=seed_url,
                                 video_url=video_url, audio_on=audio_on, mode=mode)

    if outcome is not None and outcome.fail_cause is RenderFailCause.CONTENT_AUDIT and audio_on:
        # FR-141 v1.6.6: silence the clip, KEEP every reference — the failed attempt cost $0.
        env.log.warn("content_audit_retry",
                     f"{entry.asset_id}: content-security audit failed the clip; one retry with "
                     "generate_audio=false and the silent-clip clause, references kept (FR-141)",
                     asset_id=entry.asset_id, detail=outcome.fail_message)
        audio_on = False
        folder.mark(DegradationTag.AUDIO_DROPPED_CONTENT_AUDIT)
        outcome = await _submit_clip(entry, env, submit, spend, copyset, seed_url=seed_url,
                                     video_url=video_url, audio_on=False, mode=mode,
                                     extra=SILENT_CLIP_CLAUSE)

    if outcome is not None and seed_url and _seed_url_rejected(outcome):
        # FR-24's second failure: the frame rendered and was paid for; the handoff is what broke.
        # 10 §10 requires the clip to still be generated and delivered, so this resubmission
        # stays — but as DISCRETIONARY work (FR-106c): a second full Seedance clip is not in the
        # wave-1 projection the operator approved, so the cap may refuse it (20 §8, CLAUDE.md #7).
        env.log.warn("seed_frame_url_unreachable",
                     f"{entry.asset_id}: Seedance rejected the seed-frame reference "
                     f"({outcome.fail_message}); one resubmission with in-model overlay text",
                     asset_id=entry.asset_id)
        folder.mark(DegradationTag.SEED_FRAME_URL_UNREACHABLE)
        seed_url = None
        retry = await _submit_clip(entry, env, submit, spend, copyset, seed_url=None,
                                   video_url=video_url, audio_on=audio_on, mode="in_model",
                                   kind="discretionary")
        # Nothing re-ordered: an interrupt still packages as abandoned, a cap refusal keeps the
        # rejection this reel already paid for as its honest terminal reason.
        outcome = retry or (None if env.halted else outcome)

    if outcome is None:  # nothing was ordered: Ctrl+C / deadline, or a prompt that would not fill
        if not env.halted:
            return _skip(entry, folder, spend,
                         "prompt_assembly_failed — unresolved placeholder (FR-260)")
        entry.status = PlanEntryStatus.ABANDONED
        return _skip(entry, folder, spend, "interrupted before the video job was ordered — "
                     "everything already paid for is packaged (FR-201/108)",
                     DegradationTag.ABANDONED, reel_audio=audio_on, vision_check_result=verdict,
                     reel_video_reference_url=video_url)
    if outcome.kind is not RenderOutcomeKind.SUCCESS or not outcome.result_urls:
        cause = outcome.fail_cause.value if outcome.fail_cause else outcome.kind.value
        env.log.error("render_failed",
                      f"{entry.asset_id}: {cause} — {outcome.fail_message or 'no usable result'}",
                      asset_id=entry.asset_id, task_id=outcome.task_id)
        return _skip(entry, folder, spend,
                     f"{cause}: {outcome.fail_message or 'no usable result'} "
                     f"(job {outcome.task_id or 'unknown'})", reel_audio=audio_on,
                     vision_check_result=verdict, reel_video_reference_url=video_url)
    try:
        await folder.store_render(outcome.result_urls[0])  # -> reel.mp4 (FR-72)
    except PackagingError as exc:
        _latch_disk_full(env, exc)
        return _skip(entry, folder, spend, f"{exc.reason}: {exc}", reel_audio=audio_on,
                     vision_check_result=verdict, reel_video_reference_url=video_url)

    entry.status = PlanEntryStatus.SUCCESS
    models = env.config.models
    return folder.finish(
        model_ids=([models.image, models.image_profile] if seed_rendered else [])
        + [models.video, models.video_profile],
        native_size_rendered=ASPECT_9_16,  # FR-98: shipped exactly as it came back
        vision_check_result=verdict,
        reel_audio=audio_on,  # the FINAL truth, after any content-audit degrade
        reel_video_reference_url=video_url,
        event_id=env.log.event("creative_delivered", f"{entry.asset_id} reel rendered",
                               asset_id=entry.asset_id, task_id=outcome.task_id,
                               cost_usd=round(spend.cost, 6), reel_audio=audio_on,
                               video_reference=bool(video_url)),
        **spend.meta())


# --------------------------------------------------------------------------- the seed-frame chain


async def _seed_frame(
    entry: PlanEntry, env: Env, folder: AssetFolder, submit: Any, spend: _Spend,
    copyset: CopySet | None,
) -> tuple[str | None, VisionCheckResult]:
    """Render the hook frame, keep its bytes, and check it before anything references it (FR-24)."""
    if env.halted:
        return None, VisionCheckResult.NOT_CHECKED  # the clip step packages the honest abandon
    # FR-200/FR-244: the brief's own product photos and the Inspiration pick are uploaded here
    # too — under `inspiration_mix: exclusive` they are the ONLY references this frame gets.
    refs = await attach(entry, env, folder)
    prompt = _seed_prompt(entry, env, copyset, refs)
    if prompt is None:
        return _seed_failed(entry, env, folder, "prompt assembly failed (FR-260)")
    params = RenderParams(prompt=prompt, aspect_ratio=ASPECT_9_16)
    outcome = spend.add(await submit(entry, params, RenderRefs(image_urls=_urls(refs)),
                                     job="seed_frame", priority=RenderPriority.WAVE1,
                                     kind="projected",
                                     label=f"reel seed frame · {entry.asset_id}"))
    if outcome is not None and outcome.fail_cause is RenderFailCause.MODERATION and refs:
        env.log.warn("moderation_retry",
                     f"{entry.asset_id}: seed-frame content-policy refusal; one reference-free "
                     "retry (FR-97)", asset_id=entry.asset_id, detail=outcome.fail_message)
        retry = spend.add(await submit(entry, params, RenderRefs(), job="seed_frame",
                                       priority=RenderPriority.WAVE1, kind="discretionary",
                                       label=f"seed-frame moderation retry · {entry.asset_id}"))
        if retry is not None:
            folder.mark(DegradationTag.REFS_DROPPED_MODERATION)
            outcome = retry
    if outcome is None or outcome.kind is not RenderOutcomeKind.SUCCESS or not outcome.result_urls:
        cause = (outcome.fail_message or outcome.kind.value) if outcome else "declined by the cap"
        return _seed_failed(entry, env, folder, cause)
    seed = await _store_seed(entry, env, folder, outcome.result_urls[0])
    return await _check_seed(entry, env, folder, submit, spend, copyset, refs, seed,
                             outcome.result_urls[0])


async def _check_seed(
    entry: PlanEntry, env: Env, folder: AssetFolder, submit: Any, spend: _Spend,
    copyset: CopySet | None, refs: list[Reference], seed: Path | None, url: str,
) -> tuple[str, VisionCheckResult]:
    """FR-105: check the frame, and re-render it ONCE if flagged — before Seedance sees it.

    The check reads the local `seed_frame.jpg` when the download succeeded (native resolution, no
    second fetch) and falls back to the hosted URL; what comes BACK is always the public URL,
    because a local path is not something a renderer can reference (20 §8a).

    A successful re-render is checked once more, so `retried_passed` is genuinely reachable
    (FR-27's four states) — the estimator's `vision_retry_allowance` prices exactly this pair,
    "render + re-check", per flagged asset (budget.py, FR-107). Caps are unchanged: one re-render,
    one re-check, then the frame ships whatever the second answer is.
    """
    if not env.config.run.vision_check or env.llm_call is None:
        return url, VisionCheckResult.NOT_CHECKED
    first = await _verdict(entry, env, seed or url)
    if first is None or not first.flagged:
        return url, vision_check.verdict_result(first)
    env.log.warn("vision_check_flagged",
                 f"{entry.asset_id}: seed frame flagged ({first.detail}); one re-render with "
                 "shorter, larger text before the clip is submitted (FR-105)",
                 asset_id=entry.asset_id)
    plan = vision_check.retry_plan(copyset or CopySet(asset_id=entry.asset_id,
                                                      language=entry.language),
                                   "reel", env.config.run.text_budgets)
    prompt = _seed_prompt(entry, env, plan.copy, refs, budget_scale=plan.budget_scale,
                          extra=plan.instruction)
    if prompt is None or env.halted:
        return url, VisionCheckResult.RETRIED_FAILED
    retry = spend.add(await submit(entry, RenderParams(prompt=prompt, aspect_ratio=ASPECT_9_16),
                                   RenderRefs(image_urls=_urls(refs)), job="seed_frame",
                                   priority=RenderPriority.WAVE1, kind="discretionary",
                                   label=f"seed-frame vision re-render · {entry.asset_id}"))
    if retry is None or retry.kind is not RenderOutcomeKind.SUCCESS or not retry.result_urls:
        env.log.warn("vision_retry_unavailable",
                     f"{entry.asset_id}: the flagged seed frame ships as rendered "
                     f"({'declined by the cap' if retry is None else 'the re-render failed'})",
                     asset_id=entry.asset_id)
        return url, VisionCheckResult.RETRIED_FAILED
    replaced = await _store_seed(entry, env, folder, retry.result_urls[0])  # new poster on disk
    after = await _verdict(entry, env, replaced or retry.result_urls[0])
    return retry.result_urls[0], vision_check.verdict_result(first, after, retried=True)


async def _verdict(entry: PlanEntry, env: Env, image: Path | str) -> vision_check.ImageVerdict | None:
    """One FR-105 pass over one seed frame; `None` when the check could not run (ships anyway)."""
    report = await vision_check.check([image], call=env.llm_call, engine=env.engine, log=env.log)
    return report.verdict_for(1)


def _seed_failed(
    entry: PlanEntry, env: Env, folder: AssetFolder, reason: str
) -> tuple[None, VisionCheckResult]:
    """FR-24: the reel keeps going with in-model text — and keeps its motion reference."""
    folder.mark(DegradationTag.SEED_FRAME_RENDER_FAILED)
    env.log.warn("seed_frame_render_failed",
                 f"{entry.asset_id}: seed frame not produced ({reason}); the reel is generated "
                 "with in-model overlay text and still ships (FR-24)",
                 asset_id=entry.asset_id, reason=reason)
    return None, VisionCheckResult.NOT_CHECKED


async def _store_seed(
    entry: PlanEntry, env: Env, folder: AssetFolder, url: str
) -> Path | None:
    """`seed_frame.jpg` — an asset in its own right and the gallery's poster (FR-72/76).

    Best effort by design: the Kie URL still works for Seedance even when the download does not,
    and a lost poster must never cost a clip. A full disk still latches, because 10 §10 stops
    further downloads run-wide rather than thrashing the volume.
    """
    try:
        return await folder.store_render(url, seed_frame=True)
    except PackagingError as exc:
        _latch_disk_full(env, exc)
        env.log.warn("seed_frame_not_stored",
                     f"{entry.asset_id}: seed frame could not be saved ({exc.reason}); the chain "
                     "continues on its Kie URL", asset_id=entry.asset_id)
        return None


# --------------------------------------------------------------------------- motion reference


async def _motion_reference(entry: PlanEntry, env: Env, folder: AssetFolder) -> str | None:
    """The D23 upgrade, awaited under a short bounded wait — never a dependency (FR-142)."""
    if not env.config.run.reel_video_reference or env.video_refs is None or not entry.trend_key:
        return None
    outcome = await env.video_refs.get(entry.trend_key, timeout_s=VIDEO_REF_WAIT_S)
    if outcome.ref is None:
        if outcome.degradation is not None:
            folder.mark(outcome.degradation)
        env.log.warn("video_reference_degraded",
                     f"{entry.asset_id}: {outcome.reason}; the reel is generated from its seed "
                     "frame and image references only (FR-142)", asset_id=entry.asset_id,
                     degradation=outcome.degradation.value if outcome.degradation else "",
                     reason=outcome.reason)
        return None
    if outcome.ref.local_path is not None:
        # Keep a copy in the run's `refs/` so the gallery can show what the clip mimicked (FR-150);
        # scratch is transient and a missed copy is cosmetic, so this never costs the reference.
        try:
            save_reference(env.run_dir, entry.trend_key,
                           Path(outcome.ref.local_path).read_bytes(), index=1, kind="video")
        except (OSError, PackagingError) as exc:
            env.log.warn("video_reference_not_kept",
                         f"{entry.asset_id}: motion reference not copied into refs/ ({exc})",
                         asset_id=entry.asset_id)
    return outcome.ref.url


# --------------------------------------------------------------------------- clip submission


async def _submit_clip(
    entry: PlanEntry, env: Env, submit: Any, spend: _Spend, copyset: CopySet | None, *,
    seed_url: str | None, video_url: str | None, audio_on: bool, mode: str,
    extra: str = "", kind: str = "precommitted",
) -> RenderOutcome | None:
    """One Seedance submission (FR-23). `None` means nothing was ordered — halt or a bad prompt."""
    if env.halted:  # FR-201/108: stop ORDERING; whatever is already paid for is packaged
        return None
    prompt = _clip_prompt(entry, env, copyset, audio_on=audio_on, mode=mode,
                          has_seed=bool(seed_url), extra=extra)
    if prompt is None:
        return None
    params = RenderParams(
        prompt=prompt,
        aspect_ratio=ASPECT_9_16,  # explicit; the provider's `adaptive` is never sent (FR-23)
        resolution=env.config.run.reel_resolution,
        duration_s=env.config.run.reel_duration_s,  # already clamped at pre-flight (FR-103)
        generate_audio=audio_on,
        output_format="mp4",
        moderation_enabled=env.config.run.nsfw_checker,  # forwarded uninterpreted (FR-166)
    )
    refs = RenderRefs(image_urls=[seed_url] if seed_url else [],  # FR-24: @Image1 leads
                      video_urls=[video_url] if video_url else [])
    return spend.add(await submit(entry, params, refs, job="clip", priority=RenderPriority.WAVE2,
                                  kind=kind,  # FR-106b, except the seed-URL retry (see `_chain`)
                                  label=f"reel clip · {entry.asset_id}"))


def _seed_url_rejected(outcome: RenderOutcome) -> bool:
    """True when the clip failed in a way that implicates the seed-frame reference (20 §10)."""
    if outcome.kind is RenderOutcomeKind.SUCCESS or outcome.fail_cause in (
            RenderFailCause.MODERATION, RenderFailCause.CONTENT_AUDIT):
        return False
    message = (outcome.fail_message or "").lower()
    return any(hint in message for hint in _SEED_URL_HINTS)


# --------------------------------------------------------------------------- prompt assembly


def _urls(refs: list[Reference]) -> list[str]:
    """Just the URLs — what a render job takes; the roles go into the prompt (FR-191)."""
    return [ref.url for ref in refs]


def _seed_prompt(
    entry: PlanEntry, env: Env, copyset: CopySet | None, refs: list[Reference], *,
    budget_scale: float = 1.0, extra: str = "",
) -> str | None:
    """`reel_seed_frame.md` filled — the hook text burnt in, FR-94's clauses inside the template."""
    context = _context(
        entry, env, copyset, budget_scale=budget_scale, reference_image_count=len(refs),
        reference_roles=role_lines(refs))
    # FR-19/96: with no style brief the subject is the deterministic content sentence — the same
    # substitution `image_direct.md` makes for images, done here because the seed frame has one
    # scaffold for both modes.
    context["render_prompt"] = context["render_prompt"] or context["content_sentence"]
    return _render(entry, env, SEED_TEMPLATE, env.config.models.image_profile, context, extra)


def _clip_prompt(
    entry: PlanEntry, env: Env, copyset: CopySet | None, *, audio_on: bool, mode: str,
    has_seed: bool, extra: str = "",
) -> str | None:
    """`reel_director.md` filled — nine sections, `@Image1`/`@Video1` roles, audio cue (FR-194).

    `mode` is the overlay mode IN FORCE for this submission, which is not always the configured
    one: a lost seed frame degrades `seed_frame` to `in_model` (FR-24), and `none` clears the
    protected-text block entirely so the model is not asked to preserve text nobody rendered.
    """
    clean = mode == "none"
    if clean and copyset is not None:
        copyset = replace(copyset, overlay_text="", headline="", subline="")
    context = _context(
        entry, env, copyset,
        seed_frame_ref=(_SEED_REF_LINE if has_seed else
                        _CLEAN_CLIP_REF_LINE if clean else _IN_MODEL_REF_LINE),
        audio_cue=_AUDIO_CUE if audio_on else SILENT_CLIP_CLAUSE)
    return _render(entry, env, CLIP_TEMPLATE, env.config.models.video_profile, context, extra)


def _context(entry: PlanEntry, env: Env, copyset: CopySet | None, **slots: Any) -> dict[str, str]:
    """The shared, secret-free reel context (FR-261); each role adds its own slots on top."""
    return build_context(
        trend=env.trends.get(entry.trend_key or ""),
        # None in direct mode and after FR-12's degrade — the scaffold then runs on FR-96's sentence.
        style_brief=(env.style_briefs.get(entry.trend_key or "")
                     if entry.variant == "analyzed" else None),
        copy=copyset, creative_format="reel", niche_descriptor=env.niche_descriptor,
        # FR-144/145 + FR-109 `full` (only the seed-frame role allowlists `brand_accent`), read
        # through `getattr`: this module targets the duck-typed Env surface, not its dataclass.
        campaign_brief=getattr(env, "campaign_briefs", {}).get(entry.brief_name or ""),
        brand_accent=getattr(env, "brand_accent", ""),
        brand_product_nouns=getattr(env, "brand_product_nouns", ()),
        text_budgets=env.config.run.text_budgets, **slots)


def _render(
    entry: PlanEntry, env: Env, role: str, profile: str, context: dict[str, str], extra: str = "",
) -> str | None:
    """Fill one template, or fail this creative BEFORE anything is submitted (FR-260)."""
    try:
        prompt = env.engine.render(  # 50 §7: over the bound, descriptive slots are cut in order
            role, context, profile=profile,
            max_chars=render.get_profile(profile).limits.max_prompt_chars)
    except (UnresolvedPlaceholderError, MissingTemplateError, ValueError, LookupError) as exc:
        env.log.error("prompt_assembly_failed", f"{entry.asset_id}: {exc}",
                      asset_id=entry.asset_id, role=role)
        return None
    if extra:
        prompt = f"{prompt}\n\n{extra}"
    env.log.event("render_prompt_assembled", f"{entry.asset_id} {role} ready", verbose_only=True,
                  asset_id=entry.asset_id, role=role, prompt=prompt)
    return prompt


# --------------------------------------------------------------------------- terminal packaging


def _latch_disk_full(env: Env, exc: PackagingError) -> None:
    """10 §10: once the volume is full, further downloads stop run-wide instead of thrashing it."""
    if exc.reason == "disk_full":
        env.disk_full = True


def _skip(
    entry: PlanEntry, folder: AssetFolder, spend: _Spend, reason: str,
    tag: DegradationTag | None = None, **extra: Any,
) -> AssetRecord:
    """Terminal failure that keeps every paid artifact — caption, seed frame, meta (FR-74)."""
    if entry.status is PlanEntryStatus.PENDING:
        entry.status = PlanEntryStatus.FAILED
    entry.skip_reason = entry.skip_reason or reason
    return folder.skip(reason, tag, **spend.meta(), **extra)


__all__ = ["ASPECT_9_16", "SILENT_CLIP_CLAUSE", "VIDEO_REF_WAIT_S", "render_reel"]
