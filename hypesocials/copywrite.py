"""Copywriting — one Luna call per (trend × language), split on failure (FR-99–101, 13–16, 146).

Module contract
---------------
Purpose: turn plan entries into `CopySet`s. One grouped call writes every sibling's copy at
once; a failed group splits into per-creative calls; a creative whose own call also failed ships
with a caption in OUR words and NO on-image text at all. On-image text comes back inside its
character budget, trimmed at a word boundary if the model overshot.

Public API:
    await write_copy(entries, trends=..., call=..., engine=...) -> CopyResult
    CopyResult(copy, tags) — `.degraded` / `.trimmed` are views over `tags`
    COPY_ROLE

Invariants:
- **The source's own words never become our on-image text (A20, 2026-08-11).** No path from
  `TrendItem.hook_texts`, `.text_overlay_contents` or `.panel_texts` reaches `headline`,
  `subline`, `overlay_text`, `slide_texts` or `caption`. Those three fields are exemplar
  material: they enter the PROMPT (`{{source_hooks}}`, `{{trend_texts}}`) as a pattern to
  abstract, and the model is what turns a pattern into a sentence. When the model produced
  nothing, the answer is a creative with no words — never the competitor's headline.
- **One sibling line per `pair_id`, never per asset (FR-16/22/8).** A `both`-mode pair is ONE
  logical creative rendered two ways: it gets one line in the copy call and the resulting
  `CopySet` is cloned to the sibling's `asset_id`. Listing both variants would ask the model for
  two distinct angles for one creative, which breaks the A/B comparison (identical copy is the
  whole point) and inflates the sibling list.
- **Grouping never widens the blast radius (FR-99, 10 §10).** Group call fails → one call per
  creative, one attempt each, concurrent. Per-creative call fails → the deterministic no-text
  tier (assembled caption, empty on-image fields, no model call), tagged `copy_degraded` AND
  `no_onimage_text` so the two facts stay separable in the log, meta.yaml and the gallery.
- **A weak audit trail never fails a creative (A21).** `hook_pattern_used` is validated against
  the bar `prompts/copywriter_system.md` states to the model; a generic answer costs that
  creative ONE re-ask, and a second generic answer is logged and tagged
  `hook_pattern_generic` while the copy itself ships unchanged.
- **FR-101 is two-layered.** The budget is stated in the prompt (layer one, via
  `{{text_budgets}}`); anything still over budget is trimmed here at the last word boundary —
  never mid-word, never with an ellipsis — and the asset id lands in `trimmed` for the caller's
  `text_trimmed` tag.
- **Override briefs group by (brief × language)** because they consume no trend (FR-144/146).
- Structural mimicry (FR-100) and the brief-driven relaxation (FR-146) live in the template and
  the `{{brief_directives}}` slot; `hook_pattern_used` is carried through verbatim once it has
  cleared A21's bar, so what is logged and written to meta.yaml is the model's own sentence.

Do not: call the LLM directly, write per-creative copy calls as the happy path, cut text
mid-word, invent prompt text outside the template, or copy ANY string that came from a source
post into a `CopySet` field — the Inspiration exemplars A16 threads to this call
(`{{inspiration_exemplars}}`) are under the same rule as the trend's own hooks.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hypesocials.config import TextBudgets
from hypesocials.models import (
    Brief,
    CopySet,
    DegradationTag,
    PlanEntry,
    StructuredCall,
    StyleBrief,
    TrendItem,
)
from hypesocials.prompts_engine import (
    PromptEngine,
    build_context,
    json_schema_for,
    trim_words,
)
from hypesocials.util import slugify

logger = logging.getLogger(__name__)

#: `models.copy` / `max_tokens.copy` / `reasoning_effort` — the role name config already uses.
COPY_ROLE = "copy"
_CARRIER_TURN = "Write the copy JSON for the siblings listed above now."

# ---------------------------------------------------------------------------------------------
# A21 — the `hook_pattern_used` bar.
#
# ⚠️ THESE FOUR CONSTANTS AND `prompts/copywriter_system.md` ARE ONE CONTRACT, IN BOTH
# DIRECTIONS. The template promises the model, in these words: "At least 30 characters, and at
# least four distinct content words" and "These values are rejected outright: 'curiosity hook',
# 'engaging hook', 'attention grabber', 'hook' on its own, 'pattern interrupt' on its own."
# Tighten the code and the prompt advertises a bar the code refuses; loosen it and the prompt
# lies about what is checked. Either way the model is being told something untrue about how its
# answer is judged, which is the one thing a prompt must never do. Edit the two together.
#
# Calibrated against a real passing value measured on a live run — "Curiosity-and-reveal claim,
# second person, direct address with a withheld subject" (81 characters, 8 distinct content
# words) — so the bar is real but has better than 2x headroom on a good answer.
# ---------------------------------------------------------------------------------------------

_HOOK_PATTERN_MIN_CHARS = 30
_HOOK_PATTERN_MIN_CONTENT_WORDS = 4
_GENERIC_HOOK_PATTERNS: frozenset[str] = frozenset({
    "curiosity hook", "engaging hook", "attention grabber", "hook", "pattern interrupt",
})
#: Every word appearing in a blocklisted phrase — derived from the blocklist rather than listed
#: again, so the two can never disagree about what counts as "naming the genre".
_GENERIC_VOCABULARY: frozenset[str] = frozenset(
    word for phrase in _GENERIC_HOOK_PATTERNS for word in phrase.split())
#: Words that describe nothing about a hook's shape, so they do not count toward the four.
#: Deliberately short and English-only: a Czech or German pattern line contains none of them,
#: which makes the bar EASIER to clear in those languages. The failure mode worth avoiding is a
#: validator that rejects a good non-English answer, not one that accepts a wordy English one.
_HOOK_PATTERN_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "as", "at", "be", "but", "by", "for", "from", "in", "into", "is", "it",
    "its", "of", "on", "or", "that", "the", "then", "this", "to", "who", "with",
})
_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)  # letters only: "second-person" -> second, person


@dataclass(slots=True)
class CopyResult:
    """Every creative's copy, plus the degradations the caller must tag (FR-73).

    `tags` is the ONE carrier — `asset_id -> the tags this creative earned in the copy stage` —
    so a new copy-side degradation needs no new field here, no new field on `generate.Env` and no
    new branch in the meta writer. `degraded` and `trimmed` are read-only VIEWS over it rather
    than parallel state: FR-99 and FR-101 are the questions callers actually ask, and answering
    them from the same dictionary is what stops the two spellings drifting apart.
    """

    copy: dict[str, CopySet] = field(default_factory=dict)
    tags: dict[str, tuple[DegradationTag, ...]] = field(default_factory=dict)

    @property
    def degraded(self) -> frozenset[str]:
        """FR-99 — asset ids whose copy fell back to the no-text tier (`copy_degraded`)."""
        return self._tagged(DegradationTag.COPY_DEGRADED)

    @property
    def trimmed(self) -> frozenset[str]:
        """FR-101 — asset ids whose on-image text was cut to budget (`text_trimmed`)."""
        return self._tagged(DegradationTag.TEXT_TRIMMED)

    def _tagged(self, tag: DegradationTag) -> frozenset[str]:
        return frozenset(asset_id for asset_id, tags in self.tags.items() if tag in tags)


async def write_copy(
    entries: Sequence[PlanEntry],
    *,
    trends: Mapping[str, TrendItem] | None = None,
    style_briefs: Mapping[str, StyleBrief] | None = None,
    campaign_briefs: Mapping[str, Brief] | None = None,
    call: StructuredCall,
    engine: PromptEngine,
    text_budgets: TextBudgets | None = None,
    conventions: Mapping[str, Mapping[str, str]] | None = None,
    onimage_languages: Mapping[str, str] | None = None,
    niche_descriptor: str = "",
    brand_context: str = "",
    copy_exemplars: Sequence[str] = (),
    log: Any = None,
) -> CopyResult:
    """Copy for every entry, one grouped call per (trend × language), all groups concurrent.

    Args:
        entries: the plan entries needing copy (trimmed/skipped ones excluded by the caller).
        trends: `trend_key -> TrendItem`, the material FR-14 feeds the prompt.
        style_briefs: `trend_key -> StyleBrief` from `analyze`; absent = direct mode or FR-12.
        campaign_briefs: `brief_name -> Brief` for FR-146's directive-driven copy.
        call: `llm.structured_call` (`models.StructuredCall`).
        engine: the run's `PromptEngine`; supplies `copywriter_system.md`.
        text_budgets: FR-101 ceilings; defaults to the shipped values.
        conventions: `platform -> {tone/length/hashtags}` from config (FR-15, guidance only).
        onimage_languages: `asset_id -> language` when on-image text differs from the caption.
        brand_context: Notion brand text; reaches the copywriter only (FR-109).
        copy_exemplars: `InspirationPool.exemplar_texts` (A16) — proven, human-written posts from
            the operator's own Inspiration folders, rendered into `{{inspiration_exemplars}}`.
            FORM material for this call and this call alone; no render role can resolve the slot.

    Returns:
        `CopyResult`. Every entry has a `CopySet`, but a creative whose call failed gets one with
        NO on-image words rather than the source's own (A20) — a text-free image on a proven
        layout is a usable creative, someone else's headline is not. `tags` (and its `degraded` /
        `trimmed` views) is how every loss stays visible on the asset and in the gallery.
    """
    run = _Run(call=call, engine=engine, budgets=text_budgets or TextBudgets(),
               conventions=conventions or {}, onimage_languages=onimage_languages or {},
               niche_descriptor=niche_descriptor, brand_context=brand_context,
               copy_exemplars=tuple(copy_exemplars), log=log)
    groups = _build_groups(entries, trends or {}, style_briefs or {}, campaign_briefs or {})
    outcomes = await asyncio.gather(*(_write_group(group, run) for group in groups))
    result = CopyResult()
    for copies, tags in outcomes:
        result.copy.update(copies)
        result.tags.update(tags)
    return result


# --------------------------------------------------------------------------------------------
# Grouping — (trend × language), one line per pair_id
# --------------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Run:
    """Everything constant across this run's copy calls — threaded once instead of per call."""

    call: StructuredCall
    engine: PromptEngine
    budgets: TextBudgets
    conventions: Mapping[str, Mapping[str, str]]
    onimage_languages: Mapping[str, str]
    niche_descriptor: str
    brand_context: str
    copy_exemplars: tuple[str, ...]  # A16 — pooled Inspiration `.txt` captions, copy call only
    log: Any


