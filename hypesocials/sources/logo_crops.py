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
    crop_marks(source_dir, marks, allow) -> {mark name: written patch path}

**The allowlist is not optional (v2.2.0).** `allow` is the set of COLLAPSED sanctioned mark names
the caller has already decided may be drawn on this deck (FR-310), and a box whose mark is not in
it is never cropped, never written and therefore never uploadable. Until this wave the sanction
test lived only at the ATTACH step: every one of a deck's ≤24 detected boxes was cut out of the
source slide and pushed through the Kie upload seam, and only then was the patch table filtered by
what the slide was allowed to name. The 08-14 audit found the cost of that ordering on run
`…_m39f` — a patch of a creator's *hoodie*, cropped and uploaded because the vision pass labelled
the garment "Nike" — which is paid traffic out of the source store for pixels no slide could ever
use. Sanction first, crop second; that ordering is what makes the D48 carve-out as narrow as
FR-244 says it is.

**Scope, deliberately tiny (D48).** This is the ONLY module in the codebase that uses Pillow, and
cropping is the ONLY thing it does with it — no resizing, no re-encoding of anything but the crop,
no colour work, no thumbnails, no composition. Pillow came back as a dependency for this one job
after the topic-first pivot removed it (D41–D45); anything else that wants to touch pixels is a new
decision, not an extension of this one.

**The carve-out boundary lives here.** `output/<run>/source/` is analysis-and-display-only (D46),
and D48 opened exactly one door in it: FR-244 as amended sanctions *small logo/tool-mark patches*
as render references and nothing else. Full slides, panels and any other crop remain forbidden, and
no Virlo CDN URL may ever appear in a render payload. Four things keep that door narrow — upstream,
`slide_intel._box()` refuses a "logo" spanning more than 90% of the slide and `_mark_boxes()` keeps
only marks the vision pass classified as TOOL logos; here, `allow` refuses a mark no slide of this
deck may name, and `_crop_valid` refuses a patch too small to be a mark or too flat to be a picture
of one. What crosses the boundary is a rectangle small enough to be a logo, big enough to be
legible, carrying actual pixels, and named by a mark the deck was already going to draw — written
to its own `marks/` subfolder so the sanctioned files are separable from the archive by path alone.

**Fail-open per mark (FR-315d).** A missing slide file, an unreadable image, a box that lands off
the picture, a crop the size of a postage stamp, a crop that came back as flat colour — each costs
THAT mark its patch and nothing else.
The mark still renders from its name plus its written description, which is the documented
fallback, and the deck still ships. `crop_marks` therefore never raises for a bad mark; it raises
only for a caller that hands it the wrong type, which is a bug in the caller, not a bad detection.

**Synchronous on purpose, and the caller owns that.** Opening and cropping a slide is file I/O plus
a small decode — real work on the event loop, even if it is milliseconds. Callers run it off-thread:

    patches = await asyncio.to_thread(logo_crops.crop_marks, folder, intel.mark_boxes, allowed)

