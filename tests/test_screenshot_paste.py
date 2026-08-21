"""FR-370 (D65) — the exact-pixel screenshot paste, end to end and boundary first.

What this file is about, in one paragraph. A real screenshot is the one thing on a source slide a
render model cannot reproduce: asked for "a tweet saying X" gpt-image-2 draws an invented handle,
invented words and an invented avatar onto a frame we then publish. D65's answer is the source's
own pixels — the render is ordered to leave a flat plate EMPTY, and after the frame lands the
engine composites the cropped source interface into it, LOCALLY, on this workstation, in a folder
the operator opens. Nothing about that touches a render payload, which is the property the first
test in this file pins and every other test is written not to weaken.

The five things asserted here, in the order they happen in a run:

1. **The boundary.** `outputs/screenshot_paste.py` imports nothing from `render` or `generate`, and
   `refs._sanctioned` still refuses every path under `source/` that is not a `marks/` patch.
2. **Detection** (`slide_intel`): `panel_kind` and `screenshot_box`, with NO span ceiling on the
   box (a screenshot legitimately fills its panel) and a 15%-per-axis floor.
3. **The compositor**: the raw render is backed up before a pixel moves, the crop keeps its aspect
   ratio, the frame is rewritten atomically and in its own mode, and every failure is fail-open.
4. **The gate**: five arms, each refused on its own, and the identity screen that refuses to
   republish the source creator's own post.
5. **What ships**: the paste is re-applied on every re-landing, the critics are told which
   rectangle is sanctioned, and `meta.yaml` says per row what happened.

No network, no money, no Pillow anywhere in `hypesocials/` outside the three sanctioned modules.
Real images are written to `tmp_path` and really composited: faking the pixels would leave the
only boundary that matters asserted against a mock of itself.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from hypesocials.generate import carousel as carousel_module
from hypesocials.generate import contracts as contracts_module
from hypesocials.generate import refs as refs_module
from hypesocials.models import DegradationTag, RenderOutcome, RenderOutcomeKind
from hypesocials.outputs import packager, screenshot_paste
from hypesocials.outputs.screenshot_paste import PLATE, PLATES_DIR, paste_screenshot
from hypesocials.sources import slide_intel
from hypesocials.sources.slide_intel import MarkBox, SourceSlide
from hypesocials import gauntlet

from tests.test_carousel import (
    FakeSubmit,
    give_intel,
    make_entry,
    make_env,
    make_folder,
    make_trends,
)

FRAME_PX = 1254


# --------------------------------------------------------------------------- the hard boundary


def test_the_compositor_can_never_reach_the_render_seam() -> None:
    """The D41/D46/D48 boundary, structurally: this module has no path to an upload at all.

    A grep, exactly like `test_slide_intel.py`'s, and for the same reason — the guarantee is not
    "we remembered not to upload", it is that there is no code here that could. `render.upload_file`
    is the named carve-out door and `generate/refs.py` is the other one; neither may appear, and
    neither may `hypesocials.generate` in any spelling.
    """
    source = Path(screenshot_paste.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    code = code.split('"""', 2)[-1]  # the module docstring NAMES the forbidden seam, on purpose
    for forbidden in ("upload_file", "hypesocials.render", "hypesocials.generate",
                      "from .render", "from .generate"):
        assert forbidden not in code, f"screenshot_paste reaches the render seam: {forbidden!r}"


def test_the_source_store_guard_is_untouched_by_this_feature(tmp_path: Path) -> None:
    """`refs._sanctioned` still refuses everything under `source/` but a `marks/` patch (FR-244).

    The whole feature is output-side, so the guard that decides what may be UPLOADED out of the
    source store must be exactly as narrow after D65 as before it. A stored slide is refused; the
    same slide's cropped logo patch is allowed; a `plates/` backup — the new folder this session
    writes — is refused like everything else, because it is a copy of a render, not a mark.
    """
    run_dir = tmp_path / "run"
    slide = run_dir / "source" / "post-a" / "slide_03.jpg"
    patch = run_dir / "source" / "post-a" / "marks" / "notion.png"
    plate = run_dir / "0001_carousel_linkedin" / PLATES_DIR / "slide_03_raw.jpg"
    for path in (slide, patch, plate):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    assert refs_module._sanctioned(patch) is True
    assert refs_module._sanctioned(slide) is False
    # The `plates/` backup is a copy of a RENDER, not a source byte — it is outside `source/`
    # entirely, which is the whole reason it lives in the asset folder rather than beside the
    # slide it was cut from.
    assert refs_module._sanctioned(plate) is True
    # The load-bearing half, stated as its own assertion: nothing under `source/` outside `marks/`.
    assert refs_module._sanctioned(run_dir / "source" / "post-a" / "slide_01.webp") is False


