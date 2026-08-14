"""Wave-engine tests — format dispatch, the one money door, and honest abandonment.

Post-pivot (v2.0.0) `generate.Env` carries the run's STYLE REGISTRY and its BRANDING CONFIG, and
no longer carries a style-brief book, a brand accent, brand product nouns or a video-reference
prefetch (contracts item 11). Every `Env` here is built on that post-pivot field set.

**Text-to-image is the default route (D46/F3, v2.1.0).** A meta-style ships no pixels: its
`render_prompt` and DNA rows qualify the render in WORDS, so an ordinary style-driven creative
submits with an EMPTY `image_urls` and that is the normal case, not a degradation. The only
local files a job still uploads are a campaign BRIEF's own product photos (FR-144/145), which is
why every reference assertion in this file is written against a brief rather than against a
registry entry — the registry has no picture channel left to assert on.

What did NOT change is the reason this file exists: ONE money door, the FR-106 a/b/c reservation
kinds, the two-wave permit priorities (wave-1 = image and carousel anchor and reel seed frame;
wave-2 = slides 2–N and the Seedance clip), one FR-203 ledger line per submission, and FR-108's
single grace window.

No network and no money: `render.run` is monkeypatched, `render.upload_file` is faked, the
packager's download is faked, and the budget/ledger are the REAL ones so every assertion is
against what actually lands on disk in `tmp_path`. The carousel and reel modules are faked where
only the *dispatch* is under test — their own chains have their own suites.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hypesocials import generate, render, styles
from hypesocials.budget import Budget
from hypesocials.config import BrandingConfig, Config
from hypesocials.generate import refs as refs_module
from hypesocials.models import (
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
    TrendItem,
    VisionCheckResult,
)
from hypesocials.outputs import Ledger, packager, read_meta
from hypesocials.prompts_engine import PromptEngine

REPO = Path(__file__).resolve().parents[1]
PNG = b"\x89PNG\r\n\x1a\n"
STYLE_KEY = "platform-showcase-card"
BRIEF_NAME = "product-shot"
RESULT_URL = "https://tempfile.aiquickdraw.com/result.jpg"
#: contracts item 11 — the four `Env` fields the W2 wire-in deletes, plus the method that dies
#: with `style_briefs`. Named once so the "post-pivot shape" assertion reads as a list, not a
#: sequence of `hasattr` calls whose intent has to be reconstructed.
DEAD_ENV_FIELDS = ("style_briefs", "brand_accent", "brand_product_nouns", "video_refs")


# --------------------------------------------------------------------------------- doubles


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


class Renders:
    """A fake `render.run`: records every submission and answers from a queue or a rule."""

    def __init__(self, outcomes: list[Any] | None = None, rule: Any = None) -> None:
        self.queue = list(outcomes or [])
        self.rule = rule
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, profile: str, params: Any, refs: Any,
                       priority: RenderPriority) -> RenderOutcome:
        self.calls.append({"profile": profile, "priority": priority, "params": params,
                           "refs": refs})
        answer = self.rule(self) if self.rule is not None else (
            self.queue.pop(0) if self.queue else ok())
        if isinstance(answer, BaseException):
            raise answer
        return answer

    @property
    def profiles(self) -> list[str]:
        return [call["profile"] for call in self.calls]


def ok(url: str = RESULT_URL, *, task: str = "kie_ok", cost: float = 0.03) -> RenderOutcome:
    return RenderOutcome(kind=RenderOutcomeKind.SUCCESS, task_id=task, request_token="tok",
                         result_urls=[url], cost_usd=cost, submitted_at="2026-08-09T10:00:00Z",
                         completed_at="2026-08-09T10:01:00Z")


def vision(*flags: bool) -> Any:
    """A `models.StructuredCall` answering FR-105 — one queued verdict per check call."""
    queue = list(flags) or [False]

    async def call(role: str, messages: list[dict[str, Any]], schema: dict[str, Any],
                   images: list[bytes] | None = None) -> ParsedResult:
        flagged = queue.pop(0) if len(queue) > 1 else queue[0]
        return ParsedResult(parsed={"verdicts": [{"image": 1, "text_broken": flagged,
                                                  "fake_ui": False, "detail": "garbled headline"}]},
                            raw_text="{}", cost_usd=0.01)
    return call


def refused() -> RenderOutcome:
    return RenderOutcome(kind=RenderOutcomeKind.FAIL, task_id="kie_refused", request_token="tok",
                         fail_cause=RenderFailCause.MODERATION,
                         fail_message="content policy", cost_usd=0.03)


def timed_out() -> RenderOutcome:
    """Exactly what `render/kie.py::_classify` builds when `recordInfo` never went terminal.

    The pairing is fixed at the seam — `kind=STUCK` with `fail_cause=TIMEOUT` — and `cost_usd` is
    0.0 because the record it was built from was EMPTY, not because Kie reported a zero. That is
    the ambiguity `generate._billed_usd` exists to resolve, so the double is written to carry it.
    """
    return RenderOutcome(kind=RenderOutcomeKind.STUCK, task_id="kie_stuck", request_token="tok",
                         fail_cause=RenderFailCause.TIMEOUT,
                         fail_message="no terminal state within 300s", cost_usd=0.0)


# --------------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def downloads(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Every `store_render` writes real bytes to a real folder; nothing touches the network."""
    control = SimpleNamespace(fetched=[], fail_reason="")

    async def _download(url: str) -> bytes:
        control.fetched.append(url)
        if control.fail_reason:
            raise packager.PackagingError(f"write failed: {control.fail_reason}",
                                          reason=control.fail_reason)
        return b"\xff\xd8fake-jpeg-bytes"

    monkeypatch.setattr(packager, "_download", _download)
    return control


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


def make_registry(_tmp_path: Path) -> styles.StyleRegistry:
    """A one-entry TEXT-ONLY registry — the post-D46 shape (FR-17/18/290).

    There is no reference-image scaffolding to build any more: a style qualifies its render
    through `render_prompt`, its zones and its five DNA rows, and `MetaStyle` has no
    `reference_images` field to hand `refs.attach()` a picture through. A creative wearing this
    style submits with an empty `image_urls`, which is what every reference assertion below is
    measured against.
    """
    style = MetaStyle(
        key=STYLE_KEY,
        render_prompt="Flat product card on a soft gradient ground, one hard shadow.",
        layout_zones=[LayoutZone("upper third", "headline", "bold, sentence case")],
        format_affinity=["image", "carousel", "reel"], text_density="high",
        max_onimage_chars={"headline": 100, "subline": 60, "slide": 100},
        palette=["#1B1F3B"], typography="bold condensed sans",
        text_placement="headline upper third", image_treatment="flat graphic",
        visual_pacing="one idea per panel", exclusions=["platform UI"])
    return styles.StyleRegistry(version=1, styles=[style],
                                origin=str(REPO / "prompts" / "styles.yaml"),
                                content_hash="0123456789ab")


