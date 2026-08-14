"""FR-105 v2.1.1 — the check's third question, and the retry that may not trim a quote.

Two defects shipped together on 2026-08-13 and both live in `hypesocials/vision_check.py`:

1. **The check could not see a text MISMATCH.** The question was rendered with an empty context and
   asked about two defects, so a slide whose render carried clean, legible, *invented* words passed
   — which is exactly what the audited run delivered against a source panel reading
   "CLAUDE + OBSIDIAN = 71.5X FEWER TOKENS". The fix is a referent: the locked text now travels in
   the call, one string per image, and an EMPTY string is the stronger statement ("this one is
   wordless — any words are a defect").
2. **The retry trimmed verbatim text against the wrong budget.** A 131-character mapped panel came
   back as a 53-character mid-sentence stub, because the cut was `image_headline` (90) × 0.6 and
   applied to a quote nobody may shorten (FR-304 > FR-105).

Everything here is a pure unit test of that module: the LLM is a recording fake, the engine is the
real `PromptEngine` reading the real `prompts/vision_check_question.md`, and nothing touches the
network, the filesystem or money.
"""

from __future__ import annotations

from typing import Any

import pytest

from hypesocials import vision_check
from hypesocials.config import TextBudgets
from hypesocials.models import CopySet, ParsedResult, VisionCheckResult
from hypesocials.prompts_engine import PromptEngine

#: The audited run's real source panel — 131 characters, which is over `image_headline` (90) and
#: comfortably under the `slide` budget (300) that actually governs a deck slide.
PANEL = ("Claude reads your whole vault every single time and Obsidian's index does not — "
         "that one swap is where the 71.5x saving comes from.")


class RecordingCall:
    """A `models.StructuredCall` that remembers what it was asked and answers from a table."""

    def __init__(self, verdicts: list[dict[str, Any]] | None = None) -> None:
        self.verdicts = verdicts
        self.messages: list[list[dict[str, str]]] = []
        self.schemas: list[dict[str, Any]] = []

    async def __call__(self, role, messages, json_schema, images=None) -> ParsedResult:
        self.messages.append([dict(message) for message in messages])
        self.schemas.append(json_schema)
        rows = self.verdicts if self.verdicts is not None else [
            {"image": index, "text_broken": False, "fake_ui": False, "text_mismatch": False,
             "detail": ""} for index in range(1, len(images or []) + 1)]
        return ParsedResult(parsed={"verdicts": rows}, raw_text="{}")

    @property
    def user_turn(self) -> str:
        """The carrier turn of the LAST call — where the expected text rides."""
        return next(message["content"] for message in reversed(self.messages[-1])
                    if message["role"] == "user")

    @property
    def system_turn(self) -> str:
        return next(message["content"] for message in self.messages[-1]
                    if message["role"] == "system")


def budgets() -> TextBudgets:
    return TextBudgets()


# ------------------------------------------------------------------ the expected text on the wire


async def test_the_check_carries_each_images_locked_text_as_the_mismatch_referent() -> None:
    """GAP 1, the wire half: the panel's own words appear in the call, quoted, per image.

    Without this the third question is unanswerable and the model can only say "the text is
    legible" — which the audited run's invented copy was.
    """
    call = RecordingCall()

    report = await vision_check.check([b"\xff\xd8one", b"\xff\xd8two"],
                                      expected=[PANEL, "Slide two says this"],
                                      call=call, engine=PromptEngine())

    assert report.checked is True
    assert f'image 1: "{PANEL}"' in call.user_turn
    assert 'image 2: "Slide two says this"' in call.user_turn
    assert "EXPECTED TEXT" in call.user_turn
    # The QUESTION stays in the template (FR-180); only the data rides the carrier.
    assert "TEXT MISMATCH" in call.system_turn and PANEL not in call.system_turn


