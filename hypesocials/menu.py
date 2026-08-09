"""The interactive wizard — the six prompts between `run.bat` and a resolved run.

Module contract
---------------
Purpose: own every question HypeSocials asks a human (30 §4: FR-56–60, FR-135/136/137, NFR-16),
plus the FR-28 over-cap offer and the FR-232 fidelity rating. The wizard decides *what* a run
should be; it never starts one, opens a session, or prices a plan of its own.

Public API: `Console` · `MenuResult` · `run_menu()` · `await offer_reduced_plan()` ·
`await ask_fidelity_rating()`.

Invariants:
- **Numbers and Enter, never spelling** (30 §4): every prompt shows the value in effect and takes
  a bare Enter to keep it (FR-57); a bad answer re-asks instead of guessing intent.
- **Platforms are never asked** (FR-137) — config file or `--platforms`, nothing else.
- **Step 7 (Confirm) is deliberately NOT here.** `cli.confirm_spend()` owns it, after plan
  expansion, where the estimate is real; pricing a plan that does not exist yet would be a
  parallel estimator (guidelines §2). The wizard hands back options and stops.
- **Nothing here spends or contacts anything** (FR-58/59): steps 1–6 read `configs/` and
  `briefs_dir` off local disk, and quitting at any point costs $0.
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

    def prompt(self, label: str, current: str = "") -> str:
        """One pre-filled prompt (FR-57). Bare Enter keeps `current`; EOF/Ctrl+C/`q` quits."""
        answer = self.line(f"{label} [{current or 'none'}]: ", quit_on_eof=True).strip()
        if answer.lower() in ("q", "quit"):
            raise _Quit
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

    `options` is dispatch-ready: it carries every answer that has a CLI flag, so re-loading
    `config_name` and re-applying `cli.apply_overrides()` reproduces the wizard. `config` is that
    same file already loaded and mutated, and is the ONLY carrier of the one menu answer with no
    flag behind it — `sources.active` (FR-135). Drop it and the source pick is silently dropped.
    """

    options: cli.Options
    config: Config | None = None


# --------------------------------------------------------------------------- the wizard


