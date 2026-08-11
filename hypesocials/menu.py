"""The interactive wizard — the action choice and six prompts between `run.bat` and a run.

Module contract
---------------
Purpose: own every question HypeSocials asks a human (30 §4: FR-56–60, FR-135/136/137, FR-284/285,
NFR-16), plus the FR-28 over-cap offer and the FR-232 fidelity rating. The wizard decides *what* a
run should be; it never starts one, opens a session, or prices a plan of its own.

Public API: `Console` · `MenuResult` · `run_menu()` · `await offer_reduced_plan()` ·
`await ask_fidelity_rating()`.

Invariants:
- **Numbers and Enter, never spelling** (30 §4): every prompt shows the value in effect and takes
  a bare Enter to keep it (FR-57); a bad answer re-asks instead of guessing intent.
- **Every step explains itself** (FR-284) from `wizard_help.md` — purpose lines on every run,
  fuller prose on `?`. `?` **re-asks**: returning the pre-fill instead would validate on the cap,
  counts and briefs steps and silently advance three steps.
- **Every line this module prints is ≤ 78 characters** (FR-286), with the text it does not own
  (config names, niche descriptors, paths) truncated by `_fit` and placed last. No colour, no box
  drawing, no `✓` — legacy conhost renders none of them.
- **Platforms are never asked** (FR-137) — config file or `--platforms`, nothing else.
- **Step 7 (Confirm) is deliberately NOT here.** `cli.confirm_spend()` owns it, after plan
  expansion, where the estimate is real; pricing a plan that does not exist yet would be a
  parallel estimator (guidelines §2). Step 4 therefore *validates* the cap against
  `Config.min_single_creative_usd` — the one price floor — and never estimates a plan.
- **Nothing here spends or contacts anything** (FR-58/59): steps 1–6 read `configs/` and
  `briefs_dir` off local disk, and quitting at any point costs $0. The quick action never falls
  through to `default.yaml` either: it resolves a *runnable* config or refuses (FR-285).
- **`run_menu()` is synchronous and runs BEFORE the event loop** (`__main__`, right after
  `cli.parse_args`). The two post-plan prompts are async because they are called from inside a
  running loop, and both read the console through `asyncio.to_thread` — never on the loop thread.

Do not: parse flags (`cli.py`), price anything (`budget.py`), read `.env` (D30), load or validate
brief *contents* (`briefs.py` — the picker lists names only), or start a run (`runner.py`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from hypesocials import cli
from hypesocials.budget import estimate as estimate_plan, format_usd, trim
from hypesocials.config import (
    CONFIGS_DIR, Config, ConfigError, ConfigSummary, list_configs, load_config)
from hypesocials.models import PlanEntry, PlanEntryStatus
from hypesocials.util import fit, read_text

#: FR-286: 78 is the ceiling for every printed line. `  [n] ` + a 15-char name + two spaces = 23,
#: so a picker label gets 55; a facts line is indented 6 and keeps 12 chars of slack at 66.
_NAME_WIDTH, _LABEL_WIDTH, _FACTS_WIDTH = 15, 55, 66
#: FR-284's prose, beside this module and NOT under `prompts/` (pre-flight validates that tree).
_HELP_FILE = Path(__file__).with_name("wizard_help.md")
_HELP: dict[str, str] = {}
_FORMATS = ("image", "carousel", "reel")
_PLURAL = {"image": "images", "carousel": "carousels", "reel": "reels"}
_COUNT_KEYS = {**{name: name for name in _FORMATS}, **{v: k for k, v in _PLURAL.items()}}
_MODES = ("analyzed", "direct", "both")
_NOTION = ("off", "copy", "full")
_FUTURE_SOURCES = ("google_trends", "hacker_news")  # named in the picker, not built (D20/FR-135)
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

    `options` is dispatch-ready: every answer now has a CLI flag behind it — the source pick
    included, since `--sources` landed (30 §5, FR-65/135) — so re-loading `config_name` and
    re-applying `cli.apply_overrides()` reproduces the wizard exactly. `config` is that same file
    already loaded and mutated, passed on so the runner skips a redundant second load.
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
        config = _pick_config(io, opts, configs_dir)
        if config is None:
            return None
        _pick_sources(io, config)
        _pick_counts(io, config)
        _pick_cap(io, config)
        _pick_mode(io, config)
        briefs = _pick_briefs(io, config, opts)
        _say_confirm_ahead(io, config)
        return MenuResult(_options_from(opts, config, briefs), config)
    except _Quit:
        io.say("\ncancelled — no run was started and nothing was spent")
        return None


def _pick_action(io: Console) -> str:
    """The pre-wizard action choice: one key, four options (FR-56/285).

    Quick run and the monitor-id helper ride THIS prompt rather than adding one, so NFR-16's count
    — one action choice plus seven inputs — is untouched: it bounds inputs, not options.
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
        io.say("\nquick run needs a config that can collect trends; none of these can:")
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
    _say_confirm_ahead(io, config)
    return config


