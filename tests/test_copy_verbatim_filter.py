"""D42 — the copy IS the source's own words, byte for byte, minus the brands we filter out.

This file is `test_copy_no_verbatim.py` with its polarity flipped, and the flip is the whole
point: until 2026-08-12 the barrier here asserted that NO source string could reach a creative
(A20, "no plagiarism"); the operator reversed that premise (D42, legal exposure accepted) and the
product is now a winning post's own phrasing, in its own language. What has NOT reversed is the
part that made A20 worth having — a competitor's brand must never become our pixels — so the
sentinel technique survives with a new predicate.

Four claims, in the order they can cost money:

1. **Byte identity is structural, not promised.** The engine numbers the offerable strings, the
   model returns LABELS, the engine resolves labels to the bytes it already holds. Nothing is
   retyped, nothing is trimmed (an over-budget string was never offered) and `_apply_budgets` is
   bypassed for every ref-resolved field — so diacritics, emoji and line breaks survive by
   construction rather than by care.
2. **The blocklist is absolute and asymmetric.** `branding.competitors` (§1.5 layer 1) is applied
   UNGUARDED — a configured competitor that happens to BE the topic's own name is still stripped,
   because "the name is the subject" must never be the reason a competitor ships in our frame. The
   filter's own `brands_to_strip` (layer 2) arrive already screened by `topic_filter.screen`'s M15
   guards and are applied as given, never re-judged here.
3. **The audit never costs a card.** The verifier checks every shipped string as a byte-substring
   of what the creative was entitled to quote and against the blocklist; a deviation logs and tags
   `copy_not_verbatim` and the creative ships anyway. It is already paid for — the operator needs
   to know which card to distrust, not to be handed fewer cards.
4. **It is verified at the ASSEMBLED RENDER PROMPT, not at the `CopySet`.** That is the operator's
   standing mandate and the reason `build_context` runs its own `_strip_brands` pass (M6): a brand
   can reach an image model through `{{trend_texts}}`, `{{render_prompt}}` or the deterministic
   content sentence without ever touching the copy object. The sentinel tests below assemble the
   real gpt-image-2 and seedance roles and assert the brand appears in none of them.

**What D54 compress mode (v2.3.0, FR-331) does and does not change here, because the two halves
of claim 3 part company on that path.** A compressed carousel deck's slides are the copy model's
own bytes rather than a quote of the post's, so:

* **Claim 1 does not apply to it and is not asserted to.** `_compressed` returns
  `_Written(quoted=())`, which is the same shape an override brief has always returned, and
  `_verify`'s byte-substring half self-skips on an empty pool — a compressed line is not a
  substring of anything and reporting it as a deviation would tag every deck in the mode. The
  receipts that replace the substring claim are `CopyProvenance.copy_mode == "compress"`, every
  `panel_map` row's `compressed: True`, and `source_text_original` beside `source_text` in each
  row. `tests/test_copywrite.py` owns those; this file owns what follows.
* **Claim 2 is mode-INDEPENDENT and still fail-closed, which is the half that matters most on
  this path.** `_verify`'s blocklist half reads the `CopySet`, not the quoted pool, so it audits
  every compressed slide, the compressed caption and every hashtag exactly as it audits a quote —
  and `_compress_field` applies `apply_blocklist` to the model's line BEFORE anything else, since
  a model that read a competitor's name in the fenced trend texts can write it into a slide the
  source panel never mentioned. The sentinel at the end of this file seeds a brand into a compress
  payload and proves it reaches neither the `CopySet` nor any assembled render prompt.
* **Claim 4 is unchanged in every respect.** The prompt is still where the barrier is enforced,
  and the channels `build_context` builds from the TOPIC are the same ones whatever contract wrote
  the copy.

No network: the `llm.structured_call` seam is a stub matching `models.StructuredCall`, and no test
here writes outside `tmp_path`.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from hypesocials import copywrite
from hypesocials.config import TextBudgets
from hypesocials.models import (
    CopySet,
    DegradationTag,
    MetaStyle,
    ParsedResult,
    PlanEntry,
    SourcePost,
    TrendItem,
)
from hypesocials.prompts_engine import PromptEngine, build_context

#: Nonsense on purpose: any of these turning up anywhere can only have come from the source, and
#: the BRAND one turning up anywhere at all is the failure this file exists to catch.
BRAND = "Zzqcorp"
#: Short on purpose: every hook here has to survive the tightest ceiling in force (FR-101's
#: `image_headline=42` intersected with the style's own cap), or the tests would be measuring the
#: budget filter rather than the thing they are named after.
BRAND_HOOK = f"{BRAND} raised prices again"
CLEAN_HOOK = "Nobody tells you this about pricing"
CZECH_HOOK = "Rychlejší růst — bez agentury"
EMOJI_CAPTION = "Všechno se změnilo 🚀 tenhle kvartál, a nikdo o tom nemluví #ai #saas"

NICHE = "AI automation for Czech SMBs; audience: operations leads who buy outcomes."
STYLE_KEY = "flat-card"
RENDER_PROFILE = "gpt-image-2"


# --------------------------------------------------------------------------- doubles & builders


class Recorder:
    """The `LogWriter` surface `copywrite` touches (module-local, house style)."""

    def __init__(self) -> None:
        self.warnings: list[tuple[str, str, dict[str, Any]]] = []

    def warn(self, event: str, message: str = "", /, **data: Any) -> None:
        self.warnings.append((event, message, data))

    def warned(self, event: str) -> list[str]:
        return [message for name, message, _ in self.warnings if name == event]


class DeadCall:
    """A `StructuredCall` that never produces a usable answer — every attempt degrades.

    This is the shape FR-99's last resort exists for: the grouped call fails, each per-creative
    split call fails too, and nothing is left but the deterministic tier.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, role, messages, json_schema, images=None) -> ParsedResult:
        self.calls += 1
        return ParsedResult(parsed=None, raw_text="stub failure", degraded=True)


class ScriptedCall:
    """Answers each creative from a list of payloads, one per attempt, recording every call."""

    def __init__(self, script: dict[str, list[dict[str, Any]]]) -> None:
        self.script = {asset_id: list(answers) for asset_id, answers in script.items()}
        self.calls: list[list[str]] = []

    async def __call__(self, role, messages, json_schema, images=None) -> ParsedResult:
        system = messages[0]["content"]
        asset_ids = [line.split(" · ")[0].removeprefix("- ").strip()
                     for line in system.splitlines()
                     if line.startswith("- ") and " · " in line]
        self.calls.append(asset_ids)
        creatives = []
        for asset_id in asset_ids:
            answers = self.script.get(asset_id) or []
            if answers:
                creatives.append(answers.pop(0) | {"asset_id": asset_id})
        return ParsedResult(parsed={"creatives": creatives}, raw_text="{}")


def refs(**overrides: Any) -> dict[str, Any]:
    """One `CopySelection` answer — labels only."""
    payload: dict[str, Any] = {"headline_ref": "", "subline_ref": "", "overlay_ref": "",
                               "slide_refs": [], "caption_ref": "", "through_line": "",
                               "narrative_arc": "", "motion_beat": ""}
    payload.update(overrides)
    return payload


def post(number: int, *, views: int = 1_000, caption: str = "", hooks: tuple[str, ...] = (),
         overlays: tuple[str, ...] = (), panels: tuple[str, ...] = (),
         description: str = "", author: str = "") -> SourcePost:
    return SourcePost(post_id=f"p{number}", url=f"https://virlo.test/p/{number}",
                      author=author or f"@creator{number}", views=views,
                      caption=caption or f"Caption of post {number}, as its author wrote it.",
                      hooks=list(hooks), text_overlays=list(overlays), panel_texts=list(panels),
                      description=description)


def topic(*posts: SourcePost, name: str = "AI tool stacks", key: str = "t1") -> TrendItem:
    return TrendItem(history_key=key, monitor_id="m1", name=name, topic_key=key,
                     posts=list(posts) or [post(1, hooks=(CLEAN_HOOK,))],
                     why_it_works="a withheld subject in the first line")


def style(**overrides: Any) -> MetaStyle:
    meta = MetaStyle(key=STYLE_KEY, render_prompt="Flat graphic card, centred subject, wide margins.",
                     format_affinity=["image", "carousel", "reel"],
                     max_onimage_chars={"headline": 90, "subline": 60, "slide": 90},
                     exclusions=["platform UI", "follower counters"],
                     palette=["#0B0B0C", "#3DDC97"], typography="extra-bold condensed sans",
                     text_placement="headline upper third", image_treatment="flat graphic",
                     visual_pacing="the eye lands on the headline")
    for key, value in overrides.items():
        setattr(meta, key, value)
    return meta


def entry(asset_id: str = "a1", order: int = 0, **overrides: Any) -> PlanEntry:
    plan_entry = PlanEntry(order=order, asset_id=asset_id, creative_format="image",
                           platform="linkedin", language="en", aspect_ratio="16:9",
                           trend_key="t1", style_key=STYLE_KEY)
    for key, value in overrides.items():
        setattr(plan_entry, key, value)
    return plan_entry


async def write(entries, call, **overrides: Any) -> copywrite.CopyResult:
    kwargs: dict[str, Any] = {"trends": {"t1": topic()}, "styles": {STYLE_KEY: style()},
                              "engine": PromptEngine(), "text_budgets": TextBudgets(),
                              "niche_descriptor": NICHE}
    kwargs.update(overrides)
    return await copywrite.write_copy(entries, call=call, **kwargs)


#: The `CopySet` fields that are NOT shipped words: `through_line`, `narrative_arc` and
#: `motion_beat` are free text that never becomes pixels or a caption (§1.7.2) — they reach a
#: prompt only through `build_context`, where M6's own strip pass covers them, and the
#: prompt-level tests at the bottom of this file are where that half is asserted. The three
#: identity fields carry no source text at all.
_NOT_SHIPPED_WORDS = frozenset({"asset_id", "language", "trend_key", "through_line",
                                "narrative_arc", "motion_beat", "hook_pattern_used"})


def shipped_strings(copyset: CopySet) -> str:
    """Every string this creative ships AS WORDS — pixels or caption — as one blob.

    Walks the dataclass rather than naming the fields it keeps, so a field added to `CopySet`
    tomorrow is covered by this barrier the moment it exists and has to be excluded deliberately.
    """
    return " ".join(
        " ".join(str(item) for item in value) if isinstance(value, list) else str(value)
        for name, value in dataclasses.asdict(copyset).items()
        if name not in _NOT_SHIPPED_WORDS)


# --------------------------------------------------------------------- byte identity (§1.7.3)


async def test_a_resolved_string_is_the_source_posts_own_bytes_diacritics_and_all() -> None:
    """The reversal in one assertion: the headline IS the post's hook, character for character.

    Czech diacritics and an em dash are the case free-text "return it as-is" always lost — models
    retype, and a retyped `Rychlejší` comes back `Rychlejsi`. Selection cannot lose them, because
    nothing between the `SourcePost` and the `CopySet` writes a string.
    """
    source = topic(post(1, hooks=(CZECH_HOOK,), caption=EMOJI_CAPTION))
    call = ScriptedCall({"a1": [refs(headline_ref="P1.hook.1", caption_ref="P1.caption")]})

    result = await write([entry()], call, trends={"t1": source})

    copyset = result.copy["a1"]
    assert copyset.headline == CZECH_HOOK
    assert copyset.headline in source.posts[0].hooks[0]
    assert "ě" in copyset.caption and "🚀" in copyset.caption
    assert copyset.caption == "Všechno se změnilo 🚀 tenhle kvartál, a nikdo o tom nemluví"
    assert copyset.hashtags == ["#ai", "#saas"], "the trailing run is peeled, not invented"


