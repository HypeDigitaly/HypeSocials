"""Copywriting tests — grouping, the both-mode pair rule, degradation and FR-101 enforcement.

No network: the `llm.structured_call` seam is a stub matching `models.StructuredCall`, so every
test is a pure function of the plan entries and the canned response.
"""

from __future__ import annotations

from typing import Any

from hypesocials import copywrite
from hypesocials.config import TextBudgets
from hypesocials.models import ParsedResult, PlanEntry, StyleBrief, TrendItem
from hypesocials.prompts_engine import PromptEngine


class StubCall:
    """A `StructuredCall` that answers from a canned table and records every system prompt."""

    def __init__(self, answers: dict[str, dict[str, Any]] | None = None,
                 *, fail_when: Any = None) -> None:
        self.answers = answers or {}
        self.fail_when = fail_when  # predicate over the asset ids in this call
        self.prompts: list[str] = []
        self.calls: list[list[str]] = []

    async def __call__(self, role, messages, json_schema, images=None) -> ParsedResult:
        system = messages[0]["content"]
        self.prompts.append(system)
        asset_ids = [line.split(" · ")[0].removeprefix("- ").strip()
                     for line in system.splitlines()
                     if line.startswith("- ") and " · " in line]
        self.calls.append(asset_ids)
        if self.fail_when is not None and self.fail_when(asset_ids):
            return ParsedResult(parsed=None, raw_text="stub failure", degraded=True)
        creatives = [self.answers[a] | {"asset_id": a} for a in asset_ids if a in self.answers]
        return ParsedResult(parsed={"creatives": creatives}, raw_text="{}")


def answer(**overrides: Any) -> dict[str, Any]:
    payload = {"hook_pattern_used": "negative-outcome claim, second person, seven words",
               "caption": "Most people wire this backwards.", "hashtags": ["#ai", "#tools"],
               "hook_line": "Most people wire this backwards", "headline": "Wired backwards",
               "subline": "and it costs them", "slide_texts": [], "narrative_arc": "",
               "overlay_text": "", "through_line": ""}
    payload.update(overrides)
    return payload


def entry(asset_id: str, order: int, **overrides: Any) -> PlanEntry:
    plan_entry = PlanEntry(order=order, asset_id=asset_id, creative_format="image",
                           platform="linkedin", language="en", aspect_ratio="16:9",
                           trend_key="t1")
    for key, value in overrides.items():
        setattr(plan_entry, key, value)
    return plan_entry


def make_trend() -> TrendItem:
    return TrendItem(history_key="t1", monitor_id="m1", name="AI tool stacks",
                     why_it_works="numbers in the first line",
                     hook_texts=["Nobody tells you this about AI tools"],
                     panel_texts=["panel one", "panel two", "panel three"])


def engine() -> PromptEngine:
    return PromptEngine()


def context(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"trends": {"t1": make_trend()},
                            "style_briefs": {"t1": StyleBrief(trend_key="t1",
                                                              hook_pattern="short claim")},
                            "engine": engine(), "text_budgets": TextBudgets()}
    base.update(overrides)
    return base


# ------------------------------------------------------------------ FR-16/22/8 both-mode rule


async def test_both_mode_pair_gets_one_sibling_line_and_its_copyset_is_cloned() -> None:
    """A `both`-mode pair is ONE creative rendered two ways: one sibling line in the copy call,
    then the CopySet is cloned to the sibling's asset_id. Two lines would ask for two distinct
    angles for one creative (FR-99) and break the A/B comparison (FR-16) and reuse math (FR-8)."""
    entries = [
        entry("a1_analyzed", 0, variant="analyzed", pair_id="p1"),
        entry("a1_direct", 1, variant="direct", pair_id="p1"),
        entry("a2_analyzed", 2, variant="analyzed", pair_id="p2"),
        entry("a2_direct", 3, variant="direct", pair_id="p2"),
    ]
    call = StubCall({"a1_analyzed": answer(headline="Wired backwards"),
                     "a2_analyzed": answer(headline="Seven tools, one bill")})

    result = await copywrite.write_copy(entries, call=call, **context())

    assert len(call.calls) == 1, "one grouped call per (trend x language)"
    assert call.calls[0] == ["a1_analyzed", "a2_analyzed"], "one line per pair_id, not per asset"
    assert set(result.copy) == {e.asset_id for e in entries}
    for analyzed, direct in (("a1_analyzed", "a1_direct"), ("a2_analyzed", "a2_direct")):
        clone, source = result.copy[direct], result.copy[analyzed]
        assert clone.asset_id == direct
        assert (clone.headline, clone.caption, clone.hashtags, clone.hook_pattern_used) == (
            source.headline, source.caption, source.hashtags, source.hook_pattern_used)
    assert not result.degraded


