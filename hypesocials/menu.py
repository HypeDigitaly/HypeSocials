"""The interactive wizard — the action choice and four prompts between `run.bat` and a run.

Module contract
---------------
Purpose: own every question HypeSocials asks a human (30 §4: FR-56–60, FR-136/137, FR-284/285,
FR-300, NFR-16), plus the FR-28 over-cap offer and the FR-232 fidelity rating. The wizard decides
*what* a run should be; it never starts one, opens a session, or prices a plan of its own.

Public API: `Console` · `MenuResult` · `run_menu()` · `await offer_reduced_plan()` ·
`await ask_fidelity_rating()`.

Invariants:
- **Numbers and Enter, never spelling** (30 §4): every prompt shows the value in effect and takes
  a bare Enter to keep it (FR-57); a bad answer re-asks instead of guessing intent.
- **Five inputs, and the counter derives from the live ones** (FR-300/NFR-16): config, counts,
  cap, briefs, confirm. `_live_steps()` is the ordered list; `_step()` reads a step's position
  out of it. No call site ever types a counter — a step a run does not ask is absent from the
  list, and numerator and denominator move together. (v2.0.0 deleted two steps this way: the
  source picker, because Virlo is the only source, and the mode picker, because generation has
  no modes.)
- **Every step explains itself** (FR-284) from `wizard_help.md` — purpose lines on every run,
  fuller prose on `?`. `?` **re-asks**: returning the pre-fill instead would validate on the cap,
  counts and briefs steps and silently advance three steps.
- **Every line this module prints is ≤ 78 characters** (FR-286), with the text it does not own
  (config names, niche descriptors, paths) truncated by `_fit` and placed last. No colour, no box
  drawing, no `✓`, no `→` — legacy conhost renders none of them.
- **Platforms and branding are never asked** (FR-137/FR-300) — config file or `--platforms`. The
  brand, its ratio and its mode are *shown* at the confirm step and edited nowhere but the file:
  the operator's direction for v2.0.0 was fewer inputs, not more.
- **The confirm step is deliberately NOT here.** `cli.confirm_spend()` owns it, after plan
  expansion, where the estimate is real; pricing a plan that does not exist yet would be a
  parallel estimator (guidelines §2). The cap step therefore *validates* the cap against
  `Config.min_single_creative_usd` — the one price floor — and never estimates a plan.
- **Nothing here spends or contacts anything** (FR-58/59): every step reads `configs/`,
  `prompts/styles.yaml` and `briefs_dir` off local disk, and quitting at any point costs $0. The
  quick action never falls through to `default.yaml` either: it resolves a *runnable* config or
  refuses (FR-285), where runnable now means FR-295's registry check too.
- **`run_menu()` is synchronous and runs BEFORE the event loop** (`__main__`, right after
  `cli.parse_args`). The two post-plan prompts are async because they are called from inside a
  running loop, and both read the console through `asyncio.to_thread` — never on the loop thread.

Do not: parse flags (`cli.py`), price anything (`budget.py`), read `.env` (D30), grade a style
registry (`styles.validate()` owns that — the picker only reports its verdict), load or validate
brief *contents* (`briefs.py` — the picker lists names only), or start a run (`runner.py`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from hypesocials import cli, styles
from hypesocials.budget import estimate as estimate_plan, format_usd, trim
from hypesocials.config import (
    CONFIGS_DIR, Config, ConfigError, ConfigSummary, list_configs, load_config)
from hypesocials.models import PlanEntry, PlanEntryStatus
from hypesocials.prompts_engine import PROMPTS_DIR
from hypesocials.util import fit, read_text

#: FR-286: 78 is the ceiling for every printed line. `  [n] ` + a 15-char name + two spaces = 23,
#: so a picker label gets 55; a facts line is indented 6, so 70 leaves two columns of slack for a
#: glyph a legacy console renders double-width.
_NAME_WIDTH, _LABEL_WIDTH, _FACTS_WIDTH = 15, 55, 70
#: FR-284's prose, beside this module and NOT under `prompts/` (pre-flight validates that tree).
_HELP_FILE = Path(__file__).with_name("wizard_help.md")
_HELP: dict[str, str] = {}
_FORMATS = ("image", "carousel", "reel")
_PLURAL = {"image": "images", "carousel": "carousels", "reel": "reels"}
_COUNT_KEYS = {**{name: name for name in _FORMATS}, **{v: k for k, v in _PLURAL.items()}}
#: NFR-16's five inputs, in ask order — the ONE source of every `n/N` counter (FR-300). The keys
#: are also `wizard_help.md`'s section names (`purpose.<key>` and `<key>`).
_WIZARD_STEPS = ("config", "counts", "cap", "briefs", "confirm")
#: `--quick` / action [2] asks nothing before the price (FR-285), so one live step remains.
_QUICK_STEPS = ("confirm",)
_PREFERRED_CONFIGS = ("hypedigitaly", "default")  # shipped picker default (30 §2 §Niche packs)
_BRIEF_SUFFIXES = (".yaml", ".yml", ".md", ".txt")
_RATING_PROMPT = ("Fidelity of this batch to its trends? "
                  "[1 poor · 2 acceptable · 3 strong, Enter to skip]: ")


class _Quit(Exception):
    """Ctrl+C, EOF, or an explicit `q` — the operator left before anything started."""


@dataclass(slots=True)
class Console:
    """Two callables — the wizard's only I/O seam, swapped whole in tests, never monkeypatched."""

    ask: Callable[[str], str] = input
    say: Callable[[str], None] = print

    def prompt(self, label: str, current: str = "", *, help_key: str = "") -> str:
        """One pre-filled prompt (FR-57/284). Enter keeps `current`, `?` explains, `q` quits.

        `?` **continues the loop** — help is not an answer. A bare `?` only, never `help`/`h`: a
        brief file named `help` is legal on Windows and would become unselectable.
        """
        while True:
            answer = self.line(f"{label} [{current or 'none'}]: ", quit_on_eof=True).strip()
            if answer.lower() in ("q", "quit"):
                raise _Quit
            if answer == "?":
                self.say(_explain(help_key))
                continue
            return answer or current

    def line(self, question: str, *, quit_on_eof: bool = False) -> str:
        """One raw read. EOF/Ctrl+C ends the wizard, or reads as empty for the post-run prompts."""
        try:
            return self.ask(question)
        except (EOFError, KeyboardInterrupt) as exc:
            if quit_on_eof:
                raise _Quit from exc
            return ""

    def confirm(self, question: str) -> bool:
        """A y/N read; anything else (including EOF) is 'no', because 'no' costs nothing."""
        return self.line(question).strip().lower() in ("y", "yes")


