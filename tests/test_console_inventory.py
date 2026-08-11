"""A24 — the console tells the operator WHICH posts these are and HOW our AI analysed them.

Two blocks, both printed after Select and in both preview modes, both built on `_funnel_row` and
therefore both bound by FR-286's 78 columns:

- `runner._sources_block()` — the post inventory: what kind of post won, how much material came
  with it, Virlo's own labels for it, the source's own hooks, the permalink, and whether a motion
  reference qualified. None of it was visible before A24 without reading `events.jsonl`.
- `runner._brief_block()` — the style brief in four rows (`pattern`, `angle`, `palette`,
  `forbids`). Before A24 a `StyleBrief` existed ONLY inside `events.jsonl` under `verbose_only`,
  so an operator judging a finished creative could not see the instruction it was rendered
  against without switching verbose logging on first.

Three properties are load-bearing and each is pinned below:

1. **Width.** Every line ≤78 EXCEPT a bare URL, which gets its own line under FR-286's carve-out
   (a) — a permalink has no word boundary to wrap on and the operator copies it.
2. **The Increment-B volume gate.** A paid run prints full detail for the strongest three trends
   and then `+ N more trend(s), see events.jsonl`; the two preview modes pass `limit=None` and
   print everything, because showing the whole supply before you commit to it is what FR-139/140
   exist for.
3. **`style_brief_summary` survives to disk.** The one-line brief reaches `meta.yaml` through
   `AssetRecord` and the gallery card through the meta — a console line nobody can re-read after
   the run would be half an answer.

⚠️ These blocks DO print the competitor's hooks, and that is not what A20 forbids. A20 stops the
ENGINE reproducing those strings into a creative; showing them to the operator is the entire point
of "which posts these are". They are quoted so it is unambiguous whose words they are.

Offline: pure functions of `TrendItem`/`StyleBrief` plus `tmp_path` for the meta and gallery legs.
"""

from __future__ import annotations

from pathlib import Path

from hypesocials import runner
from hypesocials.models import AssetRecord, LayoutZone, StyleBrief, TrendItem
from hypesocials.outputs import AssetFolder, read_meta, write_gallery
from hypesocials.prompts_engine import style_brief_line

WIDTH = runner._FUNNEL_WIDTH
SAFE_GLYPHS = frozenset("·—…←")

#: The LONGEST permalink in the captured corpus (74 characters, `tests/fixtures/virlo/`). Chosen
#: deliberately: indented under its row it runs to 84 columns, so it really does break FR-286 and
#: the carve-out is being exercised rather than merely declared.
PERMALINK = "https://www.tiktok.com/@ai_prompt_and_technology/photo/7580294327201549590"


def trend(name: str = "AI Trends Tracker", *, strength: float = 0.91, groups: int = 3,
          **overrides: object) -> TrendItem:
    """A trend carrying every field the two blocks read, in the shapes the corpus produces."""
    item = TrendItem(
        history_key=name.lower().replace(" ", "-"), monitor_id="9c96fddf", name=name,
        strength=strength, is_slideshow=True,
        why_it_works="a withheld subject in the first panel, then a list nobody expected",
        tactics=["numbered list", "screenshot"],
        hook_texts=["Remember.. >>"], text_overlay_contents=["ChatGPT isn't the only one >>>"],
        panel_texts=["Remember.. >>", "ChatGPT isn't the only one >>>", "the landscape"],
        hook_types=["story_tease"], visual_hook_types=["text_hook"],
        emotional_tones=["educational", "positive"],
        reference_groups=[[f"https://cdn.virlo.test/{name}-g{g}-p{p}.jpg" for p in range(3)]
                          for g in range(groups)],
        virlo_url=PERMALINK, winning_video_url="https://www.youtube.com/shorts/wqhJedUdY8Y",
        total_views=5_487_494, median_views=279_757,
        chosen_post_ids=("7310888312766549254",))
    for key, value in overrides.items():
        setattr(item, key, value)
    return item


def brief(trend_key: str = "ai-trends-tracker", *, group: int = 0, **overrides: object
          ) -> StyleBrief:
    item = StyleBrief(
        trend_key=trend_key, reference_group_index=group,
        layout_zones=[LayoutZone("upper third", "headline", "all caps")],
        exclusions=["platform UI", "@aifuture44", "follower counter", "TikTok wordmark"],
        render_prompt="Near-black ground, one electric accent.",
        palette=["#F5F5F4", "#C1391F", "#1A1A1A", "#8FA37E", "#FFFFFF"],
        typography="extra-bold condensed sans",
        hook_pattern="Curiosity-and-reveal claim, second person, withheld subject",
        content_angle="Automate the boring middle, not the flashy demo")
    for key, value in overrides.items():
        setattr(item, key, value)
    return item


