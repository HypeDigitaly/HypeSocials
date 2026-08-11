"""Shared async MCP client — the single seam every MCP-backed integration goes through.

Purpose: open, own and close MCP sessions for the servers a run actually needs (Virlo now, Notion
in W5, Postiz's optional ops seam in Phase 2) so no caller ever touches the SDK, a subprocess, a
PID or a Windows job handle. Config decides *which* server and *how to reach it*; this module
decides *how to survive Windows*.

Public API (FR-30/31, 110–117, 246):
    ServerConfig                  — one server's transport/launch/env/timeout record, from config
    open_session(cfg, log=…)      — async CM yielding one live `Session`
    Session.call_tool(tool, args) — serialized, timeout-bounded, payload already unwrapped
    Session.tool_names()          — the tool names the server advertises
    SessionPool(cfg, size, log=…) — async CM handing a BOUNDED set of sessions to work items
    MCPClientError / MCPStartupError / MCPStartupTimeout / MCPCallTimeout

Invariants enforced here, once, for every caller:
- A stdio server receives a MINIMAL environment: only the variables config names for it (FR-110).
  The SDK adds its small Windows-safe base set (PATH/SYSTEMROOT/TEMP/APPDATA/…) needed to start a
  process at all — this engine's environment is never forwarded wholesale, so one server's secret
  can never reach another server.
- Every stdio subprocess belongs to a Windows job object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
  whose handle this module holds for the session's whole lifetime (FR-111); an orderly close adds
  a `taskkill /T` sweep for anything that somehow outlived the job.
- Startup and per-call timeouts are separate, config-sourced values with distinct failure types —
  a slow launch and a hung call are different bugs (FR-112).
- Calls on one session are serialized (FR-115). Concurrency comes from more sessions, bounded by
  `SessionPool` (FR-246) — never one subprocess per work item.

Do not: spawn a session per work item; retry tool calls here (each server owns its own retry
policy — the Virlo wrapper's is FR-120); log an environment value; assume POSIX process groups.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import sys
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# `MCPError` is re-exported: it is how a server-side tool failure (e.g. the Virlo wrapper's four
# FR-119 classes) reaches a caller, so callers import it from this seam rather than from the SDK.
from mcp import Client, MCPError, StdioServerParameters, stdio_client
from mcp.client import stdio as _sdk_stdio
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp_types import INTERNAL_ERROR, Implementation

from hypesocials.util import Stopwatch

logger = logging.getLogger(__name__)

# Canonical defaults live in `configs/default.yaml` (30 FR-259); these mirror them so a direct or
# test call still behaves per PRD. Production always passes the loaded config values (FR-112).
DEFAULT_STARTUP_TIMEOUT_S = 20.0
DEFAULT_CALL_TIMEOUT_S = 30.0

#: Which environment variable each shipped stdio server needs, when config doesn't say. The tool
#: contract of a first-party/pinned server is fixed at code level (20 §2, FR-116 withdrawn).
_DEFAULT_ENV_VARS: dict[str, tuple[str, ...]] = {"virlo": ("VIRLO_API_KEY",), "notion": ("NOTION_TOKEN",)}

_CLIENT_INFO = Implementation(name="hypesocials", version="0.1.0")
_TASKKILL_TIMEOUT_S = 5.0

if sys.platform == "win32":  # pragma: no branch — Windows is the only supported host (CLAUDE.md)
    import pywintypes
    import win32api
    import win32con
    import win32job


class MCPClientError(RuntimeError):
    """Any failure raised by this module (never a provider's own tool error, which is `MCPError`)."""


class MCPStartupError(MCPClientError):
    """The stdio subprocess could not be launched, or the handshake failed (20 §10 row 1)."""


class MCPStartupTimeout(MCPStartupError):
    """The server launched but was not usable within `mcp_startup_timeout_s` (FR-112, 20 §10 row 2).

    The timeout bounds *usability*, not teardown: raising it still waits out the SDK's shielded,
    bounded kill escalation (~2 s) so the half-started subprocess tree is reaped, never abandoned.
    """


class MCPCallTimeout(MCPClientError):
    """One tool call exceeded `mcp_call_timeout_s` (FR-112) — no data, never an indefinite hang."""


@dataclass(slots=True)
class ServerConfig:
    """One `mcp_servers.<name>` entry, resolved (30 FR-130). Built by config, consumed here."""

    name: str
    command: str = ""  # stdio: full command line, e.g. "python -m hypesocials.virlo_mcp"
    transport: Literal["stdio", "streamable_http"] = "stdio"
    url: str = ""  # http transports only
    auth_env: str = ""  # http: the env var holding this server's bearer token
    env_vars: tuple[str, ...] = ()  # stdio: variable NAMES only; values are joined at spawn time
    extra_env: dict[str, str] = field(default_factory=dict)  # non-secret config values for the server
    startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S
    call_timeout_s: float = DEFAULT_CALL_TIMEOUT_S
    cwd: str | None = None

    @classmethod
    def from_mapping(
        cls,
        name: str,
        entry: Mapping[str, Any],
        *,
        startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
        call_timeout_s: float = DEFAULT_CALL_TIMEOUT_S,
        extra_env: Mapping[str, str] | None = None,
    ) -> ServerConfig:
        """Builds a config from one raw `mcp_servers` YAML entry plus the run's MCP timeouts."""
        declared = entry.get("env_vars") or entry.get("env") or _DEFAULT_ENV_VARS.get(name, ())
        return cls(
            name=name,
            command=str(entry.get("command", "")),
            transport=str(entry.get("transport", "stdio")).replace("-", "_"),  # type: ignore[arg-type]
            url=str(entry.get("url", "")),
            auth_env=str(entry.get("auth_env", "")),
            env_vars=tuple(declared),
            extra_env=dict(extra_env or {}),
            startup_timeout_s=startup_timeout_s,
            call_timeout_s=call_timeout_s,
            cwd=entry.get("cwd"),
        )


class Session:
    """One live MCP connection. Calls are serialized (FR-115) and time-bounded (FR-112)."""

    __slots__ = ("_client", "_cfg", "_lock", "_log", "_process")

    def __init__(self, cfg: ServerConfig, client: Client, process: Any | None,
                 log: Any = None) -> None:
        self._cfg = cfg
        self._client = client
        self._process = process
        self._log = log  # the run's `outputs.LogWriter`, when a run owns one (FR-77)
        self._lock = asyncio.Lock()

    @property
    def server_name(self) -> str:
        return self._cfg.name

    @property
    def pid(self) -> int | None:
        """The stdio subprocess id, for log lines and orphan checks; None for HTTP transports."""
        return getattr(self._process, "pid", None)

    async def call_tool(self, tool: str, arguments: dict[str, Any] | None = None) -> Any:
        """Calls one tool and returns its payload (structured content when the server sends it).

        Raises:
            MCPCallTimeout: the call exceeded `mcp_call_timeout_s`.
            MCPError: the server answered with a protocol error — `.code` is the server's own
                error class (the Virlo wrapper's four classes are FR-119), so callers branch on
                the code rather than parsing text.
        """
        watch, status, rows = Stopwatch(), "ok", None
        try:
            async with self._lock:  # FR-115: one call in flight per session
                try:
                    async with asyncio.timeout(self._cfg.call_timeout_s):
                        result = await self._client.call_tool(tool, arguments or {})
                except TimeoutError as exc:
                    raise MCPCallTimeout(
                        f"MCP call {self._cfg.name}.{tool} exceeded mcp_call_timeout_s="
                        f"{self._cfg.call_timeout_s}s"
                    ) from exc
            if result.is_error:
                raise MCPError(INTERNAL_ERROR,
                               f"{self._cfg.name}.{tool} failed: {_text_of(result)}")
            if result.structured_content is not None:
                rows = _row_count(result.structured_content)
                return result.structured_content
            return _text_of(result)
        except BaseException as exc:  # the error CLASS is the log field, never the arguments
            status = type(exc).__name__
            raise
        finally:
            self._log_call(tool, status, watch.elapsed_ms, rows)

    def _log_call(self, tool: str, status: str, duration_ms: int, rows: int | None = None) -> None:
        """FR-77's per-MCP-call line: server, tool, duration, outcome and the ROW COUNT — the call
        ledger, never a transcript, so arguments and payloads deliberately do not travel here
        (40 §4).

        The count is required, not decorative (FR-77 bullet 2): `virlo MCP: get_top_videos -> ok`
        read identically whether Virlo returned a hundred rows or none, which made the single most
        consequential failure of a run — an empty answer from a healthy call — invisible in the
        one log a human reads.
        """
        logger.info("MCP call %s.%s -> %s (%s rows) in %dms",
                    self._cfg.name, tool, status, "-" if rows is None else rows, duration_ms)
        if self._log is not None:
            self._log.event(
                "mcp_call", f"{self._cfg.name} MCP: {tool} -> {status}"
                            + (f", {rows} row(s)" if rows is not None else ""),
                level="info" if status == "ok" else "warn", duration_ms=duration_ms,
                server=self._cfg.name, tool=tool, status=status, rows=rows)

    async def tool_names(self) -> list[str]:
        """The tool names this server advertises — the wrapper contract check at run start."""
        async with self._lock:
            async with asyncio.timeout(self._cfg.call_timeout_s):
                listing = await self._client.list_tools()
        return [tool.name for tool in listing.tools]


@asynccontextmanager
async def open_session(cfg: ServerConfig, *, log: Any = None) -> AsyncIterator[Session]:
    """Opens ONE session and guarantees its subprocess tree dies on every exit path (FR-31/111).

    `log` is the run's `outputs.LogWriter`; with it every tool call lands in the run's own logs
    (FR-77), without it only in the stdlib logger.
    """
    sink: list[Any] = []
    transport = _build_transport(cfg, sink)
    client = Client(transport, client_info=_CLIENT_INFO, cache=None)  # cache=None: no caching (FR-118)
    token = _SPAWNED.set(sink)
    try:
        async with asyncio.timeout(cfg.startup_timeout_s):
            await client.__aenter__()
    except TimeoutError as exc:
        await _safe_close(client)
        raise MCPStartupTimeout(
            f"MCP server {cfg.name!r} was not usable within mcp_startup_timeout_s={cfg.startup_timeout_s}s"
        ) from exc
    except Exception as exc:
        await _safe_close(client)
        raise MCPStartupError(f"MCP server {cfg.name!r} failed to start: {exc}") from exc
    finally:
        _SPAWNED.reset(token)

    process = sink[0] if sink else None
    job = _hold_job_object(cfg.name, process)
    pid = getattr(process, "pid", None)
    logger.info("MCP session open: server=%s transport=%s pid=%s", cfg.name, cfg.transport, pid)
    try:
        yield Session(cfg, client, process, log)
    finally:
        await _safe_close(client)
        _close_job_handle(job)  # kill-on-close reaps anything the graceful shutdown missed
        await _taskkill_tree(cfg.name, process)
        logger.info("MCP session closed: server=%s pid=%s", cfg.name, pid)


class SessionPool:
    """A bounded set of independent sessions, handed to work items (FR-246, 20 §3).

    `size` comes from config (`virlo_session_pool`, default 3) and is normally capped by the
    caller at the number of work items — a one-monitor run opens one session. Sessions are opened
    and closed in the pool's own task, so a borrower's cancellation can never orphan a subprocess.

        async with SessionPool(cfg, size) as pool:
            async with pool.acquire() as session:
                await session.call_tool("get_top_videos", {"monitor_id": mid})
    """

    __slots__ = ("_cfg", "_exits", "_free", "_log", "_size")

    def __init__(self, cfg: ServerConfig, size: int, *, log: Any = None) -> None:
        if size < 1:
            raise MCPClientError(f"MCP session pool for {cfg.name!r} needs at least one session, got {size}")
        self._cfg = cfg
        self._size = size
        self._log = log  # forwarded to every session, so FR-77 covers pooled calls too
        self._exits: list[Any] = []
        self._free: asyncio.Queue[Session] = asyncio.Queue()

    async def __aenter__(self) -> SessionPool:
        try:
            for _ in range(self._size):
                # Sequential on purpose: an async CM must be entered and exited in the same task.
                ctx = open_session(self._cfg, log=self._log)
                self._free.put_nowait(await ctx.__aenter__())
                self._exits.append(ctx)
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, *exc: Any) -> None:
        for ctx in reversed(self._exits):
            with suppress(Exception):
                await ctx.__aexit__(None, None, None)
        self._exits.clear()

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Session]:
        """Borrows a session for one work item, returning it even if the work item fails."""
        session = await self._free.get()
        try:
            yield session
        finally:
            self._free.put_nowait(session)


