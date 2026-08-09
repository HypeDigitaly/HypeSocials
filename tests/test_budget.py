"""Budget tests — one named test per FR-107 bullet, plus FR-106's race and FR-28/106's trim.

Naming convention: `test_fr<NNN>_<what the bullet says>`. Each FR-107 test quotes its bullet in
the docstring so a reader can check the assertion against the requirement without leaving the
file. Fixtures live here (not in `conftest.py`) because nothing else needs them yet.
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
    """"vision-check calls when `vision_check` is on"."""
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


def test_fr107_vision_image_tokens_downscaled_for_analysis_native_for_checks(cfg: Config) -> None:
    """"**vision image tokens** — analysis calls priced at the downscaled size of FR-93;
    **vision-check calls priced at native render resolution**"."""
    cfg.run.vision_check = True

    def at_tier(tier: str) -> tuple[float, float]:
        cfg.platforms["linkedin"] = SimpleNamespace(  # type: ignore[assignment]
            carousel_slides=5, image_resolution=tier)
        est = estimate(cfg, [entry(0, variant="analyzed", trend_key="t1")])
        analysis = one(est, "analysis_call").unit_price
        check = one(est, "vision_check").unit_price
        assert analysis is not None and check is not None
        return analysis, check

    analysis_1k, check_1k = at_tier("1k")
    analysis_2k, check_2k = at_tier("2k")

    assert analysis_1k == analysis_2k  # analysis images are downscaled — the tier cannot move it
    assert check_2k > check_1k  # check images are native — the tier moves it


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


def test_fr107_carousel_slides_at_the_configured_ceiling(cfg: Config) -> None:
    """"carousel slides at the configured ceiling (FR-95)" — `carousel_slides` is the estimate
    basis, and a trend's own panel count may only reduce a deck below it (FR-257)."""
    cfg.platforms["linkedin"] = PlatformConfig(formats=["carousel"], carousel_slides=6)
    assert one(estimate(cfg, [entry(0, "carousel")]), "carousel_slides").quantity == 6
    assert one(estimate(cfg, [entry(0, "carousel", slide_count=4)]),
               "carousel_slides").quantity == 4
    # A source may never raise the deck above the configured ceiling.
    assert one(estimate(cfg, [entry(0, "carousel", slide_count=99)]),
               "carousel_slides").quantity == 6


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


def test_analysis_priced_per_distinct_assigned_trend(cfg: Config) -> None:
    """v1.6.5 (00-overview amendment log): M1's actual $0.23 beat its $0.16 worst case partly
    because "FR-107's analysis line priced one call while two distinct trends were assigned".

    `plan.assign()` binds a trend per ATOMIC GROUP and prefers the least-used one, so two groups
    can consume two distinct trends whatever `max_trend_reuses_per_run` says — the reuse ceiling
    only ever *reduces* the count when the pool is short. The pre-confirm estimate therefore
    prices the honest worst case: one analysis call (FR-9) and one copy call (FR-99) per group.
    """
    from hypesocials.runner import _stamp_provisional  # the pre-Collect half of the same fix

    cfg.run.max_trend_reuses_per_run = 2  # the M1 setting that hid the second trend
    plan = [entry(0, variant="analyzed"), entry(1, variant="analyzed")]
    _stamp_provisional(plan)

    assert len({e.trend_key for e in plan}) == 2  # one distinct trend per atomic group
    est = estimate(cfg, plan)
    assert one(est, "analysis_call").quantity == 2
    assert len(lines(est, "copy_call")) == 2  # FR-99 groups by (trend x language), same worst case


