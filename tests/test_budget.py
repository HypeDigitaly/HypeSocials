"""Budget tests — one named test per FR-107 bullet, plus FR-106's race and FR-28/106's trim.

Naming convention: `test_fr<NNN>_<what the bullet says>`. Each FR-107 test quotes its bullet in
the docstring so a reader can check the assertion against the requirement without leaving the
file. Fixtures live here (not in `conftest.py`) because nothing else needs them yet.

**FR-107's LLM bullets post-pivot (v2.0.0, folded in by T3.5).** The style-brief `analysis_call`
line is withdrawn with the vision stage that produced it (D41) — no LLM is asked what a trend
looks like any more — and the `analysis` ROLE survives as the VISION CHECK's role, priced through
`_check_price` (FR-27/FR-105). In its place FR-107 gained a first bullet: one batched
`filter_call` for the competitor screen (FR-294), priced pre-Collect at the worst-case bound
`len(monitors) x virlo_topics_per_monitor`. `siblings_of()` is keyed off asset ids rather than
`pair_id` — A/B mode is withdrawn, so every creative has its own CopySet.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from hypesocials import budget
from hypesocials.budget import Budget, Estimate, SpendCategory, estimate, format_usd, trim
from hypesocials.config import Config, PlatformConfig
from hypesocials.models import PlanEntry, PlanEntryStatus

# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def cfg() -> Config:
    """A config whose every value came from a file (so provenance reads `<file>.yaml`)."""
    return Config(name="test", path=Path("configs/test.yaml"))


def entry(order: int, fmt: str = "image", **kwargs: object) -> PlanEntry:
    """One plan entry with sane defaults; `kwargs` override any `PlanEntry` field."""
    fields: dict[str, object] = {
        "order": order,
        "asset_id": f"a{order}",
        "creative_format": fmt,
        "platform": "linkedin",
        "language": "en",
        "aspect_ratio": "9:16" if fmt == "reel" else "4:5",
    }
    fields.update(kwargs)
    return PlanEntry(**fields)  # type: ignore[arg-type]


def priced_reels(cfg: Config, usd_per_second: float = 0.19) -> Config:
    """Enter a real per-second reel rate — the one thing that unblocks reel planning (FR-131)."""
    cfg.models.price_per_unit.reel_second[cfg.run.reel_resolution] = usd_per_second
    return cfg


def lines(est: Estimate, code: str) -> list[budget.EstimateLine]:
    return [line for line in est.lines if line.code == code]


def one(est: Estimate, code: str) -> budget.EstimateLine:
    found = lines(est, code)
    assert len(found) == 1, f"expected exactly one {code} line, got {len(found)}"
    return found[0]


# --------------------------------------------------------------------------- FR-107 bullets


def test_fr107_vision_check_calls(cfg: Config) -> None:
    """"vision-check calls when `vision_check` is on" — and none at all when it is off.

    The off case is set EXPLICITLY since 2026-08-13: `vision_check` defaults to `True` now, so a
    plan that never touches the key is the ON case, not the OFF one.
    """
    cfg.run.vision_check = False
    plan = [entry(0), entry(1)]
    assert lines(estimate(cfg, plan), "vision_check") == []

    cfg.run.vision_check = True
    est = estimate(cfg, [entry(0), entry(1)])
    checks = lines(est, "vision_check")
    assert len(checks) == 2
    assert all(check.category is SpendCategory.LLM and check.quantity == 1 for check in checks)
    assert all(check.assumed_model == cfg.models.analysis for check in checks)


def test_fr107_carousel_is_one_vision_call_priced_with_every_slides_image_tokens(
    cfg: Config,
) -> None:
    """"A carousel is one multi-image call for the whole deck (FR-105), not one call per slide —
    but that call is priced with the vision image tokens of every slide it carries"."""
    cfg.run.vision_check = True
    cfg.run.carousel_anchor = False

    cfg.platforms["linkedin"] = PlatformConfig(formats=["carousel"], carousel_slides=3)
    small = one(estimate(cfg, [entry(0, "carousel")]), "vision_check")
    cfg.platforms["linkedin"] = PlatformConfig(formats=["carousel"], carousel_slides=8)
    big = one(estimate(cfg, [entry(0, "carousel")]), "vision_check")

    assert small.quantity == big.quantity == 1  # one call, whatever the deck size
    assert big.unit_price is not None and small.unit_price is not None
    assert big.unit_price > small.unit_price  # ... priced with all eight slides' image tokens


def test_fr107_carousel_anchor_adds_a_second_vision_call(cfg: Config) -> None:
    """"Where `carousel_anchor` is on, the deck also costs a **second** call for the anchor check
    of slide 1"."""
    cfg.run.vision_check = True
    cfg.run.carousel_anchor = True
    est = estimate(cfg, [entry(0, "carousel")])
    assert len(lines(est, "vision_check")) == 1
    anchor = one(est, "vision_check_anchor")
    assert anchor.category is SpendCategory.LLM and anchor.quantity == 1

    cfg.run.carousel_anchor = False
    assert lines(estimate(cfg, [entry(0, "carousel")]), "vision_check_anchor") == []


def test_fr107_seed_frame_renders_and_their_vision_checks(cfg: Config) -> None:
    """"seed-frame image renders for every reel under `reel_overlay_text: seed_frame`, plus a
    vision check per seed frame when `vision_check` is on (FR-105)"."""
    priced_reels(cfg)
    cfg.run.vision_check = True
    cfg.run.reel_overlay_text = "seed_frame"
    est = estimate(cfg, [entry(0, "reel", platform="tiktok")])
    seed = one(est, "reel_seed_frame")
    assert seed.quantity == 1 and seed.unit_price == cfg.models.price_per_unit.image["1k"]
    assert one(est, "vision_check").quantity == 1

    cfg.run.reel_overlay_text = "none"
    without = estimate(cfg, [entry(0, "reel", platform="tiktok")])
    assert lines(without, "reel_seed_frame") == [] and lines(without, "vision_check") == []


def test_fr107_compound_retry_allowance(cfg: Config) -> None:
    """"a retry allowance covering the worst-case **compound** per checked asset: **one moderation
    retry (FR-97) plus one vision-check re-render (FR-105)** ... sized for both rather than for
    whichever is larger"."""
    cfg.run.vision_check = True
    est = estimate(cfg, [entry(0)])
    moderation = one(est, "moderation_retry_allowance")
    vision = one(est, "vision_retry_allowance")

    assert moderation.allowance and vision.allowance
    # Compound, not max: the worst case carries BOTH amounts, and neither is expected spend.
    assert est.worst_case_usd - est.expected_usd >= moderation.amount_usd + vision.amount_usd
    assert all(line.code != "vision_retry_allowance" or line.allowance for line in est.lines)
    expected_codes = {line.code for line in est.lines if not line.allowance}
    assert "moderation_retry_allowance" not in expected_codes