# --------------------------------------------------------------------------------------------
# Internals: Windows-safe launch (FR-110), PID capture, job objects (FR-111).
# --------------------------------------------------------------------------------------------

#: Per-open_session sink the spawn probe appends the freshly spawned process to. A ContextVar (not
#: a global) so concurrent pool startups in different tasks cannot claim each other's process.
_SPAWNED: ContextVar[list[Any] | None] = ContextVar("_hypesocials_mcp_spawned", default=None)


def _install_spawn_probe() -> None:
    """Makes the SDK's spawned process visible to us.

    mcp 2.0's `stdio_client` owns the spawn and yields only streams — the process object never
    surfaces. Rather than re-implement its ~200 lines of shutdown escalation, we wrap the one
    module-level spawn helper it calls (`_create_platform_compatible_process`) so every launch is
    recorded in the caller's sink. That gives us the PID that FR-111's job assignment, the
    `taskkill /T` sweep and every log line need. If a future SDK renames the helper this degrades
    to "no PID" (logged once), never to a broken session.
    """
    original = getattr(_sdk_stdio, "_create_platform_compatible_process", None)
    if original is None or getattr(original, "_hypesocials_probe", False):
        if original is None:
            logger.warning("MCP SDK spawn helper not found; subprocess PIDs will be unavailable")
        return

    async def probe(**kwargs: Any) -> Any:
        process = await original(**kwargs)
        sink = _SPAWNED.get()
        if sink is not None:
            sink.append(process)
        return process

    probe._hypesocials_probe = True  # type: ignore[attr-defined]
    _sdk_stdio._create_platform_compatible_process = probe  # type: ignore[attr-defined]


