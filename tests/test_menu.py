"""The wizard as v2.0.0 shipped it (30 §4: FR-56–60, FR-135/136/137, FR-284/285/286, FR-300,
NFR-16) — driven through its seam.

`menu.Console` is two callables and is designed to be **swapped whole**, so nothing here
monkeypatches `print` or `input`: every test hands `run_menu` a `Console` whose `ask` answers from a
queue and whose `say` records. That is also why these tests can assert on the exact text an operator
sees, which is the only thing this module produces.

**FR-300 is the wave's change and the first half of this file.** The pivot deleted two of the seven
inputs — the source picker (Virlo is the only source) and the mode picker (generation has no modes)
— so the properties pinned below are:

- **The step counters are DERIVED.** They were seven literal `"1/7"`…`"7/7"` strings at seven call
  sites; deleting two steps that way prints a wizard that cannot count. `_live_steps()` is the
  ordered list and `_step()` reads a position out of it, so numerator and denominator move
  together. Asserted both end-to-end (`1/5`…`5/5`, `1/1` for `--quick`) and structurally (drop a
  step from a copied list and every later counter shifts).
- **The two dead steps are gone, help keys included.** No prompt mentions either, and
  `wizard_help.md` has no section for them — orphaned help prose is how a deleted step comes back.
- **A picker row now answers RUNNABILITY, not just identity** (FR-295): `cs · 2 mon · 4/2/1 ·
  hypelead · 8 styles`. A registry that will not serve this run replaces the style count with
  `NO STYLES` at pick time instead of becoming an exit-2 refusal three prompts later, and a config
  that will not load says `WILL NOT LOAD` rather than inventing a brand it never read.
- **Brand and ratio are DISPLAY-ONLY** (FR-300d) — shown at the confirm step, edited only in the
  file. The direction for v2.0.0 was fewer inputs, not more.
- **The confirm notice re-derives its duration** (FR-300e): the old "8-10 minutes" counted the
  yt-dlp motion-reference chain, which no longer exists.

Four defects an earlier draft of the wizard shipped, or nearly shipped, are pinned in the second
half: `?` returning the pre-fill (and silently advancing three steps), quick run falling through to
`default.yaml`, two picker rows that rendered identically, and lines over FR-286's 78 columns.

Nothing here spends, contacts anything or writes outside `tmp_path`; the shipped `configs/`,
`prompts/` and `niches/` folders are only ever read.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from hypesocials import cli, menu
from hypesocials.config import CONFIGS_DIR, list_configs, load_config
from hypesocials.menu import Console, run_menu

#: FR-286's ceiling for every line the tool controls.
WIDTH = 78

#: Each prompt of the FIVE-input flow, keyed by step, matched on the text the wizard prints. Text
#: rather than position, because a step may legitimately ask nothing (an absent briefs folder) and
#: positional scripts would then shift every later answer. `confirm` prompts for nothing — it is a
#: notice — so it is a live step with no entry here.
_PROMPT = {
    "action": "pick an action",
    "config": "pick a config",
    "counts": "edit the line [images",
    "cap": "dollars for this run",
    "briefs": "pick as <number>:<count>",
}
#: The two prompts v2.0.0 deleted, in the wording they used to print (FR-300a and the mode picker).
_DEAD_PROMPTS = ("pick one or more", "edit the line [mode", "generation mode", "sources")
#: One answer per step that must be accepted.
_VALID = {
    "action": "1",
    "config": "1",
    "counts": "images=1 carousels=0 reels=0",
    "cap": "3.75",
    "briefs": "1:2",
}
#: One answer per step that must be re-asked. `0.01` is the cap that killed the tool's first ever
#: run (`20260810_123057_g0pg`); the floor is $0.03, the cheapest priced image tier.
_INVALID = {
    "action": "9",
    "config": "9",
    "counts": "images=lots",
    "cap": "0.01",
    "briefs": "9:1",
}

_READY = """label: "ready pack - CZECH captions, one monitor"
niche:
  audience: "SMB founders evaluating automation"
branding:
  brand: hypelead
  brand_ratio: 0.5
run:
  formats: {{ image: 0, carousel: 6, reel: 0 }}
  languages: {{ linkedin: cs, instagram: cs, tiktok: cs }}
sources:
  virlo_monitor_ids: ["623203a9-1111-2222-3333-444455556666"]
briefs_dir: "{briefs}"
"""
_UNREADY = """label: "no monitor ids yet, not runnable"
niche:
  audience: "SMB founders evaluating automation"
run:
  formats: {{ image: 0, carousel: 6, reel: 0 }}
  languages: {{ linkedin: cs, instagram: cs, tiktok: cs }}
sources:
  virlo_monitor_ids: []
briefs_dir: "{briefs}"
"""
#: FR-314 at pick time: a config that curated its own rotation down to two of the shipped styles.
#: Both keys are real and both are carousel-affine, so the row is RUNNABLE — the only thing that
#: must change is the number the picker prints.
_CURATED = """label: "two styles only, curated"
branding:
  brand: hypelead
styles:
  enabled: [editorial-voxel-carousel, letterpress-print-carousel]
run:
  formats: {{ image: 0, carousel: 6, reel: 0 }}
