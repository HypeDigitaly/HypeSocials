"""Cross-cutting primitives every module is allowed to depend on: atomic writes, UTF-8 text
I/O, monotonic timing, and the two id/slug generators.

Deliberately a leaf: no project imports, no config, no logging. FR references are the spec
(`prds/`), not decoration: FR-256 (every file written with an explicit UTF-8 encoding),
FR-254 / NFR-20 / NFR-21 (shared and terminal state written temp-file-then-rename), FR-243
(elapsed time on the monotonic clock — a workstation sleeps and NTP steps its clock), FR-78
(ISO-8601 timestamps, ms durations), FR-70 (run_id shape), FR-71 + 20 §3 (one slug
normalization for both history keys and asset ids).
"""

from __future__ import annotations

import os
import random
import re
import string
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

UTF8 = "utf-8"
ASSET_SLUG_MAX = 40  # FR-71: Windows MAX_PATH safety for the trend slug inside an asset_id
_RUN_ID_ALPHABET = string.ascii_lowercase + string.digits
_NON_SLUG = re.compile(r"[^a-z0-9]+")


# --------------------------------------------------------------------------- text I/O

def open_utf8(path: str | Path, mode: str = "r") -> IO[Any]:
    """Open a text file as UTF-8 with LF newlines (FR-256).

    `newline="\\n"` disables Windows CRLF translation so a JSONL line is exactly the bytes we
    wrote — Czech diacritics and hook text survive round-trips on every path.
    """
    return open(path, mode, encoding=UTF8, newline="\n")


def read_text(path: str | Path) -> str:
    """Read a whole text file as UTF-8 (FR-256). Raises OSError; callers decide the fallback."""
    return Path(path).read_text(encoding=UTF8)


def atomic_write(path: str | Path, data: str | bytes) -> None:
    """Write `data` to `path` atomically: temp file in the SAME directory, fsync, os.replace.

    The same-directory rule matters — os.replace is only atomic within one volume (FR-254),
    and %TEMP% is routinely on another drive. A kill mid-write leaves the previous good file
    intact, which is what makes trend_history.json, latest.txt and meta.yaml (NFR-21)
    un-tearable. Text is encoded UTF-8 with whatever newlines the caller passed (FR-256).
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    blob = data.encode(UTF8) if isinstance(data, str) else data
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------------- time

def now_iso() -> str:
    """UTC timestamp in FR-78's exact shape, e.g. `2026-08-08T14:23:47.123Z`."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def today_iso() -> str:
    """UTC calendar date, `YYYY-MM-DD` — the ISO-8601 date FR-82's history entries store."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@dataclass(slots=True)
class Stopwatch:
    """Elapsed time on the MONOTONIC clock (FR-243); `elapsed_ms` is FR-78's log unit."""

    started: float = field(default_factory=time.monotonic)

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started

    @property
    def elapsed_ms(self) -> int:
        return int(self.elapsed_s * 1000)

    def reset(self) -> None:
        self.started = time.monotonic()


@dataclass(slots=True)
class Deadline:
    """The run's soft elapsed-time ceiling (FR-108), monotonic like every other timer (FR-243).

    Soft by contract: `expired` tells the submitter to stop ordering new work; already-submitted
    jobs still get their grace poll, so aftermath may legitimately run past it.
    """

    seconds: float
    started: float = field(default_factory=time.monotonic)

    @classmethod
    def from_minutes(cls, minutes: float) -> Deadline:
        return cls(seconds=float(minutes) * 60.0)

    @property
    def remaining_s(self) -> float:
        return max(0.0, self.seconds - (time.monotonic() - self.started))

    @property
    def expired(self) -> bool:
        return self.remaining_s <= 0.0


# --------------------------------------------------------------------------- ids

def slugify(text: str, max_len: int = ASSET_SLUG_MAX) -> str:
    """Lowercase, diacritics ASCII-folded, non-alphanumerics hyphenated — 20 §3's normalization.

    ONE function for both users of that spelling: trend history keys (`max_len=0`, uncapped, so
    two runs always derive the identical key) and the trend slug inside an asset_id (capped at
    FR-71's 40 characters). Empty or fully non-ASCII input degrades to `untitled` rather than
    producing an empty path segment.
    """
    folded = unicodedata.normalize("NFKD", text or "")
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    slug = _NON_SLUG.sub("-", ascii_only.lower()).strip("-")
    if max_len and len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "untitled"


def new_run_id() -> str:
    """FR-70's `YYYYMMDD_HHMMSS_<4-char-random>`, e.g. `20260808_143022_x7q2`.

    Local time, because the operator reads these as folder names next to their own clock; the
    random suffix is what keeps two runs launched in the same second from colliding (FR-254).
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "".join(random.choices(_RUN_ID_ALPHABET, k=4))
    return f"{stamp}_{suffix}"