# ------------------------------------------------------------------------------- 1. detection


@pytest.mark.parametrize("value,expected", [
    ("screenshot", "screenshot"),
    ("graphic", "graphic"),
    ("photo", "photo"),
    ("SCREENSHOT", "screenshot"),          # the model shouting is still an answer
    ("a screenshot of a tweet", "graphic"),  # prose is not one of the three words
    ("", "graphic"),
    (None, "graphic"),
    (7, "graphic"),
])
def test_panel_kind_admits_three_words_and_defaults_to_graphic(value: Any, expected: str) -> None:
    """`graphic` is the value under which this whole feature is inert, so it is the default.

    An older cached answer with no `panel_kind` key, a truncated row, a model that answered in a
    sentence — every one of them has to read as a panel our own style redraws, which is what the
    engine did before D65. Only the exact word turns anything on.
    """
    assert slide_intel._panel_kind(value) == expected


def test_a_screenshot_box_has_no_span_ceiling_because_it_is_never_uploaded() -> None:
    """The asymmetry with `_box()` is the point (FR-370 vs FR-244).

    A MARK box becomes a cropped patch that is uploaded to the render provider, so a rectangle
    spanning the panel is refused — it would carry the source slide itself past D48's narrow
    carve-out. A SCREENSHOT box becomes a local composite that is never uploaded anywhere, and a
    full-bleed tweet card filling its panel is the ordinary shape of the thing.
    """
    full = [0.0, 0.0, 1.0, 1.0]
    assert slide_intel._box(full) is None, "a mark box that big is a misdetection"
    assert slide_intel._screenshot_box(full) == (0.0, 0.0, 1.0, 1.0)
    assert slide_intel._screenshot_box([0.04, 0.10, 0.93, 0.84]) == (0.04, 0.10, 0.93, 0.84)


@pytest.mark.parametrize("value", [
    [0.1, 0.1, 0.14, 0.5],    # too narrow — an avatar, not an interface
    [0.1, 0.1, 0.5, 0.02],    # too short — a button row
    [0.1, 0.1, 0.0, 0.5],     # zero area
    [0.1, 0.1, 0.5],          # three numbers
    [0.1, 0.1, 0.5, 0.5, 0.5],
    "0.1,0.1,0.5,0.5",
    None,
    [None, 0.1, 0.5, 0.5],
    ["x", "y", "w", "h"],
])
def test_a_malformed_or_tiny_screenshot_box_is_refused_never_raised(value: Any) -> None:
    """Fail-open at the parse boundary: every one of these is `None`, not an exception.

    The floor is what the ceiling is for a mark box. Something under 15% of the panel on an axis
    is a favicon or the model pointing at a button, and blowing it up into a plate 84% of the
    frame wide would ship a smear the craft critic would then be told to sanction.
    """
    assert slide_intel._screenshot_box(value) is None


def test_the_box_rides_the_slide_only_when_the_panel_is_a_screenshot() -> None:
    """A box on a panel the model called a GRAPHIC is a box on somebody's design (FR-370).

    Reusing a designed layout is not this feature — our own styles redraw those, which is what the
    registry exists for. So the parser admits the rectangle only under the kind that licenses it.
    """
    intel = slide_intel.SlideIntel(post_id="p", slides=[SourceSlide(position=1),
                                                        SourceSlide(position=2)])
    payload = {"slides": [
        {"slide": 1, "onimage_text": "", "chrome_text": "", "visual_brief": "", "brand_marks": [],
         "mark_boxes": [], "panel_kind": "screenshot", "screenshot_box": [0.05, 0.2, 0.9, 0.6]},
        {"slide": 2, "onimage_text": "", "chrome_text": "", "visual_brief": "", "brand_marks": [],
         "mark_boxes": [], "panel_kind": "graphic", "screenshot_box": [0.05, 0.2, 0.9, 0.6]},
    ], "language": "en"}

    slide_intel._apply(intel, payload, [1, 2], frozenset(), None)

    assert intel.slide(1).panel_kind == "screenshot"
    assert intel.slide(1).screenshot_box == (0.05, 0.2, 0.9, 0.6)
    assert intel.slide(2).panel_kind == "graphic"
    assert intel.slide(2).screenshot_box is None