sources:
  virlo_monitor_ids: ["623203a9-1111-2222-3333-444455556666"]
briefs_dir: "{briefs}"
"""
#: FR-295 at pick time: monitor ids are fine, but `prompts_dir` resolves to a registry that will
#: not parse — the run would refuse with exit 2 after four more prompts.
_NO_STYLES = """label: "monitors fine, registry broken"
prompts_dir: "{broken}"
branding:
  brand: hypelead
run:
  formats: {{ image: 0, carousel: 6, reel: 0 }}
sources:
  virlo_monitor_ids: ["623203a9-1111-2222-3333-444455556666"]
briefs_dir: "{briefs}"
"""
#: Not valid YAML at all: `list_configs` still lists it (one broken sibling must never blank the
#: picker) but `load_config` refuses it.
_WONT_LOAD = "label: [unclosed\n"
#: A run WITH reels — the confirm notice's other duration branch (FR-300e). It states
#: `include_videos: true` because an image or reel count over slideshow-only sourcing is a load
#: refusal since v2.1.0 (D46 §0.14e): a reel-capable config is a video-sourcing config.
_WITH_REELS = """label: "reels on"
run:
  formats: {{ image: 1, carousel: 0, reel: 2 }}
sources:
  include_videos: true
  virlo_monitor_ids: ["623203a9-1111-2222-3333-444455556666"]
briefs_dir: "{briefs}"
"""
#: No `label:` at all, so the picker line is the derived niche join — the shipped niche text
#: verbatim, which is ~400 characters and is what produced an unreadable row before FR-286.
_NO_LABEL = """niche:
  audience: "founders, marketing leads and ops people at SMBs and agencies evaluating AI automation - EN, LinkedIn-led, Instagram/TikTok secondary"
  vibe: "no-fluff practitioner proof: specific numbers, real workflows, contrarian takes on AI hype; we ship the thing, we don't theorise about it"
  visual_world: "dark UI and dashboard screenshots, terminal/automation-graph fragments, one electric accent on near-black, heavy geometric sans headlines"
sources:
  virlo_monitor_ids: ["623203a9-1111-2222-3333-444455556666"]
briefs_dir: "{briefs}"
"""


@pytest.fixture(autouse=True)
def _fresh_readiness() -> Iterator[None]:
    """`menu._READINESS` is keyed on (path, mtime, size) and lives for the wizard's few seconds.
    Across a test SESSION that cache would carry one test's verdict into another's file, so every
    test starts with it empty — the escape hatch the module documents for exactly this."""
    menu._READINESS.clear()
    yield
    menu._READINESS.clear()


# --------------------------------------------------------------------------- the seam, as data


class Wizard:
    """A `Console` substitute: one answer queue per prompt, every printed line recorded.

    An unscripted prompt or an exhausted queue raises immediately, so "the wizard asked more than
    the test expected" fails loudly and by name instead of being swallowed by the EOF-quits-the-
    wizard path — which would turn a real defect into a quiet `None`. A prompt matching one of the
    two DELETED steps is its own named failure (FR-300).
    """

    def __init__(self, **answers: str | Sequence[str]) -> None:
        self.queues = {step: [value] if isinstance(value, str) else list(value)
                       for step, value in answers.items()}
        self.asked: list[str] = []
        self.said: list[str] = []

    @property
    def console(self) -> Console:
        return Console(ask=self._ask, say=self._say)

    def _ask(self, question: str) -> str:
        self.asked.append(question)
        for dead in _DEAD_PROMPTS:
            assert dead not in question.lower(), \
                f"FR-300 deleted this step, and it asked anyway: {question!r}"
        for step, matcher in _PROMPT.items():
            if matcher in question:
                queue = self.queues.get(step)
                assert queue, f"unscripted (or over-asked) {step!r} prompt: {question!r}"
                return queue.pop(0)
        raise AssertionError(f"unrecognised prompt: {question!r}")

    def _say(self, text: object) -> None:
        self.said.append(str(text))

    @property
    def printed(self) -> list[str]:
        """Every line the wizard put on the console: `say` blocks split, prompts included.

        Prompts count — FR-286 is a rule about what the tool prints, and a prompt is printed.
        """
        lines = [line.rstrip() for block in self.said for line in block.split("\n")]
        return lines + [question.rstrip() for question in self.asked]

    def count(self, step: str) -> int:
        """How many times that step's prompt was issued — 3 is a re-ask, 1 is an advance."""
        return sum(1 for question in self.asked if _PROMPT[step] in question)


def _configs(tmp_path: Path, **files: str) -> Path:
    """Write `<stem>.yaml` per keyword into a private `configs/`, plus two briefs and a broken
    style registry for the FR-295 row, and return the configs folder."""
    folder, briefs = tmp_path / "configs", tmp_path / "briefs"
    broken = tmp_path / "prompts-broken"
    folder.mkdir(parents=True, exist_ok=True)
    briefs.mkdir(parents=True, exist_ok=True)
    broken.mkdir(parents=True, exist_ok=True)
    (briefs / "alpha.yaml").write_text("message: a\n", encoding="utf-8")
    (briefs / "beta.md").write_text("# beta\n", encoding="utf-8")
    (broken / "styles.yaml").write_text("styles: [ not: valid: yaml\n", encoding="utf-8")
    for stem, template in files.items():
        (folder / f"{stem.replace('_', '-')}.yaml").write_text(
            template.format(briefs=briefs.as_posix(), broken=broken.as_posix()), encoding="utf-8")
    return folder


