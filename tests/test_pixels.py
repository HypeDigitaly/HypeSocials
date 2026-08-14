"""Header-level image measurement — what a delivered render ACTUALLY is (FR-98, v2.1.4).

`meta.yaml`'s `native_size_rendered` is documented as "what came back", and every writer of it
filled in the ratio the job REQUESTED instead. Run `20260814_010814_glz0` shipped a deck whose
anchor came back 1536x1024 under a meta line asserting `native_size_rendered: '1:1'`.

This file pins the measurement itself: the three containers a render provider returns, the ratio
label, the >2% mismatch warning, and — the property that keeps this cheap fix cheap — that an
unreadable, unknown or truncated file is answered with `None` rather than with a guess or a
traceback. Nothing here touches the network; the fixtures are bytes.

Pillow appears only as a FIXTURE ENCODER (`hypesocials/generate/pixels.py` imports nothing but
`struct`, `math` and `pathlib`): a header this file assembled by hand could agree with a parser
that is wrong about the format, so the PNG/JPEG/WebP samples are encoded by a real encoder and the
one hand-built sample is the deliberately malformed one.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from hypesocials.generate import pixels


class Log:
    """`outputs.LogWriter`'s `.warn()` and nothing else — the only method this module calls."""

    def __init__(self) -> None:
        self.lines: list[tuple[str, str, dict]] = []

    def warn(self, event_type: str, message: str = "", **data: object) -> None:
        self.lines.append((event_type, message, dict(data)))

    def fields(self, event_type: str) -> dict:
        return next((data for name, _, data in self.lines if name == event_type), {})


def encoded(width: int, height: int, fmt: str, **options: object) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (12, 34, 56)).save(buffer, format=fmt, **options)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("fmt", "options", "why"),
    [
        ("PNG", {}, "PNG states width and height in IHDR, the first chunk by specification"),
        ("JPEG", {}, "JPEG states them in the SOF segment, reached by walking marker lengths"),
        ("WEBP", {"lossless": True}, "WebP lossless packs two 14-bit fields into VP8L"),
        ("WEBP", {"lossless": False}, "WebP lossy states them after the VP8 sync code"),
    ])
@pytest.mark.parametrize(("width", "height"), [(1536, 1024), (1024, 1024), (1080, 1920), (7, 3)])
def test_the_three_containers_a_render_provider_returns_are_all_measured(
    fmt: str, options: dict, why: str, width: int, height: int, tmp_path: Path,
) -> None:
    """One table over every container × every shape this engine asks a provider for.

    The odd 7x3 row is not decoration: it is the case where a parser that read the fields in the
    wrong ORDER still passes on square images and every 16:9 test anyone would write by hand.
    """
    path = tmp_path / f"render.{fmt.lower()}"
    path.write_bytes(encoded(width, height, fmt, **options))

    assert pixels.image_size(path) == (width, height), why


def test_a_jpeg_carrying_an_exif_thumbnail_reports_the_image_and_not_the_thumbnail(
    tmp_path: Path,
) -> None:
    """The reason the JPEG reader WALKS segment lengths instead of scanning for `FF C0`.

    An EXIF thumbnail is a whole second JPEG living inside the APP1 segment of the first. A parser
    that searched the byte stream for the first start-of-frame marker would happily report the
    thumbnail's dimensions — a plausible, wrong, small number — as the render's native size.
    """
    # A hand-built APP1 whose payload contains a 160x120 start-of-frame — the shape of an embedded
    # thumbnail, assembled here because the point is the DECOY, not Pillow's EXIF writer.
    decoy = b"Exif\x00\x00" + b"\xff\xc0\x00\x11\x08\x00\x78\x00\xa0" + b"\x00" * 24
    # A segment's length counts its own two length bytes and not the marker — get that wrong and
    # the walk lands mid-payload, which is exactly the bug this test is here to catch.
    app1 = b"\xff\xe1" + (len(decoy) + 2).to_bytes(2, "big") + decoy
    # SOF states HEIGHT before WIDTH, so these bytes are a 1536-wide, 1024-tall frame.
    sof = (b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08"
           + (1024).to_bytes(2, "big") + (1536).to_bytes(2, "big") + b"\x03" + b"\x00" * 9)
    path = tmp_path / "render.jpg"
    path.write_bytes(b"\xff\xd8" + app1 + sof + b"\xff\xda\x00\x08" + b"\x00" * 6)

    assert pixels.image_size(path) == (1536, 1024), "the walk stepped OVER the thumbnail"


@pytest.mark.parametrize(
    ("data", "why"),
    [
        (b"", "an empty file"),
        (b"\x89PNG\r\n\x1a\n", "a PNG magic with no IHDR behind it"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, "a PNG whose IHDR chunk name is wrong"),
        (b"\xff\xd8fake-jpeg-bytes", "a JPEG magic with no marker segments"),
        (b"RIFF\x00\x00\x00\x00WEBPXXXX" + b"\x00" * 40, "a WebP chunk this parser cannot read"),
        (b"GIF89a" + b"\x00" * 40, "a container nothing in this engine renders"),
        (b"\x00\x00\x00\x18ftypmp42", "an MP4 — the reel path's own bytes, correctly declined"),
    ])
