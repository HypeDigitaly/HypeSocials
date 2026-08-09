"""SPIKE — RETIRED after Wave 1. Never imported by production code.

Day-one spikes (T0.3) settling OQ-2, OQ-17 residual, OQ-19/20/21/22, the mkv
upload spot-check (20-integrations §8b) and the $0 Windows signal mechanism.

Usage (from repo root, venv active):
    python spikes/day_one.py docs        # $0 — scrape Kie doc pages for exact param names
    python spikes/day_one.py virlo       # spike A ($0 model spend; Virlo metering unknown)
    python spikes/day_one.py image       # spike B (~$0.03-0.05)
    python spikes/day_one.py seedance    # spike C (~$0.5-1) + spike D (real mp4 upload)
    python spikes/day_one.py mkv         # spike D ($0)
    python spikes/day_one.py luna        # spike E (~$0.01)
    python spikes/day_one.py signals     # spike F ($0)
    python spikes/day_one.py credit      # $0 — Kie credit balance probe

Secrets: loaded from .env via python-dotenv INSIDE this process only. Keys are
never printed, logged, or written to any artifact (D30 / NFR-112).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
SPIKES = REPO / "spikes"
ART = SPIKES / "artifacts"
ART.mkdir(parents=True, exist_ok=True)

load_dotenv(REPO / ".env")

VIRLO_BASE = "https://api.virlo.ai/v1"
KIE_BASE = "https://api.kie.ai"
KIE_UPLOAD = "https://kieai.redpandaai.co"
OPENROUTER = "https://openrouter.ai/api/v1"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def key(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"missing env var {name}")
    return v


# ---------------------------------------------------------------- shape utils

def shape(obj: Any, indent: int = 0, trunc: int = 70, max_list: int = 1) -> str:
    """Render a JSON value's SHAPE: keys, types, one example item, truncated values."""
    pad = "  " * indent
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        lines = ["{"]
        for k, v in obj.items():
            lines.append(f"{pad}  {k}: {shape(v, indent + 1, trunc, max_list)}")
        lines.append(pad + "}")
        return "\n".join(lines)
    if isinstance(obj, list):
        if not obj:
            return "[] (empty)"
        head = obj[:max_list]
        body = "\n".join(
            f"{pad}  [{i}] {shape(v, indent + 1, trunc, max_list)}" for i, v in enumerate(head)
        )
        return f"[len={len(obj)}]\n{body}"
    if isinstance(obj, str):
        s = obj.replace("\n", "\\n")
        if len(s) > trunc:
            s = s[:trunc] + f"…(len={len(obj)})"
        return f'"{s}"'
    return f"{obj!r}"


def save(name: str, data: Any) -> Path:
    p = ART / name
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def hdr_note(resp: httpx.Response) -> dict[str, str]:
    """Response headers that could carry billing/credit/rate info (never request headers)."""
    keep = {}
    for k, v in resp.headers.items():
        lk = k.lower()
        if any(t in lk for t in ("credit", "cost", "bill", "quota", "limit", "usage", "balance", "price")):
            keep[k] = v
    return keep


# ------------------------------------------------------------- spike: docs ($0)

DOC_URLS = [
    "https://docs.kie.ai/llms.txt",
    "https://docs.kie.ai/llms-full.txt",
]


