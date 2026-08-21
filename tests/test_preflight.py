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
from hypesocials import codex_proxy
from hypesocials import preflight as preflight_module
from hypesocials.preflight import EXIT_PREFLIGHT, Preflight, check, collect_secrets

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


def test_fr304b_a_malformed_list_mode_refuses_the_run_through_the_same_registry_door(
    tmp_path: Path,
) -> None:
    """v2.2.0: a half-read list treatment is registry-invalid, so it lands where every other
    unusable registry lands — exit 2 at pre-flight, $0 spent, one line naming the file and key."""
    broken = _ONE_IMAGE_STYLE + "    list_mode:\n      reflow_over_chars: 180\n      max_rows: 6\n"
    config = _styled_config(tmp_path, registry=broken)
    config.run.formats = {"image": 1, "carousel": 0, "reel": 0}

    verdict = check(config, action="run", entries=[_entry(0)])

    assert verdict.ok is False
    found = [line for line in verdict.errors if "list_mode" in line]
    assert len(found) == 1 and "layout" in found[0], verdict.report


def test_a_stale_prompts_dir_screen_override_is_warned_about_and_never_refused(
    tmp_path: Path,
) -> None:
    """An operator's own `topic_filter_system.md` copied before `{{audience_profile}}` existed still
    screens — it just answers `language`/`audience_fit` from nothing, so the screen degrades
    fail-open and off-audience topics start passing again. Nothing errors and nothing logs a break,
    which is exactly why pre-flight has to say it out loud. A current override says nothing."""
    config = _styled_config(tmp_path)
    override = Path(config.prompts_dir) / "topic_filter_system.md"
    override.write_text("Screen these topics.\n\n{{topic_items}}\n{{competitor_list}}\n",
                        encoding="utf-8")
    config.run.formats = {"image": 1, "carousel": 0, "reel": 0}
    config.sources.include_videos = True  # §0.14e: an image plan needs video-sourced posts

    stale = check(config, action="run", entries=[_entry(0)])
    override.write_text("Audience: {{audience_profile}}\n{{topic_items}}\n{{competitor_list}}\n",
                        encoding="utf-8")
    current = check(config, action="run", entries=[_entry(0)])

    warned = [line for line in stale.warnings if "audience_profile" in line]
    assert stale.ok is True and len(warned) == 1, stale.report
    assert str(override) in warned[0]
    assert not [line for line in current.warnings if "audience_profile" in line]
    # No override at all is the shipped tree's business, never an operator warning.
    override.unlink()
    assert not [line for line in check(config, action="run", entries=[_entry(0)]).warnings
                if "audience_profile" in line]


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


_TWO_STYLES = _ONE_IMAGE_STYLE + """
  - key: only-deck
    render_prompt: A letterpress card, one line of type, wide margins.
    format_affinity: [carousel]
"""


