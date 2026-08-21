"""Shared contracts — the Wave-1 barrier artifact every other module imports.

Dataclasses, enums, type aliases and pinned call signatures only, so modules agree on shape
without importing each other. FR references are the spec (`prds/`), not decoration. NOT here:
logic, I/O, provider field names, config defaults, non-stdlib imports. Additions via the
conductor only (plan §3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Literal, Protocol

# Closed vocabularies that are config strings, not enums.
CreativeFormat = Literal["image", "carousel", "reel"]  # 10 FR-1
InfluenceMode = Literal["override", "blend"]  # 10 FR-144/145, D26
Platform = str  # platform names are config keys (30 §2), never hardcoded


class DegradationTag(str, Enum):
    """FR-73's `degradations` vocabulary — SINGLE source for meta.yaml and gallery badges.
    Clean asset = empty list; each tag's behaviour is owned by the FR that emits it, this enum
    owns only the spelling, so a new tag needs no schema change (the gallery loops over them).
    """

    COPY_DEGRADED = "copy_degraded"  # FR-99 (Notion absence is a warning, never a tag)
    # KEPT, REDEFINED at W2 (v2.0.0, contracts item 7): "no source string fits this style's
    # on-image budget — caption-only creative." Under the §1.7 verbatim contract an over-budget
    # string is never offered, so an empty frame is a legitimate degrade, not a failure; the tag
    # tells the operator WHY the frame is wordless. Still also set by `_fallback_copy` beside
    # COPY_DEGRADED (a failed copy call ships the top post's caption verbatim + no on-image
    # text): the first is an LLM outcome the run summary counts (FR-248's `llm_starved` set),
    # the second is what the operator will actually see in the frame.
    NO_ONIMAGE_TEXT = "no_onimage_text"
    # FR-100/101 (v2.0.0) — the verifier's polarity flip: post-pivot every on-image string must be
    # a byte-substring of the quoted `SourcePost`, so this marks the one case where a rendered
    # string drifted from its source. Audit signal only; it NEVER fails the creative — the
    # creative is already made, and the operator needs to know which card to distrust, not to be
    # handed fewer cards.
    COPY_NOT_VERBATIM = "copy_not_verbatim"
    # FR-294 — a competitor brand name was removed from this creative's text (blocklist or the
    # filter's `strip` verdict). The copy is still sourced; it is simply no longer byte-identical,
    # which is exactly what the verifier above would otherwise report as a deviation.
    COMPETITOR_STRIPPED = "competitor_stripped"
    # FR-295 — pre-D46: the assigned meta-style's reference images were missing or unusable, so
    # the style shipped as text-only. D46/F3 removed the picture channel entirely, so nothing
    # emits this any more; the member survives because FR-73's amended vocabulary still lists it
    # and older meta.yaml files on disk still carry it (the gallery must keep rendering those).
    STYLE_REFS_MISSING = "style_refs_missing"
    # --- D46 / v2.1.0 (FR-73's amended vocabulary, four new spellings) ---
    # FR-306 — the slide-intelligence pass supplied on-image text Virlo had not transcribed: at
    # least one of this deck's slides carries the VISION reading of the source panel rather than
    # Virlo's own `panel_texts[i]`. Still verbatim (it is the words that were on that slide) and
    # still position-preserving; the tag says which reading the operator is looking at, because a
    # transcription can misread a glyph in a way a Virlo panel cannot.
    VISION_TRANSCRIBED = "vision_transcribed"
    # FR-306 — the vision call failed, timed out or had nothing readable to send, so the deck kept
    # the Virlo panels it already had and rendered without visual briefs. Fail-open by contract
    # (§0.14c): a source deck we could not read is never a reason to lose a creative the operator
    # has already approved spending on.
    VISION_UNAVAILABLE = "vision_unavailable"
    # FR-304/§0.4′ — the source deck was LONGER than the platform's carousel ceiling, so only its
    # first N panels were rendered. Indices are preserved (slide i is still source panel i); what
    # is lost is the tail, and the tag is what tells the operator the deck they see is a prefix of
    # the deck that was analysed. Emitted by `generate/carousel.py` against `source_panel_count`.
    PANELS_TRUNCATED = "panels_truncated"
    # FR-307/§0.10 — no unused source post was left for this creative. Emitted in two places, both
    # meaning the same thing: `plan.assign` skips a creative group outright when a topic's fresh
    # slideshow posts are exhausted, and `copywrite` refuses (belt-and-braces behind the fetch
    # gate) when the post the plan bound turns out to be burnt after all — that creative still
    # ships, with our own assembled caption and no on-image text. Famine over silent repeats: a
    # post an earlier run quoted is never quoted again, and no neighbour is substituted for it.
    NO_FRESH_POST_AVAILABLE = "no_fresh_post_available"
    # --- D62 / v2.6.0 (FR-351): cover best-of-N ---
    # FR-351 — `run.cover_candidates` ordered two or three slide-1 renders and the ONE vision pick
    # call that chooses between them could not be trusted (no metered call, a raised call, an
    # unparseable or out-of-range answer), so candidate 1 was committed as the anchor. Fail-open
    # on the style-match shape (§0.14c): the deck is exactly the deck a `cover_candidates: 1` run
    # would have made, plus the loser candidates kept under `covers/` for the operator to compare
    # by eye. Never set when fewer than two candidates landed — there was nothing to choose, so
    # nothing degraded.
    COVER_PICK_DEGRADED = "cover_pick_degraded"
    # --- D63 / v2.7.0 (FR-343/FR-346): output language ---
    # FR-343 — translation was WANTED for this deck (`run.copy_language_mode: target`, a bound
    # panel-mapped carousel, a known source language other than the platform's) and the deck
    # shipped its SOURCE language anyway: the translate call returned nothing and the creative fell
    # back to the FR-304 verbatim mapped deck (beside `copy_degraded`), or it ended on a path that
    # never translates (`_refused`). Audit signal and console-loud like `copy_degraded`; the
    # creative ships. Never set under `source` mode, on a post already in the platform's language,
    # or when the language is unknown — those are not failures to translate, they are decisions
    # not to, and each has its own warning.
    COPY_NOT_TRANSLATED = "copy_not_translated"
    # FR-343 — a shipped translated slide measured under half or over twice its source panel's
    # length. Translation may legitimately be longer than its source (the one copy boundary where
    # that is allowed), so this is an AUDIT of the ratio, not a gate on it: the line ships, the
    # warning names the slide and both lengths, and the operator knows which card to read twice
    # (A20 polarity, exactly as `copy_not_verbatim`).
    TRANSLATE_LENGTH_DRIFT = "translate_length_drift"
    # --- D65 / v2.9.0 (FR-362/FR-363): the panel-map contract guards ---
    # FR-362 guard 1 — a numeric token on a shipped slide disagreed with the same token on that
    # row's own `source_text_original`, beyond what the OCR confusable repair (I/l -> 1, O/o -> 0)
    # could heal: `I6GB` for `16GB` is a repair, `28GB` for `128GB` is a DRIFT. The row ships the
    # original bytes for the token that drifted — or the whole original panel where the token
    # structure differs too far to do surgery — and earns this tag. What it is written against is
    # measured: the 2026-08-21 audit found `I46K STARS`, `IOX` and `I4B-3OB` rendered as pixels
    # while the correct digits sat on the SAME panel_map row, and nothing in the engine ever
    # diffed the two.
    COPY_DIGIT_DRIFT = "copy_digit_drift"
    # FR-362 guard 2 — a row's shipped words had almost nothing in common with its own
    # `source_text_original` (content-word overlap under the alignment floor), which is what a
    # deck whose compressed rows slipped by one position looks like from the inside: run
    # `20260821_030722_4344`'s `Ig_car_..._08` carried the PREVIOUS repo's text on slides 4, 6 and
    # 8 while the right text sat one row up. The row ships the verbatim original instead (wordless
    # when the original cannot be admitted) and earns this tag. Also emitted when two rows claim
    # the same `source_position` — the first keeps it, the rest are realigned the same way.
    PANEL_MAP_REALIGNED = "panel_map_realigned"
    # FR-362 guard 6 — the coverage assertion found a source panel with NEITHER a panel_map row
    # NOR a recorded drop reason: the deck simply lost it, silently, and shipped as a success
    # (4344 `Ig_02`, source panels 11–12). Panels past the platform ceiling are NOT this — they
    # are `panels_truncated`, which is a decision the plan made and priced. This tag is only ever
    # the engine losing a panel it meant to map, so it is loud on the console as well as here.
    PANEL_DROPPED_UNMAPPED = "panel_dropped_unmapped"
    # FR-363 — the caption reads as the SOURCE creator's first-person voice ("I ran the
    # experiment…", "my stack…"): published under our account it is our life story, told about
    # someone else's life. The caption still ships VERBATIM (FR-331 — the engine does not rewrite
    # a quote to sound like us), so this tag is the whole action: it puts the caption loudly on
    # the console and on the gallery card, and the operator decides.
    CAPTION_VOICE_REVIEW = "caption_voice_review"
    # FR-365 — a landed frame came back with a see-through halo around its edges (an RGBA render
    # whose alpha band is ragged and transparent at the border instead of a flat opaque
    # rectangle), the ONE resubmit that defect is entitled to came back haloed too, and the frame
    # was composited onto an opaque ground sampled from its own centre rather than lost. Measured
    # on run `20260821_121514_q745`, whose LinkedIn cover shipped with 49% of the frame under
    # alpha 250 and every one of its thirteen sibling slides carrying no alpha channel at all —
    # so this is a rare, loud provider defect rather than a matter of degree. The pixels the
    # operator sees are therefore NOT byte-for-byte what the model returned, which is the whole
    # reason this is a tag: the deck ships, and the operator knows which card was repaired.
    ALPHA_FLATTENED = "alpha_flattened"
    # FR-370 — a carousel slide ordered a reserved screenshot plate (its source panel was read as
    # a captured interface, the box parsed, the source file was on disk and the identity screen
    # passed), the render drew the empty rectangle it was told to, and the local composite that
    # was supposed to fill it did not happen: the source file would not decode, the crop came back
    # too small, the disk was full, the backup could not be written. The slide ships with the
    # EMPTY PLATE, which is deliberately visible — the critics judge it as the defect it is and
    # this tag puts it on the gallery card, because a paste that silently did not happen would
    # leave a rounded hole in the middle of a paid frame with nothing anywhere saying why.
    SCREENSHOT_PASTE_FAILED = "screenshot_paste_failed"
    # --- D56 / v2.4.0 (FR-334): matched style assignment ---
    # FR-334 — the ONE batched style-matcher call failed outright (transport error, unparseable
    # answer, degraded `ParsedResult`), so EVERY entry in the plan kept the FR-291 rotation pick it
    # already had and the run continued. A whole-call tag, deliberately: it says the matcher never
    # spoke, which is a different fact from "the matcher looked at this creative and its best
    # candidate was a poor fit" — that case is per-entry, keeps the same baseline pick, and is
    # recorded as `style_origin: "rotation"` plus `style_wanted` rather than as a degradation. The
    # creative is never worse off than a `assignment: rotation` run would have made it, which is
    # exactly why this is fail-open (§0.14c) and never a failure: a style matcher that is
    # unavailable is not a reason to lose a creative the operator approved spending on.
    STYLE_MATCH_DEGRADED = "style_match_degraded"
    REFERENCE_FREE = "reference_free"  # FR-18
    REFS_DROPPED_MODERATION = "refs_dropped_moderation"  # FR-97
    TEXT_TRIMMED = "text_trimmed"  # FR-101
    INCOMPLETE = "incomplete"  # partial carousel, FR-20/95
    SKIPPED_BUDGET = "skipped_budget"  # FR-106
    ABANDONED = "abandoned"  # FR-108 deadline / FR-201 interrupt
    SEED_FRAME_RENDER_FAILED = "seed_frame_render_failed"  # FR-24
    SEED_FRAME_URL_UNREACHABLE = "seed_frame_url_unreachable"  # FR-24
    AUDIO_DROPPED_CONTENT_AUDIT = "audio_dropped_content_audit"  # FR-141 content-audit degrade
    #   (v1.6.6): clip re-submitted once with generate_audio=false; references kept


class PlanEntryStatus(str, Enum):
    """Run-side lifecycle of a plan entry (FR-4: nothing ever leaves the plan). Wider than
    `AssetStatus`, which is what meta.yaml persists — SKIPPED/SKIPPED_BUDGET/ABANDONED map to
    AssetStatus.FAILED plus the matching DegradationTag and a `skip_reason` line.
    """

    PENDING = "pending"
    SUBMITTED = "submitted"  # money has moved — spend tallies on submission (FR-106)
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"  # dropped for a non-budget reason (10 §10)
    SKIPPED_BUDGET = "skipped_budget"  # trimmed or cap-blocked (FR-28/106)
    ABANDONED = "abandoned"  # left in flight by deadline or Ctrl+C (FR-108/201)
    # FR-325 (v2.2.0, D49): the gauntlet's terminal refusal. The creative RENDERED — its slides are
    # on disk and its money is spent — but a critic panel found a standing defect the fix loop could
    # not clear, so it is never published. Deliberately NOT a flavour of FAILED: a failed entry has
    # nothing to show, a blocked one has a full folder plus a `GAUNTLET_REPORT.yaml` explaining why
    # it is being held back. It counts as a non-success everywhere success is what matters — the
    # trend-history `record_use` window and the `set_latest` satisfaction gate both exclude it, so a
    # blocked deck's source post is NOT burnt and the run can quote it again tomorrow.
    BLOCKED = "blocked"


class AssetStatus(str, Enum):
    """meta.yaml `status` (FR-73). PENDING only between folder creation and rewrite (NFR-21)."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    #: FR-325 (v2.2.0, D49) — rendered, paid for, kept on disk (FR-74) and NOT published: the
    #: gauntlet's three-tier terminal policy blocked it. `packager.block()` is the only writer;
    #: the gallery draws a BLOCKED badge rather than the failed-card path, and any BLOCKED asset
    #: makes the run exit 1. The artifacts stay precisely so an operator can look and decide.
    BLOCKED = "blocked"