async def spike_docs() -> None:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
        for u in DOC_URLS:
            try:
                r = await c.get(u)
                print(f"{u} -> {r.status_code} len={len(r.text)}")
                if r.status_code == 200:
                    (ART / u.rsplit("/", 1)[-1]).write_text(r.text, encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                print(f"{u} -> ERROR {type(e).__name__}: {e}")


# ---------------------------------------------------------- spike A: Virlo live

async def spike_virlo() -> None:
    h = {"Authorization": f"Bearer {key('VIRLO_API_KEY')}"}
    findings: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=60, headers=h) as c:

        async def call(path: str) -> tuple[int, Any, dict[str, str]]:
            t0 = time.monotonic()
            r = await c.get(f"{VIRLO_BASE}{path}")
            dt = time.monotonic() - t0
            try:
                body = r.json()
            except Exception:  # noqa: BLE001
                body = {"__non_json__": r.text[:500]}
            print(f"\n=== GET {path} -> {r.status_code} ({dt:.2f}s)")
            print("  billing-ish headers:", hdr_note(r) or "(none)")
            print("  shape:")
            print(shape(body, 1))
            return r.status_code, body, dict(r.headers)

        st, agents, agents_hdrs = await call("/agents")
        findings["agents"] = {"status": st, "body": agents, "headers": agents_hdrs}

        # Extract monitor ids/names
        items = agents if isinstance(agents, list) else None
        if items is None and isinstance(agents, dict):
            for k in ("data", "agents", "items", "results", "monitors"):
                if isinstance(agents.get(k), list):
                    items = agents[k]
                    break
        monitors = []
        for it in items or []:
            if isinstance(it, dict):
                mid = it.get("id") or it.get("agent_id") or it.get("_id")
                name = it.get("name") or it.get("title") or it.get("theme") or it.get("niche")
                monitors.append({"id": mid, "name": name, "raw_keys": sorted(it.keys())})
        findings["monitors"] = monitors
        print("\n--- MONITORS ---")
        for m in monitors:
            print(f"  {m['id']}  |  {m['name']}")

        if monitors and monitors[0]["id"]:
            mid = monitors[0]["id"]
            findings["monitor_used"] = mid
            for sub in (f"/agents/{mid}", f"/agents/{mid}/videos", f"/agents/{mid}/slideshows"):
                st, body, _ = await call(sub)
                findings[sub] = {"status": st, "body": body}

        st, digest, _ = await call("/trends/digest")
        findings["/trends/digest"] = {"status": st, "body": digest}

    p = save("virlo_findings.json", findings)
    print(f"\nsaved -> {p}")


async def spike_virlo_monitor() -> None:
    """Second half of spike A: the three per-monitor endpoints for ONE real monitor id.

    Split out so re-runs never re-pay for /trends/digest (metered: see x-cost header).
    """
    mid = os.environ.get("SPIKE_MONITOR_ID") or "9c96fddf-dc35-4be0-bbd9-12f4d22aea12"
    findings = json.loads((ART / "virlo_findings.json").read_text(encoding="utf-8"))
    findings["monitor_used"] = mid
    h = {"Authorization": f"Bearer {key('VIRLO_API_KEY')}"}
    async with httpx.AsyncClient(timeout=90, headers=h) as c:
        for sub in (f"/agents/{mid}", f"/agents/{mid}/videos", f"/agents/{mid}/slideshows"):
            t0 = time.monotonic()
            r = await c.get(f"{VIRLO_BASE}{sub}")
            dt = time.monotonic() - t0
            try:
                body = r.json()
            except Exception:  # noqa: BLE001
                body = {"__non_json__": r.text[:500]}
            print(f"\n=== GET {sub} -> {r.status_code} ({dt:.2f}s)")
            print("  billing headers:", hdr_note(r) or "(none)")
            print("  shape:")
            print(shape(body, 1))
            findings[sub] = {"status": r.status_code, "body": body, "billing": hdr_note(r)}
    save("virlo_findings.json", findings)
    print("\nsaved -> virlo_findings.json")


# ------------------------------------------------- Kie helpers (B / C / D)

async def kie_create(client: httpx.AsyncClient, model: str, inp: dict) -> tuple[int, dict]:
    body = {"model": model, "input": inp}
    r = await client.post(f"{KIE_BASE}/api/v1/jobs/createTask", json=body)
    try:
        j = r.json()
    except Exception:  # noqa: BLE001
        j = {"__non_json__": r.text[:800]}
    print(f"createTask({model}) -> HTTP {r.status_code}")
    print(shape(j, 1))
    return r.status_code, j