def test_chrome_boxes_are_kept_apart_from_croppable_mark_boxes() -> None:
    """The identity screen's evidence, in a list nothing crops from (FR-370/FR-315).

    `_mark_boxes` drops chrome at the parse boundary because chrome is never croppable, and until
    D65 that meant the engine had no way to ask "does a watermark sit on the rectangle we were
    about to reuse". The answer is a SECOND list, and the two are separate functions rather than
    one with a flag precisely because the failure mode of confusing them is publishing a watermark.
    """
    intel = slide_intel.SlideIntel(post_id="p", slides=[SourceSlide(position=1)])
    payload = {"slides": [{
        "slide": 1, "onimage_text": "", "chrome_text": "", "visual_brief": "", "brand_marks": [],
        "panel_kind": "screenshot", "screenshot_box": [0.05, 0.2, 0.9, 0.6],
        "mark_boxes": [
            {"name": "Notion", "slide": 1, "kind": "tool", "box": [0.1, 0.1, 0.08, 0.05]},
            {"name": "TikTok watermark", "slide": 1, "kind": "chrome",
             "box": [0.6, 0.3, 0.2, 0.1]},
        ]}], "language": ""}

    slide_intel._apply(intel, payload, [1], frozenset(), None)

    assert [box.name for box in intel.mark_boxes] == ["Notion"]
    assert [box.name for box in intel.chrome_boxes] == ["TikTok watermark"]
    assert [box.name for box in intel.chrome_on(1)] == ["TikTok watermark"]
    assert intel.chrome_on(2) == []


# ------------------------------------------------------------------------------ 2. the plate


def test_the_prompt_block_and_the_compositor_quote_the_same_geometry() -> None:
    """One tuple, two readers — the render is told where the plate is and the paste aims there.

    A plate ordered at 8%-92% and filled at 10%-90% is a screenshot sitting on top of somebody's
    headline, so the block's words are built from `plate_zone()` rather than typed out beside it.
    """
    from hypesocials import prompts_engine as pe

    assert screenshot_paste.plate_zone() in pe._SCREENSHOT_PLATE_BLOCK
    assert PLATE == (0.08, 0.20, 0.84, 0.58)
    assert "8%" in screenshot_paste.plate_zone() and "92%" in screenshot_paste.plate_zone()


def test_the_plate_slot_is_empty_on_every_slide_that_takes_no_paste() -> None:
    """FR-370's budget property: the block costs the rest of the registry nothing.

    Every character in a slide prompt is charged against the style trio's trim ceiling
    (`tests/test_prompt_fit.py`), so a block that rendered on all twenty-six styles' slides to
    describe a rectangle they never reserve would be paid for by their art direction.
    """
    from hypesocials import prompts_engine as pe

    assert pe.build_context()["screenshot_plate"] == ""
    assert pe.build_context(screenshot_plate=True)["screenshot_plate"] == \
        pe._SCREENSHOT_PLATE_BLOCK
    assert "screenshot_plate" in pe.allowlist("carousel_slide.md")
    for role in ("image_post.md", "reel_seed_frame.md", "copywriter_system.md"):
        assert "screenshot_plate" not in pe.allowlist(role), role


# ---------------------------------------------------------------------------- 3. the compositor


def write_frame(path: Path, colour: tuple[int, int, int] = (240, 238, 230),
                mode: str = "RGB", size: int = FRAME_PX) -> Path:
    """A landed render: a flat frame in the deck's surface colour, the plate not yet filled."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, (size, size), colour if mode == "RGB" else (*colour, 255)).save(path)
    return path


def write_source(path: Path, width: int = 1000, height: int = 1400) -> Path:
    """A source slide carrying a tall 'interface' — deliberately NOT the plate's aspect ratio."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (width, height), (250, 250, 250))
    for top in range(0, height, 40):  # texture, so a crop is never one flat colour
        image.paste((28, 32, 200), (0, top, width, top + 20))
    image.save(path)
    return path


def test_the_raw_render_is_backed_up_before_a_pixel_moves(tmp_path: Path) -> None:
    """`plates/slide_NN_raw.<ext>` is written first, byte for byte (FR-370/FR-72).

    It is what makes the paste reviewable — "what did the model draw under there" is the first
    question an off-centre plate raises — and it is written BEFORE the composite because a
    composite that cannot be undone is a paid render the operator can never see again.
    """
    frame = write_frame(tmp_path / "asset" / "slide_03.jpg")
    raw_bytes = frame.read_bytes()
    source = write_source(tmp_path / "source" / "slide_03.jpg")

    result = paste_screenshot(frame, source, (0.05, 0.10, 0.90, 0.80))

    assert result.ok and result.reason == ""
    assert result.raw_backup == "plates/slide_03_raw.jpg"
    backup = tmp_path / "asset" / PLATES_DIR / "slide_03_raw.jpg"
    assert backup.read_bytes() == raw_bytes, "the backup is the render as it landed"
    assert frame.read_bytes() != raw_bytes, "and the slide itself was rewritten"


