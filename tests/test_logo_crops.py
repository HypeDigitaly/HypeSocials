"""`hypesocials.sources.logo_crops` — the mark's own pixels, cut out of the source slide (FR-315).

This module is the ONE Pillow user in the tree and the ONE door FR-244's amended carve-out opened
in the source store: `output/<run>/source/` stays analysis-and-display-only (D46), except for the
small logo patches written here into its `marks/` subfolder. What it buys is real — a render prompt
that only NAMES an obscure mark ("Higgsfield", "Flodesk", "Murf") gets a confident invention back —
and what it may cost is bounded, which is what this file pins:

* **the crop lands where the box said, with padding, inside the picture** — a patch that clips a
  wordmark's descenders is a reference the render model copies the clipping from, and a patch
  offset by a rounding error is the wrong pixels sent at full price;
* **the allowlist comes FIRST** (v2.2.0) — a mark this deck may not name is never cropped, never
  written and therefore never uploadable. Run `…_m39f` cropped and uploaded a patch of a creator's
  Nike hoodie because the sanction test lived only at the attach step, downstream of the file and
  the upload it was supposed to prevent;
* **the fences on the pixels themselves** — `_MIN_EDGE_PX` refuses a favicon's worth of noise
  (upstream, `slide_intel._box` refuses a "logo" spanning the whole panel) and the variance floor
  refuses a patch that is one flat colour, so what crosses the boundary is small enough to be a
  logo, big enough to be legible, and a picture of something;
* **the letterbox fallback** — a box that lands on the black bars of an inset slide is re-read
  against the visible content rectangle, but only AFTER the full-frame reading has failed, because
  remapping a box that was already right is how you break the ordinary case to fix the rare one;
* **fail-open PER MARK, never per deck** (FR-315d) — a slide that is not on disk, an unreadable
  file, a crop under the floor: each costs THAT mark its patch, logs a warning, and leaves the
  mark rendering from its name plus its written description;
* **one patch per distinct mark** — the same logo boxed on eight panels is one file, one upload
  and eight uses (FR-200/FR-244), and two different names that slug the same never overwrite each
  other;
* **the one thing that DOES raise** — a caller handing over something that is not a path. That is
  a programmer error, and it is deliberately not swallowed alongside the data failures.

Everything is synthesized: real PNG/JPEG/WEBP bytes written by Pillow into `tmp_path`, no run, no
network, no `output/` folder. The images are a few hundred pixels on a side so a fractional box
maps to a countable number of real pixels and the assertions can be exact.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from hypesocials.sources import logo_crops
from hypesocials.sources.mark_names import collapse, mark_name
from hypesocials.sources.slide_intel import MarkBox

#: Big enough that `_MIN_EDGE_PX` (24) is a small fraction of it, so a box has to be deliberately
#: tiny to trip the floor rather than tripping it by accident of the fixture's size.
SLIDE_W, SLIDE_H = 400, 600


def make_slide(folder: Path, position: int = 1, *, ext: str = ".jpg",
               size: tuple[int, int] = (SLIDE_W, SLIDE_H), mode: str = "RGB",
               bars: int = 0, flat: bool = False) -> Path:
    """One stored source slide on disk, named the way `packager.source_slide_name` names them.

    The extension is a parameter because the store takes it from the CDN URL — a live deck is
    usually `.webp`, and a crop step that only looked for `.jpg` would find nothing on a real run.

    The picture is TEXTURED — a grid of alternating blocks — rather than one flat colour, because
    the variance floor refuses a flat crop and a flat fixture would make every assertion below a
    test of that refusal instead of of the thing it is about. `bars` paints a letterbox: `bars`
    pixels of black at the top and the bottom, with the texture squeezed into what is left, which
    is the shape of every inset slideshow slide. `flat` is the opposite fixture — one colour edge
    to edge — for the tests that are about the floor.
    """
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"slide_{position:02d}{ext}"
    width, height = size
    image = Image.new(mode, size, color=(0, 0, 0) if mode == "RGB" else 0)
    if not flat:
        block = 16
        for top in range(bars, height - bars, block):
            for left in range(0, width, block):
                light = ((left // block) + (top // block)) % 2 == 0
                image.paste((230, 210, 190) if mode == "RGB" else 230,
                            (left, top, min(left + block, width),
                             min(top + block, height - bars)))
                if not light:
                    image.paste((40, 60, 120) if mode == "RGB" else 60,
                                (left + 3, top + 3, min(left + block - 3, width),
                                 min(top + block - 3, height - bars)))
    elif mode == "RGB":
        image.paste((200, 120, 40), (0, 0, width, height))
    image.save(path)
    return path


def mark(name: str = "Notion", slide: int = 1,
         box: tuple[float, float, float, float] = (0.25, 0.5, 0.25, 0.1)) -> MarkBox:
    """One detected mark. The default box is 100x60 px on the standard fixture slide — comfortably
    over the `_MIN_EDGE_PX` floor, and away from every edge so the padding is unclamped."""
    return MarkBox(name=name, slide=slide, box=box)


def allow(*names: str) -> list[str]:
    """The deck's sanctioned marks, collapsed the way `carousel._crop_patches` collapses them.

    Callers pass COLLAPSED keys (`mark_names.collapse(mark_name(x))`), which is what makes
    "Notion", "Notion logo" and "NOTION LOGO/WORDMARK" one sanctioned mark rather than three.
    """
    return [collapse(mark_name(name)) for name in (names or ("Notion",))]


# --------------------------------------------------------------------------- the happy path


def test_a_detected_mark_becomes_a_padded_png_under_the_posts_own_marks_folder(
    tmp_path: Path,
) -> None:
    """FR-315: the patch lands in `marks/`, as a PNG, padded on every side and inside the picture.

    The folder matters as much as the pixels. `refs.upload_local` refuses a source-store path that
    is not under `marks/`, so writing the patch anywhere else in the store would make it unsendable
    — and putting the ONE sanctioned-for-upload class of file behind its own path segment is what
    lets a reviewer answer "what did we send Kie out of source/" with `ls`.
    """
    folder = tmp_path / "source" / "7412998877"
    make_slide(folder)

    written = logo_crops.crop_marks(folder, [mark()], allow())

    assert list(written) == ["Notion"]
    patch = written["Notion"]
    assert patch == folder / logo_crops.MARKS_DIR / "notion.png"
    assert patch.is_file()
    with Image.open(patch) as image:
        assert image.format == "PNG"
        # 0.25 wide of 400 px is 100, plus 12% padding on each side => 124; likewise 60 -> ~74.
        assert image.size == (124, 74)
        assert image.width >= logo_crops._MIN_EDGE_PX
        assert image.height >= logo_crops._MIN_EDGE_PX


def test_a_mark_against_the_slides_corner_keeps_the_padding_that_fits(tmp_path: Path) -> None:
    """A box at the origin cannot be padded outwards, and the crop CLAMPS rather than failing.

    A logo in the corner is the commonest placement there is (it is where a watermark and a
    lockup both live), so "the padding did not fit" must cost the padding, never the patch. The
    clamp also has to hold the crop inside the image — Pillow will happily crop a negative box and
    hand back a patch with a transparent margin the render model then copies.
    """
    folder = tmp_path / "source" / "p1"
    make_slide(folder)

    written = logo_crops.crop_marks(folder, [mark(box=(0.0, 0.0, 0.2, 0.1))], allow())

    with Image.open(written["Notion"]) as image:
        # 80x60 px at the origin: no padding fits on the left or the top, 12% fits on the other
        # two sides, and nothing lands outside the picture.
        assert image.size == (90, 67)


@pytest.mark.parametrize("ext", [".jpg", ".jpeg", ".png", ".webp"])
def test_the_crop_finds_the_slide_under_whichever_extension_the_store_wrote(
    tmp_path: Path, ext: str,
) -> None:
    """`packager.source_slide_name` takes the extension from the CDN URL, so `.webp` is the common
    live case rather than an exotic one. A hardcoded `.jpg` here would silently return no patches
    on most real decks and report it as "the mark had no pixels"."""
    folder = tmp_path / "source" / "p1"
    make_slide(folder, ext=ext)

    written = logo_crops.crop_marks(folder, [mark()], allow())

    assert list(written) == ["Notion"]


def test_a_palette_or_greyscale_slide_still_writes_a_png_the_uploader_can_send(
    tmp_path: Path,
) -> None:
    """Palette and CMYK slides exist in the wild, and PNG wants a mode it can write without
    guessing. The conversion happens on the patch rather than on the slide, so nothing in the
    archive is rewritten — the source store is provenance and stays byte-identical to what the CDN
    served."""
    folder = tmp_path / "source" / "p1"
    original = make_slide(folder, mode="L")

    written = logo_crops.crop_marks(folder, [mark()], allow())

    with Image.open(written["Notion"]) as image:
        assert image.mode in ("RGB", "RGBA")
    with Image.open(original) as image:
        assert image.mode == "L", "the stored slide was not rewritten"


# ------------------------------------------------------------ FR-315d: fail-open, per mark


def test_a_crop_under_the_legibility_floor_is_skipped_with_a_line_and_no_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A patch smaller than `_MIN_EDGE_PX` in either direction is a favicon's worth of pixels:
    attaching it teaches the render model noise, at the price of an upload and a reference slot.

    The mark is not lost — it renders from its name and the template's written description, which
    is FR-315d's documented fallback — so the skip is a WARNING with a reason, and no file is
    written for a caller to find later and wonder about.
    """
    folder = tmp_path / "source" / "p1"
    make_slide(folder)
    caplog.set_level("WARNING", logger="hypesocials.sources.logo_crops")

    written = logo_crops.crop_marks(folder, [mark(box=(0.5, 0.5, 0.02, 0.02))], allow())

    assert written == {}
    assert not (folder / logo_crops.MARKS_DIR).exists(), "no folder for a patch that never was"
    assert "logo_crop_skipped" in caplog.text
    assert "px floor" in caplog.text and "Notion" in caplog.text


