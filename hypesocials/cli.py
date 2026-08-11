"""Flags in, one resolved intent out — plus the Confirm gate money may not move without.

Module contract
---------------
Purpose: parse the CLI surface of 30 §5 (FR-61–66), route the six standalone actions of the
FR-252 table, apply flag-over-config overrides for this run only, and own the pre-flight cost
display + confirmation (FR-58/59, FR-28, FR-282). Nothing here opens a session, reads a trend or
writes an asset — `runner.py` does that once this module says the operator agreed.

Public API: `Action` · `Options` · `parse_args()` · `apply_overrides()` · `estimate_report()` ·
`await confirm_spend()` · `ConfirmOutcome`.

Invariants:
- **Flags win, the config file is never rewritten** (FR-61). Overrides mutate the loaded `Config`
  object for this process only.
- **An unknown flag dies before config load** (FR-63) — argparse's own one-line error, exit 2,
  nothing on disk because no `run_id` exists yet.
- **The provenance block prints BEFORE the prompt** (FR-282): every priced row names the config
  key its rate came from, whether that key was written in the file or defaulted, and which
  configured model the rate is *assumed for*; unpriced rows say so instead of reading as free.
- **Interactive refuses over cap, `--yes` trims** (FR-28). The `--yes` path calls
  `budget.trim()` — reverse plan order, atomic groups intact — and refuses outright only when
  trimming cannot help (nothing fits at all).
- **Declining costs nothing** (FR-59): the answer is read before any provider is contacted.
- The blocking `input()` runs in a worker thread, so the confirm never stalls the event loop.

Do not: build a menu here (`menu.py`, W5 — argparse is not a wizard), price anything (that is
`budget.py`), or read the environment (`preflight.py` owns secrets).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum

from hypesocials.budget import Estimate, TrimResult, estimate as estimate_plan, format_usd, trim
from hypesocials.config import (  # `_BOUNDS` is THE bound table — a flag must never retype a bound
    CONFIGS_DIR, PLATFORMS, Config, _BOUNDS as _CONFIG_BOUNDS)
from hypesocials.models import PlanEntry
from hypesocials.sources import SOURCE_STATUS
from hypesocials.util import wrapped

PROG = "run.bat"  # what the operator actually launches; `python -m hypesocials` is the inner call
_WIDTH = 78  # FR-286: help wraps here, never at the console width, which legacy conhost mangles
_MODES = ("analyzed", "direct", "both")
_NOTION = ("off", "copy", "full")


class Action(str, Enum):
    """FR-252's routing table: one run path plus five standalone actions that never start a run."""

    RUN = "run"
    LIST_MONITORS = "list-monitors"
    PREVIEW_SOURCES = "preview-sources"
    PREVIEW_ANALYSIS = "preview-analysis"
    PUBLISH = "publish"
    PROMOTE = "promote"


@dataclass(slots=True)
class Options:
    """One parsed invocation. Every field is "what the operator asked for", never a default."""

    action: Action = Action.RUN
    config_name: str | None = None
    counts: dict[str, int] = field(default_factory=dict)  # only the formats a flag named
    platforms: list[str] | None = None
    sources: tuple[str, ...] = ()  # `--sources`, the CLI twin of the menu's picker (FR-135)
    budget_usd: float | None = None
    mode: str | None = None
    notion: str | None = None
    vision_check: bool = False
    briefs: tuple[tuple[str, int], ...] = ()  # `--brief <name>:<count>`, repeatable (FR-171)
    yes: bool = False
    quick: bool = False  # skip the wizard's questions, keep the confirm gate — a modifier, not an
    #   `Action`: it still routes through `Action.RUN` (W2 wires the flag and the menu's [2])
    history_days: int | None = None  # `--history-days`, the recency window for this run only
    target: str = ""  # `--publish <run_id>` / `--promote <run_id>`, incl. the literal "latest"
    at: str = ""  # Phase 2 schedule time for --promote

    @property
    def interactive(self) -> bool:
        """FR-66: a run without `--yes` needs a console to ask on."""
        return not self.yes


# --------------------------------------------------------------------------- parsing