def test_fr107_carousel_anchor_failure_contingency(cfg: Config) -> None:
    """"When slide 1 fails, the deck falls back to independent generation of all N slides ... A
    carousel's worst case is therefore **N + 1 renders**, and the estimate carries that
    contingency"."""
    cfg.run.carousel_anchor = True
    est = estimate(cfg, [entry(0, "carousel")])
    slides = one(est, "carousel_slides")
    contingency = one(est, "anchor_contingency_allowance")

    assert slides.quantity == cfg.platform("linkedin").carousel_slides
    assert contingency.quantity == 1 and contingency.allowance
    assert contingency.unit_price == slides.unit_price  # the N+1th render, at the same tier

    cfg.run.carousel_anchor = False
    assert lines(estimate(cfg, [entry(0, "carousel")]), "anchor_contingency_allowance") == []


def test_fr107_vision_check_image_tokens_are_priced_at_native_render_resolution(
    cfg: Config,
) -> None:
    """"**vision image tokens** — **vision-check calls priced at native render resolution**"
    (FR-107 as amended v2.0.0).

    The bullet names the CHECK alone now. Its pre-pivot twin asserted that the style-brief
    analysis line stayed flat across resolution tiers because FR-93 downscaled its images to
    ~1024 px before sending them; that line, that downscale and the whole vision-analysis stage
    are withdrawn (D41/FR-128), and the check has NEVER downscaled — it reads the render we just
    paid for, at the size we paid for it. So the tier moves this price, and must.
    """
    cfg.run.vision_check = True

    def at_tier(tier: str) -> float:
        cfg.platforms["linkedin"] = SimpleNamespace(  # type: ignore[assignment]
            carousel_slides=5, image_resolution=tier)
        check = one(estimate(cfg, [entry(0, trend_key="t1")]), "vision_check").unit_price
        assert check is not None
        return check

    assert at_tier("2k") > at_tier("1k")  # check images are native — the tier moves the price


def test_fr107_reasoning_token_allowance_scales_with_effort(cfg: Config) -> None:
    """"a **reasoning-token allowance for every Luna copy call** ... the allowance scales with the
    configured reasoning-effort setting for the copy role" (RESULTS.md §E: 0 at `low`, ~32 % of
    completion at `medium`)."""
    plan = [entry(0, trend_key="t1")]
    cfg.models.reasoning_effort = "low"
    low = one(estimate(cfg, plan), "copy_call").unit_price
    cfg.models.reasoning_effort = "medium"
    medium = one(estimate(cfg, plan), "copy_call").unit_price
    cfg.models.reasoning_effort = "high"
    high = one(estimate(cfg, plan), "copy_call").unit_price

    assert low is not None and medium is not None and high is not None
    assert low < medium < high
    rate = cfg.models.price_per_unit.llm["luna"]["reasoning_per_mtok"]
    expected_medium_extra = cfg.max_tokens_for("copy") * 0.32 / 1_000_000 * rate
    assert medium - low == pytest.approx(expected_medium_extra, rel=1e-6)


def test_fr107_split_per_creative_copy_calls(cfg: Config) -> None:
    """"It also covers the **split per-creative copy calls** of FR-99, which are a real
    conditional contributor"."""
    plan = [entry(0, trend_key="t1"), entry(1, trend_key="t1"), entry(2, trend_key="t2")]
    est = estimate(cfg, plan)
    assert len(lines(est, "copy_call")) == 2  # one grouped call per (trend x language)
    split = one(est, "copy_split_allowance")
    assert split.allowance and split.quantity == 3  # worst case: one call per creative
    assert split.category is SpendCategory.LLM


def test_fr107_topic_filter_screen_is_one_call_priced_at_the_worst_case_topic_bound(
    cfg: Config,
) -> None:
    """FR-107 (v2.0.0), first bullet: "**Topic filter call** — one batched LLM screen of all
    candidate topics at the worst-case bound `len(monitors) x virlo_topics_per_monitor x
    per-topic-tokens` priced pre-Collect".

    The bound is deliberately the CONFIG's, not the plan's: the screen is priced before Collect,
    so the only honest number is the most Virlo could hand back. A monitor that answers with three
    topics simply costs less than the line said, which is the safe direction (D11); understating
    is the one unacceptable estimator error.
    """
    cfg.sources.virlo_monitor_ids = ["m1", "m2"]
    plan = [entry(0, trend_key="t1")]

    est = estimate(cfg, plan)
    screen = one(est, "filter_call")
    assert screen.category is SpendCategory.LLM and screen.unit == "call"
    assert screen.quantity == 1  # ONE batched call, whatever the pool size
    assert screen.assumed_model == cfg.models.copy  # role `copy` — Luna prices it (§1.5)
    assert "18 topics" in screen.label  # 2 monitors x the default 9 topics per monitor
    assert one(est, "filter_retry_allowance").allowance  # FR-127 + FR-41, worst case only

    # The bound is the config's, not the plan's: more monitors is a bigger prompt, same one call.
    cfg.sources.virlo_topics_per_monitor = 3
    cheaper = one(estimate(cfg, plan), "filter_call")
    assert cheaper.quantity == 1 and cheaper.unit_price is not None
    assert screen.unit_price is not None and cheaper.unit_price < screen.unit_price

    # -1 is the kill switch (one topic per monitor), never "no topics at all".
    cfg.sources.virlo_topics_per_monitor = -1
    assert "2 topics" in one(estimate(cfg, plan), "filter_call").label


def test_no_monitors_and_brief_only_plans_are_never_charged_for_a_screen(cfg: Config) -> None:
    """Nothing is screened when nothing is collected: an unconfigured Virlo (no monitor ids) and a
    plan of `override` briefs both open no Virlo session at all (FR-144), so a filter line there
    would be money the run cannot spend."""
    trend_backed = [entry(0, trend_key="t1")]
    assert lines(estimate(cfg, trend_backed), "filter_call") == []  # no monitor ids configured

    cfg.sources.virlo_monitor_ids = ["m1"]
    briefs_only = [entry(0, brief_name="ai-audit-cta", brief_influence="override")]
    assert lines(estimate(cfg, briefs_only), "filter_call") == []
    assert lines(estimate(cfg, trend_backed), "filter_call")  # the fixture is not failing


