"""Virlo adapter — MCP tool calls in, ranked `TrendItem`s with coherent reference sets out.

Callers import `hypesocials.sources`, never this module. Behind that facade:

- **Join rule (20 §3, corrected by spikes/RESULTS.md §A):** one item per configured monitor id.
  `get_monitor_analysis` gives name, `why_it_works`, themes/tactics, timing and connecting thread;
  `get_top_videos`/`get_top_slideshows` give media, hooks, panel texts and engagement for that same
  monitor, asked for as `views desc` so "top" means top; the global `get_trends` digest enriches
  `cross_monitor_context`, may supply the LAST-RESORT reference tier (A18), and still creates no
  items. §A swaps the PRD table's digest vs monitor-analysis ownership — shapes follow RESULTS.md,
  behaviour follows the PRD.
- **Strength (FR-5):** views .35, median views .15, velocity .30, confidence .20, each min-max
  normalized inside the run's candidate pool. Hardcoded weights, by PRD decision.
- **Coherent reference sets (FR-91):** every group is ONE source — a single slideshow's panels (in
  `position` order) or one creator's thumbnails — built as `ReferenceSet` units, ALL of them.
- **Post-level freshness (FR-7):** `used_posts` picks the freshest unused set and EVERY field the
  creative is shaped by comes from that set; the same map picks the reel's motion reference (FR-24,
  three tiers, best-effort — tier 3 repeats a source rather than lose a paid reel).
- **Per-image download (FR-32/33/247):** independent per image; a dead URL drops that image only.
- **Funnel accountability (FR-155):** every stage above tallies into ONE run-wide `Counters` —
  rows in, duplicates dropped, sets qualified or turned away, the freshness verdict, images
  downloaded or dead — emitted once as the `collect_funnel` event and printed by the runner. A
  loss that is not counted here is invisible to the operator, which is the NFR-5 failure this
  object exists to close.

Invariants: no direct `api.virlo.ai` call (NFR-11); no retry on top of the wrapper's bounded retry
(FR-120) — only CDN downloads retry here; the digest is the ONLY metered call ($0.25, §A), so
`include_digest=False` keeps a preview at $0; `intelligence.*` is optional (~70% miss) and an item
stays usable without it; reels are OFF in W2 — `winning_video_url` is data, and no yt-dlp activity
happens here (that is W4's `video_ref.py`).

Do not: rank or filter for Select (it owns verdicts); mutate `models.py`; log an API key.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import statistics
import tempfile
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from hypesocials.config import Config
from hypesocials.mcp_client import MCPClientError, MCPError, ServerConfig, Session, SessionPool
from hypesocials.models import ReferenceSet, TrendItem
from hypesocials.util import slugify
from hypesocials.virlo_mcp import VirloToolError, translate

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hypesocials.outputs import LogWriter

logger = logging.getLogger(__name__)

SERVER_NAME = "virlo"
#: One page of media per monitor, asked for in the order that makes the tool's name true.
#: Virlo's maximum page size is 100 and it sorts nothing by default, so `get_top_videos` without
#: `order_by` returns insertion order — measured live 2026-08-11 on a 2,039-row monitor, a median
#: of 2,534 views against 1,940,676 for `views desc` (766x), and half the rows carrying Virlo's
#: enriched `intelligence` block (17/50 against 34/50), because Virlo enriches its winners first.
#: One sorted page beats twenty unsorted ones, so nothing here pages. `offset` is NOT sent and
#: cannot be: Virlo answers it with HTTP 400 and the wrapper refuses it structurally (20 §3).
_MEDIA_LIMIT, _MEDIA_ORDER_BY, _MEDIA_SORT = 100, "views", "desc"
_MIN_PANELS = 3  # RESULTS.md §A: 14/50 slideshows are single-image, so one panel isn't a set
_MIN_THUMBS = 2  # FR-91 wants 2-3 refs; a lone thumbnail is a last resort, not a coherent set
_MAX_EXEMPLARS = 5  # FR-100 wants 3-5 verbatim source hooks
#: A14 — the winning posts' real hashtags, as reference material for the copy call. Capped per
#: post as well as in total because a single row can carry 39 tags (measured: one motivational
#: post spraying `#mindsetquotes`-style filler), which would fill the whole list from one source
#: and tell the copywriter about that post rather than about the trend.
_MAX_HASHTAGS, _MAX_HASHTAGS_PER_POST = 8, 3
#: A13 — values Virlo writes into a classification field when it classified nothing. They are an
#: absence wearing a label, and passing "hook type: none" to a copywriter is worse than silence.
_NON_LABELS = frozenset({"none", "unknown", "n/a", "null", "other"})
_MAX_TACTICS, _MAX_THEMES, _WHY_MAX_CHARS, _CONTEXT_MAX_CHARS = 12, 3, 1200, 600  # §A: 9 themes deep
_DIGEST_ROWS, _DOWNLOAD_TIMEOUT_S, _MAX_PARALLEL, _BACKOFF_S = 8, 20.0, 8, 0.5
_TEMP_PREFIX = "hypesocials-refs-"
_SUFFIXES = (".webp", ".jpg", ".jpeg", ".png", ".gif")
#: FR-5's weights — stated in the PRD so the operator signed off on them, never a config knob.
_WEIGHTS = {"total_views": 0.35, "median_views": 0.15, "velocity": 0.30, "confidence": 0.20}
#: FR-91's frame screen. Unknown stays neutral: `intelligence.*` is absent unless
#: `intelligence_status == "ready"`, and sinking ~70% of live media would be worse than not screening.
_COMPLEXITY = {"low": 1.0, "simple": 1.0, "minimal": 1.0, "medium": 0.5, "moderate": 0.5,
               "high": 0.0, "complex": 0.0, "very_high": 0.0, "busy": 0.0}

_CACHE: dict[str, Path] = {}  # reference URL -> the local file this run downloaded it to
_CACHE_DIR: Path | None = None
_CACHE_DIR_OWNED = False

#: `Counters` fields that describe the SHAPE of the ask rather than a quantity of material. They
#: are set once on the run-wide object and must never be summed when a tally is absorbed — three
#: monitors asked for 100 rows each still asked for 100 rows per call, not 300.
_CARRIED_FIELDS = frozenset({"rows_per_call", "download_cap", "min_panels", "min_frames"})


# ------------------------------------------------------------------------------- public API


@dataclass(slots=True)
class Counters:
    """The Virlo funnel: what came in, what survived each stage, and what a job will attach (FR-155).

    ONE object per run, reported ONCE. `runner._funnel_block()` prints the human block after
    Select and in both preview modes; `virlo.fetch()` writes the machine record as the
    `collect_funnel` event. A run-wide rollup is what keeps the report survivable when a monitor
    stops meaning one trend (plan §3.4b): nine themes produce one seven-line block, not nine.

    Accumulation is deliberately two-level. `_monitor_item` builds a private tally, hands it to
    the per-monitor work and `absorb()`s it into the run-wide object afterwards, so
    `virlo_payload`'s numbers are scoped to whatever produced them instead of repeating one
    monitor-wide figure per theme — and a per-theme tally slots in underneath without moving a
    call site. Every quantity is additive; the four fields in `_CARRIED_FIELDS` are the ask's
    shape and are carried, never summed.

    **Zeros are the point.** `reference_shortfall`, `reference_image_dropped`, `trend_text_only`
    and `reference_free` fired in NONE of the archived runs, which leaves an operator unable to
    tell "nothing was lost" from "the counter is dead". Every stage is printed unconditionally, so
    a zero is an answer rather than a silence.

    **Input and output vocabulary stay disjoint** (FR-155/NFR-5). INPUT words — video, slideshow,
    panel, frame, post, set — describe Virlo evidence and appear only on `input`/`sets`/`chosen`/
    `images`. OUTPUT words — image, carousel, reel, creative, job — describe what this tool
    generates and appear only on `render`. A Virlo slideshow is evidence: it gives a trend
    *carousel affinity* (FR-90) and is never itself rendered, so "3 slideshows -> 2 carousels" is
    a sentence this object cannot produce.
    """

    # --- the ask (run-wide; a per-monitor tally leaves these at zero and `absorb` carries them)
    monitors_asked: int = 0
    monitors_failed: int = 0
    rows_per_call: int = 0
    download_cap: int = 0
    min_panels: int = _MIN_PANELS
    min_frames: int = _MIN_THUMBS
    total_available: int = 0  # Virlo's own row total behind the one page each call asked for

    # --- input: rows Virlo returned, and the ones `_dedupe` dropped before anything read them
    videos_raw: int = 0
    slideshows_raw: int = 0
    videos_kept: int = 0
    slideshows_kept: int = 0

    # --- sets: FR-91's coherent-candidate screen, and every row it turned away
    slideshow_sets: int = 0
    frame_sets: int = 0
    last_resort_sets: int = 0
    slideshows_thin: int = 0  # a slideshow with fewer than `min_panels` panels
    families_thin: int = 0  # one creator's frames, fewer than `min_frames` after the face screen
    videos_in_sets: int = 0
    videos_in_thin_families: int = 0
    videos_without_thumbnail: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)

    # --- choice: FR-7's freshness verdict per trend, and FR-24's motion tier
    chosen_fresh: int = 0
    chosen_repeated: int = 0
    chosen_last_resort: int = 0
    chosen_none: int = 0  # a trend that qualified no candidate set at all
    motion_tiers: dict[str, int] = field(default_factory=dict)

    # --- images: the CDN pass, which is where a set becomes something a job can attach
    images_attempted: int = 0
    images_downloaded: int = 0
    images_dead: int = 0
    trends_text_only: int = 0
    trends_short: int = 0  # kept its set, but with fewer images than `reference_images_per_job`

    trends_returned: int = 0

    # --- Select's verdicts. Recorded by the caller (`runner._select`), because Select owns them.
    verdict_seen: bool = False
    eligible: int = 0
    excluded_by_history: int = 0
    unusable: int = 0

    # --- the render forecast. Recorded by the caller once assignment has run.
    render_seen: bool = False
    jobs: int = 0
    jobs_dropped: int = 0
    trends_used: int = 0
    trend_refs_min: int = 0
    trend_refs_max: int = 0
    inspiration_each: int = 0
    refs_total: int = 0

    # ----------------------------------------------------------------- accumulation

    def absorb(self, other: Counters) -> None:
        """Fold one tally (a monitor's, later a theme's) into this run-wide rollup.

        Synchronous with no `await` inside, which is what makes it safe to call from the
        concurrent monitor coroutines: the event loop's single thread cannot interleave two folds
        and lose a count (the same argument `outputs.LogWriter` makes about its writes).
        """
        for spec in fields(self):
            mine, theirs = getattr(self, spec.name), getattr(other, spec.name)
            if spec.name in _CARRIED_FIELDS:
                setattr(self, spec.name, max(mine, theirs))
            elif isinstance(mine, dict):
                for key, value in theirs.items():
                    mine[key] = mine.get(key, 0) + value
            elif isinstance(mine, bool):  # before the int branch: a bool IS an int in Python
                setattr(self, spec.name, mine or theirs)
            else:
                setattr(self, spec.name, mine + theirs)

    def add_input(self, *, videos_raw: int, slideshows_raw: int, videos_kept: int,
                  slideshows_kept: int, total_available: int = 0) -> None:
        """One media pair as it arrived and as it survived `_dedupe` (the run measured 11 repeated
        rows across three monitors, which `virlo_payload` used to report as material)."""
        self.videos_raw += videos_raw
        self.slideshows_raw += slideshows_raw
        self.videos_kept += videos_kept
        self.slideshows_kept += slideshows_kept
        self.total_available += total_available

    def reject(self, reason: str, count: int = 1) -> None:
        """Name one screen a row failed. The reason strings are the `rejection_reasons` map on
        the `reference_choice` event, so every silent drop NFR-5 complains about gets a name."""
        if count:
            self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + count

    def add_choice(self, *, fresh: bool, has_set: bool, last_resort: bool, motion_tier: str) -> None:
        """One trend's chosen reference set and motion reference, classified for the report."""
        if not has_set:
            self.chosen_none += 1
        elif last_resort:
            self.chosen_last_resort += 1
        elif fresh:
            self.chosen_fresh += 1
        else:
            self.chosen_repeated += 1
        self.motion_tiers[motion_tier] = self.motion_tiers.get(motion_tier, 0) + 1

    def add_downloads(self, *, attempted: int, downloaded: int) -> None:
        """The CDN pass. `attempted - downloaded` is the dead-URL count, by construction."""
        self.images_attempted += attempted
        self.images_downloaded += downloaded
        self.images_dead += attempted - downloaded

    def record_selection(self, *, eligible: int, excluded: int, unusable: int) -> None:
        """Select's three verdict buckets (`plan.Selection`), which the adapter never sees."""
        self.verdict_seen = True
        self.eligible, self.excluded_by_history, self.unusable = eligible, excluded, unusable

    def record_render(self, *, jobs: int, dropped: int, trend_refs: Sequence[int],
                      inspiration_each: int, trends_used: int) -> None:
        """The forecast end of the funnel: how many jobs attach how much of this material.

        `trend_refs` is one count per creative that will render, so the block can say "3 trend
        ref(s)" when they agree and "2-3" when they do not, instead of inventing an average.
        """
        self.render_seen = True
        self.jobs, self.jobs_dropped, self.trends_used = jobs, dropped, trends_used
        self.trend_refs_min = min(trend_refs) if trend_refs else 0
        self.trend_refs_max = max(trend_refs) if trend_refs else 0
        self.inspiration_each = inspiration_each
        self.refs_total = sum(trend_refs) + inspiration_each * jobs

    # ----------------------------------------------------------------- derived views

    @property
    def posts_raw(self) -> int:
        """Every row Virlo shipped, videos and slideshows together — before the dedupe."""
        return self.videos_raw + self.slideshows_raw

    @property
    def posts_kept(self) -> int:
        """The rows the pipeline actually read: `posts_raw` minus the repeated ones."""
        return self.videos_kept + self.slideshows_kept

    @property
    def duplicates_dropped(self) -> int:
        return self.posts_raw - self.posts_kept

    @property
    def sets_qualified(self) -> int:
        """FR-91 coherent sets. The last-resort loose group is NOT one and is counted apart."""
        return self.slideshow_sets + self.frame_sets

    @property
    def sets_thin(self) -> int:
        return self.slideshows_thin + self.families_thin

    @property
    def motion(self) -> dict[str, int]:
        """FR-24's three tiers plus `none`, always all four keys, so a zero is visible."""
        return {tier: self.motion_tiers.get(tier, 0)
                for tier in ("fresh_same_creator", "fresh", "repeat", "none")}

    def as_event(self) -> dict[str, Any]:
        """The `collect_funnel` payload: five nested objects, exactly FR-155's shape.

        Nested on purpose, and therefore NOT the run.log line: `LogWriter._digest` truncates each
        value at 120 chars, so the human block travels through `narrative()` and this travels
        through `event()` — the same split `_spend_table` already uses.
        """
        return {
            "input": {"monitors_asked": self.monitors_asked, "monitors_failed": self.monitors_failed,
                      "videos_raw": self.videos_raw, "slideshows_raw": self.slideshows_raw,
                      "videos": self.videos_kept, "slideshows": self.slideshows_kept,
                      "duplicates_dropped": self.duplicates_dropped,
                      "total_available": self.total_available},
            "sets": {"qualified": self.sets_qualified, "slideshow_sets": self.slideshow_sets,
                     "frame_sets": self.frame_sets, "last_resort": self.last_resort_sets,
                     "too_thin": self.sets_thin, "slideshows_thin": self.slideshows_thin,
                     "families_thin": self.families_thin,
                     "videos_in_sets": self.videos_in_sets,
                     "videos_in_thin_families": self.videos_in_thin_families,
                     "videos_without_thumbnail": self.videos_without_thumbnail,
                     "rejection_reasons": dict(self.rejection_reasons)},
            "choice": {"fresh": self.chosen_fresh, "repeated": self.chosen_repeated,
                       "last_resort": self.chosen_last_resort, "no_set": self.chosen_none,
                       "trends": self.trends_returned, "motion": self.motion},
            "images": {"attempted": self.images_attempted, "downloaded": self.images_downloaded,
                       "dead": self.images_dead, "text_only_trends": self.trends_text_only,
                       "short_sets": self.trends_short},
            "caps": {"rows_per_call": self.rows_per_call, "download_cap": self.download_cap,
                     "min_panels": self.min_panels, "min_frames": self.min_frames},
        }

    def summary_line(self) -> str:
        """One flat sentence for run.log's digest of `collect_funnel` — the nested record above
        would render there as a truncated, unreadable single line."""
        return (f"{self.posts_kept} post(s) after {self.duplicates_dropped} duplicate(s), "
                f"{self.sets_qualified} coherent set(s), {self.trends_returned} trend(s), "
                f"{self.images_downloaded} of {self.images_attempted} image(s) downloaded")