def run_menu(base: cli.Options | None = None, *, console: Console | None = None,
             configs_dir: Path | None = None) -> MenuResult | None:
    """Walk 30 §4's menu and return the run the operator asked for; `None` means they left.

    The pre-wizard action choice comes first (FR-175's menu half): "Publish a finished run"
    returns `Action.PUBLISH` with its target, so the dispatcher answers with the same Phase 2
    placeholder `--publish` already prints — one honest message, not two.

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
        io.say("\nHypeSocials — interactive run wizard "
               "(Enter keeps the value in brackets, 'q' quits)")
        if io.prompt("  [1] Start a new run  [2] Publish a finished run", "1").startswith("2"):
            target = io.prompt("  which run", opts.target or "latest")
            return MenuResult(replace(opts, action=cli.Action.PUBLISH, target=target))
        config = _pick_config(io, opts, configs_dir)
        if config is None:
            return None
        _pick_sources(io, config)
        _pick_counts(io, config)
        _pick_cap(io, config)
        _pick_mode(io, config)
        briefs = _pick_briefs(io, config, opts)
        io.say("\n7/7  Confirm — the cost estimate and the final yes/no come next; "
               "nothing has been billed yet.")
        return MenuResult(_options_from(opts, config, briefs), config)
    except _Quit:
        io.say("\ncancelled — no run was started and nothing was spent (FR-59)")
        return None


def _pick_config(io: Console, opts: cli.Options, configs_dir: Path | None) -> Config | None:
    """Step 1 (FR-56/173): every `configs/*.yaml` with its line-1 or `niche:` description."""
    summaries = list_configs(configs_dir)
    if not summaries:
        io.say(f"  no config files in {configs_dir or CONFIGS_DIR} — a healthy checkout ships "
               "configs/default.yaml; copy it to make your own (30 §8)")
        return None
    default = _default_config_index(summaries, opts.config_name)
    while True:
        io.say("\n1/6  Config")
        for index, summary in enumerate(summaries, start=1):
            # A niche descriptor is three sentences long (FR-173); the picker gets one line of it.
            about = (summary.description or "no description")[:78]
            io.say(f"  [{index}] {summary.name:<18} {about}")
        answer = io.prompt("  pick a config", str(default))
        index = _int(answer)
        if index is None or not 1 <= index <= len(summaries):
            io.say(f"  '{answer}' is not one of 1–{len(summaries)}")
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


def _default_config_index(summaries: Sequence[ConfigSummary], named: str | None) -> int:
    """`--config` wins, then the shipped niche, then `default.yaml`, then whatever is first."""
    names = [summary.name for summary in summaries]
    for candidate in (str(named or "").removesuffix(".yaml"), *_PREFERRED_CONFIGS):
        if candidate in names:
            return names.index(candidate) + 1
    return 1


def _pick_sources(io: Console, config: Config) -> None:
    """Step 2 (FR-135): `sources.active` plus the named-but-unbuilt adapters, which refuse."""
    rows = list(dict.fromkeys([*config.sources.active, *_FUTURE_SOURCES]))
    while True:
        io.say("\n2/6  Sources")
        for index, name in enumerate(rows, start=1):
            io.say(f"  [{index}] {name}"
                   + ("   (named, not yet implemented)" if name in _FUTURE_SOURCES else ""))
        current = ",".join(str(rows.index(name) + 1) for name in config.sources.active)
        answer = io.prompt("  pick one or more (comma-separated)", current)
        picked, bad = [], ""
        for token in answer.replace(",", " ").split():
            index = _int(token)
            if index is None or not 1 <= index <= len(rows):
                bad = token
                break
            picked.append(rows[index - 1])
        if bad or not picked:
            io.say(f"  '{bad or answer}' is not one of 1–{len(rows)}")
            continue
        if unbuilt := [name for name in picked if name in _FUTURE_SOURCES]:
            io.say(f"  {', '.join(unbuilt)} is named for a future adapter and is not built yet — "
                   "pick virlo (D20/FR-135)")
            continue
        config.sources.active = list(dict.fromkeys(picked))
        return


def _pick_counts(io: Console, config: Config) -> None:
    """Step 3 (FR-136): formats and counts as ONE editable line, never a prompt per format."""
    while True:
        io.say("\n3/6  Formats & counts")
        current = " ".join(f"{_PLURAL[name]}={config.run.formats.get(name, 0)}"
                           for name in _FORMATS)
        pairs = _parse_pairs(io.prompt("  edit the line", current))
        counts = {_COUNT_KEYS[key]: _int(value) for key, value in (pairs or {}).items()
                  if key in _COUNT_KEYS}
        if pairs is None or len(counts) != len(pairs) or any(
                value is None or value < 0 for value in counts.values()):
            io.say("  expected whole numbers, e.g. images=4 carousels=2 reels=0")
            continue
        if not any(counts.values()):
            io.say("  that is a zero-creative plan — raise at least one count (FR-64)")
            continue
        config.run.formats.update(counts)  # type: ignore[arg-type]
        if config.run.formats.get("reel", 0) and not config.reels_plannable:
            # FR-131/FR-107: say it here, offer the run without reels — never guess a price.
            io.say(f"  note: {config.reel_price_key} is unset, so reels will not be planned; "
                   "the rest of the run is unaffected (FR-131, OQ-2)")
        return


def _pick_cap(io: Console, config: Config) -> None:
    """Step 4: the run's spend cap in dollars (D11)."""
    while True:
        io.say("\n4/6  Spend cap")
        answer = io.prompt("  dollars for this run", f"{config.run.spend_cap_usd:.2f}")
        value = _float(answer.lstrip("$"))
        if value is None or value <= 0:
            io.say(f"  '{answer}' — expected a positive number of dollars")
            continue
        config.run.spend_cap_usd = value
        return


def _pick_mode(io: Console, config: Config) -> None:
    """Step 5: generation mode and Notion influence in one grouped prompt (D2/D7)."""
    while True:
        io.say(f"\n5/6  Mode & Notion influence — mode: {'|'.join(_MODES)} · "
               f"notion: {'|'.join(_NOTION)}")
        current = f"mode={config.run.generation_mode} notion={config.run.notion_influence}"
        pairs = _parse_pairs(io.prompt("  edit the line", current)) or {}
        mode, notion = pairs.get("mode"), pairs.get("notion")
        if set(pairs) - {"mode", "notion"} or mode not in _MODES or notion not in _NOTION:
            io.say("  expected e.g. mode=both notion=off")
            continue
        config.run.generation_mode = mode  # type: ignore[assignment]
        config.run.notion_influence = notion  # type: ignore[assignment]
        return


def _pick_briefs(io: Console, config: Config,
                 opts: cli.Options) -> tuple[tuple[str, int], ...]:
    """Step 6 (FR-171/D26): names and counts only — never blocks, blank Enter means none."""
    folder = Path(config.briefs_dir)
    names = _brief_names(folder)
    io.say("\n6/6  Briefs (optional)")
    if not names:
        io.say(f"  none found in {folder} — skipped (a missing briefs_dir is no error, 30 §8)")
        return ()
    for index, name in enumerate(names, start=1):
        io.say(f"  [{index}] {name}")
    current = " ".join(f"{name}:{count}" for name, count in opts.briefs)
    while True:
        answer = io.prompt("  pick as <number>:<count>, blank for none", current)
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