async def test_one_call_per_trend_and_language_pair() -> None:
    entries = [entry("a1", 0), entry("a2", 1, language="cs"),
               entry("a3", 2, trend_key="t2", platform="instagram")]
    trends = {"t1": make_trend(), "t2": TrendItem(history_key="t2", monitor_id="m1", name="Other")}
    call = StubCall({name: answer() for name in ("a1", "a2", "a3")})

    await copywrite.write_copy(entries, call=call, **context(trends=trends))

    assert sorted(call.calls) == [["a1"], ["a2"], ["a3"]]


async def test_override_brief_creatives_group_by_brief_and_language() -> None:
    """Override briefs consume no trend (FR-144), so they group by brief x language (FR-146)."""
    entries = [entry("a1", 0, trend_key=None, brief_name="ai-audit-cta",
                     brief_influence="override"),
               entry("a2", 1, trend_key=None, brief_name="ai-audit-cta",
                     brief_influence="override")]
    call = StubCall({"a1": answer(), "a2": answer()})

    await copywrite.write_copy(entries, call=call, **context())

    assert call.calls == [["a1", "a2"]]


# ------------------------------------------------------------------ FR-99 split + degrade


async def test_failed_group_call_splits_into_one_call_per_creative() -> None:
    """Grouping is an efficiency; an efficiency may never widen the blast radius (10 §10)."""
    entries = [entry("a1", 0), entry("a2", 1), entry("a3", 2)]
    call = StubCall({name: answer() for name in ("a1", "a2", "a3")},
                    fail_when=lambda ids: len(ids) > 1)

    result = await copywrite.write_copy(entries, call=call, **context())

    assert call.calls[0] == ["a1", "a2", "a3"]
    assert sorted(call.calls[1:]) == [["a1"], ["a2"], ["a3"]]
    assert set(result.copy) == {"a1", "a2", "a3"}
    assert not result.degraded


async def test_a_creative_whose_split_call_also_fails_ships_no_onimage_text_at_all() -> None:
    """A20: the last-resort tier renders WORDLESS, never with the source's own hook.

    This test asserted the opposite until 2026-08-11 — it was named
    `..._ships_the_trends_own_hook` and required `headline` to equal the competitor's exact
    `hook_text`. That was the shipped behaviour, and the operator mandated its removal: the
    string flowed into `{{onimage_text}}`, which every render template calls "the ONLY source
    of renderable words", so a failed copy call baked a competitor's headline into the picture
    (and, on a carousel, their deck panel for panel). A text-free image on a proven layout is a
    usable creative; someone else's headline is not. The pair-cloning and both-variants-degraded
    guarantees below are unchanged — only the words are gone.
    """
    entries = [entry("a1", 0, pair_id="p1"), entry("a1_direct", 1, pair_id="p1")]
    call = StubCall({}, fail_when=lambda ids: True)

    result = await copywrite.write_copy(entries, call=call, **context())

    copyset = result.copy["a1"]
    assert copyset.headline == "", "the source's hook must never become our headline"
    assert copyset.subline == "" and copyset.overlay_text == ""
    assert copyset.slide_texts == []
    assert copyset.caption, "the caption survives — it is ours, built from the trend name"
    assert copyset.hashtags and copyset.hashtags[0].startswith("#")
    assert "copy_degraded" in copyset.hook_pattern_used
    assert result.degraded == frozenset({"a1", "a1_direct"}), "both variants are degraded"
    assert result.copy["a1_direct"].headline == copyset.headline