def _wizard(**overrides: str | Sequence[str]) -> Wizard:
    """A full walkthrough that answers every step correctly, with the named steps overridden."""
    queues: dict[str, str | Sequence[str]] = dict(_VALID)
    queues.update(overrides)
    return Wizard(**queues)


def _helped(config: str) -> Wizard:
    """A full walkthrough that presses `?` at every step before answering it, on `config`'s row."""
    queues: dict[str, str | Sequence[str]] = {step: ["?", _VALID[step]] for step in _PROMPT}
    queues["config"] = ["?", config]
    return Wizard(**queues)


def _row(printed: Sequence[str], name: str) -> tuple[str, str]:
    """One config's two picker lines: its label line and the readiness line under it (FR-284).

    Matched on the name token, never on `in` — `hypedigitaly` is a prefix of `hypedigitaly-cs`.
    """
    for index, line in enumerate(printed):
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("[") and parts[1] == name:
            return line, printed[index + 1]
    raise AssertionError(f"{name!r} has no picker row in:\n" + "\n".join(printed))


def _facts(configs: Path, name: str) -> list[str]:
    """A row's readiness facts, split back into the `·`-joined fields it was built from."""
    summary = next(row for row in list_configs(configs) if row.name == name)
    _, facts = menu._rows(1, summary)
    return [part.strip() for part in facts.split("·")]


def _counters(printed: Sequence[str]) -> list[str]:
    return [line.split()[0] for line in printed if re.match(r"^\d+/\d+\s", line)]


def _longest(printed: Sequence[str]) -> str:
    return max(printed, key=len, default="")


# --------------------------------------------------------------------------- FR-300: five inputs


def test_fr300_the_guided_run_asks_five_inputs_and_counts_them_1_of_5_through_5_of_5() -> None:
    """NFR-16 re-enumerated: config, counts, cap, briefs, confirm. The counters used to read
    `1/7`…`7/7` at seven hardcoded call sites, so deleting the source and mode steps would have
    printed a wizard whose numerator stopped at 5 and whose denominator still said 7."""
    wizard = _wizard(config="3")  # hypedigitaly: a runnable shipped config with a briefs folder

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR)

    assert result is not None
    assert menu._live_steps(quick=False) == ("config", "counts", "cap", "briefs", "confirm")
    assert _counters(wizard.printed) == ["1/5", "2/5", "3/5", "4/5", "5/5"]
    # Anchored like `_counters` above, because a counter is a line PREFIX. An unanchored search
    # also matched the picker row's own `0/6/0` format triple once the shipped configs went
    # all-carousels (D46 §0.3) — a format count is not a step counter.
    assert not any(re.match(r"^\d+/[67]\s", line) for line in wizard.printed), \
        "a leftover seven-step counter anywhere in the output"


def test_fr300_quick_run_counts_the_one_step_it_actually_has(tmp_path: Path) -> None:
    """`--quick` asks nothing before the price (FR-285), so its live list is the confirm notice
    alone — and `1/1` is what a derived counter prints for it without anybody writing `1/1`."""
    configs = _configs(tmp_path, ready=_READY)
    wizard = Wizard()

    result = run_menu(cli.Options(quick=True), console=wizard.console, configs_dir=configs)

    assert result is not None and wizard.asked == []
    assert menu._live_steps(quick=True) == ("confirm",)
    assert _counters(wizard.printed) == ["1/1"]


def test_fr300_a_counter_is_a_position_in_the_live_list_not_a_number_anybody_typed() -> None:
    """The structural half: drop a step from a copy of the live list and every later counter
    shifts by one. A literal would not move, which is precisely how the old wizard broke."""
    said: list[str] = []
    io = Console(ask=lambda question: "", say=said.append)
    full = list(menu._live_steps(quick=False))
    shorter = [step for step in full if step != "counts"]

    for steps in (full, shorter):
        for key in steps:
            menu._step(io, steps, key)

    counters = _counters([line for block in said for line in block.split("\n")])
    assert counters[:len(full)] == ["1/5", "2/5", "3/5", "4/5", "5/5"]
    assert counters[len(full):] == ["1/4", "2/4", "3/4", "4/4"]
    assert menu._step.__doc__ is not None and "DERIVED" in menu._step.__doc__
    with pytest.raises(ValueError):  # a step that is not live is a programmer error, loudly
        menu._step(io, shorter, "counts")


def test_fr300_the_source_picker_and_the_mode_picker_are_gone_help_text_included() -> None:
    """Both steps died with the pivot: Virlo is the only source, and generation has no modes. The
    `Wizard` harness fails on either prompt by name; what is asserted here is that no orphaned
    help section survives to describe a step that cannot be reached (FR-284's prose is a contract
    with the operator, and prose for a dead step is a promise the tool cannot keep)."""
    wizard = _helped("3")

    assert run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR) is not None

    assert "sources" not in menu._WIZARD_STEPS and "mode" not in menu._WIZARD_STEPS
    for dead in ("sources", "mode"):
        assert menu._explain(dead) == f"  no help text for '{dead}' — see README.md"
        assert f"\n## {dead}\n" not in menu._HELP_FILE.read_text(encoding="utf-8")
        assert f"\n## purpose.{dead}\n" not in menu._HELP_FILE.read_text(encoding="utf-8")
    text = "\n".join(wizard.printed).lower()
    assert "generation mode" not in text and "analyzed" not in text


