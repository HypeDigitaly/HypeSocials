"""Reel-chain tests — the ORDER of the chain, and the degrades that must still deliver a clip.

**No motion reference (v2.0.0, topic-first pivot).** Virlo is a text-only topic feed now, so there
is no winning video to download: the chain is seed frame -> Seedance and nothing else, every job
goes out with an EMPTY `video_urls`, and every clip is billed at the provider's no-reference rate.
The yt-dlp prefetch, the bounded wait, the `reel_video_reference_url` meta field and the four
motion-chain degradation tags all lose their emitter here — this suite is where their absence is
asserted rather than assumed.

What replaces them is continuity (M13): the clip is built from the SAME copy, the SAME assigned
meta-style and the SAME wordmark string the seed frame was built from, so Seedance is told the
signature it must preserve is already in `@Image1` instead of being handed a brand block it is not
allowed to render. `reel_director.md` therefore allowlists no `{{branding_block}}` at all (§1.4).

**And no STYLE reference either (D46/F3, v2.1.0).** The meta-style's picture channel is excised,
so a seed frame renders text-to-image off the style's prose (FR-17/18) and an ordinary reel's
whole chain carries no attachment at all until the frame itself becomes `@Image1`. The only
pictures a reel can still carry are a campaign BRIEF's own product photos (FR-144/145) on the
seed frame, and that chained frame on the clip.

No network, no money: the injected `submit` is a recorder, `render.upload_file` hands back a
deterministic URL per file, the vision call is a stub and the packager's download is faked — all
inside `tmp_path`. `generate.Env` is deliberately NOT imported: `render_reel` must run against the
duck-typed surface, and the real dataclass loses four fields at this wave's wire-in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hypesocials import prompts_engine, render, styles
from hypesocials.config import BrandingConfig, Config
from hypesocials.generate import reel
from hypesocials.generate import refs as refs_module
from hypesocials.models import (
    AssetRecord,
    AssetStatus,
    Brief,
    CopySet,
    DegradationTag,
    LayoutZone,
    MetaStyle,
    ParsedResult,
    PlanEntry,
    PlanEntryStatus,
    RenderFailCause,
    RenderOutcome,
    RenderOutcomeKind,
    TrendItem,
    VisionCheckResult,
)
from hypesocials.outputs import AssetFolder, PackagingError, packager
from hypesocials.prompts_engine import PromptEngine

REPO = Path(__file__).resolve().parents[1]
#: Real magic bytes for the brief photos this suite writes — the one picture channel D46 left.
PNG = b"\x89PNG\r\n\x1a\n"
ASSET_ID = "Tt_reel_ai-tools_01"
STYLE_KEY = "anime-noir-statement"
BRIEF_NAME = "product-shot"
SEED_URL = "https://tempfile.aiquickdraw.com/seed.jpg"
SEED_URL_2 = "https://tempfile.aiquickdraw.com/seed-retry.jpg"
CLIP_URL = "https://tempfile.aiquickdraw.com/clip.mp4"
#: Sentinels planted in the registry entry, so "the frame and the clip describe one look" cannot
#: be satisfied by prose that happens to appear in both templates.
STYLE_PROMPT = "ZZSTYLE ink-wash noir cityscape, single warm rim light, deep blacks."
MOTION_PROFILE = "graphic"


# ------------------------------------------------------------------------------ doubles


class Recorder:
    """Stands in for `outputs.LogWriter`; keeps the payloads too, because FR-298's receipts are
    event DATA, not message prose."""

    def __init__(self, trace: list[str] | None = None) -> None:
        self.lines: list[tuple[str, str]] = []
        self.data: list[tuple[str, dict[str, Any]]] = []
        self.trace = trace if trace is not None else []

    def event(self, event_type: str, message: str = "", **data: Any) -> str:
        self.lines.append((event_type, message))
        self.data.append((event_type, data))
        return f"ev_{len(self.lines)}"

    warn = event
    error = event

    def types(self) -> list[str]:
        return [event_type for event_type, _ in self.lines]

    def payload(self, event_type: str) -> dict[str, Any]:
        return next(data for name, data in self.data if name == event_type)


@dataclass
class StubEnv:
    """The duck-typed `generate.Env` surface `render_reel` is allowed to touch.

    Built WITHOUT `style_briefs` / `brand_accent` / `brand_product_nouns` / `video_refs` and
    without `brief_for()`: those four fields and that method are deleted from the real `Env` at
    this wave's wire-in (contracts item 11).
    """

    config: Config
    run_dir: Path
    engine: PromptEngine
    log: Recorder
    trends: dict[str, TrendItem] = field(default_factory=dict)
    copy: dict[str, CopySet] = field(default_factory=dict)
    local_refs: dict[str, list[tuple[Path, str]]] = field(default_factory=dict)
    campaign_briefs: dict[str, Brief] = field(default_factory=dict)
    styles: Any = None  # `styles.StyleRegistry`
    branding: BrandingConfig = field(default_factory=BrandingConfig)
    niche_descriptor: str = ""
    niche_visual_world: str = ""
    llm_call: Any = None
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


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The packager's only network call; every render is downloaded through it."""
    async def download(url: str) -> bytes:
        return b"\xff\xd8fake-media-bytes"

    monkeypatch.setattr(packager, "_download", download)


