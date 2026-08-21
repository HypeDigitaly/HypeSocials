"""Select + Expand — the deterministic middle of a run (FR-1–8, FR-90, FR-143–145, FR-304/307).

Module contract
---------------
Purpose: turn *config + requested briefs* into an ordered plan of creatives, and *collected
topics + history* into a ranked shortlist with a verdict per topic, then bind the two together.
Public API: `select()` · `build_plan()` · `assign()` and their result objects
(`Selection`/`TrendVerdict`, `Plan`/`BriefRequest`, `Assignment`/`AssignmentDecision`), plus the
source-deck rules a carousel is bound by — `fresh_source_post()`, `deck_length()`, the
per-platform ASSIGN floor those two share, `min_panels()`, and FR-345's language screen
`off_language_post()`.

Invariants:
- **Pure and instant** (NFR-2): no file, network or clock I/O — every decision leaves as data so
  `runner.py` logs it (NFR-5) and `previews.py` prints it at zero model spend (FR-139). History
  arrives as the dict `outputs.read_history()` returns. There is NO exception, not even for
  FR-345's off-language drops: a post this run may not quote leaves as `Assignment.
  off_language_posts` — the `(post_id, language)` pairs — and `runner._select` is what turns
  them into the one warning and the one console line the operator reads. A logger call from
  here would have been swallowed anyway: `__main__._configure_logging` installs a NullHandler,
  so nothing written through `logging` reaches any operator surface. The pairs are collected
  where the pool is walked exactly ONCE per `assign()`, not inside the per-topic binder that
  `_pick` calls repeatedly, so a dropped post is named once rather than once per group.
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
- **A carousel binds ONE specific fresh source post at ASSIGN, and its deck length is fixed there**
  (FR-304/FR-95/§0.4′, v2.1.0). The post id lands on `PlanEntry.source_post_id`, the deck length on
  `PlanEntry.slide_count` — before the Confirm gate, so the estimate the operator approves is
  computed from the deck the run will actually render (rule 7). A carousel that finds no unused
  slideshow post skips with `no_fresh_post_available` rather than being bound to whatever is left:
  post ids are stable, and a repeat is the exact defect D46 exists to end.

Import edge (v2.7.0, D63): this module imports `topic_filter` for `target_languages()` and
`language_code()` — the SAME two functions the LLM screen decides a topic's language with, so the
screen at Select and the screen at ASSIGN can never disagree about what this run writes. The edge
is one-way and measured: `topic_filter`'s own closure is `config · models · prompts_engine ·
render · styles · util`, none of which import `plan`.

Do not: price anything (`budget.py` owns cost and trimming), read files, or assume reels are
enabled — an unpriced reel is not planned at all (FR-131).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import count
from typing import Any, Literal

from hypesocials import topic_filter
from hypesocials.config import Config
from hypesocials.models import (
    Brief, CreativeFormat, PlanEntry, PlanEntryStatus, SourcePost, TrendItem)
from hypesocials.outputs import days_since_use, used_posts
from hypesocials.util import slugify

logger = logging.getLogger(__name__)

#: Canonical format order — the order counts are expanded in, and the order of a brief's slots.
FORMAT_ORDER: tuple[CreativeFormat, ...] = ("image", "carousel", "reel")
#: Slug standing in for the trend inside an `asset_id` until `assign()` binds one (FR-71).
PENDING_TREND_SLUG = "unassigned"
#: The clamp's lower bound and the deck-eligibility bar in ONE number (FR-257/FR-304, §0.4′/§0.14a):
#: two panels is the shortest thing that still reads as a deck, so a source post with fewer usable
#: panel slots than this is not a carousel source at all, and a bound deck is never shorter.
#:
#: Since v2.2.0 this is the GLOBAL minimum rather than the whole rule: the ASSIGN floor is
#: per-platform (`platforms.<name>.min_carousel_panels`), and `min_panels()` below is where the two
#: are reconciled. Nothing in this module compares a panel count against this constant directly any
#: more except `deck_length`, whose clamp is about the deck we render and not about bindability.
MIN_DECK_SLIDES = 2
#: What a carousel with NO bound source post is worth in slides (`_emit`, §0.14d). Since
#: 2026-08-13 `platforms.<name>.carousel_slides` is a platform HARD MAX (20/10/20), not a target,
#: so quoting it as a provisional length would price a pre-Collect plan at four times the deck any
#: run actually ships. This number is the honest stand-in until `assign()` replaces it with the
#: bound post's own panel count, and it stays the final length for an override brief, which binds
#: no post and therefore has no panels to be 1:1 with.
DEFAULT_UNBOUND_DECK_SLIDES = 5
#: The machine-readable cause a starved carousel carries (FR-307/§0.10). It is a SKIP, not a
#: fallback: binding the entry to a post whose text already shipped is the repeat D46 forbids, and
#: binding it to a video topic is the silent rank-fallback FR-90 forbids.
NO_FRESH_POST_AVAILABLE = "no_fresh_post_available"

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
    """The ranked shortlist, the full verdict feed it was distilled from, and the burnt post ids."""

    verdicts: list[TrendVerdict] = field(default_factory=list)  # ranked order, every input trend
    #: Every post id whose text already shipped inside `run.trend_history_days` — the flat union
    #: `select()` already computed to reach its FR-7 verdicts, carried forward so `assign()` can
    #: enforce the SECOND half of §0.10's post-level guard (bind only a fresh post) without a
    #: second history read. Empty when the window is off, which is what disables the guard.
    burnt_posts: frozenset[str] = frozenset()

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
    `assign()` consumes and `Selection.burnt_posts` as the union of used post ids that same
    `assign()` binds around (FR-307's pick-time guard reads the set this call already built).
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
    return Selection(verdicts=verdicts, burnt_posts=frozenset(burnt))


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
        # A provisional length stands in until `assign()` replaces it with the bound source post's
        # own panel count (FR-304/§0.4′). It is the honest number until then — the pre-Collect
        # estimate (`runner._stamp_provisional`) is quoted before any post exists, and an override
        # brief binds no post at all (§0.14d), so it stays that entry's deck length for good. NOT
        # the platform ceiling: that key is a hard MAX now, and quoting it here would balloon every
        # pre-bind estimate to 20 slides a deck.
        slide_count=DEFAULT_UNBOUND_DECK_SLIDES if fmt == "carousel" else None,
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
    #: affinity | rank_fallback | reuse | brief_override | dropped | no_fresh_post_available
    reason: str
    use_index: int = 0  # 1 = this topic's first use in the run
    detail: str = ""
    #: The slideshow post a carousel was bound to (FR-304). Empty for every other format and for
    #: override briefs, which bind nothing (§0.14d).
    source_post_id: str = ""


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
    # --- FR-307/§0.10 supply accounting, all plan-side COUNTS. The console wording lives in
    # `runner._famine_message` (that stage owns what the operator reads); what this stage owns is
    # the arithmetic behind it, so the message can state supply instead of guessing at it.
    #: Distinct unused slideshow posts that carousels could reach across the eligible pool, counted
    #: BEFORE any binding — the numerator of "how many decks could this run have made".
    carousel_posts_available: int = 0
    carousel_posts_bound: int = 0  # how many of them this plan actually took
    no_fresh_post_skips: int = 0  # creative groups skipped with `no_fresh_post_available`
    #: v2.2.0: the ASSIGN floor the supply count above was screened at — the LOWEST
    #: `platforms.<name>.min_carousel_panels` among the plan's own carousels. It travels with the
    #: counts because a supply figure without its floor is not checkable: "4 fresh post(s) were
    #: bindable" means something different at 2 panels than at 3, and this run may hold both.
    carousel_floor: int = MIN_DECK_SLIDES
    #: v2.7.0 (D63/FR-345): every candidate source post the language screen refused, as
    #: `(post_id, language)` pairs, in pool order and without repeats. Only `source` mode ever
    #: fills it — under `target` the same posts are bound and translated, so the list is empty
    #: by construction. It exists because a post that quietly leaves the supply pool is the
    #: invisible defect FR-345 was written for (run `4a0q` bound a German post and nobody could
    #: see why), and NFR-2 forbids this module from printing or logging the fact itself. The
    #: language is the NORMALISED code (`language_code`), so the console can list `de, fr`
    #: rather than whatever spelling Virlo happened to send.
    off_language_posts: list[tuple[str, str]] = field(default_factory=list)

    @property
    def summary_line(self) -> str:
        """FR-8's plain restatement, shown before generation proceeds."""
        return (f"this plan needs {self.trends_needed} distinct topic(s); "
                f"{self.usable_trends} are available after filtering "
                f"(batch ceiling {self.batch_ceiling} creatives)")

    @property
    def fresh_post_line(self) -> str:
        """FR-307's supply arithmetic for the famine message, or `""` when no carousel starved.

        The remedy is not the one FR-8's ceiling suggests: a starved carousel is not short of
        TOPICS, it is short of unused source slideshows, and widening `--history-days` makes that
        strictly worse. Whoever prints this line says so; this property only supplies the counts.
        """
        if not self.no_fresh_post_skips:
            return ""
        return (f"{self.no_fresh_post_skips} carousel(s) found no unused source slideshow: "
                f"{self.carousel_posts_available} fresh post(s) were bindable across the eligible "
                f"topics and {self.carousel_posts_bound} of them were bound "
                f"(at the {self.carousel_floor}+ usable-panel floor)")


