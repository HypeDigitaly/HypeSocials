"""Tests for the `--style-test` diagnostic mode (FR-369, v2.9.0/D65, SESSION P wave 4).

The mode exists to answer one question the operator cannot answer from a production run: *what
does each meta-style actually look like on real material?* A normal run assigns styles by rotation
or by the matcher, binds a different source post to every deck, and publishes what it learns into
`logs/trend_history.json` — three things that each make a style comparison impossible to read. The
mode removes all three: one deck per style in the order `--styles` names them, every deck on ONE
pinned source post, and nothing written outside the run folder.

Four premises are pinned here, and every one of them is a thing that would silently ruin the
diagnostic if it drifted:

1. **The `--styles` list IS the matrix.** No flag, no run: `--style-test` alone would fall back on
   `styles.enabled` from the file, whose order nobody chose and whose length silently decides how
   many decks get ordered. That is a refusal at the argparse boundary, exit 2, $0.
2. **The override table is applied as one package** (30 §5), LAST, so it beats an individual count
   or platform flag that contradicts it.
3. **The post is pinned, and is NOT burnt.** Seventeen decks bind one post; the history window is
   not written, so tomorrow's unattended run finds that post exactly as unused as it was today.
4. **`style_test=False` is the pre-D65 path byte for byte.** Several tests below exist only to say
   so — an ordinary run must not be able to tell that this mode was ever added.

Offline throughout: no MCP session, no model call, no network. The two runner tests drive the real
`_assign_visuals` and `_package` with stub collaborators, because the guards under test are wired
into those functions and a re-implementation here would prove nothing about the wiring.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from hypesocials import budget, cli, copywrite, generate, runner, styles
from hypesocials.config import Config, PlatformConfig, RunConfig, load_config
from hypesocials.models import MetaStyle, PlanEntry, PlanEntryStatus, SourcePost, TrendItem
from hypesocials.plan import assign, build_plan, select
from hypesocials.util import Deadline, Stopwatch

_KEYS = ("anime-noir-statement", "build-log-mono", "icon-ledger-carousel")


# --------------------------------------------------------------------------- builders


def _opts(*argv: str) -> cli.Options:
    """Parse a real invocation — the flag surface is what is under test, never a hand-built
    `Options` (a field set directly here would pass even if argparse never learned the flag)."""
    return cli.parse_args(list(argv))


def _config(**run_kwargs: Any) -> Config:
    return Config(run=RunConfig(**run_kwargs))


def _post(post_id: str, *, panels: int = 4, views: int = 1000) -> SourcePost:
    """A slideshow source post — the only shape FR-304 lets a carousel bind."""
    return SourcePost(
        post_id=post_id, url=f"https://www.tiktok.com/@creator/video/{post_id}",
        author="creator", caption="the hook that stole the week", views=views,
        is_slideshow=True, panel_count=panels,
        panel_texts=[f"panel {index} of {post_id}" for index in range(1, panels + 1)],
        image_urls=[f"https://cdn.virlo.test/{post_id}/{index}.jpg"
                    for index in range(1, panels + 1)])


def _topic(topic_key: str, *posts: SourcePost, strength: float = 0.5) -> TrendItem:
    return TrendItem(
        history_key=f"m1::{topic_key}", monitor_id="m1", topic_key=topic_key,
        name=topic_key.replace("-", " ").title(), strength=strength, is_slideshow=True,
        why_it_works="strong pattern interrupt", posts=list(posts))


def _entry(order: int, *, fmt: str = "carousel", style: str = "") -> PlanEntry:
    return PlanEntry(
        order=order, asset_id=f"Li_car_topic_{order + 1:02d}", creative_format=fmt,
        platform="linkedin", language="en", aspect_ratio="1:1", style_key=style)


def _style(key: str) -> MetaStyle:
    return MetaStyle(key=key, render_prompt="Flat graphic card, centred subject.",
                     match_profile="Suits short single-idea sources.",
                     format_affinity=["image", "carousel", "reel"])


def _registry(*keys: str) -> styles.StyleRegistry:
    return styles.StyleRegistry(version=1, styles=[_style(key) for key in keys],
                                origin="prompts/styles.yaml", content_hash="0123456789ab")


class _Log:
    """The three LogWriter surfaces, recorded. `narrative()` is the redaction boundary and returns
    its input unchanged for text carrying no secret, exactly as the real one does."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.warnings: list[tuple[str, str]] = []

    def narrative(self, text: str) -> str:
        return str(text)

    def event(self, code: str, message: str = "", **fields: Any) -> None:
        self.events.append((code, message))

    def warn(self, code: str, message: str = "", **fields: Any) -> None:
        self.warnings.append((code, message))

    def error(self, code: str, message: str = "", **fields: Any) -> None:
        self.warnings.append((code, message))