def give_brief(env: generate.Env, entries: list[PlanEntry], tmp_path: Path, *,
               photos: int = 1) -> list[Path]:
    """Point these entries at ONE campaign brief that ships `photos` real files (FR-144/145).

    Post-D46 this is the only way a render job carries an attachment it did not make itself, so
    it is the fixture behind every upload-memo, attachment-order and FR-97 assertion in this
    file. The files are real bytes on disk because `refs.attach()` uploads what it is handed and
    a missing file is a different test (the FR-18 loss path).
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
    env.local_refs = {entry.asset_id: tuple((path, "brief") for path in paths)
                      for entry in entries}
    for entry in entries:
        entry.brief_name, entry.brief_influence = BRIEF_NAME, "blend"
    return paths


def brief_url(path: Path) -> str:
    """The URL the faked `render.upload_file` hands back for one brief photo."""
    return f"https://kie.test/upload/{path.name}"


def make_entry(order: int = 0, fmt: str = "image", **overrides: Any) -> PlanEntry:
    entry = PlanEntry(order=order, asset_id=f"{order:04d}_{fmt}_linkedin", creative_format=fmt,
                      platform="linkedin" if fmt != "reel" else "tiktok", language="en",
                      aspect_ratio="1:1" if fmt != "reel" else "9:16",
                      trend_key="t1", style_key=STYLE_KEY, estimated_cost_usd=0.10)
    for key, value in overrides.items():
        setattr(entry, key, value)
    return entry


def make_env(tmp_path: Path, entries: list[PlanEntry], *, cap_usd: float = 5.0,
             **overrides: Any) -> generate.Env:
    trend = TrendItem(history_key="t1", monitor_id="m1", name="AI tool stacks",
                      topic_key="ai-tool-stacks", why_it_works="numbers in the first line",
                      hook_texts=["Nobody tells you this about AI tools"],
                      video_descriptions=["a creator lists seven tools"],
                      panel_texts=["panel one", "panel two"])
    env = generate.Env(
        config=Config(), run_dir=tmp_path, engine=PromptEngine(), budget=Budget(cap_usd),
        log=Log(), ledger=Ledger(tmp_path), trends={"t1": trend},
        # The post-pivot pair (contracts item 11): the assigned-style authority and the brand
        # selector. `style_briefs`, `brand_accent`, `brand_product_nouns` and `video_refs` are
        # deliberately NOT passed — they leave the dataclass at this wave's wire-in.
        styles=make_registry(tmp_path),
        branding=BrandingConfig(brand="hypelead"),
        copy={entry.asset_id: CopySet(asset_id=entry.asset_id, language="en", trend_key="t1",
                                      caption="Most people wire this backwards.", hashtags=["#ai"],
                                      headline="Wired backwards", subline="Here is the fix",
                                      overlay_text="Wired backwards",
                                      through_line="a fast reveal of the tool stack",
                                      motion_beat="the hand sweeps the cards off the table",
                                      slide_texts=["One", "Two", "Three", "Four", "Five"])
              for entry in entries},
        stop=asyncio.Event(), niche_descriptor="Audience: founders · Vibe: blunt")
    for key, value in overrides.items():
        setattr(env, key, value)
    return env


def ledger_lines(tmp_path: Path) -> list[str]:
    return (tmp_path / "LEDGER.txt").read_text(encoding="utf-8").strip().splitlines()


# --------------------------------------------------------------------- the post-pivot Env shape


def test_the_env_is_the_post_pivot_field_set(tmp_path: Path) -> None:
    """Contracts item 11, asserted rather than assumed: the run's constants are now the style
    REGISTRY and the branding config, and the four style-brief/motion-reference fields — plus
    `brief_for()`, which cannot outlive `style_briefs` — are gone.

    An `Env` that still carried them would let a caller keep resolving a per-trend style brief
    for two more waves, which is precisely the drift the additive-then-subtractive migration
    exists to end.
    """
    env = make_env(tmp_path, [make_entry()])

    assert env.styles is not None and env.styles.styles[0].key == STYLE_KEY
    assert env.branding.brand == "hypelead"
    fields = set(generate.Env.__dataclass_fields__)
    assert not fields & set(DEAD_ENV_FIELDS), \
        f"still on the Env: {sorted(fields & set(DEAD_ENV_FIELDS))}"
    assert not hasattr(generate.Env, "brief_for"), "the pair-keyed brief lookup dies with the book"


def test_ref_source_names_the_brief_whose_photos_a_creative_actually_uploaded(
    tmp_path: Path,
) -> None:
    """FR-73's provenance vocabulary post-D46 is `brief | ""` — and nothing else.

    "virlo" died with the text-only pivot (no Virlo pixel reaches a render job) and `"style"`
    died with the picture channel (D46/F3): a meta-style is words now, so a creative wearing one
    uploaded NOTHING and the honest field is empty. `"brief"` is claimed only when the brief
    actually SHIPS photos — a brief with directives and no images contributes no reference, and
    naming one would make this field a second, wrong answer to "why does this look like this".
    """
    styled = make_entry()
    env = make_env(tmp_path, [styled])

    assert generate._record(styled, env).ref_source == "", \
        "a text-only house style is not a reference source"

    with_photos = make_entry(1)
    env.copy[with_photos.asset_id] = env.copy[styled.asset_id]
    give_brief(env, [with_photos], tmp_path)
    assert generate._record(with_photos, env).ref_source == "brief"

    # A brief that ships directives and no pictures uploads nothing, so it names nothing.
    env.campaign_briefs[BRIEF_NAME].reference_image_paths = []
    assert generate._record(with_photos, env).ref_source == ""


# ------------------------------------------------- FR-73 v2.1.0: the three-stage provenance join
#
# `_record` is the ONE place the PLAN's bound post, the COPY stage's panel map and the slide
# INTELLIGENCE reading of that same deck become a single document. FR-309's gallery card is built
# from exactly these fields and re-derives nothing, so a join that drops a key, invents a value or
# lets one absent stage take another one down with it is a wrong page over a correct run.


class FakeSlide:
    """One `sources.slide_intel.SourceSlide`, duck-typed — `_record` reads attributes, not types."""

    def __init__(self, position: int, *, brief: str = "", image: str | None = None) -> None:
        self.position = position
        self.visual_brief = brief
        self.image_file = image


class FakeIntel:
    """The `SlideIntel` surface `_record` uses: `slide()`, `relative_image()`, `degradations`.

    Deliberately NOT the real dataclass. `generate` imports nothing from `sources` (the dependency
    runs the other way), so the contract between them is a duck type, and a test that instantiated
    the real class would be pinning an import this module is not allowed to have.
    """

    def __init__(self, *slides: FakeSlide, folder: str = "source/p1",
                 degradations: tuple[str, ...] = ()) -> None:
        self.slides = list(slides)
        self.folder = folder
        self.degradations = list(degradations)

    def slide(self, position: int) -> FakeSlide | None:
        return next((item for item in self.slides if item.position == position), None)

    def relative_image(self, position: int) -> str | None:
        found = self.slide(position)
        return f"{self.folder}/{found.image_file}" if found and found.image_file else None


def bound_deck(tmp_path: Path, **overrides: Any) -> tuple[PlanEntry, generate.Env]:
    """A carousel bound to post `p1` of topic `t1`, with a copy-stage map over three slides."""
    from datetime import datetime, timezone

    from hypesocials.copywrite import CopyProvenance
    from hypesocials.models import SourcePost

    entry = make_entry(0, "carousel", source_post_id="p1", slide_count=3)
    env = make_env(tmp_path, [entry])
    env.trends["t1"].posts = [SourcePost(
        post_id="p1", url="https://www.tiktok.com/@creator/photo/p1", author="creator",
        views=1_240_000, caption="the five tools I actually use", is_slideshow=True,
        panel_count=3, published_at=datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc))]
    env.copy_provenance = {entry.asset_id: CopyProvenance(
        post_id="p1", refs={"slide_1": "P1.panel.1"}, source_panel_count=3,
        panel_map=[{"slide": 1, "source_position": 1, "source_text": "Panel one",
                    "ref_label": "P1.panel.1"},
                   {"slide": 2, "source_position": 2, "source_text": "", "ref_label": ""},
                   {"slide": 3, "source_position": 3, "source_text": "Panel three",
                    "ref_label": "P1.panel.3"}])}
    for key, value in overrides.items():
        setattr(env, key, value)
    return entry, env


def test_fr73_the_meta_joins_the_bound_post_the_panel_map_and_the_slide_reading(
    tmp_path: Path,
) -> None:
    """All three stages present — the shape FR-309's three-part card is drawn from.

    The copy stage owns `{slide, source_position, source_text, ref_label}` and the intelligence
    pass owns `visual_brief` (FR-308's content directive) and `source_image` (FR-309's strip,
    run-relative per FR-75). Neither overwrites the other, and the row ORDER is the copy stage's,
    because the row IS the alignment.
    """
    entry, env = bound_deck(tmp_path)
    env.slide_intel = {"p1": FakeIntel(
        FakeSlide(1, brief="hero image, heading centred", image="slide_01.jpg"),
        FakeSlide(2, brief="two-column table, four rows", image="slide_02.jpg"),
        FakeSlide(3, brief="line chart, three series", image="slide_03.jpg"))}

    record = generate._record(entry, env)

    assert record.source_panel_count == 3
    assert record.panel_map == [
        {"slide": 1, "source_position": 1, "source_text": "Panel one", "ref_label": "P1.panel.1",
         "visual_brief": "hero image, heading centred", "source_image": "source/p1/slide_01.jpg"},
        {"slide": 2, "source_position": 2, "source_text": "", "ref_label": "",
         "visual_brief": "two-column table, four rows", "source_image": "source/p1/slide_02.jpg"},
        {"slide": 3, "source_position": 3, "source_text": "Panel three", "ref_label": "P1.panel.3",
         "visual_brief": "line chart, three series", "source_image": "source/p1/slide_03.jpg"}]
    assert record.source_post == {
        "post_id": "p1", "url": "https://www.tiktok.com/@creator/photo/p1", "author": "creator",
        "views": 1_240_000, "published_at": "2026-08-01T09:30:00+00:00",
        "caption": "the five tools I actually use"}
    assert isinstance(record.source_post["published_at"], str), \
        "meta.yaml is a document a human reads, so a datetime never reaches it"
    assert record.copy_source_post_id == "p1" and record.copy_source_refs == {
        "slide_1": "P1.panel.1"}


def test_fr73_a_panel_map_row_carries_both_intel_keys_even_with_no_intelligence_at_all(
    tmp_path: Path,
) -> None:
    """ONE row schema, always. Vision off, a failed read, a preview, a test — every row still gains
    `visual_brief` and `source_image`, empty and `None`.

    A consumer that had to ask whether a key EXISTS before reading it would be reading two schemas,
    and the gallery's alignment loop is the last place that should have to branch. The row count
    and order are untouched either way: the intelligence pass adds content to rows, it never
    creates, drops or re-orders them.
    """
    entry, env = bound_deck(tmp_path)  # env.slide_intel deliberately left empty

    record = generate._record(entry, env)

    assert [row["slide"] for row in record.panel_map] == [1, 2, 3]
    assert all(row["visual_brief"] == "" and row["source_image"] is None
               for row in record.panel_map)
    assert record.source_post is not None, "no intelligence is not no provenance"
    assert record.degradations == []


def test_fr73_a_slide_whose_picture_never_downloaded_keeps_its_row_and_loses_only_the_picture(
    tmp_path: Path,
) -> None:
    """§0.14c case (b) through the join: a 404 leaves that row's `source_image` null while its
    words, its ref label and its position survive — the gallery draws a labelled gap in that one
    tile instead of shifting every later tile up by one."""
    entry, env = bound_deck(tmp_path)
    env.slide_intel = {"p1": FakeIntel(FakeSlide(1, brief="hero image", image="slide_01.jpg"),
                                       FakeSlide(2, brief="", image=None),
                                       FakeSlide(3, brief="line chart", image="slide_03.jpg"))}

    rows = generate._record(entry, env).panel_map

    assert rows[1] == {"slide": 2, "source_position": 2, "source_text": "", "ref_label": "",
                       "visual_brief": "", "source_image": None}
    assert rows[2]["source_image"] == "source/p1/slide_03.jpg"


def test_fr73_the_join_never_mutates_the_copy_stages_own_rows(tmp_path: Path) -> None:
    """`CopyProvenance` is the caller's data and two sibling creatives may share one — so the meta
    writer copies each row before adding to it. Writing through would give the second creative a
    map already carrying the first one's briefs."""
    entry, env = bound_deck(tmp_path)
    env.slide_intel = {"p1": FakeIntel(FakeSlide(1, brief="hero image", image="slide_01.jpg"))}
    original = [dict(row) for row in env.copy_provenance[entry.asset_id].panel_map]

    generate._record(entry, env)

    assert env.copy_provenance[entry.asset_id].panel_map == original
    assert all("visual_brief" not in row
               for row in env.copy_provenance[entry.asset_id].panel_map)