@dataclass(slots=True)
class MenuResult:
    """What the wizard resolved.

    `options` is dispatch-ready: every answer the wizard takes has a CLI flag behind it (30 §5,
    FR-65), so re-loading `config_name` and re-applying `cli.apply_overrides()` reproduces the
    wizard exactly. `config` is that same file already loaded and mutated, passed on so the runner
    skips a redundant second load.
    """

    options: cli.Options
    config: Config | None = None


# --------------------------------------------------------------------------- the wizard


def run_menu(base: cli.Options | None = None, *, console: Console | None = None,
             configs_dir: Path | None = None) -> MenuResult | None:
    """Walk 30 §4's menu and return the run the operator asked for; `None` means they left.

    The pre-wizard action choice comes first (FR-285), four single keys. `[3]` returns
    `Action.PUBLISH` straight away — it does NOT ask which run before admitting it cannot publish.
    `[4]` returns `Action.LIST_MONITORS`, the $0 helper that cures a NOT RUNNABLE row from inside
    the tool instead of demanding the operator know a flag.

    Args:
        base: options from any flags supplied without `--yes`. They pre-fill the prompts instead
            of the raw config (30 §5); what the wizard never asks (`--platforms`,
            `--vision-check`) survives untouched.
        console: I/O seam, defaulting to real `input`/`print`.
        configs_dir: override the `configs/` folder (tests).
    """
    io = console or Console()
    opts = replace(base) if base is not None else cli.Options()
    try:
        io.say("\nHypeSocials — interactive run wizard")
        io.say("Enter keeps the value in brackets · '?' explains the step · 'q' quits")
        # `--quick` IS action [2] (FR-65/285): one implementation, two doors. It must not skip
        # `run_menu` in the dispatcher — that would load `default.yaml` and land on empty ids.
        action = "2" if opts.quick else _pick_action(io)
        if action in ("3", "4"):  # both skip the wizard; the dispatcher owns the rest
            standalone = cli.Action.PUBLISH if action == "3" else cli.Action.LIST_MONITORS
            return MenuResult(replace(opts, action=standalone,
                                      target=opts.target or "latest"))
        if action == "2":
            config = _quick_config(io, opts, configs_dir)
            return None if config is None else MenuResult(
                replace(_options_from(opts, config, opts.briefs), quick=True), config)
        steps = _live_steps(quick=False)
        config = _pick_config(io, opts, steps, configs_dir)
        if config is None:
            return None
        _pick_counts(io, config, steps)
        _pick_cap(io, config, steps)
        briefs = _pick_briefs(io, config, opts, steps)
        _say_confirm_ahead(io, config, steps)
        return MenuResult(_options_from(opts, config, briefs), config)
    except _Quit:
        io.say("\ncancelled — no run was started and nothing was spent")
        return None


