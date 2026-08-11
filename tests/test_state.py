"""`logs/trend_history.json` — the cross-run history layer (FR-82, FR-83, FR-153, FR-254, NFR-24).

This is the file that decides whether tomorrow's run may reuse today's trend and today's individual
posts. It is also the file two logged famines came out of, so its rules are worth pinning one by one:

- **`record_use()` is the single writer.** One lock, one critical section, one status. The entry and
  its `posts` map are written together — never two calls, never `asyncio.gather`, because a second
  `finally` unlink would delete the first writer's lock.
- **There is no migration.** An entry written before FR-153 carries no `posts` key and reads as
  "no posts used", so every candidate is fresh. That is the whole no-migration guarantee, and
  `test_fr153_an_entry_without_a_posts_key_reads_as_no_posts_used` is the test that proves there is
  never a window in which post-level recency protection is silently off.
- **The engine never crashes on history state** (FR-83): missing, corrupt, wrong-shaped and junk all
  degrade to `{}` or to "no posts", with one warning.
- **A busy lock is read-only, never a failure** (FR-254): one warning, no update, no exception, and
  the other run's lock is left exactly where it was.

Everything runs against the real file inside `tmp_path`. The repo's own `logs/trend_history.json`
holds the operator's live state and is never read or written here. `record_use` is async, and
`asyncio_mode = "auto"` (pyproject) collects bare `async def test_*` without a marker.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from hypesocials.outputs import days_since_use, read_history, record_use, used_posts
from hypesocials.outputs.state import (
    HISTORY_FILE,
    LOCK_FILE,
    MIN_PRUNE_DAYS,
    RUN_IDS_KEPT,
    STALE_LOCK_S,
)

TREND = "623203a9-4c2b-4f7e-9a11-8d3e5f0c1b22"  # a Virlo monitor/agent id, the entry key shape
OTHER = "0f9a1c74-1e55-4b90-8c02-6d7a2f4e9b31"
RUN_ID = "20260810_123845_c832"


# --------------------------------------------------------------------------- helpers


class RecordingLog:
    """The `_Log` slice `state` uses, capturing instead of printing — nothing reaches a real log."""

    def __init__(self) -> None:
        self.warnings: list[tuple[str, str, dict[str, Any]]] = []
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def warn(self, event_type: str, message: str = "", **data: Any) -> str:
        self.warnings.append((event_type, message, data))
        return event_type

    def event(self, event_type: str, message: str = "", **data: Any) -> str:
        self.events.append((event_type, message, data))
        return event_type

    @property
    def warned(self) -> list[str]:
        return [event_type for event_type, _, _ in self.warnings]


def _days_ago(days: int) -> str:
    """A `YYYY-MM-DD` date as FR-82 writes it — the same builder `tests/test_plan.py:54` uses."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def _seed(logs: Path, history: dict[str, Any]) -> Path:
    """Write a history file straight to disk, exactly as an earlier run would have left it."""
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / HISTORY_FILE
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _hold_lock(logs: Path, *, age_s: float = 0.0) -> Path:
    """Take the advisory lock as another run would, optionally aged into staleness."""
    logs.mkdir(parents=True, exist_ok=True)
    lock = logs / LOCK_FILE
    lock.write_text("4242,2026-08-10T12:38:45.000Z\n", encoding="utf-8")
    if age_s:
        stamp = time.time() - age_s
        os.utime(lock, (stamp, stamp))
    return lock


# --------------------------------------------------------------------------- round-trip


async def test_fr82_record_use_creates_the_entry_and_round_trips_through_read_history(
    tmp_path: Path,
) -> None:
    """FR-82's entry shape: `first_used`, `last_used`, `run_ids`. Written by the only writer there
    is, read back by the only reader Select uses."""
    assert await record_use(str(tmp_path), {TREND: ()}, RUN_ID) is True  # `str` path accepted too

    entry = read_history(tmp_path)[TREND]
    today = _days_ago(0)
    assert entry["first_used"] == today
    assert entry["last_used"] == today
    assert entry["run_ids"] == [RUN_ID]
    assert days_since_use(read_history(tmp_path), TREND) is not None


