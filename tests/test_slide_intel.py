"""`hypesocials.sources.slide_intel` — reading the slides a carousel was sourced FROM (FR-306).

This stage is the one that costs money on behalf of fidelity: it downloads an assigned source
post's slides into the run folder and spends ONE analysis-role call transcribing and describing
them, so our slide *i* can carry their slide *i*'s words in our own style. Everything this suite
pins is a rule that only shows up when something goes wrong on a paid run:

* **one download per slide, one call per post** — the same local bytes feed the vision call and
  the offline gallery, and an eight-slide deck never becomes eight calls (D46 §0.13/FR-306);
* **Virlo's panel text wins, verbatim** — a transcription fills empty slots only, and is kept
  beside the panel as provenance rather than replacing it (§0.11);
* **fail-open, every path** (§0.14c) — a raising or degraded call leaves the Virlo panels
  standing under `vision_unavailable`, a 404 costs one slide its image and nothing else, and
  fewer answers than slides align by position with the gaps simply absent. Nothing raises out of
  `enrich()`, because by the time it runs the operator has already approved the spend;
* **the hard boundary** — nothing here may reach the render upload seam (D41 as amended by D46).

Offline and deterministic: the LLM is a stub honouring the pinned `StructuredCall` shape, the
packager's download client is monkeypatched to serve local bytes, and every file lands under
`tmp_path`. No network, no key, no write into the repo's `output/` or `logs/`.

The posts are real `models.SourcePost` instances carrying the slideshow fields the adapter fills
(`panel_texts` index-aligned to `panel_count`, `image_urls` in panel order), so a change to that
shape fails here rather than at the first paid run.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

from hypesocials import prompts_engine as pe
from hypesocials.config import Config
from hypesocials.models import ParsedResult, SourcePost
from hypesocials.outputs import packager
from hypesocials.sources import slide_intel

SLIDE_BYTES = b"\xff\xd8\xff\xe0-not-a-real-jpeg-but-bytes-are-bytes"


# --------------------------------------------------------------------------- builders


PUBLISHED = datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc)


def _post(post_id: str = "p1", *, slides: int = 3, panels: tuple[str, ...] = ()) -> SourcePost:
    """One assigned carousel's source post, in the shape the Virlo adapter hands over (FR-293)."""
    return SourcePost(
        post_id=post_id, url=f"https://virlo.test/post/{post_id}", author="@creator",
        caption="original caption", views=1_200_000, is_slideshow=True, published_at=PUBLISHED,
        panel_texts=list(panels), panel_count=slides,
        image_urls=[f"https://cdn.virlo.test/{post_id}/slide{n}.jpg"
                    for n in range(1, slides + 1)])


class Vision:
    """A `models.StructuredCall` that answers with crafted slide rows and remembers every call.

    Honours the pinned protocol shape — `async (role, messages, json_schema, images=None)` — so a
    drift in `llm.structured_call`'s signature fails here rather than in production.
    """

    def __init__(self, *rows: dict[str, Any], raises: BaseException | None = None,
                 degraded: bool = False, reason: str = "") -> None:
        self.rows = list(rows)
        self.raises = raises
        self.degraded = degraded
        self.reason = reason
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, role: str, messages: list[dict[str, Any]],
                       json_schema: dict[str, Any], images: list[bytes] | None = None):
        self.calls.append({"role": role, "messages": messages, "schema": json_schema,
                           "images": list(images or [])})
        if self.raises is not None:
            raise self.raises
        return ParsedResult(parsed={"slides": self.rows}, raw_text="{}", cost_usd=0.02,
                            prompt_tokens=900, completion_tokens=300, degraded=self.degraded,
                            reason=self.reason)


class Log:
    """The `.warn(event_type, message, **data)` surface `LogWriter` exposes, recorded."""

    def __init__(self) -> None:
        self.warnings: list[tuple[str, str, dict[str, Any]]] = []

    def warn(self, event_type: str, message: str = "", **data: Any) -> str:
        self.warnings.append((event_type, message, data))
        return event_type

    def keys(self) -> list[str]:
        return [event_type for event_type, _, _ in self.warnings]


def _answer(slot: int, text: str = "", brief: str = "a brief", marks: tuple[str, ...] = (),
            chrome: str = "") -> dict:
    """One row of the wire shape the module parses (`_SCHEMA`'s `slides` items).

    `chrome_text` is a first-class field of that shape, not an extra: the creator's @handles, URLs,
    watermarks and page counters are transcribed AWAY from the slide's words, so they can never
    reach the panel text that §0.12 safety would then reject wholesale.
    """
    return {"slide": slot, "onimage_text": text, "chrome_text": chrome, "visual_brief": brief,
            "brand_marks": list(marks)}


@pytest.fixture
def downloads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every URL the packager was asked to fetch, in order — and never a real request.

    Patching `packager._download` rather than `store_source` keeps the atomic write, the file
    naming and the on-disk dedupe under test; only the socket is replaced.
    """
    fetched: list[str] = []

    async def _fake_download(url: str) -> bytes:
        fetched.append(url)
        if url.endswith("slide2.jpg") and getattr(_fake_download, "fail_second", False):
            raise packager.PackagingError("download failed: 404 Not Found",
                                          reason="download_failed")
        return SLIDE_BYTES + url.encode()

    monkeypatch.setattr(packager, "_download", _fake_download)
    return fetched


def _fail_slide_two(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flip the fixture's one unreachable slide on (a 404 on the source CDN, §0.14c case b)."""
    monkeypatch.setattr(packager._download, "fail_second", True, raising=False)


def _engine() -> pe.PromptEngine:
    """The real engine over the real `prompts/` folder — this also proves the new template loads."""
    return pe.PromptEngine()


def _read_yaml(run_dir: Path, post_id: str = "p1") -> dict[str, Any]:
    path = run_dir / packager.SOURCE_DIR / post_id / packager.SOURCE_META_FILE
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- happy path


