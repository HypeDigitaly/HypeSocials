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
5. **Compress mode is a THIRD contract, opted into per run (D54/FR-331, operator decision
   2026-08-20).** Under `carousel_copy_mode: "compress"` the bound decks of point 4 take a
   different call: the engine hands the model the ADMITTED panel strings themselves rather than
   labels, and asks for each one back COMPRESSED to that style's own slide budget, humanized, in
   the source post's own language. It is a deliberate, dated, partial reversal of D50's "reflow,
   never shorten" — narrower than the A20 reversal above and opted into the same way. What it is
   written against is measured: run `20260820_001158_2ard` rendered 1,048-, 1,023- and
   1,018-character source panels onto `anime-noir-statement`, whose declared slide budget is 180,
   and the decks came back as walls of text the post-render critics blocked.

   The reversal gives up ONE thing — the byte-substring claim on those slides — and keeps every
   safety rule that was never about length: the blocklist strip (fail-closed, layers 1 and 2), the
   FR-319 social-mark backstop, the FR-312 creator-line drop, the F2 page-counter drop, the
   `PANEL_SANITY_CHARS` INPUT guard, and FR-304's position preservation with its three drop
   reasons unchanged. The engine re-applies the first three to what comes BACK, because a model
   asked to rewrite a panel can put anything in it. What replaces the byte-substring receipt is
   `CopyProvenance.copy_mode`, each panel-map row's `compressed: True`, and its
   `source_text_original` — the source panel the compressed line was authored from, still on the
   row beside what shipped.

   Scope is deliberately small: only a BOUND, non-override, panel-mapped carousel (`_panel_mapped`)
   changes behaviour. Images, reels, override briefs, unbound decks, every free-text field and
   every other run stay on the selection contract above, and `verbatim` remains the engine-wide
   default. A failed compress call costs the deck nothing — it falls back to point 4's verbatim
   mapping, tagged `copy_degraded`, with no second call and no extra spend.
6. **Auto mode compresses ONLY the panels that overflow (D62/FR-353, operator decision
   2026-08-21).** `carousel_copy_mode: "auto"` is point 5's contract applied per PANEL instead of
   per DECK, and it is what the three shipped brand configs pin. The engine measures every
   ADMITTED panel of a bound deck against that deck's own slide budget (`min(text_budgets.slide,
   the assigned style's max_onimage_chars.slide)`); the positions over it — and only those — are
   listed to the compress call, and their answers are spliced back into the verbatim mapped deck
   by position. Every panel that already fits ships byte-verbatim under its own `P<n>.panel.<i>`
   label, exactly as point 4 shipped it.

   What that buys is the thing point 5 could not: compress mode is all-or-nothing per deck, so a
   deck with one 1,000-character panel and eight 90-character panels paid a model to rewrite all
   nine and lost the byte-substring claim on all nine. Auto pays for the one and keeps the eight.
   **A deck with NOTHING over budget makes no compress call at all** and is byte-identical to a
   verbatim run of the same inputs, receipts included (`copy_mode: verbatim`) — that is FR-353's
   acceptance criterion and `_compress_wanted`'s third arm is where it is enforced.

   Auto is therefore the one mode whose receipts are MIXED, per row, on purpose: a compressed row
   carries `compressed: True`, an empty `ref_label` and the source panel in `source_text_original`,
   while a quoted row carries its real label and its bytes. `CopyProvenance.copy_mode` says
   `"auto"` for the creative and `CopyProvenance.refs` holds the QUOTED rows' labels — real
   labels, kept — so `_verify`'s byte-substring half still audits the verbatim rows for real
   rather than being skipped wholesale the way it is for a fully compressed deck.
7. **Translate mode is the LANGUAGE axis (D63/FR-343, operator decision 2026-08-21).** Points 5
   and 6 are about LENGTH; `run.copy_language_mode: "target"` is about what tongue the words are
   in, and the two are orthogonal by construction — a translated deck that compressed nothing
   reports `copy_mode: verbatim, copy_language: target`. What it reverses is one sentence of
   §1.7.5: "no language is detected" and "there is no translation path" were true of every run
   before this one, and they are why a German slideshow could only ever be quoted in German onto
   an English-language creative. Under `target` a BOUND, panel-mapped deck whose post is in a
   KNOWN language other than its platform's configured one (`entry.language`) takes ONE translate
   call of its own — never grouped, because one section per creative is what keeps a deck's
   panels its own — and every other creative in the run is untouched.

   The no-shortening guarantee is what makes this a third contract rather than a variant of
   compress: no character ceiling is ever stated to the translate call, `_translate_field` has no
   `budget` parameter, and a translated line is ALLOWED to be longer than its source. That is the
   one boundary in this module where a shipped string may legitimately grow, and the audit that
   replaces the byte-substring claim is a RATIO rather than a ceiling — a line under half or over
   twice its source panel's length warns and ships (`translate_length_drift`, A20's polarity).

   Ordering with auto is fixed and load-bearing: **translate FIRST, then measure.** The FR-304
   mapped deck is translated, and it is the TRANSLATED strings that `_rows_over_budget` measures,
   because the English of a German panel is a different number of characters and budgeting the
   source would compress the wrong rows (or none of them). So a `target` + `auto` deck makes two
   calls in sequence — translate, then compress the positions that overflowed after translation —
   and a `target` + `verbatim` deck makes exactly one.

   The receipts are per creative and per row. `CopyProvenance.copy_language` is `"target"` only
   when a translation actually shipped, `CopyProvenance.source_language` records the ladder's
   answer on EVERY bound deck in BOTH modes (so meta.yaml can say what language an untranslated
   deck is in), and each panel-map row carries `translated`. Every decision NOT to translate has
   its own warning and no tag — an unknown language (`translate_language_unknown`), a post already
   in the target language, an image or a reel — while a translation that was WANTED and did not
   happen is tagged `copy_not_translated` beside whatever the failure already earned. A failed
   translate call costs the deck nothing: it falls back to point 4's verbatim mapped deck.