class TrendFeed(list):  # type: ignore[type-arg]  # a plain list of TrendItem, plus the funnel
    """What Collect returns: the ranked trend items, with this run's `Counters` attached.

    A list subclass rather than a wrapper object because the funnel is a *property of the fetch*,
    not a second channel: every caller that only wants trends (`len(trends)`, iteration, `sort`,
    `list(...)`) is untouched, and the one caller that reports the funnel reads `.counters` off
    the same result instead of a module global or an out-parameter.
    """

    __slots__ = ("counters",)

    def __init__(self, items: Sequence[TrendItem] = (), counters: Counters | None = None) -> None:
        super().__init__(items)
        self.counters = counters if counters is not None else Counters()

async def fetch(cfg: Config, *, cache_dir: Path | None = None, log: LogWriter | None = None,
                include_digest: bool = True, used_posts: Collection[str] | None = None,
                say: Callable[[str], None] | None = None) -> TrendFeed:
    """Collect every configured monitor into ranked, reference-bearing trend items.

    Args:
        cfg: the loaded run config (`sources.*` and `mcp_servers.virlo` are what matter).
        cache_dir: where reference images land; a private temp folder when omitted. The caller
            owns cleanup and calls `cleanup()` on every exit path (FR-249).
        log: the run's LogWriter, so every degrade lands in run.log/events.jsonl.
        include_digest: `False` skips `get_trends`, the one metered call, leaving
            `cross_monitor_context` empty — how a preview stays honestly at $0.
        used_posts: post ids already used inside the `trend_history_days` window (FR-7) — a set,
            or the `posts` mapping itself, since iterating it yields its keys. Omitted means
            "nothing is used yet", which is also what a history without `posts` means.
        say: the console seam, for the one refusal an operator must not have to find in run.log.

    Returns:
        A `TrendFeed` — items strongest first, with this run's funnel `Counters` attached
        (FR-155). A failed monitor contributes nothing and is logged; an empty feed means Collect
        found nothing, and the caller decides whether that aborts the run.
    """
    counters = Counters(rows_per_call=_MEDIA_LIMIT,
                        download_cap=max(1, cfg.sources.media_download_cap))
    ids = list(dict.fromkeys(str(i).strip() for i in cfg.sources.virlo_monitor_ids if str(i).strip()))
    counters.monitors_asked = len(ids)
    if not ids:
        _warn(log, "virlo_no_monitors", "sources.virlo_monitor_ids is empty — run --list-monitors",
              say=say)
        _funnel_event(log, counters)
        return TrendFeed((), counters)
    used = frozenset(str(post) for post in used_posts or ())
    size = max(1, min(cfg.sources.virlo_session_pool, len(ids) + (1 if include_digest else 0)))
    async with SessionPool(_server(cfg), size, log=log) as pool:
        jobs: list[Any] = [_monitor_item(pool, mid, cfg, log, used, counters=counters)
                           for mid in ids]
        if include_digest:
            jobs.append(_digest(pool, log))
        results = await asyncio.gather(*jobs, return_exceptions=True)

    items: list[TrendItem] = []
    context, confidences, exemplars = "", {}, []
    # `strict=True` is the guard that the labels and the gathered jobs are the same list, so the
    # "digest" label only exists when the digest job does — without that condition, every
    # `include_digest=False` call (the documented $0-preview seam) died here on a ValueError.
    labels = [*ids, "digest"] if include_digest else list(ids)
    for label, result in zip(labels, results, strict=True):
        if isinstance(result, asyncio.CancelledError):
            raise result
        if isinstance(result, BaseException):  # per-monitor degrade, never all-or-nothing (20 §10)
            if label != "digest":  # a dead digest is not a dead monitor: it creates no item (20 §3)
                counters.monitors_failed += 1
            _warn(log, "virlo_monitor_failed", f"monitor {label} returned no data: {result}",
                  monitor_id=label, error=type(result).__name__)
        elif isinstance(result, TrendItem):
            items.append(result)
        elif isinstance(result, tuple):
            context, confidences, exemplars = result
    for item in items:  # global digest first, then this monitor's own timing/thread context
        item.cross_monitor_context = " · ".join(
            part for part in (context, item.cross_monitor_context) if part)
        if item.confidence is None:  # themes lead (FR-5 v1.6.4); the digest is the empty fallback
            item.confidence = _match_confidence(item.name, confidences)
    offered = _offer_digest_exemplars(items, exemplars, cfg)
    await _download_references(items, cfg, cache_dir, log, counters=counters)
    _log_digest_exemplars(items, offered, log)
    _score(items)
    items.sort(key=lambda item: item.strength, reverse=True)
    counters.trends_returned = len(items)
    _funnel_event(log, counters)
    return TrendFeed(items, counters)


