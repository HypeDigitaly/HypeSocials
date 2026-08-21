"""Exact-pixel screenshot paste: the source's own interface, composited locally (FR-370, D65).

Module contract
---------------
Purpose: a real screenshot is the ONE thing on a source slide that a render model cannot reproduce
and must not try to. Asked for "a tweet saying X", gpt-image-2 draws a plausible tweet with an
invented handle, invented words, an invented avatar and invented engagement counts — four
fabrications where the source had a fact, on a frame the operator is about to publish. The
D65 answer is not a better prompt: it is the source's own pixels. The render reserves an EMPTY
plate (the `{{screenshot_plate}}` block on `carousel_slide.md`), and after that frame lands this
module composites the cropped source interface into it.

Public API:
    PLATE                                           # the reserved rectangle, as frame fractions
    PLATES_DIR                                      # `plates/`, where the raw render is kept
    paste_screenshot(slide_path, source_slide, box, *, plate=PLATE, corner_radius_px=24)
        -> PasteResult                              # frozen: ok · reason · zone · source_image
                                                    #         · box · raw_backup
    plate_zone(plate=PLATE) -> str                  # the plate's own prose, for a prompt/contract
    raw_backup_name(slide_name) -> str              # `plates/slide_NN_raw.<ext>`, for the gallery

**THE BOUNDARY THIS MODULE DOES NOT MOVE.** Source bytes still never reach a render payload. Every
line of work here is LOCAL, POST-RENDER and OUTPUT-SIDE: the inputs are a file the packager already
wrote into the operator's asset folder and a file the source store already downloaded, and the
output is that same asset file, rewritten in place. Nothing here uploads, submits, references or
even *names* a provider — the module imports nothing from `render` or `generate`, and
`tests/test_screenshot_paste.py` pins that with an import check. `generate/refs.py:_sanctioned`,
the path guard that refuses everything under `source/` except `marks/`, is untouched and still
refuses exactly what it refused before D65. D46's carve-out ("source is analysis-and-display-only")
is not widened either: a composited slide is display, on this workstation, in a folder the operator
opens — it is never an input to anything that costs money.

**Second sanctioned Pillow use in the tree.** `sources/logo_crops.py` (D48) was the first and
`outputs/alpha_halo.py` (D65/FR-365) is the third; the scope note on both applies here word for
word. This module opens two files, crops one, scales it, masks it and writes it back. No resizing
pipeline, no colour grading, no thumbnails, no re-encoding of anything that was not pasted into.
Anything else that wants to touch pixels is a new decision, not an extension of this one.

**Synchronous on purpose, and the caller owns that.** Two decodes, a scale and an encode is real
work — tens of milliseconds on a 1254 px frame — and the event loop here is also carrying every
other creative in the run. Callers dispatch it the way `logo_crops` and `alpha_halo` are
dispatched (rule 1: no blocking work on the loop):

    result = await asyncio.to_thread(screenshot_paste.paste_screenshot, path, source, box)

**Fail-open, always, and the failure is VISIBLE (§0.14c).** Nothing here raises for any state of
the data — a missing file, a truncated download, a decoder that refuses a webp variant, a box that
crops to nothing, a full disk on save. Every one of them returns `PasteResult(ok=False, reason=…)`
and leaves the landed render exactly as it was. That frame then ships carrying the EMPTY PLATE the
prompt ordered, which is a visible defect and is meant to be: the critics judge it as one
(FR-370's `screenshot_paste_failed` tag is the receipt), because an empty rounded rectangle in the
middle of a slide is something the operator must see rather than something to hide.

**The raw render is never thrown away.** Before a single pixel is changed, the frame as the model
returned it is copied byte-for-byte to `plates/slide_NN_raw.<ext>`. That folder is never published
(FR-72/FR-213 list it beside `covers/` and `source/`), and it is what makes the paste reviewable:
"what did the model actually draw under there" is a question an operator will ask the first time a
plate lands off-centre, and the answer should not need a re-render.

Do not: raise for a bad frame; upload anything; read anything out of `source/` for any purpose but
this local composite; import `render` or `generate`; decide WHAT a failed paste costs (the caller
owns the tag and the contract row); reach for Pillow anywhere else in the tree.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, UnidentifiedImageError

from hypesocials.util import atomic_write

logger = logging.getLogger(__name__)

#: FR-370's reserved plate as `(x, y, w, h)` fractions of the rendered frame, origin top-left:
#: **8% to 92% of the width, 20% to 78% of the height.** It is DETERMINISTIC GEOMETRY IN CODE and
#: not a style property, because two readers have to agree about it byte for byte — the prompt
#: block that orders the model to leave the rectangle empty, and this compositor that fills it.
#: A per-style plate would be a number the render was told and the paste guessed.
#:
#: Why these four numbers. The frame renders 1:1 (`plan.py`), and every shipped style keeps its
#: text inside the central 80% (FR-350's house spine), so a plate has to leave room ABOVE it for a
#: headline and BELOW it for a counter or a signature while still being big enough that a
#: screenshot inside it is legible at thumbnail scale. 20%-78% vertically leaves a fifth of the
#: frame for the line above and a fifth for the furniture below; 8%-92% horizontally is the
#: widest a plate can be while still reading as a plate rather than as a bleed.
PLATE: tuple[float, float, float, float] = (0.08, 0.20, 0.84, 0.58)

#: Where the pre-paste render is kept, inside the asset folder. A SUBFOLDER rather than a filename
#: suffix, for the same reason `covers/` and `marks/` are subfolders: the publishable set is
#: enumerated by path (FR-72), and a `slide_01_raw.jpg` sitting beside `slide_01.jpg` is one glob
#: away from being published as a slide.
PLATES_DIR = "plates"
#: The suffix on a backed-up frame: `slide_03.jpg` -> `plates/slide_03_raw.jpg`. The stem is kept
#: so the two files sort together and a reviewer can see at a glance which raw belongs to which.
_RAW_SUFFIX = "_raw"

#: Breathing room around the detected box, as a fraction of the box's own size, added on each side
#: and then clamped to the slide. A vision model brackets what it SEES — the window's content —
#: and an interface's outermost pixels (a border, a rounded corner's shadow, the last row of a
#: card) sit just outside a tight box. `logo_crops._PAD` exists for the same reason and is 0.12;
#: this is smaller because a screenshot box is large, so the same fraction would swallow the
#: creator's chrome the question deliberately excluded.
_PAD = 0.02

#: A crop smaller than this on either axis is not an interface, whatever the box said — it is an
#: avatar, a favicon or a fragment, and scaling it into a plate 84% of the frame wide would ship a
#: smear. The floor is in PIXELS of the source slide, because that is what decides whether the
#: scaled result has any detail left; `slide_intel._SCREENSHOT_BOX_MIN_SPAN` is the fractional
#: half of the same guard, applied at detection.
_MIN_CROP_PX = 96

#: The pasted screenshot's corner radius in pixels, at the frame size the engine renders (1254 px).
#: Rounded because the plate the model draws will itself be rounded (the prompt block says so), and
#: a hard-cornered rectangle sitting inside a rounded one reads as a mistake rather than a design.
_DEFAULT_RADIUS_PX = 24
#: The radius is clamped to a quarter of the pasted rectangle's short side: on a small paste a
#: 24 px radius would round the corners into a lozenge.
_RADIUS_SHARE = 0.25

#: The hairline drawn around the pasted rectangle, and how far its colour is pushed away from the
#: plate's own ground. A screenshot is usually a light card, and a light card pasted onto a light
#: plate has no edge at all — the composite then reads as if the interface bled into the slide.
#: One pixel at 18% contrast is enough to say "this is a picture inside the frame" and little
#: enough that it never reads as a drawn border the style did not order.
_BORDER_PX = 1
_BORDER_BLEND = 0.18
#: Where the plate's own ground colour is sampled from: the midpoint of each edge of the paste
#: rectangle, one pixel OUTSIDE it, on the RAW render. Four samples, averaged — cheap, and it
#: cannot be fooled by whatever the screenshot itself happens to be showing.
_GROUND_SAMPLES = 4
#: Mid-grey, used when the ground cannot be sampled at all (a paste rectangle flush against the
#: frame's edge). It contrasts adequately with both extremes, which is the only job it has.
_FALLBACK_GROUND = (128, 128, 128)

_DETAIL_MAX = 160  # operator-facing reason strings; never a payload dump


@dataclass(frozen=True)
class PasteResult:
    """What one paste attempt did — the caller's whole answer, receipts included.

    `ok` is the only field anything gates on. `reason` is operator prose and is empty exactly when
    `ok` is True; on a failure it says which of the half-dozen fail-open branches was taken, and
    it is what `meta.yaml.panel_map[*].paste_reason` and the console line both carry.

    `zone` is the prose naming WHERE the pasted pixels are, and it is load-bearing rather than
    decorative: the gauntlet writes it into the frame contract as the `screenshot:` row, and it is
    the sentence that tells three critics that everything inside that rectangle — text they did
    not order, platform chrome, logos, handles, faces — is SANCTIONED and not a leak. Empty on a
    failure, deliberately: a plate that was not filled sanctions nothing.

    `source_image` is the source slide the crop came from and `box` the rectangle it was cut with,
    both carried so a wrong-looking paste can be traced without re-running the vision pass.
    `raw_backup` is the asset-relative path of the untouched render (`plates/slide_NN_raw.jpg`),
    written before any pixel changed and empty when the backup itself failed — which is the one
    failure that stops the paste, because a composite with no way back is not reversible.
    """

    ok: bool
    reason: str = ""
    zone: str = ""
    source_image: str = ""
    box: tuple[float, float, float, float] | None = None
    raw_backup: str = ""


def plate_zone(plate: tuple[float, float, float, float] = PLATE) -> str:
    """The reserved plate as one sentence of percentages — the prompt's words and the contract's.

    Built from the same tuple the compositor pastes into, so the block that ORDERS the empty
    rectangle and the row that tells the critics what is inside it can never quote two different
    geometries. Percentages rather than fractions because the reader is a language model looking
    at a picture, and "8% to 92% of the width" is the phrasing it places correctly.
    """
    x, y, width, height = plate
    return (f"from {x:.0%} to {x + width:.0%} of the frame's width and "
            f"{y:.0%} to {y + height:.0%} of its height")


def raw_backup_name(slide_name: str) -> str:
    """`slide_03.jpg` -> `plates/slide_03_raw.jpg` — the ONE spelling of the backup's path.

    Public because two readers need it and must not each derive it: this module writes the file,
    and the gallery links it from the card beside the slide it belongs to. A second derivation is
    how a link ends up pointing at `plates/slide_3_raw.jpeg`, which exists nowhere.

    Asset-relative and forward-slashed, because that is what FR-75 lets a gallery href be.
    """
    stem, _, suffix = str(slide_name).rpartition(".")
    return f"{PLATES_DIR}/{stem or slide_name}{_RAW_SUFFIX}{f'.{suffix}' if stem else ''}"


def paste_screenshot(
    slide_path: str | Path,
    source_slide: str | Path,
    box: tuple[float, float, float, float] | None,
    *,
    plate: tuple[float, float, float, float] = PLATE,
    corner_radius_px: int = _DEFAULT_RADIUS_PX,
) -> PasteResult:
    """Composite the source's own interface into this landed frame's reserved plate (FR-370).

    Six steps, in this order, and the order is the contract: (1) validate the inputs without
    touching a file, (2) copy the raw render into `plates/` byte for byte, (3) crop the box out of
    the source slide with a little padding, (4) FIT-scale that crop into the plate preserving its
    aspect ratio and centring it, (5) round its corners and draw a one-pixel hairline around it,
    (6) rewrite the frame atomically. A failure at any step leaves the frame exactly as it landed.

    **FIT, never fill.** The crop is scaled to the largest size that fits INSIDE the plate with its
    aspect ratio intact, and centred there. The alternative — filling the plate and cropping the
    overflow — would cut words off the very interface this exists to reproduce faithfully, which
    is the whole point of the feature inverted. The letterboxing that leaves is invisible in
    practice: the model was told to render that rectangle as a flat plate in the deck's own
    surface colour, so the uncovered margin is the plate, not a bar.

    Args:
        slide_path: the landed render in the operator's asset folder (`slide_03.jpg`). Rewritten
            in place, atomically (`util.atomic_write`, NFR-21) — a torn slide is indistinguishable
            from a whole one to everything downstream.
        source_slide: the stored source panel this crop comes from
            (`output/<run>/source/<post_id>/slide_03.webp`). Read-only, and read for a LOCAL
            composite alone: nothing about this path is ever uploaded (FR-244/D46 unchanged).
        box: the FR-370 `screenshot_box` — `(x, y, w, h)` fractions of the SOURCE slide, origin
            top-left, as `slide_intel._screenshot_box()` returns them. `None` or a malformed
            tuple is a fail-open refusal, never an exception.
        plate: the reserved rectangle as fractions of the RENDERED frame. Defaults to `PLATE`, and
            a caller that passes something else must have put the same numbers in the prompt.
        corner_radius_px: the pasted rectangle's corner radius, clamped to a quarter of its short
            side. `0` pastes square corners.

    Returns:
        A `PasteResult`. `ok=True` means the file on disk now carries the source's exact pixels
        inside the plate and `plates/slide_NN_raw.<ext>` holds what the model returned.

    Raises:
        Nothing for any state of the data — that is the module's whole posture (§0.14c). A caller
        that passes a non-path gets the ordinary `TypeError` from `Path`, which is a bug in the
        caller and not a failure mode of a render.
    """
    frame, source = Path(slide_path), Path(source_slide)
    rectangle = _clean_box(box)
    if rectangle is None:
        return PasteResult(ok=False, reason="no usable screenshot box on this panel",
                           source_image=source.name)
    if not source.is_file():
        return PasteResult(ok=False, reason=f"source slide {source.name} is not on disk",
                           source_image=source.name, box=rectangle)
    backup = _back_up(frame)
    if backup is None:
        return PasteResult(ok=False, reason="the raw render could not be backed up, so it is left "
                                            "untouched rather than overwritten irreversibly",
                           source_image=source.name, box=rectangle)
    try:
        with Image.open(frame) as landed:
            landed.load()
            target = _plate_box(plate, landed.width, landed.height)
            if target is None:
                return PasteResult(ok=False, reason="the frame is too small to hold a plate",
                                   source_image=source.name, box=rectangle, raw_backup=backup)
            with Image.open(source) as origin:
                origin.load()
                patch = _crop(origin, rectangle)
            if patch is None:
                return PasteResult(
                    ok=False, source_image=source.name, box=rectangle, raw_backup=backup,
                    reason=(f"the box crops to under {_MIN_CROP_PX} px on {source.name} — too "
                            "small to be an interface"))
            placed = _fit(patch, target)
            composed = _compose(landed, placed, corner_radius_px)
            buffer = io.BytesIO()
            # The same container the frame arrived in, so no path, glob or gallery link moves.
            composed.save(buffer, format=landed.format or "PNG")
        atomic_write(frame, buffer.getvalue())
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        logger.warning("screenshot_paste_failed: %s could not take its screenshot from %s "
                       "(%s: %s) — the frame keeps the empty plate it rendered", frame.name,
                       source.name, type(exc).__name__, str(exc)[:200])
        return PasteResult(ok=False, reason=f"{type(exc).__name__}: {str(exc)[:_DETAIL_MAX]}",
                           source_image=source.name, box=rectangle, raw_backup=backup)
    zone = _zone(placed[1], composed.width, composed.height)
    logger.info("screenshot_pasted: %s carries %s's own pixels at %s", frame.name, source.name,
                zone)
    return PasteResult(ok=True, zone=zone, source_image=source.name, box=rectangle,
                       raw_backup=backup)


def _clean_box(box: tuple[float, float, float, float] | None
               ) -> tuple[float, float, float, float] | None:
    """The caller's box as four clamped floats, or `None` for anything that is not one.

    Re-validated HERE even though `slide_intel._screenshot_box()` already validated it, because
    this module is the one that turns the numbers into pixel arithmetic and a `None` reaching
    `int(round(x * width))` is a traceback on a frame that already cost money. Defence in depth
    of the cheapest kind: four floats and a zero-area test.
    """
    values = list(box) if isinstance(box, (list, tuple)) else []
    if len(values) != 4:
        return None
    try:
        x, y, width, height = (min(1.0, max(0.0, float(item))) for item in values)
    except (TypeError, ValueError):
        return None
    return (x, y, width, height) if width > 0 and height > 0 else None


def _back_up(frame: Path) -> str | None:
    """Copy the landed render into `plates/slide_NN_raw.<ext>`; return its asset-relative path.

    Byte for byte, before anything is changed, and the paste does not proceed without it: a
    composite that cannot be undone is a paid render the operator can never see again. On a
    re-render (FR-317's resubmit, the alpha guard's repair, every gauntlet fix round) this is
    called again and OVERWRITES the previous backup — which is right, because the backup exists to
    explain the frame that is on disk now, and the frame that is on disk now is the new one.

    `None`, warned, for every way a copy can fail. The caller reads that as a refusal to paste.
    """
    target = frame.parent / raw_backup_name(frame.name)
    try:
        atomic_write(target, frame.read_bytes())
    except OSError as exc:
        logger.warning("screenshot_paste_backup_failed: %s could not be copied to %s/ (%s: %s) — "
                       "no paste is attempted, so the paid render is not overwritten",
                       frame.name, PLATES_DIR, type(exc).__name__, str(exc)[:200])
        return None
    return raw_backup_name(frame.name)


def _plate_box(plate: tuple[float, float, float, float], width: int,
               height: int) -> tuple[int, int, int, int] | None:
    """The reserved plate as pixel `(left, top, right, bottom)` on THIS frame, or `None`.

    `None` only for a frame so small the plate has no area — which no render produces and every
    test eventually tries.
    """
    x, y, plate_w, plate_h = plate
    left, top = int(round(x * width)), int(round(y * height))
    right, bottom = int(round((x + plate_w) * width)), int(round((y + plate_h) * height))
    right, bottom = min(right, width), min(bottom, height)
    return (left, top, right, bottom) if right - left > 1 and bottom - top > 1 else None


def _crop(origin: Image.Image, box: tuple[float, float, float, float]) -> Image.Image | None:
    """The interface's own pixels, padded a little and clamped to the slide — or `None`.

    Padding is added on each side and then clamped, so an interface running to the slide's edge
    keeps whatever padding fits instead of losing the crop. The size floor is applied AFTER the
    clamp, because the size that matters is the size of the pixels actually cut.
    """
    x, y, width, height = box
    pad_x, pad_y = width * _PAD, height * _PAD
    left = max(0, int(round((x - pad_x) * origin.width)))
    top = max(0, int(round((y - pad_y) * origin.height)))
    right = min(origin.width, int(round((x + width + pad_x) * origin.width)))
    bottom = min(origin.height, int(round((y + height + pad_y) * origin.height)))
    if right - left < _MIN_CROP_PX or bottom - top < _MIN_CROP_PX:
        return None
    patch = origin.crop((left, top, right, bottom))
    # Palette, CMYK and greyscale source slides all exist (the store keeps whatever the CDN sent).
    # One mode from here on means the composite below never has to branch on the source's format.
    return patch if patch.mode == "RGB" else patch.convert("RGB")


def _fit(patch: Image.Image, target: tuple[int, int, int, int]
         ) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Scale the crop to the largest size that FITS inside the plate, and centre it there.

    Returns the scaled image and the pixel rectangle it occupies on the frame. The aspect ratio is
    preserved because the alternative loses words off the edge of the very interface this feature
    exists to reproduce exactly — a screenshot cropped to fill a plate is a screenshot with its
    right-hand column missing.

    `LANCZOS` because this is nearly always a DOWNSCALE (a 1200 px-wide tweet card into a ~1050 px
    plate) and lettering is what has to survive it: a nearest-neighbour or bilinear reduction of
    8 pt UI text is the difference between a legible screenshot and a smear the craft critic then
    reports as `garbled`.
    """
    left, top, right, bottom = target
    room_w, room_h = right - left, bottom - top
    scale = min(room_w / patch.width, room_h / patch.height)
    size = (max(1, int(round(patch.width * scale))), max(1, int(round(patch.height * scale))))
    scaled = patch.resize(size, Image.Resampling.LANCZOS)
    place_x = left + (room_w - size[0]) // 2
    place_y = top + (room_h - size[1]) // 2
    return scaled, (place_x, place_y, place_x + size[0], place_y + size[1])