async def test_fr153_the_posts_map_round_trips_and_used_posts_reads_it_back(
    tmp_path: Path,
) -> None:
    """FR-153: `"posts": {"<post_id>": "YYYY-MM-DD"}` inside the existing entry — one file, one
    shape, one lock. `used_posts()` is what Collect asks, so both directions are asserted."""
    await record_use(tmp_path, {TREND: ["post-a", "post-b"]}, RUN_ID)

    history = read_history(tmp_path)
    assert history[TREND]["posts"] == {"post-a": _days_ago(0), "post-b": _days_ago(0)}
    assert used_posts(history, within_days=7) == {TREND: {"post-a", "post-b"}}
    # The post ids live INSIDE the trend entry — no second file, no second lock (plan §2.2).
    assert sorted(p.name for p in tmp_path.iterdir()) == [HISTORY_FILE]


async def test_fr153_a_second_run_merges_new_post_ids_into_the_existing_map(
    tmp_path: Path,
) -> None:
    """A later run adds to the map; it never replaces it. Overwriting would hand yesterday's posts
    back as fresh and reintroduce the repetition FR-7 exists to prevent."""
    await record_use(tmp_path, {TREND: ["post-a"]}, "run-1")
    await record_use(tmp_path, {TREND: ["post-b", "post-c"]}, "run-2")

    history = read_history(tmp_path)
    assert set(history[TREND]["posts"]) == {"post-a", "post-b", "post-c"}
    assert used_posts(history, within_days=7) == {TREND: {"post-a", "post-b", "post-c"}}


async def test_fr153_duplicate_post_ids_in_one_call_are_recorded_once(tmp_path: Path) -> None:
    """A reel's motion reference can be the same post as an image in its creator-family set (the
    accepted coupling in plan §2.3) — one namespace, so one entry, not two."""
    await record_use(tmp_path, {TREND: ["post-a", "post-a", "", "post-b"]}, RUN_ID)

    assert set(read_history(tmp_path)[TREND]["posts"]) == {"post-a", "post-b"}


# --------------------------------------------------------------------------- no migration


async def test_fr153_an_entry_without_a_posts_key_reads_as_no_posts_used(tmp_path: Path) -> None:
    """THE no-migration guarantee (plan §2.2, FR-82/FR-153).

    Every entry in the operator's live `trend_history.json` predates FR-153 and carries no `posts`
    key. Such an entry must read as "no posts used" — every candidate reference set is fresh — so
    that there is no schema version, no migration step, and above all **no window in which
    post-level recency protection is silently off**. The monitor-level recency it always had
    (NFR-24) keeps working unchanged, and a write for a different trend must not touch it.
    """
    legacy = {TREND: {"first_used": _days_ago(3), "last_used": _days_ago(1),
                      "run_ids": ["20260809_210026_m9zy"]}}
    _seed(tmp_path, legacy)

    history = read_history(tmp_path)
    assert history == legacy  # nothing was invented, upgraded or re-keyed on read
    assert "posts" not in history[TREND]
    assert used_posts(history, within_days=7) == {}  # absent == no posts used == all fresh
    assert (days_since_use(history, TREND) or 0) < 2  # monitor-level recency still answers

    await record_use(tmp_path, {OTHER: ["post-x"]}, RUN_ID)

    after = read_history(tmp_path)
    assert after[TREND] == legacy[TREND]  # a write for another trend rewrote nothing here
    assert used_posts(after, within_days=7) == {OTHER: {"post-x"}}


async def test_fr153_a_trend_that_attached_zero_posts_still_records_the_trend(
    tmp_path: Path,
) -> None:
    """An empty post sequence is legitimate and is NOT "nothing happened": under
    `inspiration_mix: exclusive` a creative attaches zero trend images, and a reel whose motion
    reference failed to download never used it. The trend packaged, so the trend is recorded — and
    no `posts` key is invented, because absent means exactly "no posts used"."""
    await record_use(tmp_path, {TREND: []}, RUN_ID)

    entry = read_history(tmp_path)[TREND]
    assert entry["run_ids"] == [RUN_ID]
    assert "posts" not in entry
    assert used_posts(read_history(tmp_path), within_days=7) == {}


# --------------------------------------------------------------------------- run_ids