def assign(entries: Sequence[PlanEntry], selection: Selection, config: Config) -> Assignment:
    """Bind ranked topics to planned creatives by format affinity, then rank (FR-8/90).

    A creative is ONE unit and counts as exactly one use against `max_trend_reuses_per_run` — a
    carousel too, because its slides are render jobs inside one entry rather than entries of their
    own. `override` brief creatives consume no topic at all (FR-144): they never touch the pool,
    the reuse budget or history. When the pool has no capacity left the surplus group is kept in
    the plan with a terminal `skipped` status and a reason (FR-4/8).

    **A carousel is bound to a POST, not merely to a topic** (FR-304/FR-307, v2.1.0). For every
    non-override carousel group this call picks one specific slideshow post — fresh (its id is in
    neither the history window nor this run's own bindings), at least `min_panels(config, <the
    group's platform>)` panels long (v2.2.0: the floor is per-platform, LinkedIn 3, feed platforms
    2), and carrying usable text prospects (§0.14a) — preferring the topic's view rank, which is
    the order `TrendItem.posts` already arrives in. Format affinity is a HARD constraint there:
    only a slideshow-majority topic can source a panel-mapped deck, so a carousel with no such
    topic left skips with `no_fresh_post_available` instead of rank-falling back onto video
    material (FR-90 as amended). Images and reels keep affinity as the soft tie-break it always
    was — under `sources.include_videos: false` they are refused at pre-flight anyway (§0.14e), so
    hard-constraining them would only turn a clear config refusal into a silent famine.

    Mutates each assigned entry in place:

    - `trend_key` (the topic's `history_key`) and `topic_key` name the bound topic — the second
      is what meta.yaml, the gallery and post-level recency read (FR-73/FR-153);
    - `source_post_id` names the bound source post (carousels only, FR-304). It is what
      `copywrite` quotes panel by panel, what `sources.slide_intel` reads after the Confirm gate,
      and what the gallery joins its provenance card on;
    - `slide_count` is the deck length, fixed HERE from that post's panel count clamped under the
      `platforms.<name>.carousel_slides` HARD MAX (§0.4′) — the post's panels set the number, the
      platform only caps it, so a bound deck is 1:1 with its source. Fixing it before the estimate
      is what keeps the Confirm gate honest — vision intelligence runs later and may never change
      a deck's length;
    - `trend_reuse_index` records this creative's 0-based position among the creatives sharing
      that topic. **Legacy-only after D46 (§0.10 + the W3/F3 excision):** the bound
      `source_post_id` above says WHICH post a creative quotes, exactly and per creative, and
      the style reference window that also turned on this index died with the picture channel.
      What remains reads it only as a fallback for UNBOUND entries — `copywrite`'s degrade-path
      modulo and the runner's post-roster `-> NN` mapping — and nothing new may read it;
    - `asset_id` is rewritten with the topic's slug (FR-71).

    Entries already terminal — budget-trimmed, say — are left alone, and an `override` brief entry
    keeps the default index 0 because it attaches no topic at all. Returns one decision per group
    (FR-90's audit trail), the dropped entries, and the counts the console restatement of FR-8 and
    10 §10's famine message need.
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
    # The window's burnt ids PLUS everything this run binds as it goes: a post is a one-shot
    # resource inside a run exactly as it is across runs (§0.10), so two carousels on one topic
    # take its first and second unused post rather than quoting the same slides twice.
    burnt: set[str] = set(selection.burnt_posts)
    # FR-369 (v2.9.0, D65). `False` on every ordinary run, and every branch it guards below is
    # written so that reading it as False leaves this function byte-identical to its pre-D65 self.
    # Under the style test the material must be a CONSTANT: seventeen decks that each quoted a
    # different post would differ in their words, their panel count and their counter as well as in
    # their style, and no one could then say which of those the picture in front of them came from.
    # So the first carousel group picks exactly as it always did — the strongest bindable topic,
    # its top-ranked fresh post — and that one `(topic, post)` pair is then handed to every later
    # carousel group unchanged.
    style_test = bool(config.run.style_test)
    pinned: tuple[TrendItem, SourcePost] | None = None
    floor = _supply_floor(entries, config)
    available, off_language = _carousel_supply(pool, config, burnt, floor)
    result = Assignment(
        usable_trends=len(pool), batch_ceiling=len(pool) * max_reuses, carousel_floor=floor,
        carousel_posts_available=available, off_language_posts=off_language)

    for group, members in _groups(entries).items():
        ids = [entry.asset_id for entry in members]
        fmt = members[0].creative_format
        if members[0].brief_influence == "override":  # FR-144/§0.14d: consumes no topic, no post
            result.decisions.append(AssignmentDecision(
                group, ids, fmt, None, "brief_override",
                detail=f"brief {members[0].brief_name} owns this creative outright"))
            continue
        result.trends_needed += 1
        # A carousel binds a post, so its picker is post-aware (and affinity-constrained); every
        # other format still picks a topic alone and quotes it through `trend_reuse_index`. The
        # floor the binder screens against is the GROUP's platform (v2.2.0): every member of an
        # atomic group shares one destination, so one platform decides the whole deck's floor.
        platform = members[0].platform
        binder = ((lambda trend: fresh_source_post(trend, config, burnt, platform=platform))
                  if fmt == "carousel" else None)
        if style_test and fmt == "carousel" and pinned is not None:
            # The pin bypasses `_pick` outright rather than teaching it a mode. `_pick` answers a
            # supply question — which topic still has capacity, which of its posts is still unused
            # — and under the style test there is no supply question left to ask: the answer was
            # decided by the first group and every later group is told it. Going through the picker
            # would only give it the chance to say no (the post is now bound, its topic's rank may
            # have moved) to a pairing that is not negotiable.
            trend, post, reason = pinned[0], pinned[1], "reuse"
        else:
            trend, post, reason = _pick(pool, rank, uses, fmt, max_reuses, binder=binder)
        if trend is None:
            for entry in members:
                entry.status = PlanEntryStatus.SKIPPED
                entry.skip_reason = _skip_reason(reason, len(pool), max_reuses, config,
                                                 platform=entry.platform)
            result.dropped.extend(members)
            if reason == NO_FRESH_POST_AVAILABLE:
                result.no_fresh_post_skips += 1
            result.decisions.append(AssignmentDecision(group, ids, fmt, None, reason,
                                                      detail=members[0].skip_reason or ""))
            continue
        uses[trend.history_key] = use_index = uses.get(trend.history_key, 0) + 1
        for entry in members:
            entry.trend_key = trend.history_key
            entry.topic_key = trend.topic_key
            # 0-based, so the FIRST creative on a topic is index 0 and quotes `posts[0]` — the
            # top-viewed post. Every member of an atomic group shares one value: a deck's slides
            # must be written from one coherent source (D31). Deprecated as the post-pick key —
            # see this function's docstring; `source_post_id` below is what names the material now.
            entry.trend_reuse_index = use_index - 1
            if post is not None:  # FR-304/§0.4′ — the deck is decided here, not at render time
                entry.source_post_id = post.post_id
                entry.slide_count = deck_length(post, config, entry.platform)
            entry.asset_id = _asset_id(entry, trend.name)
        if post is not None:
            if not style_test:
                # FR-369 skips the burn, and only this line stands between the mode and itself: a
                # burnt post is unbindable for the rest of the run (§0.10), so the very first deck
                # would spend the material the other sixteen are supposed to share. The window's
                # own burnt ids are still honoured — the mode picks a FRESH post like any run, it
                # simply refuses to spend it — and history is not written either (`runner._package`
                # under the same flag), so the post is exactly as unused tomorrow as it was today.
                burnt.add(post.post_id)  # spent for the rest of this run, as well as the window
            result.carousel_posts_bound += 1
            if style_test and pinned is None:
                pinned = (trend, post)  # every later carousel group is told this pair
        result.decisions.append(AssignmentDecision(
            group, [entry.asset_id for entry in members], fmt, trend.history_key, reason,
            use_index=use_index, source_post_id=post.post_id if post else "",
            detail=f"{trend.name} · strength {trend.strength:.3f} · "
                   f"{'slideshow' if trend.is_slideshow else 'video'} source · use #{use_index}"
                   + (f" · post {post.post_id} · {members[0].slide_count} slide(s) of "
                      f"{source_panel_count(post)} source panel(s)" if post else "")
                   # FR-369's audit trail: the decision line is where an operator reads WHY two
                   # decks quote one post, and without this the run.log would look like the
                   # duplicate binding §0.10 exists to forbid.
                   + (" · style_test: post pinned" if style_test and post is not None else "")))
    return result


def _skip_reason(reason: str, pool_size: int, max_reuses: int, config: Config,
                 *, platform: str = "") -> str:
    """The one-line, machine-readable cause a skipped group carries (FR-4/FR-8/FR-307).

    Two distinct famines, and the operator needs the difference in words because the remedies point
    opposite ways: an exhausted topic pool is FR-8's arithmetic (fewer creatives, or more monitors),
    while an exhausted supply of unused slideshows is FR-307's cadence problem — running less often
    fixes it and widening the history window makes it strictly worse.
    """
    if reason == NO_FRESH_POST_AVAILABLE:
        # The floor is named WITH its platform since v2.2.0: "3+ usable panel(s)" on a run whose
        # other decks bound two-panel posts is otherwise unreadable as a per-platform rule.
        floor = min_panels(config, platform)
        return (f"{NO_FRESH_POST_AVAILABLE}: no eligible slideshow topic still offers an unused "
                f"source post with {floor}+ usable panel(s)"
                + (f" ({platform} floor)" if platform else "")
                + f" inside the {config.run.trend_history_days}-day no-repeat window "
                  "(FR-304/FR-307)")
    return (f"no_trend_available: {pool_size} usable topic(s) x {max_reuses} reuse(s) "
            "exhausted (FR-8)")


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

    For a CAROUSEL this is a constraint rather than a preference (FR-90/FR-304 as amended v2.1.0):
    our slide *i* renders their panel *i*, so a topic with no slideshow post has nothing a deck
    could be mapped from. For images and reels it stays the tie-break it always was.
    """
    return trend.is_slideshow == (fmt == "carousel")