def test_fr300_the_mode_flag_the_deleted_step_mirrored_is_gone_from_the_cli_too() -> None:
    """Every wizard answer has a flag behind it (30 §5), so a deleted step whose flag survived
    would leave the two doors disagreeing about what a run can be."""
    with pytest.raises(SystemExit) as caught:
        cli.parse_args(["--mode", "direct"])

    assert caught.value.code == 2


# --------------------------------------------------------------------------- FR-300: the picker


def test_fr300_a_picker_row_states_language_monitors_counts_brand_and_styles(
    tmp_path: Path,
) -> None:
    """`cs · 1 mon · 0/6/0 · hypelead · 8 styles` — the two facts FR-300 added (brand, usable
    style count) sit beside the three that were already there, and the style count is the count
    usable under THIS config's brand, not the registry's total. (The counts read `0/6/0` since
    v2.1.0: the shipped shape is all-carousels, D46 §0.3.)"""
    configs = _configs(tmp_path, ready=_READY)

    facts = _facts(configs, "ready")

    assert facts[:3] == ["cs", "1 mon", "0/6/0"]
    assert facts[3] == "hypelead"
    assert re.fullmatch(r"\d+ styles", facts[4]), facts
    assert int(facts[4].split()[0]) > 0
    assert menu._runnable(next(row for row in list_configs(configs) if row.name == "ready"))


def test_fr314_the_picker_counts_the_styles_this_config_selected_not_the_registrys_total(
    tmp_path: Path,
) -> None:
    """The style count is a prediction of the run, so it has to see `styles.enabled` (FR-314).

    A config that curated its rotation down to two would otherwise be advertised as an eight-style
    run at the exact moment the operator is choosing between configs — the row would be predicting
    a rotation that cannot happen. Two real, carousel-affine keys, so the row stays runnable and
    the only difference from its uncurated sibling is the number.
    """
    configs = _configs(tmp_path, curated=_CURATED, ready=_READY)

    curated, uncurated = _facts(configs, "curated"), _facts(configs, "ready")

    assert curated[4] == "2 styles"
    assert int(uncurated[4].split()[0]) > 2, "the same registry, uncurated, is the whole pool"
    assert menu._runnable(next(row for row in list_configs(configs) if row.name == "curated"))


def test_fr295_a_registry_that_will_not_serve_this_run_reads_NO_STYLES_at_pick_time(
    tmp_path: Path,
) -> None:
    """The blocker used to surface as exit 2 after four more prompts. `NO STYLES` REPLACES the
    count rather than appending a badge — a broken registry has no number worth printing, and the
    swap is what keeps a doubly-blocked row inside FR-286."""
    configs = _configs(tmp_path, nostyles=_NO_STYLES, ready=_READY)

    facts = _facts(configs, "nostyles")
    summary = next(row for row in list_configs(configs) if row.name == "nostyles")

    assert facts[:4] == ["en", "1 mon", "0/6/0", "hypelead"]
    assert facts[4] == "NO STYLES"
    assert not any("styles" in fact and fact != "NO STYLES" for fact in facts)
    assert menu._runnable(summary) is False, "FR-295 blocks a run exactly as no monitor ids do"


def test_fr300_a_config_that_will_not_load_says_so_instead_of_inventing_a_brand(
    tmp_path: Path,
) -> None:
    """`list_configs` reads a summary without validating, so a row can exist for a file
    `load_config` refuses. Printing a brand and a style count it never read would be a fiction."""
    configs = _configs(tmp_path, wontload=_WONT_LOAD)

    facts = _facts(configs, "wontload")

    assert "WILL NOT LOAD" in facts
    assert not any("styles" in fact for fact in facts)
    assert menu._runnable(next(row for row in list_configs(configs)
                               if row.name == "wontload")) is False


def test_fr300_runnable_means_monitors_AND_styles_which_is_what_preflight_will_check(
    tmp_path: Path,
) -> None:
    """`_runnable()` mirrors the pre-flight verdict (FR-283 + FR-295) so a row can never disagree
    with the refusal it is predicting — and `_preference` therefore never offers either to
    `--quick`."""
    configs = _configs(tmp_path, ready=_READY, unready=_UNREADY, nostyles=_NO_STYLES)
    rows = {row.name: row for row in list_configs(configs)}

    verdicts = {name: menu._runnable(row) for name, row in rows.items()}

    assert verdicts == {"ready": True, "unready": False, "nostyles": False}
    offered = [row.name for row in menu._preference(list(rows.values()), None)]
    assert offered == ["ready"]


