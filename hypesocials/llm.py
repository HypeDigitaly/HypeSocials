"""LLM REST seam — the engine's only door to an LLM (FR-39–41, 125–129, 248).

Module contract
---------------
Purpose: turn a role name, a message list and a JSON Schema into a parsed Python object,
hiding strict structured-output mode, provider routing, vision encoding, bounded transport
retries, truncation handling and the run-scoped 402 behind ONE call.

Public API:
    RoleSettings                                   — one role's model + limits, passed IN
    LLMClient(roles, backend=…, base_url=…, …)     — owns the httpx client and the LLM semaphore
    await client.structured_call(role, messages, json_schema, images=None) -> ParsedResult
    client.credits_exhausted                       — FR-248 run condition, for the run summary
    await client.aclose()                          — also usable as `async with LLMClient(...)`

TWO DOORS, ONE CONTRACT (SESSION O / D64)
-----------------------------------------
`backend="openrouter"` (default) is the metered REST seam this engine shipped with: a POST to
`OPENROUTER_URL` carrying `messages`, `response_format`, `max_tokens`, `provider` and
`usage.include`, priced per token and answered with `choices[0].message.content`.

`backend="codex"` is the operator's own ChatGPT/Codex subscription, exposed on loopback by
`npx openai-oauth@latest` as an OpenAI-compatible endpoint (default `http://127.0.0.1:10531/v1`).
Three measured facts shape that path (all verified live 2026-08-21):

- **Everything goes to `/responses`, images or not.** The proxy's `/chat/completions` REFUSES a
  base64 image — HTTP 500 `URL scheme must be http or https, got data:` — and FR-40 forbids
  handing it a CDN URL instead. Two endpoints would mean two response parsers, two truncation
  ladders and a vision path nobody exercises until the first slide-intelligence call of a paid
  run, so there is ONE codex request shape: `instructions` + `input` + `text.format`.
- **The cap and the nudge live under different keys.** `/responses` caps with
  `max_output_tokens` and carries turns in `input`, so FR-127's widened retry and FR-41's single
  nudge reach the body through `_cap_key` / `_append_nudge` rather than by name. The LADDER is
  unchanged: widen once, nudge once, never an identical resubmit.
- **There is no price in the answer.** `usage` has `input_tokens`/`output_tokens`/
  `output_tokens_details.reasoning_tokens` and no `cost`, because a subscription call is not
  metered. Tokens are still accumulated (they are the only measurement of a retry's weight);
  `cost_usd` stays 0.0, and `budget._llm_call_price` prices every LLM line of the estimate at $0
  with origin "subscription (Codex OAuth)" so the Confirm gate does not quote Sonnet's rate for
  work the invoice will never show.

What the codex door does NOT do: send an `Authorization` header, read `OPENROUTER_API_KEY`, send
`provider`/`usage`/`temperature`/`seed`, or latch `credits_exhausted` on a 402 — that latch prints
the words "OpenRouter credits exhausted", which on a subscription call would send the operator to
top up an account that is not in the loop. A 402 from the proxy is an ordinary HTTP error.
`reasoning.effort` accepts `xhigh` here, which OpenRouter does not take.

Everything else below is backend-agnostic: the tolerant parse, the shape gate, the two capped
content retries, the backoff ladder and the never-raises contract are the same code for both.

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
  else — not a prompt, not a log line, not an exception message. Under `backend="codex"` it is
  not read at all and no Authorization header is built: the OAuth token stays inside the local
  proxy's own `~/.codex/auth.json` and this process never holds it.

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
request after a truncation; log the API key, a header dict, or raw image bytes; send a codex
request to `/chat/completions`; or expose the proxy on anything but loopback.
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

BACKEND_OPENROUTER = "openrouter"
BACKEND_CODEX = "codex"
#: Where `npx openai-oauth@latest` listens by default. Mirrors `config.ModelsConfig.llm_base_url`;
#: the runner passes the configured value through, so this constant is only the last resort for a
#: caller that builds an `LLMClient` without a config in hand (tests, one-off probes).
CODEX_DEFAULT_BASE_URL = "http://127.0.0.1:10531/v1"
#: The one endpoint the codex backend uses — see the module docstring for why it is not
#: `/chat/completions` even for a text-only call.
_CODEX_PATH = "/responses"
_OPENROUTER_PATH = "/chat/completions"
#: What an error message calls the far end. An operator who reads "OpenRouter HTTP 500" while
#: running on their subscription goes and checks the wrong dashboard.
_BACKEND_LABELS = {BACKEND_OPENROUTER: "OpenRouter", BACKEND_CODEX: "Codex proxy"}
#: Appended to a codex transport failure that looks like "nothing is listening". The proxy is a
#: process the operator starts, so naming the command is the whole fix in one line.
_CODEX_DOWN_HINT = "is `npx openai-oauth@latest` running?"

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
#: `/responses` asks how hard to look at an image. Every image this engine sends is a rendered
#: frame or a source slide whose small on-image TEXT is the whole question (slide intelligence,
#: the gauntlet's critics), so `low` would defeat the call it is part of. The chat backend has no
#: such field and its provider default is already the equivalent.
_IMAGE_DETAIL = "high"
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
    #: "low" | "medium" | "high". `None` omits the `reasoning` field from the request entirely —
    #: which is NOT "no reasoning": a thinking model left unbidden thinks at its own default
    #: effort and bills it (Sonnet-5 bills those tokens inside `completion_tokens`, where no cap
    #: of ours distinguishes them from the answer). A role that wants a cheap answer must SAY
    #: `low`; the runner's `_ROLE_EFFORT` map is where each role's answer to that lives (F5).
    reasoning_effort: str | None = None
    temperature: float | None = None
    temperature_supported: bool = False  # FR-129 conflict gate — see module docstring
    seed: int | None = None  # Luna advertises it, Sonnet 5 does not; None omits it


class LLMClient:
    """The LLM seam. One instance per run; holds the `max_inflight_llm_calls` semaphore."""

    def __init__(
        self,
        roles: dict[str, RoleSettings],
        *,
        api_key: str | None = None,
        backend: str = BACKEND_OPENROUTER,
        base_url: str = "",
        max_inflight_llm_calls: int = DEFAULT_MAX_INFLIGHT_LLM_CALLS,
        http_max_attempts: int = DEFAULT_HTTP_MAX_ATTEMPTS,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        on_warning: Callable[..., Any] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """`on_warning(event_type, message, **data)` matches `LogWriter.warn` — pass it straight in.

        Args:
            backend: `"openrouter"` (metered REST) or `"codex"` (the local subscription proxy).
                Anything else is a programmer error and raises — config's `Literal` already
                guards the operator-facing side, so a bad value here can only come from code.
            base_url: the API root, WITHOUT the endpoint path. Empty means "the default for this
                backend": OpenRouter's own URL, or `CODEX_DEFAULT_BASE_URL`. Passing a root for
                the openrouter backend is honoured too (a corporate gateway), which is why the
                path is appended here rather than baked into one constant.
        """
        if backend not in _BACKEND_LABELS:
            raise ValueError(f"unknown LLM backend {backend!r}; expected one of {sorted(_BACKEND_LABELS)}")
        self._on_warning = on_warning
        self._backend = backend
        self._codex = backend == BACKEND_CODEX
        self._label = _BACKEND_LABELS[backend]
        self._url = _endpoint(backend, base_url)
        # After the backend is known: `_apply_floor` also grades `reasoning_effort`, which is
        # backend-dependent (`xhigh` exists on the proxy and nowhere else).
        self._roles = {name: self._apply_floor(name, s) for name, s in roles.items()}
        # D30: on the codex path the environment is never consulted. The proxy authenticates with
        # the operator's OAuth token out of process; this engine holds no credential at all.
        self._key = "" if self._codex else (
            api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", ""))
        self._attempts = max(1, int(http_max_attempts))
        self._gate = asyncio.Semaphore(max(1, int(max_inflight_llm_calls)))
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._credits_exhausted = False

    # ----------------------------------------------------------------- public API

    @property
    def credits_exhausted(self) -> bool:
        """True once OpenRouter has answered 402 — the run summary reports the shortfall (FR-248).

        Always False on the codex backend: a subscription call cannot run a prepaid balance dry,
        so a 402 from the proxy is reported as the ordinary HTTP error it is.
        """
        return self._credits_exhausted

    @property
    def backend(self) -> str:
        """Which door this client is using — `"openrouter"` or `"codex"`, for the run summary."""
        return self._backend

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
        build = _build_codex_body if self._codex else _build_body
        body = build(settings, messages, images, json_schema)
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

        Backend-agnostic by construction: the two things the ladder MUTATES — the output cap and
        the turn list — are reached through `_cap_key` and `_append_nudge`, which read the body's
        own shape. A chat body widens `max_tokens` and appends a `messages` turn; a `/responses`
        body widens `max_output_tokens` and appends an `input` turn. Same two spends, same order,
        same "never resubmit an identical request".
        """
        out = ParsedResult(parsed=None, raw_text="")
        truncation_retry, content_retry = True, True
        cap = _cap_key(body)
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
                wider = _widen(int(body[cap]), ceiling)
                if wider:
                    truncation_retry = False
                    body[cap] = wider
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
                _append_nudge(body)
                self._warn("llm_parse_retry", f"{role}: response was not schema-valid JSON; retrying once",
                           role=role, chars=len(text), finish_reason=finish, attempt=attempt,
                           truncated=out.truncated, retried=True)
                continue
            out.degraded = True
            out.reason = _degrade_reason(role, cut_off=cut_off, retry_left=truncation_retry,
                                         max_tokens=int(body[cap]), ceiling=ceiling,
                                         retried=out.retried, chars=len(text))
            self._warn("llm_parse_failed", f"{role}: {out.reason}",
                       role=role, chars=len(text), finish_reason=finish, attempt=attempt,
                       truncated=out.truncated, retried=out.retried)
            return out

    async def _post(
        self, role: str, body: dict[str, Any], usage_sink: ParsedResult
    ) -> tuple[str, str, str | None]:
        """One request with bounded 429/5xx backoff. Returns `(content, finish_reason, failure)`.

        Both backends share this ladder — only the header set, the endpoint, the name in every
        failure string and the shape of a 200 differ, and each of those four is one branch.
        """
        headers = self._headers()
        delay = _BACKOFF_BASE_S
        for attempt in range(1, self._attempts + 1):
            last = attempt == self._attempts
            try:
                response = await self._client.post(self._url, json=body, headers=headers)
            except httpx.HTTPError as exc:  # transport-level: timeout, connect, read, protocol
                if last:
                    return "", "", (f"{self._label} transport error after {attempt} attempts: "
                                    f"{type(exc).__name__}{self._down_hint(exc)}")
                await self._backoff(role, delay, f"transport {type(exc).__name__}")
                delay = min(delay * 2, _BACKOFF_CEILING_S)
                continue
            status = response.status_code
            # FR-248 — latched once, never retried, whole-run condition. OPENROUTER ONLY: the
            # latched reason names OpenRouter credits, and a subscription call has none to run
            # out of, so a 402 from the proxy falls through to the ordinary error path below.
            if status == 402 and not self._codex:
                self._latch_credits_exhausted()
                return "", "", CREDITS_EXHAUSTED_REASON
            if status in _RETRY_STATUSES and not last:
                await self._backoff(role, _retry_after(response, delay), f"HTTP {status}")
                delay = min(delay * 2, _BACKOFF_CEILING_S)
                continue
            if status >= 400:
                # The body matters: a 404 here often means "unroutable parameter set", not
                # "unknown model" (RESULTS.md §E) — surfacing only the status hides the cause.
                return "", "", f"{self._label} HTTP {status}: {_error_message(response)}"
            try:
                data = response.json()
            except ValueError:
                return "", "", f"{self._label} returned a non-JSON body"
            if isinstance(data.get("error"), dict):  # 200 with an error envelope
                return "", "", f"{self._label} error: {data['error'].get('message', 'unknown')}"
            if self._codex:
                _absorb_codex_usage(data, usage_sink)
                return (*_codex_reply(data), None)
            _absorb_usage(data, usage_sink)
            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
            return content, str(choice.get("finish_reason") or ""), None
        return "", "", f"{self._label} retries exhausted ({self._attempts} attempts)"

    def _headers(self) -> dict[str, str]:
        """D30: the Authorization header exists ONLY on the metered path, and only in this dict."""
        if self._codex:
            return {"Content-Type": "application/json"}
        return {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}

    def _down_hint(self, exc: httpx.HTTPError) -> str:
        """"Nothing is listening on 10531" is the codex backend's single most likely failure.

        It reads as a bare `ConnectError` otherwise, which tells an operator nothing about the
        one command that fixes it. Only connect-shaped failures get the hint: a read timeout on
        a call that DID reach the proxy is a slow model, not a missing process.
        """
        if self._codex and isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            return f" - {_CODEX_DOWN_HINT}"
        return ""

    async def _backoff(self, role: str, delay: float, cause: str) -> None:
        self._warn("llm_retry", f"{role}: {cause}; retrying in {delay:.1f}s", role=role, delay_s=delay)
        await asyncio.sleep(delay)

    def _latch_credits_exhausted(self) -> None:
        if not self._credits_exhausted:
            self._credits_exhausted = True
            self._warn("llm_credits_exhausted", CREDITS_EXHAUSTED_REASON)

    def _apply_floor(self, role: str, settings: RoleSettings) -> RoleSettings:
        """NFR-111: clamp a per-role token limit UP to its floor, loudly, once per run.

        Since D64 it also clamps an `xhigh` effort DOWN to `high` on the openrouter backend, on
        the same principle and for a sharper reason: `xhigh` is a GPT-5.6-through-the-proxy value,
        OpenRouter does not list it, and an unknown enum there is a 400 on EVERY call of that role
        — a config edited for the codex door would otherwise take the whole run down the moment it
        was switched back. One loud warning, one working call, no silent config rewrite (the
        `RoleSettings` the runner built is the only thing changed, never the config file).
        """
        if settings.reasoning_effort == "xhigh" and not self._codex:
            self._warn(
                "llm_effort_clamped",
                f"{role}: reasoning effort 'xhigh' exists only on the codex backend; using 'high'",
                role=role, configured="xhigh", used="high", backend=self._backend,
            )
            settings.reasoning_effort = "high"
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


