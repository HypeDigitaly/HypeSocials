"""State that outlives a single asset folder: topic history, the latest-pointer, the ledger.

Module contract
---------------
Purpose: own every cross-run shared file (`logs/trend_history.json`, `output/latest.txt`, the
`output/latest/` junction) plus the run folder's `LEDGER.txt`, with their locking, atomicity
and corruption rules inside — no caller re-implements them.
Public API: `read_history()` · `days_since_use()` · `used_posts()` · `record_use()` ·
`set_latest()` · `resolve_latest()` · `Ledger`.

What the history records (post-pivot, D42/FR-293/FR-298): the posts whose **texts** a creative
QUOTED. Copy is now verbatim source text selected by reference, so a burnt post id means "this
post's words already shipped this week", not "this post's picture was attached to a render" —
the pre-pivot reading, when the same map tracked the media a run downloaded from its source
posts. The two dimensions the recency window protects are therefore the topic (entry key) and
the quoted post (the `posts` map).

Invariants:
- Every shared-file write is atomic (temp+rename, same directory) — FR-254.
- Entry keys are `TrendItem.history_key` = `"<monitor_id>::<topic_key>"` (§1.6): one monitor
  yields several topics and each is its own recency subject. **Migration by design** (D44): a
  pre-pivot entry keyed by the bare monitor id simply stops matching, the first post-pivot run
  sees an empty window, and those entries age out through the normal `_prune` horizon. There is
  no migration pass and no schema version — a rolling window can afford to forget.
- History is guarded by an advisory pid+timestamp lock; a busy lock degrades to read-only with
  one warning and NEVER blocks or fails a run, a lock older than 60 s is stale and gets broken
  (FR-254); missing/corrupt history warns and starts fresh (FR-83); every write prunes entries
  past `max(trend_history_days, 90)` days, and each survivor's `posts` map on the same pass
  against the same horizon — rolling window, not an archive (FR-82, FR-153).
- A `posts` value is `{"date": "<ISO>", "url": "<permalink>"}` (FR-153 as amended by FR-298: the
  post URL rides beside the date, so a burnt id can be opened without a Virlo lookup). READERS
  ACCEPT BOTH SHAPES: a bare string is read as that date with no URL, so entries written before
  the amendment age out instead of crashing. The writer emits one shape, so the file converges
  without a migration pass.
- An entry with no `posts` key reads as "no posts used", so FR-153 needs no migration and there
  is never a window in which post-level recency protection is silently off.
- `latest.txt` is canonical; `latest/` is a best-effort junction made by `mklink /J` **as a
  subprocess** (`os.symlink` needs admin/Developer Mode and is never used), failures logged,
  never raised (NFR-20).
- `LEDGER.txt` is append-only: never edited or rewritten, last line for a taskId wins (FR-203).
Do not: call `set_latest()` from a run that packaged nothing or from a preview (FR-253), or
record an unpackaged topic (FR-82) — both are the caller's rule, only it knows what landed.

Blocking note: JSON read, atomic write and ledger appends are synchronous few-KB file ops —
microseconds, the same trade FR-81 makes for the log writer. Only the two genuinely waiting
operations are async: the lock retry loop and the `mklink` subprocess.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

from hypesocials.util import atomic_write, now_iso, open_utf8, read_text, today_iso

HISTORY_FILE = "trend_history.json"
LOCK_FILE = "trend_history.lock"
LATEST_FILE = "latest.txt"
LATEST_LINK = "latest"
LEDGER_FILE = "LEDGER.txt"

STALE_LOCK_S = 60.0  # FR-254: older than this and a crashed run is holding it, so break it
LOCK_WAIT_S = 1.0  # "waits briefly" — a busy lock costs a warning, never the run
RUN_IDS_KEPT = 5  # FR-82: most recent 5 run ids per trend
MIN_PRUNE_DAYS = 90  # FR-82: prune horizon is max(trend_history_days, 90)


class _Log(Protocol):
    """The slice of `LogWriter` this module uses — passing one is optional everywhere."""

    def warn(self, event_type: str, message: str = "", **data: Any) -> str: ...

    def event(self, event_type: str, message: str = "", **data: Any) -> str: ...


# --------------------------------------------------------------------- trend history

def read_history(logs_dir: str | Path, log: _Log | None = None) -> dict[str, dict[str, Any]]:
    """Return `logs/trend_history.json`, or `{}` after one warning (FR-83).

    Missing, unreadable, non-JSON and wrong-shaped files are the same case: the engine never
    crashes on history state, it just loses recency protection for this run. A junk `posts` value
    inside an otherwise valid entry is the same trade, absorbed by `used_posts()` (FR-153).
    """
    path = Path(logs_dir) / HISTORY_FILE
    try:
        loaded = json.loads(read_text(path))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        if log:
            log.warn("trend_history_invalid",
                     "trend_history.json missing or invalid; starting fresh", detail=str(exc))
        return {}
    if not isinstance(loaded, dict):
        if log:
            log.warn("trend_history_invalid", "trend_history.json missing or invalid; starting fresh")
        return {}
    return {key: value for key, value in loaded.items() if isinstance(value, dict)}


def days_since_use(history: dict[str, dict[str, Any]], history_key: str) -> float | None:
    """Age in days of a topic's `last_used`, or None if unknown — NFR-24's window input.

    `history_key` is `TrendItem.history_key` (`"<monitor_id>::<topic_key>"`); an entry written
    under the pre-pivot bare-monitor-id key never matches and answers None, which is exactly the
    "never used" the migration note promises. Tolerant of both date shapes an entry may carry
    (`YYYY-MM-DD` as written here, or a full ISO timestamp from an older file), so Select never
    re-implements date parsing.
    """
    return _age_days(history.get(history_key) or {})


def used_posts(history: dict[str, dict[str, Any]], *, within_days: float) -> dict[str, set[str]]:
    """Per history key, the post ids used inside the window — NFR-24 at post granularity (FR-153).

    The map Collect needs so a topic's post is not quoted twice inside the window: a burnt id is
    a post whose TEXT already shipped. Post ids ONLY — the recorded permalink is record-side
    provenance (FR-298) and would just make every caller strip it again. A key missing from the
    result — including every entry that carries no `posts` key at all — means "no posts used", so
    every candidate is fresh; that is the whole of the no-migration guarantee. `within_days <= 0`
    disables the window (FR-7).
    """
    if within_days <= 0:
        return {}
    fresh = {key: set(_fresh_posts(entry.get("posts"), within_days))
             for key, entry in history.items()}
    return {key: ids for key, ids in fresh.items() if ids}


async def record_use(
    logs_dir: str | Path,
    uses: Mapping[str, Sequence[tuple[str, str]]],
    run_id: str,
    *,
    history_days: int = 7,
    log: _Log | None = None,
) -> bool:
    """Record packaged topics with the posts they quoted, and prune. False if read-only.

    The single writer of `trend_history.json` (FR-82, FR-153, FR-298). `uses` maps a
    `history_key` (`"<monitor_id>::<topic_key>"`) to the `(post_id, url)` PAIRS whose text that
    topic's packaged creatives quoted — the runner builds them from the `SourcePost` each
    creative was assigned, so the pair travels together and the URL lands beside the date without
    a second lookup. A bare post-id string is tolerated in place of a pair (it records an empty
    URL) so a caller that has no permalink is not forced to invent one.

    The CALLER decides what qualifies: a key only for a topic that packaged a creative, and under
    it only the posts a creative genuinely QUOTED — an empty sequence is legitimate and still
    records the topic (an override brief quotes nothing, and a copy degrade may ship our own
    words). One lock, one critical section, one status: the entry and its `posts` map are written
    together, never in two calls. FR-254: when the lock cannot be taken in a short wait, the run
    continues read-only — one warning, no update, no exception.
    """
    wanted = {key: _pairs(posts) for key, posts in uses.items() if key}
    if not wanted:
        return True
    logs = Path(logs_dir)
    logs.mkdir(parents=True, exist_ok=True)
    if not await _acquire_lock(logs):
        if log:
            log.warn("trend_history_locked",
                     "trend_history.json is locked by another run; continuing read-only, "
                     "this run's history update is skipped", trends=len(wanted))
        return False
    try:
        history = read_history(logs, log)
        today = today_iso()
        for key, posts in wanted.items():
            entry = history.get(key) or {"first_used": today, "run_ids": []}
            entry["last_used"] = today
            entry.setdefault("first_used", today)
            previous = [rid for rid in entry.get("run_ids", []) if rid != run_id]
            entry["run_ids"] = (previous + [run_id])[-RUN_IDS_KEPT:]
            seen = entry.get("posts")  # a junk value is discarded, never a crash (FR-83)
            entry["posts"] = ((dict(seen) if isinstance(seen, dict) else {})
                              | {pid: {"date": today, "url": url} for pid, url in posts.items()})
            history[key] = entry  # `posts` is dropped again by _prune when it stays empty
        pruned = _prune(history, history_days)
        atomic_write(logs / HISTORY_FILE,
                     json.dumps(history, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    finally:
        (logs / LOCK_FILE).unlink(missing_ok=True)
    if log:
        log.event("trend_history_updated", f"recorded {len(wanted)} topic(s)",
                  trends=list(wanted), posts=sum(len(posts) for posts in wanted.values()),
                  pruned=pruned)
    return True


def _pairs(posts: Sequence[Any]) -> dict[str, str]:
    """`(post_id, url)` pairs (or bare ids) → `{post_id: url}`, deduped, blanks dropped.

    One creative can quote the same post twice (a headline and the caption off one `SourcePost`)
    and two siblings on one topic can land on the same post after a `reuse_index` wrap, so the id
    is the namespace and the first URL seen for it wins — unless it was empty and a later pair
    knows the permalink, in which case the knowing one upgrades it. A pair whose id is blank —
    or an item of a shape no reading fits — is not a post and is dropped rather than raised on:
    history is the one subsystem that never costs a run its packaging step (FR-83).
    """
    merged: dict[str, str] = {}
    for item in posts:
        if isinstance(item, str):
            post_id, url = item, ""
        else:
            try:
                post_id, url, *_ = (*item, "")  # tolerate a bare 1-tuple as well as the pair
            except TypeError:
                continue
        post_id, url = str(post_id or "").strip(), str(url or "").strip()
        if not post_id:
            continue
        if not merged.get(post_id):
            merged[post_id] = url
    return merged


def _prune(history: dict[str, dict[str, Any]], history_days: int) -> int:
    """Drop entries past `max(trend_history_days, 90)` days, and undatable junk with them —
    plus, on the same pass and the same horizon, each survivor's stale `posts` (FR-153). Returns
    the number of ENTRIES dropped; an emptied `posts` map is deleted, since absent means the same.
    """
    horizon = max(int(history_days or 0), MIN_PRUNE_DAYS)
    stale: list[str] = []
    for key, entry in history.items():
        if (age := _age_days(entry)) is None or age > horizon:
            stale.append(key)
        elif "posts" in entry:
            if fresh := _fresh_posts(entry["posts"], horizon):
                entry["posts"] = fresh
            else:
                del entry["posts"]
    for key in stale:
        del history[key]
    return len(stale)


def _fresh_posts(posts: Any, within_days: float) -> dict[str, dict[str, str]]:
    """The `posts` entries still inside a window, normalized to `{date, url}` (FR-153/FR-298).

    Dates go through `_age_days`, so both date spellings it already tolerates work here and no
    second date parser exists; anything else is junk and is dropped. Survivors come back in the
    current shape whatever shape they were stored in, which is why an older file needs no
    migration pass: `_prune` writes back what this returns, so the file converges on one shape
    the first time a run touches it.
    """
    if not isinstance(posts, dict):
        return {}
    fresh: dict[str, dict[str, str]] = {}
    for pid, seen in posts.items():
        record = _post_record(seen)
        age = _age_days({"last_used": record["date"]})
        if age is not None and age <= within_days:
            fresh[str(pid)] = record
    return fresh


def _post_record(value: Any) -> dict[str, str]:
    """One `posts` value in the current shape, whatever it was written as.

    Three spellings reach this: the current `{"date": ..., "url": ...}` mapping; a bare date
    string from before FR-298 (no URL was recorded, so there is none to invent); and the
    `"<date>|<url>"` pipe spelling FR-153's amendment text uses — read here so a file written to
    that reading is understood rather than aged out early. Anything else yields a blank date,
    which `_age_days` reports as unknown and the caller drops.
    """
    if isinstance(value, Mapping):
        return {"date": str(value.get("date") or "").strip(),
                "url": str(value.get("url") or "").strip()}
    date, separator, url = str(value or "").partition("|")
    return {"date": date.strip(), "url": url.strip() if separator else ""}


def _age_days(entry: dict[str, Any]) -> float | None:
    raw = str(entry.get("last_used") or "").strip().replace("Z", "+00:00")
    if not raw:
        return None
    try:
        used = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if used.tzinfo is None:
        used = used.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - used).total_seconds() / 86400.0


async def _acquire_lock(logs_dir: Path) -> bool:
    """Take the advisory lock (pid + timestamp), breaking it if it is older than 60 s."""
    lock = logs_dir / LOCK_FILE
    give_up_at = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(handle, f"{os.getpid()},{now_iso()}\n".encode("utf-8"))
            os.close(handle)
            return True
        except FileExistsError:
            if _lock_is_stale(lock):
                lock.unlink(missing_ok=True)
                continue
            if time.monotonic() >= give_up_at:
                return False
            await asyncio.sleep(0.05)
        except OSError:
            return False  # unwritable logs dir: read-only history, never a failed run


def _lock_is_stale(lock: Path) -> bool:
    try:
        return (time.time() - lock.stat().st_mtime) > STALE_LOCK_S
    except OSError:
        return False


# --------------------------------------------------------------------- latest pointer

async def set_latest(output_dir: str | Path, run_id: str, log: _Log | None = None) -> None:
    """Point `output/latest.txt` at `run_id` and refresh the convenience junction (FR-254/NFR-20).

    Canonical write first and atomically, so `--publish latest` never resolves to nothing; the
    junction is refreshed afterwards on a best-effort basis — a junction cannot be renamed over,
    so its unavoidable delete-then-create window is exactly why it is not the canonical pointer.
    Call only from a run that packaged at least one asset; previews never call this (FR-253).
    """
    out = Path(output_dir)
    atomic_write(out / LATEST_FILE, f"{run_id}\n")
    try:
        os.rmdir(out / LATEST_LINK)  # removes a junction; refuses a non-empty real folder
    except OSError:
        pass
    code, output = await _cmd("mklink", "/J", str(out / LATEST_LINK), str(out / run_id))
    if code != 0 and log:
        log.warn("latest_junction_failed",
                 "output/latest junction not created; latest.txt is authoritative",
                 detail=output)


def resolve_latest(output_dir: str | Path) -> Path | None:
    """Resolve the newest run folder that packaged assets, or None (FR-254; Phase 2 wire-in).

    Reads `latest.txt` — never the junction, which is a human convenience that may be missing,
    stale, or a leftover real directory.
    """
    out = Path(output_dir)
    try:
        run_id = read_text(out / LATEST_FILE).strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return None
    folder = out / run_id
    return folder if run_id and folder.is_dir() else None


async def _cmd(*args: str) -> tuple[int, str]:
    """Run one `cmd /c` command off the event loop. `mklink /J` has no Python equivalent that is
    safe here: `os.symlink` needs admin rights or Developer Mode and is forbidden project-wide."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "cmd", "/c", *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        return proc.returncode or 0, out.decode("utf-8", "replace").strip()
    except OSError as exc:
        return 1, str(exc)


