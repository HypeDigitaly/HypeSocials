"""Codex/ChatGPT subscription images — the SECOND implementation of the D34 render seam (D64).

Purpose: render GPT Image 2 through the operator's ChatGPT subscription instead of Kie.ai, by
speaking the OpenAI-compatible image API that `npx openai-oauth@latest` exposes on loopback
(`http://127.0.0.1:10531/v1`). Everything proxy-shaped — `/images/generations` vs `/images/edits`,
the `size` enum, `b64_json`, the `{"error": {...}}` envelope — stays in this file, exactly as
everything Kie-shaped stays in `kie.py`. Only `render/__init__.py` imports it.

Public API: `CodexImageClient.render()` · `.upload()` · `.aclose()` · `CodexUploadError`.

What this provider is NOT
-------------------------
There is no job queue behind the proxy: one POST blocks for the whole render (15-26 s measured on
2026-08-21) and comes back with the picture inline. So there is nothing to poll, no provider task
id and no per-job price. This client therefore MINTS its own `task_id` (`codex-<uuid>`) so the
FR-203 ledger, `meta.yaml` and every log line keep the same shape they have under Kie, and it
reports `cost_usd=0.0` because the subscription already paid.

Invariants:
- **Images only.** A Seedance/video body is a terminal FAIL (`provider_fail`), never an exception
  and never a silent image: the subscription has no video path (FR-44's "a video job is never
  resubmitted" is untouched — this one is never SUBMITTED).
- **No key, no header, no token file.** The proxy authenticates itself from `~/.codex/auth.json`;
  this module reads nothing from there and sends no `Authorization` header (D30/NFR-112).
- **The result is a local file, not a borrowed URL.** Bytes land under `<scratch_dir>/.renders/`
  by temp+rename and travel on as a `file://` URL, which `outputs.packager._download()` reads
  without a socket. Nothing here uploads anything anywhere.
- **`upload()` moves no bytes.** A reference is already a local file; the "public URL" this
  provider needs is that file's own `file://` URI. The FR-244 source-store gate (`source/` vs
  `marks/`) stays where it is, in `generate/refs.py`, and is NOT re-implemented here.
- Elapsed time is monotonic (`util.Stopwatch`, FR-243); a sleeping host cannot fake a stuck job.
- Money-shaped rules still bind even at $0: this client never resubmits (20 §8). A retry is the
  caller's, as a second `render()` call (FR-97's moderation retry, FR-317's single image resubmit).

Do not: send an API key; fetch a third-party URL to use as a reference; resubmit; raise for a
provider outcome; assume `size` is honoured (the proxy returned 1254x1254 px for every value
measured on 2026-08-21 — the request states the ratio anyway, so a fixed proxy is an improvement
rather than a change here).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import mimetypes
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import httpx

from hypesocials.models import RenderFailCause, RenderOutcome, RenderOutcomeKind
from hypesocials.render.kie import KieUploadError
from hypesocials.util import Stopwatch, atomic_write, now_iso

logger = logging.getLogger(__name__)

#: The proxy's own address. Loopback by contract: the OAuth token lives on this workstation and
#: the proxy must never be reachable from anywhere else (D30 posture, `config.models.llm_base_url`).
DEFAULT_BASE_URL = "http://127.0.0.1:10531/v1"
#: The ONE model id this provider ever sends. The configured Kie route names
#: (`gpt-image-2-text-to-image` / `-image-to-image`) stay in config untouched and are ignored here:
#: the OpenAI-shaped API picks the route by ENDPOINT (generations vs edits), not by model name.
CODEX_IMAGE_MODEL = "gpt-image-2"
GENERATIONS_PATH = "/images/generations"
EDITS_PATH = "/images/edits"
#: Where a finished render lands inside the run folder. Dot-prefixed so the gallery's slide globs
#: and the operator's eye both skip it — these are working bytes, not a packaged asset.
RENDERS_DIR = ".renders"

_SQUARE = "1024x1024"
_PORTRAIT = "1024x1536"
_LANDSCAPE = "1536x1024"
#: Engine aspect ratio -> the nearest STANDARD OpenAI size. The proxy measured on 2026-08-21
#: returns 1254x1254 whatever is asked, but a request that states the shape it wants is the one
#: that comes out right the day the proxy starts honouring it.
_SIZE_BY_RATIO: dict[str, str] = {
    "": _SQUARE, "auto": _SQUARE, "1:1": _SQUARE,
    "4:5": _PORTRAIT, "9:16": _PORTRAIT, "2:3": _PORTRAIT, "3:4": _PORTRAIT,
    "16:9": _LANDSCAPE, "3:2": _LANDSCAPE, "4:3": _LANDSCAPE, "5:4": _LANDSCAPE,
}
_MAX_REFERENCE_IMAGES = 16  # gpt-image-2's documented ceiling; the profile caps first (FR-272)

_REQUEST_TIMEOUT_S = 300.0  # client default only — every call passes the job's own remaining time
_CONNECT_TIMEOUT_S = 10.0
_BACKOFF_BASE_S = 1.5
_MAX_BACKOFF_S = 30.0

#: Keys only a video body carries (`profiles._build_seedance_2_5`). Read off the BODY rather than
#: the route name because the route name is config-supplied and this client ignores it by design.
_VIDEO_KEYS = frozenset({
    "duration", "generate_audio", "nsfw_checker", "output_format",
    "reference_image_urls", "reference_video_urls",
})
VIDEO_REFUSAL = "codex provider renders images only (no subscription path for video)"
PROXY_DOWN = "Codex proxy unreachable — is `npx openai-oauth@latest` running?"

#: OpenAI states a refusal in prose, so this is a substring test like Kie's. MODERATION is its own
#: cause because its remedy differs: FR-97 retries once with the offending references stripped.
_MODERATION_SIGNS = (
    "moderation", "safety", "content_policy", "content policy", "policy violation",
    "not allowed", "violat", "rejected",
)


class CodexRenderError(RuntimeError):
    """A proxy-side failure, already carrying the seam's own fail cause.

    Internal to this module: `render()` turns every one of these into a terminal `RenderOutcome`,
    so nothing of this shape escapes to a caller.
    """

    def __init__(self, message: str, cause: RenderFailCause = RenderFailCause.PROVIDER_FAIL) -> None:
        super().__init__(message)
        self.cause = cause


class CodexUploadError(KieUploadError):
    """One file could not become a reference URL (FR-244/163) — that reference only.

    A subclass of `KieUploadError` on purpose: `generate/refs.py` and every other caller already
    treat that type as "drop this one reference and carry on", and a provider swap must not make
    them learn a second name for the same event.
    """


class CodexImageClient:
    """One `httpx.AsyncClient` against the local proxy, with the same surface as `KieClient`.

    Owned by `render/__init__.py` — `render()`, `upload()` and `aclose()` are called from exactly
    the same three places, so nothing outside the package can tell which provider is bound.
    """

    __slots__ = ("_attempts", "_base_url", "_http", "_log", "_owns_http", "_scratch_dir",
                 "_tier_noted")

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        http_max_attempts: int = 3,
        scratch_dir: Path | str | None = None,
        log: Any = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        # NO `headers=` argument, and that is deliberate: there is no key to send, and an
        # Authorization header invented here would be the one secret this path could leak (D30).
        self._http = client or httpx.AsyncClient(
            timeout=httpx.Timeout(_REQUEST_TIMEOUT_S, connect=_CONNECT_TIMEOUT_S))
        self._owns_http = client is None  # an injected client belongs to its injector (tests)
        self._attempts = max(1, int(http_max_attempts))
        # Resolved at construction: the runner hands over `output/<run>` RELATIVE to the cwd, and
        # `Path.as_uri()` refuses a relative path (canary 20260821_112153_t91p died on exactly
        # that ValueError at the first landed render). Absolute here, once, keeps every
        # `file://` URL this client mints valid wherever it is later read.
        self._scratch_dir = Path(scratch_dir).resolve() if scratch_dir else None
        # The run's `outputs.LogWriter`, bound by `render.configure()`. Absent in tests, so every
        # call site goes through `_event`, never through the attribute (FR-77).
        self._log = log
        self._tier_noted = False

    @property
    def renders_dir(self) -> Path:
        """Where this run's finished renders land. Public so tests and the runner never guess it."""
        if self._scratch_dir is not None:
            return self._scratch_dir / RENDERS_DIR
        return Path(tempfile.gettempdir()) / "hypesocials_renders"

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # ----------------------------------------------------------------- seam ops 1-3
    async def render(
        self,
        model: str,
        body: dict[str, Any],
        *,
        timeout_s: float,
        on_intent: Any = None,
        on_submitted: Any = None,
    ) -> RenderOutcome:
        """Submit → wait → classify one image, and return its terminal `RenderOutcome`.

        `model` is the configured Kie route name and is recorded, never sent (see
        `CODEX_IMAGE_MODEL`). `body` is `profiles._build_gpt_image_2`'s object: `prompt`,
        optional `input_urls`, `aspect_ratio`, `resolution`. `on_intent` / `on_submitted` are the
        FR-203 ledger hooks, called synchronously in the caller's task exactly as Kie calls them —
        intent BEFORE the request, `on_submitted(token, None)` when the answer is lost.
        """
        token = uuid.uuid4().hex
        watch = Stopwatch()
        submitted_at = now_iso()
        if on_intent is not None:
            on_intent(token)
        if _is_video(body):
            # Never an exception: a video creative under this provider is a job that failed for a
            # stated reason, so the deck/reel around it degrades the way every other FAIL does.
            if on_submitted is not None:
                on_submitted(token, None)
            return self._finish(
                RenderOutcome(kind=RenderOutcomeKind.FAIL, request_token=token,
                              fail_cause=RenderFailCause.PROVIDER_FAIL,
                              fail_message=VIDEO_REFUSAL),
                model, submitted_at, watch)
        size = _size_for(str(body.get("aspect_ratio") or ""))
        self._note_resolution(body.get("resolution"))
        references = await self._reference_blobs(body)
        endpoint = EDITS_PATH if references else GENERATIONS_PATH
        # FR-155/NFR-5: what this job attached, on the line that says it went out. Named by FILE
        # here rather than by host, because under this provider a reference never leaves the disk.
        self._event(
            "codex_job_submitted",
            f"Codex proxy asked for {CODEX_IMAGE_MODEL} at {size} with "
            f"{len(references)} reference(s)",
            endpoint=f"{self._base_url}{endpoint}", model=CODEX_IMAGE_MODEL, route=model,
            request_token=token, size=size, timeout_s=round(timeout_s),
            reference_count=len(references),
            reference_sources=[f"local file: {name}" for name, _ in references])
        try:
            payload = await self._post_image(
                prompt=str(body.get("prompt") or ""), size=size, references=references,
                timeout_s=timeout_s, watch=watch)
            blob = _first_image(payload)
            task_id = f"codex-{uuid.uuid4().hex}"
            url = self._store(task_id, blob)
        except CodexRenderError as exc:
            if on_submitted is not None:
                on_submitted(token, None)  # no id was ever minted -> `submit_unknown`
            logger.warning("Codex render failed for %s: %s", model, exc)
            stuck = exc.cause is RenderFailCause.TIMEOUT
            return self._finish(
                RenderOutcome(
                    kind=RenderOutcomeKind.STUCK if stuck else RenderOutcomeKind.FAIL,
                    request_token=token, fail_cause=exc.cause, fail_message=str(exc)),
                model, submitted_at, watch)
        if on_submitted is not None:
            on_submitted(token, task_id)
        logger.info("Codex render done: task=%s bytes=%d elapsed=%.1fs",
                    task_id, len(blob), watch.elapsed_s)
        return self._finish(
            RenderOutcome(kind=RenderOutcomeKind.SUCCESS, task_id=task_id, request_token=token,
                          result_urls=[url], cost_usd=0.0),
            model, submitted_at, watch, **_usage(payload))

    # ----------------------------------------------------------------- seam op 4
    async def upload(self, path: str | Path) -> str:
        """A local file's reference URL — its own `file://` URI. NO network call (FR-244).

        The subscription proxy reads reference bytes out of the multipart request body, so there
        is no host to upload to and no 24 h retention to respect. The one thing that can fail is
        the file not being there, and that is `CodexUploadError`: one dropped reference, never a
        dropped job.
        """
        source = Path(path)
        if not source.is_file():
            raise CodexUploadError(f"upload source is not a file: {source}")
        url = source.resolve().as_uri()
        logger.info("Codex reference registered: file=%s", source.name)
        return url

    # ----------------------------------------------------------------- request building
    async def _reference_blobs(self, body: dict[str, Any]) -> list[tuple[str, bytes]]:
        """`input_urls` → `(file name, bytes)` in the order the provider will read them.

        Order is load-bearing (FR-95/24): the chained artifact — a carousel anchor, a reel seed
        frame — leads the list and must stay first. A URL that is not `file://` is DROPPED with a
        warned line rather than fetched: this client pulls nothing off the network, which is what
        keeps a Virlo CDN URL from becoming a render reference by accident (D41/D46).
        """
        urls = [url for url in body.get("input_urls") or [] if isinstance(url, str)]
        kept: list[tuple[str, bytes]] = []
        for url in urls[:_MAX_REFERENCE_IMAGES]:
            local = _local_path(url)
            if local is None:
                self._event("codex_reference_dropped",
                            f"reference {url[:120]} is not a local file; the codex provider "
                            "fetches nothing over the network, so it was left out",
                            level="warn", reference=url[:200])
                continue
            try:
                blob = await asyncio.to_thread(local.read_bytes)
            except OSError as exc:
                self._event("codex_reference_dropped",
                            f"reference {local.name} could not be read ({exc}); the job proceeds "
                            "with its remaining references",
                            level="warn", reference=local.name)
                continue
            if blob:
                kept.append((local.name, blob))
        return kept

    async def _post_image(
        self, *, prompt: str, size: str, references: list[tuple[str, bytes]],
        timeout_s: float, watch: Stopwatch,
    ) -> dict[str, Any]:
        """One POST: `/images/edits` when references travel, `/images/generations` when not."""
        if references:
            files = [("image[]", (name, blob, _content_type(name))) for name, blob in references]
            return await self._request(
                EDITS_PATH, timeout_s=timeout_s, watch=watch, files=files,
                data={"prompt": prompt, "model": CODEX_IMAGE_MODEL, "size": size, "n": "1"})
        return await self._request(
            GENERATIONS_PATH, timeout_s=timeout_s, watch=watch,
            json={"model": CODEX_IMAGE_MODEL, "prompt": prompt, "size": size, "n": 1})

    async def _request(
        self, path: str, *, timeout_s: float, watch: Stopwatch, **kwargs: Any,
    ) -> dict[str, Any]:
        """One bounded-retry call: 429/5xx and transport errors retried, everything else classified.

        The job timeout is the outer bound on ALL of it — attempts, backoff and the read wait —
        because there is no separate queue here for the job to sit in: the request IS the job.
        """
        url = f"{self._base_url}{path}"
        attempt = 0
        while True:
            attempt += 1
            remaining = timeout_s - watch.elapsed_s
            if remaining <= 0:
                raise CodexRenderError(f"no image within {timeout_s:.0f}s", RenderFailCause.TIMEOUT)
            try:
                response = await self._http.post(
                    url, timeout=httpx.Timeout(remaining, connect=min(_CONNECT_TIMEOUT_S, remaining)),
                    **kwargs)
            except httpx.TimeoutException as exc:
                # The caller's FR-317 single resubmit is what answers this, exactly as it answers
                # a Kie job that never left `waiting`.
                raise CodexRenderError(
                    f"no image within {timeout_s:.0f}s ({type(exc).__name__})",
                    RenderFailCause.TIMEOUT) from exc
            except httpx.HTTPError as exc:
                if attempt >= self._attempts:
                    raise CodexRenderError(f"{PROXY_DOWN} ({type(exc).__name__})") from exc
                await self._backoff(attempt, None, remaining)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= self._attempts:
                    raise CodexRenderError(f"POST {path} HTTP {response.status_code}")
                await self._backoff(attempt, response, remaining)
                continue
            if response.status_code >= 400:
                message = _error_message(response)
                raise CodexRenderError(f"POST {path} HTTP {response.status_code}: {message}",
                                       _fail_cause(message))
            try:
                payload = response.json()
            except ValueError as exc:
                raise CodexRenderError(f"{path} returned non-JSON: {_snippet(response)}") from exc
            return payload if isinstance(payload, dict) else {}

    async def _backoff(self, attempt: int, response: httpx.Response | None, remaining: float) -> None:
        """Exponential backoff, honouring `Retry-After`, never sleeping past the job's own time."""
        delay = _BACKOFF_BASE_S * (2 ** (attempt - 1))
        if response is not None:
            try:
                delay = max(delay, float(response.headers.get("retry-after", 0)))
            except ValueError:
                pass
        await asyncio.sleep(max(0.0, min(delay, _MAX_BACKOFF_S, remaining)))

    # ----------------------------------------------------------------- result bytes
    def _store(self, task_id: str, blob: bytes) -> str:
        """Write the render under `<scratch_dir>/.renders/` atomically and return its `file://` URL.

        Atomic for the same reason `meta.yaml` is (NFR-21): the packager copies these bytes into
        the asset folder afterwards, and a torn file would be a half-slide nobody could tell from
        a whole one.
        """
        target = self.renders_dir / f"{task_id}.png"
        try:
            atomic_write(target, blob)
        except OSError as exc:
            raise CodexRenderError(f"render could not be written to {target.parent}: {exc}") from exc
        return target.resolve().as_uri()

    # ----------------------------------------------------------------- run-log events (FR-77)
    def _note_resolution(self, resolution: Any) -> None:
        """Say ONCE per run that the tier the config asked for is not a tier this proxy has.

        FR-342 lets a platform pin `2k`, and the estimator prices what it pinned. This provider
        renders at whatever the proxy returns (1254 px square, measured 2026-08-21) and cannot be
        asked for more, so the honest thing is to say so — once, not once per slide.
        """
        tier = str(resolution or "").strip()
        if self._tier_noted or not tier:
            return
        self._tier_noted = True
        self._event("codex_resolution_fixed",
                    f"codex renders at the proxy's fixed size; tier {tier} requested and ignored",
                    level="warn", requested_resolution=tier)

    def _event(self, event_type: str, message: str, **data: Any) -> None:
        """One provider line into the run's OWN logs — the stdlib logger reaches no operator.

        The request body never travels here: it carries the assembled prompt, and 40 §4 keeps
        prompt-sized payloads in events.jsonl, never in run.log.
        """
        if self._log is not None:
            self._log.event(event_type, message, **data)

    def _finish(
        self, outcome: RenderOutcome, model: str, submitted_at: str, watch: Stopwatch, **data: Any,
    ) -> RenderOutcome:
        """Stamp the timings on a terminal outcome and narrate it — the one exit for `render()`."""
        outcome.submitted_at, outcome.completed_at = submitted_at, now_iso()
        outcome.elapsed_s = watch.elapsed_s
        cause = outcome.fail_cause.value if outcome.fail_cause else ""
        self._event(
            "codex_job_result",
            f"Codex {model} task {outcome.task_id or '-'}: {outcome.kind.value}"
            + (f" ({cause})" if cause else ""),
            level="error" if outcome.kind is not RenderOutcomeKind.SUCCESS else "info",
            model=model, task_id=outcome.task_id, kind=outcome.kind.value, cause=cause,
            duration_ms=int(outcome.elapsed_s * 1000), cost_usd=outcome.cost_usd, **data)
        return outcome