@dataclass(slots=True)
class _Group:
    """One copy call's scope: the siblings of one trend (or one override brief) in one language."""

    trend: TrendItem | None
    style_brief: StyleBrief | None
    campaign_brief: Brief | None
    reps: list[PlanEntry] = field(default_factory=list)  # ONE per pair_id (FR-16/22)
    siblings: dict[str, list[str]] = field(default_factory=dict)  # rep asset id -> asset ids


def _build_groups(
    entries: Sequence[PlanEntry],
    trends: Mapping[str, TrendItem],
    style_briefs: Mapping[str, StyleBrief],
    campaign_briefs: Mapping[str, Brief],
) -> list[_Group]:
    """FR-99 grouping. Override briefs have no trend, so they group by brief × language."""
    groups: dict[tuple[str, str], _Group] = {}
    pair_rep: dict[tuple[str, str, str], str] = {}
    for entry in sorted(entries, key=lambda e: e.order):
        subject = entry.trend_key or (
            f"brief/{entry.brief_name}" if entry.brief_name else entry.asset_id)
        key = (subject, entry.language)
        group = groups.get(key)
        if group is None:
            group = _Group(
                trend=trends.get(entry.trend_key or ""),
                style_brief=style_briefs.get(entry.trend_key or ""),
                campaign_brief=campaign_briefs.get(entry.brief_name or ""))
            groups[key] = group
        pair_key = (*key, entry.pair_id or entry.asset_id)
        rep = pair_rep.get(pair_key)
        if rep is None:  # first variant of this creative — it speaks for the pair
            pair_rep[pair_key] = entry.asset_id
            group.reps.append(entry)
            group.siblings[entry.asset_id] = [entry.asset_id]
        else:
            group.siblings[rep].append(entry.asset_id)
    return list(groups.values())