def test_fr314_a_style_selection_is_graded_at_preflight_and_costs_nothing_to_get_wrong(
    tmp_path: Path,
) -> None:
    """FR-314's selector rides the SAME door as FR-295's registry checks, which is what makes a
    mistyped `--styles` cost $0 rather than a plan: `cli.apply_overrides` mutates the config before
    `check` runs, so the flag's selection is what pre-flight grades, and both of its refusals —
    an unknown key, and a selection that empties a requested format's pool — land as exit-2 errors
    here alongside the brand's. A selector validated at config LOAD time would never see the flag.
    """
    config = _styled_config(tmp_path, registry=_TWO_STYLES)
    config.run.formats = {"image": 0, "carousel": 2, "reel": 0}

    assert _style_errors(check(config, action="run", entries=[_entry(0)])) == []

    config.styles.enabled = ["only-image", "only-dekc"]  # one real key, one typo
    verdict = check(config, action="run", entries=[_entry(0)])

    assert verdict.ok is False and EXIT_PREFLIGHT == 2
    unknown = [line for line in verdict.errors if "styles.enabled names" in line]
    assert len(unknown) == 1, verdict.report
    assert "only-dekc" in unknown[0]
    assert "only-deck" in unknown[0], "the line names the keys the registry really defines"
    # The typo also leaves the carousel rotation empty, and THAT line blames the selector.
    carousel = [line for line in verdict.errors if "carousel" in line]
    assert len(carousel) == 1 and "styles.enabled" in carousel[0], verdict.report

    config.styles.enabled = ["only-image", "only-deck"]  # spelled right: silent again
    assert _style_errors(check(config, action="run", entries=[_entry(0)])) == []


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
    and FR-292's web-only orange in a brand profile. Both are wrong, neither is unrunnable.

    `enabled=True` is now explicit in the fixture, because FR-318 (v2.1.3/D48) made the master
    switch default to FALSE and the empty-wordmark warning is skipped while it is off. The finding
    is about creatives this run will actually sign, and with nothing being signed there is nothing
    to warn about — so the coverage moves to a run that HAS the switch on.
    """
    config = _styled_config(tmp_path)
    config.run.formats = {"image": 2, "carousel": 0, "reel": 0}
    config.branding.enabled = True
    profile = config.branding.profiles[config.branding.brand]
    profile.wordmark = ""
    profile.colors["accent"] = "#F97316"
    config.branding.brand_ratio = 0.5

    verdict = check(config, action="run", entries=[_entry(0)])

    assert _style_errors(verdict) == [] and not [l for l in verdict.errors if "branding" in l]
    assert len([line for line in verdict.warnings if "wordmark is empty" in line]) == 1
    assert len([line for line in verdict.warnings if "WEB-ONLY" in line]) == 1


def test_fr318_an_unsigned_run_is_not_warned_about_the_wordmark_it_will_never_render(
    tmp_path: Path,
) -> None:
    """The complement, on the SAME config: switch branding off and the empty-wordmark warning goes.

    FR-318's switch removes work, it can never make a runnable config unrunnable — so no new
    refusal appears — and warning about an unrendered wordmark anyway would train the operator to
    scroll past the branding warnings that DO mean something the day they flip the switch back on.
    The web-only orange is deliberately NOT part of that: it is a colour a human typed into a
    brand profile and it is wrong in the file whatever this run signs.
    """
    config = _styled_config(tmp_path)
    config.run.formats = {"image": 2, "carousel": 0, "reel": 0}
    config.branding.enabled = True
    profile = config.branding.profiles[config.branding.brand]
    profile.wordmark = ""
    config.branding.brand_ratio = 0.5

    signed = check(config, action="run", entries=[_entry(0)])
    config.branding.enabled = False
    unsigned = check(config, action="run", entries=[_entry(0)])

    assert len([line for line in signed.warnings if "wordmark is empty" in line]) == 1
    assert [line for line in unsigned.warnings if "wordmark is empty" in line] == []
    assert [line for line in unsigned.warnings if "branding" in line] == [], \
        "no branding warning at all survives the switch being off"
    assert unsigned.errors == signed.errors, \
        "the switch removes work; it can never refuse a config that was runnable"


def test_f22_the_diacritics_hint_follows_the_source_post_not_the_configured_language(
    tmp_path: Path,
) -> None:
    """§1.7 F22: on-image text is quoted verbatim in the SOURCE post's language, so an `en` config
    can still render accented glyphs. The hint therefore fires on a verbatim (trend-backed) plan,
    and stays silent for an override-brief plan, whose language really is config's."""
    config = _styled_config(tmp_path)
    config.run.formats = {"image": 2, "carousel": 0, "reel": 0}
    config.run.gauntlet.enabled = False  # the hint family only exists when the gate is off
    assert set(config.run.languages.values()) == {"en"}
    assert not config.run.gauntlet.enabled

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
    config.run.gauntlet.enabled = False  # the hint family only exists when the gate is off

    hints = check(config, action="run", entries=[_entry(0)]).hints

    assert len([hint for hint in hints if "linkedin render Czech text" in hint]) == 1, hints
    assert [hint for hint in hints if "quoted verbatim" in hint] == []
    # ... and the check being ON silences the whole family: something IS reading the glyphs back.
    config.run.gauntlet.enabled = True
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
    # The wrap subject is the verbatim hint, which only exists with the gate off (v2.2.0).
    config.run.gauntlet.enabled = False

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
    assert "consider --gauntlet" in " ".join(line.strip() for line in lines)


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


# ------------------------------------------ FR-333 / D54: the copy mode, stated before the money


def _deck(order: int) -> PlanEntry:
    """A trend-backed CAROUSEL — the only shape `carousel_copy_mode` can reach (FR-331 scope)."""
    entry = _entry(order)
    entry.creative_format = "carousel"  # type: ignore[assignment]
    entry.aspect_ratio = "1:1"
    entry.slide_count = 6
    return entry


def test_fr333_a_compress_mode_run_says_so_at_the_screen_before_the_money_moves(
    tmp_path: Path,
) -> None:
    """FR-333's pre-flight display obligation, through the real `check()`.

    Compress is an operator toggle, and pre-flight is the last screen before the Confirm gate — so
    a run whose slides will carry a MODEL's shortening of somebody's panels rather than those
    panels has to say so where the operator is already reading about what will land on a frame.
    It rides the language hint because that is the sharper question under this mode: a compressed
    line is written rather than copied, so drifting out of the source's language is a failure
    verbatim mode does not have, and the `translated` defect blocks a whole deck.
    """
    config = _styled_config(tmp_path, registry=_TWO_STYLES)
    config.run.formats = {"image": 0, "carousel": 2, "reel": 0}
    config.run.gauntlet.enabled = False  # the hint family only exists when the gate is off
    config.run.carousel_copy_mode = "compress"

    verdict = check(config, action="run", entries=[_deck(0)])

    hints = [hint for hint in verdict.hints if "compressed from the source post" in hint]
    assert len(hints) == 1, verdict.report
    assert "carousel_copy_mode: compress" in hints[0], "the KEY is named, so the cure is printed"
    assert "in the post's own language" in hints[0]
    assert "FR-331" in hints[0] and "consider --gauntlet" in hints[0]
    assert [hint for hint in verdict.hints if "quoted verbatim" in hint] == [], \
        "one hint, one confidence: the verbatim sibling must not fire alongside it"
    assert verdict.ok, "a mode is never a refusal — it is a fact about what the run will render"