async def test_a_ref_resolved_field_is_never_trimmed_even_under_an_absurd_budget() -> None:
    """`_apply_budgets` is BYPASSED on the verbatim path (§1.7.3). The caption is the field that
    proves it: it ships whole to `caption.txt` (FR-230) and is under no on-image ceiling at all,
    while the on-image slots simply come back empty because nothing short enough was offered."""
    long_caption = ("A caption that runs on for far longer than any on-image budget would ever "
                    "allow, because a caption is read in a feed and not inside a picture.")
    source = topic(post(1, hooks=("A hook of moderate length",), caption=long_caption))
    call = ScriptedCall({"a1": [refs(headline_ref="P1.hook.1", caption_ref="P1.caption")]})

    result = await write([entry()], call, trends={"t1": source},
                         styles={STYLE_KEY: style(max_onimage_chars={"headline": 8})})

    copyset = result.copy["a1"]
    assert copyset.caption == long_caption, "no ellipsis, no cut, no word-boundary trim"
    assert copyset.headline == "", "the hook did not fit, so it was never offered"
    assert not result.trimmed
    assert DegradationTag.TEXT_TRIMMED not in result.tags.get("a1", ())


async def test_nothing_fits_ships_a_caption_only_creative_and_says_so_once() -> None:
    """§1.7.4's first degrade shape — the call SUCCEEDED, there was simply nothing short enough.
    `no_onimage_text` is what the operator will actually see in the frame, and it is not a copy
    failure: the creative ships, on a proven layout, with a real caption under it."""
    log = Recorder()
    source = topic(post(1, hooks=("A hook that will not fit an eight character budget",),
                        caption="A caption the creative can still ship."))
    call = ScriptedCall({"a1": [refs(caption_ref="P1.caption")]})

    result = await write([entry()], call, trends={"t1": source}, log=log,
                         styles={STYLE_KEY: style(max_onimage_chars={"headline": 8})})

    copyset = result.copy["a1"]
    assert (copyset.headline, copyset.subline, copyset.overlay_text) == ("", "", "")
    assert copyset.slide_texts == []
    assert copyset.caption == "A caption the creative can still ship."
    assert result.tags["a1"] == (DegradationTag.NO_ONIMAGE_TEXT,)
    assert not result.degraded, "a budget that fits nothing is not a failed copy call"
    assert len(log.warned("no_onimage_text")) == 1


# --------------------------------------------------------- labels, provenance and divergence


async def test_the_provenance_records_which_string_not_merely_which_post() -> None:
    """FR-298/contracts item 14: `copy_source_refs` is `{slot: "P<n>.<kind>[.<i>]"}` keyed by the
    `CopySet` field the label resolved into, so meta.yaml can say "quotes P1.hook.2 verbatim"."""
    source = topic(post(1, hooks=("First hook", "Second hook"), overlays=("An overlay line",),
                        caption="The caption, long enough to be one."))
    call = ScriptedCall({"a1": [refs(headline_ref="P1.hook.2", subline_ref="P1.overlay.1",
                                     caption_ref="P1.caption")]})

    result = await write([entry()], call, trends={"t1": source})

    provenance = result.provenance["a1"]
    assert provenance.post_id == "p1"
    assert provenance.refs == {"headline": "P1.hook.2", "subline": "P1.overlay.1",
                               "caption": "P1.caption"}
    assert result.copy["a1"].headline == "Second hook", "the label's INDEX is 1-based"
    assert all(copywrite._REF.match(label) for label in provenance.refs.values())


async def test_a_mapped_decks_slide_is_its_source_panel_and_a_gap_stays_a_gap() -> None:
    """FR-304 at the provenance level: `slide_<n>` means OUR slide *n*, which renders THEIR panel
    *n*, and a slot neither Virlo nor vision could fill keeps its position rather than closing.

    This test used to assert the opposite — that a dropped reference CLOSED the gap and `slide_2`
    meant "the second slide that shipped". That was defensible while every slide was an independent
    quote; under D46 the deck is a re-render of one source deck, so closing a gap ships a deck that
    reads as theirs with two slides swapped. The rule reversed with FR-302's position-preserving
    grammar, and the reversal is the fix.
    """
    source = topic(post(1, panels=("Panel one", "", "Panel three"),
                        caption="A caption, long enough to be one."))
    call = ScriptedCall({"a1": [refs(caption_ref="P1.caption")]})

    result = await write([entry("a1", 0, creative_format="carousel", slide_count=3,
                                source_post_id="p1")], call, trends={"t1": source})

    assert result.copy["a1"].slide_texts == ["Panel one", "", "Panel three"]
    assert result.provenance["a1"].refs["slide_1"] == "P1.panel.1"
    assert result.provenance["a1"].refs["slide_3"] == "P1.panel.3"
    assert "slide_2" not in result.provenance["a1"].refs, "an empty slot claims nothing"
    assert [row["source_position"] for row in result.provenance["a1"].panel_map] == [1, 2, 3]


async def test_a_ref_naming_another_post_is_re_pointed_at_the_bound_one_and_logged() -> None:
    """The plan binds the post; the model chooses the STRING. A label naming a post this creative
    was not given keeps the editorial choice (same kind, same index) and moves it to the bound
    post, so the no-repeat guarantee holds and the answer is not simply thrown away."""
    log = Recorder()
    source = topic(post(1, hooks=("First post hook",), caption="First caption, written in full."),
                   post(2, hooks=("Second post hook",), caption="Second caption, written in full."))
    call = ScriptedCall({"a2": [refs(headline_ref="P1.hook.1", caption_ref="P1.caption")]})

    result = await write([entry("a2", 1, source_post_id="p2")], call, trends={"t1": source},
                         log=log)

    assert result.copy["a2"].headline == "Second post hook", "re-pointed to the bound post"
    assert result.provenance["a2"].refs["headline"] == "P2.hook.1"
    assert result.copy["a2"].caption == "Second caption, written in full."
    assert log.warned("copy_ref_out_of_scope")


async def test_two_creatives_on_one_topic_quote_two_different_posts() -> None:
    """W5's assertion, at its source: `copy_source_post_id` differs per sibling. Cloned captions
    across the creatives of one topic are what the ASSIGN-time binding prevents — and, unlike the
    rotation it replaced, each bound post is one the plan checked was fresh (FR-307)."""
    source = topic(post(1, hooks=("First post hook",), caption="First caption, written in full."),
                   post(2, hooks=("Second post hook",), caption="Second caption, written in full."))
    call = ScriptedCall({"a1": [refs(headline_ref="P1.hook.1", caption_ref="P1.caption")],
                         "a2": [refs(headline_ref="P2.hook.1", caption_ref="P2.caption")]})

    result = await write([entry("a1", 0, source_post_id="p1"),
                          entry("a2", 1, source_post_id="p2")], call, trends={"t1": source})

    assert result.provenance["a1"].post_id != result.provenance["a2"].post_id
    assert {result.provenance["a1"].post_id, result.provenance["a2"].post_id} == {"p1", "p2"}
    assert result.copy["a1"].caption != result.copy["a2"].caption


def test_the_ref_label_grammar_is_the_pinned_one_and_description_no_longer_parses() -> None:
    """FR-302, 1-based, FOUR kinds, the one scalar carrying no index.

    `P1.description` used to parse and used to resolve, and the first paid run captioned a creative
    with what it resolved to: Virlo's own AI summary, shipped as though a human had written it.
    FR-303 removes it from the grammar itself rather than from a length filter or a caption list —
    a label nothing can name is a label nothing can ship, on any path, however the offer table is
    rebuilt later.
    """
    for label in ("P1.hook.2", "P3.panel.1", "P2.caption", "P10.overlay.4"):
        assert copywrite._REF.match(label), label
    for label in ("P1.description", "P2.description.1", "hook.1", "P1.headline.1", "P1",
                  "Pone.hook.1", "P1.hook.two", ""):
        assert copywrite._REF.match(label) is None, label
    assert set(copywrite._KIND_FIELDS) == {"hook", "overlay", "panel", "caption"}
    assert copywrite._CAPTION_KINDS == ("caption",)


# ----------------------------------------------------------- the blocklist and its asymmetry


async def test_a_blocklisted_brand_never_reaches_a_shipped_string_and_the_creative_is_tagged() -> None:
    """§1.5 layer 1, fail-closed. The strip happens at candidate-build time, so the bytes we OFFER
    are the bytes we SHIP — and `competitor_stripped` is what tells the operator the copy is still
    sourced but no longer byte-identical."""
    log = Recorder()
    source = topic(post(1, hooks=(BRAND_HOOK,), caption=f"Everyone moved off {BRAND} this month."))
    call = ScriptedCall({"a1": [refs(headline_ref="P1.hook.1", caption_ref="P1.caption")]})

    result = await write([entry()], call, trends={"t1": source}, competitors=[BRAND], log=log)

    copyset = result.copy["a1"]
    assert BRAND not in shipped_strings(copyset)
    assert BRAND.casefold() not in shipped_strings(copyset).casefold()
    assert copyset.headline == "raised prices again"
    assert copyset.caption == "Everyone moved off this month."
    assert DegradationTag.COMPETITOR_STRIPPED in result.tags["a1"]
    assert log.warned("competitor_stripped")


async def test_the_brand_is_stripped_even_when_it_is_the_topics_own_name() -> None:
    """THE pinned asymmetry (§1.5/M15, conductor decision). M15's subject-of-the-sentence guard
    belongs to the LLM's proposals, which `topic_filter.screen` has already screened by the time
    they arrive here. `branding.competitors` is the operator's own explicit list and is applied
    UNGUARDED: "the brand is what the topic is about" must never be the reason a competitor's name
    ends up in our pixels."""
    source = topic(post(1, hooks=(BRAND_HOOK,), caption=f"{BRAND} is the whole story today."),
                   name=f"{BRAND} raises prices")

    call = ScriptedCall({"a1": [refs(headline_ref="P1.hook.1", caption_ref="P1.caption")]})
    result = await write([entry()], call, trends={"t1": source}, competitors=[BRAND])

    copyset = result.copy["a1"]
    assert BRAND not in shipped_strings(copyset)
    assert copyset.headline == "raised prices again"
    assert copyset.caption == "is the whole story today."
    assert DegradationTag.COMPETITOR_STRIPPED in result.tags["a1"]
    # `through_line` falls back to the topic's NAME when the model returns none, so on this fixture
    # it still carries the brand — deliberately: it is free text that never becomes pixels, and the
    # channel it does reach (`reel_director.md`'s `{{through_line}}`) is stripped by M6 at the
    # prompt. `test_the_strip_reaches_the_channels_the_copy_object_never_touches` asserts that half.
    assert copyset.through_line == f"{BRAND} raises prices"