async def test_each_slide_downloads_once_one_call_reads_them_all_and_source_yaml_records_it(
    tmp_path: Path, downloads: list[str]
) -> None:
    """The whole contract on the path where nothing goes wrong (FR-306, FR-71)."""
    post = _post(panels=("Panel one", "", ""))
    vision = Vision(_answer(1, "Panel one as seen", "hero image, heading centred"),
                    _answer(2, "Druhý panel\nna dvou řádcích", "two-column table, four rows"),
                    _answer(3, "Third", "line chart, three series, rising", marks=("TikTok mark",)))
    log = Log()

    intel = await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                     cfg=Config(), log=log)

    assert list(intel) == ["p1"]
    report = intel["p1"]
    assert report.status == slide_intel.STATUS_OK
    # one download per slide, and exactly one question for the whole deck
    assert downloads == post.image_urls
    assert len(vision.calls) == 1
    assert vision.calls[0]["role"] == slide_intel.SLIDE_INTEL_ROLE == "analysis"
    assert len(vision.calls[0]["images"]) == 3
    assert vision.calls[0]["schema"]["name"] == "slide_intelligence"
    # the bytes are on disk, named by source position, and readable offline
    for position in (1, 2, 3):
        stored = tmp_path / "source" / "p1" / f"slide_{position:02d}.jpg"
        assert stored.is_file() and stored.read_bytes().startswith(SLIDE_BYTES)
        assert report.relative_image(position) == f"source/p1/slide_{position:02d}.jpg"
    # merge: Virlo's panel where it exists, the transcription where it does not
    assert report.panel_texts == ["Panel one", "Druhý panel\nna dvou řádcích", "Third"]
    assert [slide.text_source for slide in report.slides] == [
        slide_intel.TEXT_SOURCE_VIRLO, slide_intel.TEXT_SOURCE_VISION,
        slide_intel.TEXT_SOURCE_VISION]
    assert report.slides[2].brand_marks == ["TikTok mark"]
    assert report.usable_panels == 3
    assert report.cost_usd == 0.02 and report.prompt_tokens == 900
    assert not log.warnings, f"a clean read warned about nothing: {log.keys()}"

    stored = _read_yaml(tmp_path)
    assert stored["post_id"] == "p1"
    assert stored["url"] == "https://virlo.test/post/p1"
    assert stored["author"] == "@creator"
    assert stored["views"] == 1_200_000
    assert stored["published_at"] == "2026-08-01T09:30:00+00:00"  # ISO strings, not datetimes
    assert stored["caption"] == "original caption"
    assert stored["panel_count"] == 3
    assert stored["vision"] == {"model_role": "analysis",
                                "model_id": Config().models.analysis,
                                "status": slide_intel.STATUS_OK, "reason": ""}
    assert stored["slides"][0] == {
        "position": 1, "virlo_text": "Panel one", "vision_text": "Panel one as seen",
        # v2.2.0 provenance: the unrepaired reading (empty — nothing was repaired here) and the
        # truncation FLAG, which is contract data for the brief critic and never a blanking licence.
        "vision_text_original": "", "truncation_suspect": False,
        "chrome_text": "", "visual_brief": "hero image, heading centred", "brand_marks": [],
        "vision_transcribed": False, "image_file": "slide_01.jpg"}
    # the transcription keeps the line break it was given — verbatim means the shape too
    assert stored["slides"][1]["vision_text"] == "Druhý panel\nna dvou řádcích"
    assert stored["slides"][1]["vision_transcribed"] is True


async def test_the_same_post_bound_by_two_siblings_is_analysed_once(
    tmp_path: Path, downloads: list[str]
) -> None:
    """Two carousels on one slideshow cost one download set and one call (D46 §0.13 dedupe)."""
    post = _post(slides=2, panels=("", ""))
    vision = Vision(_answer(1, "One"), _answer(2, "Two"))

    intel = await slide_intel.enrich([post, post], run_dir=tmp_path, call=vision,
                                     engine=_engine(), cfg=Config(), log=Log())

    assert list(intel) == ["p1"]
    assert downloads == post.image_urls  # two, not four
    assert len(vision.calls) == 1


# --------------------------------------------------------------------------- merge precedence


async def test_a_virlo_panel_is_never_overwritten_by_the_transcription(
    tmp_path: Path, downloads: list[str]
) -> None:
    """§0.11: the panel Virlo gave us IS the verbatim source of record; vision only fills gaps.

    The transcription is still recorded — `source.yaml` shows both, so a mis-transcription is
    visible rather than silently merged away — but it never becomes the text that gets rendered.
    """
    post = _post(slides=2, panels=("Původní panel, verbatim", ""))
    vision = Vision(_answer(1, "A DIFFERENT reading of slide one"), _answer(2, "Slide two words"))

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=Log()))["p1"]

    assert report.slides[0].text == "Původní panel, verbatim"
    assert report.slides[0].vision_text == "A DIFFERENT reading of slide one"
    assert report.slides[0].text_source == slide_intel.TEXT_SOURCE_VIRLO
    assert report.slides[1].text == "Slide two words"
    assert report.degradations == [slide_intel.TEXT_SOURCE_VISION]  # slot 2 only
    assert _read_yaml(tmp_path)["slides"][0]["vision_transcribed"] is False


# --------------------------------------------------------------------------- creator chrome


async def test_creator_chrome_lands_in_its_own_field_and_never_in_the_slides_words(
    tmp_path: Path, downloads: list[str]
) -> None:
    """The bug this field exists for: a footer watermark used to blank the entire panel.

    Every slide of the deck that motivated this ended "@theromanknox | skool.com/knox | 3/6 |
    swipe". Transcribed into `onimage_text`, each panel then carried a handle and a URL, §0.12
    safety rejected all of them, and a real carousel shipped 100% wordless. Split at the source,
    the words stand on their own and the chrome is still recorded — provenance keeps it, pixels
    never see it.
    """
    post = _post(panels=("", "", ""))
    chrome = "@theromanknox | skool.com/knox | 3/6 | swipe"
    vision = Vision(_answer(1, "Stop guessing", "hero heading", chrome=chrome),
                    _answer(2, "Ship it weekly", "two-column list", chrome="@theromanknox 2/6"),
                    _answer(3, "", "closing card, logo only", chrome="follow for more"))
    log = Log()

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=log))["p1"]

    assert report.panel_texts == ["Stop guessing", "Ship it weekly", ""]
    assert [slide.chrome_text for slide in report.slides] == [
        chrome, "@theromanknox 2/6", "follow for more"]
    # the words the deck will quote carry no handle, no domain, no counter, no swipe cue
    for panel in report.panel_texts:
        assert "@" not in panel and "skool.com" not in panel and "swipe" not in panel
    assert report.usable_panels == 2  # the chrome-only slide is blank, not "full of text"

    stored = _read_yaml(tmp_path)
    assert [slide["chrome_text"] for slide in stored["slides"]] == [
        chrome, "@theromanknox 2/6", "follow for more"]
    assert stored["slides"][0]["vision_text"] == "Stop guessing"
    assert stored["slides"][2]["vision_text"] == ""


