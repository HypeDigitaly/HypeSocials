"""`logs/trend_history.json` — the cross-run history layer (FR-82, FR-83, FR-153, FR-254, NFR-24).

This is the file that decides whether tomorrow's run may reuse today's TOPIC and today's individual
posts. Post-pivot (v2.0.0) what it records changed meaning even though the shape barely moved:

- **The entry key is `"<monitor_id>::<topic_key>"`** (§1.6/D44), not a bare monitor id. One monitor
  yields up to nine topics and each is its own recency subject. **Migration by design**: a pre-pivot
  entry simply stops matching, the first post-pivot run sees an empty window, and the old entries
  age out through the normal `_prune` horizon. No migration pass, no schema version.
- **A burnt post id means "this post's WORDS already shipped"** (D42/FR-293), not "this post's
  picture was attached to a render". Copy is verbatim source text selected by reference, so the
  post map is what stops the same caption going out twice inside the window.
- **A `posts` value is `{"date": ..., "url": ...}`** (FR-153 as amended by FR-298): the permalink
  rides beside the date so a burnt id can be opened without a Virlo lookup. Readers accept the two
  older spellings — a bare date string, and the `"<date>|<url>"` pipe form the amendment text uses
  — so a file written before the amendment ages out instead of crashing, and converges on one
  shape the first time a run touches it.
- **`record_use()` is still the single writer.** One lock, one critical section, one status. It
  takes `(post_id, url)` PAIRS, which `runner._posts_used` builds from the `SourcePost` each
  delivered creative actually quoted (contracts item 14).
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
from types import SimpleNamespace
from typing import Any

from hypesocials.models import AssetRecord, PlanEntry, PlanEntryStatus, SourcePost, TrendItem
from hypesocials.outputs import days_since_use, read_history, record_use, used_posts
from hypesocials.outputs.state import (
    HISTORY_FILE,
    LOCK_FILE,
    MIN_PRUNE_DAYS,
    RUN_IDS_KEPT,
    STALE_LOCK_S,
)
from hypesocials.runner import _posts_used

MONITOR = "623203a9-4c2b-4f7e-9a11-8d3e5f0c1b22"  # a Virlo monitor id — half of the entry key
TOPIC = f"{MONITOR}::ai-agents-that-ship"  # `<monitor_id>::<topic_key>` (§1.6)
OTHER = f"{MONITOR}::one-prompt-workflows"  # a SECOND topic off the same monitor
RUN_ID = "20260810_123845_c832"
URL_A = "https://www.tiktok.com/@creator/video/7411111111111111111"
URL_B = "https://www.tiktok.com/@creator/video/7422222222222222222"


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
    """A `YYYY-MM-DD` date as FR-82 writes it — the same builder `tests/test_plan.py` uses."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def _post(days: int, url: str = "") -> dict[str, str]:
    """One `posts` value in the CURRENT shape (FR-298): the date the text shipped, and where."""
    return {"date": _days_ago(days), "url": url}


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
    assert await record_use(str(tmp_path), {TOPIC: ()}, RUN_ID) is True  # `str` path accepted too

    entry = read_history(tmp_path)[TOPIC]
    today = _days_ago(0)
    assert entry["first_used"] == today
    assert entry["last_used"] == today
    assert entry["run_ids"] == [RUN_ID]
    assert days_since_use(read_history(tmp_path), TOPIC) is not None


async def test_fr153_the_posts_map_round_trips_with_the_permalink_beside_the_date(
    tmp_path: Path,
) -> None:
    """FR-153 as amended by FR-298: `"posts": {"<post_id>": {"date": ..., "url": ...}}` inside the
    existing entry — one file, one shape, one lock. The URL is what makes a burnt id auditable
    without re-fetching it from Virlo; `used_posts()` is what Collect asks, so both are asserted.
    """
    await record_use(tmp_path, {TOPIC: [("post-a", URL_A), ("post-b", URL_B)]}, RUN_ID)

    history = read_history(tmp_path)
    assert history[TOPIC]["posts"] == {"post-a": _post(0, URL_A), "post-b": _post(0, URL_B)}
    # `used_posts` answers post IDS only: the permalink is record-side provenance, and returning
    # it would make every caller strip it again before comparing.
    assert used_posts(history, within_days=7) == {TOPIC: {"post-a", "post-b"}}
    # The post ids live INSIDE the topic entry — no second file, no second lock (plan §2.2).
    assert sorted(p.name for p in tmp_path.iterdir()) == [HISTORY_FILE]


