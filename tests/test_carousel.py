"""Carousel tests — the anchor chain, FR-105's ordering, and the deck's ONE assigned house style.

Post-pivot (v2.0.0) a deck's look is not analysed per trend any more: `styles.assign_styles` has
already written a `style_key` on the entry, `refs.style_of` resolves it against the run's registry,
and that single `MetaStyle` is what `{{style_dna}}`, `{{render_prompt}}`, `{{exclusions}}` and the
attached reference images all come from (FR-290/291). Three consequences are pinned here:

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

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

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
from hypesocials.render import KieOutOfCredits

REPO = Path(__file__).resolve().parents[1]
#: Real magic bytes: `styles._usable()` validates CONTENT, so a renamed `.txt` is not a reference.
PNG = b"\x89PNG\r\n\x1a\n"
STYLE_KEY = "editorial-voxel-carousel"
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
    """A `models.StructuredCall` that answers the vision check from a per-call flag table."""

    def __init__(self, flags: list[set[int]] | None = None,
                 events: list[str] | None = None) -> None:
        self.flags = flags or []
        self.calls: list[int] = []
        self.events = events if events is not None else []

    async def __call__(self, role, messages, json_schema, images=None) -> ParsedResult:
        count = len(images or [])
        self.calls.append(count)
        self.events.append(f"check:{count}")
        flagged = self.flags[len(self.calls) - 1] if len(self.calls) <= len(self.flags) else set()
        return ParsedResult(parsed={"verdicts": [
            {"image": i, "text_broken": i in flagged, "fake_ui": False, "detail": "garbled"}
            for i in range(1, count + 1)]}, raw_text="{}")


class Log:
    """`outputs.LogWriter`'s three call shapes, remembering only what tests assert on."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def event(self, event_type: str, message: str = "", **data: Any) -> str:
        self.records.append((event_type, message))
        return f"ev_{len(self.records):04d}"

    warn = event
    error = event

    def types(self) -> list[str]:
        return [event_type for event_type, _ in self.records]


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
    """
    control = SimpleNamespace(paths=[])
    refs_module.reset_uploads()

    async def _upload(path: Path) -> str:
        control.paths.append(Path(path))
        return f"https://kie.test/upload/{Path(path).name}"

    monkeypatch.setattr(render, "upload_file", _upload)
    yield control
    refs_module.reset_uploads()


def style_url(name: str) -> str:
    return f"https://kie.test/upload/{name}"


def repo_relative(path: Path) -> str:
    """`reference_images` entries are REPO-ROOT-relative (§1.3), so a `tmp_path` file is expressed
    as the relative hop out of the repo and back — the same string a shipped registry holds."""
    try:
        return Path(os.path.relpath(path, REPO)).as_posix()
    except ValueError:  # pragma: no cover - different drive; an absolute path joins the same way
        return path.as_posix()


def make_style(tmp_path: Path, *, images: int = 2, guidance: bool = True,
               key: str = STYLE_KEY) -> MetaStyle:
    """One registry entry with REAL reference files on disk, so the window rotation and the
    magic-byte check both run for real rather than against a mock."""
    folder = tmp_path / "style-refs"
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(1, images + 1):
        path = folder / f"{key}-{index:02d}.png"
        path.write_bytes(PNG + b"\x00" * 64)
        paths.append(path)
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
        exclusions=["platform UI", "engagement counters"],
        reference_images=[repo_relative(path) for path in paths])


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


def style_urls(style: MetaStyle) -> list[str]:
    """The URLs `refs.attach` produces for this style's whole reference window, in F19 order."""
    return [style_url(Path(raw).name) for raw in style.reference_images]


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