async def test_a_partial_group_response_only_splits_the_missing_creatives() -> None:
    entries = [entry("a1", 0), entry("a2", 1)]
    call = StubCall({"a1": answer()})  # a2 simply absent from the grouped response

    result = await copywrite.write_copy(entries, call=call, **context())

    assert call.calls == [["a1", "a2"], ["a2"]]
    assert result.degraded == frozenset({"a2"})


# ------------------------------------------------------------------ FR-101 budgets


async def test_over_budget_on_image_text_is_trimmed_at_a_word_boundary() -> None:
    long_headline = "Most people wire their entire AI stack backwards and never notice"
    call = StubCall({"a1": answer(headline=long_headline, subline="short")})

    result = await copywrite.write_copy([entry("a1", 0)], call=call,
                                        **context(text_budgets=TextBudgets(image_headline=42)))

    headline = result.copy["a1"].headline
    assert len(headline) <= 42
    assert long_headline.startswith(headline)
    assert not headline.endswith(" ") and headline.split()[-1] in long_headline.split()
    assert result.trimmed == frozenset({"a1"})


async def test_reel_overlay_text_uses_the_seed_frame_budget() -> None:
    call = StubCall({"a1": answer(overlay_text="Nobody tells you this one simple thing",
                                  headline="short")})

    result = await copywrite.write_copy(
        [entry("a1", 0, creative_format="reel", aspect_ratio="9:16")], call=call,
        **context(text_budgets=TextBudgets(reel_seed_headline=32)))

    assert len(result.copy["a1"].overlay_text) <= 32
    assert result.trimmed == frozenset({"a1"})


async def test_carousel_slide_texts_are_each_trimmed_and_survive_as_a_sequence() -> None:
    call = StubCall({"a1": answer(
        slide_texts=["Short one", "A slide line that runs far past the configured budget", "三"],
        narrative_arc="hook, escalation, payoff")})

    result = await copywrite.write_copy(
        [entry("a1", 0, creative_format="carousel", slide_count=3)], call=call,
        **context(text_budgets=TextBudgets(image_headline=20)))

    slides = result.copy["a1"].slide_texts
    assert len(slides) == 3 and all(len(text) <= 20 for text in slides)
    assert slides[0] == "Short one"
    assert result.trimmed == frozenset({"a1"})


async def test_copy_inside_budget_is_never_touched() -> None:
    call = StubCall({"a1": answer(headline="Wired backwards", subline="and it costs them")})
    result = await copywrite.write_copy([entry("a1", 0)], call=call, **context())
    assert result.copy["a1"].headline == "Wired backwards"
    assert not result.trimmed


# ------------------------------------------------------------------ prompt contents


async def test_the_sibling_list_names_format_platform_and_both_languages() -> None:
    entries = [entry("a1", 0, creative_format="carousel", slide_count=5)]
    call = StubCall({"a1": answer()})

    await copywrite.write_copy(entries, call=call,
                               onimage_languages={"a1": "cs"}, **context())

    line = next(l for l in call.prompts[0].splitlines() if l.startswith("- a1"))
    assert "linkedin" in line and "carousel" in line
    assert "caption en" in line and "on-image cs" in line and "5 slides" in line


async def test_hook_pattern_is_carried_through_for_the_audit_trail() -> None:
    call = StubCall({"a1": answer(hook_pattern_used="numbered promise, colon, concrete noun")})
    result = await copywrite.write_copy([entry("a1", 0)], call=call, **context())
    assert result.copy["a1"].hook_pattern_used == "numbered promise, colon, concrete noun"


async def test_brand_context_reaches_the_copywriter_but_never_a_render_prompt() -> None:
    call = StubCall({"a1": answer()})
    await copywrite.write_copy([entry("a1", 0)], call=call,
                               brand_context="ACME voice: plain, declarative", **context())
    assert "ACME voice: plain, declarative" in call.prompts[0]
