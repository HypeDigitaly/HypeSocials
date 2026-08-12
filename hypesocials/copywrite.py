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
   to the model with the slots it fits. On-image candidates are pre-filtered against the style's
   own `max_onimage_chars` (intersected with the config budgets) and must be emoji-free,
   @handle-free, URL-free and hashtag-free; caption candidates keep emoji and inline hashtags, and
   their TRAILING hashtag run is extracted into `hashtags[]` instead of being offered as pixels.
2. **The model returns REFERENCES** (`CopySelection`: `headline_ref`, `subline_ref`,
   `overlay_ref`, `slide_refs`, `caption_ref`) plus free text only where nothing becomes pixels —
   `through_line`, `narrative_arc`, `motion_beat`.
3. **The engine resolves references to bytes.** Verbatim cannot fail: nothing is retyped, no
   language is detected, no accent is lost and nothing is trimmed, because an over-budget string
   was never offered. `_apply_budgets` is BYPASSED for every ref-resolved field — trimming a
   quoted string is precisely how byte identity dies.

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
- **Sibling divergence is the ENGINE's decision (§1.6/§1.7.6).** Creative *k* on a topic quotes
  `posts[trend_reuse_index % len(posts)]` and is offered that post's strings ALONE, so two
  creatives on one topic can never ship the same caption. The model chooses which string of that
  post to use, never which post.
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

#: Ref-label grammar (contracts item 10), pinned: `P<n>.<kind>[.<i>]`, 1-based everywhere.
#: `caption` and `description` are scalar fields and carry no index.
_REF = re.compile(r"^\s*[`\"']?\s*P(\d+)\.(hook|overlay|panel|caption|description)"
                  r"(?:\.(\d+))?\s*[`\"']?\s*$", re.IGNORECASE)
#: `kind` -> the `SourcePost` attribute it numbers. Scalar kinds map to a str, list kinds to a
#: list, and nothing outside this table is quotable — the grammar and the model are one contract.
_KIND_FIELDS = {"hook": "hooks", "overlay": "text_overlays", "panel": "panel_texts",
                "caption": "caption", "description": "description"}
#: The two kinds a caption may be quoted from. Hooks and panel texts are on-image material: they
#: are written to be read in one glance, and a three-word hook makes a poor caption.
_CAPTION_KINDS = ("caption", "description")
#: Kinds that may never become pixels, however short and however clean they are.
#:
#: `description` is `SourcePost`'s one field that is NOT the creator's words: it is Virlo's
#: `summary`, written by its `intelligence` block (`sources/virlo.py::_source_post`'s field table
#: says so, and names THIS module as the place the distinction has to be enforced). That makes it
#: legitimate context and legitimately verbatim *from Virlo*, so it stays a caption candidate —
#: but burning an AI paraphrase into a frame as though a human wrote it is the one quote this
#: engine must not make, and the length filter alone would happily allow a short one.
_NEVER_ON_IMAGE = ("description",)

# ---------------------------------------------------------------------------------------------
# On-image pre-filters (§1.7.1, F23). A string that fails any of these can never be an on-image
# candidate, whatever its length: emoji and @handles render as garbage or as an accidental
# mention, URLs invite a hallucinated hyperlink, and a hashtag in the frame is a caption artefact
# that has no business inside the artwork. Captions keep all four.
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

#: How much of a candidate is shown in the prompt. The model only needs enough to CHOOSE; the
#: engine ships the original bytes from `SourcePost`, so a display truncation costs nothing.
_DISPLAY_CHARS = 400


@dataclass(slots=True)
class CopyProvenance:
    """FR-298 — WHICH post and WHICH string every field of a creative's copy came from.

    `refs` is `{slot: ref-label}` keyed by the `CopySet` field the label resolved into —
    `headline`, `subline`, `overlay_text`, `slide_1`…`slide_N`, `caption` — so meta.yaml records
    the string, not merely the post. Empty on a free-text creative (an override brief quotes
    nothing), and caption-only on the `_fallback_copy` path.
    """

    post_id: str = ""
    refs: dict[str, str] = field(default_factory=dict)


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
               strip_brands=strip_brands or {}, log=log)
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
    log: Any


