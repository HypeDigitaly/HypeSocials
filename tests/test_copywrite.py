"""Copywriting — grouping, the candidate table, the budgets that decide it, and the two schemas.

Post-pivot (v2.0.0) this module does not write words: it NUMBERS the source post's own strings,
asks the model for LABELS, and resolves those labels back to bytes (§1.7). So the surface worth
pinning changed completely, and this file follows it:

* `_offer_for` — which post a creative may quote (`entry.source_post_id`, bound at ASSIGN by
  `plan.assign` from the topic's FRESH posts, FR-304/FR-307; the old
  `posts[trend_reuse_index % len(posts)]` rotation survives for unbound entries alone and is
  deprecated) and which of its strings are offerable at all;
* `_slot_budgets` — the character ceiling actually in force, the TIGHTER of the meta-style's
  `max_onimage_chars` and FR-101's config budgets, with the slide carrying its own
  `text_budgets.slide` (D46 §0.5) and the reel's overlay borrowing the style's `headline` key
  because the registry vocabulary has no reel slot;
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


class Recorder:
    """The `LogWriter` surface `copywrite` touches — enough to assert WHICH warning fired."""

    def __init__(self) -> None:
        self.warnings: list[tuple[str, str, dict[str, Any]]] = []

    def warn(self, event: str, message: str = "", /, **data: Any) -> None:
        self.warnings.append((event, message, data))

    def warned(self, event: str) -> list[str]:
        return [message for name, message, _ in self.warnings if name == event]


def _offer(plan_entry: PlanEntry, trend: TrendItem | None = None,
           style: MetaStyle | None = None, **run_kwargs: Any) -> copywrite._Offer:
    """`_offer_for` with the run/group scaffolding a caller would otherwise have to build."""
    run = copywrite._Run(call=None, engine=PromptEngine(),  # type: ignore[arg-type]
                         budgets=run_kwargs.pop("budgets", TextBudgets()),
                         styles={STYLE_KEY: style or make_style()}, conventions={},
                         onimage_languages={}, niche_descriptor="", brand_context="",
                         competitors=tuple(run_kwargs.pop("competitors", ())),
                         strip_brands=run_kwargs.pop("strip_brands", {}),
                         merged_panels=run_kwargs.pop("merged_panels", {}),
                         burnt_posts=frozenset(run_kwargs.pop("burnt_post_ids", ())),
                         log=run_kwargs.pop("log", None))
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

    D46 binds the post at ASSIGN (`entry.source_post_id`), so two creatives on one topic are two
    different quotes of two different posts — and, unlike the rotation this replaced, each of them
    is a post the plan verified was FRESH. That is what makes a second creative on a strong topic
    worth rendering at all.
    """
    trend = make_trend(post(1, views=900, caption="First post caption, plainly written."),
                       post(2, views=800, caption="Second post caption, plainly written."))
    entries = [entry("a1", 0, source_post_id="p1"), entry("a2", 1, source_post_id="p2")]
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


def test_a_creative_is_offered_its_bound_posts_strings_and_nobody_elses() -> None:
    """The divergence rule enforced in the TABLE, not only in the resolver: the model is never
    shown a string it is not allowed to pick, so "both creatives quoted the best post" is not an
    answer it can express."""
    trend = make_trend(
        post(1, views=900, hooks=("First hook",), caption="First caption, written out in full."),
        post(2, views=800, hooks=("Second hook",), caption="Second caption, written out in full."))

    second = _offer(entry("a2", 1, source_post_id="p2"), trend)

    assert second.post is not None and second.post.post_id == "p2"
    assert second.bound, "the plan bound it; nothing here rotated to it"
    assert second.post_ordinal == 2, "labels stay TOPIC-global, so the second post is P2"
    # The caption is offerable as a headline as well as a caption — with DIFFERENT bytes on each
    # side, which is why `_Offer` keeps the two tables apart.
    assert [c.label for c in second.onimage] == ["P2.hook.1", "P2.caption"]
    assert second.onimage[0].text == "Second hook"
    assert all("P1." not in c.label for c in second.onimage + second.captions)
    assert all("First" not in c.text for c in second.onimage + second.captions)