def test_fr107_per_platform_resolution(cfg: Config) -> None:
    """"**per-platform resolution**, since price scales with output size"."""
    cfg.platforms["linkedin"] = SimpleNamespace(  # type: ignore[assignment]
        carousel_slides=5, image_resolution="1k")
    cfg.platforms["instagram"] = SimpleNamespace(  # type: ignore[assignment]
        carousel_slides=5, image_resolution="4k")
    est = estimate(cfg, [entry(0, platform="linkedin"), entry(1, platform="instagram")])
    cheap, dear = lines(est, "image_render")

    assert (cheap.unit_price, cheap.price_key) == (0.03, "models.price_per_unit.image.1k")
    assert (dear.unit_price, dear.price_key) == (0.08, "models.price_per_unit.image.4k")
    assert est.per_entry_usd[1] > est.per_entry_usd[0]


def test_fr107_carousel_slides_at_each_entrys_own_deck_length(cfg: Config) -> None:
    """"carousel slides (deck length from Virlo `panel_count` at ASSIGN per FR-95, clamped to
    platform ceiling)" — FR-107 as amended v2.1.0.

    Each deck is priced at ITS OWN length now, not at one flat number for the whole plan: a
    three-panel source and a nine-panel source in the same run cost three and six renders under a
    hard max of six. The platform max is still the bound (FR-257) — it caps a deck and never sets
    one; an entry with no `slide_count` at all falls back to it as a last resort.
    """
    cfg.platforms["linkedin"] = PlatformConfig(formats=["carousel"], carousel_slides=6)
    assert one(estimate(cfg, [entry(0, "carousel")]), "carousel_slides").quantity == 6
    assert one(estimate(cfg, [entry(0, "carousel", slide_count=4)]),
               "carousel_slides").quantity == 4
    # A source may never raise the deck above the configured ceiling.
    assert one(estimate(cfg, [entry(0, "carousel", slide_count=99)]),
               "carousel_slides").quantity == 6

    # Per-entry, not per-plan: two decks of different lengths are two differently priced lines.
    mixed = estimate(cfg, [entry(0, "carousel", slide_count=3),
                           entry(1, "carousel", slide_count=9)])
    short, long = lines(mixed, "carousel_slides")
    assert (short.quantity, long.quantity) == (3, 6)
    assert mixed.per_entry_usd[1] > mixed.per_entry_usd[0]


def test_two_bound_decks_of_different_lengths_get_different_estimated_costs(cfg: Config) -> None:
    """Regression for the audit of run 20260813_143420_oyo4: every carousel in that run carried
    the SAME `estimated_cost_usd` (0.196541) because every deck was the same flat 5 slides.

    With `carousel_slides` demoted to a platform hard max (2026-08-13), deck length comes from the
    bound post's panels, so identical per-entry costs across a plan of differing decks is now a
    symptom — the length never reached the estimator. This pins the number `estimate()` stamps
    back onto the entries, not just the lines it returns, because `meta.yaml`, the console plan
    table and the trim-to-cap arithmetic all read the entry field.
    """
    cfg.platforms["linkedin"] = PlatformConfig(formats=["carousel"], carousel_slides=20)
    short, tall = bound(0, "post-a", slides=3), bound(1, "post-b", slides=12)

    est = estimate(cfg, [short, tall])

    assert [line.quantity for line in lines(est, "carousel_slides")] == [3, 12]
    assert short.estimated_cost_usd > 0 and tall.estimated_cost_usd > short.estimated_cost_usd, \
        "a deck four times as long cannot cost the same as its sibling"
    assert est.per_entry_usd == {0: short.estimated_cost_usd, 1: tall.estimated_cost_usd}


# ------------------------------------------------- FR-306 slide intelligence (D46 §0.11)


def bound(order: int, post: str, slides: int = 4, **kwargs: object) -> PlanEntry:
    """A carousel as `plan.assign()` leaves it: a bound source post and a real deck length."""
    return entry(order, "carousel", source_post_id=post, slide_count=slides,
                 trend_key="t1", **kwargs)


def test_fr306_one_slide_intelligence_call_per_bound_carousel_source_post(cfg: Config) -> None:
    """§0.11: vision runs for every assigned carousel source post, ONE analysis-role call each,
    after the Confirm gate — so the estimate has to quote it BEFORE the gate (rule 7)."""
    est = estimate(cfg, [bound(0, "post-a", 3), bound(1, "post-b", 5)])
    first, second = lines(est, "slide_intel")

    assert first.category is SpendCategory.LLM and first.unit == "call"
    assert (first.quantity, second.quantity) == (1, 1)
    assert first.assumed_model == cfg.models.analysis  # the `analysis` role — Sonnet prices it
    assert first.price_key == "models.price_per_unit.llm.sonnet"
    assert "3 source slides" in first.label and "post post-a" in first.label
    assert second.unit_price is not None and first.unit_price is not None
    assert second.unit_price > first.unit_price, "five slides is five image blocks, not three"
    assert not first.allowance and first.amount_usd > 0
    assert one(est, "slide_intel_retry_allowance").allowance  # FR-127 + FR-41, worst case only
    assert est.per_entry_usd[0] > 0


def test_fr306_two_siblings_on_one_source_post_are_analysed_once(cfg: Config) -> None:
    """`slide_intel.enrich` deduplicates by post id, so pricing two calls for one post would
    over-quote the commonest run shape — and the one line is attributed to BOTH entries."""
    est = estimate(cfg, [bound(0, "post-a"), bound(1, "post-a"), bound(2, "post-b")])
    intel = lines(est, "slide_intel")

    assert len(intel) == 2
    assert {line.entry_orders for line in intel} == {(0, 1), (2,)}
    assert one(est, "slide_intel_retry_allowance").quantity == 4  # 2 retries x 2 posts


def test_fr306_no_line_when_vision_is_off_or_no_carousel_can_be_analysed(cfg: Config) -> None:
    """$0 spend is $0 line. A line quoting a call that will not happen reads as a rate that failed
    to load, and the two no-call shapes are the switch off (§0.6) and a plan with no analysable
    carousel in it — an image plan, or a carousel owned outright by an override brief (§0.14d)."""
    assert lines(estimate(cfg, [bound(0, "post-a")]), "slide_intel"), "the fixture must bind one"

    cfg.sources.vision_transcribe = False
    off = estimate(cfg, [bound(0, "post-a")])
    assert lines(off, "slide_intel") == [] and lines(off, "slide_intel_retry_allowance") == []

    cfg.sources.vision_transcribe = True
    assert lines(estimate(cfg, [entry(0, "image"), entry(1, "image")]), "slide_intel") == []
    brief = estimate(cfg, [bound(0, "post-a", brief_name="cta", brief_influence="override")])
    assert lines(brief, "slide_intel") == []


