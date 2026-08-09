"""Tests for `hypesocials.plan` — the Select + Expand stage (FR-1–8, FR-90, FR-143/144).

Pure logic, so every test is sync: no event loop, no I/O, no fixtures beyond small builders.
The two W2-barrier tests are `test_fr1_worked_example_*` (the PRD's own expansion example,
reproduced verbatim) and `test_fr106_*` (the compound trim-order contract).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypesocials.config import Config, PlatformConfig, RunConfig
from hypesocials.models import Brief, PlanEntry, PlanEntryStatus, TrendItem
from hypesocials.plan import BriefRequest, assign, build_plan, select

# --------------------------------------------------------------------------- builders


def _config(**run_kwargs) -> Config:
    """A Config with the PRD's default three platforms and no YAML involved."""
    cfg = Config(run=RunConfig(**run_kwargs))
    cfg.models.price_per_unit.reel_second["720p"] = 0.10  # reels priced ONLY where a test needs it
    return cfg


def _worked_example_config(*, mode: str = "analyzed") -> Config:
    """10-pipeline §1's worked example verbatim: images everywhere, carousels on Li+Ig, reels Tk."""
    cfg = _config(formats={"image": 3, "carousel": 2, "reel": 1}, generation_mode=mode)
    cfg.platforms = {
        "linkedin": PlatformConfig(formats=["image", "carousel"], carousel_slides=5),
        "instagram": PlatformConfig(formats=["image", "carousel"], carousel_slides=5),
        "tiktok": PlatformConfig(formats=["image", "reel"], carousel_slides=5),
    }
    return cfg


def _trend(key: str, *, strength: float = 0.5, slideshow: bool = False, images: bool = True,
           name: str | None = None, why: str = "strong pattern interrupt") -> TrendItem:
    return TrendItem(
        history_key=key,
        monitor_id="m1",
        name=name if name is not None else key.replace("-", " ").title(),
        strength=strength,
        is_slideshow=slideshow,
        why_it_works=why,
        reference_groups=[["https://cdn/1.jpg", "https://cdn/2.jpg"]] if images else [],
    )


def _brief(name: str, influence: str = "override", formats=("image",)) -> Brief:
    return Brief(name=name, description="d", influence=influence, formats=list(formats))


def _days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def _shape(entries: list[PlanEntry]) -> list[tuple[str, str, str]]:
    return [(e.platform, e.creative_format, e.aspect_ratio) for e in entries]


# --------------------------------------------------------------------------- FR-1 worked example


def test_fr1_worked_example_expands_to_six_creatives() -> None:
    """"The plan resolves to six creatives" — exact counts, order, ratios and ids (FR-1/2/21)."""
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
        "Li_img_unassigned_analyzed_01",
        "Ig_img_unassigned_analyzed_02",
        "Tk_img_unassigned_analyzed_03",
        "Li_car_unassigned_analyzed_04",
        "Ig_car_unassigned_analyzed_05",
        "Tk_reel_unassigned_analyzed_06",
    ]
    assert [e.slide_count for e in plan.entries] == [None, None, None, 5, 5, None]
    # "That is 13 slide/image renders" — 3 singles + 2 decks x 5 slides.
    assert sum(e.slide_count or 1 for e in plan.entries if e.creative_format != "reel") == 13
    assert all(e.variant == "analyzed" and e.pair_id is None for e in plan.entries)
    assert len({e.atomic_group for e in plan.entries}) == 6  # nothing shares a trim unit
    assert plan.notes == []