def source_panel_count(post: SourcePost) -> int:
    """How many slides the SOURCE deck has — the raw number §0.4′ clamps into a deck length.

    Widest-evidence rule, mirroring `sources.slide_intel._skeleton` so that the deck this stage
    prices and the deck the vision pass later reads can never disagree: Virlo's own `panel_count`,
    the panel texts it shipped, or the slide images it listed, whichever is largest. A post that
    declares 8 panels and lists 8 images but carries 3 non-empty texts still has 8 slides; the
    empty slots are gaps to fill (§0.14a), never evidence of a shorter deck.
    """
    return max(int(post.panel_count or 0), len(post.panel_texts), len(post.image_urls))


def usable_panel_slots(post: SourcePost, config: Config) -> int:
    """§0.14a's usable-slot count, as far as ASSIGN can honestly know it (FR-304).

    A slot is usable iff it carries words after the merge of Virlo's `panel_texts` with the vision
    transcription — but the transcription is post-Confirm spend that has not happened yet, so at
    binding time the answer has to be a PROSPECT: a slot counts when Virlo already gave it words,
    or when `sources.vision_transcribe` is on and the slot has a slide image for the vision pass
    to read. With vision off (the operator's own switch, §0.6) only Virlo's words count, which is
    why turning it off narrows the pool of bindable posts as well as the run's spend.
    """
    slots = source_panel_count(post)
    vision = bool(config.sources.vision_transcribe)
    texts, images = post.panel_texts, post.image_urls
    return sum(1 for index in range(slots)
               if (index < len(texts) and str(texts[index]).strip())
               or (vision and index < len(images) and str(images[index]).strip()))


