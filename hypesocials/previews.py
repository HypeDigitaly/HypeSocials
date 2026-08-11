"""Look before you spend — the two inspection modes, built as PREFIXES of the paid run (D19).

Module contract
---------------
Purpose: run the first stages of a real run and show what they produced, without ever reaching
the renderer. `--preview-sources` stops after Collect + Select's filtering pass and prints every
trend with the verdict a paid run would reach (FR-139); `--preview-analysis` goes two stages
further and prints the style briefs and the copy, spending LLM cost only (FR-140).

Public API: `await preview_sources(opts)` · `await preview_analysis(opts)` — both return an
FR-202 exit code (`0` shown, `2` config/pre-flight refusal, `3` transport-dead source or a trend
famine, `4` Ctrl+C) and neither ever raises for a preview outcome.

Invariants:
- **A preview is a prefix, never a parallel pipeline** (D19). Every stage below is `runner.py`'s
  own helper, called verbatim: `_open`, `_launch_summary`, `_collect`, `_select`, `_analyze`,
  `_write`, `_cleanup`. Reaching into a sibling module's private stage functions is the
  deliberate design (plan §2 T5.2) — a second dry-run implementation would drift from the paid
  path, which is precisely the thing preview modes exist to rule out.
- **Nothing reaches Kie and nothing spawns yt-dlp** (FR-139/140). The render seam is never
  configured (so `KIE_API_KEY` is neither needed nor used) and `_launch_video_refs()` is never
  called, which is what keeps the D23 chain — and its scratch dir — completely inert.
- **The run folder is log-only and never claims `latest`** (FR-253): `_package()` is not called,
  so `set_latest()`, `record_use()` and the gallery never run, and the empty `refs/` folder
  `create_run_folder()` makes is removed again so the folder holds exactly `run.log` +
  `events.jsonl`.
- **Virlo's metered digest is NOT skipped.** FR-139 requires zero *model* spend and states
  plainly that Virlo API calls may still bill against the operator's Virlo deposit (OQ-19), so
  `_collect` runs exactly as a paid run runs it — what you preview is what will run. The
  `include_digest=False` seam in `sources.fetch()` stays available for a future config gate.

Do not: render, package, write history, repoint `latest`, or re-implement a stage that
`runner.py` already owns.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import suppress

from hypesocials import cli, plan, preflight, runner
from hypesocials.budget import format_usd
from hypesocials.config import Config, ConfigError, load_config
from hypesocials.copywrite import CopyResult
from hypesocials.models import PlanEntry, PlanEntryStatus, StyleBrief, TrendItem
from hypesocials.outputs import read_history
from hypesocials.util import fit, wrapped

# D19: the paid run's own stage calls, borrowed rather than copied (see the module contract).
from hypesocials.runner import (
    _Abort,
    _analyze,
    _cleanup,
    _collect,
    _configure_llm,
    _launch_summary,
    _open,
    _select,
    _write,
)

_REFS_DIR = "refs"  # created by `create_run_folder()`; a log-only folder does not keep it


async def preview_sources(opts: cli.Options, control: runner.Control | None = None) -> int:
    """FR-139: Collect + Select's filters, every trend printed with its verdict, $0 model spend."""
    return await _preview(opts, control, deep=False)


async def preview_analysis(opts: cli.Options, control: runner.Control | None = None) -> int:
    """FR-140: also Analyze + Write, style briefs and copy printed, LLM cost only — no render."""
    return await _preview(opts, control, deep=True)