async def test_an_override_brief_suppresses_the_style_its_pictures_and_its_guidance(
    tmp_path: Path,
) -> None:
    """FR-144/M14: an `override` brief replaces the assigned style ENTIRELY — the `render_prompt`
    and the reference images both. So there is no `per_format_guidance` to append either: the
    brief's own directives are the whole creative, on every slide."""
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
    assert submit.slide(1).image_urls == [], \
        "M14: an override brief attaches no style picture at all"
    assert submit.slide(2).image_urls == [submit.slide(1).url], \
        "the anchor chain is untouched by M14 — the deck still reproduces its own slide 1"
    assert DegradationTag.REFERENCE_FREE in record.degradations
    assert style_dna(None) == "" and "STYLE_DNA" in submit.slide(1).prompt, \
        "the block is empty, not missing — the scaffold is one shape for every case"


# ------------------------------------------------------------------ references (F19 / FR-200)


async def test_style_references_lead_and_a_briefs_own_pictures_follow(tmp_path: Path) -> None:
    """F19: every render scaffold tells the model to follow the FIRST reference listed, so the
    attachment order IS the FR-145 precedence — the house style wins the look, the brief keeps its
    subject. The two role lines are worded differently for the same reason."""
    entry = make_entry(slides=2, brief_name="product", brief_influence="blend")
    style = make_style(tmp_path)
    product = tmp_path / "product.png"
    product.write_bytes(PNG + b"\x00" * 32)
    env = make_env(tmp_path, entry, texts=["one", "two"], style=style)
    env.campaign_briefs = {"product": Brief(name="product", description="", influence="blend",
                                            visual_directives={"scene": "the product on a desk"})}
    env.local_refs = {entry.asset_id: [(product, "brief")]}
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    anchor = submit.slide(1)
    assert anchor.image_urls == [*style_urls(style), style_url("product.png")]
    assert (f'Image 1 — house style reference "{STYLE_KEY}": layout, palette, typography and '
            "treatment only; no words, no logos.") in anchor.prompt
    assert "Image 3: brief subject" in anchor.prompt, "the brief's photo is the SUBJECT, not style"


async def test_each_style_file_is_uploaded_once_per_run_however_many_decks(
    tmp_path: Path, uploads: SimpleNamespace,
) -> None:
    """FR-200/244: the upload memo is run-scoped, so a style's reference window costs one upload
    per FILE per run — not one per job. A second deck on the same run re-uses the URLs; a second
    run (a different `run_dir`) uploads again, because Kie keeps an upload about 24 h."""
    style = make_style(tmp_path, images=2)
    first, second = make_entry(slides=2), make_entry(slides=2, asset_id="0002_carousel_linkedin")
    env = make_env(tmp_path, first, texts=["one", "two"], style=style)
    env.copy[second.asset_id] = env.copy[first.asset_id]

    await render_carousel(first, env, make_folder(tmp_path, first), submit=FakeSubmit())
    after_first = list(uploads.paths)
    await render_carousel(second, env, make_folder(tmp_path, second), submit=FakeSubmit())

    assert len(after_first) == 2, "the window is `styles.refs_per_job` wide, uploaded once each"
    assert uploads.paths == after_first, "the sibling deck uploaded nothing new (the memo)"

    later_run = tmp_path / "run-2"
    later_run.mkdir()
    env.run_dir = later_run
    await render_carousel(make_entry(slides=1, asset_id="0003_carousel_linkedin"),
                          make_env(later_run, first, texts=["one"], style=style),
                          make_folder(later_run, first), submit=FakeSubmit())
    assert len(uploads.paths) == 4, "a NEW run re-uploads: a memoized URL would 404 mid-batch"


async def test_a_style_whose_pictures_are_all_gone_degrades_to_text_only(tmp_path: Path) -> None:
    """FR-18/295: the written guidance is intact, so the deck still renders — but the operator
    hears which CREATIVE lost its proof, and the record says so."""
    entry = make_entry(slides=2)
    style = make_style(tmp_path, images=1)
    for raw in style.reference_images:
        (REPO / raw).unlink()
    env = make_env(tmp_path, entry, texts=["one", "two"], style=style)
    folder = make_folder(tmp_path, entry)

    record = await render_carousel(entry, env, folder, submit=FakeSubmit())

    assert DegradationTag.STYLE_REFS_MISSING in record.degradations
    assert DegradationTag.REFERENCE_FREE in record.degradations
    assert "style_refs_missing" in env.log.types()
    assert record.status is AssetStatus.SUCCESS, "a text-only style is a degrade, not a failure"


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
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry, texts=["a", "b", "c"])
    env.llm_call = VisionStub()  # present, but `run.vision_check` is off

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=FakeSubmit())

    assert env.llm_call.calls == []
    assert record.vision_check_result is VisionCheckResult.NOT_CHECKED