def _endpoint(backend: str, base_url: str) -> str:
    """The full POST target for a backend + configured root. Empty root means "the default".

    Kept out of `__init__` so a reader can see both doors' URLs in three lines, and so a test can
    assert the openrouter constant is untouched without constructing a client.
    """
    if backend == BACKEND_CODEX:
        return f"{(base_url or CODEX_DEFAULT_BASE_URL).rstrip('/')}{_CODEX_PATH}"
    return f"{base_url.rstrip('/')}{_OPENROUTER_PATH}" if base_url else OPENROUTER_URL


def _cap_key(body: dict[str, Any]) -> str:
    """Which key holds THIS body's output cap — the one FR-127's widened retry may raise.

    Read off the body rather than passed down from the backend flag: the body is the thing being
    mutated, so the ladder cannot drift from the request it is editing.
    """
    return "max_output_tokens" if "max_output_tokens" in body else "max_tokens"


def _append_nudge(body: dict[str, Any]) -> None:
    """FR-41's single formatting retry — one extra USER turn, in whichever list this body uses.

    The per-role SYSTEM prompt (chat `messages[0]`, codex `instructions`) is never touched on
    either backend: the retry asks again, it does not re-write the role.
    """
    if "input" in body:
        body["input"] = [*body["input"],
                         {"role": "user", "content": [{"type": "input_text", "text": _RETRY_NUDGE}]}]
        return
    body["messages"] = [*body["messages"], {"role": "user", "content": _RETRY_NUDGE}]


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
# The codex door — the `/responses` request shape, measured live 2026-08-21 (D64).
# --------------------------------------------------------------------------------------------