def _live_steps(*, quick: bool) -> tuple[str, ...]:
    """The steps THIS run actually asks, in ask order — the only source of an `n/N` counter.

    FR-300: counters are DERIVED from a position in this list, never typed at the call site. A
    step a run does not ask is absent from the list, so the numerator and the denominator can
    never disagree — which is exactly what broke when v2.0.0 deleted two of the seven steps while
    seven call sites still printed a hardcoded seven-step counter.

    The one branch today is `--quick` / action [2], which asks nothing before the price (FR-285)
    and so runs with the confirm notice alone. A future config-disabled step joins by filtering
    this list here and nowhere else.
    """
    return _QUICK_STEPS if quick else _WIZARD_STEPS


def _pick_action(io: Console) -> str:
    """The pre-wizard action choice: one key, four options (FR-56/285).

    Quick run and the monitor-id helper ride THIS prompt rather than adding one, so NFR-16's count
    — one action choice plus five inputs — is untouched: it bounds inputs, not options.
    """
    while True:
        io.say("\n" + _explain("purpose.action"))
        answer = io.prompt("  pick an action", "1", help_key="action")
        if answer in ("1", "2", "3", "4"):
            return answer
        io.say(f"  '{_fit(answer, 20)}' is not one of 1–4")


def _quick_config(io: Console, opts: cli.Options, configs_dir: Path | None) -> Config | None:
    """Action `[2]` / `--quick`: no pickers, but never the unrunnable config either (FR-285).

    `--config` when it named one, else the first RUNNABLE entry of `_PREFERRED_CONFIGS`, else any
    other runnable file, else a refusal showing every config and its blocker (FR-69). Falling
    through to `load_config(None)` would land on `default.yaml`'s empty `virlo_monitor_ids` and
    reproduce the original failure in one keystroke. Still interactive: the confirm gate is next.
    """
    summaries = list_configs(configs_dir)
    order = _preference(summaries, opts.config_name)
    if not order:
        io.say("\nquick run needs a config that can collect trends and dress them;")
        io.say("none of these can:")
        for index, row in enumerate(summaries, start=1):
            for line in _rows(index, row):
                io.say(line)
        io.say("  pick [4] to print your monitor ids, or [1] to walk the guided run")
        return None
    row = order[0]
    try:
        config = load_config(row.path)
    except ConfigError as exc:  # FR-69's one line; the guided run can still pick another file
        io.say(f"  {exc}")
        return None
    opts.config_name = row.name
    cli.apply_overrides(config, opts)  # 30 §5: flags still win over the file, quick or not
    io.say("\nquick run — nothing more is asked before the price. Chosen config:")
    for line in _rows(1, row):
        io.say(line)
    _say_confirm_ahead(io, config, _live_steps(quick=True))
    return config


def _step(io: Console, steps: Sequence[str], key: str, *facts: str) -> None:
    """`n/N  Spend cap — …`: the DERIVED counter, that step's prose (FR-284), then this run's facts.

    The counter is `key`'s position in `steps` (FR-300) — the reason no caller may pass a number.
    The prose is English, so it lives in `wizard_help.md` beside the fuller `?` text — first line
    the heading, the rest already indented. `facts` are what only this config can say.

    Raises:
        ValueError: `key` is not a live step. A programmer error by construction (every call site
            names a `_WIZARD_STEPS` member), and louder is better than a wizard that miscounts.
    """
    number = f"{steps.index(key) + 1}/{len(steps)}"
    head, _, rest = _explain(f"purpose.{key}").partition("\n")
    io.say(f"\n{number}  {head.strip()}")
    if rest.strip():
        io.say(rest)
    for fact in facts:
        io.say("     " + fact)