class _Engine:
    """The one `PromptEngine` member `_package` reaches for (FR-184's attribution rows). Nothing
    in this file assembles a prompt, so an empty attribution is the honest answer."""

    def attribution(self) -> list[dict[str, str]]:
        return []


def _session(config: Config, *, run_dir: Path | None = None,
             stages: list[str] | None = None) -> runner._Session:
    """A real `_Session` with stub collaborators — the production `say`/`note` and the real
    dataclass, so what these tests assert about the console is what an operator would see."""
    live = runner._Session(
        config=config, opts=cli.Options(), control=runner.Control(),
        run_id="20260821_120000_styl",
        run_dir=run_dir or Path("output/20260821_120000_styl"),
        log=_Log(), ledger=None, deadline=Deadline.from_minutes(240), clock=Stopwatch(),
        budget=budget.Budget(config.run.spend_cap_usd), engine=_Engine(),
        verbose=False, stages=list(stages) if stages is not None else [])
    live.registry = _registry("s0", "s1", "s2")
    return live


# --------------------------------------------------------------------------- FR-369 the flag


def test_fr369_style_test_without_styles_is_refused_at_the_flag_boundary() -> None:
    """The `--styles` list IS the test matrix, so the mode has no meaning without it.

    Exit 2 from argparse itself: before any config load, before a run id exists, $0 (FR-63/285).
    The alternative — falling back on `styles.enabled` — would order a different number of decks
    than anyone asked for, in an order nobody chose.
    """
    with pytest.raises(SystemExit) as exited:
        _opts("--style-test")

    assert exited.value.code == 2


def test_fr369_the_refusal_names_the_flag_it_wants(capsys: pytest.CaptureFixture[str]) -> None:
    """One line, and it says what to type next — a refusal an operator cannot act on is a crash."""
    with pytest.raises(SystemExit):
        _opts("--style-test", "--config", "default")

    message = capsys.readouterr().err
    assert "--style-test needs --styles" in message and "FR-369" in message


def test_fr369_the_flag_parses_into_options_beside_its_style_list() -> None:
    """`style_test` is a plain bool: there is no config-file half for it to be silent about."""
    opts = _opts("--style-test", "--styles", ",".join(_KEYS))

    assert opts.style_test is True
    assert opts.styles == list(_KEYS), "order is preserved — it is the matrix"
    assert _opts("--styles", ",".join(_KEYS)).style_test is False, "absent means absent"


# --------------------------------------------------------------------------- FR-369 the overrides