def _build_codex_body(
    settings: RoleSettings,
    messages: list[dict[str, Any]],
    images: Sequence[bytes] | None,
    json_schema: dict[str, Any],
) -> dict[str, Any]:
    """The same call `_build_body` describes, in the shape the local proxy accepts.

    Deliberately ABSENT, each for a reason: `provider` and `usage` are OpenRouter routing/billing
    fields the proxy does not know; `temperature` and `seed` are the FR-129 opt-ins whose whole
    justification (an OpenRouter `supported_parameters` list) does not exist here, so sending
    them would be a guess at a 400. `store: false` keeps the request out of the account's saved
    responses — this engine keeps its own transcript in `events.jsonl` (D30: nothing of ours
    should linger server-side).
    """
    instructions, turns = _codex_turns(messages)
    body: dict[str, Any] = {
        "model": settings.model,
        "input": _attach_codex_images(turns, images),
        "text": {"format": _codex_text_format(json_schema)},  # strict schema, same as FR-41's
        "max_output_tokens": settings.max_tokens,
        "store": False,
    }
    if instructions:
        body["instructions"] = instructions
    if settings.reasoning_effort:  # `xhigh` is legal on this backend and only on this backend
        body["reasoning"] = {"effort": settings.reasoning_effort}
    return body


def _codex_text_format(json_schema: dict[str, Any]) -> dict[str, Any]:
    """`/responses` flattens `{type, json_schema: {name, strict, schema}}` into one object.

    Built FROM `_response_format` rather than beside it so the schema-name sanitising and the
    bare-vs-wrapped input handling stay in ONE place — a second copy would drift the first time
    a caller passes a name with a space in it.
    """
    wrapper = _response_format(json_schema)["json_schema"]
    return {"type": "json_schema", **wrapper}