async def kie_poll(client: httpx.AsyncClient, task_id: str, timeout_s: int, interval: float = 3.0) -> dict:
    """Poll recordInfo to terminal. Records every distinct state seen with monotonic elapsed."""
    t0 = time.monotonic()
    seen: list[tuple[float, str]] = []
    last_state = None
    last: dict = {}
    while True:
        elapsed = time.monotonic() - t0
        if elapsed > timeout_s:
            print(f"TIMEOUT after {elapsed:.1f}s (states seen: {seen})")
            last["__timeout__"] = True
            break
        try:
            r = await client.get(f"{KIE_BASE}/api/v1/jobs/recordInfo", params={"taskId": task_id})
            j = r.json()
        except Exception as e:  # noqa: BLE001
            print(f"  poll error (non-terminal): {type(e).__name__}: {e}")
            await asyncio.sleep(interval)
            continue
        last = j
        data = j.get("data") or {}
        state = data.get("state")
        if state != last_state:
            seen.append((round(elapsed, 1), state))
            print(f"  t+{elapsed:6.1f}s state={state}")
            last_state = state
        if state in ("success", "fail"):
            break
        await asyncio.sleep(interval if elapsed < 60 else 10.0)
    last["__states_observed__"] = seen
    last["__elapsed_s__"] = round(time.monotonic() - t0, 1)
    return last


async def kie_upload(client: httpx.AsyncClient, path: Path, upload_path: str) -> dict:
    with path.open("rb") as fh:
        files = {"file": (path.name, fh, "application/octet-stream")}
        data = {"uploadPath": upload_path, "fileName": path.name}
        r = await client.post(f"{KIE_UPLOAD}/api/file-stream-upload", files=files, data=data)
    try:
        j = r.json()
    except Exception:  # noqa: BLE001
        j = {"__non_json__": r.text[:800]}
    print(f"file-stream-upload({path.name}, {path.stat().st_size}B) -> HTTP {r.status_code}")
    print(shape(j, 1))
    j["__http_status__"] = r.status_code
    return j


async def download(url: str, dest: Path) -> int:
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return len(r.content)


def kie_client(timeout: int = 120) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout,
        headers={"Authorization": f"Bearer {key('KIE_API_KEY')}"},
    )


# ---------------------------------------------------------- spike: credit ($0)

CREDIT_PATHS = [
    "/api/v1/chat/credit",
    "/api/v1/common/credit",
    "/api/v1/user/credit",
]


async def spike_credit(label: str = "credit") -> dict:
    out = {}
    async with kie_client(60) as c:
        for p in CREDIT_PATHS:
            try:
                r = await c.get(f"{KIE_BASE}{p}")
                try:
                    j = r.json()
                except Exception:  # noqa: BLE001
                    j = {"__non_json__": r.text[:300]}
                print(f"GET {p} -> {r.status_code}: {json.dumps(j, ensure_ascii=False)[:300]}")
                out[p] = {"status": r.status_code, "body": j}
            except Exception as e:  # noqa: BLE001
                print(f"GET {p} -> ERROR {type(e).__name__}: {e}")
                out[p] = {"error": f"{type(e).__name__}: {e}"}
    save(f"kie_{label}.json", out)
    return out


# --------------------------------------------------- spike B: GPT Image 2 refs

IMAGE_PROMPT = (
    "Recreate this visual template as a new social post. Mimic the reference images' "
    "layout structure, colour palette, typography weight and composition. "
    "Replace all headline copy with exactly this text, spelled correctly: SPIKE TEST. "
    "Do NOT copy any text, watermark, username, logo or platform UI element from the "
    "references. No TikTok/Instagram interface chrome. Clean edges, text fully inside frame."
)