async def test_a_wordless_slide_sends_an_empty_expectation_rather_than_no_line() -> None:
    """FR-304's wordless panel is a REQUIREMENT, not an absence: nothing may appear there.

    An omitted line would let the model treat invented words as unjudgeable; the `(none)` token is
    named in the template and means the opposite.
    """
    call = RecordingCall()

    await vision_check.check([b"\xff\xd8a", b"\xff\xd8b"], expected=[PANEL, ""],
                             call=call, engine=PromptEngine())

    assert "image 2: (none)" in call.user_turn
    assert "(none)" in call.system_turn, "the template must teach the token the carrier sends"


async def test_a_caller_offering_no_expected_text_sends_no_expected_block() -> None:
    """`expected=None` is "I have no referent" — the template then answers the question false."""
    call = RecordingCall()

    await vision_check.check([b"\xff\xd8a"], call=call, engine=PromptEngine())

    assert "EXPECTED TEXT" not in call.user_turn
    assert "in the order attached." in call.user_turn


async def test_an_image_past_a_short_expected_list_gets_no_row_rather_than_an_empty_one() -> None:
    """"I did not say" and "it must say nothing" are opposite claims and must not collapse.

    An empty expectation is the strong one; inferring it from a caller's omission would flag every
    legitimate word on that image.
    """
    call = RecordingCall()

    await vision_check.check([b"\xff\xd8a", b"\xff\xd8b"], expected=[PANEL],
                             call=call, engine=PromptEngine())

    assert f'image 1: "{PANEL}"' in call.user_turn
    assert "image 2:" not in call.user_turn


async def test_the_schema_requires_the_third_verdict_and_a_mismatch_flags_the_image() -> None:
    """GAP 1, the verdict half: `text_mismatch` is strict-required and is a flag on its own.

    A render can be perfectly legible, free of platform chrome, and still say something nobody
    ordered — that asset must earn the same single retry as a garbled one.
    """
    call = RecordingCall([{"image": 1, "text_broken": False, "fake_ui": False,
                           "text_mismatch": True, "detail": "shows unrelated copy"}])

    report = await vision_check.check([b"\xff\xd8a"], expected=[PANEL], call=call,
                                      engine=PromptEngine())
    verdict = report.verdict_for(1)

    assert call.schemas[0]["schema"]["properties"]["verdicts"]["items"]["required"] == [
        "image", "text_broken", "fake_ui", "text_mismatch", "detail"]
    assert verdict is not None and verdict.text_mismatch is True
    assert verdict.text_broken is False and verdict.fake_ui is False
    assert verdict.flagged is True, "a mismatch alone earns FR-105's one retry"
    assert vision_check.verdict_result(verdict) is VisionCheckResult.RETRIED_FAILED


async def test_an_unreadable_input_takes_its_expected_string_with_it() -> None:
    """The two lists are renumbered by ONE table (`positions`) or they shift apart.

    A mismatch verdict rendered against the wrong slide's text is worse than no verdict at all, and
    this is the only place the drop is known.
    """
    call = RecordingCall()

    report = await vision_check.check(["/no/such/file.jpg", b"\xff\xd8real"],
                                      expected=["never rendered", PANEL],
                                      call=call, engine=PromptEngine())

    assert f'image 1: "{PANEL}"' in call.user_turn, "the surviving image keeps ITS own text"
    assert "never rendered" not in call.user_turn
    assert [v.index for v in report.verdicts] == [2], "verdict indices stay the CALLER's positions"


# --------------------------------------------------------------- what the expected text is built of