Public API:
    await write_copy(entries, trends=..., styles=..., call=..., engine=...,
                     carousel_copy_mode="verbatim", copy_language_mode="source") -> CopyResult
    CopyResult(copy, tags, provenance) — `.degraded` / `.trimmed` are views over `tags`
    CopyProvenance(post_id, refs, copy_mode, copy_language, source_language) — FR-298's
        `copy_source_post_id` / `copy_source_refs`, plus FR-73's per-asset `copy_mode` and
        FR-346's per-asset language pair
    NoSafeCaptionError — pre-spend refusal: an offer path had no caption it was allowed to ship
    COPY_ROLE, PANEL_SANITY_CHARS, MODE_VERBATIM / MODE_AUTO / MODE_COMPRESS,
        LANGUAGE_SOURCE / LANGUAGE_TARGET

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
  bio. Captions only, and since v2.2.0 the same sentence gate also removes the DANGLING
  PROMO family (keyword-less comment bait, community/programme pitches, "you won't find this
  anywhere else", first-person money/metric claims); every removal is warned with the sentence it
  took.
- **A source PAGE COUNTER never becomes our slide's words (F2, Session 5.5).** A panel line that
  is nothing but the source deck's badge — `01 / 06`, `2 of 7`, `// 03` — is dropped at the same
  admission site, by shape rather than by identity (`sources.slide_intel.counter_line`), full-line
  only, so "3/4 of teams fail at this" is content and ships whole. Two failures, one strip: their
  page number printed on our shorter deck is a lie the operator sees first (FR-313 exists to
  re-base it onto OUR length), and a counter left in `panel_map.source_text` becomes a line of the
  gauntlet's frame contract — so the critic demands a badge the renderer was right to omit and
  BLOCKS the deck for `missing_text`. The counter stays in `panel_map.source_text_original` (the
  provenance doctrine below: original bytes are never rewritten), the row says
  `chrome_counter_stripped`, and the creative is NOT tagged `competitor_stripped` — nobody's brand
  was removed.
- **The caption never says what the OPERATOR configured (FR-99/FR-307 as amended, v2.2.0).** The
  niche descriptor steers the copy PROMPT and nothing else: no path from `run.niche_descriptor` to
  a shipped caption exists any more. The 08-14 audit found "AI tool stacks — AI automation for
  Czech SMBs; audience: operations leads who buy outcomes." published as a caption — our config
  file, verbatim, under our brand. The four caption fallbacks now have four scoped forms instead
  of one: an offer path (`_resolve`, `_mapped_fallback`) assembles the BOUND post's own best
  post-strip line plus a neutral, creator-less attribution; the refused path (`_refused`) ships
  the topic name ALONE, because FR-307 forbids quoting the post it just refused; the no-model
  tier (`_fallback_copy`) ships the top post's caption, else the topic name and its slug hashtags.
  An offer path left with nothing usable does not improvise: it raises `NoSafeCaptionError`
  (`NO_SAFE_CAPTION`) while the run is still pre-spend.
- **OCR repair is the ONE sanctioned mutation, applied at ONE boundary (FR-100/101, v2.2.0).**
  Panels, hooks and captions are admitted through `ocr_repair.repair_confusables` — an
  uppercase-token-scoped confusable fix ("Al agents" -> "AI agents") — and the repaired bytes are
  what the candidate table, the prompt, the verifier's pool and `panel_map.source_text` ALL see.
  Repairing one of those and not the others would report our own repair as `copy_not_verbatim`,
  which is why the repair happens once, at admission, in `_offer_for` (and in `_scrubbed` for the
  offer-less tier). `panel_map.source_text_original` keeps the UNREPAIRED bytes and every
  correction is logged `ocr_repaired`. A panel that looks CUT rather than finished is FLAGGED
  (`panel_map.truncation_suspect`) and never blanked, shortened or dropped — the flag is contract
  data for the post-render critic, and FR-304's alignment is not a heuristic's to break.
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
import dataclasses
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from hypesocials.config import TextBudgets
from hypesocials.models import (
    Brief,
    CopyCompressed,
    CopySelection,
    CopySet,
    CopyTranslated,
    DegradationTag,
    MetaStyle,
    PlanEntry,
    SourcePost,
    StructuredCall,
    TrendItem,
)
#: D65/FR-362 — the deterministic contract guards. They live in their own module rather than here
#: because they are PURE (strings and rows in, strings and rows out, no logging of their own) and
#: because this file is long enough that a reader looking for the copy contracts should not have
#: to walk past a digit-repair regex to find them. This module owns the seam: `_guarded` runs the
#: ladder once per creative, on every path, and emits the warnings it hands back.
from hypesocials.contract_guard import (
    guard_caption,
    guard_deck,
    mark_identifiers,
    strip_lines_equal,
)
from hypesocials.ocr_repair import repair_confusables, truncation_suspect
from hypesocials.prompts_engine import (
    PromptEngine,
    build_context,
    json_schema_for,
    trim_words,
)
#: The counter family lives with the module that models the source deck's counting convention
#: (D-D). Imported from the MODULE rather than the `hypesocials.sources` facade, exactly as
#: `generate/carousel.py` imports `detect_counter`/`CounterSpec`: the facade's own contract is the
#: adapter seam (fetch/brand/monitors), and pulling a pure string predicate through it would make
#: a chrome test look like a data fetch to every reader of this import block.
from hypesocials.sources.slide_intel import bare_numeral_position, counter_line
#: `language_code` is imported for the SAME reason `collapse` is: the ladder in `_source_language`
#: has to spell a language the way every other rung spells it, and a second normaliser here is how
#: `"English"` from one channel would stop comparing equal to `"en"` from another (D63/FR-343).
from hypesocials.topic_filter import apply_blocklist, collapse, fuzzy_strip, language_code
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
#: caption instead (its own post's best line under our attribution — see `_offer_caption`).
#: Operator-settled, 2026-08-13; the assembled form amended v2.2.0.
_CAPTION_MIN_CHARS = 25
#: The floor a SOURCE LINE promoted into a caption has to clear (FR-99/FR-307 caption forms,
#: v2.2.0). Deliberately far below `_CAPTION_MIN_CHARS`: that floor asks "is this a caption or a
#: hashtag dump", and a hook — "7 tools that replaced my stack" — is a caption's worth of words by
#: construction. This one only asks whether a line is a SENTENCE at all, so a two-word panel scrap
#: ("Step 3", "1/8") cannot become the creative's caption while a real hook can. Kept low on
#: purpose: every character of headroom here is a creative that captions itself from its own post
#: instead of raising `NO_SAFE_CAPTION` and stopping the run.
_FALLBACK_LINE_MIN_CHARS = 8
#: The attribution clause appended to a promoted source line. Ours, and NAMELESS on purpose: the
#: line is the source creator's, so the caption says where it came from without saying WHO — FR-312
#: forbids our creatives naming another account, and `SourcePost` carries no platform field to name
#: instead. A caption assembled this way makes no verbatim claim: it joins the verifier's pool as
#: our own words (`_Written.quoted`), exactly like the other assembled captions.
_NEUTRAL_ATTRIBUTION = "— from a post trending this week"

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
# FR-312 (v2.1.4, extended v2.2.0) — the CTA strip. Caption-scoped, sentence-shaped, named
# patterns only.
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
    # ---- v2.2.0, the DANGLING PROMO family (08-14 carousel audit, FR-312 as amended) ----------
    # The four above catch an instruction with a mechanism in it. What the audit found shipping
    # under our brand was the same funnel with the mechanism left implicit: a promise addressed to
    # an account that is not ours, printed where our reader cannot act on it. Each pattern below
    # still has to see the SHAPE of the pitch, never merely its subject matter.
    #
    # `comment_bait` is the keyword-less sibling of `comment_keyword`: a sentence that OPENS with
    # "comment" (or "drop a comment", or "let me know in the comments") is asking our audience to
    # feed somebody else's reply automation. Anchored at the sentence start so "the comment I got
    # was brutal" and "people comment this every time" are untouched.
    ("comment_bait", re.compile(
        r"^\W*(?:comment\b|drop\s+a\s+comment\b|let\s+me\s+know\s+in\s+the\s+comments\b)",
        re.IGNORECASE)),
    # A pitch to JOIN something of theirs. The possessive is load-bearing: "join our community" is
    # their funnel, "the community moved to Discord" is an observation about the market, and the
    # required verb + possessive + venue triple is what separates the two.
    ("community_pitch", re.compile(
        r"\b(?:join|sign\s+up\s+(?:for|to)|enrol?l\s+in|apply\s+(?:to|for))\s+"
        r"(?:my|our|the)\s+(?:free\s+|new\s+|private\s+|paid\s+)?"
        r"(?:community|programme?|cohort|academy|mastermind|bootcamp|newsletter|waitlist|"
        r"challenge|course|group|channel|discord|server|club|membership)\b", re.IGNORECASE)),
    # "You won't find this anywhere else." — an exclusivity claim about THEIR material that reads,
    # under our brand, as a claim about ours. It is never a statement of fact we can stand behind.
    ("exclusivity_claim", re.compile(
        r"\byou\s+(?:won'?t|will\s+not|can'?t|cannot|wont)\s+(?:find|see|get|hear)\s+"
        r"th(?:is|ese|at|ose)\b", re.IGNORECASE)),
    # A first-person achievement claim — "I made $12k with this", "we grew it to 40k followers".
    # Two guards keep it narrow: the pronoun is matched CASE-SENSITIVELY (a bare lowercase "i" is
    # an ordinary Czech conjunction, and IGNORECASE here would fire on half of every Czech
    # caption), and a money or metric token must appear within the same clause. Without the
    # number it is prose about the author's work; with it, it is a result our audience is being
    # invited to attribute to us.
    ("first_person_claim", re.compile(
        r"(?:\bI\b|(?i:\bwe\b))\s+(?i:made|earned|grew|built|scaled|generated|hit|added|took)\s"
        r"[^.!?\n]{0,60}?"
        r"(?:[$€£]\s?\d|\d[\d.,]*\s*(?i:k\b|m\b|%|followers|subscribers|clients|customers|"
        r"users|views|leads|sales|revenue))")),
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

#: The three copy contracts an operator may choose between for a BOUND carousel deck (D54/FR-331
#: and D62/FR-353, config key `run.carousel_copy_mode`). `verbatim` is the engine-wide default and
#: is what every other creative in the run uses whatever this says — the mode reaches exactly one
#: predicate, `_compress_wanted`, and that predicate additionally requires `_panel_mapped`.
MODE_VERBATIM = "verbatim"
MODE_COMPRESS = "compress"
#: D62/FR-353 — compress the OVERFLOWING panels of a bound deck and quote the rest. The three
#: shipped brand configs pin it, because it pays a model only for the panels that could not fit
#: the style's own slide budget and leaves every panel that already fitted byte-verbatim. A deck
#: with nothing over budget takes the ordinary verbatim path and issues no compress call at all,
#: which is why this mode can be the shipped default in a way `compress` never should have been.
MODE_AUTO = "auto"
#: D63/FR-345 — `run.copy_language_mode`'s two values, the LANGUAGE axis beside the LENGTH axis
#: above. `source` keeps every bound deck in its post's own language (the pre-D63 behaviour, byte
#: for byte); `target` translates a bound deck whose known source language differs from its
#: platform's configured language (`entry.language`). Orthogonal to `MODE_*` on purpose: a
#: translated deck that compressed nothing is `copy_mode: verbatim, copy_language: target`.
LANGUAGE_SOURCE = "source"
LANGUAGE_TARGET = "target"
#: The compress call's own template (FR-332). Rendered exactly the way the verbatim call renders
#: `copywriter_system.md`, through the same engine and the same allowlist mechanism; a missing or
#: unresolvable template warns `copy_prompt_failed` and the group falls to `_mapped_fallback`,
#: which is the verbatim mapped deck — a failure of the compress path never costs a deck its words.
_COMPRESS_TEMPLATE = "copy_compress_system.md"
_COMPRESS_CARRIER_TURN = "Return the compression JSON for the creatives listed above now."
#: The TRANSLATE call's own template (D63/FR-344), rendered through the same engine and the same
#: allowlist mechanism as the other two copy contracts. Its failure door is theirs as well —
#: `copy_prompt_failed` -> `{}` -> `_mapped_fallback`, the verbatim mapped deck — so a missing or
#: unresolvable template costs the deck its LANGUAGE and never its words.
_TRANSLATE_TEMPLATE = "copy_translate_system.md"
#: Singular ("the creative", not "the creatives") because a translate call carries exactly one
#: creative by contract: one section per deck is what keeps a deck's own panels its own, and
#: `_write_group` issues one call per translating entry rather than grouping them (D63, plan 9g).
_TRANSLATE_CARRIER_TURN = "Return the translation JSON for the creative listed above now."
#: The English name printed beside a two-letter code in the translate work order's header, for the
#: languages this operator's platforms are configured in and their near neighbours. It is a
#: COURTESY to the model, never a lookup the engine depends on: an unknown code prints as itself
#: (`"tr"` -> `"tr (tr)"`), which is still an unambiguous ISO 639-1 instruction. Deliberately not
#: a full ISO table — a hundred rows nobody has ever rendered would be dead weight in a module
#: whose one job is not to guess about languages.
_LANGUAGE_NAMES = {"en": "English", "cs": "Czech", "de": "German", "fr": "French",
                   "es": "Spanish", "it": "Italian", "pt": "Portuguese", "pl": "Polish",
                   "nl": "Dutch", "sk": "Slovak"}
#: D63/FR-343 — the length-ratio audit's two bounds. A translation is EXPECTED to change length
#: (German compounds shrink into English, English expands into Czech), so the question is never
#: "is it the same length" but "is it plausibly the same content": under half or over twice is the
#: band where a line stops looking like a translation and starts looking like a summary or a
#: hallucination. Both ship — this is an audit with A20's polarity, not a gate.
_DRIFT_FLOOR = 0.5
_DRIFT_CEILING = 2.0


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
         "drop_reason": "contains_handle_or_url", "creator_stripped": False,
         "truncation_suspect": False, "compressed": False, "translated": False}

    The row is the alignment. A deck that dropped its empty rows would tell the gallery that our
    slide 3 came from their slide 4, which is the precise failure FR-304 is written against.

    `source_text` is what SHIPPED onto our slide and `source_text_original` is the panel as it
    arrived — identical on every slide that rendered, and different exactly where `drop_reason`
    is non-empty OR `creator_stripped` is true. Keeping both is what makes the provenance honest:
    the previous shape recorded a dropped panel as `source_text: ""`, which reads as "their slide
    was blank too" and destroyed the operator's ability to see what a blank slide of ours had cost
    (audit of run 20260813_143420_oyo4). `drop_reason` is `""` on a slide that shipped, else
    `empty`, `contains_handle_or_url` or `over_budget`.

    `truncation_suspect` (FR-304c) is the seventh key and the only one that is a QUESTION rather
    than a record: the admitted panel ends in a way that reads as cut (ellipsis, hanging hyphen,
    mid-word stop). The slide shipped in full regardless — the flag exists so the post-render
    critic, which can see the frame, can settle what a heuristic cannot.

    `creator_stripped` (FR-312) is the fifth key and the one that can be true on a slide that
    SHIPPED: the panel named its own creator — a brand header, a chrome echo — that line was
    dropped and the remainder rendered. It is a per-row fact rather than a drop reason precisely
    because the slide is usually still full of words.

    `copy_mode` (FR-73/FR-331, v2.3.0) says WHICH copy contract produced this creative —
    `"verbatim"`, `"compress"` or, since D62/FR-353, `"auto"` — and it is per ASSET rather than
    per run on purpose: compress and auto reach only the bound panel-mapped carousels of a run, so
    an image, a reel, an override brief and a deck that fell back to `_mapped_fallback` all still
    report `verbatim`, which is exactly what each of them shipped. It is the receipt that replaces
    the byte-substring audit on a compressed creative (`_verify` skips half 1 when nothing was
    quoted), together with each panel-map row's `compressed` flag and its `source_text_original`.

    `"auto"` is the MIXED receipt and the one a reader must not treat as mode equality (D62): that
    deck quoted the panels that fitted its style's slide budget and compressed only the ones that
    did not, so the rows disagree with each other BY DESIGN and each row's own `compressed` flag —
    never this field — says which half a given slide belongs to. `refs` on an auto creative holds
    the quoted rows' real labels, which is why `_verify` audits those rows for real instead of
    self-skipping.

    `translated` (D63/FR-343/FR-346) is the eleventh key and the LANGUAGE half of the same row —
    True only where the shipped text is the model's translation of `source_text_original`. It is
    written on every row of every walk (`False` by construction on the verbatim, compressed and
    auto ones), for the same "one row schema always" reason `compressed` is, and it is per ROW
    rather than per creative because a translated deck under auto mode can carry a row that was
    translated and then compressed, a row that was only translated, and a row whose source panel
    was dropped before either could touch it.
    """

    post_id: str = ""
    refs: dict[str, str] = field(default_factory=dict)
    panel_map: list[dict[str, Any]] = field(default_factory=list)
    source_panel_count: int = 0
    copy_mode: str = MODE_VERBATIM
    #: D63/FR-346 — the LANGUAGE receipt, orthogonal to `copy_mode` (the LENGTH receipt above).
    #: `"target"` ONLY when a translation actually shipped on this deck (`_translated`); every
    #: other path — a `source`-mode run, a post already in the platform's language, an unknown
    #: language, a translate call that failed and fell back to the verbatim mapped deck — says
    #: `"source"`, because that is the language the bytes on the slides are in.
    copy_language: str = LANGUAGE_SOURCE
    #: D63/FR-346 — the language ladder's answer for the bound post (`SourcePost.language` from
    #: Virlo, else the vision pass's deck-level reading, else `""` = unknown), recorded on EVERY
    #: bound deck where it is known, in both modes, so `meta.yaml` can say what language a deck
    #: that was NOT translated is in. Two-letter ISO 639-1 code.
    source_language: str = ""


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
    brand_marks: Mapping[str, Sequence[str]] | None = None,
    burnt_post_ids: Sequence[str] = (),
    carousel_copy_mode: str = MODE_VERBATIM,
    copy_language_mode: str = LANGUAGE_SOURCE,
    post_languages: Mapping[str, str] | None = None,
    topic_languages: Mapping[str, str] | None = None,
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
        brand_marks: `post_id -> the logos, wordmarks and watermarks the vision pass saw on that
            deck` (`SlideIntel.slides[*].brand_marks`, FR-306), keyed by post like `chrome_lines`
            and for the same reason. Read by ONE thing — D65/FR-362's guard 9 — and used to answer
            ONE question: is a contract row nothing but somebody's wordmark? A slide whose whole
            text is `OPAL COLLECTION` (an incidental tote bag in the source photo) or `EVOLVING AI`
            (the creator's own watermark) is chrome the source stamped on its own slide, and
            shipped into `panel_map.source_text` it becomes an ORDER: run 4344 drew that watermark
            as a hero headline in our brand colour and then CHOSE that frame as the cover, because
            `cover_pick` reads the same contract. Omitted, guard 9 simply has no vocabulary and
            stays silent; every other guard is unaffected.
        burnt_post_ids: post ids this run may not quote — the used-post set the fetch gate already
            filtered on (FR-305/FR-307). Belt-and-braces, and deliberately redundant: an entry
            whose bound post turns up here is refused outright (assembled caption, wordless frame,
            `reason="no_fresh_post_available"` in the log) rather than re-pointed at a neighbour,
            because the alternative is a creative whose provenance, history record and panel map
            all name different posts.
        carousel_copy_mode: `"verbatim"` (default), `"auto"` or `"compress"` —
            `config.run.carousel_copy_mode`, D54/FR-331 and D62/FR-353. It is an OPERATOR TOGGLE
            and never a heuristic: nothing in this module may switch compression on for a run the
            operator did not put in one of the two compressing modes. (`auto` DOES measure a panel,
            and that is not a contradiction — the operator chose the rule "compress what overflows"
            and the engine applies it; what it may never do is apply that rule to a `verbatim`
            run.) It reaches exactly one predicate (`_compress_wanted`), which additionally
            requires `_panel_mapped`, so an unrecognised value simply behaves as `verbatim` here —
            the refusal for a bad value belongs to config load, where `Literal` validation catches
            it before the run costs anything.
        copy_language_mode: `"source"` (default) or `"target"` — `config.run.copy_language_mode`,
            D63/FR-343/FR-345. Under `target` a BOUND, panel-mapped deck whose post is in a known
            language other than its platform's configured one (`entry.language`) takes ONE
            translate call of its own (`_translate_wanted`, `_call_translate`); everything else —
            a post already in the target language, an unknown language, images, reels, override
            briefs, unbound decks — is untouched and byte-identical to a `source` run. An operator
            toggle exactly like `carousel_copy_mode`; an unrecognised value behaves as `source`
            here and is refused at config load.
        post_languages: `post_id -> deck-level language code` from the slide-intelligence pass
            (`SlideIntel.language`, FR-306 as amended) — rung 2 of the language ladder, read only
            when Virlo's own `SourcePost.language` is empty. Keyed by post like `merged_panels`,
            for the same reason. Omitted, rung 2 is simply unknown.
        topic_languages: `trend_key -> language code` from the FR-294 topic screen's own verdicts
            (`topic_filter.Verdict.language`) — rung 3, read only when rungs 1 and 2 both came
            back empty. It exists because under `target` mode the screen's LANG skip is switched
            off: a topic the screen read as German is deliberately let through Select, and with no
            Virlo code and no vision reading behind it that deck used to reach COPY as "unknown"
            and ship German pixels. The screen's reading is evidence this run already paid for.
            Keyed by TOPIC rather than by post, which is also why it is the last rung — one topic
            can hold posts in two languages. Omitted, rung 3 is simply unknown.
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
               chrome_lines=chrome_lines or {}, brand_marks=brand_marks or {},
               burnt_posts=frozenset(str(post_id) for post_id in burnt_post_ids
                                     if str(post_id).strip()),
               carousel_copy_mode=str(carousel_copy_mode or MODE_VERBATIM),
               copy_language_mode=str(copy_language_mode or LANGUAGE_SOURCE),
               post_languages=dict(post_languages or {}),
               topic_languages=dict(topic_languages or {}), log=log)
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
    #: D65/FR-362 guard 9 — `post_id -> the vision pass's `brand_marks` for that deck` (every logo,
    #: wordmark and watermark it could see, FR-306). Read by `_guarded` alone, and only to answer
    #: one question: is this ROW nothing but somebody's wordmark? A slide whose entire text is
    #: `OPAL COLLECTION` off an incidental tote bag, or `EVOLVING AI` off the creator's own
    #: watermark, is chrome the source stamped on its slide — never our creative's words.
    brand_marks: Mapping[str, Sequence[str]] = field(default_factory=dict)
    burnt_posts: frozenset[str] = frozenset()  # post ids an earlier run already quoted (FR-307)
    #: D54/FR-331 and D62/FR-353 — `verbatim` (default), `auto` or `compress`. Run-scoped because
    #: the operator sets it once per run; consumed per CREATIVE by `_compress_wanted`, which is the
    #: only reader, and per ROW after that on the `auto` path.
    carousel_copy_mode: str = MODE_VERBATIM
    #: D63/FR-343/FR-345 — `source` (default) or `target`: whether a BOUND deck whose post is in a
    #: language other than its platform's configured one is TRANSLATED (`target`) or quoted in the
    #: post's own language (`source`). Run-scoped like `carousel_copy_mode`; consumed per CREATIVE
    #: by `_translate_wanted`, the only reader.
    copy_language_mode: str = LANGUAGE_SOURCE
    #: D63/FR-343 rung 2 of the language ladder — `post_id -> the vision pass's deck-level
    #: language code` (`SlideIntel.language`, FR-306 as amended). Read by `_source_language` after
    #: `SourcePost.language` (rung 1, Virlo) came back empty; `""`/absent means unknown.
    post_languages: Mapping[str, str] = field(default_factory=dict)
    #: D63/FR-343 rung 3 — `trend_key -> the FR-294 topic screen's own reading of that topic's
    #: language` (`topic_filter.Verdict.language`). The weakest rung and the last one, because it
    #: is a judgement about a TOPIC's strings rather than about the bound post's own slides: two
    #: posts inside one topic can be written in different languages, which is the whole reason
    #: `off_language_post` exists. It is here because under `target` mode the screen's LANG skip
    #: is switched off, so a topic the screen read as German goes through and — with no Virlo
    #: reading and no vision reading — used to reach COPY as "unknown" and ship German pixels
    #: with `translate_language_unknown`. A reading this run already paid for is better evidence
    #: than none.
    topic_languages: Mapping[str, str] = field(default_factory=dict)
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
    #: 1-based positions a PAGE COUNTER line was dropped from at admission (F2, Session 5.5). Its
    #: own set for the same reason as the one above: a counter is the source deck's furniture, not
    #: a competitor and not another creator's name, so it may not feed a flag that tags the
    #: creative `competitor_stripped`. Rides `panel_map.chrome_counter_stripped`.
    chrome_counter_panels: frozenset[int] = frozenset()
    #: 1-based positions whose ADMITTED text looks CUT rather than finished (`ocr_repair.
    #: truncation_suspect`). A flag and nothing else: the panel renders in full, keeps its
    #: position, and the boolean rides `panel_map.truncation_suspect` to the post-render critic,
    #: which can see the frame and tell an authored ellipsis from a clipped container (FR-304c).
    truncation_suspect_panels: frozenset[int] = frozenset()
    #: This post's own lines, ranked, that may stand in for a caption the post never offered —
    #: hooks first, then overlays, then panels, each as POST-STRIP bytes and each free of social
    #: marks. Ordered by how caption-like the kind is rather than by length: a hook is written to
    #: be read on its own, a panel is one slide out of a sequence. Consumed by `_offer_caption`
    #: (FR-99/FR-307 caption forms) and by nothing else.
    caption_fallbacks: tuple[str, ...] = ()
    #: The author terms `_offer_for` built for THIS post's caption strips, kept so a promoted line
    #: (above) faces the same caption-scoped scrub the post's own caption would have faced.
    caption_terms: tuple[str, ...] = ()
    #: §1.5 layer 3's COLLAPSED identifier keys for this post — the author's handle, their display
    #: name, this deck's chrome (`_creator_identifiers`). Kept on the offer (D65/FR-362) because
    #: the contract guards need the same vocabulary layer 3 used and must not build a second one:
    #: a guard that restored `source_text_original` restored the PRE-layer-3 bytes with it, creator
    #: header and all, and it re-runs exactly this strip over them before they become an order.
    creator_identifiers: tuple[str, ...] = ()
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

    This function is also the OCR repair boundary (FR-100/101 as amended, v2.2.0): every panel,
    hook and caption is admitted through `_repaired` before any strip runs, so one reading of the
    post reaches the table, the prompt, the verifier's pool and the panel map. The raw bytes
    survive in `panels_original`, and a panel that looks cut is flagged rather than touched.

    **FR-313's bare-numeral strip is CORROBORATED here, deck-wide, before the loop starts**
    (v2.7.0/D63, amended). `slide_intel.detect_counter` accepts a line that is only a numeral
    under rule 2 alone, and rule 2 needs the shape on at least TWO slides — a single stray
    numeral must never manufacture a counting convention. The admission strip is held to the same
    bar: `numbered_positions` surveys the pre-strip panels for lines that are nothing but their
    own slide's number, and only when two or more slides agree does the loop below pass its
    ordinal down to `_strip_counter_lines`. Otherwise the position is withheld and the bare shape
    is switched off for the whole deck. Without that survey a countdown panel whose entire text is
    the numeral `1` on slide 1 would be emptied at admission and render as a wordless slide beside
    a source slide that had words — the exact FR-304 failure the counter strip was added to
    prevent, arriving from the other direction. The paired and prefix counter shapes are outside
    this gate entirely: they carry their own evidence and never asked for a position.
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
    chrome_cut: set[int] = set()       # panels a page-counter line was dropped from (F2)
    counter_hits: list[str] = []       # the counter lines themselves, for the one WARN below
    hits: list[tuple[str, str, str]] = []  # (dropped line, identifier, channel) — the FR-312 log
    caption_named = False  # the caption said the creator's name and layer 3 took it out
    haystack: list[str] = []
    suspect: set[int] = set()          # panels that look CUT rather than finished (flag only)
    promotable: dict[str, list[str]] = {"hook": [], "overlay": [], "panel": []}
    # FR-313's bare-numeral CORROBORATION, computed once over the whole deck before a single line
    # is stripped. `detect_counter` accepts a lone numeral only under rule 2 and only when at
    # least two slides carry their own position that way, and the strip below has to hold itself
    # to the same bar: a countdown panel whose entire text is the word-less number `1` would
    # otherwise be emptied at admission and render as a wordless slide, which is the FR-304
    # failure this engine exists to prevent. Two matching positions is a convention; one is a
    # slide about a number. Read off the PRE-strip panels because that is the deck as the source
    # typeset it, and no strip layer edits digits anyway.
    numbered_positions = {ordinal for ordinal, panel in enumerate(panels, start=1)
                          if any(bare_numeral_position(line) == ordinal
                                 for line in str(panel or "").split("\n"))}
    bare_corroborated = len(numbered_positions) >= 2
    for kind, raw, ordinal in _numbered_fields(post, panels):
        # THE SANCTIONED ADMISSION BOUNDARY (FR-100/101 as amended, v2.2.0). The repair happens
        # here, once, BEFORE every strip and every table — so the candidate table, the prompt, the
        # verifier's pool and the panel map all quote the same bytes. Repairing further downstream
        # would leave two readings of one panel and report our own repair as a deviation.
        admitted = _repaired(raw, kind=kind, ordinal=ordinal, asset_id=entry.asset_id,
                             post_id=str(post.post_id), log=run.log)
        text, stripped = _apply_strip(admitted, brands)
        if kind == "panel":
            # `source_text_original` is the RAW panel (doctrine: the unrepaired bytes always
            # survive in provenance), minus only the competitor strip — a blocklisted name may not
            # reach meta.yaml either. Identical to `text` on every panel nothing repaired.
            pre_creator[ordinal - 1] = (_apply_strip(raw, brands)[0] if admitted != raw else text)
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
            # CHROME, LAST STRIP BEFORE THE TABLES (F2, Session 5.5). A page counter typeset on
            # its own line — `01 / 06`, `2 of 7`, `// 03` — is the source deck's furniture, and
            # Virlo hands it over as copy because its adapter has no `chrome_text` field to split
            # it into. Left in, it becomes our slide's words, then `panel_map.source_text`, then a
            # line of the frame contract the gauntlet expects to SEE rendered — and the deck is
            # blocked for `missing_text` because the renderer rightly never drew the source's page
            # number. It is dropped HERE, above both `kept[]` and `haystack.append` below, so the
            # panel map, the render prompt and the FR-100/101 verifier's pool hold identical
            # bytes; a strip on one side of that pair alone is how a run false-flags itself
            # `copy_not_verbatim`. `pre_creator` was captured further up and KEEPS the counter —
            # provenance records what the source said, never what we admitted.
            # `position=ordinal` is what admits FR-313's BARE-NUMERAL shape (v2.7.0/D63): this
            # loop is the only place in the engine that knows which source slide a panel line was
            # transcribed from, and a lone `01` is chrome only when it equals its own slide's
            # number. Everywhere else the default `0` keeps the shape switched off — and so does
            # `bare_corroborated` above, which withholds the position on a deck where only ONE
            # slide carries its own number. That is rule 2's two-slide bar, mirrored here so the
            # detector and the strip agree: a deck the detector will not call counted is a deck
            # this strip may not empty a panel over. The paired (`01 / 06`) and prefix (`// 03`)
            # shapes are unaffected — they carry their own evidence and never needed a position.
            text, counters = _strip_counter_lines(
                text, position=ordinal if bare_corroborated else 0)
            if counters:
                chrome_cut.add(ordinal)
                counter_hits.extend(counters)
            kept[ordinal - 1] = text  # empty when the whole panel WAS the brand: a wordless slide
            if stripped:
                cut.add(ordinal)
            if creator_dropped:
                creator_cut.add(ordinal)
            if truncation_suspect(text):
                # A FLAG and nothing more (FR-304c): the panel ships in full, in its own position.
                # Blanking it would re-map the deck on a heuristic's say-so, which is a worse
                # defect than any transcription cut it might be reporting.
                suspect.add(ordinal)
        if not text.strip():
            continue  # the whole string WAS the brand — there is nothing left to quote
        haystack.append(text)
        if kind in promotable and not _social_mark(text):
            # Caption material of last resort (FR-99/FR-307 caption forms): the post's own words,
            # already through layers 1 and 3, and free of anything that would put another
            # account's identity or funnel in our caption. Nothing is decided here — `_offer_for`
            # merely records what WOULD be quotable if this creative ends up with no caption.
            promotable[kind].append(text)
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
    offer.chrome_counter_panels = frozenset(chrome_cut)
    offer.truncation_suspect_panels = frozenset(suspect)
    offer.caption_fallbacks = tuple(dict.fromkeys(
        [*promotable["hook"], *promotable["overlay"], *promotable["panel"]]))
    offer.caption_terms = tuple(own_name)
    offer.creator_identifiers = tuple(creators)  # D65/FR-362 — layer 3's keys, for the guards
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
    if chrome_cut:
        # One line per creative, like the FR-312 warning above and for the same reason: the same
        # badge sits on every panel of a numbered deck. Deduped in the prose, counted in full, and
        # deliberately NOT folded into `competitor_stripped` — nobody's brand was removed here.
        _warn(run.log, "panel_counter_stripped",
              f"{entry.asset_id}: a page counter was DROPPED from {len(chrome_cut)} panel(s) of "
              f"post {post.post_id} at admission (F2) — "
              + "; ".join(repr(line) for line in dict.fromkeys(counter_hits))
              + f" on slide(s) {', '.join(str(n) for n in sorted(chrome_cut))}. The counter is the "
                "source deck's chrome, not its words: rendered onto our slide it signs our deck "
                "with their page numbering, and expected as a contract line it blocks a render "
                "that correctly left it out. FR-313 still prints OUR own counter, re-based onto "
                "this deck's length. The rest of each panel ships byte-verbatim and every panel "
                "keeps its position; the counter itself survives in "
                "`panel_map.source_text_original`",
              asset_id=entry.asset_id, post_id=str(post.post_id),
              lines=list(dict.fromkeys(counter_hits)), slides=sorted(chrome_cut))
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


#: The kinds that pass through the OCR repair boundary (FR-100/101 as amended, v2.2.0). Panels and
#: hooks are the two channels a vision pass writes into (`sources.slide_intel` merges its
#: transcription into the panel payload, FR-306) and a caption arrives on the same OCR-ish path
#: from Virlo's own extraction. `overlay` is deliberately absent: the plan's repair boundary names
#: captions, hooks and the merged panel payload, and widening the boundary is a decision that owes
#: the FR-100 verifier a re-examination rather than a quiet extra row here.
_REPAIRED_KINDS = ("panel", "hook", "caption")


def _repaired(raw: str, *, kind: str, ordinal: int = 0, asset_id: str, post_id: str,
              log: Any) -> str:
    """One candidate string, admitted — repaired if it carries an OCR confusable, else unchanged.

    The ONE sanctioned mutation on the verbatim path (`ocr_repair`'s module contract, and FR-100/
    101 as amended in v2.2.0). "5 Al agents that replaced my stack" is not what the slide said and
    it is not what the operator paid to publish; the repair is uppercase-token-scoped, word-bounded
    and logged, and the bytes it returns are the bytes EVERYTHING downstream sees — the candidate
    table, the render prompt, `panel_map.source_text` and the verifier's pool alike. Applying it to
    one of those and not the others is the failure mode the single boundary exists to prevent.

    Every correction is reported (`ocr_repaired`) with its site, because a repair the operator
    cannot point at afterwards is indistinguishable from the drift this module exists to stop. The
    unrepaired bytes stay reachable: `panel_map.source_text_original` records them per row.
    """
    if kind not in _REPAIRED_KINDS:
        return raw
    text, corrections = repair_confusables(raw)
    if not corrections:
        return raw
    where = f"{kind}.{ordinal}" if ordinal else kind
    _warn(log, "ocr_repaired",
          f"{asset_id}: {len(corrections)} OCR confusable(s) repaired in {where} of post "
          f"{post_id} before it was admitted (FR-100/101, the one sanctioned transform) — "
          + "; ".join(f"{c.before!r} -> {c.after!r} at character {c.index}" for c in corrections)
          + ". The repaired bytes are what the prompt, the panel map and the verbatim verifier all "
            "see; the raw string is kept in the panel map's source_text_original",
          asset_id=asset_id, post_id=post_id, field=where,
          corrections=[{"before": c.before, "after": c.after, "index": c.index}
                       for c in corrections])
    return text


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

    - **author** — `SourcePost.author` (the handle, `@` and all; the collapse eats the `@`) and
      `SourcePost.author_name`, the DISPLAY form. Both are read as real fields since v2.2.0: the
      display name existed in this predicate's intent from the start but never in the data, and
      the 08-14 audit measured the consequence — "Emir | AI Lab" shipping untouched beside a
      scrubbed "@emirailab". An empty `author_name` is legitimate (an API that exposes none) and
      simply leaves the handle carrying layer 3 on its own.
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
    names = [str(post.author or ""), str(post.author_name or "")]
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

    The MECHANICS moved to `contract_guard.strip_lines_equal` with D65/FR-362 and this function is
    now its caller. Not a tidy-up: the contract guards re-run this exact strip over rows they
    RESTORED from `source_text_original` (which is the pre-layer-3 panel, creator header and all),
    and a second implementation of "drop the lines that equal an identifier" is precisely how the
    two would come to disagree about which lines those are — the same argument
    `sources/mark_names` was extracted on. The signature, the semantics and the same-object
    return are unchanged; layer 3's own vocabulary stays here, where its callers read it.
    """
    if not text or not identifiers:
        return text, False
    out, dropped = strip_lines_equal(text, identifiers)
    return out, bool(dropped)


