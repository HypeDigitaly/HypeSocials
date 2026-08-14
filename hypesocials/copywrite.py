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
   and must carry no SOCIAL MARK (FR-319: no @handle, and no URL outside the technical allowlist —
   `github.com/user/repo` is offerable, `linktr.ee/creator` is not); every kind but `panel` must
   additionally be emoji-free,
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
   slides silently swapped. A mapped panel that HAS words always ships them in full — the style's
   slide budget does not gate it, only `PANEL_SANITY_CHARS` and the @handle/URL backstop do (FIX
   2, 2026-08-13) — and every row of the panel map carries both the original panel and a
   `drop_reason`. The model still chooses that deck's cover headline, its caption and its hashtags.

Public API:
    await write_copy(entries, trends=..., styles=..., call=..., engine=...) -> CopyResult
    CopyResult(copy, tags, provenance) — `.degraded` / `.trimmed` are views over `tags`
    CopyProvenance(post_id, refs) — FR-298's `copy_source_post_id` / `copy_source_refs`
    COPY_ROLE, PANEL_SANITY_CHARS

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
- **Layer 3 removes the SOURCE CREATOR's own name (FR-312, D-C).** In run 20260813_161444_r9pz
  the author's brand header ("EMIR AI LAB", handle `emirailab`) was line 1 of every Virlo panel
  and shipped verbatim onto all eight rendered slides — our creative signed with somebody else's
  account. Layer 3 is unguarded and fail-closed like layer 1, and it works on WHOLE LINES rather
  than word boundaries: a panel line whose collapsed form EQUALS the author handle, the author's
  display name or one of that deck's `chrome_text` lines is DROPPED ENTIRELY (operator decision:
  drop, never substitute), and the rest of the panel stays byte-verbatim. Equality — never
  substring — is what keeps a headline that merely contains the word "lab" intact; the collapse
  (casefold, alphanumerics only) is what makes "EMIR AI LAB" and "emirailab" the same string. A
  legitimate short line that happens to collapse onto the handle is dropped too, and that is the
  intended trade: no output of ours may name another creator. **Captions get one extra pass
  (v2.1.3, FR-312 layer 3b):** a caption TOKEN whose collapsed form scores ≥ 0.85 similarity
  against an author identifier is removed, because "ScaleWithOma" over `@scalewithomaa` is one
  dropped character and a word-boundary regex cannot see it. That pass is caption-scoped by
  contract — panel text becomes pixels and stays under equality alone. **And one more, layer 3c
  (v2.1.4, `_strip_cta`):** a caption SENTENCE that is the source creator's call to action — a
  leading swipe cue, "link in my bio", `Comment "SCALE"`, "DM me", "tap the link" — is dropped
  whole. Not their name but their FUNNEL: glz0 published all three of those under our brand,
  instructing our audience to swipe seven slides of a five-slide deck and to visit someone else's
  bio. Captions only, five named patterns, every removal warned with the sentence it took.
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
from hypesocials.topic_filter import apply_blocklist, collapse, fuzzy_strip
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
# On-image pre-filters (§1.7.1, F23, relaxed for panels by D46 §0.14b, split by FR-319). A string
# that fails one of these can never fill the slot it failed for, whatever its length: emoji and
# @handles render as garbage or as an accidental mention, a SOCIAL link is an ad for someone else's
# funnel, and a hashtag in the frame is a caption artefact that has no business inside the artwork.
# Captions keep all four.
#
# The ONE relaxation: a `panel` candidate filling the SLIDE slot keeps emoji, newlines and
# `#`-tokens. Those three are not defects there — they are the source deck's own typography, and
# our slide *i* is a re-rendering of their slide *i* (FR-304). Rejecting them would have left the
# panel-mapped deck with a wordless slide wherever the creator used an emoji, which is the same
# empty frame D46 exists to fix. SOCIAL MARKS stay excluded on every slot and every kind: they leak
# an identity or a link rather than a voice. TECHNICAL URLs are not marks at all since v2.1.3 —
# see the FR-319 block below `_HASHTAG_TOKEN` for what that means and why.
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
#: The bare-domain TLD list includes ee/gg/be so scheme-less `linktr.ee/x`, `discord.gg/x` and
#: `youtu.be/x` are detected — FR-319 names them social marks, and an undetected URL would render.
#: Widening is fail-closed: an unrecognized host drops the candidate, never renders it.
_URL = re.compile(
    r"(?i)(?:https?://|www\.)\S+"
    r"|(?<![\w@])[\w-]+\.(?:com|net|org|io|ai|app|co|cz|sk|de|eu|me|tv|ee|gg|be)(?:/\S*)?(?!\w)")
#: One trailing `#tag` at the very end of a caption, with the whitespace before it. Applied
#: repeatedly, this peels the whole trailing run off and leaves the caption body untouched.
_TRAILING_TAG = re.compile(r"(?:\s|^)(#[^\s#]+)\s*$")
#: Any hashtag token anywhere, for MEASURING a caption's substance (§0.7). Deliberately not the
#: same expression as `_TRAILING_TAG`: an inline `#ai` stays in the caption we ship (it is part of
#: the author's sentence) but it is not what makes the sentence a caption, so it does not count
#: towards the floor.
_HASHTAG_TOKEN = re.compile(r"(?<!\w)#\S+")

# ---------------------------------------------------------------------------------------------
# FR-312 (v2.1.4) — the CTA strip. Caption-scoped, sentence-shaped, five named patterns.
#
# A caption is the one place this engine ships a stranger's prose to our audience unedited, and in
# the glz0 run that prose was carrying their funnel: swipe cues counting THEIR deck, "link in my
# bio", `Comment "SCALE"`. These are not brand names (layers 1–2 miss them) and not the creator's
# identity (layer 3 misses them) — they are instructions, and an instruction our reader cannot
# follow is worse than no sentence at all.
#
# Each pattern is deliberately narrow, because a caption sentence removed is a sentence the
# operator paid a model to choose:
# - `swipe_cue` fires only when the sentence LEADS with "swipe" — the cue's own shape ("Swipe all
#   7 slides", "Swipe up") — so "I swipe left on tools like this" is untouched;
# - `comment_keyword` needs the QUOTED SHOUTED keyword the mechanic depends on, so "the comment
#   section went wild" survives; it is written with a scoped `(?i:...)` because the caps class is
#   the pattern and a blanket IGNORECASE would erase it;
# - the other three are fixed phrases with no innocent reading in a caption we publish.
# ---------------------------------------------------------------------------------------------

#: Sentence boundaries in a caption: a terminator plus whitespace, or a line break. Captions are
#: written in lines as often as in sentences, and a cue on its own line is the commonest shape of
#: all ("...\nLink in bio 👇").
_CAPTION_SENTENCE = re.compile(r"(?<=[.!?…])\s+|\n+")
_CAPTION_CTA: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("swipe_cue", re.compile(r"^\W*swipe\b", re.IGNORECASE)),
    # `linked in bio` is as common as `link in bio` and means the same thing. The whitespace
    # between the two words is what keeps "LinkedIn bio" — one token, ordinary prose about a
    # profile — out of it.
    ("link_in_bio", re.compile(r"link(?:ed)?\s+in\s+(?:my\s+|the\s+|our\s+)?bio", re.IGNORECASE)),
    ("comment_keyword", re.compile(r"(?i:comment)\s*[\"'“”«]\s*[A-Z][A-Z ]*[\"'“”»]")),
    # The 59el run shipped `Comment CLAUDE and I will send free guide` — the same mechanic with
    # the quotes left off. A bare SHOUTED keyword (≥2 caps) right after "comment" is that
    # mechanic; "the comment section went wild" stays safe because "section" is not shouted.
    ("comment_keyword_bare", re.compile(r"(?i:comment)\s+[A-Z]{2,}(?:\s+[A-Z]{2,})*\b")),
    ("dm_me", re.compile(r"\bDM\s+(?:me|us)\b", re.IGNORECASE)),
    ("tap_the_link", re.compile(r"\btap\s+(?:the|this|my|our)\s+link\b", re.IGNORECASE)),
)