# --------------------------------------------------------------------------------------------
# Calling
# --------------------------------------------------------------------------------------------


async def _write_group(
    group: _Group, run: _Run
) -> tuple[dict[str, CopySet], dict[str, tuple[DegradationTag, ...]]]:
    """One group: grouped call → per-creative split → A21 re-ask → no-text tier (FR-99, 10 §10)."""
    payloads = await _call_copy(group, group.reps, run)
    if missing := [entry for entry in group.reps if entry.asset_id not in payloads]:
        _warn(run.log, "copy_group_split",
              f"grouped copy call missed {len(missing)} of {len(group.reps)} creatives; "
              "splitting into one call each (FR-99)",
              asset_ids=[entry.asset_id for entry in missing])
        for split in await asyncio.gather(*(
                _call_copy(group, [entry], run) for entry in missing)):
            payloads.update(split)
    generic = await _reask_generic_patterns(group, payloads, run)

    copies: dict[str, CopySet] = {}
    tags: dict[str, list[DegradationTag]] = {}

    def tag(entry: PlanEntry, *marks: DegradationTag) -> None:
        for asset_id in group.siblings[entry.asset_id]:  # FR-16: a pair degrades as one creative
            earned = tags.setdefault(asset_id, [])
            earned.extend(mark for mark in marks if mark not in earned)

    for entry in group.reps:
        payload = payloads.get(entry.asset_id)
        if payload is None:
            copyset = _fallback_copy(entry, group.trend, run.niche_descriptor)
            tag(entry, DegradationTag.COPY_DEGRADED, DegradationTag.NO_ONIMAGE_TEXT)
            _warn(run.log, "copy_degraded",
                  f"{entry.asset_id}: copy call failed; shipping a caption in our own words and "
                  "NO on-image text — the source's hook is never reused verbatim (A20)",
                  asset_id=entry.asset_id, reason="no_onimage_text")
        else:
            copyset = _to_copyset(payload, entry)
            if entry.asset_id in generic:
                tag(entry, DegradationTag.HOOK_PATTERN_GENERIC)
        if _apply_budgets(copyset, entry, run.budgets, run.log):
            tag(entry, DegradationTag.TEXT_TRIMMED)
        for asset_id in group.siblings[entry.asset_id]:  # FR-16: variants share the copy
            copies[asset_id] = dataclasses.replace(copyset, asset_id=asset_id)
    return copies, {asset_id: tuple(marks) for asset_id, marks in tags.items() if marks}