async def test_fr153_a_bare_post_id_is_tolerated_and_records_an_empty_url(tmp_path: Path) -> None:
    """A caller that has no permalink must not be forced to invent one (`state._pairs`): the id is
    the namespace, and the URL is a nicety on top of it."""
    await record_use(tmp_path, {TOPIC: ["post-a", ("post-b", URL_B)]}, RUN_ID)

    assert read_history(tmp_path)[TOPIC]["posts"] == {
        "post-a": _post(0, ""), "post-b": _post(0, URL_B)}


async def test_fr153_a_second_run_merges_new_post_ids_into_the_existing_map(
    tmp_path: Path,
) -> None:
    """A later run adds to the map; it never replaces it. Overwriting would hand yesterday's posts
    back as fresh and reintroduce the repetition FR-7 exists to prevent."""
    await record_use(tmp_path, {TOPIC: [("post-a", URL_A)]}, "run-1")
    await record_use(tmp_path, {TOPIC: [("post-b", URL_B), ("post-c", "")]}, "run-2")

    history = read_history(tmp_path)
    assert set(history[TOPIC]["posts"]) == {"post-a", "post-b", "post-c"}
    assert history[TOPIC]["posts"]["post-a"]["url"] == URL_A  # run-1's permalink survived run-2
    assert used_posts(history, within_days=7) == {TOPIC: {"post-a", "post-b", "post-c"}}


async def test_fr153_duplicate_post_ids_in_one_call_are_recorded_once(tmp_path: Path) -> None:
    """One creative can quote the same post twice — a headline and the caption off one
    `SourcePost` — and two siblings on one topic land on the same post whenever
    `trend_reuse_index` wraps (§1.6). The id is the namespace, so that is ONE entry, not two, and
    the pair that actually knows the permalink is the one that wins."""
    await record_use(tmp_path, {TOPIC: [("post-a", ""), ("post-a", URL_A), ("", URL_B),
                                        ("post-b", "")]}, RUN_ID)

    posts = read_history(tmp_path)[TOPIC]["posts"]
    assert set(posts) == {"post-a", "post-b"}  # the blank id is not a post
    assert posts["post-a"]["url"] == URL_A  # the knowing pair upgraded the empty one


# --------------------------------------------------------------------------- older shapes


async def test_fr153_an_entry_without_a_posts_key_reads_as_no_posts_used(tmp_path: Path) -> None:
    """THE no-migration guarantee (plan §2.2, FR-82/FR-153).

    An entry that carries no `posts` key must read as "no posts used" — every candidate post is
    fresh — so that there is no schema version, no migration step, and above all **no window in
    which post-level recency protection is silently off**. The topic-level recency it always had
    (NFR-24) keeps working unchanged, and a write for a different topic must not touch it.
    """
    legacy = {TOPIC: {"first_used": _days_ago(3), "last_used": _days_ago(1),
                      "run_ids": ["20260809_210026_m9zy"]}}
    _seed(tmp_path, legacy)

    history = read_history(tmp_path)
    assert history == legacy  # nothing was invented, upgraded or re-keyed on read
    assert "posts" not in history[TOPIC]
    assert used_posts(history, within_days=7) == {}  # absent == no posts used == all fresh
    assert (days_since_use(history, TOPIC) or 0) < 2  # topic-level recency still answers

    await record_use(tmp_path, {OTHER: [("post-x", URL_A)]}, RUN_ID)

    after = read_history(tmp_path)
    assert after[TOPIC] == legacy[TOPIC]  # a write for another topic rewrote nothing here
    assert used_posts(after, within_days=7) == {OTHER: {"post-x"}}


def test_fr298_readers_accept_the_two_older_posts_spellings(tmp_path: Path) -> None:
    """FR-298's amendment added the URL beside the date; three spellings can therefore be on disk.

    A bare date string is what every pre-amendment run wrote (there was no URL to record, so there
    is none to invent). The `"<date>|<url>"` pipe form is the spelling FR-153's amendment text
    uses, read here so a file written to that reading is understood rather than aged out early.
    Both must answer the window exactly as the current mapping does; anything else is junk.
    """
    history = {TOPIC: {"last_used": _days_ago(1),
                       "posts": {"bare": _days_ago(2),
                                 "piped": f"{_days_ago(2)}|{URL_B}",
                                 "current": _post(2, URL_A),
                                 "junk": 17,
                                 "stale-bare": _days_ago(40)}}}

    assert used_posts(history, within_days=7) == {TOPIC: {"bare", "piped", "current"}}