# ---------------------------------------------------------------------------------------------
# FR-319 (v2.1.3) — the SOCIAL/TECHNICAL split. A URL is not one thing.
#
# What this is written against. A source panel showed a terminal block whose last line was
# `github.com/safishamsi/graphify` — the install line, the entire point of that slide — and the
# `_URL` backstop blanked the slide for "containing a URL". The rule was right about what it was
# built for (`linktr.ee/creator` in our frame is an ad for somebody else's funnel) and wrong about
# what it caught: a repository path is the source's CONTENT, not their identity.
#
# So the question the two gates ask changes from "is there a URL here" to "does this text point
# somewhere SOCIAL". @handles are unconditionally social — an @ in our frame reads as a mention,
# whatever follows it. A URL is judged by its HOST against the allowlist below, and the judgement
# is FAIL-CLOSED: an allowlisted technical host renders byte-verbatim, and every other host —
# named social platform, link-in-bio service, unknown marketing domain, typo — still drops. The
# allowlist is short on purpose. It is easier to add `crates.io` the day a Rust deck needs it than
# to explain a creative that shipped a stranger's funnel because a domain looked harmless.
#
# The tie-break is the PRD's, spelled out: a text carrying BOTH a handle and a technical URL is
# social and drops. The handle is tested first and no host can excuse it.
# ---------------------------------------------------------------------------------------------

#: Hosts whose URLs are technical CONTENT and render as the source wrote them (FR-319). Matched by
#: SUFFIX, so `gist.github.com`, `www.github.com` and `myproject.readthedocs.io` all resolve
#: through their registrable parent. `localhost` is here for the shell lines that quote it.
_TECHNICAL_HOSTS = frozenset({
    "github.com", "gist.github.com", "gitlab.com", "bitbucket.org", "npmjs.com", "pypi.org",
    "crates.io", "huggingface.co", "readthedocs.io", "stackoverflow.com",
    "developer.mozilla.org", "docs.python.org", "localhost",
})
#: A host whose FIRST label is one of these is technical whatever its parent domain: every vendor
#: puts its reference under `docs.`, `api.` or `developer.`, and enumerating them is a losing game.
_TECHNICAL_LABELS = frozenset({"docs", "api", "developer"})
#: The scheme prefix of an absolute URL, and the dotted sub-domain labels sitting immediately to
#: the left of a bare match. `_URL`'s second branch matches the registrable pair alone
#: (`python.org` inside `docs.python.org`), so the labels in front of it have to be recovered
#: before the host can be judged — otherwise `docs.python.org` would be read as `python.org` and
#: dropped, which is precisely the class of mistake FR-319 exists to end.
_SCHEME = re.compile(r"(?i)^[a-z][a-z0-9+.-]*://")
_SUBDOMAIN_TAIL = re.compile(r"(?:[\w-]+\.)+$")

#: How much of a candidate is shown in the prompt. The model only needs enough to CHOOSE; the
#: engine ships the original bytes from `SourcePost`, so a display truncation costs nothing.
_DISPLAY_CHARS = 400
#: How far an offer will PAD a panel list out to the post's declared `panel_count` (§0.14a keeps
#: slot *i* at index *i*, so the padding is what preserves the alignment when Virlo shipped fewer
#: texts than slides). A fence, not a policy: `panel_count` is a source-controlled integer, no
#: platform's deck comes near this, and slots past it would be empty strings by definition. Real
#: panel TEXTS are never dropped by it — only invented empty slots are.
_MAX_PANEL_SLOTS = 60

#: Layer 3 (FR-312) — the shortest COLLAPSED identifier that is allowed to drop a line. Two
#: characters is an initialism, a page counter ("1/8" collapses to "18") or a stray particle, and a
#: two-character identifier would blank panels for a living. Three is where a handle starts being a
#: name. Measured after the collapse, so "@ai lab" (5) qualifies and "@ab" (2) never does.
_CREATOR_MIN_CHARS = 3
#: Which channel an identifier came from — printed in the FR-312 warning, because "the author's own
#: handle" and "a swipe cue this deck already carries as chrome" are different findings and the
#: operator reads them differently.
_ID_AUTHOR = "author"
_ID_CHROME = "chrome"

#: Why an offer refused to quote its post at all — both are FR-307/§0.10 belt-and-braces behind the
#: fetch gate, and both leave the creative with the assembled caption and a wordless frame.
_REFUSED_BURNT = "no_fresh_post_available"  # FR-73's vocabulary, verbatim
_REFUSED_MISSING = "bound_post_missing"

#: The ONLY length gate a MAPPED panel faces (FIX 2, operator ruling 2026-08-13). A bound deck's
#: slide *i* is a re-render of the source's slide *i*, so the question is never "does this panel fit
#: our headline band" — the panel IS the slide, and the render template is told to give a long
#: string room (more lines, tighter leading, a wider block) instead of shrinking it. This ceiling is
#: a SANITY fence, not a design budget: past ~1500 characters the string is a transcription accident
#: (a whole caption scraped into one panel, a vision pass that ran away), not a slide anybody read.
#:
#: What it replaces: the per-style `slide` budget (`text_budgets.slide` ∩ `max_onimage_chars.slide`,
#: 180–300 characters in the shipped registry) used to gate mapped panels too, and in run
#: 20260813_143420_oyo4 it blanked 21 of 41 mapped panels — one of them for being ONE character over
#: 300. Those budgets still govern every free-text and model-SELECTED string (`_fitting_slots`,
#: `_slot_budgets`, `_apply_budgets`); they no longer govern a panel the engine mapped.
PANEL_SANITY_CHARS = 1500

