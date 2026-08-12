"""OpenRouter REST seam — the engine's only door to an LLM (FR-39–41, 125–129, 248).

Module contract
---------------
Purpose: turn a role name, a message list and a JSON Schema into a parsed Python object,
hiding strict structured-output mode, provider routing, vision encoding, bounded transport
retries, truncation handling and the run-scoped 402 behind ONE call.

Public API:
    RoleSettings                                   — one role's model + limits, passed IN
    LLMClient(roles, ...)                          — owns the httpx client and the LLM semaphore
    await client.structured_call(role, messages, json_schema, images=None) -> ParsedResult
    client.credits_exhausted                       — FR-248 run condition, for the run summary
    await client.aclose()                          — also usable as `async with LLMClient(...)`

Invariants enforced here, once, for every caller:
- **Schema-agnostic (plan §3).** `json_schema` is whatever the caller needs; this module never
  learns a field name. New schema needs belong in the CALLER, never here.
- **No config import.** Per-role settings arrive as `RoleSettings` from the runner, keeping the
  config seam one-directional.
- **Never raises for a provider outcome.** Transport failure, HTTP error, unparseable body and
  credit exhaustion all come back as a `ParsedResult` with `degraded=True`, `parsed=None` and a
  short operator-facing cause in `reason` (`raw_text` keeps the body, for events.jsonl); callers
  write `if result.degraded: <fall back>` and attach `copy_degraded` (or fail open, for the
  topic filter) themselves. Only a programmer error (unknown role) raises.
- **402 is a run condition (FR-248).** The first 402 latches `credits_exhausted`; that call and
  every later one short-circuit to a degraded result reading exactly `CREDITS_EXHAUSTED_REASON`
  — no retry, no further HTTP. Reported distinctly from Kie's 402 (FR-167): different fix.
- **Two independent content retries, each capped at 1** (NFR-14): FR-126's tolerant parse runs
  BEFORE either is spent; FR-127's truncation retry raises `max_tokens` — bounded by the role's
  output ceiling — so the retry is never identical; FR-41's retry is the last resort and is NOT
  spent on a truncated response, because a body cut off mid-JSON is not a formatting failure and
  re-asking it only buys the same truncation at the same price.
- **NFR-111 floors** are applied at construction: a `max_tokens` below its floor is clamped UP
  and warned once, so a misconfigured tiny limit cannot silently truncate every call.
- **Vision is base64 only (FR-40).** Callers hand over already-downloaded bytes; a CDN URL is
  never re-fetched at call time. Downscaling/capping is the caller's job (FR-128/FR-93).
- **Secrets (D30/NFR-112).** `OPENROUTER_API_KEY` reaches the Authorization header and nowhere
  else — not a prompt, not a log line, not an exception message.

⚠ FR-129 CONFLICT — surfaced, not silently resolved (D15 amendment candidate).
FR-129 mandates "a stable, configured temperature". RESULTS.md §E measured that NEITHER shipped
model (`openai/gpt-5.6-luna`, `anthropic/claude-sonnet-5`) lists `temperature` in its OpenRouter
`supported_parameters`, and that sending it together with FR-125's mandatory
`provider.require_parameters: true` makes the request unroutable — HTTP 404 that reads like
"unknown model". So `temperature` is sent ONLY when a role marks it supported, and omitted by
default; the same opt-in guards `seed` (Luna advertises it, Sonnet 5 does not). FR-129's
reproducibility intent rests instead on the fixed per-role system prompt, which is
caller-supplied and never mutated here. The PRD text needs the amendment; the code cannot
honour it as written.

Do not: import config here; add a schema-specific helper; retry a 402; resubmit an identical
request after a truncation; log the API key, a header dict, or raw image bytes.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Sequence

import httpx

from hypesocials.models import ParsedResult

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
#: FR-248's exact operator-facing reason; the runner prints it verbatim, distinct from Kie's 402.
CREDITS_EXHAUSTED_REASON = "OpenRouter credits exhausted"

DEFAULT_HTTP_MAX_ATTEMPTS = 3  # NFR-14 / 20 §7 — transport retries only
DEFAULT_MAX_INFLIGHT_LLM_CALLS = 4
DEFAULT_TIMEOUT_S = 180.0  # reasoning models think for a while; a hung call must still end

_RETRY_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_TRUNCATED_REASONS = frozenset({"length", "max_tokens", "max_output_tokens"})
_BACKOFF_BASE_S = 1.0
_BACKOFF_CEILING_S = 20.0
_TRUNCATION_BUMP_MAX = 8192  # FR-127: the retry differs by a bounded token bump, never doubles forever
#: Used when a role does not declare `max_output_ceiling` — see `_output_ceiling` for the why.
_DEFAULT_MAX_OUTPUT_CEILING = 16384
_SCHEMA_NAME_SAFE = re.compile(r"[^A-Za-z0-9_-]+")
#: FR-41's one retry appends this as a USER turn — the per-role SYSTEM prompt is never touched.
_RETRY_NUDGE = "Return ONLY the JSON object required by the schema. No prose, no markdown fences."
#: Magic-byte sniff for the data: URI; OpenRouter needs a real media type, not a guess from a path.
_IMAGE_MIMES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"), (b"RIFF", "image/webp"),
)


@dataclass(slots=True)
class RoleSettings:
    """One LLM role's model and limits — built by the runner from config, never read from disk here.

    `temperature` and `seed` are opt-in for the reason in the module docstring: an unsupported
    sampling parameter plus `require_parameters: true` is a 404, not a warning. Leave both at
    their defaults unless the model's OpenRouter `supported_parameters` actually lists them.
    """

    model: str
    max_tokens: int = 4096
    max_tokens_floor: int = 0  # NFR-111 — clamped UP to this at construction, with a warning
    max_output_ceiling: int = 0  # 0 = unknown; FR-127's widened retry is clamped here (see `_output_ceiling`)
    reasoning_effort: str | None = None  # "low" | "medium" | "high"; None omits `reasoning`
    temperature: float | None = None
    temperature_supported: bool = False  # FR-129 conflict gate — see module docstring
    seed: int | None = None  # Luna advertises it, Sonnet 5 does not; None omits it


class LLMClient:
    """The OpenRouter seam. One instance per run; holds the `max_inflight_llm_calls` semaphore."""

    def __init__(
        self,
        roles: dict[str, RoleSettings],
        *,
        api_key: str | None = None,
        max_inflight_llm_calls: int = DEFAULT_MAX_INFLIGHT_LLM_CALLS,
        http_max_attempts: int = DEFAULT_HTTP_MAX_ATTEMPTS,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        on_warning: Callable[..., Any] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """`on_warning(event_type, message, **data)` matches `LogWriter.warn` — pass it straight in."""
        self._on_warning = on_warning
        self._roles = {name: self._apply_floor(name, s) for name, s in roles.items()}
        self._key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "")
        self._attempts = max(1, int(http_max_attempts))
        self._gate = asyncio.Semaphore(max(1, int(max_inflight_llm_calls)))
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._credits_exhausted = False

    # ----------------------------------------------------------------- public API

    @property
    def credits_exhausted(self) -> bool:
        """True once OpenRouter has answered 402 — the run summary reports the shortfall (FR-248)."""
        return self._credits_exhausted

    async def structured_call(
        self,
        role: str,
        messages: list[dict[str, Any]],
        json_schema: dict[str, Any],
        images: list[bytes] | None = None,
    ) -> ParsedResult:
        """One strict-schema LLM call — see `models.StructuredCall` for the pinned contract.

        Args:
            role: key into the `roles` mapping this client was built with (model, limits, effort).
            messages: OpenRouter chat messages; the caller owns the fixed per-role system prompt.
            json_schema: either a bare JSON Schema or an OpenRouter `{name, schema}` wrapper.
            images: already-downloaded bytes, attached to the last user turn as base64 (FR-40).

        Returns:
            ParsedResult — `parsed` is the validated object on success; on any failure
            `degraded=True`, `parsed=None`, `reason` carries the operator-facing cause and
            `raw_text` carries whatever body came back. Token/cost usage is accumulated across
            every attempt, because retries are billed too (FR-106c).
        """
        settings = self._roles.get(role)
        if settings is None:
            raise ValueError(f"unknown LLM role {role!r}; configured roles: {sorted(self._roles)}")
        if self._credits_exhausted:
            return ParsedResult(parsed=None, raw_text=CREDITS_EXHAUSTED_REASON, degraded=True,
                                reason=CREDITS_EXHAUSTED_REASON)
        schema = _inner_schema(json_schema)
        body = _build_body(settings, messages, images, json_schema)
        async with self._gate:  # `max_inflight_llm_calls` — every call, retries included
            return await self._run_attempts(role, body, schema, _output_ceiling(settings))

    async def aclose(self) -> None:
        """Closes the HTTP client this module opened; an injected client is the caller's to close."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> LLMClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ----------------------------------------------------------------- internals

    async def _run_attempts(
        self, role: str, body: dict[str, Any], schema: dict[str, Any], ceiling: int
    ) -> ParsedResult:
        """Parse → (FR-127 truncation retry) → (FR-41 content retry). Each is spendable exactly once.

        `attempt` counts CONTENT attempts — one `_post` call each, transport retries folded in —
        not HTTP requests, because that is the number an operator reading `events.jsonl` needs to
        answer "how many times was this prompt billed".
        """
        out = ParsedResult(parsed=None, raw_text="")
        truncation_retry, content_retry = True, True
        attempt = 0
        while True:
            attempt += 1
            text, finish, failure = await self._post(role, body, out)
            if failure is not None:
                out.raw_text = out.raw_text or failure
                out.reason = failure
                out.degraded = True
                return out
            out.raw_text = text
            parsed, tolerant = _parse_json(text)
            if parsed is not None and _satisfies(parsed, schema):
                out.parsed = parsed
                out.tolerant_parsed = tolerant  # FR-126 rescued it without spending a retry
                return out
            cut_off = finish in _TRUNCATED_REASONS
            if cut_off and truncation_retry:
                out.truncated = True
                wider = _widen(int(body["max_tokens"]), ceiling)
                if wider:
                    truncation_retry = False
                    body["max_tokens"] = wider
                    self._warn("llm_truncated", f"{role}: response hit the token limit; retrying wider",
                               role=role, new_max_tokens=wider, finish_reason=finish, attempt=attempt,
                               truncated=True, retried=out.retried)
                    continue
                # No wider body is legal, and an identical one is forbidden (FR-127) — fall through
                # to the terminal degrade rather than paying for the same truncation twice.
            elif content_retry and not cut_off:
                # FR-41's nudge is about FORMATTING. A body cut off mid-JSON is not badly
                # formatted, it is unfinished, so spending the nudge on it re-bills the whole
                # prompt for an identically capped answer (plan §1.6: 37,280 prompt tokens on one
                # call). Truncation is handled above, or it is terminal.
                content_retry = False
                out.retried = True  # FR-41's single content retry, spent only after FR-126 failed
                body["messages"] = [*body["messages"], {"role": "user", "content": _RETRY_NUDGE}]
                self._warn("llm_parse_retry", f"{role}: response was not schema-valid JSON; retrying once",
                           role=role, chars=len(text), finish_reason=finish, attempt=attempt,
                           truncated=out.truncated, retried=True)
                continue
            out.degraded = True
            out.reason = _degrade_reason(role, cut_off=cut_off, retry_left=truncation_retry,
                                         max_tokens=int(body["max_tokens"]), ceiling=ceiling,
                                         retried=out.retried, chars=len(text))
            self._warn("llm_parse_failed", f"{role}: {out.reason}",
                       role=role, chars=len(text), finish_reason=finish, attempt=attempt,
                       truncated=out.truncated, retried=out.retried)
            return out

    async def _post(
        self, role: str, body: dict[str, Any], usage_sink: ParsedResult
    ) -> tuple[str, str, str | None]:
        """One request with bounded 429/5xx backoff. Returns `(content, finish_reason, failure)`."""
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        delay = _BACKOFF_BASE_S
        for attempt in range(1, self._attempts + 1):
            last = attempt == self._attempts
            try:
                response = await self._client.post(OPENROUTER_URL, json=body, headers=headers)
            except httpx.HTTPError as exc:  # transport-level: timeout, connect, read, protocol
                if last:
                    return "", "", f"OpenRouter transport error after {attempt} attempts: {type(exc).__name__}"
                await self._backoff(role, delay, f"transport {type(exc).__name__}")
                delay = min(delay * 2, _BACKOFF_CEILING_S)
                continue
            status = response.status_code
            if status == 402:  # FR-248 — latched once, never retried, whole-run condition
                self._latch_credits_exhausted()
                return "", "", CREDITS_EXHAUSTED_REASON
            if status in _RETRY_STATUSES and not last:
                await self._backoff(role, _retry_after(response, delay), f"HTTP {status}")
                delay = min(delay * 2, _BACKOFF_CEILING_S)
                continue
            if status >= 400:
                # The body matters: a 404 here often means "unroutable parameter set", not
                # "unknown model" (RESULTS.md §E) — surfacing only the status hides the cause.
                return "", "", f"OpenRouter HTTP {status}: {_error_message(response)}"
            try:
                data = response.json()
            except ValueError:
                return "", "", "OpenRouter returned a non-JSON body"
            if isinstance(data.get("error"), dict):  # 200 with an error envelope
                return "", "", f"OpenRouter error: {data['error'].get('message', 'unknown')}"
            _absorb_usage(data, usage_sink)
            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
            return content, str(choice.get("finish_reason") or ""), None
        return "", "", f"OpenRouter retries exhausted ({self._attempts} attempts)"

    async def _backoff(self, role: str, delay: float, cause: str) -> None:
        self._warn("llm_retry", f"{role}: {cause}; retrying in {delay:.1f}s", role=role, delay_s=delay)
        await asyncio.sleep(delay)

    def _latch_credits_exhausted(self) -> None:
        if not self._credits_exhausted:
            self._credits_exhausted = True
            self._warn("llm_credits_exhausted", CREDITS_EXHAUSTED_REASON)

    def _apply_floor(self, role: str, settings: RoleSettings) -> RoleSettings:
        """NFR-111: clamp a per-role token limit UP to its floor, loudly, once per run."""
        if settings.max_tokens_floor and settings.max_tokens < settings.max_tokens_floor:
            self._warn(
                "llm_token_floor_applied",
                f"{role}: max_tokens {settings.max_tokens} is below the configured floor "
                f"{settings.max_tokens_floor}; using the floor",
                role=role, configured=settings.max_tokens, floor=settings.max_tokens_floor,
            )
            settings.max_tokens = settings.max_tokens_floor
        return settings

    def _warn(self, event_type: str, message: str, **data: Any) -> None:
        logger.warning("%s: %s", event_type, message)
        if self._on_warning is not None:
            self._on_warning(event_type, message, **data)


