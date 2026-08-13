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

The tail sections are the post-pivot additions (v2.0.0), folded in by T3.5: FR-295's registry
refusal — the meta-style registry is the visual authority and has NO built-in tier (D41), so a
missing `styles.yaml` is exit 2 rather than a silent default — FR-292's branding validation, and
FR-286's wrapping of `Preflight.report`, whose lines grew past one console line once the hints
started explaining a verbatim-copy pipeline.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from hypesocials.config import (
    Config, OutputConfig, RunConfig, SourcesConfig, formats_sourcing_violation, windows_violation,
)
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

    A brief with `influence="override"` needs no topic (FR-144); anything else — including a
    `blend` brief (FR-145) — takes a topic like any other entry and therefore cannot run. The
    asset id is FR-71's post-pivot four-segment shape; the variant tag is withdrawn (v2.0.0).
    """
    needs_topic = brief is None or influence != "override"
    return PlanEntry(  # type: ignore[arg-type]
        order=order,
        asset_id=f"Li_img_{brief or 'dance-challenge'}_{order + 1:02d}",
        creative_format="image",
        platform="linkedin",
        language="en",
        aspect_ratio="16:9",
        brief_name=brief,
        brief_influence=influence if brief else None,  # type: ignore[arg-type]
        trend_key="m1::dance-challenge" if needs_topic else None,
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


# -------------------------------------------------- (e) FR-295 registry / FR-292 branding
#
# Every registry here is built inside `tmp_path` and reached through `config.prompts_dir` (the
# FR-174 override-first seam), so these tests never depend on the shipped `prompts/styles.yaml` —
# and a broken shipped registry would fail them for the right reason rather than by accident.

_ONE_IMAGE_STYLE = """
version: 1
styles:
  - key: only-image
    render_prompt: A flat studio photograph, one product, one light.
    format_affinity: [image]
"""
_BROKEN_REFERENCE = _ONE_IMAGE_STYLE + '    reference_images: ["Inspiration/does-not-exist.png"]\n'


def _no_shipped_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the built-in tier at an empty folder, so "missing" means missing.

    `load_registry` searches `(config.prompts_dir, PROMPTS_DIR)` and the repo really does ship a
    `prompts/styles.yaml` — without this the override-miss tests below would silently be testing
    the shipped registry instead of the absence of one.
    """
    empty = tmp_path / "no-prompts-here"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr("hypesocials.preflight.PROMPTS_DIR", empty)


def _registry(tmp_path: Path, text: str) -> str:
    """Write a `styles.yaml` into its own folder and return that folder as a `prompts_dir`."""
    folder = tmp_path / "prompts"
    folder.mkdir(exist_ok=True)
    (folder / "styles.yaml").write_text(text, encoding="utf-8")
    return str(folder)


def _styled_config(tmp_path: Path, registry: str | None = _ONE_IMAGE_STYLE, **kwargs: object):
    """A runnable config (one monitor id, so FR-283 stays quiet) pointed at a private registry."""
    config = _config(tmp_path, monitor_ids=["623203a9-1111-2222-3333-444455556666"], **kwargs)
    config.prompts_dir = _registry(tmp_path, registry) if registry is not None else str(tmp_path)
    return config


def _style_errors(verdict: Preflight) -> list[str]:
    return [line for line in verdict.errors if "styles.yaml" in line or "style" in line]