async def test_a_row_without_chrome_text_still_applies(
    tmp_path: Path, downloads: list[str]
) -> None:
    """Fail-open on the field (§0.14c): a row that names no chrome is a slide with no chrome.

    An older model, a cached answer or a row that simply omitted the key must never cost the slide
    its transcription, its brief or its marks.
    """
    post = _post(slides=2, panels=("", ""))
    legacy = {"slide": 1, "onimage_text": "Words survive", "visual_brief": "a brief",
              "brand_marks": ["TikTok watermark"]}
    vision = Vision(legacy, _answer(2, "Second", "second brief", chrome="@handle"))
    log = Log()

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=log))["p1"]

    assert report.status == slide_intel.STATUS_OK
    assert report.slides[0].chrome_text == ""
    assert report.slides[0].text == "Words survive"
    assert report.slides[0].visual_brief == "a brief"
    assert report.slides[0].brand_marks == ["TikTok watermark"]
    assert report.slides[1].chrome_text == "@handle"
    assert not log.warnings, f"a missing optional field is not a degrade: {log.keys()}"
    assert _read_yaml(tmp_path)["slides"][0]["chrome_text"] == ""


async def test_chrome_never_enters_the_virlo_over_vision_merge(
    tmp_path: Path, downloads: list[str]
) -> None:
    """The merge rule is untouched by the split: `text` is still `virlo_text or vision_text`.

    Chrome sits beside both and joins neither — a Virlo panel still wins outright, an empty panel
    is still filled by the transcription alone, and a slot whose only reading was chrome is still
    a blank slot with `text_source == none`.
    """
    post = _post(panels=("Původní panel", "", ""))
    vision = Vision(_answer(1, "re-read of slide one", chrome="@creator"),
                    _answer(2, "transcribed words", chrome="linkinbio.com"),
                    _answer(3, "", chrome="4/6 swipe"))

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=Log()))["p1"]

    assert report.panel_texts == ["Původní panel", "transcribed words", ""]
    assert [slide.text_source for slide in report.slides] == [
        slide_intel.TEXT_SOURCE_VIRLO, slide_intel.TEXT_SOURCE_VISION,
        slide_intel.TEXT_SOURCE_NONE]
    assert report.slides[0].chrome_text == "@creator"  # recorded even where Virlo's panel wins
    assert report.degradations == [slide_intel.TEXT_SOURCE_VISION]


# --------------------------------------------------------------------------- fail-open matrix


@pytest.mark.parametrize("vision, cause", [
    (Vision(raises=RuntimeError("provider exploded")), "raised RuntimeError"),
    (Vision(degraded=True, reason="truncated after 12000 tokens"), "truncated"),
])
async def test_a_failed_analysis_keeps_the_panels_and_never_raises(
    tmp_path: Path, downloads: list[str], vision: Vision, cause: str
) -> None:
    """§0.14c case (a): the deck renders from Virlo panel text alone, tagged `vision_unavailable`."""
    post = _post(slides=2, panels=("Panel one", "Panel two"))
    log = Log()

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=log))["p1"]

    assert report.status == slide_intel.STATUS_UNAVAILABLE
    assert cause in report.reason
    assert report.panel_texts == ["Panel one", "Panel two"]  # nothing was lost
    assert report.degradations == [slide_intel.STATUS_UNAVAILABLE]
    assert [slide.visual_brief for slide in report.slides] == ["", ""]
    assert log.keys() == ["slide_intel_unavailable"]
    # the slides still landed on disk — the gallery's provenance strip does not depend on vision
    assert downloads == post.image_urls
    stored = _read_yaml(tmp_path)
    assert stored["vision"]["status"] == slide_intel.STATUS_UNAVAILABLE
    assert stored["slides"][0]["image_file"] == "slide_01.jpg"


async def test_one_unreachable_slide_costs_that_slide_alone(
    tmp_path: Path, downloads: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """§0.14c case (b): a 404 leaves `image_file: null` and no brief; its siblings are unaffected.

    The alignment is the sharp edge here — slide 2 was never attached, so the model's second
    answer belongs to source position 3, not to position 2.
    """
    _fail_slide_two(monkeypatch)
    post = _post(panels=("", "Panel two survived", ""))
    vision = Vision(_answer(1, "One", "first brief"), _answer(2, "Three", "third brief"))
    log = Log()

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=log))["p1"]

    assert report.status == slide_intel.STATUS_OK  # one lost image is not a failed read
    assert len(vision.calls[0]["images"]) == 2
    assert [slide.image_file for slide in report.slides] == ["slide_01.jpg", None, "slide_03.jpg"]
    assert [slide.visual_brief for slide in report.slides] == ["first brief", "", "third brief"]
    assert report.panel_texts == ["One", "Panel two survived", "Three"]
    assert report.relative_image(2) is None
    assert "slide_intel_download_failed" in log.keys()
    stored = _read_yaml(tmp_path)
    assert stored["slides"][1]["image_file"] is None
    assert stored["slides"][1]["visual_brief"] == ""


async def test_fewer_answers_than_slides_align_by_position_and_the_gap_stays_empty(
    tmp_path: Path, downloads: list[str]
) -> None:
    """§0.14c case (c): a short answer never shifts the deck — missing means absent."""
    post = _post(panels=("", "", ""))
    vision = Vision(_answer(1, "One", "first brief"), _answer(3, "Three", "third brief"))
    log = Log()

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=log))["p1"]

    assert [slide.visual_brief for slide in report.slides] == ["first brief", "", "third brief"]
    assert report.panel_texts == ["One", "", "Three"]
    assert report.usable_panels == 2
    assert log.keys() == ["slide_intel_brief_missing"]
    assert log.warnings[0][2]["slides"] == [2]