def test_the_bound_post_id_beats_the_rotation_and_the_rotation_is_only_the_legacy_path() -> None:
    """FR-304/FR-307, the pick half. The modulo could not know which posts an earlier run had
    already spent — that is how the first paid run re-quoted a post from 2023 — so the plan now
    binds a specific FRESH post id and this module looks it up. The rotation survives for the
    entries nothing binds (images and reels, until W3 retires the field with `generate/refs.py`),
    and it must not be able to override a binding: here the two disagree on purpose.
    """
    trend = make_trend(post(1, hooks=("First hook",), caption="First caption, written in full."),
                       post(2, hooks=("Second hook",), caption="Second caption, written in full."),
                       post(3, hooks=("Third hook",), caption="Third caption, written in full."))

    bound = _offer(entry("a1", 0, source_post_id="p3", trend_reuse_index=1), trend)
    unbound = _offer(entry("a2", 1, trend_reuse_index=1), trend)

    assert bound.post is not None and bound.post.post_id == "p3", "the binding wins outright"
    assert bound.post_ordinal == 3 and bound.bound
    assert unbound.post is not None and unbound.post.post_id == "p2", "the legacy rotation"
    assert not unbound.bound, "an unbound pick never claims FR-304's mapping"


def test_a_burnt_bound_post_is_refused_rather_than_swapped_for_a_neighbour() -> None:
    """FR-307/§0.10's belt-and-braces at the pick, behind the fetch gate that already dropped used
    posts. A post an earlier run quoted may not be quoted again — and the remedy is refusal, not
    substitution: swapping in P2 would leave `copy_source_post_id`, the panel map and
    `trend_history` naming three different posts, and the operator chose famine over silent
    repeats. The creative still ships: assembled caption, wordless frame."""
    log = Recorder()
    trend = make_trend(post(1, hooks=("First hook",), caption="First caption, written in full."),
                       post(2, hooks=("Second hook",), caption="Second caption, written in full."))

    refused = _offer(entry("a1", 0, source_post_id="p1"), trend, burnt_post_ids=("p1",), log=log)

    assert refused.refused == "no_fresh_post_available", "FR-73's own vocabulary"
    assert refused.post is None and refused.onimage == [] and refused.captions == []
    assert log.warned("copy_bound_post_burnt")


async def test_a_creative_whose_bound_post_is_burnt_ships_our_words_and_costs_no_call() -> None:
    """The whole-run shape of the same refusal. It is NOT `copy_degraded` — no model call failed,
    and counting it as an FR-248 `llm_starved` loss would blame the LLM for a plan that bound a
    spent post. It is not the P1 fallback either: P1 may BE the burnt post."""
    trend = make_trend(post(1, hooks=("First hook",),
                            caption="A caption long enough to be a caption."))
    call = StubCall({"a1": selection()})

    result = await copywrite.write_copy(
        [entry("a1", 0, source_post_id="p1")], call=call, burnt_post_ids=["p1"],
        niche_descriptor="AI automation for Czech SMBs", **context(trends={"t1": trend}))

    copyset = result.copy["a1"]
    assert call.calls == [], "nothing was asked, so nothing was spent"
    assert copyset.headline == "" and copyset.slide_texts == []
    assert copyset.caption == "AI tool stacks — AI automation for Czech SMBs"
    assert "First hook" not in copyset.caption
    # FR-73's amended vocabulary, and deliberately the SAME word `plan.assign` uses when it skips
    # a creative group for the same condition: the operator reads one spelling whichever gate
    # caught the exhausted supply.
    assert set(result.tags["a1"]) == {DegradationTag.NO_ONIMAGE_TEXT,
                                      DegradationTag.NO_FRESH_POST_AVAILABLE}
    assert not result.degraded, "a refusal is not a failed copy call"
    assert result.provenance["a1"].post_id == "", "nothing was quoted, so nothing is claimed"


def test_a_bound_post_the_topic_no_longer_carries_is_refused_too() -> None:
    """The other half of the binding check. A re-fetch between ASSIGN and COPY, or a mis-keyed
    topic, must not silently make the deck somebody else's."""
    log = Recorder()
    trend = make_trend(post(1, caption="A caption long enough to count as a caption."))

    refused = _offer(entry("a1", 0, source_post_id="p9"), trend, log=log)

    assert refused.refused == "bound_post_missing"
    assert refused.post is None
    assert log.warned("copy_bound_post_missing")


