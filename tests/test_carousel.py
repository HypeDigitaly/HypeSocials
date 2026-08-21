"""Carousel tests — the anchor chain, FR-105's ordering, and the deck's ONE assigned house style.

Post-pivot (v2.0.0) a deck's look is not analysed per trend any more: `styles.assign_styles` has
already written a `style_key` on the entry, `refs.style_of` resolves it against the run's registry,
and that single `MetaStyle` is what `{{style_dna}}`, `{{render_prompt}}` and `{{exclusions}}` are
built from (FR-290/291).

**A style is words, never pictures (D46/F3, v2.1.0).** The registry's reference-image channel is
excised: a deck qualifies its render through the style's prose, so an ordinary carousel submits
slide 1 with an EMPTY `image_urls` and that is the intended route, not a degradation (FR-17/18).
Exactly two kinds of picture can still reach a slide: a campaign BRIEF's own product photos
(FR-144/145), and the chained artifact this deck made itself — the finished slide 1 that slides
2–N reproduce (FR-95). Both are pinned below; nothing else may appear.

Three consequences of the assigned-style design are pinned here:

* **`{{style_dna}}` is built ONCE per deck and repeated byte for byte** (FR-189/M9) — and it is the
  FIVE DNA fields only, with the old zone-derived `layout_grid` row gone (contracts item 12);
* **cover-versus-body divergence lives in `per_format_guidance`** — slide 1 renders under
  `carousel_cover`, slides 2–N under `carousel_slide`, appended to the style's own `render_prompt`.
  That is the one block a deck is ALLOWED to vary, which is what lets the DNA stay identical;
* **the signature rides the anchor alone** (M12) — a deck signed once reads as designed, signed N
  times it reads as a watermark, so `branding_block` and the TEXT-block `wordmark` go to slide 1
  and `carousel_anchor_instruction.md` tells slides 2–N never to refill the zone.

No network and no money: `submit` is a fake matching the pinned protocol `generate.carousel.Submit`,
`render.upload_file` is a fake that hands back a deterministic URL per file, the vision check rides
a fake `models.StructuredCall`, and the packager's download is monkeypatched so real `AssetFolder`
files and a real `meta.yaml` still land on disk — all inside `tmp_path`. `Env` is a local
duck-typed stub on purpose: `generate.Env` loses four fields at this wave's wire-in and these tests
must not care.
"""

from __future__ import annotations

import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from PIL import Image

from hypesocials import cover_pick, gauntlet, prompts_engine as pe, render, styles
from hypesocials.config import BrandingConfig, Config, PlatformConfig
from hypesocials.generate import carousel as carousel_module
from hypesocials.generate import refs as refs_module
from hypesocials.generate.carousel import GUIDANCE_COVER, GUIDANCE_SLIDE, render_carousel
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
    RenderPriority,
    SourcePost,
    TrendItem,
    VisionCheckResult,
)
from hypesocials.outputs import AssetFolder, PackagingError, packager
from hypesocials.prompts_engine import PromptEngine, style_dna
from hypesocials.sources import mark_names
from hypesocials.sources.slide_intel import MarkBox, SlideIntel, SourceSlide
from hypesocials.render import KieOutOfCredits

REPO = Path(__file__).resolve().parents[1]
#: Real magic bytes for the brief photos this suite writes — the one picture channel D46 left.
PNG = b"\x89PNG\r\n\x1a\n"
STYLE_KEY = "editorial-voxel-carousel"
BRIEF_NAME = "product-shot"
#: Sentinels, so an assertion about WHICH guidance landed cannot be satisfied by prose that
#: happens to appear in both halves of the registry entry.
COVER_GUIDANCE = "ZZCOVER one full-bleed statement, no page number, no list."
SLIDE_GUIDANCE = "ZZBODY numbered page, the headline pinned to the top edge."
_SLIDE_NO = re.compile(r"slide (\d+)")


# --------------------------------------------------------------------------------- fake seams


@dataclass(slots=True)
class Call:
    """One recorded `submit` call — everything a money/ordering assertion needs."""

    index: int
    slide: int
    job: str
    priority: RenderPriority
    kind: str
    label: str
    prompt: str
    image_urls: list[str]
    #: D60/FR-342 — the render TIER this slide was submitted at, straight off `RenderParams`.
    #: Defaulted and last so every positional/keyword construction above it still holds; empty
    #: means the deck sent no resolution at all, which is what a pre-FR-342 submission looked
    #: like and is exactly the regression the test at the foot of this file watches for.
    resolution: str = ""

    @property
    def url(self) -> str:
        return f"https://kie.test/slide-{self.slide}-{self.index}.jpg"


class FakeSubmit:
    """T4.3's metered submission door, faked: records every call and answers from a rule."""

    def __init__(self, rule: Any = None, events: list[str] | None = None) -> None:
        self.rule = rule
        self.calls: list[Call] = []
        self.events = events if events is not None else []

    async def __call__(self, entry, params, refs, *, job, priority, kind, label):
        match = _SLIDE_NO.search(label)
        call = Call(index=len(self.calls), slide=int(match.group(1)) if match else 0, job=job,
                    priority=priority, kind=kind, label=label, prompt=params.prompt,
                    image_urls=list(refs.image_urls),
                    resolution=str(getattr(params, "resolution", "") or ""))
        self.calls.append(call)
        self.events.append(f"submit:{call.slide}:{kind}")
        answer = self.rule(call) if self.rule is not None else ok(call)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def slide(self, number: int) -> Call:
        return next(call for call in self.calls if call.slide == number)


def ok(call: Call, cost: float = 0.03) -> RenderOutcome:
    return RenderOutcome(kind=RenderOutcomeKind.SUCCESS, task_id=f"kie_{call.index}",
                         request_token=f"tok_{call.index}", result_urls=[call.url], cost_usd=cost,
                         submitted_at=f"2026-08-09T10:0{call.index}:00Z",
                         completed_at=f"2026-08-09T10:1{call.index}:00Z")


def failed(cause: RenderFailCause = RenderFailCause.PROVIDER_FAIL, cost: float = 0.03
           ) -> RenderOutcome:
    return RenderOutcome(kind=RenderOutcomeKind.FAIL, task_id="kie_fail", fail_cause=cause,
                         fail_message="provider said no", cost_usd=cost)


class CriticStub:
    """A `models.StructuredCall` answering the GAUNTLET's per-critic schema from a fail table.

    `rounds` is one entry per call made to the critic that OWNS `code` — a set of 1-based
    ATTACHMENT SLOTS that fail in that round. Keying on the owning critic is what makes the table
    round-accurate without the stub having to model FR-324's scoping: all three critics run
    concurrently every round, but only one of them can emit a given code (the per-critic enums are
    a partition), so "the second time `brief` was asked" IS "round 2".

    `code` therefore selects both the defect and the critic that reports it: `invented_text` is
    leakage (`brief`, always blocks), `style_layout` is contract (`system`), `contrast` is craft
    (ships unless `craft_blocks`). `unavailable` makes a critic answer unusably, which is how the
    degraded-gate path is exercised.
    """

    def __init__(self, rounds: list[set[int]] | None = None, events: list[str] | None = None,
                 code: str = "garbled", detail: str = "doubled type",
                 confidence: str = "high", unavailable: Sequence[str] = ()) -> None:
        self.rounds = [set(entry) for entry in (rounds or [])]
        self.code = code
        self.detail = detail
        self.confidence = confidence
        self.unavailable = set(unavailable)
        self.calls: list[int] = []  # frames attached, per call, in order
        self.critics: list[str] = []  # which critic each call was
        self.roles: list[str] = []  # the LLM role each call rode
        self.systems: list[str] = []  # each call's rendered critic prompt
        self.events = events if events is not None else []
        self._owner_calls = 0

    @property
    def owner(self) -> str:
        """The one critic whose enum carries `code` — the partition makes this unambiguous."""
        return next(name for name, codes in gauntlet.CRITIC_CODES.items() if self.code in codes)

    @property
    def rounds_run(self) -> int:
        """How many rounds actually judged — one per call to the owning critic."""
        return self._owner_calls

    def frames_for(self, critic: str) -> list[int]:
        """How many frames each of that critic's calls carried, in order (FR-324's scoping)."""
        return [count for count, name in zip(self.calls, self.critics) if name == critic]

    def prompt_for(self, critic: str, index: int = 0) -> str:
        """That critic's rendered system prompt on its `index`-th call — the contract on the wire."""
        return [system for system, name in zip(self.systems, self.critics)
                if name == critic][index]

    async def __call__(self, role, messages, json_schema, images=None) -> ParsedResult:
        name = str(json_schema["name"]).removeprefix("gauntlet_")
        count = len(images or [])
        self.calls.append(count)
        self.critics.append(name)
        self.roles.append(role)
        self.systems.append(next(m["content"] for m in messages if m["role"] == "system"))
        self.events.append(f"critic:{name}:{count}")
        if name in self.unavailable:
            return ParsedResult(parsed=None, raw_text="not json at all", degraded=True,
                                reason="the critic returned prose")
        failing: set[int] = set()
        if name == self.owner:
            index, self._owner_calls = self._owner_calls, self._owner_calls + 1
            failing = self.rounds[index] if index < len(self.rounds) else set()
        return ParsedResult(parsed={"frames": [
            {"frame": slot, "pass": slot not in failing,
             "defects": ([{"code": self.code, "zone": "middle", "confidence": self.confidence,
                           "detail": self.detail}] if slot in failing else [])}
            for slot in range(1, count + 1)]}, raw_text="{}")


class Log:
    """`outputs.LogWriter`'s three call shapes, remembering only what tests assert on."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []
        #: The STRUCTURED half of each line, kept beside `records` rather than folded into it:
        #: several assertions here unpack `records` as pairs, and a warning's data fields
        #: (`missing_slide_numbers`, `detail`) are what an operator reading events.jsonl actually
        #: consumes — a truncation that never touches the message is invisible without this.
        self.data: list[tuple[str, dict[str, Any]]] = []

    def event(self, event_type: str, message: str = "", **data: Any) -> str:
        self.records.append((event_type, message))
        self.data.append((event_type, data))
        return f"ev_{len(self.records):04d}"

    warn = event
    error = event

    def types(self) -> list[str]:
        return [event_type for event_type, _ in self.records]

    def fields(self, event_type: str) -> dict[str, Any]:
        """The structured fields of the LAST line of this type, or `{}` if it never fired."""
        return next((data for name, data in reversed(self.data) if name == event_type), {})


@dataclass
class Env:
    """Duck-typed stand-in for `generate.Env` — exactly the fields carousel.py reads.

    Deliberately built WITHOUT `style_briefs` / `brand_accent` / `brand_product_nouns` /
    `video_refs` and without a `brief_for()` method: those four fields and that method are deleted
    from the real `Env` at this wave's wire-in (contracts item 11), and a stub that still carried
    them would be describing a shape nothing has.
    """

    config: Config
    run_dir: Path
    engine: PromptEngine
    log: Log
    trends: dict[str, Any] = field(default_factory=dict)
    copy: dict[str, CopySet] = field(default_factory=dict)
    local_refs: dict[str, list[tuple[Path, str]]] = field(default_factory=dict)
    campaign_briefs: dict[str, Brief] = field(default_factory=dict)
    styles: Any = None  # `styles.StyleRegistry` — the post-pivot visual authority
    branding: BrandingConfig = field(default_factory=BrandingConfig)
    niche_descriptor: str = "Audience: founders · Vibe: blunt"
    niche_visual_world: str = ""
    llm_call: Any = None
    halted: bool = False
    credits_exhausted: bool = False
    disk_full: bool = False


# ------------------------------------------------------------------------------------ fixtures


def blob_for(url: str) -> bytes:
    """The bytes BOTH fakes hand back for one render URL — the download and the frame loader.

    One function on purpose (D62/FR-351): `covers/cover_candidate_2.jpg` is written from the frame
    loader's bytes and `slide_01.jpg` from the packager's download of the same URL, so a test can
    only assert "the chosen candidate is the slide that shipped" if the two fakes agree about what
    that URL contains. Real JPEG magic in front, because `generate.pixels` sniffs the header.
    """
    return b"\xff\xd8" + url.encode("utf-8")


@pytest.fixture
def frames(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """`vision_check.load_images`, faked at the door `carousel.py` imports it through (FR-351).

    Answers with `blob_for(url)` and the 1-based position each blob came from, which is the real
    loader's contract. `drop` is the half that matters: a URL listed there is left out of BOTH
    returns, exactly as an unreadable source is dropped rather than shifted — the case that would
    otherwise re-label every candidate behind it and anchor the deck to the wrong render.
    """
    control = SimpleNamespace(asked=[], drop=set())

    async def _load(sources, log=None):
        urls = [str(source) for source in sources]
        control.asked.append(urls)
        kept = [(position, url) for position, url in enumerate(urls, start=1)
                if url not in control.drop]
        return [blob_for(url) for _, url in kept], [position for position, _ in kept]

    monkeypatch.setattr(carousel_module, "load_images", _load)
    return control


class PickStub:
    """`cover_pick.pick`, faked — records the brief it was handed and answers from a fixed verdict.

    Wave 6a owns the real call; until it lands every genuine `pick()` reports itself unavailable,
    so a test that wants to exercise the CHOSEN path has to stand in for it. The recorded
    `candidates` and `brief` are what pin the contract this module is responsible for: the ids it
    numbers the candidates with, the native bytes it attaches, and the strings the cover was
    ordered to carry.
    """

    def __init__(self, chosen: int = 1, reason: str = "the cleanest type hierarchy",
                 degraded: bool = False) -> None:
        self.chosen, self.reason, self.degraded = chosen, reason, degraded
        self.candidates: list[list[cover_pick.CoverCandidate]] = []
        self.briefs: list[cover_pick.CoverBrief] = []

    async def __call__(self, candidates, brief, cfg, llm) -> cover_pick.Pick:
        self.candidates.append(list(candidates))
        self.briefs.append(brief)
        return cover_pick.Pick(chosen=self.chosen, reason=self.reason, degraded=self.degraded)


@pytest.fixture(autouse=True)
def downloads(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Every `store_render` writes real bytes to a real folder; nothing touches the network."""
    #: `per_url` (D62/FR-351) makes the stored bytes name their own URL, which is the only way to
    #: assert WHICH of three identical-looking cover candidates became `slide_01`. Off by default
    #: so every test written before the cover pick keeps the exact bytes it always got.
    control = SimpleNamespace(fetched=[], fail_contains="", fail_reason="download_failed",
                              per_url=False)

    async def _download(url: str) -> bytes:
        control.fetched.append(url)
        if control.fail_contains and control.fail_contains in url:
            raise PackagingError(f"download failed: {control.fail_reason}",
                                 reason=control.fail_reason)
        return blob_for(url) if control.per_url else b"\xff\xd8fake-jpeg-bytes"

    monkeypatch.setattr(packager, "_download", _download)
    return control


