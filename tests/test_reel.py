"""Reel-chain tests — the ORDER of the chain and every degrade that must still deliver a clip.

No network, no money: the injected `submit` is a recorder, the vision call is a stub, and the
packager's download is faked. `generate.Env` is deliberately NOT imported — T4.2 must run against
the duck-typed surface T4.3 promises (`config`, `run_dir`, `engine`, `log`, `trends`,
`style_briefs`, `copy`, `niche_descriptor`, `llm_call`, `video_refs`, `halted`,
`credits_exhausted`), never against the concrete dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from hypesocials.config import Config
from hypesocials.generate import reel
from hypesocials.generate.video_ref import VideoRef, VideoRefOutcome
from hypesocials.models import (
    AssetRecord,
    AssetStatus,
    CopySet,
    DegradationTag,
    LayoutZone,
    ParsedResult,
    PlanEntry,
    PlanEntryStatus,
    RenderFailCause,
    RenderOutcome,
    RenderOutcomeKind,
    StyleBrief,
    TrendItem,
    VisionCheckResult,
)
from hypesocials.outputs import AssetFolder, PackagingError, packager
from hypesocials.prompts_engine import PromptEngine

ASSET_ID = "Tt_reel_ai-tools_analyzed_01"
SEED_URL = "https://tempfile.aiquickdraw.com/seed.jpg"
SEED_URL_2 = "https://tempfile.aiquickdraw.com/seed-retry.jpg"
CLIP_URL = "https://tempfile.aiquickdraw.com/clip.mp4"
VIDEO_REF_URL = "https://tempfile.redpandaai.co/kieai/1/hypesocials/ref.mp4"
TREND_REFS = ["https://auth.virlo.ai/panel-1.webp", "https://auth.virlo.ai/panel-2.webp"]


# ------------------------------------------------------------------------------ doubles


class Recorder:
    """Stands in for `outputs.LogWriter`; only the three level helpers are used."""

    def __init__(self, trace: list[str] | None = None) -> None:
        self.lines: list[tuple[str, str]] = []
        self.trace = trace if trace is not None else []

    def event(self, event_type: str, message: str = "", **data: Any) -> str:
        self.lines.append((event_type, message))
        return f"ev_{len(self.lines)}"

    warn = event
    error = event

    def types(self) -> list[str]:
        return [event_type for event_type, _ in self.lines]


@dataclass
class StubEnv:
    """The duck-typed `generate.Env` surface `render_reel` is allowed to touch."""

    config: Config
    run_dir: Path
    engine: PromptEngine
    log: Recorder
    trends: dict[str, TrendItem] = field(default_factory=dict)
    style_briefs: dict[str, StyleBrief] = field(default_factory=dict)
    copy: dict[str, CopySet] = field(default_factory=dict)
    niche_descriptor: str = ""
    llm_call: Any = None
    video_refs: Any = None
    halted: bool = False
    credits_exhausted: bool = False
    disk_full: bool = False


class Submitter:
    """T4.3's money-owning `submit`, reduced to a recorder with a queue of outcomes."""

    def __init__(self, outcomes: list[RenderOutcome | None], trace: list[str] | None = None,
                 *, halt: StubEnv | None = None, halt_after: str = "") -> None:
        self.queue = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.trace = trace if trace is not None else []
        self._halt = halt
        self._halt_after = halt_after

    async def __call__(self, entry: PlanEntry, params: Any, refs: Any, *, job: str, priority: Any,
                       kind: str, label: str) -> RenderOutcome | None:
        self.calls.append({"job": job, "priority": priority, "kind": kind, "params": params,
                           "refs": refs, "label": label})
        self.trace.append(f"submit:{job}")
        if self._halt is not None and job == self._halt_after:
            self._halt.halted = True  # Ctrl+C landed while this job was in flight (FR-201)
        return self.queue.pop(0) if self.queue else None

    def of(self, job: str) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["job"] == job]


class StubRefs:
    """A `video_ref.Prefetch` stand-in — one canned answer, and the wait it was asked for."""

    def __init__(self, outcome: VideoRefOutcome) -> None:
        self.outcome = outcome
        self.waits: list[float] = []

    async def get(self, trend_key: str, *, timeout_s: float) -> VideoRefOutcome:
        self.waits.append(timeout_s)
        return self.outcome