def test_fr369_applies_the_whole_override_table_from_30_section_5() -> None:
    """Every row of the style-test override table, on one config, in one call.

    Asserted as a table rather than row by row on purpose: the mode is a PACKAGE, and a partial
    application is the failure worth catching (a run with the history skip but not the pinned
    formats would spend a production batch's money on a diagnostic).
    """
    config = _config(formats={"image": 4, "carousel": 2, "reel": 1},
                     platforms=["linkedin", "instagram", "tiktok"],
                     max_trend_reuses_per_run=6, cover_candidates=3, run_deadline_min=60)
    config.run.gauntlet.fail_action = "block"

    applied = cli.apply_overrides(config, _opts("--style-test", "--styles", ",".join(_KEYS)))

    assert config.run.style_test is True
    assert config.run.formats == {"image": 0, "carousel": 3, "reel": 0}
    assert config.run.platforms == ["linkedin"]
    assert config.run.max_trend_reuses_per_run == 3
    assert config.run.cover_candidates == 1
    assert config.run.gauntlet.fail_action == "degrade"
    assert config.run.run_deadline_min == 240
    assert config.output.gallery.title.endswith(" — STYLE TEST")
    assert config.styles.enabled == list(_KEYS), "--styles still applies, and stays in order"
    # One note per override, so the launch summary prints the whole mode rather than the accidental
    # subset that happened to differ from the file.
    for expected in ("run.style_test=true (3 style(s))",
                     "run.formats=image:0,carousel:3,reel:0",
                     "run.platforms=linkedin",
                     "run.max_trend_reuses_per_run=3",
                     "run.cover_candidates=1",
                     "run.gauntlet.fail_action=degrade",
                     "run.run_deadline_min=240"):
        assert expected in applied, f"{expected!r} missing from {applied!r}"


def test_fr369_a_single_platforms_flag_chooses_the_platform_and_a_longer_one_takes_its_first(
) -> None:
    """30 §5: "first of `run.platforms`, or the one platform `--platforms` names".

    Both halves are one line of code, because `--platforms` has already replaced the list by the
    time the package runs — which is exactly why the ORDER of the two overrides matters and is
    pinned here rather than left to reading.
    """
    named = _config(platforms=["linkedin", "instagram", "tiktok"])
    cli.apply_overrides(named, _opts("--style-test", "--styles", "a,b", "--platforms", "tiktok"))
    assert named.run.platforms == ["tiktok"]

    two = _config(platforms=["linkedin", "instagram", "tiktok"])
    cli.apply_overrides(two, _opts("--style-test", "--styles", "a,b",
                                   "--platforms", "instagram,tiktok"))
    assert two.run.platforms == ["instagram"], "first of the list the flag left standing"

    file_side = _config(platforms=["tiktok", "linkedin"])
    cli.apply_overrides(file_side, _opts("--style-test", "--styles", "a,b"))
    assert file_side.run.platforms == ["tiktok"], "first of run.platforms when no flag named one"
    assert file_side.run.languages["tiktok"], "the surviving platform keeps a language"


def test_fr369_the_deadline_is_a_floor_and_never_lowers_a_generous_config() -> None:
    """`max(configured, 240)`. A config that already allows more knows something this mode does
    not, and a diagnostic that shortened someone's deadline would abandon the very run it was
    asked to prove."""
    generous = _config(run_deadline_min=400)
    cli.apply_overrides(generous, _opts("--style-test", "--styles", "a,b"))
    assert generous.run.run_deadline_min == 400

    tight = _config(run_deadline_min=25)
    cli.apply_overrides(tight, _opts("--style-test", "--styles", "a,b"))
    assert tight.run.run_deadline_min == 240


def test_fr369_stays_inside_the_config_loaders_own_bounds_for_a_very_long_style_list() -> None:
    """`run.max_trend_reuses_per_run` is bounded 1–50 by the loader; a 60-key `--styles` must not
    write a number into the config that the file-side validator would have refused."""
    config = _config()
    keys = ",".join(f"style-{index:02d}" for index in range(60))

    cli.apply_overrides(config, _opts("--style-test", "--styles", keys))

    assert config.run.max_trend_reuses_per_run == 50
    assert config.run.formats["carousel"] == 60, "the plan still asks for one deck per style"


def test_fr369_beats_an_individual_count_flag_that_contradicts_it() -> None:
    """`--images 3 --style-test` is a contradiction, and 30 §5's table is the documented answer —
    not whichever flag argparse happened to see first. The package is applied LAST for this."""
    config = _config()

    cli.apply_overrides(config, _opts("--images", "3", "--reels", "2", "--carousels", "9",
                                      "--style-test", "--styles", "a,b"))

    assert config.run.formats == {"image": 0, "carousel": 2, "reel": 0}


