"""Render domain — one deep call from an assembled prompt to a finished, downloadable asset.

Purpose: hide every render provider behind one seam (FR-271/D34). A caller says *what* to render
and *which wave it belongs to*; this module submits, polls, classifies and returns. Kie's field
names, five poll states, `resultJson` shape and status codes never leave this package — and
neither do the Codex proxy's `/images/generations`, `size` enum and `b64_json`.

Public API
    configure(settings, log=...)  once per run, from the runner, after config load (FR-77)
    await run(profile, params, refs, priority) -> RenderOutcome    (models.RenderRun)
    await upload_file(path) -> str                                 (seam op 4, FR-244)
    await aclose()          once per run, on every exit path
    RenderGate              the 2-tier permit gate — public for its named starvation test
    RenderSettings          what `configure` needs, all of it config-sourced
    get_profile(name)       pre-flight's profile/template-set check (FR-272/263)
    KieOutOfCredits         402: a whole-run condition, never a job condition (FR-167)
    CodexUploadError        one file could not become a reference (a KieUploadError subclass)

TWO PROVIDERS, ONE SEAM (D64). `RenderSettings.provider` picks which client `configure()` binds,
and it is the ONLY line in the engine that knows there is a choice:

    `kie`    Kie.ai, metered. Needs `KIE_API_KEY`, renders images AND video, results are CDN URLs.
    `codex`  the operator's ChatGPT subscription through the local `npx openai-oauth@latest`
             proxy. Needs NO key (the proxy holds the OAuth token), renders IMAGES ONLY — a video
             body comes back as a stated FAIL, never an exception — costs $0 per job, returns a
             `file://` URL to bytes written under `<scratch_dir>/.renders/`, and `upload_file()`
             moves nothing: a reference is already a local file, so its own `file://` URI is the
             URL. `outputs.packager._download()` reads that scheme without a socket.

Everything downstream — the permit gate, `RenderOutcome`, the FR-203 ledger, FR-317's single
resubmit, `meta.yaml` — is provider-blind and stays that way.

Wiring: `configure()` binds a module-level client + gate instead of threading both through
`generate/`, `carousel.py` and `reel.py` — the caller's mental model stays "render this", not
"render this with that gate on that client". `RenderGate` still constructs standalone, so its
starvation test needs no provider, key or network (W4 barrier item).

Invariants:
- A permit is held across submit-and-poll ONLY and `run()` awaits no dependency while holding one
  — the rule that stops `max_inflight_render_jobs` carousels deadlocking (models.RenderPriority).
- WAVE2 waiters are served before ANY queued WAVE1 waiter, FIFO within a tier, no preemption.
- An unknown profile raises at lookup, before any spend (FR-272).
- Money moves at most once per `run()`: this seam never resubmits and never re-polls a task id,
  not on timeout, not on a failed poll, not on a lost response (20 §8). Every retry in the engine
  is the CALLER's, as a second `run()` call it decides to make: FR-97's moderation retry, FR-105's
  vision re-render, and — since v2.1.3/D48 — FR-317's single automatic resubmit of a timed-out or
  non-moderation-failed IMAGE job. A video job is still never resubmitted, by anyone (FR-44).
Do not: import `render.kie`/`render.profiles` from outside this package; branch on a Kie state or
route name; hold a permit across a chained-artifact await; log an API key.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hypesocials.models import RenderOutcome, RenderParams, RenderPriority, RenderRefs
from hypesocials.render import profiles as _profiles
from hypesocials.render.codex_images import CodexImageClient, CodexUploadError
from hypesocials.render.codex_images import DEFAULT_BASE_URL as CODEX_BASE_URL
from hypesocials.render.codex_images import RENDERS_DIR as SCRATCH_RENDERS_DIR
from hypesocials.render.kie import KieClient, KieError, KieOutOfCredits, KieUploadError
from hypesocials.render.profiles import ReferenceLimits, RenderProfile, UnknownProfileError

logger = logging.getLogger(__name__)

PROVIDER_KIE = "kie"
PROVIDER_CODEX = "codex"

#: Either provider client. A union rather than a Protocol because there are exactly two of them,
#: both in this package, and the union is checkable: adding a third that forgets `upload()` is a
#: type error at the assignment rather than an AttributeError mid-run.
ProviderClient = KieClient | CodexImageClient


class RenderError(RuntimeError):
    """A seam-level misuse: not configured, or a capacity that cannot bound anything."""


#: FR-203 ledger hooks. `on_intent(request_token)` fires BEFORE `createTask`; `on_submitted(
#: request_token, task_id)` fires when the response lands, with `None` for a lost response
#: (`submit_unknown`). Both run synchronously inside the calling task, so the caller identifies
#: the asset from its own context — the seam deliberately knows nothing about asset ids.
IntentHook = Callable[[str], None]
SubmittedHook = Callable[[str, "str | None"], None]


@dataclass(slots=True)
class RenderSettings:
    """Everything `configure()` needs, every value config-sourced (30 §2, FR-270)."""

    #: WHO renders (D64, `config.models.render_provider`). `kie` is the metered Kie.ai path;
    #: `codex` is the operator's ChatGPT subscription behind the local proxy — no key, images
    #: only, $0 a job. An unknown value is a `RenderError` at `configure()`, never a fallback.
    provider: str = PROVIDER_KIE
    #: The codex proxy's base URL (`config.models.llm_base_url`) — ignored under `kie`.
    base_url: str = CODEX_BASE_URL
    #: The run directory. Under `codex` the finished bytes are written to `<scratch_dir>/.renders/`
    #: and travel on as `file://` URLs, so the renders live and die with the run they belong to.
    #: `None` falls back to the system temp folder, which is only right for tests and spikes.
    scratch_dir: Path | None = None
    api_key_env: str = "KIE_API_KEY"  # the NAME of the variable; the value never lands in config
    max_inflight_render_jobs: int = 8
    poll_interval_s: float = 3.0
    #: Queue + render, not render alone (config.py). 600 s since v2.1.3/D48: an image job that
    #: times out now costs a resubmit rather than a slide (FR-317), and a second timeout is final.
    image_job_timeout_s: float = 600.0
    video_job_timeout_s: float = 300.0
    http_max_attempts: int = 3
    #: profile name -> the configured id for that family's DEFAULT route (`models.image` for
    #: gpt-image-2's reference-FREE half, `models.video` for Seedance's only route).
    model_ids: dict[str, str] = field(default_factory=dict)
    #: profile name -> the configured id for that family's REFERENCE-BEARING route
    #: (`models.image_edit`). Separate mapping because one key naming both halves is FR-241's
    #: live defect (D48): the `models.image` override collapsed anchor-chained slides onto
    #: text-to-image, which accepted the reference and ignored it. Empty leaves the profile's own
    #: declared image-to-image route in force, which is the correct route either way.
    edit_model_ids: dict[str, str] = field(default_factory=dict)
    upload_path: str = "hypesocials"
    credit_usd: float = 0.005  # Kie's published 1 USD = 200 credits (RESULTS.md §B)
    on_intent: IntentHook | None = None
    on_submitted: SubmittedHook | None = None


class RenderGate:
    """The 2-tier priority permit gate specified in models.py `RenderPriority` (FR-25).

    A plain `asyncio.Semaphore` is insufficient, and that is the whole reason this class exists:
    its waiters are strict FIFO, so a burst of WAVE1 acquisitions queued ahead of pre-committed
    WAVE2 work (slides 2-N, the Seedance clip) starves exactly the jobs FR-106b forbids
    abandoning — half-built decks. A released permit therefore goes to a waiting WAVE2 acquirer
    before any queued WAVE1 acquirer, FIFO inside each tier. Priority binds the QUEUE only: a
    held permit is never preempted and a running job always finishes.

        async with gate.permit(RenderPriority.WAVE2):
            ...submit and poll one job...

    Provider-free by design — capacity in, turns out — so its starvation test is pure asyncio.
    """

    __slots__ = ("_capacity", "_held", "_held_by_tier", "_waiters")

    def __init__(self, capacity: int) -> None:
        if int(capacity) < 1:
            raise RenderError(f"max_inflight_render_jobs must be >= 1, got {capacity!r}")
        self._capacity = int(capacity)
        self._held = 0
        self._held_by_tier: dict[RenderPriority, int] = {
            RenderPriority.WAVE2: 0, RenderPriority.WAVE1: 0}
        self._waiters: dict[RenderPriority, deque[asyncio.Future[None]]] = {
            RenderPriority.WAVE2: deque(),
            RenderPriority.WAVE1: deque(),
        }

    @property
    def in_flight(self) -> int:
        """Permits currently held — the number of jobs this gate believes are live."""
        return self._held

    def stats(self) -> tuple[int, int, int]:
        """`(running_w1, running_w2, queued)` — read-only, for FR-299's render heartbeat.

        The per-tier running counts are tracked at `permit()` scope (the tier a HOLDER entered
        under, regardless of how its permit was transferred), so the heartbeat's `(0 w1, 2 w2)`
        split names who is actually rendering, not who queued first. Behaviour of the gate is
        untouched — this observes, it never decides.
        """
        return (self._held_by_tier[RenderPriority.WAVE1], self._held_by_tier[RenderPriority.WAVE2],
                sum(len(queue) for queue in self._waiters.values()))

    @asynccontextmanager
    async def permit(self, priority: RenderPriority) -> AsyncIterator[None]:
        """Holds one permit for the body. Release is unconditional, including on cancellation."""
        await self._acquire(priority)
        self._held_by_tier[priority] += 1
        try:
            yield
        finally:
            self._held_by_tier[priority] -= 1
            self._release()

    async def _acquire(self, priority: RenderPriority) -> None:
        # No barging: a free permit is taken directly only when nobody is already queued,
        # otherwise the tier order below would be decided by luck instead of by priority.
        if self._held < self._capacity and not any(self._waiters.values()):
            self._held += 1
            return
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        queue = self._waiters[priority]
        queue.append(waiter)
        try:
            await waiter
        except asyncio.CancelledError:
            if waiter.done() and not waiter.cancelled():
                self._release()  # a permit reached us as we were cancelled — pass it on
            else:
                with suppress(ValueError):
                    queue.remove(waiter)
            raise

    def _release(self) -> None:
        """Hands the permit to the highest-priority waiter, or gives it back to the pool."""
        for tier in (RenderPriority.WAVE2, RenderPriority.WAVE1):
            queue = self._waiters[tier]
            while queue:
                waiter = queue.popleft()
                if not waiter.done():
                    waiter.set_result(None)  # transferred: `_held` stays as it is
                    return
        self._held -= 1


_settings: RenderSettings | None = None
_client: ProviderClient | None = None
_gate: RenderGate | None = None


def configure(settings: RenderSettings, *, log: Any = None) -> None:
    """Binds the run's provider client and permit gate. Called once, by the runner.

    `log` is the run's `outputs.LogWriter`; passing it is what puts every submit, poll and
    terminal result into `run.log`/`events.jsonl` (FR-77), rather than a stdlib logger nobody reads.

    The provider branch is HERE and nowhere else (D64). Under `kie` the key variable must be set —
    pre-flight (FR-45/46) normally refuses long before this, so reaching that error means the run
    skipped its own gate. Under `codex` no environment variable is read AT ALL: the proxy holds
    the operator's OAuth token and this process never sees a credential.
    """
    global _settings, _client, _gate
    provider = (settings.provider or PROVIDER_KIE).strip().lower()
    if provider == PROVIDER_CODEX:
        client: ProviderClient = CodexImageClient(
            base_url=settings.base_url,
            http_max_attempts=settings.http_max_attempts,
            scratch_dir=settings.scratch_dir,
            log=log,
        )
    elif provider == PROVIDER_KIE:
        api_key = os.environ.get(settings.api_key_env, "").strip()
        if not api_key:
            raise RenderError(f"{settings.api_key_env} is not set — no render job can be submitted")
        client = KieClient(
            api_key=api_key,
            http_max_attempts=settings.http_max_attempts,
            poll_interval_s=settings.poll_interval_s,
            upload_path=settings.upload_path,
            credit_usd=settings.credit_usd,
            log=log,
        )
    else:
        # No fallback to Kie: a typo'd provider that silently spends money is the one failure a
        # seam like this must never have (the FR-295 posture, applied to providers).
        raise RenderError(
            f"unknown render provider {settings.provider!r}; expected "
            f"{PROVIDER_KIE!r} or {PROVIDER_CODEX!r}")
    _settings = settings
    _gate = RenderGate(settings.max_inflight_render_jobs)
    _client = client
    logger.info(
        "Render seam ready: provider=%s max_inflight=%d poll=%.1fs profiles=%s",
        provider, settings.max_inflight_render_jobs, settings.poll_interval_s,
        ",".join(_profiles.PROFILE_NAMES),
    )


async def aclose() -> None:
    """Closes the provider client. Safe to call twice and on any exit path (FR-249 posture)."""
    global _client, _gate, _settings
    client, _client, _gate, _settings = _client, None, None, None
    if client is not None:
        await client.aclose()


async def run(
    profile: str,
    params: RenderParams,
    refs: RenderRefs,
    priority: RenderPriority,
) -> RenderOutcome:
    """Render one creative: submit, poll, classify, verify (models.py `RenderRun`).

    The permit is acquired here and released the moment the job is terminal, so a coroutine that
    renders an anchor and then its slides holds a permit for each job, never across the wait
    between them. Returns a terminal `RenderOutcome` for every ordinary failure — the only
    exception that escapes is `KieOutOfCredits`, which is a run condition, not a job outcome.
    """
    settings, client, gate = _require()
    render_profile = _profiles.get(profile)
    # Both configured ids travel, and the PROFILE decides which one this job's route takes
    # (FR-241/D48): `model_ids` names the default (reference-free) route, `edit_model_ids` the
    # reference-bearing one. Passing a single id here is what collapsed both halves of a
    # dual-route family onto text-to-image on every anchor-chained slide of run
    # 20260813_222101_g1xt — the seam still speaks no route name, it just stopped speaking half.
    model_id, body = render_profile.request(
        params, refs, settings.model_ids.get(profile, ""), settings.edit_model_ids.get(profile, ""))
    timeout_s = (
        settings.video_job_timeout_s if render_profile.kind == "video" else settings.image_job_timeout_s
    )
    async with gate.permit(priority):
        return await client.render(
            model_id, body, timeout_s=timeout_s,
            on_intent=settings.on_intent, on_submitted=settings.on_submitted,
        )


async def upload_file(path: str | Path) -> str:
    """Turn a local file into a URL a renderer can reference (seam op 4, FR-244/162).

    Raises `KieUploadError` for that one file — callers drop the reference and carry on; the job
    still runs with whatever references survived. Treat the URL as SAME-RUN-ONLY: a Kie upload
    carries a 24 h cache lifetime and a later run must re-upload rather than reuse a stored URL
    (20 §8b), and a codex `file://` URL points inside THIS run's folder.
    """
    _, client, _ = _require()
    return await client.upload(path)


def get_profile(name: str) -> RenderProfile:
    """Pre-flight's profile lookup (FR-272) — also how FR-263 finds the template-set name."""
    return _profiles.get(name)


def gate_stats() -> tuple[int, int, int]:
    """`(running_w1, running_w2, queued)` for the configured run, or zeros before `configure()`.

    The FR-299 heartbeat's one window into the permit gate — read-only by contract; `generate`'s
    `_drain` loop prints from it and never steers it.
    """
    return _gate.stats() if _gate is not None else (0, 0, 0)


def _require() -> tuple[RenderSettings, ProviderClient, RenderGate]:
    if _settings is None or _client is None or _gate is None:
        raise RenderError("render.configure() has not been called for this run")
    return _settings, _client, _gate


__all__ = [
    "CodexUploadError", "KieError", "KieOutOfCredits", "KieUploadError", "PROVIDER_CODEX",
    "PROVIDER_KIE", "ReferenceLimits", "RenderError", "RenderGate", "RenderProfile",
    "RenderSettings", "SCRATCH_RENDERS_DIR", "UnknownProfileError", "aclose", "configure",
    "gate_stats", "get_profile", "run", "upload_file",
]