# --------------------------------------------------------------------------------------------
# Request building — the exact shape RESULTS.md §E proved (FR-41/125/128/129, 20 §7).
# --------------------------------------------------------------------------------------------

def _output_ceiling(settings: RoleSettings) -> int:
    """The widest `max_tokens` FR-127's truncation retry may ask for on this role.

    Why a ceiling exists at all: the retry widens by up to `_TRUNCATION_BUMP_MAX`, so the
    12,000-token analysis cap would ask for 20,192. Past a model's advertised max output that is
    a hard HTTP 400 — the truncation path would stop degrading gracefully and start failing the
    call outright, which is strictly worse than the truncation it is trying to fix.

    Why the default: no role the runner builds today declares `max_output_ceiling`, and 16,384 is
    an output window every currently shipped chat model advertises, so it is the widest ask that
    is safe WITHOUT per-model knowledge. A role that knows its model's real limit sets the field.

    Why `max()` and not the bare ceiling: an operator who configures a large `max_tokens` has
    already proven that value routable on their model. Clamping the retry below it would forbid
    the retry entirely (`_widen` returns 0), turning a working config into a fail-fast one.
    """
    return max(settings.max_output_ceiling or _DEFAULT_MAX_OUTPUT_CEILING, settings.max_tokens)


def _widen(current: int, ceiling: int) -> int:
    """FR-127's wider `max_tokens`, bounded by `ceiling`. Returns 0 when no wider ask is legal.

    FR-127 forbids resubmitting an IDENTICAL request, so a bump the ceiling clamps back to the
    current value is not a retry we are allowed to spend — the caller fails fast on 0 instead.
    """
    widened = min(current + min(current, _TRUNCATION_BUMP_MAX), ceiling)
    return widened if widened > current else 0