#: The three ways a mapped panel yields a wordless slide (FR-304). One of these strings, or "",
#: lands in every `panel_map` row's `drop_reason`, so meta.yaml and the gallery can say WHY a slide
#: is bare instead of leaving the operator to infer it from an empty `source_text`.
_DROP_EMPTY = "empty"
_DROP_MARKS = "contains_handle_or_url"
_DROP_OVER_BUDGET = "over_budget"


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
    order, INCLUDING the slides whose source panel was empty, unusable or over the sanity ceiling:

        {"slide": 3, "source_position": 3, "source_text": "",
         "source_text_original": "Ask @creator for the template", "ref_label": "",
         "drop_reason": "contains_handle_or_url", "creator_stripped": False}

    The row is the alignment. A deck that dropped its empty rows would tell the gallery that our
    slide 3 came from their slide 4, which is the precise failure FR-304 is written against.

    `source_text` is what SHIPPED onto our slide and `source_text_original` is the panel as it
    arrived — identical on every slide that rendered, and different exactly where `drop_reason`
    is non-empty OR `creator_stripped` is true. Keeping both is what makes the provenance honest:
    the previous shape recorded a dropped panel as `source_text: ""`, which reads as "their slide
    was blank too" and destroyed the operator's ability to see what a blank slide of ours had cost
    (audit of run 20260813_143420_oyo4). `drop_reason` is `""` on a slide that shipped, else
    `empty`, `contains_handle_or_url` or `over_budget`.

    `creator_stripped` (FR-312) is the fifth key and the one that can be true on a slide that
    SHIPPED: the panel named its own creator — a brand header, a chrome echo — that line was
    dropped and the remainder rendered. It is a per-row fact rather than a drop reason precisely
    because the slide is usually still full of words.
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
    chrome_lines: Mapping[str, Sequence[str]] | None = None,
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
        brand_context: Notion brand text; reaches the copywriter only (FR-109). **The caller gates
            it on FR-318:** while `branding.enabled` is false this MUST arrive empty, because a
            master switch that silenced the wordmark while brand voice, offers and ICP still
            steered every headline would be a switch that did not do what it says. The gate lives
            at the call site rather than here — this module receives a string and holds no config —
            and an empty value simply leaves `{{brand_context}}` blank, which is the same shape as
            a run with no Notion pages configured. `competitors` below is NOT gated by it.
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
        chrome_lines: `post_id -> that deck's per-slide `chrome_text` strings` (FR-306's separate
            transcription of watermarks, handles, page counters and swipe/follow cues). Layer 3's
            SECOND identifier channel: a panel line that merely echoes the chrome — "SWIPE ❮❮"
            riding on `virlo_text` where `chrome_text` already holds the same cue — collapses onto
            it and is dropped (FR-312). Keyed by post like `merged_panels`, and for the same
            reason: the chrome is a property of the SOURCE DECK, so two siblings bound to one post
            see one reading of it. Omitted, the author handle alone supplies the identifiers.
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
               chrome_lines=chrome_lines or {},
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
    chrome_lines: Mapping[str, Sequence[str]] = field(default_factory=dict)  # post_id -> that
    #   deck's `chrome_text` strings — layer 3's chrome identifiers (FR-312)
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
    #: The same deck one strip EARLIER — after §1.5 layers 1–2, before layer 3's creator-line drop.
    #: It is what `panel_map.source_text_original` records, so a row whose header line was removed
    #: can still show the operator the line it lost (FR-312/FR-309). Identical to `panels`
    #: everywhere layer 3 did not fire, which is nearly everywhere.
    panels_original: tuple[str, ...] = ()
    stripped_panels: frozenset[int] = frozenset()  # 1-based positions a competitor was cut from
    #: 1-based positions layer 3 removed a creator/chrome line from (FR-312). Kept apart from
    #: `stripped_panels` on purpose: `panel_emptied_by_strip` is a competitor finding and must not
    #: start reporting creator headers, which have their own event and their own row flag.
    creator_stripped_panels: frozenset[int] = frozenset()
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
    # §1.5 layer 3 (FR-312), built once per creative from the bound post's own author and from
    # THIS deck's chrome. `creators` names lines that may not become pixels at all; `own_name` is
    # the narrower author-only set the caption strip removes at word boundaries.
    creators = _creator_identifiers(post, run.chrome_lines.get(str(post.post_id), ()))
    own_name = _creator_caption_terms(post, panels, creators)
    kept: list[str] = list(panels)  # post-strip, index-aligned — the FR-304 deck
    pre_creator: list[str] = list(panels)  # the same deck before layer 3, for the panel map
    cut: set[int] = set()
    creator_cut: set[int] = set()
    hits: list[tuple[str, str, str]] = []  # (dropped line, identifier, channel) — the FR-312 log
    caption_named = False  # the caption said the creator's name and layer 3 took it out
    haystack: list[str] = []
    for kind, raw, ordinal in _numbered_fields(post, panels):
        text, stripped = _apply_strip(raw, brands)
        if kind == "panel":
            pre_creator[ordinal - 1] = text
        # Layer 3 runs on EVERY quotable kind, not on panels alone: a hook or an overlay that is
        # nothing but the creator's brand header is the same leak wearing a different label.
        found = _creator_line_hits(text, creators)
        text, creator_dropped = _strip_creator_lines(text, creators)
        hits.extend(found)
        if kind in _CAPTION_KINDS:
            # The caption is prose, so a whole-line drop rarely reaches it — "Follow EMIR AI LAB
            # for more" is one line and mostly legitimate. Its half of layer 3 is the word-boundary
            # mechanic layers 1–2 already use, over the AUTHOR terms alone (a chrome cue like
            # "swipe" is an ordinary word in a caption and is deliberately not removed), followed
            # by the v2.1.3 FUZZY pass for the near misses a word boundary cannot see. Order
            # matters: the exact strip runs first so the fuzzy one only ever judges what survived
            # it, and both are caption-scoped — nothing on this branch becomes pixels.
            text, name_cut = _apply_strip(text, own_name)
            text, fuzzy_cut = _fuzzy_caption(text, own_name, entry.asset_id, str(post.post_id),
                                             run.log)
            # FR-312 residual (v2.1.4): the creator's FUNNEL, not their name. Runs last, over what
            # the two identity strips left, and deliberately outside `creator_dropped` — a caption
            # that lost a call to action is not a caption that named a competitor, and folding it
            # into that flag would tag the creative `competitor_stripped` for it.
            text = _strip_cta(text, entry.asset_id, str(post.post_id), run.log)
            # Both cuts make the caption non-byte-identical (so both earn `marked` below), but only
            # the word-boundary one feeds `caption_named`: that flag adds a clause to the aggregate
            # FR-312 warning which says "at word boundaries", and a fuzzy removal has already been
            # reported individually, with its ratio, by the call above. Folding it in here is how
            # the aggregate ends up announcing "0 source line(s) were DROPPED".
            creator_dropped = creator_dropped or name_cut or fuzzy_cut
            caption_named = caption_named or name_cut
        if kind == "panel":
            kept[ordinal - 1] = text  # empty when the whole panel WAS the brand: a wordless slide
            if stripped:
                cut.add(ordinal)
            if creator_dropped:
                creator_cut.add(ordinal)
        if not text.strip():
            continue  # the whole string WAS the brand — there is nothing left to quote
        haystack.append(text)
        label = f"P{offer.post_ordinal}.{kind}" + (f".{ordinal}" if ordinal else "")
        fits = _fitting_slots(text, slots, offer.budgets, kind=kind)
        # One `stripped` flag covers both strips: it means "no longer byte-identical to the source",
        # which is exactly what it meant before, and it is what earns the creative the standing
        # `competitor_stripped` tag. The FR-312 warning below carries the honest cause.
        marked = stripped or creator_dropped
        if fits:
            offer.onimage.append(_Candidate(label, text, kind, marked, slots=fits))
        if kind in _CAPTION_KINDS:
            body, tags = _split_trailing_hashtags(text)
            if _caption_substance(body) >= _CAPTION_MIN_CHARS:
                offer.captions.append(_Candidate(label, body, kind, marked, hashtags=tags))
    offer.haystack = tuple(haystack)
    offer.panels = tuple(kept)
    offer.panels_original = tuple(pre_creator)
    offer.stripped_panels = frozenset(cut)
    offer.creator_stripped_panels = frozenset(creator_cut)
    if hits or caption_named:
        # DEDUPED for the message, counted in full: a brand header sits on all eight panels of a
        # deck, and printing it eight times buries the finding it is supposed to surface.
        named = ("; ".join(f'{line!r} == the {channel} identifier {key!r}'
                           for line, key, channel in dict.fromkeys(hits))
                 or "no whole line matched")
        _warn(run.log, "panel_creator_line_stripped",
              f"{entry.asset_id}: {len(hits)} source line(s) naming the creator of post "
              f"{post.post_id} were DROPPED before anything was offered (FR-312, §1.5 layer 3) — "
              + named
              + (", and the caption lost the creator's name at word boundaries"
                 if caption_named else "")
              + ". No creative of ours may name another account, so the line is removed outright "
                "rather than replaced; the rest of each panel ships byte-verbatim, and a panel "
                "that was ONLY that line now renders wordless in its own position",
              asset_id=entry.asset_id, post_id=str(post.post_id),
              lines=[line for line, _, _ in hits],
              identifiers=[key for _, key, _ in hits],
              caption_stripped=caption_named,
              channels=sorted({channel for _, _, channel in hits}))
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
        #
        # Since FIX 2 this ceiling governs SELECTED slides only — an unbound carousel's
        # `slide_refs`, where a model chose the string and the choice can be held to a design
        # budget. A MAPPED panel bypasses it entirely (`_mapped_deck`/`PANEL_SANITY_CHARS`): that
        # text is mirrored rather than chosen, and 21 of 41 panels in run 20260813_143420_oyo4
        # were blanked by exactly this number.
        "slide": cap(budgets.slide, "slide"),
        "overlay": cap(budgets.reel_seed_headline, "overlay", "headline"),
    }


