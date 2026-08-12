"""Reels — the seed-frame chain and one Seedance clip (FR-23/24/141).

Module contract
---------------
Purpose: turn one approved reel plan entry into a packaged `reel.mp4`, plus the paid
`seed_frame.jpg` the gallery uses as its poster (FR-72/76). This module owns the CHAIN — its
order, its checks and its degrades. It owns no money, no profile choice and no ledger line: the
injected `submit` does all three (FR-106 a/b/c, FR-203).

**No motion reference (v2.0.0, topic-first pivot).** A reel is the seed frame plus Seedance and
nothing else: Virlo is a text-only topic feed now, so there is no winning video to download, no
yt-dlp chain to wait on, and every clip is billed at the provider's no-reference rate. The clip's
movement comes from the assigned style's `motion_profile` and the copy's one named `motion_beat`
(F24), both of which travel through the prompt rather than through a downloaded file.

Public API: `await render_reel(entry, env, folder, submit=...) -> AssetRecord`.

Invariants enforced here, once:
- **A seed frame that never rendered costs legibility, not a clip (FR-24).**
  `seed_frame_render_failed` degrades to `in_model` overlay text — the clip is still ordered, on
  the same style and the same copy — and still counts as delivered. Its sibling `seed_frame_url_unreachable` — the frame rendered, then
  Seedance rejected the reference — is detected, tagged and logged, but the clip that already
  failed is **not re-bought** (operator decision 2026-08-10): a heuristic message match may not
  order a second ~$4.75 render, so that reel ends as an honest render failure keeping every paid
  artifact. This is the one place the code is deliberately stricter than 10 §10's ":422" row.
- **The seed frame is checked BEFORE the clip is submitted (FR-105).** A re-render has to replace
  the frame the video is built from, not arrive after the clip is paid for. A successful re-render
  is checked once more — the estimator's `vision_retry_allowance` prices that pair, "render +
  re-check" — so FR-27's `retried_passed` is genuinely reachable; a declined or failed re-render
  is `retried_failed` and is never re-checked. The finished CLIP is never checked at all: frame
  extraction would mean ffmpeg, which this project does not carry (D10).
- **A content-security audit failure is not a moderation refusal (FR-141, v1.6.6).** Its remedy is
  silencing the clip, never stripping references — one retry with `generate_audio: false` plus the
  explicit silent-clip clause, same references, the failed attempt billed $0 (RESULTS.md §C).
- **One retry per class (NFR-4).** Three separate single retries live here and none of them stacks:
  the seed frame's moderation retry (FR-97), its vision-check re-render (FR-105), and the clip's
  content-audit silent retry — 20 §8's whole sanctioned list. There is no fourth.
- **9:16 always.** A reel's seed frame inherits the reel's ratio, never the platform's image ratio
  (FR-21), and the clip passes 9:16 explicitly — the provider's `adaptive` is never used.

Do not: call `render.run`, price anything, touch `env.budget` / `env.ledger`, vision-check the
finished clip, attach a video reference, or re-upload the Kie-hosted seed frame (D18: it is a URL
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
from hypesocials import prompts_engine
from hypesocials.outputs import AssetFolder, PackagingError
from hypesocials.generate.refs import (
    Reference, attach, branding_block, role_lines, style_of, wordmark,
)
from hypesocials.prompts_engine import (
    MissingTemplateError, UnresolvedPlaceholderError, build_context,
)

if TYPE_CHECKING:  # never at runtime — `generate/__init__.py` imports this module (circular)
    from hypesocials.generate import Env

SEED_TEMPLATE = "reel_seed_frame.md"
CLIP_TEMPLATE = "reel_director.md"
#: FR-21 — the ratio belongs to the FORMAT, so the seed frame inherits it too.
ASPECT_9_16 = "9:16"
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
#: failed render, and this match only NAMES a failure — it never orders anything.
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
    meta and caption written). `env` supplies config, prompt engine, log, the style registry and
    topic material, plus the optional `llm_call` for the vision check. `submit` is the wave
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
    """Seed frame → check → clip, with each degrade scoped to its own step."""
    run = env.config.run
    copyset = env.copy.get(entry.asset_id)
    seed_url: str | None = None
    verdict = VisionCheckResult.NOT_CHECKED
    mode = run.reel_overlay_text
    if mode == "seed_frame":  # `in_model` / `none` skip the chain entirely (FR-24)
        seed_url, verdict = await _seed_frame(entry, env, folder, submit, spend, copyset)
        mode = "seed_frame" if seed_url else "in_model"  # FR-24's degrade, either failure shape
    seed_rendered = seed_url is not None  # paid for, so it stays in `model_ids` even if dropped

    audio_on = bool(run.reel_audio)
    outcome = await _submit_clip(entry, env, submit, spend, copyset, seed_url=seed_url,
                                 audio_on=audio_on, mode=mode)

    if outcome is not None and outcome.fail_cause is RenderFailCause.CONTENT_AUDIT and audio_on:
        # FR-141 v1.6.6: silence the clip, KEEP every reference — the failed attempt cost $0.
        env.log.warn("content_audit_retry",
                     f"{entry.asset_id}: content-security audit failed the clip; one retry with "
                     "generate_audio=false and the silent-clip clause, references kept (FR-141)",
                     asset_id=entry.asset_id, detail=outcome.fail_message)
        audio_on = False
        folder.mark(DegradationTag.AUDIO_DROPPED_CONTENT_AUDIT)
        outcome = await _submit_clip(entry, env, submit, spend, copyset, seed_url=seed_url,
                                     audio_on=False, mode=mode, extra=SILENT_CLIP_CLAUSE)

    if outcome is not None and seed_url and _seed_url_rejected(outcome):
        # FR-24's second failure: the frame rendered and was paid for; the handoff is what broke.
        # NAMED, never re-bought (operator decision 2026-08-10) — 20 §8 sanctions exactly two
        # resubmissions and this was neither, so the failed outcome falls straight through to the
        # terminal path below carrying this tag and this line as its explanation.
        env.log.warn("seed_frame_url_unreachable",
                     f"{entry.asset_id}: Seedance rejected the seed-frame reference "
                     f"({outcome.fail_message}); the clip is not resubmitted",
                     asset_id=entry.asset_id)
        folder.mark(DegradationTag.SEED_FRAME_URL_UNREACHABLE)

    if outcome is None:  # nothing was ordered: Ctrl+C / deadline, or a prompt that would not fill
        if not env.halted:
            return _skip(entry, folder, spend,
                         "prompt_assembly_failed — unresolved placeholder (FR-260)")
        entry.status = PlanEntryStatus.ABANDONED
        return _skip(entry, folder, spend, "interrupted before the video job was ordered — "
                     "everything already paid for is packaged (FR-201/108)",
                     DegradationTag.ABANDONED, reel_audio=audio_on, vision_check_result=verdict)
    if outcome.kind is not RenderOutcomeKind.SUCCESS or not outcome.result_urls:
        cause = outcome.fail_cause.value if outcome.fail_cause else outcome.kind.value
        env.log.error("render_failed",
                      f"{entry.asset_id}: {cause} — {outcome.fail_message or 'no usable result'}",
                      asset_id=entry.asset_id, task_id=outcome.task_id)
        return _skip(entry, folder, spend,
                     f"{cause}: {outcome.fail_message or 'no usable result'} "
                     f"(job {outcome.task_id or 'unknown'})", reel_audio=audio_on,
                     vision_check_result=verdict)
    try:
        await folder.store_render(outcome.result_urls[0])  # -> reel.mp4 (FR-72)
    except PackagingError as exc:
        _latch_disk_full(env, exc)
        return _skip(entry, folder, spend, f"{exc.reason}: {exc}", reel_audio=audio_on,
                     vision_check_result=verdict)

    entry.status = PlanEntryStatus.SUCCESS
    models = env.config.models
    return folder.finish(
        model_ids=([models.image, models.image_profile] if seed_rendered else [])
        + [models.video, models.video_profile],
        native_size_rendered=ASPECT_9_16,  # FR-98: shipped exactly as it came back
        vision_check_result=verdict,
        reel_audio=audio_on,  # the FINAL truth, after any content-audit degrade
        event_id=env.log.event("creative_delivered", f"{entry.asset_id} reel rendered",
                               asset_id=entry.asset_id, task_id=outcome.task_id,
                               cost_usd=round(spend.cost, 6), reel_audio=audio_on,
                               seed_frame=seed_rendered),
        **spend.meta())


# --------------------------------------------------------------------------- the seed-frame chain


async def _seed_frame(
    entry: PlanEntry, env: Env, folder: AssetFolder, submit: Any, spend: _Spend,
    copyset: CopySet | None,
) -> tuple[str | None, VisionCheckResult]:
    """Render the hook frame, keep its bytes, and check it before anything references it (FR-24)."""
    if env.halted:
        return None, VisionCheckResult.NOT_CHECKED  # the clip step packages the honest abandon
    # FR-200/FR-244: the assigned style's reference window and a brief's own product photos are
    # uploaded here, once per run — the seed frame is where a reel's look is decided, so it is the
    # one job in this chain that carries pictures at all.
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
    """FR-24: the reel keeps going, with the hook rendered by the video model instead."""
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


# --------------------------------------------------------------------------- clip submission


async def _submit_clip(
    entry: PlanEntry, env: Env, submit: Any, spend: _Spend, copyset: CopySet | None, *,
    seed_url: str | None, audio_on: bool, mode: str, extra: str = "",
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
    # FR-24: the seed frame is @Image1 and the ONLY reference a clip carries — no video reference
    # exists any more, so every clip is billed at the provider's no-reference rate.
    refs = RenderRefs(image_urls=[seed_url] if seed_url else [])
    return spend.add(await submit(entry, params, refs, job="clip", priority=RenderPriority.WAVE2,
                                  kind="precommitted",  # FR-106b: every clip this chain orders
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
    context = _context(entry, env, copyset, budget_scale=budget_scale,
                       reference_roles=role_lines(refs))
    # FR-19/96: with no style instruction — an unassigned entry, or a registry that could not be
    # loaded — the subject is the deterministic content sentence, so the frame is still ABOUT
    # something. The seed frame has one scaffold for every case, which is why the substitution
    # lives here rather than in a second template.
    context["render_prompt"] = context["render_prompt"] or context["content_sentence"]
    return _render(entry, env, SEED_TEMPLATE, env.config.models.image_profile, context, extra)


def _clip_prompt(
    entry: PlanEntry, env: Env, copyset: CopySet | None, *, audio_on: bool, mode: str,
    has_seed: bool, extra: str = "",
) -> str | None:
    """`reel_director.md` filled — its sections, the `@Image1` role, the audio cue (FR-194).

    `mode` is the overlay mode IN FORCE for this submission, which is not always the configured
    one: a lost seed frame degrades `seed_frame` to `in_model` (FR-24), and `none` clears the
    protected-text block entirely so the model is not asked to preserve text nobody rendered.

    M13's continuity: on a branded reel the seed frame already carries the wordmark, and the
    director must be told to KEEP it — so the clip is built from the same copy, the same style and
    the same `wordmark` string the frame was built from, and it travels in `{{onimage_text}}`
    exactly as it did there. It never travels in `{{branding_block}}`, which this role does not
    allowlist at all (§1.4: that block is for gpt-image-2 render roles).

    F24's staging is this role's alone: `reel_beats` turns the CONFIGURED clip duration — the one
    number this chain also bills and times out on — into the director's real-second beats, so the
    prompt can never stage four seconds of action inside a five-second clip. The seed frame is a
    still and is deliberately given none.
    """
    clean = mode == "none"
    if clean and copyset is not None:
        copyset = replace(copyset, overlay_text="", headline="", subline="")
    context = _context(
        entry, env, copyset, signed=not clean,
        seed_frame_ref=(_SEED_REF_LINE if has_seed else
                        _CLEAN_CLIP_REF_LINE if clean else _IN_MODEL_REF_LINE),
        reel_beats=prompts_engine.beats_for(env.config.run.reel_duration_s),
        audio_cue=_AUDIO_CUE if audio_on else SILENT_CLIP_CLAUSE)
    return _render(entry, env, CLIP_TEMPLATE, env.config.models.video_profile, context, extra)


def _context(entry: PlanEntry, env: Env, copyset: CopySet | None, *, signed: bool = True,
             **slots: Any) -> dict[str, str]:
    """The shared, secret-free reel context (FR-261); each role adds its own slots on top.

    `style` carries the whole look now: `render_prompt`, `exclusions` and the on-image budgets for
    the seed frame, and F24's `{{motion_profile}}` for the director — one assigned registry entry
    instead of a per-trend analysis, so the frame and the clip cannot describe two different looks.
    `signed` is False only for a clip that carries no on-screen text at all: a frame with no
    lettering must not be handed a signature to preserve — neither the colour block nor the
    wordmark, since M13's continuity rule ("a wordmark already present in @Image1 persists") has
    nothing to persist when the frame was never signed.
    """
    style = style_of(entry, env)
    return build_context(
        trend=env.trends.get(entry.trend_key or ""),
        style=style,
        # B1: the wordmark is a TEXT-block string, so both roles get the SAME one — the frame burns
        # it in, the director is told it is already there (M13).
        wordmark=wordmark(entry, env) if signed else "",
        copy=copyset, creative_format="reel", niche_descriptor=env.niche_descriptor,
        # FR-144/145, read through `getattr`: this module targets the duck-typed Env surface, not
        # its dataclass.
        campaign_brief=getattr(env, "campaign_briefs", {}).get(entry.brief_name or ""),
        # FR-292's colour/letterform channel — allowlisted for `reel_seed_frame.md` and dropped by
        # the director role as an out-of-role name (§1.4/M13).
        branding_block=branding_block(entry, env, style) if signed else "",
        # A15, same seam and same narrowness: only `reel_seed_frame.md` allowlists it, so the
        # director role drops it exactly as it drops the branding block.
        niche_visual_world=getattr(env, "niche_visual_world", ""),
        # M6 (W3): config blocklist + this topic's guarded LLM strips — read through `getattr`
        # like every Env read here (this module targets the duck-typed surface).
        competitor_strings=(
            *map(str, getattr(getattr(env, "branding", None), "competitors", ())),
            *map(str, getattr(env, "strip_brands", {}).get(entry.trend_key or "", ()))),
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


__all__ = ["ASPECT_9_16", "SILENT_CLIP_CLAUSE", "render_reel"]