def test_fr306_an_unbound_carousel_is_still_quoted_at_the_worst_case(cfg: Config) -> None:
    """The Confirm gate currently runs ahead of Collect, so the plan it prices has no bound post
    yet — and a line that appeared only AFTER the gate would be spend the operator never approved.

    Worst-case-honest, exactly like `runner._stamp_provisional`'s topic keys: one source post per
    deck, at the platform ceiling. Assignment can only make it cheaper.
    """
    cfg.platforms["linkedin"] = PlatformConfig(formats=["carousel"], carousel_slides=6)
    provisional = estimate(cfg, [entry(0, "carousel"), entry(1, "carousel")])
    quoted = lines(provisional, "slide_intel")

    assert len(quoted) == 2, "two decks could genuinely be two distinct source posts"
    assert "worst case: one source post per deck" in quoted[0].label
    assert "6 source slides" in quoted[0].label  # the ceiling, until a panel count replaces it

    # ... and every way assignment can resolve it costs less than what was approved.
    siblings = estimate(cfg, [bound(0, "post-a", 6), bound(1, "post-a", 6)])
    shorter = estimate(cfg, [bound(0, "post-a", 3), bound(1, "post-b", 4)])
    for settled in (siblings, shorter):
        assert (sum(l.amount_usd for l in lines(settled, "slide_intel"))
                < sum(l.amount_usd for l in quoted))


def test_fr306_slide_intelligence_is_expected_spend_inside_the_confirm_gate(cfg: Config) -> None:
    """It is paid work the run WILL do, not a contingency — so it sits in `expected_usd`, which is
    the number FR-106a gates the batch on, and it moves the operator's total."""
    plan = [bound(0, "post-a", 4)]
    cfg.sources.vision_transcribe = False
    without = estimate(cfg, plan)
    cfg.sources.vision_transcribe = True
    with_intel = estimate(cfg, plan)

    intel = one(with_intel, "slide_intel")
    assert with_intel.expected_usd == pytest.approx(without.expected_usd + intel.amount_usd)
    assert intel.category is SpendCategory.LLM and not intel.allowance


def test_fr107_reels_priced_per_second_at_the_configured_resolution(cfg: Config) -> None:
    """"**reels priced as `price_per_unit.reel_second` x the configured duration in seconds, at
    the configured `reel_resolution`** — duration is a per-second cost lever, not a flat fee, and
    the resolution used for pricing is whatever config says, never a hardcoded 720p"."""
    cfg.models.price_per_unit.reel_second["480p"] = 0.085
    cfg.models.price_per_unit.reel_second["720p"] = 0.190
    cfg.run.reel_overlay_text = "none"
    cfg.run.reel_duration_s = 8

    cfg.run.reel_resolution = "480p"
    cheap = one(estimate(cfg, [entry(0, "reel", platform="tiktok")]), "reel_clip")
    cfg.run.reel_resolution = "720p"
    dear = one(estimate(cfg, [entry(0, "reel", platform="tiktok")]), "reel_clip")

    assert cheap.quantity == dear.quantity == 8 and cheap.unit == "second"
    assert cheap.amount_usd == pytest.approx(0.085 * 8)
    assert dear.amount_usd == pytest.approx(0.190 * 8)
    assert cheap.price_key == "models.price_per_unit.reel_second.480p"
    assert dear.assumed_model == cfg.models.video


def test_fr107_unpriced_reel_refuses_planning_and_names_the_key(cfg: Config) -> None:
    """"the estimate consequently **refuses to plan reels at all while it is unset** ... An
    unpriced format is an unbounded format" (FR-131). Reels ship unpriced by operator decision."""
    assert cfg.reel_price_per_second is None  # the shipped state
    cfg.run.vision_check = True
    est = estimate(cfg, [entry(0, "reel", platform="tiktok")])

    clip = one(est, "reel_clip")
    assert clip.unit_price is None and clip.amount_usd == 0.0  # never a guessed price
    assert clip.unpriced and clip.blocking
    assert clip.price_key == "models.price_per_unit.reel_second.720p"
    assert est.blocked == (clip,) and clip.entry_orders == (0,)
    assert clip.price_key in clip.label and "FR-131" in clip.label  # the key is named, not guessed
    # A blocked reel buys nothing else either: no seed frame, no check, no retry allowance.
    assert lines(est, "reel_seed_frame") == lines(est, "vision_check") == []
    assert est.expected_usd == 0.0 and est.per_entry_usd[0] == 0.0


def test_fr107_unpriced_non_reel_line_participates_at_zero_and_says_so(cfg: Config) -> None:
    """"when any rate is unset or zero, that line contributes $0 to the projection, the tally and
    the trim math — and the estimate ... reports **"governance partial — N lines unpriced""."""
    cfg.models.price_per_unit.image["1k"] = None
    est = estimate(cfg, [entry(0)])
    render = one(est, "image_render")

    assert render.unpriced and render.unit_price is None and render.amount_usd == 0.0
    assert render.price_key == "models.price_per_unit.image.1k"
    assert est.expected_usd > 0  # the LLM lines still price normally
    assert est.banner == f"governance partial — {len(est.unpriced_lines)} lines unpriced"


# ------------------------------------------------- v1.6.5 estimator fidelity fix (M1 finding)


def test_copy_priced_per_distinct_assigned_topic(cfg: Config) -> None:
    """v1.6.5 (00-overview amendment log): M1's actual $0.23 beat its $0.16 worst case partly
    because a per-call line "priced one call while two distinct trends were assigned".

    `plan.assign()` binds a topic per ATOMIC GROUP and prefers the least-used one, so two groups
    can consume two distinct topics whatever `max_trend_reuses_per_run` says — the reuse ceiling
    only ever *reduces* the count when the pool is short. `_stamp_provisional` models exactly that
    worst case before Collect, and the estimate prices one copy call (FR-99) per group off it.

    The `analysis_call` half of this test went with the style-brief stage (D41); what it was
    really guarding — provisional keys are DISTINCT per group, so the grouped-call count is never
    understated — is what the copy assertion carries now.
    """
    from hypesocials.runner import _stamp_provisional  # the pre-Collect half of the same fix

    cfg.run.max_trend_reuses_per_run = 2  # the M1 setting that hid the second topic
    plan = [entry(0), entry(1)]
    _stamp_provisional(plan)

    assert len({e.trend_key for e in plan}) == 2  # one distinct topic per atomic group
    est = estimate(cfg, plan)
    assert len(lines(est, "copy_call")) == 2  # FR-99 groups by (topic x language), same worst case
    assert lines(est, "analysis_call") == [], "the style-brief line is withdrawn (D41)"