def test_fr353_an_auto_mode_run_says_auto_and_says_which_panels_it_touches(
    tmp_path: Path,
) -> None:
    """D62's arm of the same hint. `auto` is what the three brand configs pin, so this is the line
    almost every real run prints at the last screen before the money moves — and it has to say two
    things `compress` did not: that the mode is `auto`, and that only the panels over the assigned
    style's budget are compressed while the rest ship verbatim. An operator who read "compressed"
    with no qualifier would think the whole deck was rewritten, which is the fear D58 withdrew the
    compress pin over."""
    config = _styled_config(tmp_path, registry=_TWO_STYLES)
    config.run.formats = {"image": 0, "carousel": 2, "reel": 0}
    config.run.gauntlet.enabled = False
    config.run.carousel_copy_mode = "auto"

    verdict = check(config, action="run", entries=[_deck(0)])

    hints = [hint for hint in verdict.hints if "compressed from the source post" in hint]
    assert len(hints) == 1, verdict.report
    assert "carousel_copy_mode: auto" in hints[0], "the KEY and the mode in force are named"
    assert "only the panels over the style's budget are compressed" in hints[0]
    assert "the rest ship verbatim" in hints[0]
    assert "FR-353" in hints[0] and "consider --gauntlet" in hints[0]
    assert "carousel_copy_mode: compress" not in hints[0], "the mode named is the one in force"
    assert [hint for hint in verdict.hints if "quoted verbatim" in hint] == []
    assert verdict.ok, "a mode is never a refusal — it is a fact about what the run will render"


def test_fr333_the_same_plan_in_verbatim_mode_prints_the_pre_d54_hint_unchanged(
    tmp_path: Path,
) -> None:
    """The regression half. `verbatim` is the engine-wide default, so the overwhelming majority of
    runs must see exactly the sentence they saw before D54 — the two hints are one branch, and an
    edit to the compress arm that leaked into this one would change what every default run says
    about its own copy at the last screen before it spends."""
    config = _styled_config(tmp_path, registry=_TWO_STYLES)
    config.run.formats = {"image": 0, "carousel": 2, "reel": 0}
    config.run.gauntlet.enabled = False
    assert config.run.carousel_copy_mode == "verbatim", "the default, not set by this test"

    verdict = check(config, action="run", entries=[_deck(0)])

    hints = [hint for hint in verdict.hints if "quoted verbatim" in hint]
    assert len(hints) == 1, verdict.report
    assert hints[0].startswith("on-image text is quoted verbatim from the source post, in that "
                               "post's own language (FR-294)")
    assert "compress" not in hints[0]


def test_fr333_an_images_only_run_in_compress_mode_says_nothing_about_compressing(
    tmp_path: Path,
) -> None:
    """FR-331's scope, enforced at the display: `carousel_copy_mode` governs BOUND CAROUSEL decks
    and nothing else. Claiming a compress contract over a batch of single images would be a false
    statement at the screen the operator is about to approve spend from — and false statements at
    that screen are exactly what pre-flight exists to prevent."""
    config = _styled_config(tmp_path)
    config.run.formats = {"image": 2, "carousel": 0, "reel": 0}
    config.run.gauntlet.enabled = False
    config.run.carousel_copy_mode = "compress"

    verdict = check(config, action="run", entries=[_entry(0)])

    assert [hint for hint in verdict.hints if "compressed from the source post" in hint] == []
    assert len([hint for hint in verdict.hints if "quoted verbatim" in hint]) == 1, verdict.report


def test_fr333_an_override_brief_deck_in_compress_mode_is_out_of_scope_too(
    tmp_path: Path,
) -> None:
    """The other half of the scope rule: an override brief binds no source post (§0.14d), so it
    has no panels to compress and takes its own free-text path in a compress-mode run. With no
    verbatim creative in the plan either, the whole hint family stays silent — which is the same
    answer this plan got before D54."""
    config = _styled_config(tmp_path, registry=_TWO_STYLES)
    config.run.formats = {"image": 0, "carousel": 2, "reel": 0}
    config.run.gauntlet.enabled = False
    config.run.carousel_copy_mode = "compress"
    brief_deck = _entry(0, brief="ai-audit-cta")
    brief_deck.creative_format = "carousel"  # type: ignore[assignment]

    verdict = check(config, action="run", entries=[brief_deck])

    assert [hint for hint in verdict.hints if "compressed from the source post" in hint] == []
    assert [hint for hint in verdict.hints if "quoted verbatim" in hint] == []


# ---- D63 ------------------ FR-345: what `copy_language_mode: target` cannot reach, said once


def _language_warnings(verdict: Preflight) -> list[str]:
    """Only FR-345's own warning. Every other line in the verdict names something else."""
    return [line for line in verdict.warnings if "copy_language_mode: target" in line]


