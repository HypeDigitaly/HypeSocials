"""The codex door — `LLMClient(backend="codex")` against the local `npx openai-oauth` proxy (D64).

What these tests pin, and why each one exists:

- The REQUEST SHAPE. Every fact below was measured live against the proxy on 2026-08-21, and the
  two that cost the most to rediscover are that `/chat/completions` refuses a base64 image
  (HTTP 500 `URL scheme must be http or https, got data:`) and that `/responses` names its cap
  `max_output_tokens`, not `max_tokens`. A body that drifts back to the chat shape fails on the
  first slide-intelligence call of a paid run, which is the worst possible place to find out.
- The LADDER IS THE SAME LADDER. FR-127 widens once, FR-41 nudges once, neither is spent twice —
  on a body whose cap and turn list live under different keys. `test_llm_truncation.py` pins that
  on the chat body; these pin the same two spends on the `/responses` body.
- $0 AND NO KEY. `usage` carries no `cost` here, and D30's Authorization header must not exist on
  a subscription call. Both are asserted, not assumed.
- The OPENROUTER PATH IS UNTOUCHED. One smoke test posts to the real constant with the old body
  keys, so a refactor that "unifies" the two doors trips here rather than in production.

**Offline by construction.** Every test drives an `httpx.AsyncClient` over `httpx.MockTransport`,
so no socket opens and no key is read (`OPENROUTER_API_KEY` is never consulted on the codex path
by construction, and the openrouter smoke test passes `api_key=""` explicitly).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from hypesocials.llm import (
    CODEX_DEFAULT_BASE_URL,
    OPENROUTER_URL,
    LLMClient,
    RoleSettings,
)

_SCHEMA = {"name": "probe deck", "schema": {"type": "object", "required": ["verdict"],
                                            "properties": {"verdict": {"type": "string"}}}}
_MESSAGES = [{"role": "system", "content": "you judge decks"},
             {"role": "user", "content": "judge this"}]
_JPEG = b"\xff\xd8\xff" + b"pixels"
_NUDGE_MARKER = "Return ONLY the JSON object"


class _Proxy:
    """A scripted `/responses` (or `/chat/completions`) endpoint plus a record of what arrived."""

    def __init__(self, replies: list[Any]) -> None:
        self._replies = replies
        self.bodies: list[dict[str, Any]] = []
        self.urls: list[str] = []
        self.header_names: list[list[str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        self.urls.append(str(request.url))
        # Header NAMES only — a value is where a key would live, and this list ends up in
        # assertion output (D30).
        self.header_names.append(sorted(name.lower() for name in request.headers))
        reply = self._replies[min(len(self.bodies) - 1, len(self._replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        status, payload = reply
        return httpx.Response(status, json=payload)


def _client(replies: list[Any], *, backend: str = "codex", max_tokens: int = 2000,
            effort: str | None = "low", attempts: int = 1,
            **kwargs: Any) -> tuple[LLMClient, _Proxy, list[tuple[str, dict[str, Any]]]]:
    """An `LLMClient` whose transport is the scripted proxy, with its warnings captured."""
    proxy = _Proxy(replies)
    events: list[tuple[str, dict[str, Any]]] = []
    client = LLMClient(
        {"analysis": RoleSettings(model="gpt-5.6-terra", max_tokens=max_tokens,
                                  reasoning_effort=effort)},
        api_key="",  # ignored on the codex path; explicit so no environment is ever consulted
        backend=backend,
        http_max_attempts=attempts,
        client=httpx.AsyncClient(transport=httpx.MockTransport(proxy.handler)),
        on_warning=lambda event, message, **data: events.append((event, data)),
        **kwargs,
    )
    return client, proxy, events


def _answer(text: str, *, status: str = "completed", reason: str | None = None,
            input_tokens: int = 3065, output_tokens: int = 29,
            reasoning_tokens: int = 0) -> tuple[int, dict[str, Any]]:
    """One `/responses` body, shaped exactly as the live proxy answered on 2026-08-21."""
    return 200, {
        "status": status,
        "incomplete_details": None if reason is None else {"reason": reason},
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "role": "assistant",
             "content": [{"type": "output_text", "text": text}]},
        ],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "output_tokens_details": {"reasoning_tokens": reasoning_tokens},
                  "total_tokens": input_tokens + output_tokens},
    }


def _call(client: LLMClient, **kwargs: Any) -> Any:
    async def run() -> Any:
        try:
            return await client.structured_call("analysis", _MESSAGES, _SCHEMA, **kwargs)
        finally:
            await client._client.aclose()  # the injected client is the caller's to close
    return asyncio.run(run())


# --------------------------------------------------------------------------- (a) request shape


def test_codex_body_is_the_responses_shape_the_proxy_measured() -> None:
    """`instructions` + `input` parts + flat `text.format` + `max_output_tokens`, and nothing
    from the chat door: no `messages`, no `response_format`, no `max_tokens`, no `provider`,
    no `usage`, no `temperature`, no `seed`."""
    client, proxy, _ = _client([_answer('{"verdict": "ok"}')])
    _call(client)

    body = proxy.bodies[0]
    assert proxy.urls[0] == f"{CODEX_DEFAULT_BASE_URL}/responses"
    assert body["model"] == "gpt-5.6-terra"
    assert body["instructions"] == "you judge decks"  # the system turn, lifted out of `input`
    assert body["input"] == [{"role": "user", "content": [{"type": "input_text",
                                                           "text": "judge this"}]}]
    assert body["text"]["format"] == {"type": "json_schema", "name": "probe_deck", "strict": True,
                                      "schema": _SCHEMA["schema"]}
    assert body["max_output_tokens"] == 2000
    assert body["reasoning"] == {"effort": "low"}
    assert body["store"] is False
    for forbidden in ("messages", "response_format", "max_tokens", "provider", "usage",
                      "temperature", "seed"):
        assert forbidden not in body


def test_codex_sends_no_authorization_header() -> None:
    """D30: the proxy authenticates out of process, so this engine holds and sends no credential."""
    client, proxy, _ = _client([_answer('{"verdict": "ok"}')])
    _call(client)
    assert "authorization" not in proxy.header_names[0]


def test_codex_images_ride_the_last_user_turn_as_input_image_parts() -> None:
    """FR-40: local bytes, base64, `detail: high`, appended to the LAST user turn — the same
    placement `_with_images` uses on the chat door, because both backends must show a model the
    same conversation."""
    messages = [{"role": "system", "content": "sys"},
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "noted"},
                {"role": "user", "content": "last"}]
    client, proxy, _ = _client([_answer('{"verdict": "ok"}')])

    async def run() -> None:
        try:
            await client.structured_call("analysis", messages, _SCHEMA, images=[_JPEG])
        finally:
            await client._client.aclose()

    asyncio.run(run())
    turns = proxy.bodies[0]["input"]
    assert [turn["role"] for turn in turns] == ["user", "assistant", "user"]
    assert turns[1]["content"] == [{"type": "output_text", "text": "noted"}]  # assistant text part
    assert turns[0]["content"] == [{"type": "input_text", "text": "first"}]   # untouched
    image = turns[2]["content"][1]
    assert image["type"] == "input_image" and image["detail"] == "high"
    assert image["image_url"].startswith("data:image/jpeg;base64,")


def test_codex_accepts_xhigh_effort_which_openrouter_does_not() -> None:
    """`xhigh` is the whole reason `config`'s effort Literal grew a fourth value (D64)."""
    client, proxy, _ = _client([_answer('{"verdict": "ok"}')], effort="xhigh")
    _call(client)
    assert proxy.bodies[0]["reasoning"] == {"effort": "xhigh"}