async def test_fr82_run_ids_keep_only_the_five_most_recent(tmp_path: Path) -> None:
    """FR-82: "most recent 5 run ids per trend" — a rolling window, not an archive."""
    for index in range(7):
        await record_use(tmp_path, {TREND: [f"post-{index}"]}, f"run-{index}")

    assert RUN_IDS_KEPT == 5
    assert read_history(tmp_path)[TREND]["run_ids"] == [f"run-{i}" for i in range(2, 7)]


async def test_fr82_the_same_run_id_is_never_recorded_twice(tmp_path: Path) -> None:
    """One run recording two creatives for the same trend is still one run. `first_used` is also
    left alone — it is the oldest date, not the newest."""
    await record_use(tmp_path, {TREND: ["post-a"]}, RUN_ID)
    first_used = read_history(tmp_path)[TREND]["first_used"]
    await record_use(tmp_path, {TREND: ["post-b"]}, RUN_ID)

    entry = read_history(tmp_path)[TREND]
    assert entry["run_ids"] == [RUN_ID]
    assert entry["first_used"] == first_used


# --------------------------------------------------------------------------- prune


async def test_fr82_entries_past_the_prune_horizon_are_dropped_on_every_write(
    tmp_path: Path,
) -> None:
    """FR-82: "every write prunes entries past `max(trend_history_days, 90)` days". Undatable junk
    goes with them — an entry nothing can age is an entry nothing can ever expire."""
    _seed(tmp_path, {
        "ancient": {"last_used": _days_ago(120), "run_ids": []},
        "undatable": {"run_ids": []},
        "recent": {"last_used": _days_ago(2), "run_ids": []},
    })

    log = RecordingLog()
    await record_use(tmp_path, {TREND: ["post-a"]}, RUN_ID, history_days=7, log=log)

    assert MIN_PRUNE_DAYS == 90
    assert set(read_history(tmp_path)) == {"recent", TREND}
    assert log.events[0][2]["pruned"] == 2


async def test_fr82_the_horizon_is_the_larger_of_history_days_and_ninety(tmp_path: Path) -> None:
    """A config asking for a 200-day window gets one; a config asking for 7 still keeps 90, because
    the archive floor is what makes a widened window possible later."""
    seed = {"old": {"last_used": _days_ago(120), "run_ids": []}}

    _seed(tmp_path, seed)
    await record_use(tmp_path, {TREND: ()}, RUN_ID, history_days=200)
    assert "old" in read_history(tmp_path)  # 120 days is inside max(200, 90)

    _seed(tmp_path, seed)
    await record_use(tmp_path, {TREND: ()}, RUN_ID, history_days=7)
    assert "old" not in read_history(tmp_path)  # 120 days is outside max(7, 90)


async def test_fr153_stale_posts_are_pruned_inside_a_surviving_entry_on_the_same_pass(
    tmp_path: Path,
) -> None:
    """FR-153: the `posts` map is pruned on the SAME pass and against the SAME horizon as the
    entries. Two prune passes with two horizons is how the two dimensions drift apart."""
    _seed(tmp_path, {"survivor": {"first_used": _days_ago(200), "last_used": _days_ago(1),
                                  "run_ids": ["run-0"],
                                  "posts": {"old-post": _days_ago(120),
                                            "fresh-post": _days_ago(1)}}})

    await record_use(tmp_path, {TREND: ["post-a"]}, RUN_ID, history_days=7)

    entry = read_history(tmp_path)["survivor"]
    assert entry["posts"] == {"fresh-post": _days_ago(1)}
    assert entry["last_used"] == _days_ago(1)  # the entry itself was not otherwise touched


async def test_fr153_an_emptied_posts_map_is_deleted_because_absent_means_the_same(
    tmp_path: Path,
) -> None:
    """Once every post in an entry has aged out, the key is removed rather than left as `{}` — the
    two states are read identically, and one shape is one fewer thing to reason about."""
    _seed(tmp_path, {"survivor": {"last_used": _days_ago(1), "run_ids": [],
                                  "posts": {"old-post": _days_ago(200)}}})

    await record_use(tmp_path, {TREND: ()}, RUN_ID, history_days=7)

    assert "posts" not in read_history(tmp_path)["survivor"]


# --------------------------------------------------------------------------- the window