async def test_a_missing_bound_post_never_borrows_the_famine_word_from_the_burnt_one() -> None:
    """The whole-run shape of `bound_post_missing`, and the tag it deliberately does NOT carry.

    Both refusals ship the same creative — our assembled caption, a wordless frame — but they are
    different faults. `no_fresh_post_available` is FR-307's famine, counted in the run summary and
    read by the operator as "the supply ran out"; a topic that changed under the plan is a
    consistency fault and borrowing the famine word would inflate the very figure §0.9's cadence
    arithmetic is measured on. It lives in `copy_bound_post_missing` in the log instead.
    """
    log = Recorder()
    trend = make_trend(post(1, hooks=("First hook",),
                            caption="A caption long enough to be a caption."))
    call = StubCall({"a1": selection()})

    result = await copywrite.write_copy(
        [entry("a1", 0, source_post_id="p404")], call=call, log=log,
        niche_descriptor="AI automation for Czech SMBs", **context(trends={"t1": trend}))

    assert call.calls == [], "a refused post is settled before anything is asked"
    assert result.tags["a1"] == (DegradationTag.NO_ONIMAGE_TEXT,)
    assert DegradationTag.NO_FRESH_POST_AVAILABLE not in result.tags["a1"]
    assert result.copy["a1"].caption == "AI tool stacks — AI automation for Czech SMBs"
    assert "First hook" not in result.copy["a1"].caption, "P1 is not a consolation prize"
    assert log.warned("copy_bound_post_missing") and log.warned("copy_post_refused")


async def test_a_burnt_bound_deck_ships_wordless_rather_than_mapping_a_spent_source() -> None:
    """The refusal outranks FR-304's deterministic mapping — the sharpest edge of §0.10.

    `_mapped_deck` needs no model in the loop, so a bound carousel whose copy CALL fails still
    ships its panels (the `_mapped_fallback` ruling). A bound carousel whose POST is burnt must not:
    the mapping would re-render, slide for slide, the exact deck an earlier run already shipped,
    which is the repeat the whole guard exists to prevent. So the deck goes out wordless, claims no
    panel map, and the operator sees the famine tag rather than yesterday's slides.
    """
    log = Recorder()
    trend = make_trend(post(1, panels=("Panel one line", "Panel two line", "Panel three line"),
                            caption="A caption long enough to be a caption at all."))

    result = await copywrite.write_copy(
        [entry("d1", 0, creative_format="carousel", slide_count=3, source_post_id="p1")],
        call=StubCall({"d1": selection()}), burnt_post_ids=["p1"], log=log,
        niche_descriptor="AI automation for Czech SMBs",
        **context(trends={"t1": trend}, styles={STYLE_KEY: make_style(
            max_onimage_chars={"headline": 90, "subline": 60, "slide": 300})}))

    copyset, provenance = result.copy["d1"], result.provenance["d1"]
    assert copyset.slide_texts == [], "not one source panel was re-rendered"
    assert "Panel one line" not in " ".join([copyset.caption, *copyset.hashtags])
    assert provenance.panel_map == [] and provenance.source_panel_count == 0
    assert provenance.post_id == "", "nothing was quoted, so nothing is claimed"
    assert set(result.tags["d1"]) == {DegradationTag.NO_ONIMAGE_TEXT,
                                      DegradationTag.NO_FRESH_POST_AVAILABLE}
    assert log.warned("copy_bound_post_burnt")


def test_the_legacy_rotation_is_guarded_by_the_same_no_repeat_rule_as_a_binding() -> None:
    """FR-307 binds on POST IDS, not on how the post was chosen. The deprecated modulo survives for
    the entries nothing binds (images, reels), and it is exactly the path that re-quoted a 2023
    post — so landing on a burnt post refuses there too rather than rotating on to a neighbour.

    Rotating on would be worse than refusing: the label grammar, the provenance and the history
    line would all name whichever post the modulo happened to reach, and the run would report a
    quote it was never entitled to make.
    """
    log = Recorder()
    trend = make_trend(post(1, hooks=("First hook",), caption="First caption, written in full."),
                       post(2, hooks=("Second hook",), caption="Second caption, written in full."))

    refused = _offer(entry("a1", 0, trend_reuse_index=1), trend, burnt_post_ids=("p2",), log=log)

    assert refused.refused == "no_fresh_post_available"
    assert refused.post is None and refused.onimage == []
    assert log.warned("copy_post_burnt"), "the rotation's own warning, not the binding's"
    assert not log.warned("copy_bound_post_burnt")