def test_fr345_target_mode_warns_that_images_reels_and_briefs_ship_their_source_language(
    tmp_path: Path,
) -> None:
    """The gap between what `target` promises on screen and what it can actually deliver.

    Translation is scoped to BOUND carousel decks (FR-343): the deck has a source post, its panels
    map one to one, and "translate these exact lines" therefore has an answer. An image quotes a
    hook, a reel quotes a caption and an override brief writes from a file — none of them has that
    shape, so all three ship whatever language their material was in.

    Nothing else on screen says so. The confirm notice and the launch summary both read "bound
    decks translated to en", which on a plan holding four images is a true sentence an operator
    will reasonably read as a false one. Hence one warning, and a COUNT rather than a list: nine
    asset ids would run past the line width, and the number is what the decision turns on.
    """
    config = _styled_config(tmp_path, registry=_TWO_STYLES)
    config.run.formats = {"image": 1, "carousel": 2, "reel": 0}
    config.run.copy_language_mode = "target"
    config.sources.include_videos = True  # §0.14e: an image plan needs video-sourced posts
    override = _deck(2)
    override.brief_name, override.brief_influence = "ai-audit-cta", "override"

    verdict = check(config, action="run",
                    entries=[_deck(0), _entry(1), override])  # one bound deck, one image, one brief

    warned = _language_warnings(verdict)
    assert len(warned) == 1, verdict.report
    assert "reaches bound carousel decks only" in warned[0]
    assert "2 image/reel/override creative(s)" in warned[0], \
        "the bound deck is reached and must not be counted against the mode"
    assert "ship their source language" in warned[0] and "FR-345" in warned[0]
    assert verdict.ok, "a scope gap is a fact about the plan, never a refusal"
    # FR-286 on THIS warning's own printed lines. The whole report is not asserted, because a
    # tmp_path in a disk message is one unbreakable token and no wrapper can shorten it.
    printed = [line for line in verdict.report.splitlines()
               if "copy_language_mode" in line or "image/reel/override" in line]
    assert printed and all(len(line) <= 78 for line in printed), verdict.report


def test_fr345_the_warning_is_silent_under_source_and_on_an_all_deck_plan(
    tmp_path: Path,
) -> None:
    """Two silences, and they are silent for different reasons.

    Under `source` there is no promise to break: every creative ships its source language and the
    line would be describing the mode rather than a gap in it.

    Under `target` with nothing but bound decks in the plan, the promise is kept in full — every
    creative in that run really is translated. A warning that fired on the CONFIGURATION rather
    than on the gap is the kind an operator learns to scroll past, which would cost the line its
    value on the run where it matters.
    """
    config = _styled_config(tmp_path, registry=_TWO_STYLES)
    config.run.formats = {"image": 1, "carousel": 2, "reel": 0}
    config.sources.include_videos = True
    assert config.run.copy_language_mode == "source", "the engine default, not set by this test"

    kept = check(config, action="run", entries=[_deck(0), _entry(1)])
    assert _language_warnings(kept) == [], kept.report

    config.run.copy_language_mode = "target"
    decks_only = check(config, action="run", entries=[_deck(0), _deck(1)])
    assert _language_warnings(decks_only) == [], decks_only.report

    # And the same plan with one image back in it says so again — the trigger is the plan.
    mixed = check(config, action="run", entries=[_deck(0), _entry(1)])
    assert len(_language_warnings(mixed)) == 1, mixed.report
    assert "1 image/reel/override creative(s)" in _language_warnings(mixed)[0]


def test_fr345_a_translating_run_with_the_gauntlet_off_gets_its_own_glyph_hint(
    tmp_path: Path,
) -> None:
    """D63's clause on the accented-glyph family, and why it is a line of its own.

    `target` does not change WHICH creatives may carry accented glyphs — the answer was already
    "any of them, whatever run.languages says" — but it changes WHOSE glyphs they are. A translated
    slide is the copy model's own string, written for a language the source never wrote in, so an
    `en` run may now deliberately order Czech diacritics rather than only stumble into them, and
    nothing has proved that glyph renderable on the way.

    It prints BESIDE whichever of the three existing arms fires rather than replacing one. The
    arms are three answers to "where does this run's on-image text come from" and are mutually
    exclusive; translation is a second question about the same text. Making it a fourth arm would
    have silenced the Czech line on exactly the run that needs it most — a `cs` config translating
    English posts into Czech, which is `hypedigitaly-cs.yaml` as shipped.
    """
    config = _styled_config(tmp_path, registry=_TWO_STYLES)
    config.run.formats = {"image": 0, "carousel": 2, "reel": 0}
    config.run.gauntlet.enabled = False  # the hint family only exists when the gate is off
    config.run.copy_language_mode = "target"

    verdict = check(config, action="run", entries=[_deck(0)])

    hints = [hint for hint in verdict.hints if "copy_language_mode: target translates" in hint]
    assert len(hints) == 1, verdict.report
    assert "the copy model's own words in this run's language" in hints[0]
    assert "FR-343" in hints[0] and "the gauntlet is off" in hints[0]
    assert [hint for hint in verdict.hints if "quoted verbatim" in hint] != [], \
        "the verbatim arm still fires — the translation clause is beside it, not instead of it"
    assert verdict.ok

    # The gauntlet reads every frame back, so with it ON the whole family stays quiet, D63 included.
    config.run.gauntlet.enabled = True
    assert check(config, action="run", entries=[_deck(0)]).hints == ()

    # And `source` mode never prints it: there is no translated string to be unsure about.
    config.run.gauntlet.enabled = False
    config.run.copy_language_mode = "source"
    silent = check(config, action="run", entries=[_deck(0)])
    assert [hint for hint in silent.hints if "copy_language_mode: target" in hint] == []
    assert [hint for hint in silent.hints if "quoted verbatim" in hint] != [], \
        "the pre-D63 hint is unchanged on the mode every default run uses"


