"""Budget tests — one named test per FR-107 bullet, plus FR-106's race and FR-28/106's trim.

Naming convention: `test_fr<NNN>_<what the bullet says>`. Each FR-107 test quotes its bullet in
the docstring so a reader can check the assertion against the requirement without leaving the
file. Fixtures live here (not in `conftest.py`) because nothing else needs them yet.

**FR-107's LLM bullets post-pivot (v2.0.0, folded in by T3.5).** The style-brief `analysis_call`
line is withdrawn with the vision stage that produced it (D41) — no LLM is asked what a trend
looks like any more — and the `analysis` ROLE survives as the VISION CHECK's role, priced through
`_check_price` (FR-27/FR-105), and D49 deleted that line too. In its place FR-107 has: one
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


def test_fr326_the_gate_is_quoted_per_creative_and_not_at_all_when_it_is_off(cfg: Config) -> None:
    """v2.2.0/D49: the FR-105 `vision_check` call lines are DELETED with the machinery they
    priced, and the post-render gate is quoted by `gauntlet_critics` instead.

    The off case is set explicitly because `run.gauntlet.enabled` defaults to True: a plan that
    never touches the key is the ON case, not the OFF one. Off means NO gate at all — not a
    fallback to the old single-shot check, which no longer exists in any form.
    """
    cfg.run.gauntlet.enabled = False
    plan = [entry(0), entry(1)]
    assert lines(estimate(cfg, plan), "gauntlet_critics") == []
    assert lines(estimate(cfg, plan), "vision_check") == []  # the retired line, gone for good

    cfg.run.gauntlet.enabled = True
    est = estimate(cfg, [entry(0), entry(1)])
    critics = lines(est, "gauntlet_critics")
    assert len(critics) == 2  # one row per creative, its own frame count
    assert all(row.category is SpendCategory.LLM and row.allowance for row in critics)
    assert all(row.assumed_model == cfg.models.critic for row in critics)


def test_fr326_a_deck_is_one_critic_call_priced_with_every_frame_it_carries(cfg: Config) -> None:
    """One multi-image call per critic per round covers the WHOLE deck (spec §2) — but that call
    is priced with the image tokens of every frame it attaches."""
    cfg.run.gauntlet.enabled = True
    cfg.run.carousel_anchor = False

    cfg.platforms["linkedin"] = PlatformConfig(formats=["carousel"], carousel_slides=3)
    small = one(estimate(cfg, [entry(0, "carousel")]), "gauntlet_critics")
    cfg.platforms["linkedin"] = PlatformConfig(formats=["carousel"], carousel_slides=8)
    big = one(estimate(cfg, [entry(0, "carousel")]), "gauntlet_critics")

    assert small.quantity == big.quantity  # critics x rounds, whatever the deck size
    assert big.unit_price is not None and small.unit_price is not None
    assert big.unit_price > small.unit_price  # ... priced with all eight frames' image tokens


def test_fr326_a_seed_frame_is_judged_and_a_reel_without_one_is_not(cfg: Config) -> None:
    """"seed-frame image renders for every reel under `reel_overlay_text: seed_frame`" — and the
    gate judges that frame (spec §7). A reel that renders no seed frame has nothing to judge: the
    finished clip is out of gauntlet scope entirely (frame extraction would mean ffmpeg, D10)."""
    priced_reels(cfg)
    cfg.run.gauntlet.enabled = True
    cfg.run.reel_overlay_text = "seed_frame"
    est = estimate(cfg, [entry(0, "reel", platform="tiktok")])
    seed = one(est, "reel_seed_frame")
    assert seed.quantity == 1 and seed.unit_price == cfg.models.price_per_unit.image["1k"]
    assert one(est, "gauntlet_critics").quantity > 0

    cfg.run.reel_overlay_text = "none"
    without = estimate(cfg, [entry(0, "reel", platform="tiktok")])
    assert lines(without, "reel_seed_frame") == [] and lines(without, "gauntlet_critics") == []


def test_fr107_the_moderation_allowance_survives_the_deleted_vision_retry(cfg: Config) -> None:
    """FR-107's compound retry allowance lost one of its two halves and kept the other.

    `vision_retry_allowance` priced "render + re-check" for FR-105's single retry; that retry is
    gone and the gate's own re-render budget is `gauntlet_rerender_allowance`, a per-deck dollar
    cap the operator typed. Quoting both would bill one gate twice. The MODERATION retry (FR-97)
    is a different failure class and is unchanged.
    """
    cfg.run.gauntlet.enabled = True
    est = estimate(cfg, [entry(0)])
    moderation = one(est, "moderation_retry_allowance")

    assert moderation.allowance
    assert lines(est, "vision_retry_allowance") == []
    assert est.worst_case_usd - est.expected_usd >= moderation.amount_usd
    expected_codes = {line.code for line in est.lines if not line.allowance}
    assert "moderation_retry_allowance" not in expected_codes


def test_fr107_carousel_anchor_failure_contingency(cfg: Config) -> None:
    """"When slide 1 fails, the deck falls back to independent generation of all N slides ... A
    carousel's worst case is therefore **N + 1 renders**, and the estimate carries that
    contingency".

    TWO units since v2.2.0: FR-95's anchor-failure shape gained a step. A dead anchor now buys ONE
    fresh anchor attempt before the reference-free burst, so the worst case is the failed slide-1
    job PLUS the failed re-anchor PLUS the N-render burst — N+2 billed renders. Both extra jobs
    bill on submission whether or not they land, so both belong in the estimate.
    """
    cfg.run.carousel_anchor = True
    est = estimate(cfg, [entry(0, "carousel")])
    slides = one(est, "carousel_slides")
    contingency = one(est, "anchor_contingency_allowance")

    assert slides.quantity == cfg.platform("linkedin").carousel_slides
    assert contingency.quantity == 2 and contingency.allowance
    assert contingency.unit_price == slides.unit_price  # the N+1th and N+2nd, at the same tier

    cfg.run.carousel_anchor = False
    assert lines(estimate(cfg, [entry(0, "carousel")]), "anchor_contingency_allowance") == []


def test_fr326_critic_image_tokens_are_priced_at_native_render_resolution(
    cfg: Config,
) -> None:
    """"**vision image tokens** — priced at native render resolution" (FR-107/FR-326).

    The gate has NEVER downscaled: it reads the render we just paid for, at the size we paid for
    it (`vision_check.load_images` sends native bytes, and that invariant outlived the check it was
    written for). So the resolution tier moves this price, and must.

    **RE-BASED at D60/FR-342 onto a 1:1 entry, and the ratio is now load-bearing.** This fixture's
    default image ratio is 4:5, which is one of 20 §8c's 1K-ONLY ratios: whatever tier a platform
    pins, Kie renders 4:5 at 1K, so both sides of the comparison below used to come back 1,024 px
    and the price rightly did not move. That was invisible while `_image_price` read the configured
    tier straight off the platform; since FR-342 it runs the entry's ratio through
    `profiles.effective_image_tier` — the same clamp the render path runs — and the old assertion
    started failing with the two tiers priced identically, which was the CORRECT answer to the
    question the test was accidentally asking. 1:1 is what a carousel slide and a house image
    actually render at, and at 1:1 the tier really does decide the pixel count.
    """
    cfg.run.gauntlet.enabled = True

    def at_tier(tier: str) -> float:
        cfg.platforms["linkedin"] = SimpleNamespace(  # type: ignore[assignment]
            carousel_slides=5, image_resolution=tier)
        price = one(estimate(cfg, [entry(0, trend_key="t1", aspect_ratio="1:1")]),
                    "gauntlet_critics").unit_price
        assert price is not None
        return price

    assert at_tier("2k") > at_tier("1k")  # critic frames are native — the tier moves the price


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
    """"**per-platform resolution**, since price scales with output size".

    **RE-BASED at D60/FR-342, twice over, and both moves are the same idea.**

    The ratio is now 1:1 because 4:5 is one of 20 §8c's 1K-only ratios (see the FR-326 test above):
    at 4:5 both platforms below would price at 1K however they were configured, and the test would
    be measuring the clamp rather than the per-platform key.

    The 4K expectation became `image.2k` for the reason FR-342 exists. The estimate is a promise
    about what the run will BUY, and FR-192's production ceiling folds a 4K request down to 2K at
    the provider — so quoting `image.4k` here would put a price on the gate that no render was ever
    going to be billed at. `effective_image_tier` is the estimator's public twin of the renderer's
    own clamp, both sides run it, and the number the operator approves is the number Kie sends.

    A 4K platform can now ONLY exist as the `SimpleNamespace` below: `PlatformConfig.
    image_resolution` is a `Literal["1k", "2k"]`, so a config file naming `4k` is refused at load
    (`tests/test_config.py`). The double is kept anyway, deliberately — the accessor is a reader
    and not a validator, and this is where that division of labour is exercised.
    """
    cfg.platforms["linkedin"] = SimpleNamespace(  # type: ignore[assignment]
        carousel_slides=5, image_resolution="1k")
    cfg.platforms["instagram"] = SimpleNamespace(  # type: ignore[assignment]
        carousel_slides=5, image_resolution="4k")
    est = estimate(cfg, [entry(0, platform="linkedin", aspect_ratio="1:1"),
                         entry(1, platform="instagram", aspect_ratio="1:1")])
    cheap, dear = lines(est, "image_render")

    assert (cheap.unit_price, cheap.price_key) == (0.03, "models.price_per_unit.image.1k")
    assert (dear.unit_price, dear.price_key) == (0.05, "models.price_per_unit.image.2k")
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


# ------------------------------------------------- FR-334 matched style assignment (v2.4.0/D56)


def test_fr334_the_style_match_call_is_quoted_under_matched_and_not_at_all_under_rotation(
    cfg: Config,
) -> None:
    """§5: matched assignment is ONE batched `analysis` call at ASSIGN, and ASSIGN runs long after
    the Confirm gate — so rule 7 says the operator approves the number before it is spent.

    `assignment: rotation` is the engine default and the escape hatch, and it spends nothing at
    all: the FR-291 scan is arithmetic over a list in memory. A line quoting a call that will not
    happen reads as a rate that failed to load, so both rows have to disappear together.
    """
    plan = [entry(0, trend_key="t1"), entry(1, "carousel", trend_key="t1")]

    assert cfg.styles.assignment == "rotation", "the engine default, unchanged by D56"
    off = estimate(cfg, plan)
    assert lines(off, "style_match_call") == []
    assert lines(off, "style_match_retry_allowance") == []

    cfg.styles.assignment = "matched"
    est = estimate(cfg, plan)
    call = one(est, "style_match_call")

    assert call.category is SpendCategory.LLM and call.unit == "call"
    assert call.assumed_model == cfg.models.analysis  # the `analysis` role — Sonnet prices it
    assert call.price_key == "models.price_per_unit.llm.sonnet"
    assert not call.allowance and call.amount_usd > 0  # paid work the run WILL do, not a hedge
    assert call.entry_orders == (0, 1) and "2 creative(s)" in call.label
    assert est.expected_usd == pytest.approx(off.expected_usd + call.amount_usd)


def test_fr334_one_batched_call_whatever_the_plan_size_with_the_same_two_retries_beside_it(
    cfg: Config,
) -> None:
    """ONE call per RUN, batched over every styled creative — so the QUANTITY never grows with the
    plan and only the prompt does. A per-creative line would over-quote a twenty-creative run by
    twentyfold and would quietly describe an architecture the module does not have.

    The allowance beside it is FR-107's per-call bound, identical to every other LLM role: FR-127's
    widened truncation retry and FR-41's parse retry are independent, each capped at one, and one
    call can spend BOTH (`llm._run_attempts`) — hence 2, priced at the widened cap. An allowance
    only, because the stage is fail-open: a failed match leaves every entry on its FR-291 baseline
    and the run continues, so there is never a re-match to pay for.
    """
    cfg.styles.assignment = "matched"

    prices = []
    for size in (1, 3, 12):
        est = estimate(cfg, [entry(index, trend_key="t1") for index in range(size)])
        call, retry = one(est, "style_match_call"), one(est, "style_match_retry_allowance")

        assert call.quantity == 1, f"{size} creatives is still one batched call"
        assert retry.quantity == 2 and retry.allowance and retry.unit == "retry"
        assert retry.category is SpendCategory.LLM
        assert call.unit_price is not None and retry.unit_price is not None
        assert retry.unit_price > call.unit_price  # ... each at FR-127's widened token cap
        assert retry.amount_usd == pytest.approx(retry.unit_price * 2)
        # The contingency rides worst case alone: FR-106a's expected projection is what the batch
        # is gated on and what `trim()` compares against a cap.
        assert est.worst_case_usd - est.expected_usd >= retry.amount_usd
        prices.append(call.unit_price)

    assert prices[0] < prices[1] < prices[2], "one call, but a prompt that grows with the plan"


def test_fr334_a_plan_of_override_briefs_alone_is_never_charged_for_a_style_match(
    cfg: Config,
) -> None:
    """Override briefs are never styled at all (M14: the brief's directives replace the style
    channel outright, so `runner._assign_visuals` filters them out before `assign_styles` ever sees
    them and they carry no `style_key` to overrule). They are therefore not in the matcher's entry
    set and must not be in its price — the same shape `_filter_lines` and `_slide_intel_lines`
    already refuse to quote for work that will not happen.

    The mixed plan is the half that matters in practice: the line still appears, but it is
    attributed to the styled orders only, and that attribution is what the per-entry share — and
    therefore every trim decision — is computed from.
    """
    cfg.styles.assignment = "matched"
    briefs_only = [entry(0, brief_name="ai-audit-cta", brief_influence="override"),
                   entry(1, brief_name="ai-audit-cta", brief_influence="override")]

    assert lines(estimate(cfg, briefs_only), "style_match_call") == []
    assert lines(estimate(cfg, briefs_only), "style_match_retry_allowance") == []

    mixed = [entry(0, brief_name="ai-audit-cta", brief_influence="override"),
             entry(1, trend_key="t1"), entry(2, "carousel", trend_key="t1")]
    call = one(estimate(cfg, mixed), "style_match_call")

    assert call.entry_orders == (1, 2), "the brief pays for no part of a match it never enters"
    assert "2 creative(s)" in call.label


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
    cfg.run.gauntlet.enabled = True
    est = estimate(cfg, [entry(0, "reel", platform="tiktok")])

    clip = one(est, "reel_clip")
    assert clip.unit_price is None and clip.amount_usd == 0.0  # never a guessed price
    assert clip.unpriced and clip.blocking
    assert clip.price_key == "models.price_per_unit.reel_second.720p"
    assert est.blocked == (clip,) and clip.entry_orders == (0,)
    assert clip.price_key in clip.label and "FR-131" in clip.label  # the key is named, not guessed
    # A blocked reel buys nothing else either: no seed frame, no gate, no retry allowance.
    assert lines(est, "reel_seed_frame") == lines(est, "gauntlet_critics") == []
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


# --------------------------------------------------------------------------- FR-326 the gauntlet


def deck_plan(cfg: Config, decks: int = 1, slides: int = 8) -> list[PlanEntry]:
    """`decks` carousels of `slides` slides each, on a platform whose hard max allows them."""
    cfg.platforms["linkedin"] = PlatformConfig(formats=["carousel"], carousel_slides=slides)
    return [entry(i, "carousel", trend_key=f"t{i}", slide_count=slides) for i in range(decks)]


def test_fr106a_enabling_the_gauntlet_never_moves_expected_spend(cfg: Config) -> None:
    """THE ACCEPTANCE TEST (gauntlet spec §5, FR-106a): the gauntlet is displayed and provisioned
    for in the WORST CASE and is otherwise invisible to the money gate.

    `expected_usd` is what FR-106a gates the batch on and what `trim()` compares against a cap, so
    a gauntlet line leaking into it would delete real creatives to pay for re-renders that mostly
    never happen — the quality gate deleting the creative it exists to improve. Every per-entry
    share must be untouched for the same reason: that number is what a trim decision is logged
    with. Only `worst_case_usd` may move, and it must actually move, or the operator is being
    quoted a gate that looks free.
    """
    plan = deck_plan(cfg, decks=2)
    cfg.run.gauntlet.enabled = False
    off = estimate(cfg, plan)
    off_shares = dict(off.per_entry_usd)

    cfg.run.gauntlet.enabled = True
    on = estimate(cfg, plan)

    assert on.expected_usd == off.expected_usd
    assert on.per_entry_usd == off_shares
    assert on.worst_case_usd > off.worst_case_usd
    assert all(line.allowance for line in on.lines if line.code.startswith("gauntlet_"))
    # ... and the same cap that fitted without the gauntlet still trims nothing with it on.
    assert trim(cfg, plan, cap_usd=off.expected_usd).trimmed == ()


def test_fr326_allowance_is_the_specs_formula(cfg: Config) -> None:
    """Spec §5: `Σ deck_budget_usd + decks x enabled_critics x rounds_max x est_call_usd`."""
    cfg.run.gauntlet.rounds_max = 3
    cfg.run.gauntlet.deck_budget_usd = 0.30
    plan = deck_plan(cfg, decks=2)
    est = estimate(cfg, plan)

    panels = lines(est, "gauntlet_critics")
    rerender = one(est, "gauntlet_rerender_allowance")
    assert len(panels) == 2  # one line per deck, priced at that deck's own frame count
    assert all(panel.quantity == 3 * 3 for panel in panels)  # 3 critics x 3 rounds
    assert all(panel.category is SpendCategory.LLM and panel.unit == "call" for panel in panels)
    assert rerender.quantity == 2 and rerender.unit_price == 0.30  # the per-deck cap IS the worst
    assert rerender.category is SpendCategory.RENDER
    assert rerender.amount_usd == pytest.approx(0.60)

    gauntlet_usd = sum(line.amount_usd for line in est.lines if line.code.startswith("gauntlet_"))
    est_call = panels[0].unit_price
    assert est_call is not None
    assert gauntlet_usd == pytest.approx(2 * 0.30 + 2 * 3 * 3 * est_call)

    # Two enabled critics means two thirds of the panel spend, and nothing else changes.
    cfg.run.gauntlet.critics["craft"].enabled = False
    assert all(panel.quantity == 2 * 3 for panel in lines(estimate(cfg, plan), "gauntlet_critics"))


def test_fr326_a_critic_call_is_priced_at_the_measured_one_thousand_completion_tokens(
    cfg: Config,
) -> None:
    """Session 5.6/F5-tail's re-base: an 8-frame call is ~27k input tokens (the measured ≈18.3k
    prompt side plus ~1,119/frame at the 4:5 `1k` tier) plus **1,000** completion, landing on ~$0.06.

    1,000, not the 5,000 this pinned before, and not the 700 it pinned before that. 700 was a
    guess. 5,000 was a measurement of a critic thinking at FULL effort inside `completion_tokens`,
    taken before F5 bound the role at `models.critic_reasoning_effort: low` — Session 5.5 wrote it
    down as provisional and promised a re-measurement. Canary `20260819_170148_2z4y` is that
    measurement: 4,769 completion tokens over 11 calls, ≈434 a call, so 1,000 quotes ~2.3x what
    the gate really returns. The constant is pinned here because understating it is the one
    estimator error that is never safe (D11) — it may only ever move against a measurement, which
    is exactly what moved it this time.
    """
    est = estimate(cfg, deck_plan(cfg, decks=1, slides=8))
    panel = one(est, "gauntlet_critics")
    assert panel.unit_price is not None

    per_frame = budget._image_tokens(1024, "4:5")
    assert per_frame == pytest.approx(1118, abs=2)  # ~1,118 tokens a frame, unchanged by F5
    input_tokens = budget._CRITIC_PROMPT_TOKENS + 8 * per_frame
    assert 27_000 <= input_tokens <= 28_000  # measured prompt side + this deck's own frames
    rates = cfg.models.price_per_unit.llm["sonnet"]
    input_usd = input_tokens / 1_000_000 * rates["input_per_mtok"]

    completion_usd = panel.unit_price - input_usd
    assert completion_usd == pytest.approx(1_000 / 1_000_000 * rates["output_per_mtok"])
    assert budget._CRITIC_COMPLETION_TOKENS == 1000
    # …and it is the CONSTANT that binds, not `max_tokens.critic` (8,000): the quote is what a
    # critic call really returns, bounded by the cap, never the cap itself.
    assert budget._CRITIC_COMPLETION_TOKENS < cfg.max_tokens_for("critic")
    assert format_usd(panel.unit_price) == "$0.06"
    assert panel.unit_price == pytest.approx(0.065, abs=0.001)


def test_fr326_critic_calls_price_off_the_sonnet_block_and_say_which_model(cfg: Config) -> None:
    """`_ROLE_PRICE_KEY["critic"]` is what stops the whole gauntlet pricing at $0 (30 §2/D49)."""
    assert budget._ROLE_PRICE_KEY["critic"] == "sonnet"
    panel = one(estimate(cfg, deck_plan(cfg)), "gauntlet_critics")
    assert panel.price_key == "models.price_per_unit.llm.sonnet"
    assert panel.assumed_model == cfg.models.critic  # its OWN role, never `models.analysis`

    # And an unset rate reports rather than pretending the gate is free (FR-282).
    cfg.models.price_per_unit.llm["sonnet"]["output_per_mtok"] = 0.0
    unpriced = one(estimate(cfg, deck_plan(cfg)), "gauntlet_critics")
    assert unpriced.unpriced and unpriced.amount_usd == 0.0 and unpriced.unit_price is None


def test_fr326_images_and_seed_frames_ride_their_own_rounds_ceiling(cfg: Config) -> None:
    """`rounds_max_image` is the standalone ceiling, and `0` means judge without re-rendering."""
    cfg.run.gauntlet.rounds_max_image = 1
    est = estimate(cfg, [entry(0, trend_key="t1")])
    assert one(est, "gauntlet_critics").quantity == 3  # 3 critics x ONE round
    # One round can never reach a re-render (the loop breaks at `rounds_max`), so no cap is quoted.
    assert lines(est, "gauntlet_rerender_allowance") == []

    cfg.run.gauntlet.rounds_max_image = 0
    zero = estimate(cfg, [entry(0, trend_key="t1")])
    assert one(zero, "gauntlet_critics").quantity == 3  # still judged, still paid for
    assert lines(zero, "gauntlet_rerender_allowance") == []

    # A reel is judged on its SEED FRAME only; without one it renders nothing the panel can read.
    priced_reels(cfg, 0.315)
    cfg.run.reel_overlay_text = "none"
    assert lines(estimate(cfg, [entry(1, "reel", platform="tiktok")]), "gauntlet_critics") == []


def test_no_gauntlet_lines_when_nothing_will_be_judged(cfg: Config) -> None:
    """`gauntlet.enabled: false` is the rollback knob — no gate, and therefore no quote for one.

    Every critic switched off is the same run by another route, and `deck_budget_usd: 0.00` is a
    legal "judge, never re-render" rather than a rate that failed to load: it must not print a $0
    row and must not raise the governance banner.
    """
    plan = deck_plan(cfg)
    cfg.run.gauntlet.enabled = False
    assert [line for line in estimate(cfg, plan).lines if line.code.startswith("gauntlet_")] == []

    cfg.run.gauntlet.enabled = True
    for critic in cfg.run.gauntlet.critics.values():
        critic.enabled = False
    assert [line for line in estimate(cfg, plan).lines if line.code.startswith("gauntlet_")] == []

    for critic in cfg.run.gauntlet.critics.values():
        critic.enabled = True
    cfg.run.gauntlet.deck_budget_usd = 0.0
    est = estimate(cfg, plan)
    assert lines(est, "gauntlet_rerender_allowance") == [] and est.banner == ""
    assert len(lines(est, "gauntlet_critics")) == 1  # the panel still runs and is still quoted


def test_fr326_critic_price_gap_is_the_preflight_predicate(cfg: Config) -> None:
    """Pre-flight's consumable check that `models.critic` resolves to a priced block (T2.4 wires
    it): the whole sentence to report, or `None` when there is nothing to say."""
    assert budget.critic_price_gap(cfg) is None

    cfg.models.price_per_unit.llm["sonnet"]["input_per_mtok"] = 0.0
    gap = budget.critic_price_gap(cfg)
    assert gap is not None
    assert "models.price_per_unit.llm.sonnet" in gap and cfg.models.critic in gap
    assert "input_per_mtok" in gap  # names the missing rate, never a vague "unpriced"

    # Silent when no critic call will be made — a rate for work that never happens is not a gap.
    cfg.run.gauntlet.enabled = False
    assert budget.critic_price_gap(cfg) is None
    cfg.run.gauntlet.enabled = True
    for critic in cfg.run.gauntlet.critics.values():
        critic.enabled = False
    assert budget.critic_price_gap(cfg) is None


# --------------------------------------------------------------------------- FR-282 provenance


def test_fr282_every_priced_line_carries_key_origin_and_assumed_model(cfg: Config) -> None:
    """FR-282: "The pre-flight cost summary SHALL print, for every priced line, which configured
    model that price is being assumed for".

    Every line names the config key its number came from. That key is a `price_per_unit` rate for
    every line but one: v2.2.0's `gauntlet_rerender_allowance` is a per-deck dollar CAP the
    operator typed at `run.gauntlet.deck_budget_usd`, not a rate the estimator multiplied out, and
    naming the rate table there would send a reader to a key that cannot explain the figure.
    """
    cfg.run.gauntlet.enabled = True
    est = estimate(cfg, [entry(0, trend_key="t1"), entry(1, "carousel", trend_key="t1")])
    assert est.lines
    for line in est.lines:
        assert line.price_key and line.price_origin and line.assumed_model
        assert line.price_key.startswith("models.price_per_unit.") or (
            line.code == "gauntlet_rerender_allowance"
            and line.price_key == "run.gauntlet.deck_budget_usd")
    assert one(est, "image_render").assumed_model == cfg.models.image
    # The `analysis_call` row went with the style-brief stage (D41) and the `vision_check` rows
    # went with the FR-105 machinery (D49). The `critic` role is what prices the gate now, so
    # `models.critic` is what its lines name.
    assert all(row.assumed_model == cfg.models.critic
               for row in lines(est, "gauntlet_critics"))
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


# ---- D60 ------------------------------ FR-342: the gate quotes the tier the provider will send
#
# The two re-bases above are the old FR-107 tests moved onto 1:1 entries. What follows is the NEW
# behaviour underneath them: `_image_price` no longer prices what the CONFIG asked for, it prices
# what Kie will RENDER, and the difference between those two is a per-ratio clamp the render path
# has always run and the estimator used to be blind to. A gate that quotes 2K and buys 1K is not
# a rounding error — it is CLAUDE.md rule 7 broken, because the number the operator approved is
# not the number the run spends.


def test_fr342_a_one_k_only_ratio_is_priced_at_1k_however_its_platform_was_pinned(
    cfg: Config,
) -> None:
    """20 §8c's clamp, at the gate: an Instagram image at FR-21's 4:5 renders 1K and is billed 1K.

    Both entries below sit on the SAME `2k` platform, so the configured tier cannot be what
    separates them — the only difference is the aspect ratio, and 4:5 is one of the ratios the
    provider will not render above 1K. The carousel slide at 1:1 gets the 2K rate the platform
    pinned; the 4:5 image does not, because nobody is going to sell us 2K pixels for it.

    This is the arm that would silently over-quote every Instagram image post if the estimator
    ever stopped running the clamp: 0.05 charged, 0.03 spent, per frame, invisibly.
    """
    cfg.platforms["instagram"] = PlatformConfig(carousel_slides=5, image_resolution="2k")
    est = estimate(cfg, [entry(0, platform="instagram", aspect_ratio="4:5"),
                         entry(1, "carousel", platform="instagram", aspect_ratio="1:1")])

    image = one(est, "image_render")
    slides = one(est, "carousel_slides")

    assert (image.unit_price, image.price_key) == (0.03, "models.price_per_unit.image.1k"), \
        "FR-342: 4:5 is a 1K-only ratio at the provider, so 1K is what the gate may quote"
    assert (slides.unit_price, slides.price_key) == (0.05, "models.price_per_unit.image.2k"), \
        "…and 1:1 on the same platform really does buy the tier the config pinned"


def test_fr342_the_critics_vision_tokens_follow_the_effective_tier_and_not_the_configured_one(
    cfg: Config,
) -> None:
    """The second reader of the same clamp, and the more expensive one to get wrong.

    `_image_price` hands back a long EDGE beside the price, and the gauntlet's critics are billed
    on it: they read the frames we rendered at the size we rendered them, so a 2K frame costs
    roughly 3,278 vision tokens where a 1K frame costs 1,398. If the estimator took the long edge
    off the configured tier instead of the effective one, every 4:5 creative on a 2K platform
    would be quoted for pixels that were never rendered — the same defect as the price above, in
    a line an operator is far less likely to check by hand.

    Asserted as two comparisons rather than as two magic numbers: at 4:5 the tier makes NO
    difference (the clamp erases it), at 1:1 it makes one. Those two facts together are the clamp,
    and they survive a re-priced token table.
    """
    cfg.run.gauntlet.enabled = True

    def critic_price(tier: str, ratio: str) -> float:
        cfg.platforms["linkedin"] = PlatformConfig(carousel_slides=5, image_resolution=tier)
        price = one(estimate(cfg, [entry(0, trend_key="t1", aspect_ratio=ratio)]),
                    "gauntlet_critics").unit_price
        assert price is not None
        return price

    assert critic_price("2k", "4:5") == critic_price("1k", "4:5"), \
        "FR-342: a 1K-only ratio renders 1K on either platform, so the critics read the same frame"
    assert critic_price("2k", "1:1") > critic_price("1k", "1:1"), \
        "…and at a ratio the provider WILL render at 2K, the taller frame costs more to read"


def test_fr342_a_four_k_platform_is_priced_at_the_ceiling_the_renderer_will_actually_send(
    cfg: Config,
) -> None:
    """FR-192's ceiling, at the gate rather than at the wire.

    4K is declared by Kie's enum and never requested by this engine: `profiles._image_resolution`
    folds it to 2K on every image job. The estimator runs the same fold through the public twin, so
    a hand-built 4K platform is quoted at the 2K rate — the rate the render will really be billed
    at — instead of at a 4K rate no job will ever produce.

    It cannot come from a config file any more (`Literal["1k", "2k"]` refuses it at load), which is
    exactly why the double is built by hand here: the accessor is a READER, the load step is the
    validator, and this is the test that keeps those two jobs from merging.
    """
    cfg.platforms["linkedin"] = SimpleNamespace(  # type: ignore[assignment]
        carousel_slides=5, image_resolution="4k")

    render = one(estimate(cfg, [entry(0, aspect_ratio="1:1")]), "image_render")

    assert (render.unit_price, render.price_key) == (0.05, "models.price_per_unit.image.2k")
    assert not render.unpriced, "the folded tier IS priced; only an unknown tier is not"