def test_fr285_quick_run_refuses_when_no_config_can_run_and_shows_every_blocker(
    tmp_path: Path,
) -> None:
    """"else a refusal showing every config and its blocker (FR-69)" — never a silent fallback onto
    a config that can collect nothing or dress nothing, and never a question either."""
    configs = _configs(tmp_path, unready=_UNREADY, nostyles=_NO_STYLES)
    wizard = Wizard()

    result = run_menu(cli.Options(quick=True), console=wizard.console, configs_dir=configs)

    assert result is None and wizard.asked == []
    printed = wizard.printed
    assert any("quick run needs a config that can collect trends" in line for line in printed)
    assert "NOT RUNNABLE" in _row(printed, "unready")[1]
    assert "NO STYLES" in _row(printed, "nostyles")[1]
    assert any("[4]" in line for line in printed)  # the cure is on screen
    assert not any("default" in line for line in printed)  # no fallthrough to default.yaml


def test_fr285_quick_run_resolves_a_RUNNABLE_config_prints_it_and_asks_nothing(
    tmp_path: Path,
) -> None:
    """The rejected draft fell through to `load_config(None)` → `default.yaml` → empty
    `virlo_monitor_ids`, which is the original failure in one keystroke. `Wizard()` carries no
    answer queues at all here, so any question the quick path asks fails the test."""
    configs = _configs(tmp_path, ready=_READY, unready=_UNREADY)
    wizard = Wizard()

    result = run_menu(cli.Options(quick=True), console=wizard.console, configs_dir=configs)

    assert wizard.asked == []  # `--quick` IS the action choice; nothing else is asked
    assert result is not None and result.config is not None
    assert result.options.config_name == "ready"
    assert result.config.sources.virlo_monitor_ids == ["623203a9-1111-2222-3333-444455556666"]
    label, facts = _row(wizard.printed, "ready")
    assert "ready pack" in label and "1 mon" in facts  # it prints WHICH, and its readiness
    assert not any("unready" in line for line in wizard.printed)
    assert result.options.quick is True and result.options.yes is False  # the gate still runs


def test_fr285_quick_run_honours_an_explicit_config_even_when_it_cannot_run(
    tmp_path: Path,
) -> None:
    """`--config` names the row; the refusal is then pre-flight's, for free (FR-283/295). Turning
    this into a menu-level refusal would make `--config X --quick` mean something other than `X`."""
    configs = _configs(tmp_path, ready=_READY, unready=_UNREADY)
    wizard = Wizard()

    result = run_menu(cli.Options(quick=True, config_name="unready"), console=wizard.console,
                      configs_dir=configs)

    assert result is not None and result.options.config_name == "unready"


def test_fr285_quick_never_implies_yes_at_the_menu_or_at_the_flag_boundary(
    tmp_path: Path,
) -> None:
    """"Still interactive: the confirm gate is next." `--quick` skips the questions, not the money
    gate — and the two flags are mutually exclusive because the combination is meaningless."""
    configs = _configs(tmp_path, ready=_READY)

    result = run_menu(cli.Options(quick=True), console=Wizard().console, configs_dir=configs)

    assert result is not None
    assert result.options.action is cli.Action.RUN
    assert result.options.quick is True and result.options.yes is False
    assert cli.parse_args(["--quick"]).interactive is True
    with pytest.raises(SystemExit) as caught:
        cli.parse_args(["--quick", "--yes"])
    assert caught.value.code == 2


def test_fr285_a_bare_enter_in_the_picker_never_lands_on_a_not_runnable_row(
    tmp_path: Path,
) -> None:
    """"ONE rule behind two doors": the pre-fill and quick run read the same preference, so Enter
    and `[2]` cannot disagree. The unrunnable file sorts FIRST here, so a pre-fill of `1` would be
    the bug — file order must not beat readiness."""
    configs = _configs(tmp_path, aaa_empty=_UNREADY, zzz_ready=_READY)
    wizard = _wizard(config="")  # Enter keeps whatever the wizard pre-filled

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=configs)

    assert result is not None and result.options.config_name == "zzz-ready"
    assert any("pick a config [2]" in question for question in wizard.asked)


def test_fr173_two_shipped_configs_differing_only_in_language_render_DIFFERENTLY() -> None:
    """`hypedigitaly.yaml` and `hypedigitaly-cs.yaml` have byte-identical `niche:` blocks and a
    single behavioural difference (`run.languages`), so a derived picker line rendered them
    identically. The `label:` key and the language fact are what tell them apart."""
    wizard = Wizard(action=["1"], config=["q"])

    assert run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR) is None

    en_label, en_facts = _row(wizard.printed, "hypedigitaly")
    cs_label, cs_facts = _row(wizard.printed, "hypedigitaly-cs")

    assert en_label != cs_label and en_facts != cs_facts
    assert "ENGLISH" in en_label and "CZECH" in cs_label
    assert en_facts.strip().split("·")[0].strip() == "en"
    assert cs_facts.strip().split("·")[0].strip() == "cs"


def test_fr284_a_zero_monitor_config_is_flagged_not_runnable_and_action_4_is_offered() -> None:
    """The shipped `default.yaml` keeps `virlo_monitor_ids: []` deliberately, so the empty state
    must be impossible to stumble into: the row says so, and the cure is one key on the same
    screen."""
    wizard = Wizard(action=["1"], config=["q"])

    assert run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR) is None

    _, facts = _row(wizard.printed, "default")
    assert "0 mon" in facts
    assert "NOT RUNNABLE - pick [4]" in facts
    assert any("[4] print my Virlo monitor ids" in line for line in wizard.printed)