def test_a_mark_naming_a_slide_that_was_never_stored_costs_that_mark_alone(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """§0.14c case b: one slide 404'd on the source CDN, so its file is simply not in the store.

    The mark boxed on it has nowhere to crop from — and every OTHER mark still gets its pixels.
    That is the shape of every failure in this module: a loss is local, named, and never allowed
    to become a deck-wide degrade.
    """
    folder = tmp_path / "source" / "p1"
    make_slide(folder, 1)  # slide 2 never downloaded
    caplog.set_level("WARNING", logger="hypesocials.sources.logo_crops")

    written = logo_crops.crop_marks(
        folder, [mark("Figma", slide=2), mark("Notion", slide=1)], allow("Figma", "Notion"))

    assert list(written) == ["Notion"], "the reachable mark is unaffected by its neighbour"
    assert "logo_crop_skipped" in caplog.text and "Figma" in caplog.text
    assert "which is not stored" in caplog.text


def test_a_file_pillow_cannot_read_is_warned_and_skipped_rather_than_raised(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """A truncated download, an unsupported webp variant, a zero-byte file: Pillow's failure
    surface is wide and every branch of it means one thing here — no patch for this mark.

    `crop_marks` is called on a run the operator has already approved spending on, so it may not
    raise for bad DATA. It may only raise for a bad CALLER, which is the test below.
    """
    folder = tmp_path / "source" / "p1"
    folder.mkdir(parents=True)
    (folder / "slide_01.jpg").write_bytes(b"not a jpeg at all, just some bytes")
    caplog.set_level("WARNING", logger="hypesocials.sources.logo_crops")

    written = logo_crops.crop_marks(folder, [mark()], allow())

    assert written == {}
    assert "logo_crop_failed" in caplog.text and "Notion" in caplog.text


def test_an_empty_mark_list_and_a_missing_folder_are_both_quiet_no_ops(tmp_path: Path) -> None:
    """No boxes is the COMMON case — most decks show no third-party mark at all — so it may not
    warn, may not create a folder and may not cost anything. A folder that does not exist behaves
    the same way for the same reason: every mark in it fails the stored-slide test."""
    assert logo_crops.crop_marks(tmp_path / "source" / "p1", [], allow()) == {}
    assert logo_crops.crop_marks(tmp_path / "nope", [mark()], allow()) == {}
    assert not (tmp_path / "source").exists()


def test_a_source_dir_that_is_not_a_path_raises_because_that_is_a_caller_bug(
    tmp_path: Path,
) -> None:
    """The ONE exception this module raises, and the line between the two kinds of wrong.

    Every failure of the DATA — a missing slide, an unreadable image, a box that crops to nothing —
    is logged and skipped, because the run has already paid for the deck. A caller passing a
    `SlideIntel`, a list or `None` where a path belongs is a defect in the caller that would
    otherwise surface as an empty patch table and a deck of hallucinated logos.
    """
    with pytest.raises(TypeError, match="source_dir must be a path"):
        logo_crops.crop_marks(None, [mark()], allow())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="got list"):
        logo_crops.crop_marks(["source", "p1"], [mark()], allow())  # type: ignore[arg-type]


# ------------------------------------------------------------------- one patch per distinct mark


def test_the_same_mark_boxed_on_two_slides_is_cropped_once(tmp_path: Path) -> None:
    """FR-200/FR-244: a logo the vision pass boxed on every panel of an eight-slide deck is the
    same logo eight times. One crop, one file, one upload, eight uses — and the FIRST box wins, so
    the patch is deterministic rather than depending on which panel happened to be read last."""
    folder = tmp_path / "source" / "p1"
    make_slide(folder, 1)
    make_slide(folder, 2)

    written = logo_crops.crop_marks(
        folder, [mark("Notion", 1, (0.25, 0.5, 0.25, 0.1)),
                 mark("Notion", 2, (0.10, 0.1, 0.40, 0.2)),  # a different box, same mark
                 mark("Figma", 2)], allow("Notion", "Figma"))

    assert sorted(written) == ["Figma", "Notion"]
    assert len(list((folder / logo_crops.MARKS_DIR).iterdir())) == 2
    with Image.open(written["Notion"]) as image:
        assert image.size == (124, 74), "the FIRST box's geometry, not the second's"


def test_the_dedupe_key_is_the_collapsed_name_and_the_returned_key_is_the_raw_one(
    tmp_path: Path,
) -> None:
    """The v2.2.0 amendment (audit defect #6), and the contract that comes with it.

    Until this wave the dedupe was keyed on the RAW detected name while the caller's patch table
    was keyed on the COLLAPSED one — so "Claude", "claude logo" and "CLAUDE LOGO/WORDMARK" became
    three crops and three Kie uploads that `carousel._crop_patches` then merged back into a single
    table entry, two of them paid for and immediately discarded. One mark is now one crop, one
    file, one upload, and the FIRST box wins so the geometry is deterministic.

    The RETURN keys stay raw on purpose: the caller collapses them itself on the way into the deck
    (that is the join), and it needs the original spelling to name the upload and to log with. The
    two spellings are deliberately different things and this test is where that is written down.
    """
    folder = tmp_path / "source" / "p1"
    make_slide(folder)

    written = logo_crops.crop_marks(
        folder, [mark("Claude"), mark("claude logo"), mark("CLAUDE LOGO/WORDMARK")],
        allow("Claude"))

    assert list(written) == ["Claude"], "one mark, however many spellings it was boxed under"
    assert [path.name for path in written.values()] == ["claude.png"]
    assert len(list((folder / logo_crops.MARKS_DIR).iterdir())) == 1, "one file, one upload"
    assert collapse(mark_name("CLAUDE LOGO/WORDMARK")) == collapse(mark_name(*written)) == "claude"


def test_two_marks_whose_names_slug_the_same_get_separate_files(tmp_path: Path) -> None:
    """A mark name is source-controlled text becoming a Windows path, so the FILENAME is reduced to
    `[a-z0-9-]` and capped — while the IDENTITY key (`collapse`) keeps every alphanumeric it has.

    Two CJK marks are therefore two different marks that slug to the same empty string, and an
    empty filename is a crash on a paid run. The fallback is the literal `mark`, uniquified with a
    `-2` like any other collision, rather than one mark's pixels silently overwriting another's —
    which would put the wrong logo on a slide with no warning anywhere. Both are still keyed by
    their real names in the returned mapping, so nothing downstream is confused.
    """
    folder = tmp_path / "source" / "p1"
    make_slide(folder)

    written = logo_crops.crop_marks(folder, [mark("日本語"), mark("한국어")],
                                    allow("日本語", "한국어"))

    assert sorted(written) == ["日本語", "한국어"]
    assert sorted(path.name for path in written.values()) == ["mark-2.png", "mark.png"]
    assert len({path for path in written.values()}) == 2, "two marks, two files"


def test_a_mark_with_no_nameable_brand_is_never_cropped(tmp_path: Path) -> None:
    """"★", "logo", "" — a box whose brand the vision pass could not name collapses to nothing.

    `mark_names` is explicit that an empty collapsed key means "never sanction this", and it cannot
    match an allowlist entry either, so such a mark has no route to a patch. The alternative is a
    file named `mark.png` uploaded as a reference for a logo nobody can name, which is an invention
    bought at full price — exactly what FR-315 exists to prevent.
    """
    folder = tmp_path / "source" / "p1"
    make_slide(folder)

    written = logo_crops.crop_marks(folder, [mark("★"), mark("logo"), mark("")],
                                    allow("Notion", "★", "logo"))

    assert written == {}
    assert not (folder / logo_crops.MARKS_DIR).exists(), "no folder for a patch that never was"


# ------------------------------------------------------- the allowlist, the floor, the letterbox


def test_a_mark_this_deck_may_not_name_is_never_cropped_and_never_written(
    tmp_path: Path,
) -> None:
    """Audit defect #6, in one test: the sanction test now runs BEFORE Pillow, not after the upload.

    Run `…_m39f` boxed "Nike" on a creator's hoodie, cropped it, wrote it into `marks/` and uploaded
    it to Kie — and only then did the attach step notice that no slide of that deck was allowed to
    name Nike. The patch cost a decode, a file, an upload and a reference slot, and no slide could
    ever have used it. `allow` is the deck's whole sanctioned set (the union over its slides), and
    a mark outside it never becomes a file at all.
    """
    folder = tmp_path / "source" / "p1"
    make_slide(folder)

    written = logo_crops.crop_marks(folder, [mark("Nike"), mark("Notion")], allow("Notion"))

    assert list(written) == ["Notion"], "the sanctioned mark is unaffected by its neighbour"
    assert [path.name for path in (folder / logo_crops.MARKS_DIR).iterdir()] == ["notion.png"]


def test_an_empty_allowlist_crops_nothing_at_all(tmp_path: Path) -> None:
    """Fail-closed, and it is the same rule as above rather than a special case: a deck that
    sanctions no mark has no mark to draw, so a patch could only be an upload nothing can use."""
    folder = tmp_path / "source" / "p1"
    make_slide(folder)

    assert logo_crops.crop_marks(folder, [mark(), mark("Figma")], []) == {}
    assert not (folder / logo_crops.MARKS_DIR).exists()


def test_a_crop_that_comes_back_as_flat_colour_is_refused(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """The variance floor (v2.2.0): a patch that is one flat colour is not a picture of a mark.

    Measured on run `…_m39f`, where two boxes landed in a slide's black letterbox bar and produced
    two near-identical black rectangles — uploaded at full price as "the Claude logo" and "the
    OpenAI logo". Plain stddev does not separate that case (a black bar with one bright sliver
    scores higher than a genuine low-contrast pastel logo); the share of a single grey bucket does.

    Here there is no letterbox to fall back to, so the refusal is final and the mark drops onto
    FR-315d's name-plus-description fallback with a line saying why.
    """
    folder = tmp_path / "source" / "p1"
    make_slide(folder, flat=True)
    caplog.set_level("WARNING", logger="hypesocials.sources.logo_crops")

    written = logo_crops.crop_marks(folder, [mark()], allow())

    assert written == {}
    assert not (folder / logo_crops.MARKS_DIR).exists()
    assert "logo_crop_skipped" in caplog.text and "flat colour" in caplog.text


def test_a_box_that_lands_on_the_letterbox_is_re_read_against_the_content_rect(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """The FALLBACK, and the reason it is only ever a fallback.

    A vision model shown a letterboxed slide reports what it SAW — coordinates over the visible
    picture, not over the canvas the picture is pasted into. On run `…_m39f` slide 1 of post
    `48aab562…` is a 1124x2000 canvas whose picture occupies the middle ~72%, and its two marks at
    `y = 0.86` therefore landed 240 px inside the black bottom bar. Re-read against the content
    rectangle, the same two boxes land on the Claude asterisk and the OpenAI knot.

    The full-frame reading is still tried FIRST and kept whenever it is usable: on the four decks
    of that same run with no letterbox, the full-frame crops are the correct logos, and remapping
    them would have moved every one of them off its mark to fix a case they do not have.
    """
    folder = tmp_path / "source" / "p1"
    make_slide(folder, bars=120)  # 120 px of black top and bottom of a 600 px slide
    caplog.set_level("INFO", logger="hypesocials.sources.logo_crops")

    written = logo_crops.crop_marks(folder, [mark(box=(0.3, 0.93, 0.2, 0.06))], allow())

    assert list(written) == ["Notion"], "the mark keeps its pixels instead of its black bar"
    assert "logo_crop_remapped" in caplog.text
    with Image.open(written["Notion"]) as image:
        assert image.size >= (logo_crops._MIN_EDGE_PX, logo_crops._MIN_EDGE_PX)
        assert logo_crops._crop_valid(image), "the remapped patch is a picture, not a bar"