async def test_a_runaway_slide_list_is_capped_before_it_becomes_money(
    tmp_path: Path, downloads: list[str]
) -> None:
    """`image_urls` is source-controlled, and every attachment is billed (rule 7).

    The cap bounds the downloads and the attachments; it never shortens the DECK — slides past it
    keep their position and their Virlo panel text, so the panel mapping stays index-aligned.
    """
    cap = slide_intel._MAX_ANALYSED_SLIDES
    post = _post(slides=cap + 6, panels=tuple(f"panel {n}" for n in range(1, cap + 7)))
    vision = Vision(*[_answer(n, f"slide {n}") for n in range(1, cap + 1)])
    log = Log()

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=log))["p1"]

    assert len(downloads) == cap
    assert len(vision.calls[0]["images"]) == cap
    assert len(report.slides) == cap + 6
    assert report.slides[-1].image_file is None
    assert report.slides[-1].text == f"panel {cap + 6}"
    assert "slide_intel_slides_capped" in log.keys()


async def test_a_post_with_no_slides_at_all_degrades_instead_of_calling(
    tmp_path: Path, downloads: list[str]
) -> None:
    """No panels, no images: there is nothing to read, so nothing is paid for."""
    post = _post(slides=0, panels=())
    vision = Vision()
    log = Log()

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=log))["p1"]

    assert report.status == slide_intel.STATUS_UNAVAILABLE
    assert report.slides == []
    assert vision.calls == [] and downloads == []
    assert log.keys() == ["slide_intel_no_slides"]
    assert _read_yaml(tmp_path)["panel_count"] == 0


async def test_without_a_model_call_the_slides_are_still_stored_for_the_gallery(
    tmp_path: Path, downloads: list[str]
) -> None:
    """`call=None` is the $0 path: downloads and provenance happen, no LLM spend is incurred."""
    post = _post(slides=2, panels=("Panel one", "Panel two"))

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=None, engine=_engine(),
                                       cfg=Config(), log=Log()))["p1"]

    assert report.status == slide_intel.STATUS_DISABLED
    assert report.cost_usd == 0.0
    assert downloads == post.image_urls
    assert _read_yaml(tmp_path)["vision"]["status"] == slide_intel.STATUS_DISABLED


async def test_no_posts_is_not_a_run_folder_write(tmp_path: Path, downloads: list[str]) -> None:
    """Reels-and-images runs call this with an empty list; it must be a no-op, not a folder."""
    assert await slide_intel.enrich([], run_dir=tmp_path, call=Vision(), engine=_engine(),
                                    cfg=Config(), log=Log()) == {}
    assert not (tmp_path / packager.SOURCE_DIR).exists()


# --------------------------------------------------------------------------- the hard boundary