# --------------------------------------------------------------------------- FR-300: confirm step


def test_fr300_brand_and_ratio_are_SHOWN_at_confirm_and_asked_nowhere(tmp_path: Path) -> None:
    """FR-300d: the operator's direction was fewer inputs, so the brand system, its ratio and its
    mode are run-wide config facts printed once — not three more prompts.

    FR-318 (v2.1.3/D48) made `branding.enabled` default to FALSE, and the confirm step REPLACES
    the brand line rather than annotating it: this is the last screen before money moves, and
    "brand hypelead · ratio 0.50" over a run that will sign nothing is a false statement about the
    creatives the operator is about to buy. The key name is printed because it is the cure.
    """
    configs = _configs(tmp_path, ready=_READY)
    wizard = _wizard()

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=configs)

    assert result is not None
    line = next(line for line in wizard.printed if "branding:" in line)
    assert line.strip() == "branding: off (branding.enabled: false) · no wordmark on any creative"
    assert len(line) <= WIDTH
    assert not any("brand hypelead" in printed for printed in wizard.printed), \
        "an unsigned run may not name a brand at the gate (FR-318)"
    assert not any("brand" in question.lower() or "ratio" in question.lower()
                   for question in wizard.asked)


def test_fr318_switching_branding_on_brings_the_brand_ratio_and_mode_line_back(
    tmp_path: Path,
) -> None:
    """The other state of the same switch: with `branding.enabled: true` the confirm step prints
    FR-300d's original brand/ratio/mode fact, because now it is true again.

    Both halves are pinned deliberately — a switch tested in one state only is a switch that can
    silently become a constant, and the fact this line states is the one an operator uses to
    decide whether the batch they are buying will carry their wordmark.
    """
    configs = _configs(tmp_path, ready=_READY.replace("  brand: hypelead\n",
                                                      "  brand: hypelead\n  enabled: true\n"))
    wizard = _wizard()

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=configs)

    assert result is not None and result.config.branding.enabled is True
    line = next(line for line in wizard.printed if "brand hypelead" in line)
    assert line.strip() == "brand hypelead · ratio 0.50 · overlay · config, not asked"
    assert len(line) <= WIDTH
    assert not any("branding: off" in printed for printed in wizard.printed)
    assert not any("brand" in question.lower() or "ratio" in question.lower()
                   for question in wizard.asked)


@pytest.mark.parametrize("reels,expected", [(0, "about 3 minutes"), (2, "5-8 minutes")])
def test_fr300_the_confirm_notice_re_derives_its_duration_without_the_yt_dlp_chain(
    tmp_path: Path, reels: int, expected: str,
) -> None:
    """FR-300e: "8-10 minutes" counted a chain that no longer exists (yt-dlp downloading the
    winning video and uploading it to Kie as a motion reference). What is left is LLM calls plus
    render jobs, and a reel is the only thing that still makes a run long."""
    configs = _configs(tmp_path, ready=_READY, reels=_WITH_REELS)
    config = load_config(configs / ("reels.yaml" if reels else "ready.yaml"))
    said: list[str] = []

    menu._say_confirm_ahead(Console(ask=lambda question: "", say=said.append), config,
                            menu._live_steps(quick=True))

    text = "\n".join(said)
    assert expected in text
    assert "8-10 minutes" not in text
    head, _, rest = inspect.getsource(menu._say_confirm_ahead).partition('"""')
    assert "8-10 minutes" not in head + rest.partition('"""')[2], \
        "the literal is gone from the CODE — its docstring may only explain why it went"


# --------------------------------------------------------------------------- FR-284: the `?` key


@pytest.mark.parametrize("step", list(_PROMPT))
def test_fr284_a_question_mark_explains_the_step_and_RE_ASKS_it(step: str, tmp_path: Path) -> None:
    """"`?` **re-asks**: returning the pre-fill would validate on the cap, counts and briefs steps
    and silently advance three steps."

    Fed `["?", "<invalid>", "<valid>"]`, a step must issue its prompt three times: once for the
    help, once for the rejected answer, once for the accepted one. A `?` that returned the pre-fill
    shows two at best — and on most steps one, because the pre-fill validates.
    """
    configs = _configs(tmp_path, ready=_READY, unready=_UNREADY)
    wizard = _wizard(**{step: ["?", _INVALID[step], _VALID[step]]})

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=configs)

    assert result is not None, "the walkthrough did not complete"
    assert wizard.count(step) >= 3, f"{step} was asked {wizard.count(step)} time(s)"
    head = next(line for line in menu._explain(step).split("\n") if line.strip())
    assert head.rstrip() in wizard.printed, f"the {step} help text was never printed"