# --------------------------------------------------------------------- outstanding-task ledger

class Ledger:
    """Append-only `LEDGER.txt` — what the run already bought, survivable by any ending.

    FR-203's intent-before-call pattern: three moments, one CSV line each
    (`timestamp,asset_id,request_token,task_id,status`) — `intent()` **before** `createTask`,
    `submitted()` when the response lands (or is lost), `terminal()` on the final state
    including `abandoned` at the deadline (FR-108). The last line for a taskId wins; nothing is
    ever edited or rewritten, because a rewrite is exactly what a kill mid-run must not be able
    to corrupt (FR-89). Each line is opened, appended and closed, so it is on disk before the
    call it describes goes out.
    """

    def __init__(self, run_dir: str | Path) -> None:
        self.path = Path(run_dir) / LEDGER_FILE
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def intent(self, asset_id: str, request_token: str) -> None:
        """Written before `createTask`. Money may move the instant after this line lands."""
        self._append(asset_id, request_token, "", "intent")

    def submitted(self, asset_id: str, request_token: str, task_id: str | None) -> None:
        """Response received (or lost: `task_id=None` → `submit_unknown`, still billed)."""
        self._append(asset_id, request_token, task_id or "",
                     "submitted" if task_id else "submit_unknown")

    def terminal(self, asset_id: str, request_token: str, task_id: str | None,
                 status: str) -> None:
        """Final state for this taskId — `success` | `fail` | `stuck` | `abandoned`."""
        self._append(asset_id, request_token, task_id or "", status)

    def _append(self, *fields: str) -> None:
        line = ",".join(_csv_safe(field) for field in (now_iso(), *fields))
        with open_utf8(self.path, "a") as handle:
            handle.write(line + "\n")


def _csv_safe(value: str) -> str:
    """Keep the CSV one-line and comma-free; ids and tokens are slug-shaped already."""
    return str(value).replace(",", ";").replace("\n", " ").replace("\r", " ").strip()