def test_expected_text_is_the_block_the_render_was_ordered_to_draw() -> None:
    """One implementation of "what did we order", mirroring `prompts_engine._onimage_text`."""
    copy = CopySet(asset_id="a", language="en", headline="Wired backwards", subline="here is why",
                   overlay_text="Stop doing this", slide_texts=["one"])

    assert vision_check.expected_text(copy, "image") == "Wired backwards\nhere is why"
    assert vision_check.expected_text(copy, "reel") == "Stop doing this"
    assert vision_check.expected_text(copy, "carousel", slide_text=PANEL) == PANEL
    # FR-304: a deck's rendered words are its slide text alone — `carousel.py` blanks the headline
    # for a wordless panel, so no headline fallback may leak in here either.
    assert vision_check.expected_text(copy, "carousel", slide_text="") == ""
    # B1/M12: the wordmark renders THROUGH the text block, so it is part of the referent.
    assert vision_check.expected_text(copy, "carousel", slide_text=PANEL,
                                      wordmark="HypeLead") == f"{PANEL}\nHypeLead"


# ------------------------------------------------------------------ FR-304's verbatim carve-out


def test_a_mapped_panels_text_survives_the_retry_byte_for_byte() -> None:
    """GAP 2: the 131-character panel stays 131 characters (FR-304 > FR-105).

    Trimming a verbatim quote to 60% of a budget produces the mid-sentence stub this module exists
    to CATCH — committed on purpose, by us, on the one asset whose words are not ours to edit.
    """
    copy = CopySet(asset_id="a", language="en", headline="Wired backwards", subline="here is why")

    plan = vision_check.retry_plan(copy, "carousel", budgets(), slide_text=PANEL, verbatim=True)

    assert len(PANEL) == 131, "the audited panel's real length — the fixture, not an assumption"
    assert plan.slide_text == PANEL and len(plan.slide_text) == 131
    assert plan.budget_scale == 1.0, "nothing was cut, so no smaller budget may be restated"
    assert plan.instruction == vision_check.VERBATIM_RETRY_INSTRUCTION
    assert "LOCKED" in plan.instruction and "layout" in plan.instruction, \
        "the difference this retry makes is layout-side (fewer elements, larger type)"


def test_a_free_composed_deck_slide_is_cut_against_the_slide_budget_not_the_headline() -> None:
    """The −40% survives for text WE wrote — measured against the slot that governs a deck slide.

    `image_headline` (90) is four times smaller than `slide` (300) and governs a cover headline,
    not a page: cutting a 131-character deck line against it was how a whole thought became a stub.
    """
    copy = CopySet(asset_id="a", language="en", headline="Wired backwards")

    plan = vision_check.retry_plan(copy, "carousel", budgets(), slide_text=PANEL)

    assert plan.slide_text == PANEL, "131 chars is inside slide(300)×0.6 = 180 — nothing to cut"
    assert plan.budget_scale == pytest.approx(0.6)
    long_line = " ".join(["word"] * 60)  # 299 characters: over 180, under the 300 ceiling
    cut = vision_check.retry_plan(copy, "carousel", budgets(), slide_text=long_line).slide_text
    assert 0 < len(cut) <= 180 and not long_line.startswith(cut + "x"), "cut at a word boundary"
    assert cut and long_line.startswith(cut)


def test_a_free_text_image_retry_still_cuts_forty_percent_of_its_own_budget() -> None:
    """The rule that did NOT change: an image's headline is ours, so it is still shortened.

    `image_headline` is the slot that governs a standalone image, the subline is dropped as the
    optional block, and the stated budget travels with the text via `budget_scale`.
    """
    headline = " ".join(["headline"] * 20)  # 179 characters, well over image_headline(90)
    copy = CopySet(asset_id="a", language="en", headline=headline, subline="a second block")

    plan = vision_check.retry_plan(copy, "image", budgets())

    assert len(plan.copy.headline) <= 54, "90 × 0.6, cut at a word boundary"
    assert headline.startswith(plan.copy.headline), "a prefix, never a re-write"
    assert plan.copy.subline == "", "fewer blocks render more reliably than shorter ones"
    assert plan.budget_scale == pytest.approx(0.6)
    assert plan.instruction == vision_check.RETRY_INSTRUCTION