class VisionCheckResult(str, Enum):
    """FR-27's four states — three cannot express "retried"."""

    PASSED = "passed"
    RETRIED_PASSED = "retried_passed"
    RETRIED_FAILED = "retried_failed"
    NOT_CHECKED = "not_checked"


@dataclass(slots=True)
class SourcePost:
    """One winning post inside a topic item — the unit verbatim copy quotes (§1.6/FR-293).

    Post-pivot the source posts ARE the asset: FR-99/100 number these fields as offerable
    candidates, the copy model returns REFERENCES into that numbering (`CopySelection`), and the
    engine resolves the reference back to these bytes. Everything here is therefore stored exactly
    as Virlo returned it — never translated, never retyped, never trimmed outside a word boundary
    — because a string that was edited on the way in can no longer be quoted verbatim on the way
    out. `views` is what ranks the list, and the rank is what the `P<n>` ref labels count over.
    """

    post_id: str
    url: str = ""  # permalink; goes to the roster line and to trend_history (FR-297b/FR-298)
    author: str = ""
    #: The creator's DISPLAY NAME, beside `author` (which carries the @handle form). FR-312's strip
    #: has always had two identity shapes to erase and only ever received one: the 08-14 audit found
    #: captions shipping "Emir | AI Lab" untouched while "@emirailab" was scrubbed, because the
    #: display name simply never reached the engine — `copywrite` reads this field and the adapter
    #: never wrote it. Empty is a legitimate value (an API that exposes no display name), and the
    #: strip degrades to handle-only rather than failing; it is never a substitute for `author`.
    author_name: str = ""
    caption: str = ""
    hooks: list[str] = field(default_factory=list)
    text_overlays: list[str] = field(default_factory=list)  # absorbs `text_overlay_contents`
    #: Per-slide words, INDEX-ALIGNED to `panel_count` (FR-293/FR-304, §0.14a of the D46 plan): slot
    #: *i* holds the text of source slide *i+1*, and a slide Virlo transcribed nothing for holds an
    #: empty string rather than closing the gap. The alignment is the contract — FR-304 renders OUR
    #: slide *i* from SOURCE panel *i*, so a compacted list would silently re-map slide 3's words
    #: onto slide 2 and produce a deck that reads as the source's with two slides swapped.
    panel_texts: list[str] = field(default_factory=list)
    description: str = ""
    views: int = 0
    # FR-297b's roster prints an age column and a type tag per post, and neither is derivable from
    # the fields above. `is_slideshow` additionally re-derives `TrendItem.is_slideshow` as the
    # majority over the topic's posts (§1.6), so format affinity stops being a per-monitor guess.
    published_at: datetime | None = None
    is_slideshow: bool = False
    # --- slideshow shape (v2.1.0, FR-293/FR-301): the three fields the adapter used to drop.
    #: How many slides the source deck has, per Virlo's own position-sorted image list. FREE and
    #: known at fetch, which is what lets ASSIGN fix the deck length before the Confirm gate
    #: (§0.4′) instead of discovering it after money moved. Zero on a video row, and zero on a
    #: slideshow row Virlo shipped without images — which is one of FR-305's drop reasons.
    panel_count: int = 0
    #: The slide image URLs, in panel order (the wrapper sorts them by Virlo's `position`), so
    #: `image_urls[i]` is the picture whose words are `panel_texts[i]`. ANALYSIS AND DISPLAY ONLY
    #: (D41 carve-out, FR-306): slide intelligence downloads them into `output/<run>/source/` and
    #: the gallery shows the local copies — a Virlo URL or byte never enters a render payload.
    image_urls: list[str] = field(default_factory=list)
    #: Virlo's own enrichment marker for this row (`"ready"` when its `intelligence` block is
    #: populated). Read as vision-eligibility evidence and logged on `topic_posts`; never a gate on
    #: its own, because rows enriched before a monitor's `data_intelligence_enabled` flipped still
    #: carry populated intelligence while the agent reports `false`.
    intelligence_status: str = ""
    # --- language (v2.7.0, D63/FR-293/FR-343): what tongue this post's own words are in.
    #: The two-letter ISO 639-1 code of the language THIS POST is written in, normalised at the
    #: adapter by `topic_filter.language_code`, so `"English"`, `"en-US"` and `"EN"` all arrive as
    #: `en` and no consumer ever has to re-parse a spelling. `""` means Virlo did not say — never
    #: "English", and never a reason on its own to drop a post. Virlo sends it free on every
    #: enriched row (`intelligence.language_detected`), which is the whole reason the output
    #: language decision costs nothing: the D63 translate ladder in `copywrite` reads THIS field
    #: first and only falls back to the vision pass's deck-level reading, and the `source`-mode
    #: bind screen in `plan` reads it to skip a post whose language is known and is not one this
    #: run writes in. NEVER a render input: it decides whether a translation is wanted and what
    #: gets recorded as provenance, and no code path turns it into a word on a slide.
    language: str = ""
    #: Virlo's `intelligence.is_multilingual` — this post mixes more than one language in its own
    #: words. It qualifies `language` rather than replacing it: on the captured corpus the single
    #: flagged row still reports `en`, so the code names the DOMINANT language rather than
    #: promising it is the only one, and a reader deciding how much to trust `language` wants both.
    #: `False` covers "one language" and "Virlo did not say" alike, because neither changes any
    #: decision here — a multilingual post is still bound and still quoted verbatim.
    multilingual: bool = False


@dataclass(slots=True)
class TrendItem:
    """One normalized trend item, assembled per configured monitor id (20 §3 join rule):
    `get_monitor_analysis` gives theme/confidence/why_it_works/tactics, `get_top_videos` +
    `get_top_slideshows` give media/hooks/panel texts/engagement for that same monitor, and the
    global `get_trends` digest only enriches `cross_monitor_context` — it creates no items.

    Post-pivot (v2.0.0) this is a TOPIC item: one topic per theme per monitor, carrying its own
    view-ranked `posts` (FR-293). The name is kept to bound the blast radius, and the media-side
    fields below stay until the W3.5 excision.
    """

    history_key: str  # dedupe + trend_history key: agent id, else normalized name slug
    monitor_id: str
    name: str
    # --- topic-item identity (v2.0.0, FR-293) ---
    # `topic_key` is the stable slug of the theme name and the second half of the post-pivot
    # `history_key` (`"<monitor_id>::<topic_key>"`, §1.6): one monitor now yields several topics,
    # so the monitor id alone can no longer key the repeat-prevention window.
    topic_key: str = ""
    # The topic's own winning posts, view-ranked. This list is the ONLY source of quotable text
    # post-pivot (FR-99/100) and the provenance the history record, the FR-297b roster and the
    # gallery receipt all read; the flat `hook_texts`/`panel_texts` lists further down
    # remain as deduped monitor-level views the prompt engine and previews read.
    posts: list[SourcePost] = field(default_factory=list)
    source: str = "virlo"  # adapter id (20 FR-121)
    strength: float = 0.0  # 0–1, computed by the adapter — the one cross-source contract (FR-5)
    strength_components: dict[str, float] = field(default_factory=dict)  # logged verbatim (FR-5)
    is_slideshow: bool = False  # drives format affinity (FR-90): the topic's view-ranked posts
    #   are majority-slideshow (§1.6 re-derivation — every post-pivot item is text-only by design)
    confidence: float | None = None
    why_it_works: str = ""
    tactics: list[str] = field(default_factory=list)
    hook_texts: list[str] = field(default_factory=list)  # few-shot exemplars for FR-100
    text_overlay_contents: list[str] = field(default_factory=list)
    panel_texts: list[str] = field(default_factory=list)  # per-slide word-count rhythm (FR-13)
    video_descriptions: list[str] = field(default_factory=list)  # feeds FR-96 content sentence
    # Virlo's own `intelligence` labels for the winning posts, deduped and view-ranked like the
    # exemplar lists above. FR-100 currently asks the copywriter to DERIVE a hook pattern in prose
    # that Virlo has already classified (`story_tease`, `question`, measured live), so these
    # replace guesswork with the source's own vocabulary. Absent until a row's
    # `intelligence_status == "ready"`, and the sorted fetch is what makes them common: coverage
    # roughly doubles when the winners lead (17/50 -> 34/50 on videos), because Virlo enriches
    # its best rows first.
    hook_types: list[str] = field(default_factory=list)
    visual_hook_types: list[str] = field(default_factory=list)
    emotional_tones: list[str] = field(default_factory=list)
    # The winning posts' REAL hashtags. The wrapper has always extracted these and nothing read
    # them, while `copywrite._hashtags()` invented tags from the trend-name slug on the FR-99
    # fallback path. Reference material for the copy call only — the model still chooses.
    hashtags: list[str] = field(default_factory=list)
    virlo_url: str | None = None
    total_views: int = 0
    median_views: int = 0
    newest_published_at: datetime | None = None  # velocity/momentum input (FR-5)
    engagement: dict[str, int] = field(default_factory=dict)  # likes/shares/comments/bookmarks
    cross_monitor_context: str = ""  # digest timing analysis + connecting threads (20 §3)