def parse_args(argv: Sequence[str] | None = None) -> Options:
    """Parse flags per 30 §5. Exits 2 with one line on an unknown or malformed flag (FR-63/69)."""
    parser = _parser()
    ns = parser.parse_args(list(argv) if argv is not None else None)
    counts = {name: value for name, value in
              (("image", ns.images), ("carousel", ns.carousels), ("reel", ns.reels))
              if value is not None}
    return Options(
        action=_action(ns),
        config_name=ns.config,
        counts=counts,
        platforms=ns.platforms,  # already the checked, deduped list (`_platforms`)
        sources=tuple(ns.sources or ()),
        budget_usd=ns.budget,
        mode=ns.mode,
        notion=ns.notion,
        vision_check=bool(ns.vision_check),
        briefs=tuple(ns.brief or ()),
        yes=bool(ns.yes),
        quick=bool(ns.quick),
        history_days=ns.history_days,
        target=str(ns.publish or ns.promote or ""),
        at=str(ns.at or ""),
    )


class _Help(argparse.RawDescriptionHelpFormatter):
    """Fixed-width help: wrap at `_WIDTH`, print the epilog exactly as written (FR-286)."""

    def __init__(self, prog: str) -> None:
        super().__init__(prog, width=_WIDTH)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, allow_abbrev=False, formatter_class=_Help,
        description="HypeSocials — viral social creatives from live Virlo trends.",
        epilog="Examples\n"
               "  run.bat --config hypedigitaly --images 2 --budget 2\n"
               "  run.bat --config hypedigitaly --brief ai-audit-cta:2 --yes --budget 2\n\n"
               "No flags plus a console shows the menu. Walkthrough: README.md")
    parser.add_argument("--config", metavar="NAME", help=f"config in configs/: {_config_names()}")
    parser.add_argument("--images", type=int, metavar="N", help="override the image count")
    parser.add_argument("--carousels", type=int, metavar="N", help="override the carousel count")
    parser.add_argument("--reels", type=int, metavar="N", help="override the reel count")
    parser.add_argument("--platforms", type=_platforms, metavar="LIST",
                        help="comma-separated platform list (FR-137)")
    parser.add_argument("--sources", type=_sources, metavar="LIST",
                        help="comma-separated source list, overrides sources.active (FR-135)")
    parser.add_argument("--budget", type=float, metavar="USD", help="override the spend cap")
    parser.add_argument("--mode", choices=_MODES, help="generation mode (D2)")
    parser.add_argument("--notion", choices=_NOTION, help="Notion influence level (D7)")
    parser.add_argument("--vision-check", action="store_true", help="enable the vision check (D3)")
    parser.add_argument("--history-days", type=_history_days, metavar="N",
                        help="recency window in days for this run; 0 turns the window off")
    parser.add_argument("--brief", action="append", type=_brief, metavar="NAME:COUNT",
                        help="request a campaign brief; repeatable (FR-171)")
    # Adjacent, one group: usage prints `[--quick | --yes]`; exclusive because --quick still asks.
    gate = parser.add_mutually_exclusive_group()
    gate.add_argument("--quick", action="store_true",
                      help="skip the menu's questions but still ask before spending")
    gate.add_argument("--yes", action="store_true", help="skip the menu; unattended (FR-60/252)")
    parser.add_argument("--list-monitors", action="store_true",
                        help="print every Virlo monitor id and name, then exit (FR-251)")
    parser.add_argument("--preview-sources", action="store_true",
                        help="trends + verdicts, no model spend; Virlo's trend digest "
                             "still meters against your Virlo deposit")
    parser.add_argument("--preview-analysis", action="store_true",
                        help="also style briefs and copy, LLM cost only (FR-140)")
    parser.add_argument("--publish", metavar="RUN_ID", help="(Phase 2, not implemented)")
    parser.add_argument("--promote", metavar="RUN_ID", help="(Phase 2, not implemented)")
    parser.add_argument("--at", metavar="ISO", help="(Phase 2, not implemented) --promote time")
    return parser