def test_fr295_a_missing_registry_refuses_the_run_and_names_where_it_looked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-295: the registry has no built-in tier (D41), so "not found" is exit 2, not a default.

    The line has to name the folders searched: an override `prompts_dir` that silently misses is
    otherwise indistinguishable from a repo whose `prompts/styles.yaml` was never authored.
    """
    _no_shipped_registry(monkeypatch, tmp_path)
    verdict = check(_styled_config(tmp_path, registry=None), action="run", entries=[_entry(0)])

    assert verdict.ok is False
    missing = [line for line in verdict.errors if "styles.yaml" in line]
    assert len(missing) == 1, verdict.report
    assert str(tmp_path) in missing[0] and "FR-290/295" in missing[0]
    assert EXIT_PREFLIGHT == 2


def test_fr295_a_requested_format_with_no_affine_style_refuses(tmp_path: Path) -> None:
    """"every format with a requested count >0 has ≥1 affine style under the active brand" — a
    registry that can only dress images cannot deliver the two carousels this config asks for."""
    config = _styled_config(tmp_path)
    config.run.formats = {"image": 4, "carousel": 2, "reel": 0}

    verdict = check(config, action="run", entries=[_entry(0)])

    carousel = [line for line in verdict.errors if "carousel" in line]
    assert verdict.ok is False and len(carousel) == 1, verdict.report
    assert "run.formats.carousel" in carousel[0]  # FR-69: name the line to edit

    config.run.formats = {"image": 4, "carousel": 0, "reel": 0}  # ... and it is silent otherwise
    assert _style_errors(check(config, action="run", entries=[_entry(0)])) == []


def test_d46_a_registry_that_still_lists_pictures_produces_no_finding_at_all(
    tmp_path: Path,
) -> None:
    """D46/FR-17/18 replaced FR-295's reference-image clause with nothing: a meta-style is TEXT,
    declares no pictures, and therefore has none that can be missing. A stale `styles.yaml` that
    still carries the dead key must load, validate silently and cost the operator neither a
    refusal nor a warning about a file no render job would have attached anyway.
    """
    config = _styled_config(tmp_path, registry=_BROKEN_REFERENCE)
    config.run.formats = {"image": 2, "carousel": 0, "reel": 0}

    verdict = check(config, action="run", entries=[_entry(0)])

    assert _style_errors(verdict) == [], verdict.report
    assert [line for line in verdict.warnings if "does-not-exist" in line] == []
    assert [line for line in verdict.warnings if "style_refs_missing" in line] == []


def test_fr295_the_registry_is_not_read_where_no_style_is_ever_assigned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--list-monitors` (FR-251) and `--preview-sources` ($0 blocklist preview, FR-139) assign no
    style. Refusing them on a registry they never read would break the commands that fix a config.
    """
    _no_shipped_registry(monkeypatch, tmp_path)
    config = _styled_config(tmp_path, registry=None)

    for action in ("list-monitors", "preview-sources"):
        assert [line for line in check(config, action=action).errors
                if "styles.yaml" in line] == [], action
    assert [line for line in check(config, action="preview-analysis").errors
            if "styles.yaml" in line], "preview-analysis assigns styles and must still refuse"


def test_fr292_a_brand_selector_with_no_profile_refuses(tmp_path: Path) -> None:
    """FR-292: `brand` selects one of `profiles`. `config._validate` fails the LOAD on this, so the
    check here is the backstop for a `Config` built in code — without it the first symptom is a
    `KeyError` inside the prompt engine, after the money gate."""
    config = _styled_config(tmp_path)
    config.branding.brand = "hypemystery"

    verdict = check(config, action="run", entries=[_entry(0)])

    brand = [line for line in verdict.errors if "branding.brand" in line]
    assert verdict.ok is False and len(brand) == 1, verdict.report
    assert "hypedigitaly" in brand[0] and "hypelead" in brand[0]  # name what IS defined


def test_fr292_branding_findings_that_only_warn(tmp_path: Path) -> None:
    """Two runtime facts the config loader cannot judge: a branded run with nothing to sign with,
    and FR-292's web-only orange in a brand profile. Both are wrong, neither is unrunnable."""
    config = _styled_config(tmp_path)
    config.run.formats = {"image": 2, "carousel": 0, "reel": 0}
    profile = config.branding.profiles[config.branding.brand]
    profile.wordmark = ""
    profile.colors["accent"] = "#F97316"
    config.branding.brand_ratio = 0.5

    verdict = check(config, action="run", entries=[_entry(0)])

    assert _style_errors(verdict) == [] and not [l for l in verdict.errors if "branding" in l]
    assert len([line for line in verdict.warnings if "wordmark is empty" in line]) == 1
    assert len([line for line in verdict.warnings if "WEB-ONLY" in line]) == 1


def test_f22_the_diacritics_hint_follows_the_source_post_not_the_configured_language(
    tmp_path: Path,
) -> None:
    """§1.7 F22: on-image text is quoted verbatim in the SOURCE post's language, so an `en` config
    can still render accented glyphs. The hint therefore fires on a verbatim (trend-backed) plan,
    and stays silent for an override-brief plan, whose language really is config's."""
    config = _styled_config(tmp_path)
    config.run.formats = {"image": 2, "carousel": 0, "reel": 0}
    assert set(config.run.languages.values()) == {"en"} and not config.run.vision_check

    verbatim = check(config, action="run", entries=[_entry(0)])
    brief_only = check(config, action="run", entries=[_entry(0, brief="ai-audit-cta")])

    assert len([hint for hint in verbatim.hints if "verbatim" in hint]) == 1, verbatim.report
    assert [hint for hint in brief_only.hints if "verbatim" in hint] == []


