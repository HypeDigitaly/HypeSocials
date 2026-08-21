"""Look before you spend — the two inspection modes, built as PREFIXES of the paid run (D19).

Module contract
---------------
Purpose: run the first stages of a real run and show what they produced, without ever reaching
the renderer. `--preview-sources` stops after Collect + the deterministic half of the competitor
screen and prints the same topics table a paid run prints, at zero model spend (FR-139);
`--preview-analysis` goes on through the real LLM screen, Select, style + branding assignment and
the copy call, and shows the verbatim copy a paid run would render — LLM cost only (FR-140). Under
`styles.assignment: matched` that includes FR-334's batched style matcher, so the mode shows the
picks a paid run would render in, for the price of the calls and nothing else (v2.4.0/D56).

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

from collections import Counter
from collections.abc import Mapping, Sequence
from contextlib import suppress

from hypesocials import cli, plan, preflight, runner, style_match, styles, topic_filter
from hypesocials.budget import format_usd
from hypesocials.config import Config, ConfigError, load_config
from hypesocials.copywrite import LANGUAGE_TARGET, MODE_AUTO, MODE_COMPRESS, CopyResult
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
    _concentration_line,
    _configure_llm,
    _funnel_block,
    _launch_summary,
    _load_registry,
    _match_receipt,
    _metered,
    _open,
    _post_roster,
    _record_style_forecast,
    _screen_topics,
    _select,
    _slide_intel,
    _style_gap_block,
    _topics_table,
    _write,
)

_REFS_DIR = "refs"  # created by `create_run_folder()`; a log-only folder does not keep it
#: FR-286: 6 spaces of indent + a 9-column label + 61 of text = 76, inside the 78-column ceiling.
_ROW_LABEL, _ROW_WIDTH = 9, 61
#: Reading order for the fit tally on the assignment header — best fit first, not alphabetical.
_FIT_ORDER = {"high": 0, "medium": 1, "low": 2}
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
    # SESSION O (D64): `--preview-analysis` talks to the LLM door, so under codex the proxy must
    # be up before `check()` can judge the ids; `--preview-sources` makes this a no-op.
    await preflight.ensure_backends(config, action=action)
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

    ASSIGN is two stages under `styles.assignment: matched` (FR-334/D56), and both run here: the
    deterministic FR-291 rotation lays down the baseline, then `_match_styles` overlays the batched
    matcher call on top of it. That is what makes `--preview-analysis` the cheapest place to read
    the matcher's picks — the same call a paid run makes, at $LLM and no render spend — and it is
    the reason this module reaches for `runner._metered` rather than calling the LLM seam directly.

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
    await _match_styles(session, live, by_key, registry)
    styles.assign_branding(live, config.branding.brand_ratio, enabled=config.branding.enabled)
    # After the matcher, deliberately: the forecast counts DISTINCT style keys (FR-155 coverage),
    # and counting the rotation baseline would forecast a spread the paid run is not going to
    # render — matched mode repeats a style on purpose wherever two creatives share an archetype.
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


# ----------------------------------------------------------------- matched assignment (FR-334)


async def _match_styles(session: runner._Session, live: Sequence[PlanEntry],
                        topics: Mapping[str, TrendItem],
                        registry: styles.StyleRegistry) -> None:
    """FR-334's matched overlay on the preview tier: one batched call, metered, fail-open.

    The rotation baseline is already on every entry when this runs, so the ONLY thing the call can
    do is replace a content-blind pick with a content-aware one. `style_match.match` is total over
    the entries it is handed and never raises (§5); a `low` fit, a key outside an entry's own pool,
    a missing row and a failed call all come back as `origin: "rotation"` / `"rotation_fallback"`,
    which is why the write-back below overwrites `style_key` on `matched` alone. Every entry keeps
    its four provenance fields either way — the fields are what the ASSIGN receipt, the gallery and
    (on a paid run) meta.yaml read to say WHY a creative wears the style it wears.

    **Override briefs are excluded, exactly as `runner._assign_visuals` excludes them** (M14: an
    `override` brief suppresses the style channel outright), which also keeps this call's entry set
    identical to the one `budget._style_match_lines` quoted at the Confirm gate — a preview that
    matched more creatives than the estimate priced would be a preview of a different run.

    The call rides `runner._metered`, so its spend lands in the same tally the copy call lands in
    and the closing `LLM spend` line of this mode counts it. That is the whole cost story of
    `--preview-analysis` under matched mode: two model calls more than a rotation run makes, no
    render job, no upload (FR-140).
    """
    config = session.config
    if config.styles.assignment != "matched":
        return  # FR-291 rotation is the whole answer; no model is asked anything at ASSIGN
    styled = [entry for entry in live if entry.brief_influence != "override"]
    if not styled:
        return
    matches = await style_match.match(styled, registry, topics, config, _metered(session))
    for entry in styled:
        answer = matches.get(entry.asset_id)
        if answer is None:  # total by contract; a gap here simply leaves the baseline pick alone
            continue
        # `style_key` is the OVERRIDE and not the outcome: `style_match` leaves it empty wherever
        # the baseline stands, so the guard below is what keeps a rejected row from blanking a
        # perfectly good rotation pick. `origin` is checked too, belt-and-braces — the one field
        # that is never empty, and the one a reader is told to check first.
        if answer.origin == style_match.ORIGIN_MATCHED and answer.style_key:
            entry.style_key = answer.style_key
        entry.style_fit = answer.fit
        entry.style_reason = answer.reason
        entry.style_origin = answer.origin
        entry.style_wanted = answer.wanted_archetype
    origins = Counter(entry.style_origin for entry in styled)
    matched = origins.get(style_match.ORIGIN_MATCHED, 0)
    failed = origins.get(style_match.ORIGIN_FALLBACK, 0)
    session.log.event(
        "style_match", f"{matched} of {len(styled)} creative(s) matched",
        matched=matched, baseline=origins.get(style_match.ORIGIN_ROTATION, 0), degraded=failed,
        candidates=len(registry), picks={e.asset_id: e.style_key for e in styled},
        wanted=[e.style_wanted for e in styled if e.style_wanted])
    if failed:
        # The same shape `_screen_topics` uses for `filter_degraded`: one warning naming the cause,
        # and a run that continues on the deterministic layer. A matcher that cannot speak is not a
        # reason to lose a creative — the baseline pick it would have overruled is an authored
        # style either way, which is why this is a warning and never an abort.
        session.log.warn("style_match_degraded",
                         f"{_degraded_cause(styled) or 'the style matcher failed'} — all {failed} "
                         "creative(s) kept their FR-291 rotation pick (fail-open, FR-334)")


def _degraded_cause(live: Sequence[PlanEntry]) -> str:
    """WHY the matcher call failed, read off the marker `style_match` stamps on every fallback row.

    One cause for the whole call by construction (the failure is run-wide), so it is read once and
    printed once — under the header that already said the baseline stands, rather than repeated
    verbatim under every creative in the plan. Empty when the rows carry no marker, which is what a
    future `style_match` that stops stamping one would look like: the caller then falls back to its
    own sentence instead of printing an empty `cause:` line.
    """
    marked = next((entry.style_reason for entry in live
                   if entry.style_origin == style_match.ORIGIN_FALLBACK and entry.style_reason), "")
    return marked.partition(f"{style_match.DEGRADED_MARKER}:")[2].strip() or marked


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

    **FR-334's provenance rides on rows of its own, borrowed from the paid ASSIGN receipt.**
    `runner._match_receipt` and `runner._style_gap_block` are called here rather than re-formatted,
    for the reason the module contract gives at the top: a second implementation of an
    operator-facing block is free to drift from the one a paid run prints, and "the preview shows
    what the run will do" then stops being a fact about the code. It also settles FR-286 once
    instead of twice — that line's own arithmetic (13 indent + 15 label + 1 gutter + 49 reason)
    lands on 78 exactly, and `reason` is the model-authored field it trims.

    Both borrowed blocks are SILENT in rotation mode, so this block prints byte-identically to
    every version before D56 whenever `assignment: rotation` is set. That is not an accident of the
    layout: it is what makes the rotation regression check (one preview under `assignment:
    rotation` against the same topic set) a diff of two files rather than a reading exercise.

    **FR-355's concentration line is the one borrowed block that is NOT mode-silent** (v2.5.2,
    D61), and deliberately so: a rotation over a twelve-key pool that keeps landing on one style is
    the same starved supply as a matcher that does, and the PRD requires the alarm to land here —
    `--preview-analysis` is the $0.30 place to find out that nine carousels want one style, rather
    than the $5 one. It does not break the rotation regression check either, because it is pure
    arithmetic over the keys printed directly above it: the same topic set and the same run id
    produce the same keys and therefore the same line, every time.
    """
    head = (f"Assignment — {len(live)} creative(s), {len({e.style_key for e in live})} style(s), "
            f"{sum(1 for e in live if e.branded)} branded")
    lines = [fit(head, 78), f"  {_brand_line(registry)}"]
    if summary := _match_summary(live):
        lines.append(f"  {summary}")
    for entry in live:
        topic = trends.get(entry.trend_key or "")
        name = topic.name if topic is not None else (entry.brief_name or "no topic")
        lines.append(f"      {_ordinal(entry)} {fit(entry.creative_format, 8):<10}"
                     f"{fit(name, 24):<25}{fit(entry.style_key or '-', 19):<20}"
                     f"{'brand' if entry.branded else 'plain'}")
        # Empty in rotation mode and on the fallback path — `_match_receipt` owns both rules, and
        # the fallback's single cause is printed once by `_match_summary` above instead of once per
        # creative. What is left is exactly the per-entry facts: the matcher looked at THIS
        # creative, and this is what it said.
        if provenance := _match_receipt(entry):
            lines.append(provenance)
    if gap := _style_gap_block(live):
        lines.append(gap)
    if concentration := _concentration_line(live):  # FR-355, borrowed like the two blocks above
        lines.append(concentration)
    return "\n".join(lines)