def test_fr7_zero_days_disables_the_post_window_entirely() -> None:
    """FR-7: "`0` still disables". `--history-days 0` is the operator's escape hatch out of an
    exhausted config, so it must return every post to the fresh pool."""
    history = {TREND: {"last_used": _days_ago(0), "posts": {"post-a": _days_ago(0)}}}

    assert used_posts(history, within_days=0) == {}
    assert used_posts(history, within_days=-1) == {}
    assert used_posts(history, within_days=7) == {TREND: {"post-a"}}


def test_fr153_posts_outside_the_window_are_not_reported_as_used() -> None:
    """NFR-24 at post granularity: the window is what makes a post fresh again. An entry whose
    every post has aged out drops out of the map altogether, which reads as "all candidates fresh".
    """
    history = {TREND: {"last_used": _days_ago(1),
                       "posts": {"stale": _days_ago(30), "fresh": _days_ago(2)}},
               OTHER: {"last_used": _days_ago(30), "posts": {"stale": _days_ago(30)}}}

    assert used_posts(history, within_days=7) == {TREND: {"fresh"}}


def test_nfr24_days_since_use_reads_both_date_shapes_and_admits_ignorance() -> None:
    """Entries carry `YYYY-MM-DD` today and may carry a full ISO timestamp from an older file. One
    parser tolerates both, so Select never re-implements date handling; unknown answers `None`."""
    history = {
        "dated": {"last_used": _days_ago(3)},
        "stamped": {"last_used": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()},
        "blank": {"last_used": ""},
        "junk": {"last_used": "last tuesday"},
    }

    assert 3 <= (days_since_use(history, "dated") or 0) < 5
    assert 2.9 < (days_since_use(history, "stamped") or 0) < 3.1
    assert days_since_use(history, "blank") is None
    assert days_since_use(history, "junk") is None
    assert days_since_use(history, "never-seen") is None


# --------------------------------------------------------------------------- FR-83 corruption


def test_fr83_a_corrupt_history_file_reads_as_empty_after_exactly_one_warning(
    tmp_path: Path,
) -> None:
    """FR-83: "missing/corrupt history warns and starts fresh". The engine never crashes on history
    state — it loses recency protection for one run, which is a cosmetic loss against a dead run.
    Exactly one warning: a corrupt file that warned twice would read as two separate problems.
    """
    (tmp_path / HISTORY_FILE).write_text("{not json at all,", encoding="utf-8")
    log = RecordingLog()

    assert read_history(tmp_path, log) == {}
    assert log.warned == ["trend_history_invalid"]


def test_fr83_a_json_document_that_is_not_an_object_is_the_same_case(tmp_path: Path) -> None:
    """Valid JSON of the wrong shape is corruption too — a list has no trend keys to read."""
    (tmp_path / HISTORY_FILE).write_text('["623203a9"]', encoding="utf-8")
    log = RecordingLog()

    assert read_history(tmp_path, log) == {}
    assert log.warned == ["trend_history_invalid"]


def test_fr83_a_missing_history_file_is_not_a_warning(tmp_path: Path) -> None:
    """The first run of a fresh checkout has no history and nothing is wrong with that."""
    log = RecordingLog()

    assert read_history(tmp_path, log) == {}
    assert log.warnings == []


def test_fr83_a_non_dict_entry_is_dropped_rather_than_returned(tmp_path: Path) -> None:
    """One junk entry never costs the whole file: the readable entries still protect their trends."""
    _seed(tmp_path, {TREND: {"last_used": _days_ago(1)}, "junk": 5, "also-junk": ["x"]})

    assert set(read_history(tmp_path)) == {TREND}


async def test_fr83_a_junk_posts_value_inside_a_valid_entry_cannot_break_a_run(
    tmp_path: Path,
) -> None:
    """A `posts` value that is not a map is discarded, never a crash (FR-83) — read as "no posts
    used", and replaced on the next write rather than merged into."""
    _seed(tmp_path, {TREND: {"last_used": _days_ago(1), "run_ids": [], "posts": "corrupted"}})

    assert used_posts(read_history(tmp_path), within_days=7) == {}
    assert await record_use(tmp_path, {TREND: ["post-a"]}, RUN_ID) is True
    assert read_history(tmp_path)[TREND]["posts"] == {"post-a": _days_ago(0)}


