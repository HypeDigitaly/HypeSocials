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
class Pulse:
    """The FR-299 silence-breaker clock: heartbeats fire on QUIET, never on a schedule.

    One instance per run, stamped by every console print (`_Session.say`/`note` both call
    `stamp()`), read by the waits that can go mute for minutes — the render `_drain` loop and the
    LLM stages. `due()` answers "has nothing printed for `interval_s`?", so a run that is already
    talking never hears a heartbeat and a bounded log volume follows by construction (a heartbeat
    is itself a printed line, so it re-stamps the clock through the same seam).

    `suppress_s` is the "first heartbeat suppressed" rule (contracts item 16): a wait passes the
    moment it STARTED, and no heartbeat fires until both the quiet interval and the suppression
    window have passed — 10 s for LLM waits, 20 s for render waits, so a fast healthy stage stays
    heartbeat-free even under the verbose 15 s cadence. Monotonic like every other timer (FR-243).
    """

    interval_s: float = 30.0
    last: float = field(default_factory=time.monotonic)

    def stamp(self) -> None:
        """Any printed line resets the quiet clock — called from the one console seam."""
        self.last = time.monotonic()

    def due(self, *, wait_started: float | None = None, suppress_s: float = 0.0) -> bool:
        """True when the console has been silent for `interval_s` (and the wait is past its
        suppression window). The CALLER prints and the print re-stamps; `due()` mutates nothing."""
        now = time.monotonic()
        if wait_started is not None and now - wait_started < suppress_s:
            return False
        return now - self.last >= self.interval_s


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


def fit(text: str, width: int) -> str:
    """One line, ≤ `width`, cut on a nearby word boundary and marked `…` (FR-286).

    Lives here because the menu, the runner and the estimate all print text they do not control —
    niche descriptors, monitor names, trend names, paths — and a hard slice is what produced the
    557-char line that mangled a real operator's console. `·`, `—`, `…` and `←` are the only
    non-ASCII glyphs proven safe on legacy conhost.
    """
    text = " ".join(str(text).split())
    if len(text) <= width:
        return text
    cut = text[:max(width - 1, 0)]
    head = cut.rpartition(" ")[0]
    return (head if len(head) >= width - 12 else cut).rstrip(" ,;:-·") + "…"


def wrapped(text: str, width: int) -> list[tuple[bool, str]]:
    """`text` split on word boundaries into `(is_first_line, part)` pairs, each ≤ `width`.

    The counterpart to `fit()` for text that must stay COMPLETE: a blocked estimate line names the
    config key the operator has to go and set, and an override list is the record of what this run
    actually changed — truncating either would hide the thing worth reading. FR-286 is a rule about
    what the tool prints, so both live at the printer and never in the data.
    """
    lines, current = [], ""
    for word in str(text).split():
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    lines.append(current)
    return [(index == 0, line) for index, line in enumerate(lines)]