# ---- D64 --------------- SESSION O: the two subscription doors, judged before the money gate
#
# `models.llm_backend` and `models.render_provider` each gained a `codex` value that routes work to
# a local `npx openai-oauth@latest` proxy on the operator's own ChatGPT subscription. Three things
# change at pre-flight, and each is a way a run could otherwise fail AFTER paying:
#
#   1. a metered key is only required when its door is the one this run uses (a workstation with no
#      OpenRouter key at all is exactly the configuration the pivot exists to serve);
#   2. the proxy has to be reachable, and it has to serve the ids this config names — an OpenRouter
#      id like `anthropic/claude-sonnet-5` means nothing to it, and is the obvious repeat mistake;
#   3. there is no subscription path for video, so a reel plan is refused rather than half-shipped.
#
# The proxy is STARTED by `preflight.ensure_backends()` (async, awaited by the runner immediately
# before `check()`); `check()` itself only reads `codex_proxy.current_handle()`, so every test here
# installs a handle directly and nothing starts, probes or downloads anything.


@pytest.fixture(autouse=True)
def _no_proxy_handle() -> object:
    """No test in this file inherits another's proxy — the handle cell is process-global."""
    codex_proxy._CURRENT = None
    preflight_module._PROXY_FAILURE = ""
    yield
    codex_proxy._CURRENT = None
    preflight_module._PROXY_FAILURE = ""


#: What the real proxy served on 2026-08-21. The ids are bare — no vendor prefix — which is the
#: whole difference between a working `codex` config and an OpenRouter one pointed at localhost.
_PROXY_MODELS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-image-2")


def _proxy_is_up(models: tuple[str, ...] = _PROXY_MODELS) -> None:
    """Install the handle `ensure_backends()` would have left behind on a healthy start."""
    codex_proxy._CURRENT = codex_proxy.ProxyHandle(
        base_url="http://127.0.0.1:10531/v1", port=10531, models=models, owned=False)


def _codex_config(tmp_path: Path, *, llm: bool = True, render: bool = True, **kwargs: object):
    """A runnable config with one or both doors pivoted, and proxy-shaped model ids throughout."""
    config = _styled_config(tmp_path, registry=_TWO_STYLES, **kwargs)
    if llm:
        config.models.llm_backend = "codex"  # type: ignore[assignment]
        config.models.analysis = "gpt-5.6-sol"
        config.models.copy = "gpt-5.6-luna"
        config.models.critic = "gpt-5.6-sol"
    if render:
        config.models.render_provider = "codex"  # type: ignore[assignment]
    return config


def _codex_errors(verdict: Preflight) -> list[str]:
    return [line for line in verdict.errors if "D64" in line]


def test_d64_a_key_is_required_only_when_its_own_door_is_the_one_this_run_uses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The point of the pivot: a workstation with NO metered keys must be able to run.

    `OPENROUTER_API_KEY` opens the OpenRouter door and `KIE_API_KEY` the Kie one. Under `codex`
    neither door is opened, so refusing on a key that would never be sent anywhere would make the
    subscription path unreachable for the operator it was built for. `VIRLO_API_KEY` is in no door
    map and stays unconditional — there is one source of trends and no substitute for it.
    """
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("KIE_API_KEY", raising=False)
    _proxy_is_up()
    config = _codex_config(tmp_path)
    config.run.formats = {"image": 0, "carousel": 1, "reel": 0}

    verdict = check(config, action="run", entries=[_deck(0)])

    assert [line for line in verdict.errors if "OPENROUTER_API_KEY" in line] == [], verdict.report
    assert [line for line in verdict.errors if "KIE_API_KEY" in line] == [], verdict.report
    # And the key that has no second door is still refused when it is missing.
    monkeypatch.delenv("VIRLO_API_KEY", raising=False)
    assert [line for line in check(config, action="run", entries=[_deck(0)]).errors
            if "VIRLO_API_KEY" in line], "there is no subscription substitute for Virlo"


@pytest.mark.parametrize(
    ("key", "attribute", "metered"),
    [("OPENROUTER_API_KEY", "llm_backend", "openrouter"),
     ("KIE_API_KEY", "render_provider", "kie")],
)
def test_d64_the_metered_door_still_refuses_on_its_own_missing_key(
    key: str, attribute: str, metered: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the gate: nothing about D64 weakens FR-46 on the doors that ARE metered.

    Parameterised over both pairs precisely because the gating is a mapping — a wiring mistake
    that dropped one key's requirement entirely would still pass a test that only checked the
    other, and the failure would surface as an HTTP 401 halfway through a paid run.
    """
    monkeypatch.delenv(key, raising=False)
    config = _styled_config(tmp_path, registry=_TWO_STYLES)
    assert getattr(config.models, attribute) == metered, "the engine default, not set by this test"

    verdict = check(config, action="run", entries=[_deck(0)])

    refusals = [line for line in verdict.errors if key in line]
    assert len(refusals) == 1, verdict.report
    assert "FR-46" in refusals[0] and ".env" in refusals[0]


