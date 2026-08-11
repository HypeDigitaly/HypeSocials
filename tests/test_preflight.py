"""FR-283 — pre-flight refuses a run no active source can serve. The §1.1 reproducer, made permanent.

This file exists because of one logged episode, `20260810_123845_c832`: `virlo` was the only active
source, `sources.virlo_monitor_ids` was `[]`, pre-flight returned `ok=True`, the estimate printed,
**$0.64 was approved**, and only then did the run die on a misconfiguration that was knowable
locally for $0. That contradicts this module's own contract — *"**Refusal is free** (FR-202 code 2):
every check here is local"* — and its FR-135 precedent, where a named-but-unbuilt adapter refuses
*before* the money gate. The reproducer lives here so `configs/default.yaml` can keep shipping
`virlo_monitor_ids: []` (plan §3.4) without the trap being reachable.

Three carve-outs are as load-bearing as the rule itself, and each is one test below:

- `--list-monitors` must survive the very rule that exists to fix it (FR-251): it runs with no valid
  run plan, and it is the ONLY route to the ids the rule demands.
- A brief-only plan consumes no trend and opens no Virlo session (FR-144), so zero monitor ids is
  not a defect for it.
- A **mixed** brief + trend plan is a *warning*, never an error: `prds/10-pipeline.md` §10 mandates
  that such a run ships its briefs and exits 1. Turning that partial success into a total refusal
  that delivers nothing would be a regression, so it is pinned here.

Everything asserts on the **specific message text**, never on `ok` — `ok` also depends on env keys,
free disk space and configured prices, so an `ok`-based assertion would be flaky and would not prove
that this rule fired. `output.dir` is redirected into `tmp_path` because `_check_disk` really does
`mkdir` plus a write probe. Nothing here contacts anything: no network, no MCP, no spend.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from hypesocials.config import Config, OutputConfig, RunConfig, SourcesConfig
from hypesocials.models import PlanEntry
from hypesocials.preflight import EXIT_PREFLIGHT, Preflight, check

#: The exact key the refusal must name — an operator has to know which line to edit (FR-69).
KEY = "sources.virlo_monitor_ids"
#: The only route to a monitor id, so a refusal that omits it is a dead end (FR-251/FR-65).
CURE = "--list-monitors"


# --------------------------------------------------------------------------- fixtures & builders


@pytest.fixture(autouse=True)
def _dummy_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Placeholder values for FR-46's three keys, so a verdict never depends on the workstation.

    D30: no real key and no `.env` read is involved — these are literal placeholders, and they exist
    only so a missing-secret error cannot be mistaken for the supply error under test.
    """
    for name in ("VIRLO_API_KEY", "OPENROUTER_API_KEY", "KIE_API_KEY"):
        monkeypatch.setenv(name, "test-not-a-real-key")
    monkeypatch.delenv("NOTION_TOKEN", raising=False)  # FR-47's warning is not this file's subject


def _config(
    tmp_path: Path,
    *,
    monitor_ids: Sequence[str] = (),
    active: Sequence[str] = ("virlo",),
    **run_kwargs: object,
) -> Config:
    """The `c832` config shape, with `output.dir` inside `tmp_path`.

    Module-local by design (the pattern of `tests/test_plan.py:19`): `conftest.py` carries zero
    fixtures, and `_check_disk` would otherwise `mkdir` and probe the repo's real `output/`.
    """
    cfg = Config(run=RunConfig(**run_kwargs))  # type: ignore[arg-type]
    cfg.sources = SourcesConfig(active=list(active), virlo_monitor_ids=list(monitor_ids))
    cfg.output = OutputConfig(dir=str(tmp_path / "output"))
    return cfg


def _entry(order: int, *, brief: str | None = None, influence: str = "override") -> PlanEntry:
    """One plan entry, carrying the only two fields the supply predicate reads.

    A brief with `influence="override"` needs no trend (FR-144); anything else — including a
    `blend` brief (FR-145) — takes a trend like any other entry and therefore cannot run.
    """
    needs_trend = brief is None or influence != "override"
    return PlanEntry(  # type: ignore[arg-type]
        order=order,
        asset_id=f"Li_img_{brief or 'dance-challenge'}_"
                 f"{'analyzed' if needs_trend else 'direct'}_{order + 1:02d}",
        creative_format="image",
        platform="linkedin",
        language="en",
        aspect_ratio="16:9",
        variant="analyzed" if needs_trend else "direct",
        brief_name=brief,
        brief_influence=influence if brief else None,  # type: ignore[arg-type]
        trend_key="dance-challenge" if needs_trend else None,
    )