async def test_fr298_a_write_converges_the_file_onto_one_posts_shape(tmp_path: Path) -> None:
    """`_prune` writes back what `_fresh_posts` normalized, so the first run to touch an older file
    upgrades every surviving value in place — which is why no migration pass exists."""
    _seed(tmp_path, {TOPIC: {"last_used": _days_ago(1), "run_ids": [],
                             "posts": {"bare": _days_ago(2),
                                       "piped": f"{_days_ago(2)}|{URL_B}"}}})

    await record_use(tmp_path, {OTHER: [("post-x", "")]}, RUN_ID, history_days=7)

    posts = read_history(tmp_path)[TOPIC]["posts"]
    assert posts["bare"] == {"date": _days_ago(2), "url": ""}
    assert posts["piped"] == {"date": _days_ago(2), "url": URL_B}


async def test_d44_a_pre_pivot_monitor_keyed_entry_simply_stops_matching(tmp_path: Path) -> None:
    """The `history_key` migration, by design (D44/§1.6): the key gained a `::<topic_key>` half, so
    every entry a pre-pivot run wrote under the bare monitor id no longer matches any topic. The
    first post-pivot run therefore sees an empty window — deliberately — and those entries age out
    through the ordinary prune horizon rather than through a migration pass nobody would test.
    """
    _seed(tmp_path, {MONITOR: {"last_used": _days_ago(1), "run_ids": ["run-0"],
                               "posts": {"post-a": _days_ago(1)}}})
    history = read_history(tmp_path)

    assert days_since_use(history, TOPIC) is None  # the topic has never been used
    assert used_posts(history, within_days=7) == {MONITOR: {"post-a"}}, \
        "the old entry is still READ — it is simply keyed by something no topic claims"

    await record_use(tmp_path, {TOPIC: [("post-b", URL_B)]}, RUN_ID, history_days=7)

    after = read_history(tmp_path)
    assert set(after) == {MONITOR, TOPIC}  # both stand; the old one expires on the 90-day horizon
    assert after[TOPIC]["posts"] == {"post-b": _post(0, URL_B)}


async def test_fr153_a_topic_that_quoted_zero_posts_still_records_the_topic(
    tmp_path: Path,
) -> None:
    """An empty post sequence is legitimate and is NOT "nothing happened": an override brief quotes
    nothing at all (FR-144), and a copy degrade may ship our own words. The topic packaged, so the
    topic is recorded — and no `posts` key is invented, because absent means exactly "no posts
    used"."""
    await record_use(tmp_path, {TOPIC: []}, RUN_ID)

    entry = read_history(tmp_path)[TOPIC]
    assert entry["run_ids"] == [RUN_ID]
    assert "posts" not in entry
    assert used_posts(read_history(tmp_path), within_days=7) == {}


# --------------------------------------------------------------------------- run_ids


async def test_fr82_run_ids_keep_only_the_five_most_recent(tmp_path: Path) -> None:
    """FR-82: "most recent 5 run ids per trend" — a rolling window, not an archive."""
    for index in range(7):
        await record_use(tmp_path, {TOPIC: [(f"post-{index}", "")]}, f"run-{index}")

    assert RUN_IDS_KEPT == 5
    assert read_history(tmp_path)[TOPIC]["run_ids"] == [f"run-{i}" for i in range(2, 7)]


async def test_fr82_the_same_run_id_is_never_recorded_twice(tmp_path: Path) -> None:
    """One run recording two creatives for the same topic is still one run. `first_used` is also
    left alone — it is the oldest date, not the newest."""
    await record_use(tmp_path, {TOPIC: [("post-a", "")]}, RUN_ID)
    first_used = read_history(tmp_path)[TOPIC]["first_used"]
    await record_use(tmp_path, {TOPIC: [("post-b", "")]}, RUN_ID)

    entry = read_history(tmp_path)[TOPIC]
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
    await record_use(tmp_path, {TOPIC: [("post-a", "")]}, RUN_ID, history_days=7, log=log)

    assert MIN_PRUNE_DAYS == 90
    assert set(read_history(tmp_path)) == {"recent", TOPIC}
    assert log.events[0][2]["pruned"] == 2