_install_spawn_probe()


def _build_transport(cfg: ServerConfig, sink: list[Any]) -> Any:
    """Returns the SDK transport (an async CM over the message streams) for this server."""
    if cfg.transport == "stdio":
        command, args = _split_command(cfg.command)
        return stdio_client(
            StdioServerParameters(command=command, args=args, env=_server_env(cfg), cwd=cfg.cwd)
        )
    if cfg.transport == "streamable_http":
        # Named FR-122 fallback (hosted Notion in PAT mode) and the Phase 2 Postiz ops seam. The
        # SDK's HTTP stack is httpx2, not this engine's httpx — deliberate, it is the SDK's own.
        headers = {}
        token = os.environ.get(cfg.auth_env, "") if cfg.auth_env else ""
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return _http_transport(cfg.url, headers)
    raise MCPClientError(f"MCP server {cfg.name!r}: unsupported transport {cfg.transport!r}")


@asynccontextmanager
async def _http_transport(url: str, headers: dict[str, str]) -> AsyncIterator[Any]:
    """Streamable-HTTP transport that also closes the HTTP client it had to create."""
    async with create_mcp_http_client(headers=headers) as http:
        async with streamable_http_client(url, http_client=http) as streams:
            yield streams


def _split_command(command: str) -> tuple[str, list[str]]:
    """Splits a configured command line and pins `python` to THIS virtual environment.

    Windows-quoted paths survive (`posix=False` keeps backslashes intact). The SDK then resolves
    `.cmd`/`.bat`/`.exe`/`.ps1` shims for anything npm-installed (FR-110); pinning `python` to
    `sys.executable` is what keeps the first-party Virlo wrapper inside the run's venv (20 §3).
    """
    if not command.strip():
        raise MCPClientError("stdio MCP server config has an empty `command`")
    tokens = [_unquote(token) for token in shlex.split(command, posix=False)]
    executable, args = tokens[0], tokens[1:]
    if Path(executable).stem.lower() in {"python", "python3", "py"}:
        executable = sys.executable
    return executable, args


