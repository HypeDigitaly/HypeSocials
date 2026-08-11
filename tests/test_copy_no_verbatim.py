"""A20 — the copy engine never reuses the source's own words, on any path.

This is the wave barrier for the substance channel. Until 2026-08-11 `copywrite._fallback_copy`
set `headline` to the competitor's exact `hook_text`, `slide_texts` to the source deck's panel
copy slide for slide, and `overlay_text` to the same hook for a reel — and those strings flow
into `prompts_engine._onimage_text`, which emits them as `headline (render verbatim): "…"` inside
the block every render template calls *the ONLY source of renderable words*. The operator's
mandate is "no plagiarism", so that path is gone: a creative whose copy call failed ships with NO
on-image text at all.

The tests below are written to FAIL LOUDLY if it ever comes back. Every trend here carries
distinctive sentinel strings in all three literal fields (`hook_texts`,
`text_overlay_contents`, `panel_texts`), and the assertion is not "the headline changed" but
"no sentinel appears anywhere in the resulting CopySet, in any field, including the caption".

A21's `hook_pattern_used` validator shares the file because it is the same discipline seen from
the other end: A20 stops the ENGINE reproducing a hook, A21 stops the MODEL getting away with a
pattern note that never described one.

No network: the `llm.structured_call` seam is a stub matching `models.StructuredCall`.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from hypesocials import copywrite
from hypesocials import prompts_engine as pe
from hypesocials.config import TextBudgets
from hypesocials.models import (
    PLACEHOLDERS,
    CopySet,
    DegradationTag,
    LayoutZone,
    ParsedResult,
    PlanEntry,
    StyleBrief,
    TrendItem,
)
from hypesocials.prompts_engine import PromptEngine, build_context

#: Nonsense on purpose: any of these turning up in a `CopySet` can only have come from the trend.
HOOK = "ZZQHOOK Remember what nobody told you"
OVERLAY = "ZZQOVERLAY ChatGPT is not the only one"
PANELS = ["ZZQPANELONE the landscape", "ZZQPANELTWO the shortlist", "ZZQPANELTHREE the pick"]
SENTINELS = ("ZZQHOOK", "ZZQOVERLAY", "ZZQPANELONE", "ZZQPANELTWO", "ZZQPANELTHREE")

NICHE = "AI automation for Czech SMBs; audience: operations leads who buy outcomes."


class DeadCall:
    """A `StructuredCall` that never produces a usable answer — every attempt degrades.

    This is the shape FR-99's last resort exists for: the grouped call fails, each per-creative
    split call fails too, and nothing is left but a deterministic copy set.
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


def answer(**overrides: Any) -> dict[str, Any]:
    payload = {"hook_pattern_used": "Withheld-subject claim, second person, one short clause",
               "caption": "Most teams wire this backwards.", "hashtags": ["#ai"],
               "hook_line": "Most teams wire this backwards", "headline": "Wired backwards",
               "subline": "and it costs them", "slide_texts": [], "narrative_arc": "",
               "overlay_text": "", "through_line": ""}
    payload.update(overrides)
    return payload


def trend() -> TrendItem:
    return TrendItem(history_key="t1", monitor_id="m1", name="AI Trends Tracker",
                     why_it_works="a withheld subject in the first line",
                     hook_texts=[HOOK], text_overlay_contents=[OVERLAY], panel_texts=list(PANELS))


def entry(asset_id: str = "a1", order: int = 0, **overrides: Any) -> PlanEntry:
    plan_entry = PlanEntry(order=order, asset_id=asset_id, creative_format="image",
                           platform="linkedin", language="en", aspect_ratio="16:9",
                           trend_key="t1")
    for key, value in overrides.items():
        setattr(plan_entry, key, value)
    return plan_entry


async def write(entries, call, **overrides: Any) -> copywrite.CopyResult:
    kwargs: dict[str, Any] = {"trends": {"t1": trend()}, "engine": PromptEngine(),
                              "text_budgets": TextBudgets(), "niche_descriptor": NICHE}
    kwargs.update(overrides)
    return await copywrite.write_copy(entries, call=call, **kwargs)