def test_this_stage_can_never_hand_a_virlo_byte_to_the_renderer() -> None:
    """D41 as amended by D46: Virlo bytes are analysis-and-display only, structurally.

    A grep, deliberately: the boundary is that this module has no code path to the upload seam at
    all, and the cheapest way to keep it that way is to fail the moment someone imports one.
    `render.upload_file` is the named carve-out boundary (§0.13), and `generate/refs.py` is the
    other door — neither may appear here.
    """
    source = Path(slide_intel.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    code = code.split('"""', 2)[-1]  # drop the module docstring, which NAMES the forbidden seam
    for forbidden in ("upload_file", "hypesocials.render", "hypesocials.generate",
                      "from .render", "from .generate"):
        assert forbidden not in code, f"slide_intel reaches the render seam: {forbidden!r}"


def test_the_question_template_is_a_real_file_that_renders_with_no_placeholders() -> None:
    """FR-174/181: the question lives in `prompts/`, not in the module, and needs no context."""
    text = _engine().render(slide_intel.QUESTION_TEMPLATE, {})
    assert pe._names(text) == []
    assert "verbatim" in text.lower()
    assert "english" in text.lower()  # the visual brief's language rule (§0.11)
    assert '"slides"' in text and '"onimage_text"' in text and '"brand_marks"' in text
    # the chrome split is instruction, not post-processing: if the question stops asking for it,
    # handles and counters come back inside the words and §0.12 blanks the panels again
    assert '"chrome_text"' in text
    lowered = text.lower()
    assert all(cue in lowered for cue in ("@handle", "url", "counter", "swipe"))
    assert set(slide_intel._SLIDE["required"]) == {
        "slide", "onimage_text", "chrome_text", "visual_brief", "brand_marks",
        "mark_boxes"}
    # v2.2.0: every mark row must say WHAT it is, and only `tool` is ever croppable. Required of
    # the model (strict mode requires every declared property) and optional of the parser, so the
    # schema could land a wave before the question learns to fill it.
    marks = slide_intel._SLIDE["properties"]["mark_boxes"]["items"]
    assert set(marks["required"]) == {"name", "slide", "box", "kind"}
    assert marks["properties"]["kind"]["enum"] == list(slide_intel.MARK_KINDS) == [
        "tool", "apparel", "chrome", "other"]


def test_a_source_controlled_post_id_cannot_escape_the_run_folder() -> None:
    """The store's folder segment is source-controlled text becoming a Windows path (FR-71)."""
    run = Path("C:/runs/20260813_101010_ab12")
    assert packager.source_dir(run, "7412998877").name == "7412998877"
    assert packager.source_dir(run, "../../etc").parent == run / packager.SOURCE_DIR
    assert ".." not in packager.source_dir(run, "../../etc").name
    assert packager.source_dir(run, "").name == "unknown-post"
    long_id = packager.source_dir(run, "x" * 40 + "." * 40).name
    assert len(long_id) <= 64 and not long_id.endswith(".")  # Windows eats a trailing dot
    assert packager.source_slide_name(7, "https://cdn.test/a/b.png?sig=1") == "slide_07.png"
    assert packager.source_slide_name(1, "https://cdn.test/a/b") == "slide_01.jpg"


# ---------------------------------------------------- D-D: the source deck's counting convention


@pytest.mark.parametrize(
    ("chrome", "panels", "count", "expected"),
    [
        # The padded convention, kept: `01 / 06` re-bases as `03 / 08`, spacing and zeros intact.
        ((["@knox | skool.com/knox | 01 / 06 | swipe"], ["@knox | 02 / 06"], ["@knox | 03 / 06"]),
         ("a", "b", "c"), 6, "03 / 08"),
        # The bare convention: no padding, no spaces around the slash.
        ((["3/6"], ["4/6"], []), ("a", "b", "c"), 6, "3/8"),
        # A worded separator is a convention too, and the spacing around it is part of it.
        (([], ["2 of 7"], []), ("a", "b", "c"), 7, "3 of 8"),
        # The prefix style: typeset into the panel's own words, and it names no total.
        (([], [], []), ("// 01 THE HOOK", "// 02 THE TURN", "// 03 THE CLOSE"), 3, "// 03"),
        # Rejected: `24/7` is a claim about opening hours. Its denominator is not the deck, and its
        # numerator is not the slide — and 24 > 7 makes it not a counter at all.
        ((["open 24/7"], ["support 24/7"], []), ("a", "b", "c"), 3, None),
        # Rejected: a date is a RUN of numbers, and one pair pulled out of it is not a counter.
        ((["posted 12/08/2026"], ["12/08/2026"], []), ("a", "b"), 2, None),
        # Rejected: nothing counted anywhere. The absence is the common case, and the safe one.
        ((["@knox | skool.com/knox"], ["swipe →"], []), ("a", "b", "c"), 3, None),
        # Rejected: ONE positional-looking token, on one slide. `1/2 cup` in a recipe deck is not
        # a page number, and a single hit is exactly what the two-slide rule exists to refuse.
        ((["1/2 cup of oats"], [], []), ("a", "b", "c"), 4, None),
    ])
def test_detect_counter_accepts_a_real_convention_and_refuses_a_lookalike(
    chrome: tuple[list[str], ...], panels: tuple[str, ...], count: int, expected: str | None,
) -> None:
    """D-D: a badge is re-based onto OUR deck in the SOURCE's hand, or there is no badge.

    The accept rules are deliberately narrow — a denominator that equals the deck's own length, or
    the same badge stating its own position on two slides — because the two failure modes are not
    symmetric. A missed counter renders a deck without a page badge and says so in the prompt; a
    false one prints "24/7" on every slide of a creative the operator paid for.
    """
    spec = slide_intel.detect_counter(chrome, panels, count)

    if expected is None:
        assert spec is None
        return
    assert spec is not None
    assert spec.format(3, 8) == expected


def test_a_counter_is_re_based_onto_our_deck_never_copied_from_theirs() -> None:
    """§0.4′ truncates a nine-panel source onto a five-slide deck — the badge must follow.

    Copying the source's own numbers would print "3/9" on slide 3 of 5 and tell the reader four
    slides are missing.
    """
    spec = slide_intel.detect_counter([["01 / 09"], ["02 / 09"]], ("a", "b"), 9)

    assert spec is not None
    assert [spec.format(n, 5) for n in (1, 5)] == ["01 / 05", "05 / 05"]
    assert spec.format(0, 5) == "" and spec.format(1, 0) == "", "a nonsense request has no badge"


def test_the_counter_spec_is_frozen_so_one_deck_counts_in_one_hand() -> None:
    """It is detected once per deck and read on every slide; a mutable one is a deck that drifts."""
    spec = slide_intel.CounterSpec(pad=2, separator=" / ", total_pad=2)

    with pytest.raises(Exception):
        spec.pad = 3  # type: ignore[misc]
    assert spec == slide_intel.CounterSpec(pad=2, separator=" / ", total_pad=2)


# ------------------------------------------- FR-313 amended (v2.1.3/D48): the OFFSET accept rules
#
# Rules 1 and 2 above answer "the denominator IS the deck" and "two slides state their own
# position". Both miss the shape a real deck actually has: an unnumbered cover. Run
# `20260813_161444_r9pz` shipped a badge-less deck because its seven panels carried `1/ 6` … `6/ 6`
# on positions 2–7 — every number one lower than its slide, and a denominator one lower than the
# deck. Rule 3 accepts that when the offset is CONSTANT and the denominator equals
# `panel_count − offset`; rule 4 accepts a constant offset alone, and only when nothing in the
# deck contradicts it. Both still lose the tie to `None`.


@pytest.mark.parametrize(
    ("chrome", "count", "expected"),
    [
        # (a) The live-corpus shape, exactly: seven panels, one unnumbered cover, `1/ 6` … `6/ 6`
        # on positions 2–7. Offset 1 everywhere, denominator 6 == 7 − 1. The separator is `"/ "`
        # — the space after the slash is part of the source's hand and is carried, not normalised.
        (([], ["1/ 6"], ["2/ 6"], ["3/ 6"], ["4/ 6"], ["5/ 6"], ["6/ 6"]), 7, "3/ 8"),
        # (b) TWO unnumbered covers (a title card and a hook card, the common eight-panel build):
        # offset 2 everywhere, denominator 6 == 8 − 2.
        (([], [], ["1/6"], ["2/6"], ["3/6"], ["4/6"], ["5/6"], ["6/6"]), 8, "3/8"),
        # (c) Rule 4, uncorroborated: the badges agree on an offset of 1 but their denominator (9)
        # cannot be checked against this deck (Virlo returned five panels of a nine-panel post).
        # Weaker evidence, so it is the LAST rule — and it is still evidence.
        (([], ["1/9"], ["2/9"]), 5, "3/8"),
        # (d) Contradicting offsets kill it: `1/6` on panel 2 (offset 1) and `3/6` on panel 3
        # (offset 0). At least one of those is not counting this deck, so neither is believed.
        (([], ["1/6"], ["3/6"]), 7, None),
        # (e) A lone candidate is never an offset. One badge is a coincidence — a statistic, a
        # recipe fraction — and the two-slide floor is what refuses it under every rule.
        (([], ["1/6"], []), 7, None),
    ])
def test_detect_counter_reads_a_deck_whose_badges_start_after_its_cover(
    chrome: tuple[list[str], ...], count: int, expected: str | None,
) -> None:
    """FR-313 amended: an unnumbered cover shifts every badge by a constant, and that is still a
    counted deck.

    The asymmetry from the v2.1.2 rules is unchanged and is why these two rules could be added at
    all: a missed counter renders a deck with no badge and says so in the prompt, while a false one
    prints a wrong page number on every slide of a creative the operator paid for. So the offset
    has to be the SAME on every candidate — one disagreement anywhere in the deck refuses the badge
    rather than being outvoted.
    """
    spec = slide_intel.detect_counter(chrome, ("panel",) * count, count)

    if expected is None:
        assert spec is None
        return
    assert spec is not None
    assert spec.format(3, 8) == expected


def test_the_offset_rules_never_resurrect_a_lookalike_the_earlier_rules_refused() -> None:
    """The D48 rules widened the accept set, so the v2.1.2 rejections are re-asserted THROUGH them.

    `24/7` twice is a constant offset of 1 by arithmetic (`open 24/7` on panels 2 and 3), and rule
    4 would take it if the sanity fence did not refuse both tokens first: 24 > 7 is not a counter,
    and a date is a run of digits rather than a pair. These are the strings that would print
    "24/7" on every slide, so they are pinned here as well as above.
    """
    assert slide_intel.detect_counter(([], ["open 24/7"], ["support 24/7"]), ("a",) * 3, 3) is None
    assert slide_intel.detect_counter(
        ([], ["posted 12/08/2026"], ["12/08/2026"]), ("a",) * 3, 3) is None
    assert slide_intel.detect_counter(([], ["1/2 cup of oats"], []), ("a",) * 3, 3) is None


@pytest.mark.parametrize(
    ("line", "is_chrome"),
    [
        # ACCEPTED — the whole line is a badge, in each convention this module already models.
        ("01 / 06", True),          # padded, spaced: the commonest slideshow hand
        ("1/6", True),              # bare
        ("2 of 7", True),           # worded separator
        ("// 01", True),            # the total-less prefix form
        ("  3 · 9  ", True),        # a middle dot separator; surrounding space is not content
        # REFUSED — every one of these is the source's own COPY, and copy ships byte-verbatim.
        ("3/4 of teams fail at this", False),   # a fraction inside a sentence
        ("24/7", False),                        # a claim about opening hours: 24 > 7
        ("16:9", False),                        # an aspect ratio, not a position
        ("12/08/2026", False),                  # a date is a run of digits, not a pair
        ("Slide 1/6", False),                   # a badge with a word on it is a typeset line
        ("// 01 THE HOOK", False),              # a prefix counter set INTO the panel's own words
        ("", False),                            # a blank line is not chrome and is not ours to drop
        ("0/6", False),                         # there is no page zero
        ("7/6", False),                         # a position past the total is not a position
    ])
def test_counter_line_is_full_line_only_so_a_fraction_inside_a_sentence_still_ships(
    line: str, is_chrome: bool,
) -> None:
    """F2 (Session 5.5): the admission-time half of the counter story, and its safety argument.

    `detect_counter` above LEARNS the source's convention so we can re-base it onto our own deck.
    This predicate answers the narrower question `copywrite._offer_for` asks of every panel line
    before it may become pixels: are these bytes furniture? They arrive as copy because Virlo's
    adapter has no `chrome_text` field, and left in they become our slide's words, then
    `panel_map.source_text`, then an expected L-line of the gauntlet's frame contract — where a
    render that correctly left the badge out is BLOCKED for `missing_text`. That is exactly what
    happened to the Ig deck on 2026-08-14.

    **Full-line only is the whole safety argument.** The line is judged after `strip()` and has to
    be counter-shaped edge to edge, so anything with a word on it is the creator's typography and
    ships untouched. The two halves of the table are the same fence from both sides: the four
    accepted shapes are the ones `detect_counter` already treats as a convention, and the refused
    ones are the strings a looser rule would silently delete from a paid creative.
    """
    assert slide_intel.counter_line(line) is is_chrome


# ------------------------------------ FR-306 amendment (v2.1.3/D48): mark boxes, sanitised hard
#
# `mark_boxes` is the rectangle FR-315 crops a logo patch out of, so it is source-controlled
# geometry on its way to Pillow and to a Kie upload. Everything below is a REJECTION, applied per
# entry and silently (§0.14c): a box this parser cannot trust costs its mark a pixel reference and
# nothing else — the mark still renders from its name and its written description.


def _row(slot: int, *boxes: dict[str, Any]) -> dict[str, Any]:
    """One answer row carrying `mark_boxes`, on top of the ordinary slide fields."""
    return _answer(slot) | {"mark_boxes": list(boxes)}


def _box(name: str = "Notion", slide: int = 1, box: Any = (0.1, 0.2, 0.2, 0.1)) -> dict[str, Any]:
    return {"name": name, "slide": slide, "box": list(box) if isinstance(box, tuple) else box}


@pytest.mark.parametrize(
    ("box", "why"),
    [
        ((0.1, 0.2, 0.2), "three numbers is not a rectangle"),
        ((0.1, 0.2, 0.2, 0.1, 0.5), "five numbers is not a rectangle either"),
        (("a", "b", "c", "d"), "non-numeric coordinates"),
        ((0.1, 0.2, 0.0, 0.1), "a zero-width box crops nothing"),
        ((0.1, 0.2, 0.2, 0.0), "a zero-height box crops nothing"),
        ((0.0, 0.0, 0.95, 0.5), "wider than 90% of the slide is the panel, not a logo"),
        ((0.0, 0.0, 0.5, 0.95), "taller than 90% of the slide is the panel, not a logo"),
        ("0.1,0.2,0.2,0.1", "a string is not a coordinate array"),
        (None, "an absent box"),
    ])
async def test_a_mark_box_that_is_not_a_small_rectangle_is_dropped_and_never_raises(
    tmp_path: Path, downloads: list[str], box: Any, why: str,
) -> None:
    """FR-306 amendment: the span ceiling is the carve-out's upstream guard, and arity is Pillow's.

    A "logo" spanning more than `_MARK_BOX_MAX_SPAN` of the slide is the model boxing the whole
    panel — cropping it would upload the source slide itself, which is exactly what FR-244's narrow
    carve-out does NOT sanction (D46 keeps `source/` analysis-and-display-only). Everything else
    here is a rectangle Pillow could not crop from, and a bad rectangle reaching Pillow is a
    traceback on a paid run.

    Every rejection is local and silent: the deck still reads, the slide still keeps its words, and
    the answer parses as a slide with no boxes rather than as a failed analysis.
    """
    post = _post(slides=2, panels=("Panel one", "Panel two"))
    vision = Vision(_row(1, _box(box=box)), _answer(2))
    log = Log()

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=log))["p1"]

    assert report.mark_boxes == [], why
    assert report.status == slide_intel.STATUS_OK, "a bad box is not a failed read (§0.14c)"
    assert report.panel_texts == ["Panel one", "Panel two"], "the deck's words are untouched"
    assert _read_yaml(tmp_path)["mark_boxes"] == []