@dataclass(slots=True)
class PlanEntry:
    """One planned creative — the unit of accounting (FR-4) and of trimming. Trimming removes
    entries from the END in reverse plan order (FR-106), so expansion emits brief entries FIRST;
    `atomic_group` makes that one rule sufficient — entries sharing a group trim together and
    never split (a carousel and its slides are one unit, D31).
    """

    order: int  # 0-based plan position; trim order is descending
    asset_id: str  # stable id and asset folder name incl. ordinal (40 FR-73)
    creative_format: CreativeFormat
    platform: Platform
    language: str
    aspect_ratio: str  # from platform+format (FR-21); an API param, never prompt text
    atomic_group: str = ""  # trim unit; defaults to the entry's own id when it stands alone
    slide_count: int | None = None  # carousels; config ceiling = estimate basis (FR-95)
    brief_name: str | None = None  # campaign brief (FR-143)
    brief_influence: InfluenceMode | None = None  # per-entry mode override (D26)
    trend_key: str | None = None  # assigned trend's history_key; None for override briefs (FR-144)
    # §1.6's rotation index: this creative's 0-based position among the creatives sharing its
    # topic, set by `plan.assign` from the `use_index` it already counts. Every member of an
    # atomic group shares one value; 0 for override briefs, which quote nothing at all.
    #
    # **Legacy-only after D46 (v2.1.0, §0.10 + W3's F3 excision).** Its two rotation consumers
    # are gone — the `posts[i % len(posts)]` post pick (replaced by `source_post_id` below: the
    # plan binds a specific fresh post at ASSIGN and `copywrite` quotes THAT one) and the style
    # reference window (`styles.pick_reference_window` died with the picture channel). What
    # remains reads it only as a FALLBACK for unbound entries: the degrade-path modulo in
    # `copywrite` and the post-roster `-> NN` mapping in `runner`.
    trend_reuse_index: int = 0
    # FR-304/FR-307 (v2.1.0) — the post this creative quotes, bound at ASSIGN by `plan.assign`
    # from the topic's FRESH posts (never a post `trend_history` records as used). It is the whole
    # no-repeat guarantee at pick time: a stable post id, chosen once, carried through copy
    # (`copywrite._offer_for` builds the candidate table from THIS post and refuses a burnt one),
    # provenance (`meta.yaml.copy_source_post_id`) and history. `None` is the legacy/unbound shape
    # — override briefs, which quote nothing, and any entry a caller built before ASSIGN ran.
    # A carousel additionally binds a SLIDESHOW post with ≥2 usable panel slots (§0.14a), because
    # FR-304 renders our slide *i* from that post's panel *i*.
    source_post_id: str | None = None
    # --- style + branding assignment (v2.0.0, FR-290/291/292) ---
    # Written by `styles.assign_styles` / `styles.assign_branding` right after `plan.assign`, both
    # pure functions of `order` over the registry: the style this creative renders in, and whether
    # it carries the wordmark. They live on the entry (not in a side table) because they are
    # persisted to meta.yaml and because trimming must never re-assign a surviving creative.
    style_key: str = ""
    branded: bool = False
    # --- FR-334 match provenance (v2.4.0, D56) — WHY this creative wears `style_key` ---
    # Written at ASSIGN by the matched-mode overlay (`style_match.match`) after `assign_styles` has
    # already laid down the FR-291 rotation baseline. On an `assignment: rotation` run the three
    # matcher-authored fields stay empty, but `style_origin` is still stamped `"rotation"` — see its
    # own note below. A blank origin means ASSIGN has not run yet, never that rotation chose.
    # They live HERE, on the entry, for the same reason `style_key` and `branded` do: `PlanEntry` is
    # what `generate/__init__.py:_record()` can see when it builds the `AssetRecord`, so a side table
    # keyed by asset_id would have to be threaded through the whole render stage to reach meta.yaml.
    # Trimming (FR-106) removes entries whole, so a surviving creative never loses its provenance and
    # never acquires somebody else's.
    #
    #: `high` | `medium` | `low` — the matcher's own confidence that this style suits this source.
    #: `medium` ACCEPTS the pick (a decent fit is a fit); `low` REJECTS it and the entry keeps its
    #: rotation baseline. Empty whenever no matched answer applies: rotation mode, a whole-call
    #: failure, an entry the answer had no row for, and every override brief (never styled at all).
    style_fit: str = ""
    #: The matcher's short prose for the fit — one operator-facing sentence, printed on the ASSIGN
    #: receipt and the gallery card. Never executable: it explains a decision already made and no
    #: render prompt, budget or drop path ever reads it.
    style_reason: str = ""
    #: WHICH algorithm produced `style_key`, and the field a reader should check FIRST: `"matched"`
    #: (the matcher picked it and the fit was accepted), `"rotation"` (the FR-291 baseline stood —
    #: either the run is in rotation mode, or the matcher's answer for this entry was low/invalid/
    #: missing), `"rotation_fallback"` (the whole matcher call failed, so every entry is on baseline
    #: and the asset also carries `STYLE_MATCH_DEGRADED`). `""` before ASSIGN has run. The
    #: rotation/rotation_fallback split is what tells a per-entry rejection apart from a run-wide
    #: outage, which the pick alone cannot: both leave the same `style_key` behind.
    style_origin: str = ""
    #: The archetype the matcher WANTED and the registry did not offer, set only alongside a `low`
    #: fit and PRESERVED through the fallback to baseline. This is the gap report (D56 decision 3):
    #: the engine never synthesizes a style at runtime — that would break FR-295's registry
    #: authority and FR-189's sole-consistency mechanism — so the miss is written down and the
    #: operator authors the missing style deliberately. Free text from the model; never a key.
    style_wanted: str = ""
    # The topic this entry quotes (§1.6). Sits beside `trend_key`, which stays the history key:
    # one monitor yields many topics, so the history key alone no longer names the material.
    topic_key: str = ""
    status: PlanEntryStatus = PlanEntryStatus.PENDING
    skip_reason: str | None = None  # one line, machine-readable cause (FR-74)
    estimated_cost_usd: float = 0.0  # logged with every trim decision (FR-106)


@dataclass(slots=True)
class LayoutZone:
    """One ordered frame region of FR-92's `layout_zones`."""

    position: str  # e.g. "upper third", "left gutter"
    content: str  # headline, subline, focal subject, negative space, badge
    text_treatment: str  # case, weight, relative size, outline/shadow
    # §1.3/FR-292: `role: "brand_slot"` marks the signature zone. Emitted into `{{layout_zones}}`
    # only when the entry is branded — an unbranded creative gets the zone omitted plus one line
    # saying the lower margin is empty, because a described-but-empty brand slot is the single
    # biggest hallucination site the render models have (M11). Last field and defaulted, so every
    # positional `LayoutZone(position, content, treatment)` construction still holds.
    role: str = ""


@dataclass(slots=True)
class ListMode:
    """A style's LIST TREATMENT — the reflow trigger and the layout it reflows into (FR-304b).

    A REFLOW TRIGGER, never a ceiling. This is the whole point and the easiest thing to get wrong:
    a mapped panel that trips either threshold is not too long, it is a LIST, and it is SET in
    `layout` — rendered WHOLE at any length. No value here can drop, shorten, or refuse text, which
    is why `overflow` offers only two ways of laying more rows out and no way of losing one.

    Consumed in exactly ONE render slot: `{{list_treatment}}` on `carousel_slide.md`, built by
    `prompts_engine._list_treatment` and fired per slide when that slide's panel trips a threshold
    (Session 5.5/F1-A — it used to be a gated append onto `{{layout_zones}}`, which the slide role
    does not name, so it reached every render role except the only one that maps panels). The slot
    is in no truncation set, so the rule cannot be cut off a long slide. The gauntlet reads the
    same sentence deck-wide through `prompts_engine.list_mode_text` (`DeckContract.list_mode`), so
    the critic judges list layout by the words the renderer was given. It never enters
    `max_onimage_chars` or
    `_budget_line` (B6), and it is never consulted by `copywrite._panel_verdict` (D50) — no drop
    path gains a style input. Absent on a style is legal and means "this style has no list
    treatment"; present but malformed is an FR-295 pre-flight exit 2, like every other registry
    defect, because a half-parsed layout rule silently changes what a paid deck looks like.
    """

    #: A panel longer than this many characters is a list panel. `0` = NEVER reflow on length —
    #: deliberately the INVERTED sense of `max_onimage_chars`' "0 = no ceiling", because this is a
    #: trigger and that is a ceiling; the styles.yaml authoring block states it out loud.
    reflow_over_chars: int = 0
    #: A panel with more than this many lines is a list panel, whatever its length.
    max_rows: int = 0
    #: Prose the render prompt can execute: how rows are set, what may never separate, and how an
    #: over-long row behaves. Free text, because it is layout direction and never becomes words.
    layout: str = ""
    #: `reflow` | `two_column` — the two ways more rows may be laid out. Neither drops text.
    overflow: str = "reflow"