def _funnel_event(log: LogWriter | None, counters: Counters) -> None:
    """FR-155's machine record: one `collect_funnel` event per run, from the one place every
    caller passes through — so a preview writes the identical event a paid run writes.

    The nested objects go in `data` and a flat sentence goes in the message, because run.log's
    digest truncates each value at 120 chars: without the sentence the run.log line for this
    event would be a shredded dict. The human block is `runner._funnel_block()`, written through
    `narrative()`; this is the half a parser reads.
    """
    if log is not None:
        log.event("collect_funnel", f"Virlo funnel: {counters.summary_line()}",
                  **counters.as_event())


async def list_monitors(cfg: Config) -> list[tuple[str, str]]:
    """Every monitor this key can see as `(id, name)` — the $0 setup aid behind `--list-monitors`
    (FR-245). Opens one session, enters no pipeline stage."""
    async with SessionPool(_server(cfg), 1) as pool, pool.acquire() as session:
        payload = await _call(session, "list_monitors")
    return [(str(row.get("id") or ""), str(row.get("name") or "")) for row in payload.get("monitors") or []]


def reference_paths(urls: Sequence[str]) -> list[Path]:
    """Local files behind already-downloaded reference URLs, in the order asked for.

    Analysis sends bytes (FR-40, downscaled per FR-93); renders send the URL itself, because Kie
    accepts Virlo's CDN directly (RESULTS.md §B). Unknown URLs are absent from the result.
    """
    return [_CACHE[url] for url in urls if url in _CACHE]