def _strip_counter_lines(text: str, *, position: int = 0) -> tuple[str, list[str]]:
    """`(the panel without its page-counter lines, the lines that went)` — F2, Session 5.5.

    Layer 3's sibling in mechanics and its opposite in subject: same whole-line rule, same
    byte-preserving join, but the predicate is `sources.slide_intel.counter_line` — SHAPE rather
    than identity, because a page counter names nobody. It matches only a line that is a counter
    edge to edge, so a panel whose words merely contain a ratio ("3/4 of teams fail at this")
    keeps every character.

    Why a counter may not become our slide's words, twice over. It is the SOURCE deck's page
    number: printed on our deck it signs a five-slide carousel "01 / 06" (their length, on our
    frame), and FR-313 already re-bases their counting convention onto OUR length for exactly that
    reason. And once it is in the panel map it is also in the frame contract the post-render critic
    verifies, so the gauntlet demands a line the renderer was right to omit — the false
    `missing_text` BLOCK that cost Session 5's Ig deck.

    Everything that survives survives byte for byte (the kept lines are the original strings), and
    only blank lines the removal orphaned at the very top or bottom go with it — a blank line
    BETWEEN two kept lines is part of the panel's shape. A panel that was ONLY its counter comes
    back empty and renders wordless in its own position, which is FR-304's rule for every empty
    panel and not a special case here.

    **`position` unlocks the BARE-NUMERAL shape (FR-313, v2.7.0/D63).** A line that is nothing but
    `01` carries no evidence of its own that it is chrome — a `5` on a slide can be the whole
    point of the slide — so `counter_line` accepts that shape only when the caller says which
    slide the line came from and the numeral EQUALS that slide's 1-based position. `_offer_for`
    knows the position (it is walking the deck by ordinal) and passes it — but only on a deck
    where at least TWO slides carry their own number that way, which is rule 2's corroboration
    mirrored at admission; on any other deck it passes `0` and the bare shape is off. Every other
    caller, and the default, leaves it at `0`, which switches the shape off entirely. Run
    `20260820_234620_j867` is what this is written against: `01`…`07` sat on their own line on all
    seven panels of a bound deck, shipped into `panel_map.source_text` and into the gauntlet's
    frame contract, and the counter detector recorded `detected: false` because no paired form
    was ever present. A panel reading `"5 tools I use\\nto ship faster"` at position 5 keeps every
    byte — the numeral there is not alone on its line.
    """
    if not text:
        return text, []
    lines = text.split("\n")
    dropped = [line for line in lines if counter_line(line, position=position)]
    if not dropped:
        return text, []
    kept = [line for line in lines if not counter_line(line, position=position)]
    while kept and not kept[0].strip():
        kept.pop(0)
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept), [line.strip() for line in dropped]


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
    - `SourcePost.author_name`, the creator's DISPLAY name, when the adapter carries one — the
      form a caption actually writes ("Emir | AI Lab"), and the one this pass was blind to until
      the field existed (v2.2.0);
    - **the DISPLAY form found on the deck** — any panel, hook or overlay line whose collapsed
      form is an AUTHOR identifier. That is where "EMIR AI LAB" comes from: the handle alone would
      not remove it, because the spaces make it three words at word boundaries.

    CHROME identifiers are deliberately excluded. "Swipe" is an ordinary word in a caption, and a
    caption is not pixels — removing it would cost the operator a legitimate sentence to solve a
    problem that only exists inside the frame.
    """
    terms: list[str] = []
    handle = str(post.author or "").strip().lstrip("@").strip()
    name = str(post.author_name or "").strip()
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

    This is the REPORTING door. `_without_cta` below is the same removal with no log, and the
    degrade tier's `_scrubbed` goes through it so the pool the verifier checks and the caption it
    ships are built by one expression (v2.2.0 — a scrub applied to one and not the other reports a
    successful strip as `copy_not_verbatim`).
    """
    hits = [(part, name) for part in _sentences(text) if (name := _cta_pattern(part))]
    for sentence, pattern in hits:
        _warn(log, "caption_cta_stripped",
              f"{asset_id}: the caption sentence {' '.join(sentence.split())!r} was removed — it "
              f"is the source creator's own call to action ({pattern}), addressed to a funnel that "
              f"is not ours (post {post_id}, FR-312). The rest of the caption ships verbatim",
              asset_id=asset_id, post_id=post_id, sentence=" ".join(sentence.split()),
              pattern=pattern)
    return _without_cta(text)


def _without_cta(text: str) -> str:
    """The CTA/promo removal itself — pure, silent, and the ONLY implementation of it.

    Both callers must produce identical bytes or `_verify` turns a successful strip into a
    `copy_not_verbatim` tag on a creative that did exactly the right thing, so the removal lives
    here once and `_strip_cta` (loud) and `_scrubbed` (silent, pool-side) both call it. A caption
    nothing matched comes back byte-identical.
    """
    parts = _sentences(text)
    if not any(_cta_pattern(part) for part in parts):
        return text
    kept = [" ".join(part.split()) for part in parts if not _cta_pattern(part)]
    return " ".join(part for part in kept if part)


