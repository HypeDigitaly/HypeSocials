"""What a delivered render ACTUALLY is — pixel dimensions read from the file's own header.

Purpose: meta.yaml's `native_size_rendered` is documented as "what came back" (FR-98), and until
v2.1.4 every writer of that field filled it with the ratio the job REQUESTED. Run
`20260814_010814_glz0` shipped a deck whose anchor came back 1536×1024 under a meta line asserting
`native_size_rendered: '1:1'` — a 3:2 picture recorded as a square, in the one document a Phase-2
publisher and the gallery both read as fact.

Public API: `image_size(path)` · `ratio_label(width, height)` · `native_size(path, requested, …)`.

Invariants:
- **Header bytes only, stdlib only.** PNG's IHDR, JPEG's SOF marker and WebP's VP8/VP8L/VP8X
  chunks each state their dimensions in the first few dozen bytes. Pillow stays where D48 put it
  (`sources/logo_crops.py`, the one place in this tree that decodes an image), because reading
  four big-endian integers does not justify a decoder or an import.
- **Unmeasurable is not an error.** An unreadable file, an unknown container or a truncated header
  returns `None`, and the caller records what it requested — exactly the pre-v2.1.4 behaviour. A
  meta field is not worth failing a paid creative over.
- **Record and warn, never re-render.** `native_size` states the measurement and emits
  `aspect_mismatch` when the provider's answer is more than `_TOLERANCE` off the ratio the job
  asked for. Acting on that (a re-render, a crop) is a decision this module does not make.

The read is synchronous and deliberately small: at most `_HEAD` bytes of a file that is already on
the local disk, taking microseconds, in the same class as `prompts_engine`'s template reads. It is
never the download.
"""

from __future__ import annotations

import struct
from math import gcd
from pathlib import Path
from typing import Any

#: Enough for PNG's IHDR and WebP's chunk headers many times over, and enough JPEG to reach the
#: SOF marker past a fat EXIF/ICC block. A header this large that still has not stated a size is
#: a file this module declines to guess about.
_HEAD = 64 * 1024
#: JPEG start-of-frame markers. `C4` (Huffman tables), `C8` (reserved) and `CC` (arithmetic coding
#: conditioning) share the range and are NOT frame headers — reading a size out of one is how a
#: naive parser reports a Huffman table's length as an image width.
_SOF = {*range(0xC0, 0xD0)} - {0xC4, 0xC8, 0xCC}
#: Ratio drift the operator does not need told about: rounding to a model's pixel grid (a 1080×1920
#: 9:16 frame is exact, a 1024×1792 one is 0.6% off) is not a mismatch, a landscape render of a
#: square job is.
_TOLERANCE = 0.02


def image_size(path: Path | str) -> tuple[int, int] | None:
    """`(width, height)` in pixels, read from the file header — or `None` if it cannot be read.

    PNG, JPEG and WebP (lossy, lossless and extended) are recognised, which is everything the
    render providers return for an image job. Anything else — a video, a truncated download, a
    container this function does not know — is `None`, never a guess and never an exception.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(_HEAD)
    except OSError:
        return None
    return _size_from(head)


def ratio_label(width: int, height: int) -> str:
    """`(1536, 1024)` -> `"3:2"` — the aspect ratio in the vocabulary the config speaks.

    Reduced by GCD, which is exactly right for the ratios this engine asks for (1:1, 4:5, 16:9,
    9:16 all come back clean). A ratio that does not reduce to small numbers is reported as it
    reduces: an honest odd number beats a rounded pretty one.
    """
    if width <= 0 or height <= 0:
        return ""
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def native_size(path: Path | str, requested: str, *, log: Any = None, **fields: Any) -> str:
    """FR-98's `native_size_rendered`, measured: `"1536x1024 (3:2)"`, or `requested` unmeasured.

    The requested ratio stays the fallback because the field must never be empty — the gallery
    prints `ratio 1:1 → <this>` and an empty half of that arrow reads as a broken run rather than
    as an unmeasured file.

    Emits ONE `aspect_mismatch` warning when the measured ratio deviates from `requested` by more
    than `_TOLERANCE`. It is a record, not a remedy: this round records and warns, and nothing
    re-renders — a paid picture of the wrong shape is still a paid picture, and re-rendering it
    automatically is a spend decision that belongs to the Confirm gate, not to a packager.
    `fields` are passed through to the log line (`asset_id`, `slide`) so the warning names the
    creative without this module knowing what a creative is.
    """
    measured = image_size(path)
    if measured is None:
        return requested
    width, height = measured
    label = ratio_label(width, height)
    size = f"{width}x{height}" + (f" ({label})" if label else "")
    wanted = _ratio_value(requested)
    if log is not None and wanted and abs((width / height) - wanted) / wanted > _TOLERANCE:
        log.warn("aspect_mismatch",
                 f"the render came back {width}x{height} ({label}) for a job that requested "
                 f"{requested} — a {abs((width / height) - wanted) / wanted:.1%} deviation. It "
                 "ships exactly as rendered (FR-98: no crop, no pad) and meta.yaml records the "
                 "size it really is; nothing is re-rendered for it",
                 requested=requested, rendered=size, width=width, height=height,
                 deviation=round(abs((width / height) - wanted) / wanted, 4), **fields)
    return size


# --------------------------------------------------------------------------------- the headers


def _size_from(head: bytes) -> tuple[int, int] | None:
    """Dispatch on the container's magic bytes; `None` for anything unrecognised."""
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return _png(head)
    if head[:2] == b"\xff\xd8":
        return _jpeg(head)
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return _webp(head)
    return None