def test_codex_omits_reasoning_when_the_role_asks_for_none() -> None:
    """An absent `reasoning` field is not "no reasoning" (see `RoleSettings`) — but it must stay
    absent rather than become `{"effort": null}`, which the proxy would reject."""
    client, proxy, _ = _client([_answer('{"verdict": "ok"}')], effort=None)
    _call(client)
    assert "reasoning" not in proxy.bodies[0]


def test_codex_base_url_override_is_honoured_without_a_double_slash() -> None:
    proxy = _Proxy([_answer('{"verdict": "ok"}')])
    client = LLMClient({"analysis": RoleSettings(model="gpt-5.5")}, backend="codex",
                       base_url="http://127.0.0.1:9999/v1/",
                       client=httpx.AsyncClient(transport=httpx.MockTransport(proxy.handler)))
    _call(client)
    assert proxy.urls[0] == "http://127.0.0.1:9999/v1/responses"


def test_an_unknown_backend_is_a_programmer_error_and_raises() -> None:
    with pytest.raises(ValueError, match="unknown LLM backend"):
        LLMClient({"analysis": RoleSettings(model="m")}, backend="anthropic-direct")


# --------------------------------------------------------------------------- (b) parse + usage


def test_codex_success_parses_the_output_text_and_maps_usage_at_zero_cost() -> None:
    """`input_tokens`/`output_tokens`/`output_tokens_details.reasoning_tokens` land on the same
    three counters the chat path fills, and `cost_usd` stays 0.0 — a subscription call is not
    metered, and there is no `usage.cost` field to read even if it were."""
    client, _, _ = _client([_answer('{"verdict": "ship it"}', output_tokens=29,
                                    reasoning_tokens=512)])
    result = _call(client)

    assert result.parsed == {"verdict": "ship it"}
    assert not result.degraded and not result.truncated and not result.retried
    assert (result.prompt_tokens, result.completion_tokens) == (3065, 29)
    assert result.reasoning_tokens == 512
    assert result.cost_usd == 0.0


