"""§1.10 / D45 — the console inventory: what a paid run SHOWS while it happens (FR-296–299).

The pre-pivot version of this file pinned `_sources_block` and `_brief_block` — the A24 answer to
"which posts these are and how our AI analysed them". Both died with the vision stage (v2.0.0).
What replaced them is a larger, stricter surface, and every property below is one the operator
asked for in words:

1. **Step by step** (FR-296) — numbered stage headers whose `[n/N]` is COMPUTED from the resolved
   plan. A brief-only run has no COLLECT/TOPICS/FILTER/SELECT and `vision_check: false` has no
   CHECK, so a hardcoded denominator is a lie in two ordinary shapes. Every header states counts
   in -> counts out, so a drop is arithmetic rather than a mystery.
2. **Proof they are sorted by views** (FR-297a) — the topics table prints ALL topics, strongest
   first, and the monotonically non-increasing `strn` column IS the proof. Its caption states the
   strength formula READ OFF `sources.STRENGTH_WEIGHTS`, so the sentence cannot drift from the
   adapter, and says the figures are each topic's OWN posts (§1.6's per-topic recompute).
3. **Which posts exactly** (FR-297b) — the roster's `P<n>` ordinals ARE the §1.7 reference labels
   the copy model is offered, and `-> NN` names the creative that quoted that post, which is what
   makes sibling divergence observable instead of grep-only.
4. **Where each creative came from** (FR-297c) — the provenance block maps every delivered
   creative back to its topic, style, signature, cost and the exact bytes it quoted.
5. **Never mute, never a ticker** (FR-299) — heartbeats are silence-breakers: a fast run prints
   none at all, and any printed line resets the clock. That is a property of `util.Pulse`, and it
   is asserted as one.
6. **A number appears in exactly ONE surface** (§1.10) — the FR-155 funnel prints once, at DONE,
   and the spend table no longer repeats the collect chain.

House rules asserted throughout: FR-286's 78 columns (URLs carved out onto their own line), no
ANSI, no `→` glyph, only `util.fit`'s proven-safe set. Offline: every surface here is a pure
function of plain dataclasses, the one filesystem leg uses `tmp_path`, no network, no keys, $0.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hypesocials import cli, generate, previews, render, runner, topic_filter
from hypesocials.config import Config
from hypesocials.models import (AssetRecord, CopySet, PlanEntry, PlanEntryStatus, RenderFailCause,
                                RenderOutcome, RenderOutcomeKind, RenderPriority, SourcePost,
                                TrendItem)
from hypesocials.util import Deadline, Pulse, Stopwatch

#: FR-286's ceiling, read off the runner so a widened console cannot silently pass this file.
WIDTH = runner._FUNNEL_WIDTH
#: `util.fit`'s proven-safe glyphs, quoted from its own docstring. `->` is the only arrow allowed
#: on a console line (FR-155 forbids `→`), and it is two ASCII characters.
SAFE_GLYPHS = frozenset("·—…←")


# --------------------------------------------------------------------------- shared assertions


def console_safe(block: str) -> None:
    """FR-286 with carve-out (a): every line ≤78 unless it is a bare URL alone on its line."""
    for line in block.splitlines():
        if line.strip().startswith("http"):
            assert line.split() == [line.strip()], \
                f"a URL must sit ALONE on its line so it stays copyable: {line!r}"
            continue
        assert len(line) <= WIDTH, f"{len(line)} chars (FR-286 allows {WIDTH}): {line!r}"
        assert "→" not in line, f"the forbidden arrow glyph reached the console: {line!r}"
        assert "\x1b" not in line, f"an ANSI escape reached the console: {line!r}"
        stray = {char for char in line if ord(char) > 127} - SAFE_GLYPHS
        assert not stray, f"glyph(s) outside util.fit's safe set {sorted(stray)}: {line!r}"


# --------------------------------------------------------------------------- the seam, as data


class Log:
    """`LogWriter`'s three surfaces, recorded. `narrative()` returns its input, exactly as the real
    redaction boundary does for text carrying no secret — so `say()`/`note()` print what they log.
    """

    def __init__(self) -> None:
        self.narrated: list[str] = []
        self.events: list[tuple[str, str, dict[str, Any]]] = []
        self.warnings: list[tuple[str, str]] = []

    def narrative(self, text: str) -> str:
        self.narrated.append(str(text))
        return str(text)

    def event(self, code: str, message: str = "", **fields: Any) -> None:
        self.events.append((code, message, fields))

    def warn(self, code: str, message: str = "", **fields: Any) -> None:
        self.warnings.append((code, message))

    def error(self, code: str, message: str = "", **fields: Any) -> None:
        self.warnings.append((code, message))


def session(*, stages: list[str] | None = None, verbose: bool = False,
            config: Config | None = None, run_dir: Path | None = None) -> runner._Session:
    """A real `_Session` with stub collaborators — `say`/`note`/`pulse` are the production ones.

    Nothing here opens a run folder, a ledger or a client: the console seam only needs the log's
    redaction boundary and the verbosity flag, and building the real thing is what keeps these
    tests honest about `say()` and `note()` rather than re-implementing them.
    """
    return runner._Session(
        config=config or Config(), opts=cli.Options(), control=runner.Control(),
        run_id="20260812_141207_k3xz", run_dir=run_dir or Path("output/20260812_141207_k3xz"),
        log=Log(), ledger=None, deadline=Deadline.from_minutes(25), clock=Stopwatch(),
        budget=None, engine=None, verbose=verbose,
        stages=list(stages) if stages is not None else [])


def printed(capsys: pytest.CaptureFixture[str]) -> list[str]:
    """Every line the console actually received since the last read."""
    return capsys.readouterr().out.splitlines()


# --------------------------------------------------------------------------- fixtures as data


#: The LONGEST permalink in the captured corpus (74 characters, `tests/fixtures/virlo/`). Chosen
#: deliberately: indented under a roster line it runs past 78 columns, so FR-286's carve-out (a) is
#: exercised rather than merely declared.
_PERMALINK = "https://www.tiktok.com/@ai_prompt_and_technology/photo/758029432720154959"


def post(post_id: str, author: str, views: int, *, hours: int = 48,
         slideshow: bool = True, caption: str = "") -> SourcePost:
    return SourcePost(
        post_id=post_id, url=f"https://www.tiktok.com/@{author}/photo/{post_id}", author=author,
        views=views, is_slideshow=slideshow,
        caption=caption or "AI agents do the work for you while you are asleep",
        published_at=datetime.now(timezone.utc) - timedelta(hours=hours))


def topic(name: str, *, monitor: str = "9c96fddf-dc35", strength: float = 0.5,
          views: int = 8_100_000, median: int = 1_700_000, posts: int = 3,
          **overrides: object) -> TrendItem:
    """A topic item carrying every field the three FR-297 surfaces read."""
    key = name.lower().replace(" ", "-")
    item = TrendItem(
        history_key=f"{monitor}::{key}", monitor_id=monitor, name=name, topic_key=key,
        strength=strength, total_views=views, median_views=median,
        virlo_url=_PERMALINK + str(posts),
        posts=[post(f"{key[:6]}-p{index}", f"creator{index}", views // (index + 1),
                    hours=24 * (index + 1)) for index in range(posts)])
    for field_name, value in overrides.items():
        setattr(item, field_name, value)
    return item


def entry(order: int, *, fmt: str = "image", trend: TrendItem | None = None, reuse: int = 0,
          style: str = "photoreal-ambient-caption", branded: bool = False) -> PlanEntry:
    return PlanEntry(
        order=order, asset_id=f"20260812_141207_k3xz_topic_{order + 1:02d}", creative_format=fmt,
        platform="linkedin", language="en", aspect_ratio="1:1",
        trend_key=trend.history_key if trend is not None else None, trend_reuse_index=reuse,
        style_key=style, branded=branded)


def record(item: PlanEntry, source: TrendItem | None = None, *, cost: float = 0.041,
           quoted: SourcePost | None = None, refs: dict[str, str] | None = None) -> AssetRecord:
    return AssetRecord(
        asset_id=item.asset_id, source=item.trend_key or "", platform="linkedin",
        source_name=source.name if source is not None else "", creative_format=item.creative_format,
        style_key=item.style_key, branded=item.branded, actual_cost_usd=cost,
        topic_key=source.topic_key if source is not None else "",
        copy_source_post_id=quoted.post_id if quoted is not None else "",
        copy_source_refs=dict(refs or ({"headline": "P1.hook.2"} if quoted is not None else {})))


# ------------------------------------------------ FR-296: stage narration, with a COMPUTED [n/N]


def test_fr296_the_stage_list_is_computed_from_the_resolved_plan_never_hardcoded() -> None:
    """A brief-only plan consumes no topic and `vision_check: false` runs no check, so the two
    ordinary shapes below have 4 and 9 stages (the v2.1.0 default plan is all-carousels, so
    INTEL is live — FR-306). A denominator typed at a call site is wrong in both.
    """
    config = Config()
    config.run.vision_check = False
    full = runner._live_stages(config, brief_only=False)
    brief_only = runner._live_stages(config, brief_only=True)
    config.run.vision_check = True
    checked = runner._live_stages(config, brief_only=False)
    config.run.formats = {"image": 2, "carousel": 0, "reel": 0}
    config.sources.include_videos = True  # §0.14e: images need the videos ask
    no_decks = runner._live_stages(config, brief_only=False)

    assert full == ["COLLECT", "TOPICS", "FILTER", "SELECT", "ASSIGN", "INTEL", "COPY",
                    "RENDER", "DONE"]
    assert len(full) == 9 and len(checked) == 10 and "CHECK" in checked
    assert "INTEL" not in no_decks, "a plan with no carousels has no source deck to read"
    assert brief_only == ["ASSIGN", "COPY", "RENDER", "DONE"], \
        "a pure-override plan has no Collect, no Topics, no Filter and no Select (10 §10)"
    assert all(stage in runner._STAGE_ORDER for stage in checked)
    assert checked == [stage for stage in runner._STAGE_ORDER if stage in checked], \
        "the live list keeps FR-296's pipeline order"
    assert full[-1] == brief_only[-1] == "DONE", "every run owes the operator a closing header"


def test_fr296_no_stage_counter_is_written_as_a_literal_anywhere() -> None:
    """The `[n/N]` tag exists in exactly one expression, built from `session.stages`. A literal
    `[3/9]` in any module would survive a stage being added or dropped and then miscount."""
    for module in (runner, previews):
        assert re.findall(r"\[\d+/\d+\]", inspect.getsource(module)) == [], module.__name__
    assert "session.stages.index(stage)" in inspect.getsource(runner._stage)


@pytest.mark.parametrize("vision,total,position", [(False, 9, 3), (True, 10, 3)])
def test_fr296_a_closing_header_reads_position_stage_body_and_elapsed(
    vision: bool, total: int, position: int, capsys: pytest.CaptureFixture[str],
) -> None:
    """`[n/N] STAGE  in -> out  elapsed` — the grammar of contracts item 16, measured.

    `n/N` moves with the live stage list (the CHECK-on run has one more stage, so the denominator
    changes and FILTER's numerator does not), the body states counts in -> counts out, and the
    elapsed is right-aligned in the tail.
    """
    config = Config()
    config.run.vision_check = vision
    live = session(stages=runner._live_stages(config, brief_only=False))

    runner._stage(live, "FILTER", "14 topic(s) -> 11 keep, 2 strip, 1 skip", elapsed_s=5.24)

    line = printed(capsys)[0]
    console_safe(line)
    assert line.startswith(f"[{position}/{total}] FILTER")
    assert "14 topic(s) -> 11 keep, 2 strip, 1 skip" in line
    assert line.endswith("5.2s") and line.rstrip() == line
    assert ("stage_complete", "FILTER: 14 topic(s) -> 11 keep, 2 strip, 1 skip") == \
        live.log.events[0][:2], "FR-298: one `stage_complete` event per header"


def test_fr296_a_stage_that_waits_opens_with_an_ellipsis_and_closes_with_the_elapsed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Stages with waits print twice — the opening form on submit (no elapsed to state yet), the
    closing form when the wait ends. An opening line that carried a duration would be a fiction."""
    live = session(stages=["COPY", "RENDER", "DONE"])

    runner._stage(live, "RENDER", "11 job(s) submitted (7 wave-1, 4 wave-2)", opening=True)
    runner._stage(live, "RENDER", "11 job(s) -> 10 ok, 1 failed", elapsed_s=221.0)

    opening, closing = printed(capsys)
    console_safe(opening)
    console_safe(closing)
    assert opening.startswith("[2/3] RENDER") and opening.endswith("...")
    assert not re.search(r"\d+(\.\d+)?s$", opening), "an opening header states no elapsed"
    assert closing.endswith("3m41s"), "over a minute the elapsed reads `<m>m<ss>s`"


def test_fr296_the_check_rollup_prints_a_dash_where_an_elapsed_would_go(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CHECK is a rollup: the vision check runs INSIDE each creative, so the stage has no elapsed
    of its own and says so with `-` rather than inventing a duration (§1.10 house rule 3)."""
    live = session(stages=["RENDER", "CHECK", "DONE"])

    runner._stage(live, "CHECK", "6 checked -> 6 pass, 0 retried, 1 not checked", elapsed_s=None)

    line = printed(capsys)[0]
    console_safe(line)
    assert line.startswith("[2/3] CHECK") and line.endswith("-")
    assert live.log.events[0][2]["elapsed_s"] is None


def test_fr296_a_stage_absent_from_this_runs_list_prints_nothing() -> None:
    """How previews reuse the stage helpers verbatim (D19): they set NO stage list, so every call
    is a no-op and no pipeline is narrated that the preview does not actually run."""
    preview = session(stages=[])
    brief_only = session(stages=runner._live_stages(Config(), brief_only=True))

    for stage in runner._STAGE_ORDER:
        runner._stage(preview, stage, "body", elapsed_s=1.0)
    runner._stage(brief_only, "COLLECT", "2 monitor(s) asked -> 64 post(s)", elapsed_s=1.0)

    assert preview.log.narrated == [] and preview.log.events == []
    assert brief_only.log.narrated == [], "a brief-only run has no COLLECT to narrate"


def test_fr296_every_header_of_every_stage_fits_the_console(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """FR-286 holds for the widest body any stage can carry — the body is fitted, never the line."""
    config = Config()
    config.run.vision_check = True
    live = session(stages=runner._live_stages(config, brief_only=False))
    body = "1234 monitor(s) asked -> 9876 post(s) split into 4321 topic(s), 0 failed, 0 synth"

    for stage in live.stages:
        runner._stage(live, stage, body, opening=True)
        runner._stage(live, stage, body, elapsed_s=3_600.0)

    lines = printed(capsys)
    assert len(lines) == 2 * len(live.stages)
    for line in lines:
        console_safe(line)


# ------------------------------------------------ FR-297a: the topics table IS the sort proof


#: FR-297a's column spec (contracts item 16), as slices. Parsing the table by fixed columns is
#: itself the width assertion: a shifted column changes what these read.
_COLUMNS = {"rk": slice(0, 5), "topic": slice(7, 29), "mon": slice(31, 34), "posts": slice(35, 41),
            "views": slice(42, 50), "median": slice(51, 59), "strn": slice(61, 66),
            "verdict": slice(68, None)}


def table_rows(block: str) -> list[dict[str, str]]:
    """The table's data rows, column by column — captions and the header are skipped."""
    rows = []
    for line in block.splitlines():
        if re.match(r"^\s{1,4}\d+\s{2}\S", line):
            rows.append({name: line[span].strip() for name, span in _COLUMNS.items()})
    return rows


def unsorted_topics() -> list[TrendItem]:
    """Input order deliberately NOT strength order — the display has to re-rank, and the verdict
    ordinals have to stay keyed to the order the engine numbered (§1.5)."""
    return [
        topic("AI agents do the work", strength=0.883, views=8_100_000, median=1_700_000),
        topic("Vibe coding is over", strength=1.000, views=12_400_000, median=1_900_000),
        topic("n8n vs Make showdown", monitor="be71-a1", strength=0.771, views=6_700_000,
              median=980_000, posts=5),
        topic("Weekend build log", monitor="be71-a1", strength=0.010, views=41_000, median=19_000,
              posts=2),
    ]


def test_fr297a_every_topic_gets_exactly_one_line() -> None:
    """ALL topics, one line each — the operator sees the whole supply the run was picked from,
    not a top-N that hides what was dropped."""
    topics = unsorted_topics()

    block = runner._topics_table(topics, {})

    console_safe(block)
    rows = table_rows(block)
    assert len(rows) == len(topics)
    assert [row["rk"] for row in rows] == ["1", "2", "3", "4"]
    printed_names = {row["topic"].rstrip("…") for row in rows}
    assert all(any(name.startswith(shown) for name in (item.name for item in topics))
               for shown in printed_names), printed_names
    assert len(printed_names) == len(topics), "no topic is folded into another's row"
    assert block.splitlines()[0].startswith("Topics -- 4 from 2 monitor(s), sorted by strength")


def test_fr297a_the_strn_column_never_rises_which_IS_the_sort_proof() -> None:
    """The operator's actual ask: PROVE the material is sorted by popularity. Fed a deliberately
    unsorted list, the printed `strn` column must be monotonically non-increasing top to bottom."""
    block = runner._topics_table(unsorted_topics(), {})

    strengths = [float(row["strn"]) for row in table_rows(block)]
    assert strengths == sorted(strengths, reverse=True), strengths
    assert all(later <= earlier for earlier, later in zip(strengths, strengths[1:]))
    assert strengths[0] == 1.0 and strengths[-1] == 0.01


def test_fr297a_the_caption_states_the_formula_the_adapter_actually_uses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The weights are READ off `sources.STRENGTH_WEIGHTS`, so the sentence cannot drift from the
    code that computed the column. Re-weighting the adapter re-writes the caption."""
    from hypesocials import sources

    weights = sources.STRENGTH_WEIGHTS
    caption = "\n".join(runner._topics_table(unsorted_topics(), {}).splitlines()[1:3])

    assert f"strength = {weights['total_views']:.2f} views" in caption
    assert f"{weights['median_views']:.2f} median" in caption
    assert f"{weights['velocity']:.2f} velocity" in caption
    assert f"{weights['engagement']:.2f} engage" in caption
    assert "min-maxed across all 4 topics" in caption
    assert "that topic's own posts" in caption, \
        "§1.6: views/median are the topic's OWN posts, not the monitor's"

    monkeypatch.setattr(sources, "STRENGTH_WEIGHTS",
                        {"total_views": 0.5, "median_views": 0.2, "velocity": 0.2,
                         "engagement": 0.1})
    rewritten = runner._topics_table(unsorted_topics(), {})
    assert "strength = 0.50 views + 0.20 median + 0.20 velocity + 0.10 engage" in rewritten


def test_fr297a_verdict_cells_are_keyed_by_input_order_ordinal_not_by_display_rank() -> None:
    """§1.5: verdicts key on the ENGINE-assigned ordinal (1-based INPUT order). Here input order
    and strength order disagree on every row, so a display-rank lookup would mislabel all four."""
    topics = unsorted_topics()
    verdicts = {
        1: topic_filter.Verdict(1, "keep"),
        2: topic_filter.Verdict(2, "strip", ["Cursor", "Lovable"]),
        3: topic_filter.Verdict(3, "skip", [], "post sells n8n Cloud"),
        4: topic_filter.Verdict(4, "keep"),
    }

    rows = table_rows(runner._topics_table(topics, verdicts))
    by_name = {row["topic"].rstrip("…"): row["verdict"] for row in rows}

    assert by_name["Vibe coding is over"] == "strip:2", "ordinal 2, displayed FIRST by strength"
    assert by_name["AI agents do the work"] == "keep", "ordinal 1, displayed SECOND"
    assert by_name["n8n vs Make showdown"] == "skip:PROMO"
    assert by_name["Weekend build log"] == "keep"
    assert runner._verdict_cell(None) == "keep", "an unscreened topic is not a dropped topic"


def test_fr297a_numbers_are_compact_never_thousands_separators() -> None:
    """`12.4M` / `980K` / `41K` — a seven-digit count with separators does not fit the column, and
    the operator is comparing magnitudes, not auditing digits (the funnel does that)."""
    block = runner._topics_table(unsorted_topics(), {})

    views = [row["views"] for row in table_rows(block)]
    assert views == ["12.4M", "8.1M", "6.7M", "41K"]
    assert [row["median"] for row in table_rows(block)] == ["1.9M", "1.7M", "980K", "19K"]
    assert not any("," in row["views"] or "," in row["median"] for row in table_rows(block))
    assert runner._compact(412) == "412" and runner._compact(1_500_000_000) == "1.5B"


def test_fr297a_a_wide_table_still_fits_and_says_nothing_when_there_is_nothing_to_say() -> None:
    """Unbounded tokens — a long topic name, a raw monitor id — are the two things that blow a
    column, so the name is fitted and monitors print as `m1`/`m2` display codes."""
    topics = [topic("A theme name that a monitor really did return once " * 3,
                    monitor="9c96fddf-dc35-4be0-bbd9-12f4d22aea12", strength=0.9),
              topic("Short one", monitor="be71-a1b2-c3d4", strength=0.4)]

    block = runner._topics_table(topics, {})

    console_safe(block)
    assert [row["mon"] for row in table_rows(block)] == ["m1", "m2"]
    assert "9c96fddf" not in block, "a raw monitor id would blow every column it sits in"
    assert table_rows(block)[0]["topic"].endswith("…")
    assert runner._topics_table([], {}) == "", "the caller guards on the empty string"


# ------------------------------------------------ FR-297b: which posts, and who quoted them


def test_fr297b_the_P_ordinals_are_view_rank_and_the_arrow_names_the_creative() -> None:
    """The roster is the §1.7 reference labelling made visible: `P<n>` is the view rank the copy
    model was offered, and `-> NN` is the creative whose `trend_reuse_index % len(posts)` chose it.
    A post nobody quoted says `unused` — silence there would read as "quoted by someone"."""
    item = topic("AI agents do the work", strength=1.0, posts=3)
    first, second = entry(0, trend=item, reuse=0), entry(4, fmt="reel", trend=item, reuse=1)

    block = runner._post_roster([item], {}, [first, second], posts_limit=None)

    console_safe(block)
    lines = [line.strip() for line in block.splitlines()]
    assert lines[0].startswith("Topic 1 -- AI agents do the work")
    assert "strn 1.000" in lines[0] and lines[0].endswith("keep")
    roster = [line for line in lines if re.match(r"^P\d", line)]
    assert [line.split()[0] for line in roster] == ["P1", "P2", "P3"], \
        "ranked by views, and the rank IS the label"
    quoted = {line.split()[0]: line.partition("slideshow")[2].strip() for line in roster}
    assert quoted["P1"] == "-> 01", "reuse index 0 quotes posts[0]"
    assert quoted["P2"] == "-> 05", "reuse index 1 quotes posts[1] — sibling divergence, visible"
    assert quoted["P3"] == "unused"
    assert "@creator0" in block and item.posts[0].post_id in block


def test_fr297b_the_permalink_sits_alone_on_its_line() -> None:
    """FR-286 carve-out (a): a permalink has no word boundary to wrap on and the operator copies
    it, so it gets its own line rather than a truncation."""
    item = topic("AI agents do the work", strength=1.0)

    block = runner._post_roster([item], {}, [entry(0, trend=item)])

    console_safe(block)
    urls = [line for line in block.splitlines() if line.strip().startswith("http")]
    assert len(urls) == 1 and urls[0].strip() == str(item.virlo_url)
    assert len(urls[0]) > WIDTH, "pick a longer fixture permalink — the carve-out is untested"


def test_fr297b_a_paid_run_shows_three_topics_by_three_posts_and_a_preview_shows_all() -> None:
    """FR-297b's volume guard: the paid console covers the strongest three assigned topics × three
    posts. `--verbose` and both preview modes pass `None`, because printing everything IS what
    those exist for (FR-139/140/299)."""
    topics = [topic(f"Theme {index}", strength=0.9 - index / 100, posts=5) for index in range(5)]
    live = [entry(index, trend=item) for index, item in enumerate(topics)]

    paid = runner._post_roster(topics, {}, live)
    uncapped = runner._post_roster(topics, {}, live, topics_limit=None, posts_limit=None)

    console_safe(paid)
    console_safe(uncapped)
    assert paid.count("Topic ") == 3 and uncapped.count("Topic ") == 5
    assert paid.count("          P") == 9 and uncapped.count("          P") == 25
    assert "Theme 0" in paid and "Theme 3" not in paid, "the three STRONGEST, not the first three"


def test_fr297b_a_topic_after_a_skip_prints_its_OWN_verdict_not_its_predecessors() -> None:
    """W5 live regression (2026-08-13): verdict ordinals are assigned by the SCREEN over the
    pre-filter list, but the paid pipeline handed `_post_roster` the post-filter `kept` list —
    so after a `skip` every later topic printed the verdict of the topic above it (the paid run
    showed `skip:PROMO` on a kept-and-quoted topic). The pipeline now passes the screened list
    (runner.py `_pipeline`); this pins the roster's half of the contract: with the SAME sequence
    the screen numbered, a kept topic that FOLLOWS a skipped one still reads `keep`."""
    screened = [topic("Kept leader", strength=0.9, posts=1),
                topic("Skipped promo", strength=0.7, posts=1),
                topic("Kept follower", strength=0.5, posts=1)]
    verdicts = {2: topic_filter.Verdict(ordinal=2, verdict="skip",
                                        brands_to_strip=[], reason="PROMO: launch post"),
                3: topic_filter.Verdict(ordinal=3, verdict="keep",
                                        brands_to_strip=[], reason="")}
    live = [entry(0, trend=screened[0]), entry(1, trend=screened[2])]

    block = runner._post_roster(screened, verdicts, live,
                                topics_limit=None, posts_limit=None)

    console_safe(block)
    heads = [line for line in block.splitlines() if line.startswith("Topic ")]
    assert len(heads) == 2, "an unassigned (skipped) topic never makes the roster on a paid run"
    assert heads[0].endswith("keep") and "Kept leader" in heads[0]
    assert heads[1].endswith("keep") and "Kept follower" in heads[1], \
        "the follower must not inherit the skipped topic's verdict"
    assert "skip:PROMO" not in block


def test_fr297b_an_unassigned_run_still_lists_the_material_it_could_have_used() -> None:
    """Previews assign nothing, so every topic prints and every post reads `unused` — the honest
    answer when no creative has claimed a post yet."""
    topics = [topic("Only theme", strength=0.5, posts=2)]

    block = runner._post_roster(topics, {}, [], topics_limit=None, posts_limit=None)

    console_safe(block)
    posts = [line.strip() for line in block.splitlines() if re.match(r"^\s+P\d", line)]
    assert len(posts) == 2 and all(line.endswith("unused") for line in posts)


# ------------------------------------------------ FR-297c: where each creative came from


def test_fr297c_the_provenance_block_maps_every_creative_back_to_its_origins() -> None:
    """One row per recorded creative: id · format · topic · style · sig · cost · ok. Then the
    verbatim receipt — WHICH post, and the first ~24 characters of the exact string quoted."""
    item = topic("AI agents do the work", strength=1.0)
    image = entry(0, trend=item, branded=True)
    image.status = PlanEntryStatus.SUCCESS
    deck = entry(1, fmt="carousel", trend=item, reuse=1, style="editorial-voxel-carousel")
    deck.status = PlanEntryStatus.SUCCESS
    records = {image.asset_id: record(image, item, cost=0.041, quoted=item.posts[0]),
               deck.asset_id: record(deck, item, cost=0.180, quoted=item.posts[1])}
    copy = {image.asset_id: CopySet(asset_id=image.asset_id, language="en",
                                    headline="AI agents do the work for you while you sleep"),
            deck.asset_id: CopySet(asset_id=deck.asset_id, language="en",
                                   headline="Vibe coding is over, we are back to reading")}

    block = runner._provenance_block([image, deck], records, {item.history_key: item}, copy)

    console_safe(block)
    lines = block.splitlines()
    assert lines[0] == "Provenance -- where each delivered creative came from"
    assert lines[1].split() == ["id", "format", "topic", "style", "sig", "cost", "ok"]
    assert lines[2].split()[0] == "01", "`id` is the asset id's trailing ordinal (FR-71)"
    assert "image" in lines[2] and "photoreal-ambient" in lines[2]
    # The cost cell goes through the run's ONE money formatter (FR-85), so this reads it rather
    # than the mockup's illustrative three decimals — one rounding rule, not two.
    assert lines[2].split()[-1] == "yes" and runner._money(0.041) in lines[2]
    assert " yes " in lines[2], "sig: this one carries the wordmark"
    assert lines[3].strip().startswith('quoted P1 @creator0 8.1M ')
    assert item.posts[0].post_id in lines[3]
    assert '"AI agents do the work' in lines[3], "the first ~24 characters, quoted verbatim"
    assert lines[4].split()[0] == "02" and "-" in lines[4], "sig `-` on an unbranded creative"
    assert lines[5].strip().startswith("quoted P2 @creator1")


def test_fr297c_a_lost_creative_gets_a_third_line_naming_the_cause() -> None:
    """Line 3 appears ONLY on a loss. `ok no` without a cause would leave the operator guessing at
    the one place the run is supposed to explain itself."""
    item = topic("Cursor tab is all you need", strength=0.6)
    reel = entry(6, fmt="reel", trend=item, reuse=0, style="anime-noir-statement", branded=True)
    reel.status = PlanEntryStatus.FAILED
    reel.skip_reason = "Seedance job timed out after 300s; seed frame kept"
    records = {reel.asset_id: record(reel, item, cost=0.425, quoted=item.posts[0])}

    block = runner._provenance_block([reel], records, {item.history_key: item},
                                     {reel.asset_id: CopySet(asset_id=reel.asset_id,
                                                             language="en",
                                                             headline="Cursor tab is all you need"
                                                                      " and nothing else")})

    console_safe(block)
    lines = block.splitlines()
    assert len(lines) == 5, "header + column head + row + receipt + cause"
    assert lines[2].split()[-1] == "no"
    assert "Seedance job timed out after 300s" in lines[4]
    assert lines[4].startswith("       "), "the cause hangs under its creative's row"


def test_fr297c_a_creative_that_quoted_nothing_prints_no_receipt_and_nothing_prints_empty() -> None:
    """An override brief quotes no post, so it has no receipt to show; a run with no records at
    all returns `""` and the caller's walrus guard drops the whole block."""
    brief_entry = entry(0, style="")
    brief_entry.status = PlanEntryStatus.SUCCESS
    brief_entry.brief_name = "ai-audit-cta"
    records = {brief_entry.asset_id: record(brief_entry, None, cost=0.03)}

    block = runner._provenance_block([brief_entry], records, {}, {})

    console_safe(block)
    assert "quoted" not in block
    assert block.splitlines()[2].split()[-1] == "yes"
    assert runner._provenance_block([brief_entry], {}, {}, {}) == ""


# ------------------------------------------------ FR-299: heartbeats are silence-breakers


def test_fr299_a_pulse_is_due_only_after_silence_AND_past_the_suppression_window() -> None:
    """The whole heartbeat contract, as arithmetic on the monotonic clock (FR-243): nothing fires
    while the console is talking, and nothing fires in the first seconds of a wait — which is why
    a fast run prints no heartbeat at all."""
    pulse = Pulse(interval_s=30.0)
    now = time.monotonic()

    pulse.last = now - 5.0
    assert pulse.due() is False, "5 s of quiet is not silence"
    pulse.last = now - 31.0
    assert pulse.due() is True, "31 s of quiet on a 30 s cadence is"
    assert pulse.due(wait_started=now - 5.0, suppress_s=20.0) is False, \
        "the first render heartbeat is suppressed 20 s into the wait"
    assert pulse.due(wait_started=now - 25.0, suppress_s=20.0) is True
    assert pulse.due(wait_started=now - 5.0, suppress_s=10.0) is False, "10 s for LLM waits"

    pulse.stamp()
    assert pulse.due(wait_started=now - 600.0, suppress_s=20.0) is False, \
        "any printed line resets the quiet clock — that is what bounds the volume"


def test_fr299_the_pulse_wrapper_actually_runs_and_returns_the_awaitables_result() -> None:
    """W5 regression (2026-08-13): `_with_pulse` crashed every live COPY stage with
    `NameError: name 'time' is not defined` — the W3.5 excision swept `import time` out of
    runner.py with its other users, and no test ever EXECUTED the wrapper (Pulse arithmetic was
    tested directly, the wrapper always faked). Caught live by `--preview-analysis`, after 761
    green tests. This test is the execution the suite was missing: a real await through the real
    wrapper, result passed through, no heartbeat needed on a fast path."""
    live = session()

    async def scenario() -> str:
        async def quick() -> str:
            return "copy result"
        return await runner._with_pulse(live, quick(), lambda: "never printed", suppress_s=10.0)

    assert asyncio.run(scenario()) == "copy result"


def test_fr299_saying_anything_re_stamps_the_pulse(capsys: pytest.CaptureFixture[str]) -> None:
    """`say()` is the ONE console seam, and it stamps: a heartbeat is itself a printed line, so
    the cadence can never compound into a ticker."""
    live = session()
    live.pulse.last = time.monotonic() - 600.0
    assert live.pulse.due() is True

    live.say("[1/8] COLLECT   2 monitor(s) asked -> 64 post(s), 0 failed          6.4s")

    assert live.pulse.due() is False
    assert printed(capsys) == [live.log.narrated[0]], "console bytes ARE run.log bytes"


def test_fr299_the_render_heartbeat_reads_the_permit_gate_not_a_guess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`render X/Y done, R running (a w1, b w2), Q queued ... <dur>` — every number off
    `render.gate_stats()` or the Env's own counters. A heartbeat that guessed would be worse than
    silence, because it would look like knowledge."""
    monkeypatch.setattr(render, "gate_stats", lambda: (0, 2, 0))
    env = generate.Env(config=Config(), run_dir=Path("output/run"), engine=None, budget=None,
                       log=Log(), ledger=None, jobs_expected=11, jobs_submitted=11, jobs_done=9)

    line = generate._heartbeat_line(env, 190.0)

    console_safe(line)
    assert line.strip() == "render 9/11 done, 2 running (0 w1, 2 w2), 0 queued ... 3m10s"
    monkeypatch.setattr(render, "gate_stats", lambda: (2, 2, 4))
    env.jobs_done = 3
    assert generate._heartbeat_line(env, 134.0).strip() == \
        "render 3/11 done, 4 running (2 w1, 2 w2), 4 queued ... 2m14s"


def test_fr299_a_fast_render_batch_prints_no_heartbeat_at_all(tmp_path: Path) -> None:
    """The silence-breaker rule, end to end through the real `_drain` loop: work that lands inside
    the suppression window is narrated by its own per-job lines and nothing else."""
    env = generate.Env(config=Config(), run_dir=tmp_path, engine=None, budget=None, log=Log(),
                       ledger=None, jobs_expected=2, jobs_submitted=2, jobs_done=2)
    said: list[str] = []
    env.say, env.pulse, env.heartbeat_s = said.append, Pulse(interval_s=30.0), 30.0

    async def scenario() -> None:
        async def done() -> AssetRecord:
            return AssetRecord(asset_id="a1", source="s", source_name="s", platform="linkedin",
                               creative_format="image")
        await generate._drain([asyncio.ensure_future(done()) for _ in range(2)], env)

    asyncio.run(scenario())

    assert [line for line in said if "render 2/2 done" in line] == []
    assert not any(line.strip().startswith("render ") for line in said), said
    assert any("gallery" in line for line in said), "FR-297f: the gallery path DOES print"


def test_fr299_the_per_job_line_names_the_creative_the_wave_and_the_price() -> None:
    """One event-driven terminal line per submission: `ok/failed · NN fmt · w1|w2 · what · dur ·
    $cost`. A failure shows its CAUSE instead of a price, because the cause is what an operator
    acts on."""
    image = entry(0, fmt="image")
    reel = entry(6, fmt="reel")
    ok = RenderOutcome(kind=RenderOutcomeKind.SUCCESS, result_urls=["https://kie/1.png"],
                       cost_usd=0.030, elapsed_s=38.4)
    bad = RenderOutcome(kind=RenderOutcomeKind.STUCK, fail_cause=RenderFailCause.TIMEOUT,
                        fail_message="no terminal state within 300s")

    good_line = generate._job_line(image, "image · gpt-image-2", RenderPriority.WAVE1, ok)
    bad_line = generate._job_line(reel, "reel clip · seedance", RenderPriority.WAVE2, bad)

    console_safe(good_line)
    console_safe(bad_line)
    assert good_line.split() == ["ok", "01", "image", "w1", "image", "38s", "$0.030"]
    assert bad_line.strip().startswith("failed  07 reel     w2")
    assert "timeout" in bad_line and "no terminal state" in bad_line
    assert "$" not in bad_line, "a job that produced nothing has no price to advertise"


# ------------------------------------------------ §1.10: a number appears in exactly ONE surface


def test_fr155_the_funnel_prints_exactly_once_and_only_at_DONE() -> None:
    """Its three pre-pivot stage-gate placements are superseded by the FR-296 headers, which carry
    the same counts the moment they become true. Printing it again mid-run would double them."""
    pipeline = inspect.getsource(runner._pipeline)
    package = inspect.getsource(runner._package)

    assert pipeline.count("_funnel_block(") == 0, "the funnel left the pipeline body (v2.0.0)"
    assert package.count("_funnel_block(") == 1
    assert package.index("_funnel_block(") > package.index("_provenance_block("), \
        "§1.10's DONE order: provenance, then the funnel, then the spend table"
    assert package.index("_spend_table(") > package.index("_funnel_block(")


def test_fr84_the_spend_table_no_longer_repeats_the_collect_chain() -> None:
    """`_spend_table` takes the summary and nothing else: the funnel prints directly above it at
    DONE, so a counters row here would print every collect number twice."""
    parameters = list(inspect.signature(runner._spend_table).parameters)

    assert parameters == ["summary"]
    assert "counters" not in inspect.getsource(runner._spend_table)


# ------------------------------------------------ FR-299: the note() verbosity seam


def test_fr299_note_writes_the_log_always_and_the_console_only_when_verbose(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """run.log and events.jsonl are UNCHANGED by verbosity — only the console tier moves
    (contracts item 16). Both halves are asserted, because a `note` that skipped the log would
    quietly delete the detail the operator is told they can read afterwards."""
    quiet, loud = session(verbose=False), session(verbose=True)

    quiet.note("          keep   AI agents do the work")
    loud.note("          keep   AI agents do the work")

    assert printed(capsys) == ["          keep   AI agents do the work"], "verbose printed once"
    assert quiet.log.narrated == ["          keep   AI agents do the work"], \
        "the quiet run still recorded it — run.log is not a verbosity tier"
    assert loud.log.narrated == quiet.log.narrated


def test_fr299_a_note_that_stays_silent_does_not_reset_the_heartbeat_clock() -> None:
    """Silence-breaker semantics: only a line the OPERATOR saw counts as breaking the silence.

    The sample line is `_store_references`' own wording — post-D46 the run-level `refs/` store
    holds a campaign brief's photos and nothing else (F3 excised the style picture channel), so
    the note it emits reads `brief ref stored`.
    """
    quiet, loud = session(verbose=False), session(verbose=True)
    for live in (quiet, loud):
        live.pulse.last = time.monotonic() - 600.0

    quiet.note("brief ref stored")
    loud.note("brief ref stored")

    assert quiet.pulse.due() is True, "nothing reached the console, so the console is still mute"
    assert loud.pulse.due() is False


# ------------------------------------------------ FR-296: the detail-line policy at FILTER


@dataclass
class _Screen:
    """A stand-in for `topic_filter.screen` — the verdicts are the fixture, not the model."""

    verdicts: dict[int, topic_filter.Verdict] = field(default_factory=dict)

    async def __call__(self, topics: Any, cfg: Any, llm: Any) -> dict[int, topic_filter.Verdict]:
        return self.verdicts


def test_fr296_filter_prints_one_line_per_NON_keep_and_keeps_go_to_the_log(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Detail lines only where a decision-with-a-cause occurred. A `keep` is the absence of a
    decision, so it travels on `note()` — visible under `--verbose`, always in run.log."""
    topics = unsorted_topics()
    verdicts = {1: topic_filter.Verdict(1, "keep"),
                2: topic_filter.Verdict(2, "strip", ["Cursor", "Lovable"]),
                3: topic_filter.Verdict(3, "skip", [], "post sells n8n Cloud"),
                4: topic_filter.Verdict(4, "keep")}
    monkeypatch.setattr(runner.topic_filter, "screen", _Screen(verdicts))
    live = session(stages=runner._live_stages(Config(), brief_only=False))

    asyncio.run(runner._screen_topics(live, topics))

    lines = printed(capsys)
    for line in lines:
        console_safe(line)
    assert [line for line in lines if line.strip().startswith("keep")] == [], \
        "a keep is not a decision-with-a-cause"
    strips = [line for line in lines if line.strip().startswith("strip")]
    skips = [line for line in lines if line.strip().startswith("skip")]
    assert len(strips) == 1 and '"Cursor", "Lovable"' in strips[0]
    assert len(skips) == 1 and "PROMO: post sells n8n Cloud" in skips[0]
    assert lines[0].startswith("[3/9] FILTER") and lines[0].endswith("...")
    assert "4 topic(s) -> 2 keep, 1 strip, 1 skip" in lines[1]
    assert live.strip_brands == {topics[1].history_key: ("Cursor", "Lovable")}, \
        "M6: the LLM's strips ride to the copy AND render paths, keyed by trend_key"
    assert [code for code, _, _ in live.log.events].count("topic_filter_verdict") == 4


def test_fr296_the_keep_verdicts_appear_under_verbose(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """The other half of the tier table: `--verbose` adds every keep and its reason."""
    verdicts = {index: topic_filter.Verdict(index, "keep", [], f"reason {index}")
                for index in range(1, 5)}
    monkeypatch.setattr(runner.topic_filter, "screen", _Screen(verdicts))
    live = session(stages=runner._live_stages(Config(), brief_only=False), verbose=True)

    asyncio.run(runner._screen_topics(live, unsorted_topics()))

    keeps = [line for line in printed(capsys) if line.strip().startswith("keep")]
    assert len(keeps) == 4 and "reason 1" in " ".join(keeps)


def test_fr294_only_a_skip_drops_a_topic_before_select() -> None:
    """A `strip` topic PROCEEDS — its competitor names are removed, the topic itself is usable
    (§1.5). Only `skip` is dropped, and it is dropped before any render spend."""
    pipeline = inspect.getsource(runner._pipeline)
    drop = next(line for line in pipeline.splitlines() if 'verdict != "skip"' in line)

    assert 'verdicts.get(ordinal) is None or verdicts[ordinal].verdict != "skip"' in drop
    assert '"strip"' not in drop, "a stripped topic is kept, not dropped"


# ------------------------------------------------ FR-306: the INTEL stage, wired and narrated
#
# The slide-intelligence pass is the one stage D46 ADDED to the pipeline, and it is the one stage
# that spends money the operator approved for something else if it is wired wrongly: it runs after
# the Confirm gate (it is paid), before COPY (its transcription fills the panel slots the offer
# reads), and only for the decks the plan actually bound. `sources.slide_intel.enrich` has its own
# suite; what is pinned here is the WIRING and the narration around it.


class _Enrich:
    """A stand-in for `sources.slide_intel.enrich` — records the call, answers with readings."""

    def __init__(self, *, answers: dict[str, Any] | None = None) -> None:
        self.answers = answers
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, posts: Any, *, run_dir: Any, call: Any, engine: Any, cfg: Any,
                       log: Any) -> dict[str, Any]:
        self.calls.append({"posts": list(posts), "run_dir": run_dir, "call": call, "cfg": cfg})
        if self.answers is not None:
            return self.answers
        return {str(item.post_id): _intel(str(item.post_id)) for item in posts}

    @property
    def post_ids(self) -> list[str]:
        return [str(item.post_id) for item in (self.calls[0]["posts"] if self.calls else ())]


def _slide(source: str = "virlo", *, brief: str = "", marks: tuple[str, ...] = ()) -> Any:
    return SimpleNamespace(text_source=source, visual_brief=brief, brand_marks=list(marks))


def _intel(post_id: str, *, slides: Any = None, status: str = "ok", cost: float = 0.02) -> Any:
    """One `SlideIntel`, duck-typed exactly as the runner reads it (`getattr` throughout)."""
    return SimpleNamespace(
        post_id=post_id, status=status, cost_usd=cost,
        slides=list(slides) if slides is not None else [_slide("virlo", brief="hero image"),
                                                        _slide("vision_transcribed", brief="table"),
                                                        _slide("none")])


def _deck_post(post_id: str) -> SourcePost:
    """A slideshow post a carousel could be bound to."""
    return SourcePost(post_id=post_id, url=f"https://www.tiktok.com/@creator/photo/{post_id}",
                      author="creator", views=900_000, is_slideshow=True, panel_count=3,
                      caption="the five tools I actually use")


def _deck_entry(order: int, post_id: str | None, *, topic_key: str = "m1::decks",
                override: bool = False) -> PlanEntry:
    item = entry(order, fmt="carousel")
    item.trend_key = topic_key
    item.source_post_id = post_id
    item.slide_count = 3
    if override:
        item.brief_influence, item.brief_name = "override", "ai-audit-cta"
    return item


def _bound_topic(*posts: SourcePost) -> TrendItem:
    return TrendItem(history_key="m1::decks", monitor_id="m1", name="Source decks",
                     topic_key="decks", posts=list(posts))


def test_fr306_only_a_bound_non_override_carousel_reaches_the_intel_stage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """WHICH decks are read, and therefore what the run pays for (§0.11: one call per bound post).

    An image and a reel bind no deck; an override brief binds none by construction (§0.14d); a
    binding the topic can no longer resolve has nothing to download. Two siblings quoting one post
    are ONE reading — the deck is a property of the source, not of the creative, and paying twice
    for the same slides would be a bill the Confirm gate never quoted.
    """
    enrich = _Enrich()
    monkeypatch.setattr(runner.sources.slide_intel, "enrich", enrich)
    live = session(stages=runner._live_stages(Config(), brief_only=False))
    live.llm = object()  # `_metered` needs a client; the wrapped call is never invoked here
    topic_item = _bound_topic(_deck_post("post-a"), _deck_post("post-b"))
    entries = [entry(0, fmt="image"), entry(1, fmt="reel"),
               _deck_entry(2, "post-a"), _deck_entry(3, "post-a"),  # siblings on one deck
               _deck_entry(4, "post-b"),
               _deck_entry(5, "post-b", override=True),  # §0.14d binds nothing
               _deck_entry(6, "post-gone"),              # the topic no longer carries it
               _deck_entry(7, None)]                     # never bound at all

    asyncio.run(runner._slide_intel(live, entries, {topic_item.history_key: topic_item}))

    assert len(enrich.calls) == 1, "one pass over the run, not one per creative"
    assert enrich.post_ids == ["post-a", "post-b"], "deduped, in plan order"
    assert sorted(live.slide_intel) == ["post-a", "post-b"]
    assert enrich.calls[0]["run_dir"] == live.run_dir
    for line in printed(capsys):
        console_safe(line)


def test_fr306_a_run_that_bound_no_deck_spends_nothing_and_still_closes_its_stage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """An images-and-reels run reaches this code and must leave without calling anything.

    The stage still opens and closes, because a header that appears only sometimes makes the
    `[n/N]` counter the operator is reading walk — and `0 deck(s) -> 0 read` is a fact worth
    printing on the run that expected decks and got none.
    """
    enrich = _Enrich()
    monkeypatch.setattr(runner.sources.slide_intel, "enrich", enrich)
    live = session(stages=runner._live_stages(Config(), brief_only=False))
    live.llm = object()

    asyncio.run(runner._slide_intel(live, [entry(0, fmt="image")], {}))

    assert enrich.calls == [] and live.slide_intel == {}
    lines = printed(capsys)
    assert any("0 source deck(s) to read" in line for line in lines)
    assert any("0 deck(s) -> 0 read" in line for line in lines)


def test_fr306_vision_off_still_reads_the_deck_for_the_gallery_at_zero_dollars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§0.6/§0.14c: `sources.vision_transcribe: false` passes `call=None`, which is the $0 path —
    the slides still download, so FR-309's source strip works on a run that paid for no analysis.
    A stage that skipped itself entirely would take the gallery's provenance with it."""
    enrich = _Enrich()
    monkeypatch.setattr(runner.sources.slide_intel, "enrich", enrich)
    config = Config()
    config.sources.vision_transcribe = False
    live = session(config=config, stages=runner._live_stages(config, brief_only=False))
    live.llm = object()
    topic_item = _bound_topic(_deck_post("post-a"))

    asyncio.run(runner._slide_intel(live, [_deck_entry(0, "post-a")],
                                    {topic_item.history_key: topic_item}))

    assert enrich.calls[0]["call"] is None, "no model call is metered, and none is made"
    assert enrich.post_ids == ["post-a"], "the download still happens — the gallery needs it"


def test_fr306_every_deck_prints_what_the_reading_actually_produced(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """D45's posture: every AI step prints its RESULT, not just its happening.

    Per deck: how many slides, whose words (Virlo vs vision), how many visual briefs, how many
    brand marks and what it cost — plus the degrade status where there is one, because a deck that
    fell back to Virlo panels alone looks identical to a clean read from the stage header.
    """
    enrich = _Enrich(answers={
        "post-a": _intel("post-a"),
        "post-b": _intel("post-b", status="vision_unavailable", cost=0.0,
                         slides=[_slide("virlo"), _slide("virlo")])})
    monkeypatch.setattr(runner.sources.slide_intel, "enrich", enrich)
    live = session(stages=runner._live_stages(Config(), brief_only=False))
    live.llm = object()
    topic_item = _bound_topic(_deck_post("post-a"), _deck_post("post-b"))

    asyncio.run(runner._slide_intel(live, [_deck_entry(0, "post-a"), _deck_entry(1, "post-b")],
                                    {topic_item.history_key: topic_item}))

    lines = printed(capsys)
    read = next(line for line in lines if line.strip().startswith("post-a"))
    degraded = next(line for line in lines if line.strip().startswith("post-b"))
    console_safe(read)
    assert "3 slide(s): 1 virlo + 1 vision, 2 brief(s), 0 mark(s), $0.02" in read
    assert "[vision_unavailable]" in degraded, "a degraded read says so on its own line"
    assert any("2 deck(s) -> 1 read, 1 degraded" in line for line in lines)
    complete = [fields for code, _, fields in live.log.events if code == "slide_intel_complete"]
    assert complete and complete[0]["decks"] == {"post-a": "ok", "post-b": "vision_unavailable"}


def test_fr306_intel_sits_after_the_confirm_gate_and_before_copy_in_both_callers() -> None:
    """The ordering IS the requirement (§0.11), and it is two requirements in one line.

    After Confirm: the pass is paid LLM spend plus a download per slide, and rule 7 allows neither
    before the gate. Before COPY: the transcription fills the panel slots `_offer_for` reads, so a
    stage that ran afterwards would produce briefs for a deck whose words were already chosen.
    `previews` runs the same pass on the $0 path, which is why it is asserted in both callers
    rather than in the runner alone.
    """
    pipeline = inspect.getsource(runner._pipeline)
    assert pipeline.index("_confirm(") < pipeline.index("_slide_intel(") < pipeline.index("_write(")

    preview = inspect.getsource(previews)
    assert "_slide_intel(" in preview, "a preview reads the decks too, at $0 (D19)"
    assert preview.index("await _slide_intel(") < preview.index("await _write("), \
        "same order, same reason"


def test_fr306_the_merged_panels_the_copy_stage_reads_come_from_this_stage_alone() -> None:
    """One reading of a deck, two consumers: `_write` derives `merged_panels` (the words) and
    `_create` rides the same objects onto `generate.Env.slide_intel` (the briefs and the picture
    paths). Two independent re-derivations would be two chances to disagree about what the source
    deck said — which is the disagreement `source.yaml` exists to make impossible."""
    write_source = inspect.getsource(runner._write)
    create_source = inspect.getsource(runner._create)

    assert "session.slide_intel.items()" in write_source and "merged_panels=" in write_source
    assert "slide_intel=dict(session.slide_intel)" in create_source
