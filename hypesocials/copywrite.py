"""Copywriting — one Luna call per (trend × language), split on failure (FR-99–101, 13–16, 146).

Module contract
---------------
Purpose: turn plan entries into `CopySet`s. One grouped call writes every sibling's copy at
once; a failed group splits into per-creative calls; a failed creative still ships on the
trend's own hook. On-image text comes back inside its character budget, trimmed at a word
boundary if the model overshot.

Public API:
    await write_copy(entries, trends=..., call=..., engine=...) -> CopyResult
    CopyResult(copy, degraded, trimmed)
    COPY_ROLE

Invariants:
- **One sibling line per `pair_id`, never per asset (FR-16/22/8).** A `both`-mode pair is ONE
  logical creative rendered two ways: it gets one line in the copy call and the resulting
  `CopySet` is cloned to the sibling's `asset_id`. Listing both variants would ask the model for
  two distinct angles for one creative, which breaks the A/B comparison (identical copy is the
  whole point) and inflates the sibling list.
- **Grouping never widens the blast radius (FR-99, 10 §10).** Group call fails → one call per
  creative, one attempt each, concurrent. Per-creative call fails → deterministic fallback copy
  (trend hook + assembled caption, no model call) and the asset id lands in `degraded` for the
  caller's `copy_degraded` tag.
- **FR-101 is two-layered.** The budget is stated in the prompt (layer one, via
  `{{text_budgets}}`); anything still over budget is trimmed here at the last word boundary —
  never mid-word, never with an ellipsis — and the asset id lands in `trimmed` for the caller's
  `text_trimmed` tag.
- **Override briefs group by (brief × language)** because they consume no trend (FR-144/146).
- Structural mimicry (FR-100) and the brief-driven relaxation (FR-146) live in the template and
  the `{{brief_directives}}` slot; `hook_pattern_used` is carried through verbatim so it stays
  auditable in the log and in meta.yaml.

Do not: call the LLM directly, write per-creative copy calls as the happy path, cut text
mid-word, or invent prompt text outside the template.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hypesocials.config import TextBudgets
from hypesocials.models import Brief, CopySet, PlanEntry, StructuredCall, StyleBrief, TrendItem
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


@dataclass(slots=True)
class CopyResult:
    """Every creative's copy, plus the two degradations the caller must tag (FR-73)."""

    copy: dict[str, CopySet] = field(default_factory=dict)
    degraded: frozenset[str] = frozenset()  # asset ids → DegradationTag.COPY_DEGRADED (FR-99)
    trimmed: frozenset[str] = frozenset()  # asset ids → DegradationTag.TEXT_TRIMMED (FR-101)


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

    Returns:
        `CopyResult`. Every entry has a `CopySet` — a creative with borrowed words beats a
        creative with none — so `degraded` and `trimmed` are how losses stay visible.
    """
    run = _Run(call=call, engine=engine, budgets=text_budgets or TextBudgets(),
               conventions=conventions or {}, onimage_languages=onimage_languages or {},
               niche_descriptor=niche_descriptor, brand_context=brand_context, log=log)
    groups = _build_groups(entries, trends or {}, style_briefs or {}, campaign_briefs or {})
    outcomes = await asyncio.gather(*(_write_group(group, run) for group in groups))
    result = CopyResult()
    degraded: set[str] = set()
    trimmed: set[str] = set()
    for copies, group_degraded, group_trimmed in outcomes:
        result.copy.update(copies)
        degraded |= group_degraded
        trimmed |= group_trimmed
    result.degraded, result.trimmed = frozenset(degraded), frozenset(trimmed)
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
) -> tuple[dict[str, CopySet], set[str], set[str]]:
    """One group: grouped call → per-creative split → deterministic fallback (FR-99, 10 §10)."""
    payloads = await _call_copy(group, group.reps, run)
    if missing := [entry for entry in group.reps if entry.asset_id not in payloads]:
        _warn(run.log, "copy_group_split",
              f"grouped copy call missed {len(missing)} of {len(group.reps)} creatives; "
              "splitting into one call each (FR-99)",
              asset_ids=[entry.asset_id for entry in missing])
        for split in await asyncio.gather(*(
                _call_copy(group, [entry], run) for entry in missing)):
            payloads.update(split)

    copies: dict[str, CopySet] = {}
    degraded: set[str] = set()
    trimmed: set[str] = set()
    for entry in group.reps:
        payload = payloads.get(entry.asset_id)
        if payload is None:
            copyset = _fallback_copy(entry, group.trend)
            degraded.update(group.siblings[entry.asset_id])
            _warn(run.log, "copy_degraded",
                  f"{entry.asset_id}: copy call failed; using the trend's own hook text",
                  asset_id=entry.asset_id)
        else:
            copyset = _to_copyset(payload, entry)
        if _apply_budgets(copyset, entry, run.budgets, run.log):
            trimmed.update(group.siblings[entry.asset_id])
        for asset_id in group.siblings[entry.asset_id]:  # FR-16: variants share the copy
            copies[asset_id] = dataclasses.replace(copyset, asset_id=asset_id)
    return copies, degraded, trimmed


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


def _fallback_copy(entry: PlanEntry, trend: TrendItem | None) -> CopySet:
    """FR-99's last resort: the trend's own hook plus an assembled caption. No model call."""
    name = trend.name if trend else (entry.brief_name or entry.asset_id)
    hook = next((text for text in (*(trend.hook_texts if trend else ()),
                                   *(trend.text_overlay_contents if trend else ()),
                                   *(trend.panel_texts if trend else ())) if text.strip()), name)
    slides = list(trend.panel_texts[:entry.slide_count or 0]) if trend else []
    return CopySet(
        asset_id=entry.asset_id,
        language=entry.language,
        trend_key=entry.trend_key,
        caption=f"{name} — {hook}" if hook != name else name,
        hashtags=_hashtags(name),
        hook_line=hook,
        headline=hook,
        slide_texts=slides or ([hook] if entry.creative_format == "carousel" else []),
        overlay_text=hook if entry.creative_format == "reel" else "",
        through_line=name,
        hook_pattern_used="copy_degraded — the trend's own hook text, reused verbatim",
    )


def _hashtags(name: str, want: int = 3) -> list[str]:
    """The platform's hashtag convention applied to the trend name — string assembly (FR-96)."""
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
