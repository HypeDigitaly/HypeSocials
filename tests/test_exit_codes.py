"""FR-202's exit-code contract — `runner.decide_exit_code()`, all five codes plus the carve-outs.

A scheduler can read nothing but the exit code, so this function IS the contract (10 §7,
FR-202) and every branch of it is named here. Pure logic: no event loop, no I/O, no spend.

Naming convention matches the sibling suites: `test_fr202_<what the requirement says>`, with the
requirement quoted in the docstring so an assertion can be checked without leaving the file.
"""

from __future__ import annotations

from hypesocials.models import DegradationTag, PlanEntry, PlanEntryStatus
from hypesocials.runner import (
    EXIT_INTERRUPTED,
    EXIT_NOTHING_USABLE,
    EXIT_OK,
    EXIT_PARTIAL,
    EXIT_PREFLIGHT,
    _analysis_degraded_line,
    decide_exit_code,
)

# --------------------------------------------------------------------------- builders


def entry(
    order: int,
    status: PlanEntryStatus = PlanEntryStatus.SUCCESS,
    *,
    brief: str | None = None,
    skip_reason: str | None = None,
    fmt: str = "image",
    variant: str = "analyzed",
) -> PlanEntry:
    """The minimal `PlanEntry` this decision reads: status, variant, skip_reason, asset_id."""
    return PlanEntry(  # type: ignore[arg-type]
        order=order,
        asset_id=f"Li_{fmt[:3]}_trend_{variant}_{order + 1:02d}",
        creative_format=fmt,
        platform="linkedin",
        language="en",
        aspect_ratio="16:9",
        variant=variant,
        status=status,
        skip_reason=skip_reason,
        brief_name=brief,
        brief_influence="override" if brief else None,
        trend_key=None if brief else "dance-challenge",
    )


# --------------------------------------------------------------------------- the five codes


def test_fr202_code_0_every_planned_creative_was_delivered() -> None:
    """"0 — Every planned creative was delivered"."""
    assert decide_exit_code([entry(0), entry(1), entry(2)]) == EXIT_OK
    assert EXIT_OK == 0


def test_fr202_code_1_partial_success_for_every_losing_status() -> None:
    """"1 — Partial success … at least one creative was skipped, failed, budget-trimmed or
    abandoned". Each losing status is asserted individually — one shared assertion would hide a
    status the branch forgot."""
    losses = (
        PlanEntryStatus.FAILED,
        PlanEntryStatus.SKIPPED,
        PlanEntryStatus.SKIPPED_BUDGET,
        PlanEntryStatus.ABANDONED,
        PlanEntryStatus.PENDING,
        PlanEntryStatus.SUBMITTED,
    )
    for status in losses:
        entries = [entry(0), entry(1, status)]
        assert decide_exit_code(entries) == EXIT_PARTIAL, status
    assert EXIT_PARTIAL == 1


def test_fr202_code_2_preflight_refusal_beats_everything_else() -> None:
    """"2 — Pre-flight refusal or config error … Detected before Collect; nothing was spent."
    It is checked first, so it wins over an interrupt and over a trend famine both."""
    assert decide_exit_code([], preflight_refused=True) == EXIT_PREFLIGHT
    assert decide_exit_code([entry(0)], preflight_refused=True) == EXIT_PREFLIGHT
    assert decide_exit_code(
        [entry(0)], preflight_refused=True, interrupted=True, trend_supply_failed=True
    ) == EXIT_PREFLIGHT
    assert EXIT_PREFLIGHT == 2


def test_fr202_code_2_for_an_empty_plan() -> None:
    """"a zero-creative plan never starts (FR-64)" — nothing was requested, nothing was spent."""
    assert decide_exit_code([]) == EXIT_PREFLIGHT
    assert decide_exit_code([], interrupted=False, trend_supply_failed=False) == EXIT_PREFLIGHT