def test_a_reel_retry_is_unchanged_and_cuts_against_the_seed_headline_budget() -> None:
    """A seed frame's hook is free-composed too, and its own slot is `reel_seed_headline`(60)."""
    hook = " ".join(["hook"] * 30)  # 149 characters
    copy = CopySet(asset_id="a", language="en", overlay_text=hook, headline=hook, subline="drop")

    plan = vision_check.retry_plan(copy, "reel", budgets())

    assert len(plan.copy.overlay_text) <= 36 and hook.startswith(plan.copy.overlay_text)
    assert plan.copy.subline == "" and plan.budget_scale == pytest.approx(0.6)


# ------------------------------------------------- D-A: the marks an image was allowed to draw


async def test_the_check_carries_the_marks_the_image_was_sanctioned_to_draw() -> None:
    """D-A: a Notion logo we ORDERED must not come back as `fake_ui`.

    The render prompt sanctions a real mark for a slide whose source panel showed one; without the
    same names on the check's carrier, the one question that asks "is there a logo on this image"
    answers true for the fidelity we just paid for, and the retry spends money undoing it.
    """
    call = RecordingCall()

    await vision_check.check([b"\xff\xd8a", b"\xff\xd8b"], expected=[PANEL, ""],
                             sanctioned_marks=[["Notion", "Obsidian"], []],
                             call=call, engine=PromptEngine())

    assert "SANCTIONED MARKS" in call.user_turn
    assert "image 1: Notion, Obsidian" in call.user_turn
    assert "image 2:" not in call.user_turn.split("SANCTIONED MARKS")[1], \
        "an image with nothing sanctioned gets no row — the strict reading is the default"
    # The RULE stays in the template (FR-180); only the names ride the carrier.
    assert "sanctioned" in call.system_turn.lower() and "Notion" not in call.system_turn


async def test_a_caller_naming_no_marks_sends_no_marks_block() -> None:
    """The pre-D-A posture, unchanged: every logo on the image is unsanctioned chrome."""
    call = RecordingCall()

    await vision_check.check([b"\xff\xd8a"], expected=[PANEL], call=call, engine=PromptEngine())

    assert "SANCTIONED MARKS" not in call.user_turn
    assert "EXPECTED TEXT" in call.user_turn


async def test_an_unreadable_input_takes_its_sanctioned_marks_with_it() -> None:
    """One drop table renumbers BOTH data lines, or slide 2's licence lands on slide 1's image."""
    call = RecordingCall()

    await vision_check.check(["/no/such/file.jpg", b"\xff\xd8real"],
                             expected=["never rendered", PANEL],
                             sanctioned_marks=[["Figma"], ["Notion"]],
                             call=call, engine=PromptEngine())

    assert "image 1: Notion" in call.user_turn, "the surviving image keeps ITS own marks"
    assert "Figma" not in call.user_turn


# ------------------------------------------------------------- D-D: the counter is ordered text


def test_the_expected_text_lists_the_slide_counter_as_ordered_words() -> None:
    """A counted deck orders its badge as a locked TEXT string, so it is part of the referent.

    Unlisted, "3/7" reads to the checker as three invented characters on every slide of the deck —
    a `text_mismatch` on the whole deck, earning a retry per slide against a defect nobody has.
    """
    copy = CopySet(asset_id="a", language="en", headline="Wired backwards", subline="here is why")

    assert vision_check.expected_text(copy, "carousel", slide_text=PANEL,
                                      slide_counter="03 / 05") == f"{PANEL}\n03 / 05"
    # The order mirrors the TEXT block the render was given: words, counter, signature.
    assert vision_check.expected_text(copy, "carousel", slide_text="Slide one",
                                      slide_counter="1/5", wordmark="HypeLead") == (
        "Slide one\n1/5\nHypeLead")
    assert vision_check.expected_text(copy, "carousel", slide_text=PANEL) == PANEL, \
        "an uncounted deck lists no badge — the opposite claim, just as sharp"
    # A wordless mapped panel of a COUNTED deck is not wordless: the badge is still ordered.
    assert vision_check.expected_text(copy, "carousel", slide_text="",
                                      slide_counter="02 / 05") == "02 / 05"


