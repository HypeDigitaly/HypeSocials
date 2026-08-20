"""`hypesocials.cover_pick` — the cover best-of-N judge (FR-351/352, D62).

One carousel orders two or three renders of slide 1 from the SAME instruction, and exactly one of
them becomes the cover AND the reference every body slide is built from. This module is the one
vision call that chooses, and almost everything worth pinning here is a way it declines to choose:

* **fewer than two candidates is not a degrade.** There is no question, so there is no call, no
  spend and no warning — the one frame that landed is the cover, on a clean `Pick`;
* **every other failure is fail-open**, exactly like the style matcher (FR-334) and slide
  intelligence (§0.14c): no `llm`, a raised call, a degraded `ParsedResult`, an answer that is not
  an object, an id outside the offered range — all of them come back as candidate 1 with
  `degraded=True` and a `reason` opening on the `cover_pick_degraded:` marker the caller turns
  into ONE operator warning and one degradation tag. A judge we could not run makes exactly the
  deck a `cover_candidates: 1` run would have made; it never loses a deck and never blocks one;
* **the answer names a candidate ID, never an attachment ordinal of the model's own.** That is
  this module's version of `style_match`'s asset_id join, and `_chosen` refuses anything else
  rather than coercing it — a clamped id is a confident-looking pick nobody made.

Two output-side properties get their own tests because the strings involved reach three surfaces a
person reads (the run log, `meta.yaml`, the gallery's candidate strip): a provider error is
reported by its exception CLASS NAME alone (D30 — an error body can carry a URL, a payload or a
key), and the model's `reason` comes back single-line and control-character-free.

Offline and deterministic, on `test_style_match.py`'s fake-`StructuredCall` pattern: no network, no
API key, no `output/` and no `logs/` writes. The prompt IS rendered — `prompts/cover_pick_system.md`
is a repo file read, and rendering it is what lets these tests inspect the contract the model was
actually shown instead of a private function's return.
"""

from __future__ import annotations

from typing import Any

import pytest

from hypesocials import cover_pick
from hypesocials.config import Config
from hypesocials.cover_pick import CoverBrief, CoverCandidate, pick
from hypesocials.models import ParsedResult
from hypesocials.prompts_engine import PROMPTS_DIR, _BUILT_INS

#: A deliberately synthetic, obviously-fake credential shape. It is NOT a key, it is the thing a
#: provider error body looks like — the string the D30 test below proves never reaches an operator.
FAKE_KEY_IN_A_URL = ("https://openrouter.test/v1/chat/completions"
                     "?api_key=sk-or-v1-THIS-IS-NOT-A-REAL-KEY-0000")

#: Two lines of registry prose standing in for a real style's DNA. Multi-line on purpose: the block
#: builder ships the DNA verbatim on its own lines, and a single-line fixture could not tell a
#: verbatim copy apart from a flattened one.
STYLE_DNA = ("GROUND near-white paper #F6F5F2, the whole frame.\n"
             "ACCENT one teal #0E9AA7, under 1/8 of the frame; counter top-right, mono caps.")


# --------------------------------------------------------------------------- builders


def _candidates(count: int = 2) -> list[CoverCandidate]:
    """`count` landed slide-1 renders, each with its own recognisable bytes."""
    return [CoverCandidate(index=index, image=f"frame-{index}".encode())
            for index in range(1, count + 1)]


def _brief(**over: Any) -> CoverBrief:
    """One deck's cover contract, as `generate.carousel` assembles it after wave 1."""
    fields: dict[str, Any] = {
        "asset_id": "a01",
        "style_key": "editorial-voxel-carousel",
        "style_dna": STYLE_DNA,
        "expected_text": ("Seven tools, one bill.", "HypeDigitaly", "1/7"),
        "counter": "1/7",
    }
    fields.update(over)
    return CoverBrief(**fields)