def test_siblings_are_counted_by_asset_id_now_that_nothing_pairs(cfg: Config) -> None:
    """`budget.siblings_of()` re-based off `pair_id` (v2.0.0, contracts W2 blocker fix).

    A both-mode pair used to be TWO renders of ONE CopySet, so the copy call's sibling count was
    the number of distinct `pair_id`s. A/B mode is withdrawn (D42): every creative gets its own
    CopySet, so the distinct ASSET IDS are the siblings — and reading `pair_id` here would raise
    `AttributeError` on every `estimate()` the moment the field is excised at W3.5, which is the
    one thing this module may never do to a run.

    Both creatives below share a topic and a language, so FR-99 groups them into ONE call whose
    prompt has to carry two sibling briefs — visibly dearer than the single-sibling call.
    """
    solo = one(estimate(cfg, [entry(0, trend_key="t1")]), "copy_call")
    paired = one(estimate(cfg, [entry(0, trend_key="t1"), entry(1, trend_key="t1")]), "copy_call")

    assert "1 siblings" in solo.label and "2 siblings" in paired.label
    assert solo.unit_price is not None and paired.unit_price is not None
    assert paired.unit_price > solo.unit_price  # one more sibling brief in the same prompt
    # ... and the split allowance (FR-99's per-creative fallback) counts the same siblings.
    assert one(estimate(cfg, [entry(0, trend_key="t1"), entry(1, trend_key="t1")]),
               "copy_split_allowance").quantity == 2


def test_truncation_retry_allowance_in_worst_case_not_expected(cfg: Config) -> None:
    """The other half of the v1.6.5 fix: FR-127's retry re-sends a truncated call WIDER, which
    roughly doubled M1's per-call cost. It is carried as extra full-cost calls per LLM call — in
    `worst_case_usd` only, because FR-106a's expected projection is never gated on a contingency
    that mostly never happens.

    Re-based off the withdrawn `analysis_call` line (D41) onto the copy call, which is the
    surviving grouped LLM call and carries the identical two-wide-calls shape.
    """
    plan = [entry(0), entry(1)]
    from hypesocials.runner import _stamp_provisional

    _stamp_provisional(plan)
    est = estimate(cfg, plan)
    copy_call, copy_retry = lines(est, "copy_call")[0], one(est, "copy_retry_allowance")

    assert copy_retry.allowance and copy_retry.category is SpendCategory.LLM
    assert copy_retry.quantity == 2 * len(lines(est, "copy_call"))  # FR-127's retry AND FR-41's
    assert copy_retry.unit_price is not None and copy_call.unit_price is not None
    assert copy_retry.unit_price > copy_call.unit_price  # ... each at FR-127's widened token cap
    # Worst case carries them; expected does not, and no entry's share is inflated by an allowance.
    assert est.worst_case_usd - est.expected_usd >= copy_retry.amount_usd
    bare = round(sum(l.amount_usd for l in est.lines if not l.allowance), 6)
    assert est.expected_usd == pytest.approx(bare)


def test_every_llm_role_carries_the_same_compound_retry_bound(cfg: Config) -> None:
    """FR-127's widened truncation retry and FR-41's parse retry are INDEPENDENT, each capped at
    one, and one call can spend both (`llm._run_attempts`) — so every LLM role carries an
    allowance of exactly two wide calls per call it makes, never `max(...)` of the two.

    This replaces the pre-pivot `analysis_call` version of the bound, deleted with the style-brief
    stage (D41). Both surviving roles are asserted in one place so a new role cannot quietly ship
    with a cheaper allowance than the code will actually spend: the filter is one batched call
    (2 retries), copy is one call per FR-99 group (2 per group).
    """
    cfg.sources.virlo_monitor_ids = ["m1", "m2"]
    est = estimate(cfg, [entry(0, trend_key="t1"), entry(1, trend_key="t2")])

    for call_code, retry_code, expected in (("filter_call", "filter_retry_allowance", 2),
                                            ("copy_call", "copy_retry_allowance", 4)):
        call, retry = lines(est, call_code)[0], one(est, retry_code)
        assert retry.allowance and retry.category is SpendCategory.LLM, retry_code
        assert retry.quantity == expected, retry_code
        assert retry.unit_price is not None and call.unit_price is not None
        assert retry.unit_price > call.unit_price, retry_code  # priced at the widened cap
        assert retry.amount_usd == pytest.approx(retry.unit_price * expected), retry_code


def test_job_projection_is_the_one_per_submission_price(cfg: Config) -> None:
    """`generate`'s metered `submit` is its only caller (FR-106/107): image, slide and seed-frame
    jobs are the platform's image tier; a clip is the per-second rate x the configured duration."""
    image = entry(0)
    reel = entry(1, "reel", platform="tiktok")
    cfg.run.reel_duration_s = 5

    for job in ("image", "slide", "seed_frame"):
        assert budget.job_projection(cfg, image, job) == cfg.models.price_per_unit.image["1k"]
    # Unpriced reels are blocked at PLANNING time (FR-131), so a clip that reaches submission
    # projects $0 rather than a guess — pre-committed work still goes out (FR-106b).
    assert cfg.reel_price_per_second is None
    assert budget.job_projection(cfg, reel, "clip") == 0.0

    # `configs/hypedigitaly.yaml`'s shipped 720p scalar, re-based at v2.0.0: 63 credits/s x $0.005
    # = $0.315 per OUTPUT second. The old 0.950/0.425 pair priced Seedance's with-a-video-reference
    # branch, which the pivot made unreachable — no motion reference is attached any more (D44) —
    # and overstating a reel ~3x silently trimmed creatives out of plans that would have fitted.
    priced_reels(cfg, 0.315)
    assert budget.job_projection(cfg, reel, "clip") == pytest.approx(1.575)  # a 5 s reel


