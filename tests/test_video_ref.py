"""Motion-reference chain tests — the qualify rules and every degrade path (FR-142/160–163).

No network and no real yt-dlp: the subprocess seam (`video_ref._run`) and the Kie upload op are
both faked, so what is under test is the engine's own decisions — the measured pixel window and
duration bound of spikes/RESULTS.md §C, and the tag each failure step reports.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from hypesocials import render
from hypesocials.generate import video_ref
from hypesocials.models import DegradationTag

UPLOADED = "https://tempfile.redpandaai.co/kieai/1/hypesocials/ref.mp4"


def fmt(format_id: str, width: int, height: int, *, vcodec: str = "avc1.4d401f",
        acodec: str = "mp4a.40.2", ext: str = "mp4") -> dict[str, Any]:
    return {"format_id": format_id, "width": width, "height": height, "vcodec": vcodec,
            "acodec": acodec, "ext": ext}


#: The real TikTok ladder from RESULTS.md §C: 1080p is 2 073 600 px and over the ceiling.
LADDER = [
    fmt("h264_1080p", 1080, 1920),
    fmt("bytevc1_720p", 720, 1280, vcodec="bytevc1"),
    fmt("h264_720p", 720, 1280),
    fmt("h264_540p", 576, 1024),
    fmt("audio_only", 0, 0, vcodec="none"),
]


def payload(duration: float = 10.0, formats: list[dict[str, Any]] | None = None) -> str:
    return json.dumps({"duration": duration, "formats": LADDER if formats is None else formats})


class FakeYtDlp:
    """Stands in for `sys.executable -m yt_dlp`: answers the probe, writes the download."""

    def __init__(self, *, probe: str = "", probe_ok: bool = True, download_ok: bool = True,
                 hang: asyncio.Event | None = None) -> None:
        self.probe = probe or payload()
        self.probe_ok = probe_ok
        self.download_ok = download_ok
        self.hang = hang
        self.calls: list[list[str]] = []

    async def __call__(self, args: list[str], *, timeout_s: float) -> tuple[bool, str]:
        self.calls.append(list(args))
        if self.hang is not None:
            await self.hang.wait()
        if "--dump-single-json" in args:
            return self.probe_ok, self.probe
        if self.download_ok:
            Path(args[args.index("-o") + 1]).write_bytes(b"fake-video-bytes")
            return True, ""
        return False, "ERROR: unable to download video data: HTTP Error 403"

    @property
    def downloads(self) -> list[list[str]]:
        return [call for call in self.calls if "--dump-single-json" not in call]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Every test gets a fresh scratch folder and a fake upload; nothing survives the test."""
    async def upload(path: str | Path) -> str:
        return UPLOADED

    monkeypatch.setattr(render, "upload_file", upload)
    yield
    video_ref.cleanup()


async def resolve(runner: FakeYtDlp, monkeypatch: pytest.MonkeyPatch, *, max_duration_s: int = 10,
                  url: str = "https://www.tiktok.com/@x/video/1") -> video_ref.VideoRefOutcome:
    """One trend through the public API, with the subprocess seam faked.

    Deliberately does NOT `aclose()`: that would sweep the scratch folder these tests inspect.
    The autouse fixture's `cleanup()` is what removes it, exactly as a run's exit path does.
    """
    monkeypatch.setattr(video_ref, "_run", runner)
    chain = video_ref.prefetch({"t1": url}, max_duration_s=max_duration_s)
    return await chain.get("t1", timeout_s=5.0)


# ------------------------------------------------------------------ qualify rules (RESULTS.md §C)


async def test_pixel_window_rejects_1080p_and_prefers_h264(monkeypatch: pytest.MonkeyPatch) -> None:
    """A raw 1080×1920 download is 2 073 600 px — over 2× Kie's 927 408 ceiling — so the engine
    must select a format, and h264 wins over bytevc1 at the same (largest qualifying) size."""
    runner = FakeYtDlp()
    outcome = await resolve(runner, monkeypatch)

    assert outcome.degradation is None and outcome.ref is not None
    assert outcome.ref.url == UPLOADED
    assert outcome.ref.duration_s == 10.0
    assert outcome.ref.local_path is not None and outcome.ref.local_path.is_file()
    chosen = runner.downloads[0]
    assert chosen[chosen.index("-f") + 1] == "h264_720p"


async def test_540p_qualifies_when_it_is_the_only_format_in_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """576×1024 = 589 824 px sits inside [409 600, 927 408] and is a perfectly good reference."""
    runner = FakeYtDlp(probe=payload(formats=[fmt("h264_1080p", 1080, 1920),
                                              fmt("h264_540p", 576, 1024)]))
    outcome = await resolve(runner, monkeypatch)

    assert outcome.ref is not None
    chosen = runner.downloads[0]
    assert chosen[chosen.index("-f") + 1] == "h264_540p"