def _unquote(token: str) -> str:
    if len(token) > 1 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return token


def _server_env(cfg: ServerConfig) -> dict[str, str]:
    """Builds the per-server environment: only the named variables, joined to values in memory.

    FR-110/NFR-112 — the config file names variables, never values; nothing key-shaped is logged.
    """
    env = dict(cfg.extra_env)
    for name in cfg.env_vars:
        value = os.environ.get(name)
        if value:
            env[name] = value
        else:
            logger.warning("MCP server %s: environment variable %s is not set", cfg.name, name)
    return env


def _hold_job_object(server: str, process: Any | None) -> Any | None:
    """Assigns the subprocess to a kill-on-close job object and returns the handle to hold (FR-111).

    The handle stays referenced for the session's lifetime; closing it (orderly exit) or losing the
    engine process entirely (Task Manager, console X, shutdown) terminates every member of the
    tree. mcp 2.0's stdio client makes its own job for the same reason — this is a second,
    engine-owned membership, so the guarantee does not depend on SDK internals staying put.
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
        handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, pid)
        try:
            win32job.AssignProcessToJobObject(job, handle)
        finally:
            win32api.CloseHandle(handle)
        return job
    except pywintypes.error:
        # The SDK's own job object still covers the tree; degrade loudly, never fail the session.
        logger.warning("MCP server %s: job-object assignment for pid %s failed", server, pid, exc_info=True)
        _close_job_handle(job)
        return None


def _close_job_handle(job: Any | None) -> None:
    if job is None or sys.platform != "win32":
        return
    with suppress(Exception):
        win32api.CloseHandle(job)


async def _safe_close(client: Client) -> None:
    """Closes the client; the SDK's shutdown is shielded and bounded, so this always returns."""
    with suppress(Exception):
        await client.__aexit__(None, None, None)


