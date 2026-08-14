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

from hypesocials import render, styles
from hypesocials.config import BrandingConfig, Config
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
                    image_urls=list(refs.image_urls))
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


class VisionStub:
    """A `models.StructuredCall` that answers the vision check from a per-call flag table.

    `defect` names WHICH of FR-105's three questions comes back true for a flagged image. It
    defaults to `text_broken` so every pre-v2.1.1 test reads unchanged, and `text_mismatch` — the
    defect the 2026-08-13 audit shipped unseen — is selected by name where it is the subject.
    `carriers` keeps each call's user turn, which is where the expected text rides.
    """

    def __init__(self, flags: list[set[int]] | None = None,
                 events: list[str] | None = None, defect: str = "text_broken",
                 detail: str = "garbled") -> None:
        self.flags = flags or []
        self.defect = defect
        #: What the model says it SAW. D-F quotes it into the re-render's instruction, so a test
        #: about the defect-aware retry needs to be able to plant a sentinel here.
        self.detail = detail
        self.calls: list[int] = []
        self.carriers: list[str] = []
        self.events = events if events is not None else []

    async def __call__(self, role, messages, json_schema, images=None) -> ParsedResult:
        count = len(images or [])
        self.calls.append(count)
        self.carriers.append(next(m["content"] for m in reversed(messages) if m["role"] == "user"))
        self.events.append(f"check:{count}")
        flagged = self.flags[len(self.calls) - 1] if len(self.calls) <= len(self.flags) else set()
        return ParsedResult(parsed={"verdicts": [
            {"image": i, "text_broken": False, "fake_ui": False, "text_mismatch": False,
             self.defect: i in flagged, "detail": self.detail}
            for i in range(1, count + 1)]}, raw_text="{}")


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