def leaks(copyset) -> list[str]:
    """Every sentinel found anywhere in the copy set — the whole object, not a chosen field.

    Walks the dataclass rather than naming fields, so a field added to `CopySet` tomorrow is
    covered by this barrier the moment it exists.
    """
    blob = " ".join(
        " ".join(str(item) for item in value) if isinstance(value, list) else str(value)
        for value in dataclasses.asdict(copyset).values())
    return [sentinel for sentinel in SENTINELS if sentinel in blob]


# ------------------------------------------------------------------ A20: the no-text tier


async def test_a_failed_image_ships_no_on_image_text_and_no_source_words() -> None:
    """The single-image shape. Empty on-image fields, and not one sentinel anywhere."""
    call = DeadCall()

    result = await write([entry()], call)

    copyset = result.copy["a1"]
    assert (copyset.headline, copyset.subline, copyset.overlay_text) == ("", "", "")
    assert copyset.slide_texts == []
    assert leaks(copyset) == [], "the source's own words reached the copy set"
    assert copyset.caption, "the caption is what survives the degrade — it must not be empty"


async def test_a_failed_carousel_does_not_reproduce_the_source_deck_panel_by_panel() -> None:
    """The shape that used to be worst: `slide_texts = trend.panel_texts[:slide_count]` copied a
    winning deck slide for slide, which is reproduction of a whole creative, not of one line."""
    call = DeadCall()

    result = await write([entry("a1", 0, creative_format="carousel", slide_count=3)], call)

    copyset = result.copy["a1"]
    assert copyset.slide_texts == []
    assert copyset.headline == ""
    assert leaks(copyset) == []


async def test_a_failed_reel_does_not_burn_the_source_hook_into_the_seed_frame() -> None:
    """A reel's `overlay_text` is baked into the seed frame AND locked as a fixed graphic layer
    for the whole clip by `reel_director.md` — the longest-lived copy of a borrowed string."""
    call = DeadCall()

    result = await write([entry("a1", 0, creative_format="reel", aspect_ratio="9:16")], call)

    copyset = result.copy["a1"]
    assert copyset.overlay_text == "" and copyset.headline == ""
    assert leaks(copyset) == []


async def test_the_degraded_caption_is_assembled_from_our_own_words() -> None:
    """Trend name plus the operator's niche descriptor — never the source hook (A20 point 2)."""
    result = await write([entry()], DeadCall())

    caption = result.copy["a1"].caption
    assert "AI Trends Tracker" in caption
    assert "AI automation for Czech SMBs" in caption
    assert not any(sentinel in caption for sentinel in SENTINELS)


async def test_both_degradation_shapes_are_tagged_and_stay_distinguishable() -> None:
    """`copy_degraded` is the LLM outcome the run summary counts; `no_onimage_text` is what the
    operator will actually see in the frame. Both reach meta.yaml and the gallery via the tags."""
    entries = [entry("a1", 0, pair_id="p1"), entry("a1_direct", 1, pair_id="p1")]

    result = await write(entries, DeadCall())

    for asset_id in ("a1", "a1_direct"):  # FR-16: a both-mode pair degrades as one creative
        assert set(result.tags[asset_id]) == {DegradationTag.COPY_DEGRADED,
                                              DegradationTag.NO_ONIMAGE_TEXT}
    assert result.degraded == frozenset({"a1", "a1_direct"})


async def test_the_fallback_never_reads_the_trends_literal_fields_at_all() -> None:
    """A structural check next to the behavioural ones: the same entry against a trend WITH the
    literal fields and one WITHOUT them must produce identical copy. If any of the three ever
    became an input again, these two would differ."""
    bare = TrendItem(history_key="t1", monitor_id="m1", name="AI Trends Tracker",
                     why_it_works="a withheld subject in the first line")

    with_texts = await write([entry()], DeadCall())
    without = await write([entry()], DeadCall(), trends={"t1": bare})

    assert with_texts.copy["a1"] == without.copy["a1"]