async def _taskkill_tree(server: str, process: Any | None) -> None:
    """Orderly-exit fallback sweep (FR-111): only runs if a process outlived its job object."""
    if sys.platform != "win32" or process is None or getattr(process, "returncode", 0) is not None:
        return
    pid = getattr(process, "pid", None)
    if pid is None:
        return
    logger.warning("MCP server %s: pid %s survived job close; running taskkill /T sweep", server, pid)
    with suppress(Exception):
        proc = await asyncio.create_subprocess_exec(
            "taskkill", "/F", "/T", "/PID", str(pid),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        async with asyncio.timeout(_TASKKILL_TIMEOUT_S):
            await proc.wait()


def _text_of(result: Any) -> str:
    """Joins a tool result's text blocks — used for unstructured returns and error messages."""
    return "\n".join(block.text for block in result.content if getattr(block, "text", None))


def _row_count(payload: Any) -> int | None:
    """How many rows a structured tool answer carries, for FR-77's result summary.

    Server-agnostic on purpose — this seam serves Virlo, Notion and later Postiz, and none of them
    may be special-cased here. The rule is the longest list in the answer: every row-bearing tool
    in this repo returns its rows as one list beside scalar metadata (`videos`, `slideshows`,
    `monitors`, `groups`), so the longest list IS the row count. `None` means the answer carried
    no list at all — a single record, which is a different thing from zero rows and is logged as
    such rather than as a misleading "0 row(s)".
    """
    if isinstance(payload, Mapping) and set(payload) == {"result"}:
        payload = payload["result"]
    if isinstance(payload, Mapping):
        lengths = [len(value) for value in payload.values() if isinstance(value, list)]
        return max(lengths) if lengths else None
    return len(payload) if isinstance(payload, list) else None


__all__ = [
    "DEFAULT_CALL_TIMEOUT_S", "DEFAULT_STARTUP_TIMEOUT_S", "MCPCallTimeout", "MCPClientError",
    "MCPError", "MCPStartupError", "MCPStartupTimeout", "ServerConfig", "Session", "SessionPool",
    "open_session",
]
