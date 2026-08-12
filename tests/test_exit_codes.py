"""FR-202's exit-code contract — `runner.decide_exit_code()`, all five codes plus the carve-outs.

A scheduler can read nothing but the exit code, so this function IS the contract (10 §7,
FR-202) and every branch of it is named here. Pure logic: no event loop, no spend; the one
pre-flight test writes only inside `tmp_path`.

Naming convention matches the sibling suites: `test_fr202_<what the requirement says>`, with the
requirement quoted in the docstring so an assertion can be checked without leaving the file.

**Amended v2.0.0 (T3.5).** FR-202's "every analyzed creative delivered carries
`analysis_missing`" clause is WITHDRAWN with the analysis stage itself (D41): there is no
analyzed/direct split left to degrade between, `_analysis_degrade_counts` and
`_analysis_degraded_line` are deleted, and the whole FR-252 fully-degraded-analysis section of
this file went with them. Two clauses replace it and are pinned below: FR-295's registry refusal
joins the exit-2 list, and `COPY_DEGRADED` keeps its code-1 semantics through the FR-248 latch.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hypesocials import preflight
from hypesocials.config import Config, OutputConfig, RunConfig, SourcesConfig
from hypesocials.llm import CREDITS_EXHAUSTED_REASON
from hypesocials.models import AssetRecord, DegradationTag, PlanEntry, PlanEntryStatus
from hypesocials.runner import (
    EXIT_INTERRUPTED,
    EXIT_NOTHING_USABLE,
    EXIT_OK,
    EXIT_PARTIAL,
    EXIT_PREFLIGHT,
    _credits_exhausted_line,
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
    """The minimal `PlanEntry` this decision reads: status, skip_reason, asset_id.

    The asset id is FR-71's post-pivot four-segment shape (`<Pl>_<fmt>_<slug>_<NN>`); the variant
    tag it used to carry is withdrawn, and so is the `variant` argument that set it.
    """
    return PlanEntry(  # type: ignore[arg-type]
        order=order,
        asset_id=f"Li_{fmt[:3]}_topic_{order + 1:02d}",
        creative_format=fmt,
        platform="linkedin",
        language="en",
        aspect_ratio="16:9",
        status=status,
        skip_reason=skip_reason,
        brief_name=brief,
        brief_influence="override" if brief else None,
        trend_key=None if brief else "m1::dance-challenge",
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
    tags = {clean.asset_id: [DegradationTag.TEXT_TRIMMED, DegradationTag.NO_ONIMAGE_TEXT]}
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


# ------------------------------------- the withdrawn analysis clause (FR-202, v2.0.0/D41)


def test_fr202_the_fully_degraded_analysis_clause_is_withdrawn_with_the_stage() -> None:
    """FR-202's "or every analyzed creative delivered carries `analysis_missing`" is WITHDRAWN.

    The style-brief vision stage is gone (D41) and generation mode with it, so there is no
    analyzed/direct split for the clause to speak about — nothing emits `analysis_missing` any
    more, and a decision still keyed on it would be a rule about a stage that cannot run. Its two
    helpers (`_analysis_degrade_counts`, `_analysis_degraded_line`) are deleted from `runner`;
    the tag itself survives in the enum only until the W3.5 excision.

    A plan every one of whose delivered creatives carries the tag is therefore a plain 0 now.
    """
    import hypesocials.runner as runner_module

    assert not hasattr(runner_module, "_analysis_degrade_counts")
    assert not hasattr(runner_module, "_analysis_degraded_line")

    entries = [entry(index) for index in range(6)]
    tags = {item.asset_id: [DegradationTag.ANALYSIS_MISSING] for item in entries}
    assert decide_exit_code(entries, degradations=tags) == EXIT_OK


# --------------------------------------------------- FR-295: the registry refusal is exit 2


def _record(asset_id: str, *tags: DegradationTag) -> AssetRecord:
    """The slice of `AssetRecord` FR-248's latch reads: the id and its degradation tags."""
    return AssetRecord(asset_id=asset_id, source="m1::dance-challenge", source_name="Dance",
                       platform="linkedin", creative_format="image", degradations=list(tags))


@pytest.fixture
def dummy_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-46's three keys as literal placeholders (D30) — no `.env` read, no real key, no spend."""
    for name in ("VIRLO_API_KEY", "OPENROUTER_API_KEY", "KIE_API_KEY"):
        monkeypatch.setenv(name, "test-not-a-real-key")
    monkeypatch.delenv("NOTION_TOKEN", raising=False)