def _is_video(body: dict[str, Any]) -> bool:
    """Is this a Seedance body? Answered from the KEYS the video profile builds, never a name."""
    return bool(_VIDEO_KEYS & set(body))


def _size_for(aspect_ratio: str) -> str:
    """Engine aspect ratio → the standard OpenAI `size`. An unknown ratio renders square."""
    return _SIZE_BY_RATIO.get(aspect_ratio.strip().lower(), _SQUARE)


def _local_path(url: str) -> Path | None:
    """A `file://` URL as a real path, or `None` for anything this client will not read.

    Percent-escapes and UNC hosts are handled by `url2pathname`, which is why the parsing is not
    a `startswith` and a slice: `file:///C:/a%20b/x.png` is a path with a space in it.
    """
    parts = urlparse(str(url))
    if parts.scheme != "file":
        return None
    raw = f"//{parts.netloc}{parts.path}" if parts.netloc else parts.path
    try:
        return Path(url2pathname(raw))
    except (OSError, ValueError):
        return None


def _content_type(name: str) -> str:
    guessed, _ = mimetypes.guess_type(name)
    return guessed if (guessed or "").startswith("image/") else "image/png"


def _first_image(payload: dict[str, Any]) -> bytes:
    """`data[0].b64_json` decoded, or `EMPTY_RESULT_URLS` — a 200 with nothing in it is a failure.

    The same rule as FR-242's on the Kie side: a green status is not a picture. There is no URL to
    reach for here, so "unreachable" collapses into "empty" and the caller sees one cause.
    """
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise CodexRenderError("proxy returned no image data", RenderFailCause.EMPTY_RESULT_URLS)
    entry = data[0] if isinstance(data[0], dict) else {}
    raw = entry.get("b64_json")
    if not isinstance(raw, str) or not raw:
        raise CodexRenderError("proxy returned an image entry with no b64_json",
                               RenderFailCause.EMPTY_RESULT_URLS)
    try:
        blob = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CodexRenderError("proxy returned undecodable b64_json",
                               RenderFailCause.EMPTY_RESULT_URLS) from exc
    if not blob:
        raise CodexRenderError("proxy returned a zero-byte image",
                               RenderFailCause.EMPTY_RESULT_URLS)
    return blob


