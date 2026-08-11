"""Select + Expand — the deterministic middle of a run (FR-1–8, FR-90, FR-143–145).

Module contract
---------------
Purpose: turn *config + requested briefs* into an ordered plan of creatives, and *collected
trends + history* into a ranked shortlist with a verdict per trend, then bind the two together.
Public API: `select()` · `build_plan()` · `assign()` and their result objects
(`Selection`/`TrendVerdict`, `Plan`/`BriefRequest`, `Assignment`/`AssignmentDecision`).

Invariants:
- **Pure and instant** (NFR-2): no file, network or clock I/O and no logging — every decision
  leaves as data so `runner.py` logs it (NFR-5) and `previews.py` prints it at zero model spend
  (FR-139). History arrives as the dict `outputs.read_history()` returns.
- **Every input trend comes back with a verdict** — `eligible` / `excluded` (with the date last
  used) / `unusable` (with the reason). Nothing is filtered away silently, because 10 §10's abort
  message must distinguish "excluded by history" from "rejected as unusable".
- **Brief entries are emitted FIRST and an `atomic_group` is never split** — the two properties
  that make FR-106's single "trim from the END, in reverse plan order" rule sufficient.
- **Nothing leaves the plan** (FR-4): a creative with no trend left keeps a terminal status and a
  reason instead of vanishing from the accounting.

Do not: price anything (`budget.py` owns cost and trimming), read files, or assume reels are
enabled — an unpriced reel is not planned at all (FR-131).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import count
from typing import Any, Literal

from hypesocials.config import Config
from hypesocials.models import (
    Brief, CreativeFormat, PlanEntry, PlanEntryStatus, TrendItem, Variant)
from hypesocials.outputs import days_since_use
from hypesocials.util import slugify

#: Canonical format order — the order counts are expanded in, and the order of a brief's slots.
FORMAT_ORDER: tuple[CreativeFormat, ...] = ("image", "carousel", "reel")
#: Slug standing in for the trend inside an `asset_id` until `assign()` binds one (FR-71).
PENDING_TREND_SLUG = "unassigned"

_FORMAT_ABBR: dict[str, str] = {"image": "img", "carousel": "car", "reel": "reel"}
_PLATFORM_ABBR: dict[str, str] = {"linkedin": "Li", "instagram": "Ig", "tiktok": "Tk"}
#: FR-21 defaults. Carousel slides are 1:1 everywhere and a reel is 9:16 on EVERY platform (the
#: ratio belongs to the format), so only single images vary by platform.
_IMAGE_RATIOS: dict[str, str] = {"linkedin": "16:9", "instagram": "4:5", "tiktok": "9:16"}
_CAROUSEL_RATIO, _REEL_RATIO, _FALLBACK_IMAGE_RATIO = "1:1", "9:16", "1:1"

Verdict = Literal["eligible", "excluded", "unusable"]


# --------------------------------------------------------------------------- select (FR-5/6/7)


@dataclass(slots=True)
class TrendVerdict:
    """One trend's fate, as `--preview-sources` prints it and a paid run would reach it (FR-139)."""

    trend: TrendItem
    verdict: Verdict
    reason: str = ""  # unusable: what was missing; excluded: which window it fell inside
    last_used: str | None = None  # FR-7: exclusions are logged WITH the date, always
    text_only: bool = False  # eligible, but the last resort of FR-90

    @property
    def label(self) -> str:
        """The exact operator-facing wording of FR-139's three verdicts."""
        if self.verdict == "excluded":
            return (f"excluded (history, last used {self.last_used or 'unknown'}, "
                    "no unused post left)")
        if self.verdict == "unusable":
            return f"unusable ({self.reason})"
        return "eligible (text_only — last resort)" if self.text_only else "eligible"


@dataclass(slots=True)
class Selection:
    """The ranked shortlist plus the full verdict feed it was distilled from."""

    verdicts: list[TrendVerdict] = field(default_factory=list)  # ranked order, every input trend

    def _of(self, verdict: Verdict) -> list[TrendVerdict]:
        return [v for v in self.verdicts if v.verdict == verdict]

    @property
    def eligible(self) -> list[TrendItem]:
        """Usable, un-excluded trends, strongest first (FR-5's `strength` is the sort key)."""
        return [v.trend for v in self._of("eligible")]

    @property
    def excluded(self) -> list[TrendVerdict]:
        return self._of("excluded")

    @property
    def unusable(self) -> list[TrendVerdict]:
        return self._of("unusable")