def test_fr295_a_registry_that_cannot_be_loaded_is_an_exit_2_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dummy_secrets: None,
) -> None:
    """FR-202's exit-2 list gains FR-295 (v2.0.0): the meta-style registry is the run's visual
    authority and has NO built-in tier (D41), so a missing or unparseable `styles.yaml` refuses
    before the money gate exactly like a missing API key does.

    Pre-flight owns the finding and `decide_exit_code(preflight_refused=True)` owns the code; both
    halves are asserted here, because either one alone would let a real refusal still exit 0.
    Everything is written inside `tmp_path`, and the built-in tier is pointed at an empty folder
    so "missing" means missing rather than "the repo ships one".
    """
    empty = tmp_path / "no-prompts-here"
    empty.mkdir()
    monkeypatch.setattr("hypesocials.preflight.PROMPTS_DIR", empty)
    config = Config(run=RunConfig())
    config.sources = SourcesConfig(active=["virlo"],
                                   virlo_monitor_ids=["623203a9-1111-2222-3333-444455556666"])
    config.output = OutputConfig(dir=str(tmp_path / "output"))
    config.prompts_dir = str(empty)  # the FR-174 override seam, pointed at nothing

    verdict = preflight.check(config, action="run", entries=[entry(0)])

    assert verdict.ok is False
    assert [line for line in verdict.errors if "styles.yaml" in line], verdict.report
    assert decide_exit_code([entry(0)], preflight_refused=True) == EXIT_PREFLIGHT
    assert preflight.EXIT_PREFLIGHT == EXIT_PREFLIGHT == 2


# ------------------------------------------- FR-248 / D42: COPY_DEGRADED stays a code-1 loss


def test_fr248_copy_degraded_is_the_only_llm_starved_tag_left_and_still_costs_exit_zero() -> None:
    """FR-202 + FR-248, restated for v2.0.0: `COPY_DEGRADED` remains a code-1 loss.

    An explicit D42 decision: under the verbatim contract a failed copy call ships the top post's
    caption verbatim, so the fallback CONTENT is now legitimate — but a failed model call is still
    a loss to surface, and a batch that silently shipped fallback copy is not a full success. The
    latch stamps every hit entry with a `skip_reason`, which is what moves the run off exit 0.

    `analysis_missing` left the `llm_starved` set with the analysis stage, so a creative carrying
    it alone is no longer charged to the latch.
    """
    entries = [entry(0), entry(1)]
    report = SimpleNamespace(records={
        entries[0].asset_id: _record(entries[0].asset_id, DegradationTag.COPY_DEGRADED),
        entries[1].asset_id: _record(entries[1].asset_id, DegradationTag.ANALYSIS_MISSING)})
    session = SimpleNamespace(llm=SimpleNamespace(credits_exhausted=True))

    line = _credits_exhausted_line(session, entries, report)

    assert CREDITS_EXHAUSTED_REASON in line and "FR-248" in line
    assert "1 creative(s) were lost or shipped degraded" in line
    assert entries[0].skip_reason == f"{CREDITS_EXHAUSTED_REASON} (FR-248)"
    assert entries[1].skip_reason is None, "analysis_missing is no longer an llm_starved tag"
    # ... and the stamped reason is what turns the delivered creative into a code-1 loss.
    assert decide_exit_code(entries) == EXIT_PARTIAL


def test_fr248_the_line_is_silent_when_credits_were_never_the_story() -> None:
    """`""` when the 402 latch never tripped — and nothing is stamped, so a clean run stays 0."""
    entries = [entry(0)]
    report = SimpleNamespace(records={entries[0].asset_id: _record(
        entries[0].asset_id, DegradationTag.COPY_DEGRADED)})

    assert _credits_exhausted_line(SimpleNamespace(llm=None), entries, report) == ""
    assert _credits_exhausted_line(
        SimpleNamespace(llm=SimpleNamespace(credits_exhausted=False)), entries, report) == ""
    assert entries[0].skip_reason is None
    assert decide_exit_code(entries) == EXIT_OK


def test_fr248_an_entry_that_already_names_its_own_cause_is_left_alone() -> None:
    """The latch explains creatives that ended with NO cause of their own. One that already
    carries a `skip_reason` keeps it: re-stamping would overwrite the precise cause with the
    general one, and both are exit 1 either way."""
    named = entry(0, PlanEntryStatus.FAILED, skip_reason="kie_timeout")
    report = SimpleNamespace(records={named.asset_id: _record(named.asset_id)})

    _credits_exhausted_line(SimpleNamespace(llm=SimpleNamespace(credits_exhausted=True)),
                            [named], report)

    assert named.skip_reason == "kie_timeout"


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
