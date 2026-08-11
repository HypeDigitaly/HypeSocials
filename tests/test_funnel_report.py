"""A19 / FR-155 — the Virlo funnel report: what came in, what survived, what a job will attach.

Across all 36 archived run folders a paid run's console said **nothing at all** about Virlo volume
between the launch block and the spend table, and four degradation counters (`reference_shortfall`,
`reference_image_dropped`, `trend_text_only`, `reference_free`) had never fired once — leaving an
operator unable to tell "nothing was lost" from "the counter is dead". `sources.Counters` plus
`runner._funnel_block()` is the answer, and this file locks the four properties that make it worth
printing:

1. **It fits the console.** Every line ≤78 characters (FR-286) in the healthy, degraded and
   zero-material shapes — and at Increment-B scale, where 20+ monitors and seven-digit counts must
   make the row packer WRAP onto continuation lines rather than overflow.
2. **It is ASCII where it counts.** `util.fit`'s docstring names `·`, `—`, `…` and `←` as the only
   non-ASCII glyphs proven safe on a legacy conhost. `→` is not among them and must never appear.
3. **The arithmetic reconciles.** input − dropped = output at every stage, asserted on the real
   captured Virlo page rather than on numbers a test author chose.
4. **It always prints.** Unlike `_restate`, which is gated on `assignment.dropped or interactive`,
   the funnel block is unconditional — "everything worked" is the answer the operator came for —
   and it sits ABOVE the per-trend detail in both preview modes, because `_verdict_block` emits
   ~8 lines per trend and would bury the rollup at Increment-B's 22 trends.

Everything is offline: `Counters` is a plain dataclass, `_funnel_block` a pure function of it, and
the one test that needs real volume reads `tests/fixtures/virlo/` from disk. No network, no MCP
subprocess, no `VIRLO_API_KEY`, no run folder.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from hypesocials import plan, previews, runner
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
    trend's name), so a recorder spelled `def event(self, name, message, **data)` collides with
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


def console_safe(block: str) -> None:
    """Every FR-286 rule the funnel owes, in one call: width, glyphs, and no `→`."""
    for line in block.splitlines():
        assert len(line) <= WIDTH, f"{len(line)} chars (FR-286 allows {WIDTH}): {line!r}"
        assert "→" not in line, f"the unsafe arrow glyph reached the console: {line!r}"
        stray = {char for char in line if ord(char) > 127} - SAFE_GLYPHS
        assert not stray, f"glyph(s) outside util.fit's proven-safe set {sorted(stray)}: {line!r}"


def labels(block: str) -> list[str]:
    """The label of every row that opened a new stage — continuation lines have a blank label."""
    return [line[2:2 + runner._FUNNEL_LABEL].strip()
            for line in block.splitlines()[1:] if line[2:3] != " "]


def continuations(block: str) -> list[str]:
    """Lines the row packer wrapped onto their own line rather than overflowing."""
    return [line for line in block.splitlines()[1:] if line.startswith(" " * 4) and line.strip()]


# --------------------------------------------------------------------------- the three shapes


def healthy() -> Counters:
    """The plan's own literal example (§3.4b), so the block this suite pins is the one designed."""
    return Counters(
        monitors_asked=3, monitors_failed=0, rows_per_call=50, download_cap=6, total_available=2674,
        videos_raw=150, slideshows_raw=139, videos_kept=145, slideshows_kept=133,
        slideshow_sets=74, frame_sets=33, slideshows_thin=26, families_thin=15,
        videos_in_sets=99, videos_in_thin_families=46,
        chosen_fresh=3, motion_tiers={"fresh_same_creator": 1, "fresh": 2},
        images_attempted=18, images_downloaded=18, trends_returned=3,
        verdict_seen=True, eligible=3,
        render_seen=True, jobs=6, trend_refs_min=3, trend_refs_max=3, inspiration_each=1,
        refs_total=24, trends_used=3)