def min_panels(config: Config, platform: str = "") -> int:
    """The ASSIGN floor in force for `platform` — how many usable source panels a post must carry
    before a carousel for that platform may be bound to it (v2.2.0).

    `platforms.<name>.min_carousel_panels` is the per-platform number (LinkedIn ships 3: a
    two-slide LinkedIn document reads as a truncated post rather than as a carousel), and
    `MIN_DECK_SLIDES` is the global minimum underneath it — a configured value below two is
    meaningless, because two panels is the shortest thing that reads as a deck at all. `config`
    refuses a floor above that platform's own `carousel_slides` at load time, so the two ends of
    the clamp can never cross here.

    An empty `platform` means "no platform in particular" and yields the global minimum: it is what
    a supply count spanning several platforms and a caller that has no entry in hand both want.
    """
    if not platform:
        return MIN_DECK_SLIDES
    return max(MIN_DECK_SLIDES, int(config.platform(platform).min_carousel_panels or 0))


def off_language_post(post: SourcePost, config: Config) -> bool:
    """FR-345's bind-time language screen: is this post one a `source`-mode run must not bind?

    True only when ALL of these hold, which is the whole rule:

    - `run.copy_language_mode` is `source`. Under `target` the test is OFF by design — a foreign
      post is bound on purpose there, and its deck is translated at COPY (FR-343). This is the
      only eligibility test in this module that reads a run mode at all, and it reads it because
      the same post is a defect under one mode and the intended material under the other.
    - the post's language is KNOWN. An empty code means Virlo sent none and nobody has looked yet
      (the vision pass runs after Confirm), and a guess is not a reason to shrink the pool —
      fail-open, exactly as the LLM screen's own language check does.
    - the run writes at least one language, and the post's is not among them. `target_languages`
      is `topic_filter`'s union of `run.languages` and `run.onimage_text_language`; an empty union
      is a config that named no language and screens nothing.

    Why this exists at all: under `source` the copy is quoted byte for byte, so a German post
    inside an otherwise-English topic ships German pixels under an English caption. The FR-294
    topic screen catches the case where the WHOLE topic is off-language; it cannot catch one
    foreign post ranked first inside a topic the screen judged English, which is what happened to
    `Ig_car_claude-ai-for-productivity-and-business_08` in run `20260820_145809_4a0q`.

    The post's own code is re-normalised through `language_code` rather than trusted: the Virlo
    adapter already normalises it on the way in, but a `SourcePost` also arrives from a preview
    fixture or a test, and one spelling rule for every rung of the ladder is the point.
    """
    if str(config.run.copy_language_mode) != "source":
        return False
    language = topic_filter.language_code(post.language)
    targets = topic_filter.target_languages(config)
    return bool(language and targets and language not in targets)