def _step(io: Console, number: str, key: str, *facts: str) -> None:
    """`4/7  Spend cap — …`: the counter, that step's prose (FR-284), then this run's facts.

    The prose is English, so it lives in `wizard_help.md` beside the fuller `?` text — first line
    the heading, the rest already indented. `facts` are what only this config can say.
    """
    head, _, rest = _explain(f"purpose.{key}").partition("\n")
    io.say(f"\n{number}  {head.strip()}")
    if rest.strip():
        io.say(rest)
    for fact in facts:
        io.say("     " + fact)


def _say_confirm_ahead(io: Console, config: Config) -> None:
    """Step 7's purpose line (FR-284): how long a run of this shape takes, where output lands."""
    minutes = "8-10 minutes" if config.run.formats.get("reel", 0) else "about 3 minutes"
    _step(io, "7/7", "confirm", f"A run of this shape takes {minutes}, and everything",
          "it makes lands under " + _fit(config.output.dir.rstrip("/\\"), 40) + "/<run id>/")


def _pick_config(io: Console, opts: cli.Options, configs_dir: Path | None) -> Config | None:
    """Step 1 (FR-56/173/284): two lines per config — its own label, then its readiness facts."""
    summaries = list_configs(configs_dir)
    if not summaries:
        io.say("  no config found — copy configs/default.yaml from a healthy checkout")
        io.say("  Looked in: " + _fit(str(configs_dir or CONFIGS_DIR), 60))
        return None
    default = _default_config_index(summaries, opts.config_name)
    while True:
        _step(io, "1/7", "config")
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
    """One config as two lines (FR-284): its own label, then its readiness facts.

    `summary.label` is the file's own one-liner and already fits; a derived niche join is three
    sentences and gets cut. Every variable-length string is LAST on its line, so a wide glyph can
    only spoil a tail. Reels read `Config.reels_plannable`, not `formats.reel > 0` — an unpriced
    `reel_second` means `plan.build_plan` drops every reel, so a row implying otherwise would lie.
    """
    counts = "/".join(str(summary.formats.get(name, 0)) for name in _FORMATS)
    facts = [summary.language or "en", f"{summary.monitor_count} monitors",
             f"{counts} img/car/reel"]
    if not _runnable(summary):
        facts.append("NOT RUNNABLE - pick [4]")
    elif recommended:
        facts.append("recommended")
    if summary.formats.get("reel", 0) and not _reels_priced(summary):
        facts.append("reels unpriced")
    return (f"  [{index}] {_fit(summary.name, _NAME_WIDTH):<{_NAME_WIDTH}}  "
            f"{_fit(summary.description or 'no description', _LABEL_WIDTH)}",
            "      " + _fit(" · ".join(facts), _FACTS_WIDTH))


def _reels_priced(summary: ConfigSummary) -> bool:
    """`Config.reels_plannable` for a row that wants reels; an unloadable file claims nothing."""
    try:
        return load_config(summary.path).reels_plannable
    except ConfigError:
        return False


def _runnable(summary: ConfigSummary) -> bool:
    """Whether this config can collect a trend at all: no monitor ids, no Virlo answer."""
    return summary.monitor_count > 0


