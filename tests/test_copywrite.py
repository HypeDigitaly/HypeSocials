"""Copywriting — grouping, the candidate table, the budgets that decide it, and the two schemas.

Post-pivot (v2.0.0) this module does not write words: it NUMBERS the source post's own strings,
asks the model for LABELS, and resolves those labels back to bytes (§1.7). So the surface worth
pinning changed completely, and this file follows it:

* `_offer_for` — which post a creative may quote (`posts[trend_reuse_index % len(posts)]`, the
  engine's decision, §1.7.6) and which of its strings are offerable at all;
* `_slot_budgets` — the character ceiling actually in force, the TIGHTER of the meta-style's
  `max_onimage_chars` and FR-101's config budgets, with the reel's overlay borrowing the style's
  `headline` key because the registry vocabulary has no reel slot;
* `_selection_schema` / `_free_text_schema` — the two answer shapes, generated from the
  dataclasses rather than hand-listed, so a field added to `CopySelection` reaches the wire;
* grouping and FR-99's split-then-fallback tiers, which are unchanged in shape and changed in
  content (no pair representative, no cloned CopySet — two creatives on one topic quote two
  different posts).

A21 (`hook_pattern_used`, the generic-pattern re-ask) is GONE: the field is not asked for, not
validated and not re-asked, and its assertions left with it — the verbatim contract replaced the
"derive a pattern, don't reuse the words" mandate it existed to police (D42).

No network: the `llm.structured_call` seam is a stub matching `models.StructuredCall`, so every
test is a pure function of the plan entries and the canned response.
"""

from __future__ import annotations

from typing import Any

from hypesocials import copywrite
from hypesocials.config import TextBudgets
from hypesocials.models import (
    Brief,
    CopySelection,
    CopySet,
    DegradationTag,
    MetaStyle,
    ParsedResult,
    PlanEntry,
    SourcePost,
    TrendItem,
)
from hypesocials.prompts_engine import PromptEngine, json_schema_for

STYLE_KEY = "flat-card"


class StubCall:
    """A `StructuredCall` that answers from a canned table and records every system prompt."""

    def __init__(self, answers: dict[str, dict[str, Any]] | None = None,
                 *, fail_when: Any = None) -> None:
        self.answers = answers or {}
        self.fail_when = fail_when  # predicate over the asset ids in this call
        self.prompts: list[str] = []
        self.schemas: list[dict[str, Any]] = []
        self.calls: list[list[str]] = []

    async def __call__(self, role, messages, json_schema, images=None) -> ParsedResult:
        system = messages[0]["content"]
        self.prompts.append(system)
        self.schemas.append(json_schema)
        asset_ids = [line.split(" · ")[0].removeprefix("- ").strip()
                     for line in system.splitlines()
                     if line.startswith("- ") and " · " in line]
        self.calls.append(asset_ids)
        if self.fail_when is not None and self.fail_when(asset_ids):
            return ParsedResult(parsed=None, raw_text="stub failure", degraded=True)
        creatives = [self.answers[a] | {"asset_id": a} for a in asset_ids if a in self.answers]
        return ParsedResult(parsed={"creatives": creatives}, raw_text="{}")


def selection(**overrides: Any) -> dict[str, Any]:
    """One `CopySelection` answer — REFERENCES, never text (§1.7.2)."""
    payload: dict[str, Any] = {"headline_ref": "P1.hook.1", "subline_ref": "", "overlay_ref": "",
                               "slide_refs": [], "caption_ref": "P1.caption",
                               "through_line": "what one prompt is worth", "narrative_arc": "",
                               "motion_beat": ""}
    payload.update(overrides)
    return payload


def free_text(**overrides: Any) -> dict[str, Any]:
    """One legacy free-text answer — the shape an override brief still gets (§1.7.5)."""
    payload: dict[str, Any] = {
        "caption": "Most people wire this backwards.", "hashtags": ["#ai", "#tools"],
        "hook_line": "Most people wire this backwards", "headline": "Wired backwards",
        "subline": "and it costs them", "slide_texts": [], "narrative_arc": "",
        "overlay_text": "", "through_line": "", "motion_beat": ""}
    payload.update(overrides)
    return payload