async def spike_image(ref_urls: list[str] | None = None) -> None:
    if not ref_urls:
        f = json.loads((ART / "virlo_findings.json").read_text(encoding="utf-8"))
        ref_urls = f.get("__chosen_refs__") or []
    if not ref_urls:
        raise SystemExit("no reference URLs — run `virlo` first and set __chosen_refs__")
    print("references:")
    for u in ref_urls:
        print("  ", u)

    inp = {
        "prompt": IMAGE_PROMPT,
        "input_urls": ref_urls,
        "aspect_ratio": "1:1",
        "resolution": "1K",
    }
    async with kie_client() as c:
        st, created = await kie_create(c, "gpt-image-2-image-to-image", inp)
        if st != 200 or not (created.get("data") or {}).get("taskId"):
            save("image_create_failed.json", {"request_input": inp, "response": created})
            raise SystemExit("createTask failed — see spikes/artifacts/image_create_failed.json")
        task_id = created["data"]["taskId"]
        print(f"taskId={task_id}")
        rec = await kie_poll(c, task_id, timeout_s=300)

    save("image_record.json", {"request_input": inp, "record": rec})
    data = rec.get("data") or {}
    urls = []
    rj = data.get("resultJson")
    if isinstance(rj, str):
        try:
            rj = json.loads(rj)
        except Exception:  # noqa: BLE001
            rj = {}
    if isinstance(rj, dict):
        urls = rj.get("resultUrls") or []
    print("resultUrls:", urls)
    print("costTime:", data.get("costTime"))
    for i, u in enumerate(urls):
        dest = ART / f"spike_b_result_{i}.png"
        n = await download(u, dest)
        print(f"downloaded {n}B -> {dest}")
    save("image_result_urls.json", {"urls": urls, "costTime": data.get("costTime")})


# ------------------------------------- spike C: Seedance price + image+video refs

SEEDANCE_PROMPT = (
    "Subject: the still frame in @Image1 comes alive. "
    "Camera: slow push-in, subtle handheld drift, matching the pacing and cut rhythm of @Video1. "
    "Motion: gentle parallax on the background, the on-frame text stays perfectly static, "
    "sharp and legible for the full clip. "
    "Lighting: keep the reference frame's palette and contrast. "
    "Audio: light ambient room tone. "
    "Do not add captions, watermarks or platform UI."
)

# Attempt-2 variant: `generate_audio: false`, so no output audio exists to fail
# Kie's output content-security audit ("output audio may be related to copyright
# restrictions" — the exact failMsg that killed attempt 1 with a music-bearing
# TikTok reference video).
SEEDANCE_PROMPT_SILENT = (
    "Subject: the still frame in @Image1 comes alive. "
    "Camera: slow push-in, subtle handheld drift, matching the pacing and cut rhythm of @Video1. "
    "Motion: gentle parallax on the background, the on-frame text stays perfectly static, "
    "sharp and legible for the full clip. "
    "Lighting: keep the reference frame's palette and contrast. "
    "Silent clip — no music, no song, no melody, no vocals, no soundtrack of any kind. "
    "Do not add captions, watermarks or platform UI."
)