# --------------------------------------------------------------------------- FR-254 locking


async def test_fr254_a_held_lock_degrades_to_read_only_with_one_warning(tmp_path: Path) -> None:
    """FR-254: "a busy lock degrades to read-only with one warning and NEVER blocks or fails a run".

    The return value is the whole status — `False` means "went read-only", not "raised". The other
    run's lock is left exactly where it was: unlinking someone else's lock is how the two-file
    design this plan rejected would have corrupted itself (plan §2.2).
    """
    lock = _hold_lock(tmp_path)
    _seed(tmp_path, {TREND: {"last_used": _days_ago(5), "run_ids": ["run-0"]}})
    log = RecordingLog()

    assert await record_use(tmp_path, {TREND: ["post-a"]}, RUN_ID, log=log) is False

    assert log.warned == ["trend_history_locked"]
    assert log.events == []  # nothing was recorded, so nothing is claimed to have been
    assert lock.is_file()  # its owner still holds it
    assert read_history(tmp_path)[TREND] == {"last_used": _days_ago(5), "run_ids": ["run-0"]}


async def test_fr254_a_lock_older_than_sixty_seconds_is_broken(tmp_path: Path) -> None:
    """A crashed run holds its lock forever, so a stale one is broken rather than waited on —
    otherwise one Ctrl+C would make every later run read-only."""
    assert STALE_LOCK_S == 60.0
    _hold_lock(tmp_path, age_s=STALE_LOCK_S + 60)
    log = RecordingLog()

    assert await record_use(tmp_path, {TREND: ["post-a"]}, RUN_ID, log=log) is True

    assert log.warnings == []
    assert read_history(tmp_path)[TREND]["posts"] == {"post-a": _days_ago(0)}


async def test_fr254_the_lock_is_released_on_the_way_out(tmp_path: Path) -> None:
    """A write that finished leaves no lock behind — the next run must not inherit a read-only
    history because this one succeeded."""
    await record_use(tmp_path, {TREND: ["post-a"]}, RUN_ID)

    assert not (tmp_path / LOCK_FILE).exists()
    assert await record_use(tmp_path, {OTHER: ["post-b"]}, "run-2") is True


async def test_fr82_recording_nothing_writes_nothing_and_takes_no_lock(tmp_path: Path) -> None:
    """A run that packaged nothing records nothing (FR-82 is the caller's rule, and this is its
    floor): no file is created, no lock is taken, and the status is still success."""
    assert await record_use(tmp_path, {}, RUN_ID) is True
    assert await record_use(tmp_path, {"": ["post-a"]}, RUN_ID) is True  # a blank key is not a trend

    assert list(tmp_path.iterdir()) == []


async def test_fr82_the_update_is_logged_once_with_its_counts(tmp_path: Path) -> None:
    """One event per write, carrying what was recorded — the line that makes a repeating run
    explainable when the same posts keep coming back."""
    log = RecordingLog()

    await record_use(tmp_path, {TREND: ["post-a", "post-b"], OTHER: []}, RUN_ID, log=log)

    assert len(log.events) == 1
    event_type, _, data = log.events[0]
    assert event_type == "trend_history_updated"
    assert sorted(data["trends"]) == sorted([OTHER, TREND])
    assert data["posts"] == 2
    assert data["pruned"] == 0


# --------------------------------------------------------------------------- the file on disk


async def test_fr254_the_history_file_is_utf8_json_with_a_trailing_newline(tmp_path: Path) -> None:
    """FR-256/FR-254: written atomically as UTF-8 with LF newlines, parseable by anything, and
    stable across runs (sorted keys) so a diff shows what changed rather than a reshuffle."""
    await record_use(tmp_path, {OTHER: ["post-b"], TREND: ["post-a"]}, RUN_ID)

    blob = (tmp_path / HISTORY_FILE).read_bytes()
    assert b"\r\n" not in blob
    assert blob.endswith(b"\n")
    text = blob.decode("utf-8")
    assert list(json.loads(text)) == sorted([OTHER, TREND])
    assert text.index(f'"{OTHER}"') < text.index(f'"{TREND}"')