def degraded() -> Counters:
    """The plan's degraded example: dead CDN urls, a text-only trend, two jobs with no trend left."""
    tally = healthy()
    tally.images_downloaded, tally.images_dead = 14, 4
    tally.trends_text_only = 1
    tally.jobs, tally.jobs_dropped = 4, 2
    tally.inspiration_each = 0
    tally.unusable, tally.excluded_by_history, tally.eligible = 1, 1, 1
    tally.chosen_fresh, tally.chosen_repeated, tally.chosen_last_resort = 1, 1, 1
    tally.motion_tiers = {"fresh": 1, "repeat": 1, "none": 1}
    return tally


def increment_b() -> Counters:
    """Increment B's shape: 22 monitors, seven-digit counts, all four motion tiers populated.

    Nothing here is achievable today — it is the arithmetic edge `_funnel_row`'s wrap exists for,
    and the plan says explicitly that nine themes must produce ONE block, not nine. If the packer
    ever stopped wrapping, this is the shape that catches it before an operator's console does.
    """
    return Counters(
        monitors_asked=22, monitors_failed=1, rows_per_call=100, download_cap=18,
        total_available=2_039_000,
        videos_raw=2_200_000, slideshows_raw=1_398_000,
        videos_kept=2_198_431, slideshows_kept=1_397_002,
        slideshow_sets=1_074_233, frame_sets=302_115, last_resort_sets=12,
        slideshows_thin=411_007, families_thin=98_222,
        chosen_fresh=1_234_567, chosen_repeated=9_876, chosen_last_resort=1_042,
        motion_tiers={"fresh_same_creator": 1_111_111, "fresh": 2_222_222,
                      "repeat": 3_333_333, "none": 4_444_444},
        images_attempted=1_800_000, images_downloaded=1_799_123, images_dead=877,
        trends_text_only=4_321, trends_returned=22,
        verdict_seen=True, eligible=1_234_567, excluded_by_history=222_222, unusable=33_333,
        render_seen=True, jobs=1_234_567, jobs_dropped=8_642, trend_refs_min=2, trend_refs_max=3,
        inspiration_each=1, refs_total=4_000_000, trends_used=22)


def nothing_returned() -> Counters:
    """Every monitor answered, none of them with a row — the shape a dead trial key produces."""
    return Counters(monitors_asked=3, monitors_failed=3, rows_per_call=100, download_cap=18)


ALL_SHAPES = {"healthy": healthy, "degraded": degraded, "increment_b": increment_b,
              "nothing_returned": nothing_returned, "untouched": Counters}


# --------------------------------------------------------------------------- FR-286: it fits


@pytest.mark.parametrize("shape", sorted(ALL_SHAPES))
def test_every_printed_line_fits_the_console_in_every_shape(shape: str) -> None:
    """FR-286 across the whole funnel surface, one shape at a time so a failure names it."""
    console_safe(runner._funnel_block(ALL_SHAPES[shape]()))


def test_the_healthy_block_names_every_stage_and_reads_as_the_plan_designed_it() -> None:
    block = runner._funnel_block(healthy())

    assert block.splitlines()[0].startswith("Virlo funnel")
    assert labels(block) == ["input", "sets", "chosen", "images", "verdict", "render"]
    assert "3 monitor(s) asked, 50 row(s) per call, 0 failed" in block
    assert "150 video(s) + 139 slideshow(s)" in block and "11 duplicate row(s) dropped" in block
    assert "107 coherent set(s) qualified" in block and "41 too thin" in block
    assert "3 fresh, 0 repeated, 0 last-resort" in block
    assert "motion 1 same-creator, 2 fresh" in block
    assert "18 of 18 downloaded, 0 dead URL" in block and "cap 6 per trend" in block
    assert "6 job(s) will attach 3 trend ref(s) + 1 inspiration each" in block
    assert len(block.splitlines()) == 7, "one block, seven lines — no wrapping at this scale"