@pytest.fixture(autouse=True)
def downloads(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Every `store_render` writes real bytes to a real folder; nothing touches the network."""
    control = SimpleNamespace(fetched=[], fail_contains="", fail_reason="download_failed")

    async def _download(url: str) -> bytes:
        control.fetched.append(url)
        if control.fail_contains and control.fail_contains in url:
            raise PackagingError(f"download failed: {control.fail_reason}",
                                 reason=control.fail_reason)
        return b"\xff\xd8fake-jpeg-bytes"

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
        Image.new("RGB", (400, 600), color=(30, 30, 60)).save(folder / f"slide_{position:02d}.jpg")
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


# --------------------------------------------------------------- FR-105 ordering (barrier item)


async def test_fr105_anchor_checked_before_slides_submitted(tmp_path: Path) -> None:
    """The anchor is a chained artifact: checking it after the deck is checking it N renders too
    late (FR-95/105). Slide 1 renders alone, is checked, and only then do slides 2–N go out."""
    entry, events = make_entry(slides=4), []
    env = make_env(tmp_path, entry)
    env.config.run.vision_check = True
    env.llm_call = VisionStub(events=events)
    submit = FakeSubmit(events=events)

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    anchor_check = events.index("check:1")
    assert events[0] == "submit:1:projected", "slide 1 renders first and alone (FR-95)"
    assert events[1] == "check:1", "nothing else is ordered before the anchor verdict"
    later = [index for index, name in enumerate(events) if name.startswith("submit:")
             and not name.startswith("submit:1:")]
    assert later and min(later) > anchor_check, "no slide 2–N is submitted before the check"
    assert env.llm_call.calls == [1, 4], "one anchor call, then ONE call for the whole deck"
    assert record.status is AssetStatus.SUCCESS
    assert record.vision_check_result is VisionCheckResult.PASSED


async def test_deck_check_is_one_call_carrying_every_delivered_slide(tmp_path: Path) -> None:
    """N slides never cost N calls, and the estimate prices it the same way (FR-105/107)."""
    entry = make_entry(slides=5)
    env = make_env(tmp_path, entry, texts=["a", "b", "c", "d", "e"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    assert env.llm_call.calls == [1, 5]


async def test_vision_check_off_never_calls_the_model(tmp_path: Path) -> None:
    """`run.vision_check` is the switch, and OFF still means off — even now that it ships ON.

    The default flipped to `true` (v2.1.1): run `20260813_143420_oyo4` shipped every creative with
    `vision_check_result: not_checked` purely because the flag was down, which is the check being
    priced in the estimate and never taken. So this test now turns it off EXPLICITLY — an operator
    who says no must still get no LLM call, whatever the default is.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.config.run.vision_check = False
    env.llm_call = VisionStub()  # a call is available; the flag is what declines it

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    assert env.llm_call.calls == []
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
    """Slide 1 failing degrades the deck to independent generation — and that fallback is
    PRE-COMMITTED work, never discretionary: the cap may not split a deck (FR-95/FR-106b).

    The anchor has to fail TWICE to reach this path since v2.1.3/D48: FR-317 grants a
    non-moderation failure exactly one automatic resubmit, and a deck that anchors on the second
    attempt is strictly better than one that falls back (the sibling test below pins that half).
    So the rule fails both attempts by INDEX rather than by slide number — the fallback's own
    slide 1 is still slide 1, and it must land.
    """
    entry = make_entry(slides=4)
    style = make_style(tmp_path)
    env = make_env(tmp_path, entry, style=style)
    submit = FakeSubmit(rule=lambda call: failed() if call.index in (0, 1) else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert len(submit.calls) == 6, "the anchor, its FR-317 resubmit, then N independent slides"
    assert [call.kind for call in submit.calls[:2]] == ["projected", "discretionary"]
    fallback = submit.calls[2:]
    assert [call.slide for call in fallback] == [1, 2, 3, 4]
    assert {call.kind for call in fallback} == {"precommitted"}, "never discretionary"
    assert {call.priority for call in fallback} == {RenderPriority.WAVE2}
    assert all(call.image_urls == [] for call in fallback), \
        "no anchor to chain to, and a style ships no pictures of its own (F3)"
    assert "carousel_anchor_fallback" in env.log.types()
    assert record.status is AssetStatus.SUCCESS and record.slide_count == 4


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


async def test_a_failed_slide_download_ships_an_incomplete_deck(
    tmp_path: Path, downloads: SimpleNamespace
) -> None:
    """10 §10: completed slides ship, metadata records `incomplete` with the missing numbers.
    Explicitly NOT all-or-nothing (D3)."""
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry)
    downloads.fail_contains = "slide-3-"
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    assert record.status is AssetStatus.SUCCESS, "a labelled incomplete deck beats nothing"
    assert record.missing_slide_numbers == [3]
    assert record.slide_count == 3
    assert "incomplete" in [tag.value for tag in record.degradations]
    on_disk = sorted(path.name for path in folder.path.glob("slide_*.jpg"))
    assert on_disk == ["slide_01.jpg", "slide_02.jpg", "slide_04.jpg"]
    assert packager.read_meta(folder.path)["missing_slide_numbers"] == [3]


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

    assert record.status is AssetStatus.SUCCESS and record.slide_count == 4
    assert record.missing_slide_numbers == [2]
    assert entry.status is PlanEntryStatus.SUCCESS and entry.skip_reason is None
    degradations = {record.asset_id: record.degradations}  # the map `runner._package` builds
    assert decide_exit_code([entry]) == EXIT_OK, "the pre-fix answer, blind to the tags"
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
    """
    entry = make_entry(slides=6)
    env = make_env(tmp_path, entry, texts=[f"line {n}" for n in range(1, 7)])
    submit = FakeSubmit(rule=lambda call: ok(call) if call.slide == 1 else failed())

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert record.missing_slide_numbers == [2, 3, 4, 5, 6] and record.slide_count == 1
    detail = env.log.fields("carousel_incomplete")["detail"]
    assert sorted(int(number) for number in _SLIDE_NO.findall(detail)) == [2, 3, 4, 5, 6], \
        "every missing number in the same line has its own explanation"
    assert detail.count("provider_fail") == 5


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
    moderation refusal on it must fail straight through to the independent-slide fallback rather
    than buy a byte-identical resubmission at full price. Every fallback slide is likewise
    reference-free, so not one of them retries either.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    submit = FakeSubmit(rule=lambda call: failed(RenderFailCause.MODERATION)
                        if call.slide == 1 else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call.kind for call in submit.calls] == ["projected", *["precommitted"] * 3], \
        "one refused anchor, then the fallback deck — no discretionary retry anywhere"
    assert "moderation_retry" not in env.log.types()
    assert "refs_dropped_moderation" not in [tag.value for tag in record.degradations]
    assert "carousel_anchor_fallback" in env.log.types()


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
    assert record.status is AssetStatus.SUCCESS


# --------------------------------------------------------------------- FR-105 retries & verdicts


async def test_flagged_anchor_with_a_declined_retry_ships_and_records_retried_failed(
    tmp_path: Path,
) -> None:
    """A flagged anchor whose discretionary re-render the cap declines still anchors the deck —
    one retry is the cap everywhere — but the verdict stays honest (FR-95/FR-106c/FR-27)."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub(flags=[{1}])  # anchor flagged; the deck call comes back clean
    submit = FakeSubmit(rule=lambda call: None if call.kind == "discretionary" else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    declined = [call for call in submit.calls if call.kind == "discretionary"]
    assert len(declined) == 1 and declined[0].slide == 1, "exactly one re-render was attempted"
    assert record.slide_count == 3, "the flagged anchor ships and the deck is built on it"
    assert record.vision_check_result is VisionCheckResult.RETRIED_FAILED


async def test_a_flagged_anchor_re_render_replaces_slide_one_with_shorter_text(
    tmp_path: Path,
) -> None:
    """FR-105's retry changes the INPUT: less text, a tighter stated budget, larger type.

    This deck binds NO source post, so its lines are text the copy stage composed and the −40% cut
    still applies to them — measured against `slide` (300), the budget that governs a deck slide,
    never against `image_headline` (v2.1.1). The mapped-panel case is the sibling test below.
    """
    long_line = " ".join(["overlong"] * 25)  # 224 characters: over slide(300) × 0.6 = 180
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=[long_line, "b", "c"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub(flags=[{1}])
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    first, retry = submit.calls[0], submit.calls[1]
    assert retry.slide == 1 and retry.kind == "discretionary"
    assert retry.priority is RenderPriority.WAVE1, "the deck is still waiting on this anchor"
    assert "re-render of an image whose text came back broken" in retry.prompt
    assert long_line in first.prompt and long_line not in retry.prompt, "the INPUT changed"
    kept = quoted_text(retry.prompt)
    assert 0 < len(kept) <= 180 and long_line.startswith(kept), "−40% of slide(300), word boundary"
    assert submit.calls[2].image_urls[0] == retry.url, "the deck anchors to the FINAL slide 1"
    assert env.llm_call.calls == [1, 1, 3], "check, re-render, RE-CHECK, then the deck call"
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED
    assert dna_block(first.prompt) == dna_block(retry.prompt), \
        "a retry changes the TEXT, never the deck's style DNA"


async def test_a_mapped_panels_re_render_keeps_its_text_byte_for_byte(tmp_path: Path) -> None:
    """FR-304 > FR-105 (v2.1.1): a verbatim quote is never trimmed, on retry included.

    The audited run cut a 131-character source panel to a 53-character mid-sentence stub — this
    module committing, deliberately, the exact defect the check exists to catch. On a panel-mapped
    deck the retry's "materially different input" is layout-side only.
    """
    panel = ("Claude reads your whole vault every single time and Obsidian's index does not — "
             "that one swap is where the 71.5x saving comes from.")
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=[panel, "two", "three"], trends=make_trends(panels=3))
    env.config.run.vision_check = True
    env.llm_call = VisionStub(flags=[{1}])
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    retry = submit.calls[1]
    assert len(panel) == 131, "the audited panel's real length — the fixture, not an assumption"
    assert quoted_text(retry.prompt) == panel and len(quoted_text(retry.prompt)) == 131
    assert "LOCKED" in retry.prompt, "the re-render is told the words may not be shortened"
    assert "Set the remaining text" not in retry.prompt, "that is the free-text retry's line"
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED


async def test_the_deck_check_carries_each_slides_locked_text_as_its_referent(
    tmp_path: Path,
) -> None:
    """FR-105 v2.1.1: the check cannot see a MISMATCH without knowing what was ordered.

    The 2026-08-13 audit shipped a slide whose source panel said one thing and whose render said
    another — legible, chrome-free, and therefore clean under the two older questions. A wordless
    mapped panel sends the empty expectation, which is the stronger claim: nothing may appear.
    """
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["Panel one verbatim", "", "Panel three verbatim"],
                   trends=make_trends(panels=3))
    env.config.run.vision_check = True
    env.llm_call = VisionStub()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    anchor_call, deck_call = env.llm_call.carriers
    assert 'image 1: "Panel one verbatim"' in anchor_call
    assert 'image 1: "Panel one verbatim"' in deck_call
    assert "image 2: (none)" in deck_call, "a wordless panel must carry no invented words"
    assert 'image 3: "Panel three verbatim"' in deck_call


async def test_a_text_mismatch_verdict_flags_the_slide_and_earns_the_one_retry(
    tmp_path: Path,
) -> None:
    """The third defect is a flag on its own: clean, legible, and not what we ordered (FR-105)."""
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two", "three"], trends=make_trends(panels=3))
    env.config.run.vision_check = True
    # anchor clean; the deck call says slide 3 renders words nobody asked for
    env.llm_call = VisionStub(flags=[set(), {3}], defect="text_mismatch")
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    retries = [call for call in submit.calls if call.kind == "discretionary"]
    assert [call.slide for call in retries] == [3], "a mismatch alone earns the one re-render"
    assert env.llm_call.calls == [1, 3, 1], "anchor call, deck call, one re-check of the re-render"
    assert env.log.fields("vision_check_flagged").get("text_mismatch") is True
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED


async def test_a_failed_vision_re_render_is_not_reported_as_a_lost_slide(tmp_path: Path) -> None:
    """A re-render that never happens loses NOTHING — the slide it was improving already shipped.

    `missing_slide_numbers` and `carousel_incomplete.detail` are read as one sentence, so a
    "slide 2: declined by the spend cap" line beside `missing: [3]` told the operator slide 2 was
    lost when slide 2 is on disk. The two uses are separated: a declined retry is
    `vision_retry_unavailable` in the log and nothing at all in the loss ledger.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub(flags=[set(), {2}])  # slide 2 of the DELIVERED pair [1, 2]
    # slide 3 genuinely fails; every discretionary job (the vision retry) is declined by the cap.
    submit = FakeSubmit(rule=lambda call: None if call.kind == "discretionary"
                        else failed() if call.slide == 3 else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert record.missing_slide_numbers == [3], "only the slide that never rendered is missing"
    detail = env.log.fields("carousel_incomplete")["detail"]
    assert "slide 3" in detail and "slide 2" not in detail, "a delivered slide is not a loss"
    assert "vision_retry_unavailable" in env.log.types(), "the declined retry is still visible"
    assert record.vision_check_result is VisionCheckResult.RETRIED_FAILED, "and still honest"


async def test_a_successful_re_render_is_re_checked_before_it_earns_retried_passed(
    tmp_path: Path,
) -> None:
    """FR-27's `retried_passed` is only honest when a real second verdict says so, and the
    estimator already prices the vision-retry allowance as render PLUS re-check."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub(flags=[{1}])  # anchor flagged once; later calls come back clean
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert env.llm_call.calls == [1, 1, 3], "the re-rendered anchor is re-checked, once"
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED
    assert len([call for call in submit.calls if call.kind == "discretionary"]) == 1


async def test_re_renders_are_re_checked_in_one_batched_call(tmp_path: Path) -> None:
    """FR-105 call economics hold for the re-check too: two re-rendered slides, ONE further call.
    The slide whose re-render still comes back flagged stays `retried_failed` (FR-27 honesty)."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.config.run.vision_check = True
    # anchor clean · deck flags slides 2 and 3 · the re-check flags the FIRST re-rendered slide
    env.llm_call = VisionStub(flags=[set(), {2, 3}, {1}])
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert env.llm_call.calls == [1, 3, 2], "one re-check carrying both re-rendered slides"
    assert [call.slide for call in submit.calls if call.kind == "discretionary"] == [2, 3]
    assert record.vision_check_result is VisionCheckResult.RETRIED_FAILED, "slide 2 still broken"
    assert record.slide_count == 3, "a flagged slide still ships — one retry, then it goes (D3)"


async def test_a_flagged_slide_in_the_deck_check_gets_one_discretionary_re_render(
    tmp_path: Path,
) -> None:
    """Each flagged slide earns at most one re-render, and it is discretionary spend (FR-106c)."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub(flags=[set(), {3}])  # anchor clean, slide 3 flagged post-deck
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    retries = [call for call in submit.calls if call.kind == "discretionary"]
    assert [call.slide for call in retries] == [3]
    assert retries[0].image_urls[0] == submit.calls[0].url, "still template-locked to the anchor"
    assert env.llm_call.calls == [1, 3, 1], "anchor call, deck call, one re-check of the re-render"
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED


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
        assert "spelled out: 0" in text_block(call.prompt), \
            "it is a locked string like any other — spelling aid included"


async def test_an_uncounted_source_deck_orders_no_badge_at_all(tmp_path: Path) -> None:
    """The absence is the common case and it is STATED, not left to the model.

    A style whose layout describes a position chip, with no string to put in it, is the single
    biggest hallucination site the render models have: they fill it with an invented "01", a "3/7"
    that matches no deck, or a page number. So an uncounted deck quotes no counter and its
    template says the frame carries none.
    """
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two", "three"], trends=make_trends(panels=3))
    give_intel(env, panels=3, chrome=["@knox | skool.com/knox", "swipe on", ""])
    env.config.run.vision_check = True
    env.llm_call = VisionStub()
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    for call in submit.calls:
        assert "counter (render verbatim)" not in call.prompt
        assert "this deck carries no slide counter" in call.prompt.lower()
    assert all("/ 03" not in carrier for carrier in env.llm_call.carriers), \
        "and the check is told to expect no badge either"


async def test_the_counter_travels_into_the_checks_expected_text(tmp_path: Path) -> None:
    """A badge we ORDERED is ordered words: unlisted, it is a text mismatch on every slide.

    The third vision question compares the rendered words against the expected ones, so a deck
    that renders "2/3" exactly as instructed would be flagged for three invented characters — and
    each flagged slide would buy a discretionary re-render against a defect nobody has.
    """
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["Panel one", "", "Panel three"],
                   trends=make_trends(panels=3))
    give_intel(env, panels=3, chrome=["1/3", "2/3", "3/3"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    anchor_call, deck_call = env.llm_call.carriers
    assert 'image 1: "Panel one\n1/3"' in anchor_call
    assert 'image 2: "2/3"' in deck_call, \
        "a wordless panel of a counted deck is not wordless — the badge is still ordered"
    assert 'image 3: "Panel three\n3/3"' in deck_call


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


async def test_the_sanctioned_marks_travel_to_the_vision_check_too(tmp_path: Path) -> None:
    """Ordering a Notion logo and then flagging it as fake UI spends the retry undoing the order.

    The check's second question asks whether the image carries platform chrome or an invented
    interface; a real product logo we deliberately sanctioned is neither, and the question template
    can only know that if the names ride the call.
    """
    entry = make_entry(slides=2, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["one", "two"], trends=make_trends(panels=2))
    give_intel(env, panels=2, marks=[["Notion logo"], ["Figma icon", "Instagram watermark"]])
    env.config.run.vision_check = True
    env.llm_call = VisionStub()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    anchor_call, deck_call = env.llm_call.carriers
    assert "SANCTIONED MARKS" in anchor_call and "image 1: Notion" in anchor_call
    assert "image 2: Figma" in deck_call
    assert "Instagram" not in deck_call, "platform chrome is never sanctioned, on either wire"


async def test_a_deck_without_intelligence_sanctions_no_mark(tmp_path: Path) -> None:
    """The pre-D-A rule is the DEFAULT: every company, product and app mark stays generic."""
    entry = make_entry(slides=2)
    env = make_env(tmp_path, entry, texts=["one", "two"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub()
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert all(marks_line(call.prompt) == "" for call in submit.calls)
    assert all("SANCTIONED MARKS" not in carrier for carrier in env.llm_call.carriers)


# ------------------------------------------------------ D-F the defect-aware retry (v2.1.2)


async def test_a_mismatch_re_render_is_told_what_it_invented_and_forbidden_to_repeat_it(
    tmp_path: Path,
) -> None:
    """D-F: the re-render's instruction names the defect the first verdict actually reported.

    "Set the remaining text noticeably larger" is a remedy for garbled glyphs and a no-op for a
    render that invented copy — which, on a panel-mapped deck, is the defect that earned the retry.
    The verdict's own `detail` is quoted in, so the second attempt is a different REQUEST.
    """
    entry = make_entry(slides=3, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=["Panel one verbatim", "two", "three"],
                   trends=make_trends(panels=3))
    env.config.run.vision_check = True
    env.llm_call = VisionStub(flags=[{1}], defect="text_mismatch",
                              detail="ZZDEFECT it shows BUILD IN PUBLIC instead")
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    retry = submit.calls[1]
    assert retry.kind == "discretionary" and retry.slide == 1
    assert "ZZDEFECT it shows BUILD IN PUBLIC instead" in retry.prompt
    assert "Render the invented words nowhere" in retry.prompt
    assert "LOCKED" in retry.prompt, "the verbatim lever is still the base — the clause is added"
    assert quoted_text(retry.prompt) == "Panel one verbatim", "FR-304: a quote is never trimmed"
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED


async def test_a_fake_ui_re_render_is_forbidden_the_chrome_it_drew(tmp_path: Path) -> None:
    """The other clause: a smaller headline does not remove an invented like counter."""
    entry = make_entry(slides=2)
    env = make_env(tmp_path, entry, texts=["one", "two"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub(flags=[{1}], defect="fake_ui", detail="ZZUI a fake like counter")
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    retry = submit.calls[1]
    assert "ZZUI a fake like counter" in retry.prompt
    assert "platform interface chrome" in retry.prompt
    assert "Set the remaining text" in retry.prompt, "the base text lever still applies"


async def test_a_broken_text_re_render_keeps_the_instruction_it_always_had(
    tmp_path: Path,
) -> None:
    """`text_broken`'s remedy IS the base wording; repeating it would dilute the real clauses."""
    entry = make_entry(slides=2)
    env = make_env(tmp_path, entry, texts=["one", "two"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub(flags=[{1}])  # the default defect is `text_broken`
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    retry = submit.calls[1]
    assert "Set the remaining text" in retry.prompt
    assert "invented or altered words" not in retry.prompt
    assert "platform interface chrome" not in retry.prompt


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

    assert len(uploads.paths) == 6, "every distinct mark is cropped and uploaded once"
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


# ------------------------------ FR-317: the resubmit ledger, separate from the vision retry's


async def test_fr317_a_slide_may_burn_its_vision_retry_and_its_resubmit_independently(
    tmp_path: Path,
) -> None:
    """NFR-4's "one retry per class", with the classes actually separated.

    They answer different questions. FR-105's retry is about the PICTURE — the render came back
    with broken glyphs, so a different request is made. FR-317's is about the JOB — the request
    never came back at all, so the identical request is made once more. A slide that times out,
    is resubmitted, lands, and is then flagged has done nothing wrong twice: it is entitled to one
    of each, and a shared ledger would silently deny the second.
    """
    entry = make_entry(slides=2)
    env = make_env(tmp_path, entry, texts=["one", "two"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub(flags=[{1}])  # the anchor is flagged AFTER its resubmit landed
    submit = FakeSubmit(rule=lambda call: failed(RenderFailCause.TIMEOUT)
                        if call.index == 0 else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    kinds = [(call.slide, call.kind) for call in submit.calls]
    assert kinds == [(1, "projected"),        # the anchor, timed out
                     (1, "discretionary"),    # FR-317's resubmit — the SAME request
                     (1, "discretionary"),    # FR-105's re-render — a DIFFERENT request
                     (2, "precommitted")]
    assert submit.calls[1].prompt == submit.calls[0].prompt, "a resubmit changes nothing"
    assert submit.calls[2].prompt != submit.calls[0].prompt, "a vision retry changes the request"
    assert "image_job_resubmit" in env.log.types()
    assert "vision_check_flagged" in env.log.types()
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED
    assert record.slide_count == 2, "the deck is whole — both retries did their job"


async def test_fr317_a_second_failure_after_the_resubmit_is_final_and_the_slide_is_lost(
    tmp_path: Path,
) -> None:
    """The ceiling. `self.resubmitted` guarantees there is never a third attempt, so the slide
    flows into the ordinary lost-slide path carrying the SECOND job's own cause.

    Losing one slide is not losing the deck (FR-95): the rest ships, `carousel_incomplete` names
    the gap, and the record carries the missing number so the gallery can leave a labelled hole
    rather than closing it.
    """
    entry = make_entry(slides=4)
    env = make_env(tmp_path, entry, texts=["one", "two", "three", "four"])
    submit = FakeSubmit(rule=lambda call: failed(RenderFailCause.TIMEOUT)
                        if call.slide == 3 else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert [call.kind for call in submit.calls if call.slide == 3] == [
        "precommitted", "discretionary"], "two attempts on slide 3, and only two"
    assert record.missing_slide_numbers == [3]
    assert record.slide_count == 3
    assert "carousel_incomplete" in env.log.types()
    assert "timeout" in env.log.fields("carousel_incomplete")["detail"]
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
    assert stored["status"] == "success", "an incomplete deck still ships (FR-95)"


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


async def test_fr321d_the_second_verdict_is_logged_as_evidence_for_retried_passed(
    tmp_path: Path,
) -> None:
    """FR-321d: `vision_check_result` claims one of four states, and `retried_passed` is the only
    one that asserts a defect was FIXED.

    Until this line that assertion rested on a verdict nothing logged — the operator could read
    the claim and not the evidence. `vision_recheck` is the evidence: one line per slide actually
    re-rendered and re-checked, `attempt=2`, carrying the same three defect flags the first pass
    logged under `vision_check_flagged`. It is a record, not a decision: the verdict it prints is
    already the one `verdict_result` is about to use, and there is never a third render.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["one", "two", "three"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub(flags=[{1}])  # anchor flagged, the re-check comes back clean
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    rechecks = [data for name, data in env.log.data if name == "vision_recheck"]
    assert len(rechecks) == 1, "one line per re-rendered slide, not per checked slide"
    assert rechecks[0]["slide"] == 1 and rechecks[0]["attempt"] == 2
    assert rechecks[0]["checked"] is True and rechecks[0]["flagged"] is False
    assert (rechecks[0]["text_broken"], rechecks[0]["fake_ui"], rechecks[0]["text_mismatch"]) == (
        False, False, False), "the same three defect flags the first pass logged"
    assert "re-checked after its one re-render: clean" in \
        next(message for name, message in env.log.records if name == "vision_recheck")
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED


async def test_fr321d_a_re_render_that_is_still_flagged_says_so_and_stays_retried_failed(
    tmp_path: Path,
) -> None:
    """The honest half, and the reason the line is worth having: the SECOND verdict decides.

    A re-render that comes back with the same defect is `retried_failed` and the recheck line says
    "still flagged" with the flag set — so a run whose summary claims a fix and whose evidence
    says otherwise is a contradiction the operator can see, rather than a claim they must trust.
    """
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["one", "two", "three"])
    env.config.run.vision_check = True
    # anchor clean, deck flags slide 2, then the re-check flags the re-rendered slide again
    env.llm_call = VisionStub(flags=[set(), {2}, {1}], defect="text_mismatch",
                              detail="still shows the wrong line")
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    (recheck,) = [data for name, data in env.log.data if name == "vision_recheck"]
    assert recheck["slide"] == 2 and recheck["attempt"] == 2
    assert recheck["flagged"] is True and recheck["text_mismatch"] is True
    assert recheck["detail"] == "still shows the wrong line"
    assert record.vision_check_result is VisionCheckResult.RETRIED_FAILED
    assert record.slide_count == 3, "one re-render, one re-check, then it ships (D3/NFR-4)"


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
    assert carousel_module._mark_name(raw) == name


async def test_fr315_a_slash_joined_descriptor_still_finds_its_uploaded_patch(
    tmp_path: Path, uploads: SimpleNamespace,
) -> None:
    """The glz0 case end to end: box `Claude`, sanctioned mark `Claude logo/wordmark`, one patch.

    The two strings are written by the same vision call and are routinely written DIFFERENTLY —
    `mark_boxes[].name` is the tool, `brand_marks[]` is what the model saw. Both sides of the join
    now run `_mark_name` before collapsing, so the descriptor's spelling stops deciding whether a
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
