"""Select + Expand — the deterministic middle of a run (FR-1–8, FR-90, FR-143–145).

Module contract
---------------
Purpose: turn *config + requested briefs* into an ordered plan of creatives, and *collected
topics + history* into a ranked shortlist with a verdict per topic, then bind the two together.
Public API: `select()` · `build_plan()` · `assign()` and their result objects
(`Selection`/`TrendVerdict`, `Plan`/`BriefRequest`, `Assignment`/`AssignmentDecision`).

Invariants:
- **Pure and instant** (NFR-2): no file, network or clock I/O and no logging — every decision
  leaves as data so `runner.py` logs it (NFR-5) and `previews.py` prints it at zero model spend
  (FR-139). History arrives as the dict `outputs.read_history()` returns.
- **One entry per creative** (v2.0.0, operator decision #2 — A/B mode withdrawn). Expansion emits
  exactly one `PlanEntry` per requested creative, and one creative is one render. FR-3's
  analyzed/direct duplication — two renders of one idea, tagged and cross-linked so a gallery
  could pair them — is gone, and with it the two `PlanEntry` fields that carried the tag and the
  link. Those fields survive as defaulted, unwritten leftovers until the Wave-3.5 excision; no id,
  group or decision in this module is keyed on either any more.
- **Every input topic comes back with a verdict** — `eligible` / `excluded` (with the date last
  used) / `unusable` (with the reason). Nothing is filtered away silently, because 10 §10's abort
  message must distinguish "excluded by history" from "rejected as unusable".
- **Brief entries are emitted FIRST and an `atomic_group` is never split** — the two properties
  that make FR-106's single "trim from the END, in reverse plan order" rule sufficient.
- **Nothing leaves the plan** (FR-4): a creative with no topic left keeps a terminal status and a
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
    Brief, CreativeFormat, PlanEntry, PlanEntryStatus, SourcePost, TrendItem)
from hypesocials.outputs import days_since_use, used_posts
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
    """One topic's fate, as the console prints it and a paid run would reach it (FR-139/FR-297).

    The "arrived without pictures" flag this carried until v2.0.0 is gone with FR-90's last-resort
    tier: Virlo is a text feed now and the pictures come from the style registry, so EVERY topic
    would raise that flag and a label that said so on every single line marked nothing.
    """

    trend: TrendItem
    verdict: Verdict
    reason: str = ""  # unusable: what was missing; excluded: which window it fell inside
    last_used: str | None = None  # FR-7: exclusions are logged WITH the date, always

    @property
    def label(self) -> str:
        """The exact operator-facing wording of FR-139's three verdicts.

        An exclusion carries its own reason rather than a fixed sentence, because FR-7 now has two
        distinct causes — every source post already used, or a post-less topic inside the
        topic-level window — and an operator deciding whether `--history-days` would help has to
        be able to tell them apart.
        """
        if self.verdict == "excluded":
            return (f"excluded (history, last used {self.last_used or 'unknown'}, "
                    f"{self.reason or 'no unused post left'})")
        if self.verdict == "unusable":
            return f"unusable ({self.reason})"
        return "eligible"


@dataclass(slots=True)
class Selection:
    """The ranked shortlist plus the full verdict feed it was distilled from."""

    verdicts: list[TrendVerdict] = field(default_factory=list)  # ranked order, every input trend

    def _of(self, verdict: Verdict) -> list[TrendVerdict]:
        return [v for v in self.verdicts if v.verdict == verdict]

    @property
    def eligible(self) -> list[TrendItem]:
        """Usable, un-excluded topics, strongest first (FR-5's `strength` is the sort key)."""
        return [v.trend for v in self._of("eligible")]

    @property
    def excluded(self) -> list[TrendVerdict]:
        return self._of("excluded")

    @property
    def unusable(self) -> list[TrendVerdict]:
        return self._of("unusable")


def select(trends: Sequence[TrendItem], config: Config,
           history: Mapping[str, dict[str, Any]] | None = None) -> Selection:
    """Rank the collected topics and give each one a verdict (FR-5/6/7).

    Ranking consumes each adapter's own `strength` in 0–1 — the one cross-source contract; Select
    knows no source's internals. Usability (FR-6) is judged before the history window (FR-7),
    because a topic with no text substance is unusable whether or not it was ever used and the
    abort message must name *that* cause rather than sending the operator off to widen a window
    that would not have helped.

    `history` is `outputs.read_history()`'s dict, keyed by `TrendItem.history_key` — post-pivot
    `"<monitor_id>::<topic_key>"`, so the window is per TOPIC and not per monitor;
    `run.trend_history_days` is the window and `0` disables it entirely.

    **FR-7 is enforced here, at POST granularity** (amended v2.0.0). The adapter used to drop
    already-used posts while choosing a reference set; post-pivot `sources/virlo.py` deliberately
    stops re-ordering on `used_posts` — the view rank of `TrendItem.posts` IS the sort proof the
    console prints (FR-297a/b) and the `P<n>` labels the copy call quotes by (§1.7) — and hands
    the exclusion decision to the stage that owns verdicts. So: a topic is excluded only when
    every one of its source posts was already used inside the window, because a topic is a
    standing subject that can be worked again the moment it surfaces a post whose text has not
    shipped yet. A topic that arrived with no posts at all carries no post identity, and there the
    topic-level `last_used` stamp is the only recency signal there is.

    Returns every input topic as a verdict, with `Selection.eligible` as the ranked shortlist
    `assign()` consumes.
    """
    known = dict(history or {})
    window = max(int(config.run.trend_history_days or 0), 0)
    # One flat union: post ids are globally unique, so which history key burnt a post does not
    # matter — a post whose text already shipped is burnt for every topic that carries it.
    burnt = {post for posts in used_posts(known, within_days=window).values() for post in posts}
    ranked = sorted(trends, key=lambda t: (-float(t.strength or 0.0), t.name.lower(),
                                           t.history_key))
    verdicts: list[TrendVerdict] = []
    for trend in ranked:
        if reason := _unusable_reason(trend):
            verdicts.append(TrendVerdict(trend, "unusable", reason=reason))
            continue
        if window and (reason := _exclusion_reason(trend, known, burnt, window)):
            entry = known.get(trend.history_key) or {}
            verdicts.append(TrendVerdict(
                trend, "excluded", reason=reason,
                last_used=str(entry.get("last_used") or "").strip() or None))
            continue
        verdicts.append(TrendVerdict(trend, "eligible"))
    return Selection(verdicts=verdicts)


def _unusable_reason(trend: TrendItem) -> str:
    """FR-6: a name plus SOME text substance, else there is nothing to drive mimicry with.

    Post-pivot the substance that matters most is the topic's own `posts` — the verbatim contract
    (§1.7) quotes their strings and nothing else — so a topic whose theme-level prose is thin is
    still perfectly usable when its winning posts carry text. The theme-level rows stay in the
    check beside them: they are what a synthesized single-topic monitor arrives with (FR-293's
    degenerate case), and either channel on its own is enough to write a creative from.
    """
    if not (trend.name or "").strip():
        return "no trend name"
    substance = (trend.why_it_works.strip()
                 or any(t.strip() for t in trend.tactics)
                 or any(d.strip() for d in trend.video_descriptions)
                 or any(_has_text(post) for post in trend.posts))
    if not substance:
        return "no text substance (needs post text, why_it_works, tactics or a description)"
    return ""


def _has_text(post: SourcePost) -> bool:
    """True when this source post carries at least one quotable string — §1.7's candidate set."""
    return any(str(text).strip() for text in (post.caption, post.description, *post.hooks,
                                              *post.text_overlays, *post.panel_texts))


def _exclusion_reason(trend: TrendItem, known: Mapping[str, dict[str, Any]],
                      burnt: set[str], window: int) -> str:
    """FR-7's cause for putting this topic out of the run, or `""` while it still has material.

    Two shapes, and the caller needs the difference in words: a topic whose every post is burnt is
    waiting for the source to surface a new post (widening the window cannot help, and neither can
    re-running), while a post-less topic inside the window is the pre-pivot whole-topic exclusion
    that `--history-days` genuinely does widen.
    """
    if trend.posts:
        if any(post.post_id not in burnt for post in trend.posts):
            return ""
        return f"all {len(trend.posts)} source post(s) used within the last {window} day(s)"
    age = days_since_use(known, trend.history_key)
    return f"used within the last {window} day(s)" if age is not None and age < window else ""


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
    """Expand requested counts into one entry per planned creative (FR-1/2/143).

    Counts are per format and are **never** multiplied across platforms (FR-2): each creative is
    round-robined over the platforms whose `formats:` allowlist enables that format, in config
    order, so remainders land on the earlier platforms. Each requested creative becomes exactly
    ONE entry (v2.0.0): FR-3's analyzed/direct duplication is withdrawn with generation mode, so a
    run of 4 images plans 4 entries and submits 4 renders, not 8.

    Brief creatives are emitted **first**, which is what makes FR-106's reverse-order trim safe:
    the campaign post the run was launched for is the last thing dropped. A brief's `count` is
    round-robined over the formats it declares, in declaration order. `allow_reels` overrides the
    FR-131 price gate for a caller that has already reported the missing price.

    Returns a `Plan` whose entries carry `order` 0..N-1 and a provisional `asset_id` — `assign()`
    rewrites the topic slug inside those ids — plus a `note` for every count that was dropped.
    """
    entries: list[PlanEntry] = []
    notes: list[str] = []
    creatives = count(1)  # one token per logical creative — the atomic_group
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
    """Append ONE logical creative as ONE entry (v2.0.0 — operator decision #2, A/B withdrawn).

    The `atomic_group` token outlives the pair it was invented for. It is still the unit
    `budget.trim` groups on when it cuts the plan back to the cap (`budget.py:548`) and the unit
    `assign()` binds a topic to (`_groups` below), and a carousel is still one atomic creative
    whose slides must never be split from each other (D31). Today every group holds exactly one
    entry; the seam stays because the trim rule is written in terms of the group, not because
    anything still pairs.
    """
    entries.append(PlanEntry(
        order=0,  # rewritten once the whole plan is emitted
        asset_id="",  # provisional until _asset_id() runs; the topic slug lands in assign()
        creative_format=fmt, platform=platform, language=config.language_for(platform),
        aspect_ratio=_aspect_ratio(config, platform, fmt),
        atomic_group=f"c{next(creatives):02d}",
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
    """FR-71's id, post-pivot: `<Pl>_<fmt>_<slug>_<NN>` — the A/B tag segment is gone.

    Nothing labels a creative `analyzed` or `direct` any more (v2.0.0), and a segment that reads
    `direct` on every folder in every run is noise inside a name that has a MAX_PATH budget.

    **The ordinal stays the tail.** It is the entry's own plan position and §1.10's provenance
    block names a creative by it (`id` = the asset id's trailing ordinal, `…_07`), so it is the
    operator's short handle across the console, the gallery and meta.yaml; anything appended after
    it would break that read. Two creatives sharing platform + format + topic still differ here,
    which is what keeps FR-71's "no silent folder overwrite" guarantee true without the A/B tag.
    """
    platform = _PLATFORM_ABBR.get(entry.platform, entry.platform[:2].capitalize() or "Xx")
    fmt = _FORMAT_ABBR.get(entry.creative_format, entry.creative_format[:4])
    return f"{platform}_{fmt}_{slugify(source_name)}_{entry.order + 1:02d}"


# ------------------------------------------------------------------- assignment (FR-8/90/144)


@dataclass(slots=True)
class AssignmentDecision:
    """Why one creative got the topic it got — FR-90's audit trail.

    `asset_ids` stays a list although an atomic group now holds exactly one entry: it is the group
    that is decided about, and the shape reads the same in run.log whether or not a future format
    ever fans one group back out.
    """

    atomic_group: str
    asset_ids: list[str]
    creative_format: CreativeFormat
    trend_key: str | None
    #: affinity | rank_fallback | reuse | brief_override | dropped
    reason: str
    use_index: int = 0  # 1 = this topic's first use in the run
    detail: str = ""


@dataclass(slots=True)
class Assignment:
    """The result of binding topics to creatives, with the numbers FR-8 makes the operator see.

    The field names keep saying `trend` where the amended FR-8 says `topic`: they are read by
    `runner`, `previews` and the FR-155 funnel, and renaming a data shape mid-pivot buys wording
    the operator never sees. The `summary_line` below — which IS what they see — says topic.
    """

    decisions: list[AssignmentDecision] = field(default_factory=list)
    dropped: list[PlanEntry] = field(default_factory=list)  # surplus past the reuse bound
    usable_trends: int = 0
    trends_needed: int = 0
    batch_ceiling: int = 0  # usable_trends x max_trend_reuses_per_run — the real batch limit

    @property
    def summary_line(self) -> str:
        """FR-8's plain restatement, shown before generation proceeds."""
        return (f"this plan needs {self.trends_needed} distinct topic(s); "
                f"{self.usable_trends} are available after filtering "
                f"(batch ceiling {self.batch_ceiling} creatives)")


def assign(entries: Sequence[PlanEntry], selection: Selection, config: Config) -> Assignment:
    """Bind ranked topics to planned creatives by format affinity, then rank (FR-8/90).

    A creative is ONE unit and counts as exactly one use against `max_trend_reuses_per_run` — a
    carousel too, because its slides are render jobs inside one entry rather than entries of their
    own. `override` brief creatives consume no topic at all (FR-144): they never touch the pool,
    the reuse budget or history. When the pool has no capacity left the surplus group is kept in
    the plan with a terminal `skipped` status and a reason (FR-4/8).

    Mutates each assigned entry in place:

    - `trend_key` (the topic's `history_key`) and `topic_key` name the bound topic — the second
      is what meta.yaml, the gallery and post-level recency read (FR-73/FR-153);
    - `trend_reuse_index` records this creative's 0-based position among the creatives sharing
      that topic. Post-pivot that index is the **sibling-divergence key**: `copywrite` quotes
      `posts[index % len(posts)]` (§1.6/§1.7.6), so two creatives on one topic quote two different
      source posts instead of shipping the same caption twice, and `styles.pick_reference_window`
      turns the same index into which slice of the assigned style's reference images this job
      attaches (A17's window rotation, re-homed);
    - `asset_id` is rewritten with the topic's slug (FR-71).

    Entries already terminal — budget-trimmed, say — are left alone, and an `override` brief entry
    keeps the default index 0 because it attaches no topic at all. Returns one decision per group
    (FR-90's audit trail), the dropped entries, and the counts the console restatement of FR-8
    needs.
    """
    max_reuses = max(int(config.run.max_trend_reuses_per_run or 1), 1)
    # No pre-filter here any more. The old "prefer topics that arrived with pictures" gate and the
    # config key that switched it on are withdrawn with the media funnel (FR-90 amended): a
    # post-pivot topic never arrives with pictures, so the gate either removed the whole pool or
    # none of it, and both outcomes were misreadings of a rule about material that no longer
    # exists. The visual authority is the assigned meta-style now (FR-290).
    pool = list(selection.eligible)
    rank = {trend.history_key: index for index, trend in enumerate(pool)}
    uses: dict[str, int] = {}
    result = Assignment(usable_trends=len(pool), batch_ceiling=len(pool) * max_reuses)

    for group, members in _groups(entries).items():
        ids = [entry.asset_id for entry in members]
        fmt = members[0].creative_format
        if members[0].brief_influence == "override":  # FR-144: consumes no topic
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
                    f"no_trend_available: {len(pool)} usable topic(s) x {max_reuses} reuse(s) "
                    "exhausted (FR-8)")
            result.dropped.extend(members)
            result.decisions.append(AssignmentDecision(group, ids, fmt, None, "dropped",
                                                      detail=members[0].skip_reason or ""))
            continue
        uses[trend.history_key] = use_index = uses.get(trend.history_key, 0) + 1
        for entry in members:
            entry.trend_key = trend.history_key
            entry.topic_key = trend.topic_key
            # 0-based, so the FIRST creative on a topic is index 0 and quotes `posts[0]` — the
            # top-viewed post. Every member of an atomic group shares one value: a deck's slides
            # must be written from one coherent source (D31).
            entry.trend_reuse_index = use_index - 1
            entry.asset_id = _asset_id(entry, trend.name)
        result.decisions.append(AssignmentDecision(
            group, [entry.asset_id for entry in members], fmt, trend.history_key, reason,
            use_index=use_index,
            detail=f"{trend.name} · strength {trend.strength:.3f} · "
                   f"{'slideshow' if trend.is_slideshow else 'video'} source · use #{use_index}"))
    return result


def _groups(entries: Sequence[PlanEntry]) -> dict[str, list[PlanEntry]]:
    """Pending entries bucketed by `atomic_group`, in plan order — the unit of assignment.

    One entry per bucket since v2.0.0 (nothing pairs any more), and the bucket is kept because it
    is the same unit `budget.trim` cuts on: assignment and trimming must not disagree about what a
    creative is.
    """
    grouped: dict[str, list[PlanEntry]] = {}
    for entry in entries:
        if entry.status is PlanEntryStatus.PENDING:
            grouped.setdefault(entry.atomic_group or entry.asset_id, []).append(entry)
    return grouped


def _affinity(trend: TrendItem, fmt: CreativeFormat) -> bool:
    """FR-90: slideshow material fits carousels; video material fits images and reels.

    `is_slideshow` is re-derived per topic post-pivot — the majority type across the topic's own
    view-ranked posts (§1.6) — so affinity now follows the composition of the posts a creative
    will actually quote instead of one label carried by a whole monitor.
    """
    return trend.is_slideshow == (fmt == "carousel")


def _pick(pool: Sequence[TrendItem], rank: Mapping[str, int], uses: Mapping[str, int],
          fmt: CreativeFormat, max_reuses: int) -> tuple[TrendItem | None, str]:
    """The strongest topic that still has reuse capacity, affinity first (FR-8/90).

    Sort key, in order: fewest uses, so a second creative prefers a fresh topic over a repeat;
    then affinity; then plain rank.

    The "arrived without pictures, use only as a last resort" tier that used to sort ahead of all
    three is withdrawn with FR-90's amendment. Post-pivot no topic arrives with pictures — Virlo is
    a text feed and the visuals come from the style registry — so a last-resort bucket that every
    single candidate falls into is not a tie-break; it is a no-op that reads like one, and the
    decision reason it produced would have labelled every assignment in every run.
    """
    candidates = [t for t in pool if uses.get(t.history_key, 0) < max_reuses]
    if not candidates:
        return None, "dropped"
    best = min(candidates, key=lambda t: (uses.get(t.history_key, 0), not _affinity(t, fmt),
                                          rank[t.history_key]))
    if uses.get(best.history_key, 0):
        return best, "reuse"
    return best, "affinity" if _affinity(best, fmt) else "rank_fallback"


__all__ = [
    "Assignment", "AssignmentDecision", "BriefRequest", "FORMAT_ORDER", "PENDING_TREND_SLUG",
    "Plan", "Selection", "TrendVerdict", "assign", "build_plan", "select",
]
