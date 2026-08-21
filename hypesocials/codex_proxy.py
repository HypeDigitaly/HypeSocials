"""The local OpenAI-compatible proxy that fronts the operator's ChatGPT/Codex subscription.

Module contract
---------------
Purpose: make `http://127.0.0.1:10531/v1` a fact of the run rather than a hope (SESSION O, D64).
`models.llm_backend: codex` and `models.render_provider: codex` both point every call at a proxy
process — `npx openai-oauth@latest` — that the operator normally starts by hand. An unattended run
(`--yes` under Task Scheduler) has nobody at the keyboard to start it, so this module PROBES the
endpoint, STARTS it when it is missing, waits for it to answer, and guarantees it dies with the
engine. Callers get a handle and three verbs; they never see a PID, a job handle or a port.

Public API:
    ProxyHandle                       — one proxy: reachable, owned-or-not, its model list
    probe(base_url, timeout_s=…)      — GET {base}/models, returns the model ids
    ensure_proxy(base_url, …)         — probe, else launch and wait; returns a `ProxyHandle`
    stop(handle)                      — kill an OWNED proxy's process tree; idempotent, never raises
    current_handle()                  — the handle `ensure_proxy` last returned, for the exit path
    ProxyUnavailable                  — the one failure type (a `RuntimeError`); pre-flight's exit 2

Invariants:
- **Loopback only, always.** Every entry point runs `_port_of()`, which REFUSES (`ValueError`) any
  base URL whose host is not `127.0.0.1` or `localhost`. The proxy speaks for the operator's own
  OAuth session; a config typo that pointed it at a LAN address would hand that session to whoever
  answered. This is the D30 posture applied to a credential this engine never even reads.
- **The token is never touched.** `~/.codex/auth.json` belongs to the proxy. This module does not
  read it, does not check whether it exists, and never names its contents in a log line. "Not
  signed in" surfaces as an unreachable endpoint, and the refusal text says `codex login`.
- **An owned child cannot outlive the engine.** The subprocess joins a Windows job object with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (the same guarantee `mcp_client` gives every MCP server), so
  losing the console, Task Manager or a crash reaps it; `stop()` adds the orderly `taskkill /T`
  sweep. A proxy the operator started themselves is `owned=False` and is NEVER killed by us.
- **stdin is DEVNULL, output goes to a file.** The proxy offers `[d] Run in background [q] Quit` on
  a TTY; attached to one it would eat the engine's own keystrokes at the Confirm gate. Its stdout
  and stderr are appended to `logs/codex_proxy.log` so a startup failure is diagnosable without
  ever reaching the operator's console mid-run.
- **Readiness is the model list, not the process.** `npx` may take 10–25 s (a cold `npx` download
  is slower still), so startup polls `probe()` once a second until the endpoint answers — a live
  PID proves nothing.

Do not: expose the proxy off-box, read or log `~/.codex/auth.json`, kill a proxy this module did
not start, block the event loop on a subprocess wait, or retry a model call here (`llm.py` owns
its own retry policy, exactly as each MCP server does).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from hypesocials.config import LOGS_DIR

logger = logging.getLogger(__name__)

if sys.platform == "win32":  # pragma: no branch — Windows is the only supported host (CLAUDE.md)
    import pywintypes
    import win32api
    import win32con
    import win32job

#: The only hosts a `llm_base_url` may name. Not a style preference: see the loopback invariant.
LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost"})
#: The port `npx openai-oauth@latest` listens on when nothing says otherwise — used only when a
#: base URL omits its port, so `http://127.0.0.1/v1` still means the proxy rather than port 80.
DEFAULT_PORT = 10531
#: The command, pinned to `@latest` on purpose: the proxy tracks OpenAI's own endpoint changes and
#: a version pinned here would rot silently into "signed in but every call 400s".
LAUNCH_COMMAND = ("openai-oauth@latest",)
#: Where the child's stdout/stderr land. Appended, never truncated: two runs in one day is the
#: normal case and the first one's crash is usually the interesting one.
LOG_PATH: Path = LOGS_DIR / "codex_proxy.log"
#: How often the startup loop asks the endpoint whether it is up yet.
_POLL_INTERVAL_S = 1.0
#: The probe's own budget. Deliberately short — a loopback GET that takes seconds is a hung proxy,
#: and the startup loop will ask again in a moment anyway.
DEFAULT_PROBE_TIMEOUT_S = 5.0
_TASKKILL_TIMEOUT_S = 5.0
#: How long an owned child gets to die politely before the job handle takes it (`stop`).
_TERMINATE_GRACE_S = 5.0

#: One sentence, reused by every refusal, because there is exactly one cure and the operator should
#: read the same words wherever the failure surfaces.
_CURE = ("run `npx openai-oauth@latest` in its own window and sign in once with `codex login`")


class ProxyUnavailable(RuntimeError):
    """The proxy is not answering and could not be started. Always carries the cure (FR-295 shape)."""


@dataclass(slots=True)
class ProxyHandle:
    """One proxy endpoint, as this run found or made it.

    Attributes:
        base_url: the `/v1` root every caller should use — normalized, no trailing slash.
        port: the loopback port behind it.
        models: the ids `GET {base_url}/models` answered with, at the moment it became ready.
            Pre-flight checks the run's configured ids against THIS list rather than probing a
            second time, so what was verified is what was seen.
        owned: `True` only when this process started the proxy. It is the whole authority for
            whether `stop()` may kill anything.
        process: the `asyncio` subprocess, when owned.
    """

    base_url: str
    port: int
    models: tuple[str, ...] = ()
    owned: bool = False
    process: Any | None = None
    _job: Any | None = field(default=None, repr=False)
    _log_file: Any | None = field(default=None, repr=False)
    _stopped: bool = field(default=False, repr=False)

    @property
    def pid(self) -> int | None:
        """The child's pid for a log line; `None` for a proxy the operator started themselves."""
        return getattr(self.process, "pid", None)

    def summary(self) -> str:
        """One console-safe clause: where it is, who started it, how many models it offers."""
        return (f"{self.base_url} · {'started by this run' if self.owned else 'already running'} · "
                f"{len(self.models)} model(s)")