def cleanup() -> None:
    """Delete this run's downloaded references (FR-249). Never touches `output/`, never raises."""
    global _CACHE_DIR, _CACHE_DIR_OWNED
    for path in _CACHE.values():
        with suppress(OSError):
            path.unlink(missing_ok=True)
    if _CACHE_DIR_OWNED and _CACHE_DIR is not None:
        with suppress(OSError):
            _CACHE_DIR.rmdir()
    _CACHE.clear()
    _CACHE_DIR, _CACHE_DIR_OWNED = None, False


# --------------------------------------------------------------------------- MCP collection

def _server(cfg: Config) -> ServerConfig:
    """The wrapper's launch record; `http_max_attempts` travels as its retry budget (FR-120)."""
    return ServerConfig.from_mapping(
        SERVER_NAME,
        cfg.mcp_servers.servers.get(SERVER_NAME, {"command": "python -m hypesocials.virlo_mcp"}),
        startup_timeout_s=float(cfg.mcp_servers.startup_timeout_s),
        call_timeout_s=float(cfg.mcp_servers.call_timeout_s),
        extra_env={"VIRLO_HTTP_MAX_ATTEMPTS": str(cfg.models.http_max_attempts)},
    )


async def _monitor_item(pool: SessionPool, monitor_id: str, cfg: Config,
                        log: LogWriter | None = None,
                        used: Collection[str] = frozenset(),
                        *, counters: Counters | None = None) -> TrendItem:
    """One monitor's three calls on one borrowed session (FR-115 serializes them anyway).

    Both media calls ask for the monitor's WINNERS: `views desc`, one page of `_MEDIA_LIMIT`.
    Unsorted, "top videos" was Virlo's insertion order and every reference this tool ever attached
    came from the bottom of a 2,039-row pool.

    The funnel is tallied on a PRIVATE `Counters` here and absorbed into the run-wide rollup
    afterwards (FR-155). That is what makes `virlo_payload`'s numbers scoped to what produced
    them: when a monitor stops meaning one trend, the per-theme work tallies underneath this same
    seam and the rollup still reconciles, instead of one monitor-wide figure being repeated per
    theme.
    """
    args = {"monitor_id": monitor_id, "limit": _MEDIA_LIMIT,
            "order_by": _MEDIA_ORDER_BY, "sort": _MEDIA_SORT}
    async with pool.acquire() as session:
        analysis = await _call(session, "get_monitor_analysis", {"monitor_id": monitor_id})
        videos = await _call(session, "get_top_videos", args)
        shows = await _call(session, "get_top_slideshows", args)
    clips, panels = videos.get("videos") or [], shows.get("slideshows") or []
    tally = Counters()
    # Virlo reports how deep the pool it just answered from is; one sorted page of `_MEDIA_LIMIT`
    # is all the adapter takes, and `total_available` is what makes that choice legible later.
    tally.total_available = int(_num(videos.get("total")) + _num(shows.get("total")))
    item = _build_item(monitor_id, analysis, clips, panels, cfg, used=used, log=log, counters=tally)
    _payload_event(log, item, tally)
    if counters is not None:
        counters.absorb(tally)
    return item


def _payload_event(log: LogWriter | None, item: TrendItem, tally: Counters) -> None:
    """FR-77's per-trend Virlo payload summary, written once at join time: key, name, media counts
    and the top engagement stats — enough to tell a thin trend from a strong one in run.log.

    The counts are the POST-DEDUPE ones (FR-155's event-shape amendment). Until 2026-08-11 this
    line reported `len(clips)`/`len(panels)` — what Virlo shipped, not what the pipeline read —
    and a real three-monitor run therefore over-reported its material by 11 rows. The raw figures
    are kept beside them as `videos_raw`/`slideshows_raw` so the drop is measurable rather than
    merely corrected.
    """
    if log is None:
        return
    newest = item.newest_published_at.date().isoformat() if item.newest_published_at else "-"
    likes = int(item.engagement.get("likes", 0))
    log.event("virlo_payload",
              f"{item.name}: after dedup {tally.videos_kept} videos, {tally.slideshows_kept} "
              f"slideshows, {item.total_views:,} views, {likes:,} likes, newest {newest}",
              trend=item.history_key, name=item.name,
              videos=tally.videos_kept, slideshows=tally.slideshows_kept,
              videos_raw=tally.videos_raw, slideshows_raw=tally.slideshows_raw,
              duplicates_dropped=tally.duplicates_dropped,
              total_available=tally.total_available,
              views=item.total_views, likes=likes, newest_published=newest)


async def _digest(pool: SessionPool,
                  log: LogWriter | None) -> tuple[str, dict[str, float], list[list[Any]]]:
    """Cross-monitor context, any confidence values the daily digest carries, and its exemplars.

    THE ONLY METERED VIRLO CALL ($0.25/run, RESULTS.md §A). It creates no trend items (20 §3) and
    its failure is never fatal — the run simply carries no cross-monitor context.

    The third return is what makes the $0.25 defensible (A18). Each digest trend ships up to five
    `top_exemplars` — real posts with thumbnails — which this adapter discarded for the tool's whole
    history while a spike flagged them as *"present and unclaimed"*. They come back grouped per
    digest trend, one list per trend, ready to be offered as the LAST-RESORT reference tier: these
    posts are global, not this niche's, so they must never outrank a monitor's own material.
    """
    try:
        async with pool.acquire() as session:
            payload = await _call(session, "get_trends")
    except (MCPClientError, MCPError, VirloToolError, ValueError) as exc:
        _warn(log, "virlo_digest_failed", f"trend digest unavailable: {exc}", error=type(exc).__name__)
        return "", {}, []
    rows = [row for group in payload.get("groups") or [] for row in group.get("trends") or []]
    rows.sort(key=lambda row: _num(row.get("ranking")) or 10_000)
    lines, confidences, exemplars = [], {}, []
    for row in rows[:_DIGEST_ROWS]:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        parts = [f"#{row['ranking']} {name}" if row.get("ranking") else name]
        parts += [str(row["momentum_status"])] if row.get("momentum_status") else []
        parts += [f"{int(_num(row['views_per_hour'])):,}/h"] if row.get("views_per_hour") else []
        lines.append(" ".join(parts))
        if row.get("confidence") is not None:
            confidences[slugify(name, 0)] = float(_num(row["confidence"]))
        posts = [post for post in row.get("top_exemplars") or []
                 if isinstance(post, Mapping) and str(post.get("thumbnail_url") or "").strip()]
        if posts:
            exemplars.append(_ranked(posts))
    return (("Global trend digest today: " + "; ".join(lines) if lines else ""),
            confidences, exemplars)


async def _call(session: Session, tool: str, args: dict[str, Any] | None = None) -> Mapping[str, Any]:
    """One tool call, its wire error translated into the typed class callers branch on (FR-119)."""
    try:
        payload = await session.call_tool(tool, args or {})
    except MCPError as exc:
        raise translate(exc) from exc
    if isinstance(payload, str):
        with suppress(ValueError):
            payload = json.loads(payload)
    if isinstance(payload, Mapping) and set(payload) == {"result"}:
        payload = payload["result"]
    return payload if isinstance(payload, Mapping) else {}