def test_f22_a_czech_config_still_gets_the_certain_hint_rather_than_the_possible_one(
    tmp_path: Path,
) -> None:
    """The two hints are siblings, and only one fires: a configured `cs` is a CERTAINTY (it decides
    brief-override creatives and every degrade path), where a verbatim creative is only a
    possibility. Printing both would say the same thing twice with two confidences."""
    config = _styled_config(tmp_path, languages={"linkedin": "cs"}, platforms=["linkedin"])
    config.run.formats = {"image": 2, "carousel": 0, "reel": 0}

    hints = check(config, action="run", entries=[_entry(0)]).hints

    assert len([hint for hint in hints if "linkedin render Czech text" in hint]) == 1, hints
    assert [hint for hint in hints if "quoted verbatim" in hint] == []
    # ... and the check being ON silences the whole family: something IS reading the glyphs back.
    config.run.vision_check = True
    assert check(config, action="run", entries=[_entry(0)]).hints == ()


def test_fr286_the_report_wraps_long_lines_instead_of_overflowing_the_console(
    tmp_path: Path,
) -> None:
    """`Preflight.report` wraps every grade at 76 columns (`util.wrapped`), continuations indented
    by two, so the whole block honours FR-286's 78-column ceiling.

    Wrapping lives at the PRINTER and not in the data: the same strings land in events.jsonl, and
    layout baked into them would travel there too. It became load-bearing post-pivot because the
    hints grew — FR-294's verbatim-language hint is a three-clause sentence explaining why an
    `en` config may still render accented glyphs — and a `fit()`-style truncation would have cut
    the cure off the end of the very line that names it.
    """
    config = _styled_config(tmp_path)
    config.run.formats = {"image": 2, "carousel": 0, "reel": 0}

    report = check(config, action="run", entries=[_entry(0)]).report
    lines = report.splitlines()

    assert lines and any(line.startswith("hint: ") for line in lines)
    assert len(lines) > 1, "the verbatim hint alone is longer than one console line"
    # A filesystem path is the one token `wrapped` cannot break — it carries no whitespace — so a
    # line that is nothing but this test's very long `tmp_path` is excluded, exactly as FR-286
    # carves out the bare permalink in the FR-297b post roster. A shipped `prompts/styles.yaml`
    # path fits with room to spare; a pytest temp directory does not.
    for line in (row for row in lines if str(tmp_path) not in row):
        assert len(line) <= 78, f"{len(line)} chars (FR-286 allows 78): {line!r}"
    continuations = [line for line in lines if line.startswith("  ")]
    assert continuations, "a wrapped grade must be visibly a continuation, not a new finding"
    # No word was cut in half by the wrap: rejoining the parts restores the original sentence.
    assert "consider --vision-check" in " ".join(line.strip() for line in lines)


# ------------------------------------------- (f) FR-138: the two config PAIRS, re-run post-flags
#
# `config._validate` refuses both pairs when the FILE loads. `cli.apply_overrides` then mutates the
# same object — `--history-days 7`, `--images 4` — and nothing re-validates it, so pre-flight is
# the only door the overridden config still passes through before the confirm gate. These tests
# build the mutated shape directly, which is exactly what a flag leaves behind.


def _pair_errors(verdict: Preflight, needle: str) -> list[str]:
    return [line for line in verdict.errors if needle in line]


def test_fr307_a_history_window_narrowed_by_a_flag_is_refused_at_preflight(
    tmp_path: Path,
) -> None:
    """The `--history-days 7` bypass: a 7-day memory over a 30-day fetch window leaves a band of
    days in which a post is forgotten by history and still fetchable — the run re-quotes, word for
    word, something it already published. The file loaded clean at 30/30; the flag broke the pair
    afterwards, so the refusal has to be reachable here (FR-138/FR-307) and must name BOTH keys.
    """
    config = _styled_config(tmp_path, trend_history_days=7)  # what `--history-days 7` leaves
    config.sources.max_post_age_days = 30

    verdict = check(config, action="run", entries=[_entry(0)])

    refusals = _pair_errors(verdict, "run.trend_history_days")
    assert verdict.ok is False and len(refusals) == 1, verdict.report
    assert "sources.max_post_age_days" in refusals[0] and "FR-307" in refusals[0]
    assert "7" in refusals[0] and "30" in refusals[0]  # both VALUES, not just both key names


def test_fr307_zero_history_and_a_wide_enough_window_are_both_silent(tmp_path: Path) -> None:
    """`trend_history_days: 0` is the deliberate opt-out — the operator has said out loud that
    repeats are acceptable — and any window at least as wide as the fetch is simply correct."""
    for history in (0, 30, 45):
        config = _styled_config(tmp_path, trend_history_days=history)
        config.sources.max_post_age_days = 30

        verdict = check(config, action="run", entries=[_entry(0)])

        assert _pair_errors(verdict, "run.trend_history_days") == [], verdict.report