async def test_fr82_the_horizon_is_the_larger_of_history_days_and_ninety(tmp_path: Path) -> None:
    """A config asking for a 200-day window gets one; a config asking for 7 still keeps 90, because
    the archive floor is what makes a widened window possible later."""
    seed = {"old": {"last_used": _days_ago(120), "run_ids": []}}

    _seed(tmp_path, seed)
    await record_use(tmp_path, {TOPIC: ()}, RUN_ID, history_days=200)
    assert "old" in read_history(tmp_path)  # 120 days is inside max(200, 90)

    _seed(tmp_path, seed)
    await record_use(tmp_path, {TOPIC: ()}, RUN_ID, history_days=7)
    assert "old" not in read_history(tmp_path)  # 120 days is outside max(7, 90)


async def test_fr153_stale_posts_are_pruned_inside_a_surviving_entry_on_the_same_pass(
    tmp_path: Path,
) -> None:
    """FR-153: the `posts` map is pruned on the SAME pass and against the SAME horizon as the
    entries. Two prune passes with two horizons is how the two dimensions drift apart."""
    _seed(tmp_path, {"survivor": {"first_used": _days_ago(200), "last_used": _days_ago(1),
                                  "run_ids": ["run-0"],
                                  "posts": {"old-post": _post(120, URL_A),
                                            "fresh-post": _post(1, URL_B)}}})

    await record_use(tmp_path, {TOPIC: [("post-a", "")]}, RUN_ID, history_days=7)

    entry = read_history(tmp_path)["survivor"]
    assert entry["posts"] == {"fresh-post": _post(1, URL_B)}
    assert entry["last_used"] == _days_ago(1)  # the entry itself was not otherwise touched


async def test_fr153_an_emptied_posts_map_is_deleted_because_absent_means_the_same(
    tmp_path: Path,
) -> None:
    """Once every post in an entry has aged out, the key is removed rather than left as `{}` — the
    two states are read identically, and one shape is one fewer thing to reason about."""
    _seed(tmp_path, {"survivor": {"last_used": _days_ago(1), "run_ids": [],
                                  "posts": {"old-post": _post(200, URL_A)}}})

    await record_use(tmp_path, {TOPIC: ()}, RUN_ID, history_days=7)

    assert "posts" not in read_history(tmp_path)["survivor"]


# --------------------------------------------------------------------------- the window


def test_fr7_zero_days_disables_the_post_window_entirely() -> None:
    """FR-7: "`0` still disables". `--history-days 0` is the operator's escape hatch out of an
    exhausted config, so it must return every post to the fresh pool."""
    history = {TOPIC: {"last_used": _days_ago(0), "posts": {"post-a": _post(0, URL_A)}}}

    assert used_posts(history, within_days=0) == {}
    assert used_posts(history, within_days=-1) == {}
    assert used_posts(history, within_days=7) == {TOPIC: {"post-a"}}


def test_fr153_posts_outside_the_window_are_not_reported_as_used() -> None:
    """NFR-24 at post granularity: the window is what makes a post quotable again. An entry whose
    every post has aged out drops out of the map altogether, which reads as "all candidates fresh".
    """
    history = {TOPIC: {"last_used": _days_ago(1),
                       "posts": {"stale": _post(30), "fresh": _post(2)}},
               OTHER: {"last_used": _days_ago(30), "posts": {"stale": _post(30)}}}

    assert used_posts(history, within_days=7) == {TOPIC: {"fresh"}}


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
    """Valid JSON of the wrong shape is corruption too — a list has no topic keys to read."""
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
    """One junk entry never costs the whole file: the readable entries still protect their topics."""
    _seed(tmp_path, {TOPIC: {"last_used": _days_ago(1)}, "junk": 5, "also-junk": ["x"]})

    assert set(read_history(tmp_path)) == {TOPIC}


async def test_fr83_a_junk_posts_value_inside_a_valid_entry_cannot_break_a_run(
    tmp_path: Path,
) -> None:
    """A `posts` value that is not a map is discarded, never a crash (FR-83) — read as "no posts
    used", and replaced on the next write rather than merged into."""
    _seed(tmp_path, {TOPIC: {"last_used": _days_ago(1), "run_ids": [], "posts": "corrupted"}})

    assert used_posts(read_history(tmp_path), within_days=7) == {}
    assert await record_use(tmp_path, {TOPIC: [("post-a", URL_A)]}, RUN_ID) is True
    assert read_history(tmp_path)[TOPIC]["posts"] == {"post-a": _post(0, URL_A)}