async def _preview(opts: cli.Options, control: runner.Control | None, *, deep: bool) -> int:
    """One preview, either depth. Mirrors `runner.run()`'s shape minus the gate and the money."""
    action = "preview-analysis" if deep else "preview-sources"
    try:
        config = load_config(opts.config_name)
    except ConfigError as exc:  # one plain line, before any run_id exists (FR-69, 30 §8)
        print(f"config error: {exc}")
        return runner.EXIT_PREFLIGHT
    overrides = cli.apply_overrides(config, opts)
    briefs, brief_errors, brief_warnings = preflight.resolve_briefs(
        opts.briefs, config, assume_yes=opts.yes)
    resolved = plan.build_plan(config, briefs=briefs)
    verdict = preflight.check(config, action=action, entries=resolved.entries,
                              briefs_errors=brief_errors)  # picks the secrets THIS action needs
    if verdict.report:
        print(verdict.report)
    if not verdict.ok:
        return runner.EXIT_PREFLIGHT

    session = _open(config, opts, control or runner.Control())
    with suppress(OSError):  # FR-253: run.log + events.jsonl, nothing else
        (session.run_dir / _REFS_DIR).rmdir()
    try:
        session.say(_launch_summary(session, overrides))
        session.say(f"{action}: no render job, no video download, no upload. This folder\n"
                    "is log-only and never becomes output/latest.")
        for line in brief_warnings:
            session.log.warn("brief_dropped", line)
        trends = await _collect(session)
        if deep:
            await _deep_stages(session, trends, resolved.entries)
        else:
            selection = plan.select(trends, config, read_history(runner.LOGS_DIR, session.log))
            session.say(_verdict_block(selection))
            # FR-154: zero ELIGIBLE trends is a failed answer, not a clean one. Counting verdicts
            # instead would call the 3-returned-all-excluded shape a success — the exact config
            # that then exits 3 on a real run. The decision lives inside this branch because
            # `selection` does not exist on the `deep` path, and reading it there would raise.
            if not selection.eligible and not session.control.stop.is_set():
                session.say(_nothing_eligible(selection, config))
                return runner.EXIT_NOTHING_USABLE
        return runner.EXIT_INTERRUPTED if session.control.stop.is_set() else runner.EXIT_OK
    except _Abort as abort:  # dead source (exit 3), or a trend famine in the deep path
        session.say(str(abort))
        return abort.code
    except Exception as exc:  # noqa: BLE001 — NFR-9: a preview never crashes the process
        session.log.error("preview_failed", f"unhandled error: {type(exc).__name__}: {exc}")
        session.say(f"{action} failed: {type(exc).__name__}: {exc} — see {session.run_dir}/run.log")
        return runner.EXIT_PARTIAL
    finally:
        await _cleanup(session)


async def _deep_stages(session: runner._Session, trends: Sequence[TrendItem],
                       entries: Sequence[PlanEntry]) -> None:
    """FR-140's two extra stages: assign, analyze, write — the same calls the paid run makes.

    Verdicts are logged by `_select()` exactly as in a run; what is *printed* here is FR-140's
    required display — the briefs and the copy — plus FR-8's supply restatement.
    """
    assignment = _select(session, list(trends), list(entries))
    session.say(assignment.summary_line)
    live = [entry for entry in entries if entry.status is PlanEntryStatus.PENDING]
    by_key = {trend.history_key: trend for trend in trends}
    # LLM seam only, built by the runner's own splinter of `_configure_providers()` (D19):
    # the full call would also build the Kie client and demand KIE_API_KEY, a key this action's
    # pre-flight does not require and this path may never use.
    _configure_llm(session)
    style_briefs = await _analyze(session, live, by_key)
    copy_result = await _write(session, live, by_key, style_briefs)
    session.say(_analysis_block(by_key, style_briefs, copy_result))
    session.say(f"LLM spend {format_usd(session.budget.spent_usd)} against the "
                f"{format_usd(session.budget.cap_usd)} cap — nothing was rendered (FR-140).")


def _verdict_block(selection: plan.Selection) -> str:
    """FR-139's display: every returned trend, its verdict, and the material behind it."""
    lines = [f"{len(selection.verdicts)} trend(s) returned — {len(selection.eligible)} eligible, "
             f"{len(selection.excluded)} excluded by history, "
             f"{len(selection.unusable)} unusable",
             "  no model spend; Virlo's own API calls still meter your Virlo deposit"]
    for item in selection.verdicts:
        trend = item.trend
        refs = [url for group in trend.reference_groups for url in group]
        lines.append(f"  {fit(trend.name, 46)}  [{fit(item.label, 26)}]")
        lines.append(f"      strength {trend.strength:.3f} · "
                     f"{'slideshow' if trend.is_slideshow else 'video'} source · "
                     f"views {trend.total_views:,} (median {trend.median_views:,})")
        # FR-286(a): a permalink and a CDN url have no word boundary, so each goes alone on its
        # own line rather than being cut — the operator opens and copies these.
        lines.append(f"      {trend.virlo_url or 'no virlo url'}")
        for field, text in (("hooks ", trend.hook_texts[:3]), ("panels", trend.panel_texts[:5])):
            for first, part in (wrapped(" | ".join(text), 62) if text else ()):
                lines.append(f"      {field if first else '      '}  {part}")
        lines.append(f"      refs    {len(refs)} image(s)"
                     + ("" if refs else " — text_only, this trend arrived with no pictures"))
        lines.extend(f"        {url}" for url in refs[:3])
    if not selection.verdicts:
        lines.append("  the active source(s) returned nothing — no trend to judge")
    return "\n".join(lines)