class Answer:
    """A `models.StructuredCall` returning a crafted verdict and remembering every call.

    Honours the pinned protocol shape — `async (role, messages, json_schema, images=None)` — which
    is the only seam `pick()` has; a stub that drifted from it would test a signature no run uses.
    The recorded `messages` and `images` are how the tests below read the prompt and the
    attachments the model was really shown.
    """

    def __init__(self, chosen: Any = 1, reason: str = "cleanest hierarchy", *,
                 raises: Exception | None = None, parsed: Any = ..., degraded: bool = False,
                 fail_reason: str = "") -> None:
        self.chosen = chosen
        self.reason = reason
        self.raises = raises
        self.parsed = parsed
        self.degraded = degraded
        self.fail_reason = fail_reason
        self.calls: list[tuple[str, list[dict[str, Any]], dict[str, Any], Any]] = []

    async def __call__(self, role: str, messages: list[dict[str, Any]],
                       json_schema: dict[str, Any], images: list[bytes] | None = None
                       ) -> ParsedResult:
        self.calls.append((role, messages, json_schema, images))
        if self.raises is not None:
            raise self.raises
        parsed = ({"chosen": self.chosen, "reason": self.reason} if self.parsed is ...
                  else self.parsed)
        return ParsedResult(parsed=parsed, raw_text="{}", degraded=self.degraded,
                            reason=self.fail_reason)

    @property
    def prompt(self) -> str:
        """The rendered system prompt of the one pick call."""
        assert len(self.calls) == 1, f"expected exactly one call, got {len(self.calls)}"
        return str(self.calls[0][1][0]["content"])

    @property
    def attachments(self) -> list[bytes]:
        """The image blobs, in the order they were handed to the provider."""
        assert len(self.calls) == 1, f"expected exactly one call, got {len(self.calls)}"
        return list(self.calls[0][3] or [])


def _contract(prompt: str) -> str:
    """Everything between the COVER CONTRACT fence markers — what the judge was told to hold the
    candidates to, read off the prompt rather than off `_contract_block`'s return."""
    head = prompt.index("<<<BEGIN DATA: COVER CONTRACT>>>")
    tail = prompt.index("<<<END DATA: COVER CONTRACT>>>")
    return prompt[head + len("<<<BEGIN DATA: COVER CONTRACT>>>"):tail]


def _roll_call(prompt: str) -> str:
    """Everything between the CANDIDATES fence markers — the id → attachment map."""
    head = prompt.index("<<<BEGIN DATA: CANDIDATES>>>")
    tail = prompt.index("<<<END DATA: CANDIDATES>>>")
    return prompt[head + len("<<<BEGIN DATA: CANDIDATES>>>"):tail]


# --------------------------------------------------------------------------- no question to ask


async def test_one_candidate_is_not_a_choice_so_no_call_is_made_and_nothing_degrades() -> None:
    """FR-351's floor: `cover_candidates: 1` and "only one of three landed" are the same deck.

    Not degraded, deliberately. A judge with one frame in front of it did not fail — there was
    nothing to judge — and warning the operator plus tagging the asset `cover_pick_degraded` about
    a call that was never needed is a false alarm, on the `style_match` "nothing in scope" reading.
    """
    llm = Answer()

    verdict = await pick(_candidates(1), _brief(), Config(), llm)

    assert llm.calls == [], "a single candidate must cost nothing"
    assert (verdict.chosen, verdict.degraded) == (1, False)
    assert cover_pick.DEGRADED_MARKER not in verdict.reason
    assert verdict.reason, "a clean pick still explains itself on the receipt"


async def test_no_candidate_at_all_still_answers_with_a_valid_pick() -> None:
    """`pick()` is total: it never raises and `chosen` is always a usable 1-based id, so a caller
    that lost every candidate still gets an answer it can write down rather than an IndexError."""
    verdict = await pick([], _brief(), Config(), Answer())

    assert (verdict.chosen, verdict.degraded) == (1, False)


async def test_no_llm_with_two_candidates_degrades_onto_candidate_one() -> None:
    """The other half of the floor: there IS a question and no way to ask it.

    Degraded here, unlike the single-candidate case above — a cover was chosen blind, which is the
    exact thing the operator paid for a second render to avoid, so it earns its warning and its
    tag.
    """
    verdict = await pick(_candidates(2), _brief(), Config(), None)

    assert (verdict.chosen, verdict.degraded) == (1, True)
    assert verdict.reason.startswith(f"{cover_pick.DEGRADED_MARKER}:"), verdict.reason


# --------------------------------------------------------------------------- the happy path