def test_fr369_the_gallery_title_suffix_is_idempotent_across_two_applications() -> None:
    """`menu.py` calls `apply_overrides` twice on the interactive path (once to pre-fill the
    prompts, once after they are answered). A title reading " — STYLE TEST — STYLE TEST" is a bug,
    and the guard that prevents it is worth a test because nothing else would ever notice."""
    config = _config()
    opts = _opts("--style-test", "--styles", "a,b")

    cli.apply_overrides(config, opts)
    once = config.output.gallery.title
    cli.apply_overrides(config, opts)

    assert config.output.gallery.title == once
    assert once.count("STYLE TEST") == 1


def test_without_the_flag_apply_overrides_touches_nothing_the_mode_would_have_touched() -> None:
    """Premise 4, at the override seam: the pre-D65 path, byte for byte.

    Every key the package writes is read back here against a config nobody asked to change — and
    `run.style_test` stays False, which is the single switch every later stage branches on.
    """
    config = _config(formats={"image": 2, "carousel": 4, "reel": 1},
                     platforms=["linkedin", "instagram"], max_trend_reuses_per_run=6,
                     cover_candidates=3, run_deadline_min=60)
    config.run.gauntlet.fail_action = "block"
    title = config.output.gallery.title

    cli.apply_overrides(config, _opts("--styles", ",".join(_KEYS), "--budget", "4"))

    assert config.run.style_test is False
    assert config.run.formats == {"image": 2, "carousel": 4, "reel": 1}
    assert config.run.platforms == ["linkedin", "instagram"]
    assert config.run.max_trend_reuses_per_run == 6
    assert config.run.cover_candidates == 3
    assert config.run.gauntlet.fail_action == "block"
    assert config.run.run_deadline_min == 60
    assert config.output.gallery.title == title
    assert config.run.spend_cap_usd == 4.0, "the flags that WERE passed still applied"


# --------------------------------------------------------------------------- FR-369 the config key


def test_fr369_run_style_test_is_cli_only_and_a_yaml_that_sets_it_is_warned_and_ignored(
    tmp_path: Path,
) -> None:
    """A file carrying the key alone is HALF a mode, and the missing half is the dangerous half.

    `run.style_test: true` on its own would skip the history write on an otherwise ordinary
    production run: the posts it published would never be burnt, the next morning's unattended
    batch would quote them again, and nothing on the console would say why. So the loader warns
    AND resets — the mode arrives as `cli.apply_overrides`' package or it does not arrive.
    """
    folder = tmp_path / "configs"
    folder.mkdir()
    (folder / "unit.yaml").write_text("run:\n  style_test: true\n", encoding="utf-8")

    config = load_config("unit", configs_dir=folder)

    assert config.run.style_test is False
    assert any("run.style_test is CLI-only" in warning and "FR-369" in warning
               for warning in config.warnings), config.warnings


def test_the_shipped_configs_all_leave_style_test_off() -> None:
    """A diagnostic that shipped switched on would silently stop every config from ever learning
    the posts it published."""
    for name in ("default", "hypedigitaly-fresh"):
        assert load_config(name).run.style_test is False, name


# --------------------------------------------------------------------------- FR-369 the pinned post


def _pinned_plan(*, style_test: bool, decks: int = 3) -> tuple[Config, list[PlanEntry], Any]:
    """A carousels-only plan over a pool with plenty of fresh posts to spend, assigned once."""
    config = _config(formats={"image": 0, "carousel": decks, "reel": 0}, platforms=["linkedin"],
                     max_trend_reuses_per_run=decks)
    config.platforms = {"linkedin": PlatformConfig(formats=["carousel"], carousel_slides=6)}
    config.run.style_test = style_test
    plan = build_plan(config)
    pool = [_topic("alpha", _post("a1"), _post("a2"), _post("a3"), strength=0.9),
            _topic("beta", _post("b1"), _post("b2"), _post("b3"), strength=0.4)]
    result = assign(plan.entries, select(pool, config), config)
    return config, plan.entries, result