def _social_mark(text: str) -> bool:
    """FR-319 — does `text` point at somebody's IDENTITY or funnel? The one gate both callers ask.

    True for any `@handle`, and for any URL whose host is not on the technical allowlist. False —
    the text keeps its words and renders byte-verbatim — only when there is no handle at all AND
    every URL in the string resolves to an allowlisted technical host.

    Fail-closed twice over. A host we cannot place is social (the allowlist is an allowlist, not a
    blocklist), and a text carrying BOTH a handle and a technical URL is social: the handle is
    tested first and `github.com` in the next sentence does not redeem it. That is the PRD's own
    tie-break — "a line containing both (social link inside a shell copy-paste, @mention in a code
    block) is dropped".

    A string with no URL and no handle never reaches the host logic at all, which is nearly every
    string this engine sees.
    """
    return bool(_HANDLE.search(text)) or _social_url(text)


def _social_url(text: str) -> bool:
    """True when `text` carries at least one URL pointing somewhere other than a technical host."""
    return any(not _technical_host(host) for host in _url_hosts(text))


def _url_hosts(text: str) -> list[str]:
    """Every host `_URL` finds in `text`, lower-cased, sub-domains recovered, port and userinfo off.

    The recovery is the fiddly half and it is not optional. `_URL`'s bare-domain branch matches a
    single label plus a known TLD, so `docs.python.org/3/library` matches as `python.org/3/library`
    and `gist.github.com` matches as `github.com` — read literally, the first would be judged as
    `python.org` (not allowlisted, dropped) and the second would pass for the wrong reason. So for
    a match that carries no scheme, the dotted labels immediately to its left are prepended back
    on, which reassembles the host the author actually wrote.
    """
    hosts: list[str] = []
    for match in _URL.finditer(text):
        raw = match.group(0)
        host = _host_of(raw)
        if not _SCHEME.match(raw) and (prefix := _SUBDOMAIN_TAIL.search(text[:match.start()])):
            host = prefix.group(0).lower() + host
        if host:
            hosts.append(host)
    return hosts


def _host_of(raw: str) -> str:
    """`"https://user@Docs.Python.org:8443/3/x?q=1"` -> `"docs.python.org"` — scheme, credentials,
    port, path, query and fragment all removed, because none of them says WHERE the link goes."""
    body = _SCHEME.sub("", raw)
    body = re.split(r"[/?#]", body, maxsplit=1)[0]
    body = body.rpartition("@")[2]  # userinfo, if any
    return body.split(":", 1)[0].strip(".").lower()


def _technical_host(host: str) -> bool:
    """Is this host on FR-319's technical allowlist — itself, a sub-domain of one, or a `docs.`,
    `api.` or `developer.` reference site? Everything else is social by construction."""
    if any(host == allowed or host.endswith(f".{allowed}") for allowed in _TECHNICAL_HOSTS):
        return True
    return host.split(".", 1)[0] in _TECHNICAL_LABELS


def _fitting_slots(text: str, slots: Sequence[str], budgets: Mapping[str, int],
                   *, kind: str = "") -> tuple[str, ...]:
    """Which of this creative's slots `text` may fill — length plus F23, relaxed per §0.14b.

    Everything here is a REJECTION rule: a string that fails is simply never offered, which is
    what makes the resolution step incapable of trimming, re-spelling or apologising later.

    One exclusion is absolute on every slot and every kind: a SOCIAL MARK (FR-319) — an `@handle`,
    which renders as somebody else's identity, or a URL pointing at a social platform, a
    link-in-bio service or any host we cannot place. A TECHNICAL URL is no longer an exclusion at
    all: `github.com/user/repo` is the content of the slide it was written on, and the PRD says in
    so many words that technical URLs may be offered to copy selection. The other three (emoji,
    newlines, hashtags) are absolute everywhere EXCEPT a `panel` filling the `slide` slot: that
    string was already on a slide, in a deck people watched to the end, and its emoji is typography
    rather than noise (D46 §0.14b). The same panel offered as a HEADLINE is held to the full rule —
    a headline is our frame's own line, not a re-render of theirs.
    """
    if _social_mark(text):
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
# §1.5 layer 3 — the SOURCE CREATOR's own name (FR-312, D-C)
#
# What this is written against, exactly. Run 20260813_161444_r9pz rendered eight slides from a
# bound slideshow whose every panel began with the author's brand header — "EMIR AI LAB", the
# display form of the handle `emirailab` — and every one of those headers shipped, verbatim,
# because the verbatim contract is doing precisely what it was built to do. Our creative came out
# signed with another account's name. Nothing upstream could have caught it: it is not a
# competitor (layer 1), the topic filter had no reason to propose it (layer 2), it is not an
# @handle or a URL (the `_panel_verdict` backstop), and it is not over any budget.
#
# The mechanic is deliberately unlike layers 1 and 2. Those remove a TERM from inside a sentence
# at word boundaries; this removes a WHOLE LINE, and only when the line is nothing but the
# identifier. A creator's brand header is its own line in every deck this failure has been seen
# in, and word-boundary removal there would leave a widowed fragment on the slide rather than a
# clean slide. The equality test is what keeps it safe to be unguarded: "EMIR AI LAB" as line 1
# goes, "why EMIR AI LAB does this" as line 1 stays whole (and is a different, much rarer problem).
#
# Fail-closed, and the cost is named up front: the collapse throws away case, spacing and
# punctuation, so a legitimate line that collapses onto the handle — "AI LAB" against `ailab` —
# is dropped too. Given the choice between one lost slide line and one creative signed with
# someone else's brand, the operator chose the lost line (D-C).
# --------------------------------------------------------------------------------------------


def _collapse(text: str) -> str:
    """`" EMIR AI LAB "` -> `"emirailab"` — casefolded, alphanumerics only, pure.

    Everything that is not a letter or a digit goes: spaces, `@`, `|`, `·`, the arrow glyphs a
    swipe cue is drawn with, emoji. That is what makes the handle (`emirailab`), the display name
    (`EMIR AI LAB`) and the watermark (`Emir | AI Lab`) one string to compare against, and what
    makes `"SWIPE ❮❮"` and `"SWIPE <<"` the same cue.

    `str.isalnum()` rather than an ASCII class on purpose: `casefold()` + `isalnum()` keep `ř`,
    `ä` and `ω`, so a Czech or Greek line collapses to its own letters instead of to a mangled
    ASCII skeleton that could collide with an unrelated identifier.

    The implementation moved to `topic_filter.collapse` with the v2.1.3 fuzzy layer (FR-312): the
    equality rule here and the similarity rule there have to agree on what "the same name" means,
    and two copies of a five-line comprehension is exactly how they would stop agreeing. This alias
    stays because this module's callers — and its tests — read it as layer 3's own vocabulary.
    """
    return collapse(text)