# --------------------------------------------------------- D-F: the retry knows which defect


def test_a_mismatch_retry_names_the_invented_words_and_forbids_them() -> None:
    """D-F: "shorter text, larger type" is a remedy for broken glyphs and a no-op for invented copy.

    The first verdict's own `detail` is quoted into the instruction, so the second attempt is a
    different REQUEST rather than a second roll of the same dice.
    """
    copy = CopySet(asset_id="a", language="en", headline="Wired backwards")
    verdict = vision_check.ImageVerdict(index=1, text_mismatch=True,
                                        detail="shows 'BUILD IN PUBLIC', not the panel's words")

    plan = vision_check.retry_plan(copy, "carousel", budgets(), slide_text=PANEL, verbatim=True,
                                   verdict=verdict)

    assert "shows 'BUILD IN PUBLIC', not the panel's words" in plan.instruction
    assert "invented or altered words" in plan.instruction
    assert "Render the invented words nowhere" in plan.instruction
    assert plan.instruction.startswith(vision_check.VERBATIM_RETRY_INSTRUCTION), \
        "the defect clause is APPENDED to the lever the caller chose, never a replacement"
    assert plan.slide_text == PANEL, "FR-304 > FR-105 still: a quote is not trimmed by a diagnosis"


def test_a_fake_ui_retry_forbids_the_chrome_the_render_actually_drew() -> None:
    """The second clause, and the second no-op: a smaller headline does not remove a play button."""
    copy = CopySet(asset_id="a", language="en", headline="Wired backwards")
    verdict = vision_check.ImageVerdict(index=1, fake_ui=True, detail="a TikTok-style like counter")

    plan = vision_check.retry_plan(copy, "image", budgets(), verdict=verdict)

    assert "a TikTok-style like counter" in plan.instruction
    assert "platform interface chrome" in plan.instruction
    assert plan.instruction.startswith(vision_check.RETRY_INSTRUCTION)
    assert plan.copy.subline == "" and plan.budget_scale == pytest.approx(0.6), \
        "the text lever is unchanged — the clause is added ON TOP of it"


def test_a_broken_text_verdict_keeps_the_instruction_it_always_had() -> None:
    """`text_broken`'s remedy IS the base wording, and duplicating it dilutes the real clauses."""
    copy = CopySet(asset_id="a", language="en", headline="Wired backwards")
    broken = vision_check.ImageVerdict(index=1, text_broken=True, detail="garbled diacritics")

    assert vision_check.retry_plan(copy, "image", budgets(),
                                   verdict=broken).instruction == vision_check.RETRY_INSTRUCTION
    assert vision_check.retry_plan(copy, "carousel", budgets(), slide_text=PANEL, verbatim=True,
                                   verdict=broken).instruction == (
        vision_check.VERBATIM_RETRY_INSTRUCTION)
    # No verdict in scope is the pre-D-F string, byte for byte — every caller keeps its default.
    assert vision_check.retry_plan(copy, "image",
                                   budgets()).instruction == vision_check.RETRY_INSTRUCTION
    assert vision_check.retry_plan(copy, "reel",
                                   budgets()).instruction == vision_check.RETRY_INSTRUCTION


def test_a_detail_less_verdict_still_names_the_defect() -> None:
    """A flag with no explanation still gets its defect forbidden — and no dangling dash."""
    copy = CopySet(asset_id="a", language="en", headline="Wired backwards")

    plan = vision_check.retry_plan(copy, "reel", budgets(),
                                   verdict=vision_check.ImageVerdict(index=1, text_mismatch=True))

    assert "no further detail was given" in plan.instruction
    assert " — ." not in plan.instruction