def test_fr369_every_carousel_group_binds_the_post_the_first_group_picked() -> None:
    """The pin itself. Seventeen decks that each quoted a different post would differ in their
    words, their panel count and their counter as well as in their style, and no one could then
    say which of those the picture in front of them came from."""
    _, entries, result = _pinned_plan(style_test=True)

    assert {entry.source_post_id for entry in entries} == {"a1"}, "one post, every deck"
    assert {entry.trend_key for entry in entries} == {"m1::alpha"}, "and one topic"
    assert {entry.slide_count for entry in entries} == {4}, "so every deck is the same length"
    assert [decision.source_post_id for decision in result.decisions] == ["a1", "a1", "a1"]
    assert all(entry.status is PlanEntryStatus.PENDING for entry in entries), "nothing skipped"


def test_fr369_the_first_group_still_picks_exactly_the_way_it_always_did() -> None:
    """The pin does not choose; it REPEATS. Deck 1 is the strongest bindable topic's top-ranked
    fresh post — the same post an ordinary run would have bound first — so the diagnostic is run
    against the material a production run would actually have used."""
    _, plain, _ = _pinned_plan(style_test=False)
    _, tested, _ = _pinned_plan(style_test=True)

    assert tested[0].source_post_id == plain[0].source_post_id == "a1"
    assert tested[0].trend_key == plain[0].trend_key


def test_fr369_the_pinned_post_is_not_burnt_and_an_ordinary_run_still_burns_every_post() -> None:
    """§0.10 says a post is a one-shot resource inside a run. Under the style test that rule is
    exactly backwards, so it is suspended — and the test asserts BOTH directions, because the
    thing that must not break is the ordinary one."""
    _, plain, _ = _pinned_plan(style_test=False)

    # Three DISTINCT posts, and they walk across both topics because `_pick` prefers the topic with
    # the fewest uses before it prefers rank — the ordinary spread the mode deliberately suspends.
    assert [entry.source_post_id for entry in plain] == ["a1", "b1", "a2"], \
        "an ordinary run spends a fresh post per deck (§0.10)"

    _, tested, _ = _pinned_plan(style_test=True)
    assert [entry.source_post_id for entry in tested] == ["a1", "a1", "a1"]


def test_fr369_the_assignment_decision_says_the_post_was_pinned() -> None:
    """run.log is where an operator reads WHY two decks quote one post; without this line the
    audit trail would look like the duplicate binding §0.10 exists to forbid."""
    _, _, tested = _pinned_plan(style_test=True)
    _, _, plain = _pinned_plan(style_test=False)

    assert all("style_test: post pinned" in decision.detail for decision in tested.decisions)
    assert not any("style_test" in decision.detail for decision in plain.decisions), \
        "and it never appears on an ordinary run"


def test_fr369_an_image_only_plan_is_unaffected_by_the_pin() -> None:
    """The pin is carousel-only by construction (only a carousel binds a post at all). The mode
    never produces such a plan, and the branch must still be inert if one arrives."""
    config = _config(formats={"image": 2, "carousel": 0, "reel": 0}, platforms=["linkedin"])
    config.run.style_test = True
    plan = build_plan(config)
    pool = [_topic("alpha", _post("a1"), strength=0.9), _topic("beta", _post("b1"), strength=0.4)]

    assign(plan.entries, select(pool, config), config)

    assert all(entry.source_post_id is None for entry in plan.entries)
    assert {entry.trend_key for entry in plan.entries} == {"m1::alpha", "m1::beta"}, \
        "images still spread across topics exactly as FR-90 says"


# --------------------------------------------------------------------------- FR-369 the 1:1 walk