def _config_names() -> str:
    """The `--config` values that exist right now, so `--help` can answer "pass what?"."""
    names = sorted(path.stem for path in CONFIGS_DIR.glob("*.yaml"))
    return ", ".join(names) if names else "none found - expected default.yaml"


def _history_days(value: str) -> int:
    """`--history-days N` → the recency window, REFUSED out of range rather than clamped (FR-285).

    The bound is `config.py`'s own table, the one that validates `run.trend_history_days` inside a
    file, so the flag can never accept a number the config loader would reject. A clamp would hide
    an operator typo until the run was over, which is the whole failure class this refusal removes.
    """
    low, high, _ = _CONFIG_BOUNDS["run.trend_history_days"]
    if not value.strip().lstrip("+").isdigit() or not low <= int(value) <= high:
        raise argparse.ArgumentTypeError(f"expected {int(low)}-{int(high)} days (0 = window off)")
    return int(value)


def _action(ns: argparse.Namespace) -> Action:
    """Standalone actions win over the run path, in the order 30 §5 lists them."""
    for flag, action in (("list_monitors", Action.LIST_MONITORS),
                         ("preview_sources", Action.PREVIEW_SOURCES),
                         ("preview_analysis", Action.PREVIEW_ANALYSIS),
                         ("publish", Action.PUBLISH), ("promote", Action.PROMOTE)):
        if getattr(ns, flag, None):
            return action
    return Action.RUN


def _sources(value: str) -> tuple[str, ...]:
    """`--sources virlo` → the source pick, validated exactly as the menu's picker validates it.

    Same two refusals as `menu._pick_sources` (FR-135), because this flag IS that step for an
    unattended run: an unknown name lists the vocabulary, and a named-but-unbuilt adapter is
    refused outright rather than accepted and silently skipped at Collect.
    """
    names = list(dict.fromkeys(name.strip() for name in str(value).split(",") if name.strip()))
    if not names or any(name not in SOURCE_STATUS for name in names):
        raise argparse.ArgumentTypeError(
            f"--sources {value!r} — expected a comma-separated list of: "
            + " | ".join(SOURCE_STATUS))
    if unbuilt := [name for name in names if not SOURCE_STATUS[name]]:
        raise argparse.ArgumentTypeError(
            f"--sources {value!r} — {', '.join(unbuilt)} is named for a future adapter and is not "
            "built yet; pick virlo (FR-135)")
    return tuple(names)


def _platforms(value: str) -> list[str]:
    """`--platforms linkedin,tiktok` → the pick, checked against D6's fixed set (FR-51/69/137).

    Checked HERE, at the boundary, exactly as `--sources` is: argparse exits 2 with one line
    before any config load, so `linkedn` costs $0 instead of loading clean and spending the plan
    on its correctly-spelled siblings. `config._validate` is the file-side twin (same tuple),
    which is why `apply_overrides` can trust `opts.platforms` and never re-checks it.
    """
    names = list(dict.fromkeys(name.strip() for name in str(value).split(",") if name.strip()))
    if not names or any(name not in PLATFORMS for name in names):
        raise argparse.ArgumentTypeError(
            f"--platforms {value!r} — expected a comma-separated list of: " + " | ".join(PLATFORMS))
    return names


def _brief(value: str) -> tuple[str, int]:
    name, _, raw = str(value).partition(":")
    count = raw.strip() or "1"
    if not name.strip() or not count.isdigit() or int(count) < 1:
        raise argparse.ArgumentTypeError(
            f"--brief {value!r} — expected <name>:<count>, e.g. ai-audit-cta:2")
    return name.strip(), int(count)


# --------------------------------------------------------------------------- overrides


