"""`hypesocials.sources.logo_crops` — the mark's own pixels, cut out of the source slide (FR-315).

This module is the ONE Pillow user in the tree and the ONE door FR-244's amended carve-out opened
in the source store: `output/<run>/source/` stays analysis-and-display-only (D46), except for the
small logo patches written here into its `marks/` subfolder. What it buys is real — a render prompt
that only NAMES an obscure mark ("Higgsfield", "Flodesk", "Murf") gets a confident invention back —
and what it may cost is bounded, which is what this file pins:

* **the crop lands where the box said, with padding, inside the picture** — a patch that clips a
  wordmark's descenders is a reference the render model copies the clipping from, and a patch
  offset by a rounding error is the wrong pixels sent at full price;
* **the two size fences** — `_MIN_EDGE_PX` refuses a favicon's worth of noise (upstream,
  `slide_intel._box` refuses a "logo" spanning the whole panel), so what crosses the boundary is
  small enough to be a logo and big enough to be legible;
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
from hypesocials.sources.slide_intel import MarkBox

#: Big enough that `_MIN_EDGE_PX` (24) is a small fraction of it, so a box has to be deliberately
#: tiny to trip the floor rather than tripping it by accident of the fixture's size.
SLIDE_W, SLIDE_H = 400, 600


def make_slide(folder: Path, position: int = 1, *, ext: str = ".jpg",
               size: tuple[int, int] = (SLIDE_W, SLIDE_H), mode: str = "RGB") -> Path:
    """One stored source slide on disk, named the way `packager.source_slide_name` names them.

    The extension is a parameter because the store takes it from the CDN URL — a live deck is
    usually `.webp`, and a crop step that only looked for `.jpg` would find nothing on a real run.
    """
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"slide_{position:02d}{ext}"
    Image.new(mode, size, color=(200, 120, 40) if mode == "RGB" else 128).save(path)
    return path


def mark(name: str = "Notion", slide: int = 1,
         box: tuple[float, float, float, float] = (0.25, 0.5, 0.25, 0.1)) -> MarkBox:
    """One detected mark. The default box is 100x60 px on the standard fixture slide — comfortably
    over the `_MIN_EDGE_PX` floor, and away from every edge so the padding is unclamped."""
    return MarkBox(name=name, slide=slide, box=box)


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

    written = logo_crops.crop_marks(folder, [mark()])

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

    written = logo_crops.crop_marks(folder, [mark(box=(0.0, 0.0, 0.2, 0.1))])

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

    written = logo_crops.crop_marks(folder, [mark()])

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

    written = logo_crops.crop_marks(folder, [mark()])

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

    written = logo_crops.crop_marks(folder, [mark(box=(0.5, 0.5, 0.02, 0.02))])

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

    written = logo_crops.crop_marks(folder, [mark("Figma", slide=2), mark("Notion", slide=1)])

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

    written = logo_crops.crop_marks(folder, [mark()])

    assert written == {}
    assert "logo_crop_failed" in caplog.text and "Notion" in caplog.text


def test_an_empty_mark_list_and_a_missing_folder_are_both_quiet_no_ops(tmp_path: Path) -> None:
    """No boxes is the COMMON case — most decks show no third-party mark at all — so it may not
    warn, may not create a folder and may not cost anything. A folder that does not exist behaves
    the same way for the same reason: every mark in it fails the stored-slide test."""
    assert logo_crops.crop_marks(tmp_path / "source" / "p1", []) == {}
    assert logo_crops.crop_marks(tmp_path / "nope", [mark()]) == {}
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
        logo_crops.crop_marks(None, [mark()])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="got list"):
        logo_crops.crop_marks(["source", "p1"], [mark()])  # type: ignore[arg-type]


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
                 mark("Figma", 2)])

    assert sorted(written) == ["Figma", "Notion"]
    assert len(list((folder / logo_crops.MARKS_DIR).iterdir())) == 2
    with Image.open(written["Notion"]) as image:
        assert image.size == (124, 74), "the FIRST box's geometry, not the second's"


def test_two_marks_whose_names_slug_the_same_get_separate_files(tmp_path: Path) -> None:
    """A mark name is source-controlled text becoming a Windows path, so it is reduced to
    `[a-z0-9-]` and capped — which means "Claude!" and "claude" collapse onto one slug.

    They are still two different marks, and a patch that silently overwrote another mark's pixels
    would put the wrong logo on a slide with no warning anywhere. The taken slug takes a `-2`.
    """
    folder = tmp_path / "source" / "p1"
    make_slide(folder)

    written = logo_crops.crop_marks(folder, [mark("Claude!"), mark("claude"), mark("CLAUDE")])

    assert sorted(written) == ["CLAUDE", "Claude!", "claude"]
    assert sorted(path.name for path in written.values()) == [
        "claude-2.png", "claude-3.png", "claude.png"]
    assert len({path for path in written.values()}) == 3, "three marks, three files"


def test_a_name_that_reduces_to_nothing_still_gets_a_usable_filename(tmp_path: Path) -> None:
    """Emoji, punctuation and CJK all reduce to an empty slug, and an empty filename is a crash on
    a paid run. The fallback is the literal `mark`, uniquified like any other collision — the mark
    is still keyed by its real name in the returned mapping, so nothing downstream is confused."""
    folder = tmp_path / "source" / "p1"
    make_slide(folder)

    written = logo_crops.crop_marks(folder, [mark("★"), mark("✦")])

    assert sorted(written) == ["★", "✦"]
    assert sorted(path.name for path in written.values()) == ["mark-2.png", "mark.png"]