async def _reask_generic_patterns(
    group: _Group, payloads: dict[str, dict[str, Any]], run: _Run
) -> set[str]:
    """A21 — one re-ask per creative whose `hook_pattern_used` came back generic. Mutates
    `payloads` in place with any answer that cleared the bar; returns the ids that never did.

    `prompts/copywriter_system.md` tells the model this value "is checked before your answer is
    accepted" and names the bar. Until A21 it was stored, logged, written to meta.yaml, shown in
    the gallery — and never read by anything, so the audit trail FR-100 promises could be the
    word "hook" and nobody would know.

    Three deliberate limits:
    - **One re-ask, never a loop.** A model that answered "curiosity hook" twice will answer it a
      third time, and a copy call is metered.
    - **A weak pattern never fails a creative.** The copy itself may be excellent; the audit note
      about it is what is thin. Failing the creative would trade a shipped post for a bookkeeping
      complaint, so a second failure is logged and tagged, and the copy ships unchanged.
    - **The re-ask keeps the better answer.** A retry that comes back generic too (or does not
      come back at all) leaves the original in place, so this can only improve an answer.
    """
    suspect = [entry for entry in group.reps
               if _hook_pattern_generic(payloads.get(entry.asset_id))]
    if not suspect:
        return set()
    _warn(run.log, "hook_pattern_reask",
          f"{len(suspect)} of {len(group.reps)} creative(s) answered with a generic "
          "hook_pattern_used; asking each once more (A21 — the copywriter template calls a "
          "generic value a failed answer)",
          asset_ids=[entry.asset_id for entry in suspect])
    retries = await asyncio.gather(*(_call_copy(group, [entry], run) for entry in suspect))
    for entry, retry in zip(suspect, retries):
        answer = retry.get(entry.asset_id)
        if answer is not None and not _hook_pattern_generic(answer):
            payloads[entry.asset_id] = answer
    still = {entry.asset_id for entry in suspect
             if _hook_pattern_generic(payloads.get(entry.asset_id))}
    for asset_id in sorted(still):
        _warn(run.log, "hook_pattern_generic",
              f"{asset_id}: hook_pattern_used is still generic after one re-ask "
              f"({str(payloads[asset_id].get('hook_pattern_used') or '')!r}) — the copy ships "
              "unchanged and the asset is tagged; a thin audit note never fails a creative (A21)",
              asset_id=asset_id, hook_pattern_used=payloads[asset_id].get("hook_pattern_used"))
    return still