def test_an_unreadable_or_unknown_file_measures_as_nothing_rather_than_as_a_guess(
    data: bytes, why: str, tmp_path: Path,
) -> None:
    """Every failure mode is `None`, and `None` is a real answer (§0.14c's shape, applied here).

    A meta field is not worth failing a paid creative over, so nothing in this module raises: the
    caller records the ratio it requested, exactly as it did before this measurement existed.
    """
    path = tmp_path / "render.bin"
    path.write_bytes(data)

    assert pixels.image_size(path) is None, why


def test_a_file_that_is_not_there_measures_as_nothing(tmp_path: Path) -> None:
    """The OSError path, which is the one a disk-full run reaches."""
    assert pixels.image_size(tmp_path / "never-written.png") is None


@pytest.mark.parametrize(
    ("width", "height", "label"),
    [(1024, 1024, "1:1"), (1536, 1024, "3:2"), (1080, 1920, "9:16"), (1200, 1500, "4:5"),
     (1920, 1080, "16:9"), (1000, 999, "1000:999"), (0, 100, ""), (100, 0, "")])
def test_the_ratio_label_reduces_honestly_including_when_it_does_not_reduce_prettily(
    width: int, height: int, label: str,
) -> None:
    """GCD reduction, and no rounding to a nearby "nice" ratio.

    1000x999 is not 1:1 and must not be printed as 1:1 — a size that ALMOST matches is exactly the
    finding an operator comparing two runs is looking for, and rounding it away is how the old
    `native_size_rendered` came to say `'1:1'` about a 3:2 picture.
    """
    assert pixels.ratio_label(width, height) == label


def test_native_size_states_the_measurement_and_warns_past_two_percent(tmp_path: Path) -> None:
    """The glz0 line itself: 1536x1024 delivered against a 1:1 request."""
    path = tmp_path / "image.png"
    path.write_bytes(encoded(1536, 1024, "PNG"))
    log = Log()

    recorded = pixels.native_size(path, "1:1", log=log, asset_id="0001_carousel_linkedin")

    assert recorded == "1536x1024 (3:2)"
    fields = log.fields("aspect_mismatch")
    assert fields["requested"] == "1:1" and fields["rendered"] == "1536x1024 (3:2)"
    assert fields["asset_id"] == "0001_carousel_linkedin", "the warning names the creative"
    assert round(fields["deviation"], 2) == 0.5, "a 3:2 answer is 50% wider than a square"


@pytest.mark.parametrize(
    ("width", "height", "requested", "warned"),
    [
        (1024, 1024, "1:1", False),                 # exact
        (1080, 1920, "9:16", False),                # exact
        (1024, 1792, "9:16", False),                # 4:7 — 1.6% off, the provider's own grid
        (1344, 768, "16:9", False),                 # 7:4 — 1.6% off, likewise
        (1536, 1024, "1:1", True),                  # the glz0 shape: 50% off
        (1024, 1536, "4:5", True),                  # 2:3 against 4:5 — 17% off
        (1024, 1024, "auto", False),                # nothing was requested to deviate from
        (1024, 1024, "", False),                    # nor here
    ])
def test_only_a_real_deviation_is_announced(
    width: int, height: int, requested: str, warned: bool, tmp_path: Path,
) -> None:
    """`aspect_mismatch` has to stay rare to stay readable.

    The tolerance exists for a provider rounding to its own pixel grid — 1024x1792 against a 9:16
    request is 1.6% off and is the SAME picture anyone asked for — not for a different shape; and a
    job that requested `auto` asked the provider to choose, so there is no requested shape to
    deviate from and no warning to give.
    """
    path = tmp_path / "image.png"
    path.write_bytes(encoded(width, height, "PNG"))
    log = Log()

    recorded = pixels.native_size(path, requested, log=log)

    assert recorded == f"{width}x{height} ({pixels.ratio_label(width, height)})"
    assert bool(log.lines) is warned


def test_an_unmeasurable_file_records_the_requested_ratio_and_says_nothing(tmp_path: Path) -> None:
    """The fallback is the pre-v2.1.4 value, which keeps the field non-empty for the gallery."""
    path = tmp_path / "image.jpg"
    path.write_bytes(b"\xff\xd8fake-jpeg-bytes")
    log = Log()

    assert pixels.native_size(path, "4:5", log=log) == "4:5"
    assert not log.lines


def test_the_measurement_never_imports_pillow(tmp_path: Path) -> None:
    """D46/D48 keep exactly one Pillow user in the tree (`sources/logo_crops.py`).

    Reading four big-endian integers does not justify a decoder, and a second importer would make
    "no media libraries" (CLAUDE.md stack rules) a claim with two exceptions instead of one.
    """
    source = Path(pixels.__file__).read_text(encoding="utf-8")

    assert "PIL" not in source and "Image" not in source
    assert "import struct" in source