def post(number: int, *, views: int = 1_000, caption: str = "", hooks: tuple[str, ...] = (),
         overlays: tuple[str, ...] = (), panels: tuple[str, ...] = (),
         description: str = "") -> SourcePost:
    return SourcePost(post_id=f"p{number}", url=f"https://virlo.test/p/{number}",
                      author=f"@creator{number}", views=views,
                      caption=caption or f"Post {number} caption, as its author wrote it.",
                      hooks=list(hooks) or [f"Hook {number}"], text_overlays=list(overlays),
                      panel_texts=list(panels), description=description)


def make_trend(*posts: SourcePost, key: str = "t1", name: str = "AI tool stacks") -> TrendItem:
    """One TOPIC item, view-ranked posts included — the only quotable material post-pivot."""
    return TrendItem(history_key=key, monitor_id="m1", name=name, topic_key=key,
                     posts=list(posts) or [post(1), post(2)])


def make_style(**overrides: Any) -> MetaStyle:
    style = MetaStyle(key=STYLE_KEY, render_prompt="Flat graphic card, centred subject.",
                      format_affinity=["image", "carousel", "reel"],
                      max_onimage_chars={"headline": 90, "subline": 60, "slide": 90})
    for key, value in overrides.items():
        setattr(style, key, value)
    return style


def entry(asset_id: str, order: int, **overrides: Any) -> PlanEntry:
    plan_entry = PlanEntry(order=order, asset_id=asset_id, creative_format="image",
                           platform="linkedin", language="en", aspect_ratio="16:9",
                           trend_key="t1", style_key=STYLE_KEY)
    for key, value in overrides.items():
        setattr(plan_entry, key, value)
    return plan_entry


def context(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"trends": {"t1": make_trend()},
                            "styles": {STYLE_KEY: make_style()},
                            "engine": PromptEngine(), "text_budgets": TextBudgets()}
    base.update(overrides)
    return base


def _offer(plan_entry: PlanEntry, trend: TrendItem | None = None,
           style: MetaStyle | None = None, **run_kwargs: Any) -> copywrite._Offer:
    """`_offer_for` with the run/group scaffolding a caller would otherwise have to build."""
    run = copywrite._Run(call=None, engine=PromptEngine(),  # type: ignore[arg-type]
                         budgets=run_kwargs.pop("budgets", TextBudgets()),
                         styles={STYLE_KEY: style or make_style()}, conventions={},
                         onimage_languages={}, niche_descriptor="", brand_context="",
                         competitors=tuple(run_kwargs.pop("competitors", ())),
                         strip_brands=run_kwargs.pop("strip_brands", {}), log=None)
    group = copywrite._Group(trend=trend if trend is not None else make_trend(),
                             campaign_brief=None, entries=[plan_entry])
    return copywrite._offer_for(plan_entry, group, run)


# ------------------------------------------------------------------ FR-99 grouping and split


async def test_one_call_per_topic_and_language_pair() -> None:
    entries = [entry("a1", 0), entry("a2", 1, language="cs"),
               entry("a3", 2, trend_key="t2", platform="instagram")]
    trends = {"t1": make_trend(), "t2": make_trend(key="t2", name="Other")}
    call = StubCall({name: selection() for name in ("a1", "a2", "a3")})

    await copywrite.write_copy(entries, call=call, **context(trends=trends))

    assert sorted(call.calls) == [["a1"], ["a2"], ["a3"]]


async def test_two_creatives_on_one_topic_share_one_call_and_quote_different_posts() -> None:
    """Post-pivot there is one line per ENTRY — no pair representative, no cloned `CopySet`.

    §1.7.6 gives creative *k* `posts[trend_reuse_index % len(posts)]`, so two creatives on one
    topic are two different quotes of two different posts. That is the whole reason the reuse
    index survived the pivot, and it is what makes a second creative on a strong topic worth
    rendering at all.
    """
    trend = make_trend(post(1, views=900, caption="First post caption, plainly written."),
                       post(2, views=800, caption="Second post caption, plainly written."))
    entries = [entry("a1", 0, trend_reuse_index=0), entry("a2", 1, trend_reuse_index=1)]
    call = StubCall({"a1": selection(caption_ref="P1.caption"),
                     "a2": selection(caption_ref="P2.caption")})

    result = await copywrite.write_copy(entries, call=call, **context(trends={"t1": trend}))

    assert call.calls == [["a1", "a2"]], "one grouped call per (topic x language)"
    assert result.copy["a1"].caption == "First post caption, plainly written."
    assert result.copy["a2"].caption == "Second post caption, plainly written."
    assert result.provenance["a1"].post_id == "p1"
    assert result.provenance["a2"].post_id == "p2"