async def test_the_filters_own_strip_list_is_applied_as_given_and_never_re_judged() -> None:
    """§1.5 layer 2 arrives post-guard from `topic_filter.screen` (subject, stopwords, product
    nouns, the <15-character floor). Re-judging it here would put one guard in two places and let
    the two drift, so this module applies exactly what it was handed — keyed by topic."""
    source = topic(post(1, hooks=("Betaco shipped an agent builder this week",),
                        caption="Betaco shipped an agent builder this week, everyone noticed."))
    call = ScriptedCall({"a1": [refs(headline_ref="P1.hook.1", caption_ref="P1.caption")]})

    result = await write([entry()], call, trends={"t1": source},
                         strip_brands={"t1": ["Betaco"]})

    assert "Betaco" not in shipped_strings(result.copy["a1"])
    assert result.copy["a1"].headline == "shipped an agent builder this week"
    assert DegradationTag.COMPETITOR_STRIPPED in result.tags["a1"]


async def test_a_string_that_was_entirely_a_brand_name_is_dropped_rather_than_shipped_empty() -> None:
    """"the whole string WAS the brand — there is nothing left to quote". An empty candidate is
    not a candidate; it must not be offered as a headline the model can select into nothing."""
    source = topic(post(1, hooks=(BRAND,), caption=f"Something real about {BRAND} pricing."))
    call = ScriptedCall({"a1": [refs(headline_ref="P1.hook.1", caption_ref="P1.caption")]})

    result = await write([entry()], call, trends={"t1": source}, competitors=[BRAND])

    assert result.copy["a1"].headline == ""
    assert BRAND not in shipped_strings(result.copy["a1"])


# ------------------------------------------------------------------ the verifier (A20 flipped)


def test_the_verifier_tags_a_deviation_and_never_fails_the_creative() -> None:
    """The audit, asserted at its own seam: a string that is not a byte-substring of what this
    creative was entitled to quote tags `copy_not_verbatim` — and the tag is the WHOLE remedy. The
    creative is already paid for by the time anything here runs."""
    log = Recorder()
    run = copywrite._Run(call=None, engine=PromptEngine(), budgets=TextBudgets(),  # type: ignore[arg-type]
                         styles={}, conventions={}, onimage_languages={}, niche_descriptor="",
                         brand_context="", competitors=(BRAND,), strip_brands={}, log=log)
    written = copywrite._Written(
        copyset=CopySet("a1", "en", headline="A headline nobody actually wrote",
                        caption="A caption the post really carries."),
        source=copywrite.CopyProvenance(post_id="p1"),
        quoted=("A caption the post really carries.",))

    tags = copywrite._verify(written, entry(), run)

    assert tags == [DegradationTag.COPY_NOT_VERBATIM]
    assert log.warned("copy_not_verbatim")
    assert "is not a byte-substring" in log.warned("copy_not_verbatim")[0]
    assert "The creative ships and is tagged" in log.warned("copy_not_verbatim")[0]


def test_the_verifier_also_catches_a_blocklisted_brand_that_survived_every_earlier_pass() -> None:
    """The fail-closed half, re-checked at the very last moment before the bytes leave the module.
    It is deliberately redundant with `_apply_strip`: one of the two is the day the other breaks."""
    log = Recorder()
    run = copywrite._Run(call=None, engine=PromptEngine(), budgets=TextBudgets(),  # type: ignore[arg-type]
                         styles={}, conventions={}, onimage_languages={}, niche_descriptor="",
                         brand_context="", competitors=(BRAND,), strip_brands={}, log=log)
    leaked = f"{BRAND} raised prices"
    written = copywrite._Written(copyset=CopySet("a1", "en", headline=leaked),
                                 source=copywrite.CopyProvenance(), quoted=(leaked,))

    assert copywrite._verify(written, entry(), run) == [DegradationTag.COPY_NOT_VERBATIM]
    assert "blocklisted competitor" in log.warned("copy_not_verbatim")[0]


def test_a_free_text_creative_claims_nothing_so_the_substring_half_does_not_apply() -> None:
    """An override brief quotes no post: there is nothing to be verbatim ABOUT, and only the
    blocklist half of the audit is meaningful for it."""
    run = copywrite._Run(call=None, engine=PromptEngine(), budgets=TextBudgets(),  # type: ignore[arg-type]
                         styles={}, conventions={}, onimage_languages={}, niche_descriptor="",
                         brand_context="", competitors=(BRAND,), strip_brands={}, log=None)
    written = copywrite._Written(copyset=CopySet("a1", "en", headline="Words we wrote ourselves"),
                                 source=copywrite.CopyProvenance(), quoted=())

    assert copywrite._verify(written, entry(), run) == []


async def test_a_healthy_verbatim_creative_earns_no_tag_at_all() -> None:
    """The control for the three above: the normal path is silent, so a tag means something."""
    source = topic(post(1, hooks=(CLEAN_HOOK,), caption="A caption the post really carries."))
    call = ScriptedCall({"a1": [refs(headline_ref="P1.hook.1", caption_ref="P1.caption")]})

    result = await write([entry()], call, trends={"t1": source})

    assert result.tags == {}
    assert result.copy["a1"].headline == CLEAN_HOOK


# ------------------------------------------------------------------ the no-call tier (§1.7.4)


async def test_a_failed_copy_call_ships_the_top_posts_caption_verbatim_and_no_on_image_text() -> None:
    """The other reversal, and the one that used to be worst. Until A20 this tier put the source's
    hook into `headline` and its deck panel for panel into `slide_texts`; A20 emptied every field.
    The pivot restores the CAPTION — the source's own words in its own language ARE the product —
    and keeps the frame wordless, because this path runs when the model told us nothing and we do
    not know WHICH string belonged in the picture."""
    log = Recorder()
    source = topic(post(1, views=900, caption="The top post's caption, exactly as written. #ai"),
                   post(2, views=100, caption="A weaker post's caption."))
    call = DeadCall()

    result = await write([entry()], call, trends={"t1": source}, log=log)

    copyset = result.copy["a1"]
    assert copyset.caption == "The top post's caption, exactly as written."
    assert copyset.hashtags == ["#ai"]
    assert (copyset.headline, copyset.subline, copyset.overlay_text) == ("", "", "")
    assert copyset.slide_texts == []
    assert set(result.tags["a1"]) == {DegradationTag.COPY_DEGRADED,
                                      DegradationTag.NO_ONIMAGE_TEXT}
    assert result.degraded == frozenset({"a1"}), "still an FR-248 llm_starved loss (exit 1)"
    assert result.provenance["a1"].post_id == "p1", "P1, not the creative's assigned post"
    assert result.provenance["a1"].refs == {"caption": "P1.caption"}
    assert log.warned("copy_degraded")


async def test_a_failed_bound_deck_still_maps_its_panels_and_a_reel_stays_wordless() -> None:
    """The FR-99-vs-FR-304 ruling (D15, SESSION G) splits the no-call tier by what the model
    actually contributed. A BOUND deck's slides are a deterministic panel mapping — no model in
    the loop — so a failed copy call ships the mapped panels verbatim, position-preserving, with
    full provenance, and loses only the model's own additions (through-line, narrative arc). A
    reel's overlay was genuinely the model's CHOICE, so guessing one is still wrong and the reel
    stays wordless."""
    source = topic(post(1, panels=("Panel one", "Panel two"), hooks=("A hook",),
                        caption="A caption, written out in full."))

    deck = await write([entry("a1", 0, creative_format="carousel", slide_count=3,
                              source_post_id="p1")], DeadCall(), trends={"t1": source})
    reel = await write([entry("a2", 0, creative_format="reel", aspect_ratio="9:16",
                              source_post_id="p1")], DeadCall(), trends={"t1": source})

    assert deck.copy["a1"].slide_texts == ["Panel one", "Panel two", ""], \
        "mapped, position-preserving, the plan's length — the empty slot IS the alignment"
    assert deck.copy["a1"].headline == "", "only the deck is mapped; nothing else is guessed"
    prov = deck.provenance["a1"]
    assert prov.post_id == "p1" and prov.source_panel_count == 2
    assert [row["source_text"] for row in prov.panel_map] == ["Panel one", "Panel two", ""]
    assert prov.refs["slide_1"] == "P1.panel.1" and prov.refs["caption"] == "P1.caption"
    assert DegradationTag.COPY_DEGRADED in deck.tags["a1"], "the LLM loss still counts (FR-248)"
    assert DegradationTag.NO_ONIMAGE_TEXT not in deck.tags["a1"], "the frame has words now"
    assert reel.copy["a2"].overlay_text == "" and reel.copy["a2"].headline == ""
    assert reel.copy["a2"].slide_texts == []
    assert deck.copy["a1"].caption == "A caption, written out in full." == reel.copy["a2"].caption


async def test_the_no_call_tier_strips_the_blocklist_from_the_caption_it_ships() -> None:
    """The degrade path is the one place a competitor's name could ride in unchecked — there is no
    model answer to filter, only our own last resort."""
    source = topic(post(1, caption=f"{BRAND} changed its pricing and everyone noticed."))

    result = await write([entry()], DeadCall(), trends={"t1": source}, competitors=[BRAND])

    assert BRAND not in shipped_strings(result.copy["a1"])
    assert result.copy["a1"].caption == "changed its pricing and everyone noticed."


async def test_a_topic_with_no_quotable_caption_falls_back_to_our_own_words_and_claims_nothing() -> None:
    """When there is nothing to quote the honest answer is ours: the topic's own name, and since
    v2.2.0 THAT ALONE. The niche descriptor used to ride along and shipped the operator's config
    file as caption copy on a paid creative (08-14 audit, FR-99/FR-307 caption forms). No
    provenance label is recorded for it either way, because it is not a quote."""
    bare = TrendItem(history_key="t1", monitor_id="m1", name="AI Trends Tracker", topic_key="t1")

    result = await write([entry()], DeadCall(), trends={"t1": bare})

    caption = result.copy["a1"].caption
    assert caption == "AI Trends Tracker"
    assert NICHE not in caption and "AI automation for Czech SMBs" not in caption
    assert result.provenance["a1"].refs == {}
    assert result.tags["a1"] == (DegradationTag.COPY_DEGRADED, DegradationTag.NO_ONIMAGE_TEXT)


# ------------------------------------------------ what may never be offered as ON-IMAGE text


def _offer(plan_entry: PlanEntry, source: TrendItem, meta: MetaStyle | None = None,
           competitors: tuple[str, ...] = (),
           chrome_lines: dict[str, list[str]] | None = None,
           log: Any = None) -> copywrite._Offer:
    run = copywrite._Run(call=None, engine=PromptEngine(), budgets=TextBudgets(),  # type: ignore[arg-type]
                         styles={STYLE_KEY: meta or style()}, conventions={},
                         onimage_languages={}, niche_descriptor="", brand_context="",
                         competitors=competitors, strip_brands={},
                         chrome_lines=chrome_lines or {}, log=log)
    return copywrite._offer_for(plan_entry, copywrite._Group(trend=source, campaign_brief=None,
                                                             entries=[plan_entry]), run)