def _nothing_eligible(selection: plan.Selection, config: Config) -> str:
    """FR-154: say which cause applies and what to change, never 'see the lines above'.

    This is the mode an operator runs *to check their config*, so a clean exit here was the most
    misleading output in the tool — it blessed a config that then failed a paid run.
    """
    if not selection.verdicts:
        ids = [str(i).strip() for i in config.sources.virlo_monitor_ids if str(i).strip()]
        cause = ("no monitor ids are configured" if not ids else
                 f"the {len(ids)} configured monitor id(s) returned nothing")
        return f"  NOT USABLE: {cause} — run run.bat --list-monitors to see the real ids"
    excluded, unusable = len(selection.excluded), len(selection.unusable)
    parts = ([f"{excluded} have no unused reference set left"] if excluded else []) + \
            ([f"{unusable} lack usable material"] if unusable else [])
    return ("  NOT USABLE: " + ", ".join(parts) + " — a real run on this config would exit 3."
            + ("\n  Widen the window with --history-days, or wait for new posts." if excluded
               else "\n  Wait for the monitors to surface richer trends."))


def _analysis_block(trends: Mapping[str, TrendItem], style_briefs: Mapping[str, StyleBrief],
                    copy_result: CopyResult) -> str:
    """FR-140's display: one block per style brief, then one per creative's copy."""
    lines = [f"{len(style_briefs)} style brief(s) and copy for {len(copy_result.copy)} "
             "creative(s) — LLM spend only, no image or video job was submitted (FR-140)"]
    for key, brief in style_briefs.items():
        name = trends[key].name if key in trends else key
        lines.append(f"  style brief — {name}")
        zones = ", ".join(zone.position for zone in brief.layout_zones) or "none"
        lines.append(f"      prompt  {_short(brief.render_prompt, 300)}")
        lines.append(f"      zones   {_short(zones)}")
        lines.append(f"      palette {_short(', '.join(brief.palette) or 'none', 80)} · "
                     f"type {_short(brief.typography, 80)}")
        lines.append(f"      hook    {_short(brief.hook_pattern, 120)}")
    for asset_id, copy in copy_result.copy.items():
        marks = [tag for tag, ids in (("copy_degraded", copy_result.degraded),
                                      ("text_trimmed", copy_result.trimmed)) if asset_id in ids]
        lines.append(f"  copy — {asset_id} [{copy.language}]"
                     + (f"  ({', '.join(marks)})" if marks else ""))
        lines.append(f"      on-image {_short(copy.headline, 60)}"
                     + (f" / {_short(copy.subline, 80)}" if copy.subline else ""))
        if copy.slide_texts:
            lines.append(f"      slides  {_short(' | '.join(copy.slide_texts), 300)}")
        if copy.overlay_text:
            lines.append(f"      overlay {_short(copy.overlay_text, 80)}")
        lines.append(f"      caption {_short(copy.caption, 240)}")
        lines.append(f"      tags    {_short(' '.join(copy.hashtags), 160)} · "
                     f"pattern {_short(copy.hook_pattern_used, 100)}")
    if not copy_result.copy:
        lines.append("  nothing was analyzed or written — see the lines above for the reason")
    return "\n".join(lines)


def _short(text: str, limit: int = 160) -> str:
    """One console line: whitespace collapsed, ASCII ellipsis (a Windows console may be cp1252)."""
    line = " ".join(str(text or "").split())
    return line if len(line) <= limit else line[:max(limit - 3, 1)].rstrip() + "..."


__all__ = ["preview_analysis", "preview_sources"]