# --------------------------------------------------------------------------- normalization

def _build_item(monitor_id: str, analysis: Mapping[str, Any], videos: list[Any], shows: list[Any],
                cfg: Config, *, used: Collection[str] = frozenset(),
                log: LogWriter | None = None, counters: Counters | None = None) -> TrendItem:
    """Assemble one normalized trend item from this monitor's three tool returns (20 §3).

    One `ReferenceSet` is chosen here — the freshest unused candidate (FR-7) — and every field the
    creative is shaped by is read off THAT set, so a second run against the same monitor changes
    the headline, the panel rhythm and the layout, not only three CDN urls.

    `counters` is the caller's tally (FR-155); omitted, a scratch one absorbs the numbers and is
    discarded, so every direct caller keeps working and nothing branches on whether it was passed.
    """
    tally = counters if counters is not None else Counters()
    raw_videos, raw_shows = len(videos), len(shows)
    videos, shows = _dedupe(videos), _dedupe(shows)  # RESULTS.md §A: the live arrays repeat posts
    tally.add_input(videos_raw=raw_videos, slideshows_raw=raw_shows,
                    videos_kept=len(videos), slideshows_kept=len(shows))
    name = str(analysis.get("name") or "").strip() or f"monitor {monitor_id}"
    # Read across the call rather than off the tally's totals: the tally may be a run-wide object
    # when a caller passes one, and "this trend fell back to the loose group" is a fact about THIS
    # trend's candidates, never about the run's.
    qualified_before, loose_before = tally.sets_qualified, tally.last_resort_sets
    candidates = _reference_groups(videos, shows, cfg, monitor_id, counters=tally)
    last_resort = (tally.sets_qualified == qualified_before
                   and tally.last_resort_sets > loose_before)
    chosen, ordered, fresh = _pick_set(candidates, used)
    media = [*videos, *shows]
    # `media` concatenates two independently sorted lists, so array order is video-then-slideshow,
    # not best-first. The few-shot lists that claim to be the trend's WINNERS are selected off this
    # merged view instead, so a 5M-view slideshow is not crowded out by a video-heavy monitor.
    ranked = _ranked(media)
    views = [_num(entry.get("views")) for entry in media]
    motion = _pick_motion([(row, _post_id(row, monitor_id, index))
                           for index, row in enumerate(videos, start=len(shows))], chosen, used)
    why, tactics, context, confidence = _analysis_fields(analysis)
    item = TrendItem(
        history_key=str(monitor_id) or slugify(name, 0),  # agent id, else the name slug (20 §3)
        monitor_id=str(monitor_id),
        name=name,
        confidence=confidence,  # FR-5 v1.6.4: mean of the consumed themes' confidence
        why_it_works=why,
        tactics=tactics,
        cross_monitor_context=context,  # `fetch` prefixes the global digest onto this
        hook_texts=_texts(media, "hook_text"),
        text_overlay_contents=_texts(videos, "text_overlay_content"),
        panel_texts=list(chosen.panel_texts),
        narrative_arc=chosen.narrative_arc,
        text_density=chosen.text_density,
        video_descriptions=_texts(media, "description"),
        # Virlo's OWN classification of the winning posts (A13). FR-100 asks the copywriter to
        # derive a hook pattern in prose that the source already labels — `story_tease`,
        # `tutorial_promise`, `text_hook` — so these replace guesswork with the source's own
        # vocabulary. Read per row and absent-safe: the agent-level `data_intelligence_enabled`
        # flag gates NEW enrichment only, and a monitor reporting `false` still carries populated
        # `intelligence` on rows enriched earlier (34/50 measured on exactly such a monitor).
        hook_types=_labels(ranked, "hook_type"),
        visual_hook_types=_labels(ranked, "visual_hook_type"),  # videos only; slideshows omit it
        emotional_tones=_labels(ranked, "emotional_tone"),
        hashtags=_tags(ranked),  # A14 — reference material for the copy call, never a mandate
        reference_groups=[list(candidate.urls) for candidate in ordered],  # group 0 = the chosen set
        is_slideshow=chosen.is_slideshow,  # drives FR-90's carousel affinity
        text_only=not ordered,  # provisional: a dead CDN URL can still empty this (FR-247)
        winning_video_url=str(motion[0]["url"]) if motion else None,
        winning_video_post_id=motion[1] if motion else None,
        # FR-7 is already enforced when this is non-empty; empty means the monitor-level window
        # decides (a `text_only` item, or a monitor whose every candidate set is used up).
        chosen_post_ids=chosen.post_ids if fresh else (),
        virlo_url=chosen.source_url or (str(motion[0]["url"]) if motion else None),
        total_views=int(sum(views)),
        median_views=int(statistics.median(views)) if views else 0,
        newest_published_at=max((when for when in map(_when, media) if when), default=None),
        engagement={key: int(sum(_num(entry.get(key)) for entry in media))
                    for key in ("likes", "shares", "comments", "bookmarks")},
    )
    # Raw component values are STAGED here and replaced by their normalized 0-1 values in `_score`
    # (min-max needs the whole pool); what reaches the log is the normalized set (FR-5).
    item.strength_components = {"total_views": float(item.total_views),
                                "median_views": float(item.median_views),
                                "velocity": _velocity(media)}
    tally.add_choice(fresh=fresh, has_set=bool(ordered), last_resort=last_resort,
                     motion_tier=motion[2] if motion else "none")
    if log is not None:  # FR-7/FR-24: a repeat, of a set or of a motion source, stays explainable
        # `fresh_count`/`stale_count`/`rejection_reasons` are FR-155's amendment to this event:
        # "repeat" alone never said whether one candidate was stale or thirty were, nor which
        # screen turned the others away — both are what an operator asking "why does today look
        # like yesterday" actually needs.
        fresh_sets = sum(1 for candidate in ordered
                         if not any(post in used for post in candidate.post_ids))
        log.event("reference_choice",
                  f"{name}: {'fresh' if fresh else 'repeat'} set of {len(ordered)} candidate(s), "
                  f"motion {motion[2] if motion else 'none'}",
                  trend=item.history_key, candidate_sets=len(ordered), set_fresh=fresh,
                  fresh_count=fresh_sets, stale_count=len(ordered) - fresh_sets,
                  rejection_reasons=dict(tally.rejection_reasons),
                  last_resort_set=last_resort,
                  post_ids=list(item.chosen_post_ids), motion_post=item.winning_video_post_id,
                  motion_tier=motion[2] if motion else "none")
    return item


