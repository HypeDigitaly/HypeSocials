"""Matched style assignment — ONE batched, fail-open LLM call at ASSIGN (FR-334, D56).

Callers import `hypesocials.style_match`. One call, one concept — of the styles this run may
wear, which one actually SUITS each creative's own source material:

    picks = await match(styled, registry, by_key, config, llm)   # {asset_id: Match}, ALWAYS total
    for entry in styled:
        pick = picks[entry.asset_id]
        entry.style_key = pick.style_key or entry.style_key      # "" = the baseline stands
        entry.style_fit, entry.style_reason = pick.fit, pick.reason
        entry.style_origin, entry.style_wanted = pick.origin, pick.wanted_archetype

**An OVERLAY, never a replacement.** `styles.assign_styles` has already laid down the FR-291
rotation baseline before this module is called, and that baseline stays exactly what it was: a
pure, content-blind function of `entry.order` over the format-affine pool, with no LLM anywhere
near it. This call can only ever say "wear THIS one instead"; every other answer — a `low` fit, a
key outside the entry's own pool, a row that never came back, a call that never happened — leaves
the rotation pick untouched. That is why `Match.style_key` is EMPTY on those paths rather than
carrying the baseline key: the winner is the caller's to keep, and a matcher that echoed the
baseline back could not be told apart from one that chose it.

**Fail-open, like the topic screen (§1.5) and slide intelligence (§0.14c).** No `llm`, a raised
call, a degraded or unparseable answer: every entry comes back on `origin="rotation_fallback"`
with `reason` opening on the `style_match_degraded:` marker, which the caller turns into ONE
operator warning and one degradation tag. A matcher we could not run is a run that assigns styles
the way it assigned them before D56 — never a run that loses its plan. The provider-side catch
logs the exception CLASS NAME and nothing else: an error body can carry a URL or a payload, and
this string reaches the operator, the run log and meta.yaml (D30).

**The determinism trade (FR-334), stated out loud.** Matched picks are NOT reproducible run to
run: the same plan against the same topics may wear different styles tomorrow, because a model
chose. What is preserved is that the substrate underneath stays deterministic — `assignment:
rotation` restores pre-D56 behaviour byte-exactly, and even under `matched` every entry this call
does not answer for keeps a pick that is a pure function of its own `order`. The mode gate lives
at the CALL SITE (`config.styles.assignment`), not here: this module is what running the matcher
means, not whether to run it.

**Nothing this module returns becomes pixels.** `reason` and `wanted_archetype` are model-authored
prose that lands on the ASSIGN receipt, in `meta.yaml` and on a gallery card — three places a
person reads and no place a render prompt, a copy call, a budget line or a drop path reads. They
are stripped of control characters (an ESC run is an ANSI sequence aimed at the operator's
console) and bounded in length on the way out of this module, so the sanitizing happens once, at
the boundary where the strings stop being an answer and start being output.

Two structural rules the rest of the module exists to keep:

- **The pool predicates are IMPORTED, never re-derived.** A candidate ballot is
  `styles.usable_styles(...)` narrowed by `styles.fmt_affine(...)`, so a `carousel_role:
  slides_only` style can no more be MATCHED onto a deck than it could be ROTATED onto one, and the
  brand filter, the FR-314 selector and FR-318's master switch all apply identically to both
  algorithms. A second copy of those rules here is how the two paths start disagreeing about what
  a run may wear.
- **Answers join on `asset_id`, never on ordinal.** The id is the only identity a creative has in
  the prompt, and an ordinal join is what produced the W5 renumbering bug (`runner.py:438-447`):
  one dropped row and every later answer lands on its predecessor's creative. An unknown id, a
  duplicated id and a missing row are all logged and all resolve to "the baseline stands".

Do not: call this before the Confirm gate (it costs money — it is priced there as
`style_match_call`); let anything here raise (`match()` is total and the caller has no fallback
path of its own); read `config.styles.assignment` here; import `runner`, `budget` or `previews`
(this is a leaf, exactly as `topic_filter` is); put `reason` or `wanted_archetype` into any
string that reaches a render provider.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, get_args

from .config import Config
from .models import (CreativeFormat, DegradationTag, MetaStyle, PlanEntry, SourcePost,
                     StructuredCall, TrendItem)
from .plan import source_panel_count, usable_panel_slots
from .prompts_engine import PromptEngine, build_context
from .styles import StyleRegistry, fmt_affine, match_profile_for, usable_styles
from .util import fit as one_line  # `util.fit` — aliased, because `fit` is this module's answer field

logger = logging.getLogger(__name__)

#: Sonnet 5 (`config.models.analysis`), the same role `slide_intel` runs on: this is a reading
#: task over third-party text, not a writing one, and the copy role's cheap model is tuned for the
#: opposite job. One call per RUN, batched over every entry in scope.
MATCH_ROLE = "analysis"
MATCH_TEMPLATE = "style_match_system.md"
_CARRIER_TURN = "Return the match JSON for the creatives above now."

#: The three fit levels of FR-335's answer contract. `medium` ACCEPTS: the pick is used exactly as
#: a `high` one is, because "no candidate is a natural home but this one will not fight the
#: content" is still a content-aware choice, and the alternative is a content-BLIND one.
FIT_HIGH, FIT_MEDIUM, FIT_LOW = "high", "medium", "low"
_ACCEPTS = frozenset({FIT_HIGH, FIT_MEDIUM})
_FITS = (FIT_HIGH, FIT_MEDIUM, FIT_LOW)

#: `Match.origin` — WHICH algorithm produced the style the caller ends up with, and the field a
#: reader should check first. The rotation/rotation_fallback split is what tells a per-entry
#: rejection apart from a run-wide outage; the pick alone cannot, since both keep the baseline.
ORIGIN_ROTATION = "rotation"
ORIGIN_MATCHED = "matched"
ORIGIN_FALLBACK = "rotation_fallback"

#: The marker every reason carries on a whole-call failure, taken from the degradation tag itself
#: rather than spelled again here — the console line, the meta.yaml tag and this string are then
#: one fact with one spelling (mirrors `topic_filter`'s `filter_degraded:`).
DEGRADED_MARKER = DegradationTag.STYLE_MATCH_DEGRADED.value

#: Output bounds for the two model-authored strings. A `reason` is specified as ~12 words and a
#: `wanted_archetype` as 3–8; these ceilings are roughly double that, so an obedient model is never
#: cut and a runaway one cannot push a 4 kB paragraph onto a console line, into `meta.yaml` and
#: through the gallery's card markup.
_MAX_REASON_CHARS = 160
_MAX_WANTED_CHARS = 72
_MAX_KEY_CHARS = 64  # a rejected `style_key` is echoed into the operator's reason line

#: Control characters (C0 + DEL) in a model-authored string, replaced before anything is printed.
#: Newlines break the receipt's one-line-per-creative shape; ESC begins an ANSI sequence that would
#: be EXECUTED by the operator's console rather than read.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

#: Prompt-leanness caps. This call matches a LOOK, so it is shown how MUCH text a source carries,
#: never the text itself: a per-field character count is the whole signal, and a 40-panel deck
#: needs no more than a dozen of them to establish "long, dense, sequential".
_MAX_LENGTHS = 12
_MAX_LABELS = 6  # hook_types / visual_hook_types / emotional_tones / engagement rows
_MAX_LABEL_CHARS = 40  # one classification label — `story_tease`, `curiosity`; never a sentence
_MAX_TOPIC_CHARS = 90
_MAX_WHY_CHARS = 200

#: The three creative formats, read off `models.CreativeFormat` rather than spelled again: the
#: candidate block states which formats a style is AFFINE to, and that answer has to come from
#: `fmt_affine` over the same vocabulary the rest of the engine uses.
_FORMATS: tuple[str, ...] = tuple(get_args(CreativeFormat))


@dataclass(slots=True)
class Match:
    """One creative's match answer, keyed by `asset_id` — what the caller stamps onto the entry.

    Every field is EMPTY where no answer applies, which is the shape that lets a caller write
    `entry.style_key = pick.style_key or entry.style_key` and have the FR-291 baseline stand by
    construction rather than by branching.
    """

    asset_id: str
    #: The ACCEPTED pick, and `""` whenever the rotation baseline stands — including a `low` fit,
    #: an out-of-pool key, a missing row and a whole-call failure. Never the baseline key echoed
    #: back: the caller owns that value and this field is the OVERRIDE, not the outcome.
    style_key: str = ""
    #: `high` | `medium` | `low`, or `""` when no answer applies (no row, an unreadable fit word,
    #: a rejected key — where printing the model's own confidence beside a rotation pick would
    #: read as "high fit, assigned anyway").
    fit: str = ""
    #: Short operator-facing prose: the model's own sentence on an answered row, an engine sentence
    #: on a rejected one, and `f"{DEGRADED_MARKER}: <cause>"` on every row of a failed call.
    #: Sanitized and length-bounded here; never executable, never rendered.
    reason: str = ""
    #: The archetype the model wanted and the registry did not offer — only on a `low` (or
    #: otherwise unusable) row, and PRESERVED through the fall back to baseline. This is D56's gap
    #: report: the engine never synthesizes a style at runtime (FR-295 registry authority), so the
    #: miss is written down and the operator authors the missing style deliberately.
    wanted_archetype: str = ""
    origin: str = ORIGIN_ROTATION  # `rotation` | `matched` | `rotation_fallback`


class _MatchUnavailable(RuntimeError):
    """The match call produced nothing usable. Caught in `match()`; the run degrades, never fails."""


# --------------------------------------------------------------------------------------------
# The match
# --------------------------------------------------------------------------------------------


async def match(entries: Sequence[PlanEntry], registry: StyleRegistry,
                topics: Mapping[str, TrendItem], cfg: Config,
                llm: StructuredCall | None) -> dict[str, Match]:
    """Match every entry once. Returns exactly one `Match` per input `asset_id`, and NEVER raises.

    The mapping is ALWAYS total: an entry the model had no row for, answered twice, or was never
    shown at all still comes back — on `origin="rotation"` with an empty `style_key`, which means
    "keep what the rotation gave you". The caller must never have to ask whether a creative was
    matched, and must never have to guard a `KeyError` around a style assignment.

    Three classes of entry never reach the prompt at all, and each costs nothing:

    - an **override brief** (`brief_influence == "override"`), which is never styled at all (M14 —
      its directives replace the style channel outright, `runner._assign_visuals`). The caller
      filters these out; this is the defence in depth, so an override entry passed in by a future
      caller comes back on `rotation` and buys no tokens;
    - an entry whose candidate pool is **empty** — no style under this brand, this
      `styles.enabled` selection and FR-318's switch is affine to its format;
    - an entry whose pool holds **exactly one** style. There is no choice to make, and a ballot
      with one name on it is a question whose answer is already known: asking it costs prompt
      space and invites a model to answer `low` on the only style the run can wear.

    When NOTHING is in scope the call is skipped entirely and every entry comes back on
    `rotation` — deliberately NOT `rotation_fallback`, even with `llm=None`. Nothing degraded: a
    matcher with nothing to choose between did not fail, and warning the operator (plus tagging
    every asset `style_match_degraded`) about a call that was never needed is a false alarm.

    Args:
        entries: this run's live plan entries, AFTER `styles.assign_styles` has set the baseline.
        registry: the loaded `styles.yaml`. `None` is tolerated (a registry-less run has no styles
            to match) and yields the all-`rotation` mapping.
        topics: the run's topics by `history_key` — `entry.trend_key`'s key space, exactly as
            `runner._pipeline` builds it. A missing key simply means fewer signals for that entry.
        cfg: the run config — `branding.brand`, `styles.enabled` and `branding.enabled` narrow the
            candidate pools, `prompts_dir` resolves the template (FR-174), `sources` decides what
            counts as a usable panel slot. `styles.assignment` is NOT read here (see module docs).
        llm: `llm.structured_call` (`models.StructuredCall`), or None. None with entries in scope
            is a degrade (there is a question and no way to ask it); None with nothing in scope is
            simply a $0 no-op.
    """
    out = {entry.asset_id: Match(asset_id=entry.asset_id) for entry in entries}
    if not out:
        return out
    try:
        ballots = _ballots(entries, registry, cfg)
    except Exception as exc:  # noqa: BLE001 — `match()` is total by contract. A pool we cannot
        # build is a question we cannot ask, which is the baseline standing, not an exception in
        # the middle of ASSIGN. Class name only (D30).
        logger.warning("style_match: candidate pools could not be built (%s) — the rotation "
                       "baseline stands for every creative", type(exc).__name__)
        ballots = {}
    if not ballots:
        logger.debug("style_match: no creative has a choice to make — no call, $0")
        return out

    cause = ""
    rows: list[Mapping[str, Any]] = []
    if llm is None:
        cause = "no model call available"
    else:
        try:
            rows = await _llm_matches(entries, ballots, topics, cfg, llm)
        except _MatchUnavailable as exc:
            cause = str(exc)
        except Exception as exc:  # noqa: BLE001 — fail-open by contract (FR-334): a match we could
            # not run must never cost the plan its styles. The class NAME only — a provider error
            # body can carry a URL or a payload and this string reaches the operator (D30).
            cause = f"the match call raised {type(exc).__name__}"
            logger.warning("style_match: match call failed (%s)", type(exc).__name__)
    if cause:
        logger.warning("style_match: matched assignment degraded — %s; the FR-291 rotation "
                       "baseline stands for every creative", cause)
        for pick in out.values():  # the marker the caller turns into ONE warning + one tag
            pick.origin = ORIGIN_FALLBACK
            pick.reason = f"{DEGRADED_MARKER}: {cause}"
        return out
    _merge(out, rows, ballots)
    return out


# --------------------------------------------------------------------------------------------
# Candidate pools — the registry's own predicates, imported
# --------------------------------------------------------------------------------------------


def _ballots(entries: Sequence[PlanEntry], registry: StyleRegistry,
             cfg: Config) -> dict[str, list[MetaStyle]]:
    """`{asset_id: the styles THIS creative may actually be given}`, for entries with a choice.

    The run-wide pool is computed ONCE (`usable_styles` is the same three filters for every entry
    — brand, the FR-314 selector, FR-318's switch) and narrowed per entry by `fmt_affine`, which
    is the only per-entry predicate there is. Both are imported from `styles`: the ballot a model
    votes on and the pool the rotation scans must be the same set, or matched mode could assign
    something rotation mode is forbidden to.

    Entries with no ballot are simply absent from the result — see `match()` for the three ways
    that happens and why each is free.
    """
    if registry is None:  # a registry-less run (pre-flight refuses it; previews may not have one)
        logger.debug("style_match: no style registry — nothing to match against")
        return {}
    pool = usable_styles(registry, cfg.branding.brand, cfg.styles.enabled,
                         branding_enabled=cfg.branding.enabled)
    ballots: dict[str, list[MetaStyle]] = {}
    for entry in entries:
        if entry.brief_influence == "override":
            continue  # M14: an override brief has no style channel at all
        candidates = [style for style in pool if fmt_affine(style, entry.creative_format)]
        if len(candidates) < 2:
            logger.debug("style_match: %s has %d candidate(s) — no choice to make, not asked",
                         entry.asset_id, len(candidates))
            continue
        ballots[entry.asset_id] = candidates
    return ballots


# --------------------------------------------------------------------------------------------
# The batched call
# --------------------------------------------------------------------------------------------


async def _llm_matches(entries: Sequence[PlanEntry], ballots: Mapping[str, Sequence[MetaStyle]],
                       topics: Mapping[str, TrendItem], cfg: Config,
                       llm: StructuredCall) -> list[Mapping[str, Any]]:
    """One call, one answer list. Raises `_MatchUnavailable` on anything that is not usable."""
    system = _system_prompt(entries, ballots, topics, cfg)
    result = await llm(
        MATCH_ROLE,
        [{"role": "system", "content": system}, {"role": "user", "content": _CARRIER_TURN}],
        _answer_schema(),
        None,  # text-only: no slide is read here, and reading one would be FR-306's job
    )
    if result.degraded:
        raise _MatchUnavailable(f"the match call degraded ({result.reason or 'no reason'})")
    if not isinstance(result.parsed, Mapping):
        raise _MatchUnavailable("the answer was not a JSON object")
    if not isinstance(rows := result.parsed.get("matches"), list):
        raise _MatchUnavailable("the answer carried no `matches` list")
    return [row for row in rows if isinstance(row, Mapping)]


def _system_prompt(entries: Sequence[PlanEntry], ballots: Mapping[str, Sequence[MetaStyle]],
                   topics: Mapping[str, TrendItem], cfg: Config) -> str:
    """The rendered `style_match_system.md`: the style vocabulary, then the per-entry ballots.

    Assembly goes through the ordinary template door for the ordinary reasons — FR-181 hot-loading
    of an edited `prompts/style_match_system.md`, FR-174's `prompts_dir` override, FR-183's
    built-in twin when the file is missing or names a placeholder this role may not resolve, and
    FR-260's refusal to send a half-filled prompt to a metered model. The engine is built per call
    exactly as `topic_filter._system_prompt` builds its own: `match()`'s signature is pinned and a
    match call happens once a run.

    `build_context()` is called with no arguments and the two slots are set on the result, the same
    way the screen sets `{{audience_profile}}`: both names belong to THIS role alone
    (`prompts_engine._ALLOWLIST`), and `build_context` is the cross-role door. The engine only
    substitutes the names its template actually contains, so the empty defaults it returns for
    every other placeholder never reach a prompt.

    Every failure here becomes `_MatchUnavailable`, i.e. the fail-open path: a template we could
    not render is a rotation baseline, never a lost run and never a truncated prompt sent anyway.
    """
    try:
        engine = PromptEngine(override_dirs=[cfg.prompts_dir] if cfg.prompts_dir else [])
        context = build_context()
        context["style_candidates"] = _candidate_block(ballots)
        context["match_entries"] = _entry_block(entries, ballots, topics, cfg)
        return engine.render(MATCH_TEMPLATE, context)
    except Exception as exc:  # noqa: BLE001 — assembly is fail-open by contract (FR-334)
        # The message is carried through, unlike the provider-side catch in `match()`: prompt
        # assembly never touches a key, a header or an environment (FR-261 is structural), so the
        # worst thing in here is a template path and a placeholder name — which is exactly what
        # the operator needs to fix it. D30's redaction concern is about payloads, not paths.
        raise _MatchUnavailable(
            f"the match prompt could not be assembled ({type(exc).__name__}: {exc})") from exc


def _candidate_block(ballots: Mapping[str, Sequence[MetaStyle]]) -> str:
    """`{{style_candidates}}` — every style ANY entry may wear, described once.

    The vocabulary, not the ballot (the template says so out loud): a style is described here once
    however many creatives could take it, and the keys an entry may actually be given are listed
    inside its own section. Order is registry FILE order, deduplicated by key, so two runs of one
    config send the same block and a diff of two prompts shows a registry edit rather than a
    dictionary's iteration order.

    Each style contributes its key, the formats it can actually take, and `styles.match_profile_for`
    — the ONE answer to "what does this style suit", authored or derived from `render_prompt`'s
    first sentence. Nothing else: palettes, layout zones and exclusions describe how a style LOOKS,
    which is the render model's question, not this one's, and shipping them would multiply the
    prompt by the size of the registry.

    The formats line runs through `fmt_affine` rather than printing `format_affinity` raw, so a
    `carousel_role: slides_only` style does not advertise a carousel it can never anchor. Otherwise
    the vocabulary block would contradict the ballots — a key claiming `carousel` while appearing
    on no carousel section — and the one thing this prompt cannot afford is a model deciding the
    per-entry list looks like an oversight.
    """
    seen: dict[str, MetaStyle] = {}
    for candidates in ballots.values():
        for style in candidates:
            seen.setdefault(style.key, style)
    blocks = []
    for style in seen.values():
        lines = [f"key: {style.key}"]
        if affine := [fmt for fmt in _FORMATS if fmt_affine(style, fmt)]:
            lines.append(f"formats: {', '.join(affine)}")
        if profile := match_profile_for(style):
            lines.append(f"suits: {profile}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _entry_block(entries: Sequence[PlanEntry], ballots: Mapping[str, Sequence[MetaStyle]],
                 topics: Mapping[str, TrendItem], cfg: Config) -> str:
    """`{{match_entries}}` — one section per creative in scope, opened by `asset_id:`.

    Plan order, so the sections read as the plan reads, and every section carries its own
    `candidates:` line: the per-entry ballot is what the model may answer with, and a style that
    is unusable for this creative must not be reachable by reading the vocabulary block above.
    """
    sections = []
    for entry in sorted(entries, key=lambda item: item.order):
        candidates = ballots.get(entry.asset_id)
        if not candidates:
            continue
        lines = [f"asset_id: {entry.asset_id}",
                 f"format: {entry.creative_format}",
                 f"candidates: {', '.join(style.key for style in candidates)}"]
        lines.extend(_signals(entry, topics.get(entry.trend_key or ""), cfg))
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _signals(entry: PlanEntry, topic: TrendItem | None, cfg: Config) -> list[str]:
    """The §3 signals for one creative — all text, all already in memory, all $0.

    What a look has to fit is the SHAPE of the source material, so this is deliberately a block of
    counts and classifications rather than of source text: how many frames, how many source panels
    stand behind them, and how many characters have to sit on each. Virlo's own `hook_types` /
    `visual_hook_types` / `emotional_tones` are the highest-value rows here and the reason this
    stage is worth a call at all — they are the SOURCE PLATFORM's classification of what these
    posts look like, they cost nothing, and until D56 nothing in the engine read them.

    The two free-text rows (`topic`, `why_it_works`) are clipped hard: they name the subject, which
    is what turns "seven dense panels" into "seven dense panels about model benchmarks". Both are
    third-party strings and both ride inside the template's DATA fence, which the engine's
    `_neutralize` pass keeps them from closing (FR-102).

    Absent values are OMITTED rather than printed empty — the template reads a missing field as
    "unknown" and explicitly refuses to lower `fit` for one, so an empty row would be noise the
    model has to price.
    """
    lines: list[str] = []
    if entry.slide_count:
        lines.append(f"deck_length: {entry.slide_count}")
    if topic is None:
        return lines
    if name := one_line(topic.name, _MAX_TOPIC_CHARS):
        lines.append(f"topic: {name}")
    if topic.strength:
        lines.append(f"strength: {topic.strength:.2f}")
    for label, values in (("hook_types", topic.hook_types),
                          ("visual_hook_types", topic.visual_hook_types),
                          ("emotional_tones", topic.emotional_tones)):
        if row := _labels(values):
            lines.append(f"{label}: {row}")
    if why := one_line(topic.why_it_works, _MAX_WHY_CHARS):
        lines.append(f"why_it_works: {why}")
    if engagement := _engagement(topic.engagement):
        lines.append(f"engagement: {engagement}")
    lines.extend(_post_signals(_bound_post(entry, topic), cfg))
    return lines


def _bound_post(entry: PlanEntry, topic: TrendItem) -> SourcePost | None:
    """The post whose SHAPE this creative is being matched against.

    A carousel binds one specific post at ASSIGN (`plan.assign`, FR-304) and that post's panels
    become our slides one for one, so it is the only honest answer for a deck. Nothing else binds a
    post, so an image or a reel falls back to the topic's view-ranked representative for its own
    reuse index — the same `posts[i % len(posts)]` walk `copywrite` uses on its degrade path, which
    keeps two creatives on one topic from being described by the same post.
    """
    if not topic.posts:
        return None
    if entry.source_post_id:
        for post in topic.posts:
            if post.post_id == entry.source_post_id:
                return post
    return topic.posts[entry.trend_reuse_index % len(topic.posts)]


def _post_signals(post: SourcePost | None, cfg: Config) -> list[str]:
    """The bound post's shape: how many panels, how popular, and how much text per field.

    LENGTHS, never bytes. The words themselves are the copy call's business under the verbatim
    contract (§1.7) and this call is choosing a look — "four panels of ~120 characters each" is
    the entire signal a style needs, it cannot be prompt-injected into a style choice the way a
    caption can, and it keeps one batched prompt small enough to stay cheap on a 20-creative plan.

    `source_panel_count` and `usable_panel_slots` are imported from `plan` for the same reason the
    pool predicates are imported from `styles`: they are the figures ASSIGN already computed to
    bind and price this deck, and a second widest-evidence rule here would eventually disagree
    with the one the deck was actually built on.
    """
    if post is None:
        return []
    lines = [f"is_slideshow: {'yes' if post.is_slideshow else 'no'}"]
    if panels := source_panel_count(post):
        lines.append(f"panel_count: {panels}")
        lines.append(f"usable_panel_slots: {usable_panel_slots(post, cfg)}")
    if post.views:
        lines.append(f"views: {post.views:,}")
    if caption := len(post.caption.strip()):
        lines.append(f"caption_chars: {caption}")
    for label, values in (("hooks_chars", post.hooks),
                          ("text_overlays_chars", post.text_overlays),
                          ("panel_texts_chars", post.panel_texts)):
        if row := _lengths(values):
            lines.append(f"{label}: {row}")
    return lines


def _lengths(values: Sequence[str]) -> str:
    """`"120, 98, 140 (+4 more)"` — per-item character counts, capped, empties included as `0`.

    An empty slot is printed rather than dropped because in `panel_texts` it is INDEX-ALIGNED
    evidence (FR-293): a deck of `140, 0, 130, 0` is a source whose words Virlo only half
    transcribed, which is a different shape from a four-panel deck with words on every slide.
    """
    counts = [len(str(value).strip()) for value in values]
    if not counts:
        return ""
    shown = ", ".join(str(count) for count in counts[:_MAX_LENGTHS])
    extra = len(counts) - _MAX_LENGTHS
    return f"{shown} (+{extra} more)" if extra > 0 else shown


def _labels(values: Sequence[str]) -> str:
    """Virlo's own classification labels, deduplicated in rank order and capped."""
    seen: dict[str, None] = {}
    for value in values:
        if text := one_line(value, _MAX_LABEL_CHARS):
            seen.setdefault(text, None)
    return ", ".join(list(seen)[:_MAX_LABELS])


def _engagement(engagement: Mapping[str, int]) -> str:
    """`"likes 12,400, comments 210"` — the topic's own counters, in config order, capped.

    Context for a human reading the prompt back, and the template says out loud that popularity
    never raises or lowers `fit`. It is here because a style choice reviewed in the log is easier
    to judge beside the numbers the operator already saw on the roster.
    """
    rows = []
    for name, value in list(engagement.items())[:_MAX_LABELS]:
        try:
            rows.append(f"{one_line(str(name), 20)} {int(value):,}")
        except (TypeError, ValueError):
            continue
    return ", ".join(rows)


def _answer_schema() -> dict[str, Any]:
    """The wire shape (FR-335). Hand-built rather than generated from a dataclass: `Match` is this
    module's own RESULT type — it carries `origin`, which the model has no say in — and the answer
    is a list of rows the engine still has to police against each entry's own ballot.

    `style_key` is a plain string and not an enum of the run's keys, deliberately: the valid set is
    PER ENTRY, one JSON Schema cannot express that, and a schema-level union of every entry's pool
    would tell the provider that any run key is acceptable on any row. Validation belongs where the
    ballot is (`_apply`), and a rejected key falls back to the baseline instead of failing the run.
    """
    row = {
        "type": "object",
        "properties": {
            "asset_id": {"type": "string"},
            "style_key": {"type": "string"},
            "fit": {"type": "string", "enum": list(_FITS)},
            "reason": {"type": "string"},
            "wanted_archetype": {"type": "string"},
        },
        "required": ["asset_id", "style_key", "fit", "reason", "wanted_archetype"],
        "additionalProperties": False,
    }
    return {
        "name": "style_matches",
        "schema": {"type": "object", "properties": {"matches": {"type": "array", "items": row}},
                   "required": ["matches"], "additionalProperties": False},
    }


# --------------------------------------------------------------------------------------------
# Merge — asset_id policing, pool validation, the accept/reject fork
# --------------------------------------------------------------------------------------------


def _merge(out: dict[str, Match], rows: Sequence[Mapping[str, Any]],
           ballots: Mapping[str, Sequence[MetaStyle]]) -> None:
    """Fold the model's rows onto the total mapping, in place. Joined on `asset_id` ONLY.

    Three ways a row is discarded, each logged and each leaving that creative on its rotation
    baseline: an id that is not this run's, a second row for an id already answered (neither is
    authoritative, and picking one would make the assignment depend on answer order), and an id
    that was never shown a ballot — a creative the prompt did not contain cannot have been judged,
    so a row naming one is invention.
    """
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        asset_id = str(row.get("asset_id") or "").strip()
        if asset_id not in out:
            logger.warning("style_match: match for unknown asset_id %r ignored — no creative in "
                           "this run carries that id", one_line(str(row.get("asset_id")), 60))
            continue
        grouped.setdefault(asset_id, []).append(row)
    if missing := sorted(set(ballots) - set(grouped)):
        logger.warning("style_match: no match returned for %s — each keeps its rotation style",
                       ", ".join(missing))
    for asset_id, group in grouped.items():
        if len(group) > 1:
            logger.warning("style_match: %d matches returned for %s — none is authoritative, so it "
                           "keeps its rotation style", len(group), asset_id)
            continue
        _apply(out[asset_id], group[0], ballots.get(asset_id, ()))


def _apply(pick: Match, row: Mapping[str, Any], ballot: Sequence[MetaStyle]) -> None:
    """One model row onto one `Match`: the pick is accepted only if BOTH gates open.

    Gate one is the fit — `high` and `medium` accept, `low` and any word outside the three reject.
    Gate two is the ballot — the key has to be one THIS creative was offered, which is what stops
    a `slides_only` style from being matched onto a deck anchor or a HypeLead card onto a
    HypeDigitaly run, whatever the model read in the vocabulary block.

    A rejection is not a failure and is never silent: `wanted_archetype` is preserved (that is the
    gap report), the reason explains which gate closed, and the caller's baseline stands.
    """
    fit = str(row.get("fit") or "").strip().lower()
    key = str(row.get("style_key") or "").strip()
    reason = _clean(row.get("reason"), _MAX_REASON_CHARS)
    wanted = _clean(row.get("wanted_archetype"), _MAX_WANTED_CHARS)
    pick.reason = reason
    if fit not in _FITS:
        logger.warning("style_match: %s answered fit %r — not one of %s, so it keeps its rotation "
                       "style", pick.asset_id, _clean(row.get("fit"), 24), "/".join(_FITS))
        pick.wanted_archetype = wanted
        return
    if fit in _ACCEPTS and key in {style.key for style in ballot}:
        pick.style_key, pick.fit, pick.origin = key, fit, ORIGIN_MATCHED
        if wanted:  # an accepted style has no gap; keeping it would pollute the gap report
            logger.debug("style_match: %s returned wanted_archetype %r on an accepted %s row — "
                         "dropped", pick.asset_id, wanted, fit)
        return
    pick.wanted_archetype = wanted
    if fit == FIT_LOW:
        # The one rejection the model MEANT: it read the ballot and said none of it fits. The fit
        # travels with it, because `rotation · low` is the line that tells an operator this
        # creative wears an arbitrary style and `wanted_archetype` names what to author.
        pick.fit = FIT_LOW
        return
    logger.warning("style_match: %s picked %r, which is not one of its candidates (%s) — it keeps "
                   "its rotation style", pick.asset_id, _clean(key, _MAX_KEY_CHARS),
                   ", ".join(style.key for style in ballot) or "(none offered)")
    # The model's own sentence argued for a style this creative cannot wear, so it would explain
    # the wrong outcome on the receipt. The engine states what actually happened instead.
    pick.reason = _clean(f"picked {_clean(key, _MAX_KEY_CHARS) or '(nothing)'}, which is not a "
                         "candidate for this creative", _MAX_REASON_CHARS)


def _clean(value: Any, limit: int) -> str:
    """A model-authored string, safe to print: no control characters, one line, `limit` chars.

    The sanitizing boundary for everything this module hands back. `reason` and `wanted_archetype`
    are written by a model and read by a person in three places — the ASSIGN receipt, `meta.yaml`
    and a gallery card — so they are cleaned ONCE, here, rather than by each of the three.

    Control characters go first and by substitution: `util.fit` collapses whitespace but leaves
    `\\x1b` intact, and an ESC run reaching a console is an ANSI sequence that is executed rather
    than read. `util.fit` then does the rest — whitespace collapse, a word-boundary cut and the
    `…` marker — so a clipped style reason looks like every other clipped line in this codebase.
    """
    return one_line(_CONTROL.sub(" ", str(value or "")), limit)


__all__ = ["DEGRADED_MARKER", "FIT_HIGH", "FIT_LOW", "FIT_MEDIUM", "MATCH_ROLE", "MATCH_TEMPLATE",
           "ORIGIN_FALLBACK", "ORIGIN_MATCHED", "ORIGIN_ROTATION", "Match", "match"]