# ------------------------------------------- A20 at the ONLY level that actually spends money
#
# Everything above asserts on a `CopySet`. That is the object, not the risk. The risk is the
# finished string handed to the image model — the one place a borrowed hook becomes pixels — and
# between the two sits `prompts_engine._onimage_text`, which turns `headline` into
# `headline (render verbatim): "…"` plus a letter-by-letter spelling aid inside the block every
# render template calls *the ONLY source of renderable words*. So the barrier is re-asserted at
# the assembled prompt, for all four gpt-image-2 roles.
#
# Note what the trend is doing in these contexts: it is PASSED to `build_context` exactly as
# `generate._assemble` passes it, so `{{trend_texts}}` and `{{source_hooks}}` are sitting in the
# context, full of sentinels, while the render role is rendered. They stay out because no render
# role's allowlist names them — which is the property `test_the_source_text_slots_…` below pins
# structurally, and which these tests prove end to end.

RENDER_PROFILE = "gpt-image-2"

def brief() -> StyleBrief:
    """A style brief with NO sentinels in it, deliberately.

    A brief's `exclusions` list is *supposed* to carry the source's literal strings — it is the
    "never reproduce these" channel and the one appearance of source words A20 exists to allow —
    so seeding it would fail this barrier for the exact behaviour the barrier is protecting.
    """
    return StyleBrief(
        trend_key="t1",
        layout_zones=[LayoutZone("upper third", "headline", "all caps, extra bold")],
        exclusions=["platform UI", "follower counters"],
        render_prompt="Near-black ground, one electric accent, heavy geometric sans headline.",
        palette=["#0B0B0C", "#3DDC97"], typography="extra-bold condensed sans",
        text_placement="headline upper third", image_treatment="flat graphic",
        visual_pacing="eye lands on the headline",
        hook_pattern="withheld-subject claim", content_angle="workflow before tooling")


def render_prompts(copyset: CopySet, *, slide_count: int = 0) -> dict[str, str]:
    """Every gpt-image-2 role this copy set can reach, assembled the way `generate` assembles it.

    `image_single_post.md` is the analyzed single image, `image_direct.md` the direct one,
    `carousel_slide.md` once per slide of the deck, `reel_seed_frame.md` the reel's hook frame.
    """
    engine = PromptEngine()
    shared: dict[str, Any] = {
        "trend": trend(), "copy": copyset, "text_budgets": TextBudgets(),
        "reference_roles": ["Image 1 — style, layout and palette reference"],
        "reference_image_count": 1, "niche_descriptor": NICHE,
        "niche_visual_world": "dark UI and dashboard screenshots on near-black",
        "brand_accent": "#3DDC97", "brand_product_nouns": ["AI audit"],
    }
    out = {
        "image_single_post.md": engine.render(
            "image_single_post.md",
            build_context(style_brief=brief(), creative_format="image", **shared),
            profile=RENDER_PROFILE),
        "image_direct.md": engine.render(
            "image_direct.md", build_context(creative_format="image", **shared),
            profile=RENDER_PROFILE),
        "reel_seed_frame.md": engine.render(
            "reel_seed_frame.md",
            build_context(style_brief=brief(), creative_format="reel", **shared),
            profile=RENDER_PROFILE),
    }
    for index in range(1, slide_count + 1):
        slides = copyset.slide_texts
        out[f"carousel_slide.md #{index}"] = engine.render(
            "carousel_slide.md",
            build_context(style_brief=brief(), creative_format="carousel",
                          slide_index=f"{index} of {slide_count}",
                          slide_text=slides[index - 1] if index <= len(slides) else "", **shared),
            profile=RENDER_PROFILE)
    return out