def test_ss0_14e_image_entries_under_slideshow_only_sourcing_are_refused(tmp_path: Path) -> None:
    """§0.14e/FR-132: with `include_videos: false` every topic is slideshow-majority, so an image
    or reel creative can only rank-fallback onto a post it cannot quote properly — silently, and
    forever. `--images 4` walks a carousel-only config into exactly that, after the load."""
    config = _styled_config(tmp_path)
    config.sources.include_videos = False
    config.run.formats = {"image": 4, "carousel": 0, "reel": 0}

    verdict = check(config, action="run", entries=[_entry(0), _entry(1)])

    refusals = _pair_errors(verdict, "sources.include_videos")
    assert verdict.ok is False and len(refusals) == 1, verdict.report
    assert "2 image" in refusals[0], "the count comes from the PLAN, not from run.formats"
    assert "§0.14e" in refusals[0] and "FR-132" in refusals[0]


def test_ss0_14d_override_brief_image_entries_never_fire_the_formats_guard(
    tmp_path: Path,
) -> None:
    """§0.14d's carve-out: an `override`-influence brief binds no source post at all (FR-144), so
    slideshow-only sourcing cannot starve it. A plan of nothing but override-brief images is a
    perfectly runnable run, and refusing it would delete the one route that needs no topic.
    """
    config = _styled_config(tmp_path)
    config.sources.include_videos = False
    config.run.formats = {"image": 2, "carousel": 0, "reel": 0}
    overrides = [_entry(0, brief="ai-audit-cta"), _entry(1, brief="ai-audit-cta")]

    verdict = check(config, action="run", entries=overrides)

    assert _pair_errors(verdict, "sources.include_videos") == [], verdict.report

    # ... and one blend brief among them is NOT exempt: FR-145 gives it a topic like anything else.
    mixed = [*overrides, _entry(2, brief="webinar", influence="blend")]
    assert len(_pair_errors(check(config, action="run", entries=mixed),
                            "sources.include_videos")) == 1


def test_ss0_14e_with_no_plan_at_all_the_guard_falls_back_to_the_configured_counts(
    tmp_path: Path,
) -> None:
    """An empty `entries` is the load-time question asked one stage later — there is no plan to
    read, so `run.formats` is the only statement of intent there is."""
    config = _styled_config(tmp_path)
    config.sources.include_videos = False
    config.run.formats = {"image": 3, "carousel": 0, "reel": 0}

    refusals = _pair_errors(check(config, action="run"), "sources.include_videos")

    assert len(refusals) == 1 and "3 image" in refusals[0]


def test_both_doors_speak_one_sentence_never_two_copies_of_it(tmp_path: Path) -> None:
    """The refusal WORDING lives in `config.py` and is imported, never retyped: the load path
    prefixes it with the file name and raises, pre-flight appends it to `errors`. Two copies of an
    operator-facing sentence drift the moment one is edited, and the operator then gets different
    advice depending on whether the mistake was in the file or in a flag."""
    config = _styled_config(tmp_path, trend_history_days=7)
    config.sources.max_post_age_days = 30
    config.sources.include_videos = False
    config.run.formats = {"image": 4, "carousel": 0, "reel": 0}

    verdict = check(config, action="run", entries=[_entry(0)])

    assert windows_violation(config) in verdict.errors
    assert formats_sourcing_violation(config, counts={"image": 1, "reel": 0}) in verdict.errors


def test_the_zero_dollar_cure_paths_are_never_refused_by_either_pair(tmp_path: Path) -> None:
    """FR-251's precedent, applied to both guards: `--list-monitors` and `--preview-sources` are
    the $0 diagnostics an operator runs to FIX a config, and a config error must never disarm its
    own cure. `--preview-analysis` is NOT exempt — it reaches the fetch gate and the affinity
    assignment both pairs govern, and it spends real OpenRouter money doing it.
    """
    config = _styled_config(tmp_path, trend_history_days=7)
    config.sources.max_post_age_days = 30
    config.sources.include_videos = False
    config.run.formats = {"image": 4, "carousel": 0, "reel": 0}

    for action in ("list-monitors", "preview-sources"):
        verdict = check(config, action=action, entries=[_entry(0)])
        assert _pair_errors(verdict, "run.trend_history_days") == [], action
        assert _pair_errors(verdict, "sources.include_videos") == [], action

    deep = check(config, action="preview-analysis", entries=[_entry(0)])
    assert len(_pair_errors(deep, "run.trend_history_days")) == 1
    assert len(_pair_errors(deep, "sources.include_videos")) == 1


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