async def test_virlos_own_summary_is_now_banned_from_every_output_not_merely_from_the_frame() -> None:
    """`SourcePost.description` is the ONE field that is not the creator's words — Virlo's
    `intelligence` block writes it (`virlo._source_post`'s table says so in as many words, and
    names `copywrite` as the module that must enforce the distinction).

    History, in two reversals. It was a CAPTION candidate and never an on-image one: legitimate
    context, legitimately verbatim *from Virlo*, and burning an AI paraphrase into a frame as
    though a human wrote it was the one quote this engine would not make. Then the first paid run
    captioned a creative with it, and the operator saw a machine's summary of a post presented as
    the post's own voice. FR-303 (D46) closes it completely: the summary is fenced CONTEXT and
    nothing else. It is enforced at the grammar (FR-302 dropped the kind), so there is no offer
    table, no caption list and no fallback tier through which it can reach an output.

    The post here has NOTHING else to caption with — the summary is the only long string on it —
    so if any path could still reach it, this is the run where it would show.
    """
    source = topic(post(1, hooks=("A real hook",), caption=" ",  # blank, not defaulted
                        description="Virlo says the post is mostly about pricing pages."))
    call = ScriptedCall({"a1": [refs(headline_ref="P1.hook.1", caption_ref="P1.description")]})

    offer = _offer(entry(), source)
    result = await write([entry()], call, trends={"t1": source})
    degraded = await write([entry("a2")], DeadCall(), trends={"t1": source})

    assert [c.label for c in offer.captions] == [], "not a caption candidate any more"
    assert "P1.description" not in [c.label for c in offer.onimage]
    assert "Virlo says" not in " ".join(c.text for c in offer.onimage + offer.captions)
    assert "Virlo says" not in shipped_strings(result.copy["a1"]), "not through a ref"
    assert "Virlo says" not in shipped_strings(degraded.copy["a2"]), "not through the degrade tier"
    assert result.copy["a1"].caption.startswith("A real hook"), (
        "the post's own hook under our attribution (FR-99/FR-307 caption forms), not the summary")
    assert NICHE not in result.copy["a1"].caption, "and never the operator's niche descriptor"


async def test_a_caption_of_hashtags_and_three_words_is_not_a_caption(
) -> None:
    """D46 §0.7, the operator-settled floor: a caption is a caption only when at least 25
    non-hashtag characters survive the trailing-tag split. Six of the eight creatives in the first
    paid run shipped a tag dump as their caption, which is what the source posts actually carried
    under the picture — so the engine now captions the creative with its own bound post's best
    remaining line plus a neutral attribution (FR-99/FR-307 caption forms, v2.2.0), exactly as it
    does when a post has no caption at all. What it may never fall back to is the operator's niche
    descriptor: that string steers the copy prompt and is not caption copy.

    The two captions below differ by ONE character — a full stop — and that is the whole boundary:
    24 non-hashtag characters is a tag dump, 25 is a caption.
    """
    thin = topic(post(1, hooks=("A real hook",),
                      caption="Everything changed today #ai #saas #growth"))
    just_enough = topic(post(1, hooks=("A real hook",),
                             caption="Everything changed today. #ai #saas #growth"))

    assert copywrite._caption_substance("Everything changed today #ai #saas #growth") == 24
    assert copywrite._caption_substance("Everything changed today. #ai #saas #growth") == 25
    assert copywrite._caption_substance("#ai #saas #growth") == 0, "tags alone measure nothing"
    assert copywrite._CAPTION_MIN_CHARS == 25

    log = Recorder()
    spam = await write([entry()], ScriptedCall({"a1": [refs(caption_ref="P1.caption")]}),
                       trends={"t1": thin}, log=log)
    real = await write([entry()], ScriptedCall({"a1": [refs(caption_ref="P1.caption")]}),
                       trends={"t1": just_enough})

    assert spam.copy["a1"].caption == "A real hook — from a post trending this week", (
        "the bound post's own best line plus a neutral attribution, never the niche descriptor")
    assert NICHE not in spam.copy["a1"].caption
    assert spam.copy["a1"].hashtags == [], "we did not adopt the tag dump either"
    assert spam.provenance["a1"].refs == {}, "our own words claim no provenance"
    assert log.warned("copy_caption_unavailable")
    assert "25 non-hashtag characters" in log.warned("copy_caption_unavailable")[0]
    assert real.copy["a1"].caption == "Everything changed today."
    assert real.copy["a1"].hashtags == ["#ai", "#saas", "#growth"]


async def test_the_substance_floor_applies_to_the_no_call_tier_too() -> None:
    """The degrade tier is the one path with no model in it to screen anything, so a hashtag-spam
    caption would otherwise ship there unchallenged — on the very path where nobody chose it.
    Under the floor it falls through to FR-99's own "minimal assembled caption"."""
    source = topic(post(1, views=900, caption="Wild results  #ai #saas #growth #startup"))

    result = await write([entry()], DeadCall(), trends={"t1": source})

    assert result.copy["a1"].caption == "AI tool stacks", (
        "the no-model tier assembles the topic name and its slug tags — nothing of ours besides")
    assert NICHE not in result.copy["a1"].caption
    assert result.provenance["a1"].refs == {} and result.provenance["a1"].post_id == ""
    assert set(result.tags["a1"]) == {DegradationTag.COPY_DEGRADED,
                                      DegradationTag.NO_ONIMAGE_TEXT}


def test_an_emoji_handle_url_or_hashtag_string_is_never_offered_as_on_image_text() -> None:
    """F23's four exclusions, at the table rather than at the regex: a string that fails any of
    them can never be an on-image candidate whatever its length, while captions keep all four."""
    source = topic(post(1, hooks=("Growth 🚀 unlocked", "Ask @someone about it",
                                  "Read more at example.com", "Wins big #ai", "A clean hook"),
                        caption=EMOJI_CAPTION))

    offer = _offer(entry(), source)

    assert [c.label for c in offer.onimage] == ["P1.hook.5"]
    assert offer.onimage[0].text == "A clean hook"
    assert [c.label for c in offer.captions] == ["P1.caption"], "the emoji caption still ships"
    assert "🚀" in offer.captions[0].text


def test_0_14b_a_panel_keeps_its_emoji_hashtag_and_line_break_for_the_slide_slot_alone() -> None:
    """D46 §0.14b's ONE relaxation, and the exact width of it.

    A source panel's emoji is typography: that string was already on a slide, in a deck people
    watched to the end, and our slide *i* IS their slide *i* (FR-304). Holding it to F23 would ship
    a panel-mapped deck with a wordless slide wherever the creator used an emoji, a hashtag or a
    second line — which is most decks. So those three are allowed for a `panel` filling the `slide`
    slot, and nowhere else: the same panel offered as a HEADLINE is our frame's own line and is
    held to the full rule.
    """
    source = topic(post(1, panels=("Growth 🚀 unlocked", "Wins big #ai", "Two lines\nof panel"),
                        hooks=("Growth 🚀 unlocked",),
                        caption="A caption long enough to be a caption at all."))

    deck = _offer(entry("d1", 0, creative_format="carousel", slide_count=3, source_post_id="p1"),
                  source)

    panels = {candidate.label: candidate for candidate in deck.onimage
              if candidate.kind == "panel"}
    assert sorted(panels) == ["P1.panel.1", "P1.panel.2", "P1.panel.3"]
    assert all(candidate.slots == ("slide",) for candidate in panels.values()), \
        "allowed for the slide it came from, never promoted into the headline"
    assert panels["P1.panel.1"].text == "Growth 🚀 unlocked", "the bytes are the source's own"
    # The identical string, offered as a HOOK, is held to the full F23 rule and reaches no slot.
    assert all(candidate.kind != "hook" for candidate in deck.onimage)


async def test_0_14b_a_panel_carrying_a_handle_or_a_url_is_excluded_like_every_other_kind() -> None:
    """The two exclusions §0.14b does NOT relax, and what they cost when they bite.

    An `@handle` renders as somebody else's identity inside our frame and a URL invites a
    hallucinated hyperlink — neither is typography, and neither becomes acceptable because a
    creator put it on a slide. The slide keeps its POSITION and renders wordless (FR-304's
    "unusable" branch), so the rest of the deck still lines up against the source.
    """
    source = topic(post(1, panels=("Ask @someone about it", "A perfectly ordinary panel",
                                   "Read more at example.com"),
                        caption="A caption long enough to be a caption at all."))
    call = ScriptedCall({"d1": [refs(caption_ref="P1.caption")]})

    result = await write(
        [entry("d1", 0, creative_format="carousel", slide_count=3, source_post_id="p1")],
        call, trends={"t1": source},
        styles={STYLE_KEY: style(max_onimage_chars={"headline": 90, "subline": 60, "slide": 300})})

    assert result.copy["d1"].slide_texts == ["", "A perfectly ordinary panel", ""]
    assert result.provenance["d1"].refs == {"slide_2": "P1.panel.2", "caption": "P1.caption"}
    assert [row["source_text"] for row in result.provenance["d1"].panel_map] == [
        "", "A perfectly ordinary panel", ""]
    assert [row["source_position"] for row in result.provenance["d1"].panel_map] == [1, 2, 3], \
        "an unusable panel keeps its slot; nothing slides up"


def test_a_captions_trailing_hashtags_are_never_offered_inside_the_frame() -> None:
    """The peeled tags travel in `hashtags[]` for the publisher; the caption BODY is what a
    headline could quote, and the untouched string carrying the tags is refused outright."""
    source = topic(post(1, caption="A caption body long enough to be one #ai #saas"))

    offer = _offer(entry(), source)

    assert offer.onimage == [], "the raw caption carries hashtags, so no slot may hold it"
    assert offer.captions[0].text == "A caption body long enough to be one"
    assert offer.captions[0].hashtags == ("#ai", "#saas")


# ----------------------------------------- §1.5 layer 3: the SOURCE CREATOR's own name (FR-312)
#
# The regression that bought this section: run 20260813_161444_r9pz shipped eight rendered slides
# whose first line was "EMIR AI LAB" — the display form of the source creator's handle,
# `emirailab`, which their deck carried as a brand header on every panel. The verbatim contract
# worked exactly as designed and put another account's name on our creative. Layers 1 and 2 could
# not see it (it is not a competitor and no filter proposed it), the @handle/URL backstop could
# not see it (it is neither) and no budget could see it (it is eleven characters).
#
# Layer 3 is unguarded and fail-closed like layer 1, and its unit is the LINE rather than the word:
# a line whose collapsed form EQUALS an identifier is dropped whole, and everything else on the
# panel ships byte for byte. Two things are pinned below and neither is an accident — a legitimate
# short line that collapses onto the handle is dropped too (`test_..._fail_closed_...`), and a line
# that merely CONTAINS an identifier is never touched.

#: The audited creator, in the two forms the run carried: the handle Virlo returned as `author`,
#: and the display form their own slides were headed with.
CREATOR_HANDLE = "@emirailab"
CREATOR_HEADER = "EMIR AI LAB"


def creator_deck(*panels: str, author: str = CREATOR_HANDLE, caption: str = "") -> TrendItem:
    """One bound slideshow post by `author`, its panels exactly as given."""
    return topic(post(1, author=author, panels=panels,
                      caption=caption or "A caption long enough to be a caption at all."))


def deck(asset_id: str = "d1", slides: int = 2) -> PlanEntry:
    return entry(asset_id, 0, creative_format="carousel", slide_count=slides, source_post_id="p1")


async def write_deck(source: TrendItem, *, slides: int = 2, log: Any = None,
                     **overrides: Any) -> copywrite.CopyResult:
    call = ScriptedCall({"d1": [refs(caption_ref="P1.caption")]})
    return await write([deck(slides=slides)], call, trends={"t1": source}, log=log,
                       styles={STYLE_KEY: style(max_onimage_chars={"headline": 90, "subline": 60,
                                                                   "slide": 300})},
                       **overrides)


