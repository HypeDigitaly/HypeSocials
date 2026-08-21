"""§1.10 / D45 — the console inventory: what a paid run SHOWS while it happens (FR-296–299).

The pre-pivot version of this file pinned `_sources_block` and `_brief_block` — the A24 answer to
"which posts these are and how our AI analysed them". Both died with the vision stage (v2.0.0).
What replaced them is a larger, stricter surface, and every property below is one the operator
asked for in words:

1. **Step by step** (FR-296) — numbered stage headers whose `[n/N]` is COMPUTED from the resolved
   plan. A brief-only run has no COLLECT/TOPICS/FILTER/SELECT and `gauntlet.enabled: false` has
   no GAUNTLET, so a hardcoded denominator is a lie in two ordinary shapes. Every header states
   counts
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
7. **The console says which COPY CONTRACT the words shipped under** (v2.3.0, D54/FR-331) — four
   surfaces gained a second arm: the COPY stage line, the FR-297c provenance receipt, the preview
   copy header and its per-creative rows, and the pre-flight language hint. Compress is an
   operator toggle, so without those arms the one difference between two runs of the same config
   is invisible in `run.log`. Each is pinned BESIDE its verbatim twin, and the verbatim wordings
   are asserted UNCHANGED: every one of them is a one-line ternary, and a rewrite of the wrong arm
   is a two-character edit. The counts come off the per-asset receipt, never off
   `config.run.carousel_copy_mode` — a compress-mode run whose call failed shipped the verbatim
   mapped deck, and a line claiming "compressed" over it would hide the degradation.
8. **The console says which ALGORITHM chose each look** (v2.4.0, D56/FR-334–337) — the ASSIGN
   stage gained a per-creative provenance line (origin/fit, then the matcher's own reason), a
   `matched N of M` tally, a gap report naming the archetypes the registry has no style for, and
   exactly ONE `style_match_degraded` warning for a whole-call failure. Under `assignment:
   rotation` none of them print and no call is made, which is the escape hatch FR-334 promises and
   is pinned as console silence rather than described. The launch block's style count joined the
   same discipline: it reports the ENABLED-aware usable pool, not the brand-only one.

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

from hypesocials import (cli, copywrite, generate, plan, preflight, previews, render, runner,
                         style_match, styles, topic_filter)
from hypesocials.config import Config
from hypesocials.models import (AssetRecord, CopySet, DegradationTag, MetaStyle, PlanEntry,
                                PlanEntryStatus, RenderFailCause, RenderOutcome,
                                RenderOutcomeKind, RenderPriority, SourcePost, TrendItem,
                                VisionCheckResult)
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
           quoted: SourcePost | None = None, refs: dict[str, str] | None = None,
           copy_mode: str = "verbatim", copy_language: str = "source",
           source_language: str = "") -> AssetRecord:
    return AssetRecord(
        copy_mode=copy_mode, copy_language=copy_language, source_language=source_language,
        asset_id=item.asset_id, source=item.trend_key or "", platform="linkedin",
        source_name=source.name if source is not None else "", creative_format=item.creative_format,
        style_key=item.style_key, branded=item.branded, actual_cost_usd=cost,
        topic_key=source.topic_key if source is not None else "",
        copy_source_post_id=quoted.post_id if quoted is not None else "",
        copy_source_refs=dict(refs or ({"headline": "P1.hook.2"} if quoted is not None else {})))


# ------------------------------------------------ FR-296: stage narration, with a COMPUTED [n/N]


def test_fr296_the_stage_list_is_computed_from_the_resolved_plan_never_hardcoded() -> None:
    """A brief-only plan consumes no topic and `gauntlet.enabled: false` runs no gate, so the two
    ordinary shapes below have 4 and 9 stages (the v2.1.0 default plan is all-carousels, so
    INTEL is live — FR-306). A denominator typed at a call site is wrong in both.
    """
    config = Config()
    config.run.gauntlet.enabled = False
    full = runner._live_stages(config, brief_only=False)
    brief_only = runner._live_stages(config, brief_only=True)
    config.run.gauntlet.enabled = True
    checked = runner._live_stages(config, brief_only=False)
    config.run.formats = {"image": 2, "carousel": 0, "reel": 0}
    config.sources.include_videos = True  # §0.14e: images need the videos ask
    no_decks = runner._live_stages(config, brief_only=False)

    assert full == ["COLLECT", "TOPICS", "FILTER", "SELECT", "ASSIGN", "INTEL", "COPY",
                    "RENDER", "DONE"]
    assert len(full) == 9 and len(checked) == 10 and "GAUNTLET" in checked
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

    `n/N` moves with the live stage list (the gated run has one more stage, so the denominator
    changes and FILTER's numerator does not), the body states counts in -> counts out, and the
    elapsed is right-aligned in the tail.
    """
    config = Config()
    config.run.gauntlet.enabled = vision
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