def _creator_identifiers(post: SourcePost,
                         chrome_lines: Sequence[str] = ()) -> dict[str, str]:
    """`collapsed identifier -> which channel named it` — layer 3's whole vocabulary (FR-312).

    Two channels, both belonging to the SOURCE, neither ever configured by us:

    - **author** — `SourcePost.author` (the handle, `@` and all; the collapse eats the `@`) plus a
      display name if the adapter ever carries one. `SourcePost` has no display-name field today,
      so it is read defensively through `getattr`: the day Virlo's row grows one, layer 3 picks it
      up without a second edit here, and until then nothing changes.
    - **chrome** — this deck's `chrome_text` strings (FR-306's separate transcription of
      watermarks, counters and swipe/follow cues). A panel line that merely echoes the chrome is
      the creator's furniture rather than their content: "SWIPE ❮❮" is on `virlo_text` in decks
      whose `chrome_text` already holds the same cue, and rendering it tells our reader to swipe
      on a deck whose slides do not swipe that way.

    A multi-line chrome string contributes each of its lines separately — the vision pass returns
    a slide's chrome as one field, and its parts are separate cues. Anything collapsing shorter
    than `_CREATOR_MIN_CHARS` is discarded outright, so an empty `chrome_text` (the common case)
    and a "1/8" counter add nothing. First writer wins, so an identifier that is BOTH the author's
    name and chrome is reported as the author's, which is the finding that matters.
    """
    out: dict[str, str] = {}
    names = [str(post.author or ""),
             str(getattr(post, "author_name", "") or getattr(post, "display_name", "") or "")]
    for raw in names:
        key = _collapse(raw)
        if len(key) >= _CREATOR_MIN_CHARS:
            out.setdefault(key, _ID_AUTHOR)
    for line in chrome_lines:
        for part in str(line or "").split("\n"):
            key = _collapse(part)
            if len(key) >= _CREATOR_MIN_CHARS:
                out.setdefault(key, _ID_CHROME)
    return out


def _strip_creator_lines(text: str, identifiers: Mapping[str, str]) -> tuple[str, bool]:
    """`(text without its creator lines, whether any line went)` — FULL-LINE equality, pure.

    A line is dropped iff its own collapsed form EQUALS one of `identifiers`. Never a substring
    test: "labs" contains "lab", every second English hook contains something, and a substring
    rule here would quietly shred the verbatim contract this module exists to keep. Equality means
    the line has to BE the identifier and nothing else.

    Everything that survives survives byte for byte — the kept lines are the original strings, not
    re-joined tokens — so a panel that loses its header line ships the remainder exactly as its
    author typed it, `\\r`, double spaces and all. Only blank lines orphaned at the very top or
    bottom by the removal are dropped with it; a blank line BETWEEN two kept lines is part of the
    panel's shape and stays.

    A text that matched nothing comes back the same object, which is what keeps this safe to run
    over every candidate on every post.
    """
    if not text or not identifiers:
        return text, False
    lines = text.split("\n")
    kept = [line for line in lines if _collapse(line) not in identifiers]
    if len(kept) == len(lines):
        return text, False
    while kept and not kept[0].strip():
        kept.pop(0)
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept), True


def _creator_line_hits(text: str, identifiers: Mapping[str, str]) -> list[tuple[str, str, str]]:
    """`(the line, the identifier it equalled, which channel)` for every line layer 3 will drop.

    The diagnostic twin of `_strip_creator_lines` — same predicate, opposite output — so the
    FR-312 warning can name the line the operator lost and say whether it was the author's own
    handle or a chrome cue that matched it. Split from the strip rather than folded into its
    return value so the strip stays the small pure function its callers (and its tests) want.
    """
    if not text or not identifiers:
        return []
    return [(line, key, identifiers[key])
            for line in text.split("\n")
            if (key := _collapse(line)) in identifiers]


def _creator_caption_terms(post: SourcePost, panels: Sequence[str],
                           identifiers: Mapping[str, str]) -> tuple[str, ...]:
    """The literal strings a CAPTION may not say — the author's name, in the forms it appears in.

    The caption is prose, so the whole-line rule above almost never bites it: "Follow EMIR AI LAB
    for more AI tool picks" is one line and most of it is legitimate. What has to go is the name
    inside it, which is the word-boundary mechanic layers 1–2 already own — so this function's
    only job is to say WHICH literal strings to hand `apply_blocklist`.

    Three sources, all of them the author's own:

    - the handle, `@` stripped (`@emirailab` -> `emirailab`), which catches a caption that
      @-mentions the creator without an `@`;
    - a display name if the post carries one;
    - **the DISPLAY form found on the deck** — any panel, hook or overlay line whose collapsed
      form is an AUTHOR identifier. That is where "EMIR AI LAB" comes from: the handle alone would
      not remove it, because the spaces make it three words at word boundaries.

    CHROME identifiers are deliberately excluded. "Swipe" is an ordinary word in a caption, and a
    caption is not pixels — removing it would cost the operator a legitimate sentence to solve a
    problem that only exists inside the frame.
    """
    terms: list[str] = []
    handle = str(post.author or "").strip().lstrip("@").strip()
    name = str(getattr(post, "author_name", "") or getattr(post, "display_name", "") or "").strip()
    terms += [value for value in (handle, name)
              if len(_collapse(value)) >= _CREATOR_MIN_CHARS]
    sources = [*panels, *(post.hooks or ()), *(post.text_overlays or ())]
    for raw in sources:
        for line in str(raw or "").split("\n"):
            if identifiers.get(_collapse(line)) == _ID_AUTHOR and line.strip():
                terms.append(line.strip())
    return tuple(dict.fromkeys(terms))


def _fuzzy_caption(text: str, terms: Sequence[str], asset_id: str, post_id: str,
                   log: Any) -> tuple[str, bool]:
    """FR-312 layer 3b — `(caption without its near-miss creator tokens, whether any went)`.

    **Captions only, and the asymmetry with panels is the whole design (PRD FR-312, v2.1.3).** A
    panel becomes pixels, so it is held to full-line collapse-EQUALITY and nothing looser: a
    similarity score in charge of slide text would eventually eat a word the creator meant. A
    caption is prose in a feed — it is the one place where a near miss can be removed without
    breaking anything the operator is looking at — and it is where the miss actually happened.
    Run 20260813 captioned a creative "ScaleWithOma" over an author whose handle is
    `@scalewithomaa`; layer 3a's word-boundary regex needs the exact term and could not see it.

    The mechanics are `topic_filter.fuzzy_strip`'s (pure, testable, one implementation); this
    wrapper exists to REPORT. Every removal is warned individually with the token, the identifier
    it matched and the measured ratio, because a fuzzy strip is a judgement call and the operator
    is entitled to audit each one — "ScaleWithOma ≈ scalewithomaa at 0.96" is a finding they can
    check, "the caption was cleaned" is not.
    """
    out, hits = fuzzy_strip(text, terms)
    for token, identifier, ratio in hits:
        _warn(log, "caption_creator_fuzzy_stripped",
              f"{asset_id}: the caption token {token!r} was removed — it matches the creator "
              f"identifier {identifier!r} of post {post_id} at {ratio:.2f} similarity, above the "
              "0.85 threshold (FR-312 layer 3b). A near miss of the author's own handle is still "
              "the author's name; captions alone are stripped this way and panel text stays "
              "byte-verbatim",
              asset_id=asset_id, post_id=post_id, token=token, identifier=identifier,
              ratio=round(ratio, 4))
    return out, bool(hits)


