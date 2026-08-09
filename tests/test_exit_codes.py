"""FR-202's exit-code contract — `runner.decide_exit_code()`, all five codes plus the carve-outs.

A scheduler can read nothing but the exit code, so this function IS the contract (10 §7,
FR-202) and every branch of it is named here. Pure logic: no event loop, no I/O, no spend.

Naming convention matches the sibling suites: `test_fr202_<what the requirement says>`, with the
requirement quoted in the docstring so an assertion can be checked without leaving the file.
"""

from __future__ import annotations

from hypesocials.models import PlanEntry, PlanEntryStatus
from hypesocials.runner import (
    EXIT_INTERRUPTED,
    EXIT_NOTHING_USABLE,
    EXIT_OK,
    EXIT_PARTIAL,
    EXIT_PREFLIGHT,
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
) -> PlanEntry:
    """The minimal `PlanEntry` this decision reads: status, skip_reason and nothing else."""
    return PlanEntry(  # type: ignore[arg-type]
        order=order,
        asset_id=f"Li_{fmt[:3]}_trend_analyzed_{order + 1:02d}",
        creative_format=fmt,
        platform="linkedin",
        language="en",
        aspect_ratio="16:9",
        variant="analyzed",
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