def test_truncation_retry_allowance_in_worst_case_not_expected(cfg: Config) -> None:
    """The other half of the v1.6.5 fix: FR-127's retry re-sends a truncated call WIDER, which
    roughly doubled M1's per-call analysis cost. It is carried as one extra full-cost call per LLM
    call — in `worst_case_usd` only, because FR-106a's expected projection is never gated on a
    contingency that mostly never happens.
    """
    plan = [entry(0, variant="analyzed"), entry(1, variant="analyzed")]
    from hypesocials.runner import _stamp_provisional

    _stamp_provisional(plan)
    est = estimate(cfg, plan)
    analysis, retry = one(est, "analysis_call"), one(est, "analysis_truncation_allowance")
    copy_retry = one(est, "copy_truncation_allowance")

    assert retry.allowance and copy_retry.allowance and retry.category is SpendCategory.LLM
    assert retry.quantity == analysis.quantity  # one extra full-cost call per analysis call
    assert retry.unit_price == analysis.unit_price
    assert copy_retry.quantity == len(lines(est, "copy_call"))
    # Worst case carries them; expected does not, and no entry's share is inflated by an allowance.
    assert est.worst_case_usd - est.expected_usd >= retry.amount_usd + copy_retry.amount_usd
    bare = round(sum(l.amount_usd for l in est.lines if not l.allowance), 6)
    assert est.expected_usd == pytest.approx(bare)


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

    priced_reels(cfg, 0.57)  # the hypedigitaly.yaml worst-case-honest scalar (v1.6.6)
    assert budget.job_projection(cfg, reel, "clip") == pytest.approx(2.85)


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
    est = estimate(cfg, [entry(0, variant="analyzed", trend_key="t1"),
                         entry(1, "carousel", trend_key="t1")])
    assert est.lines
    for line in est.lines:
        assert line.price_key and line.price_origin and line.assumed_model
        assert line.price_key.startswith("models.price_per_unit.")
    assert one(est, "image_render").assumed_model == cfg.models.image
    assert one(est, "analysis_call").assumed_model == cfg.models.analysis
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
    """Brief entries first (FR-1), then a both-mode pair, then a carousel — plan order is the
    trim order, reversed."""
    return [
        entry(0, brief_name="ai-audit-cta", atomic_group="brief-ai-audit-cta"),
        entry(1, trend_key="t1"),
        entry(2, trend_key="t2", variant="analyzed", pair_id="p1", atomic_group="pair-p1"),
        entry(3, trend_key="t2", variant="direct", pair_id="p1", atomic_group="pair-p1"),
        entry(4, "carousel", trend_key="t3", atomic_group="deck-a4"),
    ]


def test_fr106_trim_removes_whole_groups_from_the_end_in_reverse_plan_order(cfg: Config) -> None:
    """FR-106: "entries are removed from the end of the plan, in reverse plan order" — a carousel
    and a both-mode pair are one unit each, and brief creatives are trimmed last."""
    survivors_only = estimate(cfg, [entry(0, brief_name="ai-audit-cta"), entry(1, trend_key="t1")])
    plan = _mixed_plan()

    result = trim(cfg, plan, cap_usd=survivors_only.expected_usd)

    assert [e.asset_id for e in result.kept] == ["a0", "a1"]  # the brief entry survives
    assert [d.order for d in result.trimmed] == [4, 2, 3]  # deck first, then the whole pair
    assert {d.atomic_group for d in result.trimmed} == {"deck-a4", "pair-p1"}
    assert result.fits and result.estimate.expected_usd <= result.cap_usd
    assert result.original_estimate_usd > result.cap_usd


def test_fr106_atomic_groups_are_never_split_by_a_trim(cfg: Config) -> None:
    """A both-mode pair is one plan entry rendered two ways — trimming may never take one half."""
    # A cap that leaves room for the deck-less plan minus a hair reaches INTO the pair: one half
    # would fit, so a per-entry trim would split it. Both halves must go.
    without_deck = estimate(cfg, _mixed_plan()[:4]).expected_usd
    result = trim(cfg, _mixed_plan(), cap_usd=without_deck - 0.001)

    assert len([d for d in result.trimmed if d.atomic_group == "pair-p1"]) == 2
    assert not any(e.atomic_group == "pair-p1" for e in result.kept)
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