def _strip_cta(text: str, asset_id: str, post_id: str, log: Any) -> str:
    """FR-312 (v2.1.4) — the source creator's FUNNEL out of our caption, one sentence at a time.

    **Captions only.** Nothing on this path becomes pixels, and nothing here may ever be pointed
    at a panel, a hook or an overlay: a panel is a re-rendering of the source slide (FR-304) and
    editing one on a judgement call is how a verbatim deck stops being verbatim.

    What it is written against. Run `20260814_010814_glz0` shipped three captions carrying another
    account's call to action verbatim: "Swipe all 7 slides." (on a deck of five — their count, not
    ours), "Grab the free step-by-step guide via the link in my bio." (their bio) and
    `Comment "SCALE" and I'll send you the link` (their DMs). Each one is an instruction our
    audience cannot follow, addressed to a funnel that is not ours, printed under our brand.

    The unit removed is the SENTENCE, for the same reason `_scrub_creator` drops a whole sentence:
    "Grab the free guide via the link in my bio" with only "link in my bio" removed still promises
    a guide nobody can reach. Every removal is warned individually with the sentence and the
    pattern that caught it, because this strip is a judgement about MEANING and the operator is
    entitled to audit each call.

    Nothing matched means nothing happens — the caption comes back byte-identical, whitespace and
    line breaks included. Reflow (collapsing what is left onto single spaces) is a consequence of
    removing a sentence out of the middle, so it is paid only by the captions that were edited.
    """
    parts = [part for part in _CAPTION_SENTENCE.split(text) if part is not None]
    hits = [(part, name) for part in parts if (name := _cta_pattern(part))]
    if not hits:
        return text
    for sentence, pattern in hits:
        _warn(log, "caption_cta_stripped",
              f"{asset_id}: the caption sentence {' '.join(sentence.split())!r} was removed — it "
              f"is the source creator's own call to action ({pattern}), addressed to a funnel that "
              f"is not ours (post {post_id}, FR-312). The rest of the caption ships verbatim",
              asset_id=asset_id, post_id=post_id, sentence=" ".join(sentence.split()),
              pattern=pattern)
    kept = [" ".join(part.split()) for part in parts if not _cta_pattern(part)]
    return " ".join(part for part in kept if part)


def _cta_pattern(sentence: str) -> str:
    """The name of the first CTA pattern this sentence matches, or `""` — the whole gate."""
    return next((name for name, rule in _CAPTION_CTA if rule.search(sentence)), "")


def _creator_terms(post: SourcePost | None) -> tuple[str, ...]:
    """The author terms for a post seen OUTSIDE an offer — the degrade tier's convenience wrapper.

    `_fallback_copy` quotes the top post with no offer built for it, so it has neither the
    identifier map nor the deck. Author identifiers alone are available there (there is no chrome
    without a slide-intelligence pass), and that is enough for the one thing that tier ships: a
    caption.
    """
    if post is None:
        return ()
    return _creator_caption_terms(post, list(post.panel_texts or ()), _creator_identifiers(post))


def _scrubbed(text: str, brands: Sequence[str], creator_terms: Sequence[str],
              *, caption: bool = False) -> str:
    """`text` through §1.5 layers 1 and 3 in that order, for the paths with no offer table.

    One expression, so the caption a degrade tier ships and the pool the verifier checks it
    against can never be built two different ways — that mismatch is how a successful strip gets
    reported as a verbatim deviation.

    `caption=True` adds FR-312's fuzzy pass, and ONLY the caller that is building a caption may ask
    for it: the fallback tier runs this function over every quotable kind to build the verifier's
    pool, and a fuzzy strip applied to a panel there would be a rule this codebase does not have.
    It is silent by design — `_fuzzy_caption` is the reporting door, and the pool must not warn
    about a string nobody is shipping.
    """
    out, _ = _apply_strip(text, brands)
    out, _ = _strip_creator_lines(out, _creator_identifiers_from(creator_terms))
    out, _ = _apply_strip(out, creator_terms)
    if caption:
        out, _ = fuzzy_strip(out, creator_terms)
    return out


