"""Copywriting — the model SELECTS, the engine RESOLVES (§1.7 verbatim contract, FR-99–101, 146).

Module contract
---------------
Purpose: turn plan entries into `CopySet`s. One grouped call per (topic × language) writes every
creative's copy at once; a failed group splits into per-creative calls; a creative whose own call
also failed ships with the top post's caption verbatim and NO on-image text.

Post-pivot (v2.0.0) the words on a creative are **the source's own words, byte for byte**. That is
the exact opposite of the pre-pivot A20 mandate, and the reversal is deliberate (operator decision
2026-08-12): what we are reusing is a winning post's phrasing in its own language, not a
competitor's brand. The mechanism is what makes it safe, and it is structural rather than
prompt-level:

1. **The engine numbers offerable candidates.** Every string on the creative's assigned
   `SourcePost` that this engine is *willing to render* is labelled `P<n>.<kind>[.<i>]` and shown
   to the model with the slots it fits, panels first (FR-100/FR-302). On-image candidates are
   pre-filtered against the style's own `max_onimage_chars` (intersected with the config budgets)
   and must be @handle-free and URL-free; every kind but `panel` must additionally be emoji-free,
   newline-free and hashtag-free, while a `panel` offered to the SLIDE slot keeps all three
   (§0.14b — that is the source deck's own voice, and our slide *is* their slide). Caption
   candidates keep emoji and inline hashtags, their TRAILING hashtag run is extracted into
   `hashtags[]` instead of being offered as pixels, and what is left has to be a caption at all:
   under 25 non-hashtag characters it is hashtag spam, not copy, and the creative takes the
   assembled caption instead (§0.7).
2. **The model returns REFERENCES** (`CopySelection`: `headline_ref`, `subline_ref`,
   `overlay_ref`, `slide_refs`, `caption_ref`) plus free text only where nothing becomes pixels —
   `through_line`, `narrative_arc`, `motion_beat`.
3. **The engine resolves references to bytes.** Verbatim cannot fail: nothing is retyped, no
   language is detected, no accent is lost and nothing is trimmed, because an over-budget string
   was never offered. `_apply_budgets` is BYPASSED for every ref-resolved field — trimming a
   quoted string is precisely how byte identity dies.
4. **A bound carousel's slides are not selected at all (FR-304).** When the plan bound a slideshow
   post to the entry, source panel *i* becomes our slide *i*, verbatim and position-preserving,
   with no model in the loop: an empty or unusable panel keeps its index and yields an empty slide
   text (that slide renders wordless) rather than closing the gap and shipping the deck with two
   slides silently swapped. The model still chooses that deck's cover headline, its caption and
   its hashtags.

Public API:
    await write_copy(entries, trends=..., styles=..., call=..., engine=...) -> CopyResult
    CopyResult(copy, tags, provenance) — `.degraded` / `.trimmed` are views over `tags`
    CopyProvenance(post_id, refs) — FR-298's `copy_source_post_id` / `copy_source_refs`
    COPY_ROLE

Invariants:
- **Selection is structural, never a promise.** No path exists from a model's free text to
  `headline`, `subline`, `overlay_text`, `slide_texts` or `caption` on a verbatim creative: those
  five are assigned from the candidate table or left empty. A ref naming a string we did not
  offer (wrong post, wrong slot, unknown label) is logged and dropped, never approximated.
- **Which post a creative quotes is decided at ASSIGN, not here (FR-304/FR-307, D46 §0.10).**
  `entry.source_post_id` names it, the plan chose it from the topic's FRESH posts, and this module
  looks it up by id and offers that post's strings ALONE — so two creatives on one topic can never
  ship the same caption and neither can re-quote a post an earlier run already used. The model
  chooses which string of that post to use, never which post. A bound post that arrives BURNT (or
  that the topic no longer carries) is refused outright rather than quietly swapped for a
  neighbour: swapping would make `copy_source_post_id`, `trend_history` and the panel map all
  disagree about what shipped. The `posts[trend_reuse_index % len(posts)]` rotation survives ONLY
  for unbound legacy entries and is deprecated — a rotation over a list cannot know which of its
  members are burnt, which is exactly how the first paid run re-quoted a 2023 post.
- **Degrade has two distinct shapes.** No candidate fits the style's budget → `no_onimage_text`
  and a caption-only creative (the call succeeded; there was simply nothing short enough). The
  copy call failing outright → `_fallback_copy`: the top post's caption verbatim, no on-image
  text, `copy_degraded` AND `no_onimage_text`, and `copy_degraded` still counts as an FR-248
  `llm_starved` loss.
- **Grouping never widens the blast radius (FR-99, 10 §10).** Group call fails → one call per
  creative, one attempt each, concurrent. Per-creative call fails → the deterministic tier above.
- **Strips are fail-closed and asymmetric (§1.5, M15).** `branding.competitors` (layer 1) is
  applied UNGUARDED — a configured competitor that happens to be the topic's own name is still
  removed. The filter's LLM-proposed `brands_to_strip` reach this module already screened by
  `topic_filter.screen`'s M15 guards. Stripping happens at candidate-build time, so the bytes we
  offer are the bytes we ship, and the creative is tagged `competitor_stripped`.
- **The verifier is an audit, not a gate (A20 polarity flip).** Every shipped string is checked as
  a byte-substring of its post's (stripped) fields and against the blocklist; a deviation logs and
  tags `copy_not_verbatim` and the creative ships anyway. The creative is already paid for; the
  operator needs to know which card to distrust, not to be handed fewer cards.
- **Free text survives exactly where there is nothing to quote (§1.7.5).** Override briefs and
  post-less topics take the legacy free-text schema, `config.languages` applies to them, and
  FR-101's word-boundary trim applies to them — they are the only creatives `_apply_budgets`
  still touches.

Do not: call the LLM directly, retype a source string anywhere in this module, trim a ref-resolved
field, invent hashtags on the verbatim path, let a creative quote a post it was not assigned, or
re-implement the blocklist mechanics that `topic_filter.apply_blocklist` owns.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hypesocials.config import TextBudgets
from hypesocials.models import (
    Brief,
    CopySelection,
    CopySet,
    DegradationTag,
    MetaStyle,
    PlanEntry,
    SourcePost,
    StructuredCall,
    TrendItem,
)
from hypesocials.prompts_engine import (
    PromptEngine,
    build_context,
    json_schema_for,
    trim_words,
)
from hypesocials.topic_filter import apply_blocklist
from hypesocials.util import slugify

logger = logging.getLogger(__name__)

#: `models.copy` / `max_tokens.copy` / `reasoning_effort` — the role name config already uses.
COPY_ROLE = "copy"
_CARRIER_TURN = "Return the selection JSON for the creatives listed above now."

#: Which slots a format actually renders — a reel has no subline, an image has no slides. Offering
#: a candidate for a slot this creative cannot render wastes prompt space and invites a ref that
#: resolves into a field nothing reads.
_FORMAT_SLOTS: dict[str, tuple[str, ...]] = {
    "image": ("headline", "subline"),
    "carousel": ("headline", "slide"),
    "reel": ("overlay",),
}
_ALL_SLOTS = ("headline", "subline", "slide", "overlay")

#: Ref-label grammar (FR-302), pinned: `P<n>.<kind>[.<i>]`, 1-based everywhere. `caption` is a
#: scalar field and carries no index; a `panel` index is a SOURCE SLIDE POSITION (FR-304).
#:
#: **`description` is not in the grammar at all (FR-303, v2.1.0).** It used to be — as a
#: caption-only kind — and the first paid run captioned a creative with it: Virlo's AI summary,
#: shipped as though a human had written it. Removing it from the length filter alone would have
#: left the label parseable and the field numbered, so it is removed HERE, at the grammar: nothing
#: can name it, `_KIND_FIELDS` cannot resolve it, and `_numbered_fields` never sees it. The field
#: stays legitimate FENCED CONTEXT in the prompt (`{{trend_texts}}`, built by `prompts_engine`)
#: and it is still ledgered in `virlo_fields` — it simply can never become a pixel or a caption.
_REF = re.compile(r"^\s*[`\"']?\s*P(\d+)\.(hook|overlay|panel|caption)"
                  r"(?:\.(\d+))?\s*[`\"']?\s*$", re.IGNORECASE)
#: `kind` -> the `SourcePost` attribute it numbers. Scalar kinds map to a str, list kinds to a
#: list, and nothing outside this table is quotable — the grammar and the model are one contract.
#: `panel` names `panel_texts`, but its VALUES may arrive merged with the vision transcription of
#: the same slides (`sources/slide_intel`, FR-306) — see `write_copy(merged_panels=...)`.
_KIND_FIELDS = {"hook": "hooks", "overlay": "text_overlays", "panel": "panel_texts",
                "caption": "caption"}
#: The one kind a caption may be quoted from (FR-303 took the second away). Hooks and panel texts
#: are on-image material: they are written to be read in one glance, and a three-word hook makes a
#: poor caption.
_CAPTION_KINDS = ("caption",)
#: D46 §0.7 — the floor a source caption must clear to BE this creative's caption. Six of the eight
#: creatives in the first paid run were captioned with a hashtag run and three words; measured
#: after the trailing run is peeled and after every remaining `#tag` token is discounted, a caption
#: under this many characters is spam rather than copy, and the creative takes the assembled
#: caption (topic name + the standing niche line) instead. Operator-settled, 2026-08-13.
_CAPTION_MIN_CHARS = 25

# ---------------------------------------------------------------------------------------------
# On-image pre-filters (§1.7.1, F23, relaxed for panels by D46 §0.14b). A string that fails one of
# these can never fill the slot it failed for, whatever its length: emoji and @handles render as
# garbage or as an accidental mention, URLs invite a hallucinated hyperlink, and a hashtag in the
# frame is a caption artefact that has no business inside the artwork. Captions keep all four.
#
# The ONE relaxation: a `panel` candidate filling the SLIDE slot keeps emoji, newlines and
# `#`-tokens. Those three are not defects there — they are the source deck's own typography, and
# our slide *i* is a re-rendering of their slide *i* (FR-304). Rejecting them would have left the
# panel-mapped deck with a wordless slide wherever the creator used an emoji, which is the same
# empty frame D46 exists to fix. @handles and URLs stay excluded on every slot and every kind:
# they leak an identity or a link rather than a voice.
# ---------------------------------------------------------------------------------------------

#: Pictographs (1F000–1FAFF), dingbats/misc symbols (2600–27BF), the arrow-and-symbol block
#: (2B00–2BFF), the emoji variation selector and the zero-width joiner. Written as escapes rather
#: than as literal glyphs so an editor cannot normalise one away by accident, and deliberately NOT
#: covering `—`, `…` or `·`: those are ordinary punctuation in a Czech or German hook and must
#: stay quotable.
_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff\ufe0f\u200d\u2122]")
_HANDLE = re.compile(r"(?<!\w)@[\w.]")
_HASHTAG = re.compile(r"(?<!\w)#\w")
_URL = re.compile(
    r"(?i)(?:https?://|www\.)\S+"
    r"|(?<![\w@])[\w-]+\.(?:com|net|org|io|ai|app|co|cz|sk|de|eu|me|tv)(?:/\S*)?(?!\w)")
#: One trailing `#tag` at the very end of a caption, with the whitespace before it. Applied
#: repeatedly, this peels the whole trailing run off and leaves the caption body untouched.
_TRAILING_TAG = re.compile(r"(?:\s|^)(#[^\s#]+)\s*$")
#: Any hashtag token anywhere, for MEASURING a caption's substance (§0.7). Deliberately not the
#: same expression as `_TRAILING_TAG`: an inline `#ai` stays in the caption we ship (it is part of
#: the author's sentence) but it is not what makes the sentence a caption, so it does not count
#: towards the floor.
_HASHTAG_TOKEN = re.compile(r"(?<!\w)#\S+")

#: How much of a candidate is shown in the prompt. The model only needs enough to CHOOSE; the
#: engine ships the original bytes from `SourcePost`, so a display truncation costs nothing.
_DISPLAY_CHARS = 400
#: How far an offer will PAD a panel list out to the post's declared `panel_count` (§0.14a keeps
#: slot *i* at index *i*, so the padding is what preserves the alignment when Virlo shipped fewer
#: texts than slides). A fence, not a policy: `panel_count` is a source-controlled integer, no
#: platform's deck comes near this, and slots past it would be empty strings by definition. Real
#: panel TEXTS are never dropped by it — only invented empty slots are.
_MAX_PANEL_SLOTS = 60

#: Why an offer refused to quote its post at all — both are FR-307/§0.10 belt-and-braces behind the
#: fetch gate, and both leave the creative with the assembled caption and a wordless frame.
_REFUSED_BURNT = "no_fresh_post_available"  # FR-73's vocabulary, verbatim
_REFUSED_MISSING = "bound_post_missing"


@dataclass(slots=True)
class CopyProvenance:
    """FR-298 — WHICH post and WHICH string every field of a creative's copy came from.

    `refs` is `{slot: ref-label}` keyed by the `CopySet` field the label resolved into —
    `headline`, `subline`, `overlay_text`, `slide_1`…`slide_N`, `caption` — so meta.yaml records
    the string, not merely the post. Empty on a free-text creative (an override brief quotes
    nothing), and caption-only on the `_fallback_copy` path.

    `panel_map` and `source_panel_count` are FR-304's half of the same receipt, and they are what
    `AssetRecord.panel_map` / `AssetRecord.source_panel_count` are built from
    (`generate.__init__._record()`, which joins each row's `visual_brief` and `source_image` in
    from the slide-intelligence result before writing meta.yaml). One row per OUR slide, in slide
    order, INCLUDING the slides whose source panel was empty, unusable or over budget:

        {"slide": 3, "source_position": 3, "source_text": "", "ref_label": ""}

    The row is the alignment. A deck that dropped its empty rows would tell the gallery that our
    slide 3 came from their slide 4, which is the precise failure FR-304 is written against.
    """

    post_id: str = ""
    refs: dict[str, str] = field(default_factory=dict)
    panel_map: list[dict[str, Any]] = field(default_factory=list)
    source_panel_count: int = 0


@dataclass(slots=True)
class CopyResult:
    """Every creative's copy, the degradations the caller must tag (FR-73), and its provenance.

    `tags` is the ONE degradation carrier — `asset_id -> the tags this creative earned in the copy
    stage` — so a new copy-side degradation needs no new field here, no new field on
    `generate.Env` and no new branch in the meta writer. `degraded` and `trimmed` are read-only
    VIEWS over it rather than parallel state: FR-99 and FR-101 are the questions callers actually
    ask, and answering them from the same dictionary is what stops the two spellings drifting.

    `provenance` is the second carrier, added by FR-298: `asset_id -> CopyProvenance`. It is a
    separate mapping rather than fields on `CopySet` because `CopySet` is the RESOLVED-BYTES shape
    that render prompts read, and a label like `P1.hook.2` must never be able to reach a prompt.
    """

    copy: dict[str, CopySet] = field(default_factory=dict)
    tags: dict[str, tuple[DegradationTag, ...]] = field(default_factory=dict)
    provenance: dict[str, CopyProvenance] = field(default_factory=dict)

    @property
    def degraded(self) -> frozenset[str]:
        """FR-99 — asset ids whose copy fell back to the no-call tier (`copy_degraded`)."""
        return self._tagged(DegradationTag.COPY_DEGRADED)

    @property
    def trimmed(self) -> frozenset[str]:
        """FR-101 — asset ids whose FREE-TEXT copy was cut to budget (`text_trimmed`).

        Never a verbatim creative: a quoted string that did not fit was never offered, so there is
        nothing left to trim by the time the bytes exist.
        """
        return self._tagged(DegradationTag.TEXT_TRIMMED)

    def _tagged(self, tag: DegradationTag) -> frozenset[str]:
        return frozenset(asset_id for asset_id, tags in self.tags.items() if tag in tags)


async def write_copy(
    entries: Sequence[PlanEntry],
    *,
    trends: Mapping[str, TrendItem] | None = None,
    styles: Mapping[str, MetaStyle] | None = None,
    campaign_briefs: Mapping[str, Brief] | None = None,
    call: StructuredCall,
    engine: PromptEngine,
    text_budgets: TextBudgets | None = None,
    conventions: Mapping[str, Mapping[str, str]] | None = None,
    onimage_languages: Mapping[str, str] | None = None,
    niche_descriptor: str = "",
    brand_context: str = "",
    competitors: Sequence[str] = (),
    strip_brands: Mapping[str, Sequence[str]] | None = None,
    merged_panels: Mapping[str, Sequence[str]] | None = None,
    burnt_post_ids: Sequence[str] = (),
    progress: dict[str, int] | None = None,
    log: Any = None,
) -> CopyResult:
    """Copy for every entry, one grouped call per (topic × language), all groups concurrent.

    Args:
        entries: the plan entries needing copy (trimmed/skipped ones excluded by the caller).
        trends: `trend_key -> TrendItem`. Post-pivot these are TOPIC items and their `posts` are
            the only quotable material (§1.6); a topic with no posts falls to the free-text path.
        styles: `style_key -> MetaStyle`, the registry view. Supplies `max_onimage_chars`, which
            is what decides whether a source string is offerable at all. A missing style leaves
            the config budgets in force on their own.
        campaign_briefs: `brief_name -> Brief` for FR-146's directive-driven copy.
        call: `llm.structured_call` (`models.StructuredCall`).
        engine: the run's `PromptEngine`; supplies `copywriter_system.md`.
        text_budgets: FR-101 ceilings, intersected with each style's own (the tighter wins).
        conventions: `platform -> {tone/length/hashtags}` from config (FR-15, guidance only).
        onimage_languages: `asset_id -> language`, FREE-TEXT creatives only. A verbatim creative's
            language follows the string it quotes and is never chosen by us (§1.7.5).
        brand_context: Notion brand text; reaches the copywriter only (FR-109).
        competitors: `config.branding.competitors` — layer 1 of §1.5, deterministic and
            FAIL-CLOSED. Applied to every candidate UNGUARDED by M15 (a competitor that is the
            topic's own name is still stripped) and re-checked by the verifier afterwards.
        strip_brands: `trend_key -> brands_to_strip`, the topic filter's `strip` verdicts. These
            have ALREADY passed `topic_filter.screen`'s M15 guards; this module applies them, it
            never re-judges them.
        merged_panels: `post_id -> the post's per-slide on-image words, index-aligned`, the
            MERGED list `sources.slide_intel` produces (`SlideIntel.panel_texts`: Virlo's own
            `panel_texts[i]` where it has one, the vision transcription of slide *i* where it does
            not, FR-306/§0.11). Keyed by post rather than by asset id on purpose — the merge is a
            property of the SOURCE DECK, two sibling creatives bound to one post must see one
            reading of it, and the caller already holds `{post_id: SlideIntel}`. Omitted or absent
            for a post, the offer falls back to `SourcePost.panel_texts` as shipped by Virlo; the
            list is padded to the post's `panel_count` either way, because slot *i* IS source slide
            *i* (§0.14a) and a compacted list would re-map the deck. These strings go through the
            same competitor strip as every other candidate (§0.12).
        burnt_post_ids: post ids this run may not quote — the used-post set the fetch gate already
            filtered on (FR-305/FR-307). Belt-and-braces, and deliberately redundant: an entry
            whose bound post turns up here is refused outright (assembled caption, wordless frame,
            `reason="no_fresh_post_available"` in the log) rather than re-pointed at a neighbour,
            because the alternative is a creative whose provenance, history record and panel map
            all name different posts.
        progress: OPTIONAL live tally for FR-299's COPY heartbeat — this function keeps
            `{"total", "done", "in_flight"}` current while the group calls run and never reads
            it back. The runner's silence-breaker prints from it; `None` costs nothing.

    Returns:
        `CopyResult`. Every entry has a `CopySet`; `tags` (with its `degraded`/`trimmed` views)
        carries every loss, and `provenance` carries FR-298's per-slot ref labels for meta.yaml.
    """
    run = _Run(call=call, engine=engine, budgets=text_budgets or TextBudgets(),
               styles=styles or {}, conventions=conventions or {},
               onimage_languages=onimage_languages or {}, niche_descriptor=niche_descriptor,
               brand_context=brand_context, competitors=tuple(competitors),
               strip_brands=strip_brands or {}, merged_panels=merged_panels or {},
               burnt_posts=frozenset(str(post_id) for post_id in burnt_post_ids
                                     if str(post_id).strip()), log=log)
    groups = _build_groups(entries, trends or {}, campaign_briefs or {})

    async def _tracked(group: _Group) -> Any:
        if progress is not None:
            progress["in_flight"] = progress.get("in_flight", 0) + 1
        try:
            return await _write_group(group, run)
        finally:
            if progress is not None:
                progress["in_flight"] -= 1
                progress["done"] = progress.get("done", 0) + 1

    if progress is not None:
        progress.update(total=len(groups), done=0, in_flight=0)
    outcomes = await asyncio.gather(*(_tracked(group) for group in groups))
    result = CopyResult()
    for copies, tags, provenance in outcomes:
        result.copy.update(copies)
        result.tags.update(tags)
        result.provenance.update(provenance)
    return result


# --------------------------------------------------------------------------------------------
# Grouping — (topic × language), one line per creative
# --------------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Run:
    """Everything constant across this run's copy calls — threaded once instead of per call."""

    call: StructuredCall
    engine: PromptEngine
    budgets: TextBudgets
    styles: Mapping[str, MetaStyle]
    conventions: Mapping[str, Mapping[str, str]]
    onimage_languages: Mapping[str, str]
    niche_descriptor: str
    brand_context: str
    competitors: tuple[str, ...]  # §1.5 layer 1 — deterministic, fail-closed, unguarded
    strip_brands: Mapping[str, Sequence[str]]  # trend_key -> the filter's post-guard survivors
    # The last three carry defaults so a caller that has none of them — a test, a preview path —
    # constructs the run without inventing empties. `write_copy` always passes all three.
    merged_panels: Mapping[str, Sequence[str]] = field(default_factory=dict)  # post_id -> merged
    #   per-slide texts, Virlo ∪ vision (FR-306)
    burnt_posts: frozenset[str] = frozenset()  # post ids an earlier run already quoted (FR-307)
    log: Any = None


@dataclass(slots=True)
class _Group:
    """One copy call's scope: the creatives of one topic (or one override brief) in one language.

    A/B pairing is dead (v2.0.0), so there is one line per ENTRY here — no pair representative and
    no cloning of one `CopySet` across siblings. Two creatives on one topic are two different
    quotes of two different posts, which is what `PlanEntry.source_post_id` binds at ASSIGN.
    """

    trend: TrendItem | None
    campaign_brief: Brief | None
    entries: list[PlanEntry] = field(default_factory=list)


def _build_groups(
    entries: Sequence[PlanEntry],
    trends: Mapping[str, TrendItem],
    campaign_briefs: Mapping[str, Brief],
) -> list[_Group]:
    """FR-99 grouping. Override briefs have no topic, so they group by brief × language."""
    groups: dict[tuple[str, str], _Group] = {}
    for entry in sorted(entries, key=lambda e: e.order):
        subject = entry.trend_key or (
            f"brief/{entry.brief_name}" if entry.brief_name else entry.asset_id)
        key = (subject, entry.language)
        group = groups.get(key)
        if group is None:
            group = _Group(trend=trends.get(entry.trend_key or ""),
                           campaign_brief=campaign_briefs.get(entry.brief_name or ""))
            groups[key] = group
        group.entries.append(entry)
    return list(groups.values())


# --------------------------------------------------------------------------------------------
# Candidates — the offerable strings, numbered (§1.7.1)
# --------------------------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class _Candidate:
    """One offerable source string: its label, the bytes we would ship, and where they may go."""

    label: str  # `P<n>.<kind>[.<i>]` — the FR-298 provenance label, 1-based over ranked posts
    text: str  # POST-strip bytes: exactly what lands in the `CopySet`, never re-derived later
    kind: str
    stripped: bool  # a competitor name was removed on the way here (`competitor_stripped`)
    slots: tuple[str, ...] = ()  # on-image slots whose budget this text fits, ordered
    hashtags: tuple[str, ...] = ()  # the caption's trailing run, extracted (§1.7.1)


@dataclass(slots=True)
class _Offer:
    """The candidate table for ONE creative — its bound post and nothing else (FR-304/§1.7.6)."""

    post: SourcePost | None = None
    post_ordinal: int = 0  # 1-based, as it appears in the ref labels
    onimage: list[_Candidate] = field(default_factory=list)
    captions: list[_Candidate] = field(default_factory=list)
    budgets: dict[str, int] = field(default_factory=dict)  # slot -> characters, style ∩ config
    haystack: tuple[str, ...] = ()  # every stripped source field — the verifier's substring pool
    #: The post's per-slide words AFTER the strip, INDEX-ALIGNED to its `panel_count`: slot *i - 1*
    #: is source slide *i*, and an empty string is a real empty slot rather than a missing one
    #: (§0.14a). This is what FR-304's deterministic mapping walks — the candidate list above
    #: cannot serve, because it drops the empty slots and the gaps are the alignment.
    panels: tuple[str, ...] = ()
    stripped_panels: frozenset[int] = frozenset()  # 1-based positions a competitor was cut from
    #: True when this post came from `entry.source_post_id` (the plan bound it at ASSIGN) rather
    #: than from the deprecated modulo rotation. FR-304's panel mapping applies to bound decks
    #: alone: an unbound carousel has no promise that this post's slides are the deck's slides.
    bound: bool = False
    #: Set when the post may not be quoted at all — `_REFUSED_BURNT` / `_REFUSED_MISSING`. The
    #: creative still ships (it is already planned and about to be paid for); it ships the
    #: assembled caption and a wordless frame, and it is never sent to the model.
    refused: str = ""

    @property
    def by_label(self) -> dict[str, _Candidate]:
        """Label -> the ON-IMAGE candidate. Captions are looked up separately and on purpose.

        One source string can appear in both tables under one label — a short, clean caption is
        offerable as a headline AND as the caption — but with DIFFERENT bytes: the caption entry
        has had its trailing hashtag run peeled off. Merging the two here would let a headline
        resolve to the caption's shortened body (or worse, to a candidate carrying no slots at
        all, which reads as "over budget"), so the two tables never mix.
        """
        return {c.label: c for c in self.onimage}


def _offer_for(entry: PlanEntry, group: _Group, run: _Run) -> _Offer:
    """Number this creative's offerable strings — its bound post's, pre-filtered per slot.

    **Which post (FR-304/FR-307, D46 §0.10).** `entry.source_post_id` names it and `plan.assign`
    chose it from the topic's FRESH posts; this function looks it up by id among the topic's posts
    and offers that post ALONE. The old `posts[trend_reuse_index % len(posts)]` rotation survives
    only for entries nothing bound (images, reels, anything built before ASSIGN ran) and is
    DEPRECATED: a modulo over a list has no way to skip the posts an earlier run already spent, so
    a topic with one fresh post re-quoted yesterday's exact post — the defect D46 was written
    against. Labels stay TOPIC-global (`P3.hook.1` means the third-ranked post of the topic,
    whichever creative is looking at it), so FR-298's provenance and the FR-297b console roster
    read the same alphabet.

    Two tables come out of one pass, and a field can land in either, both or neither:
    `_fitting_slots` decides the pixels side on the F23 rules (relaxed for panels, §0.14b) plus
    this creative's own budgets, and the caption side additionally has to survive §0.7's substance
    floor. `panels` is built alongside them and is neither table: it is the index-aligned deck the
    FR-304 mapping walks, empty slots included.
    """
    posts = list(group.trend.posts) if group.trend else []
    if not posts:
        return _Offer()
    index, bound, refusal = _bound_index(entry, posts, run)
    if index is None:
        return _Offer(refused=refusal)
    post = posts[index]
    style = run.styles.get(entry.style_key)
    budgets = _slot_budgets(style, run.budgets)
    slots = _FORMAT_SLOTS.get(str(entry.creative_format), _ALL_SLOTS)
    brands = _strip_terms(entry, run)
    offer = _Offer(post=post, post_ordinal=index + 1, bound=bool(bound),
                   budgets={slot: budgets[slot] for slot in slots if slot in budgets})
    panels = _panel_slots(post, run)
    kept: list[str] = list(panels)  # post-strip, index-aligned — the FR-304 deck
    cut: set[int] = set()
    haystack: list[str] = []
    for kind, raw, ordinal in _numbered_fields(post, panels):
        text, stripped = _apply_strip(raw, brands)
        if kind == "panel":
            kept[ordinal - 1] = text  # empty when the whole panel WAS the brand: a wordless slide
            if stripped:
                cut.add(ordinal)
        if not text.strip():
            continue  # the whole string WAS the brand — there is nothing left to quote
        haystack.append(text)
        label = f"P{offer.post_ordinal}.{kind}" + (f".{ordinal}" if ordinal else "")
        fits = _fitting_slots(text, slots, offer.budgets, kind=kind)
        if fits:
            offer.onimage.append(_Candidate(label, text, kind, stripped, slots=fits))
        if kind in _CAPTION_KINDS:
            body, tags = _split_trailing_hashtags(text)
            if _caption_substance(body) >= _CAPTION_MIN_CHARS:
                offer.captions.append(_Candidate(label, body, kind, stripped, hashtags=tags))
    offer.haystack = tuple(haystack)
    offer.panels = tuple(kept)
    offer.stripped_panels = frozenset(cut)
    return offer


def _bound_index(
    entry: PlanEntry, posts: Sequence[SourcePost], run: _Run
) -> tuple[int | None, bool, str]:
    """`(index into posts, was it BOUND, refusal reason)` — the index is None iff there is a reason.

    Three outcomes, and the two refusals are belt-and-braces behind gates that already ran
    (FR-305 drops used posts before ranking; `plan.assign` binds only fresh ones). They are kept
    because the cost of being wrong here is a creative that quotes a post the operator was told
    they would never see again, and because a second check on a stable id is nearly free:

    - **bound and quotable** — `entry.source_post_id` names one of the topic's posts and that post
      is not burnt. This is the normal post-D46 path.
    - **bound and burnt** — refused with `no_fresh_post_available`. NOT re-pointed at a neighbour:
      a swap would leave `copy_source_post_id`, the panel map and `trend_history` naming three
      different posts, and the operator asked for famine over silent repeats (§0.10).
    - **bound and absent** — the topic no longer carries the post the plan bound (a re-fetch
      between ASSIGN and COPY, a mis-keyed topic). Refused for the same reason: quoting whatever
      else is in the list would silently make the deck someone else's.

    An entry with no binding at all falls back to the deprecated modulo rotation and is reported
    as unbound, so FR-304's panel mapping stays off for it.
    """
    bound_id = str(entry.source_post_id or "").strip()
    if not bound_id:
        index = entry.trend_reuse_index % len(posts)
        if str(posts[index].post_id) in run.burnt_posts:
            _warn(run.log, "copy_post_burnt",
                  f"{entry.asset_id}: the rotation landed on post {posts[index].post_id}, which an "
                  "earlier run already quoted; this creative quotes nothing and ships the "
                  "assembled caption (FR-307)", asset_id=entry.asset_id,
                  post_id=str(posts[index].post_id), reason=_REFUSED_BURNT)
            return None, False, _REFUSED_BURNT
        return index, False, ""
    found = next((i for i, post in enumerate(posts) if str(post.post_id) == bound_id), None)
    if found is None:
        _warn(run.log, "copy_bound_post_missing",
              f"{entry.asset_id}: the plan bound source post {bound_id}, which this topic no "
              "longer carries; this creative quotes nothing rather than quoting a post it was not "
              "assigned, and ships the assembled caption (FR-304)",
              asset_id=entry.asset_id, post_id=bound_id, reason=_REFUSED_MISSING,
              available=[str(post.post_id) for post in posts])
        return None, False, _REFUSED_MISSING
    if bound_id in run.burnt_posts:
        _warn(run.log, "copy_bound_post_burnt",
              f"{entry.asset_id}: the plan bound source post {bound_id}, which an earlier run "
              "already quoted; it is refused rather than re-pointed at another post, and this "
              "creative ships the assembled caption with no on-image text (FR-307/§0.10)",
              asset_id=entry.asset_id, post_id=bound_id, reason=_REFUSED_BURNT)
        return None, False, _REFUSED_BURNT
    return found, True, ""


def _panel_slots(post: SourcePost, run: _Run) -> list[str]:
    """This post's per-slide words, INDEX-ALIGNED to its own deck (§0.14a) — slot *i-1* is slide *i*.

    Prefers the MERGED reading when the caller has one (`write_copy(merged_panels=...)`: Virlo's
    panel text where Virlo had one, the vision transcription of that slide where it did not,
    FR-306). Falls back to `SourcePost.panel_texts` as shipped, which is already index-aligned by
    the adapter.

    The padding is the point: a post that declares eight panels and shipped three texts still has
    eight slides, and slots 4–8 being empty is what tells FR-304's mapping to render those slides
    wordless instead of pulling slide 8's words forward onto slide 4.
    """
    merged = run.merged_panels.get(str(post.post_id))
    values = [str(text or "") for text in (post.panel_texts if merged is None else merged)]
    width = max(len(values), min(_int(post.panel_count), _MAX_PANEL_SLOTS))
    return values + [""] * (width - len(values))


def _numbered_fields(
    post: SourcePost, panels: Sequence[str] | None = None
) -> list[tuple[str, str, int]]:
    """`(kind, raw text, 1-based index or 0)` for every field the ref grammar can name.

    Order is FR-100's offer priority — **panels, then overlays, then hooks, then the caption** —
    and it is a deliberate reversal of the pre-D46 order. The words ON the slides are what the
    first paid run failed to use; putting them first is what the model reads first, and for a
    carousel they are the deck itself. Within `panel` the index is the SOURCE SLIDE POSITION, so
    an empty slot is skipped as a candidate while its neighbours keep their own numbers —
    `enumerate` counts before the blank filter, never after.

    `panels` lets the caller supply the merged Virlo ∪ vision reading of the deck (`_panel_slots`);
    without it the post's own `panel_texts` are numbered.
    """
    out: list[tuple[str, str, int]] = []
    values = list(panels) if panels is not None else [str(text or "")
                                                      for text in post.panel_texts]
    out.extend(("panel", str(value), index)
               for index, value in enumerate(values, start=1) if str(value).strip())
    for kind in ("overlay", "hook"):
        field_values = getattr(post, _KIND_FIELDS[kind], None) or []
        out.extend((kind, str(value), index)
                   for index, value in enumerate(field_values, start=1) if str(value).strip())
    for kind in _CAPTION_KINDS:
        value = str(getattr(post, _KIND_FIELDS[kind], "") or "")
        if value.strip():
            out.append((kind, value, 0))
    return out


def _caption_substance(text: str) -> int:
    """How many characters of `text` are WORDS rather than hashtags — D46 §0.7's measure.

    Every `#tag` token is discounted wherever it sits and the remainder is whitespace-collapsed, so
    `"#ai #saas #growth"` measures 0, `"Read this  #ai"` measures 9, and a caption made of tags and
    an emoji cannot clear the floor by being long. It measures; `_CAPTION_MIN_CHARS` decides.
    """
    return len(" ".join(_HASHTAG_TOKEN.sub(" ", text).split()))


def _slot_budgets(style: MetaStyle | None, budgets: TextBudgets) -> dict[str, int]:
    """The character ceiling actually in force per slot — the TIGHTER of style and config.

    FR-101's config budgets are the run's ceiling; a meta-style's `max_onimage_chars` is what that
    particular layout can hold without the text colliding with its own artwork (§1.3). Neither
    outranks the other, so both apply and the smaller wins — the same `min()` `build_context`
    puts into `{{text_budgets}}` (contracts item 1), stated here in characters because this is
    where it is ENFORCED rather than described.

    A reel's seed-frame hook has no dedicated style key in the registry vocabulary
    (`headline`/`subline`/`slide`), so it borrows `headline`'s if the style names one.
    """
    style_caps = dict(style.max_onimage_chars) if style else {}

    def cap(config_value: int, *keys: str) -> int:
        limits = [config_value]
        limits += [int(style_caps[key]) for key in keys
                   if isinstance(style_caps.get(key), (int, float)) and int(style_caps[key]) > 0]
        return max(1, min(limits))

    return {
        "headline": cap(budgets.image_headline, "headline"),
        "subline": cap(budgets.image_subline, "subline"),
        # A carousel slide's text is NOT a headline any more (D46 §0.5/FR-259): under FR-304 it is
        # a whole source panel, a complete thought written to be read on its own slide, so it has
        # its own config ceiling (`text_budgets.slide`, default 300) instead of borrowing
        # `image_headline`. Borrowing is what made the first paid run's decks wordless — a 42
        # character headline budget cannot hold a real panel, and an over-budget panel is not
        # trimmed, it is simply never offered.
        "slide": cap(budgets.slide, "slide"),
        "overlay": cap(budgets.reel_seed_headline, "overlay", "headline"),
    }


def _fitting_slots(text: str, slots: Sequence[str], budgets: Mapping[str, int],
                   *, kind: str = "") -> tuple[str, ...]:
    """Which of this creative's slots `text` may fill — length plus F23, relaxed per §0.14b.

    Everything here is a REJECTION rule: a string that fails is simply never offered, which is
    what makes the resolution step incapable of trimming, re-spelling or apologising later.

    Two exclusions are absolute on every slot and every kind — an `@handle` renders as somebody
    else's identity and a URL invites a hallucinated hyperlink. The other three (emoji, newlines,
    hashtags) are absolute everywhere EXCEPT a `panel` filling the `slide` slot: that string was
    already on a slide, in a deck people watched to the end, and its emoji is typography rather
    than noise (D46 §0.14b). The same panel offered as a HEADLINE is held to the full rule — a
    headline is our frame's own line, not a re-render of theirs.
    """
    if _HANDLE.search(text) or _URL.search(text):
        return ()
    length = len(text)
    fits = tuple(slot for slot in slots if length <= budgets.get(slot, 0))
    # Measured on the bytes that SHIP, whitespace included — the alternative is to measure a
    # stripped string and then render a longer one, which is how an "in budget" headline overflows
    # its zone. Trimming the whitespace instead is not an option: nothing here edits a quote.
    if not (_EMOJI.search(text) or _HASHTAG.search(text) or "\n" in text.strip()):
        return fits
    return tuple(slot for slot in fits if slot == "slide" and kind == "panel")


def _split_trailing_hashtags(text: str) -> tuple[str, tuple[str, ...]]:
    """`"Body text #a #b"` -> `("Body text", ("#a", "#b"))` — §1.7.1's caption rule.

    Only the TRAILING run moves: a hashtag written mid-sentence is part of the caption's voice and
    stays where its author put it. Both halves remain the source's own bytes, so `caption.txt` and
    the hashtag list are still verbatim and the verifier's substring check holds for each.
    """
    body, tags = text.rstrip(), []
    while (match := _TRAILING_TAG.search(body)):
        tags.append(match.group(1))
        body = body[:match.start()].rstrip()
    return body, tuple(reversed(tags))


def _strip_terms(entry: PlanEntry, run: _Run) -> tuple[str, ...]:
    """Every brand name to remove from this creative's candidates, both §1.5 layers.

    **The asymmetry is deliberate and pinned (conductor decision, Session-B closeout obligation
    3).** Layer 1 — `branding.competitors` — is applied UNGUARDED: a configured competitor that
    happens to BE the topic's name is still stripped, because "the LLM was unavailable" or "the
    name is the subject" must never be the reason a competitor's name ships in our pixels. Layer 2
    — the filter's `brands_to_strip` — arrives having already passed `topic_filter.screen`'s M15
    guards (subject-of-the-sentence, stopwords, product nouns, the <15-char floor), and this
    module applies them as given; re-judging them here would put the guard in two places and let
    the two drift.
    """
    verdict = run.strip_brands.get(entry.trend_key or "", ())
    return (*run.competitors, *(str(brand) for brand in verdict if str(brand).strip()))


def _apply_strip(text: str, brands: Sequence[str]) -> tuple[str, bool]:
    """`(text with every brand removed, whether anything was removed)` — word-boundary, pure.

    The mechanics are `topic_filter.apply_blocklist`'s and are NOT re-implemented here: one
    word-boundary matcher, one whitespace-collapse rule, one case policy. A text that matched
    nothing comes back byte-identical, which is what keeps the verbatim contract intact for the
    overwhelming majority of strings that mention no competitor at all.
    """
    if not text or not brands:
        return text, False
    out = apply_blocklist(text, brands)
    return out, out != text


# --------------------------------------------------------------------------------------------
# Calling
# --------------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Written:
    """One creative's finished copy plus everything the caller needs to judge it.

    `quoted` is the pool the verifier checks membership against — the stripped fields of the post
    this creative actually quoted. It is deliberately NOT `offer.haystack` at the call site,
    because the two disagree on the one path that matters: `_fallback_copy` quotes the TOP post
    (`P1`), not the creative's assigned post, so verifying it against the assigned post's fields
    would report our own successful fallback as a verbatim deviation. Empty means "this creative
    quotes nothing" — a free-text brief — and only the blocklist half of the audit applies.
    """

    copyset: CopySet
    source: CopyProvenance
    tags: list[DegradationTag] = field(default_factory=list)
    quoted: tuple[str, ...] = ()


async def _write_group(
    group: _Group, run: _Run
) -> tuple[dict[str, CopySet], dict[str, tuple[DegradationTag, ...]], dict[str, CopyProvenance]]:
    """One group: grouped call → per-creative split → resolution → fallback tier (FR-99, 10 §10).

    Two call shapes, chosen by whether there is anything to quote:

    - **Verbatim** (the normal post-pivot path): `CopySelection` refs into the numbered candidate
      table, resolved to bytes here.
    - **Free text** (override briefs, and the degenerate topic that arrived with no posts): the
      legacy `CopySet` shape, `config.languages` in force, FR-101's trim applied. §1.7.5 keeps
      exactly these two cases on the configured language; everything else follows its source.

    A creative whose bound post was refused (burnt or absent, FR-307) is in neither shape: it is
    left OUT of the call entirely — there are no candidates to offer and no words to ask for, so
    asking would spend tokens on an answer we would have to discard — and it is written
    deterministically by `_refused` afterwards.
    """
    offers = {entry.asset_id: _offer_for(entry, group, run) for entry in group.entries}
    askable = [entry for entry in group.entries if not offers[entry.asset_id].refused]
    verbatim = any(offers[entry.asset_id].post is not None for entry in askable)
    payloads = await _call_copy(group, askable, run, offers, verbatim) if askable else {}
    if missing := [entry for entry in askable if entry.asset_id not in payloads]:
        _warn(run.log, "copy_group_split",
              f"grouped copy call missed {len(missing)} of {len(askable)} creatives; "
              "splitting into one call each (FR-99)",
              asset_ids=[entry.asset_id for entry in missing])
        for split in await asyncio.gather(*(
                _call_copy(group, [entry], run, offers, verbatim) for entry in missing)):
            payloads.update(split)

    copies: dict[str, CopySet] = {}
    tags: dict[str, tuple[DegradationTag, ...]] = {}
    provenance: dict[str, CopyProvenance] = {}
    for entry in group.entries:
        payload = payloads.get(entry.asset_id)
        offer = offers[entry.asset_id]
        if offer.refused:
            written = _refused(entry, group, run, offer)
        elif payload is None:
            written = _fallback(entry, group.trend, run)
        elif verbatim and offer.post is not None:
            written = _resolve(entry, payload, offer, group, run)
        else:
            written = _free_text(entry, payload, group, run)
        earned = [*written.tags, *_verify(written, entry, run)]
        copies[entry.asset_id] = written.copyset
        provenance[entry.asset_id] = written.source
        if earned:
            tags[entry.asset_id] = tuple(dict.fromkeys(earned))
    return copies, tags, provenance


async def _call_copy(
    group: _Group, entries: Sequence[PlanEntry], run: _Run,
    offers: Mapping[str, _Offer], verbatim: bool,
) -> dict[str, dict[str, Any]]:
    """One Luna call covering `entries`. Returns `{asset_id: payload}` for whatever came back."""
    style = _single_style(entries, run)
    context = build_context(
        trend=group.trend,
        style=style,
        campaign_brief=group.campaign_brief,
        creative_format=entries[0].creative_format if len(entries) == 1 else "",
        niche_descriptor=run.niche_descriptor,
        brand_context=run.brand_context,
        competitor_strings=_strip_terms(entries[0], run),  # M6: one strip pass over the fenced
        platform_conventions=_relevant(run.conventions, entries),  # trend texts as well
        text_budgets=run.budgets,
        sibling_list=_sibling_list(entries, run, offers, verbatim),
    )
    # `{{source_hooks}}` is RE-PURPOSED post-pivot (contracts item 2): the slot that used to carry
    # five exemplar hooks to abstract from now carries the numbered candidate table to CHOOSE
    # from. The numbering is written here rather than in `build_context` on purpose — this module
    # resolves the refs back to bytes, and a second implementation of the same numbering in
    # `prompts_engine` is a divergence waiting to ship the wrong string.
    context["source_hooks"] = _candidate_block(entries, offers) if verbatim else ""
    try:
        system = run.engine.render("copywriter_system.md", context)
    except (ValueError, LookupError) as exc:  # unresolved placeholder / missing template
        _warn(run.log, "copy_prompt_failed", str(exc))
        return {}
    result = await run.call(
        COPY_ROLE,
        [{"role": "system", "content": system}, {"role": "user", "content": _CARRIER_TURN}],
        _selection_schema() if verbatim else _free_text_schema(),
        None,
    )
    if result.degraded or not isinstance(result.parsed, Mapping):
        return {}
    wanted = {entry.asset_id for entry in entries}
    payloads = {}
    for item in result.parsed.get("creatives") or []:
        if isinstance(item, Mapping) and str(item.get("asset_id")) in wanted:
            payloads[str(item["asset_id"])] = dict(item)
    return payloads


def _candidate_block(entries: Sequence[PlanEntry], offers: Mapping[str, _Offer]) -> str:
    """The `{{source_hooks}}` table: one section per creative, its OWN post's strings only.

    Sectioning by creative rather than by post is what makes §1.7.6 enforceable in the prompt as
    well as in the engine — the model is never shown a string it is not allowed to pick, so the
    common failure ("both creatives quoted the best post") cannot be expressed. Labels stay
    topic-global so two sections quoting the same post agree on its number.

    Long candidates are shown truncated and multi-line ones are shown folded, because the model
    only needs enough to CHOOSE: the engine ships the original bytes from `SourcePost`, line
    breaks and all, and says so here so the model does not "fix" what it sees.

    Panels lead the table and are shown as an ORDERED SEQUENCE (FR-100's offer priority), because
    their index is not an arbitrary number — it is the position of that slide in the source deck,
    empty slots included. On a deck whose slides this engine maps itself (FR-304) the sequence is
    shown anyway and labelled as already-assigned: the model needs to see what its cover headline
    and caption are sitting on top of, and telling it the slides are taken is what stops it
    answering `slide_refs` we would then have to discard.
    """
    blocks: list[str] = []
    for entry in entries:
        offer = offers.get(entry.asset_id)
        if offer is None or offer.post is None:
            continue
        budget_line = ", ".join(f"{slot} <= {limit} characters"
                                for slot, limit in offer.budgets.items())
        lines = [f"{entry.asset_id} · {entry.creative_format} · "
                 f"quote ONLY from post P{offer.post_ordinal}"]
        lines.extend(_panel_lines(entry, offer))
        # A mapped deck's panels are shown once, in the sequence above, and are not repeated here
        # as choosable candidates — they are already assigned to their slides.
        shown = [c for c in offer.onimage
                 if not (c.kind == "panel" and _panel_mapped(entry, offer))]
        lines.append(f"  on-image candidates ({budget_line}):")
        if shown:
            lines.extend(f"    {c.label} [fits {', '.join(c.slots)}] {_display(c.text)}"
                         for c in shown)
        elif offer.onimage:
            lines.append("    NONE besides the panels above. Leave headline_ref and subline_ref "
                         "empty; the deck's slides carry this creative's words.")
        else:
            lines.append("    NONE — no string on this post fits this style's on-image budget. "
                         "Leave headline_ref, subline_ref, overlay_ref and slide_refs empty; "
                         "this creative ships caption-only.")
        lines.append("  caption candidates:")
        lines.extend(f"    {c.label} {_display(c.text)}" for c in offer.captions)
        if not offer.captions:
            lines.append("    NONE — leave caption_ref empty; this creative captions itself.")
        blocks.append("\n".join(lines))
    if not blocks:
        return ""
    header = ("Each candidate below is shown on one line and may be shown truncated; the engine "
              "renders the ORIGINAL bytes of the string you name, line breaks and all. Choose by "
              "label only.")
    return f"{header}\n\n" + "\n\n".join(blocks)


def _panel_lines(entry: PlanEntry, offer: _Offer) -> list[str]:
    """The source deck, one line per SOURCE SLIDE POSITION, empty slots included.

    Shown before every other candidate (FR-100) and shown whole rather than as the sparse list of
    offerable panels, because the sequence is the information: `slide 3 — (empty on the source
    deck)` is what makes `P1.panel.4` legible as *their fourth slide* instead of *the third string
    in a list*. Nothing here is a new candidate — the labels are the same ones the on-image table
    would print — so the block costs one line per source slide and buys the position contract.
    """
    if not offer.panels:
        return []
    mapped = _panel_mapped(entry, offer)
    lines = ["  source deck panels, in the source's own slide order"
             + (" — the slides of this carousel are ENGINE-MAPPED from them (our slide i renders "
                "their panel i, verbatim). They are already assigned: leave slide_refs empty."
                if mapped else
                " (index = the source slide's own position). Context: the ones this creative may "
                "quote appear again in the candidate list below, with the slots they fit.")]
    for position, text in enumerate(offer.panels, start=1):
        label = f"P{offer.post_ordinal}.panel.{position}"
        lines.append(f"    {label} {_display(text)}" if text.strip() else
                     f"    {label} (empty on the source deck — that slide renders without text)")
    return lines


def _panel_mapped(entry: PlanEntry, offer: _Offer) -> bool:
    """FR-304: is this creative a deck whose slides the ENGINE assigns from the source's panels?

    Three conditions, all structural. It must be a carousel (nothing else has slides); it must
    have BOUND its source post at ASSIGN (an unbound rotation pick carries no promise that this
    post's deck is our deck); and it must not be an override brief, which binds no source post at
    all and renders from its own directives (§0.14d). A blend brief is NOT exempt — it quotes the
    topic in full and merely carries a message alongside it (FR-146).
    """
    return (str(entry.creative_format) == "carousel" and offer.bound
            and entry.brief_influence != "override" and bool(offer.panels))


def _display(text: str) -> str:
    """One-line, length-capped, quoted rendering of a candidate — display only, never shipped."""
    folded = " ".join(text.split())
    if len(folded) > _DISPLAY_CHARS:
        folded = folded[:_DISPLAY_CHARS].rstrip() + " …[truncated for display]"
    return f'"{folded}"'


def _sibling_list(entries: Sequence[PlanEntry], run: _Run, offers: Mapping[str, _Offer],
                  verbatim: bool) -> str:
    """One line per creative — asset id, platform, format, and the LANGUAGE RULE in force.

    §1.7.5, F22: a verbatim creative's language is a property of the string it quotes, so the line
    says so instead of naming a language we would then be asking the model to translate into.
    `config.languages` still governs the free-text creatives (override briefs and the post-less
    degrade path), and those lines keep the pre-pivot caption/on-image tokens.

    The closing note on a free-text call is load-bearing and is written HERE rather than in the
    template on purpose. `copywriter_system.md` is a reference-selection mandate end to end — "a
    brief never turns this into a writing task", "there is no slot in your answer where invented
    lettering can go" — and for a group with nothing to quote that instruction is exactly wrong.
    `sibling_list` is the one slot this module owns inside that prompt, so the correction rides
    there, and the JSON schema sent alongside it (`_free_text_schema`) already agrees with the
    note. **Conductor: this is a real seam between T2.2 and T2.5** — the clean fix is either a
    brief-candidate section in the template (its `override` paragraph already anticipates one) or
    an explicit ruling that trendless briefs ship caption-only.
    """
    lines = []
    for entry in entries:
        offer = offers.get(entry.asset_id)
        line = f"- {entry.asset_id} · {entry.platform} · {entry.creative_format}"
        if entry.creative_format == "carousel" and entry.slide_count:
            line += f" · {entry.slide_count} slides"
        if verbatim and offer is not None and offer.post is not None:
            line += (f" · quote post P{offer.post_ordinal}"
                     " · caption language: as-selected (source language, never translated)")
            if _panel_mapped(entry, offer):
                line += " · slides engine-mapped from that post's panels (slide_refs unused)"
        else:
            onimage = run.onimage_languages.get(entry.asset_id, entry.language)
            line += f" · caption {entry.language} · on-image {onimage}"
        lines.append(line)
    if not verbatim:
        lines.append(
            "NOTE FOR THIS CALL ONLY: these creatives quote no source post. The candidate block "
            "above is empty and there are no labels to choose, so the answer shape for this call "
            "is the copy fields themselves — caption, hashtags, headline, subline, slide_texts, "
            "overlay_text, through_line, narrative_arc, motion_beat — written in the language "
            "named on each line. The JSON schema sent with this call is that shape; follow it.")
    return "\n".join(lines)


def _single_style(entries: Sequence[PlanEntry], run: _Run) -> MetaStyle | None:
    """The group's style when every creative shares one, else `None`.

    `{{text_budgets}}` is the only style-derived slot the copywriter role allowlists, and a group
    whose creatives carry two different styles has two different ceilings — printing either would
    be a lie. It costs nothing: enforcement is the candidate filter's, per creative, and the
    numbered table already states each creative's own budget.
    """
    keys = {entry.style_key for entry in entries}
    if len(keys) != 1:
        return None
    return run.styles.get(next(iter(keys)))


def _relevant(
    conventions: Mapping[str, Mapping[str, str]] | None, entries: Sequence[PlanEntry]
) -> dict[str, Mapping[str, str]]:
    """Only the platforms in this call — a LinkedIn rule in a TikTok-only call is noise."""
    if not conventions:
        return {}
    platforms = {entry.platform for entry in entries}
    return {name: entry for name, entry in conventions.items() if name in platforms}


def _selection_schema() -> dict[str, Any]:
    """The verbatim call's schema, generated from `CopySelection` (contracts item 10).

    `asset_id` is excluded from the dataclass projection and re-added first by the engine, exactly
    as the pinned contract writes it: the ANSWER fields belong to `CopySelection` and identity
    belongs to the envelope, so a future field on the dataclass reaches the schema automatically
    while the key the engine matches on cannot be renamed by accident.
    """
    fields = json_schema_for(CopySelection, exclude={"asset_id"})["properties"]
    creative = {"type": "object", "properties": {"asset_id": {"type": "string"}, **fields},
                "required": ["asset_id", *fields], "additionalProperties": False}
    return {
        "name": "copy_selection",
        "schema": {"type": "object", "properties": {"creatives": {"type": "array",
                                                                  "items": creative}},
                   "required": ["creatives"], "additionalProperties": False},
    }


def _free_text_schema() -> dict[str, Any]:
    """The override-brief / post-less shape: `CopySet` minus what the engine owns."""
    creative = json_schema_for(CopySet, exclude={"language", "trend_key"})
    return {
        "name": "social_copy",
        "schema": {"type": "object", "properties": {"creatives": {"type": "array",
                                                                  "items": creative}},
                   "required": ["creatives"], "additionalProperties": False},
    }


# --------------------------------------------------------------------------------------------
# Resolution — refs to bytes (§1.7.3)
# --------------------------------------------------------------------------------------------


def _resolve(entry: PlanEntry, payload: Mapping[str, Any], offer: _Offer, group: _Group,
             run: _Run) -> _Written:
    """Turn one `CopySelection` answer into resolved bytes plus its FR-298 provenance.

    Nothing here retypes, translates, re-cases or trims: every rendered string is a `_Candidate`'s
    `text` field, and that field was built once from the `SourcePost` (minus a logged strip). The
    only decisions left are *which* candidate and *what to do when the label is unusable*, and
    both are answered by dropping the field rather than approximating it.

    The deck is the exception, and after D46 it is the normal case: a bound carousel's
    `slide_texts` are not in the answer at all. `_mapped_deck` builds them from the source's own
    panels, position for position, and the model's `slide_refs` — if it sent any — are logged and
    discarded (FR-304).
    """
    refs: dict[str, str] = {}
    tags: list[DegradationTag] = []
    #: Strings this creative ships that are OURS rather than the post's. They join the verifier's
    #: pool so our own successful fallback is not reported as someone else's words gone missing.
    own_words: list[str] = []
    stripped = False

    def pick(raw: Any, slot: str, field_name: str) -> str:
        nonlocal stripped
        candidate = _lookup(raw, slot, offer, entry, run)
        if candidate is None:
            return ""
        refs[field_name] = candidate.label
        stripped = stripped or candidate.stripped
        return candidate.text

    headline = pick(payload.get("headline_ref"), "headline", "headline")
    subline = pick(payload.get("subline_ref"), "subline", "subline")
    overlay = pick(payload.get("overlay_ref"), "overlay", "overlay_text")
    deck = (_mapped_deck(entry, offer, run) if _panel_mapped(entry, offer)
            else _selected_deck(payload, offer, entry, run))
    slides, stripped = deck.texts, stripped or deck.stripped
    refs.update(deck.refs)
    if _panel_mapped(entry, offer) and _strings(payload.get("slide_refs")):
        _warn(run.log, "copy_slide_refs_ignored",
              f"{entry.asset_id}: the model answered with slide references on a deck whose slides "
              "are mapped from the source post's own panels (FR-304); they are discarded and the "
              "mapping stands", asset_id=entry.asset_id,
              refs=_strings(payload.get("slide_refs")))
    caption_candidate = _caption_for(payload.get("caption_ref"), offer, entry, run)
    caption, hashtags = "", []
    if caption_candidate is not None:
        refs["caption"] = caption_candidate.label
        stripped = stripped or caption_candidate.stripped
        caption, hashtags = caption_candidate.text, list(caption_candidate.hashtags)
    else:
        # The bound post carries no caption worth shipping: it is empty, it was entirely a
        # competitor's name, or — the case D46 §0.7 added — what remains after its trailing hashtag
        # run is peeled is under `_CAPTION_MIN_CHARS` non-hashtag characters, which is a tag dump
        # rather than a caption. Our own words are the honest answer, and they are ours, so no
        # verbatim claim is made about them and no provenance label is recorded. (Virlo's own
        # `description` summary is NOT a candidate here any more — FR-303 removed it from the
        # grammar, so a post with nothing but a summary caption reaches exactly this branch.)
        caption = _fallback_caption(_subject_name(entry, group), run.niche_descriptor)
        own_words.append(caption)
        _warn(run.log, "copy_caption_unavailable",
              f"{entry.asset_id}: post P{offer.post_ordinal} offers no caption with at least "
              f"{_CAPTION_MIN_CHARS} non-hashtag characters (§0.7); shipping the topic name and "
              "the standing niche line instead", asset_id=entry.asset_id,
              post_id=offer.post.post_id if offer.post else "")

    copyset = CopySet(
        asset_id=entry.asset_id,
        language=entry.language,
        trend_key=entry.trend_key,
        caption=caption,
        hashtags=hashtags,
        headline=headline,
        subline=subline,
        slide_texts=slides,
        narrative_arc=str(payload.get("narrative_arc") or ""),
        overlay_text=overlay,
        through_line=str(payload.get("through_line") or "") or _subject_name(entry, group),
        motion_beat=str(payload.get("motion_beat") or ""),
    )
    # A mapped deck keeps its empty slots (they ARE the alignment), so "did anything become
    # pixels" is a question about the strings, never about the length of the list.
    if not (headline or subline or overlay or any(text.strip() for text in slides)):
        tags.append(DegradationTag.NO_ONIMAGE_TEXT)
        _warn(run.log, "no_onimage_text",
              f"{entry.asset_id}: no string on post P{offer.post_ordinal} fits this style's "
              "on-image budget; shipping a caption-only creative (§1.7.4)",
              asset_id=entry.asset_id, budgets=dict(offer.budgets),
              offered=len(offer.onimage))
    if stripped:
        tags.append(DegradationTag.COMPETITOR_STRIPPED)
        _warn(run.log, "competitor_stripped",
              f"{entry.asset_id}: a competitor name was removed from this creative's text before "
              "it was offered (§1.5); the copy is still sourced, no longer byte-identical",
              asset_id=entry.asset_id, refs=dict(refs))
    return _Written(
        copyset=copyset,
        source=CopyProvenance(post_id=offer.post.post_id if offer.post else "", refs=refs,
                              panel_map=deck.panel_map,
                              source_panel_count=len(offer.panels)),
        tags=tags,
        quoted=(*offer.haystack, *own_words))


@dataclass(slots=True)
class _PanelDeck:
    """One carousel's finished slide texts, their provenance labels and their FR-304 panel map.

    `texts` is POSITION-INDEXED, not compacted: `texts[i - 1]` is slide *i*, and an empty string
    means that slide renders without text. `refs` carries `slide_<n> -> P<m>.panel.<n>` for the
    slides that really did quote something, and `panel_map` carries one row for EVERY slide,
    quoted or not, because the gallery aligns our slide *i* against their slide *i* (FR-309).
    """

    texts: list[str] = field(default_factory=list)
    refs: dict[str, str] = field(default_factory=dict)
    panel_map: list[dict[str, Any]] = field(default_factory=list)
    stripped: bool = False


def _mapped_deck(entry: PlanEntry, offer: _Offer, run: _Run) -> _PanelDeck:
    """FR-304 — source panel *i* becomes our slide *i*, verbatim, with no model in the loop.

    The deck's LENGTH is the plan's (`entry.slide_count`, fixed at ASSIGN from the source's
    `panel_count` clamped to the platform ceiling, §0.4′) and never this function's: the estimate
    the operator approved was priced on that number, and a copy stage that grew or shrank the deck
    would spend money the Confirm gate never quoted. Positions past the source's own panels — a
    ceiling floor, a short deck — simply render wordless.

    Three ways a panel yields an empty slide, and all three KEEP THEIR POSITION:

    - **empty on the source** — Virlo transcribed nothing and vision filled nothing (§0.14a). The
      slide renders without text; `generate/carousel` draws it as a no-text slide.
    - **unusable** — it carries an @handle or a URL (§0.14b keeps emoji, newlines and `#` for
      exactly this slot, and excludes those two everywhere).
    - **over budget** — longer than the `slide` ceiling in force (style ∩ config). It is NOT
      trimmed. "A string that does not fit was never offered" is the whole verbatim contract
      (FR-100), and trimming a source panel to fit our frame is retyping it by another name.

    All three are warned ONCE per creative, together, because the operator's question is "how much
    of this deck came through" and not "what happened to slide 4".
    """
    limit = offer.budgets.get("slide", 0)
    length = max(0, _int(entry.slide_count)) or len(offer.panels)
    deck, dropped = _PanelDeck(), []
    for position in range(1, length + 1):
        text = offer.panels[position - 1] if position <= len(offer.panels) else ""
        label = f"P{offer.post_ordinal}.panel.{position}"
        usable = bool(text.strip()) and bool(
            _fitting_slots(text, ("slide",), {"slide": limit}, kind="panel"))
        if text.strip() and not usable:
            dropped.append(f"slide {position} ({len(text)} characters, ceiling {limit})")
        deck.texts.append(text if usable else "")
        deck.refs[f"slide_{position}"] = label if usable else ""
        deck.panel_map.append({"slide": position, "source_position": position,
                               "source_text": text if usable else "",
                               "ref_label": label if usable else ""})
        deck.stripped = deck.stripped or (usable and position in offer.stripped_panels)
    deck.refs = {slot: label for slot, label in deck.refs.items() if label}
    if dropped:
        _warn(run.log, "panel_over_budget",
              f"{entry.asset_id}: {len(dropped)} source panel(s) could not be rendered as they "
              f"were written and are never trimmed (FR-100) — {'; '.join(dropped)}. Those slides "
              "render without text and keep their position, so the rest of the deck still lines "
              "up with the source", asset_id=entry.asset_id, slide_budget=limit, slides=dropped)
    return deck


def _selected_deck(payload: Mapping[str, Any], offer: _Offer, entry: PlanEntry,
                   run: _Run) -> _PanelDeck:
    """The pre-D46 path: the model's own `slide_refs`, now POSITION-PRESERVING (FR-302/FR-304).

    Reachable only by a carousel that bound no source post — an override brief with a topic, or an
    entry built before ASSIGN's binding existed. `slide_refs[k]` is slide *k+1* and an unusable
    label leaves that slide wordless instead of pulling slide 3's words onto slide 2. The old
    gap-closing behaviour was defensible while slides were independent quotes; under FR-302's
    position-preserving grammar it is a deck that reads as the source's with two slides swapped.
    """
    deck = _PanelDeck()
    for position, raw in enumerate(_strings(payload.get("slide_refs")), start=1):
        candidate = _lookup(raw, "slide", offer, entry, run)
        deck.texts.append(candidate.text if candidate else "")
        if candidate is not None:
            deck.refs[f"slide_{position}"] = candidate.label
            deck.stripped = deck.stripped or candidate.stripped
    return deck


def _lookup(raw: Any, slot: str, offer: _Offer, entry: PlanEntry, run: _Run) -> _Candidate | None:
    """One ref → the candidate it names, or `None` with a reason in the log.

    Three ways a ref can be unusable, and all three end the same way — the field ships empty:

    - **unparseable or unknown** — the model invented a label. Nothing to resolve.
    - **another post's** — §1.7.6 assigned this creative one post. The label is re-pointed at the
      assigned post when the same kind and index exist there (the model's editorial choice
      survives, the divergence rule holds); otherwise it is dropped.
    - **over budget for this slot** — the string was offered for a different slot, or for none.
      It is NOT trimmed: trimming a quoted string is how byte identity dies (§1.7.3).
    """
    label = str(raw or "").strip()
    if not label:
        return None
    match = _REF.match(label)
    if match is None:
        _warn(run.log, "copy_ref_unparseable",
              f"{entry.asset_id}: {label!r} is not a candidate label (P<n>.<kind>[.<i>]); "
              f"the {slot} ships empty", asset_id=entry.asset_id, ref=label, slot=slot)
        return None
    ordinal, kind, index = int(match.group(1)), match.group(2).lower(), match.group(3)
    canonical = f"P{ordinal}.{kind}" + (f".{int(index)}" if index else "")
    table = offer.by_label
    candidate = table.get(canonical)
    if candidate is None and ordinal != offer.post_ordinal:
        canonical = f"P{offer.post_ordinal}.{kind}" + (f".{int(index)}" if index else "")
        candidate = table.get(canonical)
        _warn(run.log, "copy_ref_out_of_scope",
              f"{entry.asset_id}: {label!r} names post P{ordinal}, which this creative was not "
              f"assigned (§1.7.6 gave it P{offer.post_ordinal}); "
              + (f"re-pointed to {canonical}" if candidate else f"the {slot} ships empty"),
              asset_id=entry.asset_id, ref=label, slot=slot,
              assigned_post=offer.post_ordinal)
    if candidate is None:
        _warn(run.log, "copy_ref_unknown",
              f"{entry.asset_id}: {label!r} was never offered for this creative; the {slot} "
              "ships empty", asset_id=entry.asset_id, ref=label, slot=slot)
        return None
    if slot not in candidate.slots:
        _warn(run.log, "copy_ref_over_budget",
              f"{entry.asset_id}: {canonical} does not fit the {slot} budget "
              f"({offer.budgets.get(slot, 0)} characters) and is never trimmed; the {slot} ships "
              "empty (§1.7.3)", asset_id=entry.asset_id, ref=canonical, slot=slot,
              length=len(candidate.text))
        return None
    return candidate


def _caption_for(raw: Any, offer: _Offer, entry: PlanEntry, run: _Run) -> _Candidate | None:
    """The caption candidate a ref names, else the assigned post's best one.

    A caption is the one field every creative needs — `caption.txt` ships verbatim to the
    publisher (FR-230) — so an unusable `caption_ref` falls back to the first caption candidate of
    the assigned post rather than shipping nothing. That fallback is still a quote of the same
    post, so provenance and the verifier stay honest.
    """
    label = str(raw or "").strip()
    table = {c.label: c for c in offer.captions}
    if label:
        match = _REF.match(label)
        kind = "" if match is None else match.group(2).lower()
        canonical = f"P{offer.post_ordinal}.{kind}" if kind else ""
        if canonical in table:
            if match is not None and int(match.group(1)) != offer.post_ordinal:
                _warn(run.log, "copy_ref_out_of_scope",
                      f"{entry.asset_id}: caption ref {label!r} names a post this creative was "
                      f"not assigned (§1.7.6 gave it P{offer.post_ordinal}); re-pointed to "
                      f"{canonical}", asset_id=entry.asset_id, ref=label, slot="caption",
                      assigned_post=offer.post_ordinal)
            return table[canonical]
        _warn(run.log, "copy_ref_unknown",
              f"{entry.asset_id}: caption ref {label!r} is not one of this creative's caption "
              "candidates; falling back to its assigned post's own caption",
              asset_id=entry.asset_id, ref=label, slot="caption")
    return offer.captions[0] if offer.captions else None


# --------------------------------------------------------------------------------------------
# Free text and the fallback tier
# --------------------------------------------------------------------------------------------


def _free_text(entry: PlanEntry, payload: Mapping[str, Any], group: _Group,
               run: _Run) -> _Written:
    """§1.7.5's free-text creatives: an override brief, or a topic that arrived with no posts.

    These quote nothing, so there is nothing to be verbatim ABOUT: the model writes the words, the
    configured language applies, and FR-101's word-boundary trim applies with it. This is the only
    path `_apply_budgets` still touches.
    """
    copyset = CopySet(
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
        through_line=str(payload.get("through_line") or "") or _subject_name(entry, group),
        motion_beat=str(payload.get("motion_beat") or ""),
    )
    tags: list[DegradationTag] = []
    if _apply_budgets(copyset, entry, run):
        tags.append(DegradationTag.TEXT_TRIMMED)
    return _Written(copyset=copyset, source=CopyProvenance(), tags=tags)


def _refused(entry: PlanEntry, group: _Group, run: _Run, offer: _Offer) -> _Written:
    """The creative whose bound post may not be quoted (FR-307/§0.10) — ours words, wordless frame.

    This is NOT `copy_degraded`: no model call failed, and counting it as an FR-248 `llm_starved`
    loss would blame the LLM for a plan that bound a post the fetch gate had already spent. It is
    not `_fallback_copy` either — that tier quotes P1, and P1 may be the very post being refused.
    So the creative ships what is unambiguously ours: the topic's own name plus the standing niche
    line, hashtags assembled from the name, and NO on-image text (`no_onimage_text`, which is what
    the operator will actually see in the frame).

    Two tags, and the second one only where it is true: `no_onimage_text` always (the frame is
    wordless whatever the reason), plus `no_fresh_post_available` when the post was BURNT — the
    same FR-73 spelling `plan.assign` uses for its own skip of the same condition, so the operator
    reads one vocabulary whichever gate caught it. A `bound_post_missing` refusal is a different
    fault (the topic changed under the plan) and does not borrow that word; it lives in the log
    line `_bound_index` already wrote.
    """
    name = _subject_name(entry, group)
    caption = _fallback_caption(name, run.niche_descriptor)
    hashtags = _hashtags(name)
    copyset = CopySet(
        asset_id=entry.asset_id,
        language=entry.language,
        trend_key=entry.trend_key,
        caption=caption,
        hashtags=hashtags,
        headline="",
        subline="",
        slide_texts=[],
        overlay_text="",
        through_line=name,
    )
    _warn(run.log, "copy_post_refused",
          f"{entry.asset_id}: its source post was refused ({offer.refused}); the creative ships "
          "the topic name plus the standing niche line and renders without on-image text. No "
          "other post is substituted — the plan's binding is the run's no-repeat guarantee",
          asset_id=entry.asset_id, reason=offer.refused,
          post_id=str(entry.source_post_id or ""))
    tags = [DegradationTag.NO_ONIMAGE_TEXT]
    if offer.refused == _REFUSED_BURNT:
        tags.append(DegradationTag.NO_FRESH_POST_AVAILABLE)
    return _Written(copyset=copyset, source=CopyProvenance(), tags=tags,
                    quoted=(caption, *hashtags))


def _fallback(entry: PlanEntry, trend: TrendItem | None, run: _Run) -> _Written:
    """FR-99's last resort — the copy call produced nothing for this creative.

    `copy_degraded` AND `no_onimage_text` travel together here and stay two facts: the first is an
    LLM outcome FR-248 counts as `llm_starved` (exit 1 — a failed copy call is a loss to surface
    even though the content it falls back to is now legitimate), the second is what the operator
    will actually see in the frame.
    """
    copyset = _fallback_copy(entry, trend, run.niche_descriptor, run.competitors)
    top = _top_post(trend)
    # This tier quotes P1, NOT the creative's assigned post — there is no answer to honour a
    # divergence rule with, and the top post is the one the operator would have picked. Provenance
    # is recorded only when the caption really did come from it (an empty caption falls through to
    # our own standing line, which claims nothing and is verified against itself).
    sources = tuple(text for text, _ in (_apply_strip(raw, run.competitors)
                                         for _, raw, _ in _numbered_fields(top))
                    if text.strip()) if top is not None else ()
    quoted = any(copyset.caption in source for source in sources)
    refs = {"caption": "P1.caption"} if quoted else {}
    _warn(run.log, "copy_degraded",
          f"{entry.asset_id}: copy call failed; shipping "
          + ("the top post's caption verbatim" if quoted else "our own standing caption")
          + " and NO on-image text (FR-99)",
          asset_id=entry.asset_id, reason="no_onimage_text",
          copy_source_post_id=top.post_id if top and quoted else "")
    return _Written(
        copyset=copyset,
        source=CopyProvenance(post_id=top.post_id if top and quoted else "", refs=refs),
        tags=[DegradationTag.COPY_DEGRADED, DegradationTag.NO_ONIMAGE_TEXT],
        quoted=sources if quoted else (copyset.caption, *copyset.hashtags))


def _fallback_copy(entry: PlanEntry, trend: TrendItem | None, niche_descriptor: str = "",
                   competitors: Sequence[str] = ()) -> CopySet:
    """The no-call tier's `CopySet`: the top post's caption verbatim, and NO on-image text.

    **What changed, twice, and why (§1.7.4).** Until A20 this function put the competitor's exact
    hook into `headline` and the source deck's panel copy into `slide_texts`, which reproduced a
    competitor's words into a shipped asset on a failure path. A20 emptied every field and wrote a
    caption in our own words. The topic-first pivot reverses the premise — the source's caption in
    its own language IS the product now — but not the on-image half: this path runs when the model
    told us nothing, so we do not know WHICH of the post's strings belonged in the frame, and
    guessing is what A20 was right about. The caption is the top post's, verbatim (minus the
    blocklist); the frame stays wordless and says so via `no_onimage_text`.

    With no posts at all — an override brief, or a topic that arrived empty — the caption falls
    back to what is ours: the topic's own name (the monitor's theme label) plus the niche
    descriptor from config, and `through_line` carries the theme name so `reel_director.md` still
    knows what the clip is about.

    §0.7's substance floor applies to this tier too, and it has to: the caption that reaches here
    is unscreened by any model, so a top post whose caption is a hashtag run and three words would
    otherwise ship as our caption on the very path where nobody chose it. Under the floor, this
    tier falls through to the assembled caption below — which is exactly what FR-99 calls the
    "minimal assembled caption" of the no-call tier.
    """
    name = trend.name if trend else (entry.brief_name or entry.asset_id)
    post = _top_post(trend)
    caption, hashtags = "", []
    if post is not None:
        text, _ = _apply_strip(post.caption, competitors)
        body, tags = _split_trailing_hashtags(text)
        if _caption_substance(body) >= _CAPTION_MIN_CHARS:
            caption, hashtags = body, list(tags)
    if not caption.strip():
        caption, hashtags = _fallback_caption(name, niche_descriptor), _hashtags(name)
    return CopySet(
        asset_id=entry.asset_id,
        language=entry.language,
        trend_key=entry.trend_key,
        caption=caption,
        hashtags=hashtags,
        hook_line="",
        headline="",
        subline="",
        slide_texts=[],
        overlay_text="",
        through_line=name,
    )


def _top_post(trend: TrendItem | None) -> SourcePost | None:
    """`P1` — the topic's highest-ranked post. `posts` arrives view-ranked from the adapter."""
    return trend.posts[0] if trend and trend.posts else None


def _subject_name(entry: PlanEntry, group: _Group) -> str:
    """What this creative is ABOUT in one label — the topic's name, else the brief's."""
    if group.trend is not None:
        return group.trend.name
    return entry.brief_name or entry.asset_id


def _fallback_caption(name: str, niche_descriptor: str) -> str:
    """Our own caption: the topic's theme name plus our own standing niche line.

    Both halves are ours — `NicheConfig.as_text()` is operator-authored config and the topic name
    is the monitor's theme label — so this string makes no verbatim claim and needs none. The
    niche line runs to a few hundred characters in real configs, so it is cut at a word boundary:
    a caption is a caption, not a config dump.
    """
    standing = trim_words(" ".join((niche_descriptor or "").split()), 180)[0]
    return f"{name} — {standing}" if standing else name


def _hashtags(name: str, want: int = 3) -> list[str]:
    """Hashtags assembled from the topic-name slug — reachable from `_fallback_copy` alone.

    On every other path the hashtags are the source post's own trailing run, extracted verbatim
    (§1.7.1). This function runs only when there is no post to take them from, which is also why
    inventing them here costs nothing: there is no provenance claim to break.
    """
    words = [word for word in slugify(name, 0).split("-") if len(word) > 2]
    return [f"#{word}" for word in words[:want]]


def _apply_budgets(copyset: CopySet, entry: PlanEntry, run: _Run) -> bool:
    """FR-101 layer two — word-boundary trim of every on-image string. True if anything was cut.

    **BYPASSED for ref-resolved fields (§1.7.3).** A quoted string is either under its slot's
    budget or it was never offered, so on the verbatim path there is nothing here to do and doing
    it anyway would silently break byte identity. What remains is the free-text path: an override
    brief's copy is the model's own prose and can overshoot exactly as it always could.

    FR-105's −40% vision-check retry re-runs the RENDER, not the copy call: it rebuilds the prompt
    through `build_context(budget_scale=...)`, so no reduced-budget branch belongs here.
    """
    style = run.styles.get(entry.style_key)
    limits = _slot_budgets(style, run.budgets)
    trimmed = False
    for name, slot in (("headline", "headline"), ("subline", "subline"),
                       ("overlay_text", "overlay")):
        before = getattr(copyset, name)
        after, cut = trim_words(before, limits[slot])
        if cut:
            setattr(copyset, name, after)
            trimmed = True
            _warn(run.log, "text_trimmed",
                  f"{entry.asset_id}: {name} exceeded {limits[slot]} characters and was cut at "
                  "the last word boundary", asset_id=entry.asset_id, field=name, before=before,
                  after=after)
    slides = []
    for index, text in enumerate(copyset.slide_texts, start=1):
        after, cut = trim_words(text, limits["slide"])
        if cut:
            trimmed = True
            _warn(run.log, "text_trimmed",
                  f"{entry.asset_id}: slide {index} exceeded {limits['slide']} characters",
                  asset_id=entry.asset_id, field=f"slide_texts[{index}]", before=text, after=after)
        slides.append(after)
    copyset.slide_texts = slides
    return trimmed


# --------------------------------------------------------------------------------------------
# The verifier — A20's polarity, flipped (§1.7)
# --------------------------------------------------------------------------------------------


def _verify(written: _Written, entry: PlanEntry, run: _Run) -> list[DegradationTag]:
    """Audit every shipped string. Deviation tags `copy_not_verbatim`; it NEVER fails a creative.

    FR-303 formalises this pass and FR-73 owns its one tag's spelling (`copy_not_verbatim`, cited
    to FR-303 in the degradation vocabulary). Two questions, asked of the finished `CopySet` rather
    than of the plan that produced it — the point of a verifier is to catch the day the plan and
    the product disagree:

    1. **Is it the source's?** Every rendered string must be a byte-substring of one of the strings
       this creative was entitled to quote (`_Written.quoted`), AFTER the logged strip. That pool
       is built from `_numbered_fields`, so it contains exactly the four quotable kinds — a shipped
       string that happens to match Virlo's `description` is a deviation like any other, which is
       the second half of FR-303's ban and the reason it is enforced at the grammar rather than at
       a length filter. Ref resolution makes the check true by construction today; it is what
       notices the day someone adds a "helpful" normalisation between the candidate table and the
       `CopySet`. It is skipped for free-text creatives, which quote nothing and claim nothing.
    2. **Is it clean?** No blocklisted competitor may appear in ANY shipped string, on any path,
       verbatim or free text. This half is the fail-closed one and it re-checks §1.5 layer 1 at
       the very last moment before the bytes leave this module — the same asymmetry `_strip_terms`
       documents: the blocklist is absolute, the filter's own proposals are not re-judged here.

    The counterpart pass at the assembled render prompt is `build_context`'s `_strip_brands` (M6);
    this one is at `CopySet` level and they are deliberately independent — a string can only reach
    a render prompt through one of the two.
    """
    copyset = written.copyset
    shipped = [("caption", copyset.caption), ("headline", copyset.headline),
               ("subline", copyset.subline), ("overlay_text", copyset.overlay_text)]
    shipped += [(f"slide_{index}", text)
                for index, text in enumerate(copyset.slide_texts, start=1)]
    shipped += [(f"hashtag_{index}", tag)
                for index, tag in enumerate(copyset.hashtags, start=1)]
    deviations: list[str] = []
    for name, text in shipped:
        if not str(text).strip():
            continue
        if apply_blocklist(text, run.competitors) != text:
            deviations.append(f"{name}: carries a blocklisted competitor name")
        elif written.quoted and not any(str(text) in source for source in written.quoted):
            deviations.append(f"{name}: is not a byte-substring of the source it was taken from")
    if not deviations:
        return []
    _warn(run.log, "copy_not_verbatim",
          f"{entry.asset_id}: {len(deviations)} shipped string(s) failed the verbatim audit — "
          + "; ".join(deviations)
          + ". The creative ships and is tagged; an audit never costs the operator a card",
          asset_id=entry.asset_id, deviations=deviations)
    return [DegradationTag.COPY_NOT_VERBATIM]


# --------------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------------


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Sequence):
        return [str(item) for item in value if str(item).strip()]
    return []


def _int(value: Any) -> int:
    """A non-negative int from anything a source or a plan can put in an integer field."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _warn(log: Any, event_type: str, message: str, **data: Any) -> None:
    logger.warning("%s: %s", event_type, message)
    if log is not None:
        log.warn(event_type, message, **data)


__all__ = ["COPY_ROLE", "CopyProvenance", "CopyResult", "write_copy"]