def _usage(payload: dict[str, Any]) -> dict[str, Any]:
    """The proxy's token counts, for the result line. Absent on some answers, so never required."""
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return {}
    return {key: usage[key] for key in ("input_tokens", "output_tokens", "total_tokens")
            if isinstance(usage.get(key), int)}


def _fail_cause(message: str) -> RenderFailCause:
    """Moderation is its own class because its remedy differs (FR-97's single stripped retry)."""
    lowered = message.lower()
    return (RenderFailCause.MODERATION if any(sign in lowered for sign in _MODERATION_SIGNS)
            else RenderFailCause.PROVIDER_FAIL)


def _error_message(response: httpx.Response) -> str:
    """`{"error": {"message": ...}}` unwrapped, falling back to the raw body."""
    try:
        payload = response.json()
    except ValueError:
        return _snippet(response)
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or "").strip() or _snippet(response)
    if isinstance(error, str) and error.strip():
        return error.strip()
    return _snippet(response)


def _snippet(response: httpx.Response) -> str:
    return response.text[:200].replace("\n", " ")


__all__ = ["CODEX_IMAGE_MODEL", "DEFAULT_BASE_URL", "CodexImageClient", "CodexRenderError",
           "CodexUploadError", "PROXY_DOWN", "RENDERS_DIR", "VIDEO_REFUSAL"]
