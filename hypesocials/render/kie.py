"""Kie.ai — the one implementation of the four-operation render-provider seam (FR-271).

Purpose: own everything Kie-shaped (`createTask`, `recordInfo`, the five poll states, the
`resultJson` string, `failCode`/`failMsg`, `creditsConsumed`, the upload host, HTTP 402/429) and
hand back only a classified `RenderOutcome` or a public URL. Only `render/__init__.py` imports it.
Public API: `KieClient.render()` · `.upload()` · `.aclose()` · `KieError` / `KieOutOfCredits` /
`KieUploadError`.
Invariants:
- Non-terminal states (`waiting`/`queuing`/`generating`) are one thing — pending — and nothing
  branches on which: Seedance never left `waiting` across a 379 s render (RESULTS.md §C).
- A failed *poll* is never a failed *job* (20 §8): one try per tick, retried with backoff,
  bounded only by the job timeout. `http_max_attempts` governs `createTask` and uploads.
- A timed-out job is a failed job, NEVER resubmitted — it was billed and its `taskId` goes to the
  caller for the ledger (FR-203).
- `state: success` is not success: `resultJson.resultUrls` must exist AND be downloadable, else
  FAIL with `empty_result_urls` / `result_url_unreachable` (FR-242).
- Elapsed time is monotonic via `util.Stopwatch` (FR-243); a sleeping host cannot fake a stuck job.
- The API key reaches one place, the `Authorization` header of the API host — never a log, an
  error message, or a third-party CDN (D30/NFR-112).
Do not: set `callBackUrl` (no public endpoint on a workstation, 20 §8); resubmit anything; retry
a 402; leak a provider string except through `RenderOutcome.fail_message`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import httpx

from hypesocials.models import RenderFailCause, RenderOutcome, RenderOutcomeKind
from hypesocials.util import Stopwatch, now_iso

logger = logging.getLogger(__name__)

JOBS_BASE = "https://api.kie.ai/api/v1/jobs"
#: The upload API lives on a DIFFERENT host from the job API, and the public URL it returns is on
#: a third one — always read `data.downloadUrl`, never construct it (RESULTS.md §D).
UPLOAD_URL = "https://kieai.redpandaai.co/api/file-stream-upload"

_TERMINAL_STATES = frozenset({"success", "fail"})
_WIDEN_AFTER_S = 60.0  # 20 §8: a job pending this long polls slower from then on
_WIDE_POLL_INTERVAL_S = 10.0
_MAX_POLL_BACKOFF_S = 30.0
_REQUEST_TIMEOUT_S = 60.0
_UPLOAD_TIMEOUT_S = 300.0  # a 200 MB reference video is a legitimate upload
_URL_CHECK_TIMEOUT_S = 20.0
_BACKOFF_BASE_S = 1.5

#: Kie's content-security/copyright audit refusal — `RenderFailCause.CONTENT_AUDIT`, a class of
#: its own because its remedy differs from a moderation refusal (silence the clip, do not strip
#: the references). RESULTS.md §C.5.
_AUDIT_SIGNS = ("content security audit", "security audit", "copyright")
_MODERATION_SIGNS = (
    "moderation", "content policy", "policy violation", "safety", "nsfw",
    "prohibited", "sensitive", "violat", "blocked",
)


class KieError(RuntimeError):
    """Any Kie-side failure; the message is provider text, already safe to log (no secrets)."""


class KieOutOfCredits(KieError):
    """HTTP 402 — a whole-run condition (FR-167). No retry can fix it; stop submitting."""


class KieUploadError(KieError):
    """One file could not be turned into a public URL (FR-244/163) — that reference only."""


class KieClient:
    """One `httpx.AsyncClient` and the job lifecycle built on it. Owned by `render/__init__`."""

    __slots__ = ("_attempts", "_credit_usd", "_http", "_log", "_poll_interval_s", "_probe",
                 "_upload_path")

    def __init__(
        self,
        *,
        api_key: str,
        http_max_attempts: int = 3,
        poll_interval_s: float = 3.0,
        upload_path: str = "hypesocials",
        credit_usd: float = 0.005,
        log: Any = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(_REQUEST_TIMEOUT_S, connect=15.0),
        )
        # Result URLs live on CDN hosts that are NOT the API host, so they are fetched by a
        # second, keyless client — an FR-242 reachability check must never ship the bearer token
        # to a third party (D30/NFR-112). A floor under the poll interval keeps a misconfigured
        # tiny value from hammering `recordInfo`.
        self._probe = httpx.AsyncClient(timeout=httpx.Timeout(_URL_CHECK_TIMEOUT_S, connect=10.0))
        self._attempts = max(1, int(http_max_attempts))
        self._poll_interval_s = max(0.5, float(poll_interval_s))
        self._upload_path = upload_path.strip("/") or "hypesocials"
        self._credit_usd = float(credit_usd)
        # The run's `outputs.LogWriter`, bound by `render.configure()`. Absent in tests and in the
        # spikes, so every call site goes through `_event`, never through the attribute (FR-77).
        self._log = log

    async def aclose(self) -> None:
        await self._http.aclose()
        await self._probe.aclose()

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
        """Submit → poll → classify one job, and return its terminal `RenderOutcome`.

        Seam ops 1-3 are one call: no caller has a reason to hold a bare job handle. `on_intent`
        / `on_submitted` are the FR-203 ledger hooks, called synchronously in the caller's task.
        """
        token = secrets.token_hex(6)
        watch = Stopwatch()
        submitted_at = now_iso()
        if on_intent is not None:
            on_intent(token)  # intent BEFORE the call: money may move the instant after (FR-203)
        try:
            task_id = await self._create_task(model, body)
        except KieOutOfCredits:
            if on_submitted is not None:
                on_submitted(token, None)
            raise
        except KieError as exc:
            if on_submitted is not None:
                on_submitted(token, None)  # response lost or refused -> `submit_unknown`
            logger.warning("Kie createTask failed for model %s: %s", model, exc)
            outcome = RenderOutcome(
                kind=RenderOutcomeKind.FAIL, request_token=token,
                fail_cause=RenderFailCause.PROVIDER_FAIL, fail_message=str(exc),
                submitted_at=submitted_at, completed_at=now_iso(), elapsed_s=watch.elapsed_s,
            )
            self._result_event(outcome, model)
            return outcome
        if on_submitted is not None:
            on_submitted(token, task_id)
        logger.info("Kie job submitted: task=%s model=%s timeout=%.0fs", task_id, model, timeout_s)
        # FR-155/NFR-5: what this job ATTACHED, on the line that says it was accepted. Until
        # 2026-08-11 this event carried no reference count at all, so no creative's provenance was
        # reconstructable from the logs — the plain reading of NFR-5, violated on every run.
        references = _reference_urls(body)
        self._event("kie_job_submitted",
                    f"Kie accepted {model} as task {task_id} with {len(references)} reference(s)",
                    endpoint=f"{JOBS_BASE}/createTask", model=model, task_id=task_id,
                    timeout_s=round(timeout_s), reference_count=len(references),
                    reference_sources=[_reference_source(url) for url in references])
        record = await self._poll(task_id, timeout_s=timeout_s, watch=watch)
        timings: dict[str, int] = {}
        outcome = await self._classify(
            record, task_id=task_id, token=token, timeout_s=timeout_s, timings=timings)
        outcome.submitted_at, outcome.completed_at = submitted_at, now_iso()
        outcome.elapsed_s = watch.elapsed_s
        logger.info(
            "Kie job terminal: task=%s kind=%s cause=%s elapsed=%.1fs cost=$%.4f",
            task_id, outcome.kind.value, outcome.fail_cause.value if outcome.fail_cause else "-",
            outcome.elapsed_s, outcome.cost_usd,
        )
        self._result_event(outcome, model, **timings)
        return outcome

    async def _create_task(self, model: str, body: dict[str, Any]) -> str:
        """`POST /jobs/createTask` — `callBackUrl` deliberately never set (20 §8)."""
        data = await self._request_json("POST", f"{JOBS_BASE}/createTask", json={"model": model, "input": body})
        task_id = str(data.get("taskId") or "")
        if not task_id:
            raise KieError("createTask returned no taskId")
        return task_id

    async def _poll(self, task_id: str, *, timeout_s: float, watch: Stopwatch) -> dict[str, Any]:
        """Polls until terminal or the job timeout; `{}` means stuck (no terminal state in time)."""
        interval = self._poll_interval_s
        while True:
            remaining = timeout_s - watch.elapsed_s
            if remaining <= 0:
                logger.warning("Kie job stuck: task=%s exceeded %.0fs", task_id, timeout_s)
                return {}
            await asyncio.sleep(min(interval, remaining))
            try:
                # attempts=1: `http_max_attempts` governs createTask and uploads only (20 §8).
                # A poll gets one try per tick, and the tick loop is the retry — bounded by the
                # job timeout alone, so a long outage delays results instead of discarding them.
                record = await self._request_json(
                    "GET", f"{JOBS_BASE}/recordInfo", attempts=1, params={"taskId": task_id}
                )
            except KieOutOfCredits:
                raise
            except KieError as exc:
                # 20 §8: a failed poll is never a failed job — a router reboot must not discard
                # paid work that is finished and waiting at Kie.
                logger.warning("Kie poll error (not terminal): task=%s %s", task_id, exc)
                interval = min(max(interval, self._poll_interval_s) * 2, _MAX_POLL_BACKOFF_S)
                continue
            state = str(record.get("state") or "")
            # The noisiest event a run emits: events.jsonl keeps every tick, run.log only when
            # the operator asked for `verbosity: verbose` (40 §4).
            self._event("kie_job_polled", f"task {task_id} is {state or 'unknown'}",
                        verbose_only=True, task_id=task_id, state=state,
                        elapsed_s=round(watch.elapsed_s, 1))
            if state in _TERMINAL_STATES:
                return record
            interval = _WIDE_POLL_INTERVAL_S if watch.elapsed_s >= _WIDEN_AFTER_S else self._poll_interval_s

    async def _classify(
        self, record: dict[str, Any], *, task_id: str, token: str, timeout_s: float,
        timings: dict[str, int],
    ) -> RenderOutcome:
        """FR-242's three outcomes. A green status with nothing behind it is a failure.

        `timings` is filled with `download_ms` when the FR-242 reachability check actually runs —
        it is the caller's terminal log line that needs it, and only this method can measure it.
        """
        outcome = RenderOutcome(
            kind=RenderOutcomeKind.FAIL, task_id=task_id, request_token=token,
            cost_usd=self._cost_usd(record),
        )
        if not record:  # timed out: failed for the plan, never resubmitted (20 §8)
            outcome.kind = RenderOutcomeKind.STUCK
            outcome.fail_cause = RenderFailCause.TIMEOUT
            outcome.fail_message = f"no terminal state within {timeout_s:.0f}s"
            return outcome
        if record.get("state") == "fail":
            message = str(record.get("failMsg") or f"failCode {record.get('failCode')}")
            outcome.fail_cause, outcome.fail_message = _fail_cause(message)
            return outcome
        urls = _result_urls(record)
        if not urls:
            outcome.fail_cause = RenderFailCause.EMPTY_RESULT_URLS
            outcome.fail_message = "state success with no usable resultUrls"
            return outcome
        check = Stopwatch()
        unreachable = await self._first_unreachable(urls)
        timings["download_ms"] = check.elapsed_ms
        if unreachable:
            outcome.fail_cause = RenderFailCause.RESULT_URL_UNREACHABLE
            outcome.fail_message = unreachable
            return outcome
        outcome.kind, outcome.result_urls = RenderOutcomeKind.SUCCESS, urls
        return outcome

    # ----------------------------------------------------------------- seam op 4
    async def upload(self, path: str | Path) -> str:
        """Local bytes → public URL (20 §8b, FR-244/162). Treat the URL as same-run-only."""
        source = Path(path)
        if not source.is_file():
            raise KieUploadError(f"upload source is not a file: {source}")
        blob = await asyncio.to_thread(source.read_bytes)  # up to 200 MB — never on the loop
        try:
            data = await self._request_json(
                "POST", UPLOAD_URL,
                files={"file": (source.name, blob)},
                data={"uploadPath": self._upload_path, "fileName": source.name},
                timeout=_UPLOAD_TIMEOUT_S,
            )
        except KieOutOfCredits:
            raise
        except KieError as exc:
            raise KieUploadError(f"upload of {source.name} failed: {exc}") from exc
        url = str(data.get("downloadUrl") or "")
        if not url:
            raise KieUploadError(f"upload of {source.name} returned no downloadUrl")
        logger.info("Kie upload ok: file=%s bytes=%d", source.name, len(blob))
        return url

    # ----------------------------------------------------------------- HTTP plumbing
    async def _request_json(self, method: str, url: str, attempts: int = 0, **kwargs: Any) -> dict[str, Any]:
        """One bounded-retry JSON call: 429/5xx/transport retried, 402 raised, body unwrapped.

        `attempts` defaults to `http_max_attempts` (createTask, upload — FR-42/244); polls pass 1
        because their retry is the poll tick itself.
        """
        budget = attempts or self._attempts
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._http.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                if attempt >= budget:
                    raise KieError(f"{method} {_endpoint(url)} failed: {exc!r}") from exc
                await self._backoff(attempt, None)
                continue
            if response.status_code == 402:
                raise KieOutOfCredits("Kie.ai reports insufficient balance — top up Kie credits")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= budget:
                    raise KieError(f"{method} {_endpoint(url)} HTTP {response.status_code}")
                await self._backoff(attempt, response)
                continue
            if response.status_code >= 400:
                raise KieError(f"{method} {_endpoint(url)} HTTP {response.status_code}: {_snippet(response)}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise KieError(f"{_endpoint(url)} returned non-JSON: {_snippet(response)}") from exc
            code = payload.get("code")
            if code is not None and int(code) != 200:
                raise KieError(f"{_endpoint(url)} code {code}: {payload.get('msg')}")
            data = payload.get("data")
            return data if isinstance(data, dict) else {}

    async def _backoff(self, attempt: int, response: httpx.Response | None) -> None:
        """Exponential backoff, honoring `Retry-After` when the provider states one."""
        delay = _BACKOFF_BASE_S * (2 ** (attempt - 1))
        if response is not None:
            try:
                delay = max(delay, float(response.headers.get("retry-after", 0)))
            except ValueError:
                pass
        await asyncio.sleep(min(delay, _MAX_POLL_BACKOFF_S))

    async def _first_unreachable(self, urls: list[str]) -> str:
        """FR-242's download check. Returns a reason for the first bad URL, or `''` if all pass."""
        for url in urls:
            try:
                response = await self._probe.head(url, follow_redirects=True)
                if response.status_code in (403, 405, 501):  # HEAD refused; prove it with one byte
                    response = await self._probe.get(
                        url, follow_redirects=True, headers={"Range": "bytes=0-0"}
                    )
            except httpx.HTTPError as exc:
                return f"result url unreachable ({exc!r})"
            if response.status_code >= 400:
                return f"result url returned HTTP {response.status_code}"
            if response.headers.get("content-length") == "0":
                return "result url returned a zero-byte body"
        return ""

    # ----------------------------------------------------------------- run-log events (FR-77)
    def _event(self, event_type: str, message: str, **data: Any) -> None:
        """One Kie call line into the run's OWN logs — the stdlib logger reaches no operator.

        The request body never travels here: it carries the assembled prompt, and 40 §4 keeps
        prompt-sized payloads in events.jsonl, never in run.log.
        """
        if self._log is not None:
            self._log.event(event_type, message, **data)

    def _result_event(self, outcome: RenderOutcome, model: str, **data: Any) -> None:
        """The terminal line for one job: what it cost, how long it took, why it failed."""
        cause = outcome.fail_cause.value if outcome.fail_cause else ""
        self._event(
            "kie_job_result",
            f"Kie {model} task {outcome.task_id or '-'}: {outcome.kind.value}"
            + (f" ({cause})" if cause else ""),
            level="error" if outcome.kind is not RenderOutcomeKind.SUCCESS else "info",
            model=model, task_id=outcome.task_id, kind=outcome.kind.value, cause=cause,
            duration_ms=int(outcome.elapsed_s * 1000), cost_usd=outcome.cost_usd, **data)

    def _cost_usd(self, record: dict[str, Any]) -> float:
        """`data.creditsConsumed` is the reconcile-to-actual figure — 0.0 on a failed job, and
        absent on some records, in which case the caller falls back to the price table (FR-282).
        """
        try:
            return round(float(record.get("creditsConsumed") or 0.0) * self._credit_usd, 6)
        except (TypeError, ValueError):
            return 0.0