def _build_body(
    settings: RoleSettings,
    messages: list[dict[str, Any]],
    images: Sequence[bytes] | None,
    json_schema: dict[str, Any],
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": settings.model,
        "messages": _with_images(messages, images),
        "response_format": _response_format(json_schema),  # FR-41 strict schema mode
        "max_tokens": settings.max_tokens,
        "provider": {"require_parameters": True},  # FR-125 — only schema-honouring providers
        "usage": {"include": True},  # cost/reasoning tokens live in the BODY, not headers
    }
    if settings.reasoning_effort:
        body["reasoning"] = {"effort": settings.reasoning_effort}
    if settings.temperature is not None and settings.temperature_supported:
        body["temperature"] = settings.temperature  # FR-129 conflict gate — module docstring
    if settings.seed is not None:
        body["seed"] = settings.seed
    return body


def _response_format(json_schema: dict[str, Any]) -> dict[str, Any]:
    """Accepts a bare schema or an already-wrapped `{name, schema}`; always emits `strict: true`."""
    wrapped = "schema" in json_schema and isinstance(json_schema.get("schema"), dict)
    name = str(json_schema.get("name") or json_schema.get("title") or "result")
    schema = json_schema["schema"] if wrapped else json_schema
    return {
        "type": "json_schema",
        "json_schema": {"name": _SCHEMA_NAME_SAFE.sub("_", name)[:64], "strict": True, "schema": schema},
    }