def sentinels_in(prompts: dict[str, str]) -> list[str]:
    """`role: sentinel` for every source string that reached a finished render prompt."""
    return [f"{role}: {sentinel}" for role, prompt in prompts.items()
            for sentinel in SENTINELS if sentinel in prompt]


async def test_a_healthy_copy_set_really_does_reach_the_render_prompt() -> None:
    """The control. Without it every assertion below could pass on a prompt builder that dropped
    the on-image text entirely, and the barrier would be measuring nothing."""
    call = ScriptedCall({"a1": [answer(headline="Wired backwards", overlay_text="Trace one flow",
                                       slide_texts=["Slide one line", "Slide two line"])]})
    result = await write([entry("a1", 0, creative_format="carousel", slide_count=2)], call)

    prompts = render_prompts(result.copy["a1"], slide_count=2)

    assert 'headline (render verbatim): "Wired backwards"' in prompts["image_single_post.md"]
    assert "W-i-r-e-d b-a-c-k-w-a-r-d-s" in prompts["image_single_post.md"]
    assert "Wired backwards" in prompts["image_direct.md"]
    assert "Trace one flow" in prompts["reel_seed_frame.md"]
    assert "Slide one line" in prompts["carousel_slide.md #1"]
    assert "Slide two line" in prompts["carousel_slide.md #2"]


async def test_a_failed_single_image_assembles_a_prompt_with_no_source_words_in_it() -> None:
    """`image_single_post.md` (analyzed) and `image_direct.md` (direct), the two single-image roles."""
    result = await write([entry()], DeadCall())

    prompts = render_prompts(result.copy["a1"])

    assert sentinels_in(prompts) == [], "the source's own words reached a paid render prompt"
    for role in ("image_single_post.md", "image_direct.md"):
        assert "render verbatim" not in prompts[role], f"{role} quoted a string it does not have"
        assert "{{" not in prompts[role], f"{role} left a raw placeholder (FR-260)"


async def test_a_failed_carousel_assembles_four_slides_with_no_source_deck_in_them() -> None:
    """The shape that used to reproduce a winning deck panel for panel. Four slides, and the
    sentinels sit in `panel_texts` — the exact list `slide_texts` was sliced from."""
    result = await write([entry("a1", 0, creative_format="carousel", slide_count=4)], DeadCall())

    prompts = render_prompts(result.copy["a1"], slide_count=4)
    slides = {role: text for role, text in prompts.items() if role.startswith("carousel_slide")}

    assert len(slides) == 4
    assert sentinels_in(prompts) == []
    for role, prompt in slides.items():
        assert "render verbatim" not in prompt, f"{role} carried a quoted string"
        assert "{{" not in prompt


async def test_a_failed_reel_seed_frame_burns_no_source_hook_into_the_picture() -> None:
    """The longest-lived copy of a borrowed string: the seed frame bakes it in, and
    `reel_director.md` then locks it as a fixed graphic layer for the whole clip."""
    result = await write([entry("a1", 0, creative_format="reel", aspect_ratio="9:16")], DeadCall())

    prompts = render_prompts(result.copy["a1"])

    assert sentinels_in(prompts) == []
    assert "render verbatim" not in prompts["reel_seed_frame.md"]


def test_the_source_text_slots_are_allowlisted_for_copy_and_analysis_roles_only() -> None:
    """The structural half of A20: three slots carry the competitor's literal words into a prompt,
    and NO render role may resolve any of them.

    This is what makes the behavioural tests above load-bearing rather than lucky. `build_context`
    fills `{{trend_texts}}`, `{{source_hooks}}` and `{{inspiration_exemplars}}` on every call,
    render roles included — the allowlist is the only thing standing between those values and an
    image prompt. Re-open one of these three for a render role and `render()` starts substituting
    scraped hooks into the block the template calls the only source of renderable words.
    """
    render_roles = {"image_single_post.md", "carousel_slide.md", "image_direct.md",
                    "reel_seed_frame.md", "carousel_anchor_instruction.md", "reel_director.md"}
    expected = {"trend_texts": {"style_brief_system.md", "copywriter_system.md"},
                "source_hooks": {"copywriter_system.md"},
                "inspiration_exemplars": {"copywriter_system.md"}}

    for name, owners in expected.items():
        assert name in PLACEHOLDERS, f"{name} left the vocabulary — this guard now checks nothing"
        holders = {role for role in pe._ALLOWLIST if name in pe.allowlist(role)}
        assert holders == owners, f"{name} is allowlisted for {sorted(holders)}"
        assert not holders & render_roles, f"{name} reached a render role"
    assert set(expected) <= set(pe._TRUNCATION_ORDER), \
        "a source-text slot outside the truncation order is the one block a long prompt can never cut"