def test_fr73_a_bound_post_the_topic_can_no_longer_resolve_carries_its_id_alone(
    tmp_path: Path,
) -> None:
    """The id is a fact; `author: ""` and `views: 0` beside it would be invented provenance.

    Reachable whenever the roster moved under the plan — a re-fetch between ASSIGN and meta, a
    trend dropped from `env.trends`, a plan resurrected from an older run. The gallery renders the
    id alone and offers no permalink, which is the honest rendering of "we know which post, and
    nothing else about it any more".
    """
    entry, env = bound_deck(tmp_path)
    env.trends["t1"].posts = []

    record = generate._record(entry, env)

    assert record.source_post == {"post_id": "p1"}
    assert record.panel_map, "losing the post does not lose the deck's own alignment"


def test_fr73_an_unbound_creative_has_no_source_post_and_no_rows(tmp_path: Path) -> None:
    """`source_post: null` is FR-309's routing signal to the single-card layout (§0.14d).

    An image, a reel and an override-brief carousel bind no deck, so there is nothing to align and
    nothing to claim — and the fallback the null routes to is today's card, unchanged.
    """
    entry = make_entry(0, "carousel", brief_influence="override", brief_name=BRIEF_NAME,
                       style_key="")
    env = make_env(tmp_path, [entry])

    record = generate._record(entry, env)

    assert record.source_post is None
    assert record.panel_map == [] and record.source_panel_count == 0
    # M14: an override brief was the visual authority, and the card says so where a style key
    # would otherwise stand — the gallery treats it as a style key like any other.
    assert record.style_key == "brief_override"