def test_d64_gating_changes_what_is_required_and_never_what_is_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D30 is not on the same dial as FR-46, and this is where the two could quietly be confused.

    A key left in `.env` from last week is still a secret this week. `collect_secrets()` feeds the
    logger's redaction set, so it must keep masking every value PRESENT in the environment whether
    or not this run has any use for it — otherwise pivoting to `codex` would start writing a live
    OpenRouter key into `events.jsonl` the first time an error message quoted a request.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-not-a-real-key")
    monkeypatch.setenv("KIE_API_KEY", "kie-not-a-real-key")
    _proxy_is_up()
    config = _codex_config(tmp_path)
    config.run.formats = {"image": 0, "carousel": 1, "reel": 0}

    verdict = check(config, action="run", entries=[_deck(0)])

    assert "sk-or-not-a-real-key" in verdict.secrets
    assert "kie-not-a-real-key" in verdict.secrets
    assert collect_secrets() == verdict.secrets, "one derivation, and the pivot does not touch it"


def test_d64_no_proxy_means_exit_2_with_the_two_commands_that_fix_it(tmp_path: Path) -> None:
    """The refusal an unattended run has to produce, and why it is a refusal at all.

    `ensure_backends()` already tried to START the proxy before `check()` ran — a scheduled `--yes`
    batch has nobody at the keyboard to notice a missing window, so pre-flight starting one is the
    difference between a run and a dead night. When even that failed there is nothing left to
    degrade to: every LLM call and every render would 404. So: exit 2, $0 spent, and both halves of
    the cure on the line, because "unreachable" alone sends an operator to their firewall.

    The reason the start failed rides along when there is one — "Node/npx was not found on PATH" is
    a different afternoon from "not signed in", and the symptom does not distinguish them.
    """
    config = _codex_config(tmp_path)
    config.run.formats = {"image": 0, "carousel": 1, "reel": 0}
    assert codex_proxy.current_handle() is None

    verdict = check(config, action="run", entries=[_deck(0)])

    refusals = [line for line in verdict.errors if "Codex proxy not reachable" in line]
    assert len(refusals) == 1, verdict.report
    assert "127.0.0.1:10531" in refusals[0]
    assert "npx openai-oauth@latest" in refusals[0] and "codex login" in refusals[0]
    assert not verdict.ok

    preflight_module._PROXY_FAILURE = "Node/npx was not found on PATH"
    detailed = [line for line in check(config, action="run", entries=[_deck(0)]).errors
                if "Codex proxy not reachable" in line]
    assert "Node/npx was not found on PATH" in detailed[0]


def test_d64_an_openrouter_model_id_under_the_codex_door_is_refused_by_name(
    tmp_path: Path,
) -> None:
    """The repeat misconfiguration, caught for $0 instead of at the first analysis call.

    `models.analysis: anthropic/claude-sonnet-5` is the shipped value and it is an OPENROUTER id.
    Pointed at the proxy it resolves to nothing, so the vision pass 404s, slide intelligence
    degrades, and every stage after it runs on empty — after the renders were paid for. There is no
    degraded version of a model that does not exist, so it is a refusal, and it names three things:
    the key to edit, the id that is wrong, and the ids that exist. The last one is not decoration —
    "unknown model" without the list is a search rather than a fix.
    """
    _proxy_is_up()
    config = _codex_config(tmp_path)
    config.models.analysis = "anthropic/claude-sonnet-5"
    config.run.formats = {"image": 0, "carousel": 1, "reel": 0}

    verdict = check(config, action="run", entries=[_deck(0)])

    refusals = [line for line in verdict.errors if "models.analysis" in line]
    assert len(refusals) == 1, verdict.report
    assert "anthropic/claude-sonnet-5" in refusals[0]
    assert "gpt-5.6-sol" in refusals[0] and "gpt-image-2" in refusals[0], "the list, not a hint"
    assert not verdict.ok
    # Only the roles this run can call are judged, and each distinct id is ONE finding: `copy` and
    # the critic are proxy ids here, so nothing else fires.
    assert len(_codex_errors(verdict)) == 1, verdict.report


