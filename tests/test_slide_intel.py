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


def _answer(slot: int, text: str = "", brief: str = "a brief", marks: tuple[str, ...] = ()) -> dict:
    """One row of the wire shape the module parses (`_SCHEMA`'s `slides` items)."""
    return {"slide": slot, "onimage_text": text, "visual_brief": brief,
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
        "visual_brief": "hero image, heading centred", "brand_marks": [],
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