def test_fr202_code_3_trend_famine_with_zero_delivered() -> None:
    """"3 — Fatal after Collect began — zero usable trends (for a plan needing trends)". Every
    entry needed a trend and none shipped, so nothing at all was deliverable."""
    entries = [entry(0, PlanEntryStatus.SKIPPED), entry(1, PlanEntryStatus.SKIPPED)]
    assert decide_exit_code(entries, trend_supply_failed=True) == EXIT_NOTHING_USABLE
    assert EXIT_NOTHING_USABLE == 3


def test_fr202_code_4_interrupted_by_sigint() -> None:
    """"4 — Interrupted by SIGINT (FR-201)"."""
    assert decide_exit_code([entry(0)], interrupted=True) == EXIT_INTERRUPTED
    assert EXIT_INTERRUPTED == 4


# --------------------------------------------------------------------------- precedence


def test_fr202_interrupted_wins_over_partial() -> None:
    """A run that was Ctrl+C'd mid-batch exits 4, not 1 — the interrupt is the story, and the
    ledger (FR-203) is what makes the losses visible."""
    entries = [entry(0), entry(1, PlanEntryStatus.ABANDONED), entry(2, PlanEntryStatus.SKIPPED)]
    assert decide_exit_code(entries) == EXIT_PARTIAL  # the same plan without the interrupt
    assert decide_exit_code(entries, interrupted=True) == EXIT_INTERRUPTED


def test_fr202_interrupted_wins_over_a_trend_famine() -> None:
    """An operator's Ctrl+C is a more precise cause than the famine it may have followed."""
    entries = [entry(0, PlanEntryStatus.SKIPPED)]
    assert decide_exit_code(entries, trend_supply_failed=True) == EXIT_NOTHING_USABLE
    assert decide_exit_code(entries, trend_supply_failed=True, interrupted=True) == EXIT_INTERRUPTED


# --------------------------------------------------------------------------- brief-only carve-out


def test_fr202_famine_but_override_brief_creatives_shipped_is_partial() -> None:
    """10 §10: "Exit code: 3 when every planned creative needed a trend (nothing deliverable),
    1 when brief creatives shipped". An override brief consumes no trend (FR-144), so its
    inputs survive a Virlo famine intact."""
    entries = [
        entry(0, brief="ai-audit-cta"),  # delivered — needed no trend
        entry(1, PlanEntryStatus.SKIPPED),  # needed a trend, dropped
        entry(2, PlanEntryStatus.SKIPPED),
    ]
    assert decide_exit_code(entries, trend_supply_failed=True) == EXIT_PARTIAL


def test_fr202_brief_only_plan_delivering_everything_is_a_plain_zero() -> None:
    """10 §10: "0 when the plan was brief-only and all delivered". A plan that never opens a
    Virlo session cannot be failed by Virlo — even with the famine flag raised."""
    entries = [entry(0, brief="ai-audit-cta"), entry(1, brief="ai-audit-cta")]
    assert decide_exit_code(entries, trend_supply_failed=True) == EXIT_OK
    assert decide_exit_code(entries) == EXIT_OK


def test_fr202_famine_flag_is_inert_once_anything_was_delivered() -> None:
    """The carve-out is "nothing deliverable", not "briefs specifically": a trend-backed creative
    that shipped before the supply ran dry is equally proof the run was not fatal."""
    entries = [entry(0), entry(1, PlanEntryStatus.SKIPPED)]
    assert decide_exit_code(entries, trend_supply_failed=True) == EXIT_PARTIAL


# --------------------------------------------------------------------------- delivered-with-loss


def test_fr202_delivered_deck_carrying_a_skip_reason_is_partial() -> None:
    """v1.6.7: "or a delivered carousel shipped incomplete (missing slides, FR-20/§10 — a lost
    slide is a loss even when the deck ships)". Status is SUCCESS and the deck is on disk, but a
    `skip_reason` names what is missing, so the run exits 1."""
    deck = entry(1, fmt="carousel", skip_reason="slides 3,4 failed (kie_timeout)")
    assert deck.status is PlanEntryStatus.SUCCESS
    assert decide_exit_code([entry(0), deck]) == EXIT_PARTIAL