def _codex_turns(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Split chat messages into the two halves `/responses` wants: `instructions` and `input`.

    System (and `developer`) turns become the instructions block, joined by a blank line so two
    system messages read as two paragraphs and not one run-on sentence. Everything else keeps its
    role and becomes content PARTS, because parts are the only content form an image can join.
    """
    instructions: list[str] = []
    turns: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        if role in {"system", "developer"}:
            text = _codex_flat_text(message.get("content"))
            if text:
                instructions.append(text)
            continue
        part_type = "output_text" if role == "assistant" else "input_text"
        turns.append({"role": role, "content": _codex_parts(message.get("content"), part_type)})
    return "\n\n".join(instructions), turns


def _codex_flat_text(content: Any) -> str:
    """A system turn as one string, whether the caller passed a string or already-built parts."""
    if isinstance(content, str):
        return content
    return "\n".join(str(part.get("text") or "") for part in content or ()
                      if isinstance(part, dict) and part.get("text"))


def _codex_parts(content: Any, part_type: str) -> list[dict[str, Any]]:
    """One turn's content as `/responses` parts. A plain string is the overwhelmingly common case."""
    if isinstance(content, str):
        return [{"type": part_type, "text": content}]
    parts: list[dict[str, Any]] = []
    for part in content or ():
        if not isinstance(part, dict):
            continue
        if part.get("type") in {"text", "input_text", "output_text"}:
            parts.append({"type": part_type, "text": str(part.get("text") or "")})
        elif part.get("type") == "image_url":  # a caller that pre-built a CHAT image part
            url = part.get("image_url")
            url = url.get("url") if isinstance(url, dict) else url
            parts.append({"type": "input_image", "image_url": str(url or ""), "detail": _IMAGE_DETAIL})
    return parts


def _attach_codex_images(
    turns: list[dict[str, Any]], images: Sequence[bytes] | None
) -> list[dict[str, Any]]:
    """FR-40 again, in `/responses` clothing: base64 parts on the LAST user turn. No CDN URLs.

    Same rule as `_with_images` — same turn, same order, same "invent a user turn if there is
    none" tail — because the two backends must show a model the same conversation.
    """
    if not images:
        return turns
    parts = [{"type": "input_image", "image_url": _data_uri(blob), "detail": _IMAGE_DETAIL}
             for blob in images if blob]
    for turn in reversed(turns):
        if turn.get("role") == "user":
            turn["content"] = [*(turn.get("content") or ()), *parts]
            return turns
    turns.append({"role": "user", "content": parts})
    return turns


def _codex_reply(data: dict[str, Any]) -> tuple[str, str]:
    """`(text, finish_reason)` out of a `/responses` answer, mapped onto the chat vocabulary.

    The answer is a LIST of output items — a reasoning item first, then the message — so the text
    is every `output_text` part concatenated and a reasoning item contributes nothing. A cut-off
    answer arrives as `status: "incomplete"` with `incomplete_details.reason`; that maps to
    `"length"` for the token cap so `_TRUNCATED_REASONS` recognises it and FR-127's widened retry
    fires exactly as on the chat path. Any other incomplete reason passes through under its own
    name — it is NOT a truncation, and calling it one would spend the wrong retry.
    """
    chunks: list[str] = []
    for item in data.get("output") or ():
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or ():
            if isinstance(part, dict) and part.get("type") == "output_text":
                chunks.append(str(part.get("text") or ""))
    text = "".join(chunks)
    if str(data.get("status") or "") != "incomplete":
        return text, "stop"
    details = data.get("incomplete_details")
    reason = str((details or {}).get("reason") or "") if isinstance(details, dict) else ""
    return text, "length" if reason == "max_output_tokens" else (reason or "incomplete")


def _absorb_codex_usage(data: dict[str, Any], sink: ParsedResult) -> None:
    """`/responses` usage → the same three counters. No `cost`: the subscription is not metered.

    `cost_usd` is left at 0.0 ON PURPOSE, not because a field happened to be missing — under this
    backend the run's LLM spend is genuinely zero, and `budget._llm_call_price` prices the
    estimate to match so the Confirm gate and the run summary tell the same story.
    """
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return
    details = usage.get("output_tokens_details") or {}
    sink.prompt_tokens += int(usage.get("input_tokens") or 0)
    sink.completion_tokens += int(usage.get("output_tokens") or 0)
    sink.reasoning_tokens += int(details.get("reasoning_tokens") or 0)


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


__all__ = ["BACKEND_CODEX", "BACKEND_OPENROUTER", "CODEX_DEFAULT_BASE_URL",
           "CREDITS_EXHAUSTED_REASON", "LLMClient", "RoleSettings"]