async def ytdlp_probe(url: str) -> dict:
    """Metadata-only probe (FR-160): duration AND the format table.

    The format table matters because Kie's Seedance route constrains a reference
    video's TOTAL PIXELS to [409600, 927408] — a raw 1080x1920 TikTok download is
    over the ceiling and must be rejected at format-selection time, not by Kie.
    """
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "yt_dlp", "--no-warnings", "--skip-download", "--dump-single-json", url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        return {"__error__": err.decode("utf-8", "replace")[-400:], "__rc__": proc.returncode}
    try:
        j = json.loads(out.decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        return {"__error__": f"json: {e}"}
    fmts = []
    for f in j.get("formats") or []:
        w, h = f.get("width"), f.get("height")
        if not w or not h:
            continue
        fmts.append({"id": f.get("format_id"), "w": w, "h": h, "px": w * h,
                     "fps": f.get("fps"), "ext": f.get("ext"), "acodec": f.get("acodec"),
                     "px_ok": 409600 <= w * h <= 927408})
    return {"duration": j.get("duration"), "ext": j.get("ext"), "title": (j.get("title") or "")[:60],
            "extractor": j.get("extractor"), "formats": fmts,
            "px_ok_formats": [f for f in fmts if f["px_ok"] and f.get("acodec") not in (None, "none")]}


# Kie Seedance reference-video pixel window, from docs (verified 2026-08-09).
PX_MIN, PX_MAX = 409_600, 927_408


async def ytdlp_download(url: str, dest: Path, fmt_id: str | None = None) -> dict:
    fmt = fmt_id or f"b[width*height<={PX_MAX}][width*height>={PX_MIN}]/b[height<=1280]/b"
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "yt_dlp", "--no-warnings", "-f", fmt, "-o", str(dest), url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return {"rc": proc.returncode, "fmt": fmt, "stderr": err.decode("utf-8", "replace")[-600:],
            "exists": dest.exists(), "size": dest.stat().st_size if dest.exists() else 0}


async def spike_seedance(image_ref: str | None = None, video_candidates: list[str] | None = None) -> None:
    if image_ref is None:
        try:
            image_ref = json.loads((ART / "image_result_urls.json").read_text(encoding="utf-8"))["urls"][0]
        except Exception as e:  # noqa: BLE001
            raise SystemExit(f"need an image reference URL: {e}")
    if video_candidates is None:
        f = json.loads((ART / "virlo_findings.json").read_text(encoding="utf-8"))
        video_candidates = f.get("__video_candidates__") or []

    attempt = os.environ.get("SPIKE_ATTEMPT", "1")
    audio = os.environ.get("SPIKE_AUDIO", "1") == "1"
    preset_video = os.environ.get("SPIKE_VIDEO_URL") or None

    report: dict[str, Any] = {"attempt": attempt, "generate_audio": audio,
                              "image_ref": image_ref, "video_candidates": video_candidates}

    # 1) credit BEFORE
    print("\n--- Kie credit BEFORE ---")
    report["credit_before"] = await spike_credit(f"credit_before_{attempt}")

    # 2) video reference chain: probe -> qualify (<=28 s) -> download -> upload
    video_url = preset_video
    probes = []
    if preset_video:
        print(f"reusing already-uploaded reference video (<24 h URL): {preset_video}")
        video_candidates = []
    for cand in video_candidates[:8]:
        p = await ytdlp_probe(cand)
        p["url"] = cand
        probes.append(p)
        print(f"probe {cand} -> duration={p.get('duration')} err={p.get('__error__', '')[:120]} "
              f"px_ok_formats={[(f['id'], f['w'], f['h'], f['px']) for f in p.get('px_ok_formats') or []][:4]}")
        d = p.get("duration")
        ok = p.get("px_ok_formats") or []
        # Prefer H.264 over bytevc1/HEVC — Kie documents "mp4/mov" but not codecs,
        # and H.264 is the universally safe decode path.
        ok.sort(key=lambda f: (0 if "h264" in (f["id"] or "") else 1, -f["px"]))
        if isinstance(d, (int, float)) and 2 <= d <= 28 and ok:
            dest = ART / "spike_c_ref_video.mp4"
            dl = await ytdlp_download(cand, dest, fmt_id=ok[0]["id"])
            print("download:", dl)
            if dl["exists"] and dl["size"] > 0:
                async with kie_client(300) as c:
                    up = await kie_upload(c, dest, "hypesocials-spike")
                report["video_upload"] = up
                video_url = (up.get("data") or {}).get("downloadUrl") or (up.get("data") or {}).get("fileUrl") \
                    or (up.get("data") or {}).get("url")
                if video_url:
                    break
    report["probes"] = probes
    report["video_url_used"] = video_url

    inp: dict[str, Any] = {
        "prompt": SEEDANCE_PROMPT if audio else SEEDANCE_PROMPT_SILENT,
        "reference_image_urls": [image_ref],
        "duration": 5,
        "resolution": "720p",
        "aspect_ratio": "9:16",
        "generate_audio": audio,
        "nsfw_checker": True,
        "output_format": "mp4",
    }
    if video_url:
        inp["reference_video_urls"] = [video_url]
    else:
        print("!! no qualifying video reference — OQ-21 falls back to image-ref-only")

    rpt_name = f"seedance_report_{attempt}.json"
    async with kie_client(300) as c:
        st, created = await kie_create(c, "bytedance/seedance-2-5", inp)
        report["create_status"] = st
        report["create_response"] = created
        report["request_input"] = inp
        save(rpt_name, report)
        if st != 200 or not (created.get("data") or {}).get("taskId"):
            raise SystemExit(f"Seedance createTask failed — see spikes/artifacts/{rpt_name}")
        task_id = created["data"]["taskId"]
        print(f"taskId={task_id}")
        rec = await kie_poll(c, task_id, timeout_s=900)
    report["record"] = rec
    save(rpt_name, report)

    data = rec.get("data") or {}
    rj = data.get("resultJson")
    if isinstance(rj, str):
        try:
            rj = json.loads(rj)
        except Exception:  # noqa: BLE001
            rj = {}
    urls = (rj or {}).get("resultUrls") or []
    print("resultUrls:", urls)
    print("costTime:", data.get("costTime"))
    for i, u in enumerate(urls):
        dest = ART / f"spike_c_result_{attempt}_{i}.mp4"
        n = await download(u, dest)
        print(f"downloaded {n}B -> {dest}")
    report["result_urls"] = urls

    print("\n--- Kie credit AFTER ---")
    report["credit_after"] = await spike_credit(f"credit_after_{attempt}")
    save(rpt_name, report)


# -------------------------------------------------------- spike D: mkv upload

async def spike_mkv() -> None:
    junk = ART / "test.mkv"
    # Matroska EBML magic + junk bytes: tests FORMAT ACCEPTANCE of the upload API only.
    # This file is NOT a playable video — it proves nothing about Kie's ability to decode mkv.
    junk.write_bytes(b"\x1a\x45\xdf\xa3" + os.urandom(4096))
    async with kie_client(120) as c:
        res = await kie_upload(c, junk, "hypesocials-spike")
    save("mkv_upload.json", res)


# ------------------------------------------------------ spike E: Luna schema

LUNA_SCHEMA = {
    "name": "social_copy",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "hook": {"type": "string"},
            "caption": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["hook", "caption", "hashtags"],
        "additionalProperties": False,
    },
}