def test_the_collapse_is_what_makes_a_handle_and_a_brand_header_one_string() -> None:
    """The whole matcher in four lines. Case, spaces, punctuation and glyphs go; letters and
    digits stay, including accented ones — a Czech line must collapse to its own letters rather
    than to a mangled ASCII skeleton that could collide with an unrelated identifier."""
    assert copywrite._collapse(CREATOR_HEADER) == "emirailab" == copywrite._collapse("@emirailab")
    assert copywrite._collapse("Emir | AI Lab ") == "emirailab"
    assert copywrite._collapse("SWIPE ❮❮") == "swipe" == copywrite._collapse("SWIPE <<")
    assert copywrite._collapse("Rychlejší růst") == "rychlejšírůst", "no accent is folded away"


def test_layer_3_drops_a_line_that_IS_the_identifier_and_never_one_that_merely_contains_it(
) -> None:
    """Equality, not substring — the single decision that keeps this safe to run unguarded over
    every candidate on every post. A substring rule would shred "The AI lab nobody talks about"
    the moment a creator called themselves `ailab`, and the verbatim contract with it."""
    identifiers = {"emirailab": "author"}

    assert copywrite._strip_creator_lines(CREATOR_HEADER, identifiers) == ("", True)
    assert copywrite._strip_creator_lines(f"{CREATOR_HEADER}\nReal words", identifiers) == (
        "Real words", True)
    assert copywrite._strip_creator_lines("Why EMIR AI LAB does this", identifiers) == (
        "Why EMIR AI LAB does this", False), "a line that CONTAINS the name is not this rule's"
    assert copywrite._strip_creator_lines("Real words", identifiers) == ("Real words", False)
    assert copywrite._strip_creator_lines("Real words", {}) == ("Real words", False)


async def test_the_creators_brand_header_is_dropped_and_the_rest_ships_byte_for_byte() -> None:
    """(a) The audited failure, and the fix in one assertion: the header line goes, everything
    below it is the source's own bytes. Dropping — not substituting — is the operator's ruling:
    there is no replacement string that would be honest, and a blank where their brand was is what
    a re-render of somebody else's slide should look like."""
    log = Recorder()
    source = creator_deck(f"{CREATOR_HEADER}\nThe 5 tools that replaced my team",
                          f"{CREATOR_HEADER}\nNumber 3 costs nothing at all")

    result = await write_deck(source, log=log)

    assert result.copy["d1"].slide_texts == ["The 5 tools that replaced my team",
                                             "Number 3 costs nothing at all"]
    assert CREATOR_HEADER not in shipped_strings(result.copy["d1"])
    assert all(text in source.posts[0].panel_texts[index]
               for index, text in enumerate(result.copy["d1"].slide_texts)), \
        "what survives is a byte-substring of the panel it came from — nothing was rewritten"
    warnings = log.warned("panel_creator_line_stripped")
    assert len(warnings) == 1, "one event per creative, however many lines it names"
    assert "'EMIR AI LAB' == the author identifier 'emirailab'" in warnings[0]


async def test_a_panel_that_names_nobody_is_returned_untouched() -> None:
    """(c) The control, and the one that matters most: layer 3 is a scalpel, and the overwhelming
    majority of panels must come out of it as the same object they went in as. If this test ever
    fails, the verbatim contract has been broken for every deck we render."""
    log = Recorder()
    source = creator_deck("The 5 tools that replaced my team",
                          "Number 3 costs nothing at all")

    result = await write_deck(source, log=log)

    assert result.copy["d1"].slide_texts == list(source.posts[0].panel_texts)
    assert [row["source_text_original"] for row in result.provenance["d1"].panel_map] == \
        list(source.posts[0].panel_texts)
    assert not any(row["creator_stripped"] for row in result.provenance["d1"].panel_map)
    assert not log.warned("panel_creator_line_stripped"), "nothing was taken, nothing is warned"


async def test_a_short_legitimate_line_that_collapses_onto_the_handle_is_dropped_too() -> None:
    """(b) FAIL-CLOSED, pinned deliberately. "AI LAB" is a perfectly good slide line, and against
    the handle `ailab` it collapses to the same nine characters and goes. That is the trade the
    operator chose (D-C): between one lost slide line and one creative signed with somebody else's
    brand, the line loses. Anyone tempted to "fix" this by adding a guard is looking at the exact
    behaviour the run 20260813_161444_r9pz audit asked for — change the PRD first (FR-312)."""
    log = Recorder()
    source = creator_deck("AI LAB\nWhat we build here", "A second panel with real words",
                          author="ailab")

    result = await write_deck(source, log=log)

    assert result.copy["d1"].slide_texts == ["What we build here",
                                             "A second panel with real words"]
    assert "'AI LAB' == the author identifier 'ailab'" in \
        log.warned("panel_creator_line_stripped")[0]


async def test_a_two_character_identifier_never_strips_anything() -> None:
    """(h) The floor. Two characters is an initialism, a page counter or a particle, and an
    identifier that short would blank panels for a living — so it is discarded before it can
    match, and the line it would have taken ships whole."""
    log = Recorder()
    source = creator_deck("AB\nThe real words of the panel", "A second panel with real words",
                          author="ab")

    result = await write_deck(source, log=log)

    assert copywrite._CREATOR_MIN_CHARS == 3
    assert copywrite._creator_identifiers(source.posts[0]) == {}, "nothing qualified"
    assert result.copy["d1"].slide_texts == ["AB\nThe real words of the panel",
                                             "A second panel with real words"]
    assert not log.warnings


async def test_a_panel_line_that_echoes_the_decks_chrome_is_dropped_as_well() -> None:
    """(d) The second identifier channel. FR-306 transcribes watermarks, counters and swipe cues
    into `chrome_text`, apart from the slide's words — but Virlo's own `panel_texts` carry the same
    cue on `virlo_text`, so "SWIPE ❮❮" reaches the deck through the front door. It is the creator's
    furniture, it tells our reader to swipe on a deck whose slides do not swipe that way, and the
    collapse makes their glyphs and ours the same cue.

    The PAGE COUNTER on panel 2 is the second half, renegotiated in Session 5.5 (F2). Layer 3
    cannot take it and never could — "1/8" collapses to two characters, below `_CREATOR_MIN_CHARS`
    — and until F2 that was the end of the story: the badge shipped as our slide's words, reached
    `panel_map.source_text`, became a line of the gauntlet's frame contract and BLOCKED the deck
    for `missing_text` because the renderer had rightly not drawn the source's page number. The
    shape strip at admission takes it now, on its own flag, and the identifier assertion below
    stays exactly as it was — it is the reason a second mechanism had to exist.
    """
    log = Recorder()
    source = creator_deck("SWIPE <<\nHere is the real content of slide one",
                          "1/8\nA second panel with real words")

    result = await write_deck(source, log=log, chrome_lines={"p1": ["SWIPE ❮❮", "1/8"]})

    assert result.copy["d1"].slide_texts == ["Here is the real content of slide one",
                                             "A second panel with real words"]
    warning = log.warned("panel_creator_line_stripped")[0]
    assert "'SWIPE <<' == the chrome identifier 'swipe'" in warning
    rows = result.provenance["d1"].panel_map
    assert rows[1]["chrome_counter_stripped"] is True, "its own flag, never creator_stripped"
    assert rows[1]["creator_stripped"] is False, "a page number is nobody's brand"
    assert rows[1]["source_text_original"] == "1/8\nA second panel with real words", \
        "provenance keeps the counter — the original bytes are never rewritten"
    assert "'1/8'" in log.warned("panel_counter_stripped")[0]
    assert copywrite._creator_identifiers(source.posts[0], ["1/8", ""]) == {
        "emirailab": "author"}, \
        "a page counter collapses to two characters and an empty chrome field to none — neither " \
        "becomes an identifier, so layer 3 is not what removes it"


async def test_f2_the_counter_strip_leaves_the_map_the_prompt_and_the_verifier_holding_one_string(
) -> None:
    """F2's byte-consistency invariant, and why the strip sits ABOVE both writes.

    `_offer_for` writes the admitted panel into two places at once: `kept[]`, which becomes
    `offer.panels` and from there `panel_map.source_text` and the render prompt's locked TEXT
    block, and `haystack`, which becomes the FR-100/101 verifier's pool of quotable bytes. A strip
    applied to one of that pair and not the other is how a run false-flags its own correct
    behaviour: the shipped string stops being a byte-substring of anything the creative was
    entitled to quote, and the audit tags an otherwise perfect deck `copy_not_verbatim`.

    Observable through the public surface exactly as an operator would read it: the `CopySet` this
    deck renders, the provenance rows `meta.yaml` carries and the audit's own verdict all describe
    the same bytes, and the label each slide resolved through is the panel's own.
    """
    log = Recorder()
    czech = "Sedm nástrojů, které používá každý"
    source = creator_deck(f"01 / 06\n{czech}", "02 / 06\nA second panel with real words")

    result = await write_deck(source, log=log)

    copyset, provenance = result.copy["d1"], result.provenance["d1"]
    rows = provenance.panel_map
    assert copyset.slide_texts == [czech, "A second panel with real words"]
    assert copyset.slide_texts == [row["source_text"] for row in rows], \
        "the panel map and the rendered words are one string, not two spellings of one"
    assert [provenance.refs[f"slide_{n}"] for n in (1, 2)] == [row["ref_label"] for row in rows]
    assert rows[0]["source_text_original"] == f"01 / 06\n{czech}", \
        "provenance keeps the counter: it records what the source said, not what we admitted"
    assert not log.warned("copy_not_verbatim"), \
        "the verifier's pool was stripped with the panels, so nothing looks retyped"
    assert DegradationTag.COPY_NOT_VERBATIM not in result.tags.get("d1", ())
    assert "01 / 06" not in shipped_strings(copyset), "no badge of theirs becomes pixels of ours"


async def test_f2_a_panel_that_was_ONLY_a_page_counter_renders_wordless_in_its_own_position(
) -> None:
    """F2 joined to FR-304's alignment rule, and to the tag it must NOT earn.

    A panel whose every line was chrome goes to "" and KEEPS ITS ROW — the row is the alignment,
    and closing the gap would tell the gallery our slide 2 renders their slide 3. The flag on that
    row is `chrome_counter_stripped` and deliberately not `creator_stripped`: the latter tags the
    creative `competitor_stripped`, which is a claim that somebody's BRAND was removed from it. A
    page number is nobody's brand, and a deck labelled that way for losing one would have an
    operator hunting a competitor that was never there.
    """
    log = Recorder()
    source = creator_deck("01 / 06", "The second panel, with real words",
                          "A third panel, also real")

    result = await write_deck(source, slides=3, log=log)

    rows = result.provenance["d1"].panel_map
    assert result.copy["d1"].slide_texts == ["", "The second panel, with real words",
                                             "A third panel, also real"]
    assert [row["source_position"] for row in rows] == [1, 2, 3], "nothing slid up"
    assert rows[0]["source_text"] == "" and rows[0]["source_text_original"] == "01 / 06"
    assert rows[0]["drop_reason"] == "empty", "the strip emptied it; the verdict is honest"
    assert rows[0]["chrome_counter_stripped"] is True
    assert rows[0]["creator_stripped"] is False, "a page number is nobody's brand"
    assert DegradationTag.COMPETITOR_STRIPPED not in result.tags.get("d1", ())
    assert "slide_1" not in result.provenance["d1"].refs, "a wordless slide quotes nothing"
    assert "'01 / 06'" in log.warned("panel_counter_stripped")[0]
    assert not log.warned("panel_creator_line_stripped"), "layer 3 is not what removed it"