# --------------------------------------------------------------------------- FR-254 locking


async def test_fr254_a_held_lock_degrades_to_read_only_with_one_warning(tmp_path: Path) -> None:
    """FR-254: "a busy lock degrades to read-only with one warning and NEVER blocks or fails a run".

    The return value is the whole status — `False` means "went read-only", not "raised". The other
    run's lock is left exactly where it was: unlinking someone else's lock is how the two-file
    design this plan rejected would have corrupted itself (plan §2.2).
    """
    lock = _hold_lock(tmp_path)
    _seed(tmp_path, {TOPIC: {"last_used": _days_ago(5), "run_ids": ["run-0"]}})
    log = RecordingLog()

    assert await record_use(tmp_path, {TOPIC: [("post-a", URL_A)]}, RUN_ID, log=log) is False

    assert log.warned == ["trend_history_locked"]
    assert log.events == []  # nothing was recorded, so nothing is claimed to have been
    assert lock.is_file()  # its owner still holds it
    assert read_history(tmp_path)[TOPIC] == {"last_used": _days_ago(5), "run_ids": ["run-0"]}


async def test_fr254_a_lock_older_than_sixty_seconds_is_broken(tmp_path: Path) -> None:
    """A crashed run holds its lock forever, so a stale one is broken rather than waited on —
    otherwise one Ctrl+C would make every later run read-only."""
    assert STALE_LOCK_S == 60.0
    _hold_lock(tmp_path, age_s=STALE_LOCK_S + 60)
    log = RecordingLog()

    assert await record_use(tmp_path, {TOPIC: [("post-a", URL_A)]}, RUN_ID, log=log) is True

    assert log.warnings == []
    assert read_history(tmp_path)[TOPIC]["posts"] == {"post-a": _post(0, URL_A)}


async def test_fr254_the_lock_is_released_on_the_way_out(tmp_path: Path) -> None:
    """A write that finished leaves no lock behind — the next run must not inherit a read-only
    history because this one succeeded."""
    await record_use(tmp_path, {TOPIC: [("post-a", URL_A)]}, RUN_ID)

    assert not (tmp_path / LOCK_FILE).exists()
    assert await record_use(tmp_path, {OTHER: [("post-b", URL_B)]}, "run-2") is True


async def test_fr82_recording_nothing_writes_nothing_and_takes_no_lock(tmp_path: Path) -> None:
    """A run that packaged nothing records nothing (FR-82 is the caller's rule, and this is its
    floor): no file is created, no lock is taken, and the status is still success."""
    assert await record_use(tmp_path, {}, RUN_ID) is True
    assert await record_use(tmp_path, {"": [("post-a", "")]}, RUN_ID) is True  # a blank key is none

    assert list(tmp_path.iterdir()) == []


async def test_fr82_the_update_is_logged_once_with_its_counts(tmp_path: Path) -> None:
    """One event per write, carrying what was recorded — the line that makes a repeating run
    explainable when the same posts keep coming back."""
    log = RecordingLog()

    await record_use(tmp_path, {TOPIC: [("post-a", URL_A), ("post-b", URL_B)], OTHER: []},
                     RUN_ID, log=log)

    assert len(log.events) == 1
    event_type, _, data = log.events[0]
    assert event_type == "trend_history_updated"
    assert sorted(data["trends"]) == sorted([OTHER, TOPIC])
    assert data["posts"] == 2
    assert data["pruned"] == 0


# ------------------------------------------- the runner seam that feeds this file (item 14)


def _entry(order: int, asset_id: str, topic_key: str,
           status: PlanEntryStatus = PlanEntryStatus.SUCCESS) -> PlanEntry:
    return PlanEntry(  # type: ignore[arg-type]
        order=order, asset_id=asset_id, creative_format="image", platform="linkedin",
        language="en", aspect_ratio="16:9", status=status, trend_key=topic_key)


def _record(asset_id: str, post_id: str) -> AssetRecord:
    """The slice of `AssetRecord` FR-153/FR-298 reads: which `SourcePost` this creative quoted."""
    return AssetRecord(asset_id=asset_id, source=TOPIC, source_name="AI agents",
                       platform="linkedin", creative_format="image",
                       copy_source_post_id=post_id)