@pytest.fixture(autouse=True)
def uploads(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """`render.upload_file`, faked — plus a CLEARED upload memo around every test.

    The memo is keyed by `run_dir` and lives for the process, which is exactly right for a run and
    exactly wrong for a suite: `tmp_path` differs per test, but a leaked memo would still let one
    test's assertion about "uploaded once" be satisfied by another test's upload.

    A file that is not on disk RAISES, exactly as the real uploader does when it opens it — that
    is what makes the FR-18 loss path testable by deleting a brief's photos rather than by
    monkeypatching a second layer of fake on top of this one.
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


def upload_url(path: Path) -> str:
    """The URL the faked `render.upload_file` hands back for one local file."""
    return f"https://kie.test/upload/{path.name}"


def make_style(_tmp_path: Path | None = None, *, guidance: bool = True,
               key: str = STYLE_KEY) -> MetaStyle:
    """One TEXT-ONLY registry entry — the post-D46 shape (FR-17/18/290).

    `MetaStyle` has no `reference_images` field any more, so there is no file scaffolding to
    build and no window to rotate: everything this style contributes to a slide is prose. The
    `tmp_path` parameter is kept (unused) so every call site still reads as "a style built for
    this run's folder" and the diff against the pre-D46 suite stays readable.
    """
    return MetaStyle(
        key=key,
        render_prompt="Isometric voxel diorama on a flat teal ground, hard shadow, wide margins.",
        subject_mode="scene_open",
        layout_zones=[LayoutZone("ZZZONE top band", "headline", "bold, sentence case"),
                      LayoutZone("lower margin", "brand", "small caps", role="brand_slot")],
        format_affinity=["image", "carousel"],
        text_density="high",
        max_onimage_chars={"headline": 90, "subline": 60, "slide": 90},
        palette=["#1B1F3B", "#F4C95D"],
        typography="bold condensed sans",
        text_placement="headline upper third",
        image_treatment="flat graphic, hard shadow",
        visual_pacing="one idea per panel",
        per_format_guidance=({GUIDANCE_COVER: COVER_GUIDANCE, GUIDANCE_SLIDE: SLIDE_GUIDANCE}
                             if guidance else {}),
        exclusions=["platform UI", "engagement counters"])


def make_registry(*entries: MetaStyle) -> styles.StyleRegistry:
    return styles.StyleRegistry(version=1, styles=list(entries),
                                origin=str(REPO / "prompts" / "styles.yaml"),
                                content_hash="0123456789ab")


def make_entry(slides: int = 4, **overrides: Any) -> PlanEntry:
    entry = PlanEntry(order=0, asset_id="0001_carousel_linkedin", creative_format="carousel",
                      platform="linkedin", language="en", aspect_ratio="1:1",
                      trend_key="t1", style_key=STYLE_KEY, slide_count=slides,
                      estimated_cost_usd=0.15)
    for key, value in overrides.items():
        setattr(entry, key, value)
    return entry


def make_trends(*, panels: int = 3, post_id: str = "post-a",
                trend_key: str = "t1") -> dict[str, TrendItem]:
    """`env.trends` carrying the SOURCE deck this entry was bound to at ASSIGN (FR-304).

    The join is `entry.trend_key` -> topic -> the post whose id is `entry.source_post_id`, which is
    the same join the gallery's provenance card makes; `panels` is the source's own panel count,
    the number `panels_truncated` is decided by.
    """
    return {trend_key: TrendItem(
        history_key=trend_key, monitor_id="m1", topic_key="ai-tool-stacks",
        name="AI tool stacks", is_slideshow=True,
        posts=[SourcePost(post_id=post_id, url="https://www.tiktok.com/@creator/video/1",
                          author="creator", caption="Most people wire this backwards.",
                          views=9000, is_slideshow=True, panel_count=panels,
                          panel_texts=[f"panel {i}" for i in range(1, panels + 1)],
                          image_urls=[f"https://cdn.virlo.test/{post_id}/{i}.jpg"
                                      for i in range(1, panels + 1)])])}


def make_env(tmp_path: Path, entry: PlanEntry, *, texts: list[str] | None = None,
             style: MetaStyle | None = None, **overrides: Any) -> Env:
    config = Config()
    copyset = CopySet(asset_id=entry.asset_id, language="en", trend_key="t1",
                      caption="Most people wire this backwards.", hashtags=["#ai"],
                      headline="Wired backwards", narrative_arc="hook, escalation, payoff, close",
                      slide_texts=texts if texts is not None
                      else ["Wired backwards", "Two", "Three", "Four"])
    env = Env(config=config, run_dir=tmp_path, engine=PromptEngine(), log=Log(),
              copy={entry.asset_id: copyset},
              styles=make_registry(style if style is not None else make_style(tmp_path)))
    for key, value in overrides.items():
        setattr(env, key, value)
    return env


def make_folder(tmp_path: Path, entry: PlanEntry) -> AssetFolder:
    return AssetFolder(tmp_path, AssetRecord(
        asset_id=entry.asset_id, source="t1", source_name="AI tool stacks",
        platform=entry.platform, creative_format="carousel",
        aspect_ratio_requested=entry.aspect_ratio, slide_count=entry.slide_count))


def dna_block(prompt: str) -> str:
    """The STYLE_DNA segment of one assembled slide prompt — FR-189's unit of comparison."""
    return prompt.split("STYLE_DNA", 1)[1].split("SLIDE CONTENT", 1)[0]


def quoted_text(prompt: str) -> str:
    """The on-image string this slide's TEXT block orders, as the render model reads it.

    `prompts_engine._onimage_text` labels a mapped slide's line `panel_text` and a cover's
    `headline`; either way the quoted value is the exact string that becomes pixels, which is what
    an FR-105 retry may (or, under FR-304, may not) have shortened.
    """
    match = re.search(r'(?:panel_text|headline) \(render verbatim\): "(.*)"', prompt)
    return match.group(1) if match else ""


def give_brief(env: Env, entries: list[PlanEntry], tmp_path: Path, *,
               photos: int = 1, influence: str = "blend") -> list[Path]:
    """Point these entries at ONE campaign brief that ships `photos` real files (FR-144/145).

    Post-D46 a brief's photos are the only files `refs.attach()` ever uploads, so this is the
    fixture behind every attachment, ordering, upload-memo and FR-97 assertion in this file.
    """
    folder = tmp_path / "brief-photos"
    folder.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index in range(1, photos + 1):
        path = folder / f"{BRIEF_NAME}-{index:02d}.png"
        path.write_bytes(PNG + b"\x00" * 64)
        paths.append(path)
    env.campaign_briefs = {BRIEF_NAME: Brief(
        name=BRIEF_NAME, description="one product photo", influence=influence,
        visual_directives={"scene": "ZZBRIEF the product on a bare desk"},
        reference_image_paths=list(paths))}
    env.local_refs = {entry.asset_id: [(path, "brief") for path in paths] for entry in entries}
    for entry in entries:
        entry.brief_name, entry.brief_influence = BRIEF_NAME, influence
    return paths


def give_intel(env: Env, *, post_id: str = "post-a", panels: int = 3,
               chrome: Sequence[str] = (), marks: Sequence[Sequence[str]] = (),
               briefs: Sequence[str] = (), boxes: Sequence[MarkBox] = ()) -> SlideIntel:
    """Hang FR-306 slide intelligence for one SOURCE post on the run (`env.slide_intel`).

    This is the deck's only view of what the source slides showed: `chrome` is the creator's
    transcribed furniture (where a page counter lives, §0.11), `marks` is `brand_marks` per slide,
    `briefs` the English content directives and `boxes` the deck-level `mark_boxes` FR-315 crops
    its logo patches from. `panels` is the SOURCE deck's length, which is deliberately allowed to
    differ from ours — the platform ceiling truncates (§0.4′), and a badge re-based onto the wrong
    length is the defect D-D exists to prevent.
    """
    intel = SlideIntel(post_id=post_id, folder=f"source/{post_id}", mark_boxes=list(boxes), slides=[
        SourceSlide(position=position,
                    virlo_text=f"panel {position}",
                    chrome_text=chrome[position - 1] if position <= len(chrome) else "",
                    visual_brief=briefs[position - 1] if position <= len(briefs) else "",
                    brand_marks=list(marks[position - 1]) if position <= len(marks) else [])
        for position in range(1, panels + 1)])
    env.slide_intel = {post_id: intel}  # duck-typed seam: `carousel._intel()` reads it via getattr
    return intel


def give_source_slides(tmp_path: Path, count: int = 3, post_id: str = "post-a") -> Path:
    """The run's source store, with REAL decodable slide images (§0.13).

    FR-315's crop step is not stubbed anywhere in this file: `logo_crops.crop_marks` opens these
    files with Pillow, writes real PNG patches into `source/<post_id>/marks/`, and `upload_local`
    then uploads exactly those paths. Faking the pixels would leave the one boundary that matters
    — what may be uploaded OUT of the source store — asserted against a mock of itself.
    """
    folder = tmp_path / "source" / post_id
    folder.mkdir(parents=True, exist_ok=True)
    for position in range(1, count + 1):
        slide = Image.new("RGB", (400, 600), color=(30, 30, 60))
        # TEXTURED, not flat (v2.2.0). `logo_crops._crop_valid` refuses a crop that is one flat
        # colour — that is how it rejects the black-letterbox patches run `…_m39f` uploaded as
        # logos — so a single-colour fixture would make every mark-patch test here a test of that
        # refusal instead of of the thing it is about.
        for top in range(0, 600, 20):
            for left in range(0, 400, 20):
                if ((left // 20) + (top // 20)) % 2:
                    slide.paste((225, 205, 185), (left, top, left + 20, top + 20))
        slide.save(folder / f"slide_{position:02d}.jpg")
    return folder



def _png_bytes(width: int, height: int) -> bytes:
    """A REAL PNG of these dimensions — what `generate.pixels` reads its IHDR out of.

    Encoded with Pillow rather than hand-assembled: the parser under test claims to read what a
    provider actually returns, and a header this suite wrote by hand could agree with a parser
    that is wrong about the format. Pillow is already a test dependency here for the source-slide
    fixtures; nothing in `hypesocials/` outside `logo_crops` imports it.
    """
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (20, 20, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def mark_patch_urls(call: Call) -> list[str]:
    """The MARK PATCH references on one submitted job — every attachment out of `marks/`."""
    return [url for url in call.image_urls if "/upload/" in url and url.endswith(".png")]


def text_block(prompt: str) -> str:
    """The TEXT block of one assembled slide prompt — every string the model may draw."""
    return prompt.split("TEXT (locked asset", 1)[-1].split("TEXT PRECEDENCE", 1)[0]


def marks_line(prompt: str) -> str:
    """The TOOL MARKS line — the ONE place a slide sanctions a real logo (D-A)."""
    after = prompt.split("TOOL MARKS (sanctioned real logos — ignore if empty):", 1)[-1]
    return after.splitlines()[1].strip() if len(after.splitlines()) > 1 else ""


# ------------------------------------------------------- the assigned meta-style (FR-290/291)


async def test_the_deck_wears_one_assigned_meta_style_for_every_slide(tmp_path: Path) -> None:
    """The pivot in one assertion: the look comes from `entry.style_key` resolved against the
    run's registry, not from an analysis of this trend's pictures — so the style's own
    `render_prompt` and its literal exclusions appear on EVERY slide of the deck."""
    entry = make_entry(slides=3)
    style = make_style(tmp_path)
    env = make_env(tmp_path, entry, texts=["one", "two", "three"], style=style)
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert refs_module.style_of(entry, env) is env.styles.styles[0]
    for call in submit.calls:
        assert style.render_prompt in call.prompt, f"slide {call.slide} lost its house style"
        assert "platform UI" in call.prompt, "the style's literal exclusions travel with it"
    assert len(submit.calls) == 3


def test_style_dna_is_the_five_meta_style_rows_and_no_layout_grid(tmp_path: Path) -> None:
    """Contracts item 12: `style_dna` reads the FIVE DNA fields off the assigned style, and the
    zone-derived `layout_grid` row is GONE — layout travels in `{{layout_zones}}` alone.

    Two descriptions of one thing is how byte-identical instructions still produce a drifting
    deck, which is why this is asserted on a style that DOES declare zones."""
    style = make_style(tmp_path)
    assert style.layout_zones, "the point of the assertion is a style that has zones to leak"

    dna = style_dna(style)

    labels = [row.split(":", 1)[0].strip() for row in dna.splitlines()]
    assert labels == ["palette", "typography", "text_placement", "image_treatment",
                      "visual_pacing"]
    assert "layout_grid" not in dna
    assert "ZZZONE" not in dna, "a zone position reached the DNA block"
    assert style_dna(None) == "", "no assigned style is an empty block, never a crash"


async def test_style_dna_is_built_once_and_byte_identical_across_slides(tmp_path: Path) -> None:
    """FR-189/M9 — the style-DNA block is built ONCE per deck and repeated verbatim; only the
    slide content and the slide index change. Drift prevention is templating, not a QA loop
    (FR-20 explicitly has no consistency check)."""
    entry = make_entry(slides=4)
    style = make_style(tmp_path)
    env = make_env(tmp_path, entry, style=style)
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    blocks = [dna_block(call.prompt) for call in submit.calls]
    assert len(blocks) == 4
    assert len(set(blocks)) == 1, "byte-identical on every slide"
    assert style_dna(style) and style_dna(style) in blocks[0]
    indexes = [re.search(r"slide (\d+ of \d+)", call.prompt).group(1) for call in submit.calls]
    assert indexes == ["1 of 4", "2 of 4", "3 of 4", "4 of 4"], "only the index moves"


async def test_slide_one_gets_the_cover_grammar_and_the_rest_the_body_grammar(
    tmp_path: Path,
) -> None:
    """M9's home for cover-versus-body divergence. `style_dna` may not vary across a deck, so the
    one legitimate difference between a cover and a page lives in `per_format_guidance` and is
    appended to the style's own `render_prompt` — `carousel_cover` for slide 1, `carousel_slide`
    for every other slide."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["one", "two", "three"])
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    anchor = submit.slide(1)
    assert COVER_GUIDANCE in anchor.prompt and SLIDE_GUIDANCE not in anchor.prompt
    for number in (2, 3):
        body = submit.slide(number)
        assert SLIDE_GUIDANCE in body.prompt and COVER_GUIDANCE not in body.prompt
    assert dna_block(anchor.prompt) == dna_block(submit.slide(2).prompt), \
        "the guidance diverged and the DNA did not — that is the whole design"


async def test_a_style_that_declares_no_guidance_appends_nothing(tmp_path: Path) -> None:
    """A deck of one grammar is the registry's stated intent, not an omission to paper over."""
    entry = make_entry(slides=2)
    style = make_style(tmp_path, guidance=False)
    env = make_env(tmp_path, entry, texts=["one", "two"], style=style)
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    for call in submit.calls:
        assert style.render_prompt in call.prompt
        assert "ZZCOVER" not in call.prompt and "ZZBODY" not in call.prompt


async def test_an_override_brief_suppresses_the_style_and_its_guidance(tmp_path: Path) -> None:
    """FR-144/M14: an `override` brief replaces the assigned style ENTIRELY. So there is no
    `per_format_guidance` to append either: the brief's own directives are the whole creative, on
    every slide.

    Post-D46 there are no style pictures left for M14 to suppress — a style was already words —
    so what this pins now is that a picture-less override deck says NOTHING about being
    reference-free (FR-18): it expected no attachment and lost none. The anchor chain is
    untouched either way, which is the half of M14 that always mattered.
    """
    entry = make_entry(slides=2, brief_name="ai-audit-cta", brief_influence="override")
    env = make_env(tmp_path, entry, texts=["one", "two"])
    env.campaign_briefs = {"ai-audit-cta": Brief(
        name="ai-audit-cta", description="a standing CTA card", influence="override",
        visual_directives={"scene": "ZZBRIEF a laptop on a bare desk, one product card"},
        copy_directives={"message": "book an AI audit"})}
    folder = make_folder(tmp_path, entry)
    submit = FakeSubmit()

    record = await render_carousel(entry, env, folder, submit=submit)

    assert refs_module.style_of(entry, env) is None, "M14: the style is suppressed, not blended"
    for call in submit.calls:
        assert "ZZBRIEF a laptop on a bare desk" in call.prompt
        assert "ZZCOVER" not in call.prompt and "ZZBODY" not in call.prompt
    assert submit.slide(1).image_urls == [], "a brief with no photos attaches nothing"
    assert submit.slide(2).image_urls == [submit.slide(1).url], \
        "the anchor chain is untouched by M14 — the deck still reproduces its own slide 1"
    assert DegradationTag.REFERENCE_FREE not in record.degradations, \
        "nothing was expected and nothing was lost — silence is the honest answer (FR-18)"
    assert style_dna(None) == "" and "STYLE_DNA" in submit.slide(1).prompt, \
        "the block is empty, not missing — the scaffold is one shape for every case"


# ------------------------------------------------------------------ references (F19 / FR-200)


async def test_a_style_driven_deck_attaches_nothing_and_says_nothing_about_it(
    tmp_path: Path, uploads: SimpleNamespace,
) -> None:
    """D46/FR-17/18: text-to-image is the deck's DEFAULT route, not a degrade.

    The style's `render_prompt` and DNA rows are the whole visual instruction, so slide 1 goes
    out with an empty reference set, nothing is uploaded, and the record carries no tag about it.
    `reference_free` is reserved for a creative that EXPECTED pictures and lost them; firing it
    on the normal case would train the operator to ignore the one line that means something.
    """
    entry = make_entry(slides=2)
    style = make_style(tmp_path)
    env = make_env(tmp_path, entry, texts=["one", "two"], style=style)
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert uploads.paths == [], "a meta-style ships no pixels (F3)"
    assert submit.slide(1).image_urls == []
    assert style.render_prompt in submit.slide(1).prompt, "the look travels as PROSE"
    assert DegradationTag.REFERENCE_FREE not in record.degradations
    assert DegradationTag.STYLE_REFS_MISSING not in record.degradations, \
        "the tag survives for old meta.yaml files on disk; nothing emits it any more"
    assert "reference_free" not in env.log.types()
    assert "house style reference" not in submit.slide(1).prompt, \
        "the F19 style role line retired with the channel it introduced"


async def test_a_briefs_own_pictures_are_the_only_attachments_a_slide_carries(
    tmp_path: Path,
) -> None:
    """FR-144/145/191: what a brief ships is attached, in the brief's own order, and introduced
    as the SUBJECT — "this product IS the subject; reproduce it faithfully".

    Before D46 the house style's window led this list and the brief's photo followed it, which
    is what made the ordering worth pinning. With the style channel excised the brief's photos
    ARE the list, and the wording is the thing that still matters: a product photo introduced as
    "layout, palette and treatment only" is a product that vanishes from its own ad.
    """
    entry = make_entry(slides=2)
    style = make_style(tmp_path)
    env = make_env(tmp_path, entry, texts=["one", "two"], style=style)
    first, second = give_brief(env, [entry], tmp_path, photos=2)
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    anchor = submit.slide(1)
    assert anchor.image_urls == [upload_url(first), upload_url(second)], "the brief's own order"
    assert "Image 1: brief subject" in anchor.prompt, "the brief's photo is the SUBJECT, not style"
    assert "Image 2: brief subject" in anchor.prompt
    assert "house style reference" not in anchor.prompt, "no style role line exists to write"


async def test_each_brief_photo_is_uploaded_once_per_run_however_many_decks(
    tmp_path: Path, uploads: SimpleNamespace,
) -> None:
    """FR-200/244: the upload memo is run-scoped, so a brief's photos cost one upload per FILE
    per run — not one per job. A second deck on the same run re-uses the URLs; a second run (a
    different `run_dir`) uploads again, because Kie keeps an upload about 24 h."""
    style = make_style(tmp_path)
    first, second = make_entry(slides=2), make_entry(slides=2, asset_id="0002_carousel_linkedin")
    env = make_env(tmp_path, first, texts=["one", "two"], style=style)
    env.copy[second.asset_id] = env.copy[first.asset_id]
    photos = give_brief(env, [first, second], tmp_path, photos=2)

    await render_carousel(first, env, make_folder(tmp_path, first), submit=FakeSubmit())
    after_first = list(uploads.paths)
    await render_carousel(second, env, make_folder(tmp_path, second), submit=FakeSubmit())

    assert after_first == photos, "both of the brief's files, uploaded once each"
    assert uploads.paths == after_first, "the sibling deck uploaded nothing new (the memo)"

    later_run = tmp_path / "run-2"
    later_run.mkdir()
    third = make_entry(slides=1, asset_id="0003_carousel_linkedin")
    later_env = make_env(later_run, third, texts=["one"], style=style)
    give_brief(later_env, [third], tmp_path, photos=2)
    await render_carousel(third, later_env, make_folder(later_run, third), submit=FakeSubmit())
    assert len(uploads.paths) == 4, "a NEW run re-uploads: a memoized URL would 404 mid-batch"


async def test_a_brief_whose_pictures_are_all_gone_degrades_to_text_only(tmp_path: Path) -> None:
    """FR-18: brief images are an input, not a prerequisite — the deck still renders on the
    style's written guidance. But this creative EXPECTED pictures and lost every one of them, so
    the operator hears which CREATIVE lost its proof and the record says so.

    This is the only shape that still earns `reference_free` post-D46: the pre-D46 version of
    this test unlinked a STYLE's files, and the style has no files to unlink any more.
    """
    entry = make_entry(slides=2)
    env = make_env(tmp_path, entry, texts=["one", "two"])
    for path in give_brief(env, [entry], tmp_path, photos=2):
        path.unlink()
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    assert DegradationTag.REFERENCE_FREE in record.degradations
    assert DegradationTag.STYLE_REFS_MISSING not in record.degradations
    assert "reference_free" in env.log.types()
    assert "style_refs_missing" not in env.log.types(), "nothing emits it post-D46"
    assert record.status is AssetStatus.SUCCESS, "a text-only render is a degrade, not a failure"


# ------------------------------------------------------------------- FR-292 / M12 the signature


async def test_the_signature_rides_the_anchor_alone_when_the_deck_is_chained(
    tmp_path: Path,
) -> None:
    """M12: a deck signed once reads as designed; signed N times it reads as a watermark. The
    wordmark is a TEXT-block string (B1) and the colour block is `{{branding_block}}`, and on a
    chained deck BOTH belong to slide 1 — slides 2–N inherit the signature from the picture they
    are reproducing."""
    entry = make_entry(slides=3, branded=True)
    env = make_env(tmp_path, entry, texts=["one", "two", "three"])
    env.branding = BrandingConfig(brand="hypelead")
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    anchor = submit.slide(1)
    assert "HypeLead" in anchor.prompt, "B1: the wordmark reaches the frame through the TEXT block"
    assert "#0FCFC4" in anchor.prompt, "FR-292 channel 2: the profile's accent colours"
    for number in (2, 3):
        body = submit.slide(number)
        assert "HypeLead" not in body.prompt, "M12: slide 2–N never refills the signature zone"
        assert "#0FCFC4" not in body.prompt


async def test_an_independently_generated_deck_still_signs_only_slide_one(tmp_path: Path) -> None:
    """The strict half of M12: with no anchor to inherit from, every slide needs the COLOUR block
    — but the WORDMARK is still slide 1's alone, whatever the deck's shape."""
    entry = make_entry(slides=3, branded=True)
    env = make_env(tmp_path, entry, texts=["one", "two", "three"])
    env.branding = BrandingConfig(brand="hypelead")
    env.config.run.carousel_anchor = False
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert all("#0FCFC4" in call.prompt for call in submit.calls), "no anchor to inherit from"
    assert [call.slide for call in submit.calls if "HypeLead" in call.prompt] == [1]


async def test_an_unbranded_deck_carries_no_wordmark_and_no_colour_block(tmp_path: Path) -> None:
    """`entry.branded` is the deterministic rotation `styles.assign_branding` already wrote, and
    an unsigned deck must reach the model carrying neither channel: no TEXT-block wordmark, no
    accent block. (The M11 "this frame carries no signature zone" line rides `{{layout_zones}}`,
    which `carousel_slide.md` does not carry at all — a slide's layout is the anchor's, so that
    half of the rule is asserted on the seed frame in `test_reel.py`.)"""
    entry = make_entry(slides=2, branded=False)
    env = make_env(tmp_path, entry, texts=["one", "two"])
    env.branding = BrandingConfig(brand="hypelead")
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    for call in submit.calls:
        assert "HypeLead" not in call.prompt and "#0FCFC4" not in call.prompt
    assert "BRANDING" in submit.slide(1).prompt, "the labelled line stays, empty (ignore-if-empty)"


# ------------------------------------------------------ D49 gauntlet ordering (barrier item)


async def test_the_anchor_is_gated_before_slides_two_onward_are_submitted(tmp_path: Path) -> None:
    """The anchor is a chained artifact: judging it after the deck is judging it N renders too
    late (FR-95/D49). Slide 1 renders alone, faces the pre-gate, and only then do slides 2-N go.

    Spec §1: the pre-gate is `run_single` with the `brief` + `craft` critics only — `system` judges
    cross-frame consistency and a deck of one has none — and FR-324's ceiling of one extra round.
    A cover that PASSES its first round (this deck's) returns there and never buys the second, so
    the pre-gate is still exactly one call per critic here.
    """
    entry, events = make_entry(slides=4), []
    env = make_env(tmp_path, entry)
    env.llm_call = CriticStub(events=events)
    submit = FakeSubmit(events=events)

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    gate = next(index for index, name in enumerate(events) if name.startswith("critic:"))
    assert events[0] == "submit:1:projected", "slide 1 renders first and alone (FR-95)"
    later = [index for index, name in enumerate(events) if name.startswith("submit:")
             and not name.startswith("submit:1:")]
    assert later and min(later) > gate, "no slide 2-N is submitted before the anchor is judged"
    assert env.llm_call.frames_for("brief") == [1, 4], "anchor alone, then the whole deck"
    assert env.llm_call.frames_for("system") == [4], "no cross-frame verdict on a deck of one"
    assert record.status is AssetStatus.SUCCESS
    assert record.gauntlet["result"] == "pass"
    assert record.vision_check_result is VisionCheckResult.PASSED


async def test_fr324_a_cover_that_fails_its_first_round_buys_exactly_one_re_render_before_the_deck(
    tmp_path: Path,
) -> None:
    """F3 (Session 5.5): the pre-gate's ONE extra round, which the code used to forbid.

    `prds/10-pipeline.md` (FR-324) grants "≤1 anchor re-render, on the deck budget"; `_anchor_gate`
    shipped `rounds_max=1`, and a round ceiling of 1 breaks BEFORE the fix loop — so a cover with a
    single fixable defect went straight to its terminal verdict having never bought the render that
    would have fixed it. The 2026-08-14 acceptance run blocked a whole deck that way, on a missing
    page counter. Two rounds is what the PRD says and what this pins: judge, fix the cover once,
    judge the replacement — and only then order the pages that will copy it.

    The ordering assertion is the point of doing it here rather than in the deck loop. Every slide
    2-N is rendered against slide 1 as its PRIMARY reference (FR-95), so a cover repaired after the
    deck was ordered is a repair nine pages never see.
    """
    entry, events = make_entry(slides=3), []
    env = make_env(tmp_path, entry, texts=["Wired backwards", "Two", "Three"])
    # `garbled` is a CRAFT code, and craft is one of the pre-gate's two critics. Entry 0 is the
    # pre-gate's round 1 (slide 1 fails), entry 1 its round 2 (the replacement is clean), entry 2
    # the deck round that follows.
    env.llm_call = CriticStub(rounds=[{1}, set(), set()], code="garbled", events=events)
    submit = FakeSubmit(events=events)

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    fixes = [call for call in submit.calls if call.kind == "discretionary"]
    assert len(fixes) == 1, [call.kind for call in submit.calls]
    assert fixes[0].slide == 1 and fixes[0].priority is RenderPriority.WAVE1, \
        "the cover's repair is wave-1 work: the deck is waiting on it"
    assert submit.calls.index(fixes[0]) < min(
        index for index, call in enumerate(submit.calls) if call.slide != 1), \
        "the cover is repaired BEFORE slides 2-N are ordered to reproduce it"
    assert env.llm_call.frames_for("craft") == [1, 1, 3], \
        "two pre-gate rounds over the cover alone, then one deck round over every frame"
    assert record.gauntlet["rerenders"] == 1, "the anchor's round is counted in the deck's receipt"
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 3
    assert env.log.fields("gauntlet_anchor")["result"] == "pass"
    assert env.log.fields("gauntlet_anchor")["rerenders"] == 1


async def test_fr324_a_cover_still_failing_after_its_one_re_render_is_final_and_buys_no_deck(
    tmp_path: Path,
) -> None:
    """The other half of the ceiling: ONE extra round, never two.

    Round 2 judges the replacement and, if the defect is still standing, that verdict is terminal —
    there is no third render, and on the leakage tier there is no deck either. Stopping here is
    what the pre-gate is FOR: every page would have copied this cover's template, its palette and
    the mark it leaked, so refusing at slide 1 saves N renders on a deck nobody could publish.
    """
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry, texts=["Wired backwards", "Two", "Three", "Four"])
    # `invented_text` is a BRIEF code — leakage, and brief is the pre-gate's other critic. The
    # cover fails round 1, is re-rendered once, and fails round 2 the same way.
    env.llm_call = CriticStub(rounds=[{1}, {1}], code="invented_text", detail="ZZ extra words")
    folder = make_folder(tmp_path, entry)
    submit = FakeSubmit()

    record = await render_carousel(entry, env, folder, submit=submit)

    assert [call.kind for call in submit.calls] == ["projected", "discretionary"], \
        "one cover, one repair, and nothing else was ever ordered"
    assert env.llm_call.frames_for("brief") == [1, 1], "two rounds, both over the cover alone"
    assert record.gauntlet["rerenders"] == 1 and record.gauntlet["result"] == "blocked"
    assert record.status is AssetStatus.BLOCKED and entry.status is PlanEntryStatus.BLOCKED
    assert (folder.path / packager.BLOCKED_FILE).exists()
    anchor_line = next(message for name, message in env.log.records if name == "gauntlet_anchor")
    assert "blocked" in anchor_line and "slides 2-4 are NOT ordered" in anchor_line


async def test_fr324_the_anchor_re_render_is_charged_to_the_decks_own_gauntlet_budget(
    tmp_path: Path,
) -> None:
    """FR-324's money clause: the extra round is bought "on the deck budget", not beside it.

    A pre-gate that spent from its own purse would double `deck_budget_usd` on every carousel. The
    proof is a cap that fits exactly one re-render: the cover takes it, and the deck round's own
    fix is then declined for want of the money the anchor already spent.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["Wired backwards", "Two", "Three"])
    env.config.run.gauntlet.deck_budget_usd = 0.05  # room for exactly one $0.03 re-render
    env.price_job = lambda _entry, _job: 0.03
    env.llm_call = CriticStub(rounds=[{1}, set(), {2}], code="garbled")
    submit = FakeSubmit(rule=lambda call: ok(call, cost=0.03))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    fixes = [call for call in submit.calls if call.kind == "discretionary"]
    assert [call.slide for call in fixes] == [1], "the cover's repair, and no second one"
    assert record.gauntlet["result"] == "budget_stop"
    # Two lines share this event type — the gauntlet's round-level stop and the deck's own refusal.
    # The refusal is the one carrying the arithmetic, and the arithmetic is what this test is about.
    stop = next(data for name, data in env.log.data
                if name == "gauntlet_budget_stop" and "spent_usd" in data)
    assert stop["spent_usd"] == pytest.approx(0.03), \
        "the deck round measured the cap against money the ANCHOR round spent"
    assert stop["cap_usd"] == pytest.approx(0.05) and stop["slide"] == 2
    assert record.status is AssetStatus.SUCCESS, "a craft opinion never costs the deck (FR-325)"


async def test_the_deck_gate_is_one_call_per_critic_for_the_whole_deck(tmp_path: Path) -> None:
    """N slides never cost N calls per critic, and the estimate prices it the same way (FR-326)."""
    entry = make_entry(slides=5)
    env = make_env(tmp_path, entry, texts=["a", "b", "c", "d", "e"])
    env.llm_call = CriticStub()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    assert env.llm_call.frames_for("system") == [5], "one call, every frame"
    assert env.llm_call.frames_for("craft") == [1, 5], "the anchor pre-gate, then the deck"
    assert env.llm_call.roles == ["critic"] * len(env.llm_call.calls), "the new LLM role"


async def test_the_gate_switched_off_never_calls_the_model(tmp_path: Path) -> None:
    """`run.gauntlet.enabled` is the switch, and OFF means NO post-render gate at all.

    Not a fallback to the FR-105 single-shot check — that machinery is deleted (D49). Renders ship
    exactly as Kie returned them, unread, and the receipt says so by being absent.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.config.run.gauntlet.enabled = False
    env.llm_call = CriticStub()  # a call is available; the flag is what declines it

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    assert env.llm_call.calls == []
    assert record.gauntlet is None, "no gate ran, so meta claims no verdict"
    assert record.vision_check_result is VisionCheckResult.NOT_CHECKED


# ------------------------------------------------------- FR-95 anchor chain (barrier item)


async def test_slides_two_onward_lead_with_the_finished_anchor(tmp_path: Path) -> None:
    """FR-95: the finished slide 1 is the PRIMARY reference, and it is introduced by the
    template-lock block rather than by a role line.

    Post-D46 the anchor is also the ONLY reference an unbriefed deck carries — slide 1 itself
    attaches nothing (F3) — so "the anchor leads" and "the anchor is the whole list" are the same
    sentence here. A brief's photos following it are pinned in the sibling test below.
    """
    entry = make_entry(slides=3)
    style = make_style(tmp_path)
    env = make_env(tmp_path, entry, texts=["one", "two", "three"], style=style)
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    anchor = submit.slide(1)
    assert anchor.kind == "projected" and anchor.priority is RenderPriority.WAVE1
    assert anchor.image_urls == [], "the anchor renders text-to-image (FR-17/18)"
    for number in (2, 3):
        call = submit.slide(number)
        assert call.image_urls == [anchor.url], "the finished slide 1 and nothing else"
        assert "ANCHOR REFERENCE" in call.prompt, "the template-lock block is prepended"
        assert call.kind == "precommitted" and call.priority is RenderPriority.WAVE2


async def test_the_anchor_leads_and_a_briefs_photos_follow_it_on_every_later_slide(
    tmp_path: Path,
) -> None:
    """FR-95 + FR-145 in one list: the chained slide 1 is PRIMARY, and the brief's own subject
    photo rides behind it so the deck reproduces its own template while keeping its product.

    Every render scaffold tells the model to follow the FIRST reference listed, so this order IS
    the precedence — swapping the two would make each body slide a fresh photo shoot rather than
    a page of one deck.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["one", "two", "three"])
    (photo,) = give_brief(env, [entry], tmp_path)
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    anchor = submit.slide(1)
    assert anchor.image_urls == [upload_url(photo)]
    for number in (2, 3):
        assert submit.slide(number).image_urls == [anchor.url, upload_url(photo)]


def test_the_chained_anchor_carries_an_explicit_role_and_never_a_blank_line() -> None:
    """`_ANCHOR_ROLE` is the fallback wording the chained slide-1 reference carries until
    `carousel_anchor_instruction.md` replaces it (FR-190). It is never rendered as-is in a live
    deck — and it is never an empty string either, which is the failure it exists to prevent."""
    role = carousel_module._ANCHOR_ROLE

    assert role and "reproduce its template" in role
    assert refs_module.role_lines([refs_module.Reference("https://kie.test/a.jpg", role)]) == [
        f"Image 1 — {role}"]


async def test_anchor_failure_falls_back_to_independent_slides_precommitted(
    tmp_path: Path,
) -> None:
    """Slide 1 failing THREE times degrades the deck to independent generation — and that fallback
    is PRE-COMMITTED work, never discretionary: the cap may not split a deck (FR-95/FR-106b).

    The anchor has to fail three times to reach this path since v2.2.0. FR-317 grants a
    non-moderation failure one automatic resubmit (v2.1.3/D48), and FR-95 then grants ONE
    replacement anchor before the deck gives up on being chained — an unchained deck is the defect
    the anchor exists to prevent, so one more cover render against a deck of four is the cheapest
    repair there is. A deck that anchors on either of those attempts is strictly better than one
    that falls back (the sibling tests below pin both halves), so the rule fails all three by INDEX
    rather than by slide number — the fallback's own slide 1 is still slide 1, and it must land.
    """
    entry = make_entry(slides=4)
    style = make_style(tmp_path)
    env = make_env(tmp_path, entry, style=style)
    submit = FakeSubmit(rule=lambda call: failed() if call.index in (0, 1, 2) else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert len(submit.calls) == 7, \
        "the anchor, its FR-317 resubmit, FR-95's replacement anchor, then N independent slides"
    assert [call.kind for call in submit.calls[:3]] == [
        "projected", "discretionary", "precommitted"], \
        "the replacement anchor is pre-committed too — the cap may not decide whether a deck chains"
    assert [call.slide for call in submit.calls[:3]] == [1, 1, 1]
    fallback = submit.calls[3:]
    assert [call.slide for call in fallback] == [1, 2, 3, 4]
    assert {call.kind for call in fallback} == {"precommitted"}, "never discretionary"
    assert {call.priority for call in fallback} == {RenderPriority.WAVE2}
    assert all(call.image_urls == [] for call in fallback), \
        "no anchor to chain to, and a style ships no pictures of its own (F3)"
    assert "carousel_anchor_retry" in env.log.types()
    assert "carousel_anchor_fallback_unchained" in env.log.types()
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 4, \
        "three dead covers are not a dead deck: the unchained burst is slide 1's last path (FR-95)"


async def test_fr317_an_anchor_that_fails_once_is_resubmitted_and_the_deck_still_chains(
    tmp_path: Path,
) -> None:
    """FR-317 (v2.1.3/D48): a timed-out or otherwise non-moderation-failed image job is sent ONCE
    more, unchanged, as discretionary spend — and when that second attempt lands, the deck keeps
    everything the first failure would have cost it.

    That is the whole point of the requirement here. The independent-slide fallback below is a
    real degradation: four slides rendered with no shared reference drift apart visually, which is
    exactly what FR-95's anchor chain exists to prevent. A single resubmit buys the chain back for
    one render, so the healed deck must anchor, not fall back.
    """
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry)
    submit = FakeSubmit(rule=lambda call: failed(RenderFailCause.TIMEOUT)
                        if call.index == 0 else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert len(submit.calls) == 5, "the dead anchor, its one resubmit, then slides 2-4"
    resubmit = submit.calls[1]
    assert resubmit.slide == 1 and resubmit.kind == "discretionary"
    assert resubmit.priority is RenderPriority.WAVE1, "still the wave the anchor belongs to"
    assert resubmit.prompt == submit.calls[0].prompt, "the SAME job, not a different request"
    assert "carousel_anchor_fallback" not in env.log.types(), "the deck anchored after all"
    assert [call.image_urls for call in submit.calls[2:]] == [[resubmit.url]] * 3, \
        "slides 2-4 chain to the anchor the RESUBMIT produced (FR-95)"
    assert "image_job_resubmit" in env.log.types()
    fields = env.log.fields("image_job_resubmit")
    assert fields["slide"] == 1 and fields["attempt"] == 2 and fields["cause"] == "timeout"
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 4


async def test_fr95_a_replacement_anchor_that_lands_chains_the_deck_instead_of_unchaining_it(
    tmp_path: Path,
) -> None:
    """FR-95 (v2.2.0): the anchor's ONE replacement, and what it buys when it lands.

    Until now a cover that failed twice condemned every remaining slide to reference-free
    generation — the visual drift FR-95 exists to prevent, bought for a single unlucky render. One
    more cover costs one image against a deck of four, the Confirm gate already prices it (the
    anchor contingency is two units, FR-107), and when it lands slides 2–N chain off it exactly as
    if the first attempt had worked.
    """
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry)
    submit = FakeSubmit(rule=lambda call: failed(RenderFailCause.TIMEOUT)
                        if call.index in (0, 1) else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert len(submit.calls) == 6, "the anchor, its FR-317 resubmit, its replacement, slides 2-4"
    replacement = submit.calls[2]
    assert replacement.slide == 1 and replacement.kind == "precommitted", \
        "pre-committed: the cap may not be the thing that decides whether a deck chains (FR-106b)"
    assert replacement.priority is RenderPriority.WAVE1, "still the wave the anchor belongs to"
    assert [call.image_urls for call in submit.calls[3:]] == [[replacement.url]] * 3, \
        "slides 2-4 chain to the anchor the REPLACEMENT produced (FR-95)"
    assert "carousel_anchor_fallback_unchained" not in env.log.types(), "the deck anchored"
    assert env.log.fields("carousel_anchor_retry")["slide"] == 1
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 4


async def test_fr323_a_re_render_references_the_anchor_and_its_nearest_delivered_neighbour(
    tmp_path: Path,
) -> None:
    """A slide rendered a SECOND time is being fitted back into a deck that already exists.

    The cover alone is a poor description of what page four looks like — it is a cover — so a
    re-render also carries the nearest already-delivered page, our own rendered artifact and never
    a source byte (FR-18/FR-323, D46-compatible). Nearest by distance with the earlier page winning
    a tie: the page before is the one a reader sees immediately before this one.
    """
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry, texts=["one", "two", "three", "four"])
    env.llm_call = CriticStub(rounds=[{3}], code="style_layout")
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    rerender = next(call for call in submit.calls if call.kind == "discretionary")
    assert rerender.slide == 3
    anchor_url, neighbour_url = submit.slide(1).url, submit.slide(2).url
    assert rerender.image_urls[:2] == [anchor_url, neighbour_url], \
        "the anchor stays Image 1 (FR-190) and the nearest delivered neighbour sits under it"
    role = next(line.strip() for line in rerender.prompt.splitlines()
                if line.strip().startswith("Image 2"))
    assert "the finished slide 2 of this same deck" in role
    assert "not its words" in role, "a neighbour contributes look, never copy"


# ------------------------------------------------------- FR-304 panel-mapped decks (§0.4′)


async def test_deck_length_is_the_entrys_assign_fixed_count_not_the_copy_length(
    tmp_path: Path,
) -> None:
    """FR-304/§0.4′: the deck is as long as the SOURCE deck, decided at ASSIGN and priced at the
    Confirm gate. Copy fills slots; it no longer decides how many there are.

    Before D46 a short copy list silently shortened the deck (`min(ceiling, len(written))`), which
    made the render count disagree with the number the operator approved money against.
    """
    entry = make_entry(slides=5, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two", "three"])
    short = FakeSubmit()
    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=short)
    assert [call.slide for call in short.calls] == [1, 2, 3, 4, 5]

    entry2 = make_entry(slides=3, asset_id="0002_carousel_linkedin", source_post_id="post-a")
    env2 = make_env(tmp_path, entry2, texts=[f"line {n}" for n in range(8)])
    long = FakeSubmit()
    await render_carousel(entry2, env2, make_folder(tmp_path, entry2), submit=long)
    assert [call.slide for call in long.calls] == [1, 2, 3], "the ceiling is never raised"


async def test_an_empty_source_panel_renders_wordless_and_never_repeats_the_headline(
    tmp_path: Path,
) -> None:
    """The defect D46 was written against: slide 4 of the source said nothing, and our slide 4
    printed slide 1's line again.

    A panel with no words is a wordless slide (FR-304) — the TEXT block goes away entirely for it,
    through the same no-on-image-text path a caption-only creative uses (FR-100's degrade), while
    the slides that DO have words keep theirs verbatim.
    """
    entry = make_entry(slides=4, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["ZZONE the opener", "", "ZZTHREE the payoff", ""])
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call.slide for call in submit.calls] == [1, 2, 3, 4]
    assert 'panel_text (render verbatim): "ZZONE the opener"' in submit.slide(1).prompt
    assert 'panel_text (render verbatim): "ZZTHREE the payoff"' in submit.slide(3).prompt
    for wordless in (2, 4):
        prompt = submit.slide(wordless).prompt
        assert "render verbatim" not in prompt, f"slide {wordless} was given words it never had"
        assert "ZZONE the opener" not in prompt, "the headline came back as a repeat"
    # The deck's own CopySet is untouched — the blanking is per-slide context, not a mutation.
    assert env.copy[entry.asset_id].headline == "Wired backwards"


async def test_every_slide_label_states_its_source_panel(tmp_path: Path) -> None:
    """FR-302's mapping is positional and 1-based, so the log says which panel a slide came from —
    `slide 2/3 (source panel 2)`. A brief-driven deck binds no post and says nothing of the kind."""
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two", "three"], trends=make_trends(panels=3))
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call.label.split(" · ")[0] for call in submit.calls] == [
        "carousel slide 1/3 (source panel 1)",
        "carousel slide 2/3 (source panel 2)",
        "carousel slide 3/3 (source panel 3)"]

    brief = make_entry(slides=2, asset_id="0002_carousel_linkedin")
    plain = FakeSubmit()
    await render_carousel(brief, make_env(tmp_path, brief, texts=["one", "two"]),
                          make_folder(tmp_path, brief), submit=plain)
    assert [call.label.split(" · ")[0] for call in plain.calls] == [
        "carousel slide 1/2", "carousel slide 2/2"]


async def test_a_source_deck_longer_than_the_ceiling_is_tagged_panels_truncated(
    tmp_path: Path,
) -> None:
    """§0.4′: the first N panels ship with their indices preserved, and the cut is LABELLED.

    The operator comparing our deck against the source in the gallery has to be able to tell
    "panels 4–9 were never ordered" from "slides 4–9 failed to render" — the second is
    `incomplete`, this is not.
    """
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two", "three"], trends=make_trends(panels=9))
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    assert "panels_truncated" in [str(getattr(tag, "value", tag)) for tag in record.degradations]
    assert "carousel_panels_truncated" in env.log.types()
    assert record.slide_count == 3 and record.missing_slide_numbers == []
    assert "panels_truncated" in packager.read_meta(folder.path)["degradations"]


async def test_a_deck_that_fits_the_ceiling_is_not_tagged_truncated(tmp_path: Path) -> None:
    """The tag is a fact about the SOURCE, so a deck that took every panel it was offered — and a
    brief-driven deck that had no source at all — carry nothing."""
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two", "three"], trends=make_trends(panels=3))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    assert [str(getattr(tag, "value", tag)) for tag in record.degradations] == []
    assert "carousel_panels_truncated" not in env.log.types()

    brief = make_entry(slides=2, asset_id="0002_carousel_linkedin")
    brief_env = make_env(tmp_path, brief, texts=["one", "two"], trends=make_trends(panels=9))
    plain = await render_carousel(brief, brief_env, make_folder(tmp_path, brief),
                                  submit=FakeSubmit())
    assert [str(getattr(tag, "value", tag)) for tag in plain.degradations] == []


# ------------------------------------------------------------------- partial decks & moderation


async def test_a_failed_slide_download_blocks_the_deck_as_incomplete(
    tmp_path: Path, downloads: SimpleNamespace
) -> None:
    """FR-363 (D65): a deck that delivered fewer slides than it ordered is never a `success`.

    This assertion used to read the other way — 10 §10's "completed slides ship", `status: success`
    plus an `incomplete` badge. The 2026-08-21 audit is what reversed it: decks shipped that way
    with the critics silent (they judge the frames that EXIST), and our slide *i* is their panel
    *i*, so a hole in the middle is not a smaller version of the approved deck, it is a different
    one. The refusal is terminal in the FR-325 sense rather than the FR-74 one — every paid slide
    stays on disk, `BLOCKED.txt` explains itself, nothing is published — which is why the
    delivered files are still asserted here, unchanged.
    """
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry)
    downloads.fail_contains = "slide-3-"
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    assert record.status is AssetStatus.BLOCKED, "3 of 4 ordered slides is not a success (FR-363)"
    assert record.skip_reason.startswith("incomplete_deck:")
    assert record.missing_slide_numbers == [3]
    assert record.slide_count == 3
    assert "incomplete" in [tag.value for tag in record.degradations], "the cause still badges"
    on_disk = sorted(path.name for path in folder.path.glob("slide_*.jpg"))
    assert on_disk == ["slide_01.jpg", "slide_02.jpg", "slide_04.jpg"], "FR-74: paid bytes kept"
    assert "Missing: 3" in (folder.path / "BLOCKED.txt").read_text(encoding="utf-8")
    assert packager.read_meta(folder.path)["missing_slide_numbers"] == [3]


async def test_fr363_a_short_deck_is_blocked_whatever_the_critics_said(
    tmp_path: Path, downloads: SimpleNamespace
) -> None:
    """The refusal is deliberately NOT conditional on the gauntlet — the critics judge the frames
    that EXIST, so a deck missing a slide has nothing for them to object to.

    That is the whole 2026-08-21 finding: decks shipped `status: success` with an `incomplete`
    badge and three clean critic verdicts, because every frame that landed really was fine. The
    question the gate cannot ask is whether the deck the operator approved is the deck that
    shipped. Our slide *i* is their panel *i* (FR-304), so a hole in the middle reads as if the
    source skipped a step and a hole at the end stops the deck mid-argument. Here every critic
    passes, and the shortfall blocks anyway.
    """
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry)
    env.llm_call = CriticStub()  # no failing rounds — every frame passes, every round
    downloads.fail_contains = "slide-3-"
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    assert record.gauntlet["result"] == "pass", "the gate had no objection to the frames it saw"
    assert record.status is AssetStatus.BLOCKED and entry.status is PlanEntryStatus.BLOCKED
    assert record.skip_reason.startswith("incomplete_deck:") and "(FR-363)" in record.skip_reason
    assert "incomplete_deck" in env.log.types(), "an error line, never a silent badge"
    assert env.log.fields("incomplete_deck")["slides_ordered"] == 4
    assert sorted(path.name for path in folder.path.glob("slide_*.jpg")) == [
        "slide_01.jpg", "slide_02.jpg", "slide_04.jpg"], "FR-74: every paid slide stays on disk"
    assert (folder.path / packager.BLOCKED_FILE).is_file()
    assert packager.read_meta(folder.path)["status"] != "success"


async def test_fr363_a_complete_deck_still_finishes_success(tmp_path: Path) -> None:
    """The control, and the reason the test above proves anything: the SAME critics, the same
    submission, every ordered slide delivered — and the deck ships as a success with no block
    file, no skip reason and no incomplete badge. FR-363 refuses a shortfall, not a carousel."""
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry)
    env.llm_call = CriticStub()
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    assert record.status is AssetStatus.SUCCESS and entry.status is PlanEntryStatus.SUCCESS
    assert record.slide_count == 4 and record.missing_slide_numbers == []
    assert not record.skip_reason and "incomplete_deck" not in env.log.types()
    assert "incomplete" not in [tag.value for tag in record.degradations]
    assert not (folder.path / packager.BLOCKED_FILE).exists()
    assert packager.read_meta(folder.path)["status"] == "success"


async def test_an_incomplete_deck_carries_the_run_to_exit_one(
    tmp_path: Path, downloads: SimpleNamespace
) -> None:
    """The 2026-08-11 regression, end to end: the deck the carousel really packages must reach
    FR-202's code 1 through the tag it really writes.

    `output/20260811_233910_wikf` delivered 6/6 creatives and exited **0** ("everything planned was
    delivered") while one meta.yaml said `status: success`, `slide_count: 4`,
    `missing_slide_numbers: [2]`, `degradations: ['text_trimmed', 'incomplete']` — slide 2 lost to
    "timeout — no terminal state within 180s". FR-202: "a delivered carousel shipped incomplete …
    a lost slide is a loss even when the deck ships".

    The entry deliberately carries **no `skip_reason`** — the deck shipped, so `package()` marks the
    folder instead — which is precisely why `decide_exit_code` has to read the degradation tags.
    """
    from hypesocials.runner import EXIT_OK, EXIT_PARTIAL, decide_exit_code

    entry = make_entry(slides=5)  # the live deck: five planned, four delivered, slide 2 timed out
    env = make_env(tmp_path, entry, texts=[f"line {n}" for n in range(5)])
    downloads.fail_contains = "slide-2-"

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    assert record.status is AssetStatus.BLOCKED and record.slide_count == 4
    assert record.missing_slide_numbers == [2]
    # D65/FR-363 closes the same gap a second time, and from the other end: the deck no longer
    # ships at all, so the entry carries a BLOCKED status and a `skip_reason` and the exit code is
    # 1 from the entry alone. The tag route below still has to answer 1 as well — it is what
    # catches every OTHER delivered loss (`text_trimmed`, `copy_degraded`), and a run whose only
    # evidence is a badge must never exit 0.
    assert entry.status is PlanEntryStatus.BLOCKED and entry.skip_reason
    degradations = {record.asset_id: record.degradations}  # the map `runner._package` builds
    assert decide_exit_code([entry]) == EXIT_PARTIAL, "the blocked entry is a loss on its own"
    assert decide_exit_code([entry], degradations=degradations) == EXIT_PARTIAL


async def test_an_incomplete_deck_names_every_lost_slide_not_the_first_three(
    tmp_path: Path,
) -> None:
    """`missing_slide_numbers` and `detail` are two halves of ONE line and they must agree.

    `detail` was capped at three reasons while the numbers listed all of them, so a six-slide deck
    that lost five announced "missing [2, 3, 4, 5, 6]" and then explained three — leaving the
    operator to guess which two slides died of what, on the single line written to tell them. The
    cap bought nothing: this is a structured field in events.jsonl, not a console line with a
    width to protect, and the loss it truncates is exactly the loss it exists to report.

    The obligation belongs to the terminal line whatever the terminal IS. Losing five slides to
    provider failures is a D51 viability loss now rather than an incomplete ship (the deck is not
    published), so the numbers and their explanations are asserted on `deck_viability_loss` — the
    line that replaced `carousel_incomplete` for this deck — and they must still agree.
    """
    entry = make_entry(slides=6)
    env = make_env(tmp_path, entry, texts=[f"line {n}" for n in range(1, 7)])
    submit = FakeSubmit(rule=lambda call: ok(call) if call.slide == 1 else failed())

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert record.missing_slide_numbers == [2, 3, 4, 5, 6] and record.slide_count == 1
    fields = env.log.fields("deck_viability_loss")
    assert fields["missing_slide_numbers"] == [2, 3, 4, 5, 6]
    detail = fields["detail"]
    assert sorted(int(number) for number in _SLIDE_NO.findall(detail)) == [2, 3, 4, 5, 6], \
        "every missing number in the same line has its own explanation"
    assert detail.count("provider_fail") == 1 and detail.count("not ordered") == 4, \
        "the slide that died says how; the four never ordered each say why not"


async def test_a_deck_that_delivers_nothing_keeps_its_paid_artifacts(tmp_path: Path) -> None:
    """FR-74: the copy was paid for, so the folder, the caption and a failed meta all survive."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    folder = make_folder(tmp_path, entry)
    folder.write_caption("Most people wire this backwards.", ["#ai"])

    record = await render_carousel(entry, env, folder, submit=FakeSubmit(rule=lambda c: failed()))

    assert record.status is AssetStatus.FAILED and entry.status is PlanEntryStatus.FAILED
    assert record.missing_slide_numbers == [1, 2, 3] and record.slide_count == 0
    assert (folder.path / "caption.txt").is_file()
    assert (folder.path / "SKIP_REASON.txt").read_text(encoding="utf-8").strip()
    assert record.actual_cost_usd > 0, "spend tallies on submission, failures included (FR-106)"


async def test_moderation_refusal_retries_reference_free_as_discretionary(
    tmp_path: Path,
) -> None:
    """FR-97: one resubmission with every reference removed, marked `refs_dropped_moderation`.

    Slide 2 is the one refused because a body slide always HAS a reference — the chained anchor —
    which is what there is to drop. The refusal on a job that carried nothing is the sibling case
    below, and it does not retry at all.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    refused: set[int] = set()

    def rule(call: Call) -> RenderOutcome:
        if call.slide == 2 and call.slide not in refused:
            refused.add(call.slide)
            return failed(RenderFailCause.MODERATION)
        return ok(call)

    submit = FakeSubmit(rule=rule)
    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    retry = next(call for call in submit.calls if call.kind == "discretionary")
    assert retry.slide == 2 and retry.image_urls == [], "every reference removed (FR-97)"
    assert retry.job == "slide" and retry.priority is RenderPriority.WAVE2
    assert "refs_dropped_moderation" in [tag.value for tag in record.degradations]
    assert record.slide_count == 3, "the deck is whole; only the references were dropped"
    assert "moderation_retry" in env.log.types()


async def test_a_refused_reference_free_slide_is_never_resubmitted(tmp_path: Path) -> None:
    """FR-97's remedy is dropping references, so a job that carried NONE has no remedy left.

    Post-D46 that is the ordinary anchor: an unbriefed slide 1 renders text-to-image, and a
    moderation refusal on it must fail straight through to FR-95's replacement anchor and then to
    the independent-slide fallback, rather than buy a byte-identical resubmission at full price.
    Every fallback slide is likewise reference-free, so not one of them retries either.

    The deck's ENDING moved with D51 and the shape is asserted here beside the retry rule: a cover
    refused on all three of its attempts is a slide with no path left, so the deck is unsalvageable
    and nothing further is ordered for it — slides 2 and 3 are never bought at all, which is the
    whole saving the viability gate exists for. What was already submitted is never cancelled; here
    that is the three refused covers, each of which is in the ledger and cost what it cost.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    submit = FakeSubmit(rule=lambda call: failed(RenderFailCause.MODERATION)
                        if call.slide == 1 else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call.kind for call in submit.calls] == ["projected", *["precommitted"] * 2], \
        "one refused anchor, its replacement, its unchained third — no discretionary retry anywhere"
    assert [call.slide for call in submit.calls] == [1, 1, 1], \
        "slides 2 and 3 are never ordered for a deck whose cover has no path left (D51)"
    assert "moderation_retry" not in env.log.types()
    # `getattr(tag, "value", tag)`, not `tag.value`: `deck_viability_loss` rides as a plain string
    # until `DegradationTag` carries the member (`carousel.DECK_VIABILITY_LOSS`, the same
    # convention as `PANELS_TRUNCATED`), and meta.yaml holds identical bytes either way.
    tags = [str(getattr(tag, "value", tag)) for tag in record.degradations]
    assert "refs_dropped_moderation" not in tags
    assert "carousel_anchor_retry" in env.log.types()
    assert "carousel_anchor_fallback_unchained" in env.log.types()
    assert record.status is AssetStatus.FAILED, "a deck with no cover is never published (D51)"
    assert "deck_viability_loss" in tags


async def test_halt_before_the_deck_orders_nothing_and_packages_honestly(
    tmp_path: Path,
) -> None:
    """FR-201/108: Ctrl+C and the deadline stop ORDERING; nothing was bought for this deck."""
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry, halted=True)
    submit = FakeSubmit()
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=submit)

    assert submit.calls == [], "not one slide was ordered"
    assert record.status is AssetStatus.FAILED
    assert entry.status is PlanEntryStatus.ABANDONED
    assert "abandoned" in [tag.value for tag in record.degradations]
    assert "interrupted" in (record.skip_reason or "")
    assert record.actual_cost_usd == 0.0


async def test_halt_after_the_anchor_ships_the_slides_that_exist(tmp_path: Path) -> None:
    """A halt mid-deck stops ordering and packages what already landed (FR-201)."""
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry)

    def rule(call: Call) -> RenderOutcome:
        env.halted = True  # the operator hits Ctrl+C while slide 1 is in flight
        return ok(call)

    submit = FakeSubmit(rule=rule)
    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call.slide for call in submit.calls] == [1]
    assert record.slide_count == 1 and record.missing_slide_numbers == [2, 3, 4]
    assert "incomplete" in [tag.value for tag in record.degradations]


async def test_out_of_credits_packages_the_deck_instead_of_raising(tmp_path: Path) -> None:
    """FR-167: the 402 is a whole-run condition — latched once, never re-tried per slide."""
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry)

    def rule(call: Call) -> Any:
        return ok(call) if call.slide == 1 else KieOutOfCredits("HTTP 402")

    record = await render_carousel(entry, env, make_folder(tmp_path, entry),
                                   submit=FakeSubmit(rule=rule))

    assert env.credits_exhausted is True
    assert record.slide_count == 1 and record.missing_slide_numbers == [2, 3, 4]
    # FR-167's point is that the 402 does not RAISE: the deck is packaged, the latch is set and the
    # run goes on to package everything else. What that packaging says changed at D65/FR-363 — one
    # of four ordered slides is an incomplete deck and is refused terminal, whatever took the other
    # three away.
    assert record.status is AssetStatus.BLOCKED