def _say_confirm_ahead(io: Console, config: Config, steps: Sequence[str]) -> None:
    """The confirm step's purpose line (FR-284): duration, brand signature, output folder.

    The durations are re-derived for v2.0.0 (FR-300e). The old "8-10 minutes" counted a chain that
    no longer exists — downloading the trend's winning video and uploading it to Kie as a
    motion reference. What is left is LLM calls (one batched topic filter, one copy call per
    topic) plus render jobs: still images and carousel slides come back in tens of seconds, while
    a reel is a seed-frame render followed by a Seedance generation whose own ceiling is
    `render.video_job_timeout_s` (300 s per job by default). Hence about three minutes without
    reels, five to eight with them — an estimate, printed as one.

    The branding line is DISPLAY-ONLY on purpose (FR-300d): v2.0.0's direction was fewer operator
    inputs, and brand/ratio/mode are run-wide config facts, not per-run choices. Named future
    option if that ever changes: make it an editable `brand=hypelead ratio=0.50` line parsed by
    `_parse_pairs`, exactly like the counts step — one prompt, not three.
    """
    minutes = "5-8 minutes" if config.run.formats.get("reel", 0) else "about 3 minutes"
    branding = config.branding
    _step(io, steps, "confirm", f"A run of this shape takes {minutes}, and everything",
          "it makes lands under " + _fit(config.output.dir.rstrip("/\\"), 40) + "/<run id>/",
          _fit(f"brand {branding.brand} · ratio {branding.brand_ratio:.2f} · {branding.mode}"
               " · config, not asked", _FACTS_WIDTH))


def _pick_config(io: Console, opts: cli.Options, steps: Sequence[str],
                 configs_dir: Path | None) -> Config | None:
    """Step 1 (FR-56/173/284): two lines per config — its own label, then its readiness facts."""
    summaries = list_configs(configs_dir)
    if not summaries:
        io.say("  no config found — copy configs/default.yaml from a healthy checkout")
        io.say("  Looked in: " + _fit(str(configs_dir or CONFIGS_DIR), 60))
        return None
    default = _default_config_index(summaries, opts.config_name)
    while True:
        _step(io, steps, "config")
        for index, summary in enumerate(summaries, start=1):
            for line in _rows(index, summary, recommended=index == default):
                io.say(line)
        answer = io.prompt("  pick a config", str(default), help_key="config")
        index = _int(answer)
        if index is None or not 1 <= index <= len(summaries):
            io.say(f"  '{_fit(answer, 20)}' is not one of 1–{len(summaries)}")
            continue
        summary = summaries[index - 1]
        try:
            config = load_config(summary.path)
        except ConfigError as exc:  # FR-69's one line — pick another file rather than die here
            io.say(f"  {exc}")
            continue
        opts.config_name = summary.name
        cli.apply_overrides(config, opts)  # 30 §5: flags pre-fill the prompts, the file is intact
        return config


def _preference(summaries: Sequence[ConfigSummary], named: str | None) -> list[ConfigSummary]:
    """`--config`'s row if it named one, else every RUNNABLE row, `_PREFERRED_CONFIGS` first.

    ONE rule behind two doors (FR-285): the picker's pre-fill and the quick action both read it,
    so a bare Enter and `[2]` can never disagree — and neither ever offers a row that has no
    monitor ids and therefore cannot collect a trend. Empty means nothing here can run.
    """
    if chosen := [row for row in summaries
                  if row.name == str(named or "").removesuffix(".yaml")]:
        return chosen
    rank = {name: index for index, name in enumerate(_PREFERRED_CONFIGS)}
    return sorted((row for row in summaries if _runnable(row)),  # stable: file order otherwise
                  key=lambda row: rank.get(row.name, len(rank)))


def _default_config_index(summaries: Sequence[ConfigSummary], named: str | None) -> int:
    """The row a bare Enter takes — never a not-runnable one unless `--config` said so."""
    best = _preference(summaries, named)
    return summaries.index(best[0]) + 1 if best else 1