def test_a_render_role_naming_a_source_text_slot_never_resolves_it(tmp_path) -> None:
    """The allowlist checked at the only level that matters: a template file that DID name one.

    FR-183 refuses the file at load and ships the built-in instead, so the sentinel never reaches
    a prompt even when the template on disk asks for it by name. Written out because "it is not in
    the allowlist" and "it cannot reach the model" are two different claims.
    """
    profile_dir = tmp_path / RENDER_PROFILE
    profile_dir.mkdir()
    (profile_dir / "image_direct.md").write_text(
        "SUBJECT: {{content_sentence}}\nHOOKS: {{source_hooks}}\nTREND: {{trend_texts}}\n",
        encoding="utf-8")
    engine = PromptEngine(prompts_dir=tmp_path)

    rendered = engine.render("image_direct.md", build_context(trend=trend(), creative_format="image"),
                             profile=RENDER_PROFILE)

    assert engine.template("image_direct.md", profile=RENDER_PROFILE).origin == "built-in default"
    assert not any(sentinel in rendered for sentinel in SENTINELS)


# ------------------------------------------------------------------ A21: the hook-pattern bar


async def test_a_generic_hook_pattern_costs_one_reask_and_then_ships_tagged() -> None:
    """One re-ask, never a loop; a thin audit note never fails a creative."""
    call = ScriptedCall({"a1": [answer(hook_pattern_used="curiosity hook"),
                                answer(hook_pattern_used="engaging hook")]})

    result = await write([entry()], call)

    assert call.calls == [["a1"], ["a1"]], "exactly one re-ask, and only of that creative"
    assert DegradationTag.HOOK_PATTERN_GENERIC in result.tags["a1"]
    assert result.copy["a1"].headline == "Wired backwards", "the copy itself still ships"
    assert not result.degraded, "a weak pattern is not a copy failure"


async def test_a_reask_that_clears_the_bar_replaces_the_generic_answer_untagged() -> None:
    good = "Curiosity-and-reveal claim, second person, direct address with a withheld subject"
    call = ScriptedCall({"a1": [answer(hook_pattern_used="hook"),
                                answer(hook_pattern_used=good, headline="Second time")]})

    result = await write([entry()], call)

    assert result.copy["a1"].hook_pattern_used == good
    assert result.copy["a1"].headline == "Second time"
    assert result.tags.get("a1") is None


async def test_a_good_hook_pattern_is_never_reasked() -> None:
    call = ScriptedCall({"a1": [answer()]})

    result = await write([entry()], call)

    assert call.calls == [["a1"]]
    assert not result.tags


def test_the_validator_matches_the_bar_the_template_promises_the_model() -> None:
    """`prompts/copywriter_system.md` states 30 characters, four distinct content words, and five
    rejected values by name. Code and template are one contract — this is where they are checked
    against each other."""
    passing = "Curiosity-and-reveal claim, second person, direct address with a withheld subject"
    assert not copywrite._hook_pattern_generic({"hook_pattern_used": passing})
    assert len(passing) >= copywrite._HOOK_PATTERN_MIN_CHARS

    for phrase in ("curiosity hook", "engaging hook", "attention grabber", "hook",
                   "pattern interrupt"):
        assert copywrite._hook_pattern_generic({"hook_pattern_used": phrase}), phrase
        assert copywrite._hook_pattern_generic({"hook_pattern_used": phrase.title() + "."}), phrase

    # Long enough for the length rule, still nothing but genre labels.
    assert copywrite._hook_pattern_generic(
        {"hook_pattern_used": "attention grabber, pattern interrupt, curiosity hook"})
    assert copywrite._hook_pattern_generic({"hook_pattern_used": ""})
    # Absent means "no answer at all", which is FR-99's business rather than this check's.
    assert not copywrite._hook_pattern_generic(None)