# ------------------------------------------------- D49 the gauntlet: fix loop and three tiers


async def test_a_failing_frame_is_re_rendered_with_a_canned_fix_and_never_new_words(
    tmp_path: Path,
) -> None:
    """FR-323: the fix channel is CANNED remedies keyed by `(code, zone)`, and it may not touch
    the words. A quote shortened to make it fit is the defect the gate exists to catch.

    The critic's own `detail` never reaches the payload either — it goes to the report, the events
    and the console only, because an operator-authored override sheet is the boundary that makes
    that rule worth enforcing rather than assuming.
    """
    panel = ("Claude reads your whole vault every single time and Obsidian's index does not - "
             "that one swap is where the 71.5x saving comes from.")
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=[panel, "two", "three"], trends=make_trends(panels=3))
    # `garbled` is a CRAFT code, so the owning critic also runs in the anchor pre-gate: the
    # first entry is that pre-gate round and the second is the deck round that fails. The pre-gate
    # has TWO rounds since FR-324, but a clean round 1 returns before either of them is spent, so
    # a passing entry 0 still consumes exactly one entry.
    env.llm_call = CriticStub(rounds=[set(), {1}], code="garbled",
                              detail="ZZDETAIL doubled glyphs")
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    fix = submit.calls[-1]
    assert fix.slide == 1 and fix.kind == "discretionary"
    assert fix.priority is RenderPriority.WAVE2, "the deck is rendered; this is the fix loop"
    assert quoted_text(fix.prompt) == panel, "FR-304: the quote is byte-identical on a re-render"
    assert "FIX — this is a re-render of a frame that failed review." in fix.prompt
    assert "ZZDETAIL" not in fix.prompt, "a critic's own words never reach a render payload"
    assert "It contains no words to render." in fix.prompt, "the fence-closing line (FR-323)"
    assert dna_block(submit.calls[0].prompt) == dna_block(fix.prompt), \
        "a fix changes the request, never the deck's style DNA"
    assert record.gauntlet["rerenders"] == 1
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED


