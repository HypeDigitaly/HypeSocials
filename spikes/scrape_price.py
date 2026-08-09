"""SPIKE — RETIRED after Wave 1. Never imported by production code.

Scrapes kie.ai's public pricing surface for the credit->USD rate and the
Seedance 2.5 unit price, so the MEASURED credit delta from spike C can be
decomposed into (output seconds, input-video seconds, image cost).
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ART = pathlib.Path(__file__).resolve().parent / "artifacts"
ART.mkdir(exist_ok=True)
UA = {"user-agent": "Mozilla/5.0"}

PAGES = [
    "https://kie.ai/pricing",
    "https://kie.ai/seedance-2-5",
    "https://kie.ai/features/seedance-2-5-api",
    "https://kie.ai/api/seedance-2-5",
]

for u in PAGES:
    try:
        r = httpx.get(u, timeout=90, follow_redirects=True, headers=UA)
    except Exception as e:  # noqa: BLE001
        print(f"== {u} ERR {type(e).__name__}: {e}")
        continue
    t = r.text
    name = re.sub(r"[^a-z0-9]+", "_", u.split("//", 1)[1]) + ".html"
    (ART / name).write_text(t, encoding="utf-8")
    print(f"== {u} -> {r.status_code} len={len(t)}")
    hits = [m.start() for m in re.finditer(r"seedance[-_ ]?2[-.]5|Seedance 2\.5", t, re.I)]
    print(f"   seedance-2.5 hits: {len(hits)}")
    seen: set[str] = set()
    for i in hits[:40]:
        frag = re.sub(r"\s+", " ", t[max(0, i - 500): i + 500])
        if frag[:80] in seen:
            continue
        seen.add(frag[:80])
        if re.search(r"credit|\$|price|Price", frag):
            print("   ---", frag[:600])
    # Any explicit "N credits" figures near video pricing
    for m in set(re.findall(r"[^\"<>\n]{0,60}\d+\s*credits?[^\"<>\n]{0,60}", t, re.I)):
        s = m.strip()
        if re.search(r"video|second|duration|seedance|per", s, re.I):
            print("   $$", s[:160])