# ------------------------------------------------------- FR-95 anchor chain (barrier item)


async def test_slides_two_onward_lead_with_the_finished_anchor(tmp_path: Path) -> None:
    """FR-95: the finished slide 1 is the PRIMARY reference, ahead of the style references, and
    it is introduced by the template-lock block rather than by a style role line."""
    entry = make_entry(slides=3)
    style = make_style(tmp_path)
    env = make_env(tmp_path, entry, texts=["one", "two", "three"], style=style)
    submit = FakeSubmit()

    await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    anchor = submit.slide(1)
    assert anchor.kind == "projected" and anchor.priority is RenderPriority.WAVE1
    assert anchor.image_urls == style_urls(style)
    for number in (2, 3):
        call = submit.slide(number)
        assert call.image_urls[0] == anchor.url, "the anchor leads the reference set"
        assert call.image_urls[1:] == style_urls(style), "the style window follows it"
        assert "ANCHOR REFERENCE" in call.prompt, "the template-lock block is prepended"
        assert call.kind == "precommitted" and call.priority is RenderPriority.WAVE2


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
    PRE-COMMITTED work, never discretionary: the cap may not split a deck (FR-95/FR-106b)."""
    entry = make_entry(slides=4)
    style = make_style(tmp_path)
    env = make_env(tmp_path, entry, style=style)
    submit = FakeSubmit(rule=lambda call: failed() if call.index == 0 else ok(call))

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    assert len(submit.calls) == 5, "the failed anchor plus N independent slides (FR-107's N+1)"
    fallback = submit.calls[1:]
    assert [call.slide for call in fallback] == [1, 2, 3, 4]
    assert {call.kind for call in fallback} == {"precommitted"}, "never discretionary"
    assert {call.priority for call in fallback} == {RenderPriority.WAVE2}
    assert all(call.image_urls == style_urls(style) for call in fallback), "no anchor reference"
    assert "carousel_anchor_fallback" in env.log.types()
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
    assert 'headline (render verbatim): "ZZONE the opener"' in submit.slide(1).prompt
    assert 'headline (render verbatim): "ZZTHREE the payoff"' in submit.slide(3).prompt
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
    """FR-97: one resubmission with every reference removed, marked `refs_dropped_moderation`."""
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
    """FR-105's retry changes the INPUT: less text, a tighter stated budget, larger type."""
    entry = make_entry(slides=3)
    env = make_env(tmp_path, entry,
                   texts=["A slide-one line that is far longer than the retry budget", "b", "c"])
    env.config.run.vision_check = True
    env.llm_call = VisionStub(flags=[{1}])
    submit = FakeSubmit()

    record = await render_carousel(entry, env, make_folder(tmp_path, entry), submit=submit)

    first, retry = submit.calls[0], submit.calls[1]
    assert retry.slide == 1 and retry.kind == "discretionary"
    assert retry.priority is RenderPriority.WAVE1, "the deck is still waiting on this anchor"
    assert "re-render of an image whose text came back broken" in retry.prompt
    assert submit.calls[2].image_urls[0] == retry.url, "the deck anchors to the FINAL slide 1"
    assert env.llm_call.calls == [1, 1, 3], "check, re-render, RE-CHECK, then the deck call"
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED
    assert dna_block(first.prompt) == dna_block(retry.prompt), \
        "a retry changes the TEXT, never the deck's style DNA"


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