def _fail_cause(message: str) -> tuple[RenderFailCause, str]:
    """Classifies `failMsg` into the class whose remedy differs (20 §10, FR-97)."""
    lowered = message.lower()
    if any(sign in lowered for sign in _AUDIT_SIGNS):
        # Not moderation: stripping references does not fix a copyright-flagged audio track. The
        # message stays the provider's own text — it reaches the operator via SKIP_REASON.txt.
        return RenderFailCause.CONTENT_AUDIT, message
    if any(sign in lowered for sign in _MODERATION_SIGNS):
        return RenderFailCause.MODERATION, message
    return RenderFailCause.PROVIDER_FAIL, message


def _reference_urls(body: dict[str, Any]) -> list[str]:
    """Every reference this request attaches, in the order the provider will read them.

    Read off the built body rather than taken as a parameter, because the body IS the record of
    what was sent: a profile that capped a list (`profiles.py` caps before spending) would
    otherwise be reported as having attached what the caller offered. The three keys are the only
    reference-bearing ones either shipped profile builds.
    """
    return [str(url) for key in ("input_urls", "reference_image_urls", "reference_video_urls")
            for url in body.get(key) or [] if isinstance(url, str)]


def _reference_source(url: str) -> str:
    """One reference's provenance, as far as a URL can honestly carry it (FR-155).

    Host-classified, deliberately: the seam sees URLs, not the `(trend, panel)` pair that produced
    them — `generate/refs.py` owns that and logs it per creative as `reference_set`. What this
    line adds is the other half nobody could otherwise reconstruct: that THIS job, at THIS task
    id, sent THAT many references and where each was hosted. A CDN url is public and carries no
    credential (D30), and only its file name travels here.
    """
    parts = urlsplit(url)
    name = PurePosixPath(parts.path).name or parts.path or "?"
    host = parts.netloc.lower()
    if "kie" in host or "redpanda" in host:
        origin = "uploaded by this run"  # a style reference, a brief image, a seed frame, a clip
    else:
        origin = host or "unknown host"
    return f"{origin}: {name}"


def _result_urls(record: dict[str, Any]) -> list[str]:
    """`resultJson` is a JSON-encoded STRING, not an object (RESULTS.md §B) — malformed = none."""
    raw = record.get("resultJson")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, dict):
        return []
    urls = raw.get("resultUrls")
    if not isinstance(urls, list):
        return []
    return [url for url in urls if isinstance(url, str) and url.startswith("http")]


def _endpoint(url: str) -> str:
    """The path only — keeps query strings (and anything key-shaped) out of messages."""
    return url.split("?", 1)[0]


def _snippet(response: httpx.Response) -> str:
    return response.text[:200].replace("\n", " ")


__all__ = ["KieClient", "KieError", "KieOutOfCredits", "KieUploadError"]