@dataclass(slots=True)
class MetaStyle:
    """One meta-style registry entry (§1.3) — the post-pivot visual authority.

    Replaces the per-trend vision analysis as the source of a creative's look: styles are authored
    once in `prompts/styles.yaml` (FR-290, loaded through the FR-174 `prompts_dir` seam) and
    ASSIGNED to entries by a deterministic order-indexed rotation (FR-291), instead of being
    re-derived by an LLM from whatever pictures a trend happened to carry. That is why there is no
    built-in fallback tier — an unusable registry is a pre-flight exit 2 (FR-295), not a degrade.

    `render_prompt` is the executable instruction (an either/or left unresolved here reaches the image
    model as a choice it will make differently on every slide, so M9 forbids it); the five DNA
    fields feed `style_dna` byte-identically across a deck. D46/F3 removed `reference_images`
    from the schema (FR-290 as amended): a style is words, its text alone carries the look, and
    `exclusions` are self-contained rules rather than strings read off attached pictures.
    """

    key: str
    render_prompt: str = ""  # <=120 words, executable, no unresolved variants (M9)
    subject_mode: str = "scene_open"  # "scene_fixed" | "scene_open" — is the subject the style's?
    layout_zones: list[LayoutZone] = field(default_factory=list)
    format_affinity: list[str] = field(default_factory=list)  # ⊆ {image, carousel, reel}, non-empty
    brand_affinity: list[str] = field(default_factory=list)  # [] = brand-neutral
    # "This style IS a brand": under its matching brand the branding block collapses to nothing
    # extra, the wordmark alone remains. Data-driven on purpose — an override registry with its own
    # keys must not silently lose the rule, which key-matching a name would do (B3).
    brand_slot: bool = False
    text_density: str = "minimal"  # minimal | moderate | high
    max_onimage_chars: dict[str, int] = field(default_factory=dict)  # headline/subline/slide
    motion_profile: str = "photographic"  # photographic | graphic (F24) — reel motion grammar
    palette: list[str] = field(default_factory=list)  # --- the five DNA fields (FR-189) ---
    typography: str = ""
    text_placement: str = ""
    image_treatment: str = ""
    visual_pacing: str = ""
    # Free prose under `carousel_cover` / `carousel_slide` (M9's either/or-resolution home), plus the
    # one marker key `carousel_role` with value "cover_only" or "slides_only": a slides-only style
    # can never anchor a deck, and under anchor-chaining that means it never takes a carousel entry
    # at all. `styles.fmt_affine` owns that reading — no caller re-implements it.
    per_format_guidance: dict[str, str] = field(default_factory=dict)
    exclusions: list[str] = field(default_factory=list)  # self-contained rules, file-free (D46/F3)
    #: FR-304b (v2.2.0): this style's list/table treatment, or `None` when it has none. See
    #: `ListMode` — a reflow trigger, never a ceiling; `styles.py` parses and validates it.
    list_mode: ListMode | None = None
    #: FR-290/FR-334 (v2.4.0, D56) — 1-2 authored sentences naming WHAT SOURCE MATERIAL this style
    #: suits: the content archetypes and source-post patterns it was drawn for (a dense listicle
    #: deck, a lifestyle POV photo set, a terminal/code walkthrough), written plainly.
    #:
    #: Read by the FR-334 matcher ALONE — it is how a candidate pool describes itself to the model
    #: that is choosing between styles. It is NOT part of the style's visual DNA and never reaches a
    #: render prompt, a budget, the gauntlet or a copy call: it says which sources deserve this look,
    #: not what the look is, and a render model handed it would try to draw the description of its
    #: own audience. Missing is legal (FR-290 as amended) — `styles.py` raises an ADVISORY warning
    #: and derives a stand-in from the first sentence of `render_prompt`, so an old registry and a
    #: hand-written override both keep loading; it is never an FR-295 pre-flight error.
    match_profile: str = ""


@dataclass(slots=True)
class CopySelection:
    """The copy call's per-creative answer under the §1.7 verbatim contract: references into the
    engine-numbered candidate list where the text becomes pixels or caption, free text only where
    nothing does. Feeds `json_schema_for(CopySelection, exclude={"asset_id"})`.

    The split from `CopySet` is the whole point of FR-99/100: the model CHOOSES (a label), the
    engine RESOLVES (the bytes). A model that answers with prose can drift, translate or invent;
    a model that answers with `P1.hook.2` cannot, and the resolution step can never fail the
    verbatim check because it copies from the source it is checked against. Ref-label grammar
    (FR-302, v2.1.0): `P<n>.<kind>[.<i>]` — `n` = 1-based post ordinal in the topic's view-ranked
    `posts`, `kind` ∈ {panel, overlay, hook, caption}, `i` = 1-based index into that post's list
    field (`caption` is a scalar and carries none). E.g. `P1.hook.2`, `P3.panel.1`. A `panel`
    index is a SOURCE SLIDE POSITION and is position-preserving. `description` is NOT a kind:
    Virlo's AI summary is fenced context only and is never offered, quoted or rendered (FR-303).

    `slide_refs` is answered only by a carousel that bound no source post. A carousel bound to a
    slideshow post has its slides mapped deterministically by the engine (source panel i → slide i,
    FR-304), so the model chooses that deck's cover headline, caption and hashtags and leaves
    `slide_refs` empty; anything it returns there is ignored and logged.
    """

    asset_id: str
    headline_ref: str = ""  # ref label, or "" = nothing fits the budget (NO_ONIMAGE_TEXT path)
    subline_ref: str = ""
    overlay_ref: str = ""  # reel seed-frame hook
    slide_refs: list[str] = field(default_factory=list)  # carousel, one label per slide
    caption_ref: str = ""
    through_line: str = ""  # free text — never pixels
    narrative_arc: str = ""  # free text — carousel arc
    motion_beat: str = ""  # free text — ONE named physical action, reel Stage 2 (F24)


@dataclass(slots=True)
class CopyCompressed:
    """The COMPRESS call's per-creative answer (D54/FR-331) — text, not references.

    The third answer shape beside `CopySelection` (labels) and `CopySet` (free text), and the one
    that needs the most explaining, because it is the shape where a model writes strings that
    become pixels on a creative bound to somebody else's post. What makes that safe is not this
    dataclass — it is the input it answers: `copywrite._compress_block` hands the model the bound
    post's OWN admitted panel strings and asks for each one back shorter, in the same language,
    with its facts intact. The model is compressing a specific string, not composing from a topic.

    `slide_texts` is POSITION-INDEXED and the position is the contract: `slide_texts[i - 1]` is the
    compression of SOURCE PANEL *i*, and an empty string means "that source panel had nothing to
    compress" (FR-304's alignment — the row is what aligns our deck with theirs, so a list that
    skipped an empty position would re-map every slide after it). The engine pads a short list,
    truncates a long one, discards a line written for a position the source left empty, and never
    consumes the list as a queue.

    `headline`, `caption` and `hashtags` are here for the same reason `CopySelection` carries their
    ref fields: a bound carousel's slides are the engine's to map, but that deck's COVER headline,
    its caption and its hashtags were always the model's to choose (FR-304). Compress authors the
    same three instead of selecting them — the caption compressed AND humanized, its comment/follow
    mechanics removed (the funnel `copywrite._strip_cta` fights sentence by sentence on the
    verbatim path).

    `through_line` and `narrative_arc` are free text on every contract, because neither becomes
    pixels. `motion_beat` is absent: compress mode is carousels only, and a reel has no panels.
    """

    asset_id: str
    headline: str = ""  # the deck's cover headline — trimmed to the style's headline budget
    caption: str = ""  # compressed AND humanized; engine falls back if it carries a social mark
    hashtags: list[str] = field(default_factory=list)  # blocklist-checked, whole-token drops
    slide_texts: list[str] = field(default_factory=list)  # slide i = compression of source panel i
    through_line: str = ""  # free text — never pixels
    narrative_arc: str = ""  # free text — carousel arc


@dataclass(slots=True)
class CopyTranslated:
    """The TRANSLATE call's per-creative answer (D63/FR-343) — `CopyCompressed` plus the language.

    The fourth answer shape and the copy role's third contract. It has `CopyCompressed`'s fields
    on purpose — the same cover headline, caption, hashtags, position-indexed `slide_texts` and two
    free-text notes — because the call is shaped the same way (`copywrite._translate_block` hands
    the model the bound post's OWN admitted panels numbered by source position) and the engine
    resolves it the same way (by INDEX, padded or truncated to the plan's deck length, a line for a
    dropped position discarded). What differs is the instruction behind the shape, and it is the
    opposite of compress on the one axis that matters: `slide_texts[i - 1]` is a TRANSLATION of
    source panel *i* into the platform's configured language that may NOT be shortened — no
    character ceiling is ever stated to this call, and a translated line is allowed to be longer
    than its source. `headline` alone keeps a budget (it is ours, FR-101); `caption` is translated
    AND humanised on the compress caption's terms.

    `source_language` is the one new field: the model's reading of the language the printed
    panels are written in, as a two-letter ISO 639-1 code. It is not a translation input — the
    engine already decided the deck was foreign before it paid for the call — it is the
    already-target BACKSTOP's evidence: when it names the TARGET language and a returned line is
    not byte-identical to its source panel, the engine ships the source bytes and warns, because
    the model has just admitted it rewrote a panel that needed no translation.
    """

    asset_id: str
    headline: str = ""  # the deck's cover headline in the target language — headline budget applies
    caption: str = ""  # translated AND humanised; engine falls back if it carries a social mark
    hashtags: list[str] = field(default_factory=list)  # blocklist-checked, whole-token drops
    slide_texts: list[str] = field(default_factory=list)  # slide i = translation of source panel i
    through_line: str = ""  # free text — never pixels
    narrative_arc: str = ""  # free text — carousel arc
    source_language: str = ""  # ISO 639-1 code the model read off the panels (backstop evidence)


@dataclass(slots=True)
class CopySet:
    """Copy for ONE creative, produced by the per-(trend x language) call of FR-99. On-image
    text arrives already trimmed at the last word boundary under the FR-101 budget — mid-word
    cuts are forbidden, and any trim emits `text_trimmed`.
    """

    asset_id: str
    language: str
    trend_key: str | None = None  # None for override briefs (grouped by brief x language)
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    hook_line: str = ""
    headline: str = ""  # on-image text block (image / every carousel slide)
    subline: str = ""
    slide_texts: list[str] = field(default_factory=list)  # carousel, one coherent sequence (FR-13)
    narrative_arc: str = ""  # carousel: hook -> escalation -> payoff -> close
    overlay_text: str = ""  # reel: burned into the seed frame (FR-24)
    through_line: str = ""  # reel: one-line content through-line for the video prompt
    motion_beat: str = ""  # reel: ONE named physical action for Stage 2 (F24) — resolved from
    #   `CopySelection.motion_beat`; free text because it never becomes pixels (§1.7)