def select(trends: Sequence[TrendItem], config: Config,
           history: Mapping[str, dict[str, Any]] | None = None) -> Selection:
    """Rank the collected trends and give each one a verdict (FR-5/6/7).

    Ranking consumes each adapter's own `strength` in 0–1 — the one cross-source contract; Select
    knows no source's internals. Usability (FR-6) is judged before the history window (FR-7),
    because a trend with no text substance is unusable whether or not it was ever used and the
    abort message must name *that* cause rather than sending the operator off to widen a window
    that would not have helped.

    `history` is `outputs.read_history()`'s dict, keyed by `TrendItem.history_key`;
    `run.trend_history_days` is the window and `0` disables it entirely. The window is applied at
    MONITOR granularity only to a trend carrying no `chosen_post_ids`, because a trend that carries
    them had FR-7 enforced upstream at POST granularity already. Returns every input trend as a
    verdict, with `Selection.eligible` as the ranked shortlist `assign()` consumes.
    """
    known = dict(history or {})
    window = max(int(config.run.trend_history_days or 0), 0)
    ranked = sorted(trends, key=lambda t: (-float(t.strength or 0.0), t.name.lower(),
                                           t.history_key))
    verdicts: list[TrendVerdict] = []
    for trend in ranked:
        if reason := _unusable_reason(trend):
            verdicts.append(TrendVerdict(trend, "unusable", reason=reason))
            continue
        trend.text_only = _is_text_only(trend)  # item-level flag, re-derived from what arrived
        # The adapter that chose this trend's reference set had already dropped every post used
        # inside the window, so excluding the monitor as well would re-impose a throughput cap of
        # monitors ÷ trend_history_days. An empty tuple — a `text_only` item, or a monitor whose
        # every candidate set is used up — leaves monitor identity as the only recency signal.
        age = days_since_use(known, trend.history_key)
        if window and not trend.chosen_post_ids and age is not None and age < window:
            entry = known.get(trend.history_key) or {}
            verdicts.append(TrendVerdict(
                trend, "excluded", reason=f"used within the last {window} day(s)",
                last_used=str(entry.get("last_used") or "").strip() or None,
                text_only=trend.text_only))
            continue
        verdicts.append(TrendVerdict(trend, "eligible", text_only=trend.text_only))
    return Selection(verdicts=verdicts)


def _unusable_reason(trend: TrendItem) -> str:
    """FR-6: a name plus SOME text substance, else there is nothing to drive mimicry with."""
    if not (trend.name or "").strip():
        return "no trend name"
    substance = (trend.why_it_works.strip()
                 or any(t.strip() for t in trend.tactics)
                 or any(d.strip() for d in trend.video_descriptions))
    if not substance:
        return "no text substance (needs why_it_works, tactics or a top-video description)"
    return ""


def _is_text_only(trend: TrendItem) -> bool:
    """FR-6: text but no picture — kept, flagged, and used only as FR-90's last resort."""
    return trend.text_only or not any(url for group in trend.reference_groups for url in group)


# --------------------------------------------------------------------- expansion (FR-1/2/3/143)


@dataclass(slots=True)
class BriefRequest:
    """One `--brief <name>:<count>` request, already resolved by `briefs.load()` (FR-143/171)."""

    brief: Brief
    count: int


@dataclass(slots=True)
class Plan:
    """The resolved run plan: a flat, ordered list of creatives plus what did not make it."""

    entries: list[PlanEntry] = field(default_factory=list)
    #: Counts dropped BEFORE expansion — unpriced reels (FR-131), a format no platform allows
    #: (FR-132), a brief with no usable format. They never become entries, so this list is the
    #: run's only record that it delivered less than it was asked for: `runner._package()` feeds
    #: it to `decide_exit_code(plan_reduced=...)`, which is what keeps FR-252's "never a silent
    #: full-success exit" true for an unattended run. Emptying it silently is a defect.
    notes: list[str] = field(default_factory=list)