def _supply_errors(verdict: Preflight) -> list[str]:
    """Only the errors this rule can produce — every one of them names the key to edit."""
    return [line for line in verdict.errors if KEY in line]


def _supply_warnings(verdict: Preflight) -> list[str]:
    """The warning grade of the same rule. No other check in this module mentions a monitor."""
    return [line for line in verdict.warnings if "monitor" in line.lower()]


# --------------------------------------------------------------------------- (a) the reproducer


def test_fr283_virlo_active_with_no_monitor_ids_refuses_before_the_money_gate(
    tmp_path: Path,
) -> None:
    """The `c832` shape: `virlo` active, `virlo_monitor_ids: []`, a real run. Exit 2, $0 spent.

    Pre-flight is the last free moment. `sources/virlo.py` short-circuits to `[]` before any
    session opens, so this run cannot produce a single creative — arithmetically, from local data
    alone (`20-integrations.md:97` "one per configured monitor id").
    """
    verdict = check(_config(tmp_path), action="run", entries=[_entry(0)])

    assert verdict.ok is False  # exit 2 — the confirm prompt is never reached
    errors = _supply_errors(verdict)
    assert len(errors) == 1, verdict.report
    assert CURE in errors[0]  # FR-69: name the cure, not just the fault
    assert EXIT_PREFLIGHT == 2  # the code `run.bat` must return for acceptance 1


def test_fr283_the_refusal_is_an_error_not_a_warning(tmp_path: Path) -> None:
    """Two grades, deliberately: this one refuses. A warning would let the estimate print and the
    operator approve a run that cannot deliver anything — exactly what `c832` did."""
    verdict = check(_config(tmp_path), action="run", entries=[_entry(0)])

    assert _supply_errors(verdict)
    assert KEY not in " ".join(verdict.warnings)
    assert KEY not in " ".join(verdict.hints)
    assert verdict.report.startswith("pre-flight refused:")


def test_fr283_whitespace_only_monitor_ids_are_not_configured_ids(tmp_path: Path) -> None:
    """"no NON-EMPTY id": a list of blanks reaches Virlo as nothing at all, so it refuses too. A
    check that only counted list length would pass a config that still cannot run."""
    verdict = check(_config(tmp_path, monitor_ids=["", "   "]), action="run",
                    entries=[_entry(0)])

    assert len(_supply_errors(verdict)) == 1, verdict.report


def test_fr283_a_configured_monitor_id_is_the_healthy_case_and_says_nothing(
    tmp_path: Path,
) -> None:
    """The rule must be silent on a runnable config — no error, and no warning either. A check
    that fired on `hypedigitaly.yaml` would be noise every single run."""
    verdict = check(_config(tmp_path, monitor_ids=["623203a9-1111-2222-3333-444455556666"]),
                    action="run", entries=[_entry(0)])

    assert _supply_errors(verdict) == []
    assert _supply_warnings(verdict) == []


def test_fr283_a_source_that_is_not_virlo_is_not_judged_by_virlos_key(tmp_path: Path) -> None:
    """The predicate's first clause is `"virlo" in sources.active`. With virlo inactive the monitor
    list is irrelevant — FR-135's own refusal is the one that speaks for an unbuilt adapter, and
    this rule must not pile a second, misleading line on top of it."""
    verdict = check(_config(tmp_path, active=["google_trends"]), action="run",
                    entries=[_entry(0)])

    assert _supply_errors(verdict) == []
    assert any("google_trends" in line for line in verdict.errors)  # FR-135 still speaks


# --------------------------------------------------------------------------- (b) FR-251 carve-out


def test_fr251_list_monitors_survives_the_rule_that_exists_to_fix_it(tmp_path: Path) -> None:
    """`--list-monitors` runs with no valid run plan (FR-251) — and it is the ONLY route to the ids
    the rule demands. Refusing it would leave an empty config with no cure inside the tool, which
    is precisely the dead end the episode was made of.

    The same config is asserted to refuse under `action="run"`, so this test cannot pass by
    accident on a fixture that was never in the failing state.
    """
    config = _config(tmp_path)

    assert _supply_errors(check(config, action="run", entries=[_entry(0)])), "fixture is not failing"
    assert _supply_errors(check(config, action="list-monitors")) == []


@pytest.mark.parametrize("action", ["preview-sources", "preview-analysis"])
def test_fr283_only_a_run_is_refused_never_a_preview(action: str, tmp_path: Path) -> None:
    """The predicate's second clause is `action == "run"`. A preview spends no Kie/OpenRouter money
    and reports its own emptiness (FR-154 owns `--preview-sources`' exit code), so this rule stays
    out of its way."""
    verdict = check(_config(tmp_path), action=action, entries=[_entry(0)])

    assert _supply_errors(verdict) == [], verdict.report


