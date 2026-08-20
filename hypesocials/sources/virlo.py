"""Virlo adapter — MCP tool calls in, ranked TEXT-ONLY topic items out (v2.0.0, FR-293).

Callers import `hypesocials.sources`, never this module. Behind that facade:

- **Join rule (20 §3 / FR-293):** one configured monitor becomes up to
  `sources.virlo_topics_per_monitor` TOPICS, one per theme. `get_monitor_analysis` gives the
  monitor's name, `why_it_works`, timing, connecting thread and its `themes[]`;
  `get_top_slideshows` (and `get_top_videos` only when `sources.include_videos` says so) gives the
  posts for that same monitor, asked for as `created_at desc` over pages `1..sources.fetch_pages`
  so the answer is THIS WEEK's collection rounds; the global `get_trends` digest enriches
  `cross_monitor_context` and still creates no items. §A of spikes/RESULTS.md swaps the PRD
  table's digest vs monitor-analysis ownership — shapes follow RESULTS.md, behaviour follows
  the PRD.
- **Window before rank (FR-301/FR-305, v2.1.0).** "Top" is now measured INSIDE a window instead of
  over all time. The ask is recency-ordered, and one gate pass then drops what the window and the
  history exclude — stale rows, unenriched slideshows, posts already quoted — before the survivors
  are ranked by views. The first paid run proved why: a `views desc` page of the live monitor spans
  2023-11 to 2026-07 and contains ZERO of the posts the Virlo UI shows for the current week, so the
  tool quoted three-year-old captions while reporting success (D46 §1).
- **A topic owns its posts (FR-293).** The monitor's deduped rows are dealt out EXCLUSIVELY: a
  theme's own `evidence_video_ids` first, then a stride deal of the remainder, so no post belongs
  to two topics of one monitor. That exclusivity is the whole point — it is what makes two topics
  from one monitor carry different post sets, different engagement and therefore different
  strengths, instead of nine copies of one monitor-wide number.
- **Text is the product (D42/FR-100/FR-293).** Every string a `SourcePost` carries is stored
  exactly as Virlo returned it — never translated, never retyped, never trimmed — because the copy
  call selects these strings BY REFERENCE and the engine resolves the reference back to these
  bytes (10 §FR-99/FR-100). A string edited on the way in can no longer be quoted verbatim on the
  way out. `panel_texts` additionally keeps its POSITIONS (§0.14a): slot *i* is source slide *i*,
  empty slots padded rather than closed, because FR-304 renders our slide *i* from that slot. No
  media travels HERE: this adapter passes slide URLs on as data (`SourcePost.image_urls`) for the
  analysis-only slide-intelligence tier (FR-306) and downloads nothing itself. The visual
  authority is the local meta-style registry (FR-290), not Virlo's pixels, and no Virlo URL or
  byte may reach a render payload (D41 carve-out).
- **Strength (FR-5, amended v2.0.0):** total views .35, median views .15, velocity .30,
  engagement .20 — each computed from the TOPIC's own posts, then min-max normalized across the
  run's FULL topic pool (every monitor's topics together) before weighting. Hardcoded weights, by
  PRD decision.
- **Funnel accountability (FR-155):** every stage above tallies into ONE run-wide `Counters` —
  rows in, duplicates dropped, the three eligibility drops, posts in and topics out, the Select
  verdict, the filter verdict — emitted once as the `collect_funnel` event and printed by the
  runner. A loss that is not counted here is invisible to the operator, which is the NFR-5 failure
  that object exists to close. The drop lines' WORDING lives here too (`Counters.drop_rows`), so
  the counter and the sentence that reports it cannot drift apart.
- **Forensics (FR-298):** `topic_posts` names EVERY post of every topic in rank order (the "which
  posts exactly" answer), `virlo_fields` is the per-monitor consumption ledger (which fields
  arrived, which were read, which were ignored), and `topic_ranked` carries the ranking table's
  rows with their RAW pre-normalization components beside the normalized ones.

Invariants: no direct `api.virlo.ai` call (NFR-11); no retry on top of the wrapper's bounded retry
(FR-120); the digest is the ONLY metered call ($0.25, §A), so `include_digest=False` keeps a
preview at $0; `intelligence.*` is optional (~70% miss on unenriched rows) and a topic stays usable
without it; `_themes()` never yields fewer items than the pre-pivot adapter did — a monitor with no
themes synthesizes exactly one topic from its aggregate, which is the pre-pivot item shape.

**The media funnel is GONE** (Wave 3.5, plan §3.5 — D41): the reference-set builder, motion
picker, digest-exemplar tier, CDN download pass and their counters were excised once nothing
reached them. This adapter reads text, splits it into topics, and ranks — nothing else.

Do not: rank or filter for Select (it owns verdicts); mutate `models.py`; log an API key.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import statistics
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from hypesocials.config import Config
from hypesocials.mcp_client import MCPClientError, MCPError, ServerConfig, Session, SessionPool
from hypesocials.models import SourcePost, TrendItem
from hypesocials.util import slugify
from hypesocials.virlo_mcp import VirloToolError, translate

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hypesocials.outputs import LogWriter

logger = logging.getLogger(__name__)

SERVER_NAME = "virlo"
#: The media ask (FR-301, v2.1.0): the newest collection rounds, `sources.fetch_pages` pages deep.
#:
#: `views desc` — what this asked for until D46 — makes "top" mean top OF ALL TIME, and that is
#: precisely the defect the first paid run shipped: on the live monitor a `views desc` page spans
#: 2023-11 to 2026-07-20 and holds 0 of the 100 posts the Virlo UI lists for the current week
#: (measured 2026-08-13), so the tool quoted a three-year-old caption and reported success.
#: `created_at desc` returns the UI grid's own rows — Virlo's newest collection rounds — and views
#: still decide the rank, just AMONG the survivors of the window (`_source_rows`, FR-305).
#:
#: Recency ordering is why this pages and the old ask did not: one page of the strongest rows is
#: self-limiting, one page of the newest rows is a sample of the newest rounds, and the window's
#: material sits behind it. Virlo's maximum page size is 100 and `page` is 1-indexed and
#: `limit`-relative (20 §3). `offset` is NOT sent and cannot be: Virlo answers it with HTTP 400
#: and the wrapper refuses it structurally.
_MEDIA_LIMIT, _MEDIA_ORDER_BY, _MEDIA_SORT = 100, "created_at", "desc"
_MAX_EXEMPLARS = 5  # FR-100 wants 3-5 verbatim source hooks
#: A14 — the winning posts' real hashtags, as reference material for the copy call. Capped per
#: post as well as in total because a single row can carry 39 tags (measured: one motivational
#: post spraying `#mindsetquotes`-style filler), which would fill the whole list from one source
#: and tell the copywriter about that post rather than about the trend.
_MAX_HASHTAGS, _MAX_HASHTAGS_PER_POST = 8, 3
#: A13 — values Virlo writes into a classification field when it classified nothing. They are an
#: absence wearing a label, and passing "hook type: none" to a copywriter is worse than silence.
_NON_LABELS = frozenset({"none", "unknown", "n/a", "null", "other"})
#: How many themes a monitor's aggregate text may quote is no longer a constant: `_MAX_THEMES = 3`
#: capped BOTH the themes consumed and the FR-5 confidence mean's denominator, and post-pivot each
#: consumed theme IS a topic — so the one number that governs is `sources.virlo_topics_per_monitor`
#: (default 9, the depth §A measured; `-1` is the kill switch). `_topic_cap()` resolves it.
_MAX_TACTICS, _WHY_MAX_CHARS, _CONTEXT_MAX_CHARS = 12, 1200, 600
_DIGEST_ROWS = 8
#: The marker `topic_filter.screen()` writes into every `Verdict.reason` when its LLM layer
#: degraded (fail-open, §1.5). `record_filter` reads it rather than importing the filter module.
_FILTER_DEGRADED = "filter_degraded"
#: FR-5's weights — stated in the PRD so the operator signed off on them, never a config knob.
#: v2.0.0 amendment: the 0.20 slot belongs to ENGAGEMENT, not to Virlo's theme `confidence`. The
#: ranked unit is now a topic and each topic is one theme, so confidence stopped being a per-item
#: discriminator (nine topics of one monitor would all carry one number, and RESULTS.md §A found
#: the digest's own `global_confidence` null on every live trend). Engagement is per-post and
#: therefore per-topic, which is exactly what the split needs it to be. `confidence` is still
#: normalized, logged and passed to prompts — it just no longer weighs the rank.
_WEIGHTS = {"total_views": 0.35, "median_views": 0.15, "velocity": 0.30, "engagement": 0.20}
#: `Counters` fields that describe the SHAPE of the ask rather than a quantity of material. They
#: are set once on the run-wide object and must never be summed when a tally is absorbed — three
#: monitors asked for 100 rows each still asked for 100 rows per call, not 300. `pages_asked`
#: joined them with FR-301's paging for the same reason: three monitors asked three pages deep
#: each still asked three pages deep, and `max()` is the fold that says so.
_CARRIED_FIELDS = frozenset({"rows_per_call", "pages_asked"})


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
    monitor-wide figure per topic — the discipline that keeps the split honest now that one
    monitor really does produce nine items. Every quantity is additive; the four fields in
    `_CARRIED_FIELDS` are the ask's shape and are carried, never summed.

    The `sets`, `choice` and `images` groups belong to the withdrawn media funnel (FR-32/33/247)
    and are excised in Wave 3.5; nothing on the live path writes them any more. The groups that
    matter post-pivot are `input` -> `drops` -> `topics` -> `filter` -> Select's verdicts -> the
    render forecast, and every one of them reconciles: rows in minus duplicates minus the three
    FR-305 drops is what the split read (`posts_kept - dropped_ineligible == posts_in`), topics
    out is what the filter judged, and what the filter kept is what Select ranked.

    **Zeros are the point.** The withdrawn media funnel's loss counters (`reference_shortfall`,
    `reference_image_dropped`, `trend_text_only`, `reference_free`) fired in NONE of the archived
    runs, which left an operator unable to tell "nothing was lost" from "the counter is dead" —
    and the live equivalents, FR-305's three drop reasons, will legitimately read zero on a
    healthy weekly run. Every stage is printed unconditionally, so a zero is an answer rather
    than a silence.

    **Input and output vocabulary stay disjoint** (FR-155/NFR-5). INPUT words — video, slideshow,
    post — describe Virlo evidence and appear only on `input`/`topics`. OUTPUT words — image,
    carousel, reel, creative, job, style ref — describe what this tool generates and appear only
    on `render`. A Virlo slideshow is evidence: it gives a topic *carousel affinity* (FR-90) and
    is never itself rendered, so "3 slideshows -> 2 carousels" is a sentence this object cannot
    produce. The media groups (`sets`/`choice`/`images`) died with the reference funnel in the
    pivot's Wave 3.5 — the live chain is input → drops → topics → filter → Select → the style
    forecast.
    """

    # --- the ask (run-wide; a per-monitor tally leaves these at zero and `absorb` carries them)
    monitors_asked: int = 0
    monitors_failed: int = 0
    #: The PAGE SIZE one call asks for, unchanged by FR-301's paging: `rows_per_call` x
    #: `pages_asked` is the ceiling on rows one monitor can contribute per media kind, and the two
    #: numbers are kept apart because the funnel header states the ask's shape rather than its
    #: product ("100 rows/call · 3 page(s)" is checkable against the wrapper's own bounds; "300"
    #: is not, and would read as a limit Virlo refuses).
    rows_per_call: int = 0
    pages_asked: int = 0  # `sources.fetch_pages` — how deep the recency window was asked for
    #: Virlo's own row total for the monitor, read from the FIRST page of each media call and
    #: never re-added per page: every page of one call echoes the same `total`, so summing pages
    #: would multiply the pool by the page count and make the header's "N available" a fiction.
    total_available: int = 0
    #: FR-301's slideshow-first ask: `sources.include_videos: false` means `get_top_videos` is
    #: NEVER CALLED, which a row of video zeros cannot distinguish from a monitor that happens to
    #: have no videos. Latched as a fact about the run so the funnel can say "disabled" in words.
    #: Named for the disabled state, not the enabled one, because `absorb` folds bools by OR and
    #: the honest rollup of "one call skipped videos" is "videos were skipped".
    videos_disabled: bool = False

    # --- input: rows Virlo returned, and the ones `_dedupe` dropped before anything read them
    videos_raw: int = 0
    slideshows_raw: int = 0
    videos_kept: int = 0
    slideshows_kept: int = 0
    #: An explicit field rather than the derived `raw - kept` view it used to be (contracts item
    #: 15): the split makes this number the one honest place to read the dedupe from, and a field
    #: is what `absorb` can fold and what a caller can state directly. `__post_init__` still
    #: derives it for a tally built in ONE shot from raws and kepts, so both construction styles
    #: agree instead of one of them silently reporting zero drops.
    duplicates_dropped: int = 0

    # --- eligibility: FR-305's gate pass, between the dedupe and the view rank. Three reasons, one
    # counter each, every one of them printed even at zero (FR-155): "the window dropped nothing"
    # and "the counter is dead" are the two readings a missing line cannot tell apart, and this
    # gate is the only place a fresh, unused, readable post can vanish before it is ever ranked.
    dropped_stale: int = 0  # no `publish_date`, or older than `sources.max_post_age_days`
    dropped_unenriched: int = 0  # a slideshow with no slides, or no readable text and no vision
    dropped_used: int = 0  # already quoted inside the `run.trend_history_days` window (FR-7)

    # --- topics: FR-293's split. Per MONITOR, never per topic — nine topics built from one
    # monitor's 200 rows are 200 posts in, not 1,800; that is what the two-level `absorb` seam
    # buys, and re-counting a monitor's rows once per topic is the exact defect it prevents.
    posts_in: int = 0
    topics_out: int = 0
    #: FR-296's TOPICS header prints `N synth`: how many of `topics_out` were SYNTHESIZED from a
    #: monitor aggregate (zero themes, or the `-1` kill switch) rather than split from a named
    #: theme — the never-fewer-items invariant made visible instead of silently indistinguishable.
    topics_synthesized: int = 0

    # --- filter: FR-294's competitor screen. Recorded by the caller (`runner._screen_topics`),
    # because the filter runs between Collect and Select and this adapter never sees a verdict.
    filter_kept: int = 0
    filter_stripped: int = 0
    filter_skipped: int = 0
    filter_degraded: bool = False  # the LLM layer failed open — every verdict defaulted to keep

    trends_returned: int = 0

    # --- Select's verdicts. Recorded by the caller (`runner._select`), because Select owns them.
    verdict_seen: bool = False
    eligible: int = 0
    excluded_by_history: int = 0
    unusable: int = 0

    # --- the render forecast. Recorded by the caller once assignment has run. Re-based twice:
    # the topic-first pivot renamed `trends_used` to `topics_used` and added `styles_used`, and
    # D46/F3 excised the style reference-image window, so the forecast no longer counts
    # attachments at all — it states coverage (jobs, styles, topics) and what was dropped.
    render_seen: bool = False
    jobs: int = 0
    jobs_dropped: int = 0
    topics_used: int = 0
    styles_used: int = 0

    # ----------------------------------------------------------------- accumulation

    def __post_init__(self) -> None:
        """Derive `duplicates_dropped` when a one-shot tally stated raws and kepts but not the fold.

        A tally is built two ways: incrementally through `add_input` (which maintains the field
        row by row) or in one shot from known totals. The second way has no other moment to
        compute the drop, and a zero there would read as "nothing was repeated" — the precise
        false negative FR-155 exists to prevent. Never negative: kepts without raws is a caller
        stating half the picture, not a discovery that rows were invented.
        """
        if not self.duplicates_dropped:
            self.duplicates_dropped = max(0, self.posts_raw - self.posts_kept)

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
        self.duplicates_dropped += (videos_raw + slideshows_raw) - (videos_kept + slideshows_kept)
        self.total_available += total_available

    def add_drops(self, *, stale: int = 0, unenriched: int = 0, used: int = 0) -> None:
        """One gate pass's three verdicts (FR-305), counted once per DROPPED ROW.

        A row is counted under the FIRST reason it fails, never under two: a 2023 slideshow with no
        panels and a burnt id is one lost post, and three tallies of it would make the funnel's
        arithmetic (`posts_kept - drops == posts_in`) stop reconciling — which is the one property
        that lets an operator read the block as a chain rather than as four independent numbers.
        """
        self.dropped_stale += stale
        self.dropped_unenriched += unenriched
        self.dropped_used += used

    def add_topics(self, *, posts_in: int, topics_out: int, synthesized: int = 0) -> None:
        """One monitor's split (FR-293): the posts it offered, and the topics they became.

        Called once per monitor, with the monitor's post count — NOT once per topic, and never
        with a topic's own share. `9 topics` beside `200 posts` is the sentence the operator needs
        ("did the split lose material?"); nine rows of 200 would be the same lie the pre-FR-155
        `virlo_payload` told about duplicates. `synthesized` counts the aggregate fallbacks among
        `topics_out` (zero themes / kill switch) for FR-296's `N synth` clause.
        """
        self.posts_in += posts_in
        self.topics_out += topics_out
        self.topics_synthesized += synthesized

    def record_filter(self, verdicts: Any) -> None:
        """FR-294's verdicts, as `runner._screen_topics` received them.

        Takes the `dict[ordinal, Verdict]` that `topic_filter.screen()` returns (or any iterable
        of verdicts) and is duck-typed on `.verdict`/`.reason`, so the funnel never imports the
        filter and the filter never imports the funnel. An unrecognised verdict counts as `keep`,
        which is the module's own total-by-construction default (§1.5) rather than a silent drop.
        """
        rows = list(verdicts.values()) if isinstance(verdicts, Mapping) else list(verdicts or ())
        for row in rows:
            verdict = str(getattr(row, "verdict", "") or "keep").strip().lower()
            if verdict == "skip":
                self.filter_skipped += 1
            elif verdict == "strip":
                self.filter_stripped += 1
            else:
                self.filter_kept += 1
            if str(getattr(row, "reason", "") or "").startswith(_FILTER_DEGRADED):
                self.filter_degraded = True

    def record_selection(self, *, eligible: int, excluded: int, unusable: int) -> None:
        """Select's three verdict buckets (`plan.Selection`), which the adapter never sees."""
        self.verdict_seen = True
        self.eligible, self.excluded_by_history, self.unusable = eligible, excluded, unusable

    def record_render(self, *, jobs: int, dropped: int,
                      topics_used: int, styles_used: int) -> None:
        """The forecast end of the funnel: coverage, not attachments (D46/F3).

        The style reference-image window is excised, so there is no per-job attachment count
        left to forecast — the row states how many jobs render, wearing how many distinct
        styles, over how many topics, and how many entries were dropped with no topic left.
        """
        self.render_seen = True
        self.jobs, self.jobs_dropped = jobs, dropped
        self.topics_used, self.styles_used = topics_used, styles_used

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
    def dropped_ineligible(self) -> int:
        """Everything FR-305's gate removed, whatever the reason — the chain's middle term:
        `posts_kept - dropped_ineligible == posts_in`."""
        return self.dropped_stale + self.dropped_unenriched + self.dropped_used

    def drop_rows(self) -> list[tuple[str, tuple[str, ...]]]:
        """FR-155's post-level drop lines as `(label, clauses)` pairs — the WORDS, not the layout.

        The one-place rule (FR-155) is about the sentence as much as the number: a counter defined
        here and phrased in `runner._funnel_block` drifts the first time a reason is renamed, and
        the operator then reads a stale word beside a fresh count. So the adapter owns both, the
        console owns the packing, and the seam between them is this list — `runner` spreads each
        pair through its own `_funnel_row(label, *clauses)` packer, which is what enforces FR-286's
        78 columns and the safe-glyph set. Both preview modes and the paid run print the identical
        rows, because all three read one `Counters`.

        FOUR rows, always, zeros included (FR-155): the three drop reasons, plus the video ask —
        `include_videos: false` means `get_top_videos` was never called at all, and a row of zeros
        beside the slideshow counts reads as "this monitor posts no videos", which is a different
        and much more alarming statement than "we did not ask".
        """
        return [
            ("dropped", (f"{self.dropped_stale} stale (outside the age window)",)),
            ("dropped", (f"{self.dropped_unenriched} unenriched (no usable slide text)",)),
            ("dropped", (f"{self.dropped_used} used (already quoted in the window)",)),
            ("videos", ("disabled (slideshow-first) — get_top_videos not called"
                        if self.videos_disabled
                        else f"enabled — {self.videos_raw} row(s) fetched",)),
        ]

    def as_event(self) -> dict[str, Any]:
        """The `collect_funnel` payload: five nested objects, exactly FR-155's re-shaped form.

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
            # FR-305's three reasons as their own object rather than three more `input` keys: they
            # are a different KIND of loss (a judgement about a row we read, not a row Virlo
            # repeated), and a parser answering "why is this run thin?" reads exactly this group.
            "drops": {"stale": self.dropped_stale, "unenriched": self.dropped_unenriched,
                      "used": self.dropped_used, "total": self.dropped_ineligible},
            "topics": {"posts_in": self.posts_in, "topics_out": self.topics_out,
                       "synthesized": self.topics_synthesized,
                       "returned": self.trends_returned},
            "filter": {"kept": self.filter_kept, "stripped": self.filter_stripped,
                       "skipped": self.filter_skipped, "degraded": self.filter_degraded},
            "verdict": {"eligible": self.eligible, "excluded_by_history": self.excluded_by_history,
                        "unusable": self.unusable},
            "caps": {"rows_per_call": self.rows_per_call, "pages_asked": self.pages_asked,
                     "videos_disabled": self.videos_disabled},
        }

    def summary_line(self) -> str:
        """One flat sentence for run.log's digest of `collect_funnel` — the nested record above
        would render there as a truncated, unreadable single line.

        Reads the post-pivot funnel end to end: what Virlo shipped, what the dedupe kept, what the
        window and the history gate dropped, what the split made of it, and what reached Select.
        """
        return (f"{self.posts_kept} post(s) after {self.duplicates_dropped} duplicate(s), "
                f"{self.dropped_ineligible} ineligible "
                f"({self.dropped_stale} stale/{self.dropped_unenriched} unenriched/"
                f"{self.dropped_used} used), "
                f"{self.topics_out} topic(s) from "
                f"{max(0, self.monitors_asked - self.monitors_failed)} monitor(s), "
                f"{self.trends_returned} returned")


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

async def fetch(cfg: Config, *, log: LogWriter | None = None,
                include_digest: bool = True, used_posts: Collection[str] | None = None,
                say: Callable[[str], None] | None = None) -> TrendFeed:
    """Collect every configured monitor into ranked TOPIC items, strongest first (FR-293).

    Args:
        cfg: the loaded run config (`sources.*` and `mcp_servers.virlo` are what matter;
            `sources.virlo_topics_per_monitor` sets how many topics one monitor may become).
        log: the run's LogWriter, so every degrade lands in run.log/events.jsonl.
        include_digest: `False` skips `get_trends`, the one metered call, leaving
            `cross_monitor_context` empty — how a preview stays honestly at $0.
        used_posts: post ids already quoted inside the `run.trend_history_days` window (FR-7).
            **Consumed since v2.1.0** (FR-305/FR-307): a burnt post is DROPPED in the gate pass
            before the view rank, counted as `dropped_used`, and never offered again. It is not a
            reordering — the surviving `TrendItem.posts` stay view-ranked and nothing else, because
            that ordering IS the sort proof the console prints (FR-297a/b) and the `P<n>` labels
            the copy call quotes by (§1.7). Select keeps its own history verdict as the backstop,
            and copywrite refuses a burnt bound post at pick time; this is the first of the three.
            An empty collection disables the drop, which is exactly what the caller passes when
            `run.trend_history_days` is `0` (`outputs.used_posts` returns nothing for a zero
            window) — one switch, honoured without this module re-reading the config.
        say: the console seam, for the one refusal an operator must not have to find in run.log.

    Returns:
        A `TrendFeed` — topics strongest first, with this run's funnel `Counters` attached
        (FR-155). A failed monitor contributes nothing and is logged; an empty feed means Collect
        found nothing, and the caller decides whether that aborts the run.
    """
    counters = Counters(rows_per_call=_MEDIA_LIMIT, pages_asked=_fetch_pages(cfg),
                        videos_disabled=not cfg.sources.include_videos)
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
        jobs: list[Any] = [_monitor_item(pool, mid, cfg, log, used, counters=counters, say=say)
                           for mid in ids]
        if include_digest:
            jobs.append(_digest(pool, log, say=say))
        results = await asyncio.gather(*jobs, return_exceptions=True)

    items: list[TrendItem] = []
    context, confidences = "", {}
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
                  say=say, monitor_id=label, error=type(result).__name__)
        elif isinstance(result, list):  # one monitor's topics (FR-293), zero of them if it failed
            items.extend(result)
        elif isinstance(result, tuple):
            context, confidences = result
    for item in items:  # global digest first, then this monitor's own timing/thread context
        item.cross_monitor_context = " · ".join(
            part for part in (context, item.cross_monitor_context) if part)
        if item.confidence is None:  # the theme leads (FR-5); the digest is the empty fallback
            item.confidence = _match_confidence(item.name, confidences)
    # The raw components are what a human argues with ("why did THAT topic win?"), and `_score`
    # overwrites them in place with their 0-1 normalizations — so they are copied out first and
    # both halves travel together on `topic_ranked` (FR-298).
    raw = {item.history_key: dict(item.strength_components) for item in items}
    _score(items)
    items.sort(key=lambda item: item.strength, reverse=True)
    counters.trends_returned = len(items)
    _ranked_event(log, items, raw)
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
                        *, counters: Counters | None = None,
                        say: Callable[[str], None] | None = None) -> list[TrendItem]:
    """One monitor's calls on one borrowed session, windowed and split into TOPICS (FR-293/FR-301).

    The media ask is `created_at desc` over pages `1..sources.fetch_pages`, which is "the newest
    collection rounds, this deep" — see `_MEDIA_ORDER_BY` for why the all-time `views desc` page it
    replaced was the D46 defect rather than a preference. Views still decide rank; they decide it
    among the survivors of the window (`_source_rows`), not among 2023's winners.

    **`get_top_videos` is called only when `sources.include_videos` is true, and the default is
    false** (FR-32/FR-301, §0.2): every live monitor is slideshow-majority, and a video row cannot
    carry the panel texts FR-304 renders a deck from. Not calling is deliberately different from
    calling and finding nothing — the funnel says "disabled", never a row of zeros
    (`Counters.videos_disabled`).

    Returns a LIST — one item per theme, or exactly one synthesized item when the monitor named no
    theme. The name is kept because the seam is the same; the cardinality is not, and every caller
    of this function reads the list.

    The funnel is tallied on a PRIVATE `Counters` here and absorbed into the run-wide rollup
    afterwards (FR-155). That is what makes the numbers scoped to what produced them: the topic
    work tallies underneath this same seam, so one monitor's rows are counted once and not once
    per topic.

    `used` IS consulted now (FR-305/FR-307): it travels into the gate pass inside `_split_topics`,
    which drops a burnt post before the view rank rather than after it. (FR-115 serializes every
    call on the borrowed session anyway, so paging costs latency, never concurrency.)
    """
    pages = _fetch_pages(cfg)
    async with pool.acquire() as session:
        analysis = await _call(session, "get_monitor_analysis", {"monitor_id": monitor_id})
        clips, video_total = ((await _media_rows(session, "get_top_videos", "videos",
                                                 monitor_id, pages))
                              if cfg.sources.include_videos else ([], 0.0))
        panels, show_total = await _media_rows(session, "get_top_slideshows", "slideshows",
                                               monitor_id, pages)
    tally = Counters(videos_disabled=not cfg.sources.include_videos)
    # Virlo reports how deep the pool it just answered from is, and every page of one call echoes
    # the same figure — so `_media_rows` reads it from the first page only and this adds the two
    # media kinds, never the pages. `total_available` is what makes the window's depth legible:
    # "300 rows asked of 2,039 available" is a sampling statement an operator can argue with.
    tally.total_available = int(video_total + show_total)
    items = _split_topics(monitor_id, analysis, clips, panels, cfg, used=used, log=log,
                          counters=tally, say=say)
    for item in items:
        _payload_event(log, item, tally)
        _topic_posts_event(log, item)
    _fields_event(log, monitor_id, analysis, clips, panels, items)
    if counters is not None:
        counters.absorb(tally)
    return items


def _fetch_pages(cfg: Config) -> int:
    """`sources.fetch_pages`, as the ask reads it — at least one page, always (FR-301).

    The floor is structural rather than defensive: a run that asked for zero pages would open a
    Virlo session, spend the digest's $0.25, collect nothing and report success — the shape of
    silent failure this whole plan exists to remove. Config validation bounds the key's upper end;
    this bounds the one value that would make the call meaningless.
    """
    return max(1, int(cfg.sources.fetch_pages))


async def _media_rows(session: Session, tool: str, key: str, monitor_id: str,
                      pages: int) -> tuple[list[Any], float]:
    """Pages `1..pages` of one media tool, concatenated, with Virlo's own row total (FR-301).

    Returns `(rows, total_available)`. The rows arrive in the order Virlo returned them, page after
    page, and are NOT deduped here: `_split_topics` runs `_dedupe` over the whole concatenation, so
    a row Virlo repeats across two pages is counted as `duplicates_dropped` exactly like the
    within-page repeats §A measured — one dedupe, one counter, one funnel line. Paging is the whole
    reason that matters now: `created_at desc` pages overlap whenever Virlo ingests a new round
    between two calls, and a silent second copy of a post would otherwise reach two topics.

    **Stops early on a short page.** A page thinner than `_MEDIA_LIMIT` is the end of the pool, so
    asking for the next one buys a guaranteed-empty round trip on every small monitor — and the
    cost is real: this runs inside `_monitor_item`'s serialized session (FR-115), so every page is
    latency the operator waits through.

    `total_available` is read from the FIRST page only. Every page of one call echoes the same
    `total` (it counts the pool, not the page), so summing pages would report a 2,039-row monitor
    as a 6,117-row one and turn the funnel header into fiction.
    """
    rows: list[Any] = []
    total = 0.0
    for page in range(1, pages + 1):
        payload = await _call(session, tool, {"monitor_id": monitor_id, "limit": _MEDIA_LIMIT,
                                              "page": page, "order_by": _MEDIA_ORDER_BY,
                                              "sort": _MEDIA_SORT})
        batch = payload.get(key) or []
        if page == 1:
            total = _num(payload.get("total"))
        rows.extend(batch)
        if len(batch) < _MEDIA_LIMIT:
            break
    return rows, total


def _payload_event(log: LogWriter | None, item: TrendItem, tally: Counters) -> None:
    """FR-77's per-item Virlo payload summary, written once at join time: key, name, post counts
    and the top engagement stats — enough to tell a thin topic from a strong one in run.log.

    The counts are the POST-DEDUPE ones (FR-155's event-shape amendment). Until 2026-08-11 this
    line reported `len(clips)`/`len(panels)` — what Virlo shipped, not what the pipeline read —
    and a real three-monitor run therefore over-reported its material by 11 rows. The raw figures
    are kept beside them as `videos_raw`/`slideshows_raw` so the drop is measurable rather than
    merely corrected.

    A TOPIC reports its OWN posts, not the monitor's totals (FR-293): nine topics printing one
    monitor-wide "100 videos, 100 slideshows" would be the same over-reporting defect the dedupe
    fix closed, one level up. The monitor-wide figures stay in `data` beside them, because the
    dedupe drop is a fact about the monitor and cannot be attributed to any one topic.

    **The window's arithmetic rides along (FR-301's event-shape amendment, v2.1.0):**
    `rows_fetched` is what the monitor's calls returned before anything judged them, and the three
    `dropped_*` figures are FR-305's gate. They are monitor-scoped like the dedupe figures beside
    them and for the same reason — the gate runs once per monitor, before the split, so no topic
    can claim a share of the loss. The message states both ends: what the dedupe kept, and what
    survived the window.
    """
    if log is None:
        return
    newest = item.newest_published_at.date().isoformat() if item.newest_published_at else "-"
    likes = int(item.engagement.get("likes", 0))
    # An item with no `posts` (an empty-monitor synthesized topic) has no post-level composition
    # of its own, so the monitor-wide deduped counts are the honest answer for it.
    videos, shows = ((sum(1 for post in item.posts if not post.is_slideshow),
                      sum(1 for post in item.posts if post.is_slideshow))
                     if item.posts else (tally.videos_kept, tally.slideshows_kept))
    log.event("virlo_payload",
              f"{item.name}: after dedup {videos} videos, {shows} "
              f"slideshows, {item.total_views:,} views, {likes:,} likes, newest {newest}"
              f" · after filtering {tally.posts_in} post(s) available, "
              f"{tally.dropped_ineligible} dropped",
              trend=item.history_key, name=item.name, topic=item.topic_key,
              videos=videos, slideshows=shows, posts=len(item.posts),
              monitor_videos_kept=tally.videos_kept, monitor_slideshows_kept=tally.slideshows_kept,
              videos_raw=tally.videos_raw, slideshows_raw=tally.slideshows_raw,
              rows_fetched=tally.posts_raw, duplicates_dropped=tally.duplicates_dropped,
              dropped_stale=tally.dropped_stale, dropped_unenriched=tally.dropped_unenriched,
              dropped_used=tally.dropped_used, posts_available=tally.posts_in,
              total_available=tally.total_available,
              views=item.total_views, likes=likes, newest_published=newest)


async def _digest(pool: SessionPool,
                  log: LogWriter | None, *,
                  say: Callable[[str], None] | None = None) -> tuple[str, dict[str, float]]:
    """Cross-monitor context and any confidence values the daily digest carries.

    THE ONLY METERED VIRLO CALL ($0.25/run, RESULTS.md §A). It creates no topics (20 §3) and its
    failure is never fatal — the run simply carries no cross-monitor context.

    **The exemplar payload is dropped (v2.0.0).** Each digest trend ships up to five
    `top_exemplars`, and this adapter used to hand them on as a last-resort REFERENCE tier (A18).
    Post-pivot there is no reference tier at all — the visuals come from the style registry — and
    those posts are global rather than this niche's, so offering their TEXT would import
    off-niche copy into a topic that has its own. The wrapper still normalizes them; nothing here
    reads them, and 20 §2's tool-table row goes with the media funnel in Wave 3.5.
    """
    try:
        async with pool.acquire() as session:
            payload = await _call(session, "get_trends")
    except (MCPClientError, MCPError, VirloToolError, ValueError) as exc:
        _warn(log, "virlo_digest_failed", f"trend digest unavailable: {exc}", say=say,
              error=type(exc).__name__)
        return "", {}
    rows = [row for group in payload.get("groups") or [] for row in group.get("trends") or []]
    rows.sort(key=lambda row: _num(row.get("ranking")) or 10_000)
    lines, confidences = [], {}
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
    return ("Global trend digest today: " + "; ".join(lines) if lines else ""), confidences


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


# ----------------------------------------------------------------- topic split (FR-293)

@dataclass(slots=True, frozen=True)
class _Theme:
    """One `analysis_data.themes[]` block, normalized into the seed of exactly one topic.

    An empty `key` marks the SYNTHESIZED seed: the monitor named no theme (or the kill switch is
    on), so the one topic built from it is the monitor aggregate — the pre-pivot item shape,
    `history_key` included.
    """

    key: str  # `slugify(name, 0)`, uncapped so two runs derive the identical key
    name: str  # the topic's own name, verbatim from Virlo
    why_it_works: str = ""
    tactics: tuple[str, ...] = ()
    confidence: float | None = None
    #: Virlo's own `evidence_video_ids` for this theme — the only first-party theme->post link
    #: that exists. Empty today; see `_allocate` for why, and what happens when it is not.
    evidence: frozenset[str] = frozenset()


@dataclass(slots=True, frozen=True)
class _Row:
    """One media row and the `SourcePost` built from it, carried as one unit.

    Both halves are needed and neither subsumes the other: `post` is the quotable text (§1.7's
    reference targets, the history record, the FR-297b roster), while `raw` still carries Virlo's
    `intelligence` classification — `hook_type`, `emotional_tone`, `visual_hook_type` — which is
    a judgement ABOUT a post rather than text FROM it, and therefore never became a `SourcePost`
    field. Keeping them paired is what lets a topic's labels be drawn from its own posts.
    """

    post: SourcePost
    raw: Mapping[str, Any]


@dataclass(slots=True, frozen=True)
class _MonitorFacts:
    """What every topic of one monitor inherits from the monitor rather than from its own theme."""

    monitor_id: str
    name: str  # the monitor's own name — the synthesized topic's name
    why_it_works: str = ""  # `analysis.why_it_works`, the monitor's own prose
    tactics: tuple[str, ...] = ()  # `analysis.viral_tactics`, below the theme's own
    context: str = ""  # timing, peak hours, connecting thread, key highlight (20 §3)
    # The three `aggregate_*` fields are the SYNTHESIZED topic's only source — a monitor with no
    # themes, or the `-1` kill switch. They span every consumed theme, which is what makes that
    # one item the pre-pivot item shape rather than a topic that lost its theme.
    aggregate_why: str = ""
    aggregate_tactics: tuple[str, ...] = ()
    aggregate_confidence: float | None = None


def _topic_cap(cfg: Config) -> int:
    """`sources.virlo_topics_per_monitor`, as the split reads it.

    `-1` is the kill switch (one item per monitor — the pre-pivot behaviour, and the only way to
    un-ship the split without a code change); `0` never reaches here because config validation
    refuses it explicitly, a run that collects nothing while reporting success being the one
    reading of "zero topics per monitor" nobody wants.
    """
    return int(cfg.sources.virlo_topics_per_monitor)


def _themes(analysis: Mapping[str, Any], cap: int) -> list[_Theme]:
    """This monitor's themes as topic seeds — the `_themes()` contract (plan §1.3, FR-293).

    Three invariants, all structural rather than advisory:

    - **Never fewer items than the pre-pivot adapter returned.** No themes, no named theme, or the
      kill switch, and the answer is a single empty-keyed seed — one topic per monitor, exactly as
      before. The list is never empty, so no caller branches on emptiness.
    - **`cap` bounds consumption.** Themes past it are dropped here, which is also what bounds the
      filter call's worst case (`len(monitors) x cap` topics, priced pre-Collect in `budget.py`).
    - **The key is stable, and unique within the monitor.** `slugify(name, 0)` is uncapped, so the
      same theme name yields the same key run after run — the whole point of a history key. A
      collision inside one monitor takes a `#2` suffix, because `runner`/`previews` build
      `{history_key: topic}` maps and a duplicate key would silently DROP a topic rather than
      report one (the exact defect Increment B's review caught).
    """
    seeds: list[_Theme] = []
    if cap > 0:
        for row in (analysis.get("themes") or [])[:cap]:
            if not isinstance(row, Mapping):
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            seeds.append(_Theme(
                key=_unique_key(slugify(name, 0), {seed.key for seed in seeds}),
                name=name,
                why_it_works=str(row.get("why_it_works") or "").strip(),
                tactics=tuple(str(value).strip() for value in row.get("tactics") or []
                              if str(value).strip()),
                confidence=_confidence(row.get("confidence")),
                evidence=frozenset(str(value) for value in row.get("evidence_video_ids") or []
                                   if str(value).strip())))
    return seeds or [_Theme(key="", name="")]


def _unique_key(key: str, taken: Collection[str]) -> str:
    """`key`, or the first `key#N` free in `taken` — see `_themes` for why a collision cannot pass."""
    if key not in taken:
        return key
    suffix = 2
    while f"{key}#{suffix}" in taken:
        suffix += 1
    return f"{key}#{suffix}"


def _confidence(value: Any) -> float | None:
    """One theme's confidence as a number, or None. `bool` is an `int` in Python, so it is refused
    explicitly — `True` would otherwise rank as a confidence of 1.00."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


# ------------------------------------------------------- the eligibility gate (FR-305/FR-307)


@dataclass(slots=True, frozen=True)
class _Gate:
    """FR-305's three predicates, resolved once per monitor from config and the history window.

    An object rather than three loose parameters because the three settings are read together,
    logged together and reasoned about together — "what window is this run looking through" is one
    question, and a run that answers it differently for two monitors has a bug rather than a
    feature. Frozen, so the gate cannot drift mid-pass.
    """

    #: `sources.max_post_age_days`. `0` disables the age cap ENTIRELY (FR-301) — the setting an
    #: archive dive or a test over the captured all-time corpus needs, and the only way a row with
    #: no `publish_date` at all survives.
    max_age_days: int
    #: The post ids quoted inside `run.trend_history_days` (FR-7). Empty = the window is off, which
    #: is what the caller passes when `trend_history_days: 0`.
    used: frozenset[str]
    #: `sources.vision_transcribe`. ON, a slideshow with slides but no `panel_texts` is KEPT: the
    #: post-Confirm slide-intelligence call (FR-306, §0.14a) reads the words off the slides
    #: themselves, so dropping it here would throw away the exact rows that tier exists for —
    #: many fresh rows carry empty `panel_texts` (D46 §1). OFF, the row has no readable text and
    #: no way to acquire any, so it cannot fill a deck and it goes.
    vision: bool

    @classmethod
    def of(cls, cfg: Config, used: Collection[str]) -> _Gate:
        """The gate this run's config and history window describe."""
        return cls(max_age_days=max(0, int(cfg.sources.max_post_age_days)),
                   used=frozenset(str(post) for post in used or ()),
                   vision=bool(cfg.sources.vision_transcribe))

    def verdict(self, row: Mapping[str, Any], *, is_slideshow: bool) -> str:
        """`""` to keep, else the counter name that owns this row's loss.

        ONE reason per row, in a fixed order — stale, then unenriched, then used — so the funnel's
        three counters sum to the number of rows the gate removed. A 2023 slideshow with no panels
        that this tool already quoted is one lost post; counting it three times would break the
        `posts_kept - dropped == posts_in` chain the funnel block is read as.
        """
        if self.max_age_days:
            when = _when(row)
            if when is None:
                return "stale"  # undatable is unwindowable: it cannot be shown to be fresh
            age = (datetime.now(timezone.utc) - when).total_seconds() / 86400.0
            if age > self.max_age_days:
                return "stale"
        if is_slideshow and self._unenriched(row):
            return "unenriched"
        # A row carrying neither `id` nor `url` has no identity history could have recorded (its
        # `post_id` is positional — see `_post_id`), so it can never match a burnt id and is not
        # tested against one.
        identity = str(row.get("id") or row.get("url") or "")
        if identity and identity in self.used:
            return "used"
        return ""

    def _unenriched(self, row: Mapping[str, Any]) -> bool:
        """§0.14a's usability predicate for a SLIDESHOW row, at fetch time.

        Two ways a deck is unusable before anything is spent on it:

        1. **No slides.** `panel_count == 0` means Virlo has no images for this post, so there is
           nothing to transcribe, nothing to show in the provenance gallery and no panel *i* for
           FR-304 to render our slide *i* from. Dead whatever the vision tier does.
        2. **No text and no way to get any.** With `vision_transcribe` off, the row's own
           `panel_texts`/`hook_text` are the only words it will ever have; with none of them it
           can only produce an empty deck.

        Deck ELIGIBILITY (§0.14a's "≥2 usable slots") is deliberately NOT decided here: usability
        is judged after the merge of Virlo's panels with the vision transcription, which happens
        post-Confirm, so ASSIGN owns that verdict (FR-304). This gate answers the cheaper
        question — could this row ever carry slide text at all — and refuses to guess the other.
        """
        if int(_num(row.get("panel_count"))) <= 0:
            return True
        if self.vision:
            return False
        has_panels = any(str(text).strip() for text in row.get("panel_texts") or [])
        return not has_panels and not str(row.get("hook_text") or "").strip()


def _eligible(videos: list[Any], shows: list[Any], gate: _Gate,
              tally: Counters) -> tuple[list[Any], list[Any]]:
    """ONE gate pass over both media arrays (FR-305), counting every drop by its reason.

    Returns the surviving `(videos, shows)`. Runs between `_dedupe` and `_source_rows` so a dropped
    row never becomes a `SourcePost`, never takes a `P<n>` label and never reaches a prompt — and
    so the funnel's arithmetic reconciles: rows kept, minus these three counters, is `posts_in`.

    Videos are gated too (staleness and the history window apply to any post), but never on the
    slideshow enrichment predicate: a video has no panels to be missing, and dropping it for that
    would silently empty a video-inclusive run.
    """
    drops = {"stale": 0, "unenriched": 0, "used": 0}
    kept: list[list[Any]] = [[], []]
    for index, rows in enumerate((videos, shows)):
        for row in rows:
            if not isinstance(row, Mapping):
                continue  # `_dedupe` already drops these; the guard keeps the pass total anyway
            reason = gate.verdict(row, is_slideshow=index == 1)
            if reason:
                drops[reason] += 1
            else:
                kept[index].append(row)
    tally.add_drops(**drops)
    return kept[0], kept[1]


def _split_topics(monitor_id: str, analysis: Mapping[str, Any], videos: list[Any], shows: list[Any],
                 cfg: Config, *, used: Collection[str] = frozenset(),
                 log: LogWriter | None = None,
                 counters: Counters | None = None,
                 say: Callable[[str], None] | None = None) -> list[TrendItem]:
    """Split one monitor's tool returns into its topics (FR-293) — the post-pivot join.

    The shape, in one line: dedupe the rows, GATE them (FR-305), rank the survivors by views, seed
    one topic per theme, deal the posts out exclusively, and build each topic from ITS OWN share.
    Nothing here downloads, screens or scores across monitors — `_score` needs the whole run's pool
    and runs in `fetch`.

    The gate sits between the dedupe and the rank ON PURPOSE. Ranking first and filtering after
    would leave `P1` naming a post nobody may quote — and the `P<n>` labels are the copy call's
    whole vocabulary (§1.7), so they must count over the pool that survived, not over the pool that
    arrived. Every ranked quantity a topic carries (FR-5's views, median, velocity, engagement,
    the slideshow majority) is then measured over the windowed survivors for free, because
    `_topic_item` only ever sees the shares dealt from `rows`.

    `counters` is the caller's tally (FR-155); omitted, a scratch one absorbs the numbers and is
    discarded, so every direct caller keeps working and nothing branches on whether it was passed.
    """
    tally = counters if counters is not None else Counters()
    raw_videos, raw_shows = len(videos), len(shows)
    videos, shows = _dedupe(videos), _dedupe(shows)  # RESULTS.md §A: the live arrays repeat posts
    tally.add_input(videos_raw=raw_videos, slideshows_raw=raw_shows,
                    videos_kept=len(videos), slideshows_kept=len(shows))
    videos, shows = _eligible(videos, shows, _Gate.of(cfg, used), tally)
    cap = _topic_cap(cfg)
    aggregate_why, aggregate_tactics, context, aggregate_confidence = _analysis_fields(
        analysis, cap)
    facts = _MonitorFacts(
        monitor_id=str(monitor_id),
        name=str(analysis.get("name") or "").strip() or f"monitor {monitor_id}",
        why_it_works=str(analysis.get("why_it_works") or "").strip(),
        tactics=tuple(str(value).strip() for value in analysis.get("viral_tactics") or []
                      if str(value).strip()),
        context=context,
        aggregate_why=aggregate_why,
        aggregate_tactics=tuple(aggregate_tactics),
        aggregate_confidence=aggregate_confidence)
    themes = _themes(analysis, cap)
    rows = _source_rows(videos, shows, str(monitor_id))
    if not rows:
        # Not fatal and not silent: the topics still carry the analysis text, and Select decides
        # (FR-6). Silent, this reads downstream as "the trend was weak" rather than "the monitor
        # shipped nothing", which is a different fix entirely — and post-FR-305 there is a THIRD
        # reading to separate from those two: the monitor shipped plenty and the window ate all of
        # it. That is an operator ACTION (widen `max_post_age_days`, add monitors, run weekly
        # instead of daily), so the famine cause is named in the sentence rather than left to be
        # reconstructed from the funnel at DONE.
        cause = (f"every one of its {tally.posts_kept} row(s) failed the eligibility gate "
                 f"({tally.dropped_stale} stale, {tally.dropped_unenriched} unenriched, "
                 f"{tally.dropped_used} already used)" if tally.dropped_ineligible
                 else "monitor returned no posts")
        _warn(log, "virlo_monitor_empty",
              f"{facts.name}: {cause} — its topic(s) carry the monitor's "
              "analysis text and nothing quotable (FR-6)", say=say, monitor_id=str(monitor_id),
              dropped_stale=tally.dropped_stale, dropped_unenriched=tally.dropped_unenriched,
              dropped_used=tally.dropped_used)
    items = [_topic_item(theme, share, facts)
             for theme, share in zip(themes, _allocate(rows, themes), strict=True)]
    tally.add_topics(posts_in=len(rows), topics_out=len(items),
                     synthesized=sum(1 for theme in themes if not theme.key))
    return items


def _source_rows(videos: list[Any], shows: list[Any], monitor_id: str) -> list[_Row]:
    """Every ELIGIBLE row as a `SourcePost`, view-ranked descending across both media kinds.

    The rows reaching here have already passed the dedupe and FR-305's gate, so this ranking is
    "the strongest of what we may use", which is what FR-301 means by *views within the window*.
    The two arrays arrive independently sorted (and by `created_at`, not by views, since D46), so
    concatenating them says nothing about strength — this is the one place that merged order
    becomes a real ranking, and that ranking is what the `P<n>` reference labels count over
    (§1.7) and what FR-297b prints as the sort proof.

    `index` runs across slideshows THEN videos exactly as `_post_id` documents, so the positional
    fallback for a row carrying neither `id` nor `url` cannot collide across the two arrays.
    """
    pairs: list[tuple[Any, int, bool]] = [
        (video, index, False) for index, video in enumerate(videos, start=len(shows))]
    pairs += [(show, index, True) for index, show in enumerate(shows)]
    built = [_Row(_source_post(raw, monitor_id, index, is_slideshow), raw)
             for raw, index, is_slideshow in pairs if isinstance(raw, Mapping)]
    # Stable, so rows tied on views keep video-then-slideshow order — the pre-pivot `_ranked`
    # order, kept so a tie does not silently reshuffle between two runs of the same page.
    return sorted(built, key=lambda row: row.post.views, reverse=True)


def _source_post(raw: Mapping[str, Any], monitor_id: str, index: int,
                 is_slideshow: bool) -> SourcePost:
    """One Virlo row as the quotable unit (§1.6/FR-293) — a field MAP, never a rewrite.

    Stated as a table because §1.7 resolves the copy call's references straight back into these
    fields, so which Virlo field lands where is a content decision, not plumbing:

    | `SourcePost`    | Virlo row            | what it actually is                              |
    |-----------------|----------------------|--------------------------------------------------|
    | `caption`       | `description`        | the creator's own caption — the verbatim material |
    | `hooks`         | `hook_text`          | the opening line Virlo lifted off the post        |
    | `text_overlays` | `text_overlay_content` | words burned into the frame (videos only)       |
    | `panel_texts`   | `panel_texts`        | per-slide words in panel order (slideshows only)  |
    | `description`   | `summary`            | **Virlo's** summary of the post, not the creator's |
    | `panel_count`   | `panel_count`        | how many slides the source deck has               |
    | `image_urls`    | `image_urls`         | those slides' URLs, position-sorted (analysis only) |
    | `intelligence_status` | `intelligence_status` | whether Virlo enriched this row            |
    | `views/author/url/published_at` | same names | identity and rank                         |
    | `author_name`   | *(nothing today)*    | the creator's DISPLAY name — see `_author_name`   |

    ⚠️ `description` is the one field that is not the creator's words: Virlo's `intelligence`
    block writes it, so it is legitimate CONTEXT (and legitimately verbatim *from Virlo*, per
    FR-293's wording) but a poor thing to burn into a frame as a quote. The candidate pre-filter
    that decides what may become pixels lives in `copywrite` (§1.7), which is where that
    distinction has to be enforced; it is named here so it cannot be discovered by surprise.

    Whitespace is stripped at the edges and nowhere else: a string is otherwise stored exactly as
    it arrived, diacritics, emoji, line breaks and all, because a string edited on the way in can
    no longer be quoted verbatim on the way out (D42).

    **Panels keep their POSITIONS (FR-293/FR-304, §0.14a).** This function used to drop empty
    entries out of `panel_texts`; it now pads instead, so slot *i* is source slide *i+1* whether or
    not Virlo transcribed that slide. The compaction was invisible and expensive: FR-304 renders
    our slide *i* from source panel *i*, so a deck whose second slide carried no text would have
    shipped slide 3's words on slide 2 and read as a faithful copy of a post nobody made. Padding
    also gives the vision tier (FR-306) somewhere to put what it reads off slide 2. Alignment
    never TRUNCATES: if Virlo somehow sends more texts than slides, the extra texts keep their
    indices rather than being thrown away, because losing source bytes is the worse failure.
    """
    hook = str(raw.get("hook_text") or "").strip()
    overlay = str(raw.get("text_overlay_content") or "").strip()
    return SourcePost(
        post_id=_post_id(raw, monitor_id, index),
        url=str(raw.get("url") or ""),
        author=str(raw.get("author_username") or ""),
        author_name=_author_name(raw),
        caption=str(raw.get("description") or "").strip(),
        hooks=[hook] if hook else [],
        text_overlays=[overlay] if overlay else [],
        panel_texts=_panels(raw),
        description=str(raw.get("summary") or "").strip(),
        views=int(_num(raw.get("views"))),
        published_at=_when(raw),
        is_slideshow=is_slideshow,
        panel_count=int(_num(raw.get("panel_count"))),
        image_urls=[str(url) for url in raw.get("image_urls") or [] if str(url).strip()],
        intelligence_status=str(raw.get("intelligence_status") or "").strip())


#: Every key a display name could plausibly arrive under, tried in this order. Virlo exposes NONE
#: of them today — measured 2026-08-14 across the whole fixture corpus and both wrapper
#: normalizers: the API's nested `author` object carries `username`, `verified`, `followers`,
#: `country` and `avatar_url`, and `virlo_mcp.server._norm_video/_norm_slideshow` forward the first
#: two of those as `author_username`/`author_followers`. So `SourcePost.author_name` is
#: DOCUMENTED-ABSENT, not populated, and `""` is its live value on every run today.
#:
#: The probe is here rather than the field being left unmapped because the consumer already exists
#: (`copywrite` reads `author_name` when it strips a creator's identity out of a caption, FR-312)
#: and because a display name is exactly the field an upstream adds without telling anyone. The day
#: Virlo's payload — or the wrapper's flattening of it — carries one, this maps it and nothing else
#: in the tree moves. A regression test pins both halves: `""` on today's shape, populated on a row
#: that carries the key (`tests/test_virlo_topics.py`).
_AUTHOR_NAME_KEYS = ("author_name", "author_nickname", "author_display_name")


def _author_name(raw: Mapping[str, Any]) -> str:
    """The creator's display name if the payload carries one — `""` on every payload today.

    Edges stripped like every other string in `_source_post`, and nothing else done to it: this is
    a name that a strip pass compares against caption bytes (FR-312), so a "helpful" case fold or
    a collapsed space here becomes a missed strip there.
    """
    for key in _AUTHOR_NAME_KEYS:
        if (value := str(raw.get(key) or "").strip()):
            return value
    return ""


def _panels(raw: Mapping[str, Any]) -> list[str]:
    """`panel_texts`, index-aligned to `panel_count` — one slot per source slide (§0.14a).

    Slots are padded with `""`, never closed, and the list is as long as the deck is wide (or as
    long as the text array, if Virlo ever sends more texts than it sent images — see
    `_source_post`). Each surviving string keeps its own bytes, inner whitespace included: these
    are slide bytes, and a slide's own line breaks are part of how it reads.
    """
    texts = [str(text) for text in raw.get("panel_texts") or []]
    slots = max(int(_num(raw.get("panel_count"))), len(texts))
    return texts + [""] * (slots - len(texts))


def _allocate(rows: Sequence[_Row], themes: Sequence[_Theme]) -> list[list[_Row]]:
    """Deal one monitor's posts across its topics — EXCLUSIVELY (FR-293; Increment-B §4.2).

    Two passes, in order:

    1. **Evidence.** A theme claims the rows its own `evidence_video_ids` name, strongest theme
       first, and a claimed row leaves the pool. Measured live (spikes §1.5): one `views desc`
       page recovers ~8% of a theme's evidence and evidence names a slideshow in 0 of 287 cases,
       so this is a weak signal and never a partition key on its own. **Today it recovers nothing
       at all** — the MCP wrapper's `_norm_theme` keeps five fields and `evidence_video_ids` is
       not among them — so the pass is inert until that field is passed through. It is written
       absent-safe deliberately: the day the wrapper forwards it, allocation gets sharper and no
       other line moves.
    2. **Stride.** Everything left is dealt `rest[i::len(themes)]` to theme *i*. Over a view-ranked
       list a stride deal is deterministic, exhaustive and non-overlapping, and it avoids
       round-robin's pathology where theme #1 eats every strong post. Exclusivity is the property
       that matters: it is what makes two topics of one monitor carry different posts, different
       engagement and therefore different strengths (§1.6), rather than nine copies of one number.

    A single seed — one theme, or the synthesized aggregate — takes every row: there is nothing to
    divide, and "all of this monitor's posts" is precisely the pre-pivot item shape.
    """
    if len(themes) <= 1:
        return [list(rows)]
    shares: list[list[_Row]] = [[] for _ in themes]
    claimed: set[str] = set()
    for index, theme in enumerate(themes):
        if not theme.evidence:
            continue
        for row in rows:
            if row.post.post_id in theme.evidence and row.post.post_id not in claimed:
                shares[index].append(row)
                claimed.add(row.post.post_id)
    rest = [row for row in rows if row.post.post_id not in claimed]
    for index in range(len(themes)):
        shares[index].extend(rest[index::len(themes)])
    # Re-ranked per share: an evidence claim can pull a weaker row ahead of a stronger strided one,
    # and `TrendItem.posts` is view-ranked by contract — the `P<n>` labels count over that order.
    return [sorted(share, key=lambda row: row.post.views, reverse=True) for share in shares]


def _topic_item(theme: _Theme, rows: Sequence[_Row], facts: _MonitorFacts) -> TrendItem:
    """One topic, built from ITS OWN posts and nothing else (FR-293).

    Every quantity below — views, median, velocity, engagement, the label lists, the hashtags, the
    slideshow majority — is measured over `rows`, this topic's exclusive share. That is the whole
    point of the split: a monitor-wide figure repeated across nine topics would rank them all
    identically and make the ranking table a decoration.

    `is_slideshow` is a strict majority over those same posts (FR-90's carousel affinity): a topic
    whose winners really are photo decks is a deck to mimic, and a tie reads as video, because the
    burden of proof sits on the rarer, more expensive-to-imitate format.

    The raw strength components are STAGED here and replaced by their normalized 0-1 values in
    `_score` — min-max needs the run's whole topic pool, which no single monitor can see.
    """
    posts = [row.post for row in rows]
    raws = [row.raw for row in rows]
    views = [float(post.views) for post in posts]
    engagement = {key: int(sum(_num(raw.get(key)) for raw in raws))
                  for key in ("likes", "shares", "comments", "bookmarks")}
    aggregate = not theme.key  # the synthesized monitor-wide topic (no themes, or kill switch)
    item = TrendItem(
        # `<mid>::<topic_key>` (§1.6) — the monitor id LEADS because Virlo's theme keys collide
        # across monitors (measured on all three live agents). The aggregate keeps the bare
        # monitor id, which is the pre-pivot key exactly.
        history_key=facts.monitor_id if aggregate else f"{facts.monitor_id}::{theme.key}",
        monitor_id=facts.monitor_id,
        name=facts.name if aggregate else theme.name,
        topic_key=theme.key,
        posts=posts,
        confidence=facts.aggregate_confidence if aggregate else theme.confidence,
        why_it_works=facts.aggregate_why if aggregate else _topic_why(theme, facts),
        tactics=(list(facts.aggregate_tactics[:_MAX_TACTICS]) if aggregate
                 else _topic_tactics(theme, facts)),
        cross_monitor_context=facts.context,  # `fetch` prefixes the global digest onto this
        hook_texts=_texts(raws, "hook_text"),
        text_overlay_contents=_texts(raws, "text_overlay_content"),
        # ONE post's panels, never several concatenated: `panel_texts` is a per-slide rhythm, and
        # slides from two different decks stitched together describe a deck that never existed.
        # The test is for READABLE panels, not for a non-empty list: since §0.14a's alignment a
        # deck Virlo transcribed nothing from carries `["", "", ""]`, which is truthy and would
        # otherwise win this pick over the topic's one genuinely transcribed deck.
        panel_texts=list(next((post.panel_texts for post in posts
                               if any(text.strip() for text in post.panel_texts)), [])),
        video_descriptions=_texts(raws, "description"),
        # Virlo's OWN classification of the winning posts (A13). FR-100 asks the copywriter to
        # derive a hook pattern in prose that the source already labels — `story_tease`,
        # `tutorial_promise`, `text_hook` — so these replace guesswork with the source's own
        # vocabulary. Read per row and absent-safe: the agent-level `data_intelligence_enabled`
        # flag gates NEW enrichment only, and a monitor reporting `false` still carries populated
        # `intelligence` on rows enriched earlier (34/50 measured on exactly such a monitor).
        hook_types=_labels(raws, "hook_type"),
        visual_hook_types=_labels(raws, "visual_hook_type"),  # videos only; slideshows omit it
        emotional_tones=_labels(raws, "emotional_tone"),
        hashtags=_tags(raws),  # A14 — reference material for the copy call, never a mandate
        is_slideshow=sum(1 for post in posts if post.is_slideshow) * 2 > len(posts),
        virlo_url=next((post.url for post in posts if post.url), None),
        total_views=int(sum(views)),
        median_views=int(statistics.median(views)) if views else 0,
        newest_published_at=max((post.published_at for post in posts if post.published_at),
                                default=None),
        engagement=engagement,
    )
    item.strength_components = {"total_views": float(item.total_views),
                                "median_views": float(item.median_views),
                                "velocity": _velocity(raws),
                                "engagement": float(sum(engagement.values()))}
    return item


def _topic_why(theme: _Theme, facts: _MonitorFacts) -> str:
    """This topic's `why_it_works`: the monitor's own reading, then the theme's own — bounded,
    because it reaches prompts."""
    theme_part = f"{theme.name}: {theme.why_it_works}" if theme.why_it_works else ""
    return " · ".join(part for part in (facts.why_it_works, theme_part) if part)[:_WHY_MAX_CHARS]


def _topic_tactics(theme: _Theme, facts: _MonitorFacts) -> list[str]:
    """The theme's own tactics first, the monitor's general ones after, deduped and capped — a
    topic is judged on its own material before the monitor's."""
    tactics: list[str] = []
    for value in (*theme.tactics, *facts.tactics):
        if value and value not in tactics:
            tactics.append(value)
    return tactics[:_MAX_TACTICS]


# ------------------------------------------------------- forensic events (FR-298)

#: The consumption ledger's other half: every field this adapter READS, per payload shape. Kept
#: beside nothing else on purpose — a field added to `_topic_item` and forgotten here shows up in
#: `virlo_fields.ignored`, which is the cheapest possible reminder and the point of the event.
_CONSUMED_ANALYSIS = frozenset({
    "name", "why_it_works", "themes", "viral_tactics", "key_highlight", "connecting_thread",
    "timing_pattern", "peak_hours"})
_CONSUMED_THEME = frozenset({"name", "why_it_works", "confidence", "tactics", "evidence_video_ids"})
#: `panel_count`, `image_urls` and `intelligence_status` joined the consumed set in v2.1.0 — the
#: three fields the ledger had been reporting as `ignored` on every single run while the deck they
#: describe was the whole product (D46 §1). They are read by `_source_post` (onto `SourcePost`),
#: by the FR-305 gate and by the slide-intelligence tier that reads the slides themselves.
_CONSUMED_POST = frozenset({
    # The three display-name candidates are consumed the moment one of them exists (`_author_name`);
    # listing them keeps the ledger honest on the day a payload starts carrying one, instead of
    # reporting a field we DO read as ignored.
    *_AUTHOR_NAME_KEYS,
    "id", "url", "author_username", "description", "summary", "views", "likes", "shares",
    "comments", "bookmarks", "hashtags", "hook_text", "text_overlay_content", "panel_texts",
    "panel_count", "image_urls", "intelligence_status",
    "hook_type", "visual_hook_type", "emotional_tone", "publish_date"})


def _topic_posts_event(log: LogWriter | None, item: TrendItem) -> None:
    """FR-298's `topic_posts`: EVERY post of this topic, in rank order — the "which posts exactly"
    answer, in one record.

    Post-level view counts reach no other machine surface (the sort is applied silently and
    `mcp_call` logs no arguments), and post rank now picks the verbatim copy: the `P<n>` ordinals
    here ARE §1.7's reference labels, so this record is what makes a rendered caption traceable to
    a real post afterwards without re-running anything.

    The per-post shape gained four keys in v2.1.0 (FR-155's event-shape amendment), and each
    answers a question the D46 post-mortem could not: `published_at` — *how old was the post we
    quoted?* (the answer was "from 2023", and no log said so); `panel_count`/`image_count` — *was
    this deck rich enough to carry a carousel, and did every slide have a picture?*; `format` and
    `vision_status` — *which rows the slide-intelligence tier will read, and which Virlo had
    already enriched*. `published_at` is a plain ISO date or `null`; nothing downstream parses a
    timestamp out of this record.

    `verbose_only` keeps run.log readable — events.jsonl always receives it, which is where a
    forensic question is answered, and FR-297b prints the head of this same list to the console.
    """
    if log is None or not item.posts:
        return
    log.event("topic_posts",
              f"{item.name}: {len(item.posts)} post(s), P1 at {item.posts[0].views:,} views "
              f"down to {item.posts[-1].views:,}",
              verbose_only=True, trend=item.history_key, topic=item.topic_key,
              posts=[{"post_id": post.post_id, "url": post.url, "author": post.author,
                      "views": post.views,
                      "published_at": (post.published_at.date().isoformat()
                                       if post.published_at else None),
                      "format": "slideshow" if post.is_slideshow else "video",
                      "panel_count": post.panel_count,
                      "image_count": len(post.image_urls),
                      "vision_status": post.intelligence_status}
                     for post in item.posts])


def _fields_event(log: LogWriter | None, monitor_id: str, analysis: Mapping[str, Any],
                  videos: Sequence[Any], shows: Sequence[Any],
                  items: Sequence[TrendItem]) -> None:
    """FR-298's `virlo_fields` — the per-monitor consumption ledger.

    Three questions nobody could answer without a debugger: what did Virlo actually send for this
    monitor, which of those fields did the adapter read, and which did it ignore. The third is the
    interesting one — a field that appears under `ignored` on every run is either a gap here or
    dead weight in the wrapper, and until this event existed the two looked identical from outside
    (`evidence_video_ids`, dropped by the wrapper's `_norm_theme`, is exactly that case).
    """
    if log is None:
        return
    ledger = {"analysis": _field_ledger([analysis], _CONSUMED_ANALYSIS),
              "theme": _field_ledger(analysis.get("themes") or [], _CONSUMED_THEME),
              "video": _field_ledger(videos, _CONSUMED_POST),
              "slideshow": _field_ledger(shows, _CONSUMED_POST)}
    ignored = sorted({name for entry in ledger.values() for name in entry["ignored"]})
    log.event("virlo_fields",
              f"monitor {monitor_id}: {len(videos)} video(s) + {len(shows)} slideshow(s) -> "
              f"{len(items)} topic(s); ignored {', '.join(ignored) or 'nothing'}",
              verbose_only=True, monitor_id=str(monitor_id), topics=len(items),
              fields=ledger, ignored=ignored)


def _field_ledger(rows: Sequence[Any], consumed: Collection[str]) -> dict[str, list[str]]:
    """One payload shape's `present` / `consumed` / `ignored` key lists.

    `present` is the UNION across rows, not the first row's keys: `intelligence.*` is absent until
    a row is enriched, so a first-row sample would report the adapter ignoring nothing while it
    ignored a field on the other ninety-nine.
    """
    present = sorted({str(key) for row in rows if isinstance(row, Mapping) for key in row})
    return {"present": present,
            "consumed": sorted(name for name in consumed if name in present),
            "ignored": sorted(name for name in present if name not in consumed)}


def _ranked_event(log: LogWriter | None, items: Sequence[TrendItem],
                  raw: Mapping[str, Mapping[str, float]]) -> None:
    """FR-298's `topic_ranked`: the ranking table's rows, with RAW components beside normalized.

    Both halves, because min-max is lossy in exactly the way that matters to the question being
    asked: `total_views: 1.0` says a topic led the pool, never whether it led by 3% or by 300x.
    FR-5 requires the full ranked list with each component in the run log, so unlike the other two
    forensic events this one is NOT `verbose_only`.
    """
    if log is None or not items:
        return
    rows = [{"rank": rank, "topic_key": item.topic_key, "history_key": item.history_key,
             "name": item.name, "monitor_id": item.monitor_id, "posts": len(item.posts),
             "views": item.total_views, "median_views": item.median_views,
             "engagement": int(sum(item.engagement.values())),
             "confidence": item.confidence, "is_slideshow": item.is_slideshow,
             "strength": item.strength, "components": dict(item.strength_components),
             "components_raw": {name: round(value, 4)
                                for name, value in raw.get(item.history_key, {}).items()}}
            for rank, item in enumerate(items, start=1)]
    log.event("topic_ranked",
              f"{len(rows)} topic(s) ranked; strongest {items[0].name} at {items[0].strength:.4f}",
              topics=rows)


def _post_id(row: Mapping[str, Any], monitor_id: str, index: int) -> str:
    """This post's identity for FR-7's window: Virlo's own stable `id` (20 §3), else its url, else
    its monitor-scoped position — `index` runs across slideshows THEN videos, so the two arrays
    cannot collide. NEVER `id(row)`: `_dedupe`'s memory-address fallback differs on every run and
    would silently turn freshness off while reporting success.
    """
    return str(row.get("id") or row.get("url") or f"{monitor_id}:{index}")


def _analysis_fields(analysis: Mapping[str, Any],
                     cap: int) -> tuple[str, list[str], str, float | None]:
    """The monitor AGGREGATE: `why_it_works`, tactics, this monitor's own context, its confidence.

    RESULTS.md §A puts all four on the monitor, not on the digest 20 §3 credits — so this is where
    FR-9/FR-14's tactics and timing inputs come from, and where the aggregate confidence is
    sourced: the MEAN over the consumed themes, since the digest's `global_confidence` is null on
    every live trend. Absent-safe, and bounded: these reach prompts.

    `cap` is `sources.virlo_topics_per_monitor` — it replaced the old `_MAX_THEMES = 3` in BOTH of
    that constant's roles, because post-pivot a consumed theme IS a topic and the two numbers can
    no longer differ without the aggregate text describing themes that produced no topic (or
    missing themes that did). Under the `-1` kill switch every theme is consumed: there is exactly
    one item, so its text and its confidence mean have to span the whole monitor.

    Post-pivot this whole aggregate reaches only ONE item — the synthesized topic of a monitor
    with no themes, or the kill switch's single item. A theme-backed topic reads its own theme
    (`_topic_why`, `_topic_tactics`, `_Theme.confidence`).
    """
    themes = analysis.get("themes") or []
    consumed = themes if cap < 0 else themes[:cap]
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
    """Strength in place: min-max each component across the run's FULL topic pool, then weight.

    The pool is every topic of every monitor, deliberately: a topic's own numbers are computed
    from its own posts (`_topic_item`), and normalizing them against the whole run is what makes
    "strongest first" mean something across monitors instead of nine separate rankings.

    Weights are renormalized over the components that actually exist, so a component the whole
    pool lacks drags nobody toward zero — it just leaves its share of weight to the components
    that arrived.
    """
    if not items:
        return
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