def test_fr369_assign_styles_fixed_walks_the_key_list_one_for_one_in_plan_order() -> None:
    """Entry *i* gets `keys[i]`. That bluntness is the feature: deck 03 must be the third key the
    operator typed, or the grid's labels do not match its pictures."""
    entries = [_entry(order) for order in range(4)]
    keys = ["k-one", "k-two", "k-three", "k-four"]

    assigned = styles.assign_styles_fixed(entries, keys)

    assert [entry.style_key for entry in entries] == keys
    assert assigned == [(entry.asset_id, key) for entry, key in zip(entries, keys)]


def test_fr369_the_walk_is_by_position_in_plan_order_not_by_the_order_value() -> None:
    """`entry.order` is GAPPED after `_confirm` trims and `_select` drops, and it arrives here in
    whatever order the caller's list happened to be in. Position after sorting is the index."""
    entries = [_entry(7), _entry(0), _entry(4)]

    styles.assign_styles_fixed(entries, ["first", "second", "third"])

    assert [(entry.order, entry.style_key) for entry in entries] == [
        (7, "third"), (0, "first"), (4, "second")]


def test_fr369_the_walk_is_pure_and_repeatable() -> None:
    """No registry, no brand, no run id, no clock — so a re-run of the same matrix is the same
    matrix, and a `--preview-analysis` shows what the paid run will do."""
    keys = ["k-one", "k-two", "k-three"]
    first = styles.assign_styles_fixed([_entry(index) for index in range(3)], keys)
    second = styles.assign_styles_fixed([_entry(index) for index in range(3)], keys)

    assert first == second


def test_fr369_no_entry_can_come_out_of_the_fixed_walk_style_less() -> None:
    """A key list shorter than the plan cannot happen through the CLI (the deck count IS the key
    count) and wraps by modulo anyway, because a style-less entry would reach the render prompt
    with no DNA at all. An empty list leaves every entry exactly as it arrived."""
    entries = [_entry(order) for order in range(5)]
    styles.assign_styles_fixed(entries, ["a", "b"])
    assert [entry.style_key for entry in entries] == ["a", "b", "a", "b", "a"]

    untouched = [_entry(order, style="was-here") for order in range(3)]
    assert styles.assign_styles_fixed(untouched, []) == []
    assert [entry.style_key for entry in untouched] == ["was-here"] * 3


def test_fr369_the_fixed_walk_is_not_the_d52_rotation_fixed_knob() -> None:
    """The reason `assign_styles_fixed` exists at all, pinned as a contrast.

    `styles.rotation: "fixed"` pins the rotation OFFSET at 0 and then runs the ordinary scan, which
    walks REGISTRY FILE order and silently steps past a candidate that is not affine to the entry's
    format. Below, the operator asked for the registry's styles in reverse and the rotation gives
    them back in file order — three decks, every label wrong. The fixed walk gives back what was
    typed.
    """
    registry = _registry("s0", "s1", "s2")
    asked = ["s2", "s1", "s0"]

    rotated = [_entry(order) for order in range(3)]
    styles.assign_styles(rotated, registry, "", enabled=asked, run_id="", rotation="fixed")
    walked = [_entry(order) for order in range(3)]
    styles.assign_styles_fixed(walked, asked)

    assert [entry.style_key for entry in rotated] == ["s0", "s1", "s2"], \
        "the rotation walks the REGISTRY's order, whatever order the flag named"
    assert [entry.style_key for entry in walked] == asked
    assert [e.style_key for e in rotated] != [e.style_key for e in walked], \
        "which is the whole reason FR-369 does not reuse the rotation"