async def test_override_brief_creatives_group_by_brief_and_language() -> None:
    """Override briefs consume no topic (FR-144), so they group by brief x language (FR-146)."""
    entries = [entry("a1", 0, trend_key=None, brief_name="ai-audit-cta",
                     brief_influence="override"),
               entry("a2", 1, trend_key=None, brief_name="ai-audit-cta",
                     brief_influence="override")]
    call = StubCall({"a1": free_text(), "a2": free_text()})

    await copywrite.write_copy(entries, call=call, **context())

    assert call.calls == [["a1", "a2"]]


async def test_failed_group_call_splits_into_one_call_per_creative() -> None:
    """Grouping is an efficiency; an efficiency may never widen the blast radius (10 §10)."""
    entries = [entry("a1", 0), entry("a2", 1), entry("a3", 2)]
    call = StubCall({name: selection() for name in ("a1", "a2", "a3")},
                    fail_when=lambda ids: len(ids) > 1)

    result = await copywrite.write_copy(entries, call=call, **context())

    assert call.calls[0] == ["a1", "a2", "a3"]
    assert sorted(call.calls[1:]) == [["a1"], ["a2"], ["a3"]]
    assert set(result.copy) == {"a1", "a2", "a3"}
    assert not result.degraded


async def test_a_partial_group_response_only_splits_the_missing_creatives() -> None:
    entries = [entry("a1", 0), entry("a2", 1)]
    call = StubCall({"a1": selection()})  # a2 simply absent from the grouped response

    result = await copywrite.write_copy(entries, call=call, **context())

    assert call.calls == [["a1", "a2"], ["a2"]]
    assert result.degraded == frozenset({"a2"})
    assert DegradationTag.NO_ONIMAGE_TEXT in result.tags["a2"], "the frame stays wordless"


# ------------------------------------------------------------------ `_offer_for`: the candidates


def test_a_creative_is_offered_its_assigned_posts_strings_and_nobody_elses() -> None:
    """The divergence rule enforced in the TABLE, not only in the resolver: the model is never
    shown a string it is not allowed to pick, so "both creatives quoted the best post" is not an
    answer it can express."""
    trend = make_trend(post(1, views=900, hooks=("First hook",), caption="First caption here."),
                       post(2, views=800, hooks=("Second hook",), caption="Second caption here."))

    second = _offer(entry("a2", 1, trend_reuse_index=1), trend)

    assert second.post is not None and second.post.post_id == "p2"
    assert second.post_ordinal == 2, "labels stay TOPIC-global, so the second post is P2"
    # The short caption is offerable as a headline as well as a caption — with DIFFERENT bytes on
    # each side, which is why `_Offer` keeps the two tables apart.
    assert [c.label for c in second.onimage] == ["P2.hook.1", "P2.caption"]
    assert second.onimage[0].text == "Second hook"
    assert all("P1." not in c.label for c in second.onimage + second.captions)
    assert all("First" not in c.text for c in second.onimage + second.captions)


def test_the_ref_labels_number_every_quotable_field_in_the_grammars_own_order() -> None:
    """`P<n>.<kind>[.<i>]` (contracts item 10): hooks, overlays and panels are 1-indexed lists,
    `caption` and `description` are scalars and carry no index. The order is the grammar's own, so
    two runs' prompts diff meaningfully."""
    single = make_trend(post(1, hooks=("Hook A", "Hook B"), overlays=("Overlay A",),
                             panels=("Panel A", "Panel B"), caption="A caption.",
                             description="Virlo's own summary."))

    offer = _offer(entry("a1", 0), single)

    assert [kind for kind, _text, _index in copywrite._numbered_fields(single.posts[0])] == [
        "hook", "hook", "overlay", "panel", "panel", "caption", "description"]
    # `description` is Virlo's own summary rather than the creator's words, so it is numbered and
    # quotable as a CAPTION and never offered as pixels (`copywrite._NEVER_ON_IMAGE`; the rule is
    # stated in `virlo._source_post`'s field table and owned by `copywrite`). Its own test is
    # `test_copy_verbatim_filter.py::test_virlos_own_summary_is_caption_material_...`.
    assert [c.label for c in offer.onimage] == [
        "P1.hook.1", "P1.hook.2", "P1.overlay.1", "P1.panel.1", "P1.panel.2", "P1.caption"]
    assert [c.label for c in offer.captions] == ["P1.caption", "P1.description"]