#: The handle the run is currently using. A module-level cell rather than a field on `Preflight`
#: because the two callers sit at opposite ends of the run: pre-flight creates it before the money
#: gate, and `runner._cleanup()` must be able to release it on EVERY exit path — including the ones
#: that never got a verdict object at all (a config error, a Ctrl+C during Collect). `stop()` clears
#: it, so a second call is a no-op rather than a second kill.
_CURRENT: ProxyHandle | None = None
#: Guards the probe-then-launch sequence: two callers arriving together must not spawn two proxies
#: racing for one port. Cheap and uncontended in practice — pre-flight is the only caller.
_LAUNCH_LOCK = asyncio.Lock()


def current_handle() -> ProxyHandle | None:
    """The proxy this run is using, or `None`.

    The exit path's whole interface — `await stop(current_handle())` is safe on every path,
    including the ones that never reached a pre-flight verdict at all.
    """
    return _CURRENT


async def probe(base_url: str, timeout_s: float = DEFAULT_PROBE_TIMEOUT_S, *,
                client: httpx.AsyncClient | None = None) -> list[str]:
    """Asks a running proxy which models it serves. The readiness test AND the config check.

    Args:
        base_url: the `/v1` root. Refused unless it is loopback (see the module invariants).
        timeout_s: the whole request's budget, connect included.
        client: an injected `httpx.AsyncClient` — the test seam (a `MockTransport` goes here).
            Production passes nothing and this call owns a client for its own lifetime.

    Returns:
        The model ids, in the order the proxy listed them (e.g. `gpt-5.6-luna`, `gpt-image-2`).

    Raises:
        ValueError: `base_url` is not loopback.
        ProxyUnavailable: nothing answered, the answer was not 200, or the body was not the
            OpenAI `{"data": [{"id": …}]}` shape. All three mean the same thing to a caller —
            there is no usable endpoint here — so they are one type carrying one cure.
    """
    _port_of(base_url)  # the loopback guard runs BEFORE any socket is opened
    url = f"{base_url.rstrip('/')}/models"
    owned_client = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=timeout_s))
    try:
        response = await http.get(url)
    except httpx.HTTPError as exc:
        raise ProxyUnavailable(f"no OpenAI-compatible endpoint at {url} "
                              f"({type(exc).__name__}) — {_CURE}") from exc
    finally:
        if owned_client:
            await http.aclose()
    if response.status_code != 200:
        raise ProxyUnavailable(f"{url} answered HTTP {response.status_code} rather than a model "
                               f"list — {_CURE}")
    try:
        rows = response.json()["data"]
        ids = [str(row["id"]) for row in rows]
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise ProxyUnavailable(f"{url} answered something that is not a model list "
                               f"({type(exc).__name__}) — {_CURE}") from exc
    if not ids:
        raise ProxyUnavailable(f"{url} answered an EMPTY model list — the proxy is up but has no "
                               f"session; {_CURE}")
    return ids


