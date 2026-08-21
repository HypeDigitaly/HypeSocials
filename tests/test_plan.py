"""Tests for `hypesocials.plan` — the Select + Expand stage (FR-1–8, FR-90, FR-143/144).

Rewritten for the topic-first pivot (v2.0.0, T3.5). Three premises of the old suite are gone and
each one took its tests with it:

1. **A/B mode is withdrawn** (operator decision #2). One requested creative is ONE `PlanEntry` and
   one render, so the `both`-mode expansion tests, the `pair_id` assertions and the `_<variant>_`
   segment of every asset id have no subject left.
2. **Virlo is a text feed** (D41). A topic never "arrives with pictures", so FR-90's last-resort
   `text_only` tier is withdrawn, `TrendVerdict.text_only` is deleted, and `_pick` has three
   sort keys instead of four.
3. **FR-7 is enforced HERE, at POST granularity** (amended v2.0.0). The adapter stopped dropping
   used posts while choosing a reference set — there is no reference set — so `select()` owns the
   exclusion decision and reads `TrendItem.posts` to make it.

Amended for the slideshow-fidelity pass (v2.1.0, D46 T2.2). A fourth premise is now pinned:

4. **A carousel binds ONE specific fresh slideshow POST at ASSIGN** (FR-304/FR-307). Affinity is a
   hard constraint for that format — a video-majority topic has no panels to map a deck onto — the
   bound post's panel count fixes `slide_count` before the Confirm gate (§0.4′), and a carousel
   with no unused source deck left skips with `no_fresh_post_available` rather than quoting a post
   whose text already shipped.

Pure logic, so every test is sync: no event loop, no I/O, no fixtures beyond small builders.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from hypesocials.config import Config, PlatformConfig, RunConfig
from hypesocials.models import Brief, PlanEntry, PlanEntryStatus, SourcePost, TrendItem
from hypesocials.plan import (
    MIN_DECK_SLIDES, NO_FRESH_POST_AVAILABLE, BriefRequest, assign, build_plan, deck_length,
    fresh_source_post, off_language_post, select, source_panel_count, usable_panel_slots)

# --------------------------------------------------------------------------- builders


def _config(**run_kwargs) -> Config:
    """A Config with the PRD's default three platforms and no YAML involved."""
    cfg = Config(run=RunConfig(**run_kwargs))
    cfg.models.price_per_unit.reel_second["720p"] = 0.10  # reels priced ONLY where a test needs it
    return cfg


def _worked_example_config() -> Config:
    """10-pipeline §1's worked example verbatim: images everywhere, carousels on Li+Ig, reels Tk."""
    cfg = _config(formats={"image": 3, "carousel": 2, "reel": 1})
    cfg.platforms = {
        "linkedin": PlatformConfig(formats=["image", "carousel"], carousel_slides=5),
        "instagram": PlatformConfig(formats=["image", "carousel"], carousel_slides=5),
        "tiktok": PlatformConfig(formats=["image", "reel"], carousel_slides=5),
    }
    return cfg


def _hk(topic: str, monitor: str = "m1") -> str:
    """The post-pivot `history_key`: `"<monitor_id>::<topic_key>"` (§1.6/D44)."""
    return f"{monitor}::{topic}"


def _post(post_id: str, *, caption: str = "the hook that stole the week",
          views: int = 1000, panels: int = 0, texts: tuple[str, ...] | None = None,
          images: bool = True) -> SourcePost:
    """One winning post inside a topic — the unit FR-7 excludes on and §1.7 quotes from.

    `panels > 0` makes it a SLIDESHOW row the way `sources/virlo.py` returns one (FR-293): a
    declared `panel_count`, `panel_texts` index-aligned to it (padded, never compacted) and one
    position-sorted image URL per panel. `texts` overrides the words slot by slot, `images=False`
    is the row that declares panels but shipped no pictures — the two levers §0.14a's usability
    predicate turns on.
    """
    words = list(texts) if texts is not None else [f"panel {i} of {post_id}"
                                                   for i in range(1, panels + 1)]
    return SourcePost(post_id=post_id, url=f"https://www.tiktok.com/@creator/video/{post_id}",
                      author="creator", caption=caption, views=views,
                      is_slideshow=panels > 0, panel_count=panels, panel_texts=words,
                      image_urls=[f"https://cdn.virlo.test/{post_id}/{i}.jpg"
                                  for i in range(1, panels + 1)] if images else [])


def _deck(post_id: str, *, panels: int = 4, views: int = 1000,
          texts: tuple[str, ...] | None = None, images: bool = True) -> SourcePost:
    """A slideshow source post — the only shape FR-304 lets a carousel bind."""
    return _post(post_id, views=views, panels=panels, texts=texts, images=images)


def _trend(topic: str, *, strength: float = 0.5, slideshow: bool = False,
           name: str | None = None, why: str = "strong pattern interrupt",
           posts: tuple[str, ...] = (), monitor: str = "m1",
           source_posts: tuple[SourcePost, ...] = ()) -> TrendItem:
    """One post-pivot TOPIC item. `posts` are its own view-ranked `SourcePost` ids (FR-293).

    `source_posts` passes fully built posts instead, for the FR-304 tests that care about panels,
    views and freshness rather than about ids alone.
    """
    return TrendItem(
        history_key=_hk(topic, monitor),
        monitor_id=monitor,
        topic_key=topic,
        name=name if name is not None else topic.replace("-", " ").title(),
        strength=strength,
        is_slideshow=slideshow,
        why_it_works=why,
        posts=list(source_posts) if source_posts else [_post(post_id) for post_id in posts])


def _deck_topic(topic: str, *decks: SourcePost, strength: float = 0.5,
                monitor: str = "m1") -> TrendItem:
    """A slideshow-majority topic carrying real slideshow posts — a bindable carousel source."""
    return _trend(topic, strength=strength, slideshow=True, monitor=monitor,
                  source_posts=decks or (_deck("post-a"),))


def _brief(name: str, influence: str = "override", formats=("image",)) -> Brief:
    return Brief(name=name, description="d", influence=influence, formats=list(formats))


def _days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def _seen(days: int, *post_ids: str) -> dict[str, object]:
    """One `trend_history.json` entry as `state.record_use` writes it post-FR-298: the topic's own
    `last_used` stamp plus a `posts` map whose values are `{date, url}` mappings."""
    return {"last_used": _days_ago(days), "run_ids": ["r1"],
            "posts": {pid: {"date": _days_ago(days), "url": ""} for pid in post_ids}}


def _shape(entries: list[PlanEntry]) -> list[tuple[str, str, str]]:
    return [(e.platform, e.creative_format, e.aspect_ratio) for e in entries]


# --------------------------------------------------------------------------- FR-1 worked example