def apply_overrides(config: Config, opts: Options) -> list[str]:
    """Apply flag-over-config for THIS run only (FR-61). Returns one note per override applied."""
    applied: list[str] = []
    for fmt, value in opts.counts.items():
        config.run.formats[fmt] = max(0, int(value))
        applied.append(f"run.formats.{fmt}={config.run.formats[fmt]}")
    if opts.platforms:
        config.run.platforms = list(opts.platforms)
        for name in opts.platforms:
            config.run.languages.setdefault(name, "en")
        applied.append(f"run.platforms={','.join(opts.platforms)}")
    if opts.sources:
        config.sources.active = list(opts.sources)
        applied.append(f"sources.active={','.join(opts.sources)}")
    if opts.budget_usd is not None:
        config.run.spend_cap_usd = float(opts.budget_usd)
        applied.append(f"run.spend_cap_usd={format_usd(config.run.spend_cap_usd)}")
    if opts.mode:
        config.run.generation_mode = opts.mode  # type: ignore[assignment]
        applied.append(f"run.generation_mode={opts.mode}")
    if opts.notion:
        config.run.notion_influence = opts.notion  # type: ignore[assignment]
        applied.append(f"run.notion_influence={opts.notion}")
    if opts.vision_check:
        config.run.vision_check = True
        applied.append("run.vision_check=true")
    if opts.history_days is not None:  # already range-checked at the boundary by `_history_days`
        config.run.trend_history_days = int(opts.history_days)
        applied.append(f"run.trend_history_days={config.run.trend_history_days}")
    return applied


# --------------------------------------------------------------------------- the confirm gate


@dataclass(slots=True)
class ConfirmOutcome:
    """The gate's verdict: what may be built, what it is expected to cost, and why."""

    approved: bool
    entries: tuple[PlanEntry, ...]
    estimate: Estimate
    exit_code: int = 0  # meaningful only when `approved` is False: 0 declined, 2 refused
    reason: str = ""
    trimmed: TrimResult | None = None


async def confirm_spend(
    config: Config,
    entries: Sequence[PlanEntry],
    *,
    assume_yes: bool,
    emit: Callable[[str], None],
    cap_usd: float | None = None,
) -> ConfirmOutcome:
    """Show the estimate, then decide whether money may move (FR-58/59, FR-28, FR-282).

    Args:
        config: the loaded run config — the only price source (NFR-18: no network).
        entries: the expanded plan; `budget.estimate()` stamps each entry's expected share.
        assume_yes: `--yes`. Over cap it auto-trims (FR-28) instead of asking; under cap it
            approves without a prompt but still emits the whole block for `run.log`.
        emit: writes one operator-facing block — the runner prints it and logs it verbatim.
        cap_usd: override for the cap comparison; defaults to `run.spend_cap_usd`.

    Returns:
        `ConfirmOutcome`. `approved=False` with `exit_code=0` is a clean decline (no calls made,
        FR-59); with `exit_code=2` it is a refusal — over cap interactively, or a cap so low that
        trimming cannot help.
    """
    cap = config.run.spend_cap_usd if cap_usd is None else float(cap_usd)
    estimate = estimate_plan(config, entries)
    emit(estimate_report(estimate, entries, cap))

    if estimate.expected_usd > cap:
        gap = estimate.expected_usd - cap
        if not assume_yes:  # FR-28: a human who can decide should decide
            return ConfirmOutcome(
                False, tuple(entries), estimate, exit_code=2,
                reason=(f"estimate {format_usd(estimate.expected_usd)} exceeds the "
                        f"{format_usd(cap)} spend cap by {format_usd(gap)} — lower the counts, "
                        "raise --budget, or re-run with --yes to auto-trim to fit (FR-28)"))
        result = trim(config, entries, cap)
        emit(result.summary_line)
        if not result.fits:
            return ConfirmOutcome(
                False, tuple(entries), result.estimate, exit_code=2,
                reason=(f"the {format_usd(cap)} cap is below the cost of any single creative — "
                        "trimming cannot help; raise --budget (FR-28)"))
        return ConfirmOutcome(True, result.kept, result.estimate, trimmed=result)

    if assume_yes:
        return ConfirmOutcome(True, tuple(entries), estimate)

    # The prompt states its own semantics because the wizard trains "Enter keeps the value" seven
    # times before this line, and here Enter cancels. Only y/yes starts — now it says so.
    question = (f"Start the run and spend up to {format_usd(estimate.expected_usd)} "
                f"(worst case {format_usd(estimate.worst_case_usd)})?\n"
                "  y = start · Enter or n = cancel, nothing is billed: ")
    answer = (await asyncio.to_thread(_ask, question)).strip().lower()
    if answer in ("y", "yes"):
        return ConfirmOutcome(True, tuple(entries), estimate)
    return ConfirmOutcome(False, tuple(entries), estimate, exit_code=0,
                          reason="declined at the confirm prompt — nothing was spent (FR-59)")