def _reference_groups(videos: list[Any], shows: list[Any], cfg: Config, monitor_id: str,
                      *, counters: Counters | None = None) -> list[ReferenceSet]:
    """FR-91's coherent-set builder: EVERY qualifying candidate as a `ReferenceSet`, best first.

    Panels lead thumbnails; a slideshow qualifies only at `_MIN_PANELS`+ (RESULTS.md §A); a creator
    family needs `_MIN_THUMBS`+ once face-dominant frames are dropped, and UI-dense/complex frames
    sink inside it. `reference_images_per_job` caps ONE set. `media_download_cap` is deliberately
    NOT applied here: it bounds downloads, and gating candidates on it left exactly two sets per
    monitor where a live monitor qualifies ~36 (spikes/RESULTS.md:163) — FR-7 chooses among all.

    Every row this screen turns away is counted on `counters` (FR-155/NFR-5). Two of the three
    reasons — the `_MIN_PANELS` and `_MIN_THUMBS` rejections — were silent until 2026-08-11, which
    is why a live run could discard 41 of 148 candidate sources and report nothing at all.
    """
    tally = counters if counters is not None else Counters()
    per_job = max(1, cfg.sources.reference_images_per_job)
    ranked: list[tuple[int, float, float, ReferenceSet]] = []
    for index, show in enumerate(shows):
        panels = [url for url in show.get("image_urls") or [] if isinstance(url, str) and url]
        if len(panels) >= _MIN_PANELS:  # the wrapper already sorted them by `position`
            tally.slideshow_sets += 1
            ranked.append((2, 1.0, _num(show.get("views")),
                           _set(panels[:per_job], [(show, _post_id(show, monitor_id, index))], True)))
        else:
            tally.slideshows_thin += 1
            tally.reject("slideshow_under_min_panels")

    families: dict[str, list[tuple[Any, str]]] = {}
    for index, video in enumerate(videos, start=len(shows)):
        if isinstance(video.get("thumbnail_url"), str) and video["thumbnail_url"]:
            families.setdefault(str(video.get("author_username") or video.get("id")), []).append(
                (video, _post_id(video, monitor_id, index)))
        else:
            tally.videos_without_thumbnail += 1
            tally.reject("video_without_thumbnail")
    for family in families.values():
        order = sorted(family, key=lambda p: (_frame_quality(p[0]), _num(p[0].get("views"))),
                       reverse=True)
        picked = ([p for p in order if p[0].get("has_face_visible") is not True] or order)[:per_job]
        if len(picked) >= _MIN_THUMBS:
            tally.frame_sets += 1
            tally.videos_in_sets += len(family)
            ranked.append((1, sum(_frame_quality(row) for row, _ in picked) / len(picked),
                           _num(picked[0][0].get("views")),
                           _set([row["thumbnail_url"] for row, _ in picked], picked, False)))
        else:
            tally.families_thin += 1
            tally.videos_in_thin_families += len(family)
            tally.reject("frame_family_under_min_thumbs")

    if not ranked:  # last resort: any image at all beats a text_only trend (FR-6/FR-90)
        loose = [(row["thumbnail_url"], (row, _post_id(row, monitor_id, index)))
                 for index, row in enumerate(videos, start=len(shows))
                 if isinstance(row.get("thumbnail_url"), str) and row["thumbnail_url"]]
        loose += [(url, (show, _post_id(show, monitor_id, index)))
                  for index, show in enumerate(shows)
                  for url in show.get("image_urls") or [] if isinstance(url, str) and url]
        if loose:
            tally.last_resort_sets += 1
            ranked.append((0, 0.0, 0.0, _set([url for url, _ in loose[:per_job]],
                                             [row for _, row in loose[:per_job]], False)))
    return [candidate for *_key, candidate in sorted(ranked, key=lambda row: row[:3], reverse=True)]


def _offer_digest_exemplars(items: list[TrendItem], exemplars: Sequence[Sequence[Any]],
                            cfg: Config) -> frozenset[str]:
    """A18's LAST-RESORT reference tier — the metered digest's own exemplar posts, offered BELOW
    every monitor-sourced candidate and only to the items that ran short. Returns the urls actually
    attached, for the log.

    Four properties make this safe to offer at all, and each is structural rather than advisory:

    - **Below everything.** These groups are APPENDED, after `_reference_groups` ranked the
      monitor's own candidates and `_pick_set` already chose among them, so a digest exemplar can
      neither become the chosen set of a trend that had one nor displace a monitor-sourced group.
    - **Only where the monitor came up short.** An item whose own sets already fill
      `media_download_cap` is offered nothing: it has enough material of its own for FR-91's
      rotation to vary, and cross-niche pictures would be a fidelity cost buying nothing. The
      threshold is the download cap because that is the number of images a trend can actually use.
    - **Never a slideshow.** An exemplar carries ONE still, exactly like a video thumbnail, so a
      set of them is a `_MIN_THUMBS` frame family and nothing here touches `is_slideshow`. A single
      still must not masquerade as a panel set: that would hand FR-90 a carousel affinity nobody
      earned, and the deck would be invented rather than mimicked.
    - **Appended, not merged.** One group per digest trend, so a set is still ONE subject (FR-91)
      even though it is not one creator.

    They remain GLOBAL rather than niche-filtered, which is a real fidelity risk and the reason for
    both the tier's position and `_log_digest_exemplars` naming every trend that could attach one.

    ⚠️ The eligibility test is made explicitly here rather than left to the download budget, which
    *looks* like it would ration these groups away on its own and does not: `_CACHE` is shared
    across items, so one bare trend fetching an exemplar leaves it cached, and every other trend's
    copy of that same group then survives `_download_references`' liveness prune untouched.

    Why here and not inside `_reference_groups`: `fetch` runs the digest CONCURRENTLY with the
    monitors (it is a separate job in the same `gather`), so at the moment an item's candidates are
    built the digest has usually not answered yet. Waiting for it would serialize the one metered
    call in front of every free one.
    """
    per_job = max(1, cfg.sources.reference_images_per_job)
    cap = max(1, cfg.sources.media_download_cap)
    groups = []
    for posts in exemplars:
        urls = list(dict.fromkeys(
            str(post["thumbnail_url"]).strip() for post in posts
            if isinstance(post, Mapping) and str(post.get("thumbnail_url") or "").strip()))
        if len(urls) >= _MIN_THUMBS:  # one still per post, so this is the frame-family rule
            groups.append(urls[:per_job])
    short = [item for item in items
             if sum(len(group) for group in item.reference_groups) < cap]
    if not groups or not short:
        return frozenset()
    for item in short:
        item.reference_groups.extend([list(group) for group in groups])
    return frozenset(url for group in groups for url in group)


def _log_digest_exemplars(items: Sequence[TrendItem], offered: Collection[str],
                          log: LogWriter | None) -> None:
    """Name every trend whose SURVIVING reference groups include a digest exemplar (A18).

    Written after the download pass on purpose: it reports what a render job can actually attach,
    not what was offered — a group whose urls never fit the download budget has already been pruned
    by then. `reference_source=digest_exemplar` is the whole point of the line: this material is
    cross-niche, so a creative that looks off-topic must be traceable to this tier afterwards
    without re-running anything.
    """
    if log is None or not offered:
        return
    for item in items:
        groups = [index for index, group in enumerate(item.reference_groups)
                  if group and all(url in offered for url in group)]
        if groups:
            log.event("digest_exemplar_attached",
                      f"{item.name}: {len(groups)} last-resort reference set(s) from the global "
                      "digest — cross-niche material, ranked below every monitor-sourced set",
                      trend=item.history_key, reference_source="digest_exemplar",
                      groups=groups, sets=len(groups))


def _set(urls: list[str], rows: Sequence[tuple[Any, str]], is_slideshow: bool) -> ReferenceSet:
    """One candidate built as a UNIT — urls, the posts behind them, and everything the creative
    derives from choosing it. `rows` are `(row, post_id)` pairs; the FIRST row is the set's own
    source, so a slideshow's panel metadata and a family's leading thumbnail agree by construction
    instead of by a hand-kept index alignment.
    """
    lead: Mapping[str, Any] = rows[0][0] if rows else {}
    return ReferenceSet(
        urls=[str(url) for url in urls],
        post_ids=tuple(dict.fromkeys(post for _, post in rows)),
        is_slideshow=is_slideshow,
        panel_texts=[str(text) for text in lead.get("panel_texts") or []],
        narrative_arc=str(lead.get("narrative_arc") or ""),
        text_density=str(lead.get("text_density") or ""),
        source_url=str(lead.get("url") or "") or None,
        author=str(lead.get("author_username") or "") or None)