@dataclass(slots=True)
class AssetRecord:
    """Mirrors meta.yaml field for field (FR-73); written `pending` at folder creation and
    rewritten to terminal status by temp+rename (NFR-21)."""

    asset_id: str  # --- identity & sourcing ---
    source: str  # trend key, or "brief/<name>"
    source_name: str
    platform: Platform
    creative_format: CreativeFormat
    # --- provenance & degradations ---
    source_hook: str = ""  # the topic's original hook line, verbatim — gallery card (FR-76, v1.6.4)
    ref_source: str = ""  # "brief" | "" — what the references came FROM; "style" died with the
    #   D46/F3 picture-channel excision (a style is words, so it is never a reference source)
    # FR-73 (v2.0.0) — post-pivot identity: the assigned meta-style, the brand system and the
    # branding-rotation outcome, and the topic this creative came from (gallery + provenance
    # block read all four; T3.2's gallery re-base is their first consumer).
    style_key: str = ""  # registry key, or "brief_override" under an override brief (M14)
    brand: str = ""  # active branding.brand at render time — never mixed (D43)
    branded: bool = False  # FR-292 floor-predicate outcome for this entry
    # FR-73/FR-334/FR-337 (v2.4.0, D56) — the style-match receipt, mirroring the four `PlanEntry`
    # fields of the same names field for field: `_record()` copies them across untouched. They sit
    # beside `style_key` because they are what that key MEANS on this asset — which algorithm chose
    # it, how well it fits, why, and what the matcher wished the registry had instead. All four are
    # empty on an `assignment: rotation` run and on every override brief, which is the honest reading
    # of "no matched answer applies" rather than a manufactured one. The FR-309 gallery prints
    # `style: X · <origin>/<fit>` from the first two, `style_reason` under it, and a wanted-archetype
    # note on any card carrying one; `style_wanted` is additionally what the operator greps across a
    # week of runs to find the archetype worth authoring next. One wrinkle worth knowing before you
    # read a card: FR-337 fixes the BADGE vocabulary at `rotation`, so a `rotation_fallback` origin
    # prints as plain `rotation` there and the `style_match_degraded` tag beside it is what says the
    # matcher never spoke. The distinction is never lost — it is just carried by the tag rather than
    # spelled twice — and meta.yaml below always records the exact origin.
    style_fit: str = ""  # high | medium | low; "" when no matched answer applies
    style_reason: str = ""  # the matcher's short prose; never executable, never a render input
    style_origin: str = ""  # rotation | matched | rotation_fallback ("" before ASSIGN ran)
    style_wanted: str = ""  # the archetype the registry did not offer — the FR-334 gap report
    topic_key: str = ""  # stable slug of the topic name (FR-293)
    # FR-298 (v2.3) — the verbatim receipt: WHICH post this creative quoted, and WHICH string.
    # `copy_source_refs` maps CopySet slot -> ref label per the §1.7 grammar, e.g.
    # {"headline": "P1.hook.2", "caption": "P1.caption"}; slot names are the CopySet field the
    # ref resolved into (`headline`, `subline`, `overlay_text`, `slide_1`…`slide_N`, `caption`).
    # Empty for override briefs and degrade paths — there was nothing quoted.
    copy_source_post_id: str = ""
    copy_source_refs: dict[str, str] = field(default_factory=dict)
    # FR-73 (v2.3.0, D54) — WHICH copy contract produced this asset: `verbatim` (the default and
    # every non-carousel, every override brief, every degrade path including a compress call that
    # failed and fell back to the verbatim mapped deck) or `compress` (a bound panel-mapped deck of
    # a `run.carousel_copy_mode: compress` run, FR-331). Per ASSET rather than per run because the
    # mode reaches only the bound decks — an image in a compress-mode run shipped verbatim copy and
    # says so. Read by the FR-309 gallery, which labels a compressed deck's slide column
    # "compressed from N chars" off each `panel_map` row's `source_text_original` length, and by
    # the FR-297c provenance block, which prints the compress receipt instead of the quoted bytes.
    copy_mode: str = "verbatim"
    # FR-73/FR-346 (v2.7.0, D63) — the LANGUAGE receipt, orthogonal to `copy_mode` above (which
    # stays the LENGTH receipt): `source` on every asset whose slides are in the post's own
    # language — every `run.copy_language_mode: source` run, every image/reel/override brief, a
    # post already in the platform's language, an unknown language, and a translate call that
    # failed and fell back to the verbatim mapped deck — and `target` ONLY when a translation
    # actually shipped on the deck (`copywrite._translated`). A translated deck that compressed
    # nothing is therefore `copy_mode: verbatim, copy_language: target`, and the gallery labels the
    # two axes separately.
    copy_language: str = "source"
    # FR-73/FR-346 (v2.7.0, D63) — the language ladder's answer for the bound post (Virlo's
    # `language_detected`, else the vision pass's deck-level reading, else `""` = unknown), as a
    # two-letter ISO 639-1 code, recorded on every bound carousel where it is known in BOTH modes —
    # so `meta.yaml` can say what language a deck that was NOT translated is in. `""` on every
    # asset that binds no post.
    source_language: str = ""
    # FR-73 (v2.1.0) — the slideshow receipt, beside the refs it explains. `copy_source_post_id`
    # says WHICH post; these three say what that post WAS and how its deck maps onto ours, which is
    # what FR-309's three-part gallery card needs to lay the source strip beside our slides.
    #
    # `source_post` is nested provenance of the bound post — `{post_id, url, author, views,
    # published_at, caption}` with ISO strings, never `datetime` objects, because meta.yaml is a
    # plain YAML document a human reads and a Phase-2 publisher parses. `None` when nothing was
    # bound: an override-brief carousel (§0.14d), an image, a reel, a degrade path.
    #
    # `source_panel_count` is the SOURCE deck's own length (not ours) — the number the gallery
    # needs to say "their 7 slides, our 5" and the number `panels_truncated` is measured against.
    # 0 on every non-carousel and on override briefs.
    #
    # `panel_map` is one row per OUR slide, in slide order and position-preserving:
    # `{slide, source_position, source_text, source_text_original, drop_reason, creator_stripped,
    # chrome_counter_stripped, ref_label, truncation_suspect, compressed, visual_brief,
    # source_image}`. All but the last two are the copy stage's
    # (`copywrite.CopyProvenance.panel_map`), and those two are joined in by
    # `generate.__init__._record()` from the slide-intelligence result (FR-306/FR-308). A slide
    # whose source panel was empty, chrome-poisoned or over the 1500-char sanity ceiling keeps its
    # row with an empty `source_text`, the pre-gate text in `source_text_original` and the cause
    # in `drop_reason` — the row is the alignment, so dropping it would silently re-map slide 3's
    # words onto slide 2, which is exactly the defect FR-304 exists to prevent. Empty list for
    # override-brief carousels and for everything that is not a deck.
    #
    # `compressed` (v2.3.0, D54/FR-331) is a bool on EVERY row of both walks — true when
    # `source_text` is the copy model's compression of `source_text_original` rather than a quote
    # of it, false on every verbatim row. One row schema always: a reader that had to ask whether
    # the key exists before trusting `source_text` would be reading two schemas, and the gallery's
    # alignment loop is the last place that should have to branch.
    #
    # `identity_scrubbed` and `chrome_watermark_stripped` (v2.9.0, D65/FR-362) are the contract
    # guards' two row flags, written on EVERY row of every walk under the same one-row-schema rule,
    # false by default. The first says a line naming ANOTHER PARTY was taken off this row before it
    # became the render contract — a creator handle, a commit line (`… merged commit 859bdce into
    # dev`), a bare `owner/repo #125` reference; the second says the row WAS a brand mark or
    # watermark the source stamped on its own slide (`OPAL COLLECTION`, `EVOLVING AI`) and was
    # stripped into chrome exactly as a page counter is. They are separate flags for the same
    # reason `creator_stripped` and `chrome_counter_stripped` are: "we nearly named another
    # account" and "we nearly reprinted their furniture" are different findings on a gallery card,
    # and only the first is about anybody's identity. Both keep their bytes in
    # `source_text_original`, and a row whose remainder read as a beheaded fragment ships wordless
    # in its own position rather than as an orphan clause.
    source_post: dict | None = None
    source_panel_count: int = 0
    panel_map: list = field(default_factory=list)
    # FR-313 (v2.5.0, D59) — did the SOURCE deck number its slides, and how did we decide it did?
    # `{detected: bool, rule: str, pattern: str, sample: str}` on EVERY bound carousel, `None` on
    # images, reels and override briefs (they bind no source deck, so the question does not apply
    # and a `False` there would read as "their deck had no counter" about a deck that never
    # existed).
    #
    # `rule` names which of `slide_intel.detect_counter`'s four accept rules fired
    # (`denominator` | `positional` | `leading_offset` | `constant_offset`) — the last two are
    # weaker evidence, so a badge that came out wrong can be traced to a rule that guessed rather
    # than to the renderer. `pattern` is the source's own hand described structurally (padding,
    # separator with its exact spacing, prefix, whether a total was shown); `sample` is OUR slide
    # 1's badge, re-based onto OUR deck length — never the source's numbers, because a five-slide
    # deck cut from nine panels must never file "01 / 09". All three are `""` when nothing was
    # detected, so a reader branches on `detected` alone and never on emptiness.
    #
    # A PLAIN DICT for the same reason `gauntlet` above is one: `models` is the bottom of the
    # import graph and `sources.slide_intel` imports it, so a typed `CounterSpec` field here would
    # be a cycle.
    counter: dict | None = None
    degradations: list[DegradationTag] = field(default_factory=list)
    brief_name: str | None = None  # --- brief overrides (D26) ---
    brief_influence_mode: InfluenceMode | None = None
    # FR-351 (v2.6.0, D62) — the cover best-of-N receipt: `{candidates: [<asset-relative paths
    # under covers/>], chosen: <1-based candidate id>, reason: <the pick's short prose>,
    # degraded: <bool>}` on every chained carousel rendered with `run.cover_candidates > 1` and at
    # least one landed candidate; `None` everywhere else (a single-cover run, an unchained deck,
    # an image, a reel). `chosen` indexes `candidates` 1-based and names the candidate that became
    # `slide_01`; the gallery draws the strip from `candidates` and marks `chosen`. A PLAIN DICT
    # for the same reason `gauntlet` and `counter` are: `models` is the bottom of the import graph.
    cover_pick: dict | None = None
    model_ids: list[str] = field(default_factory=list)  # --- model & generation (FR-270) ---
    render_not_reproducible: bool = True  # Kie exposes no seeds (FR-109/OQ-4): no seed field
    aspect_ratio_requested: str = ""  # FR-21
    native_size_rendered: str = ""  # what came back; shipped as-is, no crop/pad (FR-98)
    estimated_cost_usd: float = 0.0  # --- cost & timing ---
    actual_cost_usd: float = 0.0
    estimated_tokens: int = 0
    actual_tokens: int = 0
    job_submission_timestamp: str | None = None  # ISO 8601
    job_completion_timestamp: str | None = None  # ISO 8601
    kie_job_ids: list[str] = field(default_factory=list)
    vision_check_result: VisionCheckResult = VisionCheckResult.NOT_CHECKED  # --- quality/skip ---
    #: FR-328 (v2.2.0, D49) — `meta.yaml.gauntlet`: the post-render gate's own receipt, written on
    #: EVERY terminal path the gauntlet touched (pass, blocked, degraded, budget/deadline stop,
    #: skipped) and `None` when the gate never ran. Shape:
    #: `{result, degraded_gate, rounds: [{round, unavailable, critics: {name: n_fails},
    #: failed_frames, rerendered}], rerenders, rerender_cost_usd, critic_cost_usd}`.
    #:
    #: A PLAIN DICT on purpose, and this is a hard rule rather than a convenience: `models` is the
    #: bottom of the import graph and `gauntlet` imports it, so a typed `GauntletReport` field here
    #: would be a cycle. The full per-frame per-critic detail does not live here at all — it goes to
    #: `GAUNTLET_REPORT.yaml`, which is the operator-readable report; this field is the summary a
    #: gallery, a summary row or a Phase-2 publisher can read without parsing verdict prose.
    gauntlet: dict | None = None
    status: AssetStatus = AssetStatus.PENDING
    skip_reason: str | None = None  # also appears as a DegradationTag
    slide_count: int | None = None  # --- format-specific: carousel slides delivered ---
    # FR-321 (v2.1.3) — the deck length ORDERED at ASSIGN (FR-95), recorded beside the delivered
    # count so partial delivery is machine-readable without re-deriving it from
    # `missing_slide_numbers`. `slide_count < slides_ordered` IS the partial-deck predicate, and it
    # is what the spend table's `7/8` cell and the gallery header's partial count both read.
    # `None` on every non-carousel and on any deck packaged before this field existed — readers
    # treat a missing/None value as "no claim", never as zero.
    slides_ordered: int | None = None
    missing_slide_numbers: list[int] = field(default_factory=list)  # 1-indexed; marks `incomplete`
    reel_audio: bool | None = None
    reel_video_reference_url: str | None = None
    postiz_draft_id: str | None = None  # --- posting (Phase 2; inert in MVP, schema stays fixed) ---
    postiz_post_id: str | None = None
    postiz_state: str | None = None
    postiz_media_ids: list[str] = field(default_factory=list)
    event_id: str | None = None  # --- logging & audit: pointer into events.jsonl ---
    virlo_url: str | None = None