def test_the_degraded_shape_names_the_loss_instead_of_the_cap() -> None:
    """The `images` row swaps its cap clause for the loss when a trend fell to text-only, and the
    `render` row gains the dropped-jobs clause. Both are what the operator is looking for."""
    block = runner._funnel_block(degraded())

    console_safe(block)
    assert "14 of 18 downloaded, 4 dead URL" in block
    assert "1 trend fell to text-only" in block and "cap 6 per trend" not in block
    assert "4 job(s) will attach 3 trend ref(s)" in block
    assert "2 dropped, no trend left" in block
    assert "1 eligible, 1 excluded by history, 1 unusable" in block


def test_a_run_where_virlo_returned_nothing_says_so_in_words() -> None:
    """The one shape that is not "print the zeros": `0 video(s) + 0 slideshow(s); 0 duplicate row(s)
    dropped` would dress a failed fetch as a clean funnel."""
    block = runner._funnel_block(nothing_returned())

    console_safe(block)
    assert "Virlo returned no video and no slideshow" in block
    assert "0 video(s)" not in block and "duplicate row(s) dropped" not in block
    assert labels(block) == ["input"], "no sets/chosen/images rows for material that never arrived"
    assert "3 monitor(s) asked" in block and "3 failed" in block


@pytest.mark.parametrize("shape", ["healthy", "degraded", "nothing_returned", "untouched"])
def test_at_todays_scale_nothing_is_lost_to_the_ellipsis(shape: str) -> None:
    """Fitting inside 78 columns is necessary but not sufficient — `fit()` is the LAST resort and
    it truncates. At the scale a run reaches today no row may reach it, or the operator is reading
    a number with its tail cut off and no sign that anything is missing.

    ⚠️ Deliberately NOT asserted for the Increment-B shape. There, single clauses like
    `"N eligible, N excluded by history, N unusable, N without images"` are one string with no
    clause boundary the packer can split on, so seven-digit counts do reach `fit()` and the row
    loses its tail. See this wave's report — it is a legibility gap that lands with Increment B,
    not one that exists today.
    """
    for line in runner._funnel_block(ALL_SHAPES[shape]()).splitlines():
        assert not line.endswith("…"), f"a count was cut at today's scale: {line!r}"


def test_increment_b_scale_wraps_onto_continuation_lines_rather_than_overflowing() -> None:
    """The row packer's reason to exist. Nine themes produce ONE block (a run-wide rollup), but the
    counts inside it grow — and a clause is never split, so a wrapped row reads as its own
    continuation rather than as a cut sentence."""
    block = runner._funnel_block(increment_b())

    console_safe(block)
    assert continuations(block), "the packer overflowed instead of wrapping"
    assert labels(block) == ["input", "sets", "chosen", "images", "verdict", "render"], \
        "22 monitors still produce ONE block with one row per stage"
    # A wrapped clause stays whole: no continuation line starts mid-number or mid-word.
    for line in continuations(block):
        assert not line.strip().startswith(("(", ",", ";")), line


def test_the_unsafe_arrow_never_appears_in_any_console_string_this_module_prints() -> None:
    """`->`, never `→`. The block, the A24 detail rows and the spend table's funnel row all pass
    through `_funnel_row`, so one sweep over every shape covers the lot."""
    printed = [runner._funnel_block(shape()) for shape in ALL_SHAPES.values()]
    printed.append(runner._spend_table(_summary(), healthy()))

    for block in printed:
        assert "→" not in block
        console_safe(block)
    assert "->" in printed[-1], "the spend table's funnel chain still uses the ASCII arrow"


def _summary() -> SpendSummary:
    return SpendSummary(
        headline="requested 6 creatives, delivered 5",
        rows=(SpendRow("20260811_1200_ab12_01image", "image", 0.04, 0.04, True),),
        by_format={"image": 0.04}, llm_usd=0.11, render_usd=0.20, total_usd=0.31, cap_usd=1.0,
        over_cap_usd=0.0, skipped_budget=0, skipped_other=1, cap_status="within the $1.00 cap")