def test_fr1_worked_example_both_mode_becomes_twelve_paired_creatives() -> None:
    """"In `both` mode the same request becomes twelve creatives" (FR-3/22)."""
    plan = build_plan(_worked_example_config(mode="both"))

    assert len(plan.entries) == 12
    assert _shape(plan.entries) == [s for s in _shape(build_plan(_worked_example_config()).entries)
                                    for _ in range(2)]
    for left, right in zip(plan.entries[::2], plan.entries[1::2]):
        assert (left.variant, right.variant) == ("analyzed", "direct")
        assert left.pair_id == right.pair_id is not None
        assert left.atomic_group == right.atomic_group  # a pair trims as ONE unit


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
    """Briefs + both-mode pairs + a carousel: the emitted ORDER is what makes trimming safe."""
    cfg = _config(formats={"image": 2, "carousel": 1, "reel": 0},
                  platforms=["linkedin", "instagram"], generation_mode="both")
    plan = build_plan(cfg, briefs=[BriefRequest(_brief("ai-audit-cta"), 2)])
    entries = plan.entries

    # Brief entries FIRST, single (override makes no analysis call, so there is no A/B to draw).
    assert [e.brief_name for e in entries[:2]] == ["ai-audit-cta", "ai-audit-cta"]
    assert all(e.variant == "direct" and e.pair_id is None for e in entries[:2])
    assert all(e.brief_name is None for e in entries[2:])
    # 2 brief + 2 image pairs + 1 carousel pair = 8 entries in 5 trim units.
    assert len(entries) == 8
    groups = [e.atomic_group for e in entries]
    assert len(set(groups)) == 5
    assert groups == sorted(groups, key=groups.index)  # every group is one contiguous run
    carousel = [e for e in entries if e.creative_format == "carousel"]
    assert len(carousel) == 2 and {e.slide_count for e in carousel} == {5}
    assert len({e.atomic_group for e in carousel}) == 1  # a deck is never half-trimmed

    # Trimming from the end never splits a unit, and the campaign brief survives longest.
    for keep in range(8, -1, -1):
        survivors = _trim_from_end(entries, keep)
        counts = {g: groups.count(g) for g in {e.atomic_group for e in survivors}}
        for group, size in counts.items():
            assert sum(1 for e in survivors if e.atomic_group == group) == size
        assert [e.order for e in survivors] == sorted(e.order for e in survivors)
        if survivors:
            assert survivors[0].brief_name == "ai-audit-cta"
    assert [e.brief_name for e in _trim_from_end(entries, 2)] == ["ai-audit-cta"] * 2


# --------------------------------------------------------------------------- FR-6/7 verdicts


def test_fr7_verdicts_cover_eligible_excluded_and_unusable() -> None:
    trends = [
        _trend("fresh", strength=0.9),
        _trend("stale", strength=0.8),
        _trend("empty", strength=0.7, why=""),
    ]
    history = {"stale": {"last_used": _days_ago(2), "run_ids": ["r1"]}}
    selection = select(trends, _config(trend_history_days=7), history)

    assert [v.verdict for v in selection.verdicts] == ["eligible", "excluded", "unusable"]
    assert [t.history_key for t in selection.eligible] == ["fresh"]

    excluded = selection.excluded[0]
    assert excluded.last_used == _days_ago(2)
    assert excluded.label == f"excluded (history, last used {_days_ago(2)})"

    unusable = selection.unusable[0]
    assert "text substance" in unusable.reason
    assert unusable.label == f"unusable ({unusable.reason})"


def test_fr7_zero_days_disables_the_history_window() -> None:
    history = {"stale": {"last_used": _days_ago(0)}}
    selection = select([_trend("stale")], _config(trend_history_days=0), history)

    assert [v.verdict for v in selection.verdicts] == ["eligible"]


def test_fr7_a_trend_older_than_the_window_is_eligible_again() -> None:
    history = {"old": {"last_used": _days_ago(30)}}
    selection = select([_trend("old")], _config(trend_history_days=7), history)

    assert selection.verdicts[0].verdict == "eligible"


def test_fr6_unusable_reasons_name_what_was_missing() -> None:
    nameless = _trend("x", name="  ")
    substance_free = TrendItem(history_key="y", monitor_id="m", name="Has A Name")
    selection = select([nameless, substance_free], _config())

    reasons = {v.trend.history_key: v.reason for v in selection.unusable}
    assert reasons["x"] == "no trend name"
    assert "why_it_works" in reasons["y"]