def test_fr284_the_help_key_does_not_advance_the_three_steps_whose_prefill_validates(
    tmp_path: Path,
) -> None:
    """THE regression, stated as the values that land.

    On counts, cap and briefs the pre-filled value is valid, so a `?` that returned it would advance
    — and the answer meant for that step would be eaten by the next one. Asserting the resolved
    options is the only assertion that cannot be satisfied by an advancing `?`.
    """
    configs = _configs(tmp_path, ready=_READY, unready=_UNREADY)
    wizard = _wizard(counts=["?", _VALID["counts"]], cap=["?", _VALID["cap"]],
                     briefs=["?", _VALID["briefs"]])

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=configs)

    assert result is not None
    assert result.options.counts == {"image": 1, "carousel": 0, "reel": 0}
    assert result.options.budget_usd == 3.75  # not the config's 10.00 pre-fill
    assert result.options.briefs == (("alpha", 2),)  # not "no briefs"
    assert (wizard.count("counts"), wizard.count("cap"), wizard.count("briefs")) == (2, 2, 2)


def test_fr284_only_a_bare_question_mark_is_help_so_a_brief_named_help_stays_selectable(
    tmp_path: Path,
) -> None:
    """"Accept `?` only, not `help`/`h` — a brief file named `help` is legal on Windows and would
    become unselectable." So `help` typed at the briefs step must be read as a brief name."""
    configs = _configs(tmp_path, ready=_READY)
    (tmp_path / "briefs" / "help.yaml").write_text("message: h\n", encoding="utf-8")
    wizard = _wizard(briefs="help:1")

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=configs)

    assert result is not None
    assert result.options.briefs == (("help", 1),)
    assert wizard.count("briefs") == 1  # accepted first time: it was never treated as help


def test_fr136_counts_are_one_editable_line_never_a_prompt_per_format(tmp_path: Path) -> None:
    """One line sets all three formats, and a key left out of it keeps its current value — the
    step that would otherwise be three prompts of the five the wizard is allowed."""
    configs = _configs(tmp_path, ready=_READY)
    wizard = _wizard(counts="reels=1")

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=configs)

    assert result is not None
    assert result.options.counts == {"image": 0, "carousel": 6, "reel": 1}
    assert wizard.count("counts") == 1
    assert any("edit the line [images=0 carousels=6 reels=0]" in question
               for question in wizard.asked)


def test_fr284_the_cap_step_rejects_the_cap_that_killed_the_first_ever_run(
    tmp_path: Path,
) -> None:
    """The cap step *validates* against `Config.min_single_creative_usd` — the one price floor,
    READ and never recomputed. `$0.01` is the number that produced exit 2 on the tool's first run,
    so the wizard must name the floor rather than let pre-flight discover it later."""
    configs = _configs(tmp_path, ready=_READY)
    wizard = _wizard(cap=["0.01", "3.75"])

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=configs)

    assert result is not None and result.options.budget_usd == 3.75
    refusals = [line for line in wizard.printed if "$0.01" in line]
    assert len(refusals) == 1 and "$0.03" in refusals[0] and "floor" in refusals[0]


# --------------------------------------------------------------------------- actions & dead ends


def test_fr285_the_action_choice_is_still_four_keys_on_one_prompt() -> None:
    """Quick run and the monitor-id helper ride the action prompt rather than adding one, so
    NFR-16's count — one action choice plus five inputs — is untouched by FR-300."""
    wizard = Wizard(action=["5", "x", "1"], config=["q"])

    assert run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR) is None

    assert wizard.count("action") == 3
    assert sum(1 for line in wizard.printed if "not one of 1–4" in line) == 2
    offered = next(line for line in wizard.printed if "[1] guided run" in line)
    assert "[2] quick run" in offered and "[3] publish" in offered


def test_fr285_action_3_admits_it_cannot_publish_without_asking_which_run() -> None:
    """The first question used to be a 50% dead end: `[2] Publish` asked *which run*, then printed
    "not implemented". One prompt total now, and the dispatcher owns the refusal."""
    wizard = Wizard(action=["3"])

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR)

    assert result is not None
    assert result.options.action is cli.Action.PUBLISH
    assert result.options.target == "latest"
    assert len(wizard.asked) == 1, wizard.asked


def test_fr285_action_4_routes_to_the_monitor_id_helper_with_no_further_questions() -> None:
    """~6 lines that turn "the tool told me it's broken" into "the tool fixed itself" — and it must
    cost one keystroke, not a walkthrough."""
    wizard = Wizard(action=["4"])

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR)

    assert result is not None
    assert result.options.action is cli.Action.LIST_MONITORS
    assert len(wizard.asked) == 1, wizard.asked


def test_fr58_quitting_costs_nothing_and_says_so() -> None:
    """FR-58/59: `q` at any point ends the wizard with one line and no run."""
    wizard = Wizard(action=["1"], config=["q"])

    assert run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR) is None
    assert any("nothing was spent" in line for line in wizard.printed)


def test_fr56_a_config_folder_with_nothing_in_it_says_where_it_looked(tmp_path: Path) -> None:
    """FR-69: one plain line naming the folder it searched — a picker that just returned `None`
    would read as a crash. Both doors refuse, and neither asks a question it cannot use."""
    empty = tmp_path / "configs"
    empty.mkdir()
    guided, quick = Wizard(action=["1"]), Wizard()

    assert run_menu(cli.Options(), console=guided.console, configs_dir=empty) is None
    assert run_menu(cli.Options(quick=True), console=quick.console, configs_dir=empty) is None

    assert any("no config found" in line for line in guided.printed)
    looked = [line for line in guided.printed if "Looked in:" in line]
    # The folder is named, but as text the tool does not own it is fitted to the width budget —
    # a `tmp_path` is longer than the 60 chars FR-286 leaves for it, so only its head survives.
    assert len(looked) == 1 and str(empty)[:40] in looked[0] and len(looked[0]) <= WIDTH
    assert quick.asked == []