def test_d64_a_disabled_critics_model_id_never_refuses_a_run_it_cannot_reach(
    tmp_path: Path,
) -> None:
    """A switched-off critic's model is never resolved, so it cannot be a reason to refuse.

    The gauntlet reads `critic.model or models.critic or models.analysis` at CALL time, only for
    critics that are on. Refusing on a stale id under a disabled critic would refuse a run for a
    call that cannot happen — the same posture `_check_gauntlet` already takes when it declines to
    look at a disabled critic's prompt template.
    """
    _proxy_is_up()
    config = _codex_config(tmp_path)
    config.run.formats = {"image": 0, "carousel": 1, "reel": 0}
    for name, critic in config.run.gauntlet.critics.items():
        critic.enabled = name == "brief"
        critic.model = None if name == "brief" else "anthropic/claude-sonnet-5"

    verdict = check(config, action="run", entries=[_deck(0)])
    assert _codex_errors(verdict) == [], verdict.report

    # Turn one of them on and the same id is refused immediately, naming ITS key.
    config.run.gauntlet.critics["craft"].enabled = True
    refused = _codex_errors(check(config, action="run", entries=[_deck(0)]))
    assert len(refused) == 1 and "run.gauntlet.critics.craft.model" in refused[0], refused


def test_d64_reels_are_refused_under_the_codex_render_provider(tmp_path: Path) -> None:
    """There is no subscription path for video, and half a run is worse than a clear no.

    The proxy renders `gpt-image-2` and nothing else. A plan holding a reel under
    `render_provider: codex` would ship its images and drop its reels, which is a partial delivery
    an operator did not choose. The refusal names the count, the provider to switch back to, and
    the flag that drops the reels instead — both ways out, because either may be the right one.
    """
    _proxy_is_up()
    config = _codex_config(tmp_path)
    config.run.formats = {"image": 0, "carousel": 1, "reel": 1}
    config.sources.include_videos = True
    reel = _entry(1)
    reel.creative_format = "reel"  # type: ignore[assignment]

    verdict = check(config, action="run", entries=[_deck(0), reel])

    refusals = [line for line in verdict.errors if "reels need the kie provider" in line]
    assert len(refusals) == 1, verdict.report
    assert "1 reel(s)" in refusals[0] and "render_provider: kie" in refusals[0]
    assert "--reels 0" in refusals[0]
    assert not verdict.ok
    # The same plan on the metered door is not this rule's business at all.
    config.models.render_provider = "kie"  # type: ignore[assignment]
    assert [line for line in check(config, action="run", entries=[_deck(0), reel]).errors
            if "reels need the kie provider" in line] == []


def test_d64_the_proxys_fixed_frame_size_is_stated_before_the_money_gate(
    tmp_path: Path,
) -> None:
    """FR-342 is a KIE knob, and a `2k` config under the proxy is not wrong — it is ignored.

    An operator who pinned `image_resolution: 2k` on all three brand configs for colour accuracy
    will get ~1254 px frames from the subscription door whatever that key says. They should read
    that on the screen where they approve the plan, not discover it in the folder afterwards. A
    hint and never a finding: the run is fine, the expectation is what needed correcting.
    """
    _proxy_is_up()
    config = _codex_config(tmp_path)
    config.run.formats = {"image": 0, "carousel": 1, "reel": 0}

    verdict = check(config, action="run", entries=[_deck(0)])

    stated = [hint for hint in verdict.hints if "1254 px" in hint]
    assert len(stated) == 1, verdict.report
    assert "image_resolution" in stated[0] and "$0" in stated[0]
    assert verdict.ok, "a fixed frame size is a fact, never a refusal"
    # Kie renders at the tier the operator asked for, so the line would be a lie there.
    config.models.render_provider = "kie"  # type: ignore[assignment]
    assert [h for h in check(config, action="run", entries=[_deck(0)]).hints if "1254" in h] == []


def test_d64_the_metered_defaults_reach_none_of_this(tmp_path: Path) -> None:
    """An openrouter+kie run must not gain a single new finding, a probe or a proxy dependency.

    This is the regression that would be easiest to ship: a check that fires on every run rather
    than on the pivoted ones would make a missing proxy refuse the runs that never wanted one. The
    handle is deliberately absent here — the default config must not so much as ask for it.
    """
    config = _styled_config(tmp_path, registry=_TWO_STYLES)
    config.run.formats = {"image": 0, "carousel": 1, "reel": 0}
    assert config.models.llm_backend == "openrouter" and config.models.render_provider == "kie"
    assert codex_proxy.current_handle() is None

    verdict = check(config, action="run", entries=[_deck(0)])

    assert _codex_errors(verdict) == [], verdict.report
    assert [line for line in verdict.errors if "Codex proxy" in line] == [], verdict.report
    assert [hint for hint in verdict.hints if "1254" in hint] == []
    assert not preflight_module.codex_needed(config, "run")