async def test_a_mark_box_reaching_past_the_slide_edge_is_clamped_rather_than_dropped(
    tmp_path: Path, downloads: list[str]
) -> None:
    """Clamped on RANGE, rejected on SHAPE — the two halves of `_box` and the reason for the split.

    A model that says `1.02` means the slide's edge, and a crop that stops at the edge is the right
    crop; dropping it would cost a real mark its pixels over a rounding error. The width/height
    ceiling still applies AFTER the clamp, so a box clamped into a full-slide rectangle is refused
    by the span rule rather than sneaking through as "clamped, therefore fine".
    """
    post = _post(slides=2, panels=("Panel one", "Panel two"))
    vision = Vision(_row(1, _box("Notion", 1, (-0.2, 1.4, 0.3, 0.25)),
                            _box("Figma", 2, (0.5, 0.5, 1.6, 0.2))),
                    _answer(2))

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=Log()))["p1"]

    assert [mark.name for mark in report.mark_boxes] == ["Notion"], \
        "the second box clamps to a full-slide width and the span rule then refuses it"
    assert report.mark_boxes[0].box == (0.0, 1.0, 0.3, 0.25), "x and y clamp into [0, 1]"


@pytest.mark.parametrize(("slide", "kept"), [(0, True), (1, True), (2, True), (3, False),
                                             (-1, False), (99, False)])