def build_plan(
    config: Config,
    *,
    briefs: Sequence[BriefRequest] = (),
    allow_reels: bool | None = None,
) -> Plan:
    """Expand requested counts into one entry per planned creative (FR-1/2/3/143).

    Counts are per format and are **never** multiplied across platforms (FR-2): each creative is
    round-robined over the platforms whose `formats:` allowlist enables that format, in config
    order, so remainders land on the earlier platforms. `both` mode duplicates every creative into
    an analyzed/direct pair sharing one `pair_id` and one `atomic_group` (FR-3) — except an
    `override` brief creative, which makes no analysis call and therefore renders exactly once,
    labelled `direct` with no `pair_id`.

    Brief creatives are emitted **first**, which is what makes FR-106's reverse-order trim safe:
    the campaign post the run was launched for is the last thing dropped. A brief's `count` is
    round-robined over the formats it declares, in declaration order. `allow_reels` overrides the
    FR-131 price gate for a caller that has already reported the missing price.

    Returns a `Plan` whose entries carry `order` 0..N-1 and a provisional `asset_id` — `assign()`
    rewrites the trend slug inside those ids — plus a `note` for every count that was dropped.
    """
    entries: list[PlanEntry] = []
    notes: list[str] = []
    creatives = count(1)  # one token per logical creative — the atomic_group / pair_id
    reels_ok = config.reels_plannable if allow_reels is None else allow_reels

    for request in briefs:  # FIRST, per FR-106's trim contract
        for fmt, platform in _brief_slots(request, config, reels_ok, notes):
            _emit(entries, config, fmt, platform, creatives, brief=request.brief)
    for fmt in FORMAT_ORDER:
        requested = int(config.run.formats.get(fmt, 0) or 0)
        for _, platform in _slots(fmt, requested, config, reels_ok, notes, label=fmt):
            _emit(entries, config, fmt, platform, creatives)

    for index, entry in enumerate(entries):
        entry.order = index
        entry.asset_id = _asset_id(entry, entry.brief_name or PENDING_TREND_SLUG)
    return Plan(entries=entries, notes=notes)


def _slots(fmt: CreativeFormat, requested: int, config: Config, reels_ok: bool,
           notes: list[str], *, label: str) -> list[tuple[CreativeFormat, str]]:
    """`requested` (format, platform) pairs, round-robined over the platforms allowing `fmt`."""
    if requested <= 0:
        return []
    if fmt == "reel" and not reels_ok:  # FR-131: an unpriced format is an unbounded format
        notes.append(f"{label} x{requested} not planned: {config.reel_price_key} is unset (FR-131)")
        return []
    platforms = [p for p in config.run.platforms if fmt in config.platform(p).formats]
    if not platforms:  # FR-132: a logged drop, never an error
        notes.append(f"{label} x{requested} dropped: no enabled platform allows {fmt} (FR-132)")
        return []
    return [(fmt, platforms[i % len(platforms)]) for i in range(requested)]


def _brief_slots(request: BriefRequest, config: Config, reels_ok: bool,
                 notes: list[str]) -> list[tuple[CreativeFormat, str]]:
    """FR-143: a brief's creatives spread over the formats it declares, then over platforms."""
    name = request.brief.name
    formats = [f for f in request.brief.formats if f in FORMAT_ORDER]
    if not formats or request.count <= 0:
        notes.append(f"brief {name} x{request.count} dropped: it declares no usable format")
        return []
    per_format: dict[CreativeFormat, int] = {}
    for index in range(request.count):
        chosen = formats[index % len(formats)]
        per_format[chosen] = per_format.get(chosen, 0) + 1
    slots: list[tuple[CreativeFormat, str]] = []
    for fmt in formats:
        if fmt in per_format:
            slots += _slots(fmt, per_format[fmt], config, reels_ok, notes, label=f"brief {name}")
    return slots