# --------------------------------------------------------------------------- (c) FR-144 carve-out


def test_fr144_a_brief_only_plan_consumes_no_trend_and_is_not_refused(tmp_path: Path) -> None:
    """An `override` brief creative bypasses trends entirely — no Virlo session is ever opened —
    so zero monitor ids costs it nothing. Refusing here would break the one plan shape that is
    guaranteed to work with an empty config."""
    entries = [_entry(0, brief="ai-audit-cta"), _entry(1, brief="ai-audit-cta")]
    assert all(e.trend_key is None for e in entries)  # nothing in this plan wants a trend

    verdict = check(_config(tmp_path), action="run", entries=entries)

    assert _supply_errors(verdict) == [], verdict.report


def test_fr145_a_blend_brief_still_needs_a_trend_so_the_run_is_refused(tmp_path: Path) -> None:
    """The carve-out is `brief_influence == "override"`, not "has a brief". A `blend` brief expands
    and takes a trend like any other entry (FR-145), so a blend-only plan cannot run either."""
    entries = [_entry(0, brief="case-study", influence="blend")]
    assert entries[0].trend_key is not None

    verdict = check(_config(tmp_path), action="run", entries=entries)

    assert len(_supply_errors(verdict)) == 1, verdict.report


def test_fr283_an_empty_entries_argument_still_refuses(tmp_path: Path) -> None:
    """No entries means nothing proved it can run without a trend, so the refusal stands. `check()`
    defaults `entries=()` and several callers pass nothing; a fail-open default here would let the
    reproducer back in through the front door."""
    verdict = check(_config(tmp_path), action="run")

    assert len(_supply_errors(verdict)) == 1, verdict.report


# --------------------------------------------------------------------------- (d) the mixed plan


def test_10pipeline_mixed_brief_and_trend_plan_warns_and_is_never_refused(tmp_path: Path) -> None:
    """`10-pipeline.md` §10: a run whose briefs can ship **ships them and exits 1**.

    THE regression this file guards. An earlier draft of the plan made this shape an error, which
    would have converted a documented partial success (briefs delivered, exit 1) into a total
    refusal that delivers nothing and exits 2. The trend-backed entries drop; the brief creative
    is still bought.
    """
    brief = _entry(0, brief="ai-audit-cta")
    dropping = [_entry(1), _entry(2), _entry(3)]

    verdict = check(_config(tmp_path), action="run", entries=[brief, *dropping])

    assert _supply_errors(verdict) == [], verdict.report  # not a refusal
    warnings = _supply_warnings(verdict)
    assert len(warnings) == 1, verdict.report
    line = warnings[0]
    assert CURE in line  # the cure, on the warning too
    # "identifies the entries that will drop" — either by id or by count; both are the contract.
    assert any(e.asset_id in line for e in dropping) or str(len(dropping)) in line, line


def test_10pipeline_one_override_brief_is_what_flips_error_into_warning(tmp_path: Path) -> None:
    """The same trend-backed plan, twice: with an override brief beside it, and without.

    The grade must move, and only the grade — same key, same cure, same config. This is the pair
    that proves the predicate reads `brief_influence` rather than merely counting entries.
    """
    config = _config(tmp_path)
    trend_only = check(config, action="run", entries=[_entry(0)])
    mixed = check(config, action="run", entries=[_entry(0, brief="ai-audit-cta"), _entry(1)])

    assert len(_supply_errors(trend_only)) == 1 and _supply_warnings(trend_only) == []
    assert _supply_errors(mixed) == [] and len(_supply_warnings(mixed)) == 1


# --------------------------------------------------------------------------- refusal is free


def test_refusal_is_free_nothing_but_the_disk_probe_touches_the_filesystem(
    tmp_path: Path,
) -> None:
    """FR-255's probe is written INSIDE `output.dir` and removed again, and it is the only file
    pre-flight is allowed to create. The run folder is not made, no log is written, and the repo's
    real `output/` and `logs/` are never involved — a refusal that cost something would not be free.
    """
    config = _config(tmp_path)

    verdict = check(config, action="run", entries=[_entry(0)])

    out = Path(config.output.dir)
    assert out.is_dir()
    assert list(out.iterdir()) == []  # the probe was cleaned up, nothing else was written
    assert sorted(p.name for p in tmp_path.iterdir()) == ["output"]
    assert verdict.estimated_bytes > 0  # FR-255 still sized the run it refused
