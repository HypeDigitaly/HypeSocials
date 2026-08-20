"""Look before you spend — the two inspection modes, built as PREFIXES of the paid run (D19).

Module contract
---------------
Purpose: run the first stages of a real run and show what they produced, without ever reaching
the renderer. `--preview-sources` stops after Collect + the deterministic half of the competitor
screen and prints the same topics table a paid run prints, at zero model spend (FR-139);
`--preview-analysis` goes on through the real LLM screen, Select, style + branding assignment and
the copy call, and shows the verbatim copy a paid run would render — LLM cost only (FR-140).

Public API: `await preview_sources(opts)` · `await preview_analysis(opts)` — both return an
FR-202 exit code (`0` shown, `2` config/pre-flight refusal, `3` transport-dead source or a topic
famine, `4` Ctrl+C) and neither ever raises for a preview outcome.

Invariants:
- **A preview is a prefix, never a parallel pipeline** (D19). Every stage below is `runner.py`'s
  own helper, called verbatim: `_open`, `_launch_summary`, `_collect`, `_screen_topics`,
  `_select`, `_record_style_forecast`, `_write`, `_cleanup` — and the operator-facing blocks come
  from there too (`_topics_table`, `_post_roster`, `_funnel_block`), which is what makes
  "previews show what a paid run will do" a fact about the code rather than a promise. Reaching
  into a sibling module's private stage functions is the deliberate design (plan §2 T5.2): a
  second dry-run implementation would drift from the paid path, which is precisely the thing
  preview modes exist to rule out.
- **`--preview-sources` makes no model call at all** (FR-139). No LLM client is built, so the
  competitor screen runs on its deterministic blocklist layer alone and the table says so on its
  own line — the LLM verdicts are `--preview-analysis`'s to show and to pay for.
  `--preview-analysis` builds the LLM seam ONLY (FR-140): the render seam is never configured, so
  `KIE_API_KEY` is neither needed nor used, and no image job, video job or Kie upload exists on
  either path.
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

from hypesocials import cli, plan, preflight, runner, styles, topic_filter
from hypesocials.budget import format_usd
from hypesocials.config import Config, ConfigError, load_config
from hypesocials.copywrite import MODE_COMPRESS, CopyResult
from hypesocials.models import PlanEntry, PlanEntryStatus, TrendItem
from hypesocials.outputs import read_history
from hypesocials.prompts_engine import PROMPTS_DIR
from hypesocials.util import fit, wrapped

# D19: the paid run's own stage calls and display blocks, borrowed rather than copied (see the
# module contract). Everything here is `runner`-owned and previews only choose WHEN to call it.
from hypesocials.runner import (
    _Abort,
    _cleanup,
    _collect,
    _configure_llm,
    _funnel_block,
    _launch_summary,
    _load_registry,
    _open,
    _post_roster,
    _record_style_forecast,
    _screen_topics,
    _select,
    _slide_intel,
    _topics_table,
    _write,
)

_REFS_DIR = "refs"  # created by `create_run_folder()`; a log-only folder does not keep it
#: FR-286: 6 spaces of indent + a 9-column label + 61 of text = 76, inside the 78-column ceiling.
_ROW_LABEL, _ROW_WIDTH = 9, 61
#: The one line that tells a `--preview-sources` reader which half of the screen they are seeing.
#: Not a degradation notice: a $0 mode that cannot call a model is working exactly as specified.
_BLOCKLIST_NOTE = (
    "  verdicts  blocklist only ($0) — the LLM screen runs in --preview-analysis\n"
    "            no competitor-promo skip can appear here; a paid run may add one")


async def preview_sources(opts: cli.Options, control: runner.Control | None = None) -> int:
    """FR-139: Collect + the $0 blocklist screen, every topic on one line, zero model spend."""
    return await _preview(opts, control, deep=False)


async def preview_analysis(opts: cli.Options, control: runner.Control | None = None) -> int:
    """FR-140: also the LLM screen, Select, style/brand assignment and the verbatim copy."""
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
        # W5 live-verification fix (2026-08-12): the launch summary reads `session.registry`,
        # which a PAID run fills at the top of `_pipeline` — before ITS summary prints. Previews
        # printed first and loaded later (`--preview-sources` never loaded at all), so a healthy
        # registry was announced as "unavailable — pre-flight will refuse" on every $0 preview.
        # Same tolerant loader, same order as the paid run; `_registry()` reuses the result.
        session.registry = _load_registry(session)
        session.say(_launch_summary(session, overrides))
        session.say(f"{action}: no render job, no video download, no upload. This folder\n"
                    "is log-only and never becomes output/latest.")
        for line in brief_warnings:
            session.log.warn("brief_dropped", line)
        trends = await _collect(session)
        code = (await _deep_stages(session, trends, resolved.entries) if deep
                else await _shallow_stages(session, trends))
        if code != runner.EXIT_OK:
            return code
        return runner.EXIT_INTERRUPTED if session.control.stop.is_set() else runner.EXIT_OK
    except _Abort as abort:  # dead source (exit 3), unusable registry (exit 2), or a topic famine
        session.say(str(abort))
        return abort.code
    except Exception as exc:  # noqa: BLE001 — NFR-9: a preview never crashes the process
        session.log.error("preview_failed", f"unhandled error: {type(exc).__name__}: {exc}")
        session.say(f"{action} failed: {type(exc).__name__}: {exc} — see {session.run_dir}/run.log")
        return runner.EXIT_PARTIAL
    finally:
        await _cleanup(session)


async def _shallow_stages(session: runner._Session, trends: Sequence[TrendItem]) -> int:
    """FR-139's stages: the deterministic screen, then Select — one line per topic, no model call.

    `topic_filter.screen(llm=None)` is the SAME entry point `runner._screen_topics` wraps, called
    with its model layer left out, so layer 1 (the `branding.competitors` blocklist, fail-closed)
    decides exactly what it would decide in a paid run. What this mode cannot show is layer 2's
    judgement — the competitor-promo `skip` and the incidental-mention `strip` a model finds — and
    the note under the table says so rather than letting an empty verdict column read as "clean".

    The funnel prints LAST here (console-UX rule 6: once, at the end). It used to sit above the
    per-topic detail because that detail ran to ~8 lines per trend and would have buried the
    rollup; FR-297a's one-line-per-topic table removed the reason.
    """
    config = session.config
    verdicts = _blocklist_only(await topic_filter.screen(list(trends), config, llm=None))
    session.counters.record_filter(verdicts)
    kept = _kept(trends, verdicts)
    selection = plan.select(kept, config, read_history(runner.LOGS_DIR, session.log))
    session.counters.record_selection(eligible=len(selection.eligible),
                                      excluded=len(selection.excluded),
                                      unusable=len(selection.unusable))
    if table := _topics_table(list(trends), verdicts,
                              window_days=config.sources.max_post_age_days):  # empty only when Collect returned nothing
        session.say(table)
        session.say(_BLOCKLIST_NOTE)
    session.say(_funnel_block(session.counters))
    # FR-154: zero ELIGIBLE topics is a failed answer, not a clean one. Counting verdicts instead
    # would call the "3 returned, all excluded" shape a success — the exact config that then exits
    # 3 on a real run, which is the run this mode exists to predict.
    if not selection.eligible and not session.control.stop.is_set():
        session.say(_nothing_eligible(selection, config, skipped=len(trends) - len(kept)))
        return runner.EXIT_NOTHING_USABLE
    return runner.EXIT_OK


async def _deep_stages(session: runner._Session, trends: Sequence[TrendItem],
                       entries: Sequence[PlanEntry]) -> int:
    """FR-140's stages: the real screen, Select, assignment, styles, branding and the copy call.

    Every call here is the paid run's own, in the paid run's order — the LLM seam first (and ONLY
    the LLM seam, `_configure_llm` rather than `_configure_providers`, so no Kie client is built
    and no `KIE_API_KEY` is read), then screen, select, assign, dress, write. What differs from
    `runner._pipeline` is only what comes after: no reference upload, no render, no packaging.

    Printing order follows the console mockups (§1.10): the topics table with the LLM verdicts,
    the per-topic post roster UNCAPPED (a paid run shows the top 3×3 — showing everything is the
    whole point of a preview), FR-8's supply restatement, one determinism-receipt line per
    creative, the copy itself, and the funnel once at the end.
    """
    config = session.config
    _configure_llm(session)
    verdicts = await _screen_topics(session, trends)
    kept = _kept(trends, verdicts)
    assignment = _select(session, list(kept), list(entries))
    live = [entry for entry in entries if entry.status is PlanEntryStatus.PENDING]
    by_key = {trend.history_key: trend for trend in kept}

    registry = _registry(session)
    styles.assign_styles(live, registry, config.branding.brand,
                         enabled=config.styles.enabled,  # FR-314: preview the SELECTED rotation
                         branding_enabled=config.branding.enabled,  # FR-318: and the SIGNED pool
                         # v2.2.0: the preview seeds off its OWN run id, like any run. Under
                         # `styles.rotation: seeded` that makes the receipt below a forecast of the
                         # rotation's SHAPE — which formats get which kind of look, how many styles
                         # a batch spans — rather than of the paid run's key-by-key assignment,
                         # which cannot be forecast before that run's id exists. `fixed` restores
                         # exact preview↔run agreement, and is what to set when that matters.
                         run_id=session.run_id, rotation=config.styles.rotation)
    styles.assign_branding(live, config.branding.brand_ratio, enabled=config.branding.enabled)
    _record_style_forecast(session, live, registry, dropped=len(assignment.dropped))

    if table := _topics_table(list(trends), verdicts,
                              window_days=config.sources.max_post_age_days):
        session.say(table)
    if roster := _post_roster(list(trends), verdicts, live,
                              topics_limit=None, posts_limit=None):
        session.say(roster)
    session.say(_wrap(assignment.summary_line))
    session.say(_assign_block(live, by_key, registry))
    # `_screen_topics` already turned the ordinal-keyed verdicts round into `history_key -> brands`
    # on the session (that mapping also rides `generate.Env` on a paid run); passing it back in is
    # the pinned `_write` contract, and re-deriving it here would be a second implementation of
    # the same turn, free to disagree with the first.
    # FR-306 on the preview tier: the INTEL pass runs here too — this preview exists to show
    # what a paid run would quote, and post-D46 that includes the vision-merged panel texts and
    # per-deck reading lines. The stage HEADERS stay silent (previews set no stage list, D19);
    # the per-deck result lines print through `say` like every other preview block. Costed LLM
    # spend, exactly like the copy call this mode already makes (FR-140).
    session.stages = []  # explicit: headers off, D19 — the say-lines below still print
    await _slide_intel(session, live, by_key)
    copy_result = await _write(session, live, by_key, session.strip_brands)
    session.say(_copy_block(copy_result, live))
    session.say(_funnel_block(session.counters))
    session.say(f"LLM spend {format_usd(session.budget.spent_usd)} against the "
                f"{format_usd(session.budget.cap_usd)} cap — nothing was rendered (FR-140).")
    return runner.EXIT_OK


# --------------------------------------------------------------------------- filter plumbing


def _blocklist_only(verdicts: dict[int, topic_filter.Verdict]) -> dict[int, topic_filter.Verdict]:
    """Re-label the $0 screen's verdicts: no model layer HERE is the design, not a degradation.

    `topic_filter.screen(llm=None)` stamps every verdict with `filter_degraded: no model call
    available`, and for a paid run that is the right marker — one operator warning, and a run that
    proceeds on the blocklist alone. `--preview-sources` asks for that state deliberately (FR-139
    forbids the spend), so carrying the marker through would raise a degradation warning about a
    mode working exactly as specified, and would flip the funnel's `filter_degraded` flag on every
    single $0 preview. The verdicts and their brand lists are untouched: only the reason line is
    rewritten, back to what layer 1 actually decided.
    """
    for verdict in verdicts.values():
        verdict.reason = (f"blocklist: {', '.join(verdict.brands_to_strip)}"
                          if verdict.brands_to_strip else "")
    return verdicts


def _kept(topics: Sequence[TrendItem],
          verdicts: Mapping[int, topic_filter.Verdict]) -> list[TrendItem]:
    """The topics that survive the screen: `keep` and `strip`, never `skip` (FR-294).

    A `strip` topic stays in the run and loses the named brands inside its copy and its render
    prompt — that is what `brands_to_strip` is FOR, and dropping it would throw away usable
    material over an incidental mention. Only `skip` (the post primarily promotes a competitor)
    leaves before any spend.

    Ordinals are 1-based over the SAME sequence the screen saw, so this must never be handed a
    re-ordered list; every caller passes `trends` in collect order, which is also the order the
    table numbers and the strength rank.
    """
    return [topic for ordinal, topic in enumerate(topics, 1)
            if getattr(verdicts.get(ordinal), "verdict", "keep") != "skip"]


def _registry(session: runner._Session) -> styles.StyleRegistry:
    """Load the meta-style registry through the FR-174 seam, exactly as pre-flight loaded it.

    `--preview-analysis` assigns styles for real — that assignment IS one of the things FR-140
    exists to show — so it needs the real registry rather than a stand-in. `preflight.check` has
    already refused this action when the file is missing or unusable (FR-295, exit 2), so a raise
    here means the file changed between the two reads; it becomes the same one-line refusal rather
    than a stack trace.

    The loaded registry is published on the session because that is the seam the paid run's later
    stages read it from (`_Session.registry`), and previews never runs `_pipeline`, which is where
    a paid run fills it in.
    """
    if session.registry is not None:  # already loaded (and logged) before the launch summary
        return session.registry
    config = session.config
    try:
        registry = styles.load_registry([config.prompts_dir, PROMPTS_DIR])
    except styles.StyleRegistryError as exc:
        raise _Abort(runner.EXIT_PREFLIGHT, str(exc)) from None
    session.registry = registry
    session.log.event("style_registry", f"{len(registry)} style(s) from {registry.origin}",
                      origin=registry.origin, content_hash=registry.content_hash,
                      version=registry.version)
    return registry


# --------------------------------------------------------------------------- display blocks


def _assign_block(live: Sequence[PlanEntry], trends: Mapping[str, TrendItem],
                  registry: styles.StyleRegistry) -> str:
    """One line per creative: ordinal, format, topic, assigned style, signed or plain.

    The determinism receipt of FR-291. Style and branding are both pure functions of `entry.order`
    over the brand-filtered registry, so this block is the thing an operator re-reads after a
    second preview to confirm that the same topic set produced the same dressing — which is how
    the rotation is verified without a debugger.

    The leading number is the asset id's trailing ordinal, the short handle every other §1.10
    surface uses for a creative (the provenance block, the render lines, the gallery).
    """
    head = (f"Assignment — {len(live)} creative(s), {len({e.style_key for e in live})} style(s), "
            f"{sum(1 for e in live if e.branded)} branded")
    lines = [fit(head, 78), f"  {_brand_line(registry)}"]
    for entry in live:
        topic = trends.get(entry.trend_key or "")
        name = topic.name if topic is not None else (entry.brief_name or "no topic")
        lines.append(f"      {_ordinal(entry)} {fit(entry.creative_format, 8):<10}"
                     f"{fit(name, 24):<25}{fit(entry.style_key or '-', 19):<20}"
                     f"{'brand' if entry.branded else 'plain'}")
    return "\n".join(lines)


def _brand_line(registry: styles.StyleRegistry) -> str:
    """Which registry dressed this preview — FR-184's origin+hash attribution, extended to styles.

    The hash is the part that matters across two previews: identical hashes plus an identical
    topic set must produce an identical assignment block, and a changed hash explains the one case
    where they legitimately differ.
    """
    return f"registry v{registry.version} · {len(registry)} style(s) · sha {registry.content_hash}"


def _copy_block(copy_result: CopyResult, live: Sequence[PlanEntry]) -> str:
    """FR-140's headline display: the copy, in the language of the post it was taken from.

    On the verbatim path every string here is a byte-for-byte quote from a `SourcePost` (§1.7
    resolves references to bytes rather than asking a model to retype), so it is WRAPPED and never
    truncated — reading the actual words is the entire reason to spend the copy call before the
    render call. The `refs` row names which candidate each field resolved from (`P1.hook.2`), which
    is what makes the quote checkable against the post roster printed above.

    Under D54 compress mode (FR-331) a bound deck's slides are the copy model's compressions of
    that post's panels rather than quotes of them, so the header says which contract produced the
    words and the per-creative row says `compressed` instead of `quoted`. Nothing else changes:
    this is the mode's cheapest possible review — `--preview-analysis` costs the copy call and
    nothing else, and reading the compressed slides here is what tells the operator whether a paid
    run is worth submitting.
    """
    compressed = sum(1 for prov in copy_result.provenance.values()
                     if prov.copy_mode == MODE_COMPRESS)
    lines = ([f"Copy — {len(copy_result.copy)} creative(s), quoted verbatim in the language",
              "  of the post each string came from; nothing was rendered (FR-140)"]
             if not compressed else
             [f"Copy — {len(copy_result.copy)} creative(s), {compressed} deck(s) compressed",
              "  from the source post's panels to the style's budget, in the post's own",
              "  language; the rest quoted verbatim, nothing rendered (FR-140/FR-331)"])
    for entry in live:
        copy = copy_result.copy.get(entry.asset_id)
        if copy is None:
            continue
        marks = [tag.value for tag in copy_result.tags.get(entry.asset_id, ())]
        # The indent is built OUTSIDE `fit`, which collapses leading whitespace along with every
        # other run of it — an id line that lost its indent reads as a new block, not a heading.
        lines.append("  " + fit(f"{_ordinal(entry)} {entry.asset_id} [{copy.language}]"
                                + (f"  ({', '.join(marks)})" if marks else ""), 76))
        lines += _source_rows(copy_result, entry.asset_id)
        if copy.headline or copy.subline:
            lines += _rows("on-image", " / ".join(t for t in (copy.headline, copy.subline) if t))
        for index, slide in enumerate(copy.slide_texts, 1):
            lines += _rows(f"slide {index}", slide)
        if copy.overlay_text:
            lines += _rows("overlay", copy.overlay_text)
        if copy.motion_beat:
            lines += _rows("motion", copy.motion_beat)
        lines += _rows("caption", copy.caption or "(none)")
        if copy.hashtags:
            lines += _rows("tags", " ".join(copy.hashtags))
    if not copy_result.copy:
        lines.append("  nothing was written — see the lines above for the reason")
    return "\n".join(lines)


def _source_rows(copy_result: CopyResult, asset_id: str) -> list[str]:
    """FR-298's provenance for one creative: which post it quoted, and which strings of it.

    A D54-compressed deck says `compressed` rather than `quoted` and carries no `refs` row — it
    resolved no labels, so there are none to print (FR-302 as amended). The post is named either
    way: the provenance claim is the same, only the transform between that post and our slides is.

    `compressed` is the FIRST label in this module wider than `_ROW_LABEL`'s column, which is why
    `_rows` below now guarantees a separator instead of trusting the padding to supply one.
    """
    provenance = copy_result.provenance.get(asset_id)
    if provenance is None:
        return []
    kind = "compressed" if provenance.copy_mode == MODE_COMPRESS else "quoted"
    rows = _rows(kind, provenance.post_id or "(free text — no post quoted)")
    if provenance.refs:
        rows += _rows("refs", " ".join(f"{slot}={label}"
                                       for slot, label in sorted(provenance.refs.items())))
    return rows


def _rows(label: str, text: str) -> list[str]:
    """One labelled field, wrapped rather than cut, aligned under its own text on continuation.

    `wrapped` and not `fit` because this module's whole job is to show the operator the strings a
    paid run would burn into pixels: a caption cut at 60 characters answers a question nobody
    asked of `--preview-analysis`. FR-286's ceiling is met by wrapping instead — 6 spaces of
    indent plus a 9-column label plus 61 columns of text is 76.

    **The separator is guaranteed rather than assumed (D54 fix).** `:<{_ROW_LABEL}}` pads a SHORT
    label out to the column and supplies the gap as a side effect; it does nothing at all for a
    label that already fills the column, and `compressed` (10) ran straight into its value —
    `compressedp1`. So a label at or over the column width gets one explicit space. Every label
    this module has ever printed is eight characters or fewer (`on-image`, `slide 12`, `caption`,
    `quoted`, `overlay`, `motion`, `refs`, `tags`), so this branch is unreachable for all of them
    and their rows stay byte-identical — which is why the fix lives here rather than in
    `_ROW_LABEL`. Widening the column would have re-padded every row in every preview this tool
    has ever printed to buy one character for one mode. The worst case is still inside FR-286: 6
    indent + 10 label + 1 space + 61 text = 78.
    """
    head = f"{label} " if len(label) >= _ROW_LABEL else label
    return [f"      {head if first else '':<{_ROW_LABEL}}{part}"
            for first, part in wrapped(text, _ROW_WIDTH)]


def _wrap(text: str, width: int = 78) -> str:
    """A plain sentence, re-flowed onto FR-286-sized lines with nothing cut.

    Used for the strings this module borrows whole from elsewhere — FR-8's supply restatement is
    one sentence built by `plan.Assignment`, and at four-digit counts it runs past 78 columns.
    Wrapping at the printer keeps the rule where it belongs (FR-286 is about what the tool prints)
    without editing a data shape three other callers read.
    """
    return "\n".join(part for _, part in wrapped(text, width))


def _ordinal(entry: PlanEntry) -> str:
    """A creative's short handle: the asset id's trailing ordinal (§1.10's provenance block).

    Read off the id rather than recomputed from `order`, so this cannot drift from the folder name
    the operator will actually look in. Falls back to the plan position for an entry whose id is
    still provisional.
    """
    tail = str(entry.asset_id or "").rsplit("_", 1)[-1]
    return tail if tail.isdigit() else f"{entry.order + 1:02d}"


def _nothing_eligible(selection: plan.Selection, config: Config, *, skipped: int = 0) -> str:
    """FR-154: say which cause applies and what to change, never 'see the lines above'.

    This is the mode an operator runs *to check their config*, so a clean exit here was the most
    misleading output in the tool — it blessed a config that then failed a paid run. `skipped`
    counts the topics the competitor screen removed before Select ever saw them (FR-294): they are
    a cause of famine that no history window and no ranking change can fix, so they have to be
    named separately from what Select itself rejected.
    """
    if not selection.verdicts and not skipped:
        ids = [str(i).strip() for i in config.sources.virlo_monitor_ids if str(i).strip()]
        cause = ("no monitor ids are configured" if not ids else
                 f"the {len(ids)} configured monitor id(s) returned nothing")
        return f"  NOT USABLE: {cause} — run run.bat --list-monitors to see the real ids"
    excluded, unusable = len(selection.excluded), len(selection.unusable)
    parts = ([f"{skipped} skipped by the competitor screen"] if skipped else []) + \
            ([f"{excluded} with no unused source post left"] if excluded else []) + \
            ([f"{unusable} lack usable material"] if unusable else [])
    return ("  NOT USABLE: " + ", ".join(parts) + " — a real run on this config would exit 3."
            + ("\n  Widen the window with --history-days, or wait for new posts." if excluded
               else "\n  Wait for the monitors to surface richer topics."))


__all__ = ["preview_analysis", "preview_sources"]