async def spike_luna() -> None:
    body = {
        "model": "openai/gpt-5.6-luna",
        "messages": [
            {"role": "system", "content": "You are a short-form social copywriter. Reply only with the schema."},
            {"role": "user", "content": "Write one Instagram post for an AI automation agency. "
                                        "Hook under 8 words, caption under 200 chars, 5 hashtags."},
        ],
        "response_format": {"type": "json_schema", "json_schema": LUNA_SCHEMA},
        "reasoning": {"effort": "low"},
        "max_tokens": 1200,
        # NO `temperature`: OpenRouter's model catalog shows openai/gpt-5.6-luna
        # (and anthropic/claude-sonnet-5) do NOT list `temperature` in
        # supported_parameters. Sending it together with require_parameters=true
        # returns HTTP 404 "No endpoints found that can handle the requested
        # parameters" — the first attempt of this spike did exactly that.
        "provider": {"require_parameters": True},  # FR-125: only schema-honoring providers
        "usage": {"include": True},
    }
    async with httpx.AsyncClient(
        timeout=180,
        headers={"Authorization": f"Bearer {key('OPENROUTER_API_KEY')}",
                 "Content-Type": "application/json"},
    ) as c:
        t0 = time.monotonic()
        r = await c.post(f"{OPENROUTER}/chat/completions", json=body)
        dt = time.monotonic() - t0
        try:
            j = r.json()
        except Exception:  # noqa: BLE001
            j = {"__non_json__": r.text[:1000]}
    print(f"HTTP {r.status_code} in {dt:.2f}s")
    print("billing-ish headers:", hdr_note(r) or "(none)")
    print(shape(j, 1, trunc=200))
    parsed_ok = None
    if r.status_code == 200:
        try:
            content = j["choices"][0]["message"]["content"]
            obj = json.loads(content)
            parsed_ok = sorted(obj.keys()) == ["caption", "hashtags", "hook"] and isinstance(obj["hashtags"], list)
            print("PARSED:", json.dumps(obj, ensure_ascii=False)[:400])
            print("schema-valid:", parsed_ok)
        except Exception as e:  # noqa: BLE001
            parsed_ok = False
            print("parse FAILED:", type(e).__name__, e)
    save("luna_response.json", {"request_body": body, "status": r.status_code,
                                "response": j, "schema_valid": parsed_ok,
                                "headers_billing": hdr_note(r)})


