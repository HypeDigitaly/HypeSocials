"""The alpha-halo guard: a landed render's edges, read as pixels (FR-365, D65).

Module contract
---------------
Purpose: gpt-image-2 occasionally returns an RGBA frame whose alpha channel is a ragged,
semi-transparent smear around all four edges instead of the flat opaque rectangle every other
render is. The picture underneath is fine; the file is unpublishable. Run
`20260821_121514_q745`'s LinkedIn cover (`Li_car_ai-agents-…_01/slide_01.png`) is the case this
module is written against, and the numbers below are ITS numbers, not a guess:

    mode RGBA · 1254x1254 · fully-opaque pixels 0.01% of the frame · centre alpha 253
    corners alpha 0-1 · 49% of the frame under alpha 250 · 38% under alpha 128
    the 25 px edge ring: 100.0% of it under alpha 250

Every other slide in that same run — thirteen of them, three decks — came back mode `RGB` with no
alpha channel at all. So the defect is not a matter of degree: a clean render has NO alpha band,
and the broken one has a band that is transparent at the border and merely near-opaque in the
middle. That is what makes a cheap edge test decisive here rather than a heuristic.

Public API:
    inspect_frame(path) -> AlphaVerdict     # is this landed file haloed?
    flatten_frame(path) -> FlattenResult    # last resort: composite it onto an opaque ground

Both are SYNCHRONOUS and neither may be called on the event loop (rule 1). Callers dispatch them
the way `sources/logo_crops.py` dispatches its crop:

    verdict = await asyncio.to_thread(alpha_halo.inspect_frame, path)

**Second sanctioned Pillow use (D65/FR-365).** `sources/logo_crops.py` (D48) was the first and its
scope note applies here word for word: this module opens a frame, reads its alpha band, and — only
on the remedy path — composites and re-saves it. No resizing pipeline, no colour grading, no
thumbnails, no compositing of one picture into another (that is Wave 5's own carve-out). Nothing
here uploads anything, reads anything out of `source/`, or touches a render payload: it runs on a
file the packager has ALREADY written into the operator's asset folder, after the money is spent.

**Fail-open, always (§0.14c).** A file that is not there, a decoder that refuses it, a truncated
download — every one of those returns "clean", warned. The guard exists to catch a defect that is
loud and unambiguous; a guard that failed a deck because it could not open a file would cost the
operator slides to protect them from a halo.

**The no-alpha short circuit is a performance contract, not an optimisation.** `Image.open()` reads
the header and stops; `.load()` is what decodes megabytes of pixels. A JPEG or an ordinary RGB PNG
— the overwhelming majority of every deck — is answered from `image.mode` alone, so this guard
costs a stat and a header read per slide and a full decode only on the rare frame that HAS an alpha
band to examine.

Do not: raise for a bad frame; delete or move the original; re-encode a frame that passed; reach
for Pillow anywhere else in the tree; decide WHAT a failed check costs (the caller owns FR-317's
resubmit and the `alpha_flattened` tag).
"""

from __future__ import annotations

import io
import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from hypesocials.util import atomic_write

logger = logging.getLogger(__name__)

#: Alpha at or above this level reads as OPAQUE. Not 255, and the difference is measured: the q745
#: frame's own clean interior sits at 253 and its neighbours at 250-254, which is gpt-image-2's
#: ordinary rounding rather than transparency. A floor of 255 would call that whole frame haloed
#: — and, worse, would call a PERFECTLY GOOD RGBA render haloed for the same rounding. The defect's
#: ring is at 0-2, three orders of magnitude away from this line, so nothing about the answer is
#: sensitive to where in the 245-254 band it is drawn.
_OPAQUE_FLOOR = 250

#: The edge ring's width as a fraction of the frame's SHORT side, with an absolute floor for the
#: tiny frames only tests ever make. 2% of a 1254 px slide is 25 px — wide enough that a real halo
#: cannot hide inside it and narrow enough that it is still unambiguously "the edge" rather than a
#: quarter of the picture. The q745 halo reaches ~15% of the way in, so it saturates this ring.
_EDGE_BAND = 0.02
_MIN_BAND_PX = 4

#: How much of that ring may be non-opaque before the frame is called haloed. A full-bleed social
#: creative has NO legitimately transparent pixel anywhere — the frame is the canvas — so this is
#: a tolerance for stray decoder noise, not a budget for real transparency. Measured against the
#: defect at 1.000 and against thirteen clean slides at 0.000 (they carry no alpha band at all),
#: the whole 0.02-0.90 range separates the two equally well; 2% is chosen because it is the
#: smallest number that cannot be reached by rounding.
_RING_SHARE = 0.02

#: The central box the flatten reads its background colour out of, and the grid it samples it on.
#: Central because the halo lives at the border and the ground colour has to come from pixels the
#: defect did not touch; NEAREST-downsampled because an area-average would invent a colour that is
#: in no pixel of the frame (a cream card over a teal scene averages to a mud that belongs to
#: neither), while nearest-neighbour keeps every sampled value a colour the render actually used.
_CORE_BOX = 0.60
_CORE_GRID = 96