def vision(trace: list[str], *flags: bool) -> Any:
    """A `models.StructuredCall` answering FR-105, one queued verdict per check call.

    Two flags express the pair the estimator prices: the first check, then the re-check of the
    re-rendered frame. The last flag repeats if more calls arrive than were queued.
    """
    queue = list(flags) or [False]

    async def call(role: str, messages: list[dict[str, Any]], json_schema: dict[str, Any],
                   images: list[bytes] | None = None) -> ParsedResult:
        trace.append("vision_check")
        flagged = queue.pop(0) if len(queue) > 1 else queue[0]
        return ParsedResult(parsed={"verdicts": [{"image": 1, "text_broken": flagged,
                                                  "fake_ui": False, "detail": "garbled headline"}]},
                            raw_text="{}", cost_usd=0.01)
    return call


# ------------------------------------------------------------------------------ fixtures


def ok(url: str, *, task: str, cost: float = 0.03) -> RenderOutcome:
    return RenderOutcome(kind=RenderOutcomeKind.SUCCESS, task_id=task, result_urls=[url],
                         cost_usd=cost, submitted_at="2026-08-09T10:00:00Z",
                         completed_at="2026-08-09T10:05:00Z")


def failed(cause: RenderFailCause, message: str = "", *, task: str = "job_fail",
           cost: float = 0.0) -> RenderOutcome:
    return RenderOutcome(kind=RenderOutcomeKind.FAIL, task_id=task, fail_cause=cause,
                         fail_message=message, cost_usd=cost)


def with_video_ref() -> StubRefs:
    return StubRefs(VideoRefOutcome(ref=VideoRef(url=VIDEO_REF_URL, duration_s=10.0,
                                                 source_url="https://tiktok.test/1")))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The packager's only network call; every render is downloaded through it."""
    async def download(url: str) -> bytes:
        return b"\xff\xd8fake-media-bytes"

    monkeypatch.setattr(packager, "_download", download)


def make_entry(**overrides: Any) -> PlanEntry:
    entry = PlanEntry(order=0, asset_id=ASSET_ID, creative_format="reel", platform="tiktok",
                      language="en", aspect_ratio="9:16", variant="analyzed", trend_key="t1",
                      estimated_cost_usd=2.85)
    for key, value in overrides.items():
        setattr(entry, key, value)
    return entry


def make_env(tmp_path: Path, trace: list[str] | None = None, **run_overrides: Any) -> StubEnv:
    config = Config()
    for key, value in run_overrides.items():
        setattr(config.run, key, value)
    env = StubEnv(config=config, run_dir=tmp_path, engine=PromptEngine(), log=Recorder(trace))
    env.trends = {"t1": TrendItem(
        history_key="t1", monitor_id="m1", name="AI tool stacks",
        why_it_works="concrete numbers in the first line",
        hook_texts=["Nobody tells you this"], video_descriptions=["a creator lists seven tools"],
        reference_groups=[list(TREND_REFS)],
        winning_video_url="https://www.tiktok.com/@x/video/1")}
    env.style_briefs = {"t1": StyleBrief(
        trend_key="t1", render_prompt="Cream ground, sage blob top-right, heavy black sans.",
        layout_zones=[LayoutZone("upper third", "headline", "all caps, extra bold")],
        exclusions=["platform UI", "brand wordmark"], typography="extra-bold condensed sans")}
    env.copy = {ASSET_ID: CopySet(asset_id=ASSET_ID, language="en", caption="Seven tools.",
                                  hashtags=["ai"], overlay_text="Nobody tells you this",
                                  through_line="a fast reveal of the tool stack",
                                  hook_pattern_used="negative-outcome claim, second person")}
    return env


def make_folder(tmp_path: Path) -> AssetFolder:
    return AssetFolder(tmp_path, AssetRecord(asset_id=ASSET_ID, source="t1",
                                             source_name="AI tool stacks", platform="tiktok",
                                             creative_format="reel", variant="analyzed",
                                             generation_mode="analyzed"))


# ------------------------------------------------------------------------------ FR-105 ordering