def test_the_spend_tables_one_funnel_row_states_the_whole_chain_under_the_headline() -> None:
    """FR-84/FR-155: a run "shrunk by trend supply" must be legible beside the headline that says
    it delivered less than it was asked for."""
    table = runner._spend_table(_summary(), healthy())

    console_safe(table)
    row = next(line for line in table.splitlines() if line.startswith("  virlo"))
    assert "278 post(s) -> 107 set(s) -> 3 trend(s) -> 24 ref(s) on 6 job(s)" in row
    # …and a run with no Virlo material at all prints no row rather than a chain of zeros.
    assert "virlo" not in runner._spend_table(_summary(), nothing_returned())
    assert "virlo" not in runner._spend_table(_summary(), None)


# --------------------------------------------------------------------------- the arithmetic


def _corpus() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The real captured sorted page, through the real wrapper normalizers."""
    def body(name: str) -> dict[str, Any]:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    return ([virlo_server._norm_video(row)
             for row in body("videos_views_desc_limit100.json")["data"]["videos"]],
            [virlo_server._norm_slideshow(row)
             for row in body("slideshows_views_desc_limit100.json")["data"]["slideshows"]])


def _tallied(*, duplicate_page: bool = False) -> tuple[Counters, Any]:
    """One monitor's `TrendItem` built from the real page, with its own private tally.

    `duplicate_page` feeds the same rows twice, which is how the 11 repeated rows a real
    three-monitor run produced are reproduced offline — `virlo_payload` reported those as material
    until FR-155, so the dedupe leg of the reconciliation is the one that had actually lied.
    """
    videos, shows = _corpus()
    if duplicate_page:
        videos, shows = [*videos, *videos], [*shows, *shows]
    tally = Counters()
    item = virlo._build_item(MONITOR, {"name": "AI Trends Tracker", "why_it_works": "proof",
                                       "themes": []},
                             videos, shows, Config(), counters=tally)
    tally.trends_returned = 1
    return tally, item


def test_the_input_stage_reconciles_raw_minus_duplicates_equals_kept() -> None:
    """`virlo_payload` used to report `len(clips)`/`len(panels)` from BEFORE `_dedupe`, so the
    operator read what Virlo shipped and the pipeline used something smaller."""
    tally, _item = _tallied(duplicate_page=True)

    assert tally.posts_raw == 400, "both pages, twice"
    assert tally.posts_kept == 200, "…and every repeat dropped"
    assert tally.duplicates_dropped == tally.posts_raw - tally.posts_kept == 200
    assert tally.videos_kept + tally.slideshows_kept == tally.posts_kept
    assert "200 duplicate row(s) dropped" in runner._funnel_block(tally)


def test_the_sets_stage_accounts_for_every_row_the_input_stage_kept() -> None:
    """NFR-5's "every skip with its reason". Both `_MIN_PANELS` and `_MIN_THUMBS` rejections were
    silent until FR-155, which is how a live run discarded 41 of 148 candidate sources in silence.
    """
    tally, item = _tallied()

    assert tally.slideshows_kept == tally.slideshow_sets + tally.slideshows_thin
    assert tally.videos_kept == (tally.videos_in_sets + tally.videos_in_thin_families
                                 + tally.videos_without_thumbnail)
    assert tally.sets_qualified == tally.slideshow_sets + tally.frame_sets
    assert tally.sets_thin == tally.slideshows_thin + tally.families_thin
    # Every rejection carries a name, and the names add up to the thin count exactly.
    assert set(tally.rejection_reasons) <= {"slideshow_under_min_panels",
                                            "frame_family_under_min_thumbs",
                                            "video_without_thumbnail"}
    assert (tally.rejection_reasons.get("slideshow_under_min_panels", 0)
            + tally.rejection_reasons.get("frame_family_under_min_thumbs", 0)) == tally.sets_thin
    assert len(item.reference_groups) == tally.sets_qualified + tally.last_resort_sets


def test_the_choice_stage_classifies_every_returned_trend_exactly_once() -> None:
    """Four buckets, one trend each — a trend counted twice or not at all would make the `chosen`
    row disagree with the `verdict` row printed two lines below it."""
    tally, _item = _tallied()

    classified = (tally.chosen_fresh + tally.chosen_repeated + tally.chosen_last_resort
                  + tally.chosen_none)
    assert classified == tally.trends_returned == 1
    assert sum(tally.motion.values()) == tally.trends_returned
    assert set(tally.motion) == {"fresh_same_creator", "fresh", "repeat", "none"}, \
        "all four tiers always present, so a zero is visible rather than silent"


def test_the_images_stage_reconciles_attempted_minus_dead_equals_downloaded() -> None:
    tally = Counters()
    tally.add_downloads(attempted=18, downloaded=14)

    assert tally.images_attempted - tally.images_dead == tally.images_downloaded
    tally.add_downloads(attempted=6, downloaded=6)  # a second monitor folds in additively
    assert (tally.images_attempted, tally.images_downloaded, tally.images_dead) == (24, 20, 4)


def test_the_verdict_row_reconciles_with_the_three_buckets_select_actually_produced() -> None:
    """Recorded by the caller because Select owns the verdicts, so the two can drift. Asserted
    against a real `plan.select()` over the real corpus item rather than against chosen numbers."""
    tally, item = _tallied()
    selection = plan.select([item], Config(), {})

    tally.record_selection(eligible=len(selection.eligible), excluded=len(selection.excluded),
                           unusable=len(selection.unusable))

    assert tally.verdict_seen is True
    assert tally.eligible + tally.excluded_by_history + tally.unusable == len(selection.verdicts)
    assert len(selection.verdicts) == tally.trends_returned
    assert f"{tally.eligible} eligible" in runner._funnel_block(tally)


def test_absorbing_a_monitors_tally_sums_quantities_and_carries_the_ask() -> None:
    """The two-level accumulation: a monitor's counts ADD, the shape of the ask does not.

    `rows_per_call: 100` folded three times would read as 300 rows per call, which is the exact
    lie the run-wide rollup exists to avoid once Increment B makes one monitor several themes.
    """
    run_wide = Counters(monitors_asked=3, rows_per_call=100, download_cap=18)
    for _ in range(3):
        one_monitor = Counters()
        one_monitor.add_input(videos_raw=100, slideshows_raw=100, videos_kept=98,
                              slideshows_kept=97, total_available=2674)
        one_monitor.reject("slideshow_under_min_panels", 26)
        one_monitor.add_choice(fresh=True, has_set=True, last_resort=False, motion_tier="fresh")
        run_wide.absorb(one_monitor)

    assert (run_wide.rows_per_call, run_wide.download_cap) == (100, 18), "the ask is carried"
    assert run_wide.min_panels == virlo._MIN_PANELS and run_wide.min_frames == virlo._MIN_THUMBS
    assert run_wide.posts_raw == 600 and run_wide.posts_kept == 585
    assert run_wide.total_available == 3 * 2674
    assert run_wide.rejection_reasons == {"slideshow_under_min_panels": 78}
    assert run_wide.chosen_fresh == 3
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


def test_fr155_the_virlo_payload_line_reports_what_the_pipeline_read_not_what_virlo_shipped() -> None:
    """`virlo.py` passed `len(clips)`/`len(panels)` from BEFORE the dedupe, so the operator read
    the rows Virlo shipped and the pipeline used something smaller — 11 rows out on a real
    three-monitor run. The raw figures stay beside the deduped ones so the drop is measurable."""
    log = Recorder()
    videos, shows = _corpus()
    tally = Counters()
    item = virlo._build_item(MONITOR, {"name": "AI Trends Tracker", "why_it_works": "proof",
                                       "themes": []},
                             [*videos, *videos], [*shows, *shows], Config(), counters=tally)
    virlo._payload_event(log, item, tally)

    (_name, message, data), = [row for row in log.events if row[0] == "virlo_payload"]
    assert "after dedup 100 videos, 100 slideshows" in message
    assert (data["videos"], data["slideshows"]) == (100, 100)
    assert (data["videos_raw"], data["slideshows_raw"]) == (200, 200)
    assert data["duplicates_dropped"] == 200


# ------------------------------------------------------- unconditional, and above the detail


@pytest.mark.parametrize("shape", sorted(ALL_SHAPES))
def test_the_block_prints_for_every_shape_including_an_untouched_counters(shape: str) -> None:
    """Unlike `_restate` — gated on `assignment.dropped or session.opts.interactive`, so a clean
    `--yes` run printed nothing at all — the funnel is unconditional. There is no shape of
    `Counters` for which it returns an empty string, which is what makes the single unguarded
    `session.say(_funnel_block(...))` call in `runner._pipeline` honest."""
    block = runner._funnel_block(ALL_SHAPES[shape]())

    assert block.strip(), "a shape that prints nothing is a silence the operator cannot read"
    assert block.splitlines()[0].startswith("Virlo funnel")
    assert len(block.splitlines()) >= 2, "a header with no rows says nothing about the funnel"


def test_the_runner_says_the_funnel_unconditionally_and_restate_stays_gated() -> None:
    """The gating difference, read off the two call sites. `_restate`'s `session.say` sits under an
    `if`; the funnel's does not, and that asymmetry is the whole FR-155 decision."""
    pipeline = inspect.getsource(runner._pipeline)
    restate = inspect.getsource(runner._restate)

    said = next(line for line in pipeline.splitlines()
                if "say(_funnel_block(" in line)
    assert said.startswith("    session.say("), f"the funnel say is nested under a branch: {said!r}"
    assert "if assignment.dropped or session.opts.interactive:" in restate
    assert restate.index("if assignment.dropped") < restate.index("session.say(line)")


