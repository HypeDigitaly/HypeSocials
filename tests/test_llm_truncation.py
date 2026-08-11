"""The truncation ladder — FR-127's widened retry, its ceiling, and the FR-41 retry it must NOT spend.

Plan §1.6 measured that EVERY style-brief call this tool had ever made hit `llm_truncated`, and
that one call could bill its ~12,430-token prompt three times: attempt 1 at the cap, attempt 2 at
the widened cap, attempt 3 because FR-41's formatting retry fired on a response that was merely
unfinished. These tests pin the ladder at exactly two attempts and pin the reason that tells an
operator which of the two ends it stopped at.

**Offline by construction.** A fake stands in for `httpx.AsyncClient` through `LLMClient(client=)`,
so no socket is opened, no `OPENROUTER_API_KEY` is read (`api_key=""` is passed explicitly) and no
spend is possible. The fake records request BODIES only — never the headers, which is where the
key lives (D30).
"""

from __future__ import annotations

import copy
from typing import Any

from hypesocials.llm import _DEFAULT_MAX_OUTPUT_CEILING, LLMClient, RoleSettings

_SCHEMA = {"type": "object", "required": ["render_prompt"],
           "properties": {"render_prompt": {"type": "string"}}}
_MESSAGES = [{"role": "system", "content": "write a style brief"},
             {"role": "user", "content": "go"}]
_NUDGE_MARKER = "Return ONLY the JSON object"


class _FakeResponse:
    """The two attributes `llm._post` reads on a 200, plus the two it reads on an error."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.status_code = 200
        self.headers: dict[str, str] = {}
        self.text = ""
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    """Stands in for `httpx.AsyncClient`. Replies from a scripted list; last reply repeats.

    Only the request body is recorded. The Authorization header is deliberately dropped on the
    floor so a captured request can never carry a key into an assertion message (D30).
    """

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self._replies = replies
        self.bodies: list[dict[str, Any]] = []

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        self.bodies.append(copy.deepcopy(json))  # deep copy: llm.py mutates the body between attempts
        return _FakeResponse(self._replies[min(len(self.bodies) - 1, len(self._replies) - 1)])


def _reply(content: str, finish: str = "length") -> dict[str, Any]:
    """One OpenRouter chat completion, shaped exactly as the live runs in plan §1.6 were."""
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 12430, "completion_tokens": 2000, "cost": 0.05,
                  "completion_tokens_details": {"reasoning_tokens": 2771}},
    }


def _client(replies: list[dict[str, Any]], *, max_tokens: int = 12000,
            ceiling: int = 0) -> tuple[LLMClient, _FakeClient, list[tuple[str, dict[str, Any]]]]:
    """An LLMClient wired to a fake transport, with its warnings captured for the A8 assertions."""
    events: list[tuple[str, dict[str, Any]]] = []
    transport = _FakeClient(replies)
    client = LLMClient(
        {"analysis": RoleSettings(model="anthropic/claude-sonnet-5", max_tokens=max_tokens,
                                  max_output_ceiling=ceiling)},
        api_key="",  # never read from the environment: this test cannot reach a real endpoint
        client=transport,
        on_warning=lambda event, message, **data: events.append((event, data)),
    )
    return client, transport, events


async def test_a_truncated_call_stops_after_one_widened_retry_and_says_so() -> None:
    """Two attempts, never three: FR-127 widens once, then FR-41's retry is SKIPPED (plan A6).

    A third attempt is the defect this fixes — `20260811_135734_6h6s` billed 37,280 prompt tokens
    (3 × ~12,430) for one brief, because the formatting nudge fired on an unfinished body.
    """
    client, transport, events = _client([_reply('{"render_prompt": "half a bri'), _reply("")])

    result = await client.structured_call("analysis", _MESSAGES, _SCHEMA)

    assert len(transport.bodies) == 2, "attempt 1 + one widened retry; a third attempt means A6 failed"
    assert result.degraded is True
    assert result.truncated is True
    assert result.retried is False, "FR-41's formatting retry must not be spent on a cut-off body"
    assert result.reason, "every degrade path carries an operator-facing reason (A7)"
    assert "cut off" in result.reason
    assert "FR-41" not in result.reason, "the message must not name a retry that never ran"
    # The nudge is the observable proof the FR-41 retry never went out.
    assert not any(_NUDGE_MARKER in str(m.get("content"))
                   for m in transport.bodies[1]["messages"])
    # Usage is accumulated across BOTH billed attempts (FR-106c).
    assert result.prompt_tokens == 2 * 12430


async def test_the_widened_retry_is_wider_but_never_past_the_ceiling() -> None:
    """A5: the bump must not walk `max_tokens` past what the model will accept — that is a 400."""
    client, transport, _ = _client([_reply("{"), _reply("")], max_tokens=12000)

    await client.structured_call("analysis", _MESSAGES, _SCHEMA)

    first, second = transport.bodies[0]["max_tokens"], transport.bodies[1]["max_tokens"]
    assert first == 12000
    assert second > first, "FR-127: the retry may never be an identical request"
    assert second <= _DEFAULT_MAX_OUTPUT_CEILING, "12000 + 8192 = 20192 would be a hard HTTP 400"


async def test_a_cap_already_at_the_ceiling_fails_fast_instead_of_repeating_itself() -> None:
    """FR-127 forbids an identical retry, so at the ceiling the only legal move is to stop.

    One attempt, one clear reason naming the ceiling — not a second identical bill.
    """
    client, transport, events = _client([_reply('{"render_prompt": "cut')],
                                        max_tokens=8000, ceiling=8000)

    result = await client.structured_call("analysis", _MESSAGES, _SCHEMA)

    assert len(transport.bodies) == 1
    assert result.degraded is True and result.truncated is True
    assert "8000" in result.reason and "FR-127" in result.reason
    assert not any(event == "llm_truncated" for event, _ in events), "nothing was retried wider"


async def test_the_warning_events_carry_what_the_operator_needs_to_diagnose_a_stall() -> None:
    """A8: `finish_reason`, `attempt`, `truncated` and `retried` reach events.jsonl."""
    client, _, events = _client([_reply('{"render_prompt": "half'), _reply("")])

    await client.structured_call("analysis", _MESSAGES, _SCHEMA)

    seen = dict(events)
    assert set(seen) == {"llm_truncated", "llm_parse_failed"}
    assert seen["llm_truncated"]["finish_reason"] == "length"
    assert seen["llm_truncated"]["attempt"] == 1
    assert seen["llm_truncated"]["new_max_tokens"] > 12000
    assert seen["llm_parse_failed"]["attempt"] == 2
    assert seen["llm_parse_failed"]["truncated"] is True
    assert seen["llm_parse_failed"]["retried"] is False


async def test_a_badly_formatted_but_complete_response_still_gets_the_fr41_retry() -> None:
    """The A6 gate is narrow on purpose: only TRUNCATION skips FR-41, prose does not."""
    client, transport, events = _client(
        [_reply("here is your brief:", finish="stop"),
         _reply('{"render_prompt": "a whole brief"}', finish="stop")])

    result = await client.structured_call("analysis", _MESSAGES, _SCHEMA)

    assert len(transport.bodies) == 2
    assert result.retried is True and result.degraded is False
    assert result.parsed == {"render_prompt": "a whole brief"}
    assert any(_NUDGE_MARKER in str(m.get("content")) for m in transport.bodies[1]["messages"])
    assert [event for event, _ in events] == ["llm_parse_retry"]
