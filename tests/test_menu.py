"""The wizard (30 §4: FR-56–60, FR-135/136/137, FR-284/285/286, NFR-16) — driven through its seam.

`menu.Console` is two callables and is designed to be **swapped whole**, so nothing here
monkeypatches `print` or `input`: every test hands `run_menu` a `Console` whose `ask` answers from a
queue and whose `say` records. That is also why these tests can assert on the exact text an operator
sees, which is the only thing this module produces.

Four defects an earlier draft of the wizard shipped, or nearly shipped, are pinned below:

- **`?` returned the pre-filled value.** On the cap, counts and briefs steps a pre-fill *passes
  validation*, so pressing `?` silently advanced three steps. Every step is therefore asserted to
  re-ask: `["?", "<invalid>", "<valid>"]` must produce **three** prompts, and the value that lands
  must be the one typed after the help.
- **Quick run fell through to `load_config(None)`** → `default.yaml` → empty `virlo_monitor_ids`,
  reproducing the original `20260810_123845_c832` failure in one keystroke. Quick run must resolve a
  **runnable** config, print which one, and refuse when none can run.
- **The picker could not distinguish two of its three rows.** `hypedigitaly.yaml` and
  `hypedigitaly-cs.yaml` have byte-identical `niche:` blocks and rendered identically, so the two
  rows are compared here against the real shipped `configs/`.
- **Printed lines were not width-capped** (FR-286): a 557-character line reached a real console. Every
  line the wizard prints — help text, picker rows, prompts — is measured mechanically, on all three
  shipped configs.

Nothing here spends, contacts anything or writes outside `tmp_path`; the shipped `configs/` and
`niches/` folders are only ever read.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

import pytest

from hypesocials import cli, menu
from hypesocials.config import CONFIGS_DIR
from hypesocials.menu import Console, run_menu

#: FR-286's ceiling for every line the tool controls.
WIDTH = 78

#: Each prompt of the seven-input flow, keyed by step, matched on the text the wizard prints. Text
#: rather than position, because a step may legitimately ask nothing (an absent briefs folder) and
#: positional scripts would then shift every later answer. `counts` and `mode` share the label
#: `edit the line`, so the pre-fill disambiguates them.
_PROMPT = {
    "action": "pick an action",
    "config": "pick a config",
    "sources": "pick one or more",
    "counts": "edit the line [images",
    "cap": "dollars for this run",
    "mode": "edit the line [mode",
    "briefs": "pick as <number>:<count>",
}
#: One answer per step that must be accepted.
_VALID = {
    "action": "1",
    "config": "1",
    "sources": "1",
    "counts": "images=1 carousels=0 reels=0",
    "cap": "3.75",
    "mode": "mode=direct notion=off",
    "briefs": "1:2",
}
#: One answer per step that must be re-asked. `0.01` is the cap that killed the tool's first ever
#: run (`20260810_123057_g0pg`); the floor is $0.03, the cheapest priced image tier.
_INVALID = {
    "action": "9",
    "config": "9",
    "sources": "9",
    "counts": "images=lots",
    "cap": "0.01",
    "mode": "mode=creative",
    "briefs": "9:1",
}

_READY = """label: "ready pack - EN captions, one monitor"
niche:
  audience: "SMB founders evaluating automation"
run:
  formats: {{ image: 4, carousel: 2, reel: 0 }}
  languages: {{ linkedin: en, instagram: en, tiktok: en }}
sources:
  virlo_monitor_ids: ["623203a9-1111-2222-3333-444455556666"]
briefs_dir: "{briefs}"
"""
_UNREADY = """label: "no monitor ids yet, not runnable"
niche:
  audience: "SMB founders evaluating automation"
run:
  formats: {{ image: 4, carousel: 2, reel: 0 }}
  languages: {{ linkedin: cs, instagram: cs, tiktok: cs }}
sources:
  virlo_monitor_ids: []
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


# --------------------------------------------------------------------------- the seam, as data