def _sentences(text: str) -> list[str]:
    """A caption split into the units the CTA gate judges — sentences, and lines as sentences."""
    return [part for part in _CAPTION_SENTENCE.split(text) if part is not None]


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
    """`text` through the admission repair and §1.5 layers 1 and 3, for the paths with no offer.

    One expression, so the caption a degrade tier ships and the pool the verifier checks it
    against can never be built two different ways — that mismatch is how a successful strip gets
    reported as a verbatim deviation.

    The OCR repair leads, exactly as it does at `_offer_for`'s boundary: this function IS the
    admission boundary for the tier that has no offer table, so pool and product are repaired
    together or the repair becomes the deviation (FR-100/101 as amended). It is idempotent, so a
    caller that has already logged the corrections it found may call this over the same bytes.

    `caption=True` adds FR-312's fuzzy pass AND the CTA/dangling-promo sentence removal, and ONLY
    the caller that is building a caption may ask for them: the fallback tier runs this function
    over every quotable kind to build the verifier's pool, and either pass applied to a panel there
    would be a rule this codebase does not have. Both are silent by design — `_fuzzy_caption` and
    `_strip_cta` are the reporting doors, and the pool must not warn about a string nobody ships.
    """
    out, _ = repair_confusables(text)
    out, _ = _apply_strip(out, brands)
    out, _ = _strip_creator_lines(out, _creator_identifiers_from(creator_terms))
    out, _ = _apply_strip(out, creator_terms)
    if caption:
        out, _ = fuzzy_strip(out, creator_terms)
        out = _without_cta(out)
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
    - **Compress** (D54/FR-331, opt-in): the bound panel-mapped decks of a `compress`-mode run.
      Source panel strings in, compressed strings out, resolved by `_compressed` here.
    - **Auto** (D62/FR-353, and what the shipped brand configs pin): the same call and the same
      template, carrying ONLY the panels that overflowed their deck's slide budget, resolved by
      `_auto` here — which builds the verbatim mapped deck first and splices the answers into the
      overflowing positions alone. A deck with nothing over budget never reaches this partition:
      `_compress_wanted`'s auto arm is false for it, so it sits in `selecting` and takes the plain
      verbatim path, byte for byte.
    - **Translate** (D63/FR-343, `run.copy_language_mode: "target"`): a bound panel-mapped deck
      whose post is in a known language other than its platform's. It is a PIPELINE rather than a
      shape — `_translate_and_fit` makes the translate call, and under auto or compress it then
      makes ONE follow-up compress call on the TRANSLATED strings — and it is resolved by
      `_translated` here. One pipeline per creative, never grouped.

    A creative whose bound post was refused (burnt or absent, FR-307) is in neither shape: it is
    left OUT of the call entirely — there are no candidates to offer and no words to ask for, so
    asking would spend tokens on an answer we would have to discard — and it is written
    deterministically by `_refused` afterwards.

    **The mode SPLIT (D54).** `askable` is partitioned by `_compress_wanted` and each partition
    takes its own call, concurrently. Two calls rather than one combined schema because
    `copywriter_system.md` is a reference-SELECTION mandate end to end ("there is no slot in your
    answer where invented lettering can go"), and half a group being asked to compress would make
    that instruction false for the other half; because the two failures should be independent (a
    compress call that dies must not cost a sibling image its headline); and because it costs
    nothing where it matters — the shipped configs are all-carousel, so a compress-mode group is
    a PURE compress partition and still exactly one call. `budget._llm_lines` prices one copy call
    per (topic × language); a genuinely MIXED group is the one shape that issues two, which is why
    the estimator carries a note about it.

    **The LANGUAGE partition is taken FIRST (D63).** `translating` is computed before
    `compressing` and `compressing` excludes it, so a deck that is being translated is never also
    in the group's shared compress call: it runs its own two-stage pipeline, and the compress
    stage of that pipeline measures the TRANSLATED strings rather than the source panels. That
    ordering is the whole of FR-343's "translate before the budget test" — budgeting a German
    panel and then translating it into English would compress the wrong rows. The estimator
    prices one extra copy call per translating deck for exactly this reason (§9 of the D63 plan).
    """
    offers = {entry.asset_id: _offer_for(entry, group, run) for entry in group.entries}
    askable = [entry for entry in group.entries if not offers[entry.asset_id].refused]
    verbatim = any(offers[entry.asset_id].post is not None for entry in askable)
    # D63/FR-343: the LANGUAGE partition is taken FIRST and the length partition is taken from
    # what is left, because a translating deck runs its own two-stage pipeline (translate, then —
    # under auto or compress — a follow-up compress call on the TRANSLATED strings) and must never
    # also appear in the group's shared compress call. `_translate_wanted` is the only predicate
    # here that warns, and it is called exactly once per creative for that reason.
    translating = {entry.asset_id for entry in askable
                   if _translate_wanted(entry, offers[entry.asset_id], run)}
    compressing = {entry.asset_id for entry in askable
                   if entry.asset_id not in translating
                   and _compress_wanted(entry, offers[entry.asset_id], run)}
    selecting = [entry for entry in askable
                 if entry.asset_id not in compressing and entry.asset_id not in translating]
    # D62/FR-353: `{asset_id: the 1-based positions whose ADMITTED panel overflows this deck's own
    # slide budget}`, computed ONCE here for the auto partition and threaded into the call (which
    # lists those positions alone) and, separately, recomputed by `_auto` from the same pure pair
    # of functions when the answer comes back. `None` outside auto mode is what keeps the compress
    # path byte-identical: `only=None` means "every admitted position", which is what it always
    # listed.
    auto_rows = ({entry.asset_id: _rows_over_budget(
        _admitted_texts(entry, offers[entry.asset_id]),
        offers[entry.asset_id].budgets.get("slide", 0))
        for entry in askable if entry.asset_id in compressing}
        if run.carousel_copy_mode == MODE_AUTO else None)
    calls = []
    if selecting:
        calls.append(_call_copy(group, selecting, run, offers, verbatim))
    if compressing:
        calls.append(_call_compress(
            group, [entry for entry in askable if entry.asset_id in compressing], run, offers,
            only=auto_rows))
    # ONE translate pipeline per translating creative (D63, plan 9g) — never grouped, because
    # `{{translate_panels}}` carries one section per creative and two decks in one call would be
    # two decks' panels on one page for a model that has just been told every panel is a content
    # authority. They are gathered ALONGSIDE the two group calls rather than after them: the
    # translate call and the selection call of the same group have no dependency on each other,
    # and serialising them would add a whole model round trip to every mixed group's wall clock.
    translating_entries = [entry for entry in askable if entry.asset_id in translating]
    outcomes = await asyncio.gather(
        *calls,
        *(_translate_and_fit(group, entry, run, offers) for entry in translating_entries))
    payloads: dict[str, dict[str, Any]] = {}
    for answered in outcomes[:len(calls)]:
        payloads.update(answered)
    translations: dict[str, _Translation] = {
        entry.asset_id: translation
        for entry, translation in zip(translating_entries, outcomes[len(calls):])}
    # A translating creative is deliberately OUTSIDE the FR-99 split: its payload never lands in
    # `payloads`, and a translate call that came back empty must not be re-asked as a selection or
    # a compression — those are different contracts and would answer for a deck whose slides are
    # already mapped. Its own failure path is `_mapped_fallback` plus `copy_not_translated`, below.
    if missing := [entry for entry in askable
                   if entry.asset_id not in payloads and entry.asset_id not in translating]:
        _warn(run.log, "copy_group_split",
              f"grouped copy call missed {len(missing)} of {len(askable)} creatives; "
              "splitting into one call each (FR-99)",
              asset_ids=[entry.asset_id for entry in missing])
        # Each creative is re-asked through ITS OWN contract: a compress creative that a grouped
        # compress call missed is re-asked to compress, never to select. Re-dispatching it through
        # `_call_copy` would answer with refs into a candidate table whose panels this deck's
        # slides are already assigned from, and the deck would silently ship verbatim under a
        # `copy_mode: compress` receipt.
        for split in await asyncio.gather(*(
                _call_compress(group, [entry], run, offers, only=auto_rows)
                if entry.asset_id in compressing
                else _call_copy(group, [entry], run, offers, verbatim)
                for entry in missing)):
            payloads.update(split)

    copies: dict[str, CopySet] = {}
    tags: dict[str, tuple[DegradationTag, ...]] = {}
    provenance: dict[str, CopyProvenance] = {}
    for entry in group.entries:
        payload = payloads.get(entry.asset_id)
        offer = offers[entry.asset_id]
        if offer.refused:
            written = _refused(entry, group, run, offer)
        elif entry.asset_id in translating:
            # D63/FR-343. The branch sits ABOVE the `payload is None` tier on purpose: a
            # translating creative's answer never enters `payloads` (it has its own pipeline and
            # its own `_Translation`), so leaving it below would send every translating deck down
            # the degrade path whether or not the call succeeded. Its failure is the SAME degrade
            # tier the other two contracts use — the verbatim mapped deck, tagged `copy_degraded`
            # — and it earns `copy_not_translated` on top of it a few lines further down.
            translation = translations.get(entry.asset_id)
            written = (
                _translated(entry, translation, offer, group, run)
                if translation is not None and translation.payload is not None
                else (_mapped_fallback(entry, offer, group, run)
                      if _panel_mapped(entry, offer) else _fallback(entry, group.trend, run)))
        elif payload is None:
            # FR-99 vs FR-304 ruling (D15, SESSION G): a BOUND deck's slides are a deterministic
            # panel mapping that needs no model, so a failed copy call must not cost it its words.
            # D54 rides this branch unchanged and deliberately: a failed COMPRESS call falls back
            # to the same verbatim mapped deck, tagged `copy_degraded`, with no second call and no
            # extra spend — long slides are the outcome the operator opted out of, not a loss of
            # the deck. D62's AUTO mode rides the identical branch for the identical reason, and
            # this IS auto's whole-call failure path: every row ships verbatim (the rows that
            # already fitted were going to anyway), the overflowing ones ship long, and
            # `copy_degraded` is the only receipt that changes.
            written = (_mapped_fallback(entry, offer, group, run)
                       if _panel_mapped(entry, offer) else _fallback(entry, group.trend, run))
        elif entry.asset_id in compressing:
            written = (_auto(entry, payload, offer, group, run)
                       if run.carousel_copy_mode == MODE_AUTO
                       else _compressed(entry, payload, offer, group, run))
        elif verbatim and offer.post is not None:
            written = _resolve(entry, payload, offer, group, run)
        else:
            written = _free_text(entry, payload, group, run)
        # D65/FR-362/FR-363 — the contract guards run HERE, on the finished copy of every path,
        # and before the verifier: `_guarded` may put the source's own bytes back on a row, and
        # `_verify` has to audit what actually ships. Two statements rather than one list so the
        # order is a fact of the code rather than of Python's argument evaluation.
        guarded = _guarded(written, entry, offer, run)
        earned = [*written.tags, *guarded, *_verify(written, entry, run)]
        # D63/FR-343 — the ONE place `copy_not_translated` is decided, and it is decided here
        # rather than inside each path so no future degrade branch can forget it: translation was
        # WANTED for this creative (it is in `translating`, which already required target mode, a
        # panel-mapped deck and a known foreign language) and the bytes that shipped are in the
        # source language anyway. `copy_language` on the finished provenance is the honest test —
        # only `_translated` ever sets `target`, and it sets it only when a translation shipped.
        if entry.asset_id in translating and written.source.copy_language != LANGUAGE_TARGET:
            earned.append(DegradationTag.COPY_NOT_TRANSLATED)
            _warn(run.log, "copy_not_translated",
                  f"{entry.asset_id}: this deck was going to be translated into "
                  f"{entry.language} and shipped in its source language instead — the translate "
                  "call returned nothing, so the creative fell back to the verbatim FR-304 "
                  "mapping of its source panels (FR-343); or the call landed and the model "
                  "answered that every panel was already written in the target language, so the "
                  "already-target backstop shipped the source bytes on every row and the deck "
                  "changed no words at all. Nothing was lost that the deck had: "
                  "every admitted panel still renders, in its own position, in the language its "
                  "author wrote it in. What is missing is only the translation, and a re-run "
                  "translates it — though when `translate_already_target` is beside this warning, "
                  "the model is claiming there was nothing to translate and the language ladder "
                  "is claiming there was, and a re-run will not settle that on its own",
                  asset_id=entry.asset_id, target_language=entry.language,
                  source_language=written.source.source_language)
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
    return _answers(result, entries)


def _compress_wanted(entry: PlanEntry, offer: _Offer, run: _Run) -> bool:
    """D54/FR-331 + D62/FR-353 — does THIS creative take the compress call instead of selection?

    Three arms, one per mode, and the mode is always the FIRST condition:

    - **`verbatim`** — never. D50's "reflow, never shorten" governs the whole run.
    - **`compress`** (D54) — every panel-mapped deck, whatever its panels measure. The run is in
      compress mode (an operator toggle, never a measurement — nothing here may look at how long a
      panel is and decide to compress a `compress`-mode deck differently), and the creative is
      already a panel-mapped deck by `_panel_mapped`'s three structural tests: a carousel, BOUND at
      ASSIGN, not an override brief.
    - **`auto`** (D62) — a panel-mapped deck that has AT LEAST ONE admitted panel over its own
      slide budget. This arm measures, and the measurement is not the engine deciding to compress:
      the operator chose the rule "compress what overflows" and this is where that rule is
      evaluated. A deck with nothing over budget answers False, lands in `_write_group`'s
      `selecting` partition, and takes the ordinary verbatim path (`_call_copy` → `_resolve` →
      `_mapped_deck`) — the same call, the same template, the same schema, the same bytes and
      `copy_mode: verbatim` on its provenance. **That byte-identity is FR-353's acceptance
      criterion**, which is why the arm is written as "is anything over budget" here rather than
      as a filter inside `_auto`: a deck that would compress nothing must not pay for, or be
      shaped by, a call it does not need.

    Everything else in a compressing run — images, reels, override briefs, unbound carousels, a
    topic that arrived with no posts — is untouched under both modes, because compression is a rule
    about a bound deck's own slides and those creatives have none.

    Riding `_panel_mapped` rather than restating its conditions is the point: the compress walk
    produces the same `panel_map` the verbatim walk does, so the two must agree exactly on WHICH
    decks are mapped or a run would ship a deck with a panel map under one contract and no rows
    under the other.
    """
    if run.carousel_copy_mode == MODE_COMPRESS:
        return _panel_mapped(entry, offer)
    if run.carousel_copy_mode == MODE_AUTO:
        return _panel_mapped(entry, offer) and bool(_rows_over_budget(
            _admitted_texts(entry, offer), offer.budgets.get("slide", 0)))
    return False


def _source_language(entry: PlanEntry, offer: _Offer, run: _Run) -> str:
    """D63/FR-343 — the LANGUAGE LADDER: what tongue this creative's bound post is written in.

    Four rungs, in order, and the first non-empty answer wins:

    1. **`SourcePost.language`** — Virlo's own `intelligence.language_detected`, normalised at the
       adapter by `topic_filter.language_code`. It is free: the enriched post row already carries
       it, which is the whole reason the output-language decision costs no extra call.
    2. **`run.post_languages[post_id]`** — the slide-intelligence pass's ONE deck-level reading
       (`SlideIntel.language`, FR-306 as amended), keyed by post because the reading is a property
       of the SOURCE DECK and two sibling creatives bound to one post must see one answer.
    3. **`run.topic_languages[trend_key]`** — the FR-294 topic screen's own `Verdict.language`,
       keyed by topic. Added after the D63 review: under `target` mode the screen's LANG skip is
       switched OFF (a foreign topic is let in on purpose, because translation now exists), so a
       topic the screen read as German sails through Select, and if Virlo sent no code and the
       vision pass read none, the deck used to arrive here as "unknown" and ship German pixels
       under `translate_language_unknown`. The screen already made that reading and this run
       already paid for it; declining to use it is not caution, it is throwing away evidence.
       It sits BELOW the other two because it is a judgement about a TOPIC's strings rather than
       about the bound post's own slides, and two posts inside one topic can be written in
       different languages — that gap is exactly what `plan.off_language_post` exists for.
    4. **`""` — unknown**, and unknown is a real answer that this engine honours by doing nothing:
       the deck ships verbatim in whatever language its post is in, with one warning. There is
       deliberately NO fifth rung. A stopword or diacritics heuristic was considered and rejected
       (D63 §0): `topic_filter.fuzzy_strip` records why guessing at language from bytes is a
       decision this codebase does not make, and a wrong guess here spends a model call
       translating a deck that was already in the target language.

    Every rung goes through `language_code` even though rung 1 is normalised upstream, because
    this function is the one place the channels are compared with each other and with
    `entry.language`, and one spelling rule across the comparison is what stops `"English"` from
    failing to equal `"en"` on the one run nobody tests. Pure, silent, and safe to call from
    anywhere: an offer with no post answers `""` — the ladder describes a BOUND post, and rung 3
    is not allowed to answer for a creative that has no post to be in a language.
    """
    if offer.post is None:
        return ""
    if code := language_code(getattr(offer.post, "language", "")):
        return code
    if code := language_code(run.post_languages.get(str(offer.post.post_id), "")):
        return code
    return language_code(run.topic_languages.get(str(entry.trend_key or ""), ""))


def _translate_wanted(entry: PlanEntry, offer: _Offer, run: _Run) -> bool:
    """D63/FR-343 — does THIS creative take a translate call before anything else happens to it?

    Four conditions, and the mode is always the first, exactly as it is for `_compress_wanted`:

    - **`run.copy_language_mode` is `target`.** An operator toggle, never a measurement. Under
      `source` (the engine default) this function is false for every creative in the run and the
      module behaves byte for byte as it did before D63.
    - **`_panel_mapped`** — a carousel, BOUND at ASSIGN, not an override brief. Scope is the same
      three structural tests compress rides, and for the same reason: translation is a rule about
      a bound deck's own slides, and an image, a reel, an override brief or an unbound carousel
      has none. Those creatives ship their source language under `target` too; pre-flight warns
      about them (FR-345) rather than this module pretending otherwise.
    - **the ladder answered at all.** An unknown language is NOT a failure to translate — it is a
      decision not to, because "translate this into English" aimed at a deck that may already be
      English is a call that can only make the deck worse. One warning per creative, no tag, and
      the deck ships verbatim. The warning is emitted HERE rather than at a call site because
      this predicate runs exactly once per creative (`_write_group`'s partition), which is what
      keeps it one line per creative rather than one per caller.
    - **the ladder's answer differs from the platform's configured language** (`entry.language`,
      which `plan` set from `run.languages[platform]`). A post already in the target language is
      quoted byte for byte, costs no call, and is byte-identical to what a `source`-mode run would
      have shipped — `source_language` is still recorded on its provenance so meta.yaml can say
      so.

    Returns True only for the case where a translation is both possible and worth paying for.
    """
    if run.copy_language_mode != LANGUAGE_TARGET or not _panel_mapped(entry, offer):
        return False
    source = _source_language(entry, offer, run)
    if not source:
        _warn(run.log, "translate_language_unknown",
              f"{entry.asset_id}: this bound deck ships verbatim in whatever language its post is "
              f"in — post {offer.post.post_id if offer.post else ''} carries no language from "
              "Virlo and the vision pass read none, so there is nothing to translate FROM "
              "(FR-343). The engine does not guess at a language from the bytes: a wrong guess "
              f"pays a model to rewrite a deck that may already be in {entry.language}. Every "
              "panel still renders in full, in its own position, and the creative is not tagged",
              asset_id=entry.asset_id,
              post_id=offer.post.post_id if offer.post else "",
              target_language=entry.language)
        return False
    return source != language_code(entry.language)


def _rows_over_budget(texts: Sequence[str], budget: int) -> list[int]:
    """1-based positions whose text is longer than `budget` characters (pure; budget ≤ 0 → []).

    D62/FR-353's whole measurement, and it is deliberately a PURE function of a list of strings
    and a number: no `_Run`, no config, no offer, no logging, no I/O. Two callers today —
    `_compress_wanted`, which asks "is there anything to compress at all", and `_auto`, which asks
    "which positions" — and they must never disagree, because one decides whether the call happens
    and the other decides what the answer is allowed to touch.

    Purity is also forward-looking: SESSION N calls this on a TRANSLATED deck, where the strings
    are not `offer.panels` at all, so anything this function reached for beyond its two arguments
    would have to be faked or duplicated there.

    `budget <= 0` means "this creative renders no such slot", which `_slot_budgets` never produces
    for a carousel's `slide`. It answers "nothing is over budget" rather than "everything is": a
    missing ceiling may not be read as a ceiling of zero, which would send an entire deck to the
    compress call on the strength of a slot that does not exist.
    """
    if budget <= 0:
        return []
    return [position for position, text in enumerate(texts, start=1) if len(text) > budget]


def _admitted_texts(entry: PlanEntry, offer: _Offer) -> list[str]:
    """This deck's panel text per POSITION, dropped panels blanked — pure, and silent.

    The input `_rows_over_budget` measures. Position-indexed over `_deck_length` exactly as
    `_mapped_deck` walks it, and each position carries `text` when `_panel_verdict` admits it and
    `""` when it does not — the SAME verdict, on the same string, in the same order, so a panel
    that will render wordless can never be counted as over budget and sent to the compress call.

    What it deliberately does NOT do is warn. `_mapped_deck` logs `panel_over_budget`,
    `panel_handle_or_url` and `panel_emptied_by_strip` once per creative when it runs, and it runs
    on the auto path too (`_auto_deck` calls it first, unchanged). A measuring pass that repeated
    those three warnings would double every one of them on every auto deck, and the operator would
    read the duplicate as two decks' worth of dropped panels.
    """
    out: list[str] = []
    for position in range(1, _deck_length(entry, offer) + 1):
        text = offer.panels[position - 1] if position <= len(offer.panels) else ""
        out.append("" if _panel_verdict(text) else text)
    return out


async def _call_compress(
    group: _Group, entries: Sequence[PlanEntry], run: _Run, offers: Mapping[str, _Offer],
    *, only: Mapping[str, Sequence[int]] | None = None,
) -> dict[str, dict[str, Any]]:
    """The D54 call: source panel strings in, compressed strings out (FR-331/FR-332).

    Shaped deliberately like `_call_copy` above — same role (`COPY_ROLE`, so config's model, token
    ceiling and reasoning effort are the ones the operator already set and the estimator already
    priced), same engine, same failure door (`copy_prompt_failed` -> `{}` -> the caller's
    `_mapped_fallback`), same envelope parsing. What differs is the template, the schema and one
    context slot:

    - `{{compress_panels}}` carries the panels themselves rather than labels (`_compress_block`).
      It is allowlisted for this template and NOWHERE else, which is the enforcement that a render
      role can never be handed a block of source panel text to "work from".
    - `carousel_copy_mode="compress"` is passed PER CALL, not per run: the verbatim partition of a
      compress-mode group still passes the default, so `{{text_budgets}}`'s carousel line says
      "no per-slide ceiling" for the deck that is quoting and states the real ceiling for the deck
      that is compressing to it.

    `only` (D62/FR-353) is the auto mode's whole difference at the wire: `{asset_id: the positions
    that overflowed}`, so `_compress_block` prints those panels alone and `_sibling_list` writes
    the auto clause naming them. `None` — every compress-mode call, and every pre-D62 caller — is
    "list every admitted position", which is byte-identical to what this function always sent. The
    template needs no branch for it: it already says a position it did not print takes `""`, and
    under auto the unprinted positions are precisely the ones already shipping verbatim.
    """
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
        sibling_list=_sibling_list(entries, run, offers, True, compress=True, auto_rows=only),
        carousel_copy_mode=MODE_COMPRESS,
    )
    context["compress_panels"] = _compress_block(entries, offers, only=only)
    try:
        system = run.engine.render(_COMPRESS_TEMPLATE, context)
    except (ValueError, LookupError) as exc:  # unresolved placeholder / missing template
        _warn(run.log, "copy_prompt_failed", str(exc))
        return {}
    result = await run.call(
        COPY_ROLE,
        [{"role": "system", "content": system},
         {"role": "user", "content": _COMPRESS_CARRIER_TURN}],
        _compress_schema(),
        None,
    )
    if result.degraded or not isinstance(result.parsed, Mapping):
        return {}
    return _answers(result, entries)


def _answers(result: Any, entries: Sequence[PlanEntry]) -> dict[str, dict[str, Any]]:
    """`{asset_id: payload}` for the creatives THIS call asked about — the one envelope reader.

    Both contracts answer in the same envelope (`{"creatives": [{asset_id, …}]}`), so the
    unwrapping lives once. An item naming a creative this call did not ask about is dropped: a
    model that answers for a sibling in another group would otherwise overwrite copy that group's
    own call is about to produce.
    """
    wanted = {entry.asset_id for entry in entries}
    payloads: dict[str, dict[str, Any]] = {}
    for item in result.parsed.get("creatives") or []:
        if isinstance(item, Mapping) and str(item.get("asset_id")) in wanted:
            payloads[str(item["asset_id"])] = dict(item)
    return payloads


def _compress_block(entries: Sequence[PlanEntry], offers: Mapping[str, _Offer], *,
                    only: Mapping[str, Sequence[int]] | None = None) -> str:
    """The `{{compress_panels}}` block: one section per creative, its own deck's panels, in order.

    This is the compress contract's whole input, and every line of it is load-bearing:

    The shape is the one `copy_compress_system.md` documents and parses (FR-332), and every part of
    it is load-bearing:

        CREATIVE <asset_id> — language: <the mirror rule>
        caption source: <that post's own caption>
        1. (at most 180 characters) <source panel 1>
        3. (at most 180 characters) <source panel 3>

    - **Only ADMITTED positions are listed, and they are numbered by SOURCE POSITION.** Position 2
      is missing from the example because that source panel was empty, carried a social mark or
      broke the sanity ceiling: an unlisted number is a wordless slide, the template says so, and
      the engine enforces it whatever comes back (`_compressed_deck` discards a line written for an
      unlisted position). Numbering by source position rather than re-numbering 1..N is what keeps
      the answer alignable — the model returns one entry per slide of the deck and `""` for the
      positions it was not given, and `slide_texts[i - 1]` is read by INDEX.
    - **The budget is per creative and stated on every line**, taken from `offer.budgets["slide"]`,
      which `_slot_budgets` has already reduced to `min(text_budgets.slide, style
      max_onimage_chars.slide)` (FR-259). One number, derived once, enforced twice — the prompt
      asks for it and `_compressed_deck`'s backstop trim cuts to the same value. It is repeated per
      line rather than stated once because a model reading its ninth panel has stopped looking at
      the header.
    - **The language rule names the panels, not a language.** Compress is the LENGTH contract and
      it never changes what tongue a deck is in, so the mirror rule stands: "mirror the language
      these panels are written in" is checkable by the model against text it can see, and it is
      what keeps a compressed slide comparable, word for word, with the panel it was written down
      from. (`SourcePost` DOES carry a `language` field since v2.7.0/D63 — the sentence here used
      to say it did not, and that reasoning is retired. The field exists, the D63 ladder reads it,
      and a deck that needs its language CHANGED takes the translate contract and its own template
      instead. Naming a target language on this block would make this call a translation nobody
      priced and nobody asked for.)

    Panels are shown IN FULL and never `_display`-truncated. The verbatim table can truncate for
    display because the engine ships the original bytes from `SourcePost`; here the shown text IS
    the material being compressed, and a truncated panel would be compressed into a lie. A panel's
    own line breaks survive as indented continuation lines, so the numbering stays readable without
    reflowing the source's typography.

    **`only` narrows the listing to AUTO mode's overflowing positions (D62/FR-353)** and changes
    nothing else — same numbering by source position, same per-line budget, same header, same
    caption line. It works precisely because "an unlisted number ships wordless" was never the
    engine's reading of an unlisted number: the engine's reading is "the model was not asked about
    this position, so its answer for it is discarded", and under auto that position is already
    shipping its source panel verbatim. `None` lists every admitted position, which is what every
    compress-mode call sends and what this function did before D62, byte for byte.
    """
    blocks: list[str] = []
    for entry in entries:
        offer = offers.get(entry.asset_id)
        if offer is None or offer.post is None:
            continue
        wanted = None if only is None else {int(n) for n in only.get(entry.asset_id, ())}
        budget = offer.budgets.get("slide", 0)
        lines = [f"CREATIVE {entry.asset_id} — language: the one these panels are written in; "
                 "mirror it exactly and never translate",
                 "caption source: " + (_folded(offer.captions[0].text) if offer.captions else
                                       "(none — return an empty caption and the engine "
                                       "assembles one from this post's own words)")]
        for position in range(1, _deck_length(entry, offer) + 1):
            text = offer.panels[position - 1] if position <= len(offer.panels) else ""
            if _panel_verdict(text):
                continue  # unlisted IS the instruction: that slide ships wordless (FR-304)
            if wanted is not None and position not in wanted:
                continue  # auto mode: this panel already fits, so it ships verbatim (FR-353)
            lines.append(f"{position}. (at most {budget} characters) {_folded(text)}")
        blocks.append("\n".join(lines))
    if not blocks:
        return ""
    header = ("One section per creative, each carrying that creative's OWN source deck. These "
              "panels are the content authority: compress them, never replace them, and never "
              "write a slide from anything else on this page.")
    return f"{header}\n\n" + "\n\n".join(blocks)


def _folded(text: str) -> str:
    """A multi-line source string on a numbered line — line 1 in place, the rest indented.

    Nothing is removed, reflowed or collapsed: the panel's own line breaks are part of what the
    model is compressing, and a slide typeset as four short lines is a different string from the
    same words run together. The indent exists so a four-line panel cannot be misread as four
    panels, which is the one way this block could silently re-map a deck.
    """
    head, *rest = text.split("\n")
    return "\n".join([head, *(f"    {part}" for part in rest)])


def _compress_schema() -> dict[str, Any]:
    """The compress call's schema, generated from `CopyCompressed` (contracts item 10).

    Same construction as `_selection_schema`: `asset_id` is excluded from the dataclass projection
    and re-added first by the engine, so the ANSWER fields belong to the dataclass and identity
    belongs to the envelope. `slide_texts` is a plain array of strings and its POSITION is the
    contract — the engine pads or truncates it to the deck's length rather than trusting it, and a
    schema cannot express "as long as that creative's deck" anyway.
    """
    fields = json_schema_for(CopyCompressed, exclude={"asset_id"})["properties"]
    creative = {"type": "object", "properties": {"asset_id": {"type": "string"}, **fields},
                "required": ["asset_id", *fields], "additionalProperties": False}
    return {
        "name": "copy_compressed",
        "schema": {"type": "object", "properties": {"creatives": {"type": "array",
                                                                  "items": creative}},
                   "required": ["creatives"], "additionalProperties": False},
    }


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
                  verbatim: bool, *, compress: bool = False,
                  auto_rows: Mapping[str, Sequence[int]] | None = None,
                  translate_to: str = "") -> str:
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

    `compress` (D54/FR-331) writes the COMPRESS call's variant of the same lines, and it is a
    keyword of this function rather than a branch inside `_call_copy` because "one line per
    creative, stating the language rule that governs it" is one job with three answers, not three
    jobs. The line still names the post — the model needs to know which section of
    `{{compress_panels}}` is this creative's — and it replaces the "as-selected" language clause
    with the mirror rule and the slide budget, which are the two things the compress contract adds.
    Every caller that does not ask for it gets byte-identical output to the pre-D54 function.

    `auto_rows` (D62/FR-353) makes it four answers rather than three, and it is a FOURTH branch
    rather than an edit to the compress one on purpose: the compress wording is what three shipped
    tests pin and what every `--copy-mode compress` run still sends, so it stays untouched. The
    auto line names the positions being asked for, says out loud that every other panel of that
    deck ships verbatim and is not printed, and repeats the template's own rule that an unprinted
    position takes `""` — because under auto the unprinted positions are the majority of the deck,
    and a model that "helpfully" rewrote them would have its work discarded row by row.

    `translate_to` (D63/FR-343) is the FIFTH branch and it is tried before both compress ones,
    because a translating deck is never in a compress call's entry list and the two clauses would
    otherwise have to be read as mutually exclusive by inspection rather than by order. The line
    names BOTH languages — the ladder's reading of the panels and the platform's configured target
    — which is the one place in this whole module a language is stated to a model rather than
    described. That is not a reversal of §1.7.5's rule: the rule is that the ENGINE does not detect
    a language, and this code is the adapter's or the vision pass's answer being passed through,
    not a guess made here. The rest of the clause is the no-shortening guarantee restated on the
    line the model reads last, because a ceiling it never saw is exactly what a model invents when
    a translation runs long.
    """
    lines = []
    for entry in entries:
        offer = offers.get(entry.asset_id)
        line = f"- {entry.asset_id} · {entry.platform} · {entry.creative_format}"
        if entry.creative_format == "carousel" and entry.slide_count:
            line += f" · {entry.slide_count} slides"
        if translate_to and offer is not None and offer.post is not None:
            line += (f" · translate post P{offer.post_ordinal}'s panels from "
                     f"{_source_language(entry, offer, run)} to {translate_to}; "
                     "keep every fact, number, "
                     "name and claim; never shorten, never summarise")
        elif compress and auto_rows is not None and offer is not None and offer.post is not None:
            budget = offer.budgets.get("slide", 0)
            rows = ", ".join(str(int(position))
                             for position in auto_rows.get(entry.asset_id, ()))
            line += (f" · compress post P{offer.post_ordinal}'s panels {rows} (the ones over "
                     f"{budget} characters) to {budget} characters per slide; every other panel "
                     "of this deck ships verbatim and is not printed, so answer \"\" for every "
                     "position not printed"
                     " · language: the panels' own, mirrored exactly, never translated")
        elif compress and offer is not None and offer.post is not None:
            line += (f" · compress post P{offer.post_ordinal}'s panels to "
                     f"{offer.budgets.get('slide', 0)} characters per slide"
                     " · language: the panels' own, mirrored exactly, never translated")
        elif verbatim and offer is not None and offer.post is not None:
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
        # rather than a caption. The honest answer is the same post's best remaining line plus our
        # own attribution clause (`_offer_caption`) — an ASSEMBLED string, so it claims no
        # verbatim provenance, joins the verifier's pool as ours, and records no ref label. What
        # it may never be is our configuration (v2.2.0). (Virlo's own
        # `description` summary is NOT a candidate here any more — FR-303 removed it from the
        # grammar, so a post with nothing but a summary caption reaches exactly this branch.)
        caption = _offer_caption(offer, entry, run)
        own_words.append(caption)
        _warn(run.log, "copy_caption_unavailable",
              f"{entry.asset_id}: post P{offer.post_ordinal} offers no caption with at least "
              f"{_CAPTION_MIN_CHARS} non-hashtag characters (§0.7); the creative captions itself "
              "with that post's own best remaining line and a neutral attribution (FR-99/FR-307 "
              "caption forms) — never with the operator's niche descriptor",
              asset_id=entry.asset_id,
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
                              source_panel_count=len(offer.panels),
                              # D63/FR-346: the ladder's answer is recorded on EVERY bound
                              # creative in BOTH language modes, whether or not anything was
                              # translated. `copy_language` stays `source` here — these bytes are
                              # the post's own — and the pair is what lets meta.yaml say "this
                              # deck is in German and we shipped it that way" instead of leaving
                              # the operator to guess from the pixels.
                              source_language=_source_language(entry, offer, run)),
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
    #: D54 only — a compressed line came back over its budget and was cut at a word boundary
    #: (`text_trimmed`). Always false on the verbatim walk, where an over-budget panel is never
    #: trimmed and never can be: trimming a quote is how byte identity dies (FR-100/FIX 2).
    trimmed: bool = False
    #: D63/FR-343 only — at least one TRANSLATED line on this deck measured under half or over
    #: twice its source panel's length, so the creative earns `translate_length_drift`. It is a
    #: deck-level flag rather than a per-row one because the tag is per creative and the row that
    #: caused it is already named in the warning; and it is a separate field from `trimmed`
    #: because the two mean opposite things — `trimmed` says the engine cut a line to a ceiling,
    #: `drifted` says a line whose ceiling does not exist came back a suspicious length and
    #: shipped anyway (A20's polarity: an audit never costs the operator a card).
    drifted: bool = False


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

    A fourth per-row fact rides alongside, and it is NOT a drop reason: `truncation_suspect`
    (FR-304c, v2.2.0) says the admitted panel looks cut rather than finished. The panel still
    ships, in full, in its own position — the flag is handed to the post-render critic as contract
    data, because the critic can see the frame and this function cannot. A heuristic that could
    blank a panel would re-map the whole deck, which is worse than any transcription defect.

    §1.5 layer 3 (FR-312) has already run by the time this function sees a panel: a line that was
    the creator's own name is gone from `offer.panels` and survives in `offer.panels_original`,
    which is what each row's `source_text_original` records. Layer 3 is not a fourth drop reason —
    it usually leaves a full slide behind — so it rides its own boolean, `creator_stripped`, and
    it is `_offer_for` that warns about it, once per creative, over every kind rather than over
    panels alone.

    The PAGE COUNTER strip (F2, Session 5.5) has run by then too, in the same place and on the
    same terms: a line that was only the source deck's `01 / 06` is gone from `offer.panels`,
    survives in `source_text_original`, and rides its own boolean — `chrome_counter_stripped`.
    Its own, and never `creator_stripped`, because that flag's finding is "our creative nearly
    named another account" and this one's is "our contract nearly demanded their page number".
    """
    length = _deck_length(entry, offer)
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
                               "creator_stripped": creator_cut,
                               # F2 (Session 5.5): this row's panel carried the SOURCE deck's page
                               # counter on a line of its own and lost it at admission. Kept apart
                               # from `creator_stripped` on purpose — that flag tags the creative
                               # `competitor_stripped`, and a page number is nobody's brand. The
                               # counter itself is still in `source_text_original` above.
                               "chrome_counter_stripped": position in offer.chrome_counter_panels,
                               # FR-304c (v2.2.0): the admitted panel looks CUT rather than
                               # finished — a trailing ellipsis, a hanging hyphen, a mid-word
                               # stop. Contract data for the post-render critic, which is looking
                               # at the frame and can tell an authored cliff-hanger from a clipped
                               # container. NEVER a drop reason: the panel shipped in full.
                               "truncation_suspect": position in offer.truncation_suspect_panels,
                               # D54 (v2.3.0): FALSE here by construction — this walk QUOTES, it
                               # never compresses. The key is written on every row of both walks
                               # because `generate._panel_map`'s contract is ONE row schema always,
                               # and a gallery that had to ask whether the key exists before
                               # reading it would be reading two schemas (FR-73 as amended).
                               "compressed": False,
                               # D63 (v2.7.0): FALSE here by the same construction — this walk
                               # quotes the source's own bytes in the source's own language, so
                               # nothing on the row is a translation. `_auto_deck` inherits the
                               # key from this walk and rewrites `compressed` alone;
                               # `_translated` is the only place it ever becomes True, and it is
                               # written here so the one-row-schema contract holds on every path.
                               "translated": False})
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


def _deck_length(entry: PlanEntry, offer: _Offer) -> int:
    """How many slides this bound deck has — the PLAN's number, never a walk's own arithmetic.

    `entry.slide_count` was fixed at ASSIGN from the source's `panel_count` clamped to the platform
    ceiling (§0.4′) and is what the Confirm gate priced, so a copy stage that derived its own
    length would spend money the operator never approved. The fallback to the source's own panel
    count covers an entry built before ASSIGN carried the field.

    Extracted (v2.3.0) because THREE walks now have to agree on it: `_mapped_deck`, D54's
    `_compressed_deck`, and `_compress_block`, which tells the model how many positions to answer
    for. A prompt asking for 5 slides while the walk writes 6 rows is a deck whose last slide is
    silently wordless, and it is exactly the kind of drift a shared constant prevents and a
    repeated expression invites.
    """
    return max(0, _int(entry.slide_count)) or len(offer.panels)


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


# --------------------------------------------------------------------------------------------
# Compress mode — the third contract (D54/FR-331), and auto mode on top of it (D62/FR-353)
# --------------------------------------------------------------------------------------------


def _compressed(entry: PlanEntry, payload: Mapping[str, Any], offer: _Offer, group: _Group,
                run: _Run) -> _Written:
    """Turn one `CopyCompressed` answer into a shipped deck, its caption and its FR-304 panel map.

    The sibling of `_resolve` for the compress contract, and it differs from it in exactly one
    respect: the on-image strings are the MODEL's bytes rather than the source's, so every gate
    `_offer_for` applied on the way IN is re-applied here on the way OUT. A model asked to rewrite
    a panel can write anything, including a competitor's name it read in the fenced trend texts and
    an @handle it copied off the panel it was compressing.

    What is NOT re-derived here is the deck. `_compressed_deck` does one walk and returns both the
    slide texts and the panel map, and this function never touches either afterwards — see that
    function for why the single walk is the invariant this whole mode rests on.

    Three receipts replace the byte-substring claim, and all three are written here:
    `CopyProvenance.copy_mode = "compress"`, `panel_map[i].compressed = True`, and
    `_Written.quoted = ()`, which is what makes `_verify` skip its substring half (the precedent is
    the free-text creative, which quotes nothing either) while its blocklist half still audits every
    string this function ships — slides, caption and hashtags alike.
    """
    brands = _strip_terms(entry, run)
    tags: list[DegradationTag] = []
    own_words: list[str] = []
    deck = _compressed_deck(entry, payload, offer, run, brands)
    headline, headline_trimmed, headline_stripped = _compress_field(
        str(payload.get("headline") or ""), offer.budgets.get("headline", 0), brands,
        entry, run, where="headline")
    caption, hashtags, caption_stripped = _compressed_caption(payload, offer, entry, run, brands,
                                                              own_words)
    copyset = CopySet(
        asset_id=entry.asset_id,
        language=entry.language,
        trend_key=entry.trend_key,
        caption=caption,
        hashtags=hashtags,
        headline=headline,
        slide_texts=deck.texts,
        narrative_arc=str(payload.get("narrative_arc") or ""),
        through_line=str(payload.get("through_line") or "") or _subject_name(entry, group),
    )
    if not (headline or any(text.strip() for text in deck.texts)):
        tags.append(DegradationTag.NO_ONIMAGE_TEXT)
        _warn(run.log, "no_onimage_text",
              f"{entry.asset_id}: the compress call returned no usable text for any slide of this "
              f"deck and no cover headline; shipping a caption-only creative (FR-331). Its "
              f"{sum(1 for text in offer.panels if text.strip())} source panel(s) are unchanged "
              "and a re-run in verbatim mode would render them in full",
              asset_id=entry.asset_id, budgets=dict(offer.budgets),
              source_panels=len(offer.panels))
    if deck.trimmed or headline_trimmed:
        tags.append(DegradationTag.TEXT_TRIMMED)
    if deck.stripped or caption_stripped or headline_stripped:
        tags.append(DegradationTag.COMPETITOR_STRIPPED)
        _warn(run.log, "competitor_stripped",
              f"{entry.asset_id}: a blocklisted competitor name, or the source creator's own name "
              "(FR-312), was removed from this creative's text (§1.5). On the compress path the "
              "strip runs on both sides — the panels the model was shown and the lines it sent "
              "back — because a compressed line is the model's bytes, not the source's",
              asset_id=entry.asset_id, refs={}, copy_mode=MODE_COMPRESS,
              creator_lines=sorted(offer.creator_stripped_panels))
    return _Written(
        copyset=copyset,
        source=CopyProvenance(post_id=offer.post.post_id if offer.post else "",
                              refs={},  # FR-302 as amended: a compressed slide quotes no label
                              panel_map=deck.panel_map,
                              source_panel_count=len(offer.panels),
                              copy_mode=MODE_COMPRESS,
                              # D63/FR-346: recorded here too. Compress shortens a panel in its
                              # OWN language, so `copy_language` stays `source` and this says
                              # which language that is.
                              source_language=_source_language(entry, offer, run)),
        tags=tags,
        # FR-331: nothing here claims to be a byte-substring of the post, so the pool is empty and
        # `_verify`'s half 1 self-skips. The blocklist half runs on every shipped string regardless
        # — it reads the CopySet, not this tuple.
        quoted=())


def _compressed_deck(entry: PlanEntry, payload: Mapping[str, Any], offer: _Offer, run: _Run,
                     brands: Sequence[str]) -> _PanelDeck:
    """FR-331 — ONE walk producing this deck's `slide_texts` AND its `panel_map`.

    **The single walk is the invariant, not a tidiness preference.** `gauntlet._expected_blocks`
    builds a rendered deck's frame contract from `CopySet.slide_texts`, while the gallery, the
    FR-309 card and the operator's audit read `panel_map`. If the two were produced by two loops,
    a compressed line that one accepted and the other blanked would make the critic demand a line
    the renderer was never given — the false `missing_text` BLOCK that F2 already cost this project
    once. So there is exactly one loop, one verdict per position, and both outputs are appended
    inside it: `deck.texts[i - 1]` and `deck.panel_map[i - 1]["source_text"]` are the same string
    by construction, not by agreement.

    Per position, in this order:

    1. **The SOURCE panel faces `_panel_verdict` first, exactly as `_mapped_deck` does** — the same
       three drop reasons (`empty`, `contains_handle_or_url`, `over_budget`), the same
       position-preserving wordless slide, the same three warnings. `PANEL_SANITY_CHARS` stays an
       INPUT guard: an over-ceiling panel is a transcription accident, and compressing an accident
       produces a confident summary of noise, so it ships wordless in both modes (FR-304a as
       amended). This is why compression cannot rescue a dropped panel and is not meant to.
    2. **An admitted position takes `slide_texts[position - 1]`** — by INDEX, never by consuming a
       queue, so a model that answered "" for slide 2 leaves slide 2 wordless instead of pulling
       slide 3's line onto it. A list shorter than the deck pads with empties; a longer one is
       truncated and warned.
    3. **The engine's backstops run on what came back**, in the order of certainty: the blocklist
       strip (§1.5 layers 1 and 2, fail-closed and unguarded — the model may have written a name
       the panels never contained), then the FR-319 social-mark gate, which BLANKS the line rather
       than editing it (a compressed sentence with its @handle cut out is a sentence nobody wrote),
       then the word-boundary trim to the same `min(config, style)` budget the prompt asked for.
       The trim is a backstop and not the mechanism: the model is asked to fit, and a line that
       still overshoots is cut at a word boundary and tagged `text_trimmed`.
    4. **A model line for a position the SOURCE dropped is DISCARDED and warned.** Compression
       fills no vacuums: an empty source panel means the source slide had no words, and inventing
       some is precisely the `invented_text` defect the gauntlet blocks decks for. The row keeps
       its `drop_reason` from step 1 and the operator is told what was thrown away.
    """
    length = _deck_length(entry, offer)
    answered = _positional(payload.get("slide_texts"))
    deck = _PanelDeck()
    over: list[str] = []        # over the sanity ceiling — cited in characters
    marks: list[str] = []       # an @handle or a URL survived into the SOURCE panel text
    blanked: list[str] = []     # the source claimed words here and the strip took them all
    invented: list[str] = []    # the model wrote for a position the source left empty
    scrubbed: list[str] = []    # a compressed line carried a social mark and was blanked
    silent: list[str] = []      # an admitted panel came back with nothing to render
    for position in range(1, length + 1):
        source = offer.panels[position - 1] if position <= len(offer.panels) else ""
        original = (offer.panels_original[position - 1]
                    if position <= len(offer.panels_original) else source)
        reason = _panel_verdict(source)
        ships = not reason
        if reason == _DROP_OVER_BUDGET:
            over.append(f"slide {position} ({len(source)} characters, sanity ceiling "
                        f"{PANEL_SANITY_CHARS})")
        elif reason == _DROP_MARKS:
            marks.append(f"slide {position} (carries {_excluded_marks(source, relaxed=True)})")
        elif reason == _DROP_EMPTY and position in offer.stripped_panels:
            blanked.append(f"slide {position}")
        model_text = answered[position - 1] if position <= len(answered) else ""
        text = ""
        if ships:
            text, trimmed, cut_name = _compress_field(
                model_text, offer.budgets.get("slide", 0), brands, entry, run,
                where=f"slide {position}", blanked_into=scrubbed)
            deck.trimmed = deck.trimmed or trimmed
            deck.stripped = deck.stripped or cut_name
            if not text.strip() and not model_text.strip():
                silent.append(f"slide {position}")
        elif model_text.strip():
            invented.append(f"slide {position} ({_display(model_text)})")
        deck.texts.append(text)
        deck.panel_map.append({"slide": position, "source_position": position,
                               # `source_text` is what SHIPS, exactly as in verbatim mode — here
                               # that is the COMPRESSED string, which is why the row also carries
                               # `compressed` below. The gallery renders this beside our slide.
                               "source_text": text,
                               # The source panel as it arrived (pre-layer-3, per the provenance
                               # doctrine that original bytes are never rewritten). It is the
                               # LLM's own starting point in every row that shipped, and FR-309's
                               # card measures "compressed from N chars" off its length.
                               "source_text_original": original,
                               # FR-302 as amended (v2.3.0): a compressed slide quotes no label.
                               "ref_label": "",
                               "drop_reason": reason,
                               "creator_stripped": position in offer.creator_stripped_panels,
                               "chrome_counter_stripped": position in offer.chrome_counter_panels,
                               "truncation_suspect": position in offer.truncation_suspect_panels,
                               # D54: this row's `source_text` is the model's compression of
                               # `source_text_original`, not a quote of it. It is what tells the
                               # gallery to label the column and the auditor not to expect byte
                               # identity.
                               "compressed": True,
                               # D63 (v2.7.0): FALSE on this walk always. Compress shortens a
                               # panel in its OWN language — `_compress_block`'s header states
                               # the mirror rule and the template repeats it — so a compressed
                               # row is never a translated one. The two axes are orthogonal and
                               # only `_translated_deck` sets this key True.
                               "translated": False})
        deck.stripped = deck.stripped or (ships and (position in offer.stripped_panels
                                                     or position in offer.creator_stripped_panels))
    if len(answered) > length:
        _warn(run.log, "compress_list_truncated",
              f"{entry.asset_id}: the compress call returned {len(answered)} slide texts for a "
              f"{length}-slide deck; the extra {len(answered) - length} are discarded. The deck's "
              "length is the plan's (fixed at ASSIGN and priced at the Confirm gate), never the "
              "model's — a longer answer cannot buy a slide nobody paid for (FR-331/FR-95)",
              asset_id=entry.asset_id, answered=len(answered), slides=length)
    if over:
        _warn(run.log, "panel_over_budget",
              f"{entry.asset_id}: {len(over)} source panel(s) exceed the {PANEL_SANITY_CHARS}"
              f"-character sanity ceiling and are never compressed (FR-304a) — {'; '.join(over)}. "
              "A panel that long is a transcription accident rather than a slide, and a confident "
              "compression of an accident is worse than a wordless slide; those slides render "
              "without text and keep their position", asset_id=entry.asset_id,
              sanity_ceiling=PANEL_SANITY_CHARS, slides=over)
    if marks:
        _warn(run.log, "panel_handle_or_url",
              f"{entry.asset_id}: {len(marks)} source panel(s) carry an @handle or a URL pointing "
              f"outside the technical allowlist, and may never become pixels (FR-319) — "
              f"{'; '.join(marks)}. They are not compressed either: the gate is about identity, "
              "not length, and a compression of a line we may not render is still that line. "
              "Those slides render without text and keep their position",
              asset_id=entry.asset_id, slides=marks)
    if blanked:
        _warn(run.log, "panel_emptied_by_strip",
              f"{entry.asset_id}: {len(blanked)} source panel(s) had words and lost all of them to "
              f"the competitor strip (§1.5) — {'; '.join(blanked)}. Those slides render without "
              "text and keep their position", asset_id=entry.asset_id, slides=blanked)
    if invented:
        _warn(run.log, "compress_invented_text",
              f"{entry.asset_id}: the compress call wrote text for {len(invented)} position(s) "
              f"whose SOURCE panel has none — {'; '.join(invented)}. Discarded: compression fills "
              "no vacuums (FR-331). An empty source slide is a slide its author left wordless, and "
              "a slide of ours carrying words theirs never had is the `invented_text` defect the "
              "post-render gate blocks whole decks for",
              asset_id=entry.asset_id, slides=invented)
    if scrubbed:
        _warn(run.log, "compress_scrub",
              f"{entry.asset_id}: {len(scrubbed)} compressed line(s) carried an @handle or a URL "
              f"outside the technical allowlist and were BLANKED — {'; '.join(scrubbed)}. The line "
              "is removed whole rather than edited: a compressed sentence with its mark cut out is "
              "a sentence nobody wrote and nobody proof-read (FR-319/FR-331). Those slides render "
              "without text and keep their position", asset_id=entry.asset_id, slides=scrubbed)
    if silent:
        _warn(run.log, "compress_no_text",
              f"{entry.asset_id}: {len(silent)} admitted source panel(s) came back from the "
              f"compress call with nothing — {'; '.join(silent)}. Those slides render wordless "
              "beside a source slide that has words, which is the failure FR-304 exists to "
              "prevent; the panels themselves are intact and a verbatim re-run renders them in "
              "full", asset_id=entry.asset_id, slides=silent)
    return deck


def _compress_field(text: str, budget: int, brands: Sequence[str], entry: PlanEntry, run: _Run,
                    *, where: str,
                    blanked_into: list[str] | None = None) -> tuple[str, bool, bool]:
    """One compressed string through the engine's three backstops — `(text, trimmed, stripped)`.

    The ONE implementation, used by every field the compress call writes into pixels (each slide
    and the cover headline) so the three gates cannot be applied in two different orders on two
    different fields. Order is the order of certainty and it matters:

    1. **Blocklist** (§1.5 layers 1 and 2, fail-closed, `apply_blocklist`'s mechanics and never a
       second implementation). It runs FIRST because a name removed from a string changes its
       length, and trimming before stripping would measure a budget against bytes we do not ship.
    2. **Social marks** (FR-319). The line is BLANKED, never edited — the two callers of this
       function put words on a slide, and half a sentence is worse than no sentence. The blanking
       is reported by the caller through `blanked_into`, aggregated per creative, because one
       warning per slide buries the finding on an eight-slide deck.
    3. **The word-boundary trim** to `budget` — `min(text_budgets.slide, style
       max_onimage_chars.slide)`, the same number `_compress_block` asked the model to fit. This is
       a BACKSTOP: the prompt is the mechanism, and a line reaching here still over the ceiling is
       cut at the last word boundary and earns `text_trimmed` (FR-101's tag, FR-331's use of it).

    `budget` of 0 means "this creative renders no such slot", which `_slot_budgets` never produces
    for a carousel's `slide` or `headline`; the trim is skipped rather than blanking everything, so
    a future format that reaches here with no budget loses nothing.

    `stripped` reports the BLOCKLIST alone and never the trim: `competitor_stripped` means "a name
    was removed", and a creative tagged with it because its slide was one character too long would
    send the operator looking for a competitor nobody mentioned.
    """
    out = apply_blocklist(text, brands) if (text and brands) else text
    stripped = out != text
    if out.strip() and _social_mark(out):
        if blanked_into is not None:
            blanked_into.append(f"{where} (carries {_excluded_marks(out, relaxed=True)})")
        else:
            _warn(run.log, "compress_scrub",
                  f"{entry.asset_id}: the compressed {where} carried "
                  f"{_excluded_marks(out, relaxed=True)} and was BLANKED (FR-319/FR-331) — a "
                  "compressed line is the model's own bytes, so the social-mark gate is re-applied "
                  "to what came back, and the line is removed whole rather than edited",
                  asset_id=entry.asset_id, field=where, text=out)
        return "", False, stripped
    if budget <= 0:
        return out, False, stripped
    trimmed_text, cut = trim_words(out, budget)
    if cut:
        _warn(run.log, "text_trimmed",
              f"{entry.asset_id}: the compressed {where} came back at {len(out)} characters "
              f"against a {budget}-character budget and was cut at the last word boundary "
              "(FR-101). The budget is what the compress prompt asked for, so this is the model "
              "overshooting rather than a rule being applied late",
              asset_id=entry.asset_id, field=where, before=out, after=trimmed_text)
    return trimmed_text, cut, stripped


def _compressed_caption(payload: Mapping[str, Any], offer: _Offer, entry: PlanEntry, run: _Run,
                        brands: Sequence[str], own_words: list[str]) -> tuple[str, list[str], bool]:
    """`(caption, hashtags, whether a strip fired)` for a compressed creative (FR-331).

    The caption is compressed AND humanized by the same call (operator decision, 2026-08-20): the
    source creator's caption is written to farm their comments and their follows, and shipping it
    verbatim under our brand is the funnel leak `_strip_cta` already fights sentence by sentence on
    the verbatim path. Here the model is asked for the caption's MEANING without its mechanics.

    Two engine backstops and one fallback:

    - the blocklist runs on the caption and on every hashtag (fail-closed, and `_verify` re-checks
      it afterwards on the shipped strings);
    - a caption carrying a SOCIAL MARK is refused outright rather than edited — an @handle or a
      link-in-bio URL in a caption is somebody else's funnel whatever else the sentence says;
    - a refused or empty caption falls back to `_offer_caption`, the same assembled form
      `_resolve` and `_mapped_fallback` use: this post's own best remaining line plus a neutral
      attribution that names no account. It joins `own_words` because it is ours, not a quote —
      and if that path has nothing safe either it raises `NoSafeCaptionError` while the run is
      still pre-spend, exactly as it does in verbatim mode.
    """
    stripped = False
    raw = str(payload.get("caption") or "")
    caption = apply_blocklist(raw, brands) if (raw and brands) else raw
    stripped = stripped or caption != raw
    if not caption.strip() or _social_mark(caption):
        cause = ("carries " + _excluded_marks(caption, relaxed=True) if caption.strip()
                 else "came back empty")
        caption = _offer_caption(offer, entry, run)
        own_words.append(caption)
        _warn(run.log, "compress_caption_rejected",
              f"{entry.asset_id}: the compressed caption {cause}, so the creative captions itself "
              "with its own post's best remaining line and a neutral attribution (FR-99/FR-307 "
              "caption forms). A caption is the one string this engine publishes as prose, and a "
              "mark in it points our audience at an account that is not ours",
              asset_id=entry.asset_id, post_id=offer.post.post_id if offer.post else "")
        return caption, [], stripped
    hashtags: list[str] = []
    dropped: list[str] = []
    for tag in _strings(payload.get("hashtags")):
        if apply_blocklist(tag, brands) != tag or _social_mark(tag):
            dropped.append(tag)
            continue
        hashtags.append(tag)
    if dropped:
        stripped = True
        _warn(run.log, "competitor_stripped",
              f"{entry.asset_id}: {len(dropped)} hashtag(s) from the compress call were dropped — "
              + ", ".join(repr(tag) for tag in dropped)
              + ". A hashtag is one token and cannot be part-stripped, so a blocklisted or "
                "identity-bearing tag is removed whole (§1.5, FR-319)",
              asset_id=entry.asset_id, hashtags=dropped)
    return caption, hashtags, stripped


# --------------------------------------------------------------------------------------------
# Auto mode — compress ONLY the panels that overflow (D62/FR-353)
# --------------------------------------------------------------------------------------------


def _auto(entry: PlanEntry, payload: Mapping[str, Any], offer: _Offer, group: _Group,
          run: _Run) -> _Written:
    """FR-353 — a MIXED deck: the panels that fitted are quoted, the ones that overflowed are not.

    The sibling of `_compressed`, and everything above the deck is identical to it: the same call
    wrote this creative's caption, headline and hashtags, so the same three backstops run on them
    through `_compress_field` and `_compressed_caption`, and the same three tags
    (`no_onimage_text`, `text_trimmed`, `competitor_stripped`) are earned on the same terms.

    The deck is where it differs, and the difference is delegated whole to `_auto_deck`: the
    verbatim FR-304 mapping is built FIRST and unchanged, and only the overflowing positions are
    spliced. So `refs` here is not empty the way `_compressed`'s is — it holds the quoted rows'
    real `P<n>.panel.<i>` labels, because those rows really are byte-quotes of those panels and
    saying otherwise would throw away provenance the deck actually has.

    `quoted` is the pool `_verify` audits against, and on this path it is built as "the source's
    strings PLUS every string this call authored that ships". That is what lets half 1 of the
    audit keep working row by row: a quoted slide must still be a byte-substring of the post (a
    real check, and the only place a splicing bug would surface), while a compressed slide, the
    compressed caption, the compressed headline and the model's hashtags pass by construction
    because they are in the pool themselves. Half 2 — the blocklist — reads the `CopySet` rather
    than this tuple and is unaffected either way.

    The positions are recomputed here from `_rows_over_budget(_admitted_texts(...))` rather than
    threaded down from `_write_group`: both are pure functions of the same entry and offer, so the
    two computations cannot disagree, and passing the list through three frames just to avoid a
    list comprehension would put an invariant on a parameter instead of on a function.
    """
    brands = _strip_terms(entry, run)
    tags: list[DegradationTag] = []
    own_words: list[str] = []
    over = _rows_over_budget(_admitted_texts(entry, offer), offer.budgets.get("slide", 0))
    deck = _auto_deck(entry, payload, offer, run, brands, over)
    headline, headline_trimmed, headline_stripped = _compress_field(
        str(payload.get("headline") or ""), offer.budgets.get("headline", 0), brands,
        entry, run, where="headline")
    caption, hashtags, caption_stripped = _compressed_caption(payload, offer, entry, run, brands,
                                                              own_words)
    copyset = CopySet(
        asset_id=entry.asset_id,
        language=entry.language,
        trend_key=entry.trend_key,
        caption=caption,
        hashtags=hashtags,
        headline=headline,
        slide_texts=deck.texts,
        narrative_arc=str(payload.get("narrative_arc") or ""),
        through_line=str(payload.get("through_line") or "") or _subject_name(entry, group),
    )
    if not (headline or any(text.strip() for text in deck.texts)):
        # Under auto this can only mean the SOURCE deck is wordless: a panel that was admitted and
        # under budget ships its own bytes without the model's help, and an over-budget panel that
        # came back empty keeps its bytes too (see `_auto_deck`). So the honest message is about
        # FR-304's admission gate, not about the compress call.
        tags.append(DegradationTag.NO_ONIMAGE_TEXT)
        _warn(run.log, "no_onimage_text",
              f"{entry.asset_id}: no slide of this deck carries text and the call returned no "
              f"cover headline; shipping a caption-only creative (FR-353). Every one of its "
              f"{len(offer.panels)} source panel(s) was dropped by FR-304's admission gate — auto "
              "mode compresses only what overflows, so it can neither rescue a dropped panel nor "
              "blank an admitted one", asset_id=entry.asset_id, budgets=dict(offer.budgets),
              source_panels=len(offer.panels))
    if deck.trimmed or headline_trimmed:
        tags.append(DegradationTag.TEXT_TRIMMED)
    if deck.stripped or caption_stripped or headline_stripped:
        tags.append(DegradationTag.COMPETITOR_STRIPPED)
        _warn(run.log, "competitor_stripped",
              f"{entry.asset_id}: a blocklisted competitor name, or the source creator's own name "
              "(FR-312), was removed from this creative's text (§1.5). On the auto path the strip "
              "runs on both sides — the panels the model was shown and the lines it sent back — "
              "because a compressed line is the model's bytes, not the source's, while the rows "
              "that shipped verbatim were stripped at offer time as they always are",
              asset_id=entry.asset_id, refs=dict(deck.refs), copy_mode=MODE_AUTO,
              creator_lines=sorted(offer.creator_stripped_panels))
    # Everything this call AUTHORED that becomes pixels or prose. It joins the verifier's pool for
    # the same reason `own_words` does on the verbatim paths: a string we wrote is not a quote gone
    # missing, and reporting it as one would bury the rows where the check still has teeth.
    authored = [row["source_text"] for row in deck.panel_map if row["compressed"]]
    return _Written(
        copyset=copyset,
        source=CopyProvenance(post_id=offer.post.post_id if offer.post else "",
                              refs=deck.refs,  # the QUOTED rows' labels — real, and kept
                              panel_map=deck.panel_map,
                              source_panel_count=len(offer.panels),
                              copy_mode=MODE_AUTO,
                              # D63/FR-346: recorded here too, for the same reason. An auto deck
                              # quotes some rows and compresses others, all in the post's own
                              # language, so `copy_language` stays `source` and this names it.
                              source_language=_source_language(entry, offer, run)),
        tags=tags,
        quoted=(*offer.haystack, *own_words, *authored, caption, headline, *hashtags))


def _auto_deck(entry: PlanEntry, payload: Mapping[str, Any], offer: _Offer, run: _Run,
               brands: Sequence[str], over: Sequence[int]) -> _PanelDeck:
    """FR-353 — the verbatim mapped deck with the overflowing positions SPLICED, nothing else.

    **The verbatim walk runs first and unchanged.** `_mapped_deck` produces the texts, the refs and
    the full FR-304 panel map exactly as it does on a verbatim run, warnings included — one
    `panel_over_budget`, one `panel_handle_or_url`, one `panel_emptied_by_strip` per creative, in
    their own honest wording. Building the deck this way rather than writing a third walk is what
    guarantees an auto deck with nothing spliced is byte-identical to a verbatim one, and it is
    also why the three drop reasons, the position preservation, `creator_stripped`,
    `chrome_counter_stripped`, `truncation_suspect` and `source_text_original` all behave here
    without a line of code restating them.

    Then, per position in `over` and only those:

    1. The model's line for that position goes through `_compress_field` — blocklist (fail-closed,
       layers 1 and 2), the FR-319 social-mark gate (which BLANKS rather than edits), then the
       word-boundary trim to the same budget the prompt asked for. The same function, in the same
       order, as the compress path: a compressed line is the model's bytes whichever mode produced
       it.
    2. A line that survives is SPLICED: `texts[i - 1]` becomes it, that slide's `P<n>.panel.<i>`
       ref is removed (this row no longer quotes a label, FR-302 as amended), and the row's
       `source_text` / `ref_label` / `compressed` are rewritten to match. `source_text_original`
       is left exactly as `_mapped_deck` wrote it — the pre-layer-3 source panel — which is the
       same string `_compressed_deck` records, so the gallery's "compressed from N chars" measures
       off one shape in both modes.
    3. **A line that comes back EMPTY keeps the verbatim bytes.** Blank answer or a scrub that
       blanked it, the row is left alone: its panel, its label, `compressed: False`. Long beats
       wordless — the panel is over a design budget, not over `PANEL_SANITY_CHARS`, so it is a real
       slide with real words and rendering it long is strictly better than rendering it empty. That
       is the one place auto deliberately diverges from `_compressed_deck`, which has no verbatim
       row to fall back to and therefore ships the blank.
    4. **A line written for a position NOT in `over` is DISCARDED.** The model was not asked about
       it; the panel already fits and is already quoted verbatim on that slide. Overwriting it
       would be an unrequested rewrite of a string we are entitled to quote — the same finding
       `_compressed_deck` calls `invented`, with a different cause and its own event.
    """
    deck = _mapped_deck(entry, offer, run)
    answered = _positional(payload.get("slide_texts"))
    wanted = {int(position) for position in over}
    budget = offer.budgets.get("slide", 0)
    kept_verbatim: list[str] = []  # asked for, came back with nothing — the source bytes stand
    discarded: list[str] = []      # written for a position that was never asked about
    scrubbed: list[str] = []       # a compressed line carried a social mark and was blanked
    for position in range(1, len(deck.texts) + 1):
        model_text = answered[position - 1] if position <= len(answered) else ""
        row = deck.panel_map[position - 1]
        if position not in wanted:
            if model_text.strip():
                discarded.append(f"slide {position} ({_display(model_text)})")
            continue
        if row["drop_reason"]:  # unreachable: `_admitted_texts` blanks every dropped position
            continue
        text, trimmed, cut_name = _compress_field(
            model_text, budget, brands, entry, run, where=f"slide {position}",
            blanked_into=scrubbed)
        if not text.strip():
            kept_verbatim.append(f"slide {position} ({len(row['source_text'])} characters)")
            continue
        deck.texts[position - 1] = text
        deck.refs.pop(f"slide_{position}", None)
        row["source_text"] = text
        row["ref_label"] = ""
        row["compressed"] = True
        deck.trimmed = deck.trimmed or trimmed
        deck.stripped = deck.stripped or cut_name
    if len(answered) > len(deck.texts):
        _warn(run.log, "compress_list_truncated",
              f"{entry.asset_id}: the compress call returned {len(answered)} slide texts for a "
              f"{len(deck.texts)}-slide deck; the extra {len(answered) - len(deck.texts)} are "
              "discarded. The deck's length is the plan's (fixed at ASSIGN and priced at the "
              "Confirm gate), never the model's — a longer answer cannot buy a slide nobody paid "
              "for (FR-353/FR-95)",
              asset_id=entry.asset_id, answered=len(answered), slides=len(deck.texts))
    if scrubbed:
        _warn(run.log, "compress_scrub",
              f"{entry.asset_id}: {len(scrubbed)} compressed line(s) carried an @handle or a URL "
              f"outside the technical allowlist and were BLANKED — {'; '.join(scrubbed)}. The "
              "line is removed whole rather than edited: a compressed sentence with its mark cut "
              "out is a sentence nobody wrote (FR-319/FR-353). Under auto those slides keep their "
              "SOURCE panel instead of going wordless — see auto_row_kept_verbatim below",
              asset_id=entry.asset_id, slides=scrubbed)
    if kept_verbatim:
        _warn(run.log, "auto_row_kept_verbatim",
              f"{entry.asset_id}: {len(kept_verbatim)} over-budget panel(s) came back empty from "
              f"the compress call and ship verbatim — {'; '.join(kept_verbatim)}. Long beats "
              f"wordless: the panel is over this style's {budget}-character design budget, not "
              "over the sanity ceiling, so it is a real slide with real words and rendering it at "
              "full length is strictly better than rendering it blank (FR-353). The creative is "
              "NOT tagged for it — nothing was lost, only left uncompressed",
              asset_id=entry.asset_id, budget=budget, slides=kept_verbatim)
    if discarded:
        _warn(run.log, "auto_row_discarded",
              f"{entry.asset_id}: the compress call wrote text for {len(discarded)} position(s) "
              f"it was not asked about — {'; '.join(discarded)}. Discarded: those panels already "
              "fit the style's budget and are quoted verbatim on their slides, so a line for one "
              "of them is either an invention or an unrequested rewrite of a string we are "
              "entitled to quote (FR-353). Only the positions listed in that creative's section "
              "of the panel block are read", asset_id=entry.asset_id, slides=discarded)
    return deck


def _positional(value: Any) -> list[str]:
    """A model's POSITIONAL list of strings — blanks KEPT, because the index is the contract.

    Deliberately not `_strings`, and the difference is the whole of FR-304's alignment: `_strings`
    drops blank items, so a model answering `["", "the second slide"]` would have its second line
    land on slide 1 and its own slide 2 render wordless. Every other consumer in this module wants
    the compacted reading (a list of refs, a list of hashtags); this one is a list whose *k*th
    element IS slide *k + 1*, and losing an element re-maps the deck.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(item or "") for item in value]
    return []


# --------------------------------------------------------------------------------------------
# Translate mode — the LANGUAGE axis (D63/FR-343), orthogonal to the two length contracts above
#
# What this is written against. Virlo's monitors do not respect the operator's language: the
# strongest slideshow on a topic is as likely to be German or Czech as English, and until D63 the
# only two things the engine could do with it were quote it verbatim (a German deck published on
# an English-language platform slot) or refuse the topic at the filter's LANG screen (a strong
# post thrown away for a reason that is now fixable). Translation is the third answer, and it is
# scoped as narrowly as compress is: a BOUND, panel-mapped carousel whose source language is KNOWN
# and differs from its platform's configured one, in a run the operator put in `target` mode.
#
# The one rule that makes this a separate contract rather than a compress variant: NO CEILING. A
# translated line may be longer than its source and that is a normal outcome, so no budget is
# stated to the call, `_translate_field` has no `budget` parameter, and the only length gate a
# translated slide faces is `PANEL_SANITY_CHARS` — the same transcription-accident fence a source
# panel faces on the way in. Everything that was never about length is re-applied exactly as
# compress re-applies it: the blocklist (fail-closed, layers 1 and 2), the FR-319 social-mark
# BLANK, FR-304's position preservation and its three drop reasons.
# --------------------------------------------------------------------------------------------


async def _call_translate(group: _Group, entry: PlanEntry, run: _Run,
                          offers: Mapping[str, _Offer]) -> dict[str, dict[str, Any]]:
    """The D63 call: this deck's source panels in, the same deck in another language out (FR-343).

    Shaped deliberately like `_call_compress` — same role (`COPY_ROLE`, so the operator's model,
    token ceiling and reasoning effort are the ones the estimator already priced), same engine,
    same failure door (`copy_prompt_failed` -> `{}` -> the caller's `_mapped_fallback`), same
    `_answers` envelope. Three things differ:

    - **ONE creative per call, never a group.** `{{translate_panels}}` carries one section per
      creative and the template tells the model that section's panels are the content authority;
      two decks on one page is two content authorities, and the failure mode (a line from deck A
      answered for deck B) is precisely the alignment FR-304 exists to protect. It also keeps the
      blast radius at one deck, which is what makes the fail-open cheap.
    - **`carousel_copy_mode=MODE_VERBATIM` is passed on purpose**, even though the RUN may be in
      auto or compress mode. That is what sends `_budget_line` down its verbatim carousel branch,
      so `{{text_budgets}}` states the headline ceiling and says in so many words that a panel
      string carries none. A translate prompt that contained a per-slide character number would be
      a shortening brief wearing a translation's title, and the test for it is literal: the
      rendered prompt may not contain the substring `(at most`. The follow-up compress call — when
      the run is in auto or compress mode — is where a ceiling legitimately appears, and it is a
      SEPARATE call with a separate template.
    - **`sibling_list` takes the fifth branch** (`translate_to`), which names both languages and
      repeats the no-shortening guarantee on the line the model reads last.
    """
    entries = [entry]
    offer = offers[entry.asset_id]
    context = build_context(
        trend=group.trend,
        style=_single_style(entries, run),
        campaign_brief=group.campaign_brief,
        creative_format=entry.creative_format,
        niche_descriptor=run.niche_descriptor,
        brand_context=run.brand_context,
        competitor_strings=_strip_terms(entry, run),  # M6: one strip pass over the fenced
        platform_conventions=_relevant(run.conventions, entries),  # trend texts as well
        text_budgets=run.budgets,
        # NORMALISED here, not raw, and through the SAME expression `_translate_block` uses
        # (`language_code(...)` with the raw value as its last-resort fallback). The work order
        # prints the target once and this sibling clause prints it again, so a config that spells
        # its platform language `en-US` — or `English` — would otherwise put two different names
        # for one language into one prompt: `translate to: en` at the top and `to en-US` on the
        # line the model reads last. One spelling rule at every rung of the ladder is the whole
        # reason `language_code` is public (D63).
        sibling_list=_sibling_list(
            entries, run, offers, True,
            translate_to=language_code(entry.language) or str(entry.language or "")),
        carousel_copy_mode=MODE_VERBATIM,
    )
    context["translate_panels"] = _translate_block(entry, offer, run)
    try:
        system = run.engine.render(_TRANSLATE_TEMPLATE, context)
    except (ValueError, LookupError) as exc:  # unresolved placeholder / missing template
        _warn(run.log, "copy_prompt_failed", str(exc))
        return {}
    result = await run.call(
        COPY_ROLE,
        [{"role": "system", "content": system},
         {"role": "user", "content": _TRANSLATE_CARRIER_TURN}],
        _translate_schema(),
        None,
    )
    if result.degraded or not isinstance(result.parsed, Mapping):
        return {}
    return _answers(result, entries)


def _translate_schema() -> dict[str, Any]:
    """The translate call's schema, generated from `CopyTranslated` (contracts item 10).

    The same construction as `_compress_schema` and `_selection_schema`: `asset_id` is excluded
    from the dataclass projection and re-added first by the engine, so the ANSWER fields belong to
    the dataclass and identity belongs to the envelope. The one field `CopyCompressed` does not
    have is `source_language`, and it reaches the wire because the dataclass carries it rather
    than because anybody hand-listed it here.
    """
    fields = json_schema_for(CopyTranslated, exclude={"asset_id"})["properties"]
    creative = {"type": "object", "properties": {"asset_id": {"type": "string"}, **fields},
                "required": ["asset_id", *fields], "additionalProperties": False}
    return {
        "name": "copy_translated",
        "schema": {"type": "object", "properties": {"creatives": {"type": "array",
                                                                  "items": creative}},
                   "required": ["creatives"], "additionalProperties": False},
    }


def _translate_block(entry: PlanEntry, offer: _Offer, run: _Run) -> str:
    """The `{{translate_panels}}` block: this creative's own deck, numbered by SOURCE POSITION.

    `_compress_block`'s shape with one line changed and one line REMOVED, and both differences are
    the contract:

        CREATIVE <asset_id> — translate to: en (English); source language: de
        caption source: <that post's own caption>
        1. <source panel 1, folded, IN FULL>
        3. <source panel 3>

    - **The header names both languages** instead of stating the mirror rule. This is the one
      place in this module where a language is told to a model rather than described, and it is
      not the engine guessing: the target is `entry.language` (the operator's own
      `run.languages[platform]`, set at ASSIGN) and the source is the ladder's — Virlo's
      `language_detected`, else the vision pass's deck-level reading. The English name in brackets
      is a courtesy for the codes anybody here actually renders; an unknown code prints as itself.
    - **No per-line budget, ever.** `_compress_block` writes `(at most N characters)` on every
      line; this block writes nothing, because a translation has no ceiling and a number on the
      line is the single most reliable way to turn a translation into a summary. The absence is
      asserted by a test on the rendered prompt.

    Everything else is deliberately identical, because everything else is FR-304's alignment
    rather than compress's: only ADMITTED positions are listed (`_panel_verdict` == ""), an
    unlisted number IS the instruction that the slide ships wordless, positions are numbered by
    SOURCE POSITION rather than re-numbered 1..N so `slide_texts[i - 1]` is readable by index, and
    every panel is shown IN FULL through `_folded` rather than `_display`-truncated — the shown
    text is the material being translated, and a truncated panel would be translated into a lie.

    `run` is taken for symmetry with `_compress_block`'s neighbours and for the language ladder,
    which reads `run.post_languages` when Virlo sent nothing.
    """
    if offer.post is None:
        return ""
    source = _source_language(entry, offer, run)
    target = language_code(entry.language) or str(entry.language or "")
    lines = [f"CREATIVE {entry.asset_id} — translate to: {target} "
             f"({_LANGUAGE_NAMES.get(target, target)}); source language: {source}",
             "caption source: " + (_folded(offer.captions[0].text) if offer.captions else
                                   "(none — return an empty caption and the engine "
                                   "assembles one from this post's own words)")]
    for position in range(1, _deck_length(entry, offer) + 1):
        text = offer.panels[position - 1] if position <= len(offer.panels) else ""
        if _panel_verdict(text):
            continue  # unlisted IS the instruction: that slide ships wordless (FR-304)
        lines.append(f"{position}. {_folded(text)}")
    header = ("One section per creative, each carrying that creative's OWN source deck. These "
              "panels are the content authority: translate them, never shorten them, and never "
              "write a slide from anything else on this page.")
    return f"{header}\n\n" + "\n".join(lines)


def _translate_field(text: str, brands: Sequence[str], entry: PlanEntry, run: _Run,
                     *, where: str,
                     blanked_into: list[str] | None = None) -> tuple[str, bool]:
    """One translated string through the engine's TWO backstops — `(text, stripped)`.

    `_compress_field`'s sibling, minus the third gate, and the missing gate is the whole point of
    the contract: there is **no `budget` parameter** and no `trim_words` call anywhere on this
    path. A translated line has no ceiling — it is the source deck's own panel said in another
    language, and the target language may simply need more characters — so a slide can never earn
    `text_trimmed` here. (The cover HEADLINE is ours and keeps its budget: `_translated` runs it
    through `_compress_field` with `offer.budgets["headline"]`, exactly as the other two contracts
    do.)

    What remains runs in the order of certainty, and both gates are the ones that were never about
    length:

    1. **Blocklist** (§1.5 layers 1 and 2, fail-closed, `apply_blocklist`'s mechanics and never a
       second implementation). A model asked to translate a panel can write a competitor's name it
       read in the fenced trend texts, so the strip runs on what came BACK as well as on what went
       in.
    2. **Social marks** (FR-319). The line is BLANKED, never edited: a translated sentence with
       its @handle cut out is a sentence nobody wrote and nobody proof-read. Aggregated through
       `blanked_into` so an eight-slide deck reports one finding rather than eight.

    Then the one LENGTH test that survives, and it is a sanity fence rather than a budget: past
    `PANEL_SANITY_CHARS` the returned string is not a translation of a slide, it is a runaway —
    the same ceiling a SOURCE panel faces on the way in, applied to what comes back for the same
    reason. It blanks the line and warns `translate_over_sanity`; it never trims, because trimming
    a translated line mid-thought is exactly the shortening this contract forbids.

    `stripped` reports the BLOCKLIST alone, exactly as it does on the compress path:
    `competitor_stripped` means "a name was removed", and nothing else may borrow that word.
    """
    out = apply_blocklist(text, brands) if (text and brands) else text
    stripped = out != text
    if out.strip() and _social_mark(out):
        if blanked_into is not None:
            blanked_into.append(f"{where} (carries {_excluded_marks(out, relaxed=True)})")
        else:
            _warn(run.log, "translate_scrub",
                  f"{entry.asset_id}: the translated {where} carried "
                  f"{_excluded_marks(out, relaxed=True)} and was BLANKED (FR-319/FR-343) — a "
                  "translated line is the model's own bytes, so the social-mark gate is "
                  "re-applied to what came back, and the line is removed whole rather than edited",
                  asset_id=entry.asset_id, field=where, text=out)
        return "", stripped
    if len(out) > PANEL_SANITY_CHARS:
        _warn(run.log, "translate_over_sanity",
              f"{entry.asset_id}: the translated {where} came back at {len(out)} characters, past "
              f"the {PANEL_SANITY_CHARS}-character sanity ceiling, and was BLANKED (FR-343). A "
              "translation is allowed to be longer than its source and this is not that: past "
              "this length the string is a runaway rather than a slide, and it is removed whole "
              "rather than cut, because cutting it mid-thought is the shortening this contract "
              "exists to forbid. The source panel is intact and a verbatim re-run renders it",
              asset_id=entry.asset_id, field=where, characters=len(out),
              sanity_ceiling=PANEL_SANITY_CHARS)
        return "", stripped
    return out, stripped


def _translated_deck(entry: PlanEntry, payload: Mapping[str, Any], offer: _Offer, run: _Run,
                     brands: Sequence[str]) -> _PanelDeck:
    """FR-343 — ONE walk producing the translated deck's `slide_texts` AND its `panel_map`.

    `_compressed_deck`'s shape, and the single walk is the same invariant for the same reason:
    `gauntlet._expected_blocks` builds the rendered deck's frame contract from
    `CopySet.slide_texts` while the gallery and the operator's audit read `panel_map`, so
    `deck.texts[i - 1]` and `deck.panel_map[i - 1]["source_text"]` are the same string by
    construction rather than by agreement.

    Per position, in this order:

    1. **The SOURCE panel faces `_panel_verdict` first**, exactly as both other walks do — the same
       three drop reasons, the same position-preserving wordless slide, the same three warnings. A
       panel past the sanity ceiling is a transcription accident, and a confident translation of an
       accident is worse than a wordless slide.
    2. **The already-target BACKSTOP.** If the model's own `source_language` names the language we
       are translating INTO and the line it returned is not the source's bytes, the SOURCE bytes
       ship, the row says `translated: False`, and one warning per creative names it. The model
       has just told us it rewrote a panel that needed no translation, and a rewrite nobody asked
       for is a rewrite we do not publish. It is a backstop and not a gate: the engine already
       decided this deck was foreign (the ladder said so before the call was paid for), so this
       fires only when the two readings disagree.
    3. **An admitted position takes `slide_texts[position - 1]`** — by INDEX, never by consuming a
       queue, so a model that answered "" for slide 2 leaves slide 2 wordless instead of pulling
       slide 3's line onto it. A short list pads; a long one is truncated and warned.
    4. **The engine's backstops run on what came back** (`_translate_field`): the blocklist, then
       the social-mark BLANK, then the sanity fence. No trim, ever.
    5. **The length-ratio AUDIT.** A shipped line under half or over twice its source panel's
       length warns and ships, and sets `deck.drifted` so the creative earns
       `translate_length_drift`. Translation legitimately changes length, so this can never be a
       gate — it is the receipt that tells the operator which card to read twice, exactly as
       `copy_not_verbatim` does on the verbatim path.
    6. **An admitted position answered with NOTHING renders wordless**, collected into one
       `translate_no_text` warning, and **a line for a position the SOURCE dropped is DISCARDED**
       (`translate_invented_text`). Translation fills no vacuums for the same reason compression
       does not: an empty source slide is a slide its author left wordless, and words of ours on
       it are the `invented_text` defect the post-render gate blocks whole decks for.
    """
    length = _deck_length(entry, offer)
    answered = _positional(payload.get("slide_texts"))
    #: The model's own reading of the panels' language, normalised the same way every other rung
    #: of the ladder is. It is evidence for the backstop below and NOTHING else — it never decides
    #: whether the call happens, because the call has already happened by the time it exists.
    answered_language = language_code(payload.get("source_language"))
    already_target = bool(answered_language) and answered_language == language_code(entry.language)
    deck = _PanelDeck()
    over: list[str] = []        # over the sanity ceiling — cited in characters
    marks: list[str] = []       # an @handle or a URL survived into the SOURCE panel text
    blanked: list[str] = []     # the source claimed words here and the strip took them all
    invented: list[str] = []    # the model wrote for a position the source left empty
    scrubbed: list[str] = []    # a translated line carried a social mark and was blanked
    silent: list[str] = []      # an admitted panel came back with nothing to render
    drift: list[str] = []       # a shipped line is under half or over twice its source's length
    untouched: list[str] = []   # the backstop fired: the source bytes ship, not the model's
    for position in range(1, length + 1):
        source = offer.panels[position - 1] if position <= len(offer.panels) else ""
        original = (offer.panels_original[position - 1]
                    if position <= len(offer.panels_original) else source)
        reason = _panel_verdict(source)
        ships = not reason
        if reason == _DROP_OVER_BUDGET:
            over.append(f"slide {position} ({len(source)} characters, sanity ceiling "
                        f"{PANEL_SANITY_CHARS})")
        elif reason == _DROP_MARKS:
            marks.append(f"slide {position} (carries {_excluded_marks(source, relaxed=True)})")
        elif reason == _DROP_EMPTY and position in offer.stripped_panels:
            blanked.append(f"slide {position}")
        model_text = answered[position - 1] if position <= len(answered) else ""
        text = ""
        translated = False
        if ships and already_target and model_text.strip() and model_text != source:
            # The model says these panels are ALREADY in the target language and then handed back
            # something other than their bytes. Ship the bytes (FR-343's backstop, plan 9f).
            text = source
            untouched.append(f"slide {position}")
        elif ships:
            text, cut_name = _translate_field(model_text, brands, entry, run,
                                              where=f"slide {position}", blanked_into=scrubbed)
            deck.stripped = deck.stripped or cut_name
            if text.strip():
                translated = True
                ratio = len(text) / len(source) if source else 1.0
                if ratio < _DRIFT_FLOOR or ratio > _DRIFT_CEILING:
                    deck.drifted = True
                    drift.append(f"slide {position} ({len(source)} characters in, {len(text)} "
                                 f"out, ratio {ratio:.2f})")
            elif not model_text.strip():
                # `_compressed_deck`'s exact condition, and for its exact reason: a line the
                # ENGINE rejected (scrubbed for a social mark, blanked at the sanity fence)
                # already has its own honest warning, and reporting it a second time as "the
                # model sent nothing" would double-count one finding and name the wrong cause.
                silent.append(f"slide {position}")
        elif model_text.strip():
            invented.append(f"slide {position} ({_display(model_text)})")
        deck.texts.append(text)
        deck.panel_map.append({"slide": position, "source_position": position,
                               # What SHIPS — the translated line, the source bytes the backstop
                               # kept, or "" for a wordless slide. Same key, same meaning, same
                               # walk as the other two contracts.
                               "source_text": text,
                               # The source panel as it arrived (pre-layer-3, per the provenance
                               # doctrine that original bytes are never rewritten). It is what the
                               # gallery renders beside our slide and what the FR-346 chip
                               # measures "translated from <lang>" against.
                               "source_text_original": original,
                               # FR-302 as amended: a translated slide quotes no label. The bytes
                               # are the model's rendering of the panel, not the panel.
                               "ref_label": "",
                               "drop_reason": reason,
                               "creator_stripped": position in offer.creator_stripped_panels,
                               "chrome_counter_stripped": position in offer.chrome_counter_panels,
                               "truncation_suspect": position in offer.truncation_suspect_panels,
                               # D54: nothing on this walk is compressed. A translated deck in an
                               # auto- or compress-mode run may have rows compressed AFTERWARDS,
                               # and `_auto_deck` rewrites this key on exactly those rows.
                               "compressed": False,
                               # D63: True only where the shipped text is the model's translation
                               # of `source_text_original` — never on a dropped position, never on
                               # a row the already-target backstop handed back its source bytes.
                               "translated": translated})
        deck.stripped = deck.stripped or (ships and (position in offer.stripped_panels
                                                     or position in offer.creator_stripped_panels))
    if len(answered) > length:
        _warn(run.log, "translate_list_truncated",
              f"{entry.asset_id}: the translate call returned {len(answered)} slide texts for a "
              f"{length}-slide deck; the extra {len(answered) - length} are discarded. The deck's "
              "length is the plan's (fixed at ASSIGN and priced at the Confirm gate), never the "
              "model's — a longer answer cannot buy a slide nobody paid for (FR-343/FR-95)",
              asset_id=entry.asset_id, answered=len(answered), slides=length)
    if over:
        _warn(run.log, "panel_over_budget",
              f"{entry.asset_id}: {len(over)} source panel(s) exceed the {PANEL_SANITY_CHARS}"
              f"-character sanity ceiling and are never translated (FR-304a) — {'; '.join(over)}. "
              "A panel that long is a transcription accident rather than a slide, and a confident "
              "translation of an accident is worse than a wordless slide; those slides render "
              "without text and keep their position", asset_id=entry.asset_id,
              sanity_ceiling=PANEL_SANITY_CHARS, slides=over)
    if marks:
        _warn(run.log, "panel_handle_or_url",
              f"{entry.asset_id}: {len(marks)} source panel(s) carry an @handle or a URL pointing "
              f"outside the technical allowlist, and may never become pixels (FR-319) — "
              f"{'; '.join(marks)}. They are not translated either: the gate is about identity, "
              "not language, and a translation of a line we may not render is still that line. "
              "Those slides render without text and keep their position",
              asset_id=entry.asset_id, slides=marks)
    if blanked:
        _warn(run.log, "panel_emptied_by_strip",
              f"{entry.asset_id}: {len(blanked)} source panel(s) had words and lost all of them to "
              f"the competitor strip (§1.5) — {'; '.join(blanked)}. Those slides render without "
              "text and keep their position", asset_id=entry.asset_id, slides=blanked)
    if untouched:
        _warn(run.log, "translate_already_target",
              f"{entry.asset_id}: the translate call reported these panels are already written in "
              f"{entry.language} and then returned different words for {len(untouched)} of them — "
              f"{'; '.join(untouched)}. Those slides ship their SOURCE bytes instead (FR-343): a "
              "panel that needs no translation needs no rewrite either, and a model that improves "
              "one is doing work nobody asked for and nobody proof-read. The engine's own language "
              "ladder said this deck was foreign, so the two readings disagree — the operator may "
              "want to check which one is right",
              asset_id=entry.asset_id, slides=untouched,
              model_language=answered_language, target_language=entry.language)
    if drift:
        _warn(run.log, "translate_length_drift",
              f"{entry.asset_id}: {len(drift)} translated line(s) measured under half or over "
              f"twice their source panel's length — {'; '.join(drift)}. They SHIP: a translation "
              "legitimately changes length and this engine has no ceiling for one, so this is an "
              "audit rather than a gate (A20's polarity, exactly like copy_not_verbatim). Read "
              "those slides beside their source panels in the gallery — a line at a third of its "
              "source's length is usually a summary, and this contract forbids summaries",
              asset_id=entry.asset_id, slides=drift)
    if invented:
        _warn(run.log, "translate_invented_text",
              f"{entry.asset_id}: the translate call wrote text for {len(invented)} position(s) "
              f"whose SOURCE panel has none — {'; '.join(invented)}. Discarded: translation fills "
              "no vacuums (FR-343). An empty source slide is a slide its author left wordless, and "
              "a slide of ours carrying words theirs never had is the `invented_text` defect the "
              "post-render gate blocks whole decks for",
              asset_id=entry.asset_id, slides=invented)
    if scrubbed:
        _warn(run.log, "translate_scrub",
              f"{entry.asset_id}: {len(scrubbed)} translated line(s) carried an @handle or a URL "
              f"outside the technical allowlist and were BLANKED — {'; '.join(scrubbed)}. The line "
              "is removed whole rather than edited: a translated sentence with its mark cut out is "
              "a sentence nobody wrote and nobody proof-read (FR-319/FR-343). Those slides render "
              "without text and keep their position", asset_id=entry.asset_id, slides=scrubbed)
    if silent:
        _warn(run.log, "translate_no_text",
              f"{entry.asset_id}: {len(silent)} admitted source panel(s) came back from the "
              f"translate call with nothing — {'; '.join(silent)}. Those slides render wordless "
              "beside a source slide that has words, which is the failure FR-304 exists to "
              "prevent; the panels themselves are intact and a `--copy-language source` re-run "
              "renders them in their own language, in full",
              asset_id=entry.asset_id, slides=silent)
    return deck


@dataclass(slots=True)
class _Translation:
    """One creative's whole translate pipeline, carried from `_translate_and_fit` to `_translated`.

    Three fields because the pipeline has up to two model calls and the resolution step needs the
    outcome of both:

    - `payload` — the TRANSLATE call's answer, or `None` when the call produced nothing. `None` is
      the only failure this object reports, and its caller answers it with the verbatim mapped
      deck plus `copy_degraded` and `copy_not_translated`.
    - `deck` — the finished translated deck (texts, panel map, `stripped`, `drifted`). Empty and
      unread when `payload` is `None`; kept non-optional so no caller has to guard a type it can
      already tell from `payload`.
    - `fit` — `(the follow-up compress call's answer or None, the offer that call was built from,
      the positions it was asked about)`, or `None` when the run is in verbatim language-length
      mode or nothing overflowed after translation. The offer travels with the answer because
      splicing needs the SAME offer the call was built from — its `panels` are the translated
      strings, not the source's.
    """

    payload: dict[str, Any] | None
    deck: _PanelDeck = field(default_factory=_PanelDeck)
    fit: tuple[dict[str, Any] | None, _Offer, list[int]] | None = None


async def _translate_and_fit(group: _Group, entry: PlanEntry, run: _Run,
                             offers: Mapping[str, _Offer]) -> _Translation:
    """One creative's translate pipeline: translate, then — if the run compresses — fit (FR-343).

    **Translate FIRST, measure SECOND, and the order is the whole point.** `_rows_over_budget` is
    called on `deck.texts`, the TRANSLATED strings, never on `offer.panels`: a 210-character
    German panel can be 260 characters of English or 170, and measuring the source would compress
    a row that ended up fitting and leave one that did not. That is why `_rows_over_budget` was
    written as a pure function of a list and a number back in D62 — this call site is the reason.

    The follow-up call is the ORDINARY compress call, unchanged. What makes it work on translated
    text is one `dataclasses.replace`: the offer it is handed carries the translated strings as its
    `panels`, so `_compress_block` prints the ENGLISH lines the model is being asked to shorten
    rather than the German ones it already rendered. `stripped_panels` is cleared with it, because
    that set names positions a COMPETITOR was cut from at offer time and re-reporting it against
    the translated deck would warn `panel_emptied_by_strip` a second time for the same finding.
    Everything else on the offer — the budgets, the creator/counter/suspect position sets, the
    caption candidates, `panels_original` — is deliberately untouched: the rows still describe the
    same source deck.

    In `compress` mode every non-empty translated row is listed (that mode compresses the whole
    deck by definition); in `auto` mode only the rows that overflow after translation are. In
    `verbatim` length mode there is no second call at all and `fit` stays `None`.

    The `only` keyword is handed on for AUTO alone, and that is a wording decision rather than a
    content one: under compress mode `over` is already every admitted position, so `only` would
    print exactly the same panel block and then swap the sibling line for auto's — "compress post
    P1's panels 1, 2, 3 (the ones over 40 characters)" on a deck where every panel is being
    compressed regardless of its length, several of them comfortably under that number. Passing
    `None` keeps the compress-mode sentence a compress-mode run has always sent. The positions
    still travel on `fit`, because `_translated` needs them to splice.

    A failed follow-up is NOT a failed translation: `fit` comes back with a `None` payload, and
    `_translated` ships the translated deck uncompressed with `translate_compress_failed` and
    `copy_degraded`. The deck keeps its language; it only keeps its length as well.
    """
    offer = offers[entry.asset_id]
    payload = (await _call_translate(group, entry, run, offers)).get(entry.asset_id)
    if payload is None:
        return _Translation(payload=None)
    deck = _translated_deck(entry, payload, offer, run, _strip_terms(entry, run))
    fit: tuple[dict[str, Any] | None, _Offer, list[int]] | None = None
    if run.carousel_copy_mode in (MODE_AUTO, MODE_COMPRESS):
        budget = offer.budgets.get("slide", 0)
        over = (_rows_over_budget(deck.texts, budget) if run.carousel_copy_mode == MODE_AUTO
                else [position for position, text in enumerate(deck.texts, start=1)
                      if text.strip()])
        if over:
            translated_offer = dataclasses.replace(offer, panels=tuple(deck.texts),
                                                   stripped_panels=frozenset())
            # `only` is the AUTO signal at the wire and nothing else. Under compress mode `over`
            # already IS every admitted position, so passing it would print an identical panel
            # block and then make `_sibling_list` write the auto clause over it — "compress post
            # P1's panels 1, 2, 3 (the ones over 40 characters)" on a deck where every panel is
            # being compressed by definition, some of them well under that number. Passing `None`
            # takes the compress branch instead ("compress post P1's panels to N characters per
            # slide"), which is the sentence a compress-mode run has always sent and the only one
            # that is true here. `fit` still carries `over` — the splice in `_translated` needs
            # the positions whatever the prompt said.
            answered = await _call_compress(
                group, [entry], run, {entry.asset_id: translated_offer},
                only={entry.asset_id: over} if run.carousel_copy_mode == MODE_AUTO else None)
            fit = (answered.get(entry.asset_id), translated_offer, over)
    return _Translation(payload=payload, deck=deck, fit=fit)


def _translated(entry: PlanEntry, translation: _Translation, offer: _Offer, group: _Group,
                run: _Run) -> _Written:
    """Turn one `CopyTranslated` answer (and its optional compress follow-up) into a shipped deck.

    The sibling of `_compressed` and `_auto`, and above the deck it is identical to both: the
    call's own caption, headline and hashtags go through the same three backstops
    (`_compress_field`, `_compressed_caption`) and earn the same three tags on the same terms. The
    caption comes from the TRANSLATE payload even when a compress call ran afterwards — that
    second call was asked about slide positions and nothing else, and its caption is ignored on
    purpose so the deck's prose has ONE author.

    The deck has two shapes:

    - **No follow-up** (verbatim length mode, or nothing overflowed after translation): the
      translated deck ships as `_translated_deck` built it, `copy_mode: verbatim`. That is the
      common case and it is the one FR-343 is really about — a deck whose language changed and
      whose lengths did not.
    - **A follow-up landed**: `_auto_deck` splices the compressed lines into the TRANSLATED deck
      exactly as it splices them into a verbatim one, because that is what the translated offer
      made it — same function, same order, same `auto_row_kept_verbatim` rule (a compressed row
      that came back empty keeps its translated bytes; long beats wordless). Then every row's
      `translated` flag is carried across from the translate walk, every `ref_label` is emptied
      and `refs` is cleared, because a translated row quotes no label whether or not it was
      compressed afterwards — `_auto_deck` would otherwise leave the untouched rows holding the
      `P<n>.panel.<i>` labels `_mapped_deck` writes, and those labels claim a byte identity this
      deck gave up when it changed language. Each row's `drop_reason` is carried across for the
      same kind of reason: the second walk sees the TRANSLATED strings, so a position the SOURCE
      lost to an @handle or to the sanity ceiling reads back as a plain `empty` there, and that
      is the reason the render contract and the gallery would go on to state.

    `copy_mode` then says what the SLIDES are: `compress` when the run compressed the whole deck,
    `auto` when some rows were compressed and some were not, `verbatim` when none were. It is the
    LENGTH receipt and it stays honest about length alone; `copy_language` beside it is the
    language receipt, and this function is the only place in the module that can set it to
    `target`.

    **`copy_language` is read off the ROWS, not off the fact that a translate call happened.** It
    is `target` when at least one row's `translated` flag is True and `source` otherwise, because
    the receipt has to describe the bytes that shipped rather than the money that was spent. The
    shape that makes the difference real is the already-target backstop firing on EVERY position:
    the model answered that these panels are already written in the platform's language, so every
    row shipped its source bytes with `translated: False`, and the deck the operator receives is
    word for word the deck a `--copy-language source` run would have produced. Calling that
    `target` would tell the gallery, `meta.yaml` and the previews that the words were translated
    when nothing was.

    Saying `source` there is also what RAISES the audit signal, deliberately. `_write_group` tags
    `copy_not_translated` on any creative that was in `translating` and came back with a
    provenance that does not say `target` — so this deck earns the tag, and that is the intended
    outcome, not a false positive: a translation was wanted, a call was paid for, and the pixels
    are in the source language. The two readings disagreed (the engine's ladder said foreign, the
    model said already-target) and `translate_already_target` names that disagreement on the same
    creative; the tag is what puts it in front of the operator before nine decks render.

    `quoted=()` for the same reason `_compressed` uses it: nothing here claims to be a
    byte-substring of the post, so `_verify`'s half 1 self-skips while its blocklist half still
    audits every string that ships.
    """
    brands = _strip_terms(entry, run)
    payload = translation.payload or {}
    tags: list[DegradationTag] = []
    own_words: list[str] = []
    deck = translation.deck
    copy_mode = MODE_VERBATIM
    if translation.fit is not None:
        compressed_payload, translated_offer, over = translation.fit
        if compressed_payload is None:
            tags.append(DegradationTag.COPY_DEGRADED)
            _warn(run.log, "translate_compress_failed",
                  f"{entry.asset_id}: this deck was translated into {entry.language} and the "
                  "follow-up compress call failed, so it ships translated and UNCOMPRESSED "
                  "(FR-343/FR-353). The expensive half succeeded: every admitted panel is in the "
                  "target language, in its own position. What is missing is the fit to this "
                  f"style's {offer.budgets.get('slide', 0)}-character slide budget, so the long "
                  "lines render long — the pre-D62 outcome, not a loss of the deck",
                  asset_id=entry.asset_id, positions=list(over),
                  budget=offer.budgets.get("slide", 0))
        else:
            deck = _auto_deck(entry, compressed_payload, translated_offer, run, brands, over)
            # Both walks run `_deck_length(entry, ...)` over the same entry, so the two maps are
            # the same length by construction — the bounds check is here because a row that
            # silently kept `_mapped_deck`'s `P<n>.panel.<i>` label would be claiming a byte
            # identity this deck gave up when it changed language, and that is not a claim to
            # leave resting on an arithmetic coincidence.
            #
            # `drop_reason` is carried across for a harder reason than tidiness: `_auto_deck`
            # re-walks `_mapped_deck` over the TRANSLATED offer, whose `panels` are the translated
            # strings, so a position the SOURCE panel lost — an @handle panel (FR-319), a panel
            # past `PANEL_SANITY_CHARS`, a panel the competitor strip emptied — arrives at that
            # walk as `""` and re-reads as the blandest reason there is, `empty`. The row then
            # tells `generate/contracts.py` that the slide is wordless because the source had no
            # words, when in truth the source had words this engine may not render. The frame
            # contract prints that reason to the render model and the gallery shows it to the
            # operator, so the SOURCE walk's verdict is the only honest one and it wins here.
            #
            # The other three per-row facts — `creator_stripped`, `chrome_counter_stripped`,
            # `truncation_suspect` — cannot drift and are deliberately NOT copied: both walks read
            # them out of the same position sets on the same offer (`dataclasses.replace` changed
            # `panels` and `stripped_panels` and nothing else), so they are already identical and
            # copying them would only suggest they might not be.
            for index, row in enumerate(deck.panel_map):
                if index < len(translation.deck.panel_map):
                    source_row = translation.deck.panel_map[index]
                    row["translated"] = source_row["translated"]
                    row["drop_reason"] = source_row["drop_reason"]
                row["ref_label"] = ""
            deck.refs = {}
            deck.stripped = deck.stripped or translation.deck.stripped
            deck.drifted = translation.deck.drifted
            copy_mode = (MODE_COMPRESS if run.carousel_copy_mode == MODE_COMPRESS
                         else MODE_AUTO if any(row["compressed"] for row in deck.panel_map)
                         else MODE_VERBATIM)
    headline, headline_trimmed, headline_stripped = _compress_field(
        str(payload.get("headline") or ""), offer.budgets.get("headline", 0), brands,
        entry, run, where="headline")
    caption, hashtags, caption_stripped = _compressed_caption(payload, offer, entry, run, brands,
                                                              own_words)
    copyset = CopySet(
        asset_id=entry.asset_id,
        language=entry.language,
        trend_key=entry.trend_key,
        caption=caption,
        hashtags=hashtags,
        headline=headline,
        slide_texts=deck.texts,
        narrative_arc=str(payload.get("narrative_arc") or ""),
        through_line=str(payload.get("through_line") or "") or _subject_name(entry, group),
    )
    if not (headline or any(text.strip() for text in deck.texts)):
        tags.append(DegradationTag.NO_ONIMAGE_TEXT)
        _warn(run.log, "no_onimage_text",
              f"{entry.asset_id}: the translate call returned no usable text for any slide of "
              f"this deck and no cover headline; shipping a caption-only creative (FR-343). Its "
              f"{sum(1 for text in offer.panels if text.strip())} source panel(s) are unchanged "
              "and a `--copy-language source` re-run renders them in full, in their own language",
              asset_id=entry.asset_id, budgets=dict(offer.budgets),
              source_panels=len(offer.panels))
    if deck.trimmed or headline_trimmed:
        # Never from a slide on the translate path — `_translate_field` has no budget and cannot
        # trim. It is the cover headline (ours, and budgeted) or a line the FOLLOW-UP compress
        # call overshot its stated ceiling with, which is compress's backstop doing its job.
        tags.append(DegradationTag.TEXT_TRIMMED)
    if deck.stripped or caption_stripped or headline_stripped:
        tags.append(DegradationTag.COMPETITOR_STRIPPED)
        _warn(run.log, "competitor_stripped",
              f"{entry.asset_id}: a blocklisted competitor name, or the source creator's own name "
              "(FR-312), was removed from this creative's text (§1.5). On the translate path the "
              "strip runs on both sides — the panels the model was shown and the lines it sent "
              "back — because a translated line is the model's bytes, not the source's, and a "
              "model translating a panel can write a name it read anywhere else on the page",
              asset_id=entry.asset_id, refs={}, copy_mode=copy_mode,
              creator_lines=sorted(offer.creator_stripped_panels))
    if deck.drifted:
        tags.append(DegradationTag.TRANSLATE_LENGTH_DRIFT)
    # The LANGUAGE receipt, read off the shipped rows and never off the fact that a call ran. See
    # the docstring above: a deck every row of which came back untranslated is a deck in its
    # source language, whatever the call cost, and saying `target` over it would be the one lie
    # `_write_group`'s `copy_not_translated` audit has no way to catch.
    copy_language = (LANGUAGE_TARGET if any(row["translated"] for row in deck.panel_map)
                     else LANGUAGE_SOURCE)
    return _Written(
        copyset=copyset,
        source=CopyProvenance(post_id=offer.post.post_id if offer.post else "",
                              refs={},  # FR-302 as amended: a translated slide quotes no label
                              panel_map=deck.panel_map,
                              source_panel_count=len(offer.panels),
                              copy_mode=copy_mode,
                              copy_language=copy_language,
                              source_language=_source_language(entry, offer, run)),
        tags=tags,
        # FR-343: nothing here claims to be a byte-substring of the post — the words are in
        # another language — so the pool is empty and `_verify`'s half 1 self-skips. The blocklist
        # half runs on every shipped string regardless; it reads the CopySet, not this tuple.
        quoted=())


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
    So the creative ships what is unambiguously ours AND says nothing about the post it refused:
    the topic's own name, hashtags assembled from that name, and NO on-image text
    (`no_onimage_text`, which is what the operator will actually see in the frame). This is the
    one caption path with no source line in it at all — the offer paths promote the bound post's
    own hook, and FR-307 forbids exactly that here: the post is refused, so it may not be quoted,
    not even for a caption. The standing niche line used to be appended and is gone (v2.2.0): the
    operator's configuration is not caption copy.

    Two tags, and the second one only where it is true: `no_onimage_text` always (the frame is
    wordless whatever the reason), plus `no_fresh_post_available` when the post was BURNT — the
    same FR-73 spelling `plan.assign` uses for its own skip of the same condition, so the operator
    reads one vocabulary whichever gate caught it. A `bound_post_missing` refusal is a different
    fault (the topic changed under the plan) and does not borrow that word; it lives in the log
    line `_bound_index` already wrote.
    """
    name = _subject_name(entry, group)
    caption = _fallback_caption(name)
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
          "the topic name alone (a refused post may not be quoted, FR-307) and renders "
          "without on-image text. No "
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
    else:  # the bound post carries no §0.7-worthy caption: its own best line, attributed by us
        caption, hashtags = _offer_caption(offer, entry, run), []
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
             else "that post's own best line under our own attribution")
          + " — lost to the failure: through-line and narrative arc only (FR-99)",
          asset_id=entry.asset_id, reason="copy_call_failed",
          copy_source_post_id=offer.post.post_id if offer.post else "")
    return _Written(
        copyset=copyset,
        source=CopyProvenance(post_id=offer.post.post_id if offer.post else "", refs=refs,
                              panel_map=deck.panel_map,
                              source_panel_count=len(offer.panels),
                              # D63/FR-346: recorded even on the degrade tier, and especially
                              # here. This is the deck a failed TRANSLATE call falls back to, so
                              # the pair reads `copy_language: source` beside the foreign code the
                              # ladder found — which is exactly the evidence behind the
                              # `copy_not_translated` tag `_write_group` adds on top of it.
                              source_language=_source_language(entry, offer, run)),
        tags=tags,
        quoted=(*offer.haystack, *own_words))


def _fallback(entry: PlanEntry, trend: TrendItem | None, run: _Run) -> _Written:
    """FR-99's last resort — the copy call produced nothing for this creative.

    `copy_degraded` AND `no_onimage_text` travel together here and stay two facts: the first is an
    LLM outcome FR-248 counts as `llm_starved` (exit 1 — a failed copy call is a loss to surface
    even though the content it falls back to is now legitimate), the second is what the operator
    will actually see in the frame.
    """
    copyset = _fallback_copy(entry, trend, run.competitors, log=run.log)
    top = _top_post(trend)
    # This tier quotes P1, NOT the creative's assigned post — there is no answer to honour a
    # divergence rule with, and the top post is the one the operator would have picked. Provenance
    # is recorded only when the caption really did come from it (an empty caption falls through to
    # the topic name and its slug tags, which claim nothing and are verified against themselves).
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
          + ("the top post's caption verbatim" if quoted else "the topic name and its slug tags")
          + " and NO on-image text (FR-99)",
          asset_id=entry.asset_id, reason="no_onimage_text",
          copy_source_post_id=top.post_id if top and quoted else "")
    return _Written(
        copyset=copyset,
        source=CopyProvenance(post_id=top.post_id if top and quoted else "", refs=refs),
        tags=[DegradationTag.COPY_DEGRADED, DegradationTag.NO_ONIMAGE_TEXT],
        quoted=sources if quoted else (copyset.caption, *copyset.hashtags))


def _fallback_copy(entry: PlanEntry, trend: TrendItem | None,
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
    back to what is ours: the topic's own name (the monitor's theme label) and the hashtags its
    slug yields, and `through_line` carries the theme name so `reel_director.md` still knows what
    the clip is about. The niche descriptor was part of that assembled caption until v2.2.0 and is
    not any more (FR-99/FR-307 caption forms): a caption is not a place to publish configuration.

    The scrub the caption gets is `_scrubbed`'s, and it is the SAME expression `_fallback` builds
    the verifier's pool with — OCR repair, the blocklist, the creator's lines and name, the fuzzy
    near-miss pass and the CTA/dangling-promo sentence removal, in that order. Product and pool
    diverging by one pass is how a successful strip gets reported as `copy_not_verbatim`, so the
    only difference between the two call sites is that this one REPORTS what it removed.

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
        # Layers 1 and 3a deterministically, then FR-312's fuzzy caption pass and the CTA/promo
        # removal — this IS a caption, and it is the tier with no model and no offer table between
        # the source and the operator. `log` is optional so the function stays callable as a pure
        # builder; when it is present, the OCR repair, every fuzzy removal and every stripped
        # sentence are reported exactly the way the main path reports its own.
        _repaired(post.caption, kind="caption", asset_id=entry.asset_id,
                  post_id=str(post.post_id), log=log)  # reports; `_scrubbed` applies it
        text, _ = _fuzzy_caption(_scrubbed(post.caption, competitors, terms), terms,
                                 entry.asset_id, str(post.post_id), log)
        text = _strip_cta(text, entry.asset_id, str(post.post_id), log)
        body, tags = _split_trailing_hashtags(text)
        if _caption_substance(body) >= _CAPTION_MIN_CHARS:
            caption, hashtags = body, list(tags)
    if not caption.strip():
        caption, hashtags = _fallback_caption(name), _hashtags(name)
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


def _fallback_caption(name: str) -> str:
    """Our own caption when nothing may be quoted at all: the topic's theme name, and only that.

    **The niche descriptor is gone from here, deliberately and permanently (FR-99/FR-307 as
    amended, v2.2.0).** It used to be appended — `NicheConfig.as_text()`, operator-authored config
    — on the reasoning that a config string is ours and therefore safe to publish. The 08-14 audit
    settled that: safe to publish and fit to publish are different questions, and
    "AI tool stacks — AI automation for Czech SMBs; audience: operations leads who buy outcomes."
    went out as a caption on a paid creative. The niche descriptor steers the copy PROMPT
    (`build_context(niche_descriptor=...)`) and has no other business in this module.

    The topic name is the monitor's own theme label, so this string still makes no verbatim claim
    and needs none. It is the LAST resort of the two paths that may not quote: `_refused` (FR-307
    forbids quoting the post it just refused) and `_fallback_copy` with no usable post caption,
    where `_hashtags` adds the slug tags alongside it.
    """
    return name


class NoSafeCaptionError(RuntimeError):
    """An offer path had no caption it was ALLOWED to ship — raised while the run is pre-spend.

    Reachable only from `_offer_caption`, i.e. only when a creative's BOUND post offered no
    caption clearing §0.7's substance floor AND not one of its hooks, overlays or panels survived
    the strips as a publishable line. Every safe form has been tried by then, and the two that
    remain are both defects: improvising a caption out of config (the leak this amendment removes)
    or shipping a creative with an empty `caption.txt` into the publisher.

    So the module refuses instead, and it refuses HERE — copy runs before any render is submitted,
    so `NO_SAFE_CAPTION` costs the operator nothing but the LLM call already made. `code` is the
    machine-readable name the runner and the operator docs use.
    """

    code = "NO_SAFE_CAPTION"

    def __init__(self, asset_id: str, post_id: str) -> None:
        super().__init__(
            f"{asset_id}: its bound source post ({post_id or 'unknown'}) offers no caption this "
            "engine may ship — no caption candidate cleared the substance floor and no hook, "
            "overlay or panel survived the competitor/creator strips as a publishable line. The "
            "run stops here, before any render is submitted (NO_SAFE_CAPTION): a caption "
            "assembled out of configuration is what this refusal exists to prevent")
        self.asset_id = asset_id
        self.post_id = post_id


def _offer_caption(offer: _Offer, entry: PlanEntry, run: _Run) -> str:
    """The caption for a bound creative whose own post offered none — its words, our attribution.

    **The offer paths' safe form (FR-99/FR-307 caption forms, v2.2.0).** `_resolve` and
    `_mapped_fallback` both reach a point where the model chose no caption and the post has none
    worth §0.7: this creative is quoting that post everywhere else, so the honest caption is the
    post's own best remaining line — a hook first (it is written to be read on its own), else an
    overlay, else a panel — followed by a neutral attribution that names no account.

    The line arrives here already through §1.5 layers 1 and 3 and free of social marks
    (`_offer_for` collected it that way), and it goes through `_scrubbed(caption=True)` on the way
    out because a line promoted INTO a caption must face the caption-scoped passes its neighbours
    faced: the fuzzy creator strip and the CTA/dangling-promo removal. `_scrubbed` is the silent
    door on purpose — the alternative is warning about lines this function then rejects — and the
    one event it does emit names the promoted line and what shipped.

    Nothing usable left raises `NoSafeCaptionError`. There is no third option that is not a leak.
    """
    post_id = str(offer.post.post_id) if offer.post is not None else ""
    for line in offer.caption_fallbacks:
        text = _scrubbed(line, run.competitors, offer.caption_terms, caption=True).strip()
        # The same sanity fence a mapped panel faces (`PANEL_SANITY_CHARS`), for the same reason:
        # past it the string is a transcription accident — a whole caption scraped into one panel
        # — and a transcription accident is not a caption either. The floor below is the other
        # end: a line has to be a sentence before it can be one.
        if len(text) > PANEL_SANITY_CHARS or _caption_substance(text) < _FALLBACK_LINE_MIN_CHARS:
            continue
        caption = f"{text} {_NEUTRAL_ATTRIBUTION}"
        _warn(run.log, "copy_caption_assembled",
              f"{entry.asset_id}: post {post_id} offers no caption clearing the "
              f"{_CAPTION_MIN_CHARS}-character substance floor (§0.7), so the creative captions "
              f"itself with that post's own line {text!r} plus a neutral attribution naming no "
              "account (FR-99/FR-307 caption forms). The operator's niche descriptor is never a "
              "caption — it steers the prompt and nothing else",
              asset_id=entry.asset_id, post_id=post_id, line=text)
        return caption
    raise NoSafeCaptionError(entry.asset_id, post_id)


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


def _guarded(written: _Written, entry: PlanEntry, offer: _Offer,
             run: _Run) -> list[DegradationTag]:
    """FR-362/FR-363 — run the contract guards over one creative's finished copy. THE seam.

    ONE call site (`_write_group`'s per-entry loop) covers every path this module has: the
    verbatim mapping, the compressed deck, the auto splice, the translated deck, both degrade
    tiers and the free-text brief. That is deliberate and it is the whole design decision behind
    this function. Guarding inside each walk would mean four implementations of one rule, drifting
    apart the first time a fifth contract is added — and it is exactly how `panel_map` came to
    carry corrupted rows in the first place: every walk knew its own invariants and nobody checked
    the SHAPE they all produce. Here there is one shape, checked once, after everything that
    writes it has finished writing.

    It runs BEFORE `_verify` because the verifier reads what ships: a guard that put the source's
    own bytes back must be audited on those bytes, not on the ones it rejected. Every string a
    guard authored joins `written.quoted` on the way through, for the same reason `_auto`'s
    compressed lines join it — a restored original is not a quote gone missing, and reporting it
    as `copy_not_verbatim` would bury the rows where that check still has teeth.

    Mutation is deliberate and narrow: `panel_map` rows are REPLACED (the guard module never
    mutates the caller's dicts — it returns new ones), `slide_texts` is re-read off those rows so
    the two can never disagree, a withdrawn `ref_label` is dropped from `refs` in the same breath,
    and the caption is written back scrubbed. Nothing else on the `_Written` is touched.

    The deck half is skipped — loudly — when the rows and the slide texts disagree in count or in
    content. That invariant (`slide_texts[i] is panel_map[i]["source_text"]`) holds on all four
    walks by construction, and a deck where it does not hold is a deck this function has no honest
    way to guard: rewriting one side would silently re-map the other. The caption half still runs.
    """
    tags: list[DegradationTag] = []
    post_id = str(offer.post.post_id) if offer.post is not None else ""
    identifiers = tuple(offer.creator_identifiers)
    # `sanctioned=()` on purpose (D65): nothing is a sanctioned tool mark at COPY time. The patch
    # crop that sanctions a mark for rendering happens later, in `generate/carousel`, and Wave 2
    # of D65 is what joins the two. Until then guard 9's rule is the conservative one — a row that
    # is nothing but a mark the source stamped on its slide is chrome — and `mark_identifiers`
    # carries the seam for the caller that will have the patch list.
    marks = mark_identifiers(run.brand_marks.get(post_id, ()) if post_id else ())
    rows, slides = written.source.panel_map, written.copyset.slide_texts
    aligned = len(rows) == len(slides) and all(
        str(row.get("source_text") or "") == text for row, text in zip(rows, slides))
    if rows and not aligned:
        _warn(run.log, "panel_map_desynced",
              f"{entry.asset_id}: this creative's {len(rows)} panel_map row(s) and "
              f"{len(slides)} slide text(s) do not carry the same strings, so the FR-362 contract "
              "guards were skipped for its deck — there is no honest way to repair one side "
              "without silently re-mapping the other. The creative ships as its copy walk built "
              "it; its caption is still guarded", asset_id=entry.asset_id,
              rows=len(rows), slides=len(slides))
    if rows and aligned:
        guarded = guard_deck(rows, asset_id=entry.asset_id,
                             # The walks' OWN admission gate, passed in rather than re-implemented:
                             # a restored panel faces the same social-mark and sanity-ceiling tests
                             # `_mapped_deck` applied, and a second copy of those rules living in
                             # the guard module is how the two would come to disagree.
                             admits=lambda text: not _panel_verdict(text),
                             identifiers=identifiers, marks=marks,
                             source_panel_count=written.source.source_panel_count)
        written.source.panel_map = list(guarded.rows)
        written.copyset.slide_texts = list(guarded.texts)
        for slot in guarded.dropped_refs:
            written.source.refs.pop(slot, None)
        tags.extend(guarded.tags)
        written.quoted = (*written.quoted, *guarded.authored)
        for warning in guarded.warnings:
            _warn(run.log, warning.event_type, warning.message, **warning.data)
    caption = guard_caption(written.copyset.caption, asset_id=entry.asset_id,
                            identifiers=identifiers, marks=marks,
                            # The VOICE test asks whether this caption is the source creator's own
                            # story. An override brief's caption is written from the operator's
                            # directives, so a first-person sentence in it is the operator — and a
                            # tag that fires on our own house style is a tag the operator learns
                            # to skip. The identity scrub runs either way.
                            quoted=offer.post is not None)
    written.copyset.caption = caption.caption
    if caption.scrubbed:
        written.quoted = (*written.quoted, caption.caption)
    tags.extend(caption.tags)
    for warning in caption.warnings:
        _warn(run.log, warning.event_type, warning.message, **warning.data)
    return tags


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
       `CopySet`. It is skipped for free-text creatives, which quote nothing and claim nothing —
       and, since D54/FR-331, for COMPRESSED ones, on exactly the same mechanism and for exactly
       the same reason: `_compressed` returns `_Written(quoted=())`, so `written.quoted` is falsy
       and this half never runs. That is deliberate and it is why this function needed no change
       for compress mode. A compressed slide makes no byte-substring claim to audit; its receipts
       are `CopyProvenance.copy_mode`, the panel map's `compressed` rows and their
       `source_text_original`. Half 2 below is unaffected and still reads every string that ships.

       **An AUTO creative (D62/FR-353) is the case where half 1 is neither run wholesale nor
       skipped wholesale — it is satisfied ROW BY ROW.** `_auto` returns a pool that is the post's
       own strings PLUS every string that call authored and shipped (the spliced slide texts, the
       caption, the headline, the hashtags). So a slide that shipped verbatim is checked for real
       — it must be a byte-substring of the post, and a splicing bug that overwrote a quoted row
       would surface here as `copy_not_verbatim` — while a compressed slide is in the pool itself
       and passes by construction, which is the same outcome the empty pool buys a fully
       compressed deck, arrived at without blinding the check on the rows that still make a claim.
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


__all__ = ["COPY_ROLE", "LANGUAGE_SOURCE", "LANGUAGE_TARGET", "MODE_AUTO", "MODE_COMPRESS",
           "MODE_VERBATIM", "PANEL_SANITY_CHARS", "CopyProvenance", "CopyResult",
           "NoSafeCaptionError", "write_copy"]