def test_fr369_the_fixed_walk_never_skips_a_style_the_way_the_affinity_scan_can() -> None:
    """The second half of the same contrast: `_scan` steps past a non-affine candidate, so a
    seventeen-key matrix could come back with sixteen distinct styles and one repeat — a hole in
    the grid where nobody would look for it. The fixed walk has no such branch."""
    narrow = styles.StyleRegistry(
        version=1, origin="prompts/styles.yaml", content_hash="0123456789ab",
        styles=[MetaStyle(key="image-only", render_prompt="p", format_affinity=["image"]),
                _style("everything")])

    rotated = [_entry(order) for order in range(2)]
    styles.assign_styles(rotated, narrow, "", enabled=["image-only", "everything"],
                         run_id="", rotation="fixed")
    walked = [_entry(order) for order in range(2)]
    styles.assign_styles_fixed(walked, ["image-only", "everything"])

    assert [entry.style_key for entry in rotated] == ["everything", "everything"], \
        "the carousel-blind style was skipped and the other one used twice"
    assert [entry.style_key for entry in walked] == ["image-only", "everything"], \
        "the matrix shows every style it was asked to show, including a mismatched one"


# --------------------------------------------------------------------------- FR-369 in the runner


def _assign(config: Config, entries: list[PlanEntry]) -> runner._Session:
    live = _session(config, stages=["ASSIGN"])
    live.llm = object()  # a client exists; the point is that the matcher is never reached
    asyncio.run(runner._assign_visuals(live, entries, {}, brief_only=False))
    return live


def test_fr369_assign_visuals_bypasses_both_the_rotation_and_the_matcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stage-level wire-in. Both algorithms exist to CHOOSE a style, and choosing is the one
    thing a style test must not do — the answer is already written in the `--styles` list."""
    calls: list[int] = []

    async def matcher(entries: Any, registry: Any, topics: Any, cfg: Any, llm: Any) -> Any:
        calls.append(len(list(entries)))
        return {}

    monkeypatch.setattr(runner.style_match, "match", matcher)
    config = _config(platforms=["linkedin"])
    config.styles.assignment = "matched"
    config.styles.enabled = ["s2", "s0", "s1"]
    config.run.style_test = True
    entries = [_entry(order) for order in range(3)]

    _assign(config, entries)

    assert [entry.style_key for entry in entries] == ["s2", "s0", "s1"], "the typed order"
    assert calls == [], "no matcher call, so no spend and no hole in the matrix"
    assert all(entry.style_origin == "rotation" for entry in entries), \
        "FR-337's vocabulary is closed; the mode does not add a sixth origin"
    assert all(entry.style_reason == "style_test" for entry in entries), \
        "the reason is where the truth goes, and it is greppable across meta.yaml"


def test_fr369_the_assign_stage_prints_the_whole_matrix_before_the_receipts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One line an operator can check at a glance: did the matrix come out in the right order?

    The separator is the two-character `->`; FR-155 forbids the `→` glyph outright, and every line
    holds FR-286's 78 columns.
    """
    config = _config(platforms=["linkedin"])
    config.styles.enabled = ["s2", "s0", "s1"]
    config.run.style_test = True

    _assign(config, [_entry(order) for order in range(3)])

    lines = capsys.readouterr().out.splitlines()
    matrix = [line for line in lines if "style test:" in line]
    assert matrix == ["          style test: 01->s2, 02->s0, 03->s1"]
    assert all("→" not in line for line in lines), "FR-155 forbids the arrow glyph"
    assert all(len(line) <= 78 for line in lines), "FR-286 allows 78 columns"