def _rows(index: int, summary: ConfigSummary, *, recommended: bool = False) -> tuple[str, str]:
    """One config as two lines (FR-284/FR-300): its own label, then its readiness facts.

    The facts line answers the two questions that decide whether a run can happen at all — can
    Virlo be asked (monitor ids), and can its answer be dressed (styles under the active brand) —
    at pick time rather than at a pre-flight refusal three prompts later (FR-295)::

        cs · 2 mon · 4/2/1 · hypelead · 8 styles · recommended
        en · 0 mon · 4/2/0 · hypedigitaly · NO STYLES · NOT RUNNABLE
        en · 1 mon · 4/2/0 · WILL NOT LOAD

    The style count is the count usable under THIS config's brand, and it is replaced outright by
    `NO STYLES` when the registry will not serve this run — a broken registry has no number worth
    printing, and swapping the fact rather than appending a badge keeps both blockers on one line.

    `summary.label` is the file's own one-liner and already fits; a derived niche join is three
    sentences and gets cut. Every variable-length string is LAST on its line, so a wide glyph can
    only spoil a tail. Reels read `Config.reels_plannable`, not `formats.reel > 0` — an unpriced
    `reel_second` means `plan.build_plan` drops every reel, so a row implying otherwise would lie.
    """
    ready = _readiness(summary)
    counts = "/".join(str(summary.formats.get(name, 0)) for name in _FORMATS)
    facts = [summary.language or "en", f"{summary.monitor_count} mon", counts]
    if not ready.loadable:
        # `list_configs` reads a file's summary fields without validating it, so a row can exist
        # for a config that `load_config` refuses. Saying so here beats printing a brand and a
        # style count that were never read from anything.
        facts.append("WILL NOT LOAD")
    else:
        facts.append(ready.brand)
        facts.append("NO STYLES" if ready.styles_blocked else f"{ready.usable_styles} styles")
    if summary.monitor_count <= 0:
        # `[4]` prints monitor ids, which cures THIS blocker only: offering it beside NO STYLES
        # would send the operator to a helper that cannot fix a style registry (and the shorter
        # badge is what keeps a doubly-blocked row inside FR-286's ceiling).
        facts.append("NOT RUNNABLE" if ready.styles_blocked else "NOT RUNNABLE - pick [4]")
    elif recommended and not ready.styles_blocked:
        facts.append("recommended")
    if summary.formats.get("reel", 0) and not ready.reels_priced:
        facts.append("reels unpriced")
    return (f"  [{index}] {_fit(summary.name, _NAME_WIDTH):<{_NAME_WIDTH}}  "
            f"{_fit(summary.description or 'no description', _LABEL_WIDTH)}",
            "      " + _fit(" · ".join(facts), _FACTS_WIDTH))


@dataclass(slots=True)
class _Readiness:
    """What only a LOADED config — and the style registry it resolves — can tell the picker.

    One load answers every question the facts row asks, so a redraw never loads the same file
    three times and no rule is re-derived here that `config.py` or `styles.py` already owns.
    Nothing raises: a file that will not load, or a registry that will not parse, is a row that
    reads NOT RUNNABLE / NO STYLES, which is the whole point of showing it at pick time.
    """

    brand: str = ""
    usable_styles: int = 0  # styles assignable under `brand` (FR-291's brand filter)
    styles_blocked: bool = True  # FR-295: registry missing/broken, or a requested format has none
    reels_priced: bool = False
    loadable: bool = False


#: Keyed on (path, mtime, size): the picker asks per row on every redraw, and an operator who
#: edits a config between two redraws gets a new key rather than yesterday's verdict. Deliberately
#: does not key on `styles.yaml` — one registry serves every row and a wizard lives seconds.
_READINESS: dict[tuple[str, int, int], _Readiness] = {}


def _readiness(summary: ConfigSummary) -> _Readiness:
    """Load `summary`'s config once and ask it, and its style registry, the facts row's questions.

    The registry is resolved exactly as `preflight._check_styles` resolves it — override folder
    first, then the shipped `prompts/` tree (FR-174) — and graded by `styles.validate()`, so a row
    can never disagree with the pre-flight refusal it is predicting (FR-295).
    """
    try:
        stat = summary.path.stat()
        key = (str(summary.path), stat.st_mtime_ns, stat.st_size)
    except OSError:  # a config that vanished between listing and reading claims nothing
        key = (str(summary.path), 0, 0)
    if (cached := _READINESS.get(key)) is not None:
        return cached
    ready = _Readiness()
    _READINESS[key] = ready
    try:
        with _quiet_probe():
            config = load_config(summary.path)
    except ConfigError:
        return ready
    ready.loadable = True
    ready.reels_priced = config.reels_plannable
    ready.brand = config.branding.brand
    try:
        registry = styles.load_registry([config.prompts_dir, PROMPTS_DIR])
    except styles.StyleRegistryError:
        return ready  # missing or unparseable: FR-295 exit 2, shown here as NO STYLES
    ready.usable_styles = sum(1 for style in registry.styles
                              if styles.brand_ok(style, ready.brand))
    ready.styles_blocked = bool(styles.validate(registry, config)[0])
    return ready