#: The background of last resort, used only when the central box holds NO opaque pixel at all —
#: a frame that transparent has no ground of its own to borrow, and white is the safer of the two
#: extremes to hand an operator who is about to look at it.
_FALLBACK_GROUND = (255, 255, 255)


@dataclass(frozen=True)
class AlphaVerdict:
    """What the edge ring of one landed frame looks like. `clean` is the only field callers gate on.

    `reason` is operator prose, already sentence-shaped, and is empty exactly when `clean` is True
    and the frame was actually examined. `edges` is (top, right, bottom, left) as the non-opaque
    SHARE of each band, which is what tells a reader whether this is the four-sided q745 halo or a
    one-sided artefact; `ring_share` is the same measure over the whole ring and is the number the
    threshold is applied to. `examined` is False when the file could not be read — a fail-open
    "clean" that a log line should not describe as a passing frame.
    """

    clean: bool
    reason: str = ""
    ring_share: float = 0.0
    edges: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    examined: bool = True

    @property
    def edge_note(self) -> str:
        """`top 100%, right 100%, bottom 100%, left 100%` — the halo's shape, for one log line."""
        return ", ".join(f"{name} {share:.0%}" for name, share in
                         zip(("top", "right", "bottom", "left"), self.edges))


@dataclass(frozen=True)
class FlattenResult:
    """Did the last-resort flatten actually rewrite the file, and onto what ground?

    `ok` False is never fatal: the caller ships the haloed frame rather than losing the slide, and
    the tag plus this `reason` is what tells the operator which card to look at twice.
    """

    ok: bool
    reason: str = ""
    ground: tuple[int, int, int] = _FALLBACK_GROUND


def inspect_frame(path: str | Path) -> AlphaVerdict:
    """Is this landed render's edge ring non-opaque — FR-365's whole question, in one pass.

    Args:
        path: the file the packager already wrote into the asset folder (`slide_NN.png`,
            `image.png`, a re-rendered frame). Read-only; nothing here writes.

    Returns:
        An `AlphaVerdict`. **`clean=True` is the answer for every frame with no alpha channel**,
        returned from the header alone without decoding a single pixel — that is the JPEG and
        ordinary-RGB-PNG case and it is nearly every frame this engine renders.

        A missing file, an unreadable file or a decoder error is ALSO `clean=True`, with
        `examined=False` and a stated reason: this guard may cost a render, never a deck
        (§0.14c). The caller distinguishes the two by `examined` when it wants to.

    Raises:
        Nothing for any state of the data. A caller that passes a non-path gets the ordinary
        `TypeError` from `Path`, which is a bug in the caller.
    """
    frame = Path(path)
    try:
        with Image.open(frame) as image:
            # HEADER ONLY so far — `Image.open` is lazy and `.load()` below is the decode. A frame
            # with no alpha band cannot carry this defect, so it never pays for one.
            if "A" not in image.getbands():
                return AlphaVerdict(clean=True)
            image.load()
            alpha = image.getchannel("A")
            shares = _edge_shares(alpha)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        logger.warning("alpha_halo_unreadable: %s could not be examined (%s: %s) — the frame is "
                       "treated as clean and ships as it landed (FR-365 fail-open)",
                       frame.name, type(exc).__name__, str(exc)[:200])
        return AlphaVerdict(clean=True, reason=f"{type(exc).__name__}: {str(exc)[:120]}",
                            examined=False)
    ring = sum(count for count, _ in shares) / max(1, sum(total for _, total in shares))
    edges = tuple(count / total if total else 0.0 for count, total in shares)
    if ring <= _RING_SHARE:
        return AlphaVerdict(clean=True, ring_share=ring, edges=edges)  # type: ignore[arg-type]
    return AlphaVerdict(
        clean=False, ring_share=ring, edges=edges,  # type: ignore[arg-type]
        reason=(f"{ring:.0%} of the frame's {_EDGE_BAND:.0%} edge ring is under alpha "
                f"{_OPAQUE_FLOOR} (a see-through halo, not a picture)"))