def test_fr369_an_ordinary_assign_stage_prints_no_matrix_and_still_rotates(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Premise 4 at the ASSIGN seam: without the flag the surface is invisible and the FR-291
    rotation is the thing that ran."""
    config = _config(platforms=["linkedin"])
    config.styles.enabled = ["s2", "s0", "s1"]
    entries = [_entry(order) for order in range(3)]

    _assign(config, entries)

    assert "style test:" not in capsys.readouterr().out
    assert all(entry.style_reason == "" for entry in entries)
    assert [entry.style_key for entry in entries] != ["s2", "s0", "s1"] \
        or len({entry.style_key for entry in entries}) == 3


def test_fr369_the_console_block_wraps_a_seventeen_style_matrix_inside_78_columns() -> None:
    """The real matrix from the SESSION P run — the widest thing this surface will ever print."""
    keys = ["anime-noir-statement", "platform-showcase-card", "letterpress-print-carousel-teal",
            "meme-caricature-panels-teal", "quiet-luxury-night-photoreal-teal",
            "photoreal-ambient-caption-teal", "ugc-tabletop-statement-teal", "build-log-mono",
            "icon-ledger-carousel", "circuit-atlas-dark", "social-quote-card",
            "terminal-mockup-deck", "big-number-editorial", "contrast-verdict-deck",
            "photo-poster-statement", "neon-glass-dark", "aurora-white-deck"]
    rows = [(f"Li_car_topic_{index:02d}", key) for index, key in enumerate(keys, 1)]

    block = runner._style_test_block(rows)

    assert block, "seventeen decks print"
    assert all(len(line) <= 78 for line in block), [len(line) for line in block]
    assert block[0].startswith("          style test: 01->anime-noir-statement,")
    assert block[-1].endswith("17->aurora-white-deck"), "the last pair carries no comma"
    assert all(line.startswith(" " * 22) for line in block[1:]), "continuations hang under it"
    assert runner._style_test_block([]) == [], "and an ordinary run prints nothing at all"


# --------------------------------------------------------------------------- FR-369 the history skip


async def _package(config: Config, tmp_path: Path,
                   monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], list[str]]:
    """Drive the real `_package` with the two shared-state writers recorded, not stubbed out of
    the picture: what is under test is whether they are CALLED."""
    history: list[str] = []
    latest: list[str] = []

    async def fake_record_use(*args: Any, **kwargs: Any) -> bool:
        history.append(str(args[2] if len(args) > 2 else ""))
        return True

    async def fake_set_latest(*args: Any, **kwargs: Any) -> bool:
        latest.append(str(args[1] if len(args) > 1 else ""))
        return True

    monkeypatch.setattr(runner, "record_use", fake_record_use)
    monkeypatch.setattr(runner, "set_latest", fake_set_latest)

    live = _session(config, run_dir=tmp_path, stages=["DONE"])
    entry = _entry(0)
    entry.trend_key = "m1::alpha"
    entry.status = PlanEntryStatus.SUCCESS
    report = generate.Report(records={}, packaged_trends={"m1::alpha"})
    estimate = budget.estimate(config, [entry])

    await runner._package(live, [entry], estimate, report, {}, copywrite.CopyResult(),
                          trend_supply_failed=False)
    return history, latest


async def test_fr369_a_style_test_writes_no_trend_history_and_does_not_move_output_latest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two writes are the only things a run does outside its own folder, and both would
    sabotage the next real run: the burnt post would be gone for 30 days with nothing on the
    console to say why, and `output/latest` — what `--publish latest` resolves against — would
    point at a folder full of deliberate duplicates."""
    config = _config(platforms=["linkedin"])
    config.run.style_test = True

    history, latest = await _package(config, tmp_path, monkeypatch)

    assert history == [] and latest == []
    assert (tmp_path / "gallery.html").exists(), \
        "the run is fully auditable — it is just not remembered"


async def test_fr369_an_ordinary_run_still_records_its_history_and_repoints_latest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Premise 4 at the packaging seam — the guard must be invisible without the flag."""
    config = _config(platforms=["linkedin"])

    history, latest = await _package(config, tmp_path, monkeypatch)

    assert history == ["20260821_120000_styl"]
    assert latest == ["20260821_120000_styl"]


async def test_fr369_says_out_loud_that_the_history_was_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """A pointer that did not move is exactly the kind of silence that costs an afternoon."""
    config = _config(platforms=["linkedin"])
    config.run.style_test = True

    await _package(config, tmp_path, monkeypatch)

    lines = [line for line in capsys.readouterr().out.splitlines() if "style test:" in line]
    assert lines == [
        "          style test: no history written, output/latest unchanged (FR-369)"]
    assert len(lines[0]) <= 78, "FR-286 allows 78 columns"