@contextmanager
def _quiet_probe() -> Iterator[None]:
    """Silence the config loader's warning logger while the picker PROBES files nobody chose yet.

    `config._warn` logs one line per advisory finding (unpriced reels, a clamped bound, an unknown
    key). That is right for the config a run actually uses — the runner loads it again moments
    later and those lines reach run.log through the real path. Emitting them once per LISTED file,
    while the operator is still reading the menu, would bury the picker in advice about configs
    they are not going to pick, on a channel (`logging`'s last-resort handler) the wizard does not
    own. Suppression is scoped to the probe and restored on every exit path.
    """
    logger = logging.getLogger("hypesocials.config")
    previously_disabled = logger.disabled
    logger.disabled = True
    try:
        yield
    finally:
        logger.disabled = previously_disabled


def _runnable(summary: ConfigSummary) -> bool:
    """Whether this config can serve a run at all — the two blockers that cost nothing to check.

    No monitor ids means Virlo can return nothing (FR-283). A registry that will not parse, or
    that has no style affine to a requested format under the active brand, is a pre-flight exit 2
    (FR-295). Both used to surface after the operator had answered four more prompts; FR-300 moves
    them to the row, and `_preference` therefore never offers such a config to a quick run.
    """
    return summary.monitor_count > 0 and not _readiness(summary).styles_blocked


def _pick_counts(io: Console, config: Config, steps: Sequence[str]) -> None:
    """Step 2 (FR-136/284): formats and counts as ONE editable line, never a prompt per format."""
    slides = max((config.platform(name).carousel_slides for name in config.run.platforms),
                 default=5)
    while True:
        _step(io, steps, "counts",
              f"A deck follows its source slideshow's slide count, up to {slides} "
              "(FR-304).",
              f"The estimate prices the {slides}-slide ceiling per carousel.",
              "Platforms come from the config or --platforms, never asked here:"
              "\n     " + _fit(", ".join(config.run.platforms), 50))
        current = " ".join(f"{_PLURAL[name]}={config.run.formats.get(name, 0)}"
                           for name in _FORMATS)
        pairs = _parse_pairs(io.prompt("  edit the line", current, help_key="counts"))
        counts = {_COUNT_KEYS[key]: _int(value) for key, value in (pairs or {}).items()
                  if key in _COUNT_KEYS}
        if pairs is None or len(counts) != len(pairs) or any(
                value is None or value < 0 for value in counts.values()):
            io.say("  expected whole numbers, e.g. images=4 carousels=2 reels=0")
            continue
        if not any(counts.values()):
            io.say("  that is a zero-creative plan — raise at least one count")
            continue
        config.run.formats.update(counts)  # type: ignore[arg-type]
        if config.run.formats.get("reel", 0) and not config.reels_plannable:
            # Say it here, offer the run without reels — never guess a price.
            io.say("  note: reels have no per-second price yet, so they will not be planned;")
            io.say(f"  the rest of the run is unaffected. Unset key: {config.reel_price_key}")
        return


def _pick_cap(io: Console, config: Config, steps: Sequence[str]) -> None:
    """Step 3 (D11/FR-284): the run's spend cap, VALIDATED against the one price floor.

    No plan estimate here, deliberately. The floor is `Config.min_single_creative_usd` READ, never
    recomputed; a second estimator would need plan entries that do not exist yet, would omit the
    briefs step below it, and would print a *lower* number than the confirm step's. Two
    disagreeing prices two prompts apart is worse than one honest price late.
    """
    floor = config.min_single_creative_usd
    while True:
        _step(io, steps, "cap", *([f"The cheapest single creative this config can buy is "
                                   f"${floor:.2f}."] if floor else []))
        answer = io.prompt("  dollars for this run", f"{config.run.spend_cap_usd:.2f}",
                           help_key="cap")
        value = _float(answer.lstrip("$"))
        if value is None or value <= 0:
            io.say(f"  '{_fit(answer, 20)}' — expected a positive number of dollars")
            continue
        if floor and value < floor:
            io.say(f"  ${value:.2f} is below the ${floor:.2f} floor - pre-flight would refuse "
                   "this run")
            continue
        config.run.spend_cap_usd = value
        return