def test_the_ref_labels_number_every_quotable_field_in_the_grammars_own_order() -> None:
    """FR-302's grammar and FR-100's offer PRIORITY: panels, then overlays, then hooks, then the
    caption. The order is a reversal (it used to lead with hooks) and it is the fix for what the
    first paid run shipped — the words ON the slides are the material, so they are what the model
    reads first. `caption` is a scalar and carries no index; `description` is not in the grammar at
    all any more (FR-303).
    """
    single = make_trend(post(1, hooks=("Hook A", "Hook B"), overlays=("Overlay A",),
                             panels=("Panel A", "Panel B"),
                             caption="A caption long enough to be a caption at all.",
                             description="Virlo's own summary."))

    offer = _offer(entry("a1", 0), single)

    assert [kind for kind, _text, _index in copywrite._numbered_fields(single.posts[0])] == [
        "panel", "panel", "overlay", "hook", "hook", "caption"]
    assert [c.label for c in offer.onimage] == [
        "P1.panel.1", "P1.panel.2", "P1.overlay.1", "P1.hook.1", "P1.hook.2", "P1.caption"]
    assert [c.label for c in offer.captions] == ["P1.caption"]
    # FR-303 at the grammar rather than at a filter: nothing can NAME the summary, so nothing can
    # resolve it. Its own tests are in `test_copy_verbatim_filter.py`.
    assert "Virlo's own summary." not in [c.text for c in offer.onimage + offer.captions]
    assert copywrite._REF.match("P1.description") is None


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


# --------------------------------------------------- FR-304: the deck the engine maps itself


def deck_style(**overrides: Any) -> MetaStyle:
    """A style whose slide cap is wide enough for real panels (D46 §0.5 raises the registry)."""
    return make_style(max_onimage_chars={"headline": 90, "subline": 60, "slide": 300}, **overrides)


def deck_entry(asset_id: str = "d1", *, slides: int = 4, **overrides: Any) -> PlanEntry:
    """A carousel bound to post p1, the shape `plan.assign` produces post-D46."""
    return entry(asset_id, 0, creative_format="carousel", aspect_ratio="1:1",
                 slide_count=slides, source_post_id="p1", **overrides)