async def ensure_proxy(base_url: str, *, startup_timeout_s: float = 45.0, log: Any = None,
                       client: httpx.AsyncClient | None = None) -> ProxyHandle:
    """Returns a usable proxy at `base_url`, starting one if nothing is listening.

    Probe first, always: an operator who keeps the proxy open in its own window (the normal
    interactive case) must not get a second one racing for their port, and the handle they get
    back is `owned=False` so nothing this run does can close their window.

    When nothing answers, `npx openai-oauth@latest --port <port>` is launched with stdin at
    DEVNULL (its `[d]/[q]` key handler would otherwise fight the Confirm gate for the console),
    its output appended to `logs/codex_proxy.log`, and its process joined to a kill-on-close
    Windows job object. Then `probe()` runs once a second until the endpoint answers or
    `startup_timeout_s` expires — a cold `npx` fetch is the slow case, and the default 45 s is
    sized for it against the ~10–25 s a warm start takes.

    Args:
        base_url: the `/v1` root from `models.llm_base_url`. Loopback only.
        startup_timeout_s: how long a LAUNCHED proxy has to become usable. Ignored when one is
            already running — that path costs one probe.
        log: the run's `LogWriter`, when a run owns one; events land as `codex_proxy` lines.
        client: test seam, forwarded to `probe()`.

    Returns:
        `ProxyHandle`, with `models` filled from the probe that proved it ready.

    Raises:
        ValueError: `base_url` is not loopback.
        ProxyUnavailable: `npx` is not on PATH, the child died at once, or it never answered
            inside `startup_timeout_s`. The child is terminated before this raises — a failed
            start never leaves a process behind.
    """
    global _CURRENT
    port = _port_of(base_url)
    base = base_url.rstrip("/")
    async with _LAUNCH_LOCK:
        with suppress(ProxyUnavailable):
            models = await probe(base, client=client)
            handle = ProxyHandle(base_url=base, port=port, models=tuple(models), owned=False)
            _CURRENT = handle
            _emit(log, "codex proxy already running at " + handle.summary(), level="info")
            return handle
        handle = await _launch(base, port, startup_timeout_s=startup_timeout_s, log=log,
                               client=client)
        _CURRENT = handle
        return handle