def test_only_the_slots_this_format_renders_are_offered() -> None:
    """A reel has no subline and an image has no slides; offering a candidate for a slot the
    creative cannot render invites a ref that resolves into a field nothing reads."""
    image = _offer(entry("a1", 0, creative_format="image"))
    carousel = _offer(entry("a2", 1, creative_format="carousel", slide_count=3))
    reel = _offer(entry("a3", 2, creative_format="reel", aspect_ratio="9:16"))

    assert set(image.budgets) == {"headline", "subline"}
    assert set(carousel.budgets) == {"headline", "slide"}
    assert set(reel.budgets) == {"overlay"}


def test_an_over_budget_string_is_never_offered_which_is_why_nothing_is_ever_trimmed() -> None:
    """§1.7.3's structural guarantee: resolution cannot trim, re-spell or apologise, because the
    only strings it can reach were already short enough.

    The style caps BOTH slots an image renders, at 42 each. Capping only the headline stopped
    demonstrating anything at v2.1.0, when `text_budgets.image_subline` rose to 160 (D46 §0.5): a
    73-character hook then fits the subline slot honestly and is offered for it, which is the
    budgets working, not failing. A string is "over budget" only when it fits no slot at all.
    """
    long_hook = "A hook that runs on well past forty-two characters and keeps going besides"
    trend = make_trend(post(1, hooks=("Short hook", long_hook)))

    offer = _offer(entry("a1", 0), trend,
                   make_style(max_onimage_chars={"headline": 42, "subline": 42}))

    assert offer.budgets["headline"] == 42
    assert "P1.hook.1" in [c.label for c in offer.onimage]
    assert "P1.hook.2" not in [c.label for c in offer.onimage], "the long hook was never offered"
    assert all(len(c.text) <= 42 for c in offer.onimage)
    assert long_hook not in [c.text for c in offer.onimage]


def test_the_four_f23_exclusions_keep_a_string_out_of_the_frame_but_not_out_of_the_caption() -> None:
    """Emoji render as garbage, an @handle becomes an accidental mention, a URL invites a
    hallucinated hyperlink and a hashtag in the artwork is a caption artefact. Captions keep all
    four, because a caption is text a human reads in a feed."""
    budgets = {"headline": 90}
    fits = copywrite._fitting_slots

    assert fits("Plain readable hook", ("headline",), budgets) == ("headline",)
    assert fits("Growth 🚀 unlocked", ("headline",), budgets) == ()
    assert fits("Ask @someone about it", ("headline",), budgets) == ()
    assert fits("Read more at example.com", ("headline",), budgets) == ()
    assert fits("Read https://example.test/x", ("headline",), budgets) == ()
    assert fits("Wins big #ai", ("headline",), budgets) == ()
    assert fits("Two\nlines", ("headline",), budgets) == ()
    # Ordinary punctuation in a Czech or German hook is NOT an emoji and must stay quotable.
    assert fits("Rychlejší růst — bez agentury", ("headline",), budgets) == ("headline",)


def test_a_captions_trailing_hashtag_run_is_peeled_off_and_kept_as_hashtags() -> None:
    """Both halves stay the source's own bytes, so `caption.txt` and the hashtag list are each
    still verbatim. A hashtag written mid-sentence is part of the caption's voice and stays."""
    body, tags = copywrite._split_trailing_hashtags("The pricing page #ai is the product  #saas ")

    assert body == "The pricing page #ai is the product"
    assert tags == ("#saas",)
    assert copywrite._split_trailing_hashtags("No tags here") == ("No tags here", ())

    trend = make_trend(post(1, caption="Everything changed this quarter #ai #saas"))
    offer = _offer(entry("a1", 0), trend)
    caption = next(c for c in offer.captions if c.label == "P1.caption")
    assert caption.text == "Everything changed this quarter"
    assert caption.hashtags == ("#ai", "#saas")