@dataclass(slots=True)
class _Group:
    """One copy call's scope: the creatives of one topic (or one override brief) in one language.

    A/B pairing is dead (v2.0.0), so there is one line per ENTRY here — no pair representative and
    no cloning of one `CopySet` across siblings. Two creatives on one topic are two different
    quotes of two different posts, which is the whole point of `trend_reuse_index` post-pivot.
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
    """The candidate table for ONE creative — its assigned post and nothing else (§1.7.6)."""

    post: SourcePost | None = None
    post_ordinal: int = 0  # 1-based, as it appears in the ref labels
    onimage: list[_Candidate] = field(default_factory=list)
    captions: list[_Candidate] = field(default_factory=list)
    budgets: dict[str, int] = field(default_factory=dict)  # slot -> characters, style ∩ config
    haystack: tuple[str, ...] = ()  # every stripped source field — the verifier's substring pool

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
    """Number this creative's offerable strings — its assigned post's, pre-filtered per slot.

    The assignment is `posts[trend_reuse_index % len(posts)]` and it is the ENGINE's (§1.7.6):
    offering the whole topic would let two creatives pick the same caption, which is exactly the
    cloned-copy failure the reuse index exists to prevent. Labels stay TOPIC-global (`P3.hook.1`
    means the third-ranked post of the topic, whichever creative is looking at it), so FR-298's
    provenance and the FR-297b console roster read the same alphabet.

    Two tables come out of one pass, and a field can land in either, both or neither: `_NEVER_ON_IMAGE`
    keeps Virlo's own summary out of the pixels table while leaving it quotable as a caption, and
    `_fitting_slots` decides the rest on the F23 rules plus this creative's own budgets.
    """
    posts = list(group.trend.posts) if group.trend else []
    if not posts:
        return _Offer()
    index = entry.trend_reuse_index % len(posts)
    post = posts[index]
    style = run.styles.get(entry.style_key)
    budgets = _slot_budgets(style, run.budgets)
    slots = _FORMAT_SLOTS.get(str(entry.creative_format), _ALL_SLOTS)
    brands = _strip_terms(entry, run)
    offer = _Offer(post=post, post_ordinal=index + 1,
                   budgets={slot: budgets[slot] for slot in slots if slot in budgets})
    haystack: list[str] = []
    for kind, raw, ordinal in _numbered_fields(post):
        text, stripped = _apply_strip(raw, brands)
        if not text.strip():
            continue  # the whole string WAS the brand — there is nothing left to quote
        haystack.append(text)
        label = f"P{offer.post_ordinal}.{kind}" + (f".{ordinal}" if ordinal else "")
        fits = () if kind in _NEVER_ON_IMAGE else _fitting_slots(text, slots, offer.budgets)
        body, tags = _split_trailing_hashtags(text) if kind in _CAPTION_KINDS else (text, ())
        if fits:
            offer.onimage.append(_Candidate(label, text, kind, stripped, slots=fits))
        if kind in _CAPTION_KINDS and body.strip():
            offer.captions.append(_Candidate(label, body, kind, stripped, hashtags=tags))
    offer.haystack = tuple(haystack)
    return offer


def _numbered_fields(post: SourcePost) -> list[tuple[str, str, int]]:
    """`(kind, raw text, 1-based index or 0)` for every field the ref grammar can name.

    Order is the grammar's own — hooks, then overlays, then panels, then the two scalars — so the
    numbered block reads the same way every run and a diff of two runs' prompts is meaningful.
    """
    out: list[tuple[str, str, int]] = []
    for kind in ("hook", "overlay", "panel"):
        values = getattr(post, _KIND_FIELDS[kind], None) or []
        out.extend((kind, str(value), index)
                   for index, value in enumerate(values, start=1) if str(value).strip())
    for kind in _CAPTION_KINDS:
        value = str(getattr(post, _KIND_FIELDS[kind], "") or "")
        if value.strip():
            out.append((kind, value, 0))
    return out


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
        # A carousel slide's text is a headline in its own frame; FR-101 has always priced it that
        # way and the registry names it `slide`.
        "slide": cap(budgets.image_headline, "slide"),
        "overlay": cap(budgets.reel_seed_headline, "overlay", "headline"),
    }


def _fitting_slots(text: str, slots: Sequence[str], budgets: Mapping[str, int]) -> tuple[str, ...]:
    """Which of this creative's slots `text` may fill — length plus the four F23 exclusions.

    Everything here is a REJECTION rule: a string that fails is simply never offered, which is
    what makes the resolution step incapable of trimming, re-spelling or apologising later.
    """
    if _EMOJI.search(text) or _HANDLE.search(text) or _HASHTAG.search(text) or _URL.search(text):
        return ()
    if "\n" in text.strip():
        return ()  # a multi-line string is a caption, not a headline; the frame would break it
    # Measured on the bytes that SHIP, whitespace included — the alternative is to measure a
    # stripped string and then render a longer one, which is how an "in budget" headline overflows
    # its zone. Trimming the whitespace instead is not an option: nothing here edits a quote.
    length = len(text)
    return tuple(slot for slot in slots if length <= budgets.get(slot, 0))


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
    """
    offers = {entry.asset_id: _offer_for(entry, group, run) for entry in group.entries}
    verbatim = any(offer.post is not None for offer in offers.values())
    payloads = await _call_copy(group, group.entries, run, offers, verbatim)
    if missing := [entry for entry in group.entries if entry.asset_id not in payloads]:
        _warn(run.log, "copy_group_split",
              f"grouped copy call missed {len(missing)} of {len(group.entries)} creatives; "
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
        if payload is None:
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
        lines.append(f"  on-image candidates ({budget_line}):")
        if offer.onimage:
            lines.extend(f"    {c.label} [fits {', '.join(c.slots)}] {_display(c.text)}"
                         for c in offer.onimage)
        else:
            lines.append("    NONE — no string on this post fits this style's on-image budget. "
                         "Leave headline_ref, subline_ref, overlay_ref and slide_refs empty; "
                         "this creative ships caption-only.")
        lines.append("  caption candidates:")
        lines.extend(f"    {c.label} {_display(c.text)}" for c in offer.captions)
        if not offer.captions:
            lines.append("    NONE — leave caption_ref empty.")
        blocks.append("\n".join(lines))
    if not blocks:
        return ""
    header = ("Each candidate below is shown on one line and may be shown truncated; the engine "
              "renders the ORIGINAL bytes of the string you name, line breaks and all. Choose by "
              "label only.")
    return f"{header}\n\n" + "\n\n".join(blocks)


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
    """The override-brief / post-less shape: `CopySet` minus what the engine owns.

    `hook_pattern_used` is excluded because A21 is dead (§1.7.2): nothing validates it, nothing
    reads it, and asking for a field we discard is asking the model to spend tokens on nothing.
    The field itself survives on `CopySet` until the W3.5 excision and stays at its default.
    """
    creative = json_schema_for(CopySet, exclude={"language", "trend_key", "hook_pattern_used"})
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
    slides: list[str] = []
    for raw in _strings(payload.get("slide_refs")):
        # The provenance key is the slide's FINAL position, not the ref's position in the answer:
        # a dropped ref closes the gap in `slide_texts`, and `slide_3` in meta.yaml has to mean
        # the third slide that shipped, not the third label the model happened to write.
        candidate = _lookup(raw, "slide", offer, entry, run)
        if candidate is None:
            continue
        slides.append(candidate.text)
        refs[f"slide_{len(slides)}"] = candidate.label
        stripped = stripped or candidate.stripped
    caption_candidate = _caption_for(payload.get("caption_ref"), offer, entry, run)
    caption, hashtags = "", []
    if caption_candidate is not None:
        refs["caption"] = caption_candidate.label
        stripped = stripped or caption_candidate.stripped
        caption, hashtags = caption_candidate.text, list(caption_candidate.hashtags)
    else:
        # The assigned post carries no quotable caption at all (rare: a video post with an empty
        # caption and an empty description). Our own words are the honest answer — the topic name
        # plus the standing niche line — and they are ours, so no verbatim claim is made about
        # them and no provenance label is recorded.
        caption = _fallback_caption(_subject_name(entry, group), run.niche_descriptor)
        own_words.append(caption)
        _warn(run.log, "copy_caption_unavailable",
              f"{entry.asset_id}: post P{offer.post_ordinal} offers no quotable caption; shipping "
              "the topic name and the standing niche line instead", asset_id=entry.asset_id)

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
    if not (headline or subline or overlay or slides):
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
        source=CopyProvenance(post_id=offer.post.post_id if offer.post else "", refs=refs),
        tags=tags,
        quoted=(*offer.haystack, *own_words))


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
    """
    name = trend.name if trend else (entry.brief_name or entry.asset_id)
    post = _top_post(trend)
    caption, hashtags = "", []
    if post is not None:
        text, _ = _apply_strip(post.caption, competitors)
        caption, tags = _split_trailing_hashtags(text)
        hashtags = list(tags)
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

    Two questions, asked of the finished `CopySet` rather than of the plan that produced it — the
    point of a verifier is to catch the day the plan and the product disagree:

    1. **Is it the source's?** Every rendered string must be a byte-substring of one of the strings
       this creative was entitled to quote (`_Written.quoted`), AFTER the logged strip. Ref
       resolution makes this true by construction today; the check is what notices the day someone
       adds a "helpful" normalisation between the candidate table and the `CopySet`. It is skipped
       for free-text creatives, which quote nothing and claim nothing.
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


def _warn(log: Any, event_type: str, message: str, **data: Any) -> None:
    logger.warning("%s: %s", event_type, message)
    if log is not None:
        log.warn(event_type, message, **data)


__all__ = ["COPY_ROLE", "CopyProvenance", "CopyResult", "write_copy"]