async def test_fr105_seed_frame_checked_before_seedance_submission(tmp_path: Path) -> None:
    """The seed frame is a CHAINED artifact: checking it after the clip is submitted would mean
    discovering a broken headline one paid video too late (FR-105, plan §0 diagram caveat)."""
    trace: list[str] = []
    env = make_env(tmp_path, trace, vision_check=True)
    env.llm_call = vision(trace, False)
    env.video_refs = with_video_ref()
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"), ok(CLIP_URL, task="job_clip", cost=2.85)],
                       trace)

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert trace == ["submit:seed_frame", "vision_check", "submit:clip"]
    assert record.status is AssetStatus.SUCCESS
    assert record.vision_check_result is VisionCheckResult.PASSED
    assert record.native_size_rendered == "9:16"
    assert record.kie_job_ids == ["job_seed", "job_clip"]
    assert record.actual_cost_usd == pytest.approx(2.88)
    assert record.reel_video_reference_url == VIDEO_REF_URL
    # FR-72/76: the paid seed frame is both an asset and the gallery's poster.
    assert (folder.path / "seed_frame.jpg").is_file()
    assert (folder.path / "reel.mp4").is_file()
    seed_call, clip_call = submit.of("seed_frame")[0], submit.of("clip")[0]
    assert seed_call["params"].aspect_ratio == "9:16"  # FR-21: never the platform image ratio
    assert seed_call["kind"] == "projected" and clip_call["kind"] == "precommitted"  # FR-106 a/b
    assert clip_call["refs"].image_urls == [SEED_URL]  # FR-24: the seed frame is @Image1
    assert clip_call["params"].generate_audio is True
    assert clip_call["params"].duration_s == env.config.run.reel_duration_s


async def test_flagged_seed_frame_is_re_rendered_and_re_checked_once(tmp_path: Path) -> None:
    """FR-105's retry changes the INPUT, replaces the frame the video is built from, and is
    re-checked once so FR-27's `retried_passed` is genuinely reachable — the pair the estimator's
    `vision_retry_allowance` prices as "render + re-check". Both still precede the clip."""
    trace: list[str] = []
    env = make_env(tmp_path, trace, vision_check=True)
    env.llm_call = vision(trace, True, False)  # flagged, then clean after the shorter re-render
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"), ok(SEED_URL_2, task="job_seed_retry"),
                        ok(CLIP_URL, task="job_clip")], trace)

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert trace == ["submit:seed_frame", "vision_check", "submit:seed_frame", "vision_check",
                     "submit:clip"]
    assert submit.of("seed_frame")[1]["kind"] == "discretionary"  # FR-106c
    assert submit.of("clip")[0]["refs"].image_urls == [SEED_URL_2]
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED
    assert record.status is AssetStatus.SUCCESS


async def test_seed_frame_still_flagged_after_its_one_re_render_ships_retried_failed(
    tmp_path: Path,
) -> None:
    """One retry is the cap everywhere: a frame flagged twice ships anyway, labelled honestly."""
    trace: list[str] = []
    env = make_env(tmp_path, trace, vision_check=True)
    env.llm_call = vision(trace, True, True)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"), ok(SEED_URL_2, task="job_seed_retry"),
                        ok(CLIP_URL, task="job_clip")], trace)

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert trace.count("vision_check") == 2 and len(submit.of("seed_frame")) == 2
    assert record.vision_check_result is VisionCheckResult.RETRIED_FAILED
    assert record.status is AssetStatus.SUCCESS


async def test_declined_re_render_is_never_re_checked(tmp_path: Path) -> None:
    """A re-render the cap declined has nothing new to look at — no second check is spent."""
    trace: list[str] = []
    env = make_env(tmp_path, trace, vision_check=True)
    env.llm_call = vision(trace, True)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"), None, ok(CLIP_URL, task="job_clip")], trace)

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert trace.count("vision_check") == 1
    assert record.vision_check_result is VisionCheckResult.RETRIED_FAILED
    assert submit.of("clip")[0]["refs"].image_urls == [SEED_URL]  # the first frame still ships
    assert record.status is AssetStatus.SUCCESS


# ------------------------------------------------------------------------------ content audit