async def _call_copy(
    group: _Group, reps: Sequence[PlanEntry], run: _Run
) -> dict[str, dict[str, Any]]:
    """One Luna call covering `reps`. Returns `{asset_id: payload}` for whatever came back."""
    context = build_context(
        trend=group.trend,
        style_brief=group.style_brief,
        campaign_brief=group.campaign_brief,
        creative_format=reps[0].creative_format if len(reps) == 1 else "",
        niche_descriptor=run.niche_descriptor,
        brand_context=run.brand_context,
        copy_exemplars=run.copy_exemplars,  # A16: `{{inspiration_exemplars}}`, this role only
        platform_conventions=_relevant(run.conventions, reps),
        text_budgets=run.budgets,
        sibling_list=_sibling_list(reps, run.onimage_languages),
    )
    try:
        system = run.engine.render("copywriter_system.md", context)
    except (ValueError, LookupError) as exc:  # unresolved placeholder / missing template
        _warn(run.log, "copy_prompt_failed", str(exc))
        return {}
    result = await run.call(
        COPY_ROLE,
        [{"role": "system", "content": system}, {"role": "user", "content": _CARRIER_TURN}],
        _copy_schema(),
        None,
    )
    if result.degraded or not isinstance(result.parsed, Mapping):
        return {}
    wanted = {entry.asset_id for entry in reps}
    payloads = {}
    for item in result.parsed.get("creatives") or []:
        if isinstance(item, Mapping) and str(item.get("asset_id")) in wanted:
            payloads[str(item["asset_id"])] = dict(item)
    return payloads


def _sibling_list(reps: Sequence[PlanEntry], onimage_languages: Mapping[str, str]) -> str:
    """One line per pair_id (FR-16/22) — asset id, platform, format and both languages."""
    lines = []
    for entry in reps:
        onimage = onimage_languages.get(entry.asset_id, entry.language)
        line = (f"- {entry.asset_id} · {entry.platform} · {entry.creative_format} · "
                f"caption {entry.language} · on-image {onimage}")
        if entry.creative_format == "carousel" and entry.slide_count:
            line += f" · {entry.slide_count} slides"
        lines.append(line)
    return "\n".join(lines)


def _relevant(
    conventions: Mapping[str, Mapping[str, str]] | None, reps: Sequence[PlanEntry]
) -> dict[str, Mapping[str, str]]:
    """Only the platforms in this call — a LinkedIn rule in a TikTok-only call is noise."""
    if not conventions:
        return {}
    platforms = {entry.platform for entry in reps}
    return {name: entry for name, entry in conventions.items() if name in platforms}