def test_fr306_the_intel_tags_reach_meta_without_duplicating_the_copy_stages_own(
    tmp_path: Path,
) -> None:
    """FR-306's two degradations, in FR-73's enum, appended to what the copy stage already tagged.

    `SlideIntel.degradations` answers in the meta.yaml vocabulary by contract, so this is a lookup
    rather than a mapping table — one spelling, owned by `DegradationTag`. The de-duplication
    matters because both stages can legitimately report the same condition, and a badge printed
    twice reads as two separate losses.
    """
    entry, env = bound_deck(tmp_path)
    env.copy_tags = {entry.asset_id: [DegradationTag.NO_ONIMAGE_TEXT,
                                      DegradationTag.VISION_TRANSCRIBED]}
    env.slide_intel = {"p1": FakeIntel(FakeSlide(1),
                                       degradations=("vision_transcribed", "vision_unavailable"))}

    record = generate._record(entry, env)

    assert record.degradations == [DegradationTag.NO_ONIMAGE_TEXT,
                                   DegradationTag.VISION_TRANSCRIBED,
                                   DegradationTag.VISION_UNAVAILABLE]


def test_fr306_a_degradation_this_build_cannot_spell_is_skipped_not_raised(
    tmp_path: Path,
) -> None:
    """An unknown tag is a version skew between two modules, and the render is already paid for —
    so it is dropped from the enum-typed list rather than costing this creative its meta.yaml."""
    entry, env = bound_deck(tmp_path)
    env.slide_intel = {"p1": FakeIntel(
        FakeSlide(1), degradations=("a_tag_from_the_future", "vision_unavailable"))}

    assert generate._record(entry, env).degradations == [DegradationTag.VISION_UNAVAILABLE]


# --------------------------------------------------------------------------- dispatch by format


