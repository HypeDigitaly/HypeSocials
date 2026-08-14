"""Logo patches: the mark's own pixels, cut out of the source slide it was seen on (FR-315, D48).

Module contract
---------------
Purpose: a render prompt that NAMES a tool mark gets an invention back. "Higgsfield", "Flodesk",
"Murf", "Cursor" — the model has no reliable picture of an obscure logo, so it draws a plausible
one, and the slide ships with a mark that is confidently wrong. The fix is pixels: the vision pass
returns each mark's bounding box (`slide_intel.MarkBox`, FR-306 amendment), this module cuts that
rectangle out of the slide already stored in `output/<run>/source/<post_id>/`, and the small PNG
rides along to the render as a reference with a copy-it-exactly role line.

Public API:
    crop_marks(source_dir, marks) -> {mark name: written patch path}

**Scope, deliberately tiny (D48).** This is the ONLY module in the codebase that uses Pillow, and
cropping is the ONLY thing it does with it — no resizing, no re-encoding of anything but the crop,
no colour work, no thumbnails, no composition. Pillow came back as a dependency for this one job
after the topic-first pivot removed it (D41–D45); anything else that wants to touch pixels is a new
decision, not an extension of this one.

**The carve-out boundary lives here.** `output/<run>/source/` is analysis-and-display-only (D46),
and D48 opened exactly one door in it: FR-244 as amended sanctions *small logo/tool-mark patches*
as render references and nothing else. Full slides, panels and any other crop remain forbidden, and
no Virlo CDN URL may ever appear in a render payload. Two things keep that door narrow — upstream,
`slide_intel._box()` refuses a "logo" spanning more than 90% of the slide; here, `_MIN_EDGE_PX`
refuses a patch too small to be a mark at all. What crosses the boundary is a rectangle small
enough to be a logo and big enough to be legible, written to its own `marks/` subfolder so the
sanctioned files are separable from the archive by path alone.

**Fail-open per mark (FR-315d).** A missing slide file, an unreadable image, a box that lands off
the picture, a crop the size of a postage stamp — each costs THAT mark its patch and nothing else.
The mark still renders from its name plus its written description, which is the documented
fallback, and the deck still ships. `crop_marks` therefore never raises for a bad mark; it raises
only for a caller that hands it the wrong type, which is a bug in the caller, not a bad detection.

**Synchronous on purpose, and the caller owns that.** Opening and cropping a slide is file I/O plus
a small decode — real work on the event loop, even if it is milliseconds. Callers run it off-thread:

    patches = await asyncio.to_thread(logo_crops.crop_marks, folder, intel.mark_boxes)

Do not: upload anything (that is `generate/refs.py`'s seam), decide WHICH marks are sanctioned
(FR-310 does, upstream), write into a run folder other than the post's own source store, or reach
for Pillow anywhere else in the tree.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from hypesocials.sources.slide_intel import MarkBox

logger = logging.getLogger(__name__)

#: Where patches land inside the post's own source store: `source/<post_id>/marks/<slug>.png`.
#: A subfolder rather than a filename prefix so the ONE sanctioned-for-upload class of file in the
#: whole archive is identifiable by path — `generate/refs.py` refuses a source-store upload that is
#: not under it, and a reviewer can answer "what did we send Kie from source/" with `ls`.
MARKS_DIR = "marks"

#: Breathing room around the box, as a fraction of the box's own size, added on each side. A vision
#: model brackets the glyphs, not the mark: a wordmark's descenders, an icon's outer ring and the
#: gap that makes a logo readable all sit just outside a tight box, and a patch that clips them is
#: a reference the render model copies the clipping from.
_PAD = 0.12

#: A patch shorter than this in either direction cannot carry a legible mark — it is a favicon's
#: worth of pixels, and attaching it teaches the render model noise. Skipped with a warning, which
#: puts the mark on FR-315d's name-plus-description fallback.
_MIN_EDGE_PX = 24

#: Slide extensions the source store actually writes (`packager.source_slide_name` takes the
#: extension from the CDN URL). `.webp` is the common live case, not an exotic one.
_SLIDE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_SLUG_MAX = 48  # MAX_PATH headroom under `output/<run>/source/<post_id>/marks/`


def crop_marks(source_dir: Path, marks: Sequence[MarkBox]) -> dict[str, Path]:
    """Cut each mark's pixels out of its slide and write them as PNG patches (FR-315).

    Args:
        source_dir: this post's source store — `output/<run>/source/<post_id>/`, the folder
            holding `slide_NN.<ext>`. Patches are written to its `marks/` subfolder, which is
            created on demand.
        marks: the deck's `MarkBox` list from the vision pass (`SlideIntel.mark_boxes`), already
            range-clamped and span-checked upstream. An empty sequence is a no-op, and it is the
            common case — most decks show no third-party mark at all.

    Returns:
        `{mark name: patch path}` for the marks that produced a usable patch, and only those. A
        name absent from the mapping is a mark with no pixels, which callers read as FR-315d's
        fallback: render it from its name and its written description. The first mark to claim a
        name wins — the same logo boxed on eight slides is one patch, one upload, eight uses.

    Raises:
        TypeError: `source_dir` is not a path. That is a programmer error; every FAILURE MODE OF
            THE DATA — a slide that is not on disk, an image Pillow cannot read, a box that crops
            to nothing — is logged at WARNING and skipped, never raised (§0.14c, FR-315d).
    """
    if not isinstance(source_dir, (str, Path)):
        raise TypeError(f"source_dir must be a path, got {type(source_dir).__name__}")
    folder = Path(source_dir)
    written: dict[str, Path] = {}
    used: set[str] = set()
    for mark in marks:
        if mark.name in written:
            continue  # one patch per distinct mark, however many slides carried it
        if (path := _crop_one(folder, mark, used)) is not None:
            written[mark.name] = path
    return written


def _crop_one(folder: Path, mark: MarkBox, used: set[str]) -> Path | None:
    """One mark, from slide file to written PNG — or `None`, warned, for every way it can fail."""
    slide = _slide_file(folder, mark.slide)
    if slide is None:
        logger.warning("logo_crop_skipped: mark %r names source slide %d, which is not stored in "
                       "%s — the mark renders from its name and description (FR-315d)",
                       mark.name, mark.slide, folder.name)
        return None
    try:
        with Image.open(slide) as image:
            image.load()
            region = _pixel_box(mark.box, image.width, image.height)
            if region is None:
                logger.warning("logo_crop_skipped: mark %r crops to %d×%d px on slide %d — under "
                               "the %d px floor, so the patch would be noise, not a logo",
                               mark.name, *_span(mark.box, image.width, image.height), mark.slide,
                               _MIN_EDGE_PX)
                return None
            patch = image.crop(region)
            if patch.mode not in ("RGB", "RGBA"):
                # Palette and CMYK slides exist; PNG wants a mode it can write without guessing.
                patch = patch.convert("RGBA" if "A" in patch.getbands() else "RGB")
            target = _patch_path(folder, mark.name, used)
            target.parent.mkdir(parents=True, exist_ok=True)
            patch.save(target, format="PNG")
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        # Pillow's failure surface is wide (truncated download, unsupported webp variant, a full
        # disk on save) and every branch of it means the same thing here: no patch for this mark.
        logger.warning("logo_crop_failed: mark %r on slide %d of %s could not be cropped (%s: %s) "
                       "— the mark renders from its name and description (FR-315d)",
                       mark.name, mark.slide, folder.name, type(exc).__name__, str(exc)[:200])
        return None
    logger.debug("logo_crop: %r -> %s", mark.name, target.name)
    return target


def _slide_file(folder: Path, position: int) -> Path | None:
    """`slide_NN.<ext>` for that 1-based source position, whichever extension it was stored with.

    The store names a slide after the CDN URL's own suffix (`packager.source_slide_name`), so a
    live deck is usually `.webp` and a hardcoded `.jpg` finds nothing. Tried in a fixed order so
    the answer is deterministic when two encodings of one slide somehow coexist.
    """
    stem = f"slide_{int(position):02d}"
    return next((candidate for ext in _SLIDE_EXTS
                 if (candidate := folder / f"{stem}{ext}").is_file()), None)


def _pixel_box(
    box: tuple[float, float, float, float], width: int, height: int
) -> tuple[int, int, int, int] | None:
    """The padded fractional box as pixel `(left, top, right, bottom)`, or `None` if it is too small.

    Padding is added on each side and then CLAMPED to the image, so a mark sitting against the
    slide's edge keeps whatever padding fits instead of losing the crop. The floor is applied after
    clamping, because the size that matters is the size of the pixels actually cut.
    """
    x, y, box_w, box_h = box
    pad_x, pad_y = box_w * _PAD, box_h * _PAD
    left = max(0, int(round((x - pad_x) * width)))
    top = max(0, int(round((y - pad_y) * height)))
    right = min(width, int(round((x + box_w + pad_x) * width)))
    bottom = min(height, int(round((y + box_h + pad_y) * height)))
    if right - left < _MIN_EDGE_PX or bottom - top < _MIN_EDGE_PX:
        return None
    return (left, top, right, bottom)


def _span(box: tuple[float, float, float, float], width: int, height: int) -> tuple[int, int]:
    """The crop's would-be pixel size, for the warning that explains why it was refused."""
    return (int(round(box[2] * (1 + 2 * _PAD) * width)),
            int(round(box[3] * (1 + 2 * _PAD) * height)))


def _patch_path(folder: Path, name: str, used: set[str]) -> Path:
    """`marks/<slug>.png` for this mark, unique within the post's store.

    The slug is the mark's own name reduced to a filename — source-controlled text becoming a
    Windows path, so everything outside `[a-z0-9-]` goes and the length is capped. Two different
    names can still collapse onto one slug ("Claude!" and "claude"), so a taken slug takes a `-2`,
    `-3` … suffix rather than overwriting a patch that belongs to another mark.
    """
    slug = _SLUG_STRIP.sub("-", name.lower()).strip("-")[:_SLUG_MAX].strip("-") or "mark"
    unique, serial = slug, 1
    while unique in used:
        serial += 1
        unique = f"{slug}-{serial}"
    used.add(unique)
    return folder / MARKS_DIR / f"{unique}.png"


__all__ = ["MARKS_DIR", "crop_marks"]