@dataclass(slots=True)
class ParsedResult:
    """Return of `llm.structured_call()`; usage feeds the FR-106c reconcile step."""

    parsed: Any  # object validated against the CALLER's json_schema — schema-agnostic
    raw_text: str  # exactly what came back, logged to events.jsonl
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0  # Luna bills these on top of output (20 §7, FR-107)
    cost_usd: float = 0.0
    retried: bool = False  # the single FR-41 content retry was spent
    tolerant_parsed: bool = False  # strict parse failed; FR-126 local parse rescued it
    truncated: bool = False  # finish/stop reason said token limit (FR-127)
    degraded: bool = False  # caller must fall back (copy_degraded, or fail open at the filter)
    # WHY this exists next to `raw_text`: on a truncated call `raw_text` is a slab of unfinished
    # JSON, so an operator warning built from it cannot tell "the model was cut off" apart from
    # "the model returned garbage". `reason` is the short, operator-facing cause and is set on
    # EVERY degrade path in llm.py; `raw_text` keeps carrying the body for events.jsonl.
    reason: str = ""


class StructuredCall(Protocol):
    """PINNED SIGNATURE — `llm.structured_call()` (FR-39–41, 125–129, 248).

        async def structured_call(role, messages, json_schema, images=None) -> ParsedResult

    Schema-agnostic by contract: `role` picks model/temperature/token limits from config and
    `json_schema` is whatever the CALLER needs — later schema needs go in callers, never here.
    Behind the seam: strict schema mode, tolerant parse before the one retry, truncation retry
    with a changed request, run-scoped 402. `images` are already-downloaded local bytes sent
    base64 (FR-40). The `max_inflight_llm_calls` semaphore lives in llm.py, NOT here.
    """

    async def __call__(
        self,
        role: str,
        messages: list[dict[str, Any]],
        json_schema: dict[str, Any],
        images: list[bytes] | None = None,
    ) -> ParsedResult: ...


class RenderPriority(IntEnum):
    """Tier for the render permit gate; higher value is served first.

    **2-tier priority permit gate spec (FR-25 permit-granularity rule).** A permit is acquired
    INSIDE submit-and-poll, per submitted job, released the moment that job is terminal. No task
    may hold a permit while awaiting a dependency — one coroutine per creative holding a permit
    across its anchor await deadlocks at `max_inflight_render_jobs` carousels. A plain FIFO
    `asyncio.Semaphore` is INSUFFICIENT: pre-committed wave-2 work (slides 2–N, Seedance clips,
    FR-106b) queued behind a burst of wave-1 acquisitions is starved, and half-built decks are
    exactly what FR-106b forbids. So the allocator hands every released permit to a waiting
    WAVE2 acquirer before ANY queued WAVE1 acquirer, FIFO within each tier; priority applies to
    the QUEUE, never preempting a held permit. Named starvation test = W4 barrier item.
    """

    WAVE1 = 1  # standalone images, carousel anchor slide 1, reel seed frames
    WAVE2 = 2  # carousel slides 2–N, Seedance clips — pre-committed, must not be starved


class RenderOutcomeKind(str, Enum):
    """FR-242's three outcomes. Success-with-unusable-result folds into FAIL with a sub-cause,
    never laundered into a success."""

    SUCCESS = "success"
    FAIL = "fail"
    STUCK = "stuck"  # no terminal state within the per-job timeout; never resubmitted (20 §8)


class RenderFailCause(str, Enum):
    """Sub-cause carried out of the seam so callers never re-derive it from provider JSON."""

    PROVIDER_FAIL = "provider_fail"  # state: fail, transient/unclassified
    MODERATION = "moderation"  # policy refusal — own class, drives FR-97's single retry
    CONTENT_AUDIT = "content_audit"  # content-security/copyright audit fail (RESULTS.md §C) —
    #   distinct remedy from MODERATION: silence the clip, don't strip references (W4 degrade path)
    EMPTY_RESULT_URLS = "empty_result_urls"  # FR-242
    RESULT_URL_UNREACHABLE = "result_url_unreachable"  # FR-242 (404, dead host, wrong content)
    TIMEOUT = "timeout"  # per-job timeout exceeded (pairs with STUCK)
    CREDITS_EXHAUSTED = "credits_exhausted"  # HTTP 402 — whole-run condition (FR-167)
    # D51 (v2.2.0): the run had less time left than this job's own timeout plus grace, so it was
    # never submitted. THE ONLY UNBILLED CAUSE IN THIS ENUM — every other one describes a job that
    # reached the provider and was therefore paid for. That is exactly why two predicates must
    # exclude it by name: a refusal that never cost anything must not burn FR-317's single
    # resubmit, and re-submitting into a deadline that has already expired only refuses again.
    # Applies to `discretionary` and `projected` work only — never `precommitted`, because
    # bookkeeping may never split a deck (FR-106b).
    NO_RUNWAY = "no_runway"


@dataclass(slots=True)
class RenderParams:
    """The engine's standard render inputs; the PROFILE renames them per provider (FR-272), so
    no caller ever speaks a provider field name."""

    prompt: str  # fully assembled; an unresolved placeholder never reaches here (FR-260)
    aspect_ratio: str  # API parameter, never prompt text (FR-94 clause 4)
    resolution: str | None = None  # 1K/2K/4K images, 480p/720p reels (NFR-13)
    duration_s: int | None = None  # reels 4–30, clamped at pre-flight (FR-103/164)
    generate_audio: bool | None = None  # reels, from `reel_audio` (FR-141/165)
    output_format: str | None = None  # e.g. "mp4"
    moderation_enabled: bool | None = None  # provider knob, forwarded uninterpreted (FR-166)


@dataclass(slots=True)
class RenderRefs:
    """Reference media as PUBLIC URLs only (base64 is an OpenRouter-vision convention, FR-40);
    local bytes arrive here only after the upload seam op (FR-200/244). The profile's declared
    limits cap these lists — excess is dropped and logged, never sent. Order matters: a chained
    artifact (carousel anchor, reel seed frame) is PRIMARY and leads `image_urls` (FR-95/24).
    """

    image_urls: list[str] = field(default_factory=list)
    video_urls: list[str] = field(default_factory=list)  # Seedance motion reference (FR-142)


@dataclass(slots=True)
class RenderOutcome:
    """One terminal render result, classified by the seam (FR-242/271)."""

    kind: RenderOutcomeKind
    task_id: str | None = None  # provider job id; the ledger's terminal field (FR-203)
    request_token: str | None = None  # client-generated, written BEFORE createTask (FR-203)
    result_urls: list[str] = field(default_factory=list)  # empty unless kind is SUCCESS
    fail_cause: RenderFailCause | None = None
    fail_message: str = ""  # provider reason carried through intact, safe to log
    cost_usd: float = 0.0  # tallied on submission — failures included (FR-106)
    submitted_at: str | None = None  # ISO 8601, for meta.yaml
    completed_at: str | None = None  # ISO 8601, for meta.yaml
    elapsed_s: float = 0.0  # measured on the MONOTONIC clock (FR-243), never wall-clock


class RenderRun(Protocol):
    """PINNED SIGNATURE — `render.run()` (20 §12 D34, plan §1 render/).

        async def run(profile, params, refs, priority) -> RenderOutcome

    ONE deep call: submit -> poll -> classify -> result URLs, permit acquired inside it (see
    RenderPriority). The four-op provider protocol, Kie's field names, five poll states and
    status codes stay BEHIND this seam. An unknown `profile` is a pre-flight refusal (exit 2,
    FR-272), never a runtime surprise; a timed-out job is a failed job, never resubmitted.
    """

    async def __call__(
        self,
        profile: str,
        params: RenderParams,
        refs: RenderRefs,
        priority: RenderPriority,
    ) -> RenderOutcome: ...


@dataclass(slots=True)
class Brief:
    """A campaign brief: a small named file, or a folder when it ships its own images (FR-172)."""

    name: str  # folder/file name, and the value `--brief <name>:<count>` takes
    description: str  # one line, shown wherever briefs are listed
    influence: InfluenceMode  # override = consumes no trend (FR-144); blend = trend wins visuals
    formats: list[CreativeFormat] = field(default_factory=list)
    copy_directives: dict[str, str] = field(default_factory=dict)  # message, cta, structure
    visual_directives: dict[str, str] = field(default_factory=dict)  # replace render_prompt on
    reference_image_paths: list[Path] = field(default_factory=list)  # uploaded per FR-200


class BriefLoader(Protocol):
    """PINNED SIGNATURE — `briefs.load()`, implemented in W5.

        def load(name: str, briefs_dir: Path) -> Brief

    Resolves from `briefs_dir` ONLY (no cross-folder collision rules). Missing or malformed
    raises naming the exact file — a pre-flight error before any billable call, dropping only
    that brief's creatives under `--yes` (FR-172/252).
    """

    def __call__(self, name: str, briefs_dir: Path) -> Brief: ...


