"""The viral-video motion reference: probe → qualify → download → upload (FR-142, 20 §8b).

Module contract
---------------
Purpose: turn a trend's winning post URL into something Seedance can reference — a public Kie URL
for a clip that is short enough, small enough and inside the provider's pixel window — while the
Analyze stage is still running (D23). Callers get one honest answer per trend and never learn that
yt-dlp, a scratch folder or a format table were involved.

Public API:
    prefetch(candidates, *, max_duration_s, log) -> Prefetch   launched once, alongside Analyze
    await Prefetch.get(trend_key, *, timeout_s) -> VideoRefOutcome     never raises
    await Prefetch.aclose()                     cancel outstanding work, sweep scratch
    cleanup()                                   module-level, idempotent scratch removal (FR-249)
    VideoRef · VideoRefOutcome

Invariants enforced here, once, for every caller:
- **Every failure degrades, never blocks (FR-163).** Probe failure, malformed metadata, nothing
  short enough, a dead download, a rejected upload: each comes back as a `VideoRefOutcome` naming
  its own `DegradationTag`, and the reel is generated from its seed frame and images alone.
- **Nothing is ever trimmed (FR-161).** A clip over `max_duration_s` is skipped — trimming needs
  ffmpeg. Duration comes from yt-dlp's own metadata, and those seconds are BILLED at the
  with-video rate (v1.6.6), so the bound is a price lever, not only a safety one.
- **The format is chosen before a byte moves.** Kie documents `reference_video_urls` at
  300–6000 px per side and **409 600–927 408 total pixels** (`ReferenceLimits`, RESULTS.md §C): a
  raw 1080×1920 phone download is 2 073 600 px and is rejected outright. Progressive formats only
  (`acodec != "none"`), h264 preferred over bytevc1/HEVC — no merging, because merging is ffmpeg.
- **No activity at import time, and none unless a caller asks.** `prefetch()` starts the work, so
  the preview modes — which never call it — stay honestly free of yt-dlp and Kie traffic
  (FR-139/140).
- **Kill-tolerant cleanup (RESULTS.md §F).** A real Ctrl+C reaches yt-dlp too, because it shares
  the console; every kill here tolerates `ProcessLookupError` — the child may already be gone.

Do not: invoke ffmpeg, trim or re-encode anything, retry a step past its single attempt, write
into `output/` (scratch only, FR-249/FR-86), or import `render.kie` / `render.profiles` directly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hypesocials import render
from hypesocials.models import DegradationTag
from hypesocials.util import slugify

logger = logging.getLogger(__name__)

#: The render profile whose documented limits every qualifying decision is measured against — the
#: bounds live in `ReferenceLimits`, never hardcoded here (20 §8a, RESULTS.md §C).
VIDEO_PROFILE = "seedance-2-5"
PROBE_TIMEOUT_S = 90.0
DOWNLOAD_TIMEOUT_S = 300.0

_SCRATCH_PREFIX = "hypesocials-videoref-"
_H264_MARKERS = ("avc1", "avc3", "h264")
_REASON_MAX = 200


@dataclass(slots=True)
class VideoRef:
    """One qualifying motion reference, already public and ready for `reference_video_urls`."""

    url: str  # Kie-hosted, SAME-RUN-ONLY (~24 h upload lifetime, 20 §8b)
    duration_s: float  # probed, and billed at the with-video rate (FR-161)
    source_url: str  # the trend's own post URL, for the log and meta
    local_path: Path | None = None  # scratch copy, so the run can keep it in `refs/` (FR-71/150)


@dataclass(slots=True)
class VideoRefOutcome:
    """The answer for one trend: a reference, or the named reason there is none (FR-163)."""

    ref: VideoRef | None = None
    degradation: DegradationTag | None = None  # the tag the caller marks on the asset (FR-73)
    reason: str = ""  # one safe line, already trimmed — never a secret (D30)


class Prefetch:
    """The in-flight chains for one run. Constructed by `prefetch()`, never directly.

    One task per candidate, all started at once: the chain's 15–60 s of probe/download/upload
    overlaps Analyze and Write instead of extending the reel's critical path (FR-142). `get()`
    awaits one trend's task under a short bounded wait and answers honestly either way.
    """

    __slots__ = ("_log", "_tasks")

    def __init__(self, tasks: dict[str, asyncio.Task[VideoRefOutcome]], log: Any = None) -> None:
        self._tasks = tasks
        self._log = log

    async def get(self, trend_key: str, *, timeout_s: float) -> VideoRefOutcome:
        """This trend's motion reference, or why it has none. Never raises (except cancellation).

        A task still running when `timeout_s` elapses is left running — a later `get()` on the
        same trend can still succeed — because the work is already paid for in bandwidth.
        """
        task = self._tasks.get(trend_key)
        if task is None:
            return VideoRefOutcome(degradation=DegradationTag.NO_QUALIFYING_VIDEO,
                                   reason="no winning-video candidate for this trend")
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout_s)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return VideoRefOutcome(degradation=DegradationTag.PROBE_FAILED,
                                   reason=f"video reference not ready within {timeout_s:.0f}s")
        except Exception as exc:  # noqa: BLE001 — a chain crash degrades like any other step
            return VideoRefOutcome(degradation=DegradationTag.PROBE_FAILED,
                                   reason=f"video-reference chain error: {type(exc).__name__}")

    async def aclose(self) -> None:
        """Cancel every outstanding chain and sweep the scratch folder (FR-249), tolerating
        children a real Ctrl+C already killed through the shared console (RESULTS.md §F)."""
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            with suppress(Exception):
                await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks = {}
        cleanup()


def prefetch(
    candidates: Mapping[str, str], *, max_duration_s: int, log: Any = None
) -> Prefetch:
    """Start one probe/download/upload chain per candidate and return immediately (D23).

    `candidates` is `{trend_key: winning_video_url}` for the trends that carry one;
    `max_duration_s` is `run.reel_reference_max_s` (FR-161); `log` is the run's LogWriter. The
    returned `Prefetch` is what the reel chain awaits at Seedance submission time, and the caller
    owns `aclose()` on every exit path — the preview modes simply never call this at all.
    """
    tasks = {
        key: asyncio.create_task(_resolve(key, url, int(max_duration_s), log),
                                 name=f"video_ref:{key}")
        for key, url in candidates.items() if str(url or "").strip()
    }
    if tasks:
        _event(log, "video_reference_prefetch",
               f"probing {len(tasks)} winning video(s) for a motion reference, "
               f"bound {max_duration_s}s (FR-142)", candidates=len(tasks),
               max_duration_s=int(max_duration_s))
    return Prefetch(tasks, log)


def cleanup() -> None:
    """Delete this run's scratch downloads (FR-249). Idempotent, never touches `output/`."""
    global _SCRATCH
    folder, _SCRATCH = _SCRATCH, None
    if folder is not None:
        shutil.rmtree(folder, ignore_errors=True)