def test_fr202_a_whole_plan_of_incomplete_decks_is_partial_not_ok() -> None:
    """Every entry SUCCESS but every entry carrying a loss — the `whole` count, not the delivered
    count, is what the 0/1 decision compares against the plan length."""
    entries = [entry(index, fmt="carousel", skip_reason="slide 5 failed") for index in range(3)]
    assert decide_exit_code(entries) == EXIT_PARTIAL


def test_fr202_empty_skip_reason_string_does_not_manufacture_a_loss() -> None:
    """`skip_reason=""` is "no reason recorded", not a loss — only a real one-line cause is."""
    assert decide_exit_code([entry(0, skip_reason=""), entry(1)]) == EXIT_OK


# ------------------------------------------------- the partial deck, as the live run produced it


def test_fr202_partial_deck_from_the_live_run_exits_one_on_its_incomplete_tag() -> None:
    """The 2026-08-11 regression, in the exact shape `output/20260811_233910_wikf` wrote.

    `Li_car_ai-trends-tracker_analyzed_05/meta.yaml` recorded `status: success`, `slide_count: 4`,
    `missing_slide_numbers: [2]` and `degradations: ['text_trimmed', 'incomplete']` after slide 2
    hit "timeout — no terminal state within 180s". There is **no `skip_reason`** on that entry —
    the deck shipped, so `carousel.package()` marks the folder `incomplete` instead — and the run
    exited 0 with "everything planned was delivered". FR-202 code 1: "a lost slide is a loss even
    when the deck ships".
    """
    deck = entry(4, fmt="carousel")
    others = [entry(index) for index in range(4)]
    tags = {deck.asset_id: [DegradationTag.TEXT_TRIMMED, DegradationTag.INCOMPLETE]}

    assert deck.status is PlanEntryStatus.SUCCESS and deck.skip_reason is None
    assert decide_exit_code([*others, deck]) == EXIT_OK  # the pre-fix answer, without the tags
    assert decide_exit_code([*others, deck], degradations=tags) == EXIT_PARTIAL


def test_fr202_text_trimmed_alone_is_not_a_loss() -> None:
    """`_DELIVERED_LOSS_TAGS` is `incomplete` alone. `text_trimmed` is FR-101's character budget
    being honoured — the same live deck carried both, and treating every tag as a loss would make
    exit 0 unreachable for any run whose copy came back one word long."""
    clean = entry(0)
    tags = {clean.asset_id: [DegradationTag.TEXT_TRIMMED, DegradationTag.HOOK_PATTERN_GENERIC]}
    assert decide_exit_code([clean], degradations=tags) == EXIT_OK


def test_fr202_incomplete_on_a_creative_that_did_not_deliver_changes_nothing() -> None:
    """The clause is about a DELIVERED creative. A failed entry is already a loss by status, and
    an unrelated record in the map must never promote a clean plan to partial."""
    tags = {"some_other_asset": [DegradationTag.INCOMPLETE]}
    assert decide_exit_code([entry(0), entry(1)], degradations=tags) == EXIT_OK


def test_fr202_an_empty_degradation_map_is_the_old_behaviour_exactly() -> None:
    """Every caller that passes nothing gets the pre-A9 decision — the tags only ever ADD a loss."""
    entries = [entry(0), entry(1, fmt="carousel")]
    assert decide_exit_code(entries) == EXIT_OK
    assert decide_exit_code(entries, degradations={}) == EXIT_OK
    assert decide_exit_code(entries, degradations={entries[1].asset_id: []}) == EXIT_OK


# --------------------------------------------------- FR-252 / A9: fully-degraded analysis


