"""SPIKE — RETIRED after Wave 1. Never imported by production code.

Verifies the spike-C Seedance result is a real, well-formed mp4 WITHOUT ffmpeg
(the engine never ships ffmpeg — D10/§8b): parses the ISO-BMFF box tree for
mvhd duration, tkhd track geometry, and whether an audio track (soun hdlr)
exists at all. Also scrapes kie.ai's per-model pricingDesc strings.
"""

from __future__ import annotations

import pathlib
import re
import struct
import sys

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ART = pathlib.Path(__file__).resolve().parent / "artifacts"


def boxes(buf: bytes, start: int, end: int, depth: int = 0):
    off = start
    while off + 8 <= end:
        size = struct.unpack(">I", buf[off:off + 4])[0]
        typ = buf[off + 4:off + 8].decode("latin1")
        body = off + 8
        if size == 1:
            size = struct.unpack(">Q", buf[off + 8:off + 16])[0]
            body = off + 16
        if size == 0:
            size = end - off
        yield typ, body, off + size, depth
        if typ in ("moov", "trak", "mdia", "minf", "stbl", "udta"):
            yield from boxes(buf, body, off + size, depth + 1)
        off += size
        if size <= 0:
            break


def inspect(p: pathlib.Path) -> None:
    b = p.read_bytes()
    print(f"\n== {p.name}  {len(b)} bytes  ftyp={b[8:12].decode('latin1', 'replace')}")
    handlers, tracks = [], []
    for typ, body, endb, depth in boxes(b, 0, len(b)):
        if typ == "mvhd":
            ver = b[body]
            if ver == 1:
                ts, dur = struct.unpack(">IQ", b[body + 12:body + 24])
            else:
                ts, dur = struct.unpack(">II", b[body + 12:body + 20])
            print(f"   mvhd: timescale={ts} duration={dur} -> {dur / ts:.3f} s")
        elif typ == "tkhd":
            ver = b[body]
            base = body + (32 if ver == 1 else 20)
            w, h = struct.unpack(">II", b[base + 52:base + 60])
            tracks.append((w >> 16, h >> 16))
        elif typ == "hdlr":
            handlers.append(b[body + 8:body + 12].decode("latin1", "replace"))
    print(f"   track geometry (tkhd): {[t for t in tracks if t != (0, 0)]}")
    print(f"   handlers: {handlers}  -> audio track present: {'soun' in handlers}")


for name in ("spike_c_result_2_0.mp4", "spike_c_ref_video.mp4"):
    f = ART / name
    if f.exists():
        inspect(f)

print("\n== kie.ai per-model pricingDesc ==")
for slug in ("gpt-image-2", "seedance-2-5"):
    try:
        r = httpx.get(f"https://kie.ai/{slug}", timeout=90, follow_redirects=True,
                      headers={"user-agent": "Mozilla/5.0"})
    except Exception as e:  # noqa: BLE001
        print(f"  {slug}: ERR {e}")
        continue
    for m in set(re.findall(r'\\"path\\":\\"([a-z0-9\-]+)\\".{0,400}?pricingDesc\\":\\"(.*?)\\"', r.text)):
        print(f"  [{slug}] {m[0]}: {m[1][:400]}")