def test_nfr18_estimate_is_computed_from_local_config_only(cfg: Config) -> None:
    """NFR-18: "using only local config values (no network call), so the estimate appears before
    any external service is contacted"."""
    source = Path(budget.__file__).read_text(encoding="utf-8")
    assert "httpx" not in source and "urllib" not in source and "requests" not in source
    assert not asyncio.iscoroutinefunction(estimate)
    est = estimate(cfg, [entry(0), entry(1, "carousel")])
    assert est.expected_usd > 0


# --------------------------------------------------------------------------- FR-282 provenance


def test_fr282_every_priced_line_carries_key_origin_and_assumed_model(cfg: Config) -> None:
    """FR-282: "The pre-flight cost summary SHALL print, for every priced line, which configured
    model that price is being assumed for"."""
    cfg.run.vision_check = True
    est = estimate(cfg, [entry(0, trend_key="t1"), entry(1, "carousel", trend_key="t1")])
    assert est.lines
    for line in est.lines:
        assert line.price_key and line.price_origin and line.assumed_model
        assert line.price_key.startswith("models.price_per_unit.")
    assert one(est, "image_render").assumed_model == cfg.models.image
    # The `analysis_call` row went with the style-brief stage (D41). The `analysis` ROLE did not:
    # it is the vision check's role now, which is exactly what these lines price (FR-27/FR-105),
    # so `models.analysis` and `max_tokens.analysis` keep meaning something and keep being named.
    assert all(check.assumed_model == cfg.models.analysis
               for check in lines(est, "vision_check"))
    assert one(est, "copy_call").assumed_model == cfg.models.copy


def test_fr282_origin_says_built_in_default_when_the_file_omitted_the_key() -> None:
    """A rate that fell back at load time must not claim to have come from the config file."""
    from_file = Config(path=Path("configs/mine.yaml"))
    defaulted = Config(path=Path("configs/mine.yaml"),
                       defaults_applied=("models.price_per_unit",))
    assert one(estimate(from_file, [entry(0)]), "image_render").price_origin == "mine.yaml"
    assert one(estimate(defaulted, [entry(0)]), "image_render").price_origin == "built-in default"


def test_fr282_swapped_model_keeps_its_predecessors_price_and_says_so(cfg: Config) -> None:
    """FR-282: prices "SHALL NOT be cleared, renamed, or auto-adjusted when a model is swapped;
    the estimator SHALL continue using the values present in config"."""
    cfg.models.image = "some-new-image-route"
    render = one(estimate(cfg, [entry(0)]), "image_render")
    assert render.unit_price == 0.03  # yesterday's rate, unchanged
    assert render.assumed_model == "some-new-image-route"  # ... and visibly assumed for the new id


def test_fr282_unset_llm_rate_prints_unpriced_and_contributes_zero(cfg: Config) -> None:
    """An unset LLM rate is reported, never silently treated as free."""
    cfg.models.price_per_unit.llm["luna"]["output_per_mtok"] = 0.0
    est = estimate(cfg, [entry(0, trend_key="t1")])
    copy_line = one(est, "copy_call")
    assert copy_line.unpriced and copy_line.amount_usd == 0.0 and copy_line.unit_price is None
    assert copy_line in est.unpriced_lines and "unpriced" in est.banner


def test_unknown_price_tier_is_unpriced_rather_than_silently_retiered(cfg: Config) -> None:
    """A tier with no entry in the price table names the missing key instead of guessing 1k."""
    cfg.platforms["linkedin"] = SimpleNamespace(  # type: ignore[assignment]
        carousel_slides=5, image_resolution="8k")
    render = one(estimate(cfg, [entry(0)]), "image_render")
    assert render.unpriced and render.price_key == "models.price_per_unit.image.8k"


# --------------------------------------------------------------------------- FR-28/106 trimming


def _mixed_plan() -> list[PlanEntry]:
    """Brief entries first (FR-1), then a two-entry trim unit, then a carousel — plan order is the
    trim order, reversed.

    The two-entry group used to be a both-mode A/B pair, which is withdrawn (v2.0.0): `plan._emit`
    puts exactly one entry in a group today. The fixture builds one by hand anyway, because FR-106
    is written in terms of the GROUP and not the entry — `budget.trim` must be unable to take half
    a unit whatever a future format puts inside one, and a carousel is already an atomic creative
    whose slides may never be split (D31).
    """
    return [
        entry(0, brief_name="ai-audit-cta", atomic_group="brief-ai-audit-cta"),
        entry(1, trend_key="t1"),
        entry(2, trend_key="t2", atomic_group="unit-a2"),
        entry(3, trend_key="t2", atomic_group="unit-a2"),
        entry(4, "carousel", trend_key="t3", atomic_group="deck-a4"),
    ]


def test_fr106_trim_removes_whole_groups_from_the_end_in_reverse_plan_order(cfg: Config) -> None:
    """FR-106: "entries are removed from the end of the plan, in reverse plan order" — a carousel
    and a multi-entry group are one unit each, and brief creatives are trimmed last."""
    survivors_only = estimate(cfg, [entry(0, brief_name="ai-audit-cta"), entry(1, trend_key="t1")])
    plan = _mixed_plan()

    result = trim(cfg, plan, cap_usd=survivors_only.expected_usd)

    assert [e.asset_id for e in result.kept] == ["a0", "a1"]  # the brief entry survives
    assert [d.order for d in result.trimmed] == [4, 2, 3]  # deck first, then the whole unit
    assert {d.atomic_group for d in result.trimmed} == {"deck-a4", "unit-a2"}
    assert result.fits and result.estimate.expected_usd <= result.cap_usd
    assert result.original_estimate_usd > result.cap_usd


def test_fr106_atomic_groups_are_never_split_by_a_trim(cfg: Config) -> None:
    """One trim unit goes whole or stays whole — trimming may never take half of it."""
    # A cap that leaves room for the deck-less plan minus a hair reaches INTO the two-entry unit:
    # one half would fit, so a per-entry trim would split it. Both halves must go.
    without_deck = estimate(cfg, _mixed_plan()[:4]).expected_usd
    result = trim(cfg, _mixed_plan(), cap_usd=without_deck - 0.001)

    assert len([d for d in result.trimmed if d.atomic_group == "unit-a2"]) == 2
    assert not any(e.atomic_group == "unit-a2" for e in result.kept)
    assert [e.asset_id for e in result.kept] == ["a0", "a1"]