def _png(head: bytes) -> tuple[int, int] | None:
    """IHDR is the first chunk by specification: width and height are two big-endian uint32."""
    if len(head) < 24 or head[12:16] != b"IHDR":
        return None
    return _checked(*struct.unpack(">II", head[16:24]))


def _jpeg(head: bytes) -> tuple[int, int] | None:
    """Walk the marker segments to the frame header — `FF Cx len(2) precision(1) H(2) W(2)`.

    Segment lengths are what make this a walk rather than a scan: an EXIF thumbnail inside APP1 is
    a whole second JPEG, and a parser that searched for the first `FF C0` byte pair would happily
    report the thumbnail's dimensions as the image's.
    """
    index = 2
    while index + 3 < len(head):
        if head[index] != 0xFF:  # not on a marker boundary: the header is malformed or truncated
            return None
        marker = head[index + 1]
        if marker in (0xFF, 0x01) or 0xD0 <= marker <= 0xD9:  # padding/TEM/RSTn/SOI/EOI: no length
            index += 1 if marker == 0xFF else 2
            continue
        length = int.from_bytes(head[index + 2:index + 4], "big")
        if marker in _SOF:
            if index + 9 > len(head):
                return None
            height, width = struct.unpack(">HH", head[index + 5:index + 9])
            return _checked(width, height)
        if length < 2:
            return None
        index += 2 + length
    return None


def _webp(head: bytes) -> tuple[int, int] | None:
    """The three chunk flavours, each stating its size differently (RIFF container, little-endian).

    `VP8X` is the extended header (24-bit canvas size minus one), `VP8 ` the lossy bitstream (two
    14-bit fields after the 3-byte sync code) and `VP8L` the lossless one (two 14-bit fields packed
    across a 32-bit word).
    """
    chunk = head[12:16]
    if chunk == b"VP8X" and len(head) >= 30:
        width = int.from_bytes(head[24:27], "little") + 1
        height = int.from_bytes(head[27:30], "little") + 1
        return _checked(width, height)
    if chunk == b"VP8 " and len(head) >= 30 and head[23:26] == b"\x9d\x01\x2a":
        width, height = struct.unpack("<HH", head[26:30])
        return _checked(width & 0x3FFF, height & 0x3FFF)
    if chunk == b"VP8L" and len(head) >= 25 and head[20] == 0x2F:
        bits = int.from_bytes(head[21:25], "little")
        return _checked((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    return None


def _checked(width: int, height: int) -> tuple[int, int] | None:
    """A zero side is a header this parser misread; report nothing rather than a nonsense ratio."""
    return (width, height) if width > 0 and height > 0 else None


def _ratio_value(requested: str) -> float:
    """`"16:9"` -> 1.777…; 0.0 for `auto`, an empty string or anything unparseable.

    0.0 disables the comparison, which is the honest answer for a job that asked the provider to
    choose: there is no requested shape to deviate from.
    """
    parts = str(requested or "").split(":")
    if len(parts) != 2:
        return 0.0
    try:
        width, height = float(parts[0]), float(parts[1])
    except ValueError:
        return 0.0
    return width / height if width > 0 and height > 0 else 0.0


__all__ = ["image_size", "native_size", "ratio_label"]
