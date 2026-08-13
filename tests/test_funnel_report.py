"""FR-155 — the Virlo funnel report, re-shaped for the topic pipeline (v2.0.0/v2.1.0).

The block is now the end-of-run reconciliation of FIVE stages — input -> topics -> filter ->
Select's verdicts -> the render COVERAGE row — and it prints **exactly once, at DONE**
(§1.10 rule 6). Three things about the old suite died with the media funnel:

1. **The `sets` / `chosen` / `images` rows are gone.** Virlo is a text-only source (D41), so there
   are no reference sets to qualify, no motion tier to classify and no CDN pass to survive. The
   render row briefly counted STYLE references instead — and D46/F3 excised that channel too
   (a meta-style is words, FR-17/18), so the row now states COVERAGE: how many jobs render,
   wearing how many distinct styles, over how many topics. There is no attachment forecast left
   in this block at all, and `style_refs_min` / `style_refs_max` / `refs_total` are gone from
   `Counters` with the window they measured.
2. **The funnel's three stage-gate placements are gone.** FR-296's stage headers carry the same
   counts the moment they become true, so a rollup printed three times would restate numbers the
   operator has already read; the block appears once, in `_package`, above the spend table.
3. **The spend table's `virlo` chain row is gone.** §1.10's rule is that a number appears in
   exactly ONE of {stage header, table, funnel, spend row}, and the funnel now prints directly
   above the spend table — repeating the chain there would double every count it carries.

What survives unchanged is why the block is worth printing at all, and this file pins it:

- **It fits the console.** Every ROW ≤78 characters (FR-286) in the healthy, degraded, empty and
  Increment-B shapes, and the row packer WRAPS rather than overflows at seven-digit counts.
  (The header overflow T3.5 pinned as a strict xfail was fixed in-wave: compact `available`
  count + `·` clause joins + a `wrapped` fallback — its test now passes plainly.)
- **It is ASCII where it counts.** `util.fit`'s docstring names `·`, `—`, `…` and `←` as the only
  non-ASCII glyphs proven safe on a legacy conhost. `→` is not among them and must never appear.
- **The arithmetic reconciles**, asserted on the real captured Virlo page and the real captured
  nine-theme analysis rather than on numbers a test author chose.
- **It always prints.** Unlike `_restate`, which is gated, the funnel is unconditional — "nothing
  was lost" is the answer the operator came for, and a dead counter must be distinguishable from
  a healthy zero.

Everything is offline: `Counters` is a plain dataclass, `_funnel_block` a pure function of it, and
the tests that need real volume read `tests/fixtures/virlo/` from disk. No network, no MCP
subprocess, no `VIRLO_API_KEY`, no run folder.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from hypesocials import previews, runner
from hypesocials.budget import SpendRow, SpendSummary
from hypesocials.config import Config
from hypesocials.sources import Counters
from hypesocials.sources import virlo
from hypesocials.virlo_mcp import server as virlo_server

FIXTURES = Path(__file__).parent / "fixtures" / "virlo"
MONITOR = "9c96fddf-dc35-4be0-bbd9-12f4d22aea12"

#: FR-286's console width, read off the runner so a widened console cannot silently pass this file.
WIDTH = runner._FUNNEL_WIDTH

#: `util.fit`'s proven-safe set, quoted from its own docstring. Anything else non-ASCII on a
#: printed line is a mojibake risk on the cp1252 console this tool actually runs on.
SAFE_GLYPHS = frozenset("·—…←")


# --------------------------------------------------------------------------- shared assertions


class Recorder:
    """`LogWriter`'s event surface, with POSITIONAL-ONLY heads.

    Both loggers under test pass a `name=` keyword of their own (`virlo_payload` carries the
    topic's name), so a recorder spelled `def event(self, name, message, **data)` collides with
    the code it is recording — which is a fixture bug that reads exactly like a production one.
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def event(self, event_type: str, message: str = "", /, **data: Any) -> None:
        self.events.append((event_type, message, data))

    warn = event
    error = event

    def named(self, event_type: str) -> list[tuple[str, dict[str, Any]]]:
        return [(message, data) for name, message, data in self.events if name == event_type]


def glyph_safe(block: str) -> None:
    """The glyph half of FR-286: nothing outside `util.fit`'s proven-safe set, and never `→`."""
    for line in block.splitlines():
        assert "→" not in line, f"the unsafe arrow glyph reached the console: {line!r}"
        stray = {char for char in line if ord(char) > 127} - SAFE_GLYPHS
        assert not stray, f"glyph(s) outside util.fit's proven-safe set {sorted(stray)}: {line!r}"


def console_safe(block: str) -> None:
    """Width AND glyphs, line by line — the whole of what FR-286 asks of a printed block."""
    glyph_safe(block)
    for line in block.splitlines():
        assert len(line) <= WIDTH, f"{len(line)} chars (FR-286 allows {WIDTH}): {line!r}"


def rows_of(block: str) -> str:
    """Everything under the header — the part `_funnel_row` lays out and guarantees the width of."""
    return "\n".join(block.splitlines()[1:])


def labels(block: str) -> list[str]:
    """The label of every row that opened a new stage — continuation lines have a blank label."""
    return [line[2:2 + runner._FUNNEL_LABEL].strip()
            for line in block.splitlines()[1:] if line[2:3] != " "]


def continuations(block: str) -> list[str]:
    """Lines the row packer wrapped onto their own line rather than overflowing."""
    return [line for line in block.splitlines()[1:] if line.startswith(" " * 4) and line.strip()]


# --------------------------------------------------------------------------- the four shapes


def healthy() -> Counters:
    """A three-monitor run that lost nothing: the shape §1.10's DONE block was designed around."""
    return Counters(
        monitors_asked=3, monitors_failed=0, rows_per_call=50, total_available=2674,
        videos_raw=150, slideshows_raw=139, videos_kept=145, slideshows_kept=133,
        posts_in=278, topics_out=9, topics_synthesized=0, trends_returned=9,
        filter_kept=8, filter_stripped=1, filter_skipped=0,
        verdict_seen=True, eligible=6, excluded_by_history=2, unusable=1,
        render_seen=True, jobs=6, jobs_dropped=0, topics_used=3, styles_used=3)


def degraded() -> Counters:
    """Every post-pivot loss at once: a competitor promo skipped, the filter's LLM layer failed
    open, two creatives that found no topic left, and the thinner coverage that follows — four
    jobs over two topics wearing two styles instead of six over three wearing three."""
    tally = healthy()
    tally.filter_kept, tally.filter_stripped, tally.filter_skipped = 6, 2, 1
    tally.filter_degraded = True
    tally.eligible, tally.excluded_by_history, tally.unusable = 1, 1, 1
    tally.jobs, tally.jobs_dropped = 4, 2
    tally.topics_used, tally.styles_used = 2, 2
    return tally


def increment_b() -> Counters:
    """The arithmetic edge the row packer exists for: 22 monitors and seven-digit counts.

    Nothing here is achievable today. Nine themes per monitor must still produce ONE block, not
    198 of them, and if the packer ever stopped wrapping this is the shape that catches it before
    an operator's console does.
    """
    return Counters(
        monitors_asked=22, monitors_failed=1, rows_per_call=100, total_available=2_039_000,
        videos_raw=2_200_000, slideshows_raw=1_398_000,
        videos_kept=2_198_431, slideshows_kept=1_397_002,
        posts_in=3_595_433, topics_out=198, topics_synthesized=4, trends_returned=198,
        filter_kept=1_234_567, filter_stripped=222_222, filter_skipped=33_333,
        verdict_seen=True, eligible=1_234_567, excluded_by_history=222_222, unusable=33_333,
        render_seen=True, jobs=1_234_567, jobs_dropped=8_642, topics_used=22, styles_used=8)


def nothing_returned() -> Counters:
    """Every monitor answered, none of them with a row — the shape a dead trial key produces."""
    return Counters(monitors_asked=3, monitors_failed=3, rows_per_call=100)


ALL_SHAPES = {"healthy": healthy, "degraded": degraded, "increment_b": increment_b,
              "nothing_returned": nothing_returned, "untouched": Counters}


# --------------------------------------------------------------------------- FR-286: it fits


@pytest.mark.parametrize("shape", sorted(ALL_SHAPES))
def test_every_printed_row_fits_the_console_in_every_shape(shape: str) -> None:
    """FR-286 across the funnel's rows, one shape at a time so a failure names it.

    The rows are what `_funnel_row` lays out, and its packer is the guarantee: a clause is never
    split, so a row that cannot fit wraps onto a continuation line rather than overflowing. The
    header is laid out by hand and is asserted separately below — it does NOT hold today.
    """
    block = runner._funnel_block(ALL_SHAPES[shape]())

    console_safe(rows_of(block))
    glyph_safe(block)  # the header's glyphs are fine; only its width is not


def test_fr286_the_funnel_header_fits_the_console_at_a_real_runs_scale() -> None:
    """FR-286: "no console line exceeds 78 columns". The header is a console line.

    `total_available` was promoted into the header by FR-297d so an operator can see how deep the
    one page each call asked for reaches into Virlo's own row total. It SUMS across monitors
    (`absorb`) and reaches seven digits on real runs, so the raw number overflowed the header —
    this test shipped as T3.5's strict xfail pinning that defect, and flipped to a plain pass
    when the conductor's fix landed: the header now prints FR-297's compact form (`2.7K
    available`) and wraps as a last resort (`util.wrapped`). Asserted at Increment-B scale too.
    """
    header = runner._funnel_block(healthy()).splitlines()[0]
    assert len(header) <= WIDTH, f"{len(header)} chars: {header!r}"

    big = healthy()
    big.monitors_asked, big.total_available = 22, 2_039_000
    for line in runner._funnel_block(big).splitlines():
        assert len(line) <= WIDTH, f"{len(line)} chars: {line!r}"


def test_the_healthy_block_names_every_surviving_stage_and_reads_as_designed() -> None:
    """The five rows of the post-pivot funnel, in pipeline order, with their exact wording."""
    block = runner._funnel_block(healthy())

    assert block.splitlines()[0].startswith("Virlo funnel")
    assert labels(block) == ["input", "dropped", "dropped", "dropped", "videos", "topics", "filter", "verdict", "render"]
    # Conductor fix for the FR-286 header overflow: `total_available` prints in FR-297's
    # compact form (2,674 -> 2.7K) and the clauses join on `·` — the raw figure stays in the
    # `collect_funnel` event.
    assert "3 monitor(s) asked · 50 rows/call · 0 failed · 2.7K available" in block
    assert "150 video(s) + 139 slideshow(s)" in block and "11 duplicate row(s) dropped" in block
    assert "278 post(s) split into 9 topic(s)" in block and "0 synthesized" in block
    assert "8 kept, 1 stripped, 0 skipped" in block
    assert "6 eligible, 2 excluded by history, 1 unusable" in block
    # D46/F3: coverage, not attachments — a style ships no pictures, so there is nothing per-job
    # left to forecast and the row answers "how widely was the registry actually used".
    assert "6 job(s) will render" in block
    assert "3 style(s) over 3 topic(s)" in block
    assert "style ref" not in block, "the attachment forecast retired with the picture channel"
    assert len(block.splitlines()) == 10, (
        "one block, ten lines — six stage rows plus the four always-printed gate rows "
        "(FR-305/307), no wrapping at this scale")


def test_every_withdrawn_reference_counter_is_gone_from_the_object_and_the_block() -> None:
    """Two excisions, one guarantee: no counter that measured a PICTURE survives anywhere.

    D41 killed the media funnel (Virlo is a text feed — no reference sets to qualify, no motion
    tier to classify, no CDN pass to survive) and D46/F3 killed the style reference window that
    briefly replaced it (a meta-style is words, FR-17/18). Both are asserted structurally — a
    slots dataclass rejects the field outright, which is stronger than populating it and proving
    it prints nothing — AND on the printed block, because a clause can outlive its counter.
    """
    tally = healthy()
    for dead_field in ("slideshow_sets", "frame_sets", "slideshows_thin", "chosen_fresh",
                       "motion_tiers", "images_attempted", "images_downloaded", "images_dead",
                       "trends_text_only", "trends_short", "rejection_reasons", "download_cap",
                       # D46/F3: the style-reference forecast, excised with the window it sized.
                       "style_refs_min", "style_refs_max", "refs_total"):
        assert not hasattr(tally, dead_field), \
            f"withdrawn reference counter survived the excision: {dead_field!r}"

    block = runner._funnel_block(tally)

    assert labels(block) == ["input", "dropped", "dropped", "dropped", "videos", "topics", "filter", "verdict", "render"]
    for dead in ("set(s)", "coherent", "motion", "downloaded", "dead URL", "text-only",
                 "inspiration", "trend ref", "style ref", "will attach"):
        assert dead not in block, f"a withdrawn reference clause reached the funnel: {dead!r}"


def test_the_degraded_shape_names_every_loss_it_carries() -> None:
    """The clauses that only appear when something went wrong — each one is what the operator is
    looking for when the run delivered less than the plan asked for."""
    block = runner._funnel_block(degraded())

    console_safe(rows_of(block))
    assert "6 kept, 2 stripped, 1 skipped" in block
    assert "LLM layer degraded — blocklist only" in block
    assert "1 eligible, 1 excluded by history, 1 unusable" in block
    assert "4 job(s) will render" in block
    assert "2 style(s) over 2 topic(s)" in block, (
        "thinner coverage is itself a loss the operator is looking for — a batch drawn from two "
        "topics wearing two styles repeats itself in a way six over three does not")
    assert "2 dropped, no topic left" in block


def test_a_run_where_virlo_returned_nothing_says_so_in_words() -> None:
    """The one shape that is not "print the zeros": `0 video(s) + 0 slideshow(s); 0 duplicate
    row(s) dropped` would dress a failed fetch as a clean funnel. The topics row goes with it —
    "0 posts split into 0 topics" is arithmetic about material that never arrived."""
    block = runner._funnel_block(nothing_returned())

    console_safe(rows_of(block))
    assert "Virlo returned no video and no slideshow" in block
    assert "0 video(s)" not in block and "duplicate row(s) dropped" not in block
    assert labels(block) == ["input", "dropped", "dropped", "dropped", "videos"], (
        "no topics/filter/verdict rows for material never collected; the gate rows still "
        "print so 'not called' is distinguishable from 'nothing found' (FR-305/307)")
    assert "3 monitor(s) asked" in block and "3 failed" in block


def test_a_healthy_zero_still_prints_its_row() -> None:
    """**Zeros are the point.** Four pre-pivot counters fired in NONE of the archived runs, which
    left an operator unable to tell "nothing was lost" from "the counter is dead". Every stage
    that RAN prints, whatever its numbers — the empty-fetch shape above is the only exception."""
    tally = healthy()
    tally.filter_stripped = tally.filter_skipped = 0
    tally.excluded_by_history = tally.unusable = 0
    tally.jobs_dropped = 0
    tally.topics_used = tally.styles_used = 0

    block = runner._funnel_block(tally)

    assert "0 stripped, 0 skipped" in block
    assert "0 excluded by history, 0 unusable" in block
    # A registry-less preview records zero coverage honestly rather than omitting the clause —
    # "0 style(s) over 0 topic(s)" beside a job count is a visible contradiction the operator can
    # act on; a missing clause is one they cannot even see.
    assert "0 style(s) over 0 topic(s)" in block


@pytest.mark.parametrize("shape", ["healthy", "degraded", "nothing_returned", "untouched"])
def test_at_todays_scale_nothing_is_lost_to_the_ellipsis(shape: str) -> None:
    """Fitting inside 78 columns is necessary but not sufficient — `fit()` is the LAST resort and
    it truncates. At the scale a run reaches today no row may reach it, or the operator is reading
    a number with its tail cut off and no sign that anything is missing.

    ⚠️ Deliberately NOT asserted for the Increment-B shape. There, single clauses like
    `"N eligible, N excluded by history, N unusable"` are one string with no clause boundary the
    packer can split on, so seven-digit counts do reach `fit()` and the row loses its tail. That
    is a legibility gap that lands with Increment B, not one that exists today.
    """
    for line in runner._funnel_block(ALL_SHAPES[shape]()).splitlines():
        assert not line.endswith("…"), f"a count was cut at today's scale: {line!r}"


def test_increment_b_scale_wraps_onto_continuation_lines_rather_than_overflowing() -> None:
    """The row packer's reason to exist. 22 monitors × 9 themes produce ONE block (a run-wide
    rollup), but the counts inside it grow — and a clause is never split, so a wrapped row reads
    as its own continuation rather than as a cut sentence."""
    block = runner._funnel_block(increment_b())

    console_safe(rows_of(block))
    assert continuations(block), "the packer overflowed instead of wrapping"
    assert labels(block) == ["input", "dropped", "dropped", "dropped", "videos", "topics", "filter", "verdict", "render"], \
        "22 monitors still produce ONE block with one row per stage"
    # A wrapped clause stays whole: no continuation line starts mid-number or mid-word.
    for line in continuations(block):
        assert not line.strip().startswith(("(", ",", ";")), line


def test_the_unsafe_arrow_never_appears_in_any_console_string_this_module_prints() -> None:
    """`->`, never `→` (FR-155). One sweep over every shape plus the spend table covers the lot."""
    printed = [runner._funnel_block(shape()) for shape in ALL_SHAPES.values()]
    printed.append(runner._spend_table(_summary()))

    for block in printed:
        glyph_safe(block)


# --------------------------------------------------------------------------- the spend table


def _summary() -> SpendSummary:
    return SpendSummary(
        headline="requested 6 creatives, delivered 5",
        rows=(SpendRow("Li_img_ai-agents-that-ship_01", "image", 0.04, 0.04, True),),
        by_format={"image": 0.04}, llm_usd=0.11, render_usd=0.20, total_usd=0.31, cap_usd=1.0,
        over_cap_usd=0.0, skipped_budget=0, skipped_other=1, cap_status="within the $1.00 cap")


def test_the_spend_table_no_longer_restates_the_funnel_chain() -> None:
    """§1.10 rule 5: a number appears in exactly ONE of {stage header, table, funnel, spend row}.

    The funnel prints directly above this table at DONE, so the single-line `virlo` chain row the
    table used to carry would double every count the block already states — and `_spend_table`
    consequently takes the summary alone, with no `Counters` parameter left to disagree with.
    """
    assert list(inspect.signature(runner._spend_table).parameters) == ["summary"]

    table = runner._spend_table(_summary())

    console_safe(table)
    assert "virlo" not in table and "post(s)" not in table
    assert table.splitlines()[0] == "requested 6 creatives, delivered 5"
    assert "TOTAL  llm" in table and "within the $1.00 cap" in table


# --------------------------------------------------------------------------- the arithmetic


def _corpus() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The real captured sorted page, through the real wrapper normalizers."""
    def body(name: str) -> dict[str, Any]:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    return ([virlo_server._norm_video(row)
             for row in body("videos_views_desc_limit100.json")["data"]["videos"]],
            [virlo_server._norm_slideshow(row)
             for row in body("slideshows_views_desc_limit100.json")["data"]["slideshows"]])


def _analysis(*, themed: bool) -> dict[str, Any]:
    """The real captured nine-theme `analysis_data`, or the degenerate no-theme monitor."""
    detail = json.loads((FIXTURES / "agent_detail.json").read_text(encoding="utf-8"))
    analysis = dict(detail["data"]["analysis_data"]) if themed else {"why_it_works": "proof",
                                                                     "themes": []}
    analysis["name"] = "AI Trends Tracker"
    return analysis


def _all_time() -> Config:
    """The config the captured corpus must be read under (FR-301/FR-305).

    `tests/fixtures/virlo/` is a pre-D46 `views desc` capture spanning 2023-11 to 2026-07, i.e.
    exactly the all-time pool the 30-day window now refuses — so under the shipped default every
    row lands in `dropped_stale` and the reconciliation below would be measuring the gate rather
    than the dedupe and the split. The window's own arithmetic is asserted separately, on rows
    dated relative to now.
    """
    cfg = Config()
    cfg.sources.max_post_age_days = 0  # FR-301's documented off switch
    cfg.sources.include_videos = True  # the corpus carries 100 video rows; count them
    return cfg


def _tallied(*, themed: bool = True, duplicate_page: bool = False) -> tuple[Counters, list[Any]]:
    """One monitor's topics built from the real page, with its own private tally.

    `duplicate_page` feeds the same rows twice, which is how the 11 repeated rows a real
    three-monitor run produced are reproduced offline — `virlo_payload` reported those as material
    until FR-155, so the dedupe leg of the reconciliation is the one that had actually lied.
    """
    videos, shows = _corpus()
    if duplicate_page:
        videos, shows = [*videos, *videos], [*shows, *shows]
    tally = Counters()
    items = virlo._split_topics(MONITOR, _analysis(themed=themed), videos, shows, _all_time(),
                                counters=tally)
    tally.trends_returned = len(items)
    return tally, items


def test_the_input_stage_reconciles_raw_minus_duplicates_equals_kept() -> None:
    """`virlo_payload` used to report `len(clips)`/`len(panels)` from BEFORE `_dedupe`, so the
    operator read what Virlo shipped and the pipeline used something smaller."""
    tally, _items = _tallied(duplicate_page=True)

    assert tally.posts_raw == 400, "both pages, twice"
    assert tally.posts_kept == 200, "…and every repeat dropped"
    assert tally.duplicates_dropped == tally.posts_raw - tally.posts_kept == 200
    assert tally.videos_kept + tally.slideshows_kept == tally.posts_kept
    assert "200 duplicate row(s) dropped" in runner._funnel_block(tally)


def test_the_topics_stage_accounts_for_every_post_the_input_stage_kept() -> None:
    """FR-293's split, on the real page and the real nine-theme analysis: the posts are dealt out
    EXCLUSIVELY, so nothing is lost between input and topics and nothing is counted twice.

    `posts_in` is recorded once PER MONITOR, never per topic — nine topics each reporting the
    monitor's 200 rows would be 1,800, the same over-reporting defect the dedupe fix closed one
    level up, and the two-level `absorb` seam is what prevents it.
    """
    tally, items = _tallied()

    assert tally.posts_in == tally.posts_kept == 200
    assert tally.topics_out == len(items) == 9
    assert tally.topics_synthesized == 0
    assert sum(len(topic.posts) for topic in items) == tally.posts_in
    assert len({post.post_id for topic in items for post in topic.posts}) == tally.posts_in
    assert "200 post(s) split into 9 topic(s)" in runner._funnel_block(tally)


def test_a_monitor_with_no_themes_synthesizes_exactly_one_topic_and_says_so() -> None:
    """FR-293's never-fewer-items invariant: zero themes synthesizes ONE topic from the monitor
    aggregate — the pre-pivot item shape. The funnel's `N synthesized` clause is what makes that
    fallback visible instead of indistinguishable from a real one-theme monitor."""
    tally, items = _tallied(themed=False)

    assert len(items) == tally.topics_out == 1
    assert tally.topics_synthesized == 1
    assert "200 post(s) split into 1 topic(s)" in runner._funnel_block(tally)
    assert "1 synthesized" in runner._funnel_block(tally)


def test_the_three_drop_reasons_print_as_their_own_rows_even_when_every_one_is_zero() -> None:
    """FR-155's post-level drop vocabulary, sourced from the adapter (one-place rule).

    The WORDS live beside the counters in `sources/virlo.py` — a reason renamed in the funnel
    block and not in the gate would put a stale sentence beside a fresh number, and the operator
    would have no way to tell which of the two was lying. `runner._funnel_block` splices these
    rows into the printed block (W2 wire-in); what is pinned here is that they exist, that they
    print at zero, and that they survive the runner's own packer inside FR-286's 78 columns.
    """
    tally = healthy()
    tally.add_drops(stale=12, unenriched=3, used=1)

    rows = tally.drop_rows()
    printed = [line for label, clauses in rows for line in runner._funnel_row(label, *clauses)]

    assert [label for label, _clauses in rows] == ["dropped", "dropped", "dropped", "videos"]
    assert "12 stale" in printed[0] and "3 unenriched" in printed[1] and "1 used" in printed[2]
    console_safe("\n".join(printed))

    # Zeros print. "The window dropped nothing" and "the counter is dead" are the two readings a
    # missing line cannot tell apart, which is the NFR-5 failure the whole funnel exists to close.
    empty = [line for label, clauses in Counters().drop_rows()
             for line in runner._funnel_row(label, *clauses)]
    assert len(empty) == 4
    assert "0 stale" in empty[0] and "0 unenriched" in empty[1] and "0 used" in empty[2]


def test_the_video_row_says_disabled_in_words_rather_than_printing_a_row_of_zeros() -> None:
    """FR-301/§0.2: `include_videos: false` means `get_top_videos` is never called. "We did not
    ask" and "this monitor posts no videos" are different facts, only one of them is the
    operator's own decision, and zero video rows beside a slideshow count reads as the wrong one."""
    label, (off_clause,) = Counters(videos_disabled=True).drop_rows()[3]
    _label, (on_clause,) = Counters(videos_raw=140).drop_rows()[3]

    assert label == "videos"
    assert "disabled (slideshow-first)" in off_clause and "get_top_videos not called" in off_clause
    assert on_clause == "enabled — 140 row(s) fetched"
    console_safe("\n".join(runner._funnel_row(label, off_clause)))


def test_the_drop_counters_reconcile_the_input_stage_with_the_topics_stage() -> None:
    """The chain the block is read as, end to end: rows Virlo shipped, minus the repeats, minus
    the three eligibility reasons, IS what the split received. Asserted on the real corpus with a
    30-day window applied to a page that predates it — the drop is 200 rows, and the point is that
    all 200 are ACCOUNTED for rather than merely absent."""
    videos, shows = _corpus()
    tally = Counters()

    virlo._split_topics(MONITOR, _analysis(themed=True), videos, shows, Config(), counters=tally)

    assert tally.posts_kept == 200, "the dedupe kept the whole captured page"
    assert tally.dropped_ineligible == 200 - tally.posts_in
    assert tally.dropped_stale > 0, "a 2023-2026 all-time page against a 30-day window"
    assert tally.summary_line().count("ineligible") == 1


def test_the_filter_row_counts_every_verdict_exactly_once() -> None:
    """FR-294. `record_filter` is duck-typed on `.verdict`/`.reason`, so the funnel never imports
    the filter and the filter never imports the funnel — and the three buckets must therefore add
    up to the number of topics screened, with an unrecognised verdict counting as `keep` (the
    filter's own total-by-construction default) rather than vanishing.
    """
    from hypesocials.topic_filter import Verdict

    tally = Counters()
    verdicts = {1: Verdict(1), 2: Verdict(2, "strip", ["Acme"]),
                3: Verdict(3, "skip", reason="promotes Acme Cloud"),
                4: Verdict(4, "nonsense-from-a-model")}
    tally.record_filter(verdicts)

    assert (tally.filter_kept, tally.filter_stripped, tally.filter_skipped) == (2, 1, 1)
    assert tally.filter_kept + tally.filter_stripped + tally.filter_skipped == len(verdicts)
    assert tally.filter_degraded is False
    assert "2 kept, 1 stripped, 1 skipped" in runner._funnel_block(tally)


def test_the_filter_row_shows_the_fail_open_degrade() -> None:
    """§1.5: layer 2 fails OPEN — a dead model keeps every topic, with the blocklist still
    deciding. The funnel is where a run says it screened on half its evidence."""
    from hypesocials.topic_filter import Verdict

    tally = Counters()
    tally.record_filter({1: Verdict(1, reason="filter_degraded: model returned no JSON")})

    assert tally.filter_degraded is True
    assert "LLM layer degraded — blocklist only" in runner._funnel_block(tally)


def test_the_verdict_row_reconciles_with_the_three_buckets_select_actually_produced() -> None:
    """Recorded by the caller because Select owns the verdicts, so the two can drift. Asserted
    against a real `plan.select()` over the real corpus topics rather than against chosen numbers.
    """
    from hypesocials import plan

    tally, items = _tallied()
    selection = plan.select(items, Config(), {})

    tally.record_selection(eligible=len(selection.eligible), excluded=len(selection.excluded),
                           unusable=len(selection.unusable))

    assert tally.verdict_seen is True
    assert tally.eligible + tally.excluded_by_history + tally.unusable == len(selection.verdicts)
    assert len(selection.verdicts) == tally.trends_returned == tally.topics_out
    assert f"{tally.eligible} eligible" in runner._funnel_block(tally)


def test_the_render_row_states_coverage_rather_than_attachments() -> None:
    """D46/F3: `record_render` forecasts COVERAGE — jobs, distinct styles, distinct topics — and
    the per-job attachment count it used to take is gone with the window it measured.

    The old contract (item 13/15) was a RANGE, never an average: "2 style ref(s)" when every
    creative's window agreed, "0-2" when it did not, because an average invents a number no job
    will ever attach. That rule died honestly rather than quietly — a meta-style ships no
    pictures (FR-17/18), so there is no per-job count to average OR to range over, and the
    parameter was removed rather than left accepting a list nothing can fill. What replaces it
    answers the question the operator still has: how widely was the registry actually used?

    Two shapes, because they read differently: full coverage says nothing more, and a run that
    lost creatives to an exhausted topic pool prints the drop beside the narrower spread.
    """
    assert "style_refs" not in inspect.signature(Counters.record_render).parameters, \
        "the attachment forecast retired with the picture channel (D46/F3)"

    wide, narrow = Counters(), Counters()
    wide.record_render(jobs=3, dropped=0, topics_used=2, styles_used=3)
    narrow.record_render(jobs=3, dropped=1, topics_used=1, styles_used=1)

    assert (wide.render_seen, wide.jobs, wide.topics_used, wide.styles_used) == (True, 3, 2, 3)
    assert "3 job(s) will render" in runner._funnel_block(wide)
    assert "3 style(s) over 2 topic(s)" in runner._funnel_block(wide)
    assert "dropped, no topic left" not in runner._funnel_block(wide), \
        "a run that dropped nothing must not print a drop clause of zero"

    assert "1 style(s) over 1 topic(s)" in runner._funnel_block(narrow)
    assert "1 dropped, no topic left" in runner._funnel_block(narrow)


def test_absorbing_a_monitors_tally_sums_quantities_and_carries_the_ask() -> None:
    """The two-level accumulation (contracts item 15): a monitor's counts ADD, the shape of the
    ask does not.

    `rows_per_call: 100` folded three times would read as 300 rows per call — the exact lie the
    run-wide rollup exists to avoid now that one monitor really does produce nine topics.
    """
    run_wide = Counters(monitors_asked=3, rows_per_call=100)
    for _ in range(3):
        one_monitor = Counters()
        one_monitor.add_input(videos_raw=100, slideshows_raw=100, videos_kept=98,
                              slideshows_kept=97, total_available=2674)
        one_monitor.add_topics(posts_in=195, topics_out=9, synthesized=1)
        run_wide.absorb(one_monitor)

    assert run_wide.rows_per_call == 100, "the ask is carried, never summed"
    assert run_wide.posts_raw == 600 and run_wide.posts_kept == 585
    assert run_wide.duplicates_dropped == 15
    assert run_wide.total_available == 3 * 2674
    assert (run_wide.posts_in, run_wide.topics_out, run_wide.topics_synthesized) == (585, 27, 3)
    assert run_wide.verdict_seen is False and run_wide.render_seen is False


# ------------------------------------------------ FR-77: the two log lines A19 had to repair


def test_fr77_every_mcp_call_line_carries_the_row_count_the_prd_example_shows() -> None:
    """FR-77 bullet 1 quotes its own example — *"Virlo MCP: trends → 27 trends found"* — and the
    shipped line was `virlo MCP: get_top_videos -> ok (1971ms)`. It read identically whether Virlo
    returned a hundred rows or none, which made the single most consequential failure of a run —
    an empty answer from a healthy call — invisible in the one log a human reads.
    """
    from hypesocials.mcp_client import ServerConfig, Session, _row_count

    log = Recorder()
    session = Session(ServerConfig(name="virlo"), client=None, process=None, log=log)  # type: ignore[arg-type]
    videos, shows = _corpus()

    session._log_call("get_top_videos", "ok", 1971, _row_count({"videos": videos}))
    session._log_call("get_top_slideshows", "ok", 800, _row_count({"slideshows": shows}))
    session._log_call("get_top_videos", "ok", 12, _row_count({"videos": []}))
    session._log_call("get_monitor_analysis", "ok", 40, _row_count({"name": "AI Trends Tracker"}))

    messages = [message for _name, message, _data in log.events]
    assert messages[0] == "virlo MCP: get_top_videos -> ok, 100 row(s)"
    assert messages[1] == "virlo MCP: get_top_slideshows -> ok, 100 row(s)"
    assert messages[2] == "virlo MCP: get_top_videos -> ok, 0 row(s)", \
        "an empty answer from a healthy call is the failure this count exists to expose"
    assert messages[3] == "virlo MCP: get_monitor_analysis -> ok", \
        "a single record is not zero rows, and must not be logged as though it were"
    assert [data["rows"] for _n, _m, data in log.events] == [100, 100, 0, None]


def test_fr155_the_virlo_payload_line_reports_a_topics_own_posts_not_the_monitors() -> None:
    """FR-293 one level up from the dedupe fix: a TOPIC reports ITS OWN posts.

    Nine topics each printing one monitor-wide "100 videos, 100 slideshows" would be the same
    over-reporting the pre-FR-155 line was guilty of — it passed `len(clips)`/`len(panels)` from
    before `_dedupe`, so a real three-monitor run over-reported its material by 11 rows. The
    monitor-wide figures stay in `data` beside the topic's own, because the dedupe drop is a fact
    about the monitor and cannot be attributed to any one topic.
    """
    log = Recorder()
    tally, items = _tallied(duplicate_page=True)
    topic = items[0]
    virlo._payload_event(log, topic, tally)

    (message, data), = log.named("virlo_payload")
    assert data["posts"] == len(topic.posts) < tally.posts_kept
    assert data["videos"] + data["slideshows"] == len(topic.posts)
    assert f"after dedup {data['videos']} videos, {data['slideshows']} slideshows" in message
    assert (data["monitor_videos_kept"], data["monitor_slideshows_kept"]) == (100, 100)
    assert (data["videos_raw"], data["slideshows_raw"]) == (200, 200)
    assert data["duplicates_dropped"] == 200
    assert data["topic"] == topic.topic_key


# ---------------------------------------------- printed ONCE, at DONE, in the pinned order


@pytest.mark.parametrize("shape", sorted(ALL_SHAPES))
def test_the_block_prints_for_every_shape_including_an_untouched_counters(shape: str) -> None:
    """Unlike `_restate` — gated on `assignment.dropped or session.opts.interactive`, so a clean
    `--yes` run printed nothing at all — the funnel is unconditional. There is no shape of
    `Counters` for which it returns an empty string, which is what makes the single unguarded
    `session.say(_funnel_block(...))` call in `runner._package` honest."""
    block = runner._funnel_block(ALL_SHAPES[shape]())

    assert block.strip(), "a shape that prints nothing is a silence the operator cannot read"
    assert block.splitlines()[0].startswith("Virlo funnel")
    assert len(block.splitlines()) >= 2, "a header with no rows says nothing about the funnel"


def test_the_funnel_is_said_exactly_once_unconditionally_and_at_done() -> None:
    """FR-155 re-placed (§1.10 rule 6). The three pre-pivot stage-gate placements are superseded
    by FR-296's stage headers, which carry the same counts the moment they become true — so the
    block appears in `_package` alone, before the spend table, and nowhere else in the runner.

    The gating asymmetry with `_restate` is the whole FR-155 decision and is asserted beside it:
    the funnel's `session.say` sits at the function's own indent, `_restate`'s sits under an `if`.
    """
    module = Path(runner.__file__).read_text(encoding="utf-8")
    package = inspect.getsource(runner._package)
    restate = inspect.getsource(runner._restate)

    assert "_funnel_block" not in inspect.getsource(runner._pipeline)
    assert module.count("_funnel_block(") == 2, "the definition and exactly ONE call site"
    said = [line for line in package.splitlines() if "say(_funnel_block(" in line]
    assert len(said) == 1
    assert said[0].startswith("    session.say("), f"the funnel say is nested: {said[0]!r}"
    assert package.index("_funnel_block(") > package.index("_provenance_block(")
    assert package.index("_funnel_block(") < package.index("_spend_table(")

    assert "if assignment.dropped or session.opts.interactive:" in restate
    assert restate.index("if assignment.dropped") < restate.index("session.say(")


def test_the_pipeline_runs_the_stages_in_the_pinned_topic_first_order() -> None:
    """The plan's own stage order, read off `_pipeline`'s source (§1.10 / plan §3's W3 row):

        confirm -> collect -> screen_topics -> select -> assign
        -> assign_styles + assign_branding -> store_references -> write_copy -> create

    Textual order in the source is the only offline proxy for execution order, and it is enough:
    every one of these is a single awaited call in a straight-line coroutine. The two style calls
    live INSIDE `_assign_visuals`, so they are asserted against that function's own source.
    """
    pipeline = inspect.getsource(runner._pipeline)
    stages = ["_confirm(", "_collect(", "_screen_topics(", "_select(", "_assign_visuals(",
              "_store_references(", "_write(", "_create(", "_package("]
    positions = [pipeline.index(token) for token in stages]

    assert positions == sorted(positions), dict(zip(stages, positions))

    visuals = inspect.getsource(runner._assign_visuals)
    assert visuals.index("assign_styles(") < visuals.index("assign_branding(")
    # FILTER really does sit between Collect and Select — a `skip` must never reach Select, and
    # it is metered, so it must never run before the Confirm gate.
    assert pipeline.index("_screen_topics(") > pipeline.index("_confirm(")


def test_both_preview_modes_print_the_funnel_last_and_reuse_the_runners_own_block() -> None:
    """FR-139/140 + console-UX rule 6. The funnel used to sit ABOVE the per-trend detail because
    `_verdict_block` emitted ~8 lines per trend and would have buried the rollup; FR-297a's
    one-line-per-topic table removed that reason, so both previews now close with it — the same
    position a paid run puts it in.

    Both reuse `runner._funnel_block` rather than forking one (D19): two blocks would be two
    shapes free to disagree about the same run.
    """
    shallow = inspect.getsource(previews._shallow_stages)
    deep = inspect.getsource(previews._deep_stages)

    assert shallow.index("_topics_table(") < shallow.index("_funnel_block(session.counters)")
    for earlier in ("_topics_table(", "_post_roster(", "_assign_block(", "_copy_block("):
        assert deep.index(earlier) < deep.index("_funnel_block(session.counters)"), earlier
    assert previews._funnel_block is runner._funnel_block


# --------------------------------------------------------------------------- no topic names


def test_a_topic_name_cannot_reach_the_funnel_block_because_counters_cannot_hold_one() -> None:
    """The structural reason the block needs no `fit()` on its rows: the object it is built from
    has no string-valued field at all. Topic names are the one unbounded token in this pipeline,
    and every width guarantee above rests on their absence.

    The two dictionaries are keyed by a CLOSED vocabulary — four motion tiers and three rejection
    reasons, both spelled in `virlo.py` and both dying at W3.5 — so they cannot carry operator
    data either.
    """
    for spec in dataclasses.fields(Counters):
        assert spec.type in ("int", "bool", "dict[str, int]"), \
            f"Counters.{spec.name}: {spec.type} — a non-numeric field can carry a topic name"

    tally, items = _tallied()
    tally.record_selection(eligible=len(items), excluded=0, unusable=0)
    block = runner._funnel_block(tally)

    for topic in items:
        assert topic.name
        for word in topic.name.split():
            assert word not in block, f"a topic-name token reached the funnel: {word!r}"