def flatten_frame(path: str | Path) -> FlattenResult:
    """Composite a haloed frame onto an opaque ground of its OWN colour and rewrite it in place.

    The last resort behind FR-365's single resubmit, and deliberately the last: it changes pixels
    the operator paid a model to produce. It runs only when a second render came back haloed too,
    and the alternative it is chosen over is shipping a see-through slide or losing the deck.

    **Why composite rather than just drop the alpha band.** Measured on the q745 cover: discarding
    the channel (`convert("RGB")`) exposes the RGB values the transparent border was hiding, and
    they are a ragged black smoke ring — the frame gets WORSE, not better. Compositing over an
    opaque ground is what makes the border disappear, because at alpha 0 the result is the ground
    and at the interior's alpha 253 it is the render.

    **Why the ground is sampled and not a constant.** White rescues the q745 cover because that
    deck's ground is near-white; on `anime-noir-statement` or `circuit-atlas-dark` a white border
    would be a brighter defect than the halo it replaced. So the colour comes from the frame
    itself: the most common exactly-repeated colour among the OPAQUE pixels of the central 60%,
    sampled on a nearest-neighbour grid so every candidate is a colour the render actually used.

    Args:
        path: the frame to rewrite. Overwritten atomically (`util.atomic_write`, NFR-21's rule),
            because a torn slide is indistinguishable from a whole one to everything downstream.

    Returns:
        `FlattenResult(ok=True, ground=…)` when the file on disk is now opaque. `ok=False` with a
        reason for every failure — an unreadable file, a frame with no alpha to flatten, a full
        disk on save. Never raises: the caller's answer to a failed flatten is to ship the haloed
        frame with the tag, which is still a deck.
    """
    frame = Path(path)
    try:
        with Image.open(frame) as image:
            image.load()
            if "A" not in image.getbands():
                return FlattenResult(ok=False, reason="frame carries no alpha channel to flatten")
            rgba = image if image.mode == "RGBA" else image.convert("RGBA")
            ground = _dominant_opaque_colour(rgba)
            flat = Image.new("RGB", rgba.size, ground)
            flat.paste(rgba, (0, 0), rgba)  # the alpha band IS the mask: ground where it is 0
            buffer = io.BytesIO()
            # Same container the frame arrived in, so no path, glob or gallery link has to move.
            flat.save(buffer, format=image.format or "PNG")
        atomic_write(frame, buffer.getvalue())
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        logger.warning("alpha_flatten_failed: %s could not be flattened (%s: %s) — the frame ships "
                       "as it landed", frame.name, type(exc).__name__, str(exc)[:200])
        return FlattenResult(ok=False, reason=f"{type(exc).__name__}: {str(exc)[:120]}")
    logger.info("alpha_flattened: %s composited onto its own ground #%02x%02x%02x",
                frame.name, *ground)
    return FlattenResult(ok=True, ground=ground)


def _edge_shares(alpha: Image.Image) -> list[tuple[int, int]]:
    """Per edge band, `(non-opaque pixels, pixels in that band)` — top, right, bottom, left.

    Four crops and four histograms rather than a Python walk over the pixels: a 1254x1254 frame is
    1.5 M alpha bytes and counting them in the interpreter is a tenth of a second per slide for an
    answer Pillow's C histogram gives in microseconds. The bands are cut so they do not overlap
    (top and bottom take the full width, left and right take what is between them), which is what
    keeps `ring_share` a true share rather than one that double-counts the corners — and the
    corners are exactly where this defect is strongest.
    """
    width, height = alpha.size
    band = max(_MIN_BAND_PX, int(round(_EDGE_BAND * min(width, height))))
    band = min(band, max(1, min(width, height) // 2))  # a frame smaller than two bands is all edge
    boxes = (
        (0, 0, width, band),                      # top
        (width - band, band, width, height - band),  # right, between the horizontal bands
        (0, height - band, width, height),        # bottom
        (0, band, band, height - band),           # left, between the horizontal bands
    )
    shares: list[tuple[int, int]] = []
    for box in boxes:
        left, top, right, bottom = box
        if right <= left or bottom <= top:
            shares.append((0, 0))
            continue
        histogram = alpha.crop(box).histogram()
        total = (right - left) * (bottom - top)
        shares.append((sum(histogram[:_OPAQUE_FLOOR]), total))
    return shares


def _dominant_opaque_colour(rgba: Image.Image) -> tuple[int, int, int]:
    """The most repeated colour among the OPAQUE pixels of the frame's central box.

    Sampled on a `_CORE_GRID`-square nearest-neighbour grid — ~9 k pixels whatever the frame's real
    size is — so the `Counter` below is bounded work no matter how big a future render gets. Only
    pixels at or above `_OPAQUE_FLOOR` are counted: a semi-transparent pixel's stored colour is not
    the colour anyone sees, and letting those vote would tint the ground towards the very halo this
    is trying to bury.
    """
    width, height = rgba.size
    inset_x, inset_y = int(width * (1 - _CORE_BOX) / 2), int(height * (1 - _CORE_BOX) / 2)
    core = rgba.crop((inset_x, inset_y, width - inset_x, height - inset_y))
    grid = min(_CORE_GRID, max(1, core.width), max(1, core.height))
    sample = core.resize((grid, grid), Image.Resampling.NEAREST)
    counts: Counter[tuple[int, int, int]] = Counter(
        (red, green, blue) for red, green, blue, band in sample.getdata()
        if band >= _OPAQUE_FLOOR)
    if not counts:
        return _FALLBACK_GROUND
    return counts.most_common(1)[0][0]


__all__ = ["AlphaVerdict", "FlattenResult", "flatten_frame", "inspect_frame"]