async def test_a_bound_decks_slides_are_mapped_from_the_source_panels_position_for_position() -> None:
    """FR-304, the whole rule in one assertion: OUR slide *i* renders THEIR panel *i*, verbatim,
    and the model is not in the loop. It chooses the cover headline, the caption and the hashtags;
    the deck is arithmetic.

    The empty middle slot is the point. Compacting it would put panel 4's words on slide 3 and
    ship a deck that reads as the source's with two slides swapped — which is precisely the defect
    the index-aligned `panel_texts` contract (§0.14a) exists to make impossible.
    """
    trend = make_trend(post(1, hooks=("A cover hook",),
                            panels=("Panel one line", "Panel two line", "",
                                    "Panel four line"),
                            caption="A caption long enough to be a caption at all."))
    call = StubCall({"d1": selection(headline_ref="P1.hook.1", caption_ref="P1.caption",
                                     slide_refs=[])})

    result = await copywrite.write_copy([deck_entry()], call=call, **context(
        trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    copyset, provenance = result.copy["d1"], result.provenance["d1"]
    assert copyset.slide_texts == ["Panel one line", "Panel two line", "", "Panel four line"]
    assert copyset.headline == "A cover hook", "the LLM still chooses the cover"
    assert provenance.refs["slide_1"] == "P1.panel.1"
    assert provenance.refs["slide_4"] == "P1.panel.4", "slide 4 quotes panel 4, not panel 3"
    assert "slide_3" not in provenance.refs, "an empty panel quotes nothing and claims nothing"
    assert provenance.source_panel_count == 4
    assert provenance.panel_map == [
        {"slide": 1, "source_position": 1, "source_text": "Panel one line",
         "source_text_original": "Panel one line", "ref_label": "P1.panel.1", "drop_reason": "",
         "creator_stripped": False},
        {"slide": 2, "source_position": 2, "source_text": "Panel two line",
         "source_text_original": "Panel two line", "ref_label": "P1.panel.2", "drop_reason": "",
         "creator_stripped": False},
        {"slide": 3, "source_position": 3, "source_text": "", "source_text_original": "",
         "ref_label": "", "drop_reason": "empty", "creator_stripped": False},
        {"slide": 4, "source_position": 4, "source_text": "Panel four line",
         "source_text_original": "Panel four line", "ref_label": "P1.panel.4", "drop_reason": "",
         "creator_stripped": False},
    ], "one row per OUR slide, empty ones included — the row IS the alignment (FR-309)"


async def test_the_merged_vision_panels_are_what_a_mapped_deck_quotes() -> None:
    """The T2.3 seam, asserted: `write_copy(merged_panels={post_id: [...]})` is where slide
    intelligence's reading of the deck arrives (FR-306 — Virlo's panel where it has one, the vision
    transcription of that slide where it does not). Keyed by POST, because the merge is a property
    of the source deck and two siblings bound to one post must see one reading of it."""
    trend = make_trend(post(1, panels=("Virlo had this one", "", ""),
                            caption="A caption long enough to be a caption at all."))
    call = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})

    result = await copywrite.write_copy(
        [deck_entry(slides=3)], call=call,
        merged_panels={"p1": ["Virlo had this one", "Vision read this one", ""]},
        **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert result.copy["d1"].slide_texts == ["Virlo had this one", "Vision read this one", ""]
    assert result.provenance["d1"].refs["slide_2"] == "P1.panel.2"


async def test_a_long_mapped_panel_ships_verbatim_whatever_the_slide_budget_says() -> None:
    """FIX 2 (operator ruling 2026-08-13), and the regression that paid for it.

    In run 20260813_143420_oyo4 the per-style slide budget (180–300 characters) gated the MAPPED
    deck as well as the chosen text, and it blanked 21 of 41 panels — one of them for being a
    single character over 300. A style ceiling is a design rule for text WE choose; a mapped panel
    is text we MIRROR, and our slide *i* is a re-render of their slide *i* whatever its length. So
    the budget is out of this path entirely: the panel ships whole, and the render template is told
    to give it room rather than to fit it.
    """
    log = Recorder()
    long_panel = "Panel one. " + "It keeps explaining the point at length. " * 11  # ~470 chars
    assert 300 < len(long_panel) < copywrite.PANEL_SANITY_CHARS
    trend = make_trend(post(1, panels=(long_panel, "Third-of-the-way panel"),
                            caption="A caption long enough to be a caption at all."))
    call = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})

    result = await copywrite.write_copy([deck_entry(slides=2)], call=call, log=log, **context(
        trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))  # slide cap 300

    copyset, provenance = result.copy["d1"], result.provenance["d1"]
    assert copyset.slide_texts == [long_panel, "Third-of-the-way panel"], "verbatim, in full"
    assert provenance.refs["slide_1"] == "P1.panel.1"
    assert provenance.panel_map[0]["drop_reason"] == ""
    assert provenance.panel_map[0]["source_text_original"] == long_panel
    assert not result.trimmed and DegradationTag.TEXT_TRIMMED not in result.tags.get("d1", ())
    assert not log.warnings, "nothing was lost, so nothing is warned about"