def test_fr252_every_analyzed_creative_carrying_analysis_missing_exits_one() -> None:
    """10 §7 FR-202, amended 2026-08-11: "or every analyzed creative delivered carries
    `analysis_missing`". 30 §5 FR-252: "the run ships direct-mode creatives per FR-12 … Exit code
    1". Nothing else was lost — every entry is SUCCESS with no skip_reason — and it is still a 1."""
    entries = [entry(index) for index in range(6)]
    tags = {item.asset_id: [DegradationTag.ANALYSIS_MISSING] for item in entries}

    assert decide_exit_code(entries) == EXIT_OK  # the same plan with its briefs intact
    assert decide_exit_code(entries, degradations=tags) == EXIT_PARTIAL


def test_fr252_some_analyzed_creatives_degraded_is_still_a_clean_zero() -> None:
    """**EVERY, never "at least one"** (plan §2.3). At the observed ~1-in-7 degrade rate over six
    analysis calls, "at least one" fires on ~60 % of healthy runs — exit 0 becomes unreachable and
    the code stops carrying information. One, two, five of six degraded: still 0."""
    entries = [entry(index) for index in range(6)]
    for degraded_count in (1, 2, 5):
        tags = {item.asset_id: [DegradationTag.ANALYSIS_MISSING]
                for item in entries[:degraded_count]}
        assert decide_exit_code(entries, degradations=tags) == EXIT_OK, degraded_count


def test_fr252_zero_analyzed_creatives_is_never_fully_degraded() -> None:
    """Zero of zero is not "every". A direct-mode run and a brief-only run (FR-144 emits override
    briefs `direct`) have no analyzed creative for the clause to speak about, and reading vacuous
    truth here would make exit 1 unreachable-in-reverse — every clean direct run would exit 1."""
    direct = [entry(0, variant="direct"), entry(1, variant="direct")]
    assert decide_exit_code(direct, degradations={}) == EXIT_OK
    # even with the tag present on a direct creative, which no FR-12 path emits
    assert decide_exit_code(
        direct, degradations={direct[0].asset_id: [DegradationTag.ANALYSIS_MISSING]}) == EXIT_OK

    briefs = [entry(0, brief="ai-audit-cta", variant="direct")]
    assert decide_exit_code(briefs, degradations={}) == EXIT_OK


def test_fr252_a_both_mode_pair_counts_only_its_analyzed_half() -> None:
    """FR-3's A/B ships a `direct` sibling that never had an analysis call to lose. A run whose
    every ANALYZED creative degraded is fully degraded even though half the plan is direct."""
    analyzed = [entry(0), entry(2)]
    direct = [entry(1, variant="direct"), entry(3, variant="direct")]
    tags = {item.asset_id: [DegradationTag.ANALYSIS_MISSING] for item in analyzed}
    assert decide_exit_code([*analyzed, *direct], degradations=tags) == EXIT_PARTIAL


def test_fr252_an_undelivered_analyzed_creative_is_outside_the_denominator() -> None:
    """The clause reads "every analyzed creative **delivered**". A skipped entry is already a loss
    by status; counting it as a clean analysis would let one skip hide a fully-degraded batch."""
    shipped = [entry(0), entry(1)]
    lost = entry(2, PlanEntryStatus.FAILED, skip_reason="kie_timeout")
    tags = {item.asset_id: [DegradationTag.ANALYSIS_MISSING] for item in shipped}
    assert decide_exit_code([*shipped, lost], degradations=tags) == EXIT_PARTIAL


# ------------------------------------------------------------- FR-252's summary line


def test_fr252_summary_line_names_the_count_of_degraded_creatives() -> None:
    """FR-252: "The summary line names the count of degraded creatives (e.g. 'all 6 creatives
    shipped in direct mode due to analysis failure')"."""
    entries = [entry(index) for index in range(6)]
    tags = {item.asset_id: [DegradationTag.ANALYSIS_MISSING] for item in entries}

    line = _analysis_degraded_line(entries, tags)

    assert line.startswith("all 6 analyzed creative(s) shipped in direct mode")
    assert "analysis_missing" in line and "FR-252" in line