Do not: upload anything (that is `generate/refs.py`'s seam), decide WHICH marks are sanctioned
(FR-310 does, upstream), write into a run folder other than the post's own source store, or reach
for Pillow anywhere else in the tree.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from hypesocials.sources.mark_names import collapse, mark_name
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

#: Grey levels per bucket, and the share of one bucket at which a patch stops being a picture of
#: anything. Measured on run `…_m39f`, whose black-letterbox crops sat at 0.978 of a single bucket
#: while every real logo patch in the same run — including two low-contrast pastel marks the
#: content-rect fallback recovered — sat at 0.86 or below. 0.95 is the gap, with the tolerance on
#: the side of KEEPING a patch: a false "uniform" only sends the mark down the content-rect retry
#: and, if that fails too, back onto FR-315d's name-plus-description fallback, which is where it
#: would have been anyway.
_UNIFORM_BUCKET = 16
_UNIFORM_SHARE = 0.95

#: The content-rect probe (a `_PROBE`×`_PROBE` area-averaged thumbnail). `_BAR_SPREAD` is the
#: grey-level spread within one probe row/column that still reads as a flat letterbox bar, and
#: `_MIN_BAR` is the fraction of the frame the bars must eat before the picture counts as
#: letterboxed at all — a slide with a plain margin is not a letterbox, and remapping against one
#: would move a box that was already correct.
_PROBE = 64
_BAR_SPREAD = 8
_MIN_BAR = 0.04


def crop_marks(
    source_dir: Path, marks: Sequence[MarkBox], allow: Iterable[str]
) -> dict[str, Path]:
    """Cut each SANCTIONED mark's pixels out of its slide and write them as PNG patches (FR-315).

    Args:
        source_dir: this post's source store — `output/<run>/source/<post_id>/`, the folder
            holding `slide_NN.<ext>`. Patches are written to its `marks/` subfolder, which is
            created on demand.
        marks: the deck's `MarkBox` list from the vision pass (`SlideIntel.mark_boxes`), already
            range-clamped and span-checked upstream. An empty sequence is a no-op, and it is the
            common case — most decks show no third-party mark at all.
        allow: the COLLAPSED sanctioned mark names for this whole deck (FR-310) — the union of
            what each of its slides may name, spelled the way `mark_names.collapse(mark_name(x))`
            spells it. Required, and empty means empty: a deck that sanctions nothing gets no
            patches, because a patch nothing may draw is an upload nothing can use. Names are
            re-normalized here anyway (both operations are idempotent), so a caller that hands
            over already-collapsed keys and one that hands over raw sanctioned names agree.

    Returns:
        `{mark name: patch path}` for the marks that produced a usable patch, and only those.

        **The keys are the RAW detected names**, exactly as they arrived on the `MarkBox` — not
        the collapsed key this function joins and dedupes on. That asymmetry is the contract:
        `carousel._crop_patches` re-keys the table with `collapse(mark_name(name))` on its way into
        the deck's patch map, and it needs the original spelling to log and to name the upload
        with. DEDUPE, however, is by collapsed key (v2.2.0): "Claude", "claude logo" and
        "CLAUDE LOGO/WORDMARK" are one mark, one crop, one upload and one reference slot, and the
        first box to claim that key wins so the geometry is deterministic. Keying the dedupe by the
        raw name — as this module did until the 08-14 audit — meant three spellings of one logo
        became three uploads that the caller's collapsed table then merged back into one anyway.

        A name absent from the mapping is a mark with no pixels, which callers read as FR-315d's
        fallback: render it from its name and its written description.

    Raises:
        TypeError: `source_dir` is not a path. That is a programmer error; every FAILURE MODE OF
            THE DATA — a slide that is not on disk, an image Pillow cannot read, a box that crops
            to nothing, a box that crops to flat colour — is logged at WARNING and skipped, never
            raised (§0.14c, FR-315d).
    """
    if not isinstance(source_dir, (str, Path)):
        raise TypeError(f"source_dir must be a path, got {type(source_dir).__name__}")
    folder = Path(source_dir)
    sanctioned = {key for name in allow if (key := collapse(mark_name(name)))}
    written: dict[str, Path] = {}
    used: set[str] = set()
    claimed: set[str] = set()
    for mark in marks:
        key = collapse(mark_name(mark.name))
        if not key or key in claimed:
            continue  # one patch per distinct mark, however many slides (or spellings) carried it
        if key not in sanctioned:
            # Not a warning: an unsanctioned mark is the ORDINARY case on a deck whose vision pass
            # boxed the creator's clothing, a platform watermark or a tool no slide of ours names.
            logger.debug("logo_crop_unsanctioned: mark %r is not on this deck's sanctioned list, "
                         "so it is never cropped and never uploaded (FR-310/FR-315)", mark.name)
            continue
        claimed.add(key)
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
            patch = _patch(image, mark)
            if patch is None:
                return None
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


def _patch(image: Image.Image, mark: MarkBox) -> Image.Image | None:
    """This mark's pixels: the box as the model wrote it, or — only if that failed — remapped.

    The box's fractions are read against the WHOLE FRAME first, because that is what the vision
    question asks for and what every patch this module has ever written was cut with. Only when the
    resulting crop is unusable (too small to be a mark, or flat colour) is the picture re-examined
    for a letterbox, and the fractions re-read against the visible content rectangle instead.

    That ordering is measured, not assumed. On run `…_m39f`, four of the seven decks' slides carry
    no letterbox at all and their full-frame crops are correct logos; the fifth (`48aab562…`) is a
    1124×2000 canvas whose picture occupies rows 425–1636, and its two boxes at `y = 0.86` landed
    240 px into the black bottom bar — two identical near-black patches, 0.978 of one grey bucket,
    uploaded at full price as "the Claude logo" and "the OpenAI logo". Re-read against the content
    rectangle the same two boxes land exactly on the Claude asterisk and the OpenAI knot. A vision
    model shown a letterboxed image reports what it SAW, and what it saw was the picture.

    Fallback, never first: a remap applied up front would move every box on every ordinary slide
    with a plain margin, which is a correct patch made wrong to fix an incorrect one.
    """
    region = _pixel_box(mark.box, image.width, image.height)
    patch = image.crop(region) if region is not None else None
    if patch is not None and _crop_valid(patch):
        return patch
    rect = _content_rect(image)
    if rect is None:
        if region is None:
            logger.warning("logo_crop_skipped: mark %r crops to %d×%d px on slide %d — under the "
                           "%d px floor, so the patch would be noise, not a logo",
                           mark.name, *_span(mark.box, image.width, image.height), mark.slide,
                           _MIN_EDGE_PX)
        else:
            logger.warning("logo_crop_skipped: mark %r crops to flat colour on slide %d and the "
                           "slide carries no letterbox to re-read the box against — the mark "
                           "renders from its name and description (FR-315d)",
                           mark.name, mark.slide)
        return None
    remapped = _pixel_box(_remap(mark.box, rect), image.width, image.height)
    retry = image.crop(remapped) if remapped is not None else None
    if retry is None or not _crop_valid(retry):
        logger.warning("logo_crop_skipped: mark %r on slide %d is unusable both against the full "
                       "frame and against the letterboxed content rect %s — the mark renders from "
                       "its name and description (FR-315d)",
                       mark.name, mark.slide, tuple(round(value, 3) for value in rect))
        return None
    logger.info("logo_crop_remapped: mark %r on slide %d was re-read against the letterboxed "
                "content rect %s — the full-frame box landed on the bars",
                mark.name, mark.slide, tuple(round(value, 3) for value in rect))
    return retry


def _crop_valid(patch: Image.Image) -> bool:
    """Is this rectangle of pixels a picture of a mark — big enough, and not one flat colour?

    Two fences, both cheap and both about the same thing: what a render model can learn from the
    reference we are about to pay to upload.

    - **Size** (`_MIN_EDGE_PX`, since D48): a patch under the floor in either direction is a
      favicon's worth of pixels and teaches the model noise.
    - **Variance** (v2.2.0): a patch that is `_UNIFORM_SHARE` of ONE grey bucket is not a logo — it
      is a letterbox bar, a blank margin, or a box that landed on the background. It is refused
      here rather than at the attach step, because by the attach step it is already a file in
      `marks/` and a candidate for upload.

    Measured on `…_m39f` rather than guessed: real patches from that run score 0.482–0.855 of their
    dominant bucket, the two black-bar patches score 0.978, and plain stddev does NOT separate them
    (the black bars scored 34.5 against a genuine pastel logo's 5.9 — a bar with one bright sliver
    is "high contrast" and a low-contrast logo is not). Bucket share is the property that matches
    the question being asked.
    """
    if patch.width < _MIN_EDGE_PX or patch.height < _MIN_EDGE_PX:
        return False
    grey = patch.convert("L")
    pixels = grey.width * grey.height
    if not pixels:
        return False
    histogram = grey.histogram()
    dominant = max(sum(histogram[level:level + _UNIFORM_BUCKET])
                   for level in range(0, 256, _UNIFORM_BUCKET))
    return dominant / pixels < _UNIFORM_SHARE


def _content_rect(image: Image.Image) -> tuple[float, float, float, float] | None:
    """The picture inside the letterbox as fractional `(left, top, right, bottom)`, or `None`.

    A slideshow slide is regularly a 9:16 canvas with a 4:5 picture pasted into it, and the bars
    are flat: one colour, edge to edge, for hundreds of rows. The probe is a 64×64 area-averaged
    thumbnail — small enough that this costs a resize and 4 096 integer reads however big the slide
    is, coarse enough (one probe row ≈ 1.6% of the height) that it can only ever find bars that are
    worth finding.

    `None` means "not letterboxed", which is the answer for the ordinary slide and therefore the
    common one: bars must be flat within `_BAR_SPREAD` grey levels, agree with each other, and eat
    at least `_MIN_BAR` of the frame before the picture counts as inset at all. A slide that is
    flat all the way across (a blank download) also returns `None` — there is no content rect to
    find in a picture with no content.
    """
    grid = image.convert("L").resize((_PROBE, _PROBE), Image.Resampling.BOX)
    # `tobytes()` rather than `getdata()`: one grey level per byte for an "L" image, in row order,
    # and not the deprecated accessor. 4 096 bytes, whatever the slide's real resolution is.
    levels = list(grid.tobytes())
    rows = [levels[index * _PROBE:(index + 1) * _PROBE] for index in range(_PROBE)]
    columns = [[row[index] for row in rows] for index in range(_PROBE)]
    top, bottom = _flat_run(rows), _flat_run(rows[::-1])
    left, right = _flat_run(columns), _flat_run(columns[::-1])
    if top + bottom >= _PROBE or left + right >= _PROBE:
        return None  # nothing but bars: a blank or single-colour slide, not a letterboxed one
    if (top + bottom) < _MIN_BAR * _PROBE and (left + right) < _MIN_BAR * _PROBE:
        return None  # a margin, not a letterbox — remapping against it would move a correct box
    return (left / _PROBE, top / _PROBE, (_PROBE - right) / _PROBE, (_PROBE - bottom) / _PROBE)


def _flat_run(lines: Sequence[Sequence[int]]) -> int:
    """How many leading probe rows (or columns) are one flat colour, all of them the same one.

    Both conditions matter. "Flat within itself" alone accepts the smooth vertical gradient a lot
    of designed backgrounds have; requiring every bar line to sit within `_BAR_SPREAD` of the FIRST
    one as well means a run only counts while the colour is not going anywhere — which is what a
    letterbox bar does and what a gradient does not.
    """
    count, anchor = 0, None
    for line in lines:
        low, high = min(line), max(line)
        if high - low > _BAR_SPREAD:
            break
        if anchor is None:
            anchor = (low + high) / 2
        elif abs((low + high) / 2 - anchor) > _BAR_SPREAD:
            break
        count += 1
    return count


def _remap(
    box: tuple[float, float, float, float], rect: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    """The same fractional box, read against the content rectangle instead of the whole frame."""
    x, y, box_w, box_h = box
    left, top, right, bottom = rect
    width, height = right - left, bottom - top
    return (left + x * width, top + y * height, box_w * width, box_h * height)


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