def test_fr6_text_but_no_images_stays_eligible_and_is_flagged_text_only() -> None:
    selection = select([_trend("wordy", images=False)], _config())

    verdict = selection.verdicts[0]
    assert verdict.verdict == "eligible" and verdict.text_only
    assert verdict.trend.text_only is True
    assert "last resort" in verdict.label


def test_fr5_ranking_is_strength_desc_and_deterministic() -> None:
    trends = [_trend("a", strength=0.2), _trend("b", strength=0.9), _trend("c", strength=0.9)]
    selection = select(trends, _config())

    assert [t.history_key for t in selection.eligible] == ["b", "c", "a"]


# --------------------------------------------------------------------------- FR-8/90 assignment


def test_fr90_slideshow_trends_go_to_carousels_and_video_trends_to_images() -> None:
    cfg = _config(formats={"image": 1, "carousel": 1, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg)
    selection = select([_trend("vid", strength=0.9), _trend("deck", strength=0.5, slideshow=True)],
                       cfg)

    result = assign(plan.entries, selection, cfg)

    assigned = {e.creative_format: e.trend_key for e in plan.entries}
    assert assigned == {"image": "vid", "carousel": "deck"}
    assert [d.reason for d in result.decisions] == ["affinity", "affinity"]
    assert result.trends_needed == 2 and result.usable_trends == 2
    assert result.batch_ceiling == 4  # 2 usable x max_trend_reuses_per_run 2


def test_fr90_no_affinity_match_falls_back_to_plain_rank_order() -> None:
    cfg = _config(formats={"image": 0, "carousel": 1, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg)
    selection = select([_trend("weak-vid", strength=0.3), _trend("strong-vid", strength=0.9)], cfg)

    result = assign(plan.entries, selection, cfg)

    assert plan.entries[0].trend_key == "strong-vid"
    assert result.decisions[0].reason == "rank_fallback"


def test_fr90_text_only_trends_are_the_last_resort() -> None:
    cfg = _config(formats={"image": 2, "carousel": 0, "reel": 0}, platforms=["linkedin"],
                  max_trend_reuses_per_run=2)
    plan = build_plan(cfg)
    selection = select([_trend("pics", strength=0.4), _trend("words", strength=0.99, images=False)],
                       cfg)

    assign(plan.entries, selection, cfg)

    # require_reference_image defaults true: an image-bearing trend exists, so text_only is unused.
    assert [e.trend_key for e in plan.entries] == ["pics", "pics"]


def test_fr90_text_only_is_used_once_image_bearing_capacity_runs_out() -> None:
    cfg = _config(formats={"image": 2, "carousel": 0, "reel": 0}, platforms=["linkedin"],
                  max_trend_reuses_per_run=1, require_reference_image=False)
    plan = build_plan(cfg)
    selection = select([_trend("pics", strength=0.4), _trend("words", strength=0.99, images=False)],
                       cfg)

    result = assign(plan.entries, selection, cfg)

    assert [e.trend_key for e in plan.entries] == ["pics", "words"]
    assert [d.reason for d in result.decisions] == ["affinity", "last_resort_text_only"]


def test_fr8_both_mode_pair_shares_one_trend_and_counts_as_one_reuse() -> None:
    cfg = _config(formats={"image": 2, "carousel": 0, "reel": 0}, platforms=["linkedin"],
                  generation_mode="both", max_trend_reuses_per_run=1)
    plan = build_plan(cfg)

    result = assign(plan.entries, select([_trend("solo")], cfg), cfg)

    first, second = plan.entries[:2], plan.entries[2:]
    assert {e.trend_key for e in first} == {"solo"}  # one trend across the A/B pair
    assert result.decisions[0].use_index == 1  # the pair is ONE use, not two
    assert all(e.status is PlanEntryStatus.SKIPPED for e in second)
    assert all("no_trend_available" in (e.skip_reason or "") for e in second)
    assert result.dropped == second and result.decisions[1].reason == "dropped"


def test_fr8_reuse_wraps_around_and_is_bounded() -> None:
    cfg = _config(formats={"image": 3, "carousel": 0, "reel": 0}, platforms=["linkedin"],
                  max_trend_reuses_per_run=2)
    plan = build_plan(cfg)

    result = assign(plan.entries, select([_trend("a", strength=0.9), _trend("b")], cfg), cfg)

    assert [e.trend_key for e in plan.entries] == ["a", "b", "a"]
    assert [d.reason for d in result.decisions] == ["affinity", "affinity", "reuse"]
    assert result.summary_line == (
        "this plan needs 3 distinct trend(s); 2 are available after filtering "
        "(batch ceiling 4 creatives)")


def test_fr8_assignment_rewrites_the_asset_id_with_the_trend_slug() -> None:
    cfg = _config(formats={"image": 0, "carousel": 1, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg)

    assign(plan.entries, select([_trend("dance", name="Dance Challenge!")], cfg), cfg)

    assert plan.entries[0].asset_id == "Li_car_dance-challenge_analyzed_01"


def test_fr144_override_brief_creatives_consume_no_trend() -> None:
    cfg = _config(formats={"image": 1, "carousel": 0, "reel": 0}, platforms=["linkedin"],
                  max_trend_reuses_per_run=1)
    plan = build_plan(cfg, briefs=[BriefRequest(_brief("ai-audit-cta"), 1)])

    result = assign(plan.entries, select([_trend("solo")], cfg), cfg)

    brief_entry, trend_entry = plan.entries
    assert brief_entry.trend_key is None and brief_entry.brief_influence == "override"
    assert brief_entry.asset_id == "Li_img_ai-audit-cta_direct_01"
    assert trend_entry.trend_key == "solo"  # the brief left the trend budget untouched
    assert [d.reason for d in result.decisions] == ["brief_override", "affinity"]
    assert result.trends_needed == 1


def test_fr145_blend_brief_creatives_expand_and_take_a_trend_like_any_other() -> None:
    cfg = _config(formats={"image": 0, "carousel": 0, "reel": 0}, platforms=["linkedin"],
                  generation_mode="both")
    plan = build_plan(cfg, briefs=[BriefRequest(_brief("case-study", influence="blend"), 1)])

    assign(plan.entries, select([_trend("solo")], cfg), cfg)

    assert [e.variant for e in plan.entries] == ["analyzed", "direct"]  # normal FR-3 expansion
    assert {e.trend_key for e in plan.entries} == {"solo"}
    assert plan.entries[0].pair_id == plan.entries[1].pair_id is not None


def test_assign_skips_entries_that_are_already_terminal() -> None:
    cfg = _config(formats={"image": 2, "carousel": 0, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg)
    plan.entries[0].status = PlanEntryStatus.SKIPPED_BUDGET

    result = assign(plan.entries, select([_trend("solo")], cfg), cfg)

    assert plan.entries[0].trend_key is None  # a budget-trimmed entry is left alone
    assert plan.entries[1].trend_key == "solo"
    assert result.trends_needed == 1


def test_assign_with_no_eligible_trends_drops_every_trend_dependent_entry() -> None:
    cfg = _config(formats={"image": 1, "carousel": 0, "reel": 0}, platforms=["linkedin"])
    plan = build_plan(cfg, briefs=[BriefRequest(_brief("ai-audit-cta"), 1)])

    result = assign(plan.entries, select([], cfg), cfg)

    assert result.usable_trends == 0 and result.batch_ceiling == 0
    assert [e.status for e in plan.entries] == [PlanEntryStatus.PENDING, PlanEntryStatus.SKIPPED]
    assert len(result.dropped) == 1  # the brief-only creative still stands (10 §10 carve-out)