# --------------------------------------------------------------------------- the chain


async def _resolve(
    trend_key: str, source_url: str, max_duration_s: int, log: Any
) -> VideoRefOutcome:
    """Probe → qualify → download → upload for ONE candidate. Returns, never raises."""
    limits = render.get_profile(VIDEO_PROFILE).limits
    ok, payload = await _run(["--skip-download", "--dump-single-json", "--no-playlist",
                              source_url], timeout_s=PROBE_TIMEOUT_S)
    if not ok:
        return _degrade(log, trend_key, DegradationTag.PROBE_FAILED,
                        f"yt-dlp probe failed: {payload}")
    facts = _probe_facts(payload)
    if facts is None:
        return _degrade(log, trend_key, DegradationTag.MALFORMED_METADATA,
                        "yt-dlp returned no usable JSON metadata or duration")
    meta, duration = facts
    if duration > max_duration_s:
        return _degrade(log, trend_key, DegradationTag.NO_QUALIFYING_VIDEO,
                        f"winning video runs {duration:.0f}s, over the {max_duration_s}s bound "
                        "(never trimmed — that would need ffmpeg)")
    chosen = _pick_format(meta.get("formats"), limits)
    if chosen is None:
        return _degrade(log, trend_key, DegradationTag.NO_QUALIFYING_VIDEO,
                        "no progressive mp4 format inside the provider's pixel window "
                        f"{limits.video_pixel_window}")
    dest = _scratch() / f"{slugify(trend_key) or 'trend'}_ref.mp4"
    ok, detail = await _run(["-f", chosen, "-o", str(dest), "--no-playlist", "--no-progress",
                             source_url], timeout_s=DOWNLOAD_TIMEOUT_S)
    path = _downloaded(dest)
    if not ok or path is None:
        return _degrade(log, trend_key, DegradationTag.DOWNLOAD_FAILED,
                        f"yt-dlp download failed: {detail or 'no file was written'}")
    size = path.stat().st_size
    if limits.max_video_bytes and size > limits.max_video_bytes:
        return _degrade(log, trend_key, DegradationTag.NO_QUALIFYING_VIDEO,
                        f"downloaded reference is {size / 1_048_576:.0f} MB, over the provider's "
                        f"{limits.max_video_bytes // 1_048_576} MB limit")
    try:
        url = await render.upload_file(path)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — any upload failure is one degrade, never a raise
        return _degrade(log, trend_key, DegradationTag.UPLOAD_FAILED,
                        f"Kie file upload failed: {type(exc).__name__}: {exc}")
    _event(log, "video_reference_ready",
           f"{trend_key}: {duration:.0f}s motion reference uploaded ({size / 1_048_576:.1f} MB); "
           "its seconds are billed at the with-video rate (FR-161)",
           trend_key=trend_key, duration_s=round(duration, 1), format_id=chosen)
    return VideoRefOutcome(ref=VideoRef(url=url, duration_s=duration, source_url=source_url,
                                        local_path=path))