#: FR-181 two-level template layout, level 1: the three GLOBAL role templates sit FLAT in
#: `prompts/`. They belong to the OpenRouter roles, not to any render profile, and exist once.
GLOBAL_TEMPLATES: tuple[str, ...] = (
    # The copywriter and the FR-294 topic filter, plus D46's slide-intelligence question (FR-306,
    # v2.1.0), which is global for the same reason they are: it belongs to the analysis role, not
    # to any render profile, and must read identically for every post it is asked about.
    # `vision_check_question.md` was the fourth and is DELETED (v2.2.0, D49): FR-105's single-shot
    # check is the gauntlet's work now, so the file, its built-in twin and its allowlist row went
    # with the `vision_check.check()` machinery rather than lingering as a role nothing calls.
    "copywriter_system.md", "topic_filter_system.md", "slide_intel_question.md",
    # v2.2.0 (D49, FR-322/FR-323): the gauntlet's four prompt artifacts. The three critics belong
    # to the `critic` role — a global role, exactly like the vision check they replace — and each
    # must read identically for every frame it judges. `gauntlet_fix.md` is the odd one: it
    # resolves NOTHING (its canned remedy sentences are selected in code and keyed by
    # `(code, zone)`), which is the same shape `vision_check_question.md` has always had.
    "critic_brief.md", "critic_system.md", "critic_craft.md", "gauntlet_fix.md",
    # v2.3.0 (D54, FR-331/FR-332): the carousel COMPRESS call. Global for the same reason
    # `copywriter_system.md` is — it belongs to the `copy` role rather than to any render profile,
    # and it must read identically for every deck it compresses. It is a SECOND template for one
    # role, which is new here and is the point: the two are different contracts (select a label
    # versus compress a string), the operator chooses between them per run, and giving the second
    # its own file is what lets either be hot-edited (FR-181) without disturbing the other.
    "copy_compress_system.md",
    # v2.7.0 (D63, FR-343/FR-344): the carousel TRANSLATE call — the THIRD template on the `copy`
    # role, beside the two above, and global for the same reason they are: it must read identically
    # for every deck it translates. It is its own file rather than a mode flag on the compress
    # template because the two contracts contradict each other on purpose — compress shortens to a
    # stated ceiling in the source language, translate changes the language and may NOT shorten (no
    # ceiling is ever stated to it) — and giving each its own file is what lets either be hot-edited
    # (FR-181) without the other's rules bleeding in.
    "copy_translate_system.md",
    # v2.4.0 (D56, FR-334/FR-335): the style matcher. Global on the same grounds as
    # `topic_filter_system.md`, which it is modelled on — it belongs to the `analysis` role rather
    # than to any render profile, and it must read identically for every entry it assigns, because
    # the whole point of one batched call is that every creative in the plan is judged by the same
    # question. It is the SECOND template on the analysis role beside `slide_intel_question.md`, the
    # same one-role-two-contracts shape `copy_compress_system.md` introduced for `copy`.
    "style_match_system.md",
    # v2.6.0 (D62, FR-351/FR-352): the cover best-of-N judge. Global on the same grounds as the
    # two screens above — it belongs to the `analysis` role rather than to any render profile, and
    # every deck's candidates must be judged by the same question or "best cover" means a different
    # thing per deck. It is the THIRD template on that role, beside `slide_intel_question.md` and
    # `style_match_system.md`, and the first one that is handed pixels: the candidate frames ride
    # as image attachments, so the words here are only the yardstick they are held against.
    "cover_pick_system.md",
)

#: The subset of `GLOBAL_TEMPLATES` that is DECLARED here but whose file and FR-183 built-in twin
#: have not been authored yet — an artifact of the v2.2.0 wave order, in which the name rows land
#: (T1.0) two waves ahead of the prompt bytes (T2.2) and their built-in twins (T2.4). It exists so
#: the registry can be honest about the full role set the moment the schema freezes, without the
#: parity checks reading a file that is not written yet.
#:
#: **This set must be EMPTY when the gauntlet ships.** Removing a name here is what puts that
#: prompt under `test_template_parity`'s byte/placeholder checks, so the last wave to author these
#: files empties this tuple in the same commit.
#:
#: EMPTIED at v2.2.0/T2.4, in the commit that added the four built-in twins: all four prompts now
#: ship bytes AND an FR-183 fallback, so every parity and placeholder check applies to them. The
#: constant itself is kept (rather than deleted) as the sequencing seam the next schema freeze will
#: use — it costs one empty frozenset and it is what the trip-wire in `test_template_parity` reads.
PENDING_TEMPLATES: frozenset[str] = frozenset()

#: FROZEN (spec §3): the complete vocabulary the three critic roles may resolve between them —
#: nothing outside this set, and every per-critic `_ALLOWLIST` row is a SUBSET of it. Declared here
#: rather than only in `prompts_engine` because the name rows and the placeholder sets are one
#: contract that four parallel tasks build against, and because it is what lets the reachability
#: check tell "not wired up yet" apart from "dead vocabulary" while `PENDING_TEMPLATES` is
#: non-empty. `gauntlet_fix.md` is deliberately absent from the consumers: it resolves NOTHING —
#: its canned remedy sentences are selected in code and keyed by `(code, zone)`, exactly as
#: `vision_check_question.md`'s carrier turn always was.
CRITIC_PLACEHOLDERS: frozenset[str] = frozenset({
    "expected_blocks", "required_marks", "forbidden_terms", "style_dna", "layout_zones",
    "list_mode", "sanctioned_illegible", "platform",
})

#: Level 2: per-profile render sets under `prompts/<profile>/` (FR-181/262). A new profile ships
#: its own complete set in its own subfolder; shipped profiles have built-in defaults (FR-183),
#: a new profile's set is validated at pre-flight instead (FR-263).
PROFILE_TEMPLATES: dict[str, tuple[str, ...]] = {
    "gpt-image-2": (
        # Post-W3.5 set: the merged `image_post.md` (F16) is the ONE image role — the two files
        # it merged left every surface with the excision.
        "image_post.md", "carousel_slide.md", "carousel_anchor_instruction.md",
        "reel_seed_frame.md",
    ),
    "seedance-2-5": ("reel_director.md",),
}