def _pick_briefs(io: Console, config: Config, opts: cli.Options,
                 steps: Sequence[str]) -> tuple[tuple[str, int], ...]:
    """Step 4 (FR-171/D26/FR-284): names and counts only — never blocks, blank Enter is none."""
    folder = Path(config.briefs_dir)
    names = _brief_names(folder)
    _step(io, steps, "briefs")
    if not names:
        io.say("  none found — skipped. A missing or empty briefs folder is not an error.")
        io.say(f"  Looked in: {_fit(str(folder), 60)}")
        return ()
    for index, name in enumerate(names, start=1):
        io.say(f"  [{index}] {_fit(name, 66)}")
    current = " ".join(f"{name}:{count}" for name, count in opts.briefs)
    while True:
        answer = io.prompt("  pick as <number>:<count>, blank for none", current,
                           help_key="briefs")
        if not answer:
            return ()
        picked = _parse_briefs(answer, names)
        if picked is None:
            io.say(f"  expected e.g. 1:2 3:1 (numbers 1–{len(names)}, or exact brief names)")
            continue
        return picked


def _brief_names(folder: Path) -> list[str]:
    """What the active `briefs_dir` offers: a folder name, or a loose file's stem (30 §2)."""
    try:
        entries = sorted(folder.iterdir()) if folder.is_dir() else []
    except OSError:
        return []
    return sorted({path.name if path.is_dir() else path.stem for path in entries
                   if path.is_dir() or path.suffix.lower() in _BRIEF_SUFFIXES})


def _parse_briefs(answer: str, names: Sequence[str]) -> tuple[tuple[str, int], ...] | None:
    """`1:2 ai-audit-cta:1` → `(("<name>", 2), ("ai-audit-cta", 1))`; `None` if anything is off."""
    picked: list[tuple[str, int]] = []
    for token in answer.replace(",", " ").split():
        name, _, raw = token.partition(":")
        count = _int(raw) if raw else 1
        index = _int(name)
        if index is not None:
            if not 1 <= index <= len(names):
                return None
            name = names[index - 1]
        elif name not in names:
            return None
        if count is None or count < 1:
            return None
        picked.append((name, count))
    return tuple(picked) or None


def _options_from(opts: cli.Options, config: Config,
                  briefs: tuple[tuple[str, int], ...]) -> cli.Options:
    """Every wizard answer in the shape the dispatcher already understands (`cli.Options`).

    `notion` is carried over from the resolved config rather than from a prompt: it is not a
    wizard question any more (FR-300 withdrew the mode/Notion step), but it still has a flag, so
    the round-trip stays exact. The source list stopped travelling entirely at W3.5 — Virlo is
    the only source and `sources.active` is a config-file fact with no flag twin left.
    """
    return replace(
        opts, action=cli.Action.RUN, config_name=config.name,
        counts={name: int(config.run.formats.get(name, 0)) for name in _FORMATS},
        budget_usd=config.run.spend_cap_usd,
        notion=config.run.notion_influence, briefs=briefs, yes=False)


# --------------------------------------------------------------------------- post-plan prompts