def test_codex_concatenates_every_output_text_part_and_ignores_reasoning_items() -> None:
    """The answer is a LIST of items; a reasoning item has no `output_text` and contributes
    nothing, while a message split across two parts must not lose its second half."""
    status, payload = _answer("ignored")
    payload["output"] = [
        {"type": "reasoning", "summary": [{"type": "summary_text", "text": "thinking"}]},
        {"type": "message", "content": [{"type": "output_text", "text": '{"verdict": "a'},
                                        {"type": "output_text", "text": 'b"}'}]},
    ]
    client, _, _ = _client([(status, payload)])
    assert _call(client).parsed == {"verdict": "ab"}


# --------------------------------------------------------------------------- (c) truncation


def test_incomplete_max_output_tokens_widens_that_key_exactly_once() -> None:
    """FR-127 on the `/responses` body: `status: incomplete` + `reason: max_output_tokens` is the
    same signal as `finish_reason: length`, and the retry raises `max_output_tokens` — never
    `max_tokens`, which this body does not have."""
    client, proxy, events = _client(
        [_answer('{"verdict": "cut of', status="incomplete", reason="max_output_tokens"),
         _answer('{"verdict": "whole"}')])
    result = _call(client)

    assert [body["max_output_tokens"] for body in proxy.bodies] == [2000, 4000]
    assert all("max_tokens" not in body for body in proxy.bodies)
    assert result.truncated and result.parsed == {"verdict": "whole"}
    assert not result.retried  # the FR-41 nudge was NOT spent on a truncation
    assert [event for event, _ in events] == ["llm_truncated"]
    assert all(_NUDGE_MARKER not in json.dumps(body) for body in proxy.bodies)


def test_a_second_truncation_degrades_and_never_resubmits_an_identical_body() -> None:
    """Two truncations end the call: FR-127 forbids an identical resubmit, so there is no third
    attempt and the reason names the cap the operator has to raise."""
    client, proxy, _ = _client(
        [_answer("{", status="incomplete", reason="max_output_tokens")], max_tokens=12000)
    result = _call(client)

    assert len(proxy.bodies) == 2  # 12,000 then the ceiling-clamped 16,384, then stop
    assert [body["max_output_tokens"] for body in proxy.bodies] == [12000, 16384]
    assert result.degraded and "cut off twice" in (result.reason or "")


# --------------------------------------------------------------------------- (d) format nudge


def test_non_json_spends_one_nudge_appended_to_input_as_a_user_turn() -> None:
    """FR-41 on the `/responses` body: the nudge is an extra USER turn in `input` (with an
    `input_text` part, the only content form this endpoint takes), and `instructions` — the
    per-role system prompt — is untouched."""
    client, proxy, events = _client([(200, _answer("here you go: nope")[1]),
                                     _answer('{"verdict": "ok"}')])
    result = _call(client)

    assert len(proxy.bodies) == 2
    assert proxy.bodies[0]["input"] == proxy.bodies[1]["input"][:-1]  # appended, never rewritten
    nudge = proxy.bodies[1]["input"][-1]
    assert nudge["role"] == "user"
    assert nudge["content"][0]["type"] == "input_text"
    assert _NUDGE_MARKER in nudge["content"][0]["text"]
    assert proxy.bodies[1]["instructions"] == "you judge decks"
    assert result.retried and result.parsed == {"verdict": "ok"}
    assert [event for event, _ in events] == ["llm_parse_retry"]