#: FR-182 placeholder vocabulary — plain `{{name}}` substitution: no expressions, conditionals
#: or loops. Assembly fills these from the style brief, the copy output and an allowlisted,
#: secret-free context object (FR-261); anything unresolved fails the creative BEFORE submission
#: (FR-260). Names are from 50 §2 (render scaffolds) and 50 §5 (the two LLM system templates),
#: plus the slots the pipeline's own FRs require: niche descriptor (FR-147), brief directives
#: (FR-144/145) and the deterministic direct-mode content sentence (FR-96).
PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "render_prompt", "layout_zones", "onimage_text", "exclusions", "style_dna",
        "slide_index", "seed_frame_ref", "audio_cue",  # render scaffolds
        "sibling_list", "source_hooks", "platform_conventions",
        "brand_context",  # copywriter_system.md — `source_hooks` is the §1.7 candidate table,
        #   OVERWRITTEN by copywrite after build_context returns (W2 addendum item 4)
        "trend_texts",
        "niche_descriptor", "brief_directives", "content_sentence",  # pipeline-required slots
        # W1 barrier review additions (2026-08-09):
        "text_budgets",  # in-force on-image text budgets line (FR-101/105/188) — config-sourced,
        #   re-computed on the −40% vision-check retry; templates never hardcode the numbers
        "through_line",  # CopySet.through_line → reel_director.md (FR-13/23); content_sentence
        #   stays reserved for FR-96's deterministic direct-mode/reference-free sentence
        "reference_roles",  # one engine-emitted line per attached reference: index · source kind ·
        #   contribution · exclusions (FR-191/91) — carries the RESULTS.md §B wordmark defense
        # A15 steering fix (2026-08-11):
        # D46 (v2.1.0) slideshow-fidelity slots — carousel_slide.md only (FR-304/FR-308):
        "visual_brief",  # the slide's English content directive from slide intelligence (FR-306):
        #   WHAT the source slide shows (chart, icon grid, numbered list), rendered in OUR style —
        #   never a style command, never competitor marks (§0.12). Empty when vision degraded.
        "slide_panel_source",  # the FR-304 position line — "source panel i of N" — so the model
        #   knows this slide mirrors one specific slide of the source deck, not a free layout.
        # v2.1.2 visual-fidelity round (D-A/D-D) — carousel_slide.md only, both empty by default:
        "tool_marks",  # D-A: the SANCTIONED marks line. Every mark named on it renders as the REAL
        #   logo in its true brand colours, exempt from the style's palette discipline and placed
        #   where the source panel put it (an icon beside its list row). It is the ONE narrow hole
        #   in the "draw a generic unlettered shape" rule, which still governs every competitor,
        #   creator and platform mark, and it never sanctions platform chrome, watermarks,
        #   usernames or engagement counters.
        "slide_counter",  # D-D: the deck's own position badge STRING ("3/7"), never derived from
        #   `slide_index` (which is orientation metadata the templates forbid drawing). Since D59
        #   the string reaches the model down THREE channels, and they have to agree: the locked
        #   `counter` entry inside `{{onimage_text}}`, which is the WORDS themselves; the
        #   `counter_slot` zone inside `{{layout_zones}}`, which on a carousel only the gauntlet's
        #   critic ever reads (`generate/contracts.py` builds it there; `carousel_slide.md` names
        #   no `{{layout_zones}}` slot at all); and `{{counter_rule}}` (FR-338, at the bottom of
        #   this set), which is the SLIDE RENDERER's own channel for where the badge goes — or
        #   for the fact that this deck carries none. The shipped template still names no slot for this
        #   raw value; the name lives here because `build_context` carries it (FR-261 condition 2)
        #   and an override template may name it.
        # Session 5.5/F1-A — carousel slides ONLY, and empty on every frame that is not a list:
        "list_treatment",  # FR-304b's list layout as one executable sentence — the lead label, the
        #   style author's own `layout` prose and the `overflow` rule — gated on THIS frame's mapped
        #   panel (`prompts_engine._list_treatment`). It had no name here until F1-A because it was
        #   APPENDED onto the assembled `{{layout_zones}}` value, and `carousel_slide.md` names no
        #   `{{layout_zones}}` slot: the one role that maps source panels was the one role never
        #   told to set a list as a list, while the gauntlet's `system` critic judged its slides
        #   against the rule. A missing row here is not a loud failure — a template naming an
        #   out-of-vocabulary slot is refused by `prompts_engine._unresolvable_names`, and the role
        #   falls back to its `_BUILT_INS` twin with one WARN line, i.e. the whole deck renders from
        #   the OLD template bytes. Deliberately absent from `_TRUNCATION_ORDER`: uncuttable, like
        #   the TEXT block whose setting it describes.
        "niche_visual_world",  # `niche.visual_world` ALONE — the operator's standing art direction
        #   in the only shape a render prompt may carry it. Deliberately NOT `niche_descriptor`,
        #   which also carries `audience`: copy-side context must not leak into a render prompt,
        #   and the per-role allowlist exists to enforce exactly that (FR-261/109). Allowlisted for
        #   the four gpt-image-2 roles, so `direct` mode finally sees the art direction too.
        # Topic-first pivot (v2.0.0, contracts item 2 — the names the pivot added, after the six
        # pre-pivot orphans left with the W3.5 excision). This line used to promise a "final
        # 25-name vocabulary" and it was neither final nor 25 for long: every round since has added
        # slots, and the set stands at 43 names — 41 of them before D62 added the cover judge's two
        # at the bottom. Read the number off `len(models.PLACEHOLDERS)`, never off a comment:
        "branding_block",  # FR-292's second channel: accent colours, font letterforms, placement
        #   hint and the profile's `never:` lines, pre-rendered by prompts_engine._branding_block();
        #   empty when unbranded. The wordmark NEVER travels here — it is a TEXT-block entry (B1).
        "topic_items",  # FR-294: the engine-numbered topic blocks for the filter call — ordinals
        #   1..N assigned by _topic_items(), never raw topic_key (a crafted name must not spoof
        #   another topic's verdict). Allowlisted for topic_filter_system.md ALONE.
        "competitor_list",  # FR-294: branding.competitors for the same call, same single role.
        "audience_profile",  # v2.2.0: `NicheConfig.as_text()` for the SCREEN, and the only place
        #   the niche is read outside the copy path. topic_filter_system.md ALONE allowlists it,
        #   on the `competitor_list` precedent: the screen cannot judge `audience_fit` or a topic's
        #   language without knowing who this run writes for, and no render role may ever see it —
        #   that is what `niche_visual_world` exists for. `topic_filter._system_prompt` writes the
        #   value onto the built context after `build_context` returns, exactly as `copywrite` does
        #   with `source_hooks`, so the name lives in the vocabulary without a builder of its own.
        "motion_profile",  # F24: the registry's photographic|graphic switch — selects the reel
        #   director's LOOK/CAMERA paragraph. reel_director.md only.
        "motion_beat",  # F24: CopySelection.motion_beat — ONE named physical action for the
        #   reel's Stage 2. reel_director.md only; free text that never becomes pixels.
        # --- v2.2.0 (D49, FR-322): the gauntlet critics' vocabulary. These are CONTRACT slots, not
        # render slots: they carry what a frame was ORDERED to contain to a model that is looking at
        # what came back, and they are allowlisted for the three `critic_*.md` roles alone. Two
        # names already in this set — `style_dna` and `layout_zones` — are reused rather than
        # duplicated, which is also the honest caveat FR-322 states out loud: those two blocks are
        # render-prompt text, so the "fresh context" a critic gets is fresh of everything EXCEPT the
        # only referent a style judgement could possibly have. `gauntlet_fix.md` names none of
        # these; it resolves nothing at all.
        "expected_blocks",  # the per-frame enumerated line blocks — `L1:`/`L2:`… plus `counter:`,
        #   `signature:` and (D65/FR-366) `marks:` rows, `(none)` for a frame that is wordless BY
        #   MANDATE. This is the referent for every "missing" and every "invented" verdict, and the
        #   one thing that can tell a wordless frame apart from a frame whose words failed to
        #   render: the picture cannot, the contract can.
        "required_marks",  # FR-330's REQUIRED side: the FR-315 sanctioned tool marks this deck
        #   ordered as real logos AND actually cropped patches for (D65/FR-366). Deck-wide, and it
        #   is the EXEMPTION list — which frame owes which mark is the `marks:` row above, because
        #   a union read as a demand accuses frames whose source panels carried no logo.
        "forbidden_terms",  # FR-330's FORBIDDEN side, and the expensive one: creator identity
        #   forms, competitor names, unsanctioned brand marks, §0.12 flag names. Present in a
        #   frame = `forbidden_mark`/`identity_leak`, and the critics are told to fail when unsure.
        "list_mode",  # the style's list treatment as flattened prose ("" when it has none), so a
        #   list frame is judged against the layout it was actually ordered into (FR-329).
        "sanctioned_illegible",  # derived from the style: what this style DELIBERATELY renders
        #   unreadable (greeked bars, texture lettering). Without it a critic reads a style's own
        #   signature as a `garbled` defect and blocks a deck for looking correct.
        "platform",  # the target platform, for the craft critic's publish-bar phrasing.
        # --- v2.3.0 (D54, FR-331/FR-332): the compress call's one slot. ---
        "compress_panels",  # the bound deck's OWN admitted panel strings, numbered by SOURCE
        #   position with the per-slide budget and the language-mirror line, written onto the built
        #   context by `copywrite._call_compress` AFTER `build_context` returns — the same
        #   after-the-fact shape `source_hooks` and `audience_profile` already use, and for the same
        #   reason: the module that resolves the answer owns the block the question was asked with,
        #   so there is one implementation and nothing to drift. `copy_compress_system.md` ALONE
        #   allowlists it, which is the enforcement that matters: no render role can ever be handed
        #   a block of source panel text to "work from", and no other copy role can either.
        #   The name has to live HERE and not only in `prompts_engine._ALLOWLIST`, because
        #   `_unresolvable_names()` checks this vocabulary FIRST — a template naming a slot absent
        #   from it is refused as unusable, the role falls back silently to its FR-183 built-in
        #   twin, and every operator hot-edit of the file (FR-181) stops reaching a model.
        # --- v2.7.0 (D63, FR-343/FR-344): the translate call's one slot. ---
        "translate_panels",  # the bound deck's OWN admitted panel strings, numbered by SOURCE
        #   position with NO per-line budget and the from→to language line, written onto the built
        #   context by `copywrite._call_translate` AFTER `build_context` returns — the same
        #   after-the-fact shape `compress_panels` uses, by the same module, for the same reason
        #   (the module that resolves the answer owns the block the question was asked with).
        #   `copy_translate_system.md` ALONE allowlists it: a render role handed it would letter a
        #   wall of foreign panel prose, the compress role would be handed a licence to change the
        #   language its own rule 2 forbids it to touch, and the selection role a block to retype.
        #   Declared HERE for the `_unresolvable_names()` reason recorded above `compress_panels`.
        # --- v2.4.0 (D56, FR-334/FR-335): the style matcher's two slots. ---
        # Both are allowlisted for `style_match_system.md` ALONE, and that exclusivity is the
        # enforcement that matters: a render role handed `{{style_candidates}}` would receive a
        # catalogue of the styles it was NOT assigned and blend them, which is precisely the
        # cross-style contamination FR-189 exists to prevent. The same rule that keeps
        # `compress_panels` off every render prompt keeps these two there.
        "style_candidates",  # the entry-eligible candidate pool as fenced DATA: one block per
        #   style key with its `match_profile` (FR-290's "what sources this style suits"), built
        #   from `styles.usable_styles` x `styles.fmt_affine` — the imported predicates, never
        #   re-derived, so a `carousel_role: slides_only` style can no more be matched onto a deck
        #   anchor than it could be rotated onto one.
        "match_entries",  # the per-entry sections, keyed by ASSET_ID and never by ordinal: format,
        #   the text-only source signals (topic strength, Virlo's own hook/visual-hook/emotional
        #   classifications, the bound post's overlays, hooks, panel count and views, the derived
        #   deck length) — all $0, all already in memory at ASSIGN. The asset_id key is load-bearing:
        #   an ordinal join is what caused the W5 renumbering bug, and a trimmed or reordered plan
        #   must never be able to hand one creative another creative's verdict.
        # --- v2.5.0 (D59, FR-338): the counter's own channel to the slide renderer. ---
        "counter_rule",  # CAROUSEL SLIDES ONLY. The single line that tells the SLIDE RENDERER what
        #   to do about this deck's position badge: the `counter_slot` zone's own words when the
        #   style declares one and the deck is counted (rendered by the same formatter the critic's
        #   `{{layout_zones}}` uses, so renderer and critic read the badge in identical words), the
        #   house-default corner when the style declares no such zone, or the flat statement that
        #   this deck carries NO counter at all. It exists for the same reason `list_treatment`
        #   above does, in the same role, against the same hole: `carousel_slide.md` names no
        #   `{{layout_zones}}` slot, so the zone that places the badge reached the image, reel and
        #   critic paths and never the deck renderer — which was left to infer a badge from
        #   whatever chip STYLE_DNA happened to describe, on counted and uncounted decks alike.
        #   Deliberately absent from `_TRUNCATION_ORDER` and `_STYLE_TRIO`: uncuttable, like the
        #   TEXT block whose badge it places. Empty under an override brief and on a style-less
        #   context, exactly as `list_treatment` and `layout_zones` are.
        # --- v2.9.0 (D65, FR-370): the reserved screenshot plate. ---
        "screenshot_plate",  # CAROUSEL SLIDES ONLY, and only the ones taking a paste. The block
        #   that orders the render to leave ONE flat rounded rectangle empty — 8%-92% of the width
        #   by 20%-78% of the height, the compositor's own geometry quoted through
        #   `screenshot_paste.plate_zone()` — so that after the frame lands the engine can
        #   composite the source panel's REAL captured interface into it, exact pixel for exact
        #   pixel. It exists because a screenshot is the one thing on a source slide a render
        #   model cannot reproduce and must not try to: asked for "a tweet saying X" it draws an
        #   invented handle, invented words and an invented avatar onto a frame we are about to
        #   publish. Empty on every slide that takes no paste, which is nearly all of them, so it
        #   costs the rest of the registry nothing. Uncuttable (absent from `_TRUNCATION_ORDER`
        #   and `_STYLE_TRIO`): a plate the model was told about at half length is a plate drawn
        #   somewhere else, and the paste would land on top of the words.
        # --- v2.6.0 (D62, FR-351/FR-352): the cover judge's two slots. ---
        # Both are allowlisted for `cover_pick_system.md` ALONE, on the `style_candidates` terms
        # and for a sharper reason: `cover_contract` carries one style's whole DNA together with
        # every string that has to be legible on the cover, so a render role able to resolve it
        # would be handed a second copy of its own art direction plus a list of words no TEXT
        # block sanctioned. Neither slot ever becomes pixels — this call reads finished frames and
        # returns one candidate id and one sentence for a person to read.
        "cover_contract",  # what the cover was ORDERED to be, as fenced DATA: the deck's asset_id,
        #   its assigned style key, the counter it carries (or the statement that it carries none,
        #   which makes a badge on any candidate invented chrome), every expected string one per
        #   line, and the `style_dna` bytes the render prompt itself carried — verbatim, because a
        #   paraphrase would judge the candidates against a look nothing was rendered from.
        "cover_candidates",  # the roll-call mapping each answerable candidate id to its attached
        #   image ("candidate 2 — attachment 2"). The answer names an ID and never an ordinal of
        #   the model's own, so this block is the only thing tying a number to a picture.
    }
)