def test_a_topic_with_no_posts_offers_nothing_and_falls_to_the_free_text_path() -> None:
    """The degenerate topic (§1.7.5): nothing to quote, so the group takes the legacy free-text
    schema and `config.languages` governs it — the one case besides an override brief where this
    module still asks a model for words."""
    bare = TrendItem(history_key="t1", monitor_id="m1", name="bare", topic_key="t1")

    empty = _offer(entry("a1", 0), bare)

    assert empty.post is None
    assert (empty.onimage, empty.captions, empty.haystack) == ([], [], ())


# ------------------------------------------------------------------ `_slot_budgets`: the ceiling


def test_the_budget_in_force_is_the_tighter_of_the_style_and_the_config() -> None:
    """Neither outranks the other (§1.3/FR-101): the config budget is the run's ceiling, the
    style's `max_onimage_chars` is what that layout can hold without the text colliding with its
    own artwork, so both apply and the smaller wins."""
    budgets = TextBudgets(image_headline=42, image_subline=60, reel_seed_headline=32)

    tight_style = copywrite._slot_budgets(
        make_style(max_onimage_chars={"headline": 34, "subline": 80, "slide": 110}), budgets)
    loose_style = copywrite._slot_budgets(
        make_style(max_onimage_chars={"headline": 200}), budgets)
    no_style = copywrite._slot_budgets(None, budgets)

    assert tight_style["headline"] == 34, "the style is tighter"
    assert tight_style["subline"] == 60, "the config is tighter"
    assert tight_style["slide"] == 42, "a slide's text is a headline in its own frame"
    assert loose_style["headline"] == 42
    assert no_style == {"headline": 42, "subline": 60, "slide": 42, "overlay": 32}


def test_a_zero_or_absent_style_cap_leaves_the_config_budget_in_force() -> None:
    """`max_onimage_chars: {headline: 34, subline: 0, slide: 0}` is how the registry says "this
    style carries a headline and nothing else" — a 0 is not a budget of zero characters here, it
    is the absence of a style-side cap, and the slot's own offerability is decided by
    `_FORMAT_SLOTS` instead."""
    limits = copywrite._slot_budgets(
        make_style(max_onimage_chars={"headline": 34, "subline": 0, "slide": 0}),
        TextBudgets(image_headline=42, image_subline=60))

    assert limits["headline"] == 34
    assert limits["subline"] == 60 and limits["slide"] == 42


def test_the_reel_overlay_borrows_the_styles_headline_cap_because_the_registry_has_no_reel_slot() -> None:
    """The registry vocabulary is `headline`/`subline`/`slide`; a reel's seed-frame hook is a
    headline in a 9:16 frame, so it takes the style's headline cap when the style names one and
    `reel_seed_headline` otherwise."""
    budgets = TextBudgets(reel_seed_headline=32)

    borrowed = copywrite._slot_budgets(make_style(max_onimage_chars={"headline": 20}), budgets)
    explicit = copywrite._slot_budgets(
        make_style(max_onimage_chars={"headline": 20, "overlay": 12}), budgets)
    unstyled = copywrite._slot_budgets(make_style(max_onimage_chars={}), budgets)

    assert borrowed["overlay"] == 20, "the style's headline cap governs the seed-frame hook"
    assert explicit["overlay"] == 12, "an explicit overlay cap wins over the borrowed one"
    assert unstyled["overlay"] == 32


# ------------------------------------------------------------------ the two answer schemas