async def test_the_judge_is_shown_the_contract_the_candidates_and_the_frames_in_order() -> None:
    """The whole call, in one pass: what the model is told, what it is shown, and what comes back.

    Three things are asserted together because they are one contract. The fenced block carries
    every string that has to be legible and the `style_dna` bytes VERBATIM — a paraphrase would
    judge the frames against a look nothing was rendered from. The attachments are the candidates'
    own bytes in candidate order, because `llm._with_images` puts them on the last user turn in the
    order they arrive and the roll-call block promises the model that attachment *i* is candidate
    *i*. And the answer's `chosen` is returned as given: 2 means the second frame, not "the second
    thing I looked at".
    """
    llm = Answer(chosen=2, reason="teal accent holds, counter top-right")
    candidates = _candidates(3)

    verdict = await pick(candidates, _brief(), Config(), llm)

    assert (verdict.chosen, verdict.degraded) == (2, False)
    assert verdict.reason == "teal accent holds, counter top-right"
    assert llm.calls[0][0] == cover_pick.PICK_ROLE == "analysis"
    contract = _contract(llm.prompt)
    assert "asset_id: a01" in contract and "style_key: editorial-voxel-carousel" in contract
    assert "counter: 1/7" in contract
    for expected in ("Seven tools, one bill.", "HypeDigitaly", "1/7"):
        assert expected in contract, f"the cover's expected text is not in the contract: {expected}"
    assert STYLE_DNA in contract, "the DNA reached the judge paraphrased or re-wrapped"
    roll_call = _roll_call(llm.prompt)
    for index in (1, 2, 3):
        assert f"candidate {index} — attachment {index}" in roll_call
    assert llm.attachments == [candidate.image for candidate in candidates]
    assert "{{" not in llm.prompt, "a slot was left unresolved in a metered prompt (FR-260)"


async def test_an_empty_expected_string_is_dropped_and_an_uncounted_deck_says_so() -> None:
    """Two contract details the judge's first test depends on.

    An empty `expected_text` entry is not a string a frame can show, so it never becomes a blank
    contract line the model then hunts for. And an uncounted deck states the absence IN WORDS
    rather than by omitting the field: "no counter" is an active judging criterion (D59/FR-338),
    and a missing line reads as unknown.
    """
    llm = Answer()

    await pick(_candidates(2), _brief(expected_text=("Only this one.", "", "   "), counter=""),
               Config(), llm)

    contract = _contract(llm.prompt)
    assert "Only this one." in contract
    assert "counter: none — this deck is uncounted" in contract
    body = [line for line in contract.splitlines() if line.startswith("  ")]
    assert body == ["  Only this one."], f"an empty expected string reached the prompt: {body}"


# --------------------------------------------------------------------------- fail-open, five ways


@pytest.mark.parametrize("answered", [0, 4, "x", None, 2.5, ""])
async def test_an_id_outside_the_offered_range_degrades_onto_candidate_one(answered: Any) -> None:
    """`_chosen` policing, which is this module's asset_id join.

    An id one past the end, a zero, a word, a float, a `null` and a missing value are all the same
    event: the answer does not name a frame we rendered. None of them is coerced — clamping 4 to 3
    would hand the caller a pick nobody made — so the deck falls back to candidate 1 and says why.
    """
    llm = Answer(chosen=answered)

    verdict = await pick(_candidates(3), _brief(), Config(), llm)

    assert (verdict.chosen, verdict.degraded) == (1, True)
    assert verdict.reason.startswith(f"{cover_pick.DEGRADED_MARKER}:"), verdict.reason
    assert "1..3" in verdict.reason, "the reason must name the ids that WERE offered"


async def test_a_numeric_string_is_accepted_because_it_names_a_frame_unambiguously() -> None:
    """A strict schema is a request, not a guarantee: `"2"` is the second candidate and refusing it
    would throw away a good pick over a JSON type."""
    verdict = await pick(_candidates(3), _brief(), Config(), Answer(chosen="2"))

    assert (verdict.chosen, verdict.degraded) == (2, False)


async def test_a_raised_call_is_reported_by_its_class_name_and_never_by_its_body() -> None:
    """D30 at the boundary that matters: this string reaches the operator's console, `meta.yaml`
    and a gallery card, and a provider error body can carry a URL, a payload or a key."""
    llm = Answer(raises=RuntimeError(f"502 from {FAKE_KEY_IN_A_URL}"))

    verdict = await pick(_candidates(2), _brief(), Config(), llm)

    assert (verdict.chosen, verdict.degraded) == (1, True)
    assert "RuntimeError" in verdict.reason
    assert "sk-or-v1" not in verdict.reason and "openrouter.test" not in verdict.reason
    assert "502" not in verdict.reason, "the provider's own message must not be echoed at all"


async def test_a_degraded_result_degrades_the_pick() -> None:
    """`ParsedResult.degraded` is the client saying "I have no answer for you" — after its own
    retries, so there is nothing left to try here and the deck anchors on candidate 1."""
    llm = Answer(degraded=True, fail_reason="schema validation failed twice")

    verdict = await pick(_candidates(2), _brief(), Config(), llm)

    assert (verdict.chosen, verdict.degraded) == (1, True)
    assert "schema validation failed twice" in verdict.reason