def fits(block: str) -> None:
    """FR-286 with carve-out (a): every line ≤78 unless it is a bare URL on its own line."""
    for line in block.splitlines():
        if line.strip().startswith("http"):
            assert line.strip() == line.strip().split()[0], \
                f"a URL must sit ALONE on its line so it stays copyable: {line!r}"
            continue
        assert len(line) <= WIDTH, f"{len(line)} chars (FR-286 allows {WIDTH}): {line!r}"
        assert "→" not in line, f"the unsafe arrow glyph reached the console: {line!r}"
        stray = {char for char in line if ord(char) > 127} - SAFE_GLYPHS
        assert not stray, f"glyph(s) outside util.fit's proven-safe set {sorted(stray)}: {line!r}"


# --------------------------------------------------------------------------- Sources block


def test_the_sources_block_answers_which_posts_these_are() -> None:
    block = runner._sources_block([trend()])

    fits(block)
    assert block.splitlines()[0] == "Sources — AI Trends Tracker"
    assert "slideshow" in block and "3 set(s), 9 image(s)" in block and "strength 0.910" in block
    assert PERMALINK in block
    assert "5,487,494 views total" in block and "median 279,757" in block
    assert "1 post(s) chosen" in block
    assert '"Remember.. >>"' in block, "the source's own hook, quoted as someone else's words"
    assert "story_tease" in block and "text_hook" in block
    assert "educational" in block
    # HOST ONLY, and `www.` stripped: a motion-reference url carries a token-length tail that
    # would blow FR-286's width for no operator benefit (`_motion_clause`'s own reasoning).
    assert "youtube.com (reel only)" in block
    assert "wqhJedUdY8Y" not in block


def test_every_sources_line_fits_except_the_permalink_that_owns_its_line() -> None:
    """The carve-out, stated as a measurement: the URL line is over 78 and everything else is not.
    A block that squeaked under 78 only because the fixture's URL was short would prove nothing."""
    block = runner._sources_block([trend()])
    url_lines = [line for line in block.splitlines() if line.strip().startswith("http")]

    fits(block)
    assert len(url_lines) == 1
    assert len(url_lines[0]) > WIDTH, "pick a longer fixture permalink — the carve-out is untested"
    assert url_lines[0].startswith(runner._DETAIL_INDENT), "the url aligns under its row's text"


def test_an_unbounded_trend_name_is_cut_rather_than_allowed_to_overflow() -> None:
    """The one place a trend name DOES reach the console (the funnel block deliberately has none),
    so it is the one place `fit()` has to hold."""
    block = runner._sources_block([trend("A monitor theme name " * 12)])

    fits(block)
    assert block.splitlines()[0].startswith("Sources — ")
    assert block.splitlines()[0].endswith("…")


def test_a_text_only_trend_prints_fewer_rows_rather_than_empty_ones() -> None:
    """Rows are emitted only when their fields carry something: a monitor whose rows arrived with
    no `intelligence` block must not print `hooks` with nothing after the label."""
    bare = trend("Bare theme", groups=0, hook_texts=[], text_overlay_contents=[], panel_texts=[],
                 hook_types=[], visual_hook_types=[], emotional_tones=[], tactics=[],
                 virlo_url=None, winning_video_url=None, chosen_post_ids=())

    block = runner._sources_block([bare])

    fits(block)
    assert "text_only — this trend arrived with no pictures" in block
    assert "hooks" not in block and "motion" not in block
    assert "http" not in block
    assert all(line.strip() for line in block.splitlines()), "no row printed with a blank tail"


def test_a_paid_run_shows_the_strongest_three_and_counts_the_rest() -> None:
    """A24's Increment-B volume guard. At 9–22 trends this section would otherwise print 9–22
    blocks and bury the funnel rollup an operator reads first."""
    trends = [trend(f"Theme {index}", strength=0.9 - index / 100) for index in range(9)]

    block = runner._sources_block(trends)

    fits(block)
    assert runner._DETAIL_TRENDS == 3
    assert block.count("Sources — ") == 3
    assert "Sources — Theme 0" in block and "Sources — Theme 2" in block
    assert "Sources — Theme 3" not in block
    assert "+ 6 more trend(s), see events.jsonl" in block


def test_a_preview_prints_every_trend_because_that_is_what_a_preview_is_for() -> None:
    """FR-139/140: both preview modes pass `limit=None`. Showing the operator the whole supply
    before they commit to it is the entire purpose of the mode."""
    trends = [trend(f"Theme {index}", strength=0.9 - index / 100) for index in range(9)]

    block = runner._sources_block(trends, limit=None)

    fits(block)
    assert block.count("Sources — ") == 9
    assert "more trend(s)" not in block


def test_the_blocks_are_ordered_strongest_first_whatever_order_they_arrive_in() -> None:
    """`_assigned_trends` returns plan order; the display re-ranks, because "the strongest three"
    is only a useful gate if the three really are the strongest."""
    trends = [trend("Weakest", strength=0.10), trend("Strongest", strength=0.99),
              trend("Middle", strength=0.50)]

    block = runner._sources_block(trends, limit=None)
    order = [line.removeprefix("Sources — ") for line in block.splitlines()
             if line.startswith("Sources — ")]

    assert order == ["Strongest", "Middle", "Weakest"]