async def test_the_contract_carries_each_frames_locked_text_as_the_referent(
    tmp_path: Path,
) -> None:
    """FR-322: a critic cannot see an invented or a missing string without knowing what was
    ordered. A wordless mapped panel says `(none)`, which is the stronger claim of the two."""
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["Panel one verbatim", "", "Panel three verbatim"],
                   trends=make_trends(panels=3))
    env.llm_call = CriticStub()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    deck = env.llm_call.prompt_for("brief", 1)  # [0] is the anchor pre-gate, clean in one round
    assert 'L1: "Panel one verbatim"' in deck
    assert "(none) — wordless by mandate" in deck, "a wordless frame carries no invented words"
    assert 'L1: "Panel three verbatim"' in deck


async def test_a_standing_leakage_defect_blocks_the_deck_and_keeps_every_artifact(
    tmp_path: Path,
) -> None:
    """FR-325 tier 1: `invented_text` standing after the last round BLOCKS, whatever `fail_action`
    says, and blocking withholds publication rather than deleting anything (FR-74).

    The plan entry goes `BLOCKED` — a non-success everywhere success matters, so the source post is
    not burnt in the history window and the run exits 1 — and the folder gains the two files that
    explain it.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.config.run.gauntlet.rounds_max = 2
    # `invented_text` is a BRIEF code, so the owning critic runs in the anchor pre-gate too:
    # entry 0 is that pre-gate round — clean, so the pre-gate returns after it and never reaches
    # the fix round FR-324 grants it — and entries 1-2 are the deck's two rounds. Round 2 names
    # SLOT 1 rather than slot 2 because FR-324 scopes brief to the RE-RENDERED frames alone, so
    # the one frame attached in round 2 is slide 2 - the scoping made visible.
    env.llm_call = CriticStub(rounds=[set(), {2}, {1}], code="invented_text",
                              detail="ZZ extra words")
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    assert record.status is AssetStatus.BLOCKED and entry.status is PlanEntryStatus.BLOCKED
    assert record.gauntlet["result"] == "blocked"
    assert record.slide_count == 3, "every paid slide is kept on disk"
    assert sorted(path.name for path in folder.path.glob("slide_*.jpg")) == [
        "slide_01.jpg", "slide_02.jpg", "slide_03.jpg"]
    blocked = (folder.path / packager.BLOCKED_FILE).read_text(encoding="utf-8")
    assert "BLOCKED" in blocked and "NOT published" in blocked
    assert "invented_text on frame" in blocked, "the paragraph names the standing defect"
    report = yaml.safe_load(
        (folder.path / packager.GAUNTLET_REPORT_FILE).read_text(encoding="utf-8"))
    assert report["result"] == "blocked" and len(report["rounds"]) == 2
    assert any(row["code"] == "invented_text" and row["detail"] == "ZZ extra words"
               for round_row in report["rounds"] for row in round_row["defects"]), \
        "the critic's own wording belongs in the report a PERSON reads, and only there"


async def test_a_craft_only_standing_failure_ships_tagged_rather_than_blocking(
    tmp_path: Path,
) -> None:
    """FR-325 tier 3: craft is an opinion about quality, and blocking a deck on one costs more
    than the defect. The deck ships, carries `GAUNTLET_CRAFT`, and says so in its receipt."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.config.run.gauntlet.rounds_max = 1
    env.llm_call = CriticStub(rounds=[set(), {2}], code="contrast", detail="pale on pale")
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    assert record.status is AssetStatus.SUCCESS and entry.status is PlanEntryStatus.SUCCESS
    assert record.gauntlet["result"] == "pass" and record.gauntlet["craft_only"] is True
    assert carousel_module.GAUNTLET_CRAFT in record.degradations
    assert not (folder.path / packager.BLOCKED_FILE).exists()