async def test_a_panel_that_was_ONLY_the_creators_name_renders_wordless_in_its_own_position(
) -> None:
    """(e) The empty case, joined to FR-304's alignment rule. A panel whose every line was the
    creator's goes to "", the slide renders without text and it KEEPS ITS ROW — the row is the
    alignment, and closing the gap would tell the gallery our slide 2 renders their slide 3."""
    source = creator_deck(CREATOR_HEADER, "The second panel, with real words",
                          "A third panel, also real")

    result = await write_deck(source, slides=3)

    assert result.copy["d1"].slide_texts == ["", "The second panel, with real words",
                                             "A third panel, also real"]
    rows = result.provenance["d1"].panel_map
    assert [row["source_position"] for row in rows] == [1, 2, 3], "nothing slid up"
    assert rows[0]["drop_reason"] == "empty", "the strip emptied it; the verdict is honest"
    assert rows[0]["source_text"] == "" and rows[0]["source_text_original"] == CREATOR_HEADER
    assert "slide_1" not in result.provenance["d1"].refs


async def test_the_panel_map_row_says_creator_stripped_and_keeps_the_pre_strip_panel() -> None:
    """(f) The receipt. `source_text` is what SHIPPED, `source_text_original` is the panel as it
    reached layer 3, and `creator_stripped` is the flag that explains the difference — the one row
    fact that can be true on a slide which rendered perfectly well. Without the pair, an operator
    reading meta.yaml could not tell a panel we edited from a panel the source wrote that way."""
    original = f"{CREATOR_HEADER}\nThe 5 tools that replaced my team"
    source = creator_deck(original, "A second panel with real words")

    rows = (await write_deck(source)).provenance["d1"].panel_map

    assert rows[0]["source_text"] == "The 5 tools that replaced my team"
    assert rows[0]["source_text_original"] == original, "pre-strip, so the loss is visible"
    assert rows[0]["creator_stripped"] is True
    assert rows[0]["drop_reason"] == "", "the slide shipped — this is not a drop"
    assert rows[1] == {"slide": 2, "source_position": 2,
                       "source_text": "A second panel with real words",
                       "source_text_original": "A second panel with real words",
                       "ref_label": "P1.panel.2", "drop_reason": "", "creator_stripped": False,
                       # F2 (Session 5.5): the seventh key, and the reason it is not the sixth —
                       # a page counter is chrome, not a creator's name, so it never rides
                       # `creator_stripped` into a `competitor_stripped` tag. This panel had none.
                       "chrome_counter_stripped": False,
                       # FR-304c (v2.2.0): the eighth key. A panel that reads as finished is not
                       # a suspect, and a suspect would still have shipped in full.
                       "truncation_suspect": False,
                       # D54 (v2.3.0): the ninth. This deck was written in verbatim mode, where
                       # the walk quotes and never compresses, so the key is False by
                       # construction — but it is WRITTEN, because both walks emit one row
                       # schema and the FR-73 reader may never have to ask which one it got.
                       "compressed": False,
                       # D63 (v2.7.0): the tenth, on exactly the same terms. This run kept its
                       # source language (the engine default), so nothing on any row is a
                       # translation — and the key is still written, because one row schema
                       # always is the contract every reader of `panel_map` relies on.
                       "translated": False,
                       # D65 (v2.9.0, FR-362): the eleventh and twelfth, from the contract guards.
                       # This panel's own creator line was taken at admission by layer 3 (the row
                       # above says so); THIS row named nobody and was nobody's wordmark, so both
                       # guard flags are False — and written, like every other key here.
                       "identity_scrubbed": False, "chrome_watermark_stripped": False}


async def test_the_caption_loses_the_creators_name_at_word_boundaries() -> None:
    """(g) The caption is prose, so the whole-line rule barely touches it — "Follow EMIR AI LAB for
    more AI tool picks" is one line and most of it is legitimate. Its half of layer 3 is the
    word-boundary mechanic layers 1 and 2 already own, over the AUTHOR terms alone: the handle, and
    the DISPLAY form found on the deck (the handle by itself would never match three spaced words).

    A chrome cue is deliberately NOT a caption term: "swipe" is an ordinary word in a sentence, and
    a caption is not pixels.
    """
    source = creator_deck(f"{CREATOR_HEADER}\nThe 5 tools that replaced my team",
                          "Swipe through the whole list to see them",
                          caption="Follow EMIR AI LAB for more AI tool picks")

    result = await write_deck(source, chrome_lines={"p1": ["SWIPE ❮❮"]})

    copyset = result.copy["d1"]
    assert copyset.caption == "Follow for more AI tool picks"
    assert CREATOR_HEADER not in shipped_strings(copyset)
    assert "emirailab" not in shipped_strings(copyset).casefold()
    assert copyset.slide_texts[1] == "Swipe through the whole list to see them", \
        "a chrome cue is not a caption term and not a substring rule — the sentence survives"


# ------------------------------ FR-319: the social / technical split on the verbatim path (D48)
#
# Before v2.1.3 both gates asked "is there a URL here" and blanked the panel if there was. On a
# developer-tooling deck that is most of the deck: `github.com/user/repo` IS the slide's content,
# and a shell line quoting `pypi.org` is the point of the panel. The question changed to "does this
# text point at somebody's IDENTITY or funnel", and the answer is fail-closed twice over — an
# allowlisted technical host renders byte-verbatim, every other host drops, and a line carrying
# BOTH a handle and a technical URL is social and drops (the PRD's own tie-break).


@pytest.mark.parametrize(
    ("text", "social"),
    [
        # Technical CONTENT — rendered as the source wrote it. Matched by registrable SUFFIX, so
        # a `gist.` sub-domain resolves through its parent, and by first LABEL, so every vendor's
        # `docs.`/`api.`/`developer.` reference site is covered without enumerating vendors.
        ("Clone it from github.com/acme/toolkit", False),
        ("The whole thing is in gist.github.com/acme/1234", False),
        ("Straight out of docs.python.org/3/library/asyncio.html", False),
        ("POST to api.stripe.com/v1/charges", False),
        ("It has been on pypi.org since March", False),
        ("Plain words, no link, no handle — the case that is nearly every string", False),
        # Social marks — dropped, the slide keeps its POSITION and ships wordless (FR-304).
        ("Ask @creator about it", True),
        ("Follow instagram.com/creator", True),
        ("Everything is in skool.com/creator", True),
        ("All my links at linktr.ee/creator", True),
        ("Come argue with me at discord.gg/abcd", True),
        ("Full breakdown: youtu.be/dQw4w9WgXcQ", True),
        # An unknown marketing domain is social by construction: the allowlist is an ALLOWLIST,
        # and it is easier to add `crates.io` the day a Rust deck needs it than to explain a
        # creative that shipped a stranger's funnel because a domain looked harmless.
        ("Read more at example.com", True),
        # The tie-break, stated in the PRD and pinned here: a handle is tested first and no
        # technical host in the same line redeems it.
        ("Clone github.com/acme/toolkit and ping @creator", True),
    ])
def test_fr319_a_handle_or_an_unplaceable_host_is_social_and_a_technical_url_is_content(
    text: str, social: bool,
) -> None:
    """The ONE gate both callers ask (`_fitting_slots` for offers, the panel map for mapped decks).

    The asymmetry of the two errors is what sets the default. Dropping a technical URL costs a
    developer deck its actual content — 21 of 41 panels in run `20260813_143420_oyo4` went wordless
    for exactly this reason — while keeping an unplaceable one ships somebody else's funnel inside
    a frame the operator paid for. So content wins on the hosts we can place, and everything else
    still drops.
    """
    assert copywrite._social_mark(text) is social