def test_fr296_the_gauntlet_rollup_prints_a_dash_where_an_elapsed_would_go(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """GAUNTLET is a rollup: the gate runs INSIDE each creative, so the stage has no elapsed
    of its own and says so with `-` rather than inventing a duration (§1.10 house rule 3)."""
    live = session(stages=["RENDER", "GAUNTLET", "DONE"])

    runner._stage(live, "GAUNTLET", "6 judged -> 6 pass, 0 blocked, 0 stopped", elapsed_s=None)

    line = printed(capsys)[0]
    console_safe(line)
    assert line.startswith("[2/3] GAUNTLET") and line.endswith("-")
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
    config.run.gauntlet.enabled = True
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

    # v2.2.0: every cell carries the screened `<language>/fit|unfit` tail beside its verdict, and
    # `?` is what a verdict with no usable language answer prints (fail-open, still a keep).
    assert by_name["Vibe coding is over"] == "strip:2 ?/fit", "ordinal 2, displayed FIRST"
    assert by_name["AI agents do the work"] == "keep ?/fit", "ordinal 1, displayed SECOND"
    assert by_name["n8n vs Make showdown"] == "skip:PROMO ?/fit"
    assert by_name["Weekend build log"] == "keep ?/fit"
    assert runner._verdict_cell(None) == "keep ?/fit", \
        "an unscreened topic is not a dropped topic"
    assert runner._verdict_cell(topic_filter.Verdict(
        5, "skip", [], "off-language", language="de", skip_code=topic_filter.SKIP_LANGUAGE)) \
        == "skip:LANG de/fit", "the code and the language it objected to travel together"
    assert runner._verdict_cell(topic_filter.Verdict(
        6, "skip", [], "wrong audience", language="en", audience_fit=False,
        skip_code=topic_filter.SKIP_AUDIENCE)) == "skip:AUDIENCE en/unfit"


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
    assert "strn 1.000" in lines[0] and lines[0].endswith("keep ?/fit")  # v2.2.0 verdict tail
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
    assert heads[0].endswith("keep ?/fit") and "Kept leader" in heads[0]
    assert heads[1].endswith("keep ?/fit") and "Kept follower" in heads[1], \
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
    """`_spend_table` takes the summary and the gate column: the funnel prints directly above it
    at DONE, so a counters row here would print every collect number twice. `gates` (v2.2.0) is a
    per-creative COLUMN read off `meta.yaml.gauntlet`, not a second copy of any counter."""
    parameters = list(inspect.signature(runner._spend_table).parameters)

    assert parameters == ["summary", "gates"]
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
    # GAUNTLET joined the live stages (`run.gauntlet.enabled` defaults on, v2.2.0/D49).
    assert lines[0].startswith("[3/10] FILTER") and lines[0].endswith("...")
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


# --------------------------------- FR-296/FR-328: the GAUNTLET rollup reads the records
#
# Run 20260814_010814_glz0 printed `6 checked -> 4 pass, 3 retried`, and 4 + 3 > 6, because two
# buckets counted the same creative. The lesson outlived the CHECK rollup it was learned on: this
# stage's counts are read off each record's own `meta.yaml.gauntlet.result`, which is exactly one
# value per creative, so a creative cannot be in two buckets and the console cannot disagree with
# the document the operator opens afterwards.


def _gated(**counts: int) -> generate.Report:
    """A `Report` carrying `counts` creatives per gauntlet result, ids in plan order."""
    records: dict[str, AssetRecord] = {}
    for result, many in counts.items():
        for _ in range(many):
            asset_id = f"{len(records) + 1:04d}_carousel_linkedin"
            records[asset_id] = AssetRecord(
                asset_id=asset_id, source="t1", source_name="AI tool stacks",
                platform="linkedin", creative_format="carousel",
                gauntlet={"result": result, "degraded_gate": False, "rounds": [],
                          "rerenders": 0, "rerender_cost_usd": 0.0, "critic_cost_usd": 0.01})
    return generate.Report(records=records)


def test_fr328_the_gauntlet_rollups_categories_are_disjoint_and_add_up(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every judged creative lands in exactly one of pass / blocked / stopped."""
    live = session(stages=["RENDER", "GAUNTLET", "DONE"])

    runner._gauntlet_rollup(live, _gated(**{"pass": 3, "blocked": 2, "budget_stop": 1}))

    line = printed(capsys)[0]
    console_safe(line)
    assert "6 judged -> 3 pass, 2 blocked, 1 stopped" in line
    numbers = [int(n) for n in re.findall(r"(\d+) (?:pass|blocked|stopped)", line)]
    assert sum(numbers) == 6, "pass + blocked + stopped accounts for every judged creative"


def test_fr328_a_blocked_creative_gets_its_own_do_not_publish_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The one console line that means "do not publish this" names the two files that explain it."""
    live = session(stages=["RENDER", "GAUNTLET", "DONE"])

    runner._gauntlet_rollup(live, _gated(blocked=1))

    lines = printed(capsys)
    for line in lines:
        console_safe(line)
    assert any("BLOCKED" in line and "BLOCKED.txt" in line for line in lines)


def _degraded_gate(unavailable: tuple[str, ...]) -> generate.Report:
    """One creative whose gate DEGRADED, with `unavailable` critics recorded on its round.

    The two causes of `degraded_gate` are told apart by exactly this field (Session 5.6/F7), so the
    fixture varies it and nothing else.
    """
    asset_id = "0001_carousel_linkedin"
    return generate.Report(records={asset_id: AssetRecord(
        asset_id=asset_id, source="t1", source_name="AI tool stacks", platform="linkedin",
        creative_format="carousel",
        gauntlet={"result": "degraded", "degraded_gate": True, "rerenders": 1,
                  "rerender_cost_usd": 0.04, "critic_cost_usd": 0.03,
                  "rounds": [{"round": 1, "failed_frames": [3], "rerendered": [3],
                              "critics": {"system": 1}, "unavailable": list(unavailable)}]})})


def test_fr325_the_degraded_gate_line_names_which_of_its_two_causes_it_had(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`degraded_gate` is one flag with two meanings, and the operator acts differently on each.

    A critic that could not be READ (D3) means the gate was thinner than configured — the deck may
    carry a defect nobody looked for, and the answer is to re-run. A standing DEMOTED defect means
    the gate saw everything and decided the deck ships anyway — the answer is to look at the frame
    and move on. One sentence for both would have been the cheapest line on the page and the least
    useful, so `_gauntlet_lines` forks on the dropped set.

    Session 5.7/F8 gave the flag a THIRD cause — a standing low-confidence system verdict — and
    deliberately no third console line: it shares the demotion sentence with FR-325's cosmetic
    tier because it shares the operator's answer, and which of the two it was is read off the
    round lines' codes and GAUNTLET_REPORT.yaml's confidences. So the fork stays two-way and the
    sentence names both demotion causes.
    """
    live = session(stages=["RENDER", "GAUNTLET", "DONE"])

    runner._gauntlet_rollup(live, _degraded_gate(()))
    cosmetic = printed(capsys)
    runner._gauntlet_rollup(live, _degraded_gate(("brief",)))
    dropped = printed(capsys)

    for line in (*cosmetic, *dropped):
        console_safe(line)
    assert any("cosmetic/low-confidence defect(s) stand and ship" in line
               for line in cosmetic), cosmetic
    assert not any("could not be read" in line for line in cosmetic)
    assert any("brief could not be read" in line and "(D3)" in line for line in dropped), dropped
    assert not any("cosmetic" in line for line in dropped)
    # Both forks still say DEGRADED and neither says BLOCKED: a degraded deck IS published.
    for lines in (cosmetic, dropped):
        assert any("gate DEGRADED" in line for line in lines)
        assert not any("BLOCKED" in line for line in lines)


def test_fr296_a_clean_gate_prints_its_header_and_nothing_else(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A round that found nothing is silence by design: the header already says how many passed,
    and a line per passing round would bury the one deck that did not."""
    live = session(stages=["RENDER", "GAUNTLET", "DONE"])

    runner._gauntlet_rollup(live, _gated(**{"pass": 6}))

    lines = printed(capsys)
    assert len(lines) == 1, "a clean gate owes the operator exactly one line"
    assert "6 judged -> 6 pass, 0 blocked, 0 stopped" in lines[0]


# ------------------------ FR-84/FR-326: the per-role LLM usage table (v2.2.0, D49)
#
# The gauntlet made LLM spend the LARGER half of a run's bill at worst case (spec §5: three critics
# x three rounds is comparable to the whole re-render budget), and until this table existed the
# operator's only view of it was one `llm $0.42` figure inside the spend total. Token counts are
# what actually move that number, so token counts are what it prints.


def test_fr326_the_llm_usage_table_folds_per_critic_roles_into_their_base_role(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`critic:brief` is a MODEL override, not a second budget: an operator reading a cost table
    wants "the critics cost $0.34", not three rows that have to be added up by hand.

    Row order is pipeline order (screen, copy, gate), the totals row adds up, and the render row
    carries no tokens by nature — it is priced per job, not per token.
    """
    live = session()
    live.llm_usage = {
        "analysis": runner._RoleUsage(2, 8_000, 4_400, 0.031),
        "copy": runner._RoleUsage(3, 12_000, 900, 0.021),
        "critic": runner._RoleUsage(9, 94_000, 6_300, 0.252),
        "critic:brief": runner._RoleUsage(3, 31_000, 2_100, 0.084),
    }

    table = runner._llm_usage_table(live, SimpleNamespace(render_usd=0.96))

    rows = [line.split() for line in table.splitlines()[2:]]
    assert [row[0] for row in rows] == ["analysis", "copy", "critic", "llm", "render"]
    critic = next(row for row in rows if row[0] == "critic")
    assert critic[1:4] == ["12", "125000", "8400"], "the override folds into its base role"
    total = next(row for row in rows if row[0] == "llm")  # "llm total" splits into two tokens
    assert total[2:5] == ["17", "145000", "13700"]
    assert rows[-1][-1] == "$0.96", "render spend rides the same block, without tokens"
    for line in table.splitlines():
        console_safe(line)
        assert len(line) <= 78, f"FR-286 allows 78: {line!r}"


def test_fr326_a_run_that_made_no_metered_call_says_so_rather_than_printing_an_empty_table(
) -> None:
    """A preview, a declined gate and an aborted run all land here; a header with no rows under
    it reads as a rendering bug, and one sentence is the honest answer."""
    assert "no metered LLM call" in runner._llm_usage_table(session(),
                                                            SimpleNamespace(render_usd=0.0))


# ------------------------------------- D54/FR-331: the four console surfaces the mode changes
#
# Compress mode is an operator TOGGLE, so the console has to say which contract the words on the
# frames actually shipped under — otherwise the one difference between two runs of the same config
# is invisible in `run.log` and the operator is comparing galleries from memory.
#
# The verbatim wordings are UNCHANGED, byte for byte, and are re-asserted here beside their
# compress twins rather than merely left alone: "the other branch still says what it said" is the
# regression these four surfaces most need, because each is a one-line ternary and a rewrite of
# either arm is a two-character edit.
#
# House rules apply to the new strings exactly as to the old ones: 78 columns, no ANSI, no `→`,
# `->` only (`console_safe`).


class CompressedCopy:
    """A stand-in for `copywrite.write_copy` returning a canned `CopyResult`.

    The COPY stage line counts off the per-asset PROVENANCE rather than off
    `config.run.carousel_copy_mode`, and this is why the double is shaped around provenance: the
    two disagree exactly where it matters — a compress-mode run whose call failed shipped the
    verbatim mapped deck, and a line claiming "compressed" over it would hide the degradation.
    """

    def __init__(self, modes: Sequence[str], languages: Sequence[str] = (),
                 not_translated: Sequence[int] = ()) -> None:
        self.modes = list(modes)
        # D63: the LANGUAGE receipt is a second axis on the SAME provenance, and the tag is a
        # third fact that can disagree with both — a deck that wanted a translation and did not
        # get one ships `copy_language: source` AND `copy_not_translated`, which is exactly the
        # combination the console has to keep telling apart.
        self.languages = list(languages)
        self.not_translated = set(not_translated)

    async def __call__(self, entries: Sequence[PlanEntry], **kwargs: Any) -> copywrite.CopyResult:
        result = copywrite.CopyResult()
        for index, item in enumerate(entries):
            mode = self.modes[index] if index < len(self.modes) else "verbatim"
            language = (self.languages[index] if index < len(self.languages)
                        else copywrite.LANGUAGE_SOURCE)
            result.copy[item.asset_id] = CopySet(asset_id=item.asset_id, language="en")
            result.provenance[item.asset_id] = copywrite.CopyProvenance(
                post_id="p1", copy_mode=mode, copy_language=language,
                source_language="de" if language == copywrite.LANGUAGE_TARGET else "")
            if index in self.not_translated:
                result.tags[item.asset_id] = (DegradationTag.COPY_NOT_TRANSLATED,)
        return result


async def copy_stage(modes: Sequence[str], monkeypatch: pytest.MonkeyPatch, *,
                     languages: Sequence[str] = (), not_translated: Sequence[int] = (),
                     stages: list[str] | None = None) -> runner._Session:
    """Run the real COPY stage over a canned result, so the printed line is the production one.

    Returns the session so a caller can read `log.warnings` — the D63 `copy_not_translated` block
    is a console line AND a `run.log` warning, and the pair is the contract.
    """
    live = session(stages=stages or ["COPY"])
    live.llm = object()  # `_metered` needs a client; the wrapped call is never invoked here
    item = topic("AI agents do the work")
    entries = [entry(index, fmt="carousel", trend=item) for index in range(len(modes))]
    monkeypatch.setattr(copywrite, "write_copy",
                        CompressedCopy(modes, languages, not_translated))
    await runner._write(live, entries, {item.history_key: item}, {})
    return live


async def test_fr296_the_copy_stage_line_names_the_contract_the_words_shipped_under(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The COPY closing line, both arms (FR-296 + D54).

    A run in which nothing compressed keeps the pre-D54 sentence byte for byte — that is the whole
    of the regression half. A run in which anything did says HOW MANY did, because a mixed run is
    the normal shape the day an image or a reel joins an all-carousel config, and "2 creative(s)
    compressed" over a batch that also quoted two would be false.
    """
    await copy_stage(["verbatim", "verbatim"], monkeypatch)
    verbatim = printed(capsys)

    await copy_stage(["compress", "compress"], monkeypatch)
    compressed = printed(capsys)

    await copy_stage(["compress", "verbatim"], monkeypatch)
    mixed = printed(capsys)

    for lines in (verbatim, compressed, mixed):
        console_safe("\n".join(lines))
        assert lines[0].startswith("[1/1] COPY"), "the opening line is untouched by the mode"
    assert "1 call(s) -> 2 creative(s) quoted verbatim" in verbatim[1], \
        "the pre-D54 sentence, unchanged, on a run where nothing compressed"
    assert "1 call(s) -> 2 creative(s), 2 compressed" in compressed[1]
    assert "1 call(s) -> 2 creative(s), 1 compressed" in mixed[1], "counted, never assumed"
    assert "quoted verbatim" not in compressed[1] and "quoted verbatim" not in mixed[1]


def test_fr297c_a_compressed_creative_gets_a_receipt_that_does_not_claim_a_quote() -> None:
    """FR-297c's second line has to change shape, not just wording, for a compressed deck.

    Its slides are the copy model's compressions of that post's panels, so there is no "exact
    string quoted" to print and `copy_source_refs` is empty by contract (FR-302 as amended).
    Printing the verbatim receipt with an empty quote would read as "this creative quoted nothing
    from a post it names", which is the opposite of what happened. The post is still named — the
    provenance CLAIM is unchanged, only the transform is — and the line points at `meta.yaml`'s
    `panel_map`, where every row carries the source panel beside what shipped.
    """
    item = topic("AI agents do the work", strength=1.0)
    deck = entry(0, fmt="carousel", trend=item, style="anime-noir-statement")
    deck.status = PlanEntryStatus.SUCCESS
    records = {deck.asset_id: record(deck, item, cost=0.180, quoted=item.posts[0], refs={},
                                     copy_mode="compress")}
    copy = {deck.asset_id: CopySet(asset_id=deck.asset_id, language="en",
                                   slide_texts=["Ship it, then measure."])}

    block = runner._provenance_block([deck], records, {item.history_key: item}, copy)

    console_safe(block)
    receipt = block.splitlines()[3].strip()
    assert receipt.startswith("compressed P1 @creator0 ")
    assert item.posts[0].post_id in receipt, "the post is still named — the claim is unchanged"
    assert receipt.endswith("-> panel_map"), "where the operator reads both sides of each row"
    assert '"' not in receipt, "there is no quoted string to show, so none is invented"
    assert "quoted" not in receipt


def test_fr297c_the_verbatim_receipt_is_untouched_beside_its_compress_twin() -> None:
    """The regression half of the line above: a `verbatim` record on the same code path still
    prints the pre-D54 receipt, first ~24 characters and all. Both arms in one test, because the
    two are one ternary and an edit to either is a two-character change."""
    item = topic("AI agents do the work", strength=1.0)
    image = entry(0, trend=item)
    image.status = PlanEntryStatus.SUCCESS
    records = {image.asset_id: record(image, item, cost=0.041, quoted=item.posts[0])}
    copy = {image.asset_id: CopySet(asset_id=image.asset_id, language="en",
                                    headline="AI agents do the work for you while you sleep")}

    block = runner._provenance_block([image], records, {item.history_key: item}, copy)

    console_safe(block)
    receipt = block.splitlines()[3].strip()
    assert receipt.startswith("quoted P1 @creator0 ")
    assert '"AI agents do the work' in receipt, "the first ~24 characters, quoted verbatim"
    assert "panel_map" not in receipt and "compressed" not in receipt


def test_fr140_the_preview_copy_header_says_which_contract_wrote_the_words() -> None:
    """`--preview-analysis` is compress mode's CHEAPEST review: it costs the copy call and nothing
    else, and reading the compressed slides there is what tells the operator whether a paid run is
    worth submitting. So the header has to say which contract produced them — and, on a mixed
    batch, how many decks each one covered."""
    item = topic("AI agents do the work")
    deck = entry(0, fmt="carousel", trend=item)
    image = entry(1, trend=item)
    result = copywrite.CopyResult()
    for plan_entry, mode in ((deck, "compress"), (image, "verbatim")):
        result.copy[plan_entry.asset_id] = CopySet(
            asset_id=plan_entry.asset_id, language="en", caption="A caption.",
            slide_texts=["Ship it, then measure."] if mode == "compress" else [])
        result.provenance[plan_entry.asset_id] = copywrite.CopyProvenance(post_id="p1",
                                                                          copy_mode=mode)

    mixed = previews._copy_block(result, [deck, image])
    for plan_entry in (deck, image):
        result.provenance[plan_entry.asset_id] = copywrite.CopyProvenance(post_id="p1")
    verbatim = previews._copy_block(result, [deck, image])

    console_safe(mixed)
    console_safe(verbatim)
    assert mixed.splitlines()[0] == "Copy — 2 creative(s), 1 deck(s) compressed"
    assert "from the source post's panels to the style's budget, in the post's own" in mixed
    assert "the rest quoted verbatim, nothing rendered (FR-140/FR-331/FR-353)" in mixed
    assert "under copy mode auto, only the panels that overflowed it" in mixed, \
        "D62: the header covers both compressing contracts, so it names the difference"
    # …and with nothing compressed the pre-D54 header returns, byte for byte.
    assert verbatim.splitlines()[0] == "Copy — 2 creative(s), quoted verbatim in the language"
    assert verbatim.splitlines()[1] == \
        "  of the post each string came from; nothing was rendered (FR-140)"
    assert "compressed" not in verbatim


def test_fr140_a_compressed_creatives_preview_row_says_compressed_and_prints_no_refs() -> None:
    """The per-creative rows under that header, on the same terms: `compressed` where a quoting
    creative says `quoted`, and no `refs` row at all — it resolved no labels, so there are none to
    print, and an empty `refs` line reads as a lost receipt rather than an absent one."""
    item = topic("AI agents do the work")
    deck = entry(0, fmt="carousel", trend=item)
    result = copywrite.CopyResult()
    result.copy[deck.asset_id] = CopySet(asset_id=deck.asset_id, language="en",
                                         caption="A caption.",
                                         slide_texts=["Ship it, then measure."])
    result.provenance[deck.asset_id] = copywrite.CopyProvenance(post_id="p1",
                                                                copy_mode="compress")

    block = previews._copy_block(result, [deck])

    console_safe(block)
    row = next(line for line in block.splitlines() if "compressed" in line and "deck(s)" not in line)
    assert row.strip().startswith("compressed"), "the transform, where a quote would say `quoted`"
    assert "p1" in row, "the post is still named — the provenance claim is unchanged"
    assert "refs" not in block, "FR-302: a compressed slide resolved no label to print"
    assert "Ship it, then measure." in block, "the compressed slide is READ here — that is the job"


# ------------------------------------ D62/FR-353: the same four surfaces, for the AUTO contract
#
# Auto is the mode the three shipped brand configs pin, so these are the lines almost every real
# run now prints. What each has to avoid is the same trap in two directions: `quoted` over a deck
# whose long panels were rewritten is false, and `compressed` over a deck whose short panels were
# quoted word for word is equally false. Every surface below names the MODE instead of picking one
# of the two halves and calling it the deck.


async def test_fr353_the_copy_stage_line_counts_auto_decks_and_names_both_contracts(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The COPY closing line under D62, all three of its compressing shapes.

    An `auto` deck did not ship pure quotes either, so it is counted in the same number. What it
    does NOT get is a qualifier bolted onto the compress sentence: `_stage` gives this body 54
    columns and `2 compressed (auto or compress)` does not fit at realistic counts. So a pure-auto
    run says `auto-compressed`, and only a genuinely mixed run — the one shape where the split is
    not already implied — pays the extra `(N auto)` clause.
    """
    await copy_stage(["auto", "auto"], monkeypatch)
    auto = printed(capsys)

    await copy_stage(["auto", "verbatim"], monkeypatch)
    mixed = printed(capsys)

    await copy_stage(["auto", "compress"], monkeypatch)
    both = printed(capsys)

    for lines in (auto, mixed, both):
        console_safe("\n".join(lines))
        assert lines[0].startswith("[1/1] COPY"), "the opening line is untouched by the mode"
        assert all(len(line) <= WIDTH for line in lines), lines
    assert "1 call(s) -> 2 creative(s), 2 auto-compressed" in auto[1]
    assert "1 call(s) -> 2 creative(s), 1 auto-compressed" in mixed[1], \
        "counted off the per-asset receipt, never assumed from the config's mode"
    assert "1 call(s) -> 2 creative(s), 2 compressed (1 auto)" in both[1], \
        "the mixed shape is the only one that has to name the split"
    assert "quoted verbatim" not in auto[1] and "quoted verbatim" not in both[1]


def test_fr353_an_auto_creatives_receipt_names_the_mode_rather_than_half_the_deck() -> None:
    """FR-297c's line 2 for an auto deck. Neither of the two pre-D62 shapes is true of it: the
    verbatim receipt would present ONE quoted slide as the receipt for a deck that also compressed
    three, and the compress receipt would deny the rows that really are byte-quotes. So the line
    says `auto` and points at the `panel_map`, which is the only place the split is recorded row
    by row."""
    item = topic("AI agents do the work", strength=1.0)
    deck = entry(0, fmt="carousel", trend=item, style="anime-noir-statement")
    deck.status = PlanEntryStatus.SUCCESS
    records = {deck.asset_id: record(deck, item, cost=0.180, quoted=item.posts[0],
                                     refs={"slide_1": "P1.panel.1"}, copy_mode="auto")}
    copy = {deck.asset_id: CopySet(asset_id=deck.asset_id, language="en",
                                   slide_texts=["A panel short enough to quote whole.",
                                                "Ship it, then measure."])}

    block = runner._provenance_block([deck], records, {item.history_key: item}, copy)

    console_safe(block)
    receipt = block.splitlines()[3].strip()
    assert receipt.startswith("auto P1 @creator0 ")
    assert item.posts[0].post_id in receipt, "the post is still named — the claim is unchanged"
    assert receipt.endswith("-> panel_map"), "where the operator reads both sides of each row"
    assert '"' not in receipt, "no single slide is promoted into being the deck's receipt"
    assert "compressed" not in receipt and "quoted" not in receipt
    assert all(len(line) <= WIDTH for line in block.splitlines()), block


def test_fr353_an_auto_creatives_preview_row_says_auto_and_DOES_print_its_refs() -> None:
    """The `--preview-analysis` row, and the one place auto differs from compress by ADDING rather
    than removing: an auto deck resolved a real `P<n>.panel.<i>` label for every panel that fitted
    its budget and shipped that panel's bytes, so those labels exist and are worth reading. The
    refs row is the list of slides the operator can check against the post roster; the slides
    missing from it are the ones that were compressed."""
    item = topic("AI agents do the work")
    deck = entry(0, fmt="carousel", trend=item)
    result = copywrite.CopyResult()
    result.copy[deck.asset_id] = CopySet(asset_id=deck.asset_id, language="en",
                                         caption="A caption.",
                                         slide_texts=["A panel short enough to quote whole.",
                                                      "Ship it, then measure."])
    result.provenance[deck.asset_id] = copywrite.CopyProvenance(
        post_id="p1", refs={"slide_1": "P1.panel.1"}, copy_mode="auto")

    block = previews._copy_block(result, [deck])

    console_safe(block)
    row = next(line for line in block.splitlines() if line.strip().startswith("auto"))
    assert "p1" in row, "the post is named exactly as it is on every other contract"
    assert "slide_1=P1.panel.1" in block, "FR-353: the QUOTED rows kept real labels — print them"
    assert not any(line.strip().startswith("compressed") for line in block.splitlines()), \
        "one deck, one row label, and it is the mode — the header's own count is a separate line"
    assert "Ship it, then measure." in block, "the compressed slide is READ here — that is the job"
    assert all(len(line) <= WIDTH for line in block.splitlines()), block


def test_fr353_the_preflight_language_hint_names_auto_and_what_it_leaves_alone() -> None:
    """The pre-flight arm, measured for width the way this file measures every hint: through
    `Preflight.report`, which is the one place layout happens. Auto's clause is the longest of the
    three and is the one that could push a wrapped line past FR-286's ceiling."""
    config = Config()
    config.run.gauntlet.enabled = False
    config.run.carousel_copy_mode = "auto"
    hints: list[str] = []

    preflight._check_language_hint(config, [entry(0, fmt="carousel")], hints)

    for line in preflight.Preflight(hints=tuple(hints)).report.splitlines():
        assert len(line) <= WIDTH, f"{len(line)} chars (FR-286 allows {WIDTH}): {line!r}"
        assert "→" not in line and "\x1b" not in line, line
    assert len(hints) == 1
    assert "carousel_copy_mode: auto" in hints[0] and "FR-353" in hints[0]
    assert "only the panels over the style's budget are compressed" in hints[0]
    assert "the rest ship verbatim" in hints[0]
    assert "consider --gauntlet" in hints[0], "the hint's whole point survives the branch"


def test_fr333_the_preflight_language_hint_states_the_compress_contract_when_it_applies() -> None:
    """FR-333's pre-flight display rule rides the hint an operator is already reading.

    Compress makes the language question SHARPER, not softer: a compressed line is written by a
    model rather than copied byte for byte, so drifting out of the source's language is a failure
    mode verbatim mode simply does not have — and the `translated` defect blocks a whole deck.
    Three shapes, one hint each, and the verbatim wording is unchanged where it still applies.
    """
    deck = entry(0, fmt="carousel")
    config = Config()
    config.run.gauntlet.enabled = False

    config.run.carousel_copy_mode = "compress"
    compressed: list[str] = []
    preflight._check_language_hint(config, [deck], compressed)

    config.run.carousel_copy_mode = "verbatim"
    verbatim: list[str] = []
    preflight._check_language_hint(config, [deck], verbatim)

    # A hint is DATA, not a console line: `Preflight.report` is the one place every grade passes
    # through and it wraps at 76, because layout belongs at the printer and never in a string that
    # also lands in events.jsonl. So the width rule is measured on what actually PRINTS, and not
    # through `console_safe` — the shipped hints have always carried `§` (a PRD section reference
    # is what makes a hint actionable), which is outside `util.fit`'s console-safe set by design.
    for line in preflight.Preflight(hints=tuple(compressed + verbatim)).report.splitlines():
        assert len(line) <= WIDTH, f"{len(line)} chars (FR-286 allows {WIDTH}): {line!r}"
        assert "→" not in line and "\x1b" not in line, line
    assert len(compressed) == 1 and len(verbatim) == 1
    assert "carousel on-image text is compressed from the source post's panels to the" in \
        compressed[0]
    assert "carousel_copy_mode: compress" in compressed[0] and "FR-331" in compressed[0]
    assert "consider --gauntlet" in compressed[0], "the hint's whole point survives the branch"
    # The pre-D54 sentence, unchanged, on a run that did not opt in.
    assert verbatim[0].startswith("on-image text is quoted verbatim from the source post, in "
                                  "that post's own language (FR-294)")
    assert "compressed" not in verbatim[0]


def test_fr333_the_preflight_hint_ignores_the_mode_on_a_run_with_no_carousels() -> None:
    """`carousel_copy_mode` governs bound carousel decks and nothing else, so an images-only run
    in compress mode says exactly what it said before D54 — claiming a compress contract over a
    batch of single images would be a false statement at the screen before the money moves."""
    config = Config()
    config.run.gauntlet.enabled = False
    config.run.carousel_copy_mode = "compress"
    hints: list[str] = []

    preflight._check_language_hint(config, [entry(0)], hints)

    assert len(hints) == 1 and "quoted verbatim from the source post" in hints[0]
    assert "compress" not in hints[0]


def test_fr286_a_label_that_fills_the_row_column_still_gets_its_separating_space() -> None:
    """The D54 collision, closed at `previews._rows` and pinned here as bytes.

    `:<{_ROW_LABEL}}` pads a SHORT label out to the column and supplies the gap as a side effect of
    the padding. It does nothing at all for a label that already fills the column — and
    `compressed` is ten characters against a nine-column label, so the preview's provenance row
    printed `compressedp1`: the transform welded onto the post id, in the one surface whose entire
    job is to be read.

    Both arms are asserted as exact bytes. The fix is a branch on label LENGTH, so the only way to
    be sure it did not re-pad every other row in every preview this tool prints is to pin one row
    that takes it and one that does not — every label this module ships (`quoted`, `on-image`,
    `caption`, `slide 12`, `overlay`, `motion`, `refs`, `tags`) is eight characters or fewer and
    must come out exactly as it always has.
    """
    item = topic("AI agents do the work")
    deck = entry(0, fmt="carousel", trend=item)
    result = copywrite.CopyResult()
    result.copy[deck.asset_id] = CopySet(asset_id=deck.asset_id, language="en",
                                         caption="A caption.",
                                         slide_texts=["Ship it, then measure."])

    result.provenance[deck.asset_id] = copywrite.CopyProvenance(post_id="p1",
                                                                copy_mode="compress")
    compressed = previews._copy_block(result, [deck])
    result.provenance[deck.asset_id] = copywrite.CopyProvenance(
        post_id="p1", refs={"slide_1": "P1.panel.1"})
    verbatim = previews._copy_block(result, [deck])

    console_safe(compressed)
    console_safe(verbatim)
    assert "      compressed p1" in compressed.splitlines(), \
        "label, ONE space, content — never the `compressedp1` weld"
    assert "compressedp1" not in compressed
    # The unchanged arm, byte for byte: a short label is still padded to the nine-column grid, so
    # `quoted`/`refs`/`slide 1`/`caption` all start their content in the same column they always
    # did — which is what makes a preview readable as a table rather than as a list.
    rows = verbatim.splitlines()
    assert "      quoted   p1" in rows
    assert "      refs     slide_1=P1.panel.1" in rows
    assert "      slide 1  Ship it, then measure." in rows
    assert "      caption  A caption." in rows
    assert len({len(row) - len(row.lstrip()) for row in rows if row.startswith("      ")}) == 1, \
        "every field row keeps the same six-space indent"


def test_fr286_the_widest_row_this_module_can_print_still_fits_the_console() -> None:
    """The arithmetic behind the fix, asserted rather than trusted: 6 indent + a 10-character
    label + 1 separating space + `_ROW_WIDTH` of text is 78, which is exactly FR-286's ceiling and
    not one column over it. `_rows` is measured directly, on the longest label the module ships and
    a value long enough to fill the wrap width — the assembled preview above cannot reach this
    worst case because its own values are short."""
    # Real prose, because `wrapped` breaks on word boundaries and never mid-word (FR-101's rule,
    # applied to layout): a 400-character single token is not a shape this module can print.
    lines = previews._rows("compressed", " ".join(["compressed"] * 60))

    assert len(lines) > 1, "a value that long must WRAP rather than overflow or vanish"
    for line in lines:
        assert len(line) <= WIDTH, f"{len(line)} chars (FR-286 allows {WIDTH}): {line!r}"
    assert lines[0].startswith("      compressed compressed"), "label, one space, then content"
    assert lines[1].startswith(" " * (6 + previews._ROW_LABEL)), \
        "continuation lines align under the content, not under the label"

# ------------------------- D56/FR-334-337: what MATCHED assignment adds to the ASSIGN stage
#
# Matched assignment is an overlay on the FR-291 rotation, and the console is where an operator
# sees which of the two chose each look. Four surfaces are new, and each is a §1.10 rule applied
# to a new fact rather than a new rule:
#
# * a per-creative CONTINUATION line under the existing receipt (origin/fit, then the model's own
#   reason) — a continuation and not four more columns, because FR-286's 78 are already spent;
# * a `matched N of M` tally, so "the mode is on" is arithmetic rather than an announcement;
# * the GAP REPORT — the archetypes the matcher wanted and this registry has no style for. D56
#   decision 3: the engine never synthesizes a style at runtime, so a miss is written down and the
#   operator authors it deliberately;
# * exactly ONE `style_match_degraded` warning for a whole-call failure, in the `filter_degraded`
#   posture (FR-294): said after the receipts, never instead of them, and the run continues.
#
# Everything below is offline. Two tests call the pure block builders; three drive `_assign_visuals`
# with `style_match.match` stubbed, which is the seam — the matcher's OWN fail-open behaviour is
# `tests/test_style_match.py`'s subject, and asserting it twice would be two owners of one rule.


def _match_style(key: str, **over: object) -> MetaStyle:
    """One registry entry, affine to everything, so a fixture's pool is never the variable."""
    fields: dict[str, object] = {"render_prompt": "Flat graphic card, centred subject.",
                                 "match_profile": "Suits short single-idea sources.",
                                 "format_affinity": ["image", "carousel", "reel"]}
    fields.update(over)
    return MetaStyle(key=key, **fields)  # type: ignore[arg-type]


def _match_registry(*keys: str) -> styles.StyleRegistry:
    return styles.StyleRegistry(version=1, styles=[_match_style(key) for key in keys],
                                origin="prompts/styles.yaml", content_hash="0123456789ab")


def _match_session(assignment: str = "matched") -> runner._Session:
    """An ASSIGN-stage session: matched mode, a three-style registry, an unused client."""
    config = Config()
    config.styles.assignment = assignment
    config.styles.enabled = []
    live = session(config=config, stages=["ASSIGN"])
    live.registry = _match_registry("s0", "s1", "s2")
    live.llm = object()  # `_metered` needs a client; the stubbed matcher never calls through it
    return live


def _answer(item: PlanEntry, **over: object) -> style_match.Match:
    return style_match.Match(asset_id=item.asset_id, **over)  # type: ignore[arg-type]


def _stub_matcher(monkeypatch: pytest.MonkeyPatch,
                  answers: dict[str, style_match.Match]) -> list[int]:
    """Replace `style_match.match` with one that answers `answers`; returns a call counter."""
    calls: list[int] = []

    async def matcher(entries: Any, registry: Any, topics: Any, cfg: Any, llm: Any) -> Any:
        calls.append(len(list(entries)))
        return answers

    monkeypatch.setattr(runner.style_match, "match", matcher)
    return calls


def test_fr337_the_assign_receipt_gains_an_origin_fit_and_reason_continuation_line() -> None:
    """The per-creative provenance line, in all four of the states the vocabulary can produce.

    Two of them print NOTHING, and that is the load-bearing half. A `rotation`-mode run has no
    provenance to report — the receipt above it already said everything there is to say about how
    the style was chosen — and a `rotation_fallback` means every entry in the plan carries the SAME
    whole-call failure, which the single warning below the loop says once instead of N times. A
    line per creative in either case would be D45's "a heading with no rows under it" defect wearing
    a different shape: noise an operator learns to skip, on the one surface that has to stay worth
    reading.

    A `low` fit DOES print, on `rotation/low`: that entry got a real answer, the answer was "nothing
    here fits", and the operator wants the sentence that said so beside the gap report.
    """
    matched = entry(0)
    matched.style_origin, matched.style_fit = "matched", "high"
    matched.style_reason = "seven dense labelled panels suit a ledger deck"  # 45 of the 49 columns
    low = entry(1)
    low.style_origin, low.style_fit = "rotation", "low"
    low.style_reason = "no enabled style renders a social screenshot"
    low.style_wanted = "social screenshot card"
    baseline, degraded = entry(2), entry(3)
    baseline.style_origin = "rotation"  # what `_assign_visuals` stamps on every entry, pre-overlay
    degraded.style_origin = "rotation_fallback"
    degraded.style_reason = f"{style_match.DEGRADED_MARKER}: the match call raised TimeoutError"

    lines = {item.asset_id: runner._match_receipt(item)
             for item in (matched, low, baseline, degraded)}

    for line in lines.values():
        console_safe(line)
    assert lines[matched.asset_id].split() == [
        "matched/high", "seven", "dense", "labelled", "panels", "suit", "a", "ledger", "deck"]
    assert lines[matched.asset_id].startswith(" " * 13), "it hangs under its creative's receipt"
    assert "…" not in lines[matched.asset_id], "a reason inside 49 columns arrives whole"
    assert lines[low.asset_id].startswith(" " * 13 + "rotation/low "), \
        "a low fit keeps its number — the answer was real, it just did not fit"
    assert lines[baseline.asset_id] == "", "a rotation-mode entry has no provenance to add"
    assert lines[degraded.asset_id] == "", \
        "a whole-call failure is ONE warning below the loop, never one line per creative"


def test_fr286_the_widest_provenance_line_the_vocabulary_can_produce_still_fits() -> None:
    """The arithmetic `_match_receipt`'s own docstring states, asserted rather than trusted:
    13 indent + 15 label + 1 gutter + 49 reason = 78, which is exactly FR-286's ceiling.

    `rotation/medium` is the widest label the origin/fit vocabulary can spell (15 characters) and
    `reason` is MODEL-AUTHORED, which is why it is last on the line and why it is the only thing on
    it allowed to be cut. This session already fixed a real truncation defect caused by exactly this
    kind of growth in `menu.py`, so the ceiling is measured on the WORST case rather than on a
    typical one: a reason at the matcher's own `_MAX_REASON_CHARS` bound with no word boundary in
    it, which is the only shape that makes `util.fit` return its full width (a reason with spaces
    backs up to the last boundary and comes out shorter). Both shapes are asserted, because "it
    fits" has to hold for the one that fills the line and not only for the one that does not reach
    it.
    """
    worst, spaced = entry(0), entry(1)
    for item in (worst, spaced):
        item.style_origin, item.style_fit = "rotation", "medium"
    worst.style_reason = "x" * style_match._MAX_REASON_CHARS
    spaced.style_reason = "reason " * 40

    line, wrapped_line = runner._match_receipt(worst), runner._match_receipt(spaced)

    assert len("rotation/medium") == 15, "the widest label the origin/fit vocabulary can produce"
    assert 13 + 15 + 1 + 49 == WIDTH, "the arithmetic `_match_receipt`'s docstring states"
    assert len(line) == WIDTH, f"{len(line)} chars — this shape is meant to fill FR-286 exactly"
    assert len(wrapped_line) <= WIDTH, f"{len(wrapped_line)} chars (FR-286 allows {WIDTH})"
    console_safe(line)
    console_safe(wrapped_line)
    # …and the cut lands on the reason, never on the label the operator needs to read.
    for cut in (line, wrapped_line):
        assert cut.startswith(" " * 13 + "rotation/medium ")
        assert cut.endswith("…"), "util.fit marks the cut rather than ending mid-word"
    assert style_match._MAX_REASON_CHARS > WIDTH, \
        "the matcher's own bound is looser than this line, so `fit` is what really holds it"


def test_fr334_the_gap_report_lists_distinct_archetypes_commonest_first_and_is_silent_when_clean(
) -> None:
    """D56 decision 3 in console form: the shopping list for `prompts/styles.yaml`.

    Distinct wants with a count, not one row per creative — reprinting the same archetype four
    times would bury how many distinct gaps there really are, which is the only number that turns
    this block into an authoring decision. Commonest first for the same reason.

    Silent on a clean run, because the alternative is a heading with no rows under it (D45), and
    silent on a matched run where every creative found a style — which is the normal outcome and
    must not print a block that reads like a finding.
    """
    wanted = []
    for index, want in enumerate(["numbered listicle deck"] * 3 + ["social screenshot card"] * 2
                                 + ["dark benchmark diagram"]):
        item = entry(index)
        item.style_wanted = want
        wanted.append(item)

    block = runner._style_gap_block(wanted)

    console_safe(block)
    lines = block.splitlines()
    assert lines[0].strip().startswith("style gap: 3 archetype(s)"), "DISTINCT wants, not creatives"
    assert "styles.yaml (FR-334)" in lines[1]
    assert [line.strip() for line in lines[2:]] == [
        "- numbered listicle deck (3 creative(s))",
        "- social screenshot card (2 creative(s))",
        "- dark benchmark diagram (1 creative(s))"], "commonest first, then alphabetical"
    assert runner._style_gap_block([entry(0), entry(1)]) == "", \
        "a run that wanted nothing prints no block at all"


def test_fr334_a_gap_report_row_of_runaway_model_prose_is_still_bounded_to_the_console() -> None:
    """Every row is free model text, so every row goes through `util.fit` — the same discipline the
    receipt's reason gets. A matcher that answered with a paragraph would otherwise wrap the
    operator's console and take the block's readability with it."""
    runaway = entry(0)
    runaway.style_wanted = "listicle " * 40

    block = runner._style_gap_block([runaway])

    console_safe(block)
    assert block.splitlines()[2].strip().startswith("- listicle listicle"), "still named"


# ------------------------------- D61/FR-355: the concentration alarm on the same ASSIGN stage
#
# The gap report above says "the registry has no style for what these creatives are"; this one
# says "the registry HAS styles and the run kept picking the same one". Both are supply findings
# an operator acts on by authoring, never by re-running, so both are warnings with no effect on a
# single render — and both are silent on a healthy plan, because a line that prints every time is
# furniture rather than an alarm.


def _plan(*keys: str) -> list[PlanEntry]:
    """A plan carrying exactly these style keys, in order — `""` is an override brief (M14)."""
    return [entry(index, style=key) for index, key in enumerate(keys)]


def test_fr355_one_style_over_half_the_plan_prints_the_alarm_and_fills_fr286_exactly() -> None:
    """The plan document's own worked example, asserted character for character.

    `icon-ledger-carousel 6/9` is the shape D61 was written for: nine carousels, a twelve-key
    enabled pool, and two thirds of the run wearing one style. Six of nine is not a defect — it
    is a legal answer from both assignment algorithms — so the line reports and never refuses.

    The width is the second half of the point. This exact line is 78 characters, which is FR-286's
    ceiling to the column, and it got there with the longest style key the shipped registry
    actually holds. That is not luck: `_concentration_line` sizes the key from what the counts
    spend, so the arithmetic in its docstring (10 + 15 + 20 + 1 + 3 + 29) is the line below.
    """
    plan = _plan(*["icon-ledger-carousel"] * 6, "letterpress-print-carousel", "neon-glass-dark",
                 "aurora-white-deck")

    line = runner._concentration_line(plan)

    console_safe(line)
    assert line == "          concentration: icon-ledger-carousel 6/9 (>1/2) - pool may be starved"
    assert len(line) == WIDTH, f"{len(line)} chars — this shape is meant to fill FR-286 exactly"
    assert line.startswith(" " * 10), "the ASSIGN receipts' own indent, so it hangs with them"


def test_fr355_the_distinct_count_trigger_needs_a_plan_of_five_and_an_even_split_to_be_seen(
) -> None:
    """Trigger (b) — "fewer than 3 distinct styles on a plan of 5+", and where it can show.

    A MEASURED consequence of the two rules rather than a design choice, and worth pinning because
    it is not obvious from reading them: on 5 creatives across 2 styles the split is 3/2 or 4/1,
    and `count * 2 > total` is true of both, so trigger (a) claims that plan and names the culprit.
    The distinct-count line is only ever the whole story on an EVEN plan split exactly down the
    middle — 3/3 on six — where no style holds more than half and the alarm would otherwise
    have nothing to say about a run that used two styles all day.

    Both are asserted here, because "the 5-creative plan still warns" is the operator-facing
    promise and "it warns through arm (a)" is the reason the (b) line does not appear there.
    """
    even = runner._concentration_line(_plan("s0", "s1", "s0", "s1", "s0", "s1"))
    lopsided = runner._concentration_line(_plan("s0", "s1", "s0", "s1", "s0"))
    single = runner._concentration_line(_plan(*["s0"] * 5))

    for line in (even, lopsided, single):
        console_safe(line)
    assert even == "          concentration: only 2 style(s) across 6 - pool may be starved"
    assert lopsided == "          concentration: s0 3/5 (>1/2) - pool may be starved", \
        "both triggers hold and (a) wins: it names the style, which is the actionable half"
    assert single == "          concentration: s0 5/5 (>1/2) - pool may be starved", \
        "a one-style plan is the starvation this alarm is named after"


def test_fr355_a_healthy_spread_and_a_plan_too_small_to_judge_both_print_nothing() -> None:
    """D45's rule applied to an alarm: silence is the normal outcome and has to be the normal
    output.

    Three styles across nine creatives is the spread D61 wants and prints nothing at all. The
    4-creative 2/2 plan is the other half of the same discipline — 2 of 4 is not MORE than half
    (the comparison is strict), and trigger (b)'s floor of 5 exists precisely so that small plans,
    which cannot be spread by construction, are not scolded for their size on every run.
    """
    spread = runner._concentration_line(_plan("a", "b", "c", "a", "b", "c", "a", "b", "c"))
    small = runner._concentration_line(_plan("a", "a", "b", "b"))
    empty = runner._concentration_line([])

    assert spread == "", "3 of 9 is not more than half and 3 distinct clears the floor"
    assert small == "", "an exact half is a spread, and 4 creatives are below the (b) floor"
    assert empty == "", "no plan, no finding"


def test_fr355_override_briefs_count_in_neither_the_numerator_nor_the_denominator() -> None:
    """M14 in the alarm's arithmetic: a creative with no style channel is not a starved one.

    An `override` brief's `style_key` stays `""` all run (`_assign_visuals` filters those entries
    out before `assign_styles` ever sees them), so counting them would make every brief-only plan
    read as a starved pool — the one shape that deliberately asked for no pool at all. Both
    halves are pinned: they cannot ADD a distinct "style" to the denominator, and cannot rescue a
    genuinely concentrated plan by padding the total until the majority test stops being true.
    """
    brief_only = runner._concentration_line(_plan("", "", "", "", "", ""))
    padded = runner._concentration_line(_plan("s0", "s0", "s0", "s1", "", "", "", ""))

    console_safe(padded)
    assert brief_only == "", "six creatives, zero style channels, nothing to report"
    assert padded == "          concentration: s0 3/4 (>1/2) - pool may be starved", \
        "4 styled creatives, not 8 — the four briefs are outside both sides of the fraction"


def test_fr286_the_widest_concentration_line_a_registry_key_can_produce_still_fits() -> None:
    """The style key is registry-authored and therefore unbounded, so it is the one token on this
    line allowed to be cut — the same discipline `_match_receipt` gives the model's reason.

    A 40-character key is roughly double anything the shipped registry holds, which is the point:
    the width guarantee has to come from the arithmetic and not from the fixture. The cut is
    checked too, because a line that fits by silently deleting the style name would pass a length
    assertion and tell the operator nothing about which style ran away with the plan.
    """
    long_key = "photoreal-ambient-caption-with-a-long-tail"[:40]
    wide = runner._concentration_line(_plan(*[long_key] * 6, "s1", "s2", "s3"))
    many = runner._concentration_line(_plan(*[long_key] * 60, *(f"s{n}" for n in range(40))))

    for line in (wide, many):
        console_safe(line)
        assert len(line) <= WIDTH, f"{len(line)} chars (FR-286 allows {WIDTH}): {line!r}"
        assert "concentration: photoreal-ambie" in line, "cut, but still named"
        assert line.endswith("(>1/2) - pool may be starved"), "the verdict is never the cut"
    assert len(long_key) == 40, "the fixture must be wider than any key the registry holds"
    assert "…" in wide, "util.fit marks the cut rather than ending mid-word"
    assert len(many.split()[1]) < len(wide.split()[1]), \
        "a 3-digit tally buys its extra columns out of the key, never off the end of the line"


def test_fr355_a_rotation_run_over_a_one_style_registry_says_so_on_the_console_and_in_the_log(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The wire-in, driven through the real ASSIGN narration in ROTATION mode.

    A registry offering one usable style is the starved pool in its purest form, and the FR-291
    scan will dutifully put all five creatives in it. That is the case FR-355 exists for, and it
    has nothing to do with the matcher — which is why the alarm sits outside the `matched_mode`
    branch and why this test makes no model call at all.

    `run.log` gets BOTH numbers (the majority and the distinct count) while the console gets one
    line, because the two triggers are two different authoring problems and the log is read after
    the fact by someone who has to tell them apart.
    """
    live = _match_session(assignment="rotation")
    live.registry = _match_registry("only-style")
    entries = [entry(index) for index in range(5)]

    asyncio.run(runner._assign_visuals(live, entries, {}, brief_only=False))

    lines = printed(capsys)
    for line in lines:
        console_safe(line)
    alarm = [line for line in lines if "concentration:" in line]
    assert alarm == ["          concentration: only-style 5/5 (>1/2) - pool may be starved"]
    assert [code for code, _ in live.log.warnings] == ["style_concentration"]
    assert live.log.warnings[0][1] == ("only-style on 5 of 5 styled creative(s), 1 distinct "
                                       "style(s) - the pool may be starved"), \
        "the log states both triggers' numbers; the console chose one of them to say"
    fields = next(data for code, _, data in live.log.events if code == "visuals_assigned")
    assert fields["style_key"] == "only-style", "the alarm counted what the receipts printed"


def test_fr355_the_alarm_lands_in_preview_analysis_through_the_same_borrowed_function() -> None:
    """FR-286/FR-355's other required surface, and the reason it is a borrow rather than a copy.

    The PRD puts the concentration line in `--preview-analysis` on purpose: that mode is the
    ~$0.30 place to learn that nine carousels all want one style, and a paid run is the $5 one.
    `previews._assign_block` does NOT go through `_assign_visuals` — previews assign styles on
    their own prefix path — so the line had to be wired there too, and it is wired by calling the
    runner's own function, exactly as that block already borrows `_match_receipt` and
    `_style_gap_block`. The identity assertion is the part that matters: a second implementation
    of an operator-facing line is free to drift from the one a paid run prints.

    Unlike the two blocks it sits under, this one is NOT silent in rotation mode — a rotation
    that keeps landing on one style is the same starved pool as a matcher that does — so the
    assertion below runs on a plain unmatched plan, which is the ordinary preview.
    """
    assert previews._concentration_line is runner._concentration_line, \
        "borrowed, never re-formatted — two shapes would be free to disagree about one run"
    live = _plan(*["icon-ledger-carousel"] * 6, "s1", "s2", "s3")

    block = previews._assign_block(live, {}, _match_registry("icon-ledger-carousel"))

    console_safe(block)
    assert block.splitlines()[-1] == \
        "          concentration: icon-ledger-carousel 6/9 (>1/2) - pool may be starved", \
        "last line of the assignment block, under the receipts it counted"
    clean = previews._assign_block(_plan("a", "b", "c"), {}, _match_registry("a"))
    assert "concentration" not in clean, "a spread preview prints byte-identically to before D61"


def test_fr337_a_matched_run_prints_the_provenance_lines_the_tally_and_the_gap_block(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """The whole ASSIGN stage under matched mode, end to end through the real narration.

    Three creatives, three different outcomes — an accepted pick, an accepted `medium` (a decent
    fit is a fit, so it reads exactly like `high` and the operator judges the difference), and a
    `low` that keeps its rotation baseline and contributes a want to the gap report. The tally is
    what makes "the mode ran" arithmetic: `matched 2 of 3` cannot be true of a run where the
    matcher never spoke, and `2` is countable off the lines above it.

    Since D61 this fixture also earns FR-355's concentration warning — two of its three creatives
    land on one style — which is why the warning assertion below names that code instead of
    demanding an empty list. The distinction it now pins is the one that matters: a supply FINDING
    is not a DEGRADATION, and neither is a per-entry `low`.
    """
    live = _match_session()
    entries = [entry(0), entry(1), entry(2)]
    _stub_matcher(monkeypatch, {
        entries[0].asset_id: _answer(entries[0], style_key="s2", fit="high", origin="matched",
                                     reason="a single big claim suits the statement style"),
        entries[1].asset_id: _answer(entries[1], style_key="s0", fit="medium", origin="matched",
                                     reason="dense rows, close enough to a ledger deck"),
        entries[2].asset_id: _answer(entries[2], fit="low", origin="rotation",
                                     reason="no enabled style renders a terminal mockup",
                                     wanted_archetype="terminal mockup deck")})

    asyncio.run(runner._assign_visuals(live, entries, {}, brief_only=False))

    lines = printed(capsys)
    for line in lines:
        console_safe(line)
    baseline = [entry(index) for index in range(3)]
    styles.assign_styles(baseline, _match_registry("s0", "s1", "s2"), live.config.branding.brand,
                         branding_enabled=live.config.branding.enabled, run_id=live.run_id,
                         rotation=live.config.styles.rotation)
    assert [item.style_key for item in entries[:2]] == ["s2", "s0"], \
        "the two accepted winners are written in place, over whatever the rotation gave them"
    assert entries[2].style_key == baseline[2].style_key, \
        "the low fit keeps the FR-291 baseline byte for byte — the overlay cannot lose a pick"
    assert any(line.strip().startswith("matched/high ") for line in lines)
    assert any(line.strip().startswith("matched/medium ") for line in lines), \
        "`medium` is ACCEPTED and prints like `high` — the operator reads the difference"
    assert any(line.strip().startswith("rotation/low ") for line in lines)
    assert any("matched 2 of 3 creative(s); 1 kept the rotation baseline" in line
               for line in lines)
    assert any("style gap: 1 archetype(s)" in line for line in lines)
    assert any("terminal mockup deck (1 creative(s))" in line for line in lines)
    assert [code for code, _ in live.log.warnings] == ["style_concentration"], \
        "nothing DEGRADED — a per-entry rejection is a normal answer. The one warning here is " \
        "FR-355's supply alarm, which this fixture earns honestly: two of its three creatives " \
        "land on one style, and D61 says so whichever algorithm put them there"


def test_fr337_a_whole_call_failure_is_ONE_warning_and_never_a_line_per_creative(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """FR-294's `filter_degraded` posture, verbatim: one warning, after the receipts rather than
    instead of them, and the run continues on the FR-291 baseline.

    **This began as a MEASURED FINDING and is now the fix (2026-08-20, W4 barrier).** The runner
    used to compose `f"{cause} — the FR-291 rotation baseline stands, every creative kept a style"`
    and print it through `fit(told, 74)`. The reassurance clause alone is 67 characters, so ANY real
    cause (`style_match_degraded: the match call raised TimeoutError` is 55) pushed the composed
    line past 120 and `fit` ate the reassurance entirely — the console showed the failure and not
    the "nothing was lost" half, which is the half that decides whether an operator aborts a run
    they think has styleless creatives. The conductor split it into two lines: the cause keeps the
    marker and stays last-and-cuttable on its own line, and the fixed sentence gets a line where
    nothing can cut it. Both now measure well inside FR-286 (58 and 66 with their indents).

    So the assertions below pin the SPLIT, not the join: exactly one marker-bearing line however
    large the plan, the cause whole on it, and the reassurance present and untruncated on a line of
    its own. `run.log` still keeps the cause whole through `log.warn`.
    """
    live = _match_session()
    entries = [entry(index) for index in range(4)]
    cause = f"{style_match.DEGRADED_MARKER}: the match call raised TimeoutError"
    _stub_matcher(monkeypatch, {item.asset_id: _answer(item, origin="rotation_fallback",
                                                       reason=cause) for item in entries})

    asyncio.run(runner._assign_visuals(live, entries, {}, brief_only=False))

    lines = printed(capsys)
    for line in lines:
        console_safe(line)
    assert [code for code, _ in live.log.warnings] == ["style_match_degraded"], \
        "exactly one warning for the whole call, whatever the plan size"
    assert live.log.warnings[0][1] == cause, "run.log keeps the cause whole; only the console cuts"
    told = [line for line in lines if style_match.DEGRADED_MARKER in line]
    assert len(told) == 1, told
    assert "the match call raised TimeoutError" in told[0], \
        "WHAT failed is the half that must survive the cut — it is what an operator acts on"
    reassurance = [line for line in lines if "the FR-291 rotation baseline stands" in line]
    assert len(reassurance) == 1, reassurance
    assert reassurance[0].strip() == "the FR-291 rotation baseline stands, every creative kept " \
                                     "a style", "the fixed half must arrive WHOLE — it is the " \
                                                "half that says nothing was lost"
    assert all(len(line) <= 78 for line in (told[0], reassurance[0])), \
        "FR-286: splitting the join must not merely move the overflow"
    assert not any(runner._STYLE_MATCH_DEGRADED in line for line in lines
                   if line.startswith(" " * 13)), \
        "no per-creative provenance line: four entries, one shared cause, one warning"
    # …and the baseline really did stand: the same keys the pure rotation would have assigned.
    expected = [entry(index) for index in range(4)]
    styles.assign_styles(expected, _match_registry("s0", "s1", "s2"), live.config.branding.brand,
                         branding_enabled=live.config.branding.enabled, run_id=live.run_id,
                         rotation=live.config.styles.rotation)
    assert [item.style_key for item in entries] == [item.style_key for item in expected]
    assert all(item.style_origin == "rotation_fallback" for item in entries), \
        "the PICK is the baseline; the ORIGIN records that the matcher never spoke (FR-337)"


def test_fr291_a_rotation_mode_run_prints_exactly_what_it_printed_before_d56(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """The escape hatch, asserted on the console rather than described: `assignment: rotation` makes
    no call, adds no line and raises no warning.

    That is the promise FR-334's determinism note makes — one config line restores pre-D56
    behaviour — and the console is where an operator would first notice it had not been kept. The
    stubbed matcher is left in place ON PURPOSE: if the mode gate ever moved out of the call site,
    this test would see the call and the extra lines it prints.
    """
    live = _match_session(assignment="rotation")
    entries = [entry(0), entry(1)]
    calls = _stub_matcher(monkeypatch, {})

    asyncio.run(runner._assign_visuals(live, entries, {}, brief_only=False))

    lines = printed(capsys)
    assert calls == [], "rotation mode must not reach the matcher at all — it is post-Confirm spend"
    assert live.log.warnings == []
    assert not any("matched" in line for line in lines)
    assert not any("style gap" in line for line in lines)
    assert all(item.style_origin == "rotation" for item in entries), \
        "FR-337 gives the field no empty case — `rotation` is the honest answer here"
    for line in lines:
        console_safe(line)


def test_fr290_the_launch_block_style_count_is_the_ENABLED_aware_usable_pool() -> None:
    """FR-77's opening block, and the one number in it an operator reads to confirm a pool took
    effect.

    This line used to re-derive its answer from `brand_ok` alone, so it ignored FR-314's
    `styles.enabled` and reported every brand-compatible style in the FILE rather than the ones the
    config can actually wear. Against a twelve-key selection over a nineteen-style registry that is
    `18 usable here` where the truth is `12` — precisely the number the operator is checking.

    Pinned as an EQUALITY against `styles.usable_styles`, never as a literal, because a literal
    would pass again the moment someone re-derived the count from a second predicate that happened
    to agree on this fixture. The fixture is chosen so the two predicates DISAGREE: an empty
    `styles.enabled` cannot catch this regression, since brand-only and enabled-aware give the same
    answer there.
    """
    config = Config()
    config.branding.brand, config.branding.enabled = "hypedigitaly", False
    config.styles.enabled = ["s0", "s2"]
    live = session(config=config)
    live.registry = styles.StyleRegistry(
        version=3, content_hash="abcdef012345", origin="prompts/styles.yaml",
        styles=[_match_style("s0"), _match_style("s1"), _match_style("s2"),
                _match_style("lead", brand_affinity=["hypelead"]), _match_style("s4")])

    block = runner._launch_summary(live, [])

    console_safe(block)
    enabled_aware = len(styles.usable_styles(live.registry, config.branding.brand,
                                             config.styles.enabled,
                                             branding_enabled=config.branding.enabled))
    brand_only = sum(1 for style in live.registry.styles
                     if styles.brand_ok(style, config.branding.brand,
                                        branding_enabled=config.branding.enabled))
    assert (enabled_aware, brand_only) == (2, 4), "the fixture must make the two predicates differ"
    line = next(row for row in block.splitlines() if row.startswith("  styles"))
    assert "5 styles ·" in line, "the FILE's own size is still stated — the two numbers differ"
    assert f"· {enabled_aware} usable here" in line
    assert f"{brand_only} usable here" not in line, \
        "the brand-only count is the pre-D56 bug: it promises styles this config cannot wear"
    assert "registry v3 · " in line and "sha abcdef01" in line


# ------------------------------------------- FR-343/FR-345/FR-346 (v2.7.0, D63): output language
#
# Four console surfaces gain a LANGUAGE fact, and every one of them already carried a LENGTH fact
# (D54's compress, D62's auto) in the same slot. The tests below are written as pairs for exactly
# that reason: the language answer must be added WITHOUT rewriting the length answer, and the two
# must stay legible when a deck did both — a translated deck under copy mode auto was translated
# first and then compressed, and no single word carries that.
#
# The fourth surface, `copy_not_translated`, is the only LOUD one: it says a translation was
# wanted and did not happen, which on a `--yes` run is the last chance the operator has to stop
# a batch that is about to render nine decks in the wrong language for their platform.


async def test_fr346_the_copy_stage_line_counts_the_decks_that_changed_language(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The COPY closing line, on the language axis (FR-346).

    Counted off the per-asset PROVENANCE like every other clause on this line, never off
    `run.copy_language_mode`: the two disagree exactly where it matters — a target-mode run whose
    translate call failed shipped the source language, and a line claiming "2 translated" over it
    would deny the loss the `copy_not_translated` block below is shouting about.
    """
    await copy_stage(["verbatim", "verbatim"], monkeypatch, languages=["target", "target"])
    translated = printed(capsys)

    await copy_stage(["verbatim", "verbatim"], monkeypatch, languages=["target", "source"])
    one_of_two = printed(capsys)

    for lines in (translated, one_of_two):
        console_safe("\n".join(lines))
        assert lines[0].startswith("[1/1] COPY"), "the opening line is untouched by the language"
    assert "1 call(s) -> 2 creative(s), 2 translated" in translated[1]
    assert "1 call(s) -> 2 creative(s), 1 translated" in one_of_two[1], "counted, never assumed"
    assert "quoted verbatim" not in translated[1], \
        "a translated deck did not quote its post's words, whatever its copy_mode says"


async def test_fr346_a_deck_that_translated_and_compressed_says_both_inside_53_columns(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one shape that cannot carry the `N call(s) -> N creative(s)` head, measured.

    `_stage` gives this body 53 columns on the full ten-stage list, and the head is 26 of them at
    single-digit counts with each clause costing 14 — 54 characters of text into 53 columns, and
    `fit` would eat the word `translated` whole. So the head goes: the call count is already on
    this stage's OPENING line, two lines above on the same screen, and the translated count is
    printed nowhere else. Run through the REAL ten-stage list rather than a one-stage test list,
    because the one-stage list is much wider and would not catch it.

    The 53 is COPY's own number and is re-derived here rather than restated: `_stage` computes
    `59 - len(tag)` and COPY's tag on that list is `[7/10]`, six characters. DONE's is `[10/10]`,
    seven, so the narrowest body anywhere on a ten-stage run is 52 — but no stage borrows another
    stage's width, and reading 52 off the wrong tag is how this comment got questioned once
    already. The assertion below measures the rendered line instead of trusting either number.
    """
    stages = list(runner._STAGE_ORDER)
    tag = f"[{stages.index('COPY') + 1}/{len(stages)}]"
    assert 59 - len(tag) == 53, "`_stage`'s own arithmetic, re-derived — COPY's tag is [7/10]"
    await copy_stage(["auto", "compress"], monkeypatch, languages=["target", "target"],
                     stages=stages)
    lines = printed(capsys)

    console_safe("\n".join(lines))
    closing = lines[1]
    assert closing.startswith(f"{tag} COPY")
    assert len(closing) == 78, "the header spends its full width — 53 of it on this body"
    assert "2 creative(s), 2 compressed, 2 translated" in closing
    assert "…" not in closing, "the whole sentence fits — nothing was cut to make room"
    assert "call(s) ->" not in closing, "the head is what goes; the opening line already said it"
    assert "auto-compressed" not in closing and "(2 auto)" not in closing, \
        "the auto qualifier goes with the head — the panel map records the per-row split"


async def test_fr346_the_four_length_only_shapes_are_byte_identical_under_source_mode(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression half: with nothing translated, D54's and D62's four sentences are untouched.

    Every one of them is a branch of one if/elif chain that D63 inserted two arms in FRONT of, and
    an arm inserted in front of a chain is exactly how the arm below it stops being reachable.
    """
    shapes = {
        ("verbatim", "verbatim"): "1 call(s) -> 2 creative(s) quoted verbatim",
        ("compress", "compress"): "1 call(s) -> 2 creative(s), 2 compressed",
        ("auto", "auto"): "1 call(s) -> 2 creative(s), 2 auto-compressed",
        ("auto", "compress"): "1 call(s) -> 2 creative(s), 2 compressed (1 auto)",
    }
    for modes, expected in shapes.items():
        await copy_stage(list(modes), monkeypatch)
        lines = printed(capsys)
        console_safe("\n".join(lines))
        assert expected in lines[1], modes
        assert "translated" not in lines[1], "a source-mode run says nothing about language"


async def test_fr343_copy_not_translated_is_loud_on_the_console_like_copy_degraded(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wanted translation that did not happen is news, and news at COPY time is actionable.

    The words on those slides are legitimate — they are the post's own panels, verbatim — but they
    are in the wrong language for the platform they are about to be published on, and on a `--yes`
    run this block is the only place it is said before the money moves. Two lines, the shape
    `filter_degraded` and `style_match_degraded` both settled on: the variable list is the only
    thing `fit` may cut, and the fixed sentence explaining what shipped instead cannot be cut at
    all. The tag word is printed verbatim so console and `meta.yaml` are greppable alike.
    """
    live = await copy_stage(["verbatim"] * 3, monkeypatch, not_translated=[0, 2])
    lines = printed(capsys)

    console_safe("\n".join(lines))
    assert lines[2] == "  copy_not_translated: 2 deck(s) -- 01, 03"
    assert lines[3] == "  they shipped the post's own language, verbatim (FR-343)"
    codes = [code for code, _ in live.log.warnings]
    assert codes == ["copy_not_translated"], "one warning for the run, not one per deck"
    assert "20260812_141207_k3xz_topic_01" in live.log.warnings[0][1], \
        "run.log gets the FULL asset ids — the console shows ordinals for 78 columns"


async def test_fr343_a_clean_run_prints_no_copy_not_translated_block_at_all(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D45: no heading without rows. A run where every wanted translation happened — and every
    `source`-mode run, which wanted none — says nothing, because a "0 decks untranslated" line
    trains an operator to skim exactly the block that will one day say 9."""
    live = await copy_stage(["verbatim", "verbatim"], monkeypatch, languages=["target", "target"])
    lines = printed(capsys)

    assert len(lines) == 2, lines
    assert not any("copy_not_translated" in line for line in lines)
    assert live.log.warnings == []


def test_fr343_copy_not_translated_is_not_in_the_credits_exhausted_starved_set() -> None:
    """It is NOT an LLM loss, and FR-248's latch must not adopt it.

    `_credits_exhausted_line` charges creatives to OpenRouter's 402 — every asset it names gets a
    `skip_reason` stamped and drops off a clean exit 0. An untranslated deck rendered fine and cost
    what it was quoted; the translate call that ACTUALLY failed already carries `copy_degraded`,
    which is in the set. Adding the sibling there would charge a deliberate decision (a deck on a
    degrade path, a language the ladder could not name) to a 402 that never happened.
    """
    source = inspect.getsource(runner._credits_exhausted_line)

    assert "COPY_DEGRADED" in source, "the fixture is not failing — the set is still here"
    assert "COPY_NOT_TRANSLATED" not in source


def test_fr345_the_launch_summary_states_the_language_dial_before_anything_is_spent() -> None:
    """FR-345's launch-summary line: which language this run's decks come out in.

    It names the PLATFORMS' configured language and not the mode word alone, because "target" on
    its own does not tell an operator which tongue their slides will be in — and a run whose
    platforms disagree prints all of them, which is also the shape that makes a misconfigured
    platform visible before the money moves.
    """
    config = Config()
    config.run.formats = {"image": 0, "carousel": 2, "reel": 0}
    live = session(config=config)

    source_mode = runner._launch_summary(live, [])
    config.run.copy_language_mode = "target"
    target_mode = runner._launch_summary(live, [])
    config.run.languages = dict(config.run.languages) | {"instagram": "cs"}
    two_languages = runner._launch_summary(live, [])

    for block in (source_mode, target_mode, two_languages):
        console_safe(block)
    assert "  language    copy: source · posts keep their own language" in source_mode
    assert "  language    copy: target · bound decks translated to en" in target_mode
    assert "bound decks translated to en/cs" in two_languages, \
        "one line per run, every target it has — a first-seen order the operator can recognise"


def test_fr345_a_plan_with_no_carousel_prints_no_language_line() -> None:
    """Translation reaches bound carousel decks and nothing else (FR-343), so on a plan that makes
    no deck the dial changes nothing and printing it would be noise — the same gate the FR-333
    `carousels` line directly above it already has."""
    config = Config()
    config.run.formats = {"image": 3, "carousel": 0, "reel": 0}
    config.run.copy_language_mode = "target"

    block = runner._launch_summary(session(config=config), [])

    console_safe(block)
    assert "  language" not in block and "  carousels" not in block


def test_fr346_the_provenance_row_of_a_translated_deck_names_the_direction() -> None:
    """FR-297c's second line, on the language axis — and it WINS over both mode rows.

    A translated deck quoted nothing (the walk clears every `ref_label`: a label pointing at bytes
    we did not ship would be a false receipt), so the verbatim receipt cannot print. `compressed`
    or `auto` would name the wrong transform — this deck's slides are that post's panels in another
    language, and the deck below did both. The direction is what makes the row checkable against
    the source strip in the gallery, and `panel_map` is where the per-row split is written down.
    """
    item = topic("AI agents do the work", strength=1.0)
    deck = entry(0, fmt="carousel", trend=item, style="anime-noir-statement")
    deck.status = PlanEntryStatus.SUCCESS
    records = {deck.asset_id: record(deck, item, cost=0.180, quoted=item.posts[0], refs={},
                                     copy_mode="auto", copy_language="target",
                                     source_language="de")}
    copy = {deck.asset_id: CopySet(asset_id=deck.asset_id, language="en",
                                   slide_texts=["Ship it, then measure."])}

    block = runner._provenance_block([deck], records, {item.history_key: item}, copy)

    console_safe(block)
    receipt = block.splitlines()[3].strip()
    assert receipt.startswith("translated P1 @creator0 ")
    assert " de->en " in receipt, "source language to the platform's, on the row itself"
    assert item.posts[0].post_id in receipt, "the post is still named — the claim is unchanged"
    assert receipt.endswith("-> panel_map"), "where the operator reads both sides of each row"
    assert '"' not in receipt, "there is no quoted string to show, so none is invented"
    assert "auto" not in receipt and "compressed" not in receipt


def test_fr346_a_translated_deck_with_no_known_source_language_still_prints_a_row() -> None:
    """`??` rather than a blank or a guess. The ladder answers `""` only where Virlo said nothing
    and the vision pass read nothing, which is a shape `_translate_wanted` refuses — but a record
    resurrected from an older run, or a hand-edited `meta.yaml`, can still arrive here, and a row
    that silently dropped the arrow would read as a verbatim receipt with a missing quote."""
    item = topic("AI agents do the work", strength=1.0)
    deck = entry(0, fmt="carousel", trend=item)
    deck.status = PlanEntryStatus.SUCCESS
    records = {deck.asset_id: record(deck, item, quoted=item.posts[0], refs={},
                                     copy_language="target")}

    block = runner._provenance_block([deck], records, {item.history_key: item}, {})

    console_safe(block)
    assert " ??->en " in block.splitlines()[3]


def test_fr346_the_preview_copy_header_and_rows_say_which_deck_changed_language() -> None:
    """`--preview-analysis` is the CHEAPEST review of a translation: it costs the copy calls and
    nothing else, and reading the translated slides there is what tells the operator whether the
    words are worth rendering. So the header counts the decks that changed language and each row
    says `translated … from de` — wider than `_ROW_LABEL`, on the separator guarantee `compressed`
    bought in D54. A `source`-mode run reaches neither and prints its old two lines byte for byte.
    """
    item = topic("AI agents do the work")
    deck = entry(0, fmt="carousel", trend=item)
    image = entry(1, trend=item)
    result = copywrite.CopyResult()
    for plan_entry in (deck, image):
        result.copy[plan_entry.asset_id] = CopySet(
            asset_id=plan_entry.asset_id, language="en", caption="A caption.")
    result.provenance[deck.asset_id] = copywrite.CopyProvenance(
        post_id="p1", copy_language=copywrite.LANGUAGE_TARGET, source_language="de")
    result.provenance[image.asset_id] = copywrite.CopyProvenance(post_id="p1")

    block = previews._copy_block(result, [deck, image])

    console_safe(block)
    assert block.splitlines()[0] == "Copy — 2 creative(s), 1 deck(s) translated"
    assert "  into the platform's language and never shortened (FR-343); the rest" in block
    assert "  quoted verbatim in the post's own language, nothing rendered (FR-140)" in block
    rows = [line for line in block.splitlines() if line.strip().startswith("translated")]
    assert len(rows) == 1 and rows[0].strip() == "translated p1 from de"
    assert "      quoted   p1" in block, "the image beside it still says `quoted`, unchanged"


def test_fr346_a_preview_of_a_translated_and_compressed_deck_states_both_transforms() -> None:
    """Under copy mode auto a translated deck was translated first and then fitted to its style's
    budget, so the header carries a clause for each: one question is what language the words are
    in, the other is how long they are, and answering only the second is how D54's sentence would
    quietly claim a compressed deck is in the post's own language."""
    item = topic("AI agents do the work")
    deck = entry(0, fmt="carousel", trend=item)
    result = copywrite.CopyResult()
    result.copy[deck.asset_id] = CopySet(asset_id=deck.asset_id, language="en")
    result.provenance[deck.asset_id] = copywrite.CopyProvenance(
        post_id="p1", copy_mode=copywrite.MODE_AUTO,
        copy_language=copywrite.LANGUAGE_TARGET, source_language="de")

    block = previews._copy_block(result, [deck])

    console_safe(block)
    assert block.splitlines()[0] == "Copy — 1 creative(s), 1 deck(s) translated"
    assert "  1 deck(s) were then fitted to the style's slide budget (FR-331/FR-353)" in block
    assert [line for line in block.splitlines() if line.strip().startswith("auto")] == [], \
        "the row says `translated`: the bigger claim about the same bytes wins"
def test_fr345_the_bind_skip_says_on_the_console_which_posts_the_language_screen_refused(
) -> None:
    """FR-345's off-language receipt, and the reason it is a LINE rather than a logger call.

    `plan.off_language_post` drops a candidate source post whose known language this run does not
    write. That is right under `source` mode — the panels ship byte for byte, so a German post
    inside an English topic would put German pixels under an English caption — but a post that
    silently leaves the supply pool is the invisible defect FR-345 was written for. Run `4a0q`
    bound one and nobody could see why.

    The fact used to be a `logger.warning` inside `plan`, which reached NOBODY:
    `__main__._configure_logging` installs a NullHandler and no console handler at all, so the
    line was written and thrown away on every run. It is data on `plan.Assignment` now, and this
    stage is what says it. The mode key is named because it is the cure: flipping
    `run.copy_language_mode` to `target` binds those same posts and translates their decks.
    """
    empty = runner._off_language_line(plan.Assignment())
    one = runner._off_language_line(plan.Assignment(off_language_posts=[("post-de", "de")]))
    two = runner._off_language_line(plan.Assignment(
        off_language_posts=[("post-de", "de"), ("post-fr", "fr"), ("post-de2", "de")]))

    assert empty == "", "a run that refused nothing prints nothing — no `0 post(s)` furniture"
    console_safe(one)
    console_safe(two)
    assert one == "  off-language  1 post(s) skipped (de) - copy_language_mode: source"
    assert two == "  off-language  3 post(s) skipped (de, fr) - copy_language_mode: source", \
        "posts are counted, languages are listed distinct and sorted"


def test_fr286_the_off_language_line_cuts_the_codes_and_never_the_config_key() -> None:
    """The one unbounded token on the line is the language list, so it is the only thing `fit`
    may eat. Whatever it cuts, the count at the front and `copy_language_mode: source` at the
    back survive — the first says how much supply was lost and the second says how to get it
    back, and a line that lost either would be worse than no line."""
    crowded = runner._off_language_line(plan.Assignment(off_language_posts=[
        (f"post-{code}", code) for code in
        ("de", "fr", "es", "it", "pt", "nl", "pl", "sv", "da", "fi", "cs", "hu")]))

    console_safe(crowded)
    assert crowded.startswith("  off-language  12 post(s) skipped (")
    assert crowded.endswith(" - copy_language_mode: source")


def test_fr345_the_select_stage_is_what_writes_the_warning_and_the_line() -> None:
    """The wire-in, pinned where the two halves meet. `plan` returns the pairs and prints nothing
    (NFR-2); SELECT is the stage that owns what the operator reads, so it writes both the
    `plan_off_language_posts` warning into `run.log` and the console line above FR-307's supply
    arithmetic — when both fire, the language screen is the CAUSE of the shortage the famine line
    is about to report, and a cause reads better above its effect."""
    source = inspect.getsource(runner._select)

    assert "off_language_posts" in source and "plan_off_language_posts" in source
    assert source.index("_off_language_line") < source.index("fresh_post_line"), \
        "the cause is said before the effect it produced"