def test_fr106_every_trim_decision_carries_its_estimated_cost_and_marks_the_entry(
    cfg: Config,
) -> None:
    """FR-106: "Every trimmed entry is logged individually with its reason and its estimated
    cost"; FR-4 keeps it in the plan as `skipped_budget`."""
    plan = _mixed_plan()
    result = trim(cfg, plan, cap_usd=0.05)

    assert result.trimmed
    for trimmed in result.trimmed:
        assert trimmed.estimated_cost_usd > 0
        assert trimmed.status is PlanEntryStatus.SKIPPED_BUDGET
        assert trimmed.skip_reason and "spend cap" in trimmed.skip_reason
        assert trimmed in plan  # FR-4: nothing ever leaves the plan
    assert format_usd(result.cap_usd) in result.summary_line


def test_fr28_trim_is_deterministic(cfg: Config) -> None:
    """"Deterministic means two identical over-budget runs trim identically"."""
    first = trim(cfg, _mixed_plan(), cap_usd=0.12)
    second = trim(cfg, _mixed_plan(), cap_usd=0.12)
    assert [d.order for d in first.trimmed] == [d.order for d in second.trimmed]
    assert [e.asset_id for e in first.kept] == [e.asset_id for e in second.kept]


def test_fr28_a_cap_nothing_fits_under_reports_that_trimming_cannot_help(cfg: Config) -> None:
    """"A `--yes` run only refuses outright when trimming cannot help ... a cap so low that
    nothing at all fits"."""
    result = trim(cfg, _mixed_plan(), cap_usd=0.0001)
    assert result.kept == () and not result.fits


def test_trim_leaves_a_plan_that_already_fits_untouched(cfg: Config) -> None:
    plan = _mixed_plan()
    result = trim(cfg, plan, cap_usd=100.0)
    assert result.trimmed == () and len(result.kept) == len(plan) and result.fits


# --------------------------------------------------------------------------- FR-106 reservations


async def test_reservation_race_concurrent_reserves_never_jointly_exceed_cap() -> None:
    """FR-106c: "a dozen vision retries all reading "$1.40 remaining" at once would all conclude
    they fit, and would jointly spend $6. The reservation makes the decision and the debit one
    indivisible step" — N concurrent attempts, exactly the affordable number granted."""
    cap = Budget(1.00)
    attempts = [cap.reserve(0.10, label=f"vision retry {i}") for i in range(40)]
    granted = await asyncio.wait_for(asyncio.gather(*attempts), timeout=5)  # no deadlock

    assert sum(1 for reservation in granted if reservation is not None) == 10
    assert cap.remaining_usd == 0.0  # exactly the cap claimed, never a cent more
    assert not cap.fits(0.000001)


async def test_fr106c_reserve_release_and_reconcile_track_the_remainder() -> None:
    """A reservation that never reached the provider is released; one that did reconciles to the
    provider's own figure, "so the remainder tracks reality instead of drifting on estimates"."""
    cap = Budget(1.00)
    never_sent = await cap.reserve(0.30, label="submission that failed to leave")
    sent = await cap.reserve(0.30, label="vision re-render")
    assert never_sent is not None and sent is not None
    assert cap.remaining_usd == pytest.approx(0.40)

    await cap.release(never_sent)
    assert cap.remaining_usd == pytest.approx(0.70)

    await cap.reconcile(sent, 0.05)  # Kie billed less than the estimate held
    assert cap.spent_usd == pytest.approx(0.05)
    assert cap.remaining_usd == pytest.approx(0.95)
    await cap.reconcile(sent, 0.05)  # idempotent: a second terminal report changes nothing
    assert cap.spent_usd == pytest.approx(0.05)


async def test_fr106a_projection_gates_wave_one_at_expected_cost() -> None:
    """FR-106a: "Wave 1 is released only if that projection fits"."""
    cap = Budget(0.50)
    assert cap.fits(0.50) and not cap.fits(0.51)
    await cap.commit(0.20, label="wave-1 images", kind="projected")
    assert cap.fits(0.30) and not cap.fits(0.31)


async def test_fr106b_precommitted_wave_two_submits_even_over_cap() -> None:
    """FR-106b: pre-committed wave-2 work "always submit[s] once its prerequisite completes,
    regardless of the interim cap state" — cap bookkeeping never splits a deck."""
    cap = Budget(0.10)
    await cap.commit(0.09, label="anchor slide", kind="projected")
    assert await cap.reserve(0.09, label="discretionary retry") is None  # (c) is declined

    slides = await cap.commit(0.09, label="slides 2-N")  # (b) is not
    assert slides is not None and cap.remaining_usd < 0
    summary = cap.summary([])
    assert summary.over_cap_usd == pytest.approx(0.08)
    assert "over the" in summary.cap_status


async def test_fr85_missing_provider_billing_data_keeps_the_estimate(cfg: Config) -> None:
    """FR-85: "Unknown costs (where provider did not return billing data) are marked estimated"."""
    cap = Budget(1.00)
    held = await cap.commit(0.03, label="image render", asset_id="a0")
    await cap.reconcile(held, None)

    assert held.estimated_only and held.actual_usd is None
    assert cap.spent_usd == pytest.approx(0.03)
    row = cap.summary([entry(0)]).rows[0]
    assert row.estimated_only and row.billed_usd == pytest.approx(0.03)


async def test_fr84_summary_tallies_billed_attempts_on_submission(cfg: Config) -> None:
    """FR-84: one row per creative with estimated vs billed-attempts (failures included) vs
    delivered, subtotals per format and a grand total split LLM vs render."""
    plan = [entry(0), entry(1, "carousel")]
    est = estimate(cfg, plan)
    cap = Budget(1.00)
    failed = await cap.commit(0.03, label="image render", asset_id="a0")
    await cap.reconcile(failed, 0.03)  # submitted, then failed — the spend still counts
    deck = await cap.commit(0.15, label="carousel slides", asset_id="a1")
    await cap.reconcile(deck, 0.15)
    await cap.reconcile(
        await cap.commit(0.002, label="copy call", category=SpendCategory.LLM, asset_id="a1"),
        0.002)
    plan[1].status = PlanEntryStatus.SUCCESS

    summary = cap.summary(plan, est)
    assert summary.headline == "requested 2 creatives, delivered 1"
    image_row, deck_row = summary.rows
    assert image_row.billed_usd == pytest.approx(0.03) and not image_row.delivered
    assert deck_row.delivered and deck_row.billed_usd == pytest.approx(0.152)
    assert summary.by_format == {"image": pytest.approx(0.03), "carousel": pytest.approx(0.152)}
    assert summary.render_usd == pytest.approx(0.18)
    assert summary.llm_usd == pytest.approx(0.002)
    assert summary.total_usd == pytest.approx(0.182)
    assert summary.banner == est.banner and "within the" in summary.cap_status