def _copy_schema() -> dict[str, Any]:
    """Generated from `CopySet`'s own fields, so the template and the schema cannot drift."""
    creative = json_schema_for(CopySet, exclude={"language", "trend_key"})
    return {
        "name": "social_copy",
        "schema": {"type": "object", "properties": {"creatives": {"type": "array",
                                                                  "items": creative}},
                   "required": ["creatives"], "additionalProperties": False},
    }


# --------------------------------------------------------------------------------------------
# Results — mapping, fallback, FR-101 enforcement
# --------------------------------------------------------------------------------------------


def _to_copyset(payload: Mapping[str, Any], entry: PlanEntry) -> CopySet:
    return CopySet(
        asset_id=entry.asset_id,
        language=entry.language,
        trend_key=entry.trend_key,
        caption=str(payload.get("caption") or ""),
        hashtags=_strings(payload.get("hashtags")),
        hook_line=str(payload.get("hook_line") or ""),
        headline=str(payload.get("headline") or ""),
        subline=str(payload.get("subline") or ""),
        slide_texts=_strings(payload.get("slide_texts")),
        narrative_arc=str(payload.get("narrative_arc") or ""),
        overlay_text=str(payload.get("overlay_text") or ""),
        through_line=str(payload.get("through_line") or ""),
        hook_pattern_used=str(payload.get("hook_pattern_used") or ""),
    )


def _fallback_copy(entry: PlanEntry, trend: TrendItem | None,
                   niche_descriptor: str = "") -> CopySet:
    """FR-99's last resort, A20 shape: a caption in OUR words and NO on-image text. No model call.

    **What this used to do, and why it stopped (operator mandate, 2026-08-11).** Until A20 this
    function set `headline` to the competitor's exact `hook_text`, `slide_texts` to the source
    deck's panel copy slide for slide, and `overlay_text` to the same hook for a reel. Those
    strings flow into `prompts_engine._onimage_text`, which emits them as
    `headline (render verbatim): "…"` plus a letter-by-letter spelling aid, inside the block every
    render template calls *the ONLY source of renderable words*. A carousel reproduced the source
    deck panel by panel; a reel burnt the source hook into the seed frame and then locked it as a
    fixed graphic layer for the whole clip. The docstring here justified it as *"a creative with
    borrowed words beats a creative with none"*. **That reasoning is overturned.** It is the one
    place in this pipeline that reproduced a competitor's literal words into a shipped asset, and
    no amount of prompt-level anti-plagiarism discipline elsewhere survives an engine that does
    it deterministically on a failure path.

    So every on-image field is empty here. The render side already copes: `_onimage_text` returns
    `""` when there is no copy and every image role instructs the model to ignore an empty
    labelled line, so what ships is a text-free creative on a proven layout — usable, and honest
    about being wordless via `no_onimage_text`.

    The caption is assembled from what is OURS: the trend's own name (the monitor's theme label,
    not any post's copy) and the niche descriptor from config. `hook_line` and `through_line`
    stay clear of the source too — `through_line` reaches `reel_director.md` as a description of
    what the clip is about, so it carries the theme name and nothing scraped.
    """
    name = trend.name if trend else (entry.brief_name or entry.asset_id)
    return CopySet(
        asset_id=entry.asset_id,
        language=entry.language,
        trend_key=entry.trend_key,
        caption=_fallback_caption(name, niche_descriptor),
        hashtags=_hashtags(name),
        hook_line="",
        headline="",
        subline="",
        slide_texts=[],
        overlay_text="",
        through_line=name,
        hook_pattern_used="copy_degraded — no pattern was written; this creative ships with no "
                          "on-image text rather than the source's own words (A20)",
    )


def _fallback_caption(name: str, niche_descriptor: str) -> str:
    """The no-text tier's caption: the trend's theme name plus our own standing niche line.

    Both halves are ours — `NicheConfig.as_text()` is operator-authored config and the trend name
    is the monitor's theme label — so nothing scraped can reach `caption.txt`, which FR-230 ships
    verbatim to the publisher. The niche line runs to a few hundred characters in real configs,
    so it is cut at a word boundary: a caption is a caption, not a config dump.
    """
    standing = trim_words(" ".join((niche_descriptor or "").split()), 180)[0]
    return f"{name} — {standing}" if standing else name