def _inner_schema(json_schema: dict[str, Any]) -> dict[str, Any]:
    inner = json_schema.get("schema")
    return inner if isinstance(inner, dict) else json_schema


def _with_images(messages: list[dict[str, Any]], images: Sequence[bytes] | None) -> list[dict[str, Any]]:
    """FR-40: local bytes become base64 `image_url` parts on the LAST user turn. No CDN URLs, ever."""
    if not images:
        return list(messages)
    parts = [{"type": "image_url", "image_url": {"url": _data_uri(blob)}} for blob in images if blob]
    out = [dict(message) for message in messages]
    for message in reversed(out):
        if message.get("role") == "user":
            content = message.get("content")
            existing = [{"type": "text", "text": content}] if isinstance(content, str) else list(content or [])
            message["content"] = existing + parts
            return out
    out.append({"role": "user", "content": parts})
    return out


def _data_uri(blob: bytes) -> str:
    mime = next((m for magic, m in _IMAGE_MIMES if blob.startswith(magic)), "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}"


# --------------------------------------------------------------------------------------------
# Response handling — tolerant parse (FR-126) and usage accounting (FR-106c / NFR-18).
# --------------------------------------------------------------------------------------------

def _degrade_reason(
    role: str,
    *,
    cut_off: bool,
    retry_left: bool,
    max_tokens: int,
    ceiling: int,
    retried: bool,
    chars: int,
) -> str:
    """The operator-facing cause of a terminal degrade — it names the path ACTUALLY taken.

    The message this replaced said "no schema-valid JSON after the FR-41 retry" on every terminal
    path. Once a truncated response can skip that retry, naming a retry that never ran is worse
    than saying nothing: it sends the operator to look at prompt formatting when the real cause
    is the token cap, which is the exact confusion that let every analysis call truncate unnoticed.
    """
    if cut_off and retry_left:
        return (f"response cut off at max_tokens {max_tokens}, already the widest output this role "
                f"may ask for ({ceiling}); a wider retry is impossible and an identical one is "
                f"forbidden (FR-127) — raise models.max_tokens.{role} only if the model allows more")
    if cut_off:
        return (f"response cut off twice; the widened retry at max_tokens {max_tokens} was still "
                f"truncated — raise models.max_tokens.{role} (ceiling {ceiling})")
    if retried:
        return f"no schema-valid JSON after the FR-41 formatting retry ({chars} chars returned)"
    return f"no schema-valid JSON and no retry was available ({chars} chars returned)"


def _parse_json(text: str) -> tuple[Any, bool]:
    """Strict parse first; then FR-126's tolerant rescue. Returns `(obj_or_None, was_tolerant)`."""
    candidate = (text or "").strip()
    if not candidate:
        return None, False
    try:
        return json.loads(candidate), False
    except ValueError:
        pass
    if candidate.startswith("```"):  # ```json … ``` fences
        candidate = candidate.strip("`")
        candidate = candidate.split("\n", 1)[-1] if candidate[:16].lower().startswith("json") else candidate
        candidate = candidate.rsplit("```", 1)[0]
    balanced = _first_balanced_object(candidate)
    if balanced:
        try:
            return json.loads(balanced), True
        except ValueError:
            return None, False
    return None, False


def _first_balanced_object(text: str) -> str:
    """First `{…}` whose braces balance, ignoring braces inside strings. Prose/fences fall away."""
    depth, start, in_string, escaped = 0, -1, False, False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return ""


def _satisfies(parsed: Any, schema: dict[str, Any]) -> bool:
    """Cheap shape gate: an object schema's `required` keys must be present.

    Strict mode already validates server-side; this exists so a TOLERANT parse of half a
    response cannot be handed to a caller as if the provider had validated it.
    """
    if schema.get("type", "object") != "object":
        return parsed is not None
    if not isinstance(parsed, dict):
        return False
    return all(key in parsed for key in schema.get("required") or ())


def _absorb_usage(data: dict[str, Any], sink: ParsedResult) -> None:
    """Accumulate tokens and cost across attempts — a retried call is billed twice (RESULTS.md §E)."""
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return
    details = usage.get("completion_tokens_details") or {}
    sink.prompt_tokens += int(usage.get("prompt_tokens") or 0)
    sink.completion_tokens += int(usage.get("completion_tokens") or 0)
    sink.reasoning_tokens += int(details.get("reasoning_tokens") or 0)
    sink.cost_usd += float(usage.get("cost") or 0.0)


def _retry_after(response: httpx.Response, fallback: float) -> float:
    """Honour a numeric `Retry-After` on 429 (guidelines §6); anything else uses our own backoff."""
    raw = response.headers.get("retry-after", "")
    try:
        return min(max(float(raw), 0.0), _BACKOFF_CEILING_S)
    except ValueError:
        return fallback


def _error_message(response: httpx.Response) -> str:
    """The provider's own reason, never a header or a key — safe to log and to show an operator."""
    try:
        payload = response.json()
    except ValueError:
        return (response.text or "")[:300]
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)[:300]
    return str(error or payload)[:300]


__all__ = ["CREDITS_EXHAUSTED_REASON", "LLMClient", "RoleSettings"]