def test_no_trends_at_all_prints_nothing_rather_than_an_empty_header() -> None:
    """The caller guards with `if inventory := _sources_block(...)`, so "" is the contract."""
    assert runner._sources_block([]) == ""
    assert runner._brief_block({}, {}) == ""


# --------------------------------------------------------------------------- Brief block


def test_the_brief_block_answers_how_our_ai_analysed_them() -> None:
    item = trend()
    block = runner._brief_block({"ai-trends-tracker#0": brief()}, {item.history_key: item})

    fits(block)
    assert block.splitlines()[0] == "Brief — AI Trends Tracker"
    assert "Curiosity-and-reveal claim" in block
    assert "Automate the boring middle" in block
    assert "#F5F5F4" in block and "#C1391F" in block
    assert "#FFFFFF" not in block, "the palette row shows the first four, not the whole list"
    assert "4 observed string(s) blocked from the frame" in block


def test_a_trend_with_several_briefs_names_the_reference_group_behind_each() -> None:
    """FR-91's rotation makes one trend produce several briefs, and an operator comparing them has
    to see which pictures each one looked at."""
    item = trend()
    briefs = {f"ai-trends-tracker#{index}": brief(group=index, content_angle=f"angle {index}")
              for index in range(2)}

    block = runner._brief_block(briefs, {item.history_key: item}, limit=None)

    fits(block)
    assert "Brief — AI Trends Tracker [reference group 1]" in block
    assert "Brief — AI Trends Tracker [reference group 2]" in block
    assert "angle 0" in block and "angle 1" in block


def test_the_brief_block_takes_the_same_volume_gate_as_the_sources_block() -> None:
    items = {f"t{index}": trend(f"Theme {index}", strength=0.9 - index / 100)
             for index in range(6)}
    briefs = {f"t{index}#0": brief(trend_key=f"t{index}") for index in range(6)}

    paid = runner._brief_block(briefs, items)
    preview = runner._brief_block(briefs, items, limit=None)

    fits(paid)
    fits(preview)
    assert paid.count("Brief — ") == 3 and "+ 3 more brief(s), see events.jsonl" in paid
    assert preview.count("Brief — ") == 6 and "more brief(s)" not in preview


def test_a_brief_with_no_exclusions_prints_no_forbids_row() -> None:
    item = trend()
    block = runner._brief_block({"ai-trends-tracker#0": brief(exclusions=[])},
                                {item.history_key: item})

    fits(block)
    assert "forbids" not in block
    assert "pattern" in block and "angle" in block and "palette" in block


# ----------------------------------------------- the one-line brief reaches disk and the gallery


def test_the_brief_summary_is_one_line_of_pattern_angle_palette() -> None:
    """`style_brief_line` is a pure function of the brief, like `style_dna`, so the console line,
    the meta.yaml field and the gallery card cannot drift from each other."""
    line = style_brief_line(brief())

    assert line.count("\n") == 0
    assert line.startswith("Curiosity-and-reveal claim, second person, withheld subject · ")
    assert "Automate the boring middle, not the flashy demo" in line
    assert "#F5F5F4, #C1391F" in line
    assert style_brief_line(None) == "", "direct mode and FR-12's degrade have no brief to show"


def test_the_brief_summary_reaches_meta_yaml_and_the_gallery_card(tmp_path: Path) -> None:
    """A24's second half. Until it landed, `StyleBrief` lived only in `events.jsonl` under
    `verbose_only`, so the instruction a creative was rendered against was unreadable afterwards
    unless verbose logging happened to be on at the time."""
    summary = style_brief_line(brief())
    record = AssetRecord(asset_id="a1", source="ai-trends-tracker", source_name="AI Trends Tracker",
                         platform="linkedin", creative_format="image",
                         hook_pattern_used="Withheld-subject claim, second person, one clause",
                         style_brief_summary=summary)
    folder = AssetFolder(tmp_path, record)
    folder.write_caption("A caption in our own words.", ["#ai"])

    assert read_meta(folder.path)["style_brief_summary"] == summary

    page = write_gallery(tmp_path, title="Run")
    assert page is not None
    html = page.read_text(encoding="utf-8")
    assert "Brief asked for:" in html
    assert "Automate the boring middle, not the flashy demo" in html
    assert "Curiosity-and-reveal claim" in html


def test_a_direct_mode_creative_writes_no_brief_line_and_the_card_omits_the_row(
    tmp_path: Path,
) -> None:
    """Absence is the answer — the `analysis_missing` badge already says there was no brief, and a
    card row reading "Brief asked for:" with nothing after it says the opposite of that."""
    record = AssetRecord(asset_id="a1", source="ai-trends-tracker", source_name="AI Trends Tracker",
                         platform="linkedin", creative_format="image", variant="direct")
    folder = AssetFolder(tmp_path, record)

    assert read_meta(folder.path)["style_brief_summary"] == ""

    page = write_gallery(tmp_path, title="Run")
    assert page is not None and "Brief asked for:" not in page.read_text(encoding="utf-8")