async def test_a_mark_box_naming_a_slide_outside_the_deck_is_dropped_or_falls_back_to_its_row(
    tmp_path: Path, downloads: list[str], slide: int, kept: bool,
) -> None:
    """The box names its own slide, so a mislabelled one is caught by the RANGE test rather than
    trusted because of where it arrived.

    Two behaviours are pinned together because they are one line of the implementation. A FALSY
    `slide` (0, or absent) falls back to the answer row's own position — an entry that names no
    slide arrived on a slide, and that is the slide it belongs to. Any other out-of-deck value,
    negative ones included, named nothing and is dropped: FR-315 would otherwise crop it from a
    file that is not there, or from the wrong panel.
    """
    post = _post(slides=2, panels=("Panel one", "Panel two"))
    vision = Vision(_row(1, _box("Notion", slide)), _answer(2))

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=Log()))["p1"]

    assert [mark.name for mark in report.mark_boxes] == (["Notion"] if kept else [])
    if kept:
        assert 1 <= report.mark_boxes[0].slide <= 2


async def test_the_deck_keeps_at_most_twenty_four_mark_boxes_however_many_the_model_returned(
    tmp_path: Path, downloads: list[str]
) -> None:
    """The cap is per DECK, not per slide (FR-306 amendment): each box becomes a cropped patch and
    a Kie upload downstream (FR-315), so it is a cost fence like every other number in that block.

    RAISED from 10 to 24 after the glz0 audit (v2.1.4). Ten was set on the belief that ten marks
    is already more than a real deck carries; the run then produced a tool round-up whose panels
    carried 21 distinct product logos, and eleven of them shipped with no patch — rendering from
    their names alone, which is precisely the invented-logo failure FR-315 exists to end. A tool
    round-up is a format this product renders, so the cap has to hold one.
    """
    post = _post(slides=2, panels=("Panel one", "Panel two"))
    vision = Vision(_row(1, *(_box(f"Mark {n}", 1) for n in range(16))),
                    _row(2, *(_box(f"Mark {n}", 2) for n in range(16, 32))))

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=Log()))["p1"]

    assert len(report.mark_boxes) == slide_intel._MAX_MARK_BOXES == 24
    assert [mark.name for mark in report.mark_boxes[:16]] == [f"Mark {n}" for n in range(16)], \
        "the cap takes the tail, in detection order — it never reshuffles"
    assert [mark.name for mark in report.boxes_on(2)] == [f"Mark {n}" for n in range(16, 24)]
    assert len(_read_yaml(tmp_path)["mark_boxes"]) == 24


async def test_a_deck_of_twenty_one_real_marks_keeps_every_one_of_them(
    tmp_path: Path, downloads: list[str]
) -> None:
    """The glz0 shape itself, pinned: 21 distinct marks across a deck now all survive the cap.

    Deck 01 of run `20260814_010814_glz0` was exactly this — a round-up naming 21 tools, capped to
    10, eleven marks left to the render model's imagination. Written as its own test beside the
    boundary test above because the boundary is arithmetic and this is the case that was lost.
    """
    post = _post(slides=2, panels=("Panel one", "Panel two"))
    vision = Vision(_row(1, *(_box(f"Tool {n}", 1) for n in range(11))),
                    _row(2, *(_box(f"Tool {n}", 2) for n in range(11, 21))))

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=Log()))["p1"]

    assert len(report.mark_boxes) == 21, "no real mark loses its pixels to the fence any more"


async def test_a_payload_with_no_mark_boxes_key_parses_as_a_deck_with_no_boxes(
    tmp_path: Path, downloads: list[str]
) -> None:
    """Strict mode makes `mark_boxes` REQUIRED of the model and OPTIONAL of the parser (§0.14c).

    An older cached answer, a truncated row, or a model that simply omitted the key is a slide with
    no boxes — never a failed read and never a warning, because a deck with no third-party mark on
    it is the ordinary case and the marks are an upgrade to it.
    """
    post = _post(slides=2, panels=("Panel one", "Panel two"))
    vision = Vision(_answer(1, "Words"), _answer(2, "More words"))
    log = Log()

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=log))["p1"]

    assert report.mark_boxes == [] and report.boxes_on(1) == []
    assert report.status == slide_intel.STATUS_OK
    assert not log.warnings, f"an absent optional key is not a degrade: {log.keys()}"
    assert _read_yaml(tmp_path)["mark_boxes"] == []


@pytest.mark.parametrize(("kind", "kept"), [("tool", True), ("apparel", False),
                                            ("chrome", False), ("other", False),
                                            ("TOOL", True), ("nonsense", True), (None, True)])