def fresh_source_post(trend: TrendItem, config: Config,
                      burnt: Collection[str] = frozenset(), *,
                      platform: str = "") -> SourcePost | None:
    """This topic's best unused slideshow post for a panel-mapped deck, or None (FR-304/FR-307).

    "Best" is simply the first one in `trend.posts`, because that list arrives view-ranked and the
    view rank is the whole reason to quote a post at all (§1.6). Eligibility is D46's own predicate:
    an id that is not burnt (neither in the history window nor already bound in this run), at least
    `min_panels(config, platform)` source panels, and at least that many usable panel slots
    (§0.14a).

    **A FOURTH test since v2.7.0 (D63/FR-345), and the only mode-gated one:** under
    `run.copy_language_mode: source` a post whose language is known and is not one this run writes
    is skipped (`off_language_post` above). Under `target` it is bound like any other, because the
    deck it produces is translated at COPY — the same post is the defect in one mode and the point
    in the other. This is the fix for the German deck of run `20260820_145809_4a0q`, where the
    topic screen passed an English-looking topic whose top-ranked post was German and the deck
    shipped German panels under an English caption.

    The test is applied HERE and not one layer up because the alternatives are worse: screening
    after `_pick` has chosen would leave the group with no post at all rather than the topic's
    next-best one, and screening the whole topic is FR-294's job at Select, where the decision is
    about a topic's own strings rather than about one ranked post inside it.

    `platform` is the DESTINATION of the creative being bound (v2.2.0): the floor is per-platform
    now, so the same post can be bindable for Instagram and not for LinkedIn. Omitting it screens
    against the global minimum, which is the pre-v2.2.0 behaviour and what a caller with no entry
    in hand (a preview, a supply count) gets.

    Returns the `SourcePost` itself rather than its id: the caller needs the panel count to fix the
    deck length in the same step, and re-finding the post by id afterwards is how those two numbers
    drift apart.
    """
    used = set(burnt)
    floor = min_panels(config, platform)
    for post in trend.posts:
        post_id = str(post.post_id or "").strip()
        if not post_id or post_id in used:
            continue
        if source_panel_count(post) < floor:
            continue
        if usable_panel_slots(post, config) < floor:
            continue
        if off_language_post(post, config):  # FR-345, `source` mode only — silent here, and
            continue  # collected once per post by `_carousel_supply`, which walks the pool once
        return post
    return None


