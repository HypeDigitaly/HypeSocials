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

No network: the `llm.structured_call` seam is a stub matching `models.StructuredCall`, and no test
here writes outside `tmp_path`.
"""

from __future__ import annotations

import dataclasses
from typing import Any

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
         description: str = "") -> SourcePost:
    return SourcePost(post_id=f"p{number}", url=f"https://virlo.test/p/{number}",
                      author=f"@creator{number}", views=views,
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
    """When there is nothing to quote the honest answer is ours: the topic name plus the standing
    niche line. No provenance label is recorded for it, because it is not a quote."""
    bare = TrendItem(history_key="t1", monitor_id="m1", name="AI Trends Tracker", topic_key="t1")

    result = await write([entry()], DeadCall(), trends={"t1": bare})

    caption = result.copy["a1"].caption
    assert "AI Trends Tracker" in caption and "AI automation for Czech SMBs" in caption
    assert result.provenance["a1"].refs == {}
    assert result.tags["a1"] == (DegradationTag.COPY_DEGRADED, DegradationTag.NO_ONIMAGE_TEXT)


# ------------------------------------------------ what may never be offered as ON-IMAGE text


def _offer(plan_entry: PlanEntry, source: TrendItem, meta: MetaStyle | None = None,
           competitors: tuple[str, ...] = ()) -> copywrite._Offer:
    run = copywrite._Run(call=None, engine=PromptEngine(), budgets=TextBudgets(),  # type: ignore[arg-type]
                         styles={STYLE_KEY: meta or style()}, conventions={},
                         onimage_languages={}, niche_descriptor="", brand_context="",
                         competitors=competitors, strip_brands={}, log=None)
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
    assert result.copy["a1"].caption.startswith("AI tool stacks"), "our own assembled caption"


async def test_a_caption_of_hashtags_and_three_words_is_not_a_caption(
) -> None:
    """D46 §0.7, the operator-settled floor: a caption is a caption only when at least 25
    non-hashtag characters survive the trailing-tag split. Six of the eight creatives in the first
    paid run shipped a tag dump as their caption, which is what the source posts actually carried
    under the picture — so the engine now falls back to the assembled caption (topic name plus the
    standing niche line) instead, exactly as it does when a post has no caption at all.

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

    assert spam.copy["a1"].caption == f"AI tool stacks — {NICHE}"
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

    assert result.copy["a1"].caption == f"AI tool stacks — {NICHE}"
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


def test_a_captions_trailing_hashtags_are_never_offered_inside_the_frame() -> None:
    """The peeled tags travel in `hashtags[]` for the publisher; the caption BODY is what a
    headline could quote, and the untouched string carrying the tags is refused outright."""
    source = topic(post(1, caption="A caption body long enough to be one #ai #saas"))

    offer = _offer(entry(), source)

    assert offer.onimage == [], "the raw caption carries hashtags, so no slot may hold it"
    assert offer.captions[0].text == "A caption body long enough to be one"
    assert offer.captions[0].hashtags == ("#ai", "#saas")


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