async def stop(handle: ProxyHandle | None) -> None:
    """Releases a proxy. Kills the process tree only when THIS run started it. Never raises.

    Idempotent by design: it runs from `runner._cleanup()`, which itself runs on every exit path
    including the ones that already failed — a cleanup step that can throw turns one bad run into
    two bad lines. A second call, a `None`, or a handle whose child is already gone are all
    silent no-ops.

    Order mirrors `mcp_client.open_session()`'s teardown, for the same reasons: ask politely
    (`terminate()`), then close the job handle — kill-on-close reaps anything the polite ask
    missed — then a `taskkill /T` sweep for a grandchild that somehow outlived the job (`npx`
    spawns the real node process as a child, so there is always a tree here, never one pid).
    """
    global _CURRENT
    if handle is None:
        return
    if handle is _CURRENT:
        _CURRENT = None
    if not handle.owned or handle._stopped:
        return
    handle._stopped = True
    process, pid = handle.process, handle.pid
    if process is not None and getattr(process, "returncode", None) is None:
        with suppress(Exception):
            process.terminate()
        with suppress(Exception):
            async with asyncio.timeout(_TERMINATE_GRACE_S):
                await process.wait()
    _close_job_handle(handle._job)
    handle._job = None
    await _taskkill_tree(process)
    with suppress(Exception):
        if handle._log_file is not None:
            handle._log_file.close()
    handle._log_file = None
    logger.info("codex proxy stopped: pid=%s port=%s", pid, handle.port)


# --------------------------------------------------------------------------------- internals