async def test_video_longer_than_the_bound_is_skipped_never_trimmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-161: trimming would need ffmpeg, so an 11 s clip under a 10 s bound is simply not used —
    and it is never downloaded, so no bandwidth is spent either (FR-160)."""
    runner = FakeYtDlp(probe=payload(duration=11.0))
    outcome = await resolve(runner, monkeypatch, max_duration_s=10)

    assert outcome.ref is None
    assert outcome.degradation is DegradationTag.NO_QUALIFYING_VIDEO
    assert "11s" in outcome.reason and "10s bound" in outcome.reason
    assert runner.downloads == []


async def test_formats_without_audio_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Progressive only: pairing a video-only stream with an audio one would mean merging, and
    merging means ffmpeg."""
    runner = FakeYtDlp(probe=payload(formats=[fmt("h264_720p", 720, 1280, acodec="none")]))
    outcome = await resolve(runner, monkeypatch)

    assert outcome.degradation is DegradationTag.NO_QUALIFYING_VIDEO
    assert runner.downloads == []


# ------------------------------------------------------------------ every failure has its own tag


async def test_probe_failure_degrades_as_probe_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeYtDlp(probe_ok=True)
    runner.probe_ok = False
    runner.probe = "ERROR: Video unavailable"
    outcome = await resolve(runner, monkeypatch)

    assert outcome.ref is None
    assert outcome.degradation is DegradationTag.PROBE_FAILED
    assert "Video unavailable" in outcome.reason


@pytest.mark.parametrize("bad", ["not json at all", '{"formats": []}', '{"duration": 0}'])
async def test_malformed_metadata_degrades_as_malformed_metadata(
    bad: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No JSON, no duration and a zero duration are the same defect: unusable metadata."""
    outcome = await resolve(FakeYtDlp(probe=bad), monkeypatch)

    assert outcome.degradation is DegradationTag.MALFORMED_METADATA


async def test_download_failure_degrades_as_download_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome = await resolve(FakeYtDlp(download_ok=False), monkeypatch)

    assert outcome.ref is None
    assert outcome.degradation is DegradationTag.DOWNLOAD_FAILED
    assert "403" in outcome.reason


async def test_upload_failure_degrades_as_upload_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse(path: str | Path) -> str:
        raise render.KieUploadError("upload rejected: 500")

    monkeypatch.setattr(render, "upload_file", refuse)
    outcome = await resolve(FakeYtDlp(), monkeypatch)

    assert outcome.ref is None
    assert outcome.degradation is DegradationTag.UPLOAD_FAILED
    assert "upload rejected" in outcome.reason


async def test_trend_without_a_candidate_answers_without_starting_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeYtDlp()
    monkeypatch.setattr(video_ref, "_run", runner)
    chain = video_ref.prefetch({}, max_duration_s=10)

    outcome = await chain.get("t1", timeout_s=5.0)

    assert outcome.degradation is DegradationTag.NO_QUALIFYING_VIDEO
    assert runner.calls == []
    await chain.aclose()


# ------------------------------------------------------------------ lifecycle (FR-249, RESULTS §F)


async def test_get_times_out_without_killing_the_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """A slow chain answers "not ready" and keeps running, so a later get() can still succeed."""
    gate = asyncio.Event()
    runner = FakeYtDlp(hang=gate)
    monkeypatch.setattr(video_ref, "_run", runner)
    chain = video_ref.prefetch({"t1": "https://tiktok.test/1"}, max_duration_s=10)

    early = await chain.get("t1", timeout_s=0.01)
    assert early.ref is None
    assert early.degradation is DegradationTag.PROBE_FAILED
    assert "not ready" in early.reason

    gate.set()
    later = await chain.get("t1", timeout_s=5.0)
    assert later.ref is not None
    await chain.aclose()


async def test_aclose_cancels_outstanding_work_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(video_ref, "_run", FakeYtDlp(hang=asyncio.Event()))
    chain = video_ref.prefetch({"t1": "https://tiktok.test/1"}, max_duration_s=10)
    await asyncio.sleep(0)

    await chain.aclose()
    await chain.aclose()  # idempotent, exactly as every exit path calls it

    assert (await chain.get("t1", timeout_s=0.01)).degradation is DegradationTag.NO_QUALIFYING_VIDEO


async def test_cleanup_removes_the_scratch_folder_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-249: working files are deleted on every exit path; `output/` is never touched."""
    outcome = await resolve(FakeYtDlp(), monkeypatch)
    assert outcome.ref is not None and outcome.ref.local_path is not None
    scratch = outcome.ref.local_path.parent
    assert scratch.is_dir()

    video_ref.cleanup()
    video_ref.cleanup()

    assert not scratch.exists()