async def test_an_answer_that_is_not_an_object_degrades_the_pick() -> None:
    """A list, a string or a `None` where an object was promised: nothing to read `chosen` off."""
    verdict = await pick(_candidates(2), _brief(), Config(), Answer(parsed=["candidate 2"]))

    assert (verdict.chosen, verdict.degraded) == (1, True)


async def test_a_candidate_with_no_bytes_is_refused_before_the_call_is_billed() -> None:
    """The attachment-order invariant, defended where it is cheap.

    `llm._with_images` drops a falsy blob, which would shift every later attachment one slot left
    and make the roll-call's id → picture map a lie. A pick made against the wrong frames is worse
    than no pick, so the deck degrades and the call is never made.
    """
    llm = Answer(chosen=2)
    candidates = [CoverCandidate(index=1, image=b"frame-1"), CoverCandidate(index=2, image=b"")]

    verdict = await pick(candidates, _brief(), Config(), llm)

    assert llm.calls == [], "a call whose attachments cannot be trusted must not be billed"
    assert (verdict.chosen, verdict.degraded) == (1, True)
    assert "candidate 2 landed no bytes" in verdict.reason


# --------------------------------------------------------------------------- what comes back out


async def test_control_characters_in_the_reason_are_scrubbed_before_anyone_reads_it() -> None:
    """`reason` is model-authored prose printed on a console, written into `meta.yaml` and put on a
    gallery card. A newline breaks the receipt's one-line shape and an ESC run is an ANSI sequence
    the operator's terminal EXECUTES rather than shows."""
    llm = Answer(chosen=2, reason="teal accent\r\n\x1b[31mholds\x00 at thumbnail")

    verdict = await pick(_candidates(2), _brief(), Config(), llm)

    assert verdict.chosen == 2
    assert "\n" not in verdict.reason and "\r" not in verdict.reason
    assert "\x1b" not in verdict.reason and "\x00" not in verdict.reason
    assert "teal accent" in verdict.reason and "holds" in verdict.reason


async def test_a_runaway_reason_is_bounded_before_it_reaches_a_console_line() -> None:
    """~12 words were asked for; the ceiling is roughly double, so an obedient model is never cut
    and a runaway one cannot push a paragraph through three surfaces a person reads."""
    llm = Answer(chosen=1, reason="stopping power " * 200)

    verdict = await pick(_candidates(2), _brief(), Config(), llm)

    assert len(verdict.reason) <= cover_pick._MAX_REASON_CHARS
    assert verdict.degraded is False, "a long reason is not a failed pick"


# --------------------------------------------------------------------------- the template itself


def test_the_answer_schema_asks_for_exactly_the_two_fields_the_module_reads() -> None:
    """Strict JSON (FR-352): `chosen` an integer, `reason` a string, both required and nothing
    else. `additionalProperties: False` is what keeps a provider from padding the object with
    fields the module would then have to decide whether to trust."""
    schema = cover_pick._answer_schema()

    assert schema["name"] == "cover_pick"
    inner = schema["schema"]
    assert inner["required"] == ["chosen", "reason"]
    assert inner["additionalProperties"] is False
    assert inner["properties"]["chosen"]["type"] == "integer"
    assert inner["properties"]["reason"]["type"] == "string"


async def test_the_shipped_template_renders_with_no_unresolved_slot() -> None:
    """FR-260/261 end to end, through the REAL engine and the real file.

    No `prompts_dir`, so the template resolves from `prompts/` rather than from its built-in twin:
    this is the assertion that would fail the day `cover_contract` or `cover_candidates` left
    `models.PLACEHOLDERS` or the role's `_ALLOWLIST` row — at which point the engine would quietly
    fall back to the twin and every operator hot-edit of the file (FR-181) would stop reaching a
    model.
    """
    llm = Answer(chosen=1)

    await pick(_candidates(2), _brief(), Config(), llm)

    assert "{{" not in llm.prompt and "}}" not in llm.prompt
    assert llm.prompt.startswith("ROLE"), "the built-in twin stood in for the file"


def test_the_built_in_twin_is_byte_identical_to_the_shipped_file() -> None:
    """FR-183: the fallback fires only when the file is already broken — the one moment nobody is
    reading the prompt. `test_template_parity.py` owns this check for every role; it is repeated
    here because THIS module is the one that breaks if the two copies disagree about the judging
    order or the answer shape, and a reader of this file should not have to go and find out."""
    on_disk = (PROMPTS_DIR / cover_pick.PICK_TEMPLATE).read_text(encoding="utf-8")

    assert _BUILT_INS[cover_pick.PICK_TEMPLATE] == on_disk