def _hook_pattern_generic(payload: Mapping[str, Any] | None) -> bool:
    """A21 — True when `hook_pattern_used` is the kind of answer the template calls a failure.

    Three cheap, explainable rules rather than a judgement call, in the order they were cheapest
    to state to the model (see `_GENERIC_HOOK_PATTERNS` for the contract with the template):

    1. under `_HOOK_PATTERN_MIN_CHARS` — nothing that short describes a shape;
    2. the whole value, normalized, is one of the five phrases the template rejects by name;
    3. every content word it does carry comes from that same generic vocabulary, which catches
       "attention grabber pattern interrupt hook" — long enough for rule 1, still a genre label.

    `None` means the copy call produced no answer at all for this creative; that is the FR-99
    fallback's business, not this check's, so it is not "generic".
    """
    if payload is None:
        return False
    value = str(payload.get("hook_pattern_used") or "")
    if len(" ".join(value.split())) < _HOOK_PATTERN_MIN_CHARS:
        return True
    words = [match.group(0).casefold() for match in _WORDS.finditer(value)]
    if " ".join(words) in _GENERIC_HOOK_PATTERNS:
        return True
    content = {word for word in words if word not in _HOOK_PATTERN_STOPWORDS}
    if content and content <= _GENERIC_VOCABULARY:
        return True
    return len(content) < _HOOK_PATTERN_MIN_CONTENT_WORDS


def _hashtags(name: str, want: int = 3) -> list[str]:
    """The platform's hashtag convention applied to the trend name — string assembly (FR-96).

    Deliberately still invented from the trend-name slug, and deliberately still only reachable
    from `_fallback_copy`. The winning posts' REAL hashtags now travel to the copy call as
    reference material (`TrendItem.hashtags`, rendered inside `{{trend_texts}}`), where the model
    chooses among them the way it chooses everything else. Emitting them verbatim from here would
    turn reference material into a mandate and hand the model's one editorial job to a slice —
    and this function runs only when there was no model answer at all.
    """
    words = [word for word in slugify(name, 0).split("-") if len(word) > 2]
    return [f"#{word}" for word in words[:want]]


def _apply_budgets(copyset: CopySet, entry: PlanEntry, budgets: TextBudgets, log: Any) -> bool:
    """FR-101 layer two — word-boundary trim of every on-image string. True if anything was cut.

    FR-105's −40% vision-check retry re-runs the render, not the copy call: it rebuilds the
    prompt through `build_context(budget_scale=...)` and re-trims with `trim_words`, so no
    reduced-budget branch belongs here.
    """
    headline_limit = budgets.image_headline
    subline_limit = budgets.image_subline
    seed_limit = budgets.reel_seed_headline
    trimmed = False
    for name, limit in (("headline", headline_limit), ("subline", subline_limit),
                        ("overlay_text", seed_limit)):
        before = getattr(copyset, name)
        after, cut = trim_words(before, limit)
        if cut:
            setattr(copyset, name, after)
            trimmed = True
            _warn(log, "text_trimmed",
                  f"{entry.asset_id}: {name} exceeded {limit} characters and was cut at the last "
                  "word boundary", asset_id=entry.asset_id, field=name, before=before, after=after)
    slides = []
    for index, text in enumerate(copyset.slide_texts, start=1):
        after, cut = trim_words(text, headline_limit)
        if cut:
            trimmed = True
            _warn(log, "text_trimmed",
                  f"{entry.asset_id}: slide {index} exceeded {headline_limit} characters",
                  asset_id=entry.asset_id, field=f"slide_texts[{index}]", before=text, after=after)
        slides.append(after)
    copyset.slide_texts = slides
    return trimmed


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Sequence):
        return [str(item) for item in value if str(item).strip()]
    return []


def _warn(log: Any, event_type: str, message: str, **data: Any) -> None:
    logger.warning("%s: %s", event_type, message)
    if log is not None:
        log.warn(event_type, message, **data)


__all__ = ["COPY_ROLE", "CopyResult", "write_copy"]