async def test_content_audit_retries_once_silent_and_keeps_refs(tmp_path: Path) -> None:
    """FR-141 (v1.6.6): the remedy for a content-security audit is silencing the clip, never
    FR-97's reference strip — the motion reference is the whole point of the render."""
    env = make_env(tmp_path)
    env.video_refs = with_video_ref()
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([
        ok(SEED_URL, task="job_seed"),
        failed(RenderFailCause.CONTENT_AUDIT,
               "Content security audit did not pass. The output audio may be related to "
               "copyright restrictions.", task="job_audit", cost=0.0),
        ok(CLIP_URL, task="job_clip", cost=2.85),
    ])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    clips = submit.of("clip")
    assert len(clips) == 2  # exactly one retry (NFR-4)
    assert clips[0]["params"].generate_audio is True
    assert clips[1]["params"].generate_audio is False
    assert reel.SILENT_CLIP_CLAUSE in clips[1]["params"].prompt
    assert clips[1]["refs"].image_urls == [SEED_URL]  # references KEPT
    assert clips[1]["refs"].video_urls == [VIDEO_REF_URL]
    assert clips[1]["kind"] == "precommitted"  # the failed attempt was billed $0 (RESULTS.md §C)
    assert DegradationTag.AUDIO_DROPPED_CONTENT_AUDIT in record.degradations
    assert record.reel_audio is False  # meta tells the final truth
    assert record.status is AssetStatus.SUCCESS
    assert record.kie_job_ids == ["job_seed", "job_audit", "job_clip"]


# ------------------------------------------------------------------------------ FR-24 degrades


async def test_seed_frame_render_failure_degrades_to_in_model_and_keeps_the_motion_reference(
    tmp_path: Path,
) -> None:
    """FR-24 / 10 §10: a lost seed frame costs legibility, not a clip — and not the video ref."""
    env = make_env(tmp_path)
    env.video_refs = with_video_ref()
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([failed(RenderFailCause.PROVIDER_FAIL, "renderer exploded", cost=0.03),
                        ok(CLIP_URL, task="job_clip", cost=2.85)])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert DegradationTag.SEED_FRAME_RENDER_FAILED in record.degradations
    clip = submit.of("clip")[0]
    assert clip["refs"].image_urls == []
    assert clip["refs"].video_urls == [VIDEO_REF_URL]  # the motion reference survives
    assert "hook text" in clip["params"].prompt  # the overlay moved into the video model
    assert record.status is AssetStatus.SUCCESS
    assert (folder.path / "reel.mp4").is_file()
    assert record.actual_cost_usd == pytest.approx(2.88)  # the failed frame was still billed


async def test_seed_url_rejected_at_submission_resubmits_once_without_it(tmp_path: Path) -> None:
    """20 §10's second seed-frame row: the render succeeded and was paid for; the handoff broke."""
    env = make_env(tmp_path)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([
        ok(SEED_URL, task="job_seed"),
        failed(RenderFailCause.PROVIDER_FAIL, "reference image url could not be downloaded"),
        ok(CLIP_URL, task="job_clip"),
    ])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    clips = submit.of("clip")
    assert len(clips) == 2 and clips[1]["refs"].image_urls == []
    assert DegradationTag.SEED_FRAME_URL_UNREACHABLE in record.degradations
    assert record.status is AssetStatus.SUCCESS  # never a whole-reel failure


async def test_video_reference_degradation_ships_a_seed_frame_only_reel(tmp_path: Path) -> None:
    """FR-142: the motion reference is an upgrade, never a dependency."""
    env = make_env(tmp_path)
    env.video_refs = StubRefs(VideoRefOutcome(
        degradation=DegradationTag.NO_QUALIFYING_VIDEO,
        reason="winning video runs 45s, over the 10s bound"))
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"), ok(CLIP_URL, task="job_clip")])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert DegradationTag.NO_QUALIFYING_VIDEO in record.degradations
    clip = submit.of("clip")[0]
    assert clip["refs"].video_urls == []
    assert clip["refs"].image_urls == [SEED_URL]
    assert record.status is AssetStatus.SUCCESS
    assert record.reel_video_reference_url is None
    assert env.video_refs.waits == [reel.VIDEO_REF_WAIT_S]  # a SHORT bounded wait, not forever
    assert "video_reference_degraded" in env.log.types()


async def test_moderation_refusal_on_the_seed_frame_retries_reference_free(tmp_path: Path) -> None:
    """FR-97 still applies to the seed frame: one reference-free retry, then the chain continues."""
    env = make_env(tmp_path)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([failed(RenderFailCause.MODERATION, "content policy"),
                        ok(SEED_URL, task="job_seed_retry"), ok(CLIP_URL, task="job_clip")])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    seeds = submit.of("seed_frame")
    assert seeds[0]["refs"].image_urls == TREND_REFS
    assert seeds[1]["refs"].image_urls == [] and seeds[1]["kind"] == "discretionary"
    assert DegradationTag.REFS_DROPPED_MODERATION in record.degradations
    assert record.status is AssetStatus.SUCCESS