async def test_a_low_confidence_craft_opinion_never_fails_a_frame_at_all(
    tmp_path: Path,
) -> None:
    """Spec §3: `craft` defects at `confidence: low` are RECORDED and never fail the frame — the
    publish bar is "would a reasonable operator refuse to publish this", and unsure means yes."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.llm_call = CriticStub(rounds=[set(), {2}], code="composition", confidence="low")
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call for call in submit.calls if call.kind == "discretionary"] == []
    assert record.gauntlet["result"] == "pass" and record.gauntlet["rerenders"] == 0


async def test_the_per_deck_budget_stops_the_fix_loop_and_the_deck_still_ships(
    tmp_path: Path,
) -> None:
    """The money seam (spec §1): `run.gauntlet.deck_budget_usd` is a REAL gate the caller enforces,
    and the gauntlet maps the refusal to `budget_stop`. The frames already on disk still ship."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.config.run.gauntlet.deck_budget_usd = 0.01  # under one render's projection
    env.price_job = lambda _entry, _job: 0.04
    env.llm_call = CriticStub(rounds=[{2}], code="style_layout")
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call for call in submit.calls if call.kind == "discretionary"] == [], \
        "nothing was ordered once the per-deck cap was reached"
    assert record.gauntlet["result"] == "budget_stop"
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 3
    assert "gauntlet_budget_stop" in env.log.types()


async def test_f4_concurrent_fix_re_renders_can_never_jointly_outspend_the_per_deck_cap(
    tmp_path: Path,
) -> None:
    """F4 (Session 5.5): the cap is a RESERVATION, not a reading of what was already billed.

    `gauntlet._rerender_all` gathers every failing frame of a round CONCURRENTLY, and the old check
    read `gauntlet_spend` — a number that only moves after the awaits finish. On 2026-08-14 that
    let eleven $0.03 re-renders ship against a $0.30 cap: eight of the eleven checks each saw
    $0.00. `_claim` now decides and debits under one lock and `_settle` releases in a `finally`,
    which is `Budget.reserve`'s own pattern one scope down.

    Eight frames fail at once against a cap that fits six. WHICH two are declined is not the claim
    — it depends on the order `gather` happens to resume the closures in — so the assertions are
    counts and totals, which are deterministic: six times $0.03 is the largest multiple of the
    projection that fits under $0.20, and the seventh claim is refused before it can be submitted.
    """
    entry = make_entry(slides=8)
    env = make_env(tmp_path, entry, texts=[f"line {n}" for n in range(1, 9)])
    env.config.run.gauntlet.deck_budget_usd = 0.20
    env.price_job = lambda _entry, _job: 0.03
    # `style_layout` is a SYSTEM code, and system does not sit on the anchor pre-gate — so the
    # pre-gate passes untouched and entry 0 IS the deck's round 1, failing all eight frames.
    env.llm_call = CriticStub(rounds=[set(range(1, 9))], code="style_layout")
    submit = FakeSubmit(rule=lambda call: ok(call, cost=0.03))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    fixes = [call for call in submit.calls if call.kind == "discretionary"]
    declined = [data for name, data in env.log.data
                if name == "gauntlet_rerender" and data.get("status") == "declined_deck_budget"]
    assert len(fixes) == 6, (
        f"{len(fixes)} re-renders = ${0.03 * len(fixes):.2f} against a $0.20 cap")
    assert len(declined) == 2, "every frame the cap could not pay for is refused, not skipped"
    assert len(fixes) + len(declined) == 8, "eight frames failed; each one got an answer"
    assert record.gauntlet["rerender_cost_usd"] == pytest.approx(0.18)
    assert record.gauntlet["rerender_cost_usd"] <= env.config.run.gauntlet.deck_budget_usd
    assert record.gauntlet["rerenders"] == 6 and record.gauntlet["result"] == "budget_stop"
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 8, \
        "a deck that ran out of fix money still ships every slide it paid for"


async def test_f4_a_declined_claim_is_given_back_so_the_next_round_can_still_spend_it(
    tmp_path: Path,
) -> None:
    """The `finally` half of F4: a claim that never became a submission is RELEASED.

    A leaked reservation is a deck refusing its own next fix over money it never spent, and there
    are five returns to leak one from. Here the runway refusal fires after the claim, so every
    frame of round 1 claims, refuses and gives the money back — and the cap is untouched.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.config.run.gauntlet.deck_budget_usd = 0.20
    env.price_job = lambda _entry, _job: 0.03
    env.runway_ok = lambda _job: False  # refused AFTER `_claim`, which is the leak site
    env.llm_call = CriticStub(rounds=[{2, 3}], code="style_layout")
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call for call in submit.calls if call.kind == "discretionary"] == []
    assert record.gauntlet["rerender_cost_usd"] == pytest.approx(0.0), "nothing was billed"
    assert "gauntlet_budget_stop" not in env.log.types(), \
        "no frame was ever refused for money: both claims were handed straight back"
    assert record.gauntlet["result"] == "deadline_stop"


def test_f1c_a_fix_re_render_is_assembled_against_the_same_body_budget_as_its_first_render(
    tmp_path: Path,
) -> None:
    """F1-C: `_prompt_cap` reserves the fix channel on EVERY pass, so the rulebook never moves.

    `PromptEngine.render(suffix=...)` counts the suffix inside `max_chars` — correctly, because the
    provider counts it — so passing the raw profile limit gave a first render `cap` characters of
    body and a re-render `cap - len(fix) - 2`. This template's assembled tail is the back half of
    CONSTRAINTS, so round 2 was judged against rules round 2 was never sent: 924-1,248 characters
    of lost rulebook per fix round in the 2026-08-14 run, and a loop that oscillates rather than
    converging. Hold the reservation always, hand the real suffix's room back when there is one,
    and never exceed the wall.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    deck = carousel_module._Deck(entry, env, make_folder(tmp_path, entry), FakeSubmit())
    wall = deck._limits.max_prompt_chars
    reserve = gauntlet.fix_reserve(env.engine)
    fix = "F" * (reserve - carousel_module._SUFFIX_SEPARATOR)  # the longest suffix reserved for

    first, retry = deck._prompt_cap(""), deck._prompt_cap(fix)

    assert first == wall - reserve, (first, wall, reserve)
    assert retry - (len(fix) + carousel_module._SUFFIX_SEPARATOR) == first, \
        "the body budget moved between passes — this is the defect F1-C closed"
    assert retry <= wall, "the provider's wall is never exceeded, whatever the sheet says"
    assert deck._prompt_cap("a short remedy") - len("a short remedy") - 2 == first, \
        "an ordinary suffix rides in the space already held back for it"


async def test_f1c_a_real_fix_round_assembles_the_same_rulebook_the_first_render_carried(
    tmp_path: Path,
) -> None:
    """F1-C end to end: the fix rides AFTER an unchanged rulebook, not instead of its tail.

    The two prompts are not identical and must not be — a re-render legitimately gains FR-323's
    nearest-delivered-neighbour reference. What must not move is the CONSTRAINTS block, because
    that is what the assembler dropped when the suffix ate into the budget and what the critics
    judge the replacement against.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["Wired backwards", "Two", "Three"])
    env.llm_call = CriticStub(rounds=[{2}], code="style_layout")
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    wall = render.get_profile(env.config.models.image_profile).limits.max_prompt_chars
    first = next(call for call in submit.calls
                 if call.slide == 2 and call.kind != "discretionary")
    fix = next(call for call in submit.calls if call.kind == "discretionary")
    assert len(first.prompt) <= wall and len(fix.prompt) <= wall
    body, _, suffix = fix.prompt.partition("\n\nFIX — this is a re-render")
    assert suffix, "the canned remedy is a SUFFIX, appended after the finished prompt"
    assert body.split("CONSTRAINTS:", 1)[1] == first.prompt.split("CONSTRAINTS:", 1)[1], \
        "round 2 was assembled against a different rulebook than round 1"
    assert quoted_text(fix.prompt) == quoted_text(first.prompt), "FR-304: the words never move"


async def test_an_expired_runway_declines_the_fix_rather_than_buying_a_certain_timeout(
    tmp_path: Path,
) -> None:
    """D51 inside the money seam: a job the clock cannot pay for is refused BEFORE the reservation,
    which is what makes the refusal free. The gauntlet maps it to `deadline_stop`."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.runway_ok = lambda _job: False
    env.llm_call = CriticStub(rounds=[{2}], code="style_layout")
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call for call in submit.calls if call.kind == "discretionary"] == []
    assert record.gauntlet["result"] == "deadline_stop"
    assert record.status is AssetStatus.SUCCESS, "the deck ships what the clock already paid for"


async def test_a_failed_fix_re_render_is_not_reported_as_a_lost_slide(
    tmp_path: Path, downloads: SimpleNamespace
) -> None:
    """A fix that never happens loses NOTHING - the slide it was improving already shipped.

    `missing_slide_numbers` and `carousel_incomplete.detail` are read as one sentence, so a
    "slide 2: declined by the spend cap" line beside `missing: [3]` told the operator slide 2 was
    lost when slide 2 is on disk. A declined fix is a log line and nothing in the loss ledger.

    Slide 3 is lost to its DOWNLOAD rather than to its render, deliberately: a slide lost to a
    render defect stops the deck outright (D51) and there would be no fix left to decline, while a
    failed download is our end of a job the provider completed - 10 §10's partial deck.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.llm_call = CriticStub(rounds=[{2}], code="style_layout")
    downloads.fail_contains = "slide-3-"  # slide 3 renders and never lands on disk
    submit = FakeSubmit(rule=lambda call: None if call.kind == "discretionary" else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert record.missing_slide_numbers == [3], "only the slide that never rendered is missing"
    detail = env.log.fields("carousel_incomplete")["detail"]
    assert "slide 3" in detail and "slide 2" not in detail, "a delivered slide is not a loss"
    assert "vision_retry_unavailable" in env.log.types(), "the declined fix is still visible"
    assert record.gauntlet["result"] == "budget_stop"


async def test_an_unreadable_critic_is_dropped_and_the_deck_still_ships(tmp_path: Path) -> None:
    """D3: a broken checker never blocks delivery. An unparseable critic is dropped for the whole
    deck, the round is judged on the survivors, and `degraded_gate` says the gate was thinner."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.llm_call = CriticStub(unavailable=["brief"])

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    assert record.status is AssetStatus.SUCCESS
    assert record.gauntlet["degraded_gate"] is True
    assert "brief" in record.gauntlet["rounds"][0]["unavailable"]
    assert carousel_module.GAUNTLET_DEGRADED in record.degradations