def test_fr1_worked_example_expands_to_six_creatives() -> None:
    """"The plan resolves to six creatives" — exact counts, order, ratios and ids (FR-1/2/21).

    Post-pivot the same request is six creatives and SIX renders: FR-3's analyzed/direct
    duplication is withdrawn (v2.0.0), so nothing here doubles and no id carries a variant tag.
    """
    plan = build_plan(_worked_example_config())

    assert _shape(plan.entries) == [
        ("linkedin", "image", "16:9"),
        ("instagram", "image", "4:5"),
        ("tiktok", "image", "9:16"),
        ("linkedin", "carousel", "1:1"),
        ("instagram", "carousel", "1:1"),
        ("tiktok", "reel", "9:16"),  # the ONLY platform whose allowlist enables reels
    ]
    assert [e.order for e in plan.entries] == [0, 1, 2, 3, 4, 5]
    assert [e.asset_id for e in plan.entries] == [
        "Li_img_unassigned_01",
        "Ig_img_unassigned_02",
        "Tk_img_unassigned_03",
        "Li_car_unassigned_04",
        "Ig_car_unassigned_05",
        "Tk_reel_unassigned_06",
    ]
    assert [e.slide_count for e in plan.entries] == [None, None, None, 5, 5, None]
    # "That is 13 slide/image renders" — 3 singles + 2 decks x 5 slides.
    assert sum(e.slide_count or 1 for e in plan.entries if e.creative_format != "reel") == 13
    assert len({e.atomic_group for e in plan.entries}) == 6  # nothing shares a trim unit
    assert plan.notes == []


def test_fr1_one_requested_creative_is_exactly_one_entry() -> None:
    """v2.0.0, operator decision #2: A/B mode is withdrawn, so expansion never doubles.

    This is the arithmetic the withdrawn `both` mode used to break: 4 images + 2 carousels is six
    entries and six atomic groups, never twelve, and no entry is cross-linked to a sibling.
    """
    plan = build_plan(_config(formats={"image": 4, "carousel": 2, "reel": 0}))

    assert len(plan.entries) == sum(_config().run.formats.values()) == 6
    assert len({e.atomic_group for e in plan.entries}) == 6
    assert all(len(e.asset_id.split("_")) == 4 for e in plan.entries), \
        "the asset id is <Pl>_<fmt>_<slug>_<NN> — the A/B tag segment is gone (FR-71)"


def test_fr2_counts_distribute_round_robin_with_remainder_to_earlier_platforms() -> None:
    """4 images over 3 platforms is 4 creatives, not 12 — remainder to the earlier platform."""
    plan = build_plan(_config(formats={"image": 4, "carousel": 0, "reel": 0}))

    assert [e.platform for e in plan.entries] == ["linkedin", "instagram", "tiktok", "linkedin"]


def test_fr132_format_with_no_enabled_platform_is_dropped_with_a_note() -> None:
    cfg = _config(formats={"image": 0, "carousel": 0, "reel": 2}, platforms=["linkedin"])
    plan = build_plan(cfg)

    assert plan.entries == []
    assert "no enabled platform allows reel" in plan.notes[0]


def test_fr131_unpriced_reels_are_not_planned_at_all() -> None:
    cfg = Config(run=RunConfig(formats={"image": 1, "carousel": 0, "reel": 2}))  # reel_second unset
    plan = build_plan(cfg)

    assert [e.creative_format for e in plan.entries] == ["image"]
    assert cfg.reel_price_key in plan.notes[0]


# --------------------------------------------------------------------------- FR-106 trim order


def _trim_from_end(entries: list[PlanEntry], keep: int) -> list[PlanEntry]:
    """FR-106's one rule: remove from the END in reverse plan order, whole `atomic_group`s only."""
    survivors = list(entries)
    while len(survivors) > keep and survivors:
        doomed = survivors[-1].atomic_group
        survivors = [e for e in survivors if e.atomic_group != doomed]
    return survivors


def test_fr106_compound_plan_emits_briefs_first_and_groups_contiguously() -> None:
    """Briefs + images + a carousel: the emitted ORDER is what makes trimming safe.

    The pair that used to make one group hold two entries is gone (v2.0.0), so every group is a
    single creative today — the group seam survives because a carousel's slides must still never
    be split from each other (D31) and because `budget.trim` cuts on the same unit.
    """
    cfg = _config(formats={"image": 2, "carousel": 1, "reel": 0},
                  platforms=["linkedin", "instagram"])
    plan = build_plan(cfg, briefs=[BriefRequest(_brief("ai-audit-cta"), 2)])
    entries = plan.entries

    assert [e.brief_name for e in entries[:2]] == ["ai-audit-cta", "ai-audit-cta"]  # briefs FIRST
    assert all(e.brief_name is None for e in entries[2:])
    # 2 brief + 2 image + 1 carousel = 5 entries in 5 trim units.
    assert len(entries) == 5
    groups = [e.atomic_group for e in entries]
    assert len(set(groups)) == 5
    assert groups == sorted(groups, key=groups.index)  # every group is one contiguous run
    carousel = [e for e in entries if e.creative_format == "carousel"]
    assert len(carousel) == 1 and carousel[0].slide_count == 5

    # Trimming from the end never splits a unit, and the campaign brief survives longest.
    for keep in range(5, -1, -1):
        survivors = _trim_from_end(entries, keep)
        assert [e.order for e in survivors] == sorted(e.order for e in survivors)
        if survivors:
            assert survivors[0].brief_name == "ai-audit-cta"
    assert [e.brief_name for e in _trim_from_end(entries, 2)] == ["ai-audit-cta"] * 2


# --------------------------------------------------------------------------- FR-6/7 verdicts


def test_fr7_verdicts_cover_eligible_excluded_and_unusable() -> None:
    """FR-7/FR-139's three verdicts, and the three shapes that produce them post-pivot."""
    trends = [
        _trend("fresh", strength=0.9, posts=("post-a",)),
        _trend("stale", strength=0.8),  # post-less: the topic-level stamp is the only signal
        _trend("empty", strength=0.7, why=""),
    ]
    history = {_hk("stale"): _seen(2)}
    selection = select(trends, _config(trend_history_days=7), history)

    assert [v.verdict for v in selection.verdicts] == ["eligible", "excluded", "unusable"]
    assert [t.topic_key for t in selection.eligible] == ["fresh"]

    excluded = selection.excluded[0]
    assert excluded.last_used == _days_ago(2)
    assert excluded.label == (f"excluded (history, last used {_days_ago(2)}, "
                              "used within the last 7 day(s))")

    unusable = selection.unusable[0]
    assert "text substance" in unusable.reason
    assert unusable.label == f"unusable ({unusable.reason})"


def test_fr7_zero_days_disables_the_history_window() -> None:
    history = {_hk("stale"): _seen(0, "post-a")}
    selection = select([_trend("stale", posts=("post-a",))],
                       _config(trend_history_days=0), history)

    assert [v.verdict for v in selection.verdicts] == ["eligible"]


def test_fr7_a_topic_with_one_unused_post_left_is_still_eligible() -> None:
    """FR-7 at POST granularity (amended v2.0.0). A topic is a standing subject that can be worked
    again the moment it surfaces a post whose text has not shipped yet — so one fresh post keeps
    the whole topic in the run, even though the topic itself was used yesterday.

    Under the pre-pivot monitor identity this topic was locked out for the whole window; with nine
    topics per monitor that arithmetic would have emptied a config in a couple of runs.
    """
    history = {_hk("m1-topic"): _seen(1, "post-used")}
    trend = _trend("m1-topic", posts=("post-used", "post-fresh"))

    selection = select([trend], _config(trend_history_days=7), history)

    assert [v.verdict for v in selection.verdicts] == ["eligible"]
    assert [t.history_key for t in selection.eligible] == [_hk("m1-topic")]