def test_the_crop_keeps_its_aspect_ratio_and_is_centred_in_the_plate(tmp_path: Path) -> None:
    """FIT, never fill (FR-370). A cropped screenshot is a screenshot with a column missing.

    The fixture's interface is 5:7 and the plate is 84%x58% of a square frame, so the fit is
    height-bound: the pasted rectangle must span the plate's full height, sit centred horizontally,
    and be narrower than the plate by exactly the aspect difference.
    """
    frame = write_frame(tmp_path / "asset" / "slide_02.png")
    source = write_source(tmp_path / "source" / "slide_02.png", width=1000, height=1400)

    result = paste_screenshot(frame, source, (0.0, 0.0, 1.0, 1.0))

    assert result.ok
    # `zone` names the PASTED rectangle, not the plate — the surface either side of a tall
    # screenshot is still judged by every rule the critics have.
    assert "20% to 78% of its height" in result.zone
    left, right = (int(part.rstrip("%")) for part in
                   result.zone.split("from ", 1)[1].split(" of the frame")[0].split(" to "))
    assert left > 8 and right < 92, "a tall crop cannot fill a wider plate"
    assert abs((50 - left) - (right - 50)) <= 1, "and it is centred"


def test_the_composite_preserves_the_frames_own_mode_and_leaves_the_edge_ring_alone(
        tmp_path: Path) -> None:
    """The alpha-halo guard (FR-365) reads this same file afterwards and must see the same frame.

    Two properties, one test: an RGBA render stays RGBA (a mode chosen here would make FR-365's
    verdict a verdict about the paste), and the 2% edge ring the guard measures is untouched —
    the plate spans 8%-92% x 20%-78%, so it cannot reach the border.
    """
    frame = write_frame(tmp_path / "asset" / "slide_01.png", mode="RGBA")
    corner_before = Image.open(frame).getpixel((3, 3))
    source = write_source(tmp_path / "source" / "slide_01.png")

    assert paste_screenshot(frame, source, (0.0, 0.1, 1.0, 0.8)).ok

    after = Image.open(frame)
    assert after.mode == "RGBA"
    assert after.getpixel((3, 3)) == corner_before
    assert after.getpixel((FRAME_PX // 2, FRAME_PX // 2)) != corner_before, "the middle moved"


def test_the_frame_is_rewritten_whole_or_not_at_all(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """Atomic (temp+rename, NFR-21): a kill mid-write leaves the previous good file.

    Asserted through the seam the module actually uses rather than by racing it: the write goes
    through `util.atomic_write`, and a failure inside it leaves the landed render exactly as it
    was — with the paste reporting the failure instead of raising it.
    """
    frame = write_frame(tmp_path / "asset" / "slide_04.jpg")
    before = frame.read_bytes()
    source = write_source(tmp_path / "source" / "slide_04.jpg")
    calls: list[Path] = []
    real = screenshot_paste.atomic_write

    def _fail(path: Any, data: Any) -> None:
        calls.append(Path(path))
        if Path(path).name == "slide_04.jpg":
            raise OSError("no space left on device")
        real(path, data)

    monkeypatch.setattr(screenshot_paste, "atomic_write", _fail)

    result = paste_screenshot(frame, source, (0.05, 0.10, 0.90, 0.80))

    assert result.ok is False and "OSError" in result.reason
    assert frame.read_bytes() == before, "the paid render is untouched by a failed paste"
    assert [path.name for path in calls] == ["slide_04_raw.jpg", "slide_04.jpg"]


@pytest.mark.parametrize("case", ["missing_source", "corrupt_source", "no_box", "tiny_crop"])
def test_every_failure_is_fail_open_and_leaves_the_render_standing(tmp_path: Path,
                                                                   case: str) -> None:
    """§0.14c: nothing here raises, and nothing here loses the slide.

    A failed paste ships the EMPTY PLATE the render drew, which is deliberately visible — the
    craft critic reports it and `screenshot_paste_failed` badges the card. What must never happen
    is an exception on a frame that already cost money.
    """
    frame = write_frame(tmp_path / "asset" / f"slide_0{len(case) % 9}.jpg")
    before = frame.read_bytes()
    source = tmp_path / "source" / "missing.jpg"
    box: Any = (0.05, 0.10, 0.90, 0.80)
    if case == "corrupt_source":
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"\xff\xd8not really a jpeg at all")
    elif case == "no_box":
        write_source(source)
        box = None
    elif case == "tiny_crop":
        write_source(source, width=120, height=120)
        box = (0.0, 0.0, 0.2, 0.2)  # 24 px of a 120 px slide — under the crop floor

    result = paste_screenshot(frame, source, box)

    assert result.ok is False and result.reason
    assert frame.read_bytes() == before


def test_the_pasted_pixels_are_the_sources_own_and_not_a_redrawing(tmp_path: Path) -> None:
    """The headline claim of D65, asserted as pixels: EXACT, not similar (FR-370).

    The frame is a PNG (lossless, so a byte comparison means something), the corners are square
    and the hairline is the only thing drawn over the boundary — so the interior of the pasted
    rectangle must equal the source crop scaled the same way, pixel for pixel. If this ever fails
    the feature has quietly become "a picture that resembles the screenshot", which is what the
    render model was already doing.
    """
    frame = write_frame(tmp_path / "asset" / "slide_05.png")
    source = write_source(tmp_path / "source" / "slide_05.png", width=900, height=1200)

    result = paste_screenshot(frame, source, (0.0, 0.0, 1.0, 1.0), corner_radius_px=0)

    assert result.ok
    composed = Image.open(frame)
    plate_left = int(round(PLATE[0] * FRAME_PX))
    plate_top = int(round(PLATE[1] * FRAME_PX))
    room = (int(round(PLATE[2] * FRAME_PX)), int(round(PLATE[3] * FRAME_PX)))
    scale = min(room[0] / 900, room[1] / 1200)
    size = (round(900 * scale), round(1200 * scale))
    expected = Image.open(source).convert("RGB").resize(size, Image.Resampling.LANCZOS)
    place = (plate_left + (room[0] - size[0]) // 2, plate_top + (room[1] - size[1]) // 2)
    # Inset by two pixels on every side: the 1 px hairline is drawn over the boundary, which is
    # the one row of the rectangle that is deliberately not the source's.
    box = (place[0] + 2, place[1] + 2, place[0] + size[0] - 2, place[1] + size[1] - 2)
    assert composed.crop(box).tobytes() == expected.crop(
        (2, 2, size[0] - 2, size[1] - 2)).tobytes()


def test_it_composites_a_real_source_slide_from_a_real_run_folder(tmp_path: Path) -> None:
    """The live shape, on bytes a live run actually downloaded — `.webp`, not the suite's `.jpg`.

    The source store names a slide after the CDN URL's own suffix, so nearly every real deck is
    webp and every fixture in this file is not. Skipped when no run folder is present (a fresh
    clone, CI), because a test that quietly asserts nothing is worse than one that says why.
    """
    slides = sorted(Path("output").glob("*/source/*/slide_01.*"))
    if not slides:
        pytest.skip("no run folder with a stored source slide on this workstation")
    frame = write_frame(tmp_path / "asset" / "slide_01.png")

    result = paste_screenshot(frame, slides[0], (0.06, 0.12, 0.88, 0.72))

    assert result.ok, result.reason
    assert (tmp_path / "asset" / PLATES_DIR / "slide_01_raw.png").is_file()
    assert Image.open(frame).size == (FRAME_PX, FRAME_PX)


def test_the_backup_name_is_spelled_in_exactly_one_place() -> None:
    """The gallery links `plates/…` and this module writes it; a second derivation is a dead link."""
    assert screenshot_paste.raw_backup_name("slide_07.webp") == "plates/slide_07_raw.webp"
    assert screenshot_paste.raw_backup_name("slide_07") == "plates/slide_07_raw"


# ------------------------------------------------------------------------------- 4. the gate


def build_deck(tmp_path: Path, *, reuse: bool = True, kind: str = "screenshot",
               box: Any = (0.05, 0.15, 0.88, 0.70), slides: int = 3, on_disk: bool = True,
               chrome_text: str = "", marks: Any = (), chrome_boxes: Any = (),
               author: str = "emirailab") -> Any:
    """A `_Deck` whose source panel 2 is a screenshot, with every gate arm switchable.

    Built through the same factories `tests/test_carousel.py` uses so the predicate is exercised
    against the real `_Deck`, the real config object and the real slide-intelligence record rather
    than against a stand-in shaped like the ones this test would have written.
    """
    entry = make_entry(slides=slides, source_post_id="post-a")
    env = make_env(tmp_path, entry, texts=[f"line {n}" for n in range(1, slides + 1)])
    env.config.run.screenshot_reuse = reuse
    env.trends = make_trends(panels=slides)
    env.trends["t1"].posts[0].author = author
    intel = give_intel(env, panels=slides, chrome=["", chrome_text, ""],
                       marks=[(), tuple(marks), ()])
    intel.slides[1].panel_kind = kind
    intel.slides[1].screenshot_box = box
    intel.chrome_boxes = list(chrome_boxes)
    if on_disk:
        for position in range(1, slides + 1):
            name = f"slide_{position:02d}.jpg"
            write_source(tmp_path / "source" / "post-a" / name, width=800, height=1000)
            intel.slides[position - 1].image_file = name
    return carousel_module._Deck(entry, env, make_folder(tmp_path, entry), FakeSubmit())


def test_the_gate_reserves_a_plate_only_when_every_arm_agrees(tmp_path: Path) -> None:
    """The happy path first, so the refusals below are refusals OF something (FR-370)."""
    deck = build_deck(tmp_path)

    assert deck.paste_slides == {2}
    assert "screenshot_plates_reserved" in deck.env.log.types()


@pytest.mark.parametrize("kwargs,reason", [
    ({"reuse": False}, "the operator never switched it on"),
    ({"kind": "graphic"}, "the panel is a design, not a capture"),
    ({"kind": "photo"}, "the panel is a photograph"),
    ({"box": None}, "no box parsed"),
    ({"on_disk": False}, "the source slide was never stored"),
])
def test_each_gate_arm_refuses_on_its_own(tmp_path: Path, kwargs: dict[str, Any],
                                          reason: str) -> None:
    """Five arms, five refusals, each with everything else set to pass.

    Ordering a plate the paste cannot fill is strictly worse than not ordering one: the render
    draws an empty rounded rectangle in the middle of a paid slide and the deck ships with a hole
    in it. So every arm has to be able to say no by itself.
    """
    assert build_deck(tmp_path, **kwargs).paste_slides == set(), reason


def test_a_screenshot_of_the_creators_own_post_is_never_reused(tmp_path: Path) -> None:
    """The identity screen, words arm (FR-370/FR-312).

    Third-party content inside the plate is exactly what this feature exists for. The SOURCE
    CREATOR's own post is the opposite: their handle, their avatar and their engagement counts,
    republished under our account — the leak FR-312 spends a whole strip pass preventing in the
    words, arriving as pixels instead. v1 refuses the paste; blurring a region is its own feature.
    """
    deck = build_deck(tmp_path, chrome_text="@emirailab · 3/6", author="emirailab")

    assert deck.paste_slides == set()
    assert "screenshot_paste_skipped_identity" in deck.env.log.types()
    detail = deck.env.log.fields("screenshot_paste_skipped_identity")["detail"]
    assert "emirailab" in detail


def test_the_creators_own_mark_on_the_panel_also_refuses_the_paste(tmp_path: Path) -> None:
    """Same screen, second spelling: the handle is `emirailab`, the panel shows `Emir AI Lab`.

    `_is_author_mark` matches containment BOTH ways over collapsed keys, which is the D65/FR-366
    fix this reuses rather than re-implements — one vocabulary for "is this the creator", used by
    the sanction gate and by this screen alike.
    """
    deck = build_deck(tmp_path, marks=("Emir AI Lab",), author="emirailab")

    assert deck.paste_slides == set()
    assert "screenshot_paste_skipped_identity" in deck.env.log.types()


def test_platform_chrome_sitting_on_the_screenshot_refuses_the_paste(tmp_path: Path) -> None:
    """The geometric arm: a watermark half inside the crop is still a watermark once published.

    Any overlap at all is enough — there is no fraction of somebody's signature that is acceptable
    to republish, and the box the crop is cut with was supposed to exclude it.
    """
    overlapping = MarkBox(name="TikTok watermark", slide=2, box=(0.5, 0.4, 0.2, 0.1),
                          kind="chrome")
    assert build_deck(tmp_path, chrome_boxes=(overlapping,)).paste_slides == set()

    # …and a watermark clear of the rectangle does NOT refuse it: the box is 0.05-0.93 wide and
    # 0.15-0.85 tall, so a mark in the top-left corner above it is outside.
    clear = MarkBox(name="TikTok watermark", slide=2, box=(0.0, 0.0, 0.04, 0.05), kind="chrome")
    assert build_deck(tmp_path, chrome_boxes=(clear,)).paste_slides == {2}


def test_a_plate_slide_is_ordered_wordless_and_briefless(tmp_path: Path) -> None:
    """The screenshot IS the content (FR-370), so the render is told to draw no words at all.

    Re-setting the panel's words in the deck's typeface above a picture of those same words prints
    the slide twice. The mapped bytes are not lost — `self.texts` still carries them, and so do the
    panel map and `meta.yaml` — but the RENDER is ordered empty of them, and the visual brief
    (which describes the very screenshot about to be pasted) is withheld for the same reason.
    """
    deck = build_deck(tmp_path)
    deck.env.slide_intel["post-a"].slides[1].visual_brief = "a tweet card with an avatar"

    plate_prompt = deck._prompt(2, anchor=False, refs=[])
    plain_prompt = deck._prompt(3, anchor=False, refs=[])

    assert "SCREENSHOT PLATE" in plate_prompt and "8% to 92%" in plate_prompt
    assert "line 2" not in plate_prompt, "the plate slide's own line is not lettered"
    assert "a tweet card with an avatar" not in plate_prompt
    assert "SCREENSHOT PLATE" not in plain_prompt
    assert "line 3" in plain_prompt
    assert deck.texts[1] == "line 2", "and the mapped bytes survive on the deck"


# ------------------------------------------------------------------- 5. landing, critics, meta


@pytest.fixture
def landings(monkeypatch: pytest.MonkeyPatch) -> None:
    """`packager._download` answers with a REAL frame, so `_store` writes a compositable file."""
    async def _download(url: str) -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", (FRAME_PX, FRAME_PX), (240, 238, 230)).save(buffer, format="JPEG")
        return buffer.getvalue()

    monkeypatch.setattr(packager, "_download", _download)


def landed(number: int, index: int = 0) -> RenderOutcome:
    return RenderOutcome(kind=RenderOutcomeKind.SUCCESS, task_id=f"kie_{number}_{index}",
                         result_urls=[f"https://kie.test/slide-{number}-{index}.jpg"],
                         cost_usd=0.05)


async def test_the_paste_happens_at_the_landing_seam_and_again_on_a_re_render(
        tmp_path: Path, landings: None) -> None:
    """FR-370's hook point: one seam, so every route through it is covered.

    First render, FR-317's resubmit, FR-351's chosen cover, FR-95's replacement anchor, FR-365's
    alpha repair and every gauntlet fix round all land through `_store`. A paste placed there is
    re-applied identically each time, which is what makes "the critics always judge the composited
    frame" true rather than true-on-the-first-attempt: the second landing overwrites both the slide
    and its `plates/` backup, so the backup still explains the frame that is on disk.
    """
    deck = build_deck(tmp_path)

    assert await deck._store(2, landed(2), lost=True) is True
    first = deck.paths[2].read_bytes()
    assert deck.pastes[2].ok is True
    assert (deck.folder.path / PLATES_DIR / "slide_02_raw.jpg").is_file()
    assert "screenshot_pasted" in deck.env.log.types()

    # …and the same slide re-rendered by the gauntlet's fix loop is pasted again.
    assert await deck._store(2, landed(2, index=1), lost=False) is True
    assert deck.pastes[2].ok is True
    assert deck.paths[2].read_bytes() == first, "the same crop, the same plate, the same pixels"


async def test_a_slide_that_ordered_no_plate_is_never_touched(tmp_path: Path,
                                                              landings: None) -> None:
    """The landing seam is shared by the whole deck, so the predicate has to hold at it too."""
    deck = build_deck(tmp_path)

    await deck._store(3, landed(3), lost=True)

    assert 3 not in deck.pastes
    assert not (deck.folder.path / PLATES_DIR).exists()


async def test_a_failed_paste_ships_the_empty_plate_tagged_and_judged(
        tmp_path: Path, landings: None) -> None:
    """FR-370: the defect is made VISIBLE rather than hidden — and the sanction is withheld.

    Three consequences of one failure, and the third is the important one: the frame contract
    carries NO `screenshot:` row, so the craft critic sees a bare plate on a frame it was never
    told to excuse, and reports it. A sanction written from what was ORDERED rather than from what
    HAPPENED would have told the critics to ignore exactly the frame the operator needs to see.
    """
    deck = build_deck(tmp_path)
    (tmp_path / "source" / "post-a" / "slide_02.jpg").unlink()

    await deck._store(2, landed(2), lost=True)

    assert deck.pastes[2].ok is False
    assert DegradationTag.SCREENSHOT_PASTE_FAILED in deck.folder.record.degradations
    assert "screenshot_paste_failed" in deck.env.log.types()
    contract = deck._contract([1, 2, 3])
    assert contract.frame(2).screenshot_zone == ""


async def test_the_critics_are_told_which_rectangle_is_sanctioned(tmp_path: Path,
                                                                  landings: None) -> None:
    """The `screenshot:` row rides the EXISTING `{{expected_blocks}}` channel (FR-370).

    Per frame, never deck-wide: a deck-level slot would sanction the same rectangle on frames that
    took no paste, and those frames are judged by every rule in the rulebook. The row says the
    pixels are the source's own, which is the one thing a picture cannot tell a critic — without
    it, a pasted tweet reads as the worst leak the brief critic knows.
    """
    deck = build_deck(tmp_path)
    await deck._store(2, landed(2), lost=True)

    contract = deck._contract([1, 2, 3])
    blocks = gauntlet._expected_blocks(contract, [1, 2, 3])

    assert contract.frame(2).screenshot_zone
    assert contract.frame(3).screenshot_zone == ""
    assert "screenshot:" in blocks.split("frame 2")[1].split("frame 3")[0]
    assert "screenshot:" not in blocks.split("frame 3")[1]
    assert "EXACT PIXELS" in blocks
    # The frame was ordered wordless BY MANDATE, and the mandate names itself.
    assert contract.frame(2).body_lines == []
    assert contract.frame(2).wordless_reason == "screenshot_paste"
    assert "screenshot_paste" in blocks


def test_the_frame_contract_carries_the_zone_through_untouched() -> None:
    """`contracts.frame_contract` passes the prose along; it never invents or edits one."""
    frame = contracts_module.frame_contract(4, "", screenshot_zone="from 10% to 90% of the width")

    assert frame.screenshot_zone == "from 10% to 90% of the width"
    assert contracts_module.frame_contract(4, "").screenshot_zone == ""


async def test_meta_records_the_paste_per_row_and_names_no_second_path(
        tmp_path: Path, landings: None) -> None:
    """FR-370's receipts (FR-73): four keys on the panel-map rows the deck already writes.

    `source_image` already names the source slide the crop came from, so the paste adds no second
    path key — two answers to one question is how a gallery ends up linking a file that moved.
    """
    deck = build_deck(tmp_path)
    deck.folder.record.panel_map = [
        {"slide": number, "source_position": number, "source_text": f"line {number}",
         "source_image": f"source/post-a/slide_0{number}.jpg"} for number in (1, 2, 3)]
    await deck._store(2, landed(2), lost=True)

    rows = deck._paste_meta()

    pasted = next(row for row in rows if row["slide"] == 2)
    assert pasted["pasted"] is True and pasted["paste_ok"] is True
    assert pasted["paste_reason"] == ""
    assert pasted["paste_box"] == [0.05, 0.15, 0.88, 0.7]
    assert pasted["source_image"] == "source/post-a/slide_02.jpg"
    assert not any(key.endswith("_path") for key in pasted)
    plain = next(row for row in rows if row["slide"] == 3)
    assert plain["pasted"] is False and plain["paste_ok"] is True and plain["paste_box"] is None


def test_a_deck_that_ordered_no_plate_writes_the_pre_d65_panel_map(tmp_path: Path) -> None:
    """Nothing about a run with `screenshot_reuse: false` moves — not even a key (D58's shape)."""
    deck = build_deck(tmp_path, reuse=False)
    deck.folder.record.panel_map = [{"slide": 1, "source_position": 1, "source_text": "line 1"}]

    assert deck._paste_meta() == [{"slide": 1, "source_position": 1, "source_text": "line 1"}]


def test_the_three_brand_configs_pin_the_feature_and_the_engine_default_does_not() -> None:
    """FR-370's rollout: opt-in by default, on where the operator actually runs (D58's shape)."""
    from hypesocials.config import RunConfig, load_config

    assert RunConfig().screenshot_reuse is False
    for name in ("hypedigitaly", "hypedigitaly-cs", "hypedigitaly-fresh"):
        loaded = load_config(f"configs/{name}.yaml")
        cfg = loaded[0] if isinstance(loaded, tuple) else loaded
        assert cfg.run.screenshot_reuse is True, name