async def test_the_receipt_records_every_round_on_the_terminal_path(tmp_path: Path) -> None:
    """FR-328/spec §6: `meta.yaml.gauntlet` carries the whole shape on EVERY terminal path."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.config.run.gauntlet.rounds_max = 2
    env.llm_call = CriticStub(rounds=[{3}], code="style_layout")
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    gate = record.gauntlet
    assert set(gate) == {"result", "degraded_gate", "craft_only", "rounds", "rerenders",
                         "rerender_cost_usd", "critic_cost_usd"}
    assert gate["result"] == "pass" and gate["rerenders"] == 1
    assert gate["rounds"][0]["failed_frames"] == [3] and gate["rounds"][0]["rerendered"] == [3]
    stored = yaml.safe_load((folder.path / packager.META_FILE).read_text(encoding="utf-8"))
    assert stored["gauntlet"]["result"] == "pass", "and it survives the YAML round trip"


async def test_disk_full_stops_further_downloads_and_flags_the_run(
    tmp_path: Path, downloads: SimpleNamespace
) -> None:
    """10 §10: that creative fails with `disk_full` and further downloads STOP rather than
    thrash a full disk — the condition outlives this deck, so the run carries it."""
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry)
    downloads.fail_contains, downloads.fail_reason = "slide-2-", "disk_full"
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    assert env.disk_full is True, "the runner needs this beyond the one creative"
    assert [url for url in downloads.fetched if "slide-3-" in url or "slide-4-" in url] == []
    assert record.slide_count == 1 and record.missing_slide_numbers == [2, 3, 4]
    assert sorted(path.name for path in folder.path.glob("slide_*.jpg")) == ["slide_01.jpg"]
    assert "disk_full" in " ".join(message for _, message in env.log.records)


# ------------------------------------------------- D-D the slide counter (v2.1.2, visual fidelity)


async def test_a_counted_source_deck_numbers_every_slide_over_our_own_length(
    tmp_path: Path,
) -> None:
    """D-D: the badge is the SOURCE's convention, re-based onto the deck we actually ship.

    The source signed each slide "01 / 06" in its chrome; our deck is three slides long because
    the platform ceiling cut it (§0.4′). Copying their numbers would print "03 / 06" on the last
    slide and tell the reader three slides are missing, so the padding, the spacing and the slash
    are kept while the numbers are re-based — and unlike the wordmark, which signs slide 1 alone
    (M12), a page badge belongs on every page.
    """
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two", "three"], trends=make_trends(panels=6))
    give_intel(env, panels=6, chrome=[f"@knox | skool.com/knox | 0{n} / 06 | swipe"
                                      for n in range(1, 7)])
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    badges = [re.search(r'counter \(render verbatim\): "(.*)"', call.prompt)
              for call in submit.calls]
    assert [match.group(1) for match in badges if match] == ["01 / 03", "02 / 03", "03 / 03"], \
        "every slide states its own place, in the source's hand, over OUR length"
    for call in submit.calls:
        assert "counter (render verbatim)" in text_block(call.prompt), \
            "the badge renders through the TEXT block, never as a layout instruction"
        assert "spelled out" not in text_block(call.prompt), \
            "Session 5.5/F1-B: digits and a slash carry no accent, so no letter-by-letter echo"


async def test_an_uncounted_source_deck_orders_no_badge_at_all(tmp_path: Path) -> None:
    """The absence is the common case, and on a style that describes a chip it is STATED.

    A style whose layout declares a position chip, with no string to put in it, is the single
    biggest hallucination site the render models have: they fill it with an invented "01", a "3/7"
    that matches no deck, or a page number. So an uncounted deck quotes no counter, and where the
    style asked for a badge the slide is told out loud that this deck carries none.

    **D59/FR-338 moved that sentence into `{{counter_rule}}`** and gated it on the style, which is
    the second half of this test. The old prose said "this deck carries no slide counter" on every
    slide of every deck — including decks in styles that never described a chip, where it was a
    paragraph of uncuttable prompt suppressing a device nobody had ordered. Now: a declaring style
    gets the absence line, a silent style gets an empty slot, and neither gets a badge.
    """
    counter_zone = LayoutZone("top-right corner", "slide-position badge", "small mono chip",
                              role="counter_slot")
    declaring = make_style(tmp_path)
    declaring.layout_zones = [*declaring.layout_zones, counter_zone]

    for style, declares in ((make_style(tmp_path), False), (declaring, True)):
        entry = make_entry(slides=3, source_post_id="post-a")
        env = make_env(tmp_path, entry, texts=["one", "two", "three"],
                       trends=make_trends(panels=3), style=style)
        give_intel(env, panels=3, chrome=["@knox | skool.com/knox", "swipe on", ""])
        env.llm_call = CriticStub()
        submit = FakeSubmit()

        await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

        assert submit.calls, "the deck rendered"
        for call in submit.calls:
            assert "counter (render verbatim)" not in call.prompt
            stated = pe._NO_COUNTER_LINE.lower() in call.prompt.lower()
            assert stated is declares, (
                "a style that declares a counter_slot zone is told the deck carries none; "
                "a style that never described a chip is told nothing (D59/FR-338)")
        assert all("/ 03" not in system for system in env.llm_call.systems), \
            "and every critic is told to expect no badge either"


async def test_the_counter_travels_into_the_gauntlet_contract(tmp_path: Path) -> None:
    """A badge we ORDERED is ordered words: unlisted, it reads as invented text on every frame.

    The `brief` critic compares what is drawn against what was ordered, so a deck that renders
    "2/3" exactly as instructed would be failed for three invented characters — and every failing
    frame would buy a discretionary fix re-render against a defect nobody has. The counter is its
    own contract row rather than a body line, which is also why a wordless panel of a COUNTED deck
    is still `(none)` for its words and still carries its badge.
    """
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["Panel one", "", "Panel three"],
                   trends=make_trends(panels=3))
    give_intel(env, panels=3, chrome=["1/3", "2/3", "3/3"])
    env.llm_call = CriticStub()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    deck = env.llm_call.prompt_for("brief", 1)
    assert 'L1: "Panel one"' in deck and 'counter: "1/3"' in deck
    assert 'counter: "2/3"' in deck, \
        "a wordless panel of a counted deck still carries the badge it was ordered"
    assert 'L1: "Panel three"' in deck and 'counter: "3/3"' in deck


async def test_a_deck_with_no_slide_intelligence_counts_nothing(tmp_path: Path) -> None:
    """Fail-open (§0.14c): intelligence that degraded costs the badge, never the deck.

    Every pre-D-D path lands here — an override brief that binds no post, a run whose vision pass
    failed, an older `Env` with no `slide_intel` field at all — and all of them render exactly as
    they did before, which is what makes this seam safe to add.
    """
    entry = make_entry(slides=2, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two"], trends=make_trends(panels=2))
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert not hasattr(env, "slide_intel"), "the field is optional by design"
    assert all("counter (render verbatim)" not in call.prompt for call in submit.calls)
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 2


# ------------------------------------------- FR-313 (D59): the counter receipt on `meta.yaml`


async def test_a_counted_decks_meta_records_the_badge_and_the_rule_that_found_it(
    tmp_path: Path,
) -> None:
    """FR-313 amended (D59): the deck says on disk that it counts itself, and on what evidence.

    A wrong page badge is one of the few defects an operator can see instantly and cannot debug at
    all — the badge is drawn by a render model from a string the pipeline detected six stages
    earlier. So the detection is filed beside the artifacts: WHICH accept rule believed it (a
    denominator that equalled the source deck's own length is the strong one; an uncorroborated
    offset is the one to doubt first), the source's hand described structurally, and slide 1's
    badge as this deck actually ordered it.

    `sample` is re-based onto OUR three slides exactly as the rendered badge is — a receipt that
    said "01 / 06" about a deck shipping "01 / 03" would document a badge nobody rendered.
    """
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two", "three"], trends=make_trends(panels=6))
    give_intel(env, panels=6, chrome=[f"@knox | skool.com/knox | 0{n} / 06 | swipe"
                                      for n in range(1, 7)])
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    stored = packager.read_meta(folder.path)["counter"]
    assert stored == record.counter, "the record and the file are one document, not two"
    assert stored["detected"] is True
    assert stored["rule"] == "denominator", (
        "rule 1: the badges' denominator WAS the source deck's length — the strongest evidence")
    assert stored["sample"] == "01 / 03", "our own length, in their hand"
    assert "pad=2" in stored["pattern"] and "sep=' / '" in stored["pattern"], (
        "the spacing around the slash is the source's typography: described, not normalised")
    assert "numerator_only=False" in stored["pattern"], "this convention showed a total"


async def test_an_uncounted_bound_deck_still_files_a_counter_row_saying_no(
    tmp_path: Path,
) -> None:
    """The absence is the common case, so it is RECORDED rather than left to a missing key.

    "This deck ships no badge" is what `detected: false` claims, and it is the claim that matters:
    a reader branches on that one bool and never on whether three strings happen to be empty. The
    row exists for every bound deck — including one whose vision pass degraded and never got to
    look — because a key that appears only on counted decks makes every reader ask two questions
    where the schema should answer one.
    """
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two", "three"], trends=make_trends(panels=3))
    give_intel(env, panels=3, chrome=["@knox | skool.com/knox", "swipe on", ""])
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    assert record.counter == {"detected": False, "rule": "", "pattern": "", "sample": ""}
    assert packager.read_meta(folder.path)["counter"] == record.counter

    blind = make_entry(slides=2, asset_id="0003_carousel_linkedin", source_post_id="post-a")
    blind_env = make_env(tmp_path, blind, texts=["one", "two"], trends=make_trends(panels=2))
    blind_folder = make_folder(tmp_path, blind)

    degraded = await render_carousel(blind, blind_env, blind_folder, submit=FakeSubmit())

    assert not hasattr(blind_env, "slide_intel"), "no vision pass ran on this one at all"
    assert degraded.counter == {"detected": False, "rule": "", "pattern": "", "sample": ""}, (
        "a deck that never got to look still ships no badge, and that is what the row states")


async def test_a_creative_that_bound_no_source_deck_files_no_counter_row_at_all(
    tmp_path: Path,
) -> None:
    """`None`, not `detected: false` — the question is about a deck that does not exist.

    An override brief binds no source post (FR-144/§0.14d), and neither does an image or a reel.
    "Their deck carried no counter" would be an answer about nobody's deck, so the field stays
    null and the gallery, the publisher and the operator all read the same absence.
    """
    entry = make_entry(slides=2, brief_name="ai-audit-cta", brief_influence="override")
    env = make_env(tmp_path, entry, texts=["one", "two"])
    env.campaign_briefs = {"ai-audit-cta": Brief(
        name="ai-audit-cta", description="a standing CTA card", influence="override",
        visual_directives={"scene": "ZZBRIEF a laptop on a bare desk, one product card"},
        copy_directives={"message": "book an AI audit"})}
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    assert not entry.source_post_id, "an override brief is never bound to a post at ASSIGN"
    assert record.counter is None
    stored = packager.read_meta(folder.path)
    assert "counter" in stored and stored["counter"] is None, (
        "written as an explicit null, so the key means the same thing on every creative")
    # Images and reels reach the same value from the other side: neither packager passes the
    # field, so the dataclass default is what their `meta.yaml` carries.
    assert AssetRecord(asset_id="0004_image_linkedin", source="t1", source_name="AI tool stacks",
                       platform="linkedin", creative_format="image").counter is None


# --------------------------------------------- D-A sanctioned tool marks (v2.1.2, visual fidelity)


async def test_a_panels_own_product_logo_is_sanctioned_and_everything_else_is_not(
    tmp_path: Path,
) -> None:
    """D-A: the ONE element exempt from the style's palette is a real mark the panel showed.

    A source slide about tool stacks shows the tools' logos, and greeking them into unlettered
    blobs loses the whole point of the slide. What may NOT be sanctioned is everything the rest of
    this system already forbids: a configured competitor (M6 — the screen's verdict outranks the
    panel), the creator's own signature, and platform chrome, which every render template bans in
    every frame whatever this line says.
    """
    entry = make_entry(slides=2, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two"], trends=make_trends(panels=2))
    env.branding = BrandingConfig(brand="hypelead", competitors=["Jasper"])
    give_intel(env, panels=2, marks=[
        ["Notion logo icon", "Obsidian app icon", "TikTok watermark", "@creator handle",
         "Jasper logo", "creator wordmark"],
        []])
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert marks_line(submit.slide(1).prompt) == "Notion, Obsidian", \
        "cleaned to the brand NAME — a render model given 'logo icon' draws the word"
    for banned in ("TikTok", "Jasper", "@creator", "watermark"):
        # Asserted on the TOOL MARKS line, not on the whole prompt: the scaffold's own prose
        # FORBIDS watermarks and chrome in every frame, and this line is the one place that ban
        # can be lifted. What matters is that none of these four names reaches it.
        assert banned not in marks_line(submit.slide(1).prompt), \
            f"{banned} was sanctioned as a real mark"
    assert marks_line(submit.slide(2).prompt) == "", \
        "a panel that showed no mark sanctions none — the line stays empty (ignore-if-empty)"


async def test_the_sanctioned_marks_travel_into_the_gauntlet_contract_both_ways(
    tmp_path: Path,
) -> None:
    """FR-330, both directions. Ordering a Notion logo and then failing the frame for drawing one
    spends the whole fix budget undoing FR-315, so a sanctioned mark is REQUIRED; everything the
    D-A gate refused — a competitor, the creator's own mark, platform chrome — is FORBIDDEN, and
    its presence is the leakage the `brief` critic exists to catch.
    """
    entry = make_entry(slides=2, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two"], trends=make_trends(panels=2))
    give_intel(env, panels=2, marks=[["Notion logo"], ["Figma icon", "Instagram watermark"]])
    env.llm_call = CriticStub()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    deck = env.llm_call.prompt_for("brief", 1)
    required = deck.split("REQUIRED marks", 1)[-1].split("FORBIDDEN", 1)[0]
    forbidden = deck.split("FORBIDDEN terms and marks", 1)[-1]
    assert "Notion" in required and "Figma" in required
    assert "Instagram" not in required, "platform chrome is never sanctioned"
    assert "Instagram" in forbidden, "and what the gate refused is what the critic looks for"


async def test_a_deck_without_intelligence_sanctions_no_mark(tmp_path: Path) -> None:
    """The pre-D-A rule is the DEFAULT: every company, product and app mark stays generic."""
    entry = make_entry(slides=2)
    env = make_env(tmp_path, entry, texts=["one", "two"])
    env.llm_call = CriticStub()
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert all(marks_line(call.prompt) == "" for call in submit.calls)
    # And the contract says so too: with nothing sanctioned, the REQUIRED side is `(none)`, which
    # is the strict reading — every logo a critic sees on these frames is an unsanctioned one.
    required = env.llm_call.prompt_for("brief", 0).split("REQUIRED marks", 1)[-1]
    assert required.split("FORBIDDEN", 1)[0].strip().endswith("(none)")


# ------------------------------------------ FR-315 mark patches: the mark's own pixels (D48)


async def test_fr315_a_sanctioned_mark_rides_as_a_cropped_patch_behind_the_anchor(
    tmp_path: Path, uploads: SimpleNamespace,
) -> None:
    """FR-315: a mark NAMED in a prompt comes back invented; a mark ATTACHED comes back itself.

    "Higgsfield", "Flodesk", "Murf" — the render model has no reliable picture of an obscure logo,
    so it draws a plausible one and the slide ships confidently wrong. The deck therefore crops
    each detected mark out of the source slide it was seen on, uploads it once, and attaches it per
    slide with a copy-it-exactly role line.

    ORDER is the contract asserted here. The anchor is `Image 1` and outranks everything — FR-190
    rewrites its role line from `carousel_anchor_instruction.md` over position 0 — and the patches
    come last because they are the narrowest attachments in the set: one logo each, contributing
    nothing but their own pixels, not layout, not palette, not the words around them.
    """
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two", "three"], trends=make_trends(panels=3))
    give_source_slides(tmp_path, 3)
    give_intel(env, panels=3, marks=[["Notion logo"], ["Notion logo"], ["Notion logo"]],
               boxes=[MarkBox("Notion logo", 1, (0.2, 0.2, 0.3, 0.15))])
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    anchor, second = submit.slide(1), submit.slide(2)
    assert mark_patch_urls(anchor) == ["https://kie.test/upload/notion-logo.png"]
    assert second.image_urls[0] == anchor.url, "the anchor is Image 1 and stays Image 1 (FR-95)"
    assert second.image_urls[-1] == "https://kie.test/upload/notion-logo.png", "patches last"
    # The role LINE, not the template's standing prose about mark patches: the patch is introduced
    # by position, under the cleaned brand NAME (a model told to copy "Notion logo" draws the word).
    role = next(line.strip() for line in second.prompt.splitlines() if line.startswith("  Image 2"))
    assert role.startswith("Image 2 — MARK PATCH: the exact 'Notion' mark, cropped from the source")
    assert "pixel-faithfully" in role and "no invented substitute" in role
    assert [path.name for path in uploads.paths] == ["notion-logo.png"], \
        "one crop and one upload for the whole deck, however many slides use it (FR-200/244)"
    assert env.log.fields("mark_patches_ready")["uploaded"] == 1


async def test_fr315_a_slide_never_carries_more_than_four_patches_or_breaks_the_ref_ceiling(
    tmp_path: Path, uploads: SimpleNamespace,
) -> None:
    """Two caps, and the one that gives way first.

    A slide never sanctions more than `_MAX_MARKS` marks, so it can never want more than four
    patches — a panel showing nine real logos is an icon grid, and telling a model to draw nine
    real marks faithfully is how it draws nine invented ones. The provider's 16-reference ceiling
    is applied once at the END, so a photo-heavy brief costs the deck its patches rather than its
    anchor.
    """
    entry = make_entry(slides=2, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two"], trends=make_trends(panels=2))
    give_source_slides(tmp_path, 2)
    names = ["Notion", "Figma", "Linear", "Raycast", "Obsidian", "Cursor"]
    give_intel(env, panels=2, marks=[names, names],
               boxes=[MarkBox(name, 1, (0.1 * index, 0.1, 0.15, 0.1))
                      for index, name in enumerate(names)])
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert len(uploads.paths) == 4, \
        "only the marks a slide may actually DRAW are cropped: the sanction cap is the crop " \
        "allowlist (v2.2.0), so the two marks beyond `_MAX_MARKS` never become pixels, never " \
        "reach the source store's `marks/` folder and never reach Kie"
    for call in submit.calls:
        assert len(mark_patch_urls(call)) <= carousel_module._MAX_MARK_PATCHES == 4
        assert len(call.image_urls) <= 16, "the provider's hard ceiling, applied last (FR-272)"
    assert marks_line(submit.slide(1).prompt).count(",") == 3, \
        "four sanctioned marks name four logos, and the patch cap matches the sanction cap"


async def test_fr315_a_failed_patch_upload_leaves_the_mark_rendering_from_its_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-315d: pixels are an UPGRADE, and every way of losing them costs the mark alone.

    The slide still renders, the mark is still sanctioned by name on the TOOL MARKS line, and the
    template's written description is still the fallback it always was. A patch that could not be
    uploaded may never block a job the operator has already approved paying for.
    """
    entry = make_entry(slides=2, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two"], trends=make_trends(panels=2))
    give_source_slides(tmp_path, 2)
    give_intel(env, panels=2, marks=[["Notion logo"], ["Notion logo"]],
               boxes=[MarkBox("Notion logo", 1, (0.2, 0.2, 0.3, 0.15))])

    async def _upload(path: Path) -> str:
        raise RuntimeError("kie upload timed out")

    monkeypatch.setattr(render, "upload_file", _upload)
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert all(mark_patch_urls(call) == [] for call in submit.calls)
    assert marks_line(submit.slide(1).prompt) == "Notion", "the NAME path is the documented fallback"
    assert "reference_upload_failed" in env.log.types()
    assert env.log.fields("mark_patches_ready")["uploaded"] == 0
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 2


async def test_fr315_an_unreadable_source_store_is_logged_once_and_costs_no_slide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deck-wide half of the same posture: the crop pass itself blew up.

    `logo_patch_unavailable` is one line for the whole deck rather than one per mark, because the
    failure is one fact about the store — and the deck then renders exactly as a pre-D48 deck did,
    with every sanctioned mark named and none of them attached.
    """
    entry = make_entry(slides=2, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two"], trends=make_trends(panels=2))
    give_source_slides(tmp_path, 2)
    give_intel(env, panels=2, marks=[["Notion logo"], []],
               boxes=[MarkBox("Notion logo", 1, (0.2, 0.2, 0.3, 0.15))])

    def _explode(*_args: Any, **_kwargs: Any) -> dict[str, Path]:
        raise OSError("the source folder vanished mid-run")

    monkeypatch.setattr(carousel_module, "crop_marks", _explode)
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert env.log.types().count("logo_patch_unavailable") == 1
    assert all(mark_patch_urls(call) == [] for call in submit.calls)
    assert marks_line(submit.slide(1).prompt) == "Notion"
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 2


async def test_fr315_a_croppable_mark_that_the_sanction_filter_rejected_never_reaches_a_job(
    tmp_path: Path, uploads: SimpleNamespace,
) -> None:
    """The join is on the SANCTION list, never on the patch table — and that is a safety property.

    A competitor's logo, the source creator's own mark and platform chrome are all perfectly
    croppable: a box was detected, the pixels exist, and `crop_marks` will happily cut them out.
    Attaching one would put a competitor's brand, in full colour, on a slide the operator paid for
    — so a mark whose NAME was filtered out may not reach the job through the back door of having
    been croppable.
    """
    entry = make_entry(slides=2, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two"], trends=make_trends(panels=2))
    env.branding = BrandingConfig(brand="hypelead", competitors=["Jasper"])
    give_source_slides(tmp_path, 2)
    give_intel(env, panels=2, marks=[["Notion logo", "Jasper logo", "TikTok watermark"], []],
               boxes=[MarkBox("Notion logo", 1, (0.1, 0.1, 0.2, 0.1)),
                      MarkBox("Jasper logo", 1, (0.4, 0.1, 0.2, 0.1)),
                      MarkBox("TikTok watermark", 1, (0.7, 0.1, 0.2, 0.1))])
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert mark_patch_urls(submit.slide(1)) == ["https://kie.test/upload/notion-logo.png"]
    attached = " ".join(url for call in submit.calls for url in call.image_urls)
    assert "jasper" not in attached and "tiktok" not in attached
    assert marks_line(submit.slide(1).prompt) == "Notion"


# ----------------------------- FR-317: the resubmit ledger, separate from the gauntlet fix's


async def test_fr317_a_slide_may_burn_its_gauntlet_fix_and_its_resubmit_independently(
    tmp_path: Path,
) -> None:
    """NFR-4's "one retry per class", with the classes actually separated (spec §7).

    They answer different questions. The GAUNTLET's fix is about the PICTURE — the render came back
    with broken glyphs, so a different request is made. FR-317's is about the JOB — the request
    never came back at all, so the identical request is made once more. A slide that times out, is
    resubmitted, lands, and is then failed by a critic has done nothing wrong twice: it is entitled
    to one of each, and a shared ledger would silently deny the second. A gauntlet fix is itself
    never resubmitted — it is a fresh submission with its own ledger rows.
    """
    entry = make_entry(slides=2)
    env = make_env(tmp_path, entry, texts=["one", "two"])
    # `garbled` is a craft code and craft also runs the anchor pre-gate, so entry 0 is that
    # round: the anchor is failed by the DECK round, after its FR-317 resubmit already landed.
    env.llm_call = CriticStub(rounds=[set(), {1}], code="garbled")
    submit = FakeSubmit(rule=lambda call: failed(RenderFailCause.TIMEOUT)
                        if call.index == 0 else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    kinds = [(call.slide, call.kind) for call in submit.calls]
    assert kinds == [(1, "projected"),        # the anchor, timed out
                     (1, "discretionary"),    # FR-317's resubmit — the SAME request
                     (2, "precommitted"),     # the body page, chained to the anchor that landed
                     (1, "discretionary")]    # the gauntlet's fix — a DIFFERENT request
    assert submit.calls[1].prompt == submit.calls[0].prompt, "a resubmit changes nothing"
    assert submit.calls[3].prompt != submit.calls[0].prompt, "a fix changes the request"
    assert "image_job_resubmit" in env.log.types()
    assert "gauntlet_rerender" in env.log.types()
    assert record.gauntlet["rerenders"] == 1
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED
    assert record.slide_count == 2, "the deck is whole — both retries did their job"


async def test_fr317_a_second_failure_after_the_resubmit_is_final_and_the_slide_is_lost(
    tmp_path: Path,
) -> None:
    """The ceiling. `self.resubmitted` guarantees there is never a third attempt, so the slide
    flows into the ordinary lost-slide path carrying the SECOND job's own cause.

    What that path ENDS in moved with D51 (v2.2.0): a slide that has used its resubmit and still
    has nothing is permanently lost, and our slide *i* is their panel *i* (FR-304), so the deck
    cannot be shipped around the hole. The deck is therefore a `deck_viability_loss` — every paid
    slide kept on disk (FR-74), the missing number recorded, nothing further ordered — rather than
    an incomplete ship. Slide 4 is the measurable half of that: it is never bought.
    """
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry, texts=["one", "two", "three", "four"])
    submit = FakeSubmit(rule=lambda call: failed(RenderFailCause.TIMEOUT)
                        if call.slide == 3 else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call.kind for call in submit.calls if call.slide == 3] == [
        "precommitted", "discretionary"], "two attempts on slide 3, and only two"
    assert record.missing_slide_numbers == [3, 4]
    assert record.slide_count == 2
    assert record.status is AssetStatus.FAILED, "an unsalvageable deck is not published (D51)"
    assert "deck_viability_loss" in env.log.types()
    assert "timeout" in env.log.fields("deck_viability_loss")["detail"]
    assert env.log.types().count("image_job_resubmit") == 1


async def test_fr317_a_halted_run_declines_the_resubmit_rather_than_ordering_new_work(
    tmp_path: Path,
) -> None:
    """FR-201/108/167: `env.halted` is re-read immediately BEFORE the resubmission, because the
    first attempt may have spent its whole 600 s timeout inside the window where Ctrl+C landed.

    A grace window is the run stopping. Ordering a fresh job from inside it would be the one thing
    FR-108's "never a resubmission" clause has always forbidden, arriving through a new door.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["one", "two", "three"])

    def rule(call: Call) -> RenderOutcome:
        env.halted = True  # Ctrl+C landed while this job was in flight
        return failed(RenderFailCause.TIMEOUT)

    submit = FakeSubmit(rule=rule)
    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert len(submit.calls) == 1, "nothing new was ordered after the halt"
    assert "image_job_resubmit" not in env.log.types()
    assert "image_job_resubmit_skipped" in env.log.types()
    assert record.status is AssetStatus.FAILED


async def test_fr317_a_moderation_refusal_is_never_answered_with_the_identical_request(
    tmp_path: Path,
) -> None:
    """The one failure excluded by name. FR-97 owns a content-policy refusal and its remedy is
    DROPPING references; re-asking the identical question would buy the identical no at full
    price, which is money spent to learn nothing."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["one", "two", "three"])
    give_brief(env, [entry], tmp_path)  # a body slide then HAS a reference to drop
    refused: set[int] = set()

    def rule(call: Call) -> RenderOutcome:
        if call.slide == 2 and call.slide not in refused:
            refused.add(call.slide)
            return failed(RenderFailCause.MODERATION)
        return ok(call)

    submit = FakeSubmit(rule=rule)
    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    retries = [call for call in submit.calls if call.slide == 2 and call.kind == "discretionary"]
    assert len(retries) == 1 and retries[0].image_urls == [], "FR-97's remedy, and only it"
    assert "moderation_retry" in env.log.types()
    assert "image_job_resubmit" not in env.log.types(), "FR-317 does not stack on FR-97"
    assert record.slide_count == 3


# ---------------------------------------- FR-321: partial delivery and the second vision verdict


async def test_fr321_the_meta_records_what_the_deck_was_ORDERED_to_be_beside_what_shipped(
    tmp_path: Path,
) -> None:
    """FR-321: `slide_count` alone reads as a complete deck of that length everywhere downstream.

    A 7 is a 7 whether eight were ordered or seven were, which is how a truncated deck reached the
    spend table as an unqualified `yes` and the gallery header as "delivered 6 of 6". Recording
    both makes "7 of 8" a machine-readable fact those two surfaces then state instead of derive.

    The pair is written on EVERY terminal, which is what this deck now exercises: slide 4 is
    refused by moderation, that is a permanent render defect, and the deck ends as a D51 viability
    loss — kept on disk, not published, and still stating three of four.
    """
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry, texts=["one", "two", "three", "four"])
    submit = FakeSubmit(rule=lambda call: failed(RenderFailCause.MODERATION)
                        if call.slide == 4 else ok(call))
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=submit)

    assert record.slide_count == 3 and record.slides_ordered == 4
    stored = yaml.safe_load((folder.path / packager.META_FILE).read_text(encoding="utf-8"))
    assert stored["slide_count"] == 3 and stored["slides_ordered"] == 4
    assert stored["missing_slide_numbers"] == [4]
    assert stored["status"] == "failed", "a deck missing a panel is not published (D51)"
    assert "deck_viability_loss" in stored["degradations"]


async def test_fr321_a_whole_deck_records_the_same_number_twice_rather_than_omitting_one(
    tmp_path: Path,
) -> None:
    """The pair is written on EVERY deck, complete ones included. A field present only when
    something went wrong is a field every reader has to special-case, and `budget._deck_counts`
    reads a half-present pair as "no claim was made" — which would be wrong here."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["one", "two", "three"])
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    assert record.slide_count == record.slides_ordered == 3
    stored = yaml.safe_load((folder.path / packager.META_FILE).read_text(encoding="utf-8"))
    assert stored["slides_ordered"] == 3 and stored["missing_slide_numbers"] == []


# ------------------------------------- FR-316: the visual brief, cleaned at the CHOKEPOINT


async def test_fr316_a_wordless_slide_is_sent_no_visual_brief_at_all(tmp_path: Path) -> None:
    """FR-316's sharper rule: a panel our deck maps with NO text is deliberately wordless.

    A brief describing what that panel showed is exactly the input that puts a headline, a label
    or an invented widget back onto it — and the slide's whole job is to carry nothing. The
    neighbouring slides keep their briefs, because the rule is about the slide, not the deck.
    """
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["Panel one", "", "Panel three"],
                   trends=make_trends(panels=3))
    give_intel(env, panels=3, briefs=["ZZBRIEF hero card, heading centred",
                                      "ZZBRIEF full-bleed product photograph",
                                      "ZZBRIEF line chart, three series"])
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert "ZZBRIEF hero card" in submit.slide(1).prompt
    assert "ZZBRIEF line chart" in submit.slide(3).prompt
    assert "ZZBRIEF" not in submit.slide(2).prompt, "a wordless slide gets a content-free brief"
    assert "visual_brief_dropped_wordless" in env.log.types()
    assert env.log.fields("visual_brief_dropped_wordless")["slide"] == 2