def test_fr7_a_topic_whose_every_post_is_burnt_is_excluded_and_says_which_cause() -> None:
    """The other half of the post-granular rule: with no unused post left there is nothing new to
    quote, so the topic drops — and the reason says so, because widening `--history-days` cannot
    help here and the operator must be able to tell that from the post-less exclusion below."""
    history = {_hk("used-up"): _seen(1, "post-a", "post-b")}

    verdict = select([_trend("used-up", posts=("post-a", "post-b"))],
                     _config(trend_history_days=7), history).excluded[0]

    assert verdict.reason == "all 2 source post(s) used within the last 7 day(s)"
    assert verdict.label == (f"excluded (history, last used {_days_ago(1)}, "
                             "all 2 source post(s) used within the last 7 day(s))")
    assert "FR-" not in verdict.label  # §2.4: citations belong in events.jsonl, not on the console


def test_fr7_a_post_burnt_under_another_topic_is_burnt_here_too() -> None:
    """`select()` unions every history key's posts into ONE set, because post ids are globally
    unique: a post whose text already shipped is burnt for every topic that carries it, whichever
    monitor or theme surfaced it this time."""
    history = {_hk("other-topic", "m9"): _seen(1, "shared-post")}
    trend = _trend("this-topic", posts=("shared-post",))

    selection = select([trend], _config(trend_history_days=7), history)

    assert [v.verdict for v in selection.verdicts] == ["excluded"]
    assert selection.excluded[0].reason == "all 1 source post(s) used within the last 7 day(s)"
    assert selection.excluded[0].last_used is None  # this topic has no entry of its own


def test_fr7_a_post_less_topic_falls_back_to_the_topic_level_stamp() -> None:
    """The only case topic identity still decides. A topic that arrived with no posts carries no
    post identity at all, so its own `last_used` is the only recency signal there is — and this
    exclusion IS the one `--history-days` widens, which is why its reason is worded differently."""
    history = {_hk("wordy"): _seen(2), _hk("older"): _seen(30)}
    trends = [_trend("wordy", strength=0.9), _trend("older", strength=0.8)]

    selection = select(trends, _config(trend_history_days=7), history)

    assert [v.verdict for v in selection.verdicts] == ["excluded", "eligible"]
    assert selection.excluded[0].reason == "used within the last 7 day(s)"
    assert selection.excluded[0].trend.posts == []


def test_fr7_zero_days_disables_the_window_for_a_topic_with_no_post_identity() -> None:
    """`0` still disables the window entirely — the post-level predicate never re-enables it."""
    history = {_hk("used-up"): _seen(0)}

    selection = select([_trend("used-up")], _config(trend_history_days=0), history)

    assert [v.verdict for v in selection.verdicts] == ["eligible"]


def test_fr7_select_mutates_no_source_owned_post_data() -> None:
    """`select()`'s purity contract (plan.py:10-13), re-based on `posts`.

    The view rank of `TrendItem.posts` IS the sort proof the console prints (FR-297a/b) and the
    `P<n>` labels the copy call quotes by (§1.7), so a Select that quietly re-ordered posts to put
    the fresh ones first would falsify both surfaces while looking like a helpful optimisation.
    """
    trend = _trend("m1-topic", posts=("post-a", "post-b", "post-c"))
    order_before = [post.post_id for post in trend.posts]
    history = {_hk("m1-topic"): _seen(1, "post-a")}

    select([trend], _config(trend_history_days=7), history)

    assert [post.post_id for post in trend.posts] == order_before
    assert len(trend.posts) == 3  # nothing was filtered out of the topic either


def test_fr7_a_topic_older_than_the_window_is_eligible_again() -> None:
    history = {_hk("old"): _seen(30, "post-a")}
    selection = select([_trend("old", posts=("post-a",))], _config(trend_history_days=7), history)

    assert selection.verdicts[0].verdict == "eligible"


def test_fr6_unusable_reasons_name_what_was_missing() -> None:
    nameless = _trend("x", name="  ")
    substance_free = TrendItem(history_key=_hk("y"), monitor_id="m1", topic_key="y",
                               name="Has A Name")
    selection = select([nameless, substance_free], _config())

    reasons = {v.trend.topic_key: v.reason for v in selection.unusable}
    assert reasons["x"] == "no trend name"
    assert "why_it_works" in reasons["y"] and "post text" in reasons["y"]


def test_fr6_post_text_alone_is_enough_substance() -> None:
    """FR-6 re-based (v2.0.0): the substance that matters most post-pivot is the topic's own posts,
    because the verbatim contract (§1.7) quotes their strings and nothing else. A topic whose
    theme-level prose is thin is perfectly usable when its winning posts carry text."""
    quiet_theme = _trend("wordy", why="", posts=("post-a",))
    assert not quiet_theme.why_it_works and not quiet_theme.tactics

    selection = select([quiet_theme], _config())

    assert [v.verdict for v in selection.verdicts] == ["eligible"]

    # ... and a post carrying no quotable string at all is not substance.
    silent = _trend("silent", why="")
    silent.posts = [SourcePost(post_id="post-a", url="https://x/1")]
    assert select([silent], _config()).verdicts[0].verdict == "unusable"


def test_fr5_ranking_is_strength_desc_and_deterministic() -> None:
    trends = [_trend("a", strength=0.2), _trend("b", strength=0.9), _trend("c", strength=0.9)]
    selection = select(trends, _config())

    assert [t.topic_key for t in selection.eligible] == ["b", "c", "a"]


# --------------------------------------------------------------------------- FR-8/90 assignment