def _pick_format(formats: Any, limits: Any) -> str | None:
    """The best progressive format inside the provider's window, or `None` (RESULTS.md §C).

    Rules, in order: a real video+audio stream (no merging — merging is ffmpeg), both sides inside
    `video_dimension_range`, total pixels inside `video_pixel_window`, then h264 preferred over
    bytevc1/HEVC and the largest qualifying frame first.
    """
    low_px, high_px = limits.video_pixel_window
    low_side, high_side = limits.video_dimension_range
    ranked: list[tuple[int, int, str]] = []
    for entry in formats or ():
        if not isinstance(entry, Mapping):
            continue
        width, height = _int(entry.get("width")), _int(entry.get("height"))
        codec = str(entry.get("vcodec") or "").lower()
        audio = str(entry.get("acodec") or "none").lower()
        if not width or not height or codec in ("", "none") or audio == "none":
            continue
        if not (low_side <= width <= high_side and low_side <= height <= high_side):
            continue
        pixels = width * height
        if not (low_px <= pixels <= high_px):
            continue
        if str(entry.get("ext") or "").lower() not in limits.video_formats:
            continue
        identifier = str(entry.get("format_id") or "")
        if identifier:
            ranked.append((0 if any(m in codec for m in _H264_MARKERS) else 1, -pixels, identifier))
    return min(ranked)[2] if ranked else None


# --------------------------------------------------------------------------- subprocess & scratch

_SCRATCH: Path | None = None


async def _run(args: Sequence[str], *, timeout_s: float) -> tuple[bool, str]:
    """One bounded yt-dlp call as `sys.executable -m yt_dlp` — no PATH or `.cmd` shim guesswork.

    Returns `(ok, stdout)` on success and `(False, reason)` on any failure; the process is killed
    on timeout and on cancellation, tolerating a child the console already killed (RESULTS.md §F).
    """
    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "yt_dlp", *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(timeout_s):
                out, err = await process.communicate()
        except TimeoutError:
            _kill(process)
            return False, f"timed out after {timeout_s:.0f}s"
        if process.returncode:
            return False, _tidy(err.decode("utf-8", "replace"), last_line=True)
        return True, out.decode("utf-8", "replace")
    except asyncio.CancelledError:
        _kill(process)
        raise
    except (OSError, ValueError) as exc:  # yt-dlp not installed, bad args, spawn refused
        return False, f"{type(exc).__name__}: {exc}"


def _kill(process: Any) -> None:
    """Best-effort kill. `ProcessLookupError` is normal: a real Ctrl+C hits the whole group."""
    if process is None or process.returncode is not None:
        return
    with suppress(ProcessLookupError, OSError, ValueError):
        process.kill()


def _scratch() -> Path:
    """This run's private scratch folder, created on first use and owned by `cleanup()`."""
    global _SCRATCH
    if _SCRATCH is None:
        _SCRATCH = Path(tempfile.mkdtemp(prefix=_SCRATCH_PREFIX))
    _SCRATCH.mkdir(parents=True, exist_ok=True)
    return _SCRATCH


def _downloaded(dest: Path) -> Path | None:
    """The file yt-dlp actually wrote — it may have kept its own extension."""
    if dest.is_file() and dest.stat().st_size:
        return dest
    return next((p for p in sorted(dest.parent.glob(f"{dest.stem}.*"))
                 if p.is_file() and p.stat().st_size), None)


# --------------------------------------------------------------------------- small helpers


def _probe_facts(payload: str) -> tuple[Mapping[str, Any], float] | None:
    """`(metadata, duration)` from one probe payload, or `None` when either is unusable."""
    try:
        meta = json.loads(payload)
        duration = float(meta["duration"])
    except (TypeError, ValueError, KeyError):
        return None
    return (meta, duration) if isinstance(meta, Mapping) and duration > 0 else None


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _tidy(text: str, *, last_line: bool = False) -> str:
    """One safe, bounded log line — the last line of a traceback-ish stderr, or the whole text."""
    lines = [line for line in str(text).splitlines() if line.strip()]
    picked = (lines[-1] if lines else "") if last_line else " ".join(lines)
    return " ".join(picked.split())[:_REASON_MAX] or "no output"


def _degrade(log: Any, trend_key: str, tag: DegradationTag, reason: str) -> VideoRefOutcome:
    """One named degrade line, logged where the operator will look for it (FR-163)."""
    line = _tidy(reason)
    if log is not None:
        log.warn("video_reference_failed", f"{trend_key}: {line}",
                 trend_key=trend_key, degradation=tag.value, reason=line)
    logger.warning("video reference for %s degraded (%s): %s", trend_key, tag.value, line)
    return VideoRefOutcome(degradation=tag, reason=line)


def _event(log: Any, event_type: str, message: str, **data: Any) -> None:
    logger.info("%s: %s", event_type, message)
    if log is not None:
        log.event(event_type, message, **data)


__all__ = ["Prefetch", "VideoRef", "VideoRefOutcome", "cleanup", "prefetch"]