def _emit(entries: list[PlanEntry], config: Config, fmt: CreativeFormat, platform: str,
          creatives: Iterator[int], *, brief: Brief | None = None) -> None:
    """Append one logical creative: a single entry, or FR-3's analyzed/direct pair as one group."""
    group = f"c{next(creatives):02d}"
    variants: tuple[Variant, ...] = ("direct",)
    if brief is None or brief.influence != "override":  # override has no analysis call to A/B
        mode = config.run.generation_mode
        variants = ("analyzed", "direct") if mode == "both" else (
            ("analyzed",) if mode == "analyzed" else ("direct",))
    for variant in variants:
        entries.append(PlanEntry(
            order=0,  # rewritten once the whole plan is emitted
            asset_id="",  # provisional until _asset_id() runs; the trend slug lands in assign()
            creative_format=fmt, platform=platform, language=config.language_for(platform),
            aspect_ratio=_aspect_ratio(config, platform, fmt), variant=variant,
            pair_id=group if len(variants) == 2 else None, atomic_group=group,
            slide_count=config.platform(platform).carousel_slides if fmt == "carousel" else None,
            brief_name=brief.name if brief else None,
            brief_influence=brief.influence if brief else None))


def _aspect_ratio(config: Config, platform: str, fmt: CreativeFormat) -> str:
    """FR-21: platform × format defaults, overridable per platform in config."""
    if override := config.platform(platform).aspect_ratios.get(fmt):
        return override
    if fmt == "reel":
        return _REEL_RATIO  # a property of the FORMAT — 9:16 on every platform
    if fmt == "carousel":
        return _CAROUSEL_RATIO
    return _IMAGE_RATIOS.get(platform, _FALLBACK_IMAGE_RATIO)


def _asset_id(entry: PlanEntry, source_name: str) -> str:
    """FR-71's `<Pl>_<fmt>_<slug>_<variant>_<NN>`; the ordinal is the entry's own plan position."""
    platform = _PLATFORM_ABBR.get(entry.platform, entry.platform[:2].capitalize() or "Xx")
    fmt = _FORMAT_ABBR.get(entry.creative_format, entry.creative_format[:4])
    return f"{platform}_{fmt}_{slugify(source_name)}_{entry.variant}_{entry.order + 1:02d}"


# ------------------------------------------------------------------- assignment (FR-8/90/144)


@dataclass(slots=True)
class AssignmentDecision:
    """Why one creative (or one both-mode pair) got the trend it got — FR-90's audit trail."""

    atomic_group: str
    asset_ids: list[str]
    creative_format: CreativeFormat
    trend_key: str | None
    #: affinity | rank_fallback | reuse | last_resort_text_only | brief_override | dropped
    reason: str
    use_index: int = 0  # 1 = this trend's first use in the run; a both-mode pair counts once
    detail: str = ""


@dataclass(slots=True)
class Assignment:
    """The result of binding trends to creatives, with the numbers FR-8 makes the operator see."""

    decisions: list[AssignmentDecision] = field(default_factory=list)
    dropped: list[PlanEntry] = field(default_factory=list)  # surplus past the reuse bound
    usable_trends: int = 0
    trends_needed: int = 0
    batch_ceiling: int = 0  # usable_trends x max_trend_reuses_per_run — the real batch limit

    @property
    def summary_line(self) -> str:
        """FR-8's plain restatement, shown before generation proceeds."""
        return (f"this plan needs {self.trends_needed} distinct trend(s); "
                f"{self.usable_trends} are available after filtering "
                f"(batch ceiling {self.batch_ceiling} creatives)")