def test_the_nudge_is_spent_at_most_once() -> None:
    """Two unparseable answers degrade rather than nudging forever (NFR-14)."""
    client, proxy, _ = _client([(200, _answer("prose, always prose")[1])])
    result = _call(client)
    assert len(proxy.bodies) == 2
    assert result.degraded and "FR-41" in (result.reason or "")


# --------------------------------------------------------------------------- (e) transport


def test_a_connect_error_names_the_command_that_starts_the_proxy() -> None:
    """The single most likely codex failure is "nothing is listening on 10531". A bare
    `ConnectError` tells an operator nothing; the hint is the whole fix in one line."""
    boom = httpx.ConnectError("all connection attempts failed")
    client, _, _ = _client([boom])
    result = _call(client)

    assert result.degraded
    assert "Codex proxy transport error after 1 attempts: ConnectError" in (result.reason or "")
    assert "npx openai-oauth@latest" in (result.reason or "")
    assert "OpenRouter" not in (result.reason or "")


def test_a_read_timeout_gets_no_proxy_hint_because_the_proxy_answered() -> None:
    """A call that REACHED the proxy and then timed out is a slow model, not a dead process —
    pointing at the start command there would send the operator to the wrong fix."""
    client, _, _ = _client([httpx.ReadTimeout("timed out")])
    result = _call(client)
    assert result.degraded and "npx" not in (result.reason or "")


def test_codex_http_and_envelope_errors_say_codex_proxy_not_openrouter() -> None:
    client, _, _ = _client([(500, {"error": {"message": "URL scheme must be http or https"}})])
    result = _call(client)
    assert (result.reason or "").startswith("Codex proxy HTTP 500: URL scheme must be")

    client, _, _ = _client([(200, {"error": {"message": "quota"}})])
    assert _call(client).reason == "Codex proxy error: quota"


def test_a_402_from_the_proxy_is_an_ordinary_error_and_never_latches_credits() -> None:
    """FR-248's latch prints "OpenRouter credits exhausted" and stops every later LLM call for the
    whole run. On a subscription there are no OpenRouter credits to exhaust, so a 402 here must
    stay a plain HTTP error — latching it would kill a run over an account nobody is billing."""
    client, _, _ = _client([(402, {"error": {"message": "payment required"}})])
    result = _call(client)

    assert client.credits_exhausted is False
    assert "Codex proxy HTTP 402" in (result.reason or "")
    assert "credits exhausted" not in (result.reason or "")


# --------------------------------------------------------------------------- (f) openrouter


def test_the_openrouter_door_is_byte_for_byte_the_old_one() -> None:
    """The regression guard for this whole session: same URL constant, same body keys, same
    Authorization header, same `choices[0].message.content` parse. If a "unification" refactor
    ever pulls the chat door onto `/responses`, this fails first."""
    reply = (200, {"choices": [{"message": {"content": '{"verdict": "ok"}'},
                                "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cost": 0.02,
                             "completion_tokens_details": {"reasoning_tokens": 4}}})
    client, proxy, _ = _client([reply], backend="openrouter")
    result = _call(client)

    assert proxy.urls[0] == OPENROUTER_URL
    assert set(proxy.bodies[0]) == {"model", "messages", "response_format", "max_tokens",
                                    "provider", "usage", "reasoning"}
    assert proxy.bodies[0]["messages"] == _MESSAGES
    assert proxy.bodies[0]["provider"] == {"require_parameters": True}
    assert "authorization" in proxy.header_names[0]
    assert result.parsed == {"verdict": "ok"} and result.cost_usd == 0.02


def test_xhigh_on_the_openrouter_backend_is_clamped_to_high_with_one_warning() -> None:
    """A config edited for the codex door and switched back must not 400 on every single call:
    `xhigh` is not in OpenRouter's effort enum, and an unknown enum value there is a hard 400.
    One loud warning, one working call — and only the `RoleSettings` is touched, never the file."""
    reply = (200, {"choices": [{"message": {"content": '{"verdict": "ok"}'},
                                "finish_reason": "stop"}]})
    client, proxy, events = _client([reply], backend="openrouter", effort="xhigh")
    _call(client)

    assert proxy.bodies[0]["reasoning"] == {"effort": "high"}
    assert [event for event, _ in events] == ["llm_effort_clamped"]