async def test_fr316_a_brief_sentence_naming_the_source_creator_is_scrubbed_whole(
    tmp_path: Path,
) -> None:
    """FR-316/FR-312: the source author's identity may not travel into a render prompt in ANY
    spelling, and the unit dropped is the SENTENCE.

    Removing only the name leaves "The logo sits top left", which directs a logo into the corner —
    the creator's signature by another route. Matching is collapsed (punctuation, spacing and case
    removed on both sides) because one vision pass transcribes one creator three ways in one deck:
    `@emirailab`, `Emir AI Lab`, `EMIR AI LAB`.
    """
    entry = make_entry(slides=2, source_post_id="post-a")
    trends = make_trends(panels=2)
    trends["t1"].posts[0].author = "@emirailab"
    env = make_env(tmp_path, entry, texts=["Panel one", "Panel two"], trends=trends)
    give_intel(env, panels=2, briefs=[
        "ZZKEEP a dark card with three rows. The EMIR AI LAB wordmark sits top left. "
        "ZZALSO a rising line chart fills the lower half.",
        "ZZPLAIN a full-bleed photograph of a desk."])
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    prompt = submit.slide(1).prompt
    assert "ZZKEEP a dark card with three rows." in prompt
    assert "ZZALSO a rising line chart" in prompt, "the other sentences survive"
    assert "EMIR AI LAB" not in prompt and "wordmark sits top left" not in prompt
    assert "visual_brief_creator_scrubbed" in env.log.types()
    assert env.log.fields("visual_brief_creator_scrubbed")["author"] == "emirailab"
    assert "ZZPLAIN" in submit.slide(2).prompt, "a brief that names nobody is untouched"


async def test_fr316_a_two_character_author_never_scrubs_a_brief(tmp_path: Path) -> None:
    """The floor, and it is the same trade FR-312's own `_CREATOR_MIN_CHARS` makes.

    A two-letter handle collapsed would match half of any English sentence, and a brief scrubbed
    to nothing is a slide that renders content-free for no reason at all. So an author identifier
    shorter than `_MIN_AUTHOR_IDENT` is not matched, and the brief ships whole.
    """
    entry = make_entry(slides=2, source_post_id="post-a")
    trends = make_trends(panels=2)
    trends["t1"].posts[0].author = "@ab"
    env = make_env(tmp_path, entry, texts=["Panel one", "Panel two"], trends=trends)
    give_intel(env, panels=2, briefs=["ZZBRIEF a table about ab testing and its abbreviations.",
                                      "ZZBRIEF a photograph."])
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert "ZZBRIEF a table about ab testing and its abbreviations." in submit.slide(1).prompt
    assert "visual_brief_creator_scrubbed" not in env.log.types()


async def test_fr316_a_competitor_named_in_a_visual_brief_never_reaches_the_render_prompt(
    tmp_path: Path,
) -> None:
    """The competitor strip is DOWNSTREAM and unchanged: `build_context` runs M6's pass over this
    value with every other context field, so `_visual_brief` deliberately does not repeat it.

    Pinned here anyway, because "the brief goes through the strip" is the property, and it is one
    refactor away from being false — the brief is the newest channel into a render prompt and the
    blocklist is the oldest rule about them.
    """
    entry = make_entry(slides=2, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["Panel one", "Panel two"], trends=make_trends(panels=2))
    env.branding = BrandingConfig(brand="hypelead", competitors=["Zzqcorp"])
    give_intel(env, panels=2, briefs=["ZZBRIEF a comparison card against Zzqcorp pricing.", ""])
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert all("Zzqcorp" not in call.prompt for call in submit.calls)
    assert "ZZBRIEF a comparison card against" in submit.slide(1).prompt


# ------------------------------- v2.1.4 hotfix wave (run 20260814_010814_glz0 audit)
#
# Four defects the paid verification run put on the record, each pinned by the shape that produced
# it rather than by the fix that answers it.


@pytest.mark.parametrize(
    ("raw", "name"),
    [
        ("Claude logo/wordmark", "Claude"),      # the glz0 miss, exactly as transcribed
        # the 59el misses, exactly as transcribed: a trailing comma-clause is a LOCATION and is
        # cut whole — the peeler can never exhaust free-form location prose word by word
        ("Claude logo/wordmark, top left", "Claude"),
        ("Claude asterisk icon, inside Decision Brief recommendation banner", "Claude"),
        ("Notion logo", "Notion"),               # the shape that always worked
        ("Figma icon/logo", "Figma"),
        ("Linear logo + wordmark", "Linear"),
        ("Perplexity logo & wordmark", "Perplexity"),
        ("Midjourney logo / mark", "Midjourney"),
        ("logo/wordmark", ""),                   # descriptors only: no brand, never sanctioned
        ("AT&T logo", "AT&T"),                   # the joiner is INSIDE the brand and stays
        ("Ben & Jerry's wordmark", "Ben & Jerry's"),
        ("H&M", "H&M"),
    ])
def test_a_mark_name_peels_joined_descriptors_without_rewriting_the_brand(
    raw: str, name: str,
) -> None:
    """FR-315's join lives or dies on this function, and in glz0 it died on one slash.

    The vision pass wrote `"Claude logo/wordmark"`; the peeler split on whitespace, saw
    `logo/wordmark` as one unknown word, stopped, and left the descriptor in the name. The patch
    table — keyed on the box's own name, `Claude` — never matched, so deck 06's uploaded
    `claude.png` was attached to nothing (`mark_patches_attached patched: []`) and the cover
    recoloured the Claude mark into the style's teal.

    The fix treats `/`, `+` and `&` as word breaks WHILE PEELING and rebuilds whatever survives
    with its original joiner, which is why the last three rows matter as much as the first: a brand
    whose name contains an ampersand is a brand, not a list, and "AT&T" may never become "AT T".
    """
    assert mark_names.mark_name(raw) == name


async def test_fr315_a_slash_joined_descriptor_still_finds_its_uploaded_patch(
    tmp_path: Path, uploads: SimpleNamespace,
) -> None:
    """The glz0 case end to end: box `Claude`, sanctioned mark `Claude logo/wordmark`, one patch.

    The two strings are written by the same vision call and are routinely written DIFFERENTLY —
    `mark_boxes[].name` is the tool, `brand_marks[]` is what the model saw. Both sides of the join
    now run `mark_name` before collapsing, so the descriptor's spelling stops deciding whether a
    logo we already cropped and paid to upload actually reaches the render.
    """
    entry = make_entry(slides=2, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two"], trends=make_trends(panels=2))
    give_source_slides(tmp_path, 2)
    give_intel(env, panels=2, marks=[["Claude logo/wordmark"], ["Claude logo/wordmark"]],
               boxes=[MarkBox("Claude", 1, (0.2, 0.2, 0.3, 0.15))])
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert mark_patch_urls(submit.slide(1)) == ["https://kie.test/upload/claude.png"]
    assert env.log.fields("mark_patches_attached")["name_only"] == [], \
        "no sanctioned mark is left rendering from its name while its patch sits uploaded"
    assert marks_line(submit.slide(1).prompt) == "Claude", "and the prompt names the brand alone"


async def test_a_deck_records_the_gpt_image_2_routes_its_slides_actually_used(
    tmp_path: Path,
) -> None:
    """FR-270/FR-241 (audit R2): `model_ids` is a record, and a record may not name a route
    nothing took.

    An anchored deck submits its cover reference-free (text-to-image) and every body slide with
    the anchor attached (image-to-image), so meta must carry BOTH configured ids. Until v2.1.4 it
    carried `models.image` alone — a text-to-image id claimed for the reference-bearing renders
    that are most of a deck, on every creative in the glz0 run.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["one", "two", "three"])
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert record.model_ids == [env.config.models.image, env.config.models.image_edit,
                                env.config.models.image_profile]
    assert submit.slide(1).image_urls == [] and submit.slide(2).image_urls, \
        "the recorded routes are the ones these submissions really took"


async def test_a_deck_records_the_pixel_size_it_really_got_and_warns_on_the_ratio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-98 (audit R4): `native_size_rendered` is "what came back", so it is now MEASURED.

    glz0 deck 01 asked for `1:1`, was delivered 1536x1024, and filed `native_size_rendered: '1:1'`
    — the meta document a Phase-2 publisher and the gallery both read as fact. The size is read
    from the delivered file's own PNG header (no Pillow outside `logo_crops`) and a deviation past
    2% is warned once per deck. Nothing re-renders: a paid picture of the wrong shape is still a
    paid picture, and spending again is the Confirm gate's decision, not the packager's.
    """
    async def _wide(url: str) -> bytes:
        return _png_bytes(1536, 1024)

    monkeypatch.setattr(packager, "_download", _wide)
    entry = make_entry(slides=2)
    env = make_env(tmp_path, entry, texts=["one", "two"])

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    assert record.native_size_rendered == "1536x1024 (3:2)"
    assert record.aspect_ratio_requested == "1:1", "what was ASKED for is untouched beside it"
    warned = env.log.fields("aspect_mismatch")
    assert warned["requested"] == "1:1" and warned["rendered"] == "1536x1024 (3:2)"
    assert warned["width"] == 1536 and warned["height"] == 1024
    assert env.log.types().count("aspect_mismatch") == 1, "one measurement per deck, not per slide"


async def test_a_deck_delivered_at_the_ratio_it_asked_for_is_recorded_without_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ordinary case: the size is still recorded honestly, and nothing is announced.

    `aspect_mismatch` has to stay rare to stay readable, so a square answer to a square request
    passes in silence — and meta still gains the real pixel dimensions, which is the number an
    operator comparing two runs actually wants.
    """
    async def _square(url: str) -> bytes:
        return _png_bytes(1024, 1024)

    monkeypatch.setattr(packager, "_download", _square)
    entry = make_entry(slides=2)
    env = make_env(tmp_path, entry, texts=["one", "two"])

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    assert record.native_size_rendered == "1024x1024 (1:1)"
    assert "aspect_mismatch" not in env.log.types()


async def test_an_unreadable_delivered_file_leaves_the_requested_ratio_standing(
    tmp_path: Path,
) -> None:
    """Unmeasurable is not an error (the default fake download writes headerless bytes).

    A container this parser does not know is a meta field that says what the job asked for, which
    is exactly the pre-v2.1.4 value — never an empty string, because the gallery prints it as the
    right-hand side of `ratio 1:1 → …`, and never a failed creative.
    """
    entry = make_entry(slides=2)
    env = make_env(tmp_path, entry, texts=["one", "two"])

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    assert record.native_size_rendered == "1:1"
    assert "aspect_mismatch" not in env.log.types()


async def test_an_unanchored_deck_records_only_the_reference_free_route(tmp_path: Path) -> None:
    """The other half of the same rule: a deck that attaches nothing claims nothing.

    `carousel_anchor: false` sends every slide out reference-free, so `models.image_edit` never
    ran and naming it would be the same lie in the opposite direction.
    """
    entry = make_entry(slides=2)
    env = make_env(tmp_path, entry, texts=["one", "two"])
    env.config.run.carousel_anchor = False

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    assert record.model_ids == [env.config.models.image, env.config.models.image_profile]


# ---- D60 ---------------------- FR-342: every slide is submitted at the tier its price approved


async def test_fr342_every_slide_of_a_deck_carries_the_platforms_configured_render_tier(
    tmp_path: Path,
) -> None:
    """The deck half of FR-342's one-key promise: what the Confirm gate quoted is what goes out.

    `budget._image_price` and `_Deck._submit` read the SAME accessor (`Config.image_resolution`),
    so a config that pins `2k` on LinkedIn is quoted at `models.price_per_unit.image.2k` and then
    submits at 2K. Before FR-342 the second half simply did not happen: `RenderParams.resolution`
    was never set on a slide, `profiles._image_resolution` filled the gap with its `1K` default,
    and every deck the three brand configs rendered was quoted for pixels it did not buy.

    Asserted on EVERY slide and not just the anchor, because the anchor and the body slides go
    through different arms of `_submit` (wave 1 vs wave 2, chained reference vs not) and a tier
    wired into one of them is a deck rendered at two sizes.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["one", "two", "three"])
    env.config.platforms["linkedin"] = PlatformConfig(carousel_slides=6, image_resolution="2k")
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert len(submit.calls) == 3
    assert [call.resolution for call in submit.calls] == ["2k", "2k", "2k"], \
        "one deck, one tier — the anchor and the body slides read the same key"


async def test_fr342_a_deck_on_an_unpinned_platform_still_renders_at_the_engine_default(
    tmp_path: Path,
) -> None:
    """The D58 shape, seen from the wire: a config that never opted in buys exactly what it always
    bought.

    `1k` is not a fallback here, it is the engine default — and the value matters beyond the price,
    because it is also what `profiles._image_resolution` sends for an unset resolution. So the
    string that now travels explicitly on every slide is the string the provider was already
    receiving implicitly, and no config that ignored FR-342 saw its renders change.
    """
    entry = make_entry(slides=2)
    env = make_env(tmp_path, entry, texts=["one", "two"])
    assert "linkedin" not in env.config.platforms, "the fixture config pins nothing per platform"
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call.resolution for call in submit.calls] == ["1k", "1k"]


# ---- D62 -------------------- FR-351: cover best-of-N — buy three covers, ship the best of them
#
# The cover is the one frame every other slide copies (FR-95), so it is the cheapest frame in the
# deck to get right and the most expensive one to get wrong. D62 buys `run.cover_candidates` of
# them concurrently, at an IDENTICAL prompt, and one metered vision call picks which anchors the
# deck. Five properties are pinned here and each is a decision rather than an implementation
# detail:
#
# * `cover_candidates: 1` is the pre-D62 path BYTE FOR BYTE — one submission, no fan-out, no pick
#   call, no receipt. A default that quietly tripled render spend would re-price every config that
#   never opted in (the D58 rule);
# * the candidates carry the SAME prompt. A perturbed prompt would make them incomparable: the
#   judge would be choosing between two briefs rather than between two readings of one;
# * the WINNER is what slides 2..N chain to. Committing one cover and referencing another would
#   drift the deck exactly as an unchained deck does, having paid three times for the privilege;
# * a candidate that never landed is a WARNING, never a missing slide and never D51 doom. D51 is
#   about a slide that can never come, and slide 1 came;
# * every failure of the JUDGE ships the deck anyway (FR-351's fail-open shape, borrowed whole
#   from the style matcher): a degraded verdict commits candidate 1 and says so on the artifact.


def cover_env(tmp_path: Path, entry: PlanEntry, candidates: int, **overrides: Any) -> Env:
    """An `Env` wired the way `runner._create` wires one for a cover-pick run (FR-351).

    The gauntlet is switched OFF and `llm_call` is still handed over, which is the exact shape D62
    added: `contracts.gate_on` ANDs `run.gauntlet.enabled` in, so the pick's seam can be present
    without the post-render gate running. It also keeps these tests about the cover pick — a live
    critic panel would put its own re-renders in `submit.calls`.
    """
    env = make_env(tmp_path, entry, **overrides)
    env.config.run.cover_candidates = candidates
    env.config.run.gauntlet.enabled = False
    env.llm_call = object()  # never called directly: `cover_pick.pick` is the seam, and it is faked
    return env


def cover_file(tmp_path: Path, entry: PlanEntry, number: int) -> Path:
    """One kept cover candidate's path on disk — `<asset>/covers/cover_candidate_<n>.jpg`."""
    return (tmp_path / entry.asset_id / carousel_module.COVERS_DIR
            / f"{carousel_module.COVER_CANDIDATE_STEM}_{number}.jpg")