def _pick_sources(io: Console, config: Config) -> None:
    """Step 2 (FR-135/284): `sources.active` plus the named-but-unbuilt adapters, which refuse."""
    rows = list(dict.fromkeys([*config.sources.active, *_FUTURE_SOURCES]))
    monitors = len(config.sources.virlo_monitor_ids)
    while True:
        _step(io, "2/7", "sources")
        for index, name in enumerate(rows, start=1):
            note = ("   (named, not yet implemented)" if name in _FUTURE_SOURCES else
                    f"   ({monitors} monitor id(s) in this config)" if name == "virlo" else "")
            io.say(f"  [{index}] {name}{note}")
        current = ",".join(str(rows.index(name) + 1) for name in config.sources.active)
        io.say(f"     In effect now: {_fit(', '.join(config.sources.active), 50)}")
        answer = io.prompt("  pick one or more (comma-separated)", current, help_key="sources")
        picked, bad = [], ""
        for token in answer.replace(",", " ").split():
            index = _int(token)
            if index is None or not 1 <= index <= len(rows):
                bad = token
                break
            picked.append(rows[index - 1])
        if bad or not picked:
            io.say(f"  '{_fit(bad or answer, 20)}' is not one of 1–{len(rows)}")
            continue
        if unbuilt := [name for name in picked if name in _FUTURE_SOURCES]:
            io.say("  that adapter is named for a future release and is not built yet — pick")
            io.say(f"  virlo instead. Not built: {_fit(', '.join(unbuilt), 40)}")
            continue
        config.sources.active = list(dict.fromkeys(picked))
        return


def _pick_counts(io: Console, config: Config) -> None:
    """Step 3 (FR-136/284): formats and counts as ONE editable line, never a prompt per format."""
    slides = max((config.platform(name).carousel_slides for name in config.run.platforms),
                 default=5)
    while True:
        _step(io, "3/7", "counts",
              f"A carousel is a deck of {slides} slides, so 2 order {2 * slides} images.",
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


def _pick_cap(io: Console, config: Config) -> None:
    """Step 4 (D11/FR-284): the run's spend cap, VALIDATED against the one price floor.

    No plan estimate here, deliberately. The floor is `Config.min_single_creative_usd` READ, never
    recomputed; a second estimator would need plan entries that do not exist yet, would omit the
    briefs step below it, and would print a *lower* number than step 7's. Two disagreeing prices
    three prompts apart is worse than one honest price late.
    """
    floor = config.min_single_creative_usd
    while True:
        _step(io, "4/7", "cap", *([f"The cheapest single creative this config can buy is "
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


def _pick_mode(io: Console, config: Config) -> None:
    """Step 5 (D2/D7/FR-284): generation mode and Notion influence in one grouped prompt."""
    while True:
        _step(io, "5/7", "mode")
        current = f"mode={config.run.generation_mode} notion={config.run.notion_influence}"
        pairs = _parse_pairs(io.prompt("  edit the line", current, help_key="mode")) or {}
        mode, notion = pairs.get("mode"), pairs.get("notion")
        if set(pairs) - {"mode", "notion"} or mode not in _MODES or notion not in _NOTION:
            io.say("  expected e.g. mode=both notion=off")
            continue
        config.run.generation_mode = mode  # type: ignore[assignment]
        config.run.notion_influence = notion  # type: ignore[assignment]
        return


def _pick_briefs(io: Console, config: Config,
                 opts: cli.Options) -> tuple[tuple[str, int], ...]:
    """Step 6 (FR-171/D26/FR-284): names and counts only — never blocks, blank Enter is none."""
    folder = Path(config.briefs_dir)
    names = _brief_names(folder)
    _step(io, "6/7", "briefs")
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
    """Every wizard answer in the shape the dispatcher already understands (`cli.Options`)."""
    return replace(
        opts, action=cli.Action.RUN, config_name=config.name,
        counts={name: int(config.run.formats.get(name, 0)) for name in _FORMATS},
        sources=tuple(config.sources.active),
        budget_usd=config.run.spend_cap_usd, mode=config.run.generation_mode,
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