# ------------------------------------------------------ spike F: Windows signals

async def spike_signals() -> None:
    child = SPIKES / "signal_child.py"
    results: dict[str, Any] = {}

    # 1) add_signal_handler proof (one line, in-process, on a Proactor loop)
    import signal as _sig
    loop = asyncio.ProactorEventLoop()
    try:
        loop.add_signal_handler(_sig.SIGINT, lambda: None)
        results["add_signal_handler"] = "NO ERROR (unexpected)"
    except NotImplementedError as e:
        results["add_signal_handler"] = f"NotImplementedError: {e!r}"
    except Exception as e:  # noqa: BLE001
        results["add_signal_handler"] = f"{type(e).__name__}: {e}"
    finally:
        loop.close()
    print("loop.add_signal_handler(SIGINT) ->", results["add_signal_handler"])

    # 2) mechanism A: child self-raises SIGINT from a background thread
    print("\n--- mechanism A: signal.raise_signal(SIGINT) from a worker thread ---")
    p = await asyncio.create_subprocess_exec(
        sys.executable, str(child), "raise_signal",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await p.communicate()
    text_a = out.decode("utf-8", "replace")
    print(text_a)
    results["mechanism_raise_signal"] = {"rc": p.returncode, "output": text_a}

    # 3) mechanism B: external CTRL_C_EVENT to a child in its own process group
    print("\n--- mechanism B: GenerateConsoleCtrlEvent(CTRL_C_EVENT, child_pgid) ---")
    import subprocess
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    proc = subprocess.Popen(
        [sys.executable, str(child), "wait"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        creationflags=CREATE_NEW_PROCESS_GROUP,
    )
    await asyncio.sleep(4)  # let the child install its handler + spawn its subprocess
    sends = []
    for i in range(2):
        try:
            os.kill(proc.pid, _sig.CTRL_C_EVENT)
            sends.append(f"send#{i + 1}: ok")
        except Exception as e:  # noqa: BLE001
            sends.append(f"send#{i + 1}: {type(e).__name__}: {e}")
        await asyncio.sleep(3)
    try:
        text_b = proc.communicate(timeout=25)[0]
    except subprocess.TimeoutExpired:
        proc.kill()
        text_b = (proc.communicate()[0] or "") + "\n<<killed after timeout>>"
    print("\n".join(sends))
    print(text_b)
    results["mechanism_ctrl_c_event"] = {"rc": proc.returncode, "sends": sends, "output": text_b}

    save("signal_results.json", results)


async def _probe_only() -> None:
    """$0 dry run of the FR-160 probe/qualify half of the video-reference chain."""
    f = json.loads((ART / "virlo_findings.json").read_text(encoding="utf-8"))
    out = []
    for cand in (f.get("__video_candidates__") or [])[:8]:
        p = await ytdlp_probe(cand)
        p["url"] = cand
        out.append(p)
        print(f"\n{cand}\n  duration={p.get('duration')} err={str(p.get('__error__', ''))[:200]}")
        for fm in (p.get("formats") or [])[:40]:
            print(f"    {fm['id']:>22} {fm['w']}x{fm['h']} px={fm['px']} fps={fm['fps']} "
                  f"ext={fm['ext']} a={fm['acodec']} px_ok={fm['px_ok']}")
    save("ytdlp_probes.json", out)


# ------------------------------------------------------------------- dispatch

ACTIONS = {
    "docs": spike_docs,
    "virlo": spike_virlo,
    "virlo_monitor": spike_virlo_monitor,
    "image": spike_image,
    "seedance": spike_seedance,
    "probe": lambda: _probe_only(),
    "mkv": spike_mkv,
    "luna": spike_luna,
    "signals": spike_signals,
    "credit": spike_credit,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ACTIONS:
        raise SystemExit(f"usage: python spikes/day_one.py [{'|'.join(ACTIONS)}]")
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(ACTIONS[sys.argv[1]]())


if __name__ == "__main__":
    main()