def count(log: Log, event_type: str) -> int:
    """How many lines of one type this deck logged — a warning per loser has to be countable."""
    return len([name for name in log.types() if name == event_type])


async def test_fr351_one_cover_candidate_is_the_pre_d62_deck_byte_for_byte(
    tmp_path: Path, frames: SimpleNamespace,
) -> None:
    """The engine default buys ONE cover and writes NO receipt (FR-351, D58's default rule).

    `cover_candidates: 1` must not merely produce a deck that looks the same — it must take the
    same code path, submit the same single slide-1 job, and leave `meta.yaml.cover_pick` at `None`,
    because a receipt describing a choice nobody made is a receipt that misleads. The frame loader
    is asserted UNTOUCHED for the same reason: a single-cover run fetches no candidate bytes, so a
    config that never opted in pays neither the extra renders nor the extra downloads.
    """
    entry = make_entry(slides=3)
    env = cover_env(tmp_path, entry, 1, texts=["one", "two", "three"])
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call.slide for call in submit.calls] == [1, 2, 3], "one cover, then the body pages"
    assert submit.calls[0].kind == "projected", "the anchor's own reservation kind, unchanged"
    assert record.cover_pick is None
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 3
    assert frames.asked == [], "no candidate bytes are fetched when there is nothing to choose"
    assert not (tmp_path / entry.asset_id / carousel_module.COVERS_DIR).exists()
    assert "cover_candidates" not in env.log.types()


async def test_fr351_three_covers_are_submitted_identically_and_the_chosen_one_anchors_the_deck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, downloads: SimpleNamespace,
    frames: SimpleNamespace,
) -> None:
    """The whole feature in one deck: three identical orders, one verdict, one anchor.

    The prompt equality is the load-bearing half. These are not three variations on a cover — they
    are the same request three times, and the only thing allowed to differ is the provider's own
    sampling. If the prompt moved per candidate the pick would be comparing briefs, and "the model
    liked candidate 2" would say nothing at all about which cover is better.

    The other half is that the WINNER is what the deck then copies: `slide_01` carries candidate
    2's bytes AND slides 2–3 reference candidate 2's URL. A deck that committed one cover and
    chained to another would drift exactly as an unchained deck does.
    """
    entry = make_entry(slides=3)
    env = cover_env(tmp_path, entry, 3, texts=["Wired backwards", "two", "three"])
    picker = PickStub(chosen=2, reason="the cleanest type hierarchy")
    monkeypatch.setattr(cover_pick, "pick", picker)
    downloads.per_url = True
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    covers = submit.calls[:3]
    assert [call.slide for call in covers] == [1, 1, 1]
    assert len({call.prompt for call in covers}) == 1, "one request, submitted three times"
    assert {call.kind for call in covers} == {"projected"}
    assert {call.priority for call in covers} == {RenderPriority.WAVE1}
    # The candidate ids ARE submission order, which is what lets a log line, a file name and
    # `chosen` all name the same render. Pinned rather than assumed.
    assert frames.asked == [[call.url for call in covers]]

    chosen_url = covers[1].url
    assert (tmp_path / entry.asset_id / "slide_01.jpg").read_bytes() == blob_for(chosen_url)
    assert [call.image_urls for call in submit.calls[3:]] == [[chosen_url]] * 2, \
        "slides 2-3 chain to the cover that WON, not to the one that happened to be first"
    for number in (1, 2, 3):
        assert cover_file(tmp_path, entry, number).read_bytes() == blob_for(covers[number - 1].url)

    assert record.cover_pick == {
        "candidates": ["covers/cover_candidate_1.jpg", "covers/cover_candidate_2.jpg",
                       "covers/cover_candidate_3.jpg"],
        "chosen": 2, "reason": "the cleanest type hierarchy", "degraded": False}
    stored = yaml.safe_load(
        (tmp_path / entry.asset_id / packager.META_FILE).read_text(encoding="utf-8"))
    assert stored["cover_pick"] == record.cover_pick, "the receipt reaches meta.yaml intact"
    assert DegradationTag.COVER_PICK_DEGRADED not in record.degradations
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 3
    assert env.log.fields("cover_candidates") == {
        "asset_id": entry.asset_id, "submitted": 3, "landed": 3, "candidates": [1, 2, 3]}
    assert env.log.fields("cover_pick")["chosen"] == 2
    assert "cover_candidate_lost" not in env.log.types(), \
        "a cover that lost a comparison did not FAIL — it is simply not the one that anchors"


async def test_fr351_the_judge_is_handed_native_bytes_and_the_contract_the_cover_was_ordered_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, frames: SimpleNamespace,
) -> None:
    """What the pick call actually sees (FR-351/FR-352) — ids, bytes, DNA and the legible strings.

    Every piece of this is a contract another module depends on. The ids are 1-based submission
    order, so `chosen` can be matched back to a file. The bytes are NATIVE (`load_images`, the same
    loader the gauntlet's critics use) — a downscaled cover is a cover whose type cannot be judged.
    The DNA is the exact `{{style_dna}}` bytes every slide of this deck was rendered under
    (FR-189), because a judge holding candidates against a paraphrase of the contract is grading a
    prompt nobody sent. And `expected_text` is what has to be LEGIBLE on the frame: slide 1's own
    line and the wordmark when the deck is signed, with empty strings dropped — "is '' legible" is
    not a question.
    """
    entry = make_entry(slides=3, branded=True)
    style = make_style(tmp_path)
    env = cover_env(tmp_path, entry, 2, texts=["Wired backwards", "two", "three"], style=style)
    env.branding = BrandingConfig(brand="hypelead")
    picker = PickStub(chosen=1)
    monkeypatch.setattr(cover_pick, "pick", picker)
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert len(picker.candidates) == 1, "ONE call per deck, whatever the candidate count"
    candidates = picker.candidates[0]
    assert [candidate.index for candidate in candidates] == [1, 2]
    assert [candidate.image for candidate in candidates] == [
        blob_for(call.url) for call in submit.calls[:2]], "native bytes, in candidate order"

    brief = picker.briefs[0]
    assert brief.asset_id == entry.asset_id and brief.style_key == STYLE_KEY
    assert brief.style_dna == style_dna(style), "the exact bytes the render prompts carried"
    assert brief.style_dna and brief.style_dna in submit.calls[0].prompt
    assert "Wired backwards" in brief.expected_text
    assert "HypeLead" in brief.expected_text, \
        "a signed deck must be judged on whether its signature is legible (B1/FR-292)"
    assert all(text.strip() for text in brief.expected_text), "empty strings are not questions"
    assert brief.counter == "", "no source counter was detected, so this deck carries no badge"


async def test_fr351_a_degraded_pick_commits_candidate_one_tags_the_deck_and_ships_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, downloads: SimpleNamespace,
    frames: SimpleNamespace,
) -> None:
    """§0.14c's fail-open shape, applied to the cover: a judge we could not run never costs a deck.

    The pick is a judgement about renders that ALREADY EXIST and are already paid for. So every
    way it can fail — no metered answer, a raised call, an unparseable verdict — commits candidate
    1, which is precisely the deck a `cover_candidates: 1` run would have made, and the artifact
    says so: `cover_pick_degraded` on `degradations`, `degraded: true` on the receipt, and the
    model's own account of what went wrong kept in `reason` for the operator to read.
    """
    entry = make_entry(slides=2)
    env = cover_env(tmp_path, entry, 3, texts=["one", "two"])
    monkeypatch.setattr(cover_pick, "pick", PickStub(
        chosen=1, reason=f"{cover_pick.DEGRADED_MARKER}: the pick call raised TimeoutError",
        degraded=True))
    downloads.per_url = True
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert (tmp_path / entry.asset_id / "slide_01.jpg").read_bytes() == \
        blob_for(submit.calls[0].url), "candidate 1 anchors by default"
    assert record.cover_pick is not None and record.cover_pick["degraded"] is True
    assert record.cover_pick["chosen"] == 1
    assert cover_pick.DEGRADED_MARKER in record.cover_pick["reason"]
    assert DegradationTag.COVER_PICK_DEGRADED in record.degradations
    assert "cover_pick_degraded" in env.log.types() and "cover_pick" not in env.log.types()
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 2, \
        "a broken judge never blocks delivery (D3)"
    assert len(record.cover_pick["candidates"]) == 3, "all three are still kept for the operator"


async def test_fr351_a_candidate_that_never_landed_is_a_warning_and_never_a_missing_slide(
    tmp_path: Path, frames: SimpleNamespace,
) -> None:
    """Two of three covers die; the deck is whole, unmarked and NOT unsalvageable (FR-351 vs D51).

    D51 stops a deck when a slide is permanently lost to a render defect, because our slide *i* IS
    their panel *i* and a hole in the middle is a broken deck rather than a shorter one. A cover
    candidate is not that: it was competing for a slot the deck filled anyway. Filing it as a loss
    would put "slide 1: provider_fail" in `missing_slide_numbers`' explanation for a slide that is
    on disk, and — far worse — would latch `doomed` and stop the deck buying its remaining pages.

    The REAL `cover_pick.pick` runs here rather than a stub, on purpose: one landed candidate is a
    question with no content, and the module answers it without a model call at all.

    A SECOND failure is final, per candidate: candidates 1 and 2 each burn their own FR-317
    resubmit here and neither is attempted a third time (the ledger is `(1, candidate_id)`, so a
    used one-shot stops that candidate and only that candidate).
    """
    entry = make_entry(slides=3)
    env = cover_env(tmp_path, entry, 3, texts=["one", "two", "three"])
    submit = FakeSubmit(rule=lambda call: failed() if call.index in (0, 1, 2, 3) else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call.slide for call in submit.calls[:5]] == [1, 1, 1, 1, 1]
    assert [call.kind for call in submit.calls[:5]] == [
        "projected", "discretionary", "projected", "discretionary", "projected"], \
        "candidates 1 and 2 each spend their OWN resubmit; candidate 3 lands first time (FR-351)"
    assert len(submit.calls) == 7, "five cover attempts, then slides 2 and 3 — never a third try"
    survivor = submit.calls[4]
    assert [call.image_urls for call in submit.calls[5:]] == [[survivor.url]] * 2

    assert record.status is AssetStatus.SUCCESS and record.slide_count == 3
    assert record.missing_slide_numbers == [] and not record.skip_reason
    assert DegradationTag.INCOMPLETE not in record.degradations
    assert "carousel_slide_lost" not in env.log.types(), "nothing was lost — slide 1 arrived"
    assert "carousel_anchor_retry" not in env.log.types(), "a landed cover needs no replacement"
    assert count(env.log, "cover_candidate_lost") == 2
    assert record.cover_pick == {"candidates": ["covers/cover_candidate_3.jpg"], "chosen": 3,
                                 "reason": "only one candidate landed — nothing to choose",
                                 "degraded": False}
    assert cover_file(tmp_path, entry, 3).is_file()
    assert not cover_file(tmp_path, entry, 1).exists(), "a cover that never came has no bytes"


async def test_fr351_when_no_candidate_lands_the_deck_takes_the_old_single_anchor_failure_path(
    tmp_path: Path, frames: SimpleNamespace,
) -> None:
    """Zero landed is one dead anchor, not three — FR-95's ladder is unchanged underneath D62.

    A fan-out that comes back empty is the same situation a lone failed cover always was, so it
    gets the same treatment: ONE loss line, ONE replacement anchor (`_reanchor`, pre-committed
    because the cap may not decide whether a deck chains), and the unchained burst only if that
    replacement dies too. Three candidates dying of one provider fault is one setback with three
    receipts; three lines in `missing_slide_numbers`' explanation would read as three lost slides.

    No receipt is written either: nothing landed, so there was never a choice to report.
    """
    entry = make_entry(slides=4)
    env = cover_env(tmp_path, entry, 3)
    submit = FakeSubmit(rule=lambda call: failed() if call.index <= 7 else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call.kind for call in submit.calls[:8]] == [
        "projected", "discretionary", "projected", "discretionary", "projected", "discretionary",
        "precommitted", "discretionary"], \
        "each candidate spends its own FR-317 resubmit, then FR-95's replacement anchor spends its"
    assert [call.slide for call in submit.calls[:8]] == [1] * 8
    assert len(submit.calls) == 12, "... and then the unchained burst of all four slides"
    assert {call.priority for call in submit.calls[8:]} == {RenderPriority.WAVE2}
    assert all(call.image_urls == [] for call in submit.calls[8:]), "nothing to chain to"

    assert env.log.fields("cover_candidates") == {
        "asset_id": entry.asset_id, "submitted": 3, "landed": 0, "candidates": []}
    assert count(env.log, "carousel_slide_lost") == 2, \
        "one line for the dead fan-out and one for the dead replacement — never one per candidate"
    assert "carousel_anchor_retry" in env.log.types()
    assert "carousel_anchor_fallback_unchained" in env.log.types()
    assert "cover_candidate_lost" not in env.log.types(), \
        "nothing landed, so nothing 'lost a comparison' — this is the ordinary dead-anchor path"
    assert record.cover_pick is None
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 4, \
        "a dead fan-out is not a dead deck: the unchained burst is slide 1's last path (FR-95)"


async def test_fr351_extra_covers_are_not_ordered_when_nothing_can_judge_them(
    tmp_path: Path, frames: SimpleNamespace,
) -> None:
    """No metered call means no fan-out — buying renders nobody can rank is waste, not a hedge.

    Without `Env.llm_call` the pick can never run, so three covers would be bought, candidate 1
    committed, and the operator handed exactly the deck a `cover_candidates: 1` run makes, for
    three times the render spend. The extras are therefore never ordered at all, and the reason is
    stated ONCE on the deck rather than left to be found in the ledger afterwards.
    """
    entry = make_entry(slides=2)
    env = cover_env(tmp_path, entry, 3, texts=["one", "two"])
    env.llm_call = None
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call.slide for call in submit.calls] == [1, 2], "one cover, exactly as at 1"
    assert record.cover_pick is None
    assert count(env.log, "cover_candidates_unjudged") == 1
    assert env.log.fields("cover_candidates_unjudged")["cover_candidates"] == 3
    assert frames.asked == []
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 2


async def test_fr351_a_candidate_whose_bytes_will_not_download_is_dropped_never_shifted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, frames: SimpleNamespace,
) -> None:
    """`load_images` drops an unreadable source, and the candidate ids must survive the hole.

    This is the bug the loader's `positions` return exists to prevent, seen from the cover pick: if
    candidate 2's bytes fail and the remaining blobs are read positionally, candidate 3 is handed
    to the judge AS candidate 2 — and `chosen: 2` then anchors the deck to a render nobody looked
    at. So the ids the judge sees are asserted to be the SUBMISSION ids, gap included, and the
    candidate with no bytes is simply absent from the strip rather than shifting the rest along.
    """
    entry = make_entry(slides=2)
    env = cover_env(tmp_path, entry, 3, texts=["one", "two"])
    picker = PickStub(chosen=3, reason="the widest margins")
    monkeypatch.setattr(cover_pick, "pick", picker)
    submit = FakeSubmit()
    frames.drop.add("https://kie.test/slide-1-1.jpg")  # candidate 2 lands, then will not download

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert len(submit.calls) == 4, "three candidates landed; only their BYTES went missing"
    assert [candidate.index for candidate in picker.candidates[0]] == [1, 3], \
        "candidate 3 is offered as 3 — never renumbered into the hole candidate 2 left"
    assert record.cover_pick is not None
    assert record.cover_pick["chosen"] == 3
    assert record.cover_pick["candidates"] == ["covers/cover_candidate_1.jpg",
                                               "covers/cover_candidate_3.jpg"]
    assert not cover_file(tmp_path, entry, 2).exists()
    assert [call.image_urls for call in submit.calls[3:]] == [[submit.calls[2].url]], \
        "the body page chains to candidate 3 — the render the pick actually named"
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 2


async def test_fr351_each_cover_candidate_carries_its_own_fr317_resubmit_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, frames: SimpleNamespace,
) -> None:
    """FR-351 x FR-317: three concurrent covers are three JOBS, and each gets its own one retry.

    The ledger used to be keyed by slide number, and every candidate IS slide 1 — so under
    `asyncio.gather` the first candidate to time out took the only retry and the other two silently
    lost theirs. Which one won was a scheduling accident: re-order the tasks and a different deck
    comes out. `run.cover_candidates: 3` with a flaky provider would then buy three covers and
    salvage one, having been entitled to salvage all three.

    So the key is `(1, candidate_id)`. Every candidate that times out is resubmitted once, exactly
    once, and the operator-facing lines still say `slide 1` — the candidate id rides the structured
    fields, because slide 1 is the slide being bought and the fan-out is ours, not theirs.
    """
    entry = make_entry(slides=2)
    env = cover_env(tmp_path, entry, 3, texts=["one", "two"])
    monkeypatch.setattr(cover_pick, "pick", PickStub(chosen=3, reason="the widest margins"))
    # Every candidate times out on its FIRST attempt and lands on its own resubmit.
    submit = FakeSubmit(rule=lambda call: failed(RenderFailCause.TIMEOUT)
                        if call.index in (0, 2, 4) else ok(call))

    deck = carousel_module._Deck(entry, env, make_folder(tmp_path, entry), submit)
    await deck.build()
    record = deck.package()

    assert deck.resubmitted == {(1, 1), (1, 2), (1, 3)}, \
        "one ledger PER CANDIDATE — not one shared bucket the fastest timeout empties"
    assert [call.kind for call in submit.calls[:6]] == [
        "projected", "discretionary"] * 3, "attempt, retry, attempt, retry, attempt, retry"
    assert [call.slide for call in submit.calls[:6]] == [1] * 6
    for first, retry in ((0, 1), (2, 3), (4, 5)):
        assert submit.calls[retry].prompt == submit.calls[first].prompt, \
            "the SAME job again, not a different request (FR-317)"

    resubmits = [data for name, data in env.log.data if name == "image_job_resubmit"]
    assert [data["candidate"] for data in resubmits] == [1, 2, 3]
    assert all(data["slide"] == 1 and data["attempt"] == 2 for data in resubmits)
    assert all("slide 1" in message for name, message in env.log.records
               if name == "image_job_resubmit"), "the SENTENCE names the slide, never a candidate"

    assert record.cover_pick is not None and record.cover_pick["chosen"] == 3
    assert len(record.cover_pick["candidates"]) == 3, "all three were salvaged and all three kept"
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 2


async def test_fr317_a_single_cover_deck_keeps_the_one_shot_it_always_shared_with_its_reanchor(
    tmp_path: Path, frames: SimpleNamespace,
) -> None:
    """The other half of the ledger change: at `cover_candidates: 1` NOTHING moved (D58's rule).

    `_render`'s `ledger` defaults to the slide number, so a single-cover deck and FR-95's
    replacement anchor share bucket `1` exactly as they did before D62 — the anchor's resubmit is
    the deck's only one, and the replacement gets none. Pinned as its own test because the default
    is what keeps every pre-D62 config byte-identical, and a default is the easiest thing in a
    signature to change by accident.
    """
    entry = make_entry(slides=3)
    env = cover_env(tmp_path, entry, 1, texts=["one", "two", "three"])
    submit = FakeSubmit(rule=lambda call: failed(RenderFailCause.TIMEOUT)
                        if call.index in (0, 1, 2) else ok(call))

    deck = carousel_module._Deck(entry, env, make_folder(tmp_path, entry), submit)
    await deck.build()

    assert deck.resubmitted == {1}, "the slide number, plain — no candidate tuple anywhere"
    assert [call.kind for call in submit.calls[:3]] == [
        "projected", "discretionary", "precommitted"], \
        "anchor, its one resubmit, then the replacement — which gets no resubmit of its own"
    assert not [data for name, data in env.log.data
                if name == "image_job_resubmit" and "candidate" in data]