async def offer_reduced_plan(config: Config, entries: Sequence[PlanEntry], *,
                             cap_usd: float | None = None,
                             console: Console | None = None) -> tuple[PlanEntry, ...] | None:
    """FR-28's interactive over-cap path: state the gap, OFFER a plan that fits, then decide.

    An interactive run refuses to start over cap — but a bare refusal makes the operator re-run
    the whole wizard guessing a smaller number. `budget.trim()` already computes the deterministic
    plan `--yes` would have run (reverse plan order, atomic groups never split), so the offer *is*
    that plan: the same rule, shown instead of silently applied.

    Returns the entries to build — trimmed ones stay in the plan as `SKIPPED_BUDGET` (FR-4), so
    the run exits 1 — or `None` when the offer was declined or nothing fits at all, which the
    caller turns into exit code 2 with nothing spent.
    """
    io = console or Console()
    cap = config.run.spend_cap_usd if cap_usd is None else float(cap_usd)
    before = estimate_plan(config, entries).expected_usd
    result = trim(config, entries, cap)
    io.say(f"estimate {format_usd(before)} exceeds the {format_usd(cap)} spend cap by "
           f"{format_usd(before - cap)} — an interactive run does not start over cap (FR-28)")
    if not result.fits:
        io.say(f"  trimming cannot help: no single creative fits inside {format_usd(cap)} — "
               "raise --budget or run.spend_cap_usd")
        _restore(result.trimmed)
        return None
    io.say(f"  offered instead: {_counts(result.kept)} at "
           f"{format_usd(result.estimate.expected_usd)} "
           f"({len(result.trimmed)} creative(s) dropped, last-planned first)")
    if await asyncio.to_thread(io.confirm, "  run the reduced plan? [y/N] "):
        return result.kept
    _restore(result.trimmed)
    io.say("  nothing was spent — lower the counts or raise the spend cap and re-run (FR-59)")
    return None


async def ask_fidelity_rating(opts: cli.Options, *,
                              console: Console | None = None) -> int | None:
    """FR-232: the optional 1–3 fidelity rating, asked once after the spend summary.

    **One rating per run, not per creative** — 00-overview's metric is "≥80% of rated runs score
    2+". Suppressed under `--yes` and with no console attached (`cli.console_refusal`), skippable
    with a bare Enter, so nothing unattended ever waits on it. Returns 1, 2, 3 or `None`; the
    value is returned and never written — `runner.py` owns run.log.
    """
    if opts.yes or cli.console_refusal(opts) is not None:
        return None
    io = console or Console()
    answer = (await asyncio.to_thread(io.line, _RATING_PROMPT)).strip()
    rating = _int(answer)
    if rating in (1, 2, 3):
        return rating
    if answer:
        io.say("  not a 1–3 rating — no rating recorded")
    return None


# --------------------------------------------------------------------------- small helpers


#: FR-286's width fitter moved to `util.py` in wave 4 — the runner and the estimate print
#: operator-supplied text too, and one hard slice is what mangled a real console.
_fit = fit


def _explain(help_key: str) -> str:
    """A `## <key>` section of `wizard_help.md` (FR-284), read on first use and cached.

    Anything above the first heading is editor notes. A missing or unreadable file degrades to one
    line — help text is never a reason a wizard stops.
    """
    if not _HELP:
        try:
            blocks = read_text(_HELP_FILE).split("\n## ")[1:]
        except OSError:
            blocks = []
        _HELP[""] = ""  # marks the file as read, so an absent file is not re-read every `?`
        for head, _, body in (block.partition("\n") for block in blocks):
            _HELP[head.strip()] = body.strip("\n")
    return _HELP.get(help_key) or f"  no help text for '{help_key}' — see README.md"


def _restore(entries: Sequence[PlanEntry]) -> None:
    """Undo `trim()`'s mutation when its offer was declined — the plan must not look budget-cut."""
    for entry in entries:
        entry.status = PlanEntryStatus.PENDING
        entry.skip_reason = None


def _counts(entries: Sequence[PlanEntry]) -> str:
    """`images=2 carousels=1 reels=0` for any set of plan entries."""
    tally: dict[str, int] = {}
    for entry in entries:
        tally[entry.creative_format] = tally.get(entry.creative_format, 0) + 1
    return " ".join(f"{_PLURAL[name]}={tally.get(name, 0)}" for name in _FORMATS)


def _parse_pairs(answer: str) -> dict[str, str] | None:
    """`a=1 b=2` → `{"a": "1", "b": "2"}`; `None` when any token is not a `key=value`."""
    pairs: dict[str, str] = {}
    for token in answer.replace(",", " ").split():
        key, sep, value = token.partition("=")
        if not sep or not key.strip() or not value.strip():
            return None
        pairs[key.strip().lower()] = value.strip().lower()
    return pairs or None


def _int(text: str) -> int | None:
    """`"3"` → 3; anything that is not a whole number → `None`."""
    return int(text.strip()) if text.strip().lstrip("+-").isdigit() else None


def _float(text: str) -> float | None:
    try:
        return float(str(text).strip())
    except ValueError:
        return None


__all__ = [
    "Console", "MenuResult", "ask_fidelity_rating", "offer_reduced_plan", "run_menu",
]