def test_the_selection_schema_is_generated_from_copyselection_with_asset_id_on_the_envelope() -> None:
    """Contracts item 10, exactly: the ANSWER fields belong to `CopySelection` and identity belongs
    to the envelope, so a future field on the dataclass reaches the wire automatically while the
    key the engine matches on cannot be renamed by accident."""
    schema = copywrite._selection_schema()
    creative = schema["schema"]["properties"]["creatives"]["items"]
    generated = json_schema_for(CopySelection, exclude={"asset_id"})["properties"]

    assert schema["name"] == "copy_selection"
    assert set(creative["properties"]) == {"asset_id", *generated}
    assert list(creative["properties"])[0] == "asset_id"
    assert creative["required"] == list(creative["properties"])  # strict mode (RESULTS.md §E)
    assert creative["additionalProperties"] is False
    assert schema["schema"]["required"] == ["creatives"]
    # The five reference fields and the three free-text ones, and nothing that ships bytes.
    assert {"headline_ref", "subline_ref", "overlay_ref", "slide_refs", "caption_ref",
            "through_line", "narrative_arc", "motion_beat"} == set(generated)


def test_the_free_text_schema_is_the_copyset_shape_minus_what_the_engine_owns() -> None:
    """`language`/`trend_key` are the engine's bookkeeping and `hook_pattern_used` is A21's dead
    field: asking for a value we discard is asking the model to spend tokens on nothing."""
    creative = copywrite._free_text_schema()["schema"]["properties"]["creatives"]["items"]

    assert copywrite._free_text_schema()["name"] == "social_copy"
    assert {"language", "trend_key", "hook_pattern_used"}.isdisjoint(creative["properties"])
    assert {"caption", "headline", "subline", "slide_texts", "overlay_text", "motion_beat"} <= set(
        creative["properties"])
    assert creative["additionalProperties"] is False


async def test_a_verbatim_group_is_sent_the_selection_schema_and_a_brief_group_the_free_text_one() -> None:
    """The two call shapes are chosen by whether there is anything to quote, and the schema is
    what makes the choice binding on the model rather than advisory."""
    verbatim = StubCall({"a1": selection()})
    await copywrite.write_copy([entry("a1", 0)], call=verbatim, **context())

    brief_only = StubCall({"a2": free_text()})
    await copywrite.write_copy(
        [entry("a2", 0, trend_key=None, brief_name="ai-audit-cta", brief_influence="override")],
        call=brief_only, **context())

    assert verbatim.schemas[0]["name"] == "copy_selection"
    assert brief_only.schemas[0]["name"] == "social_copy"


# ------------------------------------------------------------------ the sibling list


async def test_a_verbatim_line_names_the_assigned_post_and_refuses_to_choose_a_language() -> None:
    """§1.7.5/F22: a verbatim creative's language is a property of the string it quotes, so the
    line says so instead of naming a language we would then be asking the model to translate into.
    """
    call = StubCall({"a1": selection()})

    await copywrite.write_copy([entry("a1", 0, creative_format="carousel", slide_count=5)],
                               call=call, onimage_languages={"a1": "cs"}, **context())

    line = next(l for l in call.prompts[0].splitlines() if l.startswith("- a1"))
    assert "linkedin" in line and "carousel" in line and "5 slides" in line
    assert "quote post P1" in line
    assert "caption language: as-selected (source language, never translated)" in line
    assert "caption en" not in line and "on-image cs" not in line


async def test_a_free_text_line_still_carries_the_configured_caption_and_on_image_languages() -> None:
    """`config.languages` stays meaningful for exactly the creatives that quote nothing: override
    briefs and the post-less degrade path."""
    call = StubCall({"a1": free_text()})

    await copywrite.write_copy(
        [entry("a1", 0, trend_key=None, brief_name="ai-audit-cta", brief_influence="override")],
        call=call, onimage_languages={"a1": "cs"}, **context())

    line = next(l for l in call.prompts[0].splitlines() if l.startswith("- a1"))
    assert "caption en" in line and "on-image cs" in line
    assert "as-selected" not in line
    assert "these creatives quote no source post" in call.prompts[0]


async def test_brand_context_reaches_the_copywriter_but_never_a_render_prompt() -> None:
    call = StubCall({"a1": selection()})
    await copywrite.write_copy([entry("a1", 0)], call=call,
                               brand_context="ACME voice: plain, declarative", **context())
    assert "ACME voice: plain, declarative" in call.prompts[0]


