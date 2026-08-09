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
from hypesocials.config import Config
from hypesocials.models import PlanEntry

PROG = "hypesocials"
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
    budget_usd: float | None = None
    mode: str | None = None
    notion: str | None = None
    vision_check: bool = False
    briefs: tuple[tuple[str, int], ...] = ()  # `--brief <name>:<count>`, repeatable (FR-171)
    yes: bool = False
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
        platforms=[p.strip() for p in ns.platforms.split(",") if p.strip()] if ns.platforms else None,
        budget_usd=ns.budget,
        mode=ns.mode,
        notion=ns.notion,
        vision_check=bool(ns.vision_check),
        briefs=tuple(ns.brief or ()),
        yes=bool(ns.yes),
        target=str(ns.publish or ns.promote or ""),
        at=str(ns.at or ""),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, allow_abbrev=False,
        description="HypeSocials — viral social creatives from live Virlo trends.",
        epilog="No flags and a console attached shows the interactive menu (Wave 5).")
    parser.add_argument("--config", metavar="NAME", help="config file in configs/ (FR-61)")
    parser.add_argument("--images", type=int, metavar="N", help="override the image count")
    parser.add_argument("--carousels", type=int, metavar="N", help="override the carousel count")
    parser.add_argument("--reels", type=int, metavar="N", help="override the reel count")
    parser.add_argument("--platforms", metavar="LIST", help="comma-separated platform list (FR-137)")
    parser.add_argument("--budget", type=float, metavar="USD", help="override the spend cap")
    parser.add_argument("--mode", choices=_MODES, help="generation mode (D2)")
    parser.add_argument("--notion", choices=_NOTION, help="Notion influence level (D7)")
    parser.add_argument("--vision-check", action="store_true", help="enable the vision check (D3)")
    parser.add_argument("--brief", action="append", type=_brief, metavar="NAME:COUNT",
                        help="request a campaign brief; repeatable (FR-171)")
    parser.add_argument("--yes", action="store_true", help="skip the menu; unattended (FR-60/252)")
    parser.add_argument("--list-monitors", action="store_true",
                        help="print every Virlo monitor id and name, then exit (FR-251)")
    parser.add_argument("--preview-sources", action="store_true",
                        help="trends + eligibility verdicts, zero model spend (FR-139)")
    parser.add_argument("--preview-analysis", action="store_true",
                        help="also style briefs and copy, LLM cost only (FR-140)")
    parser.add_argument("--publish", metavar="RUN_ID", help="Phase 2 placeholder (FR-175)")
    parser.add_argument("--promote", metavar="RUN_ID", help="Phase 2 placeholder (FR-175)")
    parser.add_argument("--at", metavar="ISO", help="Phase 2 schedule time for --promote")
    return parser


def _action(ns: argparse.Namespace) -> Action:
    """Standalone actions win over the run path, in the order 30 §5 lists them."""
    for flag, action in (("list_monitors", Action.LIST_MONITORS),
                         ("preview_sources", Action.PREVIEW_SOURCES),
                         ("preview_analysis", Action.PREVIEW_ANALYSIS),
                         ("publish", Action.PUBLISH), ("promote", Action.PROMOTE)):
        if getattr(ns, flag, None):
            return action
    return Action.RUN


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

    question = (f"Proceed and spend up to {format_usd(estimate.expected_usd)} "
                f"(worst case {format_usd(estimate.worst_case_usd)})? [y/N] ")
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
        out.append(f"      price {key[1]} [{origin}] — assumed for {model}")
    for line in estimate.blocked:
        out.append(f"  BLOCKED  {line.label}")
    if estimate.banner:
        out.append(f"  {estimate.banner} — those lines contribute $0.00 to this total (FR-282)")
    out.append(f"  expected {format_usd(estimate.expected_usd)} · "
               f"worst case {format_usd(estimate.worst_case_usd)} · "
               f"cap {format_usd(cap_usd)}")
    out.append("  Nothing has been billed yet.")
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