# ------------------------------------------- A21: the CODE and the TEMPLATE are one contract
#
# `copywrite.py:87-98` says so in a comment: the template promises the model "at least 30
# characters and at least four distinct content words" and names five rejected values, and those
# words come from the four constants. A comment cannot enforce that. Below, the template is READ
# and the numbers and phrases it states to the model are checked against what the code enforces —
# in both directions, so tightening the code or loosening the prompt both fail here.

#: Only the numbers a bar this size can plausibly state. The template writes them as words.
NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
                8: "eight", 9: "nine", 10: "ten"}


def one_line(text: str) -> str:
    """The template is hard-wrapped at ~72 columns, so every stated rule spans two or three
    lines. Collapse before matching, or the assertions test the line breaks."""
    return " ".join(text.split())


def copywriter_template() -> str:
    return one_line((pe.PROMPTS_DIR / "copywriter_system.md").read_text(encoding="utf-8"))


def test_the_template_states_the_exact_thresholds_the_code_enforces() -> None:
    """Numbers first. The template names both; drift either way lies to the model about how its
    answer is judged, which is the one thing a prompt must never do."""
    stated = copywriter_template().casefold()
    words = NUMBER_WORDS[copywrite._HOOK_PATTERN_MIN_CONTENT_WORDS]

    assert f"at least {copywrite._HOOK_PATTERN_MIN_CHARS} characters" in stated
    assert f"at least {words} distinct content words" in stated
    # And the built-in copy of the same template says it too (FR-183: it is what actually ships
    # when the file is unreadable, and a fallback that advertises a different bar is a silent lie).
    built_in = one_line(pe._BUILT_INS["copywriter_system.md"]).casefold()
    assert f"at least {copywrite._HOOK_PATTERN_MIN_CHARS} characters" in built_in
    assert f"at least {words} distinct content words" in built_in


def test_the_phrases_the_template_rejects_by_name_are_exactly_the_code_blocklist() -> None:
    """Both directions. A phrase the template names and the code accepts is a bar the model is
    told about and never held to; one the code rejects and the template never names is a rewrite
    the model was given no way to avoid."""
    stated = copywriter_template()
    sentence = stated.split("rejected outright:", 1)[1].split("Naming the genre", 1)[0]
    named = {phrase.casefold() for phrase in re.findall(r'"([^"]+)"', sentence)}

    assert named == set(copywrite._GENERIC_HOOK_PATTERNS), \
        f"template names {sorted(named)}, code blocks {sorted(copywrite._GENERIC_HOOK_PATTERNS)}"
    for phrase in named:  # …and each one really is refused, in the shapes a model writes them in
        for variant in (phrase, phrase.title(), phrase.upper(), f"{phrase.capitalize()}.",
                        f"  {phrase}  "):
            assert copywrite._hook_pattern_generic({"hook_pattern_used": variant}), variant


def test_the_passing_example_the_template_shows_the_model_actually_passes() -> None:
    """The template quotes one real value from a live run as "a passing value reads like this".
    If the code rejected it, every creative would burn a re-ask following the instructions."""
    stated = copywriter_template()
    example = re.search(r'A passing value reads like this[^"]*"([^"]+)"', stated)

    assert example is not None, "the template no longer shows the model a passing example"
    value = example.group(1)
    assert not copywrite._hook_pattern_generic({"hook_pattern_used": value}), value
    assert len(value) >= copywrite._HOOK_PATTERN_MIN_CHARS