def _match_summary(live: Sequence[PlanEntry]) -> str:
    """The assignment header's second line under matched mode: how many picks the matcher moved.

    Silent unless the matcher actually SPOKE — which is tested by looking for a matched pick, a
    whole-call fallback or any fit at all, and deliberately NOT by "does an entry carry an origin".
    `runner._assign_visuals` stamps `style_origin: "rotation"` on every live entry before the
    overlay runs (FR-337 gives meta.yaml's field no empty case), so an origin on its own means only
    "ASSIGN happened here" and would print a matcher tally under a rotation run that never made a
    call. That is exactly the line the rotation regression check would trip over.

    A whole-call failure replaces the tally rather than joining it: "0 matched, 4 baseline" and
    "the call failed, everything is on baseline" are the same numbers and different facts, and the
    second one is the one an operator has to act on (§5's `style_match_degraded`). It is also where
    the failure's CAUSE is printed — once for the call that had it, rather than once per creative,
    which is what the per-row marker would have produced.
    """
    origins = Counter(entry.style_origin for entry in live if entry.style_origin)
    spoke = (origins.keys() & {style_match.ORIGIN_MATCHED, style_match.ORIGIN_FALLBACK}
             or any(entry.style_fit for entry in live))
    if not spoke:
        return ""
    if failed := origins.get(style_match.ORIGIN_FALLBACK, 0):
        # Three lines rather than one trimmed one: "nothing was lost" is the half an operator needs
        # and it is the half a 78-column cut would have taken (FR-286 is met by wrapping here, the
        # same trade `_rows` makes for the copy it prints). The cause is the third line because it
        # is the only variable-length part and the only one worth a whole line of its own.
        cause = _degraded_cause(live)
        return (f"{style_match.DEGRADED_MARKER} — the matcher call failed; all {failed} "
                "creative(s)\n  kept their FR-291 rotation pick and nothing was lost (fail-open)"
                + (f"\n  cause: {fit(cause, 69)}" if cause else ""))
    fits = Counter(entry.style_fit for entry in live
                   if entry.style_origin == style_match.ORIGIN_MATCHED and entry.style_fit)
    detail = ", ".join(f"{count} {level}" for level, count in
                       sorted(fits.items(), key=lambda item: _FIT_ORDER.get(item[0], 9)))
    # The paid ASSIGN receipt's own sentence (`runner._assign_visuals`), plus the fit tally this
    # mode can afford to add: a preview is read side by side with the copy it would quote, and
    # "3 matched, all of them high" is a different decision to make than "3 matched, all medium".
    baseline = origins.get(style_match.ORIGIN_ROTATION, 0)
    return fit(f"matched {origins.get(style_match.ORIGIN_MATCHED, 0)} of {sum(origins.values())} "
               "creative(s)" + (f" ({detail})" if detail else "")
               + (f"; {baseline} kept the rotation baseline" if baseline else ""), 76)


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

    D62's `auto` mode (FR-353) is counted in the SAME number and labelled differently in the row:
    an auto deck compressed only the panels that overflowed its style's budget and quoted the rest,
    so it belongs in "how many decks did not ship pure quotes" (the question the header answers)
    while its own row says `auto` rather than `compressed`, because "compressed" over a deck whose
    slides are mostly verbatim would be exactly as wrong as "quoted" over one whose slides are not.

    D63's translation (FR-343) is counted on its OWN axis and answered first, because it is the one
    thing about this block's opening promise — "in the language of the post it was taken from" —
    that can be false. A translated deck's slides are the post's panels in the PLATFORM's language,
    never shortened, so the header says how many decks changed language and the compression count
    (a different question about the same decks) keeps its own clause underneath. A `source`-mode
    run reaches neither branch and prints exactly the two lines it always did.
    """
    compressed = sum(1 for prov in copy_result.provenance.values()
                     if prov.copy_mode in (MODE_COMPRESS, MODE_AUTO))
    translated = sum(1 for prov in copy_result.provenance.values()
                     if prov.copy_language == LANGUAGE_TARGET)
    if translated:
        lines = [f"Copy — {len(copy_result.copy)} creative(s), {translated} deck(s) translated",
                 "  into the platform's language and never shortened (FR-343); the rest",
                 "  quoted verbatim in the post's own language, nothing rendered (FR-140)"]
        if compressed:
            lines.append(f"  {compressed} deck(s) were then fitted to the style's slide budget "
                         "(FR-331/FR-353)")
    elif compressed:
        lines = [f"Copy — {len(copy_result.copy)} creative(s), {compressed} deck(s) compressed",
                 "  from the source post's panels to the style's budget, in the post's own",
                 "  language (under copy mode auto, only the panels that overflowed it);",
                 "  the rest quoted verbatim, nothing rendered (FR-140/FR-331/FR-353)"]
    else:
        lines = [f"Copy — {len(copy_result.copy)} creative(s), quoted verbatim in the language",
                 "  of the post each string came from; nothing was rendered (FR-140)"]
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

    A D62 `auto` deck says `auto` and DOES print a refs row (FR-353): it resolved a real label for
    every panel that fitted its budget and shipped that panel's bytes, so those labels exist and
    are worth reading — the refs row is the list of slides the operator can check against the post
    roster above, and the slides missing from it are the ones that were compressed.

    A D63-TRANSLATED deck says `translated` and wins over both mode words (FR-343): its slides are
    that post's panels in another language, which is a bigger claim about the same bytes than
    either `compressed` or `auto` makes, and a translated auto deck is both at once. It carries no
    refs row for the same reason a compressed deck does not — the walk clears every `ref_label`,
    because a label pointing at bytes we did not ship would be a false receipt — and it adds
    `from <code>` so the row says which language the panels were read out of.

    `compressed` is the FIRST label in this module wider than `_ROW_LABEL`'s column, which is why
    `_rows` below now guarantees a separator instead of trusting the padding to supply one. `auto`
    (4) is well inside it and pads like every other short label; `translated` (10) is the same
    width as `compressed` and rides the same guarantee.
    """
    provenance = copy_result.provenance.get(asset_id)
    if provenance is None:
        return []
    kind = {MODE_COMPRESS: "compressed", MODE_AUTO: "auto"}.get(provenance.copy_mode, "quoted")
    detail = provenance.post_id or "(free text — no post quoted)"
    if provenance.copy_language == LANGUAGE_TARGET:
        kind = "translated"
        if provenance.source_language:
            detail = f"{detail}  from {provenance.source_language}"
    rows = _rows(kind, detail)
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