def _ask(question: str) -> str:
    """Blocking console read, always called through `asyncio.to_thread`."""
    try:
        return input(question)
    except (EOFError, KeyboardInterrupt):
        return "n"


def estimate_report(estimate: Estimate, entries: Sequence[PlanEntry], cap_usd: float) -> str:
    """The pre-confirm block: aggregated priced rows with FR-282 provenance, then the totals.

    Rows collapse per line *kind* and price key so a twelve-creative plan still reads in one
    glance; each row still names the key, its origin and the model the rate is assumed for,
    which is the whole point of FR-282 — a swapped model carrying yesterday's price is visible
    on screen, not on the invoice.
    """
    rows: dict[tuple[str, str, bool], list[float]] = {}
    labels: dict[tuple[str, str, bool], tuple[str, str, str]] = {}
    for line in estimate.lines:
        key = (line.code, line.price_key, line.allowance)
        bucket = rows.setdefault(key, [0.0, 0.0])
        bucket[0] += line.quantity
        bucket[1] += line.amount_usd
        labels.setdefault(key, (line.code, line.price_origin, line.assumed_model))

    out = [f"Cost estimate — {len(entries)} planned creative(s), cap {format_usd(cap_usd)}"]
    for key, (quantity, amount) in rows.items():
        code, origin, model = labels[key]
        tail = " (worst-case allowance)" if key[2] else ""
        # Sub-cent lines print at four decimals: a real $0.0019 copy call must never look like
        # the "$0.00" of an unpriced one (FR-282's whole point is telling those two apart).
        rate = (f"${amount:.4f}" if 0 < amount < 0.01 else format_usd(amount)) if amount \
            else "unpriced — contributes $0.00"
        out.append(f"  {code:<28} x{quantity:<6g} {rate}{tail}")
        out.append(f"      price {key[1]} [{origin}]")  # two lines, each ending in its variable
        out.append(f"            assumed for {model}")  # part: a long model id never truncates
    for line in estimate.blocked:
        # FR-286: `label` carries FR-131's full diagnosis and runs past 100 chars with a real
        # asset id, so the PRINTER wraps it. Shortening the label instead would drop the price
        # key an operator needs to go and set.
        out.extend(f"  {'BLOCKED  ' if first else '           '}{part}"
                   for first, part in wrapped(line.label, _WIDTH - 11))
    if estimate.banner:
        out.append(f"  {estimate.banner}")
        out.append("  those lines contribute $0.00 to this total")
    # "(Kie/OpenRouter)" is not decoration: Virlo's trend calls meter against a prepaid deposit
    # this estimator cannot price, so an unqualified total would read as "the whole run costs $X".
    out.append(f"  expected {format_usd(estimate.expected_usd)} (Kie/OpenRouter) · "
               f"worst case {format_usd(estimate.worst_case_usd)} · "
               f"cap {format_usd(cap_usd)}")
    out.append("  Nothing billed yet. Virlo trend calls meter against your Virlo deposit.")
    return "\n".join(out)


def console_refusal(opts: Options) -> str | None:
    """FR-66: an interactive run with no terminal to ask on refuses instead of hanging."""
    if not opts.interactive:
        return None
    try:
        attached = bool(sys.stdin) and sys.stdin.isatty()
    except (AttributeError, ValueError):  # pragma: no cover - detached stdin
        attached = False
    return None if attached else (
        "no interactive terminal available, use --yes — an unattended run must pass --yes so no "
        "prompt can block it (FR-66)")


__all__ = [
    "Action", "ConfirmOutcome", "Options", "PROG", "apply_overrides", "confirm_spend",
    "console_refusal", "estimate_report", "parse_args",
]