def test_fr153_posts_used_reports_only_the_posts_a_delivered_creative_quoted() -> None:
    """`runner._posts_used` produces exactly the `{history_key: [(post_id, url)]}` shape
    `record_use` consumes (contracts item 14) — the pinned seam between the two.

    Post-pivot the history's job is verbatim-copy freshness, so the record is
    `copy_source_post_id` off each DELIVERED creative's meta record, never the whole topic's post
    list: a topic contributes only the posts that actually became pixels or captions. The URL
    rides along, resolved from the topic's own `SourcePost`, so the history entry is auditable
    without a Virlo lookup. A creative that did not deliver contributes nothing.
    """
    topic = TrendItem(
        history_key=TOPIC, monitor_id=MONITOR, topic_key="ai-agents-that-ship", name="AI agents",
        posts=[SourcePost(post_id="post-a", url=URL_A, author="c", views=9),
               SourcePost(post_id="post-b", url=URL_B, author="c", views=4)])
    entries = [
        _entry(0, "Li_img_ai-agents_01", TOPIC),
        _entry(1, "Li_img_ai-agents_02", TOPIC),
        _entry(2, "Li_img_ai-agents_03", TOPIC, PlanEntryStatus.FAILED),
    ]
    report = SimpleNamespace(
        packaged_trends={TOPIC},
        records={"Li_img_ai-agents_01": _record("Li_img_ai-agents_01", "post-a"),
                 "Li_img_ai-agents_02": _record("Li_img_ai-agents_02", "post-b"),
                 "Li_img_ai-agents_03": _record("Li_img_ai-agents_03", "post-a")})

    uses = _posts_used(SimpleNamespace(), report, {TOPIC: topic}, entries)

    assert uses == {TOPIC: [("post-a", URL_A), ("post-b", URL_B)]}


def test_fr153_two_creatives_quoting_one_post_record_it_once() -> None:
    """§1.6's sibling divergence means two creatives on one topic usually quote two posts — but
    `trend_reuse_index` wraps once the creatives outnumber the posts, and a repeated pair must not
    become a repeated history row."""
    topic = TrendItem(history_key=TOPIC, monitor_id=MONITOR, topic_key="t", name="AI agents",
                      posts=[SourcePost(post_id="post-a", url=URL_A)])
    entries = [_entry(0, "a1", TOPIC), _entry(1, "a2", TOPIC)]
    report = SimpleNamespace(packaged_trends={TOPIC},
                             records={"a1": _record("a1", "post-a"),
                                      "a2": _record("a2", "post-a")})

    assert _posts_used(SimpleNamespace(), report, {TOPIC: topic}, entries) == {
        TOPIC: [("post-a", URL_A)]}


def test_fr153_a_creative_that_quoted_nothing_leaves_its_topic_with_an_empty_list() -> None:
    """A packaged topic is recorded even when nothing was quoted (an override brief, a copy
    degrade) — `record_use` treats the empty list as "the topic shipped, no post burnt", which is
    exactly the distinction the entry-versus-posts split exists to keep."""
    topic = TrendItem(history_key=TOPIC, monitor_id=MONITOR, topic_key="t", name="AI agents")
    entry = _entry(0, "a1", TOPIC)
    report = SimpleNamespace(packaged_trends={TOPIC}, records={"a1": _record("a1", "")})

    assert _posts_used(SimpleNamespace(), report, {TOPIC: topic}, [entry]) == {TOPIC: []}


# --------------------------------------------------------------------------- the file on disk


async def test_fr254_the_history_file_is_utf8_json_with_a_trailing_newline(tmp_path: Path) -> None:
    """FR-256/FR-254: written atomically as UTF-8 with LF newlines, parseable by anything, and
    stable across runs (sorted keys) so a diff shows what changed rather than a reshuffle."""
    await record_use(tmp_path, {OTHER: [("post-b", URL_B)], TOPIC: [("post-a", URL_A)]}, RUN_ID)

    blob = (tmp_path / HISTORY_FILE).read_bytes()
    assert b"\r\n" not in blob
    assert blob.endswith(b"\n")
    text = blob.decode("utf-8")
    assert list(json.loads(text)) == sorted([OTHER, TOPIC])
    first, second = sorted([OTHER, TOPIC])
    assert text.index(f'"{first}"') < text.index(f'"{second}"')  # written sorted, not as passed