def _creator_identifiers_from(terms: Sequence[str]) -> dict[str, str]:
    """Literal creator terms -> the collapsed identifier map `_strip_creator_lines` expects."""
    return {key: _ID_AUTHOR for term in terms
            if len(key := _collapse(term)) >= _CREATOR_MIN_CHARS}


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
            # FR-99 vs FR-304 ruling (D15, SESSION G): a BOUND deck's slides are a deterministic
            # panel mapping that needs no model, so a failed copy call must not cost it its words.
            written = (_mapped_fallback(entry, offer, group, run)
                       if _panel_mapped(entry, offer) else _fallback(entry, group.trend, run))
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
        # ONE tag for the whole §1.5 family (FR-73 spells it `competitor_stripped` and this module
        # does not get to invent vocabulary), so the message names both things it can mean rather
        # than asserting the commoner one. Which strip actually fired is in its own event: layer 1
        # and 2 have no per-line event, layer 3 has `panel_creator_line_stripped`.
        tags.append(DegradationTag.COMPETITOR_STRIPPED)
        _warn(run.log, "competitor_stripped",
              f"{entry.asset_id}: a blocklisted competitor name, or the source creator's own name "
              "(FR-312), was removed from this creative's text before it was offered (§1.5); the "
              "copy is still sourced, no longer byte-identical",
              asset_id=entry.asset_id, refs=dict(refs),
              creator_lines=sorted(offer.creator_stripped_panels))
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

    **A mapped panel that has words ALWAYS ships them (FIX 2, operator ruling 2026-08-13).** The
    per-style slide budget is out of this loop entirely: it is a design ceiling for text WE choose,
    and this text is not chosen, it is mirrored. Run 20260813_143420_oyo4 lost 21 of 41 mapped
    panels to that budget (one at 301 characters against a 300 ceiling) and shipped decks whose
    slides were blank next to a source slide full of words — the exact failure FR-304 exists to
    prevent. What remains is a three-way taxonomy, evaluated in this order, and every verdict is
    recorded per row in `panel_map.drop_reason` so the map itself says why a slide is bare:

    - **`empty`** — nothing after `strip()`. Virlo transcribed nothing and vision filled nothing
      (§0.14a), or the whole panel WAS a competitor's name and §1.5 removed it, or the position
      lies past the source deck's own end. `generate/carousel` draws it as a no-text slide.
    - **`contains_handle_or_url`** — the SAFETY BACKSTOP, and the only content rule left here. The
      constant keeps its name and its meaning NARROWS to social marks alone (FR-319, v2.1.3): an
      @handle renders as somebody else's identity, and a URL pointing at a social platform, a
      link-in-bio service or any host outside the technical allowlist is an ad for someone else's
      funnel. A TECHNICAL URL no longer fires it — `github.com/user/repo` in a terminal block is
      the content of that slide, and blanking it was the defect this amendment fixes. §0.14b
      relaxes emoji, newlines and `#` for this slot; it never relaxes a social mark. It is a
      backstop rather than a filter because FR-306's `chrome_text` field now takes creator
      watermarks, counters and swipe cues off the `onimage_text` transcription upstream — before
      that split, a vision pass that read "@creator" off a watermark cost the whole panel.
    - **`over_budget`** — longer than `PANEL_SANITY_CHARS`. Not a design budget: a transcription
      accident. It is still never trimmed (FR-100), because a trimmed quote is not a quote.

    All three KEEP THEIR POSITION — the row is the alignment — and each is warned once per
    creative, in its own event with its own honest cause, because "21 panels blanked" and "one
    panel was a watermark" are different questions and used to share one misleading sentence.

    §1.5 layer 3 (FR-312) has already run by the time this function sees a panel: a line that was
    the creator's own name is gone from `offer.panels` and survives in `offer.panels_original`,
    which is what each row's `source_text_original` records. Layer 3 is not a fourth drop reason —
    it usually leaves a full slide behind — so it rides its own boolean, `creator_stripped`, and
    it is `_offer_for` that warns about it, once per creative, over every kind rather than over
    panels alone.
    """
    length = max(0, _int(entry.slide_count)) or len(offer.panels)
    deck = _PanelDeck()
    over: list[str] = []       # over the sanity ceiling — cited in characters
    marks: list[str] = []      # an @handle or a URL survived into the panel text
    blanked: list[str] = []    # the source claimed words here and the strip took them all
    for position in range(1, length + 1):
        text = offer.panels[position - 1] if position <= len(offer.panels) else ""
        # What the panel said before §1.5 layer 3 took its creator line out (FR-312). Identical to
        # `text` everywhere layer 3 was silent, which is nearly every row.
        original = (offer.panels_original[position - 1]
                    if position <= len(offer.panels_original) else text)
        creator_cut = position in offer.creator_stripped_panels
        label = f"P{offer.post_ordinal}.panel.{position}"
        reason = _panel_verdict(text)
        ships = not reason
        if reason == _DROP_OVER_BUDGET:
            over.append(f"slide {position} ({len(text)} characters, sanity ceiling "
                        f"{PANEL_SANITY_CHARS})")
        elif reason == _DROP_MARKS:
            marks.append(f"slide {position} (carries {_excluded_marks(text, relaxed=True)})")
        elif reason == _DROP_EMPTY and position in offer.stripped_panels:
            blanked.append(f"slide {position}")
        deck.texts.append(text if ships else "")
        deck.refs[f"slide_{position}"] = label if ships else ""
        deck.panel_map.append({"slide": position, "source_position": position,
                               # `source_text` stays what SHIPS (the gallery renders it beside our
                               # slide); `source_text_original` is the pre-gate panel, so a dropped
                               # slide can still show the operator what it dropped (FR-309).
                               "source_text": text if ships else "",
                               "source_text_original": original,
                               "ref_label": label if ships else "",
                               "drop_reason": reason,
                               # FR-312: this row's panel named its creator and lost that line.
                               # `source_text_original` above is where the operator (and the
                               # FR-309 gallery) can see exactly what was taken out.
                               "creator_stripped": creator_cut})
        deck.stripped = deck.stripped or (ships and (position in offer.stripped_panels
                                                     or creator_cut))
    deck.refs = {slot: label for slot, label in deck.refs.items() if label}
    if over:
        _warn(run.log, "panel_over_budget",
              f"{entry.asset_id}: {len(over)} source panel(s) exceed the {PANEL_SANITY_CHARS}"
              f"-character sanity ceiling and are never trimmed (FR-100) — {'; '.join(over)}. A "
              "panel that long is a transcription accident rather than a slide; those slides "
              "render without text and keep their position", asset_id=entry.asset_id,
              sanity_ceiling=PANEL_SANITY_CHARS, slides=over)
    if marks:
        _warn(run.log, "panel_handle_or_url",
              f"{entry.asset_id}: {len(marks)} source panel(s) carry an @handle or a URL pointing "
              f"outside the technical allowlist, and may never become pixels (FR-319; a "
              f"github.com or docs. link WOULD have rendered) — {'; '.join(marks)}. Usually this "
              "is creator chrome "
              "read off the slide by vision; FR-306's chrome_text field keeps it out of the panel "
              "text, so a panel still arriving with one here is the source's own. Those slides "
              "render without text and keep their position", asset_id=entry.asset_id, slides=marks)
    if blanked:
        _warn(run.log, "panel_emptied_by_strip",
              f"{entry.asset_id}: {len(blanked)} source panel(s) had words and lost all of them to "
              f"the competitor strip (§1.5) — {'; '.join(blanked)}. Those slides render without "
              "text and keep their position", asset_id=entry.asset_id, slides=blanked)
    return deck


def _panel_verdict(text: str) -> str:
    """`""` when this mapped panel ships verbatim, else which of the three drop reasons applies.

    Order matters and is the order of certainty: an empty string has nothing to judge, a SOCIAL
    MARK (FR-319 — an @handle, or a URL pointing anywhere but an allowlisted technical host) is a
    content rule that no length could excuse, and the sanity ceiling is the last and weakest test.
    Nothing about the style's or the config's slide budget is consulted — a mapped panel is not
    text we chose (FIX 2), and since v2.1.3 a technical URL is not a reason to blank a slide
    either: `github.com/user/repo` inside a terminal block IS the slide.
    """
    if not text.strip():
        return _DROP_EMPTY
    if _social_mark(text):
        return _DROP_MARKS
    if len(text) > PANEL_SANITY_CHARS:
        return _DROP_OVER_BUDGET
    return ""


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
    """One ref → the candidate it names, or `None` with an HONEST reason in the log.

    Three ways a ref can be unusable, and all three end the same way — that slot resolves to no
    string:

    - **unparseable or unknown** — the model invented a label. Nothing to resolve.
    - **another post's** — §1.7.6 assigned this creative one post. The label is re-pointed at the
      assigned post when the same kind and index exist there (the model's editorial choice
      survives, the divergence rule holds); otherwise it is dropped.
    - **not offerable for THIS slot** — the string was offered for a different slot, or the slot's
      exclusions refuse it (an emoji or a hashtag outside a mapped slide), or it is longer than the
      slot's budget, or this creative's format renders no such slot at all. It is NOT trimmed:
      trimming a quoted string is how byte identity dies (§1.7.3).

    The last case used to log as `copy_ref_over_budget` and claim a length failure whatever the
    real cause, and to claim the frame "ships empty" even on a mapped deck whose slide 1 renders
    its own panel text regardless (audit of run 20260813_143420_oyo4, FIX 5b). It now names the
    cause it measured and describes the outcome that actually follows.
    """
    label = str(raw or "").strip()
    if not label:
        return None
    match = _REF.match(label)
    outcome = _unresolved_outcome(slot, entry, offer)
    if match is None:
        _warn(run.log, "copy_ref_unparseable",
              f"{entry.asset_id}: {label!r} is not a candidate label (P<n>.<kind>[.<i>]); "
              f"{outcome}", asset_id=entry.asset_id, ref=label, slot=slot)
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
              + (f"re-pointed to {canonical}" if candidate else outcome),
              asset_id=entry.asset_id, ref=label, slot=slot,
              assigned_post=offer.post_ordinal)
    if candidate is None:
        _warn(run.log, "copy_ref_unknown",
              f"{entry.asset_id}: {label!r} was never offered for this creative; {outcome}",
              asset_id=entry.asset_id, ref=label, slot=slot)
        return None
    if slot not in candidate.slots:
        cause = _rejection_cause(candidate, slot, offer)
        _warn(run.log, "copy_ref_rejected",
              f"{entry.asset_id}: {canonical} may not fill the {slot} slot — {cause}. It is never "
              f"trimmed or re-spelled to make it fit (§1.7.3); {outcome}",
              asset_id=entry.asset_id, ref=canonical, slot=slot, cause=cause,
              length=len(candidate.text), offered_for=list(candidate.slots))
        return None
    return candidate


def _rejection_cause(candidate: _Candidate, slot: str, offer: _Offer) -> str:
    """WHY this candidate is not offerable for `slot` — measured, never assumed to be length.

    The order is the order the offer applied: a slot this format does not render at all, then the
    F23 character exclusions (`_fitting_slots`'s absolute rules, relaxed only for a `panel` filling
    `slide`, §0.14b), then the slot's own budget. The fall-through names the slots the string WAS
    offered for, which is the honest answer when a caller asks for a slot the string simply was
    never a fit for.
    """
    if slot not in offer.budgets:
        return f"this creative's format renders no {slot} slot"
    limit = offer.budgets.get(slot, 0)
    relaxed = slot == "slide" and candidate.kind == "panel"
    excluded = _excluded_marks(candidate.text, relaxed=relaxed)
    if excluded:
        return (f"it carries {excluded}, which the {slot} slot never renders (F23; §0.14b relaxes "
                "emoji, line breaks and hashtags for a mapped slide alone)")
    if len(candidate.text) > limit:
        return f"it is {len(candidate.text)} characters and the {slot} budget is {limit}"
    return (f"it was offered for {', '.join(candidate.slots)} only"
            if candidate.slots else "it was offered for no slot at all")


def _excluded_marks(text: str, *, relaxed: bool = False) -> str:
    """Which F23 exclusions this string carries, named. `relaxed` drops the §0.14b three.

    "a URL" means a SOCIAL URL since FR-319: a technical host renders, so naming it here would
    explain a rejection that did not happen — which is exactly how `_rejection_cause` used to blame
    a length failure on a character class.
    """
    checks: list[tuple[str, Any]] = [("an @handle", lambda value: bool(_HANDLE.search(value))),
                                     ("a URL", _social_url)]
    if not relaxed:
        checks += [("an emoji", lambda value: bool(_EMOJI.search(value))),
                   ("a hashtag", lambda value: bool(_HASHTAG.search(value)))]
    found = [name for name, carries in checks if carries(text)]
    if not relaxed and "\n" in text.strip():
        found.append("a line break")
    return ", ".join(found)


def _unresolved_outcome(slot: str, entry: PlanEntry, offer: _Offer) -> str:
    """What ACTUALLY happens to this creative when `slot` resolves to nothing.

    "The headline ships empty" was untrue on the commonest deck we render: a mapped carousel's
    anchor draws its own panel text through the TEXT block whether or not a cover headline was
    ever chosen (`prompts_engine._onimage_text` prefers the slide's text), so the frame is not
    wordless and telling the operator it is sends them looking for a defect that is not there.
    """
    if slot == "headline" and _panel_mapped(entry, offer):
        return ("no cover headline is recorded; slide 1 still renders its engine-mapped panel "
                "text, so the anchor is not wordless (FR-304)")
    return f"this creative's {slot} carries no string and that zone renders wordless"


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


def _mapped_fallback(entry: PlanEntry, offer: _Offer, group: _Group, run: _Run) -> _Written:
    """FR-99's fallback for a BOUND deck — the mapping stands even though the model said nothing.

    The FR-99-vs-FR-304 ruling (D15, SESSION G): `_mapped_deck` is deterministic — source panel
    *i* becomes our slide *i* with no model in the loop — so a failed copy call on a bound
    carousel loses only what the model actually contributed (`through_line`, `narrative_arc`,
    a caption CHOICE). The slides ship mapped, the caption falls back to the bound post's own
    best candidate (`_caption_for(None, …)`, still the same post, §0.7 in force), and
    `copy_degraded` still tags the creative because the LLM outcome IS a loss FR-248 counts —
    it is just no longer a loss of the deck's words.
    """
    deck = _mapped_deck(entry, offer, run)
    refs = dict(deck.refs)
    own_words: list[str] = []
    caption_candidate = _caption_for(None, offer, entry, run)
    if caption_candidate is not None:
        refs["caption"] = caption_candidate.label
        caption, hashtags = caption_candidate.text, list(caption_candidate.hashtags)
    else:  # the bound post carries no §0.7-worthy caption: our own words, claimed as ours
        caption, hashtags = _fallback_caption(_subject_name(entry, group),
                                              run.niche_descriptor), []
        own_words.append(caption)
    copyset = CopySet(
        asset_id=entry.asset_id,
        language=entry.language,
        trend_key=entry.trend_key,
        caption=caption,
        hashtags=hashtags,
        slide_texts=deck.texts,
        through_line=_subject_name(entry, group),
    )
    tags = [DegradationTag.COPY_DEGRADED]
    if not any(text.strip() for text in deck.texts):
        tags.append(DegradationTag.NO_ONIMAGE_TEXT)
    if deck.stripped or (caption_candidate is not None and caption_candidate.stripped):
        tags.append(DegradationTag.COMPETITOR_STRIPPED)
    _warn(run.log, "copy_degraded",
          f"{entry.asset_id}: copy call failed; the bound deck still renders its "
          f"{sum(1 for text in deck.texts if text.strip())} mapped panel(s) verbatim (FR-304 "
          "needs no model) and ships "
          + ("its post's own caption" if caption_candidate is not None
             else "our own standing caption")
          + " — lost to the failure: through-line and narrative arc only (FR-99)",
          asset_id=entry.asset_id, reason="copy_call_failed",
          copy_source_post_id=offer.post.post_id if offer.post else "")
    return _Written(
        copyset=copyset,
        source=CopyProvenance(post_id=offer.post.post_id if offer.post else "", refs=refs,
                              panel_map=deck.panel_map,
                              source_panel_count=len(offer.panels)),
        tags=tags,
        quoted=(*offer.haystack, *own_words))


def _fallback(entry: PlanEntry, trend: TrendItem | None, run: _Run) -> _Written:
    """FR-99's last resort — the copy call produced nothing for this creative.

    `copy_degraded` AND `no_onimage_text` travel together here and stay two facts: the first is an
    LLM outcome FR-248 counts as `llm_starved` (exit 1 — a failed copy call is a loss to surface
    even though the content it falls back to is now legitimate), the second is what the operator
    will actually see in the frame.
    """
    copyset = _fallback_copy(entry, trend, run.niche_descriptor, run.competitors, log=run.log)
    top = _top_post(trend)
    # This tier quotes P1, NOT the creative's assigned post — there is no answer to honour a
    # divergence rule with, and the top post is the one the operator would have picked. Provenance
    # is recorded only when the caption really did come from it (an empty caption falls through to
    # our own standing line, which claims nothing and is verified against itself).
    # Both strips, in the order `_offer_for` applies them, so the verifier's pool holds the same
    # bytes the caption above was built from. Layer 3 has to reach this tier as well (FR-312): it
    # is the ONE caption path with no offer table behind it, and a top post whose caption says
    # "Follow EMIR AI LAB for more" would otherwise ship that sentence on a failure. The v2.1.3
    # fuzzy pass is switched on for the CAPTION entry alone, exactly as `_fallback_copy` builds the
    # string it ships — the pool and the product have to be scrubbed identically or a successful
    # strip reads as a verbatim deviation, and a fuzzy pool entry for a panel would be a rule this
    # codebase does not have.
    creator = _creator_terms(top)
    sources = tuple(text for text in
                    (_scrubbed(raw, run.competitors, creator, caption=kind in _CAPTION_KINDS)
                     for kind, raw, _ in _numbered_fields(top))
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
                   competitors: Sequence[str] = (), *, log: Any = None) -> CopySet:
    """The no-call tier's `CopySet`: the top post's caption verbatim, and NO on-image text.

    **What changed, twice, and why (§1.7.4).** Until A20 this function put the competitor's exact
    hook into `headline` and the source deck's panel copy into `slide_texts`, which reproduced a
    competitor's words into a shipped asset on a failure path. A20 emptied every field and wrote a
    caption in our own words. The topic-first pivot reverses the premise — the source's caption in
    its own language IS the product now — but not the on-image half: this path runs when the model
    told us nothing, so we do not know WHICH of the post's strings belonged in the frame, and
    guessing is what A20 was right about. The caption is the top post's, verbatim (minus the
    blocklist AND minus its creator's own name, §1.5 layers 1 and 3); the frame stays wordless and
    says so via `no_onimage_text`.

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
        terms = _creator_terms(post)
        # Layers 1 and 3a deterministically, then FR-312's fuzzy caption pass — this IS a caption,
        # and it is the tier with no model and no offer table between the source and the operator.
        # `log` is optional so the function stays callable as a pure builder; when it is present,
        # every fuzzy removal is reported the same way the main path reports its own.
        text, _ = _fuzzy_caption(_scrubbed(post.caption, competitors, terms), terms,
                                 entry.asset_id, str(post.post_id), log)
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


__all__ = ["COPY_ROLE", "PANEL_SANITY_CHARS", "CopyProvenance", "CopyResult", "write_copy"]