async def test_fr319_a_panel_that_is_a_technical_url_renders_verbatim_in_its_own_slot(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """End to end on the path that spends money: the panel keeps its text, its row and its label.

    `drop_reason` is the receipt — an empty one is the claim "nothing was taken from this slide",
    and it is what distinguishes a panel we rendered as written from one we blanked. The social
    sibling beside it must still drop, or the split is not a split.
    """
    source = creator_deck("Clone it from github.com/acme/toolkit",
                          "All my links at linktr.ee/creator",
                          author="@someoneelse")

    result = await write_deck(source)

    copyset = result.copy["d1"]
    assert copyset.slide_texts == ["Clone it from github.com/acme/toolkit", ""]
    rows = result.provenance["d1"].panel_map
    assert rows[0]["drop_reason"] == "", "a technical URL is content, not a drop"
    assert rows[0]["source_text"] == "Clone it from github.com/acme/toolkit"
    assert [row["source_position"] for row in rows] == [1, 2], "the social panel kept its row"
    assert rows[1]["source_text"] == "" and rows[1]["drop_reason"]


# ------------------------------- FR-312 layer 3b: the fuzzy CAPTION strip (v2.1.3, captions only)
#
# Layer 3a removes the author's name at WORD BOUNDARIES, which needs the caption to spell the
# handle the way the handle is spelled. Run 20260813 shipped a caption saying "ScaleWithOma" over
# an author whose handle is `@scalewithomaa` — one dropped character, invisible to a whole-term
# regex. Similarity can see it (0.96), and a caption is the one place in this codebase where a
# near miss may be removed, because nothing in a caption becomes pixels.

#: The audited pair: the handle Virlo returned, and the near-miss the caption was written with.
FUZZY_HANDLE = "@scalewithomaa"
FUZZY_NEAR_MISS = "ScaleWithOma"


async def test_fr312_a_caption_naming_a_near_miss_of_the_handle_loses_it_and_says_the_ratio() -> None:
    """The audited defect, and the receipt that makes the judgement auditable.

    A fuzzy strip is the one removal in this codebase of a string that is not byte-equal to
    anything we were given, so it is warned INDIVIDUALLY with the token, the identifier it matched
    and the measured similarity: "ScaleWithOma ≈ scalewithomaa at 0.96" is a finding the operator
    can check, "the caption was cleaned" is not.
    """
    log = Recorder()
    source = creator_deck("A first panel with real words", "A second panel with real words",
                          author=FUZZY_HANDLE,
                          caption=f"Built by {FUZZY_NEAR_MISS} for the community")

    result = await write_deck(source, log=log)

    assert result.copy["d1"].caption == "Built by for the community"
    warnings = log.warned("caption_creator_fuzzy_stripped")
    assert len(warnings) == 1, "one line per removed token, not one per caption"
    assert f"{FUZZY_NEAR_MISS!r} was removed" in warnings[0]
    assert "0.96 similarity" in warnings[0] and "0.85 threshold" in warnings[0]
    data = next(fields for name, _, fields in log.warnings
                if name == "caption_creator_fuzzy_stripped")
    assert data["token"] == FUZZY_NEAR_MISS, "the token AS WRITTEN, so the operator can find it"
    assert data["identifier"] == FUZZY_HANDLE.lstrip("@"), "the author term it was judged against"
    assert data["ratio"] == pytest.approx(0.96, abs=0.01)


@pytest.mark.parametrize("word", ["community", "scale", "with", "confidence", "companies"])
async def test_fr312_an_ordinary_word_that_shares_letters_with_the_handle_survives(
    word: str,
) -> None:
    """The 0.85 threshold, from the other side. "community" scores 0.27 against `scalewithomaa`
    and "scale" scores 0.56 — the caption's own vocabulary, and a strip that ate any of it would
    be rewriting the source's prose rather than removing its signature.

    Pinned word by word because a threshold lowered "just a little" to catch one more spelling is
    exactly how a similarity score starts editing captions.
    """
    log = Recorder()
    caption = f"A caption about {word} that runs long enough to be a real caption"
    source = creator_deck("A first panel with real words", "A second panel with real words",
                          author=FUZZY_HANDLE, caption=caption)

    result = await write_deck(source, log=log)

    assert result.copy["d1"].caption == caption, "byte-identical — nothing was judged"
    assert not log.warned("caption_creator_fuzzy_stripped")


async def test_fr312_a_caption_that_names_nobody_comes_back_byte_identical() -> None:
    """The control, and the one that matters most: the overwhelming majority of captions must come
    out of layer 3b as the same string they went in as. If this ever fails, every caption the tool
    ships has been quietly rewritten."""
    caption = "Seven tools, four workflows, and the one nobody sets up correctly"
    source = creator_deck("A first panel with real words", "A second panel with real words",
                          author=FUZZY_HANDLE, caption=caption)

    result = await write_deck(source)

    assert result.copy["d1"].caption == caption


async def test_fr312_a_panel_is_never_fuzzied_however_close_it_reads_to_the_author() -> None:
    """The asymmetry between captions and panels IS the design (PRD FR-312, v2.1.3).

    A panel becomes PIXELS, so it is held to full-line collapse-EQUALITY and nothing looser: put a
    similarity score in charge of slide text and it eventually eats a word the creator meant, on a
    creative nobody re-reads before it ships. `ScaleWithOma` collapses to `scalewithoma`, which is
    not `scalewithomaa`, so the panel stands — while the identical string in the caption beside it
    goes. Both halves are asserted in one run, because the point is that they DIFFER.
    """
    log = Recorder()
    source = creator_deck(FUZZY_NEAR_MISS, f"{FUZZY_NEAR_MISS}\nThe five tools I actually use",
                          author=FUZZY_HANDLE,
                          caption=f"More from {FUZZY_NEAR_MISS} every single week, no exceptions")

    result = await write_deck(source, log=log)

    assert result.copy["d1"].slide_texts == [
        FUZZY_NEAR_MISS, f"{FUZZY_NEAR_MISS}\nThe five tools I actually use"], \
        "a near miss is not the identifier; the panel keeps its own bytes"
    assert not log.warned("panel_creator_line_stripped")
    assert result.copy["d1"].caption == "More from every single week, no exceptions", \
        "the caption half of the same layer still fires on the same string"
    assert len(log.warned("caption_creator_fuzzy_stripped")) == 1


# ------------------------------------------- the barrier at the level that actually spends money
#
# Everything above asserts on a `CopySet`. That is the object, not the risk. The risk is the
# finished string handed to the image model, and between the two sits `build_context`, which
# assembles `{{trend_texts}}`, `{{render_prompt}}` and the deterministic content sentence from the
# TOPIC — channels the copy object never touches. So the barrier is re-asserted at the assembled
# prompt, for every render role a creative can reach, with the topic's own texts full of the brand.


def render_prompts(copyset: CopySet, source: TrendItem, *, slide_count: int = 0,
                   competitors: tuple[str, ...] = ()) -> dict[str, str]:
    """Every role this copy set can reach, assembled the way `generate` assembles it.

    `image_post.md` is the merged single-post role (F16), `carousel_slide.md` runs once per slide,
    `reel_seed_frame.md` is the reel's hook frame and `reel_director.md` is the clip itself — the
    one role that carries the copy but refuses the branding block (§1.4/M13).
    """
    engine = PromptEngine()
    shared: dict[str, Any] = {
        "trend": source, "style": style(), "copy": copyset, "text_budgets": TextBudgets(),
        "reference_roles": ['Image 1 — house style reference "flat-card": layout only'],
        "niche_descriptor": NICHE,
        "niche_visual_world": "dark UI and dashboard screenshots on near-black",
        "competitor_strings": competitors,
    }
    out = {
        "image_post.md": engine.render(
            "image_post.md", build_context(creative_format="image", **shared),
            profile=RENDER_PROFILE),
        "reel_seed_frame.md": engine.render(
            "reel_seed_frame.md", build_context(creative_format="reel", **shared),
            profile=RENDER_PROFILE),
        "reel_director.md": engine.render(
            "reel_director.md",
            build_context(creative_format="reel", seed_frame_ref="@Image1 is the seed frame",
                          audio_cue="silent", **shared),
            profile="seedance-2-5"),
    }
    for index in range(1, slide_count + 1):
        slides = copyset.slide_texts
        out[f"carousel_slide.md #{index}"] = engine.render(
            "carousel_slide.md",
            build_context(creative_format="carousel", slide_index=f"{index} of {slide_count}",
                          slide_text=slides[index - 1] if index <= len(slides) else "", **shared),
            profile=RENDER_PROFILE)
    return out


async def test_a_healthy_copy_set_really_does_reach_the_render_prompt() -> None:
    """The control. Without it every assertion below could pass on a prompt builder that dropped
    the on-image text entirely, and the barrier would be measuring nothing.

    Two writes, because a creative is offered only the slots ITS format renders: a carousel has no
    overlay slot and a reel has no slides, so one `CopySet` cannot legitimately carry both.
    """
    source = topic(post(1, hooks=(CZECH_HOOK,), panels=("Slide one line", "Slide two line"),
                        overlays=("Trace one flow",), caption="A caption."))
    deck_call = ScriptedCall({"a1": [refs(headline_ref="P1.hook.1",
                                          slide_refs=["P1.panel.1", "P1.panel.2"],
                                          caption_ref="P1.caption")]})
    clip_call = ScriptedCall({"a2": [refs(overlay_ref="P1.overlay.1", caption_ref="P1.caption")]})
    deck = await write([entry("a1", 0, creative_format="carousel", slide_count=2)], deck_call,
                       trends={"t1": source})
    clip = await write([entry("a2", 0, creative_format="reel", aspect_ratio="9:16")], clip_call,
                       trends={"t1": source})

    prompts = render_prompts(deck.copy["a1"], source, slide_count=2)
    reel_prompts = render_prompts(clip.copy["a2"], source)

    assert f'headline (render verbatim): "{CZECH_HOOK}"' in prompts["image_post.md"]
    assert "R-y-c-h-l-e-j-š-í" in prompts["image_post.md"], "FR-186's diacritics defence"
    assert "Slide one line" in prompts["carousel_slide.md #1"]
    assert "Slide two line" in prompts["carousel_slide.md #2"]
    assert "Trace one flow" in reel_prompts["reel_seed_frame.md"]
    assert "Trace one flow" in reel_prompts["reel_director.md"], "M13: the clip preserves it"
    assert all("{{" not in prompt for prompt in (*prompts.values(), *reel_prompts.values())), \
        "FR-260: no raw placeholder reaches a paid API"


async def test_no_competitor_string_survives_into_any_assembled_render_prompt() -> None:
    """The operator's standing verify-at-the-prompt mandate (M6), and the new predicate this file
    exists for. The topic here is SATURATED with the brand — its name, its hooks, its panels, its
    captions and the summary the content sentence is built from — and the copy call is given the
    same competitor list the render assembly is. Not one of the four roles may carry it.
    """
    source = topic(
        post(1, hooks=(BRAND_HOOK,), panels=(f"{BRAND} panel one", f"{BRAND} panel two"),
             overlays=(f"{BRAND} overlay",), caption=f"{BRAND} changed everything this quarter.",
             description=f"A post about {BRAND} and its pricing page."),
        name=f"{BRAND} pricing changes")
    source.hook_texts = [BRAND_HOOK]
    source.video_descriptions = [f"a creator explains what {BRAND} shipped"]
    call = ScriptedCall({"a1": [refs(headline_ref="P1.hook.1",
                                     slide_refs=["P1.panel.1", "P1.panel.2"],
                                     caption_ref="P1.caption",
                                     through_line=f"why {BRAND} matters")]})
    result = await write([entry("a1", 0, creative_format="carousel", slide_count=2)], call,
                         trends={"t1": source}, competitors=[BRAND])

    prompts = render_prompts(result.copy["a1"], source, slide_count=2, competitors=(BRAND,))

    leaks = [f"{role}: {prompt[max(0, prompt.find(BRAND) - 60):prompt.find(BRAND) + 60]}"
             for role, prompt in prompts.items() if BRAND.casefold() in prompt.casefold()]
    assert leaks == [], "a competitor's name reached a paid render prompt"
    assert BRAND not in shipped_strings(result.copy["a1"])
    # …and the control: the same assembly WITHOUT the strip does carry it, so the assertion above
    # is measuring the strip rather than a topic that never mentioned the brand.
    unfiltered = render_prompts(result.copy["a1"], source, slide_count=2)
    assert any(BRAND.casefold() in prompt.casefold() for prompt in unfiltered.values())


async def test_the_strip_reaches_the_channels_the_copy_object_never_touches() -> None:
    """M6 names five of them — `content_sentence`, `render_prompt`, `trend_texts`, `through_line`
    and `brief_directives`. `trend_texts` and the content sentence are built from the TOPIC after
    copy is finished, so a `CopySet`-level strip alone would leave the brand in the prompt."""
    source = topic(post(1, hooks=(BRAND_HOOK,), caption=f"{BRAND} did it again."),
                   name=f"{BRAND} pricing changes")
    source.hook_texts = [BRAND_HOOK]

    unfiltered = build_context(trend=source, style=style(), creative_format="image")
    filtered = build_context(trend=source, style=style(), creative_format="image",
                             competitor_strings=(BRAND,),
                             content_sentence=f"a post about {BRAND} pricing")

    assert BRAND in unfiltered["trend_texts"], "the control: it really is in there"
    for slot in ("trend_texts", "content_sentence", "render_prompt", "through_line",
                 "brief_directives"):
        assert BRAND.casefold() not in filtered[slot].casefold(), slot


# --------------------------------- FR-312 layer 3c: the CAPTION CTA strip (v2.1.4, captions only)
#
# Layers 1–3b remove NAMES: competitors, the creator's handle, near misses of it. Run
# 20260814_010814_glz0 shipped the thing none of them look for — the creator's FUNNEL, quoted
# verbatim under our brand:
#
#   "Swipe all 7 slides."                              (our deck had five)
#   "Grab the free step-by-step guide via the link in my bio."   (their bio)
#   'Comment "SCALE" and I'll send you the link'                 (their DMs)
#
# Each is an instruction our audience cannot follow. The unit removed is the SENTENCE, for the same
# reason `_scrub_creator` drops a whole sentence: "Grab the free guide via the link in my bio" with
# only the four cue words removed still promises a guide nobody can reach.


@pytest.mark.parametrize(
    ("cue", "pattern"),
    [
        ("Swipe all 7 slides.", "swipe_cue"),
        ("Swipe up for the full breakdown.", "swipe_cue"),
        ("Grab the free step-by-step guide via the link in my bio.", "link_in_bio"),
        ("Everything is linked in bio.", "link_in_bio"),
        ('Comment "SCALE" and I will send you the link.', "comment_keyword"),
        # the 59el miss: the same mechanic with the quotes left off (deck 02's caption shipped it)
        ("Comment CLAUDE and I will send free guide to install them.", "comment_keyword_bare"),
        ("DM me the word AUDIT for the template.", "dm_me"),
        ("Tap the link to get the whole stack.", "tap_the_link"),
    ])
async def test_fr312_a_creators_call_to_action_is_dropped_from_the_caption_sentence_and_all(
    cue: str, pattern: str,
) -> None:
    """One row per pattern, each written the way glz0 (or its near neighbour) actually wrote it.

    The surviving sentence is asserted byte for byte beside the removal, because the promise of a
    sentence-level strip is that it takes ONE sentence: a caption reduced to its first clause is a
    different failure from a caption carrying somebody else's funnel, not a milder one.
    """
    log = Recorder()
    caption = f"Seven tools that replaced my whole stack. {cue}"
    source = creator_deck("A first panel with real words", "A second panel with real words",
                          caption=caption)

    result = await write_deck(source, log=log)

    assert result.copy["d1"].caption == "Seven tools that replaced my whole stack."
    warnings = log.warned("caption_cta_stripped")
    assert len(warnings) == 1, "one line per removed sentence"
    assert cue.rstrip() in warnings[0] and pattern in warnings[0], \
        "the warning quotes the sentence and names the pattern that caught it"


async def test_fr312_a_cue_on_its_own_line_is_a_sentence_too() -> None:
    """Captions are written in lines as often as in sentences, and the commonest shape of all is a
    bare cue on the last line with no terminator: `…\\nLink in bio 👇`.

    Splitting on line breaks as well as on `.!?` is what makes that shape reachable; without it the
    whole caption would be one sentence and the strip would either take everything or nothing.
    """
    log = Recorder()
    source = creator_deck("A first panel with real words", "A second panel with real words",
                          caption="Seven tools that replaced my whole stack\nLink in bio")

    result = await write_deck(source, log=log)

    assert result.copy["d1"].caption == "Seven tools that replaced my whole stack"
    assert len(log.warned("caption_cta_stripped")) == 1


@pytest.mark.parametrize(
    "caption",
    [
        "Follow for more AI tool picks.",
        "The comment section on the original post was full of good ideas.",
        "I swipe left on tools that need a demo call.",
        "We linked our findings in the docs, with the raw numbers beside them.",
        "Tap targets under 44px are the reason this dashboard fails on mobile.",
        "Recruiters read your LinkedIn bio before they read anything else.",
        "Seven tools, four workflows, and the one nobody sets up correctly.",
    ])
async def test_fr312_ordinary_prose_that_merely_sounds_like_a_cue_survives_intact(
    caption: str,
) -> None:
    """The other half, and the one that decides whether this strip is safe to run unguarded.

    Every row here contains a word one of the five patterns is built around — "comment", "swipe",
    "link", "tap", "follow" — used as ordinary English. A caption is prose the operator paid a
    model to choose, so a pattern that eats any of these is worse than the defect it fixes: the
    funnel sentence is visible in a review, a silently shortened caption is not.
    """
    log = Recorder()
    source = creator_deck("A first panel with real words", "A second panel with real words",
                          caption=caption)

    result = await write_deck(source, log=log)

    assert result.copy["d1"].caption == caption, "byte-identical: nothing matched, nothing moved"
    assert not log.warned("caption_cta_stripped")


async def test_fr312_a_caption_with_nothing_to_strip_is_never_even_reflowed() -> None:
    """The control for the reflow: whitespace is only ever collapsed on a caption that WAS edited.

    Removing a sentence out of the middle leaves double spaces behind, so the survivors are
    rejoined — but a caption nobody touched must come back with its own line breaks and spacing
    intact, or every caption this tool ships has been quietly rewritten.
    """
    caption = "Two lines,\nand the second one matters.   Spaced oddly on purpose."
    source = creator_deck("A first panel with real words", "A second panel with real words",
                          caption=caption)

    result = await write_deck(source)

    assert result.copy["d1"].caption == caption


async def test_fr312_the_cta_strip_never_reaches_a_panel_a_hook_or_an_overlay() -> None:
    """Caption-scoped by contract, and this is the assertion that holds it there.

    A panel becomes PIXELS: our slide *i* is a re-rendering of their slide *i* (FR-304), and
    editing one on a judgement about MEANING is how a verbatim deck stops being verbatim. A source
    slide that really did say "Swipe up" renders saying "Swipe up" — the fix for that is the
    chrome split (§0.11), not a caption rule reaching into the frame.
    """
    log = Recorder()
    source = creator_deck("Swipe all 7 slides", "Comment \"SCALE\" for the link",
                          caption="A caption long enough to be a caption at all.")

    result = await write_deck(source, log=log)

    assert result.copy["d1"].slide_texts == ["Swipe all 7 slides",
                                             "Comment \"SCALE\" for the link"]
    assert not log.warned("caption_cta_stripped")


# ------------------------------------- D54/FR-331: the same barrier, on the contract that WRITES
#
# Every sentinel above seeds a competitor into a post and proves the ENGINE never resolves it into
# a creative. Compress mode adds a second door and it is the more dangerous one: the model is
# handed the fenced trend texts and asked to produce bytes, so it can write a brand name into a
# slide the source panel never mentioned. The strip therefore runs on the way OUT as well — layer
# 1 first of `_compress_field`'s three backstops, `_verify`'s blocklist half over what shipped —
# and the substring half self-skips because a compressed line quotes nothing.


def compressed_answer(**overrides: Any) -> dict[str, Any]:
    """One `CopyCompressed` answer — the compress contract's shape (text out, not labels)."""
    payload: dict[str, Any] = {"headline": "", "caption": "", "hashtags": [], "slide_texts": [],
                               "through_line": "", "narrative_arc": ""}
    payload.update(overrides)
    return payload


async def test_d54_a_compressed_deck_ships_quoted_nothing_and_skips_the_substring_audit() -> None:
    """The claim-1 carve-out, asserted rather than assumed.

    `_verify`'s half 1 runs only `if written.quoted`, so a contract that quotes nothing is exempt
    by construction — the same door the free-text override brief has always used. What proves the
    exemption is real is the deck itself: every shipped slide differs from its source panel (that
    is what compression IS), and not one of them is tagged `copy_not_verbatim`. Without the
    carve-out the tag would fire on every creative in the mode and mean nothing thereafter.
    """
    source = creator_deck("A source panel written out at the length a real page carries.",
                          "A second source panel, likewise long enough to be worth shortening.",
                          author="@somebodyelse")
    call = ScriptedCall({"d1": [compressed_answer(
        caption="The tools, in the order that matters.",
        slide_texts=["The first panel, shortened.", "The second panel, shortened."])]})

    result = await write([deck(slides=2)], call, trends={"t1": source},
                        carousel_copy_mode="compress",
                        styles={STYLE_KEY: style(max_onimage_chars={"headline": 90,
                                                                    "slide": 300})})

    copyset, provenance = result.copy["d1"], result.provenance["d1"]
    assert copyset.slide_texts == ["The first panel, shortened.", "The second panel, shortened."]
    assert all(shipped not in source.posts[0].panel_texts for shipped in copyset.slide_texts), \
        "the control: these really are NOT byte-substrings of the panels they came from"
    assert DegradationTag.COPY_NOT_VERBATIM not in result.tags.get("d1", ())
    assert provenance.copy_mode == "compress"
    assert all(row["compressed"] is True for row in provenance.panel_map)
    assert all(row["source_text_original"] and row["source_text"] != row["source_text_original"]
               for row in provenance.panel_map), "the row carries both sides of the compression"


async def test_d54_a_competitor_seeded_into_a_compress_payload_reaches_neither_copy_nor_prompt(
) -> None:
    """The sentinel, re-aimed at the door compress mode opens.

    Here the BRAND is not in the panels at all — it is in the topic name, the fenced trend texts
    and the summary, exactly where a compressing model would read it — and the scripted answer
    writes it into a slide, the headline, the caption and a hashtag, which is the worst case the
    contract allows. §1.5 layer 1 is FAIL-CLOSED and unguarded, so none of the four may survive
    into the `CopySet`, and the assembled render prompts (claim 4, unchanged by the mode) may not
    carry it either. The control at the end proves the assembly WOULD have carried it, so this is
    measuring the strip rather than a topic that never mentioned the brand.
    """
    log = Recorder()
    source = creator_deck("A clean source panel about pricing pages.",
                          "A second clean source panel about onboarding.",
                          author="@somebodyelse")
    source.name = f"{BRAND} pricing changes"
    source.hook_texts = [BRAND_HOOK]
    source.video_descriptions = [f"a creator explains what {BRAND} shipped"]
    call = ScriptedCall({"d1": [compressed_answer(
        headline=f"{BRAND} changed pricing",
        caption=f"{BRAND} changed everything this quarter.",
        hashtags=["#ai", f"#{BRAND.lower()}"],
        slide_texts=[f"{BRAND} raised prices on the pricing page.", "Onboarding, shortened."])]})

    result = await write([deck(slides=2)], call, trends={"t1": source}, log=log,
                        competitors=[BRAND], carousel_copy_mode="compress",
                        styles={STYLE_KEY: style(max_onimage_chars={"headline": 90,
                                                                    "slide": 300})})

    copyset = result.copy["d1"]
    assert BRAND.casefold() not in shipped_strings(copyset).casefold(), \
        "a competitor the MODEL wrote is still a competitor — layer 1 is fail-closed either way"
    assert f"#{BRAND.lower()}" not in copyset.hashtags, "a hashtag is one token, dropped whole"
    assert DegradationTag.COMPETITOR_STRIPPED in result.tags["d1"]
    assert log.warned("competitor_stripped")

    prompts = render_prompts(copyset, source, slide_count=2, competitors=(BRAND,))
    leaks = [role for role, prompt in prompts.items() if BRAND.casefold() in prompt.casefold()]
    assert leaks == [], f"a competitor's name reached a paid render prompt: {leaks}"
    unfiltered = render_prompts(copyset, source, slide_count=2)
    assert any(BRAND.casefold() in prompt.casefold() for prompt in unfiltered.values()), \
        "the control: the same assembly without the strip really does carry it"


async def test_d54_the_blocklist_half_of_the_verifier_still_audits_a_compressed_deck() -> None:
    """Claim 2 is mode-independent, and this is the assertion that says so at the VERIFIER.

    `_verify`'s half 2 reads the `CopySet` rather than the quoted pool, so it cannot be skipped by
    a contract that quotes nothing. Driven directly here — with a `CopySet` that carries the brand
    and an empty quoted pool, the shape `_compressed` produces — because the engine's own strip
    would (correctly) never let such a set exist, and the point is that the audit behind the strip
    is still armed.
    """
    log = Recorder()
    run = copywrite._Run(call=None, engine=PromptEngine(), budgets=TextBudgets(),  # type: ignore[arg-type]
                        styles={STYLE_KEY: style()}, conventions={}, onimage_languages={},
                        niche_descriptor=NICHE, brand_context="", competitors=(BRAND,),
                        strip_brands={}, carousel_copy_mode="compress", log=log)
    written = copywrite._Written(
        copyset=CopySet(asset_id="d1", language="en", trend_key="t1",
                        caption="A caption.", slide_texts=[f"{BRAND} raised prices."]),
        source=copywrite.CopyProvenance(post_id="p1", copy_mode="compress"),
        quoted=())  # the compress shape: nothing claims to be a byte-substring of anything

    tags = copywrite._verify(written, deck(slides=1), run)

    assert DegradationTag.COPY_NOT_VERBATIM in tags, \
        "the blocklist half fires on a compressed string exactly as it does on a quoted one"
    assert log.warnings, "and it is reported, not merely tagged"