def test_a_long_but_generic_value_and_an_empty_one_both_fail_while_a_czech_one_passes() -> None:
    """The three edges the thresholds exist for, plus the one the STOPWORD list exists for.

    `_HOOK_PATTERN_STOPWORDS` is English-only on purpose (`copywrite.py:109-116`): a Czech or
    German pattern line contains none of them, so every word counts and the bar is EASIER to
    clear. A validator that rejected a good non-English answer would be the worse failure.
    """
    assert copywrite._hook_pattern_generic(
        {"hook_pattern_used": "attention grabber and pattern interrupt, a curiosity hook"})
    assert copywrite._hook_pattern_generic({"hook_pattern_used": ""})
    assert copywrite._hook_pattern_generic({"hook_pattern_used": "   "})
    assert copywrite._hook_pattern_generic({"hook_pattern_used": "short claim, two words"})
    czech = "Tvrzení se zadrženým podmětem, druhá osoba, přímé oslovení"
    assert not copywrite._hook_pattern_generic({"hook_pattern_used": czech})


async def test_a_reask_that_answers_nothing_leaves_the_original_and_still_tags() -> None:
    """The re-ask can only improve an answer. A retry that comes back empty-handed must not blank
    the pattern that was already there — the copy ships, tagged, with the weak note attached."""
    call = ScriptedCall({"a1": [answer(hook_pattern_used="pattern interrupt")]})  # nothing for #2

    result = await write([entry()], call)

    assert call.calls == [["a1"], ["a1"]]
    assert result.copy["a1"].hook_pattern_used == "pattern interrupt"
    assert DegradationTag.HOOK_PATTERN_GENERIC in result.tags["a1"]
    assert not result.degraded, "a thin audit note is never a copy failure"


async def test_only_the_generic_sibling_is_reasked_and_a_pair_is_tagged_as_one_creative() -> None:
    """Scope. The re-ask is per creative, not per group — asking the whole group again would
    re-bill every sibling for one weak note — and a both-mode pair tags as one creative (FR-16)."""
    good = "Curiosity-and-reveal claim, second person, direct address with a withheld subject"
    entries = [entry("a1", 0, pair_id="p1"), entry("a1_direct", 1, pair_id="p1"),
               entry("a2", 2)]
    call = ScriptedCall({"a1": [answer(hook_pattern_used="hook"),
                                answer(hook_pattern_used="engaging hook")],
                         "a2": [answer(hook_pattern_used=good)]})

    result = await write(entries, call)

    assert call.calls == [["a1", "a2"], ["a1"]], "one grouped call, then one re-ask of a1 alone"
    for asset_id in ("a1", "a1_direct"):
        assert DegradationTag.HOOK_PATTERN_GENERIC in result.tags[asset_id]
    assert "a2" not in result.tags


async def test_the_generic_tag_reaches_the_asset_record_the_gallery_reads(tmp_path) -> None:
    """A21 says the second failure is "logged and marked on the asset". `CopyResult.tags` is the
    carrier `generate._record` copies into `AssetRecord.degradations`, which is what meta.yaml and
    the gallery badges are built from — so the tag is worth nothing until it lands there."""
    from hypesocials import generate
    from hypesocials.budget import Budget
    from hypesocials.config import Config
    from hypesocials.outputs import Ledger

    call = ScriptedCall({"a1": [answer(hook_pattern_used="curiosity hook"),
                                answer(hook_pattern_used="curiosity hook")]})
    result = await write([entry()], call)

    env = generate.Env(config=Config(), run_dir=tmp_path, engine=PromptEngine(),
                       budget=Budget(1.0), log=None, ledger=Ledger(tmp_path),
                       trends={"t1": trend()}, copy=result.copy, copy_tags=result.tags)
    record = generate._record(entry(), env)

    assert DegradationTag.HOOK_PATTERN_GENERIC in record.degradations
    assert record.hook_pattern_used == "curiosity hook", "the weak note stays attached, verbatim"