def test_the_funnel_prints_above_the_per_trend_detail_in_both_preview_modes() -> None:
    """FR-139/155. `previews._verdict_block` emits ~8 lines per trend; at Increment B's 22 trends
    that is 176 lines, and a rollup printed underneath them is a rollup nobody reads."""
    shallow = inspect.getsource(previews._preview)
    deep = inspect.getsource(previews._deep_stages)

    assert shallow.index("_funnel_block(session.counters)") < shallow.index("_verdict_block(")
    assert shallow.index("_funnel_block(session.counters)") < shallow.index("_sources_block(")
    assert deep.index("_funnel_block(session.counters)") < deep.index("_sources_block(")
    assert deep.index("_funnel_block(session.counters)") < deep.index("_analysis_block(")
    # Both previews reuse the runner's own block rather than forking one (D19).
    assert previews._funnel_block is runner._funnel_block


def test_the_paid_run_prints_the_funnel_before_any_per_trend_detail_too() -> None:
    pipeline = inspect.getsource(runner._pipeline)

    assert pipeline.index("_funnel_block(") < pipeline.index("_sources_block(")
    assert pipeline.index("_funnel_block(") < pipeline.index("_brief_block(")


# --------------------------------------------------------------------------- no trend names


def test_a_trend_name_cannot_reach_the_funnel_block_because_counters_cannot_hold_one() -> None:
    """The structural reason the block needs no `fit()` on its rows: the object it is built from
    has no string-valued field at all. Trend names are the one unbounded token in this pipeline,
    and every width guarantee above rests on their absence.

    The two dictionaries are keyed by a CLOSED vocabulary — four motion tiers and three rejection
    reasons, all spelled in `virlo.py` — so they cannot carry operator data either.
    """
    for spec in dataclasses.fields(Counters):
        assert spec.type in ("int", "bool", "dict[str, int]"), \
            f"Counters.{spec.name}: {spec.type} — a non-numeric field can carry a trend name"

    tally, item = _tallied()
    tally.record_selection(eligible=1, excluded=0, unusable=0)
    block = runner._funnel_block(tally)

    assert item.name and item.name not in block
    for word in item.name.split():
        assert word not in block, f"a trend-name token reached the funnel: {word!r}"
