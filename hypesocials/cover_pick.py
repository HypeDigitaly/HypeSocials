"""Cover best-of-N — ONE fail-open vision call that picks a carousel's anchor (FR-351/352, D62).

Callers import `hypesocials.cover_pick`. One call, one concept — of the two or three slide-1
renders this deck just bought, which one should every body slide copy:

    verdict = await pick(candidates, brief, cfg, llm)     # a Pick, ALWAYS; never raises
    winner = candidates[verdict.chosen - 1]               # `chosen` is 1-based, always in range

**Shaped on `style_match.py`.** Same contract, same reasons: a judge we could not run is a deck
that anchors to its first candidate — exactly the deck a `cover_candidates: 1` run would have
made — never a deck that is lost, and never a deck that waits. Every failure path (no metered
call, a raised call, a degraded or unparseable answer, an id outside the candidate range) comes
back as `Pick(chosen=1, degraded=True)` with `reason` opening on the `cover_pick_degraded:`
marker, which the caller turns into ONE operator warning and one degradation tag
(`DegradationTag.COVER_PICK_DEGRADED`).

**What the judge sees and what it judges.** Every landed candidate's native bytes ride as image
attachments in candidate order, and the fenced `{{cover_contract}}` block carries the deck's
style key, the exact `style_dna` bytes the render prompt carried, and every string that has to be
legible on the cover. The judging order is fixed by the template and is not a taste: (1) does the
frame honour the style contract — palette, ground, type, counter position, no invented chrome;
(2) are the expected strings legible at thumbnail size; (3) stopping power. Contract before
craft, because a beautiful cover that breaks the DNA is the one every body slide will then copy.

Nothing the model writes is rendered. `reason` is read by a person in the run log, `meta.yaml`
and the gallery's candidate strip; it is sanitized and length-bounded here, once.

The template is `prompts/cover_pick_system.md` (+ its byte-identical twin in
`prompts_engine._BUILT_INS`), role `analysis`, and the two placeholders it names
(`cover_contract`, `cover_candidates`) are allowlisted for THIS role only (FR-261).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from hypesocials.config import Config
from hypesocials.models import DegradationTag, StructuredCall
from hypesocials.prompts_engine import PromptEngine, build_context
from hypesocials.util import fit as one_line  # the `style_match` alias: a one-line, width-bounded cut

logger = logging.getLogger(__name__)

#: The template this module renders and the LLM role it bills to (`analysis`: Sonnet, vision).
PICK_ROLE = "analysis"
PICK_TEMPLATE = "cover_pick_system.md"

#: The user turn the candidate images ride on. `llm._with_images` attaches every blob as base64
#: `image_url` parts on the LAST user turn (`llm.py:397-410`), and this is it — so attachment order
#: is exactly the order this module passes the bytes in, which is what `{{cover_candidates}}`
#: promises the model when it says "the first attachment is the first candidate id in that list".
_CARRIER_TURN = "Pick the cover for the deck above now."

#: The marker every degraded reason carries, taken from the degradation tag itself so the console
#: line, the meta.yaml tag and this string are one fact with one spelling (the `style_match`
#: precedent).
DEGRADED_MARKER = DegradationTag.COVER_PICK_DEGRADED.value

#: Output bound for the model-authored `reason` (~12 words specified; roughly double so an
#: obedient model is never cut and a runaway one cannot push a paragraph onto a console line).
_MAX_REASON_CHARS = 160

#: Control characters (C0 + DEL) in a model-authored string, replaced before anything is printed
#: — an ESC run reaching the operator's console is an ANSI sequence that is executed, not read.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(slots=True)
class CoverCandidate:
    """One landed slide-1 render: the id the model answers with, and its native bytes."""

    index: int  # 1-based candidate id — the attachment slot AND the id in the answer
    image: bytes  # native bytes, already fetched; never a URL (the call attaches base64)


@dataclass(slots=True)
class CoverBrief:
    """What the cover was ORDERED to be — the contract the judge holds every candidate against."""

    asset_id: str
    style_key: str
    style_dna: str  # the exact DNA bytes the render prompt carried (FR-189: identical per deck)
    #: Every string that must be legible on the cover: slide 1's own text, the wordmark when the
    #: deck is branded, the counter badge when the deck is counted. Empty strings are dropped.
    expected_text: tuple[str, ...] = ()
    counter: str = ""  # slide 1's badge (`"1/7"`), or `""` for an uncounted deck


@dataclass(slots=True)
class Pick:
    """The verdict the caller commits. `chosen` is ALWAYS a valid 1-based candidate id."""

    chosen: int = 1
    reason: str = ""
    degraded: bool = False  # True → `reason` opens on `DEGRADED_MARKER`


class _PickUnavailable(RuntimeError):
    """The pick call produced nothing usable. Caught in `pick()`; the deck degrades, never fails."""


async def pick(candidates: Sequence[CoverCandidate], brief: CoverBrief, cfg: Config,
               llm: StructuredCall | None) -> Pick:
    """Choose the anchor among `candidates`. Returns a `Pick` and NEVER raises.

    Fewer than two candidates is not a degrade: there is no choice to make, and candidate 1 (or
    the only one) is returned on a non-degraded `Pick` with a plain reason. `llm=None` with two or
    more candidates IS a degrade — there is a question and no way to ask it.
    """
    if len(candidates) < 2:
        return Pick(chosen=candidates[0].index if candidates else 1,
                    reason="only one candidate landed — nothing to choose")
    cause = ""
    if llm is None:
        cause = "no model call available"
    else:
        try:
            return await _llm_pick(candidates, brief, cfg, llm)
        except _PickUnavailable as exc:
            cause = str(exc)
        except Exception as exc:  # noqa: BLE001 — fail-open by contract (FR-351). Class NAME only:
            # a provider error body can carry a URL or a payload and this string reaches the
            # operator (D30).
            cause = f"the pick call raised {type(exc).__name__}"
            logger.warning("cover_pick: pick call failed (%s)", type(exc).__name__)
    logger.warning("cover_pick: %s — candidate 1 anchors %s", cause, brief.asset_id)
    return Pick(chosen=candidates[0].index, reason=f"{DEGRADED_MARKER}: {cause}", degraded=True)


async def _llm_pick(candidates: Sequence[CoverCandidate], brief: CoverBrief, cfg: Config,
                    llm: StructuredCall) -> Pick:
    """One call, one answer. Raises `_PickUnavailable` on anything that is not usable.

    The frames are the question and the fenced contract is the yardstick, so both travel in one
    message: the rendered system turn carries `{{cover_contract}}` and `{{cover_candidates}}`, and
    the bytes ride as base64 attachments on the carrier turn IN CANDIDATE ORDER. That order is the
    module's one structural invariant — the model answers with a candidate ID, and the only way it
    can know which id names which picture is that attachment *i* is the *i*-th line of the block.
    """
    if missing := [candidate.index for candidate in candidates if not candidate.image]:
        # Never reached from a healthy caller (a `CoverCandidate` is built from a LANDED render),
        # and worth $0 to refuse anyway: `llm._with_images` drops falsy blobs, which would shift
        # every later attachment one slot left and make the block's id→picture map a lie. A pick
        # made against the wrong frames is worse than no pick at all.
        raise _PickUnavailable(f"candidate {missing[0]} landed no bytes to judge")
    result = await llm(
        PICK_ROLE,
        [{"role": "system", "content": _system_prompt(candidates, brief, cfg)},
         {"role": "user", "content": _CARRIER_TURN}],
        _answer_schema(),
        [candidate.image for candidate in candidates],  # attachment order IS candidate order
    )
    if result.degraded:
        raise _PickUnavailable(f"the pick call degraded ({result.reason or 'no reason'})")
    if not isinstance(result.parsed, Mapping):
        raise _PickUnavailable("the answer was not a JSON object")
    chosen = _chosen(result.parsed.get("chosen"), candidates)
    reason = _clean(result.parsed.get("reason"), _MAX_REASON_CHARS)
    logger.info("cover_pick: %s anchors on candidate %d of %d — %s", brief.asset_id, chosen,
                len(candidates), reason or "no reason given")
    return Pick(chosen=chosen, reason=reason, degraded=False)


def _chosen(answer: Any, candidates: Sequence[CoverCandidate]) -> int:
    """The answered id, policed against the ids this call actually offered. Raises otherwise.

    A numeric STRING is accepted (`"2"`) because a strict schema is a request and not a guarantee,
    and "2" is unambiguously the second candidate. Everything else is refused rather than coerced:
    an id one past the end, a zero, a word, a `null` and a missing key are all the same event —
    the answer does not name a frame we rendered, so there is nothing to commit and the deck falls
    back to candidate 1. Coercing an out-of-range number (clamping 4 to 3, say) would hand the
    caller a confident-looking pick nobody made.
    """
    valid = [candidate.index for candidate in candidates]
    try:
        chosen: int | None = int(str(answer).strip())
    except (TypeError, ValueError):
        chosen = None
    if chosen not in valid:
        raise _PickUnavailable(f"answered candidate {_clean(answer, 24) or '(nothing)'}, not one "
                               f"of {_ids(valid)}")
    return chosen


def _ids(valid: Sequence[int]) -> str:
    """`"1..3"` for the ordinary contiguous slate, the ids themselves for anything else."""
    if len(valid) > 1 and list(valid) == list(range(valid[0], valid[0] + len(valid))):
        return f"{valid[0]}..{valid[-1]}"
    return ", ".join(str(index) for index in valid)


def _system_prompt(candidates: Sequence[CoverCandidate], brief: CoverBrief, cfg: Config) -> str:
    """The rendered `cover_pick_system.md`: the deck's contract, then the candidate roll-call.

    Assembly goes through the ordinary template door for the ordinary reasons — FR-181 hot-loading
    of an edited `prompts/cover_pick_system.md`, FR-174's `prompts_dir` override, FR-183's built-in
    twin when the file is missing or names a placeholder this role may not resolve, and FR-260's
    refusal to send a half-filled prompt to a metered model. The engine is built per call exactly
    as `style_match._system_prompt` builds its own.

    `build_context()` is called with no arguments and the two slots are set on the result, the same
    way the matcher sets `{{style_candidates}}`: both names belong to THIS role alone
    (`prompts_engine._ALLOWLIST`), and `build_context` is the cross-role door. The engine only
    substitutes the names its template actually contains, so the empty defaults it returns for
    every other placeholder never reach a prompt.

    Every failure here becomes `_PickUnavailable`, i.e. the fail-open path: a template we could not
    render is a deck anchored on candidate 1, never a lost deck and never a truncated prompt sent
    anyway.
    """
    try:
        engine = PromptEngine(override_dirs=[cfg.prompts_dir] if cfg.prompts_dir else [])
        context = build_context()
        context["cover_contract"] = _contract_block(brief)
        context["cover_candidates"] = _candidate_block(candidates)
        return engine.render(PICK_TEMPLATE, context)
    except Exception as exc:  # noqa: BLE001 — assembly is fail-open by contract (FR-351)
        # The message is carried through, unlike the provider-side catch in `pick()`: prompt
        # assembly never touches a key, a header or an environment (FR-261 is structural), so the
        # worst thing in here is a template path and a placeholder name — which is exactly what
        # the operator needs to fix it. D30's redaction concern is about payloads, not paths.
        raise _PickUnavailable(
            f"the pick prompt could not be assembled ({type(exc).__name__}: {exc})") from exc


def _contract_block(brief: CoverBrief) -> str:
    """`{{cover_contract}}` — what the cover was ORDERED to be, as fenced DATA lines.

    Three identity lines, then the legibility list, then the DNA. The identity lines say which
    deck this is, which style it was assigned and whether it carries a counter — the last one in
    words rather than by omission, because "no counter" is something the judge has to check FOR.
    Then every string that has to be legible rides one per indented line. Then the style's own DNA
    lands verbatim, because the DNA is the yardstick and a paraphrase of it would judge the
    candidates against a look nothing was rendered from.

    Nothing here is cut. A `reason` is model prose and is bounded on the way out (`_clean`), but
    an expected string is a CONTRACT string — the exact text a candidate has to show — and a
    silently trimmed one would fail every frame that spelled it correctly. Control characters are
    still flattened to spaces: a newline inside one of these strings would break the one-line-per-
    string shape this block promises, and an ESC run has no business in a prompt at all.
    """
    lines = [f"asset_id: {brief.asset_id}",
             f"style_key: {brief.style_key or '(none assigned)'}",
             f"counter: {_counter_line(brief.counter)}"]
    if strings := [text for text in (_flat(item) for item in brief.expected_text) if text]:
        lines.append("expected_text:")
        lines.extend(f"  {text}" for text in strings)
    else:
        lines.append("expected_text: none — this cover carries no quoted words of ours")
    if dna := brief.style_dna.strip():
        lines.append("style_dna:")
        lines.append(dna)
    else:
        lines.append("style_dna: none recorded for this deck")
    return "\n".join(lines)


def _counter_line(counter: str) -> str:
    """The `counter:` value — the badge this cover carries, or why it may carry none (FR-338).

    An uncounted deck says so IN WORDS rather than by omitting the line, because "no counter" is
    an active judging criterion here and an absent field reads as unknown. The D59 counter rule is
    what the render was held to; this is the same rule stated once more, for the eye that checks it.
    """
    if badge := _flat(counter):
        return badge
    return ("none — this deck is uncounted; a page number or counter chip on any candidate is "
            "invented chrome")


def _candidate_block(candidates: Sequence[CoverCandidate]) -> str:
    """`{{cover_candidates}}` — the roll-call that maps each answerable id to an attached image.

    One line per candidate, in the order the bytes are attached. The id is the candidate's own
    `index` and the attachment position is this block's own 1-based counter: they agree today and
    the model is told the mapping either way, so a caller that ever hands over a non-contiguous
    slate (candidates 1 and 3 landed, 2 timed out) still gets a prompt whose ids name real frames.
    """
    return "\n".join(f"candidate {candidate.index} — attachment {position}"
                     for position, candidate in enumerate(candidates, start=1))


def _answer_schema() -> dict[str, Any]:
    """The wire shape (FR-352). Hand-built rather than generated from a dataclass, on the
    `style_match._answer_schema` precedent: `Pick` is this module's own RESULT type — it carries
    `degraded`, which the model has no say in — and `chosen` is still policed against this call's
    own candidate ids after it arrives.

    `chosen` is a plain integer and not an enum of the offered ids: the valid set is per CALL, the
    provider is asked for one deck at a time, and a schema that could express it would still not
    remove the `_chosen` check — a strict schema is a request, not a guarantee.
    """
    return {
        "name": "cover_pick",
        "schema": {
            "type": "object",
            "properties": {"chosen": {"type": "integer"}, "reason": {"type": "string"}},
            "required": ["chosen", "reason"],
            "additionalProperties": False,
        },
    }


def _flat(value: Any) -> str:
    """A contract string, safe to put on one line of the prompt — and NEVER shortened.

    The counterpart to `_clean` below, and the difference is the whole point: `_clean` bounds
    model-authored prose on its way OUT to an operator, while this bounds nothing on its way IN to
    the judge. An `expected_text` entry is the exact string a candidate has to show; trim it and
    the judge marks a correct frame wrong.
    """
    return _CONTROL.sub(" ", str(value or "")).strip()


def _clean(value: Any, limit: int) -> str:
    """A model-authored string, safe to print: no control characters, one line, `limit` chars."""
    return one_line(_CONTROL.sub(" ", str(value or "")), limit)


__all__ = ["DEGRADED_MARKER", "PICK_ROLE", "PICK_TEMPLATE", "CoverBrief", "CoverCandidate",
           "Pick", "pick"]