@pytest.mark.parametrize("action", ["list-monitors", "preview-sources"])
def test_d64_the_zero_dollar_cure_paths_never_need_a_proxy(
    action: str, tmp_path: Path,
) -> None:
    """FR-251's posture, applied to a new provider: a diagnostic must not need what it diagnoses.

    `--list-monitors` prints the ids a broken config is missing and `--preview-sources` is the $0
    blocklist preview. Neither reaches an LLM or renders a pixel, so refusing either because a
    proxy is not running would break the very commands an operator uses to get back to a run.
    """
    config = _codex_config(tmp_path)
    assert codex_proxy.current_handle() is None

    verdict = check(config, action=action)

    assert [line for line in verdict.errors if "Codex proxy" in line] == [], verdict.report
    assert not preflight_module.codex_needed(config, action)


@pytest.mark.asyncio
async def test_d64_ensure_backends_is_a_no_op_on_a_metered_run_and_never_raises(
    tmp_path: Path,
) -> None:
    """The async half, at both ends of its contract.

    On a metered run it must not touch the network at all — the base URL is deliberately garbage
    here, and a call that tried to reach it would fail. On a pivoted run whose proxy cannot start
    it must still not RAISE: a failure there is a pre-flight finding, written by `_check_codex`,
    printed beside everything else that is wrong with the run. A coroutine that threw would abort
    the pass and hide those other lines.
    """
    metered = _styled_config(tmp_path, registry=_TWO_STYLES)
    metered.models.llm_base_url = "http://an-address-nothing-can-reach.invalid:1/v1"
    assert await preflight_module.ensure_backends(metered, action="run") == ""
    assert codex_proxy.current_handle() is None

    off_box = _codex_config(tmp_path)
    off_box.models.llm_base_url = "http://10.0.0.5:10531/v1"  # the loopback guard's own case
    reason = await preflight_module.ensure_backends(off_box, action="run")
    assert "off-box" in reason and codex_proxy.current_handle() is None
    assert [line for line in check(off_box, action="run", entries=[_deck(0)]).errors
            if "Codex proxy not reachable" in line], "the reason becomes a finding, not a crash"


def test_d64_the_provider_summary_names_both_doors_in_console_width(tmp_path: Path) -> None:
    """The one fact about a run that stopped being inferable from the config's model ids.

    `gpt-image-2` is a Kie route name AND a proxy id, so after D64 an operator reading the launch
    block cannot tell from the models alone which provider they are about to spend against. These
    two lines say it outright, and they carry the money clause — an operator reading
    `$0, subscription` beside a $6 estimate knows the pivot did not take.

    Nothing secret is in them: a provider, a loopback host and model ids, all of which are already
    written in the config file (D30).
    """
    codex = _codex_config(tmp_path)
    lines = preflight_module.provider_summary(codex)
    block = "\n".join(lines)

    assert "codex via 127.0.0.1:10531" in block and "subscription" in block
    # The clause may wrap onto the continuation line, so the words are checked and not the run of
    # bytes between them — a width assertion below is what pins the layout.
    flat = " ".join(block.split())
    assert "copy gpt-5.6-luna" in flat and "analysis gpt-5.6-sol" in flat
    assert "gpt-image-2" in block and "$0" in block and "1254 px" in block
    assert "no video" in block, "the one thing the subscription door cannot do"
    assert all(len(line) <= 78 for line in lines), lines

    metered = "\n".join(preflight_module.provider_summary(_styled_config(
        tmp_path, registry=_TWO_STYLES)))
    assert "openrouter" in metered and "anthropic/claude-sonnet-5" in metered
    assert "kie" in metered and "seedance-2-5" in metered
    assert "127.0.0.1" not in metered, "a metered run names no proxy it will never contact"


def test_d64_a_preview_needs_the_llm_door_and_never_the_render_one(tmp_path: Path) -> None:
    """The two doors have different reaches, and `--preview-analysis` is where they part.

    A preview really does make LLM calls — that is the thing it previews — so a pivoted LLM door
    needs its proxy there or the preview would 404 its way through every stage. It renders nothing
    at all, so a pivoted RENDER door needs nothing: refusing a $0 preview because no image
    endpoint was up would break the cheapest way there is to check a config, which is exactly what
    FR-251 says must never happen.
    """
    render_only = _codex_config(tmp_path, llm=False)  # kie -> codex renders, OpenRouter LLM
    assert not preflight_module.codex_needed(render_only, "preview-analysis")
    preview = check(render_only, action="preview-analysis", entries=[_deck(0)])
    assert [line for line in preview.errors if "Codex proxy" in line] == [], preview.report

    llm_only = _codex_config(tmp_path, render=False)  # OpenRouter -> codex LLM, Kie renders
    assert preflight_module.codex_needed(llm_only, "preview-analysis")
    refused = check(llm_only, action="preview-analysis", entries=[_deck(0)])
    assert [line for line in refused.errors if "Codex proxy not reachable" in line], refused.report

    # With the proxy up, the same preview is clean and says nothing about pixels it will not make.
    _proxy_is_up()
    clean = check(llm_only, action="preview-analysis", entries=[_deck(0)])
    assert [line for line in clean.errors if "Codex proxy" in line] == [], clean.report
    assert [hint for hint in clean.hints if "1254" in hint] == [], "a preview renders nothing"