async def test_fr321_a_deck_that_shipped_short_carries_both_counts_and_is_called_partial(
    cfg: Config,
) -> None:
    """FR-321: `delivered` answers "did this creative ship at all", which a 7-of-8 deck answers
    with `True` — `carousel.package()` marks it incomplete rather than failing it, and that is
    correct. It is also how a truncated deck came to read as an unqualified success on the one
    surface the operator scans first.

    So the row carries the pair `carousel.package()` writes (`slide_count` / `slides_ordered`) and
    derives `partial` from it, and the headline names the count. Deriving rather than storing is
    what keeps the headline, the spend table and the closing line from disagreeing about one
    number they all print.
    """
    plan = [entry(0, "carousel"), entry(1, "carousel"), entry(2, "image")]
    for item in plan:
        item.status = PlanEntryStatus.SUCCESS
    cap = Budget(1.00)
    for item in plan:
        await cap.reconcile(await cap.commit(0.15, label="deck", asset_id=item.asset_id), 0.15)
    records = {plan[0].asset_id: SimpleNamespace(slide_count=7, slides_ordered=8),
               plan[1].asset_id: SimpleNamespace(slide_count=6, slides_ordered=6)}

    summary = cap.summary(plan, records=records)

    short, whole, image = summary.rows
    assert (short.slides_delivered, short.slides_ordered) == (7, 8) and short.partial
    assert (whole.slides_delivered, whole.slides_ordered) == (6, 6) and not whole.partial
    assert (image.slides_delivered, image.slides_ordered) == (None, None), \
        "no record, no claim — an image has no deck length to be short of"
    assert not image.partial
    assert summary.partial == 1
    assert summary.headline == "requested 3 creatives, delivered 3 (1 partial)"


async def test_fr321_a_deck_that_failed_outright_is_a_skip_and_never_a_partial(
    cfg: Config,
) -> None:
    """`partial` requires `delivered`. A deck that shipped nothing is a SKIP with its own reason,
    and counting it here as well would report one loss twice in two vocabularies — the closing
    line would say "generated 0 · 1 partial", which is a sentence about nothing."""
    plan = [entry(0, "carousel")]
    plan[0].status = PlanEntryStatus.FAILED
    cap = Budget(1.00)

    summary = cap.summary(
        plan, records={plan[0].asset_id: SimpleNamespace(slide_count=0, slides_ordered=8)})

    assert summary.rows[0].delivered is False and summary.rows[0].partial is False
    assert summary.partial == 0
    assert summary.headline == "requested 1 creatives, delivered 0", "no partial clause at all"


async def test_fr321_a_meta_written_before_the_requirement_existed_makes_no_claim(
    cfg: Config,
) -> None:
    """A record with `slide_count` and no `slides_ordered` was packaged before FR-321.

    Guessing the ordered count from the delivered one would report every old truncated deck as
    complete — precisely the silence this requirement removes — so the pair is read as a pair, and
    a half-present pair claims nothing. The mapping shape is covered too, because `meta.yaml` read
    back off disk is a dict rather than a dataclass.
    """
    plan = [entry(0, "carousel"), entry(1, "carousel")]
    for item in plan:
        item.status = PlanEntryStatus.SUCCESS
    cap = Budget(1.00)

    summary = cap.summary(plan, records={
        plan[0].asset_id: SimpleNamespace(slide_count=7),                 # pre-FR-321 dataclass
        plan[1].asset_id: {"slide_count": 5, "slides_ordered": 8}})       # meta.yaml off disk

    legacy, off_disk = summary.rows
    assert (legacy.slides_delivered, legacy.slides_ordered) == (7, None) and not legacy.partial
    assert (off_disk.slides_delivered, off_disk.slides_ordered) == (5, 8) and off_disk.partial
    assert summary.partial == 1


async def test_skipped_counts_separate_budget_trims_from_other_losses(cfg: Config) -> None:
    """FR-84's closing lines split "skipped by budget" from deadline/other skips."""
    plan = _mixed_plan()
    trim(cfg, plan, cap_usd=0.05)
    plan[0].status = PlanEntryStatus.ABANDONED
    summary = Budget(1.00).summary(plan)
    assert summary.skipped_budget == sum(
        1 for e in plan if e.status is PlanEntryStatus.SKIPPED_BUDGET)
    assert summary.skipped_other == 1


def test_format_usd_rounds_half_up_to_cents() -> None:
    """Guidelines §7: one documented rounding rule, applied once, at display time."""
    assert format_usd(0.005) == "$0.01"
    assert format_usd(0.125) == "$0.13"
    assert format_usd(1.0) == "$1.00"


def test_the_retry_allowance_prices_the_cap_llm_will_actually_ask_for() -> None:
    """`llm._widen` clamps the widened retry at `_output_ceiling` (16,384), which the estimate
    ignored — over-stating every retry-allowance line by ~3,800 output tokens once a role's
    `max_tokens` rose to 12,000. Over-stating is the safe direction (D11), but a number the
    operator reads should be the number the code will spend. Post-pivot the lines this governs
    are the filter's and copy's (D41 withdrew the style-brief one), and both go through
    `budget._widened_cap`, so one parity assertion still covers every role there is.

    Re-homed verbatim from `test_reference_rotation.py` (deleted in the topic-first pivot's W1,
    plan v2.2 blocker fix): the parity assertion below was that file's one test unrelated to
    reference rotation, and `budget.py`'s constants comment names THIS file now.
    """
    from hypesocials.llm import (  # the source of truth these two constants mirror
        _DEFAULT_MAX_OUTPUT_CEILING,
        _TRUNCATION_BUMP_MAX,
        RoleSettings,
        _output_ceiling,
        _widen,
    )

    assert budget._RETRY_TOKEN_BUMP == _TRUNCATION_BUMP_MAX
    assert budget._RETRY_TOKEN_CEILING == _DEFAULT_MAX_OUTPUT_CEILING
    for cap in (600, 2000, 12000, 20000):
        settings = RoleSettings(model="m", max_tokens=cap)
        ceiling = _output_ceiling(settings)
        # `_widen` answers 0 when no wider ask is legal (FR-127 forbids an identical retry); the
        # estimate still has to price FR-41's parse retry, which re-bills at the original cap.
        assert budget._widened_cap(cap) == (_widen(cap, ceiling) or cap)