def test_fr90_slideshow_topics_go_to_carousels_and_video_topics_to_images() -> None:
    """FR-90: `is_slideshow` is re-derived per topic post-pivot (the majority type across its own
    view-ranked posts, §1.6), so affinity follows the composition of the posts a creative will
    actually quote rather than one label carried by a whole monitor."""
    cfg = _config(formats={"image": 1, "carousel": 1, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg)
    selection = select([_trend("vid", strength=0.9), _deck_topic("deck", strength=0.5)], cfg)

    result = assign(plan.entries, selection, cfg)

    assigned = {e.creative_format: e.topic_key for e in plan.entries}
    assert assigned == {"image": "vid", "carousel": "deck"}
    assert [d.reason for d in result.decisions] == ["affinity", "affinity"]
    assert result.trends_needed == 2 and result.usable_trends == 2
    # `max_trend_reuses_per_run` default is 6 (D36 post-level recency + FR-91 per-reuse rotation),
    # so the ceiling this fixture computes is 2 usable x 6 = 12.
    assert result.batch_ceiling == 12


def test_fr90_no_affinity_match_falls_back_to_plain_rank_order_for_an_image() -> None:
    """Affinity stays the SOFT tie-break it always was for images and reels (FR-90).

    Under `sources.include_videos: false` those formats are refused at pre-flight (§0.14e), so
    hard-constraining them here would turn a config refusal the operator can act on into a silent
    famine — an image is written from a post's caption or hooks either way.
    """
    cfg = _config(formats={"image": 1, "carousel": 0, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg)
    selection = select([_deck_topic("weak-deck", strength=0.3),
                        _deck_topic("strong-deck", strength=0.9)], cfg)

    result = assign(plan.entries, selection, cfg)

    assert plan.entries[0].topic_key == "strong-deck"
    assert result.decisions[0].reason == "rank_fallback"


def test_fr90_a_carousel_never_rank_falls_back_onto_video_material() -> None:
    """FR-90 as amended v2.1.0: affinity is a CONSTRAINT for carousels, and the miss is a skip.

    Our slide *i* renders their panel *i* (FR-304), so a video-majority topic has nothing to map a
    deck from. The pre-D46 code bound it anyway and labelled the decision `rank_fallback`, which is
    exactly how run `20260813_093720_7hiu` came to quote hashtag captions onto five slides.
    """
    cfg = _config(formats={"image": 0, "carousel": 1, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg)
    selection = select([_trend("weak-vid", strength=0.3), _trend("strong-vid", strength=0.9)], cfg)

    result = assign(plan.entries, selection, cfg)

    entry = plan.entries[0]
    assert entry.trend_key is None and entry.source_post_id is None
    assert entry.status is PlanEntryStatus.SKIPPED
    assert (entry.skip_reason or "").startswith(f"{NO_FRESH_POST_AVAILABLE}: ")
    assert "no-repeat window" in (entry.skip_reason or "")
    assert result.decisions[0].reason == NO_FRESH_POST_AVAILABLE
    assert "rank_fallback" not in {d.reason for d in result.decisions}
    assert result.no_fresh_post_skips == 1 and result.carousel_posts_available == 0
    assert result.fresh_post_line == (
        "1 carousel(s) found no unused source slideshow: 0 fresh post(s) were bindable across the "
        "eligible topics and 0 of them were bound (at the 3+ usable-panel floor)"), \
        "v2.2.0: the supply figure names the ASSIGN floor it was counted at — LinkedIn's is 3"


# ------------------------------------------------------- FR-304/FR-307 source-post binding


def test_fr304_a_carousel_binds_the_viewiest_fresh_slideshow_post_and_its_deck_length() -> None:
    """The whole of §0.4′ in one assignment: WHICH post, and how many slides it makes.

    `TrendItem.posts` arrives view-ranked, so "first bindable" IS "viewiest bindable" — and the
    deck length is that post's own `panel_count`, fixed here so the Confirm gate prices the deck
    the run will actually render rather than a flat platform number.
    """
    cfg = _config(formats={"image": 0, "carousel": 1, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg)
    assert plan.entries[0].slide_count == 5, \
        "DEFAULT_UNBOUND_DECK_SLIDES stands in until ASSIGN binds — never the 20-slide max"
    topic = _deck_topic("decks", _deck("post-top", panels=3, views=9000),
                        _deck("post-second", panels=4, views=100))

    result = assign(plan.entries, select([topic], cfg), cfg)

    entry = plan.entries[0]
    assert entry.source_post_id == "post-top"
    assert entry.slide_count == 3, "the bound post's panel count, not the platform max"
    assert result.decisions[0].source_post_id == "post-top"
    assert "post post-top · 3 slide(s) of 3 source panel(s)" in result.decisions[0].detail
    assert result.carousel_posts_available == 2 and result.carousel_posts_bound == 1
    assert result.fresh_post_line == "", "nothing starved, so there is no famine line to print"


def test_fr304_a_video_post_inside_a_slideshow_topic_is_never_bound() -> None:
    """A topic is slideshow-MAJORITY, not slideshow-only (§1.6), so the pick still reads panels."""
    cfg = _config(formats={"image": 0, "carousel": 1, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg)
    topic = _deck_topic("mixed", _post("post-video", views=9000),  # no panels at all
                        # 3 panels rather than 2 since v2.2.0: this platform's ASSIGN floor is
                        # `platforms.linkedin.min_carousel_panels` (3), and this test is about the
                        # VIDEO post being unbindable, not about the floor.
                        _deck("post-deck", panels=3, views=10))

    assign(plan.entries, select([topic], cfg), cfg)

    assert plan.entries[0].source_post_id == "post-deck"
    assert plan.entries[0].slide_count == 3


def test_fr307_a_post_burnt_by_history_is_not_bound_and_the_next_one_is() -> None:
    """§0.10's pick-time half of the guard: `select()` computed the burnt union, `assign()` binds
    around it. The topic itself is still eligible — one fresh post is all it needs (FR-7)."""
    cfg = _config(formats={"image": 0, "carousel": 1, "reel": 0}, platforms=["linkedin"],
                  trend_history_days=30)
    plan = build_plan(cfg)
    topic = _deck_topic("decks", _deck("post-yesterday", panels=6, views=9000),
                        _deck("post-fresh", panels=3, views=50))
    history = {_hk("decks"): _seen(1, "post-yesterday")}
    selection = select([topic], cfg, history)

    assert selection.burnt_posts == frozenset({"post-yesterday"})
    result = assign(plan.entries, selection, cfg)

    assert plan.entries[0].source_post_id == "post-fresh"
    assert plan.entries[0].slide_count == 3
    assert result.carousel_posts_available == 1, "the burnt post is not counted as supply"


def test_fr307_two_carousels_on_one_topic_take_two_different_posts_then_starve() -> None:
    """A post is a one-shot resource INSIDE a run as well as across runs (§0.10). The third deck
    has nothing left to quote, so it skips — it never wraps back onto slide-for-slide repeats."""
    cfg = _config(formats={"image": 0, "carousel": 3, "reel": 0}, platforms=["linkedin"],
                  max_trend_reuses_per_run=6)
    plan = build_plan(cfg)
    # 3 panels on `post-a`, not 2: LinkedIn's v2.2.0 ASSIGN floor is 3 and this test is about
    # exhaustion, not about the floor.
    topic = _deck_topic("decks", _deck("post-a", panels=3, views=900),
                        _deck("post-b", panels=4, views=200))

    result = assign(plan.entries, select([topic], cfg), cfg)

    assert [e.source_post_id for e in plan.entries] == ["post-a", "post-b", None]
    assert [e.slide_count for e in plan.entries] == [3, 4, 5]  # the starved entry keeps its stub
    assert [d.reason for d in result.decisions] == ["affinity", "reuse", NO_FRESH_POST_AVAILABLE]
    assert plan.entries[2].status is PlanEntryStatus.SKIPPED
    assert result.no_fresh_post_skips == 1
    assert result.carousel_posts_available == 2 and result.carousel_posts_bound == 2
    assert "2 fresh post(s) were bindable" in result.fresh_post_line


def test_fr307_a_topic_with_no_bindable_deck_left_loses_the_entry_to_a_weaker_topic() -> None:
    """Bindability is a FILTER over the candidate topics, not a test applied to the winner.

    The strong topic here is perfectly eligible — it still carries a fresh post, so FR-7's topic
    gate keeps it — but its only SLIDESHOW is one an earlier run already quoted, and its other post
    is a video with no panels to map (FR-304). If the pick chose the topic first and looked for a
    deck second, this entry would skip while a bindable deck sat one rank down; instead the topic
    falls out of the candidate list and the weaker topic's fresh deck is bound.

    This is the cross-topic half of §0.10's exhaustion rule. The within-topic half (a second
    carousel taking a second post, a third starving) is pinned above; famine is only honest once it
    means the whole eligible pool is spent, not that the first choice was.
    """
    cfg = _config(formats={"image": 0, "carousel": 1, "reel": 0}, platforms=["linkedin"],
                  trend_history_days=30)
    plan = build_plan(cfg)
    strong = _deck_topic("strong", _deck("post-burnt", panels=6, views=9000),
                         _post("post-video", views=8000), strength=0.9)
    weak = _deck_topic("weak", _deck("post-fresh", panels=3, views=10), strength=0.2)
    history = {_hk("strong"): _seen(1, "post-burnt")}

    selection = select([strong, weak], cfg, history)
    result = assign(plan.entries, selection, cfg)

    assert [t.topic_key for t in selection.eligible] == ["strong", "weak"], \
        "the strong topic is still eligible — one fresh post is all FR-7 asks of a topic"
    assert plan.entries[0].topic_key == "weak"
    assert plan.entries[0].source_post_id == "post-fresh" and plan.entries[0].slide_count == 3
    assert plan.entries[0].status is PlanEntryStatus.PENDING
    assert result.decisions[0].reason == "affinity"
    assert result.no_fresh_post_skips == 0
    assert result.carousel_posts_available == 1, "the burnt deck and the video are not supply"


def test_v220_the_assign_floor_is_per_platform_so_one_post_binds_on_instagram_and_not_linkedin(
) -> None:
    """`platforms.<name>.min_carousel_panels` is the ASSIGN floor (v2.2.0/D49).

    A two-panel post is a legitimate feed carousel and a truncated-looking LinkedIn document, so
    the same topic supplies Instagram and starves LinkedIn in the same run. The global
    `MIN_DECK_SLIDES` stays underneath as the minimum a floor may ever mean.
    """
    cfg = _config(formats={"image": 0, "carousel": 2, "reel": 0},
                  platforms=["linkedin", "instagram"])
    plan = build_plan(cfg)
    topic = _deck_topic("decks", _deck("post-two", panels=2, views=900))

    result = assign(plan.entries, select([topic], cfg), cfg)

    linkedin, instagram = plan.entries[0], plan.entries[1]
    assert linkedin.platform == "linkedin" and instagram.platform == "instagram"
    assert instagram.source_post_id == "post-two" and instagram.slide_count == 2
    assert linkedin.source_post_id is None
    assert linkedin.status is PlanEntryStatus.SKIPPED
    assert "3+ usable panel(s) (linkedin floor)" in (linkedin.skip_reason or "")
    assert result.carousel_floor == MIN_DECK_SLIDES, \
        "the supply count is screened at the LOWEST floor the plan's own carousels carry"
    assert result.carousel_posts_available == 1


def test_fr307_the_supply_figure_counts_each_post_once_however_many_topics_carry_it() -> None:
    """§0.9's supply arithmetic is what W5 writes into FR-307's placeholder, so it has to be the
    number of DECKS the run could actually bind — not a sum of per-topic counts.

    One post can sit in two topics (the clusters are themed, not disjoint), and counting it twice
    would overstate the weekly supply and make a daily cadence look affordable when it is not.
    """
    cfg = _config(formats={"image": 0, "carousel": 2, "reel": 0}, platforms=["linkedin"],
                  max_trend_reuses_per_run=6)
    plan = build_plan(cfg)
    shared = _deck("post-shared", panels=4, views=900)
    # `post-own` carries 3 panels since v2.2.0 — LinkedIn's ASSIGN floor — so that it still counts
    # as supply here; the arithmetic under test is the DE-DUPLICATION of `post-shared`.
    first = _deck_topic("agents", shared, _deck("post-own", panels=3, views=100), strength=0.9)
    second = _deck_topic("automation", shared, strength=0.4)

    result = assign(plan.entries, select([first, second], cfg), cfg)

    assert result.carousel_posts_available == 2, "post-shared is one deck, not two"
    assert [e.source_post_id for e in plan.entries] == ["post-shared", "post-own"], \
        "and once bound it is spent for the whole run, in every topic that carries it"
    assert result.carousel_posts_bound == 2 and result.no_fresh_post_skips == 0


def test_fr304_the_platform_max_caps_a_deck_it_never_sets_one() -> None:
    """The 2026-08-13 repurposing, end to end: `carousel_slides` is a platform HARD MAX and the
    SOURCE decides the length under it.

    Run 20260813_143420_oyo4 shipped every deck at exactly 5 slides — 5- to 8-panel sources all
    cut to the old flat ceiling — which is the defect this pins. Instagram's max is the tightest
    of the three (10), so it is the one where truncation is still reachable at all.
    """
    cfg = _config(formats={"image": 0, "carousel": 3, "reel": 0}, platforms=["instagram"])
    assert cfg.platform("instagram").carousel_slides == 10, "the platform's own published ceiling"
    plan = build_plan(cfg)
    assert [e.slide_count for e in plan.entries] == [5, 5, 5], \
        "before ASSIGN a deck is the provisional length, NOT the 10-slide max"
    topic = _deck_topic("decks", _deck("post-tall", panels=12, views=9000),
                        _deck("post-short", panels=3, views=500),
                        _deck("post-thin", panels=1, views=100))

    result = assign(plan.entries, select([topic], cfg), cfg)

    assert plan.entries[0].slide_count == 10, "12 panels truncated to Instagram's max"
    assert "post post-tall · 10 slide(s) of 12 source panel(s)" in result.decisions[0].detail
    assert plan.entries[1].slide_count == 3, "3 panels ship 3 slides — not padded up to anything"
    assert plan.entries[2].status is PlanEntryStatus.SKIPPED, "a 1-panel post is not a deck"
    assert result.decisions[2].reason == NO_FRESH_POST_AVAILABLE
    assert deck_length(_deck("post-tall", panels=12), cfg, "linkedin") == 12, \
        "and on a platform whose max is 20, the same source ships all 12"


def test_fr304_the_deck_is_clamped_into_two_and_the_platform_ceiling() -> None:
    """§0.4′/FR-257's clamp, both ends. A source deck longer than the max ships its first N
    panels (the cut is tagged `panels_truncated` at generate time); a one-panel post is not a
    carousel source at all, so the floor is only ever reached through the max."""
    cfg = _config(formats={"image": 0, "carousel": 2, "reel": 0}, platforms=["linkedin"])
    cfg.platforms["linkedin"] = PlatformConfig(formats=["carousel"], carousel_slides=4)
    plan = build_plan(cfg)
    topic = _deck_topic("decks", _deck("post-long", panels=9, views=900),
                        _deck("post-short", panels=2, views=100))

    assign(plan.entries, select([topic], cfg), cfg)

    assert [e.slide_count for e in plan.entries] == [4, 2]
    tiny = PlatformConfig(formats=["carousel"], carousel_slides=1)
    cfg.platforms["linkedin"] = tiny
    assert deck_length(_deck("post-short", panels=2), cfg, "linkedin") == MIN_DECK_SLIDES, \
        "a misconfigured ceiling of 1 can never produce a one-slide carousel"


def test_fr304_a_one_panel_post_is_not_a_carousel_source() -> None:
    """§0.14a's deck-eligibility bar: two usable panel slots, or it is not a deck."""
    cfg = _config(formats={"image": 0, "carousel": 1, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg)
    topic = _deck_topic("thin", _deck("post-single", panels=1))

    result = assign(plan.entries, select([topic], cfg), cfg)

    assert plan.entries[0].status is PlanEntryStatus.SKIPPED
    assert result.decisions[0].reason == NO_FRESH_POST_AVAILABLE


def test_fr304_usable_panel_slots_follow_the_vision_switch() -> None:
    """§0.14a: a slot is usable iff it carries words after the merge — and at ASSIGN the vision
    half of that merge is a PROSPECT, gated by `sources.vision_transcribe` (§0.6).

    With vision on, a picture is a promise of words; with it off, only the words Virlo already
    shipped count, which narrows the pool of bindable posts as well as the run's spend.
    """
    cfg = _config()
    silent = _deck("post-silent", panels=4, texts=("", "", "", ""))
    half = _deck("post-half", panels=4, texts=("headline", "", "", ""))

    assert source_panel_count(silent) == 4
    assert usable_panel_slots(silent, cfg) == 4 and usable_panel_slots(half, cfg) == 4

    cfg.sources.vision_transcribe = False
    assert usable_panel_slots(silent, cfg) == 0
    assert usable_panel_slots(half, cfg) == 1  # one non-empty slot is below the two-slot bar
    topic = _deck_topic("quiet", silent, half)
    assert fresh_source_post(topic, cfg) is None

    pictureless = _deck("post-nopics", panels=4, texts=("a", "b", "", ""), images=False)
    assert usable_panel_slots(pictureless, cfg) == 2, "Virlo's own words never need a picture"
    assert fresh_source_post(_deck_topic("wordy", pictureless), cfg) is pictureless


def test_fr144_an_override_brief_carousel_binds_no_post_and_keeps_the_default_length() -> None:
    """§0.14d: FR-304 does not apply to an `override` brief. It quotes no source, so it has no
    panel map, no bound post and no source-driven length — `DEFAULT_UNBOUND_DECK_SLIDES` stays its
    deck for good, which is why that constant is not the platform hard max."""
    cfg = _config(formats={"image": 0, "carousel": 0, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg, briefs=[BriefRequest(_brief("ai-audit-cta", formats=("carousel",)), 1)])

    result = assign(plan.entries, select([_trend("vid", strength=0.9)], cfg), cfg)

    entry = plan.entries[0]
    assert entry.creative_format == "carousel" and entry.brief_influence == "override"
    assert entry.source_post_id is None and entry.slide_count == 5
    assert entry.status is PlanEntryStatus.PENDING
    assert [d.reason for d in result.decisions] == ["brief_override"]
    assert result.no_fresh_post_skips == 0 and result.trends_needed == 0


def test_fr90_no_last_resort_tier_survives_the_pivot() -> None:
    """FR-90's "arrived without pictures, use only as a last resort" bucket is withdrawn (v2.0.0).

    Virlo is a text feed and the visuals come from the style registry, so EVERY topic would fall
    into that bucket: a tie-break every candidate satisfies is not a tie-break, and the decision
    reason it produced would have labelled every assignment of every run. Plain strength rank is
    what decides, and `last_resort_text_only` is not a reason this module can emit any more.
    """
    cfg = _config(formats={"image": 2, "carousel": 0, "reel": 0}, platforms=["linkedin"],
                  max_trend_reuses_per_run=1)
    plan = build_plan(cfg)
    selection = select([_trend("weak", strength=0.4), _trend("strong", strength=0.99)], cfg)

    result = assign(plan.entries, selection, cfg)

    assert [e.topic_key for e in plan.entries] == ["strong", "weak"]
    assert {d.reason for d in result.decisions} == {"affinity"}


def test_fr8_reuse_wraps_around_and_is_bounded() -> None:
    """FR-8's ceiling, and the restatement the operator reads before generation proceeds."""
    cfg = _config(formats={"image": 3, "carousel": 0, "reel": 0}, platforms=["linkedin"],
                  max_trend_reuses_per_run=2)
    plan = build_plan(cfg)

    result = assign(plan.entries, select([_trend("a", strength=0.9), _trend("b")], cfg), cfg)

    assert [e.topic_key for e in plan.entries] == ["a", "b", "a"]
    assert [d.reason for d in result.decisions] == ["affinity", "affinity", "reuse"]
    assert result.summary_line == (
        "this plan needs 3 distinct topic(s); 2 are available after filtering "
        "(batch ceiling 4 creatives)")


def test_fr8_the_reuse_index_diverges_siblings_on_one_topic() -> None:
    """`trend_reuse_index` survives the pivot, re-scoped (§1.6/arch #8): it is the 0-based position
    among the creatives sharing a topic, and `copywrite` quotes `posts[index % len(posts)]` with
    it. Two creatives on one topic must therefore carry two different indices, or the run ships
    the same caption twice — and the FIRST one must be 0, so it quotes the top-viewed post."""
    cfg = _config(formats={"image": 2, "carousel": 0, "reel": 0}, platforms=["linkedin"],
                  max_trend_reuses_per_run=2)
    plan = build_plan(cfg)

    assign(plan.entries, select([_trend("solo", posts=("post-a", "post-b"))], cfg), cfg)

    assert [e.trend_reuse_index for e in plan.entries] == [0, 1]
    assert {e.trend_key for e in plan.entries} == {_hk("solo")}


def test_fr8_assignment_rewrites_the_asset_id_and_stamps_the_topic_key() -> None:
    """FR-71's slug is the TOPIC's name, and FR-73's `topic_key` is stamped beside `trend_key` —
    meta.yaml, the gallery and post-level recency all read the second one (§1.6)."""
    cfg = _config(formats={"image": 0, "carousel": 1, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg)
    topic = _deck_topic("dance", _deck("post-a"))
    topic.name = "Dance Challenge!"

    assign(plan.entries, select([topic], cfg), cfg)

    assert plan.entries[0].asset_id == "Li_car_dance-challenge_01"
    assert plan.entries[0].trend_key == _hk("dance")
    assert plan.entries[0].topic_key == "dance"


def test_fr8_a_plan_bigger_than_the_pool_keeps_its_surplus_as_terminal_skips() -> None:
    """FR-4/FR-8: nothing leaves the plan. The surplus group goes terminal with a reason naming
    the arithmetic that produced it, so `_package` can still account for it."""
    cfg = _config(formats={"image": 2, "carousel": 0, "reel": 0}, platforms=["linkedin"],
                  max_trend_reuses_per_run=1)
    plan = build_plan(cfg)

    result = assign(plan.entries, select([_trend("solo")], cfg), cfg)

    first, second = plan.entries[0], plan.entries[1]
    assert first.trend_key == _hk("solo") and result.decisions[0].use_index == 1
    assert second.status is PlanEntryStatus.SKIPPED
    assert "no_trend_available" in (second.skip_reason or "")
    assert "1 usable topic(s) x 1 reuse(s)" in (second.skip_reason or "")
    assert result.dropped == [second] and result.decisions[1].reason == "dropped"


def test_fr144_override_brief_creatives_consume_no_topic() -> None:
    cfg = _config(formats={"image": 1, "carousel": 0, "reel": 0}, platforms=["linkedin"],
                  max_trend_reuses_per_run=1)
    plan = build_plan(cfg, briefs=[BriefRequest(_brief("ai-audit-cta"), 1)])

    result = assign(plan.entries, select([_trend("solo")], cfg), cfg)

    brief_entry, topic_entry = plan.entries
    assert brief_entry.trend_key is None and brief_entry.brief_influence == "override"
    assert brief_entry.topic_key == "" and brief_entry.asset_id == "Li_img_ai-audit-cta_01"
    assert topic_entry.trend_key == _hk("solo")  # the brief left the topic budget untouched
    assert [d.reason for d in result.decisions] == ["brief_override", "affinity"]
    assert result.trends_needed == 1


def test_fr145_blend_brief_creatives_take_a_topic_like_any_other() -> None:
    cfg = _config(formats={"image": 0, "carousel": 0, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg, briefs=[BriefRequest(_brief("case-study", influence="blend"), 1)])

    result = assign(plan.entries, select([_trend("solo")], cfg), cfg)

    assert len(plan.entries) == 1  # one requested creative, one entry (A/B withdrawn)
    assert plan.entries[0].trend_key == _hk("solo")
    assert [d.reason for d in result.decisions] == ["affinity"]
    assert result.trends_needed == 1


def test_assign_skips_entries_that_are_already_terminal() -> None:
    cfg = _config(formats={"image": 2, "carousel": 0, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg)
    plan.entries[0].status = PlanEntryStatus.SKIPPED_BUDGET

    result = assign(plan.entries, select([_trend("solo")], cfg), cfg)

    assert plan.entries[0].trend_key is None  # a budget-trimmed entry is left alone
    assert plan.entries[1].trend_key == _hk("solo")
    assert result.trends_needed == 1


def test_assign_with_no_eligible_topics_drops_every_topic_dependent_entry() -> None:
    cfg = _config(formats={"image": 1, "carousel": 0, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg, briefs=[BriefRequest(_brief("ai-audit-cta"), 1)])

    result = assign(plan.entries, select([], cfg), cfg)

    assert result.usable_trends == 0 and result.batch_ceiling == 0
    assert [e.status for e in plan.entries] == [PlanEntryStatus.PENDING, PlanEntryStatus.SKIPPED]
    assert len(result.dropped) == 1  # the brief-only creative still stands (10 §10 carve-out)


# ---- D63 --------------------- FR-345: the bind-time language screen, and the mode that gates it


def _spoken(post: SourcePost, language: str) -> SourcePost:
    """The same source post with Virlo's `intelligence.language_detected` reading attached."""
    post.language = language
    return post


def test_fr345_a_foreign_post_is_unbindable_under_source_and_the_pick_falls_to_the_next_one(
) -> None:
    """The German-deck defect of run `20260820_145809_4a0q`, made unrepeatable.

    That run bound `Ig_car_claude-ai-for-productivity-and-business_08` to a German post inside a
    topic the FR-294 screen had judged English, and shipped German panels under an English caption
    — because under `source` mode the copy is quoted byte for byte and nothing downstream can
    change a word of it. The topic screen could not have caught it: it grades a TOPIC's own
    strings, and one foreign post ranked first inside an otherwise-English topic is invisible to
    it. So the screen belongs where the post is chosen.

    The fallback is the point, not the skip: the topic keeps its other posts, and the binder takes
    the next view-ranked one that this run can actually quote.
    """
    cfg = _config()
    foreign = _spoken(_deck("post-de", panels=5, views=9000), "de")
    ours = _spoken(_deck("post-en", panels=4, views=1000), "en")
    topic = _deck_topic("ai-tools", foreign, ours)

    assert cfg.run.copy_language_mode == "source", "the engine default, not set by this test"
    assert off_language_post(foreign, cfg) is True
    assert off_language_post(ours, cfg) is False
    assert fresh_source_post(topic, cfg) is ours, \
        "the higher-viewed post is refused and the pick falls through, it does not skip the topic"


def test_fr345_target_mode_turns_the_screen_off_and_the_foreign_post_wins_its_rank_back(
) -> None:
    """Under `target` the same post is the intended material, not a defect.

    A bound deck is translated at COPY (FR-343), so a German post produces an English deck and its
    view rank is worth having — it is usually the reason the topic surfaced at all. This is the
    only eligibility test in the module that reads a run mode, and it reads one because the
    identical post is unusable under one value and first choice under the other.
    """
    cfg = _config(copy_language_mode="target")
    foreign = _spoken(_deck("post-de", panels=5, views=9000), "de")
    ours = _spoken(_deck("post-en", panels=4, views=1000), "en")

    assert off_language_post(foreign, cfg) is False
    assert fresh_source_post(_deck_topic("ai-tools", foreign, ours), cfg) is foreign
    # The other three tests are untouched by the mode — a one-panel post is still not a deck.
    thin = _spoken(_deck("post-thin", panels=1), "de")
    assert fresh_source_post(_deck_topic("thin", thin), cfg) is None


def test_fr345_a_post_with_no_language_reading_is_bound_under_both_modes() -> None:
    """Fail-open, exactly like the LLM screen's own language check.

    An empty code means Virlo sent no `language_detected` and the vision pass has not run yet — it
    runs after the Confirm gate, and this decision is made before it. A guess is not a reason to
    shrink the pool: the honest posture is to bind the post, and let COPY warn
    (`translate_language_unknown`) and ship its words verbatim if nobody ever learns the language.

    A run that configured no language at all screens nothing either, for the same reason: an empty
    target set is a config that never said what it writes, not a config that writes nothing.
    """
    silent = _spoken(_deck("post-quiet", panels=4), "")
    for mode in ("source", "target"):
        cfg = _config(copy_language_mode=mode)
        assert off_language_post(silent, cfg) is False
        assert fresh_source_post(_deck_topic("quiet", silent), cfg) is silent

    nowhere = _config(languages={})
    nowhere.run.onimage_text_language = {}
    assert off_language_post(_spoken(_deck("post-de", panels=4), "de"), nowhere) is False


def test_fr345_the_language_is_normalised_and_the_onimage_slot_counts_as_a_target() -> None:
    """Two details that decide real runs, pinned so neither drifts.

    The code is re-normalised through `topic_filter.language_code` rather than trusted: the Virlo
    adapter normalises on the way in, but a `SourcePost` also arrives from a preview fixture or a
    test, and one spelling rule for every rung of the ladder is the whole point of that function
    being public. `"German"` is `de` — the alias table beats the first-two-letters fallback that
    used to answer `ge`.

    And the target set is `run.languages` UNION `run.onimage_text_language` (whatever
    `topic_filter.target_languages` says), so a config that writes English captions over Czech
    on-image text can bind a Czech post. Two answers to "what does this run write" is exactly how
    a topic gets skipped at Select and an off-language post bound at ASSIGN.
    """
    cfg = _config()
    assert off_language_post(_spoken(_deck("post-named", panels=4), "German"), cfg) is True
    assert off_language_post(_spoken(_deck("post-named", panels=4), "English"), cfg) is False
    assert off_language_post(_spoken(_deck("post-named", panels=4), "en-US"), cfg) is False

    czech = _spoken(_deck("post-cs", panels=4), "cs")
    assert off_language_post(czech, cfg) is True, "an `en` run cannot quote it"
    cfg.run.onimage_text_language = {"linkedin": "cs"}
    assert off_language_post(czech, cfg) is False, "now something this run writes IS Czech"


def test_fr345_the_supply_count_agrees_with_the_binder_and_returns_every_post_it_drops(
) -> None:
    """`_carousel_supply` runs the SAME screen, and it is where the drop becomes visible.

    Two halves. The count is the numerator of FR-307's famine message ("N fresh post(s) were
    bindable"), so counting a post the binder will refuse would make that message argue against
    the very skip it is explaining.

    And the pairs are collected HERE rather than in the binder because this is the one walk that
    sees each candidate post exactly once per `assign()`: `_pick` calls the binder once per topic
    per creative group, so the same German post would otherwise be reported nine times on a
    nine-deck plan.

    They leave as DATA on `Assignment`, never as a `logging` call. That is NFR-2 (this module
    prints nothing and logs nothing — every decision leaves as data so `runner.py` can write it
    and `previews.py` can show it at $0), and it is also the only shape that WORKS:
    `__main__._configure_logging` installs a NullHandler, so a `logger.warning` from here reaches
    no operator surface at all. `runner._select` turns the pairs into one `plan_off_language_posts`
    warning and one console line — a drop nobody can see is the defect FR-345 exists to end.
    """
    cfg = _config(formats={"image": 0, "carousel": 1, "reel": 0}, platforms=["instagram"])
    foreign = _spoken(_deck("post-de", panels=5, views=9000), "de")
    ours = _spoken(_deck("post-en", panels=4, views=1000), "en")
    topic = _deck_topic("ai-tools", foreign, ours)
    plan = build_plan(cfg)

    result = assign(plan.entries, select([topic], cfg), cfg)

    assert result.carousel_posts_available == 1, "the German post is not supply this run can spend"
    assert plan.entries[0].source_post_id == "post-en"
    assert result.off_language_posts == [("post-de", "de")], \
        "the id AND the normalised code, so the console can name both the loss and the cure"

    # Under `target` both posts are supply, nothing is dropped and the list stays empty.
    translating = _config(formats={"image": 0, "carousel": 1, "reel": 0},
                          platforms=["instagram"], copy_language_mode="target")
    result = assign(build_plan(translating).entries,
                    select([_deck_topic("ai-tools", foreign, ours)], translating), translating)

    assert result.carousel_posts_available == 2
    assert result.off_language_posts == []


def test_fr345_plan_writes_no_log_records_at_all_and_names_each_dropped_post_once() -> None:
    """NFR-2's purity, pinned as an absence: `plan` emits nothing through `logging`, ever.

    The module used to write one `logger.warning` per off-language post. It was invisible —
    `__main__._configure_logging` installs a NullHandler and no console handler — so the operator
    of run `4a0q` still could not see why a post left the pool. The cure was to move the fact into
    the result object, and this test is what keeps it there: any future decision that reaches for
    a logger inside `plan` fails here rather than being discovered on a paid run.

    The second half is the de-duplication. One post can sit in several topics of one pool, and the
    console line counts posts rather than sightings, so the walk records each id at most once.
    """
    cfg = _config(formats={"image": 0, "carousel": 2, "reel": 0}, platforms=["instagram"])
    german = _spoken(_deck("post-de", panels=5, views=9000), "de")
    french = _spoken(_deck("post-fr", panels=5, views=8000), "fr")
    ours = _spoken(_deck("post-en", panels=4, views=1000), "en")
    pool = [_deck_topic("ai-tools", german, french, ours),
            _deck_topic("ai-agents", german, ours)]  # the SAME German post, seen twice

    with _no_log_records() as records:
        result = assign(build_plan(cfg).entries, select(pool, cfg), cfg)

    assert records == [], "plan must not write log records — NFR-2, and nothing would read them"
    assert result.off_language_posts == [("post-de", "de"), ("post-fr", "fr")], \
        "pool order, each post id once, both codes normalised"


@contextmanager
def _no_log_records() -> Iterator[list[logging.LogRecord]]:
    """Capture anything `hypesocials.plan` writes through `logging`, which must be nothing."""
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("hypesocials.plan")
    handler = _Capture()
    logger.addHandler(handler)
    previous, logger.propagate = logger.propagate, False
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.propagate = previous


def test_fr345_a_topic_whose_every_post_is_foreign_starves_under_source_and_binds_under_target(
) -> None:
    """End to end through `assign()`, because the two modes must differ in the PLAN, not only in a
    predicate. Under `source` the carousel keeps its terminal status and FR-307's own reason —
    the material exists but this run cannot quote it, which is the same shape as a topic whose
    slideshows have all been used. Under `target` the identical inputs produce a bound deck whose
    length comes from the German post's panels, priced before the Confirm gate exactly like any
    other (§0.4′)."""
    foreign = _spoken(_deck("post-de", panels=6), "de")
    kwargs = {"formats": {"image": 0, "carousel": 1, "reel": 0}, "platforms": ["instagram"]}

    kept = _config(**kwargs)
    plan = build_plan(kept)
    starved = assign(plan.entries, select([_deck_topic("nur-deutsch", foreign)], kept), kept)

    assert plan.entries[0].status is PlanEntryStatus.SKIPPED
    assert starved.decisions[0].reason == NO_FRESH_POST_AVAILABLE
    assert starved.no_fresh_post_skips == 1 and starved.carousel_posts_available == 0

    translating = _config(**kwargs, copy_language_mode="target")
    bound_plan = build_plan(translating)
    bound = assign(bound_plan.entries, select([_deck_topic("nur-deutsch", foreign)], translating),
                   translating)

    assert bound_plan.entries[0].status is PlanEntryStatus.PENDING
    assert bound_plan.entries[0].source_post_id == "post-de"
    assert bound_plan.entries[0].slide_count == 6, "the deck length still comes from the source"
    assert bound.no_fresh_post_skips == 0 and bound.carousel_posts_bound == 1