# ------------------------------------------------------------------------------ lifecycle


async def test_halt_before_clip_submission_packages_honestly(tmp_path: Path) -> None:
    """FR-201/108: Ctrl+C stops ORDERING. What was already bought is packaged and labelled."""
    env = make_env(tmp_path)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed")], halt=env, halt_after="seed_frame")

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert submit.of("clip") == []  # nothing was ordered after the stop
    assert record.status is AssetStatus.FAILED
    assert DegradationTag.ABANDONED in record.degradations
    assert entry.status is PlanEntryStatus.ABANDONED
    assert "interrupted" in (record.skip_reason or "")
    assert record.actual_cost_usd == pytest.approx(0.03)  # the seed frame was billed
    assert (folder.path / "seed_frame.jpg").is_file()  # and it is kept (FR-74)
    assert (folder.path / "SKIP_REASON.txt").is_file()


async def test_clip_failure_keeps_the_paid_artifacts(tmp_path: Path) -> None:
    """10 §10: a failed creative still ships its folder, its seed frame and a failed meta."""
    env = make_env(tmp_path)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"),
                        failed(RenderFailCause.TIMEOUT, "no terminal state in 600s",
                               task="job_clip", cost=2.85)])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert record.status is AssetStatus.FAILED
    assert "timeout" in (record.skip_reason or "")
    assert record.actual_cost_usd == pytest.approx(2.88)  # billed on submission, failure included
    assert (folder.path / "seed_frame.jpg").is_file()
    assert not (folder.path / "reel.mp4").exists()


async def test_in_model_mode_skips_the_seed_frame_entirely(tmp_path: Path) -> None:
    """FR-24's other two values: no seed render, no check, straight to the clip."""
    trace: list[str] = []
    env = make_env(tmp_path, trace, reel_overlay_text="in_model", vision_check=True)
    env.llm_call = vision(trace, True)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([ok(CLIP_URL, task="job_clip")], trace)

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert trace == ["submit:clip"]
    assert record.vision_check_result is VisionCheckResult.NOT_CHECKED
    assert record.status is AssetStatus.SUCCESS
    assert not (folder.path / "seed_frame.jpg").exists()


async def test_disk_full_latches_on_the_clip_store_and_fails_that_creative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """10 §10: a full disk fails this creative AND stops further downloads run-wide."""
    async def out_of_space(url: str) -> bytes:
        raise PackagingError("cannot write reel.mp4: no space left", reason="disk_full")

    monkeypatch.setattr(packager, "_download", out_of_space)
    env = make_env(tmp_path)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"), ok(CLIP_URL, task="job_clip")])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert env.disk_full is True
    assert record.status is AssetStatus.FAILED
    assert "disk_full" in (record.skip_reason or "")


async def test_disk_full_on_the_poster_latches_but_still_delivers_the_reel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The poster is best-effort — a lost seed frame costs legibility, not a clip (FR-24) — but a
    full volume is a run-wide condition and must not stay invisible."""
    real = packager._download

    async def first_write_fails(url: str) -> bytes:
        if url == SEED_URL:
            raise PackagingError("cannot write seed_frame.jpg: no space left", reason="disk_full")
        return await real(url)

    monkeypatch.setattr(packager, "_download", first_write_fails)
    env = make_env(tmp_path)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"), ok(CLIP_URL, task="job_clip")])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert env.disk_full is True
    assert record.status is AssetStatus.SUCCESS  # the chain continued on the Kie URL
    assert submit.of("clip")[0]["refs"].image_urls == [SEED_URL]
    assert not (folder.path / "seed_frame.jpg").exists()
    assert "seed_frame_not_stored" in env.log.types()


async def test_kie_out_of_credits_is_latched_and_packaged(tmp_path: Path) -> None:
    """FR-167 is a whole-run condition: latch it, package honestly, never retry a certainty."""
    env = make_env(tmp_path)
    entry, folder = make_entry(), make_folder(tmp_path)

    async def broke(*args: Any, **kwargs: Any) -> RenderOutcome:
        raise reel.render.KieOutOfCredits("HTTP 402")

    record = await reel.render_reel(entry, env, folder, submit=broke)

    assert env.credits_exhausted is True
    assert record.status is AssetStatus.FAILED
    assert "kie_credits_exhausted" in (record.skip_reason or "")