def deck_length(post: SourcePost, config: Config, platform: str) -> int:
    """§0.4′/FR-95/FR-257: the source's panel count clamped into `[2, carousel_slides]`.

    **The source decides the length; `carousel_slides` is only a HARD MAX** (operator decision
    2026-08-13). It is what the destination platform will accept — 20 on LinkedIn and TikTok, 10 on
    Instagram — and nothing else in the engine treats it as a target any more, so a 7-panel post
    ships a 7-slide deck and a 3-panel post ships 3. That is FR-304's 1:1 panel fidelity: run
    20260813_143420_oyo4 cut every 5–8 panel source down to 5 because this key used to mean both
    things at once.

    Free arithmetic over data Virlo already handed us, which is exactly why the deck length is
    fixed here and not after the vision pass: the Confirm gate prices the deck it will render
    (rule 7), and vision intelligence is additive content that may never change a length.

    A source deck longer than the max is TRUNCATED to its first N panels with the indices
    preserved — `generate/carousel.py` tags that cut `panels_truncated` by comparing this length
    back against `source_panel_count()`. With the maxes at 20/10/20 that cut is now the rare case
    it should always have been. The max itself is floored at `MIN_DECK_SLIDES` so a misconfigured
    `carousel_slides: 1` cannot produce a one-slide "carousel".
    """
    ceiling = max(int(config.platform(platform).carousel_slides or 0), MIN_DECK_SLIDES)
    return max(MIN_DECK_SLIDES, min(source_panel_count(post), ceiling))