def test_a_group_whose_creatives_carry_two_styles_prints_no_budget_line_at_all() -> None:
    """`{{text_budgets}}` is the only style-derived slot the copywriter role allowlists, and a
    group with two styles has two ceilings — printing either would be a lie. It costs nothing:
    enforcement is the candidate filter's, per creative, and the numbered table states each
    creative's own budget anyway."""
    run = copywrite._Run(call=None, engine=PromptEngine(), budgets=TextBudgets(),  # type: ignore[arg-type]
                         styles={STYLE_KEY: make_style(), "other": make_style(key="other")},
                         conventions={}, onimage_languages={}, niche_descriptor="",
                         brand_context="", competitors=(), strip_brands={}, log=None)

    one = copywrite._single_style([entry("a1", 0), entry("a2", 1)], run)
    two = copywrite._single_style([entry("a1", 0), entry("a2", 1, style_key="other")], run)

    assert one is not None and one.key == STYLE_KEY
    assert two is None


# ------------------------------------------------------------------ FR-101, on the one path left


async def test_free_text_copy_is_still_trimmed_at_a_word_boundary() -> None:
    """`_apply_budgets` survives for override briefs alone: that copy is the model's own prose and
    can overshoot exactly as it always could. FR-101's trim never cuts mid-word."""
    long_headline = "Most people wire their entire AI stack backwards and never notice"
    call = StubCall({"a1": free_text(headline=long_headline, subline="short")})

    result = await copywrite.write_copy(
        [entry("a1", 0, trend_key=None, brief_name="ai-audit-cta", brief_influence="override")],
        call=call, **context(text_budgets=TextBudgets(image_headline=42)))

    headline = result.copy["a1"].headline
    assert len(headline) <= 42
    assert long_headline.startswith(headline)
    assert not headline.endswith(" ") and headline.split()[-1] in long_headline.split()
    assert result.trimmed == frozenset({"a1"})
    assert DegradationTag.TEXT_TRIMMED in result.tags["a1"]


async def test_a_free_text_creative_is_trimmed_against_the_styles_own_ceiling_too() -> None:
    """The style's cap is in force on this path as well — a brief's prose still has to fit the
    layout it is being rendered into."""
    call = StubCall({"a1": free_text(headline="A headline of twenty-nine plus characters")})

    result = await copywrite.write_copy(
        [entry("a1", 0, trend_key=None, brief_name="b", brief_influence="override")],
        call=call, **context(styles={STYLE_KEY: make_style(max_onimage_chars={"headline": 20})}))

    assert len(result.copy["a1"].headline) <= 20
    assert result.trimmed == frozenset({"a1"})


async def test_a_verbatim_creatives_copy_is_never_trimmed_because_it_never_needs_to_be() -> None:
    """The bypass (§1.7.3), asserted from the outside: an over-budget string was never offered, so
    the resolved bytes are already inside the ceiling and `trimmed` stays empty."""
    trend = make_trend(post(1, hooks=("Exactly the hook we want",),
                            caption="A caption that runs well past any on-image budget, "
                                    "because captions are read in a feed and not in a frame."))
    call = StubCall({"a1": selection(headline_ref="P1.hook.1", caption_ref="P1.caption")})

    result = await copywrite.write_copy([entry("a1", 0)], call=call, **context(
        trends={"t1": trend}, text_budgets=TextBudgets(image_headline=42)))

    assert result.copy["a1"].headline == "Exactly the hook we want"
    assert result.copy["a1"].caption.endswith("read in a feed and not in a frame.")
    assert not result.trimmed


async def test_the_free_text_answer_still_fills_the_legacy_copyset_fields() -> None:
    """The override-brief path is unchanged in shape: the model writes the words, the configured
    language applies, and nothing about it claims to be verbatim."""
    call = StubCall({"a1": free_text(slide_texts=["One", "Two"], motion_beat="hand lifts the cup")})

    result = await copywrite.write_copy(
        [entry("a1", 0, trend_key=None, brief_name="b", brief_influence="override",
               creative_format="carousel", slide_count=2)],
        call=call, campaign_briefs={"b": Brief(name="b", description="d", influence="override")},
        **context())

    copyset = result.copy["a1"]
    assert copyset.slide_texts == ["One", "Two"]
    assert copyset.motion_beat == "hand lifts the cup"
    assert copyset.hashtags == ["#ai", "#tools"]
    assert result.provenance["a1"].post_id == "" and result.provenance["a1"].refs == {}
    assert isinstance(copyset, CopySet)
