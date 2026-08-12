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

Pure logic, so every test is sync: no event loop, no I/O, no fixtures beyond small builders.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypesocials.config import Config, PlatformConfig, RunConfig
from hypesocials.models import Brief, PlanEntry, PlanEntryStatus, SourcePost, TrendItem
from hypesocials.plan import BriefRequest, assign, build_plan, select

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
          views: int = 1000) -> SourcePost:
    """One winning post inside a topic — the unit FR-7 excludes on and §1.7 quotes from."""
    return SourcePost(post_id=post_id, url=f"https://www.tiktok.com/@creator/video/{post_id}",
                      author="creator", caption=caption, views=views)


def _trend(topic: str, *, strength: float = 0.5, slideshow: bool = False,
           name: str | None = None, why: str = "strong pattern interrupt",
           posts: tuple[str, ...] = (), monitor: str = "m1") -> TrendItem:
    """One post-pivot TOPIC item. `posts` are its own view-ranked `SourcePost` ids (FR-293)."""
    return TrendItem(
        history_key=_hk(topic, monitor),
        monitor_id=monitor,
        topic_key=topic,
        name=name if name is not None else topic.replace("-", " ").title(),
        strength=strength,
        is_slideshow=slideshow,
        why_it_works=why,
        posts=[_post(post_id) for post_id in posts])


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
    selection = select([_trend("vid", strength=0.9), _trend("deck", strength=0.5, slideshow=True)],
                       cfg)

    result = assign(plan.entries, selection, cfg)

    assigned = {e.creative_format: e.topic_key for e in plan.entries}
    assert assigned == {"image": "vid", "carousel": "deck"}
    assert [d.reason for d in result.decisions] == ["affinity", "affinity"]
    assert result.trends_needed == 2 and result.usable_trends == 2
    # `max_trend_reuses_per_run` default is 6 (D36 post-level recency + FR-91 per-reuse rotation),
    # so the ceiling this fixture computes is 2 usable x 6 = 12.
    assert result.batch_ceiling == 12


def test_fr90_no_affinity_match_falls_back_to_plain_rank_order() -> None:
    cfg = _config(formats={"image": 0, "carousel": 1, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg)
    selection = select([_trend("weak-vid", strength=0.3), _trend("strong-vid", strength=0.9)], cfg)

    result = assign(plan.entries, selection, cfg)

    assert plan.entries[0].topic_key == "strong-vid"
    assert result.decisions[0].reason == "rank_fallback"


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

    assign(plan.entries, select([_trend("dance", name="Dance Challenge!")], cfg), cfg)

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