def _post_id(row: Mapping[str, Any], monitor_id: str, index: int) -> str:
    """This post's identity for FR-7's window: Virlo's own stable `id` (20 §3), else its url, else
    its monitor-scoped position — `index` runs across slideshows THEN videos, so the two arrays
    cannot collide. NEVER `id(row)`: `_dedupe`'s memory-address fallback differs on every run and
    would silently turn freshness off while reporting success.
    """
    return str(row.get("id") or row.get("url") or f"{monitor_id}:{index}")


def _pick_set(sets: list[ReferenceSet],
              used: Collection[str]) -> tuple[ReferenceSet, list[ReferenceSet], bool]:
    """FR-7's choice: the freshest unused candidate, then the other fresh ones, then the used ones.

    `sets` arrives strongest-first, so "freshest unused" is the strongest candidate none of whose
    posts appear in the history window — deterministic on identical input. Returns that set (an
    empty `ReferenceSet` when the monitor offered no candidate at all, so callers branch on nothing),
    the candidate list reordered so the chosen set is group 0 and top-ups prefer fresh material, and
    whether the choice was actually fresh. When every candidate is used the strongest is still chosen
    — an image-less trend is worse than a repeated one — but reported stale, so `chosen_post_ids`
    stays empty and the monitor-level window decides the exclusion.
    """
    fresh, stale = [], []
    for candidate in sets:
        (stale if any(post in used for post in candidate.post_ids) else fresh).append(candidate)
    ordered = fresh + stale
    return (ordered[0] if ordered else ReferenceSet()), ordered, bool(fresh)


def _pick_motion(videos: Sequence[tuple[Any, str]], chosen: ReferenceSet,
                 used: Collection[str]) -> tuple[Mapping[str, Any], str, str] | None:
    """The reel's motion reference (FR-24) as `(row, post_id, tier)`, in three tiers of preference:

    1. `fresh_same_creator` — an unused video by the chosen set's own creator: fresh AND topically
       coherent, so a slideshow's copy is not animated by a stranger's clip;
    2. `fresh` — else the highest-viewed unused video;
    3. `repeat` — else the highest-viewed video regardless, logged as a repeat.

    **Tier 3 is the point.** Freshness must never cost a reel: a repeated motion source is a
    cosmetic loss, a failed reel is a paid one ($4.78 measured). This returns None only when no
    video carries a url at all — never because everything has been used.
    """
    ranked = sorted((pair for pair in videos if pair[0].get("url")),
                    key=lambda pair: _num(pair[0].get("views")), reverse=True)
    fresh = [pair for pair in ranked if pair[1] not in used]
    handle = chosen.author or ""
    same = [pair for pair in fresh
            if handle and str(pair[0].get("author_username") or "") == handle]
    for tier, pool in (("fresh_same_creator", same), ("fresh", fresh), ("repeat", ranked)):
        if pool:
            return pool[0][0], pool[0][1], tier
    return None


def _analysis_fields(analysis: Mapping[str, Any]) -> tuple[str, list[str], str, float | None]:
    """`why_it_works`, tactics, this monitor's own context and its confidence, from `analysis_data`.

    RESULTS.md §A puts all four on the monitor, not on the digest 20 §3 credits — so this is where
    FR-9/FR-14's tactics and timing inputs come from, and (FR-5 v1.6.4) where the 0.20 confidence
    component is sourced: the MEAN over the consumed themes, since the digest's `global_confidence`
    is null on every live trend. Absent-safe, and bounded: these reach prompts.
    """
    themes = analysis.get("themes") or []
    consumed = themes[:_MAX_THEMES]
    scored = [float(t["confidence"]) for t in consumed
              if isinstance(t.get("confidence"), (int, float)) and not isinstance(t["confidence"], bool)]
    why = " · ".join(part for part in [
        str(analysis.get("why_it_works") or "").strip(),
        *(f"{t.get('name')}: {t['why_it_works']}" for t in consumed if t.get("why_it_works")),
    ] if part)[:_WHY_MAX_CHARS]
    tactics: list[str] = []
    for value in [t for theme in themes for t in theme.get("tactics") or []] + list(
            analysis.get("viral_tactics") or []):
        text = str(value).strip()
        if text and text not in tactics:
            tactics.append(text)
    parts = [f"Timing: {analysis['timing_pattern']}"] if analysis.get("timing_pattern") else []
    if analysis.get("peak_hours"):
        parts.append("Peak hours: " + ", ".join(str(hour) for hour in analysis["peak_hours"][:6]))
    parts += [f"{label}: {analysis[key]}" for key, label in
              (("connecting_thread", "Connecting thread"), ("key_highlight", "Key highlight"))
              if analysis.get(key)]
    return (why, tactics[:_MAX_TACTICS], " · ".join(parts)[:_CONTEXT_MAX_CHARS],
            statistics.fmean(scored) if scored else None)


def _frame_quality(video: Mapping[str, Any]) -> float:
    """FR-91's frame screen: a dominant face is the heavy penalty (portrait pull + moderation
    risk), on-screen text and visual complexity the lighter ones (platform UI gets copied)."""
    quality = _COMPLEXITY.get(str(video.get("visual_complexity") or "").lower(), 0.5)
    quality -= 2.0 if video.get("has_face_visible") is True else 0.0
    return quality - (0.5 if video.get("has_text_overlay") is True else 0.0)


def _dedupe(rows: list[Any]) -> list[Any]:
    """Drop repeated posts, keyed by id then url (RESULTS.md §A saw live duplicates)."""
    seen: set[str] = set()
    kept = []
    for row in rows:
        key = str(row.get("id") or row.get("url") or id(row)) if isinstance(row, Mapping) else ""
        if key and key not in seen:
            seen.add(key)
            kept.append(row)
    return kept


def _texts(rows: list[Any], key: str) -> list[str]:
    """Deduped, non-empty values of one optional field, capped at the few-shot budget."""
    out: list[str] = []
    for row in rows:
        value = str(row.get(key) or "").strip()
        if value and value not in out:
            out.append(value)
    return out[:_MAX_EXEMPLARS]


def _ranked(rows: Sequence[Any]) -> list[Any]:
    """The same rows, highest-viewed first — the order every "winning posts" list should read in.

    Virlo returns each media call sorted, but `[*videos, *shows]` glues two sorted lists together,
    so position in that merged list says nothing about strength. Stable: rows with equal views keep
    Virlo's own order.
    """
    return sorted(rows, key=lambda row: _num(row.get("views")) if isinstance(row, Mapping) else 0.0,
                  reverse=True)


def _labels(rows: list[Any], key: str) -> list[str]:
    """One `intelligence` classification field across the winners, deduped and capped (A13).

    Rows arrive view-ranked, so the strongest post's label leads. `_NON_LABELS` values are dropped
    BEFORE the cap, not after — Virlo writes a literal `"none"` on rows it could not classify, and
    letting those consume cap slots would hide real labels behind three spellings of nothing.
    """
    return _texts([row for row in rows if isinstance(row, Mapping)
                   and str(row.get(key) or "").strip().lower() not in _NON_LABELS], key)


def _tags(rows: list[Any]) -> list[str]:
    """The winning posts' real hashtags, view-ranked, deduped case-insensitively and capped (A14).

    Virlo spells them BOTH ways inside a single response — `"#ai"` on one row, `"ai"` on the next
    — so every tag is normalized to one leading `#` before the dedupe, or the same tag lands twice.
    `_MAX_HASHTAGS_PER_POST` keeps one tag-spraying post from filling the whole list.
    """
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        taken = 0
        for raw in row.get("hashtags") or []:
            tag = "#" + str(raw).strip().lstrip("#").strip()
            if len(tag) < 2 or tag.lower() in seen:
                continue
            seen.add(tag.lower())
            out.append(tag)
            taken += 1
            if taken >= _MAX_HASHTAGS_PER_POST:
                break
    return out[:_MAX_HASHTAGS]