def _port_of(base_url: str) -> int:
    """The loopback guard and the port parser, in one place so neither can be skipped.

    Raises `ValueError` — not `ProxyUnavailable` — because an off-box URL is a CONFIG mistake, not
    an unreachable service: no amount of starting proxies will fix it, and the operator has to
    edit `models.llm_base_url`. Pre-flight grades it as the same exit-2 refusal either way.
    """
    parts = urlsplit(base_url if "//" in base_url else f"//{base_url}")
    host = (parts.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        raise ValueError(
            f"models.llm_base_url is {base_url!r}, whose host is {host or 'unset'!r} — the Codex "
            "proxy speaks for this workstation's own ChatGPT sign-in and must never be reached "
            f"off-box; use {', '.join(sorted(LOOPBACK_HOSTS))} (D30)")
    try:
        port = parts.port
    except ValueError as exc:  # a non-numeric port never reaches a socket
        raise ValueError(f"models.llm_base_url is {base_url!r}: {exc}") from exc
    return int(port or DEFAULT_PORT)


async def _launch(base_url: str, port: int, *, startup_timeout_s: float, log: Any,
                  client: httpx.AsyncClient | None) -> ProxyHandle:
    """Starts the proxy and waits for it to serve a model list. Cleans up after itself on failure."""
    npx = _resolve_npx()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    sink = open(LOG_PATH, "ab")  # noqa: SIM115 — the handle lives as long as the child does
    try:
        process = await asyncio.create_subprocess_exec(
            npx, *LAUNCH_COMMAND, "--port", str(port),
            stdin=asyncio.subprocess.DEVNULL, stdout=sink, stderr=sink)
    except OSError as exc:
        sink.close()
        raise ProxyUnavailable(f"could not start the Codex proxy ({npx}): {exc} — {_CURE}") from exc
    handle = ProxyHandle(base_url=base_url, port=port, owned=True, process=process,
                         _job=_hold_job_object(process), _log_file=sink)
    logger.info("codex proxy launching: pid=%s port=%s log=%s", handle.pid, port, LOG_PATH)
    _emit(log, f"starting the Codex proxy on 127.0.0.1:{port} (up to "
               f"{startup_timeout_s:.0f}s; output in {LOG_PATH})", level="info")
    try:
        handle.models = tuple(await _wait_ready(base_url, process, startup_timeout_s, client))
    except ProxyUnavailable:
        await stop(handle)
        raise
    _emit(log, "codex proxy ready at " + handle.summary(), level="info")
    return handle


async def _wait_ready(base_url: str, process: Any, startup_timeout_s: float,
                      client: httpx.AsyncClient | None) -> list[str]:
    """Polls `probe()` once a second until the endpoint answers, the child dies, or time runs out.

    The dead-child arm matters as much as the timeout: `npx` exits within a second or two when the
    package name is wrong or the port is taken, and waiting the full 45 s to say so would look
    exactly like a slow start. The child's own words are already in `logs/codex_proxy.log`, which
    is what the refusal points at.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, float(startup_timeout_s))
    last = ""
    while True:
        try:
            return await probe(base_url, client=client)
        except ProxyUnavailable as exc:
            last = str(exc)
        code = getattr(process, "returncode", None)
        if code is not None:
            raise ProxyUnavailable(
                f"the Codex proxy exited immediately (code {code}) — see {LOG_PATH}; {_CURE}")
        if loop.time() >= deadline:
            raise ProxyUnavailable(
                f"the Codex proxy did not answer at {base_url} within {startup_timeout_s:.0f}s "
                f"(last: {last}) — see {LOG_PATH}; {_CURE}")
        await asyncio.sleep(_POLL_INTERVAL_S)


def _resolve_npx() -> str:
    """Finds the `npx` launcher, `.cmd` shim included — the Windows half of `mcp_client`'s FR-110.

    `mcp_client` hands this job to the MCP SDK, which resolves `.cmd`/`.bat`/`.exe`/`.ps1` for
    npm-installed commands. There is no SDK on this path, so the same resolution happens here:
    `shutil.which` honours PATHEXT, and the explicit `.cmd` fallback covers a PATHEXT an operator
    has trimmed. The FULL PATH is what gets executed — `create_subprocess_exec` with a bare `npx`
    finds nothing on Windows, since the thing on PATH is `npx.cmd`.
    """
    for candidate in ("npx", "npx.cmd", "npx.exe"):
        found = shutil.which(candidate)
        if found:
            return found
    raise ProxyUnavailable("Node/npx was not found on PATH, so the Codex proxy cannot be started "
                           "— install Node.js 24+, or set models.llm_backend: openrouter and "
                           "models.render_provider: kie to go back to the metered providers")


def _hold_job_object(process: Any) -> Any | None:
    """Assigns the child to a kill-on-close job object and returns the handle to hold.

    The twin of `mcp_client._hold_job_object` (FR-111), duplicated rather than imported because it
    is private to that module and a public export would make one seam's internals another's API.
    If it changes there, change it here. Failure degrades LOUDLY and never blocks the run: `stop()`
    still terminates the child and still sweeps with `taskkill /T`; what is lost is only the
    guarantee that a hard engine death (Task Manager, console X) reaps the proxy too.
    """
    if sys.platform != "win32" or process is None:
        return None
    pid = getattr(process, "pid", None)
    if pid is None:
        return None
    job = None
    try:
        job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
        handle = win32api.OpenProcess(
            win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, pid)
        try:
            win32job.AssignProcessToJobObject(job, handle)
        finally:
            win32api.CloseHandle(handle)
        return job
    except pywintypes.error:
        logger.warning("codex proxy: job-object assignment for pid %s failed", pid, exc_info=True)
        _close_job_handle(job)
        return None


def _close_job_handle(job: Any | None) -> None:
    if job is None or sys.platform != "win32":
        return
    with suppress(Exception):
        win32api.CloseHandle(job)


async def _taskkill_tree(process: Any | None) -> None:
    """Orderly-exit sweep: `npx` starts node as a CHILD, so the tree can outlive the parent."""
    if sys.platform != "win32" or process is None:
        return
    pid = getattr(process, "pid", None)
    if pid is None:
        return
    with suppress(Exception):
        proc = await asyncio.create_subprocess_exec(
            "taskkill", "/F", "/T", "/PID", str(pid),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        async with asyncio.timeout(_TASKKILL_TIMEOUT_S):
            await proc.wait()


def _emit(log: Any, message: str, *, level: str = "info") -> None:
    """One line into the run's own log when a run owns one; the stdlib logger either way (FR-77)."""
    logger.info("%s", message)
    if log is not None:
        with suppress(Exception):  # a logging failure must never take the proxy down
            log.event("codex_proxy", message, level=level)


__all__ = [
    "DEFAULT_PORT", "DEFAULT_PROBE_TIMEOUT_S", "LAUNCH_COMMAND", "LOG_PATH", "LOOPBACK_HOSTS",
    "ProxyHandle", "ProxyUnavailable", "current_handle", "ensure_proxy", "probe", "stop",
]