async def test_a_panel_past_the_sanity_ceiling_keeps_position_and_cites_it() -> None:
    """The one length rule left on a mapped panel, and it is a fence rather than a budget.

    Past `PANEL_SANITY_CHARS` the string is a transcription accident — a whole caption scraped into
    one panel, a vision pass that ran away — not a slide anybody read. It is still never trimmed
    (FR-100: a trimmed quote is not a quote), the slide KEEPS ITS POSITION, and the warning cites
    the characters measured against the ceiling that actually applied. The old line read
    "(96 characters, ceiling 300)" on panels it had blanked for other reasons entirely.
    """
    log = Recorder()
    runaway = "W" * 1600
    trend = make_trend(post(1, panels=("Short panel", runaway, "Third panel"),
                            caption="A caption long enough to be a caption at all."))
    call = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})

    result = await copywrite.write_copy([deck_entry(slides=3)], call=call, log=log, **context(
        trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    copyset = result.copy["d1"]
    assert copyset.slide_texts == ["Short panel", "", "Third panel"]
    assert not any(runaway.startswith(text) and text for text in copyset.slide_texts), \
        "no prefix of it shipped either — a trimmed quote is not a quote"
    assert result.provenance["d1"].panel_map[1] == {
        "slide": 2, "source_position": 2, "source_text": "", "source_text_original": runaway,
        "ref_label": "", "drop_reason": "over_budget", "creator_stripped": False}
    assert len(log.warned("panel_over_budget")) == 1
    warning = log.warned("panel_over_budget")[0]
    assert "slide 2 (1600 characters, sanity ceiling 1500)" in warning


async def test_a_panel_carrying_a_handle_or_a_url_says_so_and_keeps_the_original() -> None:
    """FIX 5a: the handle/URL backstop gets its OWN warning, naming what it found.

    The audited run rejected whole panels because the vision pass transcribed a creator's watermark
    into the panel text — and then reported the loss as a budget overflow, which sent the operator
    hunting for a character ceiling that had nothing to do with it. FR-306's `chrome_text` field
    keeps that chrome out of `onimage_text` upstream; this check stays as the backstop, and now it
    says what it is. The pre-gate string survives in `source_text_original`, so the provenance can
    still show what the blank slide cost.
    """
    log = Recorder()
    trend = make_trend(post(1, panels=("Follow @growthdaily for more", "A perfectly good panel",
                                       "Read the rest at example.com"),
                            caption="A caption long enough to be a caption at all."))
    call = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})

    result = await copywrite.write_copy([deck_entry(slides=3)], call=call, log=log, **context(
        trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    rows = result.provenance["d1"].panel_map
    assert result.copy["d1"].slide_texts == ["", "A perfectly good panel", ""]
    assert [row["drop_reason"] for row in rows] == [
        "contains_handle_or_url", "", "contains_handle_or_url"]
    assert [row["source_position"] for row in rows] == [1, 2, 3], "position kept, nothing slides up"
    assert rows[0]["source_text_original"] == "Follow @growthdaily for more"
    assert rows[2]["source_text_original"] == "Read the rest at example.com"
    assert rows[0]["source_text"] == "", "what SHIPPED is still honestly empty"
    assert not log.warned("panel_over_budget"), "this is not a length failure and never was"
    handles = log.warned("panel_handle_or_url")
    assert len(handles) == 1
    assert "slide 1 (carries an @handle)" in handles[0]
    assert "slide 3 (carries a URL)" in handles[0]


async def test_an_empty_panel_is_silent_unless_the_strip_is_what_emptied_it() -> None:
    """The third verdict, `empty`, and the one case where it is worth a word.

    A slot Virlo never filled, or a position past the source deck's end, is normal (§0.14a) and is
    already visible in the panel map — warning about it is the noise that buried the real losses in
    the audited run. A panel that HAD words and lost every one of them to the competitor strip is
    a different fact, and the operator is told.
    """
    quiet, loud = Recorder(), Recorder()
    trend = make_trend(post(1, panels=("Plain panel", ""),
                            caption="A caption long enough to be a caption at all."))
    stripped = make_trend(post(1, panels=("Plain panel", "Nitro"),
                               caption="A caption long enough to be a caption at all."))
    answer = {"d1": selection(headline_ref="", caption_ref="P1.caption")}

    silent = await copywrite.write_copy([deck_entry(slides=3)], call=StubCall(answer), log=quiet,
                                        **context(trends={"t1": trend},
                                                  styles={STYLE_KEY: deck_style()}))
    warned = await copywrite.write_copy([deck_entry(slides=2)], call=StubCall(answer), log=loud,
                                        competitors=["Nitro"],
                                        **context(trends={"t1": stripped},
                                                  styles={STYLE_KEY: deck_style()}))

    assert [row["drop_reason"] for row in silent.provenance["d1"].panel_map] == ["", "empty",
                                                                                "empty"]
    assert not quiet.warnings, "an empty source slot is not a loss to report"
    assert [row["drop_reason"] for row in warned.provenance["d1"].panel_map] == ["", "empty"]
    assert "slide 2" in loud.warned("panel_emptied_by_strip")[0]


def test_a_panel_keeps_its_emoji_newlines_and_hashtags_for_the_slide_slot_alone() -> None:
    """D46 §0.14b. Those three are the source deck's own typography and our slide IS their slide,
    so refusing them would leave the frame wordless exactly where a creator got expressive. The
    same panel offered as a HEADLINE is still held to the full F23 rule — a headline is our frame's
    own line, not a re-render of theirs — and @handles and URLs are excluded on every slot, because
    they leak an identity or a link rather than a voice."""
    fits = copywrite._fitting_slots
    budgets = {"headline": 90, "slide": 300}
    slots = ("headline", "slide")

    assert fits("Growth 🚀 unlocked", slots, budgets, kind="panel") == ("slide",)
    assert fits("Two\nlines on one slide", slots, budgets, kind="panel") == ("slide",)
    assert fits("Wins big #ai", slots, budgets, kind="panel") == ("slide",)
    assert fits("A plain panel line", slots, budgets, kind="panel") == ("headline", "slide")
    # The two that stay absolute, on the relaxed kind as well.
    assert fits("Ask @someone about it", slots, budgets, kind="panel") == ()
    assert fits("Read more at example.com", slots, budgets, kind="panel") == ()
    # And every other kind keeps all five exclusions, `slide` slot included.
    assert fits("Growth 🚀 unlocked", slots, budgets, kind="hook") == ()
    assert fits("Growth 🚀 unlocked", slots, budgets) == ()


async def test_an_emoji_panel_really_does_reach_the_deck() -> None:
    """The §0.14b relaxation at the level that ships bytes, not at the predicate."""
    trend = make_trend(post(1, panels=("Growth 🚀 unlocked", "Then it plateaued"),
                            caption="A caption long enough to be a caption at all."))
    call = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})

    result = await copywrite.write_copy([deck_entry(slides=2)], call=call, **context(
        trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert result.copy["d1"].slide_texts == ["Growth 🚀 unlocked", "Then it plateaued"]


async def test_a_mapped_deck_ignores_slide_refs_the_model_sent_anyway_and_says_so() -> None:
    """The deck is not negotiable. A model that answers with slide labels — an older prompt, a
    hallucinated habit — cannot re-order the source's slides."""
    log = Recorder()
    trend = make_trend(post(1, panels=("Panel one", "Panel two"),
                            caption="A caption long enough to be a caption at all."))
    call = StubCall({"d1": selection(caption_ref="P1.caption", headline_ref="",
                                     slide_refs=["P1.panel.2", "P1.panel.1"])})

    result = await copywrite.write_copy([deck_entry(slides=2)], call=call, log=log, **context(
        trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert result.copy["d1"].slide_texts == ["Panel one", "Panel two"], "source order, not theirs"
    assert log.warned("copy_slide_refs_ignored")


async def test_an_unbound_carousel_keeps_the_selection_path_and_it_is_position_preserving() -> None:
    """The pre-D46 path still exists for a carousel nothing bound — and it, too, no longer closes
    gaps. `slide_refs[k]` is slide *k+1*; an unusable label leaves that slide wordless instead of
    pulling slide 3's words onto slide 2 (FR-302's position-preserving grammar)."""
    trend = make_trend(post(1, panels=("Panel one", "Panel two", "Panel three"),
                            caption="A caption long enough to be a caption at all."))
    call = StubCall({"c1": selection(headline_ref="", caption_ref="P1.caption",
                                     slide_refs=["P1.panel.1", "P1.panel.9", "P1.panel.3"])})

    result = await copywrite.write_copy(
        [entry("c1", 0, creative_format="carousel", aspect_ratio="1:1", slide_count=3)],
        call=call, **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert result.copy["c1"].slide_texts == ["Panel one", "", "Panel three"]
    assert result.provenance["c1"].refs["slide_3"] == "P1.panel.3"
    assert "slide_2" not in result.provenance["c1"].refs
    assert result.provenance["c1"].panel_map == [], "no binding, no FR-304 map"


async def test_a_deck_whose_panels_are_all_empty_ships_caption_only() -> None:
    """The `no_onimage_text` degrade, on a deck: the list of slides is full of empty slots (they
    are the alignment) and not one of them became pixels, so the tag is decided on the STRINGS."""
    trend = make_trend(post(1, panels=("", ""),
                            caption="A caption long enough to be a caption at all."))
    call = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})

    result = await copywrite.write_copy([deck_entry(slides=2)], call=call, **context(
        trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert result.copy["d1"].slide_texts == ["", ""]
    assert result.tags["d1"] == (DegradationTag.NO_ONIMAGE_TEXT,)


async def test_the_deck_length_is_the_plans_not_the_sources() -> None:
    """§0.4′: the deck was fixed at ASSIGN from `panel_count` clamped to the platform ceiling, and
    that number is what the Confirm gate priced. A copy stage that grew the deck to fit a longer
    source would spend money the operator never approved; one that shrank it would leave a slide
    the estimator paid for unrendered. Positions past the source's own panels render wordless."""
    trend = make_trend(post(1, panels=("One", "Two", "Three", "Four", "Five"),
                            caption="A caption long enough to be a caption at all."))
    call = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})

    short = await copywrite.write_copy([deck_entry(slides=3)], call=call, **context(
        trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))
    over = await copywrite.write_copy([deck_entry(slides=7)], call=StubCall(
        {"d1": selection(headline_ref="", caption_ref="P1.caption")}), **context(
        trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert short.copy["d1"].slide_texts == ["One", "Two", "Three"]
    assert over.copy["d1"].slide_texts == ["One", "Two", "Three", "Four", "Five", "", ""]
    assert len(over.provenance["d1"].panel_map) == 7


def test_panel_slots_are_padded_to_the_declared_panel_count_never_compacted() -> None:
    """§0.14a at the offer: a post that declares eight panels and shipped three texts still has
    eight slides, and slots 4–8 being empty is what tells the mapping to render them wordless
    instead of pulling slide 8's words forward onto slide 4."""
    sparse = make_trend(post(1, panels=("First", "", "Third"),
                             caption="A caption long enough to be a caption at all."))
    sparse.posts[0].panel_count = 6

    offer = _offer(deck_entry(), sparse, deck_style())

    assert offer.panels == ("First", "", "Third", "", "", "")
    assert [c.label for c in offer.onimage if c.kind == "panel"] == ["P1.panel.1", "P1.panel.3"], \
        "an empty slot is not a candidate, and its neighbours keep their own numbers"


# ------------------------------------------------------------------ `_slot_budgets`: the ceiling


def test_the_budget_in_force_is_the_tighter_of_the_style_and_the_config() -> None:
    """Neither outranks the other (§1.3/FR-101): the config budget is the run's ceiling, the
    style's `max_onimage_chars` is what that layout can hold without the text colliding with its
    own artwork, so both apply and the smaller wins."""
    budgets = TextBudgets(image_headline=42, image_subline=60, slide=300,
                          reel_seed_headline=32)

    tight_style = copywrite._slot_budgets(
        make_style(max_onimage_chars={"headline": 34, "subline": 80, "slide": 110}), budgets)
    loose_style = copywrite._slot_budgets(
        make_style(max_onimage_chars={"headline": 200}), budgets)
    no_style = copywrite._slot_budgets(None, budgets)

    assert tight_style["headline"] == 34, "the style is tighter"
    assert tight_style["subline"] == 60, "the config is tighter"
    # D46 §0.5/FR-259: the slide has its OWN config ceiling now. It used to borrow
    # `image_headline`, and borrowing is what made the first paid run's decks wordless — a source
    # panel is a whole thought, not a headline, and an over-budget panel is never trimmed.
    assert tight_style["slide"] == 110, "the style is tighter"
    assert loose_style["headline"] == 42
    assert no_style == {"headline": 42, "subline": 60, "slide": 300, "overlay": 32}


def test_a_zero_or_absent_style_cap_leaves_the_config_budget_in_force() -> None:
    """`max_onimage_chars: {headline: 34, subline: 0, slide: 0}` is how the registry says "this
    style carries a headline and nothing else" — a 0 is not a budget of zero characters here, it
    is the absence of a style-side cap, and the slot's own offerability is decided by
    `_FORMAT_SLOTS` instead."""
    limits = copywrite._slot_budgets(
        make_style(max_onimage_chars={"headline": 34, "subline": 0, "slide": 0}),
        TextBudgets(image_headline=42, image_subline=60, slide=300))

    assert limits["headline"] == 34
    assert limits["subline"] == 60 and limits["slide"] == 300


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