def assign(entries: Sequence[PlanEntry], selection: Selection, config: Config) -> Assignment:
    """Bind ranked trends to planned creatives by format affinity, then rank (FR-8/90).

    A both-mode pair and a carousel are each ONE unit: the pair shares one trend (otherwise the
    A/B comparison is meaningless) and counts as exactly one use against
    `max_trend_reuses_per_run`. `override` brief creatives consume no trend at all (FR-144) — they
    never touch the pool, the reuse budget or history. When the pool has no capacity left the
    surplus group is kept in the plan with a terminal `skipped` status and a reason (FR-4/8).

    Mutates each assigned entry in place: `trend_key` is set and `asset_id` is rewritten with the
    trend's slug (FR-71). Entries already terminal — budget-trimmed, say — are left alone.
    Returns one decision per group (FR-90's audit trail), the dropped entries, and the counts the
    console restatement of FR-8 needs.
    """
    max_reuses = max(int(config.run.max_trend_reuses_per_run or 1), 1)
    pool = list(selection.eligible)
    if config.run.require_reference_image and any(not t.text_only for t in pool):
        pool = [t for t in pool if not t.text_only]  # FR-90: text_only only when nothing else is
    rank = {trend.history_key: index for index, trend in enumerate(pool)}
    uses: dict[str, int] = {}
    result = Assignment(usable_trends=len(pool), batch_ceiling=len(pool) * max_reuses)

    for group, members in _groups(entries).items():
        ids = [entry.asset_id for entry in members]
        fmt = members[0].creative_format
        if members[0].brief_influence == "override":  # FR-144: consumes no trend
            result.decisions.append(AssignmentDecision(
                group, ids, fmt, None, "brief_override",
                detail=f"brief {members[0].brief_name} owns this creative outright"))
            continue
        result.trends_needed += 1
        trend, reason = _pick(pool, rank, uses, fmt, max_reuses)
        if trend is None:
            for entry in members:
                entry.status = PlanEntryStatus.SKIPPED
                entry.skip_reason = (
                    f"no_trend_available: {len(pool)} usable trend(s) x {max_reuses} reuse(s) "
                    "exhausted (FR-8)")
            result.dropped.extend(members)
            result.decisions.append(AssignmentDecision(group, ids, fmt, None, "dropped",
                                                      detail=members[0].skip_reason or ""))
            continue
        uses[trend.history_key] = use_index = uses.get(trend.history_key, 0) + 1
        for entry in members:
            entry.trend_key = trend.history_key
            entry.asset_id = _asset_id(entry, trend.name)
        result.decisions.append(AssignmentDecision(
            group, [entry.asset_id for entry in members], fmt, trend.history_key, reason,
            use_index=use_index,
            detail=f"{trend.name} · strength {trend.strength:.3f} · "
                   f"{'slideshow' if trend.is_slideshow else 'video'} source · use #{use_index}"))
    return result


def _groups(entries: Sequence[PlanEntry]) -> dict[str, list[PlanEntry]]:
    """Pending entries bucketed by `atomic_group`, in plan order — the unit of assignment."""
    grouped: dict[str, list[PlanEntry]] = {}
    for entry in entries:
        if entry.status is PlanEntryStatus.PENDING:
            grouped.setdefault(entry.atomic_group or entry.asset_id, []).append(entry)
    return grouped


def _affinity(trend: TrendItem, fmt: CreativeFormat) -> bool:
    """FR-90: slideshow material fits carousels; video material fits images and reels."""
    return trend.is_slideshow == (fmt == "carousel")


def _pick(pool: Sequence[TrendItem], rank: Mapping[str, int], uses: Mapping[str, int],
          fmt: CreativeFormat, max_reuses: int) -> tuple[TrendItem | None, str]:
    """The strongest trend that still has reuse capacity, affinity first (FR-8/90).

    Sort key, in order: `text_only` last always (FR-90's last resort), then fewest uses so a
    second creative prefers a fresh trend over a repeat, then affinity, then plain rank.
    """
    candidates = [t for t in pool if uses.get(t.history_key, 0) < max_reuses]
    if not candidates:
        return None, "dropped"
    best = min(candidates, key=lambda t: (
        t.text_only, uses.get(t.history_key, 0), not _affinity(t, fmt), rank[t.history_key]))
    if best.text_only:
        return best, "last_resort_text_only"
    if uses.get(best.history_key, 0):
        return best, "reuse"
    return best, "affinity" if _affinity(best, fmt) else "rank_fallback"


__all__ = [
    "Assignment", "AssignmentDecision", "BriefRequest", "FORMAT_ORDER", "PENDING_TREND_SLUG",
    "Plan", "Selection", "TrendVerdict", "assign", "build_plan", "select",
]