def _compose(landed: Image.Image, placed: tuple[Image.Image, tuple[int, int, int, int]],
             corner_radius_px: int) -> Image.Image:
    """Paste the scaled crop onto the landed frame with rounded corners and a hairline.

    The frame's OWN mode is preserved end to end — an RGBA render stays RGBA, a JPEG's RGB stays
    RGB — because the alpha-halo guard (FR-365) reads this same file afterwards and its verdict
    must be about the render the model returned, not about a mode this composite chose. The plate
    sits well inside the frame (8%-92% x 20%-78%), so nothing here touches the edge ring that
    guard measures.

    The mask is what rounds the corners: an `L`-mode rounded rectangle, white inside and black
    outside, handed to `paste()` as its third argument. The hairline is drawn on the FRAME after
    the paste rather than on the patch before it, so it lands exactly on the boundary between the
    pasted pixels and the plate instead of eating a row of the screenshot.
    """
    scaled, rectangle = placed
    left, top, right, bottom = rectangle
    width, height = right - left, bottom - top
    radius = max(0, min(int(corner_radius_px), int(min(width, height) * _RADIUS_SHARE)))
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
    frame = landed if landed.mode in ("RGB", "RGBA") else landed.convert("RGB")
    frame = frame.copy()
    ground = _ground(frame, rectangle)
    frame.paste(scaled.convert(frame.mode), (left, top), mask)
    ImageDraw.Draw(frame).rounded_rectangle(
        (left, top, right - 1, bottom - 1), radius=radius, outline=_hairline(ground, frame.mode),
        width=_BORDER_PX)
    return frame