async def test_dispatch_reaches_each_format_module_with_the_right_submit_kinds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_one` dispatches by format and every module spends through the SAME injected `submit` —
    one money path, not two. Kinds are FR-106's: wave-1 work is `projected`, the deck's slides and
    the Seedance clip are `precommitted`."""
    entries = [make_entry(0, "image"), make_entry(1, "carousel"), make_entry(2, "reel")]
    env = make_env(tmp_path, entries)
    seen: list[tuple[str, str, RenderPriority]] = []

    async def fake_carousel(entry, env_, folder, *, submit):
        await submit(entry, SimpleNamespace(prompt="p", aspect_ratio="1:1"),
                     SimpleNamespace(image_urls=[], video_urls=[]), job="slide",
                     priority=RenderPriority.WAVE2, kind="precommitted", label="slide 1")
        entry.status = PlanEntryStatus.SUCCESS
        return folder.finish()

    async def fake_reel(entry, env_, folder, *, submit):
        await submit(entry, SimpleNamespace(prompt="p", aspect_ratio="9:16"),
                     SimpleNamespace(image_urls=[], video_urls=[]), job="clip",
                     priority=RenderPriority.WAVE2, kind="precommitted", label="reel clip")
        entry.status = PlanEntryStatus.SUCCESS
        return folder.finish()

    async def spy(entry, params, refs, *, env, job, priority, kind, label):
        seen.append((job, kind, priority))
        return await real_submit(entry, params, refs, env=env, job=job, priority=priority,
                                 kind=kind, label=label)

    real_submit = generate._submit
    monkeypatch.setattr(generate, "_submit", spy)
    monkeypatch.setattr(generate, "render_carousel", fake_carousel)
    monkeypatch.setattr(generate, "render_reel", fake_reel)
    renders = Renders(rule=lambda _self: ok())
    monkeypatch.setattr(render, "run", renders)

    report = await generate.create(entries, env)

    assert seen == [("image", "projected", RenderPriority.WAVE1),
                    ("slide", "precommitted", RenderPriority.WAVE2),
                    ("clip", "precommitted", RenderPriority.WAVE2)]
    # `submit` owns the profile choice: only a clip goes to the video profile (FR-281).
    assert renders.profiles == [env.config.models.image_profile, env.config.models.image_profile,
                                env.config.models.video_profile]
    assert len(report.records) == 3
    assert report.packaged_trends == {"t1"}  # FR-82: one history line per packaged trend


async def test_real_carousel_and_reel_chains_land_through_the_wave_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two-wave shape without a network: the REAL `render_carousel` and `render_reel` run
    behind the injected `submit`, so the deck's anchor and the reel's seed frame go out as wave-1
    and the deck's remaining slides plus the clip as wave-2 (FR-25/95/24), and every file lands in
    its own folder. Nothing anywhere carries a video reference (v2.0.0)."""
    deck, clip = make_entry(0, "carousel"), make_entry(1, "reel")
    env = make_env(tmp_path, [deck, clip])

    def result(self: Renders) -> RenderOutcome:  # the clip comes back mp4, everything else jpg
        video = self.calls[-1]["profile"] == env.config.models.video_profile
        return ok("https://tempfile.aiquickdraw.com/clip.mp4" if video else RESULT_URL,
                  task=f"kie_{len(self.calls)}")

    renders = Renders(rule=result)
    monkeypatch.setattr(render, "run", renders)

    report = await generate.create([deck, clip], env)

    slides = env.config.platform("linkedin").carousel_slides
    assert deck.status is PlanEntryStatus.SUCCESS and clip.status is PlanEntryStatus.SUCCESS
    assert (tmp_path / deck.asset_id / "slide_01.jpg").is_file()
    assert (tmp_path / clip.asset_id / "seed_frame.jpg").is_file()
    assert (tmp_path / clip.asset_id / "reel.mp4").is_file()
    assert report.records[deck.asset_id].slide_count == slides
    # Anchor first and alone (WAVE1), then the rest of the deck and the clip as wave-2 work.
    deck_calls = [call for call in renders.calls if call["params"].aspect_ratio == "1:1"]
    assert deck_calls[0]["priority"] is RenderPriority.WAVE1
    assert {call["priority"] for call in deck_calls[1:]} == {RenderPriority.WAVE2}
    assert renders.profiles.count(env.config.models.video_profile) == 1  # one clip, one profile
    assert all(call["refs"].video_urls == [] for call in renders.calls)
    assert len(ledger_lines(tmp_path)) == len(renders.calls)  # one terminal line per submission


async def test_a_briefs_photo_is_uploaded_once_for_the_whole_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: SimpleNamespace,
) -> None:
    """FR-200/244: the upload memo is run-scoped, so three creatives sharing one campaign brief
    upload its photo ONCE — and every job still attaches it.

    Post-D46 a brief's photos are the ONLY files this memo ever holds (the style window it was
    written for is excised, F3), which makes them the only fixture that can still prove the
    memo's once-per-file-per-run rule end to end.
    """
    entries = [make_entry(0, "image"), make_entry(1, "image"), make_entry(2, "image")]
    env = make_env(tmp_path, entries)
    (photo,) = give_brief(env, entries, tmp_path)
    renders = Renders(rule=lambda _self: ok())
    monkeypatch.setattr(render, "run", renders)

    await generate.create(entries, env)

    assert uploads.paths == [photo], "one file, one upload, three creatives"
    assert len(renders.calls) == 3
    assert all(call["refs"].image_urls == [brief_url(photo)] for call in renders.calls)


async def test_a_style_driven_creative_attaches_nothing_and_says_nothing_about_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uploads: SimpleNamespace,
) -> None:
    """D46/FR-17/18: text-to-image is the DEFAULT route, not a degrade.

    A creative wearing a house style and carrying no brief uploads nothing, submits with an
    empty `image_urls`, and is neither tagged nor warned about it — it lost nothing, so there is
    nothing to report. `reference_free` is reserved for the creative that EXPECTED pictures and
    lost every one of them, and a warning here would train the operator to ignore the one line
    that means something.
    """
    entry = make_entry()
    env = make_env(tmp_path, [entry])
    renders = Renders(rule=lambda _self: ok())
    monkeypatch.setattr(render, "run", renders)

    report = await generate.create([entry], env)

    assert uploads.paths == [], "a meta-style ships no pixels (F3)"
    assert renders.calls[0]["refs"].image_urls == []
    record = report.records[entry.asset_id]
    assert DegradationTag.REFERENCE_FREE not in record.degradations
    assert DegradationTag.STYLE_REFS_MISSING not in record.degradations, \
        "the tag survives for old meta.yaml files on disk; nothing emits it any more"
    assert "reference_free" not in env.log.types()


async def test_a_brief_whose_photos_all_vanished_is_the_one_reference_free_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-18's "an input, not a prerequisite", and the loss it is worth a word about.

    The brief shipped two photos and neither could be attached (deleted off disk between the
    plan and the render). The job still goes out on the style's written guidance — a lost
    reference costs a reference, never a creative — but the absence is TAGGED and LOGGED,
    because this creative expected pictures and reached the model without them.
    """
    entry = make_entry()
    env = make_env(tmp_path, [entry])
    for path in give_brief(env, [entry], tmp_path, photos=2):
        path.unlink()
    renders = Renders(rule=lambda _self: ok())
    monkeypatch.setattr(render, "run", renders)

    report = await generate.create([entry], env)

    assert renders.calls[0]["refs"].image_urls == []
    assert DegradationTag.REFERENCE_FREE in report.records[entry.asset_id].degradations
    assert "reference_free" in env.log.types()
    assert report.records[entry.asset_id].status is AssetStatus.SUCCESS, \
        "a reference-free render is a degrade, not a failure"


async def test_every_submission_is_billed_and_gets_one_terminal_ledger_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-203: one `terminal` line per submission — including the moderation-refused attempt that
    was billed and then retried (20 §8's tally-on-submission).

    The refused job carries the brief's photo, because FR-97's remedy is DROPPING references and
    a job that had none has no second submission to make (the settled reading of `and urls`,
    pinned on its own below).
    """
    entry = make_entry()
    env = make_env(tmp_path, [entry])
    give_brief(env, [entry], tmp_path)
    monkeypatch.setattr(render, "run", Renders([refused(), ok(task="kie_retry")]))

    report = await generate.create([entry], env)

    statuses = [line.split(",")[-1] for line in ledger_lines(tmp_path)]
    assert statuses.count("moderation") == 1 and statuses.count("success") == 1
    assert entry.status is PlanEntryStatus.SUCCESS
    record = report.records[entry.asset_id]
    assert DegradationTag.REFS_DROPPED_MODERATION in record.degradations  # FR-97
    assert env.budget.spent_usd == pytest.approx(0.06)  # both attempts billed, failures included


async def test_a_timed_out_job_is_billed_at_zero_not_at_the_full_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `20260813_143420_oyo4` over-report, pinned: a timeout is a KNOWN cost, not a missing one.

    `outcome.cost_usd if outcome.cost_usd else None` could not tell "the provider billed nothing"
    from "the provider reported nothing", so every timed-out job took FR-85's estimated path and
    booked its whole per-job projection as billed. That run reported $1.27 against $0.94 of real
    Kie spend, on rows the summary then labelled `estimated_only` — an inflated total wearing the
    badge that says "trust the estimate here".

    A timed-out job delivered nothing, so it reconciles at a measured 0.0 and its row carries a
    real figure rather than a flagged one.

    Since v2.1.3/D48 the dead attempt is followed by FR-317's one automatic resubmit, so the two
    halves of the money line are asserted separately: the timed-out ATTEMPT bills $0, the
    surviving attempt bills what it really cost, and the run's total is the survivor alone. That
    is precisely the arithmetic that makes a resubmit affordable — the pair costs one render, not
    two — and it only holds while the dead attempt keeps reconciling at zero.
    """
    entry = make_entry()
    env = make_env(tmp_path, [entry])
    monkeypatch.setattr(render, "run", Renders([timed_out(), ok(cost=0.07)]))

    report = await generate.create([entry], env)

    # The per-ATTEMPT half, at the one function that decides it: a timeout reconciles at a
    # measured 0.0, a delivered render at its reported figure, and neither takes FR-85's
    # estimated path (`None`) — which is the branch that booked the whole projection.
    assert generate._billed_usd(timed_out()) == 0.0
    assert generate._billed_usd(ok(cost=0.07)) == pytest.approx(0.07)
    assert [line.split(",")[-1] for line in ledger_lines(tmp_path)[-2:]] == ["timeout", "success"], \
        "FR-203 still names the dead job, and the resubmit is its own terminal line"
    # The RUN half: entry estimate is $0.10, the dead attempt contributed nothing, so the total is
    # the survivor's $0.07 exactly — neither doubled nor rounded up to an estimate.
    assert env.budget.spent_usd == pytest.approx(0.07), "the survivor alone, not two renders"
    (row,) = env.budget.summary([entry]).rows
    assert row.billed_usd == pytest.approx(0.07) and row.estimated_usd == pytest.approx(0.10)
    assert not row.estimated_only, "0.0 here is measured, not assumed — FR-85's badge is a lie now"
    assert entry.status is PlanEntryStatus.SUCCESS, "FR-317 healed it"
    assert report.records[entry.asset_id].actual_cost_usd == pytest.approx(0.07)


async def test_a_job_that_times_out_twice_bills_nothing_at_all_and_fails_honestly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the same discrimination, and FR-317's ceiling: a SECOND timeout is final.

    Both attempts produced nothing, so both reconcile at a measured 0.0 and the run's total spend
    for this creative is exactly zero — no estimate, no `estimated_only` badge, and no third
    attempt. The creative FAILS and keeps its paid caption (FR-74): this is about what the money
    line says, not about laundering the outcome.
    """
    entry = make_entry()
    env = make_env(tmp_path, [entry])
    renders = Renders([timed_out(), timed_out(), ok()])  # the third must stay in the queue
    monkeypatch.setattr(render, "run", renders)

    report = await generate.create([entry], env)

    assert len(renders.calls) == 2, "one resubmit, never two (FR-317)"
    assert env.budget.spent_usd == 0.0, "two jobs that produced nothing billed nothing"
    (row,) = env.budget.summary([entry]).rows
    assert row.billed_usd == 0.0 and not row.estimated_only
    assert entry.status is PlanEntryStatus.FAILED
    assert "timeout" in (entry.skip_reason or "")
    assert report.records[entry.asset_id].actual_cost_usd == 0.0
    assert "image_job_resubmit" in env.log.types()
    assert [line.split(",")[-1] for line in ledger_lines(tmp_path)[-2:]] == ["timeout", "timeout"]


async def test_a_success_that_reports_no_billing_data_still_books_the_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-85 unchanged for everything that is not a timeout — the other half of the discrimination.

    A job that COMPLETED and came back without a `creditsConsumed` field really did work we cannot
    price: the estimate stands and the row says `estimated_only`. Booking that one at 0.0 would
    under-report a delivered render, which is the mirror-image defect of the one above.
    """
    entry = make_entry()
    env = make_env(tmp_path, [entry])
    monkeypatch.setattr(render, "run", Renders([ok(cost=0.0)]))

    await generate.create([entry], env)

    assert env.budget.spent_usd > 0.0, "the estimate stands where no figure was reported"
    (row,) = env.budget.summary([entry]).rows
    assert row.billed_usd > 0.0 and row.estimated_only
    assert entry.status is PlanEntryStatus.SUCCESS


async def test_moderation_retry_declined_by_the_cap_is_a_skipped_budget_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-106c: the retry is the discretionary tail, so a cap with nothing left declines it — and
    the creative fails with the refusal it already paid for, never with an unbudgeted submission."""
    entry = make_entry()
    env = make_env(tmp_path, [entry], cap_usd=0.03)
    give_brief(env, [entry], tmp_path)  # FR-97 only retries a job that HAD references
    monkeypatch.setattr(render, "run", Renders([refused(), ok()]))

    report = await generate.create([entry], env)

    assert entry.status is PlanEntryStatus.FAILED
    assert "skipped_budget" in " ".join(env.log.types())
    assert report.records[entry.asset_id].status is AssetStatus.FAILED
    assert len(ledger_lines(tmp_path)) == 1  # only the refused job was ever submitted


async def test_a_moderation_refusal_on_a_reference_free_job_is_a_straight_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-97's remedy is "resubmit once with every reference removed" — so a job that carried
    NO references has no remedy left, and the refusal is terminal on the first attempt.

    Post-D46 this is the common shape rather than the exotic one: an ordinary style-driven
    creative attaches nothing (F3), and re-sending a byte-identical prompt to the same moderation
    endpoint would buy a second refusal at full price and call it a retry.
    """
    entry = make_entry()
    env = make_env(tmp_path, [entry])  # no brief: nothing to drop
    renders = Renders([refused(), ok(task="kie_never_ordered")])
    monkeypatch.setattr(render, "run", renders)

    report = await generate.create([entry], env)

    assert len(renders.calls) == 1, "a reference-free refusal buys no second submission"
    assert entry.status is PlanEntryStatus.FAILED
    record = report.records[entry.asset_id]
    assert DegradationTag.REFS_DROPPED_MODERATION not in record.degradations
    assert "moderation_retry" not in env.log.types()
    assert "moderation" in (entry.skip_reason or "")


# --------------------------------------------------------------------------- FR-27 / FR-105


async def test_standalone_image_is_vision_checked_re_rendered_once_and_re_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-27/105: a standalone image gets the same treatment a slide and a seed frame get — one
    check, ONE discretionary re-render of a flagged image, one re-check, then it ships. The
    estimator bills `checked_images` for every image (budget.py), so skipping the check would be
    charging for a pass that never ran."""
    entry = make_entry()
    env = make_env(tmp_path, [entry])
    env.config.run.vision_check = True
    env.llm_call = vision(True, False)  # flagged, then clean after the shorter, larger re-render
    renders = Renders([ok(task="kie_first"), ok(task="kie_retry")])
    monkeypatch.setattr(render, "run", renders)

    report = await generate.create([entry], env)

    record = report.records[entry.asset_id]
    assert len(renders.calls) == 2, "the flagged image earns exactly one re-render (NFR-4)"
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED
    assert record.kie_job_ids == ["kie_first", "kie_retry"]
    assert record.actual_cost_usd == pytest.approx(0.06)  # both renders billed at submission
    assert (tmp_path / entry.asset_id / "image.jpg").is_file()  # the re-render REPLACED the file


async def test_vision_check_off_leaves_a_standalone_image_not_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`run.vision_check: false` — one render, one verdict of `not_checked`, no LLM call.

    The default flipped to `true` (v2.1.1), so the flag is set DOWN here rather than assumed: run
    `20260813_143420_oyo4` delivered eight creatives all reading `vision_check_result:
    not_checked` purely because the switch was off, which is a check the estimate priced and the
    run never took. What survives the flip is D3's half of the contract — a check the operator
    declined must cost nothing and produce the honest `not_checked`, never a silent pass.
    """
    entry = make_entry()
    env = make_env(tmp_path, [entry])
    env.config.run.vision_check = False
    env.llm_call = vision(True)  # a call is available; the flag is what declines it
    renders = Renders(rule=lambda _self: ok())
    monkeypatch.setattr(render, "run", renders)

    report = await generate.create([entry], env)

    assert len(renders.calls) == 1
    assert report.records[entry.asset_id].vision_check_result is VisionCheckResult.NOT_CHECKED


# --------------------------------------------------------------------------- 10 §10 disk_full


async def test_disk_full_latches_and_stops_further_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, downloads: SimpleNamespace,
) -> None:
    """10 §10: "that creative fails with reason `disk_full`; further downloads stop rather than
    thrashing a full disk". The latch lives on `Env` and is reported back on `Report`."""
    first, second = make_entry(0), make_entry(1)
    env = make_env(tmp_path, [first, second])
    monkeypatch.setattr(render, "run", Renders(rule=lambda _self: ok()))

    downloads.fail_reason = "disk_full"
    report = await generate.create([first], env)
    assert env.disk_full and report.disk_full
    assert first.status is PlanEntryStatus.FAILED and "disk_full" in (first.skip_reason or "")

    downloads.fail_reason = ""  # the disk did not heal: the latch is what stops the next download
    fetched = len(downloads.fetched)
    later = await generate.create([second], env)

    assert len(downloads.fetched) == fetched  # nothing was downloaded after the latch
    assert later.disk_full and second.status is PlanEntryStatus.FAILED
    assert "downloads stopped" in (second.skip_reason or "")


# --------------------------------------------------------------------------- FR-108 / FR-201


async def test_grace_window_abandons_in_flight_work_with_a_ledger_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-108/201/203: at the stop, in-flight jobs get ONE grace window; what is still running is
    abandoned — entry terminal, folder terminal (never pending meta, NFR-21), taskId in the ledger,
    and the spend it already incurred still counted, because it was billed at submission."""
    monkeypatch.setattr(generate, "GRACE_S", 0.05)
    monkeypatch.setattr(generate, "_HALT_POLL_S", 0.01)
    entry = make_entry()
    env = make_env(tmp_path, [entry])
    on_intent, on_submitted = generate.ledger_hooks(env.ledger)

    async def hang(profile, params, refs, priority) -> RenderOutcome:
        on_intent("tok_hung")  # exactly what the seam does, inside the caller's task (FR-203)
        on_submitted("tok_hung", "kie_hung")
        env.stop.set()  # Ctrl+C lands while this job is in flight
        await asyncio.sleep(30)
        raise AssertionError("the grace window must have cancelled this job")

    monkeypatch.setattr(render, "run", hang)

    report = await asyncio.wait_for(generate.create([entry], env), timeout=5)

    assert entry.status is PlanEntryStatus.ABANDONED
    record = report.records[entry.asset_id]
    assert record.status is AssetStatus.FAILED  # terminal, not pending (NFR-21)
    assert DegradationTag.ABANDONED in record.degradations
    assert read_meta(tmp_path / entry.asset_id)["status"] == "failed"
    assert (tmp_path / entry.asset_id / "SKIP_REASON.txt").is_file()
    assert (tmp_path / entry.asset_id / "caption.txt").is_file()  # the paid copy survives (FR-74)

    last = ledger_lines(tmp_path)[-1]
    assert last.endswith("abandoned") and "kie_hung" in last
    assert env.budget.remaining_usd < env.budget.cap_usd  # billed at submission, never released
    assert "grace_poll" in env.log.types()


async def test_halt_before_create_leaves_every_entry_terminal_and_orders_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-201: the first Ctrl+C stops ORDERING. Entries that never reached a submission are
    abandoned with an honest reason and cost nothing."""
    entry = make_entry()
    env = make_env(tmp_path, [entry])
    env.stop.set()
    renders = Renders()
    monkeypatch.setattr(render, "run", renders)

    report = await generate.create([entry], env)

    assert renders.calls == [] and env.budget.spent_usd == 0.0
    assert entry.status is PlanEntryStatus.ABANDONED
    assert DegradationTag.ABANDONED in report.records[entry.asset_id].degradations
    assert not (tmp_path / "LEDGER.txt").exists() or ledger_lines(tmp_path) == []


async def test_expired_deadline_halts_ordering_exactly_like_ctrl_c(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-108's deadline and FR-201's interrupt reach `generate` through one flag, `env.halted`,
    measured on the monotonic clock (`util.Deadline`, FR-243)."""
    from hypesocials.util import Deadline

    entry = make_entry()
    env = make_env(tmp_path, [entry], deadline=Deadline(seconds=0.0))
    renders = Renders()
    monkeypatch.setattr(render, "run", renders)

    await generate.create([entry], env)

    assert env.halted and renders.calls == []
    assert entry.status is PlanEntryStatus.ABANDONED


def test_partial_deck_ships_but_the_run_exits_partial(tmp_path: Path) -> None:
    """FR-202: code 1 is "completed with at least one creative skipped, failed, budget-trimmed or
    abandoned". A carousel that ships four of six slides is `SUCCESS` + `incomplete` + a
    `skip_reason` naming the missing ones (FR-20, 10 §10) — delivered, but a loss, so exit 1."""
    from hypesocials.runner import EXIT_OK, EXIT_PARTIAL, decide_exit_code

    whole = make_entry(0, "carousel", status=PlanEntryStatus.SUCCESS)
    partial = make_entry(1, "carousel", status=PlanEntryStatus.SUCCESS,
                         skip_reason="slide 5: provider_fail; slide 6: provider_fail")

    assert decide_exit_code([whole]) == EXIT_OK
    assert decide_exit_code([whole, partial]) == EXIT_PARTIAL


# --------------------------------------------------------------------------- FR-167


async def test_kie_out_of_credits_latches_and_skips_every_later_creative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-167: 402 is a whole-run condition. The first creative releases its reservation (nothing
    was submitted), latches the flag, and every later creative is skipped with the top-up message
    instead of re-proving a certainty."""
    first, second = make_entry(0), make_entry(1)
    env = make_env(tmp_path, [first, second])
    renders = Renders([render.KieOutOfCredits("HTTP 402"), ok()])
    monkeypatch.setattr(render, "run", renders)

    await generate.create([first], env)
    assert env.credits_exhausted and env.budget.spent_usd == 0.0  # released: nothing was submitted
    assert "kie_credits_exhausted" in (first.skip_reason or "")

    report = await generate.create([second], env)

    assert len(renders.calls) == 1  # the latch, not a second 402
    assert second.status is PlanEntryStatus.FAILED
    assert report.records[second.asset_id].status is AssetStatus.FAILED


# ------------------------------- v2.1.4: honest meta for a standalone image (glz0 audit R2/R4)


def _png_bytes(width: int, height: int) -> bytes:
    """A PNG header of these dimensions — the bytes `generate.pixels` measures.

    Hand-assembled (IHDR is fixed-layout and its CRC is not read by anything here) so this file
    stays free of an image library: the point is the HEADER, and the parser under test reads
    nothing past byte 24.
    """
    ihdr = b"IHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + len(ihdr[4:]).to_bytes(4, "big") + ihdr
            + b"\x00\x00\x00\x00" + b"IEND")


async def test_a_reference_free_image_records_the_route_it_actually_took(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-270/FR-241 (audit R2): `model_ids` names the route this creative used, not both halves.

    A style is words (D46), so an ordinary image submits with no references at all and goes to the
    text-to-image route — which is what `models.image` names.
    """
    entry = make_entry()
    env = make_env(tmp_path, [entry])
    monkeypatch.setattr(render, "run", Renders(rule=lambda _self: ok()))

    report = await generate.create([entry], env)

    assert report.records[entry.asset_id].model_ids == [env.config.models.image,
                                                        env.config.models.image_profile]


async def test_an_image_carrying_a_briefs_photo_records_the_image_to_image_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of FR-241, and the one glz0 got wrong on every reference-bearing render.

    A campaign brief's own product photo is a reference, so the job goes to the image-to-image
    route (`models.image_edit`). Recording `models.image` for it — as every creative in that run
    did — claims a route the job never touched, in the document the operator audits a render with.
    """
    entry = make_entry()
    env = make_env(tmp_path, [entry])
    give_brief(env, [entry], tmp_path)
    monkeypatch.setattr(render, "run", Renders(rule=lambda _self: ok()))

    report = await generate.create([entry], env)

    assert report.records[entry.asset_id].model_ids == [env.config.models.image_edit,
                                                        env.config.models.image_profile]


async def test_an_image_records_the_pixel_size_it_really_got_and_warns_on_the_ratio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, downloads: SimpleNamespace,
) -> None:
    """FR-98 (audit R4): `native_size_rendered` is measured off the delivered file, not restated.

    glz0 recorded `native_size_rendered: '1:1'` for a picture that came back 1536x1024. The field
    is documented as "what came back", the gallery prints it as `ratio 1:1 -> …`, and a Phase-2
    publisher will read it as fact — so it is now the file's own header, with one warning when the
    provider's answer is more than 2% off the shape that was ordered. Nothing re-renders.
    """
    async def _wide(url: str) -> bytes:
        return _png_bytes(1536, 1024)

    monkeypatch.setattr(packager, "_download", _wide)
    entry = make_entry()
    env = make_env(tmp_path, [entry])
    monkeypatch.setattr(render, "run", Renders(rule=lambda _self: ok()))

    report = await generate.create([entry], env)

    record = report.records[entry.asset_id]
    assert record.native_size_rendered == "1536x1024 (3:2)"
    assert record.aspect_ratio_requested == "1:1", "what was ASKED for stands beside it"
    assert "aspect_mismatch" in env.log.types()


async def test_a_vision_re_render_is_measured_on_the_file_that_actually_ships(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The re-render REPLACES the delivered file, so it is the second picture that gets measured.

    The first download is square and the second is not; recording the first would describe a file
    that is no longer on disk, which is the same class of untruth as recording the requested ratio.
    """
    sizes = [(1024, 1024), (1536, 1024)]
    seen: list[str] = []

    async def _two(url: str) -> bytes:
        seen.append(url)
        return _png_bytes(*sizes[min(len(seen) - 1, 1)])

    monkeypatch.setattr(packager, "_download", _two)
    entry = make_entry()
    env = make_env(tmp_path, [entry])
    env.config.run.vision_check = True
    env.llm_call = vision(True, False)  # flagged, then clean after the one re-render
    monkeypatch.setattr(render, "run", Renders([ok(task="kie_first"), ok(task="kie_retry")]))

    report = await generate.create([entry], env)

    record = report.records[entry.asset_id]
    assert record.vision_check_result is VisionCheckResult.RETRIED_PASSED
    assert record.native_size_rendered == "1536x1024 (3:2)", "the SECOND file is the one on disk"