def _carousel_supply(pool: Sequence[TrendItem], config: Config, burnt: Collection[str],
                     floor: int = MIN_DECK_SLIDES,
                     ) -> tuple[int, list[tuple[str, str]]]:
    """Distinct unused source posts the run's carousels could reach — FR-307's supply numerator.

    Counted over the SLIDESHOW half of the pool only, because affinity is a hard constraint for
    carousels: a bindable post sitting inside a video-majority topic is supply no deck can spend,
    and reporting it would make a famine message argue against the skip that produced it.

    `floor` is the LOWEST ASSIGN floor across the carousels this plan actually holds (v2.2.0). A
    plan can mix platforms with different floors, and the honest numerator for "how many decks
    could this run have made" is the count some carousel in it could still bind: counting against
    the strictest floor would understate the supply a TikTok deck can reach, and counting against
    no floor at all would report posts nothing in the plan may bind.

    FR-345's language screen applies here too, and it must: this count is the numerator of the
    famine message, so counting a post `fresh_source_post` will refuse to bind would make that
    message argue against the skip it is explaining. It is also the ONE walk that sees every
    candidate post exactly once per `assign()`, which is why the dropped posts are collected here
    rather than in the binder — `_pick` calls the binder once per topic per creative group, and
    the same German post would otherwise be reported nine times on a nine-deck plan.

    Returns BOTH numbers a caller needs, because they come from the same walk and separating them
    would mean walking twice with two chances to disagree: the count itself, and the
    `(post_id, language)` pairs the screen refused. The pairs leave as DATA on `Assignment`
    (NFR-2) — `runner._select` writes the warning and the console line, since a `logging` call
    from here reaches nobody (`__main__._configure_logging` installs a NullHandler and no console
    handler at all). Order is pool order and each post id appears at most once, so the console
    line is stable between two runs of the same plan.
    """
    used = set(burnt)
    available: set[str] = set()
    off_language: list[tuple[str, str]] = []
    seen_off: set[str] = set()
    for trend in pool:
        if not trend.is_slideshow:
            continue
        for post in trend.posts:
            post_id = str(post.post_id or "").strip()
            if (post_id and post_id not in used and post_id not in available
                    and source_panel_count(post) >= floor
                    and usable_panel_slots(post, config) >= floor):
                if off_language_post(post, config):
                    if post_id not in seen_off:
                        seen_off.add(post_id)
                        off_language.append(
                            (post_id, topic_filter.language_code(post.language)))
                    continue
                available.add(post_id)
    return len(available), off_language


