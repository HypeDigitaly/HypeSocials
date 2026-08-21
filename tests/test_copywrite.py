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
    CopyCompressed,
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


def compressed(**overrides: Any) -> dict[str, Any]:
    """One `CopyCompressed` answer — the D54 contract's shape (FR-331/FR-332).

    Text out, not labels: the compress call is handed the bound post's own admitted panels and
    asked for each of them back shorter. `slide_texts` is POSITION-INDEXED — element *k* is the
    compression of SOURCE PANEL *k+1* — and a blank element means "that source panel had nothing
    to compress", which is why the engine reads it by index and never as a queue.
    """
    payload: dict[str, Any] = {
        "headline": "Wired backwards", "caption": "The tools, in the order that matters.",
        "hashtags": ["#ai", "#tools"], "slide_texts": [], "through_line": "what one prompt buys",
        "narrative_arc": ""}
    payload.update(overrides)
    return payload


def post(number: int, *, views: int = 1_000, caption: str = "", hooks: tuple[str, ...] = (),
         overlays: tuple[str, ...] = (), panels: tuple[str, ...] = (),
         description: str = "", language: str = "") -> SourcePost:
    """One ranked source post. `language` is D63's rung 1 — Virlo's own `language_detected`,
    normalised at the adapter, and empty on every pre-D63 row (which is what "unknown" means)."""
    return SourcePost(post_id=f"p{number}", url=f"https://virlo.test/p/{number}",
                      author=f"@creator{number}", views=views,
                      caption=caption or f"Post {number} caption, as its author wrote it.",
                      hooks=list(hooks) or [f"Hook {number}"], text_overlays=list(overlays),
                      panel_texts=list(panels), description=description, language=language)


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
    # v2.2.0 (FR-99/FR-307 caption forms): the topic name ALONE. A refused post may not be quoted
    # even for a caption, and the operator's niche descriptor is not caption copy at all.
    assert copyset.caption == "AI tool stacks"
    assert "First hook" not in copyset.caption
    assert "AI automation for Czech SMBs" not in copyset.caption
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
    assert result.copy["a1"].caption == "AI tool stacks", "the topic name alone (v2.2.0)"
    assert "First hook" not in result.copy["a1"].caption, "P1 is not a consolation prize"
    assert "AI automation for Czech SMBs" not in result.copy["a1"].caption, "nor is our config"
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
    # Eight keys per row since Session 5.5 (F2): `chrome_counter_stripped` joins the other two
    # per-row facts that are not drop reasons — this deck carried no page counter, so it is False
    # on every row, exactly like `creator_stripped` above it. NINE since v2.3.0 (D54): every row of
    # BOTH walks carries `compressed`, and the verbatim walk writes False on every one of them by
    # construction. The key is asserted here rather than filtered out because "one row schema
    # always" is the contract `generate._panel_map` and the FR-309 gallery read (FR-73 as amended):
    # a reader that had to ask whether the key exists would be reading two schemas.
    assert provenance.panel_map == [
        {"slide": 1, "source_position": 1, "source_text": "Panel one line",
         "source_text_original": "Panel one line", "ref_label": "P1.panel.1", "drop_reason": "",
         "creator_stripped": False, "chrome_counter_stripped": False,
         "truncation_suspect": False, "compressed": False, "translated": False,
         # D65 (v2.9.0, FR-362): the eleventh and twelfth, written on every row of every
         # walk by the contract guards under the same one-row-schema rule. Nothing on
         # this deck named another party and no row was a brand mark, so both are False.
         "identity_scrubbed": False, "chrome_watermark_stripped": False},
        {"slide": 2, "source_position": 2, "source_text": "Panel two line",
         "source_text_original": "Panel two line", "ref_label": "P1.panel.2", "drop_reason": "",
         "creator_stripped": False, "chrome_counter_stripped": False,
         "truncation_suspect": False, "compressed": False, "translated": False,
         # D65 (v2.9.0, FR-362): the eleventh and twelfth, written on every row of every
         # walk by the contract guards under the same one-row-schema rule. Nothing on
         # this deck named another party and no row was a brand mark, so both are False.
         "identity_scrubbed": False, "chrome_watermark_stripped": False},
        {"slide": 3, "source_position": 3, "source_text": "", "source_text_original": "",
         "ref_label": "", "drop_reason": "empty", "creator_stripped": False,
         "chrome_counter_stripped": False, "truncation_suspect": False, "compressed": False,
         "translated": False, "identity_scrubbed": False, "chrome_watermark_stripped": False},
        {"slide": 4, "source_position": 4, "source_text": "Panel four line",
         "source_text_original": "Panel four line", "ref_label": "P1.panel.4", "drop_reason": "",
         "creator_stripped": False, "chrome_counter_stripped": False,
         "truncation_suspect": False, "compressed": False, "translated": False,
         # D65 (v2.9.0, FR-362): the eleventh and twelfth, written on every row of every
         # walk by the contract guards under the same one-row-schema rule. Nothing on
         # this deck named another party and no row was a brand mark, so both are False.
         "identity_scrubbed": False, "chrome_watermark_stripped": False},
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
    row = result.provenance["d1"].panel_map[1]
    # FR-304c (v2.2.0): a runaway panel is a truncation SUSPECT as well as over the ceiling — the
    # flag is contract data for the post-render critic and never a second drop reason, so the row
    # is asserted around it rather than on it.
    assert {key: value for key, value in row.items() if key != "truncation_suspect"} == {
        "slide": 2, "source_position": 2, "source_text": "", "source_text_original": runaway,
        "ref_label": "", "drop_reason": "over_budget", "creator_stripped": False,
        # F2 (Session 5.5): the eighth key. A runaway transcription is not a page counter, so the
        # chrome strip was silent here and the row says so.
        "chrome_counter_stripped": False,
        # D54 (v2.3.0): the ninth. This run is verbatim mode, so nothing on any row compressed.
        "compressed": False,
        # D63 (v2.7.0): the tenth, and False on this walk by construction — the verbatim mapping
        # quotes the source's own bytes in the source's own language. Asserted rather than
        # filtered out for the same "one row schema always" reason `compressed` is.
        "translated": False,
        # D65 (v2.9.0, FR-362): the eleventh and twelfth, from the contract guards. This row ships
        # nothing at all (the panel is past the sanity ceiling), so neither the identity scrub nor
        # the watermark strip had anything to look at — and both keys are still written.
        "identity_scrubbed": False, "chrome_watermark_stripped": False}
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


# ------------------------------------------------ D54/FR-331: the compress contract, end to end
#
# The third call shape beside selection (labels in, bytes resolved here) and free text (an
# override brief's own prose). Compress is the one where a model writes strings that become
# pixels on a creative bound to somebody ELSE's post, so what these tests pin is not "did it
# compress" — it is every gate the engine re-applies on the way out, and the alignment contract
# that keeps our slide *i* over their slide *i* while it does.
#
# `carousel_copy_mode="compress"` is an OPERATOR TOGGLE. Nothing below measures a panel and turns
# it on, because nothing in the engine may: a run is in compress mode or it is not, and the second
# condition (`_panel_mapped`) is structural. That is why every test here passes the mode
# explicitly, and why the verbatim guard near the bottom of this section exists at all.


def compress_deck(*panels: str, caption: str = "A caption long enough to be a caption at all.",
                  key: str = "t1") -> TrendItem:
    """A topic whose top post is a slideshow with `panels` — the compress path's only input."""
    return make_trend(post(1, panels=panels, caption=caption), key=key)


async def compress(entries: Any, call: StubCall, *, log: Any = None, **over: Any) -> Any:
    """`write_copy` in compress mode — the one line every test in this section shares."""
    return await copywrite.write_copy(entries if isinstance(entries, list) else [entries],
                                      call=call, log=log, carousel_copy_mode="compress", **over)


async def test_the_compress_call_uses_its_own_template_and_its_own_schema() -> None:
    """The contract is chosen by the SCHEMA and the TEMPLATE together, not by prose.

    A compress creative must not be sent `copywriter_system.md` (a reference-SELECTION mandate end
    to end — "there is no slot in your answer where invented lettering can go") nor
    `_selection_schema`, whose answer fields are all `*_ref`. Either would make the answer we then
    resolve a shape the model was told not to produce. So: `copy_compressed` on the wire, the
    compress role statement in the system prompt, and the source panels themselves in
    `{{compress_panels}}` instead of a numbered table of labels to choose from.
    """
    trend = compress_deck("Panel one, at the length a real slideshow page carries.",
                          "Panel two, likewise.")
    call = StubCall({"d1": compressed(slide_texts=["Panel one, short", "Panel two, short"])})

    await compress(deck_entry(slides=2), call,
                   **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert call.schemas[0]["name"] == "copy_compressed", "never `copy_selection` on this path"
    prompt = call.prompts[0]
    assert "You compress words a deck already has." in prompt
    assert "Panel one, at the length a real slideshow page carries." in prompt, \
        "the panels themselves are the payload — a label table would be the other contract"
    assert "there is no slot in your answer where invented lettering can go" not in prompt


def test_the_compress_schema_is_generated_from_copycompressed_with_asset_id_on_the_envelope() -> None:
    """The same construction as `_selection_schema` (contracts item 10), so a field added to
    `CopyCompressed` reaches the wire without anybody editing a hand-listed schema — and
    `asset_id` still belongs to the envelope rather than to the answer."""
    schema = copywrite._compress_schema()
    creative = schema["schema"]["properties"]["creatives"]["items"]
    generated = json_schema_for(CopyCompressed, exclude={"asset_id"})["properties"]

    assert schema["name"] == "copy_compressed"
    assert set(creative["properties"]) == {"asset_id", *generated}
    assert list(creative["properties"])[0] == "asset_id"
    assert creative["required"] == list(creative["properties"])  # strict mode (RESULTS.md §E)
    assert creative["additionalProperties"] is False
    assert {"headline", "caption", "hashtags", "slide_texts", "through_line",
            "narrative_arc"} == set(generated)
    assert "motion_beat" not in generated, "compress is carousels only; a reel has no panels"
    assert "slide_refs" not in generated, "a compressed slide quotes no label (FR-302 amended)"


async def test_a_mixed_group_splits_into_one_call_per_MODE_not_one_call_per_creative() -> None:
    """The D54 split, and the reason it is per MODE: one grouped call cannot carry two mandates.

    `copywriter_system.md` tells the model it may not invent lettering; asking half a group to
    compress would make that instruction false for the other half. So a group holding a
    panel-mapped carousel and an image takes exactly two calls — one per contract — and each one
    lists only its own creatives. It is still ONE call on the shipped configs, which are
    all-carousel; a genuinely mixed group is the one shape that pays for two.
    """
    trend = make_trend(post(1, panels=("Panel one line", "Panel two line"),
                            caption="A caption long enough to be a caption at all."),
                       post(2, hooks=("An image hook",),
                            caption="A second caption, plainly written."))
    entries = [deck_entry("d1", slides=2), entry("i1", 1, source_post_id="p2")]
    call = StubCall({"d1": compressed(slide_texts=["Panel one", "Panel two"]),
                     "i1": selection(headline_ref="P2.hook.1", caption_ref="P2.caption")})

    result = await compress(entries, call,
                            **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert sorted(call.calls) == [["d1"], ["i1"]], "one call per contract, neither mixed"
    assert sorted(schema["name"] for schema in call.schemas) == ["copy_compressed",
                                                                "copy_selection"]
    assert result.copy["d1"].slide_texts == ["Panel one", "Panel two"]
    assert result.copy["i1"].headline == "An image hook", "the image still SELECTS, verbatim"
    assert result.provenance["d1"].copy_mode == "compress"
    assert result.provenance["i1"].copy_mode == "verbatim", "the mode is per CREATIVE, not per run"


async def test_a_model_list_shorter_than_the_deck_pads_and_a_longer_one_is_truncated() -> None:
    """1:1 alignment is the ENGINE's, never the model's. The deck's length was fixed at ASSIGN and
    priced at the Confirm gate (§0.4'), so a short answer leaves the tail wordless rather than
    shrinking the deck, and a long one cannot buy a slide nobody paid for."""
    log = Recorder()
    trend = compress_deck("Panel one", "Panel two", "Panel three")
    short = StubCall({"d1": compressed(slide_texts=["Only one"])})
    long_answer = StubCall({"d1": compressed(slide_texts=["A", "B", "C", "D", "E"])})

    padded = await compress(deck_entry(slides=3), short,
                            **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))
    cut = await compress(deck_entry(slides=3), long_answer, log=log,
                         **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert padded.copy["d1"].slide_texts == ["Only one", "", ""]
    assert [row["slide"] for row in padded.provenance["d1"].panel_map] == [1, 2, 3], \
        "a short answer never shortens the deck — the rows are the alignment"
    assert cut.copy["d1"].slide_texts == ["A", "B", "C"]
    assert len(cut.provenance["d1"].panel_map) == 3
    assert "returned 5 slide texts for a 3-slide deck" in log.warned("compress_list_truncated")[0]


async def test_a_source_empty_position_stays_empty_even_when_the_model_answered_for_it() -> None:
    """Compression fills no vacuums (FR-331).

    An empty source panel means the source slide had no words. A slide of ours carrying words
    theirs never had is the `invented_text` defect the post-render gate blocks whole decks for —
    and it is the defect compress mode was adopted to REDUCE, so producing it here would be the
    mode arguing with its own reason to exist. The line is discarded, the row keeps its `empty`
    drop reason and its position, and the operator is told exactly what was thrown away.
    """
    log = Recorder()
    trend = compress_deck("Panel one", "", "Panel three")
    call = StubCall({"d1": compressed(
        slide_texts=["First, shortened", "A slide the source never had", "Third, shortened"])})

    result = await compress(deck_entry(slides=3), call, log=log,
                            **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    rows = result.provenance["d1"].panel_map
    assert result.copy["d1"].slide_texts == ["First, shortened", "", "Third, shortened"]
    assert rows[1]["drop_reason"] == "empty" and rows[1]["source_text"] == ""
    assert [row["source_position"] for row in rows] == [1, 2, 3], "position kept, nothing slides up"
    invented = log.warned("compress_invented_text")
    assert len(invented) == 1 and "slide 2" in invented[0]
    assert "A slide the source never had" in invented[0], "the operator sees what was discarded"


async def test_the_drop_taxonomy_is_the_verbatim_one_judged_on_the_SOURCE_panel() -> None:
    """FR-304a as amended: the same three drop reasons, in the same order, on the same string.

    `_panel_verdict` runs on the SOURCE panel before the model's line is looked at, exactly as it
    does in verbatim mode — which is why compression cannot rescue a dropped panel and is not
    meant to. `PANEL_SANITY_CHARS` in particular stays an INPUT guard: a 1,600-character panel is
    a transcription accident, and a confident compression of an accident is worse than a wordless
    slide.
    """
    log = Recorder()
    runaway = "W" * 1600
    trend = compress_deck("", "Follow @growthdaily for more", runaway, "A perfectly good panel")
    call = StubCall({"d1": compressed(
        slide_texts=["one", "two", "three", "A shorter, perfectly good panel"])})

    result = await compress(deck_entry(slides=4), call, log=log,
                            **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    rows = result.provenance["d1"].panel_map
    assert [row["drop_reason"] for row in rows] == [
        "empty", "contains_handle_or_url", "over_budget", ""]
    assert result.copy["d1"].slide_texts == ["", "", "", "A shorter, perfectly good panel"]
    assert rows[2]["source_text_original"] == runaway, "the pre-gate panel survives in the row"
    assert "sanity ceiling 1500" in log.warned("panel_over_budget")[0]
    assert "slide 2 (carries an @handle)" in log.warned("panel_handle_or_url")[0]
    assert "never compressed" in log.warned("panel_over_budget")[0], \
        "the warning must say the panel was not compressed either, or it reads as a length rule"


async def test_a_compressed_line_carrying_a_handle_or_a_url_is_BLANKED_and_warned() -> None:
    """FR-319 re-applied on the way OUT, because a compressed line is the model's own bytes.

    The line is removed WHOLE rather than edited: a compressed sentence with its @handle cut out
    is a sentence nobody wrote and nobody proof-read. The source panel here is clean, so this can
    only be the model copying a mark it read elsewhere on the page — which is exactly why the gate
    runs on both sides.
    """
    log = Recorder()
    trend = compress_deck("A clean panel about the workflow", "Another clean panel")
    call = StubCall({"d1": compressed(
        slide_texts=["The workflow, via @growthdaily", "Another clean line"])})

    result = await compress(deck_entry(slides=2), call, log=log,
                            **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    rows = result.provenance["d1"].panel_map
    assert result.copy["d1"].slide_texts == ["", "Another clean line"]
    assert rows[0]["drop_reason"] == "", "the SOURCE panel was fine — this is not a source drop"
    assert rows[0]["source_text"] == ""
    assert rows[0]["source_text_original"] == "A clean panel about the workflow"
    scrub = log.warned("compress_scrub")
    assert len(scrub) == 1 and "slide 1 (carries an @handle)" in scrub[0]
    assert "BLANKED" in scrub[0]


async def test_a_competitor_name_in_a_compressed_line_is_stripped_fail_closed() -> None:
    """§1.5 layer 1 runs on what came BACK, unguarded, and before anything else.

    The model may write a name the panels never contained — it can read one in the fenced trend
    texts — so the blocklist is applied to the compressed line, not only to the panel it was
    compressing. It runs FIRST of the three backstops because a name removed from a string changes
    its length, and trimming before stripping would measure a budget against bytes we do not ship.
    """
    log = Recorder()
    trend = compress_deck("A panel about scheduling posts", "A second panel")
    call = StubCall({"d1": compressed(slide_texts=["Nitro schedules the posts", "Second line"])})

    result = await compress(deck_entry(slides=2), call, log=log, competitors=["Nitro"],
                            **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert "Nitro" not in result.copy["d1"].slide_texts[0]
    assert DegradationTag.COMPETITOR_STRIPPED in result.tags["d1"]
    assert "the strip runs on both sides" in log.warned("competitor_stripped")[0]
    assert DegradationTag.COPY_NOT_VERBATIM not in result.tags["d1"], \
        "a compressed deck claims no byte identity, so the substring audit has nothing to report"


async def test_the_backstop_trim_cuts_at_a_word_boundary_and_tags_text_trimmed() -> None:
    """The trim is a BACKSTOP, not the mechanism: the prompt states the ceiling and the model is
    asked to meet it. A line that still overshoots is cut at the last word boundary — never
    mid-word — and earns FR-101's tag, so the operator knows the model was late rather than the
    rule."""
    log = Recorder()
    over = "A compressed line that still runs well past the ceiling it was given"
    trend = compress_deck("A source panel with plenty of words in it to shorten.")
    call = StubCall({"d1": compressed(slide_texts=[over])})

    result = await compress(deck_entry(slides=1), call, log=log, **context(
        trends={"t1": trend},
        styles={STYLE_KEY: make_style(max_onimage_chars={"headline": 90, "slide": 30})}))

    shipped = result.copy["d1"].slide_texts[0]
    assert len(shipped) <= 30 and over.startswith(shipped)
    assert shipped.split()[-1] in over.split(), "cut at a word boundary, never mid-word"
    assert DegradationTag.TEXT_TRIMMED in result.tags["d1"] and result.trimmed == frozenset({"d1"})
    assert "against a 30-character budget" in log.warned("text_trimmed")[0]
    assert result.provenance["d1"].panel_map[0]["source_text"] == shipped, \
        "the row records what SHIPPED, so it moves with the trim"


async def test_the_compressed_decks_panel_map_rows_are_the_receipt_the_gallery_reads() -> None:
    """FR-73/FR-304(d)/FR-309, as one row-by-row assertion.

    Four claims and each is load-bearing: `compressed: True` tells the auditor not to expect byte
    identity, `source_text` is what SHIPS (the same string the render prompt locked and the
    gauntlet will demand), `source_text_original` is the model's own starting point (the length
    FR-309's card labels "compressed from N chars" off), and `ref_label` is EMPTY because a
    compressed slide quotes no label — FR-302 as amended.
    """
    trend = compress_deck("Panel one, written out at the length a real page carries.",
                          "", "Panel three, likewise long enough to be worth compressing.")
    call = StubCall({"d1": compressed(slide_texts=["One, short", "ignored", "Three, short"])})

    result = await compress(deck_entry(slides=3), call,
                            **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    copyset, provenance = result.copy["d1"], result.provenance["d1"]
    rows = provenance.panel_map
    assert all(row["compressed"] is True for row in rows), "every row of the walk, drops included"
    assert [row["source_text"] for row in rows] == copyset.slide_texts, \
        "ONE walk: `slide_texts[i]` and `panel_map[i].source_text` are the same string by " \
        "construction — the invariant `gauntlet._expected_blocks` rests on"
    assert rows[0]["source_text_original"] == \
        "Panel one, written out at the length a real page carries."
    assert len(rows[0]["source_text"]) < len(rows[0]["source_text_original"])
    assert all(row["ref_label"] == "" for row in rows), "FR-302: no labels on this path"
    assert provenance.refs == {} and provenance.post_id == "p1"
    assert provenance.source_panel_count == 3


async def test_a_failed_compress_call_ships_the_verbatim_mapped_deck_and_says_copy_degraded() -> None:
    """The fallback is today's FR-304 mapped deck, and it costs nothing extra.

    Long slides are the outcome the operator opted OUT of, not a loss of the deck — so a compress
    call that dies falls straight onto the deterministic verbatim mapping, tagged `copy_degraded`,
    with no second call. And the receipt tells the truth about what actually shipped: `copy_mode`
    is `verbatim` on the creative even though the RUN asked for compress, because a per-asset
    receipt reading "compressed" over verbatim panels would hide the degradation.
    """
    log = Recorder()
    trend = compress_deck("Panel one line", "Panel two line")
    call = StubCall({"d1": compressed(slide_texts=["never seen"])}, fail_when=lambda ids: True)

    result = await compress(deck_entry(slides=2), call, log=log,
                            **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert result.copy["d1"].slide_texts == ["Panel one line", "Panel two line"], "verbatim"
    assert DegradationTag.COPY_DEGRADED in result.tags["d1"]
    assert result.provenance["d1"].copy_mode == "verbatim"
    assert all(row["compressed"] is False for row in result.provenance["d1"].panel_map)
    assert result.provenance["d1"].refs["slide_1"] == "P1.panel.1", "the labels are back"
    assert log.warned("copy_degraded")


async def test_a_creative_a_grouped_compress_call_missed_is_re_asked_to_COMPRESS() -> None:
    """FR-99's per-creative split, re-dispatched through each creative's OWN contract.

    Re-asking a compress creative through `_call_copy` would answer with refs into a candidate
    table whose panels this deck's slides are already assigned from — and the deck would ship
    verbatim under a `copy_mode: compress` receipt, which is a receipt that lies.
    """
    trend = compress_deck("Panel one line", "Panel two line")
    call = StubCall({"d1": compressed(slide_texts=["One, short", "Two, short"]),
                     "d2": compressed(slide_texts=["One, short", "Two, short"])},
                    fail_when=lambda ids: len(ids) > 1)
    entries = [deck_entry("d1", slides=2), deck_entry("d2", slides=2)]

    result = await compress(entries, call,
                            **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert call.calls[0] == ["d1", "d2"] and sorted(call.calls[1:]) == [["d1"], ["d2"]]
    assert all(schema["name"] == "copy_compressed" for schema in call.schemas), \
        "every re-ask took the compress schema — never the selection one"
    assert result.copy["d1"].slide_texts == ["One, short", "Two, short"]
    assert result.provenance["d2"].copy_mode == "compress"


async def test_compress_mode_leaves_every_creative_that_is_not_a_bound_deck_alone() -> None:
    """`_compress_wanted` is `mode is compress AND _panel_mapped`, and the second half is
    structural: an image, an override brief and an UNBOUND carousel have no panel mapping of their
    own, so a compress-mode run touches none of them — and issues no compress call at all when the
    partition comes out empty."""
    trend = make_trend(post(1, hooks=("An image hook",), panels=("Panel one",),
                            caption="A caption long enough to be a caption at all."))
    entries = [entry("i1", 0, source_post_id="p1"),
               entry("c1", 1, creative_format="carousel", aspect_ratio="1:1", slide_count=1),
               entry("b1", 2, trend_key=None, brief_name="b", brief_influence="override")]
    call = StubCall({"i1": selection(headline_ref="P1.hook.1", caption_ref="P1.caption"),
                     "c1": selection(headline_ref="", caption_ref="P1.caption",
                                     slide_refs=["P1.panel.1"]),
                     "b1": free_text()})

    result = await compress(entries, call,
                            **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert "copy_compressed" not in [schema["name"] for schema in call.schemas], \
        "an empty compress partition issues no compress call at all"
    assert all(prov.copy_mode == "verbatim" for prov in result.provenance.values())
    assert result.copy["c1"].slide_texts == ["Panel one"], "the unbound selection path, untouched"


async def test_verbatim_mode_never_issues_a_compress_call_on_a_bound_deck() -> None:
    """The byte-identical regression guard, stated as the one thing that must not happen.

    Verbatim is the engine-wide default and D50 still governs it — reflow, never shorten. The
    FR-304 section above already pins what a verbatim mapped deck produces; what it cannot pin is
    that D54 stayed behind its toggle, because it never passes a mode at all. So: the same deck,
    the default mode, and no compress anything on the wire, in the prompt or in the receipts.
    """
    trend = compress_deck("Panel one, written out at the length a real page carries.",
                          "Panel two, likewise.")
    call = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})

    result = await copywrite.write_copy(  # no `carousel_copy_mode` — the default IS the point
        [deck_entry(slides=2)], call=call,
        **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert [schema["name"] for schema in call.schemas] == ["copy_selection"]
    assert "You compress words a deck already has." not in call.prompts[0]
    assert "compress post P1's panels" not in call.prompts[0]
    assert result.copy["d1"].slide_texts == [
        "Panel one, written out at the length a real page carries.", "Panel two, likewise."], \
        "D50 in force: the panel ships whole, at whatever length it is"
    assert result.provenance["d1"].copy_mode == "verbatim"
    assert result.provenance["d1"].refs["slide_1"] == "P1.panel.1"
    assert all(row["compressed"] is False for row in result.provenance["d1"].panel_map)


def test_positional_keeps_blanks_because_the_index_is_the_contract() -> None:
    """The silent-remap trap, closed at the primitive.

    `_strings` — which every other consumer in the module wants — DROPS blank items, so a model
    answering `["", "second"]` would have "second" land on slide 1 and its own slide 2 render
    wordless. That is a deck reading as the source's with two slides swapped, which is precisely
    the defect FR-304's index alignment exists to make impossible. `_positional` is the reading
    that keeps the blank, and this is the assertion that keeps the two functions apart.
    """
    assert copywrite._positional(["", "second"]) == ["", "second"]
    assert copywrite._strings(["", "second"]) == ["second"], "the OTHER reading, and why it hurts"
    assert copywrite._positional(["a", None, "c"]) == ["a", "", "c"], "None is a blank, not a gap"
    assert copywrite._positional("one line") == ["one line"]
    assert copywrite._positional(None) == [] and copywrite._positional(7) == []


async def test_a_model_blank_at_position_one_leaves_slide_one_wordless_not_slide_two() -> None:
    """The same trap at the level that ships bytes: a blank first answer must not pull slide 2's
    line forward. Both source panels have words, so nothing here is a source drop — the only thing
    under test is which slide the model's one sentence lands on."""
    log = Recorder()
    trend = compress_deck("Panel one has words of its own.", "Panel two also has words.")
    call = StubCall({"d1": compressed(slide_texts=["", "second"])})

    result = await compress(deck_entry(slides=2), call, log=log,
                            **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert result.copy["d1"].slide_texts == ["", "second"], "never ['second', '']"
    rows = result.provenance["d1"].panel_map
    assert rows[0]["source_text"] == "" and rows[0]["drop_reason"] == "", \
        "the source panel was admitted; it is the ANSWER that was empty"
    assert rows[1]["source_text"] == "second"
    assert "slide 1" in log.warned("compress_no_text")[0], \
        "an admitted panel back with nothing is worth a word — the source slide HAS text"


async def test_a_compressed_deck_that_came_back_empty_ships_caption_only_and_says_why() -> None:
    """The `no_onimage_text` degrade on the compress path names the re-run that would fix it: the
    panels themselves are intact, so a verbatim re-run renders them in full."""
    log = Recorder()
    trend = compress_deck("Panel one has words.", "Panel two has words.")
    call = StubCall({"d1": compressed(headline="", slide_texts=["", ""])})

    result = await compress(deck_entry(slides=2), call, log=log,
                            **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert result.copy["d1"].slide_texts == ["", ""]
    assert DegradationTag.NO_ONIMAGE_TEXT in result.tags["d1"]
    assert "a re-run in verbatim mode would render them in full" in log.warned("no_onimage_text")[0]


async def test_the_compressed_caption_is_refused_whole_when_it_carries_a_social_mark() -> None:
    """A caption is the one string this engine publishes as prose, and an @handle or a
    link-in-bio URL in it points our audience at an account that is not ours. It is refused
    OUTRIGHT rather than edited, and the creative captions itself from its own post's best
    remaining line under a neutral attribution — the same form `_resolve` falls back to."""
    log = Recorder()
    trend = compress_deck("Panel one has words.", "Panel two has words.")
    call = StubCall({"d1": compressed(caption="Great stuff - follow @growthdaily for more",
                                      hashtags=["#ai"], slide_texts=["One", "Two"])})

    result = await compress(deck_entry(slides=2), call, log=log,
                            **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    caption = result.copy["d1"].caption
    assert "@growthdaily" not in caption and caption.strip()
    assert result.copy["d1"].hashtags == [], "a refused caption takes its tags with it"
    assert "carries an @handle" in log.warned("compress_caption_rejected")[0]


async def test_a_blocklisted_hashtag_from_the_compress_call_is_dropped_whole() -> None:
    """A hashtag is ONE token and cannot be part-stripped, so a blocklisted or identity-bearing
    tag is removed entire (§1.5, FR-319) — and `_verify`'s blocklist half re-checks what ships."""
    log = Recorder()
    trend = compress_deck("A panel about scheduling posts.")
    call = StubCall({"d1": compressed(hashtags=["#ai", "#nitro", "#tools"],
                                      slide_texts=["A shorter panel"])})

    result = await compress(deck_entry(slides=1), call, log=log, competitors=["Nitro"],
                            **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert result.copy["d1"].hashtags == ["#ai", "#tools"]
    assert "'#nitro'" in log.warned("competitor_stripped")[0]


async def test_the_compress_sibling_line_names_the_post_the_budget_and_the_mirror_rule() -> None:
    """`_sibling_list(compress=True)` — one line per creative, stating the language rule in force.

    Three facts, each answering a question the model would otherwise guess at: WHICH section of
    `{{compress_panels}}` is this creative's, WHAT number it is being cut to, and WHOSE language
    the answer is in. The engine detects no languages (§1.7.5) and must not start now, so the rule
    names the panels rather than a language — checkable by the model against text it can see.
    """
    trend = compress_deck("Panel one has words.", "Panel two has words.")
    call = StubCall({"d1": compressed(slide_texts=["One", "Two"])})

    await compress(deck_entry(slides=2), call,
                   **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    line = next(l for l in call.prompts[0].splitlines() if l.startswith("- d1"))
    assert "compress post P1's panels to 300 characters per slide" in line
    assert "language: the panels' own, mirrored exactly, never translated" in line
    assert "quote post P1" not in line, "the verbatim clause is REPLACED, not appended"
    assert "as-selected" not in line


async def test_the_compress_block_lists_only_admitted_panels_numbered_by_source_position() -> None:
    """The block is the compress contract's whole input, and an UNLISTED number is the instruction
    that the slide ships wordless. Numbering by SOURCE POSITION rather than re-numbering 1..N is
    what keeps the answer alignable: the model returns one entry per slide of the deck, `""` for
    the positions it was not given, and `slide_texts[i - 1]` is read by index."""
    trend = compress_deck("Panel one has words.", "", "Panel three has words.")
    call = StubCall({"d1": compressed(slide_texts=["One", "", "Three"])})

    await compress(deck_entry(slides=3), call,
                   **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    block = call.prompts[0]
    assert "1. (at most 300 characters) Panel one has words." in block
    assert "3. (at most 300 characters) Panel three has words." in block
    assert "\n2. (at most" not in block, "an empty panel is UNLISTED — that is the instruction"
    assert "caption source: A caption long enough to be a caption at all." in block
    assert "mirror it exactly and never translate" in block


async def test_a_panel_is_shown_to_the_compress_call_IN_FULL_never_display_truncated() -> None:
    """The verbatim candidate table may truncate for display, because the engine ships the ORIGINAL
    bytes of whatever label the model names. Here the shown text IS the material being compressed,
    so a truncated panel would be compressed into a lie."""
    long_panel = "Panel one. " + "It keeps explaining the point at length. " * 11  # ~470 chars
    assert len(long_panel) > copywrite._DISPLAY_CHARS
    trend = compress_deck(long_panel)
    call = StubCall({"d1": compressed(slide_texts=["A short compression of it"])})

    await compress(deck_entry(slides=1), call,
                   **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    assert long_panel in call.prompts[0]
    assert "…[truncated for display]" not in call.prompts[0]


# ------------------------------------------ D62/FR-353: auto mode — compress ONLY what overflows
#
# Auto is compress's contract applied per PANEL instead of per DECK, and it is what the three
# shipped brand configs pin. Two claims carry the whole mode and every test below serves one of
# them:
#
# 1. **A deck with nothing over budget is a VERBATIM run, byte for byte** — no compress call, no
#    compress template, no `compressed` row, `copy_mode: verbatim` on the receipt. That is FR-353's
#    acceptance criterion, and it is why auto could take a shipped pin where `compress` could not.
# 2. **A deck with something over budget is MIXED, and the mix is per row** — the overflowing
#    positions carry the model's line, every other position carries the source's bytes and its own
#    `P<n>.panel.<i>` label, and no row is ever moved.
#
# The budget under test is 40 characters (`auto_style`), small enough that an ordinary sentence
# overflows it and a short one does not — which is the only distinction this mode turns on.


def auto_style(**overrides: Any) -> MetaStyle:
    """A deck style declaring a 40-character slide budget — the ceiling these tests measure against.

    `deck_style`'s 300 is realistic for the registry and useless here: a panel long enough to beat
    it is a wall of text nobody would read in a test, and the interesting cases are one short panel
    beside one long one. 40 is the same rule at a readable scale, and `_slot_budgets` reduces it
    exactly as it reduces 300 (`min(text_budgets.slide, max_onimage_chars.slide)`).
    """
    return make_style(max_onimage_chars={"headline": 90, "subline": 60, "slide": 40}, **overrides)


#: One panel comfortably inside the 40-character budget, and one comfortably outside it. Named
#: rather than inlined because half these tests assert on the exact bytes surviving a splice.
SHORT = "Short one."
LONG = "A panel that runs well past the forty character budget this style declares."


async def auto(entries: Any, call: StubCall, *, log: Any = None, **over: Any) -> Any:
    """`write_copy` in auto mode — the one line every test in this section shares."""
    return await copywrite.write_copy(entries if isinstance(entries, list) else [entries],
                                      call=call, log=log, carousel_copy_mode="auto", **over)


def test_rows_over_budget_is_a_pure_measurement_and_nothing_else() -> None:
    """The primitive FR-353 turns on, pinned on its own because two callers must never disagree.

    `_compress_wanted` asks it "is there anything to compress at all" and `_auto` asks it "which
    positions"; if those two answers ever came apart, a deck would pay for a call whose answer it
    then refused to splice, or splice one it never asked for. It stays a pure function of a list
    and a number — SESSION N calls it on a TRANSLATED deck, where the strings are not
    `offer.panels` at all.
    """
    assert copywrite._rows_over_budget([], 40) == []
    assert copywrite._rows_over_budget(["", "", ""], 40) == [], "an empty row is never over"
    assert copywrite._rows_over_budget(["x" * 40], 40) == [], "AT the budget is not OVER it"
    assert copywrite._rows_over_budget(["x" * 41], 40) == [1], "one character over is over"
    assert copywrite._rows_over_budget([SHORT, LONG, SHORT, LONG, SHORT], 40) == [2, 4]
    assert copywrite._rows_over_budget([LONG], 0) == [], (
        "no budget means no ceiling: reading a missing slot as a ceiling of zero would send a "
        "whole deck to the compress call on the strength of a slot that does not exist")


def test_admitted_texts_blanks_every_dropped_position_and_says_nothing_about_it() -> None:
    """The input `_rows_over_budget` measures: the deck by position, with FR-304's own verdict
    applied and NOTHING logged.

    Two things it must get right. A panel that will render wordless — empty, carrying a social
    mark, past the sanity ceiling — measures as `""` and can never be counted as over budget, so
    the compress call is never asked about a slide that ships blank. And the pass is silent:
    `_mapped_deck` warns about those same three drops once per creative when it runs, and it runs
    on the auto path too, so a measuring pass that warned as well would double every one of them.
    """
    log = Recorder()
    runaway = "W" * (copywrite.PANEL_SANITY_CHARS + 1)
    trend = compress_deck(LONG, "", "Follow @growthdaily for more", runaway)
    plan_entry = deck_entry(slides=4)
    offer = _offer(plan_entry, trend, auto_style(), log=log)

    admitted = copywrite._admitted_texts(plan_entry, offer)

    assert admitted == [LONG, "", "", ""], "the three drop reasons all blank their position"
    assert copywrite._rows_over_budget(admitted, 40) == [1], \
        "the runaway past the sanity ceiling is a DROPPED panel, not the longest one"
    assert log.warnings == [], "measuring warns about nothing; `_mapped_deck` owns those three"


async def test_an_auto_deck_with_nothing_over_budget_is_a_verbatim_run_byte_for_byte() -> None:
    """FR-353's acceptance criterion, asserted as equality against the verbatim run itself.

    Every panel of this deck already fits its style's budget, so there is nothing to compress and
    auto must cost nothing and change nothing: the SELECTION schema on the wire, the copywriter
    template in the prompt, no compress anything, and a `CopySet` and a `CopyProvenance` equal to
    what the same inputs produce with no mode passed at all — `copy_mode: verbatim` included,
    because that is what this creative actually shipped.

    Comparing whole objects rather than a field at a time is the point. A future edit that added a
    tag, dropped a ref, or wrote `compressed: False` rows through some new path would pass a
    field-by-field test and fail this one.
    """
    trend = compress_deck(SHORT, "Short two.", "Short three.")
    live = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})
    control = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})
    scene: dict[str, Any] = dict(trends={"t1": trend}, styles={STYLE_KEY: auto_style()})

    automatic = await auto(deck_entry(slides=3), live, **context(**scene))
    verbatim = await copywrite.write_copy([deck_entry(slides=3)], call=control,
                                          **context(**scene))

    assert [schema["name"] for schema in live.schemas] == ["copy_selection"], \
        "no compress call: the partition was empty, so there was nothing to pay a model for"
    assert "You compress words a deck already has." not in live.prompts[0]
    assert "compress post P1's panels" not in live.prompts[0]
    assert automatic.copy["d1"] == verbatim.copy["d1"]
    assert automatic.provenance["d1"] == verbatim.provenance["d1"]
    assert automatic.provenance["d1"].copy_mode == "verbatim", "what it shipped, not what it ran"
    assert automatic.tags == verbatim.tags == {}


async def test_only_the_over_budget_positions_are_asked_for_and_only_they_are_spliced() -> None:
    """The mode's whole shape in one deck: five slides, two of them too long.

    Three surfaces have to agree, and this asserts all three from one run. The PROMPT lists panels
    2 and 4 alone, numbered by source position and each with its budget. The SIBLING line says
    which positions those are, that everything else ships verbatim, and that unprinted positions
    take `""`. And the RESULT is mixed per row: 2 and 4 carry the model's lines with no ref label
    and `compressed: True`, while 1, 3 and 5 carry the source's own bytes under their own
    `P1.panel.<i>` labels — every row in its own position, as FR-304 has always required.
    """
    trend = compress_deck(SHORT, LONG, "Short three.", LONG, "Short five.")
    call = StubCall({"d1": compressed(slide_texts=["", "short two", "", "short four", ""])})

    result = await auto(deck_entry(slides=5), call,
                        **context(trends={"t1": trend}, styles={STYLE_KEY: auto_style()}))

    prompt = call.prompts[0]
    assert call.schemas[0]["name"] == "copy_compressed"
    assert "\n2. (at most 40 characters) " + LONG in prompt
    assert "\n4. (at most 40 characters) " + LONG in prompt
    for skipped in ("\n1. (at most", "\n3. (at most", "\n5. (at most"):
        assert skipped not in prompt, "a panel that already fits is not paid for a second time"
    line = next(l for l in prompt.splitlines() if l.startswith("- d1"))
    assert "compress post P1's panels 2, 4 (the ones over 40 characters) to 40 characters" in line
    assert "every other panel of this deck ships verbatim and is not printed" in line
    assert 'answer "" for every position not printed' in line
    assert "language: the panels' own, mirrored exactly, never translated" in line

    copy = result.copy["d1"]
    rows = result.provenance["d1"].panel_map
    assert copy.slide_texts == [SHORT, "short two", "Short three.", "short four", "Short five."]
    assert [row["source_position"] for row in rows] == [1, 2, 3, 4, 5], "nothing moved"
    assert [row["compressed"] for row in rows] == [False, True, False, True, False]
    for position in (2, 4):
        row = rows[position - 1]
        assert row["ref_label"] == "", "FR-302 as amended: a compressed slide quotes no label"
        assert row["source_text"] == copy.slide_texts[position - 1]
        assert row["source_text_original"] == LONG, "the panel it was authored from, kept whole"
    for position in (1, 3, 5):
        row = rows[position - 1]
        assert row["ref_label"] == f"P1.panel.{position}"
        assert row["source_text"] == row["source_text_original"] == copy.slide_texts[position - 1]
    assert result.provenance["d1"].refs == {"slide_1": "P1.panel.1", "slide_3": "P1.panel.3",
                                            "slide_5": "P1.panel.5"}
    assert result.provenance["d1"].copy_mode == "auto"
    assert result.tags.get("d1", ()) == (), "nothing was lost, so nothing is tagged"


async def test_an_over_budget_row_answered_empty_keeps_its_verbatim_bytes() -> None:
    """Long beats wordless (FR-353), and it is the one place auto deliberately diverges from
    `_compressed_deck`.

    A compress-mode deck that gets nothing back for an admitted panel ships that slide blank — it
    has no verbatim row to fall back to. An auto deck does: the panel is over a DESIGN budget, not
    over `PANEL_SANITY_CHARS`, so it is a real slide with real words, and rendering it long is
    strictly better than rendering it empty. The row stays a quote — its label, its bytes,
    `compressed: False` — and the creative is not tagged, because nothing was lost.
    """
    log = Recorder()
    trend = compress_deck(SHORT, LONG)
    call = StubCall({"d1": compressed(slide_texts=["", ""])})

    result = await auto(deck_entry(slides=2), call, log=log,
                        **context(trends={"t1": trend}, styles={STYLE_KEY: auto_style()}))

    rows = result.provenance["d1"].panel_map
    assert result.copy["d1"].slide_texts == [SHORT, LONG]
    assert rows[1]["compressed"] is False and rows[1]["ref_label"] == "P1.panel.2"
    assert rows[1]["source_text"] == LONG
    assert result.provenance["d1"].refs["slide_2"] == "P1.panel.2"
    kept = log.warned("auto_row_kept_verbatim")
    assert len(kept) == 1 and "slide 2" in kept[0]
    assert "came back empty from the compress call and ship verbatim" in kept[0]
    assert "NOT tagged" in kept[0], "the operator is told this cost the deck nothing"
    assert result.tags.get("d1", ()) == ()
    assert log.warned("compress_no_text") == [], "that is the OTHER mode's finding and its wording"


async def test_a_line_written_for_a_position_that_already_fits_is_discarded_and_warned() -> None:
    """The model was not asked about slide 1 — its panel fits and is already quoted verbatim there
    — so a line for it is either an invention or an unrequested rewrite of a string we are entitled
    to quote. Either way it is thrown away, the source bytes stand, and the operator is shown what
    was discarded, exactly as `compress_invented_text` shows them on the other mode."""
    log = Recorder()
    trend = compress_deck(SHORT, LONG)
    call = StubCall({"d1": compressed(
        slide_texts=["I rewrote your short slide anyway", "short two"])})

    result = await auto(deck_entry(slides=2), call, log=log,
                        **context(trends={"t1": trend}, styles={STYLE_KEY: auto_style()}))

    assert result.copy["d1"].slide_texts == [SHORT, "short two"]
    rows = result.provenance["d1"].panel_map
    assert rows[0]["compressed"] is False and rows[0]["ref_label"] == "P1.panel.1"
    discarded = log.warned("auto_row_discarded")
    assert len(discarded) == 1 and "slide 1" in discarded[0]
    assert "I rewrote your short slide anyway" in discarded[0], "the operator sees what went"
    assert "it was not asked about" in discarded[0]


async def test_a_failed_auto_call_ships_the_whole_deck_verbatim_and_says_copy_degraded() -> None:
    """Auto's whole-call failure path is `_mapped_fallback`, unchanged and shared with compress.

    It is the cheapest possible failure: the rows that already fitted were shipping verbatim
    anyway, and the ones that overflowed ship long — which is the pre-D62 outcome, not a loss of
    the deck. `copy_degraded` still tags it because a failed LLM call is a loss FR-248 counts, and
    the receipt says `verbatim` because that is what these slides are.
    """
    log = Recorder()
    trend = compress_deck(SHORT, LONG)
    call = StubCall({"d1": compressed(slide_texts=["", "short two"])}, fail_when=lambda ids: True)

    result = await auto(deck_entry(slides=2), call, log=log,
                        **context(trends={"t1": trend}, styles={STYLE_KEY: auto_style()}))

    assert result.copy["d1"].slide_texts == [SHORT, LONG], "every row verbatim, none blank"
    assert DegradationTag.COPY_DEGRADED in result.tags["d1"]
    assert result.provenance["d1"].copy_mode == "verbatim", "what shipped, not what was asked for"
    assert all(row["compressed"] is False for row in result.provenance["d1"].panel_map)
    assert result.provenance["d1"].refs == {"slide_1": "P1.panel.1", "slide_2": "P1.panel.2",
                                            "caption": "P1.caption"}, \
        "`_mapped_fallback` picks the bound post's own caption too — that is the whole tier"
    assert "copy call failed" in log.warned("copy_degraded")[0]


async def test_a_spliced_line_faces_the_blocklist_and_the_backstop_trim_like_any_other() -> None:
    """A spliced line is the MODEL's bytes, so `_compress_field` runs on it exactly as it does on
    the compress path — same function, same order, same tags.

    Two findings, one run each. A blocklisted competitor name is stripped fail-closed and the
    creative is tagged `competitor_stripped`; a line that comes back over the budget the prompt
    asked for is cut at the last word boundary and tagged `text_trimmed`. Neither is a rule being
    applied late: the strip is §1.5 and the trim is a backstop behind a prompt that stated the
    number.
    """
    log = Recorder()
    trend = compress_deck(SHORT, LONG)
    scene: dict[str, Any] = dict(trends={"t1": trend}, styles={STYLE_KEY: auto_style()})

    stripped = await auto(deck_entry(slides=2),
                          StubCall({"d1": compressed(slide_texts=["", "Nitro makes it quick"])}),
                          log=log, competitors=["Nitro"], **context(**scene))
    overshot = await auto(
        deck_entry(slides=2),
        StubCall({"d1": compressed(
            slide_texts=["", "A compressed line that itself runs past the forty ceiling"])}),
        log=log, **context(**scene))

    assert "Nitro" not in stripped.copy["d1"].slide_texts[1]
    assert DegradationTag.COMPETITOR_STRIPPED in stripped.tags["d1"]
    assert "the strip runs on both sides" in log.warned("competitor_stripped")[0]

    shipped = overshot.copy["d1"].slide_texts[1]
    assert 0 < len(shipped) <= 40 and not shipped.endswith("fort"), "cut at a WORD boundary"
    assert DegradationTag.TEXT_TRIMMED in overshot.tags["d1"]
    assert "against a 40-character budget" in log.warned("text_trimmed")[0]


async def test_the_verifier_still_audits_the_quoted_rows_of_an_auto_deck_for_real() -> None:
    """Half 1 of `_verify` is neither run wholesale nor skipped wholesale on this path — it is
    satisfied ROW BY ROW (FR-353).

    A compressed slide is in the pool by construction and passes; a QUOTED slide is checked against
    the post's own strings and would fail if anything between the panel map and the `CopySet` ever
    rewrote it. The negative half is what proves the check still has teeth: hand the verifier the
    same auto pool with one quoted slide replaced, and the audit names it.
    """
    log = Recorder()
    trend = compress_deck(SHORT, LONG)
    call = StubCall({"d1": compressed(slide_texts=["", "short two"])})
    scene: dict[str, Any] = dict(trends={"t1": trend}, styles={STYLE_KEY: auto_style()})

    clean = await auto(deck_entry(slides=2), call, log=log, **context(**scene))
    assert DegradationTag.COPY_NOT_VERBATIM not in clean.tags.get("d1", ())

    written = copywrite._Written(
        copyset=CopySet(asset_id="d1", language="en",
                        slide_texts=["A sentence this post never carried.", "short two"]),
        source=copywrite.CopyProvenance(copy_mode="auto"),
        quoted=(*clean.copy["d1"].slide_texts, clean.copy["d1"].caption))
    run = copywrite._Run(call=None, engine=PromptEngine(),  # type: ignore[arg-type]
                         budgets=TextBudgets(), styles={}, conventions={}, onimage_languages={},
                         niche_descriptor="", brand_context="", competitors=(), strip_brands={},
                         log=log)

    assert copywrite._verify(written, deck_entry(slides=2), run) == [
        DegradationTag.COPY_NOT_VERBATIM]
    assert "slide_1: is not a byte-substring" in log.warned("copy_not_verbatim")[0]


async def test_compress_mode_still_lists_every_admitted_panel_and_writes_the_pre_d62_line() -> None:
    """The regression guard for D54's own path: `only=None` is what compress mode always sends.

    D62 added a parameter to two functions that compress mode calls on every run, so the claim
    worth pinning is that the parameter's absent value reproduces the old behaviour exactly — the
    block lists every admitted position, and the sibling line carries the pre-D62 compress clause
    with none of auto's wording anywhere near it.
    """
    trend = compress_deck(SHORT, LONG, "Short three.")
    call = StubCall({"d1": compressed(slide_texts=["a", "b", "c"])})
    plan_entry = deck_entry(slides=3)

    await compress(plan_entry, call,
                   **context(trends={"t1": trend}, styles={STYLE_KEY: auto_style()}))

    prompt = call.prompts[0]
    for position, text in ((1, SHORT), (2, LONG), (3, "Short three.")):
        assert f"\n{position}. (at most 40 characters) {text}" in prompt
    line = next(l for l in prompt.splitlines() if l.startswith("- d1"))
    assert "compress post P1's panels to 40 characters per slide" in line
    assert "the ones over" not in line and "ships verbatim" not in line
    assert "not printed" not in line

    offers = {plan_entry.asset_id: _offer(plan_entry, trend, auto_style())}
    assert copywrite._compress_block([plan_entry], offers) == copywrite._compress_block(
        [plan_entry], offers, only=None), "the default and the explicit `None` are one path"


# ------------------------------------------- D63/FR-343: translate mode — the LANGUAGE axis
#
# The third copy contract, and the one whose whole point is a NEGATIVE: it may not shorten. Auto
# and compress are about how long a slide's words are; this is about what tongue they are in, and
# the two are orthogonal on purpose — a translated deck that compressed nothing reports
# `copy_mode: verbatim, copy_language: target`.
#
# Three claims carry the mode and every test below serves one of them:
#
# 1. **No ceiling reaches the translate call.** No `(at most` in the rendered prompt, no `budget`
#    parameter on `_translate_field`, no `text_trimmed` from a slide, and a 1,010-character answer
#    ships all 1,010 characters onto a style whose slide budget is 180.
# 2. **Translate runs BEFORE the auto budget test.** `_rows_over_budget` measures the TRANSLATED
#    strings, so a German panel that overflows and translates short is left alone while a short
#    German panel whose English runs long is the one that pays for a compress call.
# 3. **Every decision NOT to translate is silent and free.** An unknown language, a post already
#    in the target language and a `source`-mode run all produce byte-identical output, and only a
#    translation that was WANTED and did not happen is tagged (`copy_not_translated`).


class SchemaCall(StubCall):
    """A `StubCall` whose canned answer depends on WHICH SCHEMA the engine sent.

    The translate pipeline is the first path in this module that issues two calls for ONE creative
    — translate, then (under auto or compress) a follow-up compress on the translated strings — so
    an answer table keyed by asset id alone cannot express it. Keying by schema name is how a test
    says "this is the translation, and that is the compression of it".

    `fails` names the schemas that answer nothing at all, which is how the two independent failure
    paths are exercised separately: a dead translate call falls to the verbatim mapped deck, while
    a dead follow-up compress leaves the deck translated and long.
    """

    def __init__(self, by_schema: dict[str, dict[str, Any]], *,
                 fails: tuple[str, ...] = ()) -> None:
        super().__init__({})
        self.by_schema = dict(by_schema)
        self.fails = frozenset(fails)

    async def __call__(self, role, messages, json_schema, images=None):  # type: ignore[override]
        name = str(json_schema.get("name", ""))
        self.answers = dict(self.by_schema.get(name, {}))
        self.fail_when = (lambda ids: True) if name in self.fails else None
        return await super().__call__(role, messages, json_schema, images)


def translated(**overrides: Any) -> dict[str, Any]:
    """One `CopyTranslated` answer — the D63 contract's shape (FR-343/FR-344).

    `CopyCompressed`'s fields plus `source_language`, and `slide_texts` is POSITION-INDEXED for
    the same reason: element *k* is the TRANSLATION of source panel *k+1*, and a blank element
    means "that source panel had nothing to translate". The engine reads it by index and never as
    a queue, so the alignment is the engine's, never the model's.
    """
    payload: dict[str, Any] = {
        "headline": "Eleven tools, three kept", "caption": "The three that survived the test.",
        "hashtags": ["#ai", "#tools"], "slide_texts": [], "through_line": "what survived",
        "narrative_arc": "", "source_language": "de"}
    payload.update(overrides)
    return payload


def foreign_deck(asset_id: str = "d1", *, post_id: str = "p1", slides: int = 2,
                 order: int = 0, **overrides: Any) -> PlanEntry:
    """A bound carousel pointed at `post_id` — `deck_entry` pins p1 and cannot take a second."""
    plan_entry = deck_entry(asset_id, slides=slides, **overrides)
    plan_entry.source_post_id = post_id
    plan_entry.order = order
    return plan_entry


def german_trend(*panels: str, key: str = "t1", language: str = "de",
                 caption: str = "Elf Werkzeuge getestet, drei sind geblieben.") -> TrendItem:
    """A topic whose top post is a German slideshow — the translate path's only input."""
    return make_trend(post(1, panels=panels, caption=caption, language=language), key=key)


async def translate(entries: Any, call: StubCall, *, log: Any = None, **over: Any) -> Any:
    """`write_copy` in target-language mode — the one line every test in this section shares."""
    return await copywrite.write_copy(entries if isinstance(entries, list) else [entries],
                                      call=call, log=log, copy_language_mode="target", **over)


#: A source panel at the length run `20260820_001158_2ard` measured on real slideshow pages, in
#: German, and its English translation at very nearly the same length. Both are far over the
#: 180-character slide budget the style below declares, which is exactly the point: a translated
#: slide has no budget, so both numbers are irrelevant to what ships.
GERMAN_WALL = ("Wir haben elf KI Werkzeuge getestet und nur drei davon haben den Alltag "
               "wirklich veraendert. " * 12)[:1048]
ENGLISH_WALL = ("We tested eleven AI tools and only three of them actually changed the "
                "working day. " * 13)[:1010]


def wall_style(**overrides: Any) -> MetaStyle:
    """A deck style declaring a 180-character slide budget — the registry's own tight end."""
    return make_style(max_onimage_chars={"headline": 90, "subline": 60, "slide": 180},
                      **overrides)


def test_translate_field_takes_no_budget_at_all() -> None:
    """The signature IS the contract (FR-343). `_compress_field` takes a budget and trims to it;
    this function has no budget to trim to, and a future edit that "helpfully" added one would
    turn the translate call into the shortening brief the whole mode exists not to be."""
    import inspect

    parameters = inspect.signature(copywrite._translate_field).parameters

    assert "budget" not in parameters, "a translated line has no ceiling — FR-343's whole point"
    assert set(parameters) == {"text", "brands", "entry", "run", "where", "blanked_into"}
    assert "budget" in inspect.signature(copywrite._compress_field).parameters, \
        "the control: the compress sibling DOES take one, which is what makes the absence a rule"


async def test_a_translated_line_ships_every_character_it_came_back_with() -> None:
    """FR-343's acceptance criterion: 1,048 characters of German in, 1,010 of English out, onto a
    style whose slide budget is 180 — and all 1,010 ship.

    Nothing about this deck is trimmed, and nothing about it claims byte identity either: the row
    quotes no label, `refs` is empty, `copy_language` is `target` and `source_language` records
    what the ladder read. `copy_mode` stays `verbatim` because the LENGTH contract did not change
    — the two axes are orthogonal, and a reader who conflates them would think this deck was
    compressed.
    """
    log = Recorder()
    assert len(GERMAN_WALL) == 1048 and len(ENGLISH_WALL) == 1010
    trend = german_trend(GERMAN_WALL, "Kurze zweite Seite.")
    call = SchemaCall({"copy_translated": {"d1": translated(
        slide_texts=[ENGLISH_WALL, "A short second page."])}})

    result = await translate(foreign_deck(slides=2), call, log=log,
                             **context(trends={"t1": trend}, styles={STYLE_KEY: wall_style()}))

    copyset, provenance = result.copy["d1"], result.provenance["d1"]
    assert copyset.slide_texts == [ENGLISH_WALL, "A short second page."]
    assert len(copyset.slide_texts[0]) == 1010, "every character, against a 180-character budget"
    assert DegradationTag.TEXT_TRIMMED not in result.tags.get("d1", ())
    assert log.warned("text_trimmed") == [], "no slide budget was ever applied to measure against"
    rows = provenance.panel_map
    assert [row["translated"] for row in rows] == [True, True]
    assert all(row["ref_label"] == "" for row in rows), "FR-302: a translated slide quotes nothing"
    assert [row["compressed"] for row in rows] == [False, False], "the LENGTH axis did not move"
    assert rows[0]["source_text_original"] == GERMAN_WALL, "the panel it was translated from"
    assert provenance.refs == {}
    assert provenance.copy_language == "target" and provenance.source_language == "de"
    assert provenance.copy_mode == "verbatim"
    assert DegradationTag.COPY_NOT_VERBATIM not in result.tags.get("d1", ()), \
        "`quoted` is empty on this path, so `_verify`'s substring half self-skips"
    assert DegradationTag.COPY_NOT_TRANSLATED not in result.tags.get("d1", ())


async def test_the_target_language_is_spelled_one_way_on_both_lines_of_the_translate_prompt(
) -> None:
    """`en-US` in a config may not become two different languages inside one prompt.

    The work order at the top prints `translate to: <code>` through `language_code`; the sibling
    clause at the bottom prints the target again. Passing `entry.language` raw to the second one
    produced `translate to: en (English)` above and `to en-US` below on any config whose platform
    language carries a regional tag — one prompt naming the destination twice, differently, with
    nothing to tell the model which spelling is the real one.
    """
    trend = german_trend("Erste Seite mit Woertern.", "Zweite Seite mit Woertern.")
    call = SchemaCall({"copy_translated": {"d1": translated(
        slide_texts=["First page with words.", "Second page with words."])}})
    regional = foreign_deck(slides=2)
    regional.language = "en-US"

    await translate(regional, call,
                    **context(trends={"t1": trend}, styles={STYLE_KEY: wall_style()}))

    prompt = call.prompts[0]
    line = next(row for row in prompt.splitlines() if row.startswith("- d1"))
    assert "CREATIVE d1 — translate to: en (English); source language: de" in prompt
    assert "translate post P1's panels from de to en;" in line
    assert "en-US" not in prompt, "one language, one spelling, on every line of the page"


async def test_the_translate_prompt_states_no_ceiling_and_names_both_languages() -> None:
    """The prompt is where the no-shortening guarantee is actually made, so it is asserted
    literally: not one `(at most` anywhere on the page.

    `_call_translate` passes `carousel_copy_mode="verbatim"` for exactly this reason — that is the
    `_budget_line` branch which states the headline ceiling and says a panel string carries none.
    The sibling line names both languages (the ladder's reading and the platform's configured
    target) and the panel block lists the admitted positions, numbered by SOURCE POSITION, with no
    number in front of them.
    """
    trend = german_trend("Erste Seite mit Woertern.", "", "Dritte Seite mit Woertern.")
    call = SchemaCall({"copy_translated": {"d1": translated(
        slide_texts=["First page with words.", "", "Third page with words."])}})

    await translate(foreign_deck(slides=3), call,
                    **context(trends={"t1": trend}, styles={STYLE_KEY: wall_style()}))

    prompt = call.prompts[0]
    assert call.schemas[0]["name"] == "copy_translated"
    assert "You translate a deck that already has its words." in prompt
    assert "(at most" not in prompt, "a per-line ceiling turns a translation into a summary"
    line = next(l for l in prompt.splitlines() if l.startswith("- d1"))
    assert "translate post P1's panels from de to en" in line
    assert "never shorten, never summarise" in line
    assert "quote post P1" not in line and "as-selected" not in line, \
        "the verbatim clause is REPLACED, not appended"
    assert "CREATIVE d1 — translate to: en (English); source language: de" in prompt
    assert "\n1. Erste Seite mit Woertern." in prompt
    assert "\n3. Dritte Seite mit Woertern." in prompt
    assert "caption source: Elf Werkzeuge getestet, drei sind geblieben." in prompt
    # The unlisted-position claim is asserted on the BLOCK rather than on the rendered page: the
    # template's own rules are a numbered list, so `\n2. ` appears in the prose whatever the deck
    # looks like, and asserting it against the whole prompt would pin the template's wording.
    plan_entry = foreign_deck(slides=3)
    block = copywrite._translate_block(
        plan_entry, _offer(plan_entry, trend, wall_style()),
        copywrite._Run(call=None, engine=PromptEngine(),  # type: ignore[arg-type]
                       budgets=TextBudgets(), styles={}, conventions={}, onimage_languages={},
                       niche_descriptor="", brand_context="", competitors=(), strip_brands={}))
    numbered = [line for line in block.splitlines() if line.split(".", 1)[0].isdigit()]
    assert numbered == ["1. Erste Seite mit Woertern.", "3. Dritte Seite mit Woertern."], \
        "only ADMITTED positions, numbered by SOURCE position, and never a budget on the line"


async def test_translate_runs_before_the_auto_budget_test_and_auto_measures_the_english() -> None:
    """FR-343's ordering rule, proved by making the two orders disagree.

    German panel 1 is 50 characters (over the 40-character budget) and its English is 6; German
    panel 2 is 5 characters (under it) and its English is 65. Measuring the SOURCE would compress
    panel 1 and leave panel 2 long — the wrong deck. Measuring the TRANSLATION, which is what
    `_translate_and_fit` does, asks for panel 2 alone.

    So the prompts arrive in a fixed order (translate, then compress), the compress block lists the
    ENGLISH text of position 2 and nothing else, and the shipped deck is mixed per row: position 2
    compressed AND translated, position 1 translated only.
    """
    trend = german_trend("Ein ziemlich langer deutscher Satz ueber Werkzeuge.", "Kurz.")
    long_english = "A much longer English sentence about the workflow that overflows."
    call = SchemaCall({
        "copy_translated": {"d1": translated(slide_texts=["Tools.", long_english])},
        "copy_compressed": {"d1": compressed(slide_texts=["", "A short English line."])}})

    result = await copywrite.write_copy(
        [foreign_deck(slides=2)], call=call, copy_language_mode="target",
        carousel_copy_mode="auto",
        **context(trends={"t1": trend}, styles={STYLE_KEY: auto_style()}))

    assert [schema["name"] for schema in call.schemas] == ["copy_translated", "copy_compressed"], \
        "translate FIRST, then fit — the reverse order would budget the German"
    assert "You translate a deck that already has its words." in call.prompts[0]
    assert "You compress words a deck already has." in call.prompts[1]
    fit = call.prompts[1]
    assert "\n2. (at most 40 characters) " + long_english in fit, "the ENGLISH, not the German"
    assert "\n1. (at most" not in fit, "position 1 translated SHORT and is not paid for twice"
    assert "Ein ziemlich langer deutscher Satz" not in fit

    copyset, provenance = result.copy["d1"], result.provenance["d1"]
    rows = provenance.panel_map
    assert copyset.slide_texts == ["Tools.", "A short English line."]
    assert [row["compressed"] for row in rows] == [False, True]
    assert [row["translated"] for row in rows] == [True, True]
    assert all(row["ref_label"] == "" for row in rows), "translated rows quote no label, either half"
    assert provenance.refs == {}
    assert provenance.copy_mode == "auto" and provenance.copy_language == "target"
    assert rows[1]["source_text_original"] == "Kurz.", "the SOURCE panel, not its translation"


async def test_the_already_target_backstop_ships_the_source_bytes_and_says_so() -> None:
    """9f — the model says these panels are already in the target language and then rewrites one.

    The engine's ladder had already decided this deck was foreign before it paid for the call, so
    the two readings disagree and the honest answer is the one that publishes nothing nobody
    asked for: the SOURCE bytes ship, the row says `translated: False`, and one warning per
    creative tells the operator the two readings disagreed.
    """
    log = Recorder()
    trend = german_trend("The page as its author wrote it.", "A second page.")
    call = SchemaCall({"copy_translated": {"d1": translated(
        source_language="en",
        slide_texts=["A tidier page than its author wrote.", "A second page."])}})

    result = await translate(foreign_deck(slides=2), call, log=log,
                             **context(trends={"t1": trend}, styles={STYLE_KEY: wall_style()}))

    rows = result.provenance["d1"].panel_map
    assert result.copy["d1"].slide_texts[0] == "The page as its author wrote it."
    assert rows[0]["translated"] is False, "nothing was translated onto this row"
    already = log.warned("translate_already_target")
    assert len(already) == 1 and "slide 1" in already[0]
    assert "ship their SOURCE bytes instead" in already[0]
    assert "slide 2" not in already[0], "byte-identical lines are not a finding"


async def test_a_deck_whose_every_row_kept_its_source_bytes_says_copy_language_source() -> None:
    """`copy_language` is read off the ROWS, never off the fact that a call was paid for.

    The shape: the already-target backstop fires on EVERY position. The model answered that these
    panels are already written in the platform's language and then handed back different words, so
    every row shipped its source bytes with `translated: False` — and the deck the operator
    receives is word for word the deck a `--copy-language source` run would have made. Calling
    that `target` would tell the gallery, `meta.yaml` and the previews that the words were
    translated when nothing was.

    `copy_not_translated` on top of it is the INTENDED audit signal and not a false positive: a
    translation was wanted, a call was paid for, and the pixels are in the source language. The
    two readings disagreed — the engine's ladder said foreign, the model said already-target — and
    `translate_already_target` names that disagreement on the same creative.
    """
    log = Recorder()
    trend = german_trend("The page as its author wrote it.", "A second page as written.")
    call = SchemaCall({"copy_translated": {"d1": translated(
        source_language="en",
        slide_texts=["A tidier first page.", "A tidier second page."])}})

    result = await translate(foreign_deck(slides=2), call, log=log,
                             **context(trends={"t1": trend}, styles={STYLE_KEY: wall_style()}))

    provenance = result.provenance["d1"]
    assert result.copy["d1"].slide_texts == ["The page as its author wrote it.",
                                             "A second page as written."]
    assert all(row["translated"] is False for row in provenance.panel_map)
    assert provenance.copy_language == "source", "nothing on any row was translated"
    assert provenance.source_language == "de", "the ladder's answer is recorded either way"
    assert DegradationTag.COPY_NOT_TRANSLATED in result.tags["d1"]
    assert len(log.warned("translate_already_target")) == 1
    assert len(log.warned("copy_not_translated")) == 1


async def test_a_source_dropped_position_keeps_its_own_drop_reason_through_the_compress_splice(
) -> None:
    """The reason a slide is wordless has to be the SOURCE's reason, on every path (FR-304/319).

    Under `target` + `auto` the follow-up compress call re-walks `_mapped_deck` over an offer whose
    `panels` are the TRANSLATED strings. A position the source lost — this one carries an @handle
    and may never become pixels — arrives at that walk as `""` and re-reads as the blandest reason
    there is, `empty`. The row would then tell `generate/contracts.py` (and through it the frame
    contract the render model reads, and the gallery the operator reads) that the slide is bare
    because the source had no words, when in truth the source had words this engine refuses to
    render. So the source walk's verdict is carried across and wins.
    """
    trend = german_trend("Folge mir @jemand fuer mehr", "Kurz.",
                         "Ein ziemlich langer deutscher Satz ueber Werkzeuge und Ablaeufe.")
    long_english = "A much longer English sentence about the workflow that overflows."
    call = SchemaCall({
        "copy_translated": {"d1": translated(slide_texts=["", "Tools.", long_english])},
        "copy_compressed": {"d1": compressed(slide_texts=["", "", "A short English line."])}})

    result = await copywrite.write_copy(
        [foreign_deck(slides=3)], call=call, copy_language_mode="target",
        carousel_copy_mode="auto",
        **context(trends={"t1": trend}, styles={STYLE_KEY: auto_style()}))

    rows = result.provenance["d1"].panel_map
    assert [schema["name"] for schema in call.schemas] == ["copy_translated", "copy_compressed"]
    assert rows[0]["drop_reason"] == "contains_handle_or_url", \
        "the SOURCE panel's verdict, not the translated offer's re-reading of an empty string"
    assert rows[0]["source_text"] == "" and rows[0]["translated"] is False
    assert rows[0]["source_text_original"] == "Folge mir @jemand fuer mehr", "provenance intact"
    assert [row["drop_reason"] for row in rows[1:]] == ["", ""], "the admitted rows drop nothing"
    assert [row["compressed"] for row in rows] == [False, False, True]
    assert result.copy["d1"].slide_texts == ["", "Tools.", "A short English line."]


async def test_an_unknown_source_language_ships_verbatim_warns_once_and_tags_nothing() -> None:
    """An unknown language is a decision NOT to translate, never a failure to (FR-343).

    Virlo sent no language and the vision pass read none, so there is nothing to translate FROM
    and the engine refuses to guess from the bytes. The deck is byte-identical to what a `source`
    run makes of the same inputs, the operator gets one line naming the post, and the creative
    carries no tag at all — `copy_not_translated` means "we meant to and could not", which is a
    different fact.
    """
    log = Recorder()
    trend = german_trend("Erste Seite mit Woertern.", "Zweite Seite.", language="")
    scene: dict[str, Any] = dict(trends={"t1": trend}, styles={STYLE_KEY: wall_style()})
    live = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})
    control = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})

    unknown = await translate(foreign_deck(slides=2), live, log=log, **context(**scene))
    source_mode = await copywrite.write_copy([foreign_deck(slides=2)], call=control,
                                             **context(**scene))

    assert [schema["name"] for schema in live.schemas] == ["copy_selection"], "no translate call"
    assert unknown.copy["d1"] == source_mode.copy["d1"]
    assert unknown.provenance["d1"] == source_mode.provenance["d1"]
    assert unknown.provenance["d1"].source_language == ""
    assert unknown.provenance["d1"].copy_language == "source"
    assert unknown.tags == source_mode.tags == {}
    warned = log.warned("translate_language_unknown")
    assert len(warned) == 1 and "post p1 carries no language" in warned[0]
    assert "does not guess at a language" in warned[0]


async def test_a_post_already_in_the_target_language_costs_no_call_and_still_records_it() -> None:
    """The commonest `target`-mode deck of all: an English post on an English platform slot.

    There is nothing to translate, so nothing is paid for and nothing changes — the run is byte
    for byte a `source`-mode run. What DOES change is the receipt: `source_language` says `en`,
    which is how meta.yaml can state the language of a deck that was never translated.
    """
    trend = make_trend(post(1, panels=("Panel one line", "Panel two line"),
                            caption="A caption long enough to be a caption at all.",
                            language="en"))
    scene: dict[str, Any] = dict(trends={"t1": trend}, styles={STYLE_KEY: wall_style()})
    live = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})
    control = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})

    target = await translate(foreign_deck(slides=2), live, **context(**scene))
    source_mode = await copywrite.write_copy([foreign_deck(slides=2)], call=control,
                                             **context(**scene))

    assert [schema["name"] for schema in live.schemas] == ["copy_selection"]
    assert target.copy["d1"] == source_mode.copy["d1"]
    assert target.provenance["d1"] == source_mode.provenance["d1"]
    assert target.provenance["d1"].source_language == "en"
    assert target.provenance["d1"].copy_language == "source"
    assert target.tags == {}


async def test_every_translating_creative_takes_its_own_call_and_the_rest_share_one() -> None:
    """One section per creative is the contract, so translating decks are NEVER grouped (plan 9g).

    Two German decks and one image on one topic: two translate calls, each naming one asset, plus
    exactly one selection call for the image. Grouping the two decks would put two content
    authorities on one page for a model that has just been told each section's panels decide what
    its slides say.
    """
    trend = make_trend(post(1, panels=("Erste Seite.", "Zweite Seite."), language="de",
                            caption="Elf Werkzeuge getestet, drei sind geblieben."),
                       post(2, panels=("Dritte Seite.", "Vierte Seite."), language="de",
                            caption="Ein zweiter Beitrag, schlicht geschrieben."),
                       post(3, hooks=("An image hook",),
                            caption="A third caption, plainly written."))
    entries = [foreign_deck("d1", post_id="p1", slides=2, order=0),
               foreign_deck("d2", post_id="p2", slides=2, order=1),
               entry("i1", 2, source_post_id="p3")]
    call = SchemaCall({
        "copy_translated": {"d1": translated(slide_texts=["First page.", "Second page."]),
                            "d2": translated(slide_texts=["Third page.", "Fourth page."])},
        "copy_selection": {"i1": selection(headline_ref="P3.hook.1", caption_ref="P3.caption")}})

    result = await translate(entries, call,
                             **context(trends={"t1": trend}, styles={STYLE_KEY: wall_style()}))

    assert sorted(call.calls) == [["d1"], ["d2"], ["i1"]], "never two decks on one page"
    assert sorted(schema["name"] for schema in call.schemas) == [
        "copy_selection", "copy_translated", "copy_translated"]
    assert result.copy["d1"].slide_texts == ["First page.", "Second page."]
    assert result.copy["d2"].slide_texts == ["Third page.", "Fourth page."]
    assert result.copy["i1"].headline == "An image hook", "the image still SELECTS, verbatim"
    assert result.provenance["i1"].copy_language == "source", "images never translate (FR-345)"
    assert result.provenance["d1"].copy_language == "target"
    assert result.provenance["d2"].copy_language == "target"


async def test_the_follow_up_under_compress_mode_sends_the_compress_sentence_not_autos() -> None:
    """`--copy-mode compress` + `--copy-language target`: the SECOND call must sound like compress.

    Under compress mode every admitted position is being compressed by definition, so the list of
    "rows to compress after translation" is simply every admitted row. Handing that list on as
    `only` would print an identical panel block and then swap the sibling line for auto's —
    "compress post P1's panels 1, 2 (the ones over 40 characters)" on a deck where panel 1 is
    six characters long and is being compressed anyway. The model reads that clause and is being
    told something untrue about why it is shortening a line.

    So `only` is the AUTO signal at the wire and nothing else: compress mode passes `None`, which
    is the sentence a compress-mode run has always sent. The splice still knows the positions —
    they travel on `_Translation.fit`, not on the prompt.
    """
    trend = german_trend("Kurz.", "Ein ziemlich langer deutscher Satz ueber Werkzeuge.")
    long_english = "A much longer English sentence about the workflow that overflows."
    call = SchemaCall({
        "copy_translated": {"d1": translated(slide_texts=["Short.", long_english])},
        "copy_compressed": {"d1": compressed(slide_texts=["Short.", "A short English line."])}})

    result = await copywrite.write_copy(
        [foreign_deck(slides=2)], call=call, copy_language_mode="target",
        carousel_copy_mode="compress",
        **context(trends={"t1": trend}, styles={STYLE_KEY: auto_style()}))

    fit = call.prompts[1]
    assert [schema["name"] for schema in call.schemas] == ["copy_translated", "copy_compressed"]
    assert "compress post P1's panels to 40 characters per slide" in fit
    assert "the ones over" not in fit, "auto's clause has no business on a compress-mode call"
    assert "answer \"\" for every position not printed" not in fit, "that is auto's rule too"
    assert result.provenance["d1"].copy_mode == "compress"
    assert result.copy["d1"].slide_texts == ["Short.", "A short English line."]


async def test_a_failed_translate_call_ships_the_verbatim_deck_and_says_copy_not_translated(
) -> None:
    """The fail-open tier, and it costs the deck nothing but its language.

    `_mapped_fallback` is the same degrade path a failed selection or compress call takes: the
    FR-304 mapping needs no model, so every admitted panel still renders, in its own position, in
    German. Two tags travel together and they are two different facts — `copy_degraded` says an
    LLM call died (FR-248 counts it), `copy_not_translated` says the thing that died was the
    translation, which is what the console and the gallery badge read.
    """
    log = Recorder()
    trend = german_trend("Erste Seite mit Woertern.", "Zweite Seite mit Woertern.")
    call = SchemaCall({"copy_translated": {"d1": translated(slide_texts=["never seen"])}},
                      fails=("copy_translated",))

    result = await translate(foreign_deck(slides=2), call, log=log,
                             **context(trends={"t1": trend}, styles={STYLE_KEY: wall_style()}))

    provenance = result.provenance["d1"]
    assert result.copy["d1"].slide_texts == ["Erste Seite mit Woertern.",
                                             "Zweite Seite mit Woertern."], "German, in full"
    assert DegradationTag.COPY_DEGRADED in result.tags["d1"]
    assert DegradationTag.COPY_NOT_TRANSLATED in result.tags["d1"]
    assert provenance.copy_language == "source", "the bytes are the post's own — say so"
    assert provenance.source_language == "de"
    assert provenance.copy_mode == "verbatim"
    assert all(row["translated"] is False for row in provenance.panel_map)
    assert provenance.refs["slide_1"] == "P1.panel.1", "the labels are back — these ARE quotes"
    assert "shipped in its source language instead" in log.warned("copy_not_translated")[0]
    assert log.warned("copy_degraded"), "a dead call is still a dead call"
    assert call.calls == [["d1"]], "no second call, no split, no extra spend"


async def test_a_failed_follow_up_compress_leaves_the_deck_translated_and_long() -> None:
    """The expensive half succeeded, so the deck keeps it (FR-343/FR-353).

    A dead follow-up compress is not a dead translation: every panel is in the target language and
    in its own position, and only the FIT to the style's slide budget is missing. That is the
    pre-D62 outcome — long slides — and it is tagged `copy_degraded` because a call died, never
    `copy_not_translated`, because the translation is exactly what did ship.
    """
    log = Recorder()
    trend = german_trend("Kurz.", "Ein ziemlich langer deutscher Satz ueber Werkzeuge.")
    long_english = "A much longer English sentence about the workflow that overflows."
    call = SchemaCall({"copy_translated": {"d1": translated(
        slide_texts=["Short.", long_english])}}, fails=("copy_compressed",))

    result = await copywrite.write_copy(
        [foreign_deck(slides=2)], call=call, log=log, copy_language_mode="target",
        carousel_copy_mode="auto",
        **context(trends={"t1": trend}, styles={STYLE_KEY: auto_style()}))

    provenance = result.provenance["d1"]
    assert result.copy["d1"].slide_texts == ["Short.", long_english], "English, uncompressed"
    assert DegradationTag.COPY_DEGRADED in result.tags["d1"]
    assert DegradationTag.COPY_NOT_TRANSLATED not in result.tags["d1"], \
        "the translation is precisely what DID ship"
    assert provenance.copy_language == "target" and provenance.copy_mode == "verbatim"
    assert [row["translated"] for row in provenance.panel_map] == [True, True]
    failed = log.warned("translate_compress_failed")
    assert len(failed) == 1 and "ships translated and UNCOMPRESSED" in failed[0]


async def test_a_line_that_drifts_far_from_its_sources_length_warns_and_ships() -> None:
    """A20's polarity on the one axis this contract cannot gate (FR-343).

    A translation legitimately changes length, so there is no ceiling to fail and no floor to
    refuse — but a 400-character panel answered with 40 characters is a summary, and a summary is
    the thing this contract forbids. The line ships, the warning names the slide and both lengths,
    and the creative is tagged so the operator knows which card to read twice.
    """
    log = Recorder()
    long_german = ("Ein deutscher Absatz ueber Werkzeuge und Ablaeufe. " * 8)[:400]
    trend = german_trend(long_german)
    call = SchemaCall({"copy_translated": {"d1": translated(
        slide_texts=["Tools and workflows, in brief."])}})

    result = await translate(foreign_deck(slides=1), call, log=log,
                             **context(trends={"t1": trend}, styles={STYLE_KEY: wall_style()}))

    assert len(long_german) == 400
    assert result.copy["d1"].slide_texts == ["Tools and workflows, in brief."], "it SHIPS"
    assert DegradationTag.TRANSLATE_LENGTH_DRIFT in result.tags["d1"]
    drift = log.warned("translate_length_drift")
    assert len(drift) == 1 and "slide 1 (400 characters in, 30 out" in drift[0]
    assert "audit rather than a gate" in drift[0]


async def test_an_empty_answer_goes_wordless_and_an_answer_for_a_dropped_panel_is_discarded(
) -> None:
    """The two halves of FR-304's alignment, restated for the translate walk.

    An ADMITTED panel answered with nothing renders wordless in its own position — the slide is
    bare beside a source slide that has words, which is worth a warning and never worth pulling
    the next line forward onto. A DROPPED position answered anyway is thrown away: translation
    fills no vacuums, exactly as compression does not, and words of ours on a slide theirs left
    blank are the `invented_text` defect the post-render gate blocks whole decks for.
    """
    log = Recorder()
    trend = german_trend("Erste Seite mit Woertern.", "", "Dritte Seite mit Woertern.")
    call = SchemaCall({"copy_translated": {"d1": translated(
        slide_texts=["", "A slide the source never had", "Third page with words."])}})

    result = await translate(foreign_deck(slides=3), call, log=log,
                             **context(trends={"t1": trend}, styles={STYLE_KEY: wall_style()}))

    rows = result.provenance["d1"].panel_map
    assert result.copy["d1"].slide_texts == ["", "", "Third page with words."]
    assert [row["source_position"] for row in rows] == [1, 2, 3], "position kept, nothing slid up"
    assert [row["translated"] for row in rows] == [False, False, True]
    assert rows[1]["drop_reason"] == "empty" and rows[1]["source_text"] == ""
    silent = log.warned("translate_no_text")
    assert len(silent) == 1 and "slide 1" in silent[0]
    invented = log.warned("translate_invented_text")
    assert len(invented) == 1 and "slide 2" in invented[0]
    assert "A slide the source never had" in invented[0], "the operator sees what was discarded"


async def test_a_competitor_name_in_a_translated_line_is_stripped_fail_closed() -> None:
    """§1.5 layer 1 runs on what came BACK, unguarded, and before anything else — the compress
    path's rule, on the translate path, for the same reason: a model translating a panel can write
    a name it read in the fenced trend texts, so the blocklist is applied to the line it returned
    and not only to the panel it was translating."""
    log = Recorder()
    trend = german_trend("Eine Seite ueber das Planen von Beitraegen.", "Eine zweite Seite.")
    call = SchemaCall({"copy_translated": {"d1": translated(
        slide_texts=["Nitro schedules the posts", "A second page."])}})

    result = await translate(foreign_deck(slides=2), call, log=log, competitors=["Nitro"],
                             **context(trends={"t1": trend}, styles={STYLE_KEY: wall_style()}))

    assert "Nitro" not in result.copy["d1"].slide_texts[0]
    assert DegradationTag.COMPETITOR_STRIPPED in result.tags["d1"]
    assert "the strip runs on both sides" in log.warned("competitor_stripped")[0]
    assert DegradationTag.COPY_NOT_VERBATIM not in result.tags["d1"], \
        "a translated deck claims no byte identity, so the substring audit has nothing to report"


async def test_a_translated_line_carrying_a_handle_is_BLANKED_and_warned() -> None:
    """FR-319 re-applied on the way OUT, because a translated line is the model's own bytes.

    The line is removed WHOLE rather than edited: a translated sentence with its @handle cut out
    is a sentence nobody wrote and nobody proof-read. The source panel here is clean, so this can
    only be the model copying a mark it read elsewhere on the page.
    """
    log = Recorder()
    trend = german_trend("Eine saubere Seite ueber den Ablauf.", "Eine zweite saubere Seite.")
    call = SchemaCall({"copy_translated": {"d1": translated(
        slide_texts=["The workflow, via @growthdaily", "A second clean line."])}})

    result = await translate(foreign_deck(slides=2), call, log=log,
                             **context(trends={"t1": trend}, styles={STYLE_KEY: wall_style()}))

    rows = result.provenance["d1"].panel_map
    assert result.copy["d1"].slide_texts == ["", "A second clean line."]
    assert rows[0]["drop_reason"] == "", "the SOURCE panel was fine — this is not a source drop"
    assert rows[0]["translated"] is False and rows[0]["source_text"] == ""
    assert rows[0]["source_text_original"] == "Eine saubere Seite ueber den Ablauf."
    scrub = log.warned("translate_scrub")
    assert len(scrub) == 1 and "slide 1 (carries an @handle)" in scrub[0]
    assert "BLANKED" in scrub[0]
    assert log.warned("translate_no_text") == [], \
        "the model answered; the ENGINE rejected it, and that is one finding, not two"


async def test_an_english_deck_and_a_german_one_in_one_group_take_different_contracts() -> None:
    """The mixed group, end to end — the shape every real `target`-mode run will actually have.

    Both creatives are bound panel-mapped decks on one topic, so they land in one group and one
    partition pass. The English one is already in the target language: it takes the ordinary
    selection call, quotes its panels under their real labels, and its receipt says `source`. The
    German one takes a translate call of its own, quotes nothing, and its receipt says `target`.
    Nothing about either creative is affected by the other.
    """
    trend = make_trend(post(1, panels=("Panel one line", "Panel two line"), language="en",
                            caption="A caption long enough to be a caption at all."),
                       post(2, panels=("Erste Seite.", "Zweite Seite."), language="de",
                            caption="Elf Werkzeuge getestet, drei sind geblieben."))
    entries = [foreign_deck("c1", post_id="p1", slides=2, order=0),
               foreign_deck("d1", post_id="p2", slides=2, order=1)]
    call = SchemaCall({
        "copy_selection": {"c1": selection(headline_ref="", caption_ref="P1.caption")},
        "copy_translated": {"d1": translated(slide_texts=["First page.", "Second page."])}})

    result = await translate(entries, call,
                             **context(trends={"t1": trend}, styles={STYLE_KEY: wall_style()}))

    english, german = result.provenance["c1"], result.provenance["d1"]
    assert sorted(call.calls) == [["c1"], ["d1"]]
    assert result.copy["c1"].slide_texts == ["Panel one line", "Panel two line"], "byte-verbatim"
    assert english.copy_language == "source" and english.source_language == "en"
    assert english.refs["slide_1"] == "P1.panel.1", "a quoted deck keeps its labels"
    assert all(row["translated"] is False for row in english.panel_map)
    assert result.copy["d1"].slide_texts == ["First page.", "Second page."]
    assert german.copy_language == "target" and german.source_language == "de"
    assert german.refs == {} and all(row["translated"] for row in german.panel_map)
    assert result.tags == {}, "neither creative lost anything"


async def test_the_language_ladder_prefers_virlos_answer_and_falls_back_to_the_vision_pass(
) -> None:
    """The first two rungs, in order (§2). Rung 1 is Virlo's `SourcePost.language` and it is free;
    rung 2 is the vision pass's ONE deck-level reading, keyed by post because the reading is a
    property of the source deck. The first non-empty answer wins, and a disagreement is not a vote
    — rung 1's `de` beats rung 2's `en` and the deck translates."""
    trend_unknown = german_trend("Erste Seite.", "Zweite Seite.", language="")
    trend_known = german_trend("Erste Seite.", "Zweite Seite.", language="de")
    scene: dict[str, Any] = dict(styles={STYLE_KEY: wall_style()})
    second_rung = SchemaCall({"copy_translated": {"d1": translated(
        slide_texts=["First page.", "Second page."])}})
    first_rung = SchemaCall({"copy_translated": {"d1": translated(
        slide_texts=["First page.", "Second page."])}})

    from_vision = await translate(foreign_deck(slides=2), second_rung,
                                  post_languages={"p1": "de"},
                                  **context(trends={"t1": trend_unknown}, **scene))
    from_virlo = await translate(foreign_deck(slides=2), first_rung,
                                 post_languages={"p1": "en"},
                                 **context(trends={"t1": trend_known}, **scene))

    assert second_rung.schemas[0]["name"] == "copy_translated", "rung 2 answered, so it translates"
    assert from_vision.provenance["d1"].source_language == "de"
    assert from_vision.provenance["d1"].copy_language == "target"
    assert first_rung.schemas[0]["name"] == "copy_translated", "rung 1 wins and it says foreign"
    assert from_virlo.provenance["d1"].source_language == "de", \
        "Virlo's answer is not overruled by the vision pass's"


async def test_rung_three_is_the_topic_screens_own_reading_when_both_post_rungs_are_silent(
) -> None:
    """The gap the D63 review found, closed: the FILTER already read this topic's language.

    Under `target` the screen's LANG skip is switched OFF on purpose — a foreign topic is let in
    because translation now exists — so a topic the screen graded `de` sails through Select. If
    Virlo's post row carries no `language_detected` and the vision pass read nothing off the
    slides, the ladder used to run out at rung 2 and the deck shipped GERMAN pixels on an English
    platform slot with a `translate_language_unknown` warning beside it. The screen's verdict is a
    reading this run already paid a model for; declining to use it is not caution, it is throwing
    evidence away.

    It is the LAST rung because it is a judgement about a TOPIC's strings, and one topic can hold
    posts in two languages — the gap `plan.off_language_post` exists for.
    """
    trend = german_trend("Erste Seite.", "Zweite Seite.", language="")
    call = SchemaCall({"copy_translated": {"d1": translated(
        slide_texts=["First page.", "Second page."])}})

    result = await translate(foreign_deck(slides=2), call,
                             topic_languages={"t1": "de"},
                             **context(trends={"t1": trend}, styles={STYLE_KEY: wall_style()}))

    assert call.schemas[0]["name"] == "copy_translated", "rung 3 answered, so the deck translates"
    assert result.provenance["d1"].source_language == "de"
    assert result.provenance["d1"].copy_language == "target"
    assert result.copy["d1"].slide_texts == ["First page.", "Second page."]


async def test_rung_one_still_wins_over_rung_three_and_an_unrelated_topic_key_is_ignored(
) -> None:
    """Order is the whole ladder, and rung 3 is keyed by TOPIC — both halves pinned here.

    Virlo's per-POST answer beats the screen's per-TOPIC one whenever both exist: the post is what
    gets quoted, the topic is only where it was found. And a `topic_languages` map that does not
    hold this creative's own `trend_key` is not an answer for it — a lookup that fell through to
    "some other topic said German" would translate a deck on evidence about different words.
    """
    known = german_trend("Erste Seite.", "Zweite Seite.", language="de")
    unknown = german_trend("Erste Seite.", "Zweite Seite.", language="")
    scene: dict[str, Any] = dict(styles={STYLE_KEY: wall_style()})
    over_ruled = SchemaCall({"copy_translated": {"d1": translated(
        slide_texts=["First page.", "Second page."])}})
    log = Recorder()
    stranger = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})

    beats = await translate(foreign_deck(slides=2), over_ruled,
                            topic_languages={"t1": "fr"},
                            **context(trends={"t1": known}, **scene))
    missed = await translate(foreign_deck(slides=2), stranger, log=log,
                             topic_languages={"some-other-topic": "de"},
                             **context(trends={"t1": unknown}, **scene))

    assert beats.provenance["d1"].source_language == "de", "rung 1 is the post's own reading"
    assert [schema["name"] for schema in stranger.schemas] == ["copy_selection"], \
        "no rung answered for THIS topic, so no translate call was made"
    assert missed.provenance["d1"].source_language == ""
    assert missed.provenance["d1"].copy_language == "source"
    assert len(log.warned("translate_language_unknown")) == 1


# ------------------------------------------------------ FR-313: the BARE-NUMERAL page counter
#
# Run `20260820_234620_j867` is the fixture. Its bound deck put the source's page number on a line
# of its own — `01` … `07`, no separator, no total — on all seven panels, and every one of them
# shipped into `panel_map.source_text` and into the gauntlet's expected-line contract while
# `counter.detected` recorded `false`, because no paired form was ever present to detect.
#
# The shape is the weakest one this engine models, so it needs corroboration: `counter_line`
# accepts a lone numeral ONLY when the caller says which slide it came from and the numeral equals
# that slide's own position. `_offer_for` is the only place in the engine that knows.

#: The j867 panel, verbatim from that run's `meta.yaml`, with `NN` standing in for its counter.
J867_PANEL = ("Jason AI\nby Reply\n{}\nPersonal Assistant\nPAID\nFREE\nChatGPT\nNanoClaw\n"
              "@oleg.talk")


async def test_a_bare_numeral_equal_to_its_slide_number_is_chrome_and_is_dropped() -> None:
    """FR-313 on the j867 panels: all seven `01`…`07` lines go, and everything else stays.

    The line lands in `chrome_counter_panels` and on each row's `chrome_counter_stripped`, exactly
    as a paired `01 / 06` counter does — it is the same finding wearing a weaker shape, and it may
    never ride `creator_stripped`, whose meaning is "our creative nearly named another account".
    `source_text_original` keeps the counter, because provenance records what the source said and
    never what we admitted.
    """
    log = Recorder()
    panels = tuple(J867_PANEL.format(f"{number:02d}") for number in range(1, 8))
    trend = make_trend(post(1, panels=panels,
                            caption="The AI assistants I actually pay for."))
    plan_entry = deck_entry(slides=7)

    offer = _offer(plan_entry, trend, deck_style(), log=log)

    assert offer.chrome_counter_panels == frozenset(range(1, 8)), "all seven, one per slide"
    assert all("\n01\n" not in text and "\n07\n" not in text for text in offer.panels)
    assert offer.panels[0].startswith("Jason AI\nby Reply\nPersonal Assistant")
    assert offer.panels_original[0] == panels[0], "the counter survives in the ORIGINAL bytes"
    warned = log.warned("panel_counter_stripped")
    assert len(warned) == 1 and "was DROPPED from 7 panel(s)" in warned[0]

    call = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})
    result = await copywrite.write_copy(
        [deck_entry(slides=7)], call=call,
        **context(trends={"t1": trend}, styles={STYLE_KEY: deck_style()}))

    rows = result.provenance["d1"].panel_map
    assert all(row["chrome_counter_stripped"] is True for row in rows)
    assert all(row["creator_stripped"] is False for row in rows), "a page number is nobody's brand"
    assert rows[0]["source_text_original"] == panels[0]


def test_a_numeral_that_opens_a_sentence_is_content_and_keeps_every_byte() -> None:
    """The safety half of FR-313, and the reason the rule needs the position at all: a `5` on a
    slide can be the whole point of the slide. Only a line that is NOTHING BUT the numeral, and
    only when it equals its own slide's position, is chrome — `"5 tools I use"` is a headline."""
    panels = ("A first page of words.", "A second page.", "A third page.", "A fourth page.",
              "5 tools I use\nto ship faster")
    trend = make_trend(post(1, panels=panels, caption="The tools I actually use."))

    offer = _offer(deck_entry(slides=5), trend, deck_style())

    assert offer.chrome_counter_panels == frozenset(), "nothing here is a bare numeral line"
    assert offer.panels[4] == "5 tools I use\nto ship faster", "every byte"


def test_a_bare_numeral_on_the_wrong_slide_is_content_and_an_unknown_position_never_strips(
) -> None:
    """`_strip_counter_lines` forwards the position and `0` switches the shape off entirely.

    `07` on slide 1 is content — a spec, a count, a price — and only the caller that knows the
    line came from slide 7 may read it as that slide's page number. Every caller that does not
    know leaves `position` at its default, which is what keeps the weakest shape from firing on a
    string nobody can place.
    """
    assert copywrite._strip_counter_lines("Tools\n03\nper week", position=3) == (
        "Tools\nper week", ["03"])
    assert copywrite._strip_counter_lines("Tools\n03\nper week", position=1) == (
        "Tools\n03\nper week", [])
    assert copywrite._strip_counter_lines("Tools\n03\nper week") == (
        "Tools\n03\nper week", []), "an unknown position can never admit a bare numeral"
    assert copywrite._strip_counter_lines("Tools\n01 / 06\nper week") == (
        "Tools\nper week", ["01 / 06"]), "the PAIRED shape never needed a position"


def test_a_lone_bare_numeral_on_one_slide_is_content_and_the_deck_keeps_it() -> None:
    """FR-313 rule 2's CORROBORATION, mirrored at admission (D63 review fix).

    `slide_intel.detect_counter` accepts the bare shape under rule 2 alone, and rule 2 needs two
    slides carrying their own position before it will call a deck counted. The admission strip had
    no such bar: `_offer_for` handed the ordinal down on every panel, so ONE panel whose whole text
    is the numeral `1` on slide 1 was emptied at admission and rendered as a wordless slide beside
    a source slide that had a word on it. That is the FR-304 failure the counter strip exists to
    prevent, arriving from the other direction.

    A countdown deck, a `1` that is the answer, a slide whose entire point is a number: one match
    is a slide about a number, two matches are a convention. So the survey runs over the whole deck
    before a byte is stripped, and a single hit switches the shape off for every panel.
    """
    panels = ("1", "A second page of words.", "A third page of words.")
    trend = make_trend(post(1, panels=panels, caption="The countdown starts here."))

    offer = _offer(deck_entry(slides=3), trend, deck_style())

    assert offer.chrome_counter_panels == frozenset(), "one slide is not a counting convention"
    assert offer.panels[0] == "1", "the whole panel survives — it would be wordless otherwise"


def test_two_slides_that_each_carry_their_own_number_corroborate_and_both_lose_it() -> None:
    """The bar is two, and two is enough: the shortest deck that can carry a convention does.

    `MIN_DECK_SLIDES` is 2, so a two-slide deck reading `1` / `2` is the smallest case where the
    numerals agree with their positions on more than one slide — the same evidence `detect_counter`
    calls RULE_POSITIONAL. Both counters go, both panels keep their words, and each row records the
    strip on `chrome_counter_stripped` exactly as a paired `01 / 06` would.
    """
    log = Recorder()
    trend = make_trend(post(1, panels=("1\nAlpha", "2\nBeta"),
                            caption="Two pages and a page number on each."))

    offer = _offer(deck_entry(slides=2), trend, deck_style(), log=log)

    assert offer.chrome_counter_panels == frozenset({1, 2})
    assert offer.panels == ("Alpha", "Beta"), "the words stay, the furniture goes"
    assert offer.panels_original == ("1\nAlpha", "2\nBeta"), "provenance keeps the source's bytes"
    assert len(log.warned("panel_counter_stripped")) == 1


def test_the_corroboration_survey_reads_positions_and_not_merely_bare_numerals() -> None:
    """Two bare numerals are not two matches unless each one equals ITS OWN slide's position.

    A deck whose slide 1 says `7` and whose slide 2 says `9` carries two lone numerals and no
    counting convention at all — they are prices, counts, scores. The survey compares each numeral
    against the position it sits on, which is the same comparison `counter_line` makes and the
    reason `bare_numeral_position` exists as a public helper: a caller has to be able to ask which
    slide a numeral would be chrome for before it decides whether to strip anything.
    """
    trend = make_trend(post(1, panels=("7\nAlpha", "9\nBeta"),
                            caption="Two numbers and no page counter anywhere."))

    offer = _offer(deck_entry(slides=2), trend, deck_style())

    assert offer.chrome_counter_panels == frozenset()
    assert offer.panels == ("7\nAlpha", "9\nBeta"), "neither numeral names its own slide"


async def test_every_row_of_a_verbatim_and_a_compressed_deck_says_translated_false() -> None:
    """One row schema always (FR-73 as amended), and the new key obeys it on every walk.

    `translated` is written on the verbatim walk, on the compress walk and on the auto rows that
    inherit from the verbatim one, so no reader of `panel_map` — the gallery, `generate._record`,
    the FR-309 card — has to ask whether the key exists before reading it. A `source`-language run
    is every run that has ever happened before D63, and all of them answer False.
    """
    trend = compress_deck("Panel one line", "", "Panel three line")
    verbatim_call = StubCall({"d1": selection(headline_ref="", caption_ref="P1.caption")})
    compress_call = StubCall({"d1": compressed(slide_texts=["One", "", "Three"])})
    scene: dict[str, Any] = dict(trends={"t1": trend}, styles={STYLE_KEY: deck_style()})

    quoted = await copywrite.write_copy([deck_entry(slides=3)], call=verbatim_call,
                                        **context(**scene))
    shortened = await compress(deck_entry(slides=3), compress_call, **context(**scene))

    assert all(row["translated"] is False for row in quoted.provenance["d1"].panel_map)
    assert all(row["translated"] is False for row in shortened.provenance["d1"].panel_map)
    assert all("translated" in row for row in shortened.provenance["d1"].panel_map), \
        "written, not merely absent-and-falsy — a reader may never have to ask"


async def test_a_runaway_translation_is_BLANKED_at_the_sanity_fence_and_never_cut() -> None:
    """The ONE length gate that survives on this path, and it is a fence rather than a budget.

    `PANEL_SANITY_CHARS` is the same ceiling a SOURCE panel faces on the way in: past it the
    string is a transcription accident, not a slide. Applied to what comes BACK it catches the
    model that ran away, and it BLANKS rather than trims — cutting a translated line mid-thought
    is exactly the shortening this contract exists to forbid, and it would earn `text_trimmed`
    for a rule the translate call was never given.
    """
    log = Recorder()
    runaway = "A sentence that will not stop. " * 60  # ~1,860 characters
    assert len(runaway) > copywrite.PANEL_SANITY_CHARS
    trend = german_trend("Erste Seite mit Woertern.", "Zweite Seite mit Woertern.")
    call = SchemaCall({"copy_translated": {"d1": translated(
        slide_texts=[runaway, "Second page with words."])}})

    result = await translate(foreign_deck(slides=2), call, log=log,
                             **context(trends={"t1": trend}, styles={STYLE_KEY: wall_style()}))

    rows = result.provenance["d1"].panel_map
    assert result.copy["d1"].slide_texts == ["", "Second page with words."]
    assert rows[0]["translated"] is False and rows[0]["drop_reason"] == "", \
        "the SOURCE panel was fine — this is the ANSWER being unusable, not a source drop"
    assert DegradationTag.TEXT_TRIMMED not in result.tags.get("d1", ()), \
        "blanked, never cut — a trimmed translation is the shortening this mode forbids"
    over = log.warned("translate_over_sanity")
    assert len(over) == 1 and "past the 1500-character sanity ceiling" in over[0]
    assert "removed whole rather than cut" in over[0]
    assert log.warned("translate_no_text") == [], \
        "one finding, one warning: the model DID answer, and the honest cause is above"


async def test_a_translate_answer_longer_than_the_deck_is_truncated_and_says_so() -> None:
    """The deck's length is the PLAN's — fixed at ASSIGN, priced at the Confirm gate (§0.4').

    A model that answers for eight positions on a two-slide deck cannot buy the six slides nobody
    paid for, so the extras are discarded and the operator is told how many went. The same rule
    the compress and auto walks enforce, in this walk's own vocabulary.
    """
    log = Recorder()
    trend = german_trend("Erste Seite mit Woertern.", "Zweite Seite mit Woertern.")
    call = SchemaCall({"copy_translated": {"d1": translated(
        slide_texts=["First page.", "Second page.", "A third", "A fourth"])}})

    result = await translate(foreign_deck(slides=2), call, log=log,
                             **context(trends={"t1": trend}, styles={STYLE_KEY: wall_style()}))

    assert result.copy["d1"].slide_texts == ["First page.", "Second page."]
    assert len(result.provenance["d1"].panel_map) == 2
    truncated = log.warned("translate_list_truncated")
    assert len(truncated) == 1
    assert "returned 4 slide texts for a 2-slide deck" in truncated[0]