def test_fr232_the_fidelity_rating_is_optional_and_never_waits_on_an_unattended_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One 1–3 rating per run, asked after the spend summary, skippable with a bare Enter and
    suppressed entirely under `--yes` or with no terminal attached (FR-66) — nothing unattended
    may block on a human."""
    answers = iter(["2", "", "9"])
    io = Console(ask=lambda question: next(answers), say=lambda text: None)
    asked: list[str] = []
    monkeypatch.setattr(cli.sys, "stdin", type("Tty", (), {"isatty": lambda self: True})())

    assert asyncio.run(menu.ask_fidelity_rating(cli.Options(), console=io)) == 2
    assert asyncio.run(menu.ask_fidelity_rating(cli.Options(), console=io)) is None, "bare Enter"
    assert asyncio.run(menu.ask_fidelity_rating(cli.Options(), console=io)) is None, "not 1–3"

    silent = Console(ask=lambda question: asked.append(question) or "3", say=lambda text: None)
    assert asyncio.run(menu.ask_fidelity_rating(cli.Options(yes=True), console=silent)) is None
    monkeypatch.setattr(cli.sys, "stdin", type("Pipe", (), {"isatty": lambda self: False})())
    assert asyncio.run(menu.ask_fidelity_rating(cli.Options(), console=silent)) is None
    assert asked == [], "neither --yes nor a detached console may read a prompt at all"


# --------------------------------------------------------------------------- FR-286: line width


@pytest.mark.parametrize("index,name",
                         [(1, "default"), (2, "hypedigitaly-cs"), (3, "hypedigitaly")])
def test_fr286_no_printed_line_exceeds_78_characters_on_any_shipped_config(
    index: int, name: str,
) -> None:
    """"Every line this module prints is ≤ 78 characters, with the text it does not own truncated
    and placed last."

    Measured over a whole walkthrough per shipped config, with `?` pressed at every step so the help
    prose is measured too — it is printed verbatim and is the largest body of text in the tool. The
    557-character line a real run produced came from exactly this class of unbounded echo.
    """
    wizard = _helped(str(index))

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR)

    assert result is not None and result.options.config_name == name
    over = [line for line in wizard.printed if len(line) > WIDTH]
    assert over == [], f"{len(over)} line(s) over {WIDTH}: {_longest(over)!r}"
    assert len(wizard.printed) > 80  # a walkthrough that printed nothing would pass vacuously


def test_fr286_the_quick_path_and_the_quick_refusal_are_width_capped_too(tmp_path: Path) -> None:
    """Both quick-run outcomes print picker rows built from text the tool does not own, and the
    FR-295 row is the widest of them (brand + NO STYLES + NOT RUNNABLE on one line)."""
    for index, files in enumerate(({"ready": _READY, "unready": _UNREADY},
                                   {"unready": _UNREADY, "nostyles": _NO_STYLES})):
        wizard = Wizard()
        run_menu(cli.Options(quick=True), console=wizard.console,
                 configs_dir=_configs(tmp_path / str(index), **files))
        over = [line for line in wizard.printed if len(line) > WIDTH]
        assert over == [], f"{_longest(over)!r}"


def test_fr286_a_config_with_no_label_of_its_own_is_truncated_and_marked(tmp_path: Path) -> None:
    """The row that mangled a real console: with no `label:`, `_describe` falls back to the niche
    join — three sentences, ~400 characters, and `hypedigitaly.yaml`'s own is exactly that long. The
    label must be cut on a word boundary and marked `…`, not hard-sliced and not printed whole."""
    configs = _configs(tmp_path, verbose=_NO_LABEL)
    wizard = Wizard(action=["1"], config=["q"])

    assert run_menu(cli.Options(), console=wizard.console, configs_dir=configs) is None

    label, facts = _row(wizard.printed, "verbose")
    assert len(label) <= WIDTH and len(facts) <= WIDTH
    assert label.endswith("…"), label  # cut, and the operator can see that it was cut
    assert [line for line in wizard.printed if len(line) > WIDTH] == []


def test_fr286_no_colour_no_box_drawing_no_check_marks_and_no_arrow_glyph() -> None:
    """Legacy conhost prints `←[32m` literally, has no box-drawing coverage in Consolas' primary
    set, and U+2713 is absent from cp437/cp852. `·`, `—`, `…` and `←` are the four proven glyphs;
    `→` is FORBIDDEN (FR-155) and `->` is what the tool writes instead."""
    wizard = _helped("3")

    assert run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR) is not None

    text = "\n".join(wizard.printed)
    assert "\x1b" not in text  # no ANSI escape of any kind
    assert "→" not in text
    assert not set(text) & set("✓✗│─┌┐└┘├┤┬┴┼█▀▄")
    for character in set(text):
        assert character.isascii() or character in "·—…←", repr(character)