class Wizard:
    """A `Console` substitute: one answer queue per prompt, every printed line recorded.

    An unscripted prompt or an exhausted queue raises immediately, so "the wizard asked more than
    the test expected" fails loudly and by name instead of being swallowed by the EOF-quits-the-
    wizard path — which would turn a real defect into a quiet `None`.
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
    """Write `<stem>.yaml` per keyword into a private `configs/`, plus two briefs, and return it."""
    folder, briefs = tmp_path / "configs", tmp_path / "briefs"
    folder.mkdir(parents=True, exist_ok=True)
    briefs.mkdir(parents=True, exist_ok=True)
    (briefs / "alpha.yaml").write_text("message: a\n", encoding="utf-8")
    (briefs / "beta.md").write_text("# beta\n", encoding="utf-8")
    for stem, template in files.items():
        (folder / f"{stem.replace('_', '-')}.yaml").write_text(
            template.format(briefs=briefs.as_posix()), encoding="utf-8")
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


def _longest(printed: Sequence[str]) -> str:
    return max(printed, key=len, default="")


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


def test_fr284_the_cap_step_rejects_the_cap_that_killed_the_first_ever_run(
    tmp_path: Path,
) -> None:
    """Step 4 *validates* against `Config.min_single_creative_usd` — the one price floor, READ and
    never recomputed. `$0.01` is the number that produced exit 2 on the tool's first run, so the
    wizard must name the floor rather than let pre-flight discover it later."""
    configs = _configs(tmp_path, ready=_READY)
    wizard = _wizard(cap=["0.01", "3.75"])

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=configs)

    assert result is not None and result.options.budget_usd == 3.75
    refusals = [line for line in wizard.printed if "$0.01" in line]
    assert len(refusals) == 1 and "$0.03" in refusals[0] and "floor" in refusals[0]


# --------------------------------------------------------------------------- FR-285: quick run


def test_fr285_quick_run_resolves_a_RUNNABLE_config_prints_it_and_asks_nothing(
    tmp_path: Path,
) -> None:
    """Action `[2]` / `--quick`: no pickers, but never the unrunnable config either.

    The rejected draft fell through to `load_config(None)` → `default.yaml` → empty
    `virlo_monitor_ids`, which is the original failure in one keystroke. `Wizard()` carries no answer
    queues at all here, so any question the quick path asks fails the test.
    """
    configs = _configs(tmp_path, ready=_READY, unready=_UNREADY)
    wizard = Wizard()

    result = run_menu(cli.Options(quick=True), console=wizard.console, configs_dir=configs)

    assert wizard.asked == []  # `--quick` IS the action choice; nothing else is asked
    assert result is not None and result.config is not None
    assert result.options.config_name == "ready"
    assert result.config.sources.virlo_monitor_ids == ["623203a9-1111-2222-3333-444455556666"]
    label, facts = _row(wizard.printed, "ready")
    assert "ready pack" in label and "1 monitors" in facts  # it prints WHICH, and its readiness
    assert not any("unready" in line for line in wizard.printed)


def test_fr285_quick_run_refuses_when_the_only_config_available_cannot_run(
    tmp_path: Path,
) -> None:
    """"else a refusal showing every config and its blocker (FR-69)" — never a silent fallback onto
    a config that can collect nothing, and never a question either."""
    configs = _configs(tmp_path, unready=_UNREADY)
    wizard = Wizard()

    result = run_menu(cli.Options(quick=True), console=wizard.console, configs_dir=configs)

    assert result is None  # refused, not started
    assert wizard.asked == []
    printed = wizard.printed
    assert any("quick run needs a config that can collect trends" in line for line in printed)
    _, facts = _row(printed, "unready")
    assert "NOT RUNNABLE" in facts and "0 monitors" in facts
    assert any("[4]" in line for line in printed)  # the cure is on screen
    assert not any("default" in line for line in printed)  # no fallthrough to default.yaml


def test_fr285_quick_run_honours_an_explicit_config_even_when_it_is_not_runnable(
    tmp_path: Path,
) -> None:
    """`--config` names the row; the refusal is then pre-flight's, for free (FR-283). Turning this
    into a menu-level refusal would make `--config X --quick` mean something other than `X`."""
    configs = _configs(tmp_path, ready=_READY, unready=_UNREADY)
    wizard = Wizard()

    result = run_menu(cli.Options(quick=True, config_name="unready"), console=wizard.console,
                      configs_dir=configs)

    assert result is not None and result.options.config_name == "unready"


def test_fr285_quick_run_never_implies_yes_at_the_menu_or_at_the_flag_boundary() -> None:
    """"Still interactive: the confirm gate is next." `--quick` skips the questions, not the money
    gate — and the two flags are mutually exclusive because the combination is meaningless."""
    assert cli.parse_args(["--quick"]).quick is True
    assert cli.parse_args(["--quick"]).yes is False
    assert cli.parse_args(["--quick"]).interactive is True

    with pytest.raises(SystemExit) as caught:
        cli.parse_args(["--quick", "--yes"])
    assert caught.value.code == 2


def test_fr285_the_quick_result_stays_interactive_so_the_confirm_gate_still_runs(
    tmp_path: Path,
) -> None:
    configs = _configs(tmp_path, ready=_READY)

    result = run_menu(cli.Options(quick=True), console=Wizard().console, configs_dir=configs)

    assert result is not None
    assert result.options.quick is True
    assert result.options.yes is False
    assert result.options.action is cli.Action.RUN


# --------------------------------------------------------------------------- the picker


def test_fr284_a_zero_monitor_config_is_flagged_not_runnable_and_action_4_is_offered() -> None:
    """The shipped `default.yaml` keeps `virlo_monitor_ids: []` deliberately, so the empty state must
    be impossible to stumble into: the row says so, and the cure is one key on the same screen."""
    wizard = Wizard(action=["1"], config=["q"])

    assert run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR) is None

    _, facts = _row(wizard.printed, "default")
    assert "0 monitors" in facts
    assert "NOT RUNNABLE - pick [4]" in facts
    assert any("[4] print my Virlo monitor ids" in line for line in wizard.printed)


def test_fr173_two_configs_differing_only_in_language_render_DIFFERENTLY() -> None:
    """`hypedigitaly.yaml` and `hypedigitaly-cs.yaml` have byte-identical `niche:` blocks and a
    single behavioural difference (`run.languages`), so a derived picker line rendered them
    identically. The `label:` key and the language fact are what tell them apart now."""
    wizard = Wizard(action=["1"], config=["q"])

    assert run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR) is None

    en_label, en_facts = _row(wizard.printed, "hypedigitaly")
    cs_label, cs_facts = _row(wizard.printed, "hypedigitaly-cs")

    assert en_label != cs_label and en_facts != cs_facts
    assert "ENGLISH" in en_label and "CZECH" in cs_label
    assert en_facts.strip().split("·")[0].strip() == "en"
    assert cs_facts.strip().split("·")[0].strip() == "cs"


def test_fr285_a_bare_enter_in_the_picker_never_lands_on_a_not_runnable_row(
    tmp_path: Path,
) -> None:
    """"ONE rule behind two doors": the pre-fill and quick run read the same preference, so Enter and
    `[2]` cannot disagree. The unrunnable file sorts FIRST here, so a pre-fill of `1` would be the
    bug — file order must not beat readiness.
    """
    configs = _configs(tmp_path, aaa_empty=_UNREADY, zzz_ready=_READY)
    wizard = _wizard(config="")  # Enter keeps whatever the wizard pre-filled

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=configs)

    assert result is not None and result.options.config_name == "zzz-ready"
    assert any("pick a config [2]" in question for question in wizard.asked)


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


# --------------------------------------------------------------------------- counters and dead ends


def test_fr284_the_step_counters_read_1_of_7_through_7_of_7() -> None:
    """They used to read `1/6 … 6/6` and then `7/7 Confirm`. Seven steps, seven counters, and no
    `n/6` anywhere."""
    wizard = _wizard(config="3")  # hypedigitaly: a runnable shipped config with a briefs folder

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR)

    assert result is not None
    counters = [line.split()[0] for line in wizard.printed
                if re.match(r"^\d/\d\s", line)]
    assert counters == ["1/7", "2/7", "3/7", "4/7", "5/7", "6/7", "7/7"]


def test_fr285_action_3_admits_it_cannot_publish_without_asking_which_run() -> None:
    """The first question used to be a 50% dead end: `[2] Publish` asked *which run*, then printed
    "not implemented". One prompt total now, and the dispatcher owns the refusal."""
    wizard = Wizard(action=["3"])

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR)

    assert result is not None
    assert result.options.action is cli.Action.PUBLISH
    assert result.options.target == "latest"
    assert len(wizard.asked) == 1, wizard.asked
    assert not any("run" in question.lower() and "which" in question.lower()
                   for question in wizard.asked)


def test_fr285_action_4_routes_to_the_monitor_id_helper_with_no_further_questions() -> None:
    """~6 lines that turn "the tool told me it's broken" into "the tool fixed itself" — and it must
    cost one keystroke, not a walkthrough."""
    wizard = Wizard(action=["4"])

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR)

    assert result is not None
    assert result.options.action is cli.Action.LIST_MONITORS
    assert len(wizard.asked) == 1, wizard.asked


def test_fr56_an_unrecognised_action_key_re_asks_and_names_the_range() -> None:
    wizard = Wizard(action=["5", "x", "1"], config=["q"])

    assert run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR) is None
    assert wizard.count("action") == 3
    assert sum(1 for line in wizard.printed if "not one of 1–4" in line) == 2


def test_fr58_quitting_costs_nothing_and_says_so() -> None:
    """FR-58/59: `q` at any point ends the wizard with one line and no run."""
    wizard = Wizard(action=["1"], config=["q"])

    assert run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR) is None
    assert any("nothing was spent" in line for line in wizard.printed)


# --------------------------------------------------------------------------- FR-286: line width


@pytest.mark.parametrize("index,name", [(1, "default"), (2, "hypedigitaly-cs"), (3, "hypedigitaly")])
def test_fr286_no_printed_line_exceeds_78_characters_on_any_shipped_config(
    index: int, name: str,
) -> None:
    """"Every line this module prints is ≤ 78 characters, with the text it does not own truncated and
    placed last."

    Measured over a whole walkthrough per shipped config, with `?` pressed at every step so the help
    prose is measured too — it is printed verbatim and is the largest body of text in the tool. The
    557-character line a real run produced came from exactly this class of unbounded echo.
    """
    wizard = _helped(str(index))

    result = run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR)

    assert result is not None and result.options.config_name == name
    over = [line for line in wizard.printed if len(line) > WIDTH]
    assert over == [], f"{len(over)} line(s) over {WIDTH}: {_longest(over)!r}"
    assert len(wizard.printed) > 100  # a walkthrough that printed nothing would pass vacuously


def test_fr286_the_quick_path_and_the_quick_refusal_are_width_capped_too(tmp_path: Path) -> None:
    """Both quick-run outcomes print picker rows built from text the tool does not own."""
    for files in ({"ready": _READY, "unready": _UNREADY}, {"unready": _UNREADY}):
        wizard = Wizard()
        run_menu(cli.Options(quick=True), console=wizard.console,
                 configs_dir=_configs(tmp_path / str(len(files)), **files))
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


def test_fr286_no_colour_no_box_drawing_and_no_check_marks_reach_the_console() -> None:
    """Legacy conhost prints `←[32m` literally, has no box-drawing coverage in Consolas' primary
    set, and U+2713 is absent from cp437/cp852. `·`, `—`, `…` and `←` are the four proven glyphs."""
    wizard = _helped("3")

    assert run_menu(cli.Options(), console=wizard.console, configs_dir=CONFIGS_DIR) is not None

    text = "\n".join(wizard.printed)
    assert "\x1b" not in text  # no ANSI escape of any kind
    assert not set(text) & set("✓✗│─┌┐└┘├┤┬┴┼█▀▄")
    for character in set(text):
        assert character.isascii() or character in "·—…←", repr(character)