def test_fr252_summary_line_respects_fr286s_78_column_bound() -> None:
    """FR-286: no console line exceeds 78 columns, and `→` is never emitted (`util.fit` names the
    glyphs proven safe on legacy conhost; `—` is one, the arrow is not). Checked at a three-digit
    count too, since the count is the one variable-width token in the sentence."""
    for count in (1, 6, 128):
        entries = [entry(index) for index in range(count)]
        tags = {item.asset_id: [DegradationTag.ANALYSIS_MISSING] for item in entries}
        line = _analysis_degraded_line(entries, tags)
        assert line, count
        for text in line.splitlines():
            assert len(text) <= 78, (count, len(text), text)
            assert "→" not in text


def test_fr252_summary_line_is_silent_unless_the_degrade_was_total() -> None:
    """Same trigger as the exit code, from the same helper — a partially degraded run is already a
    1 for whatever else it lost, and FR-252 legislates only the fully-degraded sentence."""
    entries = [entry(0), entry(1)]
    assert _analysis_degraded_line(entries, {}) == ""
    assert _analysis_degraded_line(
        entries, {entries[0].asset_id: [DegradationTag.ANALYSIS_MISSING]}) == ""
    assert _analysis_degraded_line([entry(0, variant="direct")], {}) == ""


# --------------------------------------------------------------------------- reduced plan (FR-252)


def test_fr252_dropped_format_never_exits_a_silent_full_success() -> None:
    """30 §5: "A trimmed, reduced, or partially-dropped unattended run is a partial success …
    never a silent full-success exit." The regression: an unpriced reel (FR-131) or a format no
    platform allows (FR-132) is dropped BEFORE expansion, so it leaves no `PlanEntry` behind —
    every surviving entry succeeds and the run would otherwise exit 0 having delivered less than
    it was asked for. `plan.Plan.notes` is the only surviving evidence, so it decides."""
    entries = [entry(0), entry(1)]
    assert decide_exit_code(entries) == EXIT_OK  # the same plan with nothing dropped
    assert decide_exit_code(entries, plan_reduced=True) == EXIT_PARTIAL


def test_fr252_a_reduced_plan_cannot_downgrade_a_worse_outcome() -> None:
    """The flag only ever turns a 0 into a 1: pre-flight, the interrupt and the famine all name a
    more precise cause and are checked first."""
    assert decide_exit_code([], plan_reduced=True) == EXIT_PREFLIGHT
    assert decide_exit_code([entry(0)], plan_reduced=True, interrupted=True) == EXIT_INTERRUPTED
    assert decide_exit_code([entry(0, PlanEntryStatus.SKIPPED)], plan_reduced=True,
                            trend_supply_failed=True) == EXIT_NOTHING_USABLE
    assert decide_exit_code([entry(0), entry(1, PlanEntryStatus.FAILED)],
                            plan_reduced=True) == EXIT_PARTIAL


# --------------------------------------------------------------------------- shape of the codes


def test_fr202_the_five_codes_are_distinct_and_stable() -> None:
    """"the codes are stable and mean exactly one thing each" — a scheduler reads integers."""
    codes = (EXIT_OK, EXIT_PARTIAL, EXIT_PREFLIGHT, EXIT_NOTHING_USABLE, EXIT_INTERRUPTED)
    assert codes == (0, 1, 2, 3, 4)
    assert len(set(codes)) == 5


def test_fr202_decide_exit_code_never_mutates_the_plan() -> None:
    """The summary renders the same entries afterwards (FR-4: nothing ever leaves the plan)."""
    entries = [entry(0), entry(1, PlanEntryStatus.FAILED, skip_reason="kie_timeout")]
    before = [(e.status, e.skip_reason, e.asset_id) for e in entries]
    decide_exit_code(entries, interrupted=False)
    assert [(e.status, e.skip_reason, e.asset_id) for e in entries] == before