@pytest.fixture(autouse=True)
def uploads(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """`render.upload_file`, faked — plus a CLEARED upload memo around every test (FR-200/244).

    A file that is not on disk RAISES, exactly as the real uploader does when it opens it, so the
    FR-18 loss path is exercised by deleting a brief's photos rather than by a second fake.
    """
    control = SimpleNamespace(paths=[])
    refs_module.reset_uploads()

    async def _upload(path: Path) -> str:
        control.paths.append(Path(path))
        if not Path(path).is_file():
            raise FileNotFoundError(path)
        return f"https://kie.test/upload/{Path(path).name}"

    monkeypatch.setattr(render, "upload_file", _upload)
    yield control
    refs_module.reset_uploads()


def ok(url: str, *, task: str, cost: float = 0.03) -> RenderOutcome:
    return RenderOutcome(kind=RenderOutcomeKind.SUCCESS, task_id=task, result_urls=[url],
                         cost_usd=cost, submitted_at="2026-08-09T10:00:00Z",
                         completed_at="2026-08-09T10:05:00Z")


def failed(cause: RenderFailCause, message: str = "", *, task: str = "job_fail",
           cost: float = 0.0) -> RenderOutcome:
    return RenderOutcome(kind=RenderOutcomeKind.FAIL, task_id=task, fail_cause=cause,
                         fail_message=message, cost_usd=cost)


def make_style(_tmp_path: Path | None = None) -> MetaStyle:
    """One TEXT-ONLY registry entry — the post-D46 shape (FR-17/18/290).

    `MetaStyle` has no `reference_images` field any more, so there are no files to write and no
    window to rotate: everything this style contributes to the frame and the director is prose.
    The `tmp_path` parameter is kept (unused) so the call sites still read as "a style built for
    this run's folder".
    """
    return MetaStyle(
        key=STYLE_KEY, render_prompt=STYLE_PROMPT, subject_mode="scene_fixed",
        layout_zones=[LayoutZone("upper third", "headline", "all caps, extra bold"),
                      LayoutZone("lower margin", "brand", "small caps", role="brand_slot")],
        format_affinity=["image", "reel"], motion_profile=MOTION_PROFILE,
        max_onimage_chars={"headline": 46, "subline": 0, "slide": 0},
        palette=["#0B0B0C", "#E8552F"], typography="extra-bold condensed sans",
        text_placement="headline upper third", image_treatment="ink wash",
        visual_pacing="one beat per frame",
        exclusions=["platform UI", "ZZEXCLUDE brand wordmark"])


def give_brief(env: StubEnv, entry: PlanEntry, tmp_path: Path, *, photos: int = 1) -> list[Path]:
    """Point this reel at a campaign brief that ships `photos` real files (FR-144/145).

    Post-D46 a brief's photos are the only pictures the seed frame can carry, which makes them
    the only fixture left that can prove FR-97's reference-drop retry actually drops something.
    """
    folder = tmp_path / "brief-photos"
    folder.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index in range(1, photos + 1):
        path = folder / f"{BRIEF_NAME}-{index:02d}.png"
        path.write_bytes(PNG + b"\x00" * 64)
        paths.append(path)
    env.campaign_briefs = {BRIEF_NAME: Brief(
        name=BRIEF_NAME, description="one product photo", influence="blend",
        visual_directives={"scene": "the product on a bare desk"},
        reference_image_paths=list(paths))}
    env.local_refs = {entry.asset_id: [(path, "brief") for path in paths]}
    entry.brief_name, entry.brief_influence = BRIEF_NAME, "blend"
    return paths


def upload_url(path: Path) -> str:
    """The URL the faked `render.upload_file` hands back for one local file."""
    return f"https://kie.test/upload/{path.name}"


def make_entry(**overrides: Any) -> PlanEntry:
    entry = PlanEntry(order=0, asset_id=ASSET_ID, creative_format="reel", platform="tiktok",
                      language="en", aspect_ratio="9:16", trend_key="t1", style_key=STYLE_KEY,
                      estimated_cost_usd=2.85)
    for key, value in overrides.items():
        setattr(entry, key, value)
    return entry


def make_env(tmp_path: Path, trace: list[str] | None = None, *,
             style: MetaStyle | None = None, **run_overrides: Any) -> StubEnv:
    config = Config()
    for key, value in run_overrides.items():
        setattr(config.run, key, value)
    env = StubEnv(config=config, run_dir=tmp_path, engine=PromptEngine(), log=Recorder(trace))
    env.trends = {"t1": TrendItem(
        history_key="t1", monitor_id="m1", name="AI tool stacks", topic_key="ai-tool-stacks",
        why_it_works="concrete numbers in the first line",
        hook_texts=["Nobody tells you this"], video_descriptions=["a creator lists seven tools"])}
    env.styles = styles.StyleRegistry(
        version=1, styles=[style if style is not None else make_style(tmp_path)],
        origin=str(REPO / "prompts" / "styles.yaml"), content_hash="0123456789ab")
    env.copy = {ASSET_ID: CopySet(asset_id=ASSET_ID, language="en", caption="Seven tools.",
                                  hashtags=["ai"], overlay_text="Nobody tells you this",
                                  through_line="a fast reveal of the tool stack",
                                  motion_beat="the hand sweeps the cards off the table")}
    return env


def make_folder(tmp_path: Path) -> AssetFolder:
    return AssetFolder(tmp_path, AssetRecord(asset_id=ASSET_ID, source="t1",
                                             source_name="AI tool stacks", platform="tiktok",
                                             creative_format="reel"))


# ------------------------------------------------- no motion reference (operator decision 1)


async def test_no_job_in_the_chain_ever_carries_a_video_reference(tmp_path: Path) -> None:
    """The pivot's hardest edge on this path: Virlo is text-only, so nothing downloads a winning
    video and every submission goes out with an EMPTY `video_urls` — which is also what makes the
    clip billable at the provider's no-reference rate (20 §8)."""
    env = make_env(tmp_path)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"), ok(CLIP_URL, task="job_clip", cost=2.85)])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert submit.calls, "the chain has to have ordered something for this to mean anything"
    for call in submit.calls:
        assert call["refs"].video_urls == [], f"{call['job']} carried a video reference"
    assert submit.of("clip")[0]["refs"].image_urls == [SEED_URL], "FR-24: @Image1 and nothing else"
    assert record.status is AssetStatus.SUCCESS


async def test_the_delivered_reel_records_no_video_reference_url(tmp_path: Path) -> None:
    """`reel_video_reference_url` keeps its schema slot (FR-73 stays fixed) and ships its default:
    nothing writes it any more, so a meta.yaml claiming a motion reference would be a lie."""
    env = make_env(tmp_path)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"), ok(CLIP_URL, task="job_clip", cost=2.85)])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert record.reel_video_reference_url is None
    assert packager.read_meta(folder.path).get("reel_video_reference_url") is None


def test_the_module_carries_no_motion_reference_machinery_at_all() -> None:
    """The dead prompt weight F24 deletes is dead CODE here too: a surviving prefetch symbol, a
    surviving wait constant or a surviving `video_urls=` argument is how "no motion reference"
    quietly becomes "no motion reference on the happy path"."""
    import inspect

    surviving = sorted(name for name in dir(reel)
                       if "video_ref" in name.lower() or "motion_reference" in name.lower()
                       or "yt_dlp" in name.lower() or name == "VIDEO_REF_WAIT_S")
    source = inspect.getsource(reel)

    assert surviving == []
    assert "video_urls=" not in source, "the chain names a field it must never fill"
    assert "no motion reference" in reel.__doc__.lower(), \
        "the module contract has to SAY it, or the next reader re-adds the chain"


async def test_the_clip_is_ordered_as_precommitted_wave_two_work_with_no_reference_seconds(
    tmp_path: Path,
) -> None:
    """FR-106b: every clip this chain orders is pre-committed, and the params carry only what the
    provider bills — duration, resolution, audio — with no reference-seconds allowance anywhere."""
    env = make_env(tmp_path)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"), ok(CLIP_URL, task="job_clip", cost=2.85)])

    await reel.render_reel(entry, env, folder, submit=submit)

    clip = submit.of("clip")[0]
    assert clip["kind"] == "precommitted"
    assert clip["params"].duration_s == env.config.run.reel_duration_s
    assert clip["params"].aspect_ratio == "9:16"  # explicit; `adaptive` is never sent (FR-23)
    assert clip["params"].generate_audio is True
    assert not hasattr(clip["params"], "reference_seconds")


# ------------------------------------------------------------------ M13 continuity (§1.4/F24)


async def test_the_seed_frame_and_the_clip_describe_one_look_and_one_copy(tmp_path: Path) -> None:
    """M13: with no motion reference, continuity IS the contract. The frame and the director are
    built from the same assigned meta-style and the same `CopySet`, so the two prompts cannot
    describe two different reels — the style's own sentence reaches the frame, its
    `motion_profile` reaches the director, and the copy's one named beat reaches Stage 2 (F24)."""
    style = make_style(tmp_path)
    env = make_env(tmp_path, style=style)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"), ok(CLIP_URL, task="job_clip", cost=2.85)])

    await reel.render_reel(entry, env, folder, submit=submit)

    seed = submit.of("seed_frame")[0]["params"].prompt
    clip = submit.of("clip")[0]["params"].prompt
    assert STYLE_PROMPT in seed, "the frame renders the assigned house style"
    assert "Nobody tells you this" in seed and "Nobody tells you this" in clip, \
        "one copy: the hook the frame burns in is the text the clip is told to preserve"
    assert MOTION_PROFILE in clip, "F24: the registry's motion profile selects the LOOK paragraph"
    assert "the hand sweeps the cards off the table" in clip, "F24: the copy's one named beat"
    assert prompts_engine.beats_for(env.config.run.reel_duration_s) in clip, \
        "F24a: real-second beats computed from the duration this chain also bills"
    assert "ZZEXCLUDE brand wordmark" in clip, "the style's literal exclusions travel to both roles"


async def test_the_director_role_is_never_handed_a_branding_block(tmp_path: Path) -> None:
    """§1.4: `{{branding_block}}` is for the gpt-image-2 render roles. Seedance is not asked to
    render a signature — it is told the one in `@Image1` must persist unchanged (M13), and the
    wordmark travels for both roles inside `{{onimage_text}}`."""
    env = make_env(tmp_path)
    env.branding = BrandingConfig(brand="hypelead")
    entry, folder = make_entry(branded=True), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"), ok(CLIP_URL, task="job_clip", cost=2.85)])

    await reel.render_reel(entry, env, folder, submit=submit)

    seed = submit.of("seed_frame")[0]["params"].prompt
    clip = submit.of("clip")[0]["params"].prompt
    assert "branding_block" not in prompts_engine.allowlist(reel.CLIP_TEMPLATE)
    assert "branding_block" in prompts_engine.allowlist(reel.SEED_TEMPLATE)
    assert "#0FCFC4" in seed, "the frame gets FR-292's colour channel"
    assert "#0FCFC4" not in clip, "the director role dropped it as an out-of-role name"
    assert "HypeLead" in seed and "HypeLead" in clip, "B1/M13: the wordmark is TEXT-block, both"


async def test_an_unbranded_reel_is_told_its_signature_zone_is_empty(tmp_path: Path) -> None:
    """M11 — a described-but-empty brand slot is the top hallucination site, so the style's
    `role: brand_slot` zone is emitted only when the creative is branded, and the frame is told
    in one line that its lower margin is empty."""
    env = make_env(tmp_path)
    env.branding = BrandingConfig(brand="hypelead")
    entry, folder = make_entry(branded=False), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"), ok(CLIP_URL, task="job_clip")])

    await reel.render_reel(entry, env, folder, submit=submit)

    seed = submit.of("seed_frame")[0]["params"].prompt
    assert "HypeLead" not in seed and "#0FCFC4" not in seed
    assert "carries no signature zone" in seed
    assert "upper third" in seed, "the style's other zones are unaffected"


async def test_a_text_free_clip_is_the_only_unsigned_one(tmp_path: Path) -> None:
    """`signed` is False for exactly one shape: `reel_overlay_text: none`, a clip with no
    lettering at all. A frame with no words must not be handed a signature to preserve — there is
    nothing for M13's continuity rule to keep — so neither channel reaches the director."""
    env = make_env(tmp_path, reel_overlay_text="none")
    env.branding = BrandingConfig(brand="hypelead")
    entry, folder = make_entry(branded=True), make_folder(tmp_path)
    submit = Submitter([ok(CLIP_URL, task="job_clip", cost=2.85)])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    clip = submit.of("clip")[0]["params"].prompt
    assert submit.of("seed_frame") == [], "`none` skips the frame entirely (FR-24)"
    assert "HypeLead" not in clip and "#0FCFC4" not in clip
    assert "Nobody tells you this" not in clip, "the overlay copy is cleared for a clean clip"
    assert "keep every frame free" in clip
    assert record.status is AssetStatus.SUCCESS


async def test_a_signed_reel_carries_the_wordmark_into_both_prompts(tmp_path: Path) -> None:
    """The other side of the same switch: when the clip DOES carry text, both roles get the same
    wordmark string — the frame burns it in, the director is told it is already there."""
    env = make_env(tmp_path)
    env.branding = BrandingConfig(brand="hypedigitaly")
    entry, folder = make_entry(branded=True), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"), ok(CLIP_URL, task="job_clip")])

    await reel.render_reel(entry, env, folder, submit=submit)

    assert "HypeDigitaly" in submit.of("seed_frame")[0]["params"].prompt
    assert "HypeDigitaly" in submit.of("clip")[0]["params"].prompt


# ------------------------------------------------------------------------------ FR-105 ordering


async def test_fr105_seed_frame_checked_before_seedance_submission(tmp_path: Path) -> None:
    """The seed frame is a CHAINED artifact: checking it after the clip is submitted would mean
    discovering a broken headline one paid video too late (FR-105)."""
    trace: list[str] = []
    env = make_env(tmp_path, trace, vision_check=True)
    env.llm_call = vision(trace, False)
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
    # FR-72/76: the paid seed frame is both an asset and the gallery's poster.
    assert (folder.path / "seed_frame.jpg").is_file()
    assert (folder.path / "reel.mp4").is_file()
    seed_call, clip_call = submit.of("seed_frame")[0], submit.of("clip")[0]
    assert seed_call["params"].aspect_ratio == "9:16"  # FR-21: never the platform image ratio
    assert seed_call["kind"] == "projected" and clip_call["kind"] == "precommitted"  # FR-106 a/b


async def test_the_delivered_event_names_whether_a_seed_frame_was_paid_for(
    tmp_path: Path,
) -> None:
    """FR-298's receipt half: `creative_delivered` says `seed_frame=` so a reel's cost can be
    reconciled from the event stream alone — one render or two.

    The degraded half scripts TWO frame failures, not one: the seed frame is an image job, so
    FR-317 (v2.1.3/D48) spends one automatic resubmit on it before the reel gives up. Scripting a
    single failure would have the resubmit consume the CLIP's queued outcome and deliver a frame,
    which is a different test.
    """
    env = make_env(tmp_path)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"), ok(CLIP_URL, task="job_clip", cost=2.85)])

    await reel.render_reel(entry, env, folder, submit=submit)
    assert env.log.payload("creative_delivered")["seed_frame"] is True

    degraded_env = make_env(tmp_path / "second")
    (tmp_path / "second").mkdir(exist_ok=True)
    degraded = Submitter([failed(RenderFailCause.PROVIDER_FAIL, "renderer exploded", cost=0.03),
                          failed(RenderFailCause.PROVIDER_FAIL, "renderer exploded again",
                                 cost=0.03),
                          ok(CLIP_URL, task="job_clip", cost=2.85)])

    await reel.render_reel(make_entry(), degraded_env, make_folder(tmp_path / "second"),
                           submit=degraded)
    assert degraded_env.log.payload("creative_delivered")["seed_frame"] is False
    assert len(degraded.of("seed_frame")) == 2, "one resubmit, and a second failure is final"


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
    FR-97's reference strip — the seed frame is the whole point of the render."""
    env = make_env(tmp_path)
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
    assert clips[1]["refs"].video_urls == []  # …and there was never a video one to keep
    assert clips[1]["kind"] == "precommitted"  # the failed attempt was billed $0 (RESULTS.md §C)
    assert DegradationTag.AUDIO_DROPPED_CONTENT_AUDIT in record.degradations
    assert record.reel_audio is False  # meta tells the final truth
    assert record.status is AssetStatus.SUCCESS
    assert record.kie_job_ids == ["job_seed", "job_audit", "job_clip"]


# ------------------------------------------------------------------------------ FR-24 degrades


async def test_seed_frame_render_failure_degrades_to_in_model_overlay_text(
    tmp_path: Path,
) -> None:
    """FR-24 / 10 §10: a lost seed frame costs legibility, not a clip. The hook moves into the
    video model, the clip is still ordered on the SAME copy and the SAME style, and every failed
    frame attempt is still billed.

    "Lost" now means lost TWICE. FR-317 (v2.1.3/D48) gives the frame one automatic resubmit
    because the whole reel is built on it, so the degradation this test is about only happens
    after the second attempt fails as well — and that is the intent preserved, not weakened: the
    script fails both so the in-model overlay path is still what gets exercised.
    """
    env = make_env(tmp_path)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([failed(RenderFailCause.PROVIDER_FAIL, "renderer exploded", cost=0.03),
                        failed(RenderFailCause.PROVIDER_FAIL, "renderer exploded again",
                               cost=0.03),
                        ok(CLIP_URL, task="job_clip", cost=2.85)])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert DegradationTag.SEED_FRAME_RENDER_FAILED in record.degradations
    frames = submit.of("seed_frame")
    assert [call["kind"] for call in frames] == ["projected", "discretionary"], \
        "FR-317's resubmit is discretionary spend the cap may decline (FR-106c)"
    assert "image_job_resubmit" in env.log.types()
    clip = submit.of("clip")[0]
    assert clip["refs"].image_urls == [] and clip["refs"].video_urls == []
    assert "hook text" in clip["params"].prompt  # the overlay moved into the video model
    assert MOTION_PROFILE in clip["params"].prompt, "the style survives its frame"
    assert record.status is AssetStatus.SUCCESS
    assert (folder.path / "reel.mp4").is_file()
    assert record.actual_cost_usd == pytest.approx(2.91)  # both dead frames were still billed


async def test_seed_url_rejection_is_named_but_never_buys_a_second_clip(tmp_path: Path) -> None:
    """20 §10's second seed-frame row is DETECTED and logged — and that is all it does.

    The resubmission that used to follow was a third paid Seedance clip on a heuristic string
    match, outside 20 §8's two sanctioned resubmissions; the operator deleted it (2026-08-10).
    What must survive is the diagnosis: exactly one clip ordered, the tag on the record, the
    named log line, and an honest terminal failure that keeps every paid artifact (FR-74).
    """
    env = make_env(tmp_path)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([
        ok(SEED_URL, task="job_seed"),
        failed(RenderFailCause.PROVIDER_FAIL, "reference image url could not be downloaded",
               task="job_clip"),
        ok(CLIP_URL, task="job_clip_never_ordered"),  # must stay in the queue
    ])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert len(submit.of("clip")) == 1  # no second ~$4.75 clip, ever
    assert "seed_frame_url_unreachable" in env.log.types()  # the diagnosis survives
    assert DegradationTag.SEED_FRAME_URL_UNREACHABLE in record.degradations
    assert record.status is AssetStatus.FAILED
    assert "reference image url could not be downloaded" in (record.skip_reason or "")
    assert entry.status is PlanEntryStatus.FAILED
    assert (folder.path / "seed_frame.jpg").is_file()  # the paid frame is still packaged (FR-74)
    assert not (folder.path / "reel.mp4").exists()


async def test_moderation_refusal_on_the_seed_frame_retries_reference_free(
    tmp_path: Path,
) -> None:
    """FR-97 still applies to the seed frame: one reference-free retry, then the chain continues.

    Post-D46 the references it drops are a campaign BRIEF's own photos — the only pictures a
    seed frame can carry now that a meta-style ships none (F3).
    """
    env = make_env(tmp_path)
    entry, folder = make_entry(), make_folder(tmp_path)
    (photo,) = give_brief(env, entry, tmp_path)
    submit = Submitter([failed(RenderFailCause.MODERATION, "content policy"),
                        ok(SEED_URL, task="job_seed_retry"), ok(CLIP_URL, task="job_clip")])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    seeds = submit.of("seed_frame")
    assert seeds[0]["refs"].image_urls == [upload_url(photo)]
    assert seeds[1]["refs"].image_urls == [] and seeds[1]["kind"] == "discretionary"
    assert DegradationTag.REFS_DROPPED_MODERATION in record.degradations
    assert record.status is AssetStatus.SUCCESS


async def test_a_refused_reference_free_seed_frame_is_never_resubmitted(tmp_path: Path) -> None:
    """FR-97's remedy is dropping references, so a frame that carried NONE has no remedy left.

    Post-D46 that is the ordinary reel: no brief, a text-only style, an empty `image_urls`. A
    second identical submission to the same moderation endpoint would buy a second refusal at
    full price and call it a retry — so the refusal is terminal, and the chain degrades to the
    in-model overlay path exactly as any other lost frame does (FR-24).
    """
    env = make_env(tmp_path)
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([failed(RenderFailCause.MODERATION, "content policy"),
                        ok(CLIP_URL, task="job_clip", cost=2.85)])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert len(submit.of("seed_frame")) == 1, "no second frame was ever ordered"
    assert submit.of("seed_frame")[0]["refs"].image_urls == []
    assert "moderation_retry" not in env.log.types()
    assert DegradationTag.REFS_DROPPED_MODERATION not in record.degradations
    assert DegradationTag.SEED_FRAME_RENDER_FAILED in record.degradations
    assert record.status is AssetStatus.SUCCESS, "a lost frame costs legibility, not a clip"


async def test_a_text_only_style_renders_the_reel_and_says_nothing_about_it(
    tmp_path: Path, uploads: SimpleNamespace,
) -> None:
    """D46/FR-17/18: a meta-style is words, so the seed frame renders text-to-image and that is
    the intended route rather than a degrade.

    Nothing is uploaded, `image_urls` is empty, and the record carries NO tag about it — this
    creative expected no picture and lost none. The style's own sentence still reaches the frame,
    which is the whole point: the look travels as prose.
    """
    env = make_env(tmp_path, style=make_style(tmp_path))
    entry, folder = make_entry(), make_folder(tmp_path)
    submit = Submitter([ok(SEED_URL, task="job_seed"), ok(CLIP_URL, task="job_clip")])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert uploads.paths == [], "a meta-style ships no pixels (F3)"
    assert submit.of("seed_frame")[0]["refs"].image_urls == []
    assert STYLE_PROMPT in submit.of("seed_frame")[0]["params"].prompt
    assert DegradationTag.STYLE_REFS_MISSING not in record.degradations, \
        "the tag survives for old meta.yaml files on disk; nothing emits it any more"
    assert DegradationTag.REFERENCE_FREE not in record.degradations
    assert "reference_free" not in env.log.types()
    assert record.status is AssetStatus.SUCCESS


async def test_a_brief_whose_pictures_are_all_gone_still_renders_the_reel(tmp_path: Path) -> None:
    """FR-18: brief images are an input, not a prerequisite — the frame still renders on the
    style's written guidance. But this creative EXPECTED pictures and lost every one of them, so
    the absence is tagged and logged, which is the one shape that still earns `reference_free`.
    """
    env = make_env(tmp_path)
    entry, folder = make_entry(), make_folder(tmp_path)
    for path in give_brief(env, entry, tmp_path, photos=2):
        path.unlink()
    submit = Submitter([ok(SEED_URL, task="job_seed"), ok(CLIP_URL, task="job_clip")])

    record = await reel.render_reel(entry, env, folder, submit=submit)

    assert submit.of("seed_frame")[0]["refs"].image_urls == []
    assert DegradationTag.REFERENCE_FREE in record.degradations
    assert DegradationTag.STYLE_REFS_MISSING not in record.degradations
    assert "reference_free" in env.log.types()
    assert STYLE_PROMPT in submit.of("seed_frame")[0]["params"].prompt
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