def _when(row: Mapping[str, Any]) -> datetime | None:
    """`publish_date` as an aware UTC datetime; unparseable or absent is None."""
    with suppress(ValueError):
        parsed = datetime.fromisoformat(str(row.get("publish_date") or "").replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _velocity(media: list[Any]) -> float:
    """FR-5's momentum signal: views relative to how recently the posts published."""
    now = datetime.now(timezone.utc)
    ages = ((_num(row.get("views")), _when(row)) for row in media)
    return sum(views / (max(0.0, (now - when).total_seconds() / 86400.0) + 1.0 if when else 31.0)
               for views, when in ages)


def _match_confidence(name: str, confidences: Mapping[str, float]) -> float | None:
    """Virlo's own confidence for this theme when the digest named it (usually null — §A)."""
    slug = slugify(name, 0)
    return next((value for other, value in confidences.items()
                 if other and (other in slug or slug in other)), None)


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


# --------------------------------------------------------------------------- ranking (FR-5)

def _score(items: list[TrendItem]) -> None:
    """Strength in place: min-max each component across the run's candidate pool, then weight.

    Weights are renormalized over the components that actually exist, so a missing confidence
    (RESULTS.md §A: `global_confidence` is null for every live trend) drags nobody toward zero —
    it just leaves 0.20 of weight to be shared by the components that arrived.
    """
    if not items:
        return
    for item in items:
        if item.confidence is not None:
            item.strength_components["confidence"] = float(item.confidence)
    columns = {name: _minmax([item.strength_components.get(name) for item in items])
               for name in _WEIGHTS if any(name in item.strength_components for item in items)}
    for index, item in enumerate(items):
        parts = {name: column[index] for name, column in columns.items()
                 if name in item.strength_components}
        weight = sum(_WEIGHTS[name] for name in parts) or 1.0
        item.strength = round(sum(_WEIGHTS[n] * v for n, v in parts.items()) / weight, 4)
        item.strength_components = {name: round(value, 4) for name, value in parts.items()}


def _minmax(values: list[float | None]) -> list[float]:
    """0-1 within the pool; an absent value stays 0 and a tied pool scores 1 (0 when all-zero)."""
    present = [value for value in values if value is not None]
    low, high = (min(present), max(present)) if present else (0.0, 0.0)
    if high - low <= 0:
        return [0.0 if value is None else (1.0 if high > 0 else 0.0) for value in values]
    return [0.0 if value is None else (value - low) / (high - low) for value in values]


# --------------------------------------------------------------------------- CDN downloads

async def _download_references(items: list[TrendItem], cfg: Config, cache_dir: Path | None,
                               log: LogWriter | None,
                               *, counters: Counters | None = None) -> None:
    """Fetch the chosen set first, top up to `media_download_cap`, then prune what died.

    The chosen set (group 0, FR-7) is downloaded whole so the render job's own set is never the
    part that got rationed; the remaining candidates — fresh ones first, since `_pick_set` ordered
    them that way — top the trend up to `media_download_cap`, which is what keeps the analysis call
    at FR-9's six images. One dead image removes itself and nothing else (FR-32/33/247); a group
    that ends up short still ships and the shortfall is logged; a trend left with zero images
    becomes `text_only` (FR-6/FR-90).
    """
    tally = counters if counters is not None else Counters()
    cap = max(1, cfg.sources.media_download_cap)
    tally.download_cap = max(tally.download_cap, cap)
    queued: list[str] = []
    for item in items:
        budget = cap
        for group in item.reference_groups:  # group 0 is the chosen set and is never trimmed here
            queued += group[:max(0, budget)]
            budget -= len(group)
    wanted = [url for url in dict.fromkeys(queued) if url not in _CACHE]
    if wanted:
        target, limiter = _cache_dir(cache_dir), asyncio.Semaphore(_MAX_PARALLEL)
        attempts = max(1, cfg.models.http_max_attempts)

        async def one(url: str) -> tuple[str, Path | None]:
            async with limiter:
                return url, await _download(client, url, target, attempts, log)

        async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_S, follow_redirects=True) as client:
            for url, path in await asyncio.gather(*(one(url) for url in wanted)):
                if path is not None:
                    _CACHE[url] = path

    # FR-155: attempted vs downloaded, measured on the same list the pass actually worked from,
    # so "0 dead URL" is a measurement and never an assumption. Anything already in `_CACHE` was
    # fetched by an earlier item this run and is not attempted twice.
    tally.add_downloads(attempted=len(wanted),
                        downloaded=sum(1 for url in wanted if url in _CACHE))
    per_job = max(1, cfg.sources.reference_images_per_job)
    for item in items:
        alive = [[url for url in group if url in _CACHE] for group in item.reference_groups]
        chosen = alive[0] if alive else []  # the CHOSEN set, judged before the empties are dropped
        item.reference_groups = [group for group in alive if group]
        item.text_only = not item.reference_groups
        if not chosen:  # its urls all died, so none of its posts was attached to anything
            item.chosen_post_ids = ()
        judged = chosen or (item.reference_groups[0] if item.reference_groups else [])
        if item.text_only:
            tally.trends_text_only += 1
            _warn(log, "trend_text_only", f"{item.name}: no usable reference image — last-resort "
                  "trend (FR-6/90)", trend=item.history_key)
        elif len(judged) < per_job:
            tally.trends_short += 1
            _warn(log, "reference_shortfall", f"{item.name}: {len(judged)} of {per_job} references "
                  "survived — the job proceeds with fewer (FR-247)", trend=item.history_key)


async def _download(client: httpx.AsyncClient, url: str, target: Path, attempts: int,
                    log: LogWriter | None) -> Path | None:
    """One reference image, bounded by `http_max_attempts`; None means "drop this image only"."""
    suffix = Path(url.split("?", 1)[0]).suffix.lower()
    path = target / f"{hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]}{suffix if suffix in _SUFFIXES else '.img'}"
    if path.exists():
        return path
    reason = "no attempt completed"
    for attempt in range(1, attempts + 1):
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            reason = type(exc).__name__
            if getattr(getattr(exc, "response", None), "status_code", None) in (401, 403, 404, 410):
                break  # a retry cannot fix a dead or forbidden URL
        else:
            if response.content:
                path.write_bytes(response.content)
                return path
            reason = "zero-byte body"
        if attempt < attempts:
            await asyncio.sleep(_BACKOFF_S * 2 ** (attempt - 1))
    _warn(log, "reference_image_dropped", f"reference image dropped ({reason})", url=url, reason=reason)
    return None


def _cache_dir(requested: Path | None) -> Path:
    """Where downloads land: the caller's folder when it names one, else a private temp dir."""
    global _CACHE_DIR, _CACHE_DIR_OWNED
    if requested is not None:
        _CACHE_DIR, _CACHE_DIR_OWNED = Path(requested), False
    elif _CACHE_DIR is None:
        _CACHE_DIR, _CACHE_DIR_OWNED = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX)), True
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def _warn(log: LogWriter | None, event: str, message: str, *,
          say: Callable[[str], None] | None = None, **data: Any) -> None:
    """One degrade line: to the console logger, to both run logs when a run owns one, and — when
    the caller passed the console seam — to the operator's screen, because a misconfiguration they
    must fix is worth nothing buried in run.log."""
    logger.warning("%s", message)
    if say is not None:
        say(message)
    if log is not None:
        log.warn(event, message, **data)