def _supply_floor(entries: Sequence[PlanEntry], config: Config) -> int:
    """The lowest ASSIGN floor among the plan's pending carousels — `_carousel_supply`'s screen.

    No carousel in the plan means no supply question to answer, and the global minimum is then the
    neutral answer (the count is only ever printed by a famine message a carousel raised).
    """
    floors = [min_panels(config, entry.platform) for entry in entries
              if entry.creative_format == "carousel" and entry.status is PlanEntryStatus.PENDING
              and entry.brief_influence != "override"]
    return min(floors) if floors else MIN_DECK_SLIDES


def _pick(pool: Sequence[TrendItem], rank: Mapping[str, int], uses: Mapping[str, int],
          fmt: CreativeFormat, max_reuses: int,
          *, binder: Callable[[TrendItem], SourcePost | None] | None = None,
          ) -> tuple[TrendItem | None, SourcePost | None, str]:
    """The strongest topic that still has reuse capacity, plus the post a carousel binds (FR-8/90).

    Sort key, in order: fewest uses, so a second creative prefers a fresh topic over a repeat;
    then affinity; then plain rank.

    The "arrived without pictures, use only as a last resort" tier that used to sort ahead of all
    three is withdrawn with FR-90's amendment. Post-pivot no topic arrives with pictures — Virlo is
    a text feed and the visuals come from the style registry — so a last-resort bucket that every
    single candidate falls into is not a tie-break; it is a no-op that reads like one, and the
    decision reason it produced would have labelled every assignment in every run.

    `binder` (carousels only, FR-304) turns a topic into the fresh source post it would bind, or
    None when it has none left. With a binder the sort loses its affinity term — affinity and
    bindability are both filters then, so every survivor is an affinity match — and the two ways to
    come back empty stay distinguishable: `dropped` means the reuse budget is spent, while
    `no_fresh_post_available` means topics remain but their slideshows do not (FR-307).
    """
    candidates = [t for t in pool if uses.get(t.history_key, 0) < max_reuses]
    if not candidates:
        return None, None, "dropped"
    if binder is None:
        best = min(candidates, key=lambda t: (uses.get(t.history_key, 0), not _affinity(t, fmt),
                                              rank[t.history_key]))
        if uses.get(best.history_key, 0):
            return best, None, "reuse"
        return best, None, "affinity" if _affinity(best, fmt) else "rank_fallback"
    bindable = [(trend, post) for trend in candidates if _affinity(trend, fmt)
                and (post := binder(trend)) is not None]
    if not bindable:
        return None, None, NO_FRESH_POST_AVAILABLE
    trend, post = min(bindable, key=lambda pair: (uses.get(pair[0].history_key, 0),
                                                  rank[pair[0].history_key]))
    return trend, post, "reuse" if uses.get(trend.history_key, 0) else "affinity"


__all__ = [
    "Assignment", "AssignmentDecision", "BriefRequest", "FORMAT_ORDER", "MIN_DECK_SLIDES",
    "NO_FRESH_POST_AVAILABLE", "PENDING_TREND_SLUG", "Plan", "Selection", "TrendVerdict", "assign",
    "build_plan", "deck_length", "fresh_source_post", "min_panels", "off_language_post", "select",
    "source_panel_count", "usable_panel_slots",
]