async def test_only_a_tool_logo_keeps_its_box(
    tmp_path: Path, downloads: list[str], kind: str | None, kept: bool,
) -> None:
    """v2.2.0: the box only exists so FR-315 can crop it, so a mark nothing may draw gets none.

    Run `…_m39f` is the measured case: the vision pass boxed "Nike" on a creator's hoodie, the crop
    step cut it out of the source slide, and the patch was uploaded to Kie — bought pixels for a
    mark no slide of that deck could ever name. Apparel, platform chrome and "I could not place it"
    are all the same answer here.

    `kind` is REQUIRED of the model and OPTIONAL of the parser, defaulting to `tool`: an absent key
    (an older cached answer, a truncated row, every answer the current question produces until the
    wave-1d prompt lands) parses exactly as today, and an unrecognised label is an unclassified
    tool rather than a silent new class. Case is not significant.
    """
    post = _post(slides=2, panels=("Panel one", "Panel two"))
    box = _box("Notion") | ({} if kind is None else {"kind": kind})
    vision = Vision(_row(1, box), _answer(2))
    log = Log()

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=log))["p1"]

    assert [item.name for item in report.mark_boxes] == (["Notion"] if kept else [])
    assert report.status == slide_intel.STATUS_OK, "a dropped box is not a failed read (§0.14c)"
    assert not log.warnings, f"a mark we may not draw is ordinary, not a degrade: {log.keys()}"
    if kept:
        assert report.mark_boxes[0].kind == slide_intel.MARK_KIND_TOOL


async def test_the_creators_own_mark_and_platform_chrome_never_get_a_box(
    tmp_path: Path, downloads: list[str]
) -> None:
    """FR-312's identity strip, applied to the pixels as well as to the words.

    A deck that strips "@theromanknox" out of its caption and then uploads that creator's wordmark
    as a render reference has published their signature anyway, through a different door. The
    handle and the display name are matched in their collapsed forms, because one slide's watermark
    is "@theromanknox" and the next slide's footer is "The Roman Knox". Platform chrome goes the
    same way for the same reason: a TikTok watermark is the app's signature, not the slide's
    subject, and FR-310 would refuse to let our deck draw it in any case.
    """
    post = _post(slides=2, panels=("Panel one", "Panel two"))
    post.author, post.author_name = "@theromanknox", "The Roman Knox"
    vision = Vision(_row(1, _box("@theromanknox logo"), _box("The Roman Knox wordmark"),
                         _box("TikTok"), _box("Instagram logo"), _box("Notion")),
                    _answer(2))

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=Log()))["p1"]

    assert [item.name for item in report.mark_boxes] == ["Notion"]


async def test_the_transcription_is_ocr_repaired_once_with_the_raw_reading_kept(
    tmp_path: Path, downloads: list[str]
) -> None:
    """The sanctioned admission boundary (`ocr_repair`), and the two rules that come with it.

    "Al agents" transcribed off a slide that reads "AI agents" is a defect the pipeline used to
    render faithfully onto a paid frame — verbatim is exactly what it promises, and the bytes it
    was handed were wrong. The repair happens HERE, once, so the panel map, the prompt and FR-100's
    verifier pool all see the same bytes; the raw reading is kept as `vision_text_original`; and a
    Virlo panel — the actual source of record — is never touched by any of it (§0.11).
    """
    post = _post(slides=2, panels=("Al tools that Virlo really sent", ""))
    vision = Vision(_answer(1, "a different reading"), _answer(2, "5 Al agents that ship"))
    log = Log()

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=log))["p1"]

    assert report.slides[1].vision_text == "5 AI agents that ship"
    assert report.slides[1].vision_text_original == "5 Al agents that ship"
    assert report.panel_texts[0] == "Al tools that Virlo really sent", \
        "a Virlo panel is the source of record and is never repaired"
    assert not log.warnings, f"a repair is not a degrade: {log.keys()}"
    stored = _read_yaml(tmp_path)["slides"]
    assert stored[1]["vision_text"] == "5 AI agents that ship"
    assert stored[1]["vision_text_original"] == "5 Al agents that ship"
    assert stored[0]["vision_text_original"] == "", "nothing was repaired on slide one"


async def test_a_panel_that_looks_cut_is_flagged_and_keeps_every_byte(
    tmp_path: Path, downloads: list[str]
) -> None:
    """`truncation_suspect` is contract data for the brief critic, never a licence to blank a slide.

    Dropping a suspect panel would silently re-map the whole deck (FR-304 renders our slide *i*
    from source panel *i*), which is a worse failure than any transcription defect — and an
    authored cliff-hanger looks identical to a clipped container from here. The critic is the one
    looking at the rendered frame, so it gets the flag and the bytes, and this stage keeps both.
    """
    cut = "The three habits that separate people who ship from people who keep planning and…"
    post = _post(slides=2, panels=(cut, "A finished line."))
    vision = Vision(_answer(1), _answer(2))

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=Log()))["p1"]

    assert [slide.truncation_suspect for slide in report.slides] == [True, False]
    assert report.panel_texts == [cut, "A finished line."], "flagged, not shortened"
    assert [row["truncation_suspect"] for row in _read_yaml(tmp_path)["slides"]] == [True, False]


async def test_the_mark_boxes_recorded_in_source_yaml_are_the_ones_the_crop_step_will_read(
    tmp_path: Path, downloads: list[str]
) -> None:
    """FR-71 provenance for the pixels: `source.yaml` records WHERE each cropped patch came from,
    so a patch that rendered wrong can be traced back to its rectangle without re-running (and
    re-paying for) the vision pass. The stored row must therefore be the sanitised box, not the
    model's raw answer."""
    post = _post(slides=2, panels=("Panel one", "Panel two"))
    vision = Vision(_row(1, _box("  Notion   logo  ", 1, (0.05, 0.05, 0.18, 0.09))), _answer(2))

    report = (await slide_intel.enrich([post], run_dir=tmp_path, call=vision, engine=_engine(),
                                       cfg=Config(), log=Log()))["p1"]

    assert report.mark_boxes == [slide_intel.MarkBox(
        name="Notion logo", slide=1, box=(0.05, 0.05, 0.18, 0.09))], "whitespace collapsed"
    assert _read_yaml(tmp_path)["mark_boxes"] == [
        {"name": "Notion logo", "slide": 1, "box": [0.05, 0.05, 0.18, 0.09], "kind": "tool"}]