def _ground(frame: Image.Image, rectangle: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """The plate's own colour, sampled one pixel OUTSIDE the paste rectangle's four edge midpoints.

    Sampled rather than assumed because the plate is whatever surface colour the deck's style
    declared — cream on `paper-editorial-carousel`, near-black on `circuit-atlas-dark` — and a
    hairline drawn without knowing which would be invisible on half the registry and a scar on the
    other half. Four cheap reads, averaged; a sample that falls outside the frame is skipped, and
    a rectangle with no sampleable neighbour at all falls back to mid-grey.
    """
    left, top, right, bottom = rectangle
    mid_x, mid_y = (left + right) // 2, (top + bottom) // 2
    points = ((mid_x, top - 2), (right + 1, mid_y), (mid_x, bottom + 1), (left - 2, mid_y))
    reads = [frame.getpixel(point)[:3] for point in points
             if 0 <= point[0] < frame.width and 0 <= point[1] < frame.height]
    if not reads:
        return _FALLBACK_GROUND
    return tuple(sum(channel) // len(reads) for channel in zip(*reads))  # type: ignore[return-value]


def _hairline(ground: tuple[int, int, int], mode: str) -> tuple[int, ...]:
    """A one-pixel edge colour: the plate's ground, pushed `_BORDER_BLEND` toward its opposite.

    Toward BLACK on a light plate and toward WHITE on a dark one, so the line is always a little
    more contrast than its surroundings and never a hard black rule the style never ordered. The
    tuple is widened to four channels on an RGBA frame, because Pillow wants a colour of the
    image's own arity and a three-tuple on an RGBA draw is silently transparent.
    """
    luminance = (ground[0] * 299 + ground[1] * 587 + ground[2] * 114) / 1000
    toward = 0 if luminance >= 128 else 255
    line = tuple(int(round(value + (toward - value) * _BORDER_BLEND)) for value in ground)
    return (*line, 255) if mode == "RGBA" else line


def _zone(rectangle: tuple[int, int, int, int], width: int, height: int) -> str:
    """Where the pasted pixels actually ARE, in percentages — the critics' sanctioned rectangle.

    Measured off the placed rectangle rather than off `PLATE`, because FIT-scaling centres a crop
    whose aspect ratio rarely matches the plate's: a tall phone screenshot occupies the plate's
    full height and a narrow column of its width, and telling three critics to sanction the whole
    plate would sanction a band of empty surface on either side of it. The sentence names what is
    there, so what is NOT there is still judged by every rule in the rulebook.
    """
    left, top, right, bottom = rectangle
    return (f"from {left / width:.0%} to {right / width:.0%} of the frame's width and "
            f"{top / height:.0%} to {bottom / height:.0%} of its height")


__all__ = ["PLATE", "PLATES_DIR", "PasteResult", "paste_screenshot", "plate_zone",
           "raw_backup_name"]
