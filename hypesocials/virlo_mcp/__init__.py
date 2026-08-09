"""Virlo MCP wrapper — public surface: the tool names and the four failure classes (20 §3).

Purpose: HypeSocials talks to Virlo through exactly one seam, an MCP stdio server this project
ships (`python -m hypesocials.virlo_mcp`, D21/NFR-11). This module is what the *engine* side
imports: the tool contract it may call, and the error classes it branches on. The server itself
lives in `server.py` and is never imported by engine code.

Public API:
    TOOL_NAMES                  — the five tools, exactly (FR-118/245)
    VirloToolError + subclasses — auth / rate-limit / not-found / server-error (FR-119)
    translate(exc)              — turn the `MCPError` a tool call raised into its typed class
    mcp_error(cls, message)     — server-side constructor for the same wire error

Invariants:
- Four distinguishable classes, carried as JSON-RPC error codes, so no caller parses error text.
- `retryable` is the whole retry rule: auth and not-found are never retried, by anyone (FR-120).
- The wrapper owns the bounded retry (`http_max_attempts`); the engine must NOT retry on top of it.

Do not: add a sixth tool, cache anything, or rank/filter — the wrapper normalizes fields and
nothing else (FR-118); Select owns judgement.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mcp import MCPError

#: Application-defined JSON-RPC error codes, one per FR-119 class. Outside the -32768..-32000
#: range the protocol reserves, so an SDK code can never be mistaken for a Virlo one.
ERROR_AUTH = -33001
ERROR_RATE_LIMIT = -33002
ERROR_NOT_FOUND = -33003
ERROR_SERVER = -33004

#: The complete tool contract (FR-118). Fixed at code level — never config-mapped (FR-116 withdrawn).
TOOL_NAMES: tuple[str, ...] = (
    "get_trends",
    "get_monitor_analysis",
    "get_top_videos",
    "get_top_slideshows",
    "list_monitors",
)


class VirloToolError(RuntimeError):
    """Base of the four distinguishable Virlo failure classes (FR-119)."""

    code: ClassVar[int] = ERROR_SERVER
    retryable: ClassVar[bool] = False


class VirloAuthError(VirloToolError):
    """401/403 — a retry cannot fix credentials; log naming `VIRLO_API_KEY` (20 §10)."""

    code: ClassVar[int] = ERROR_AUTH


class VirloRateLimitError(VirloToolError):
    """429 — bounded backoff inside the wrapper; persistent limiting surfaces as repeated no-data."""

    code: ClassVar[int] = ERROR_RATE_LIMIT
    retryable: ClassVar[bool] = True


class VirloNotFoundError(VirloToolError):
    """404 (and Virlo's 400 "not a monitor id") — a bad id, never retried."""

    code: ClassVar[int] = ERROR_NOT_FOUND


class VirloServerError(VirloToolError):
    """5xx, connect failure, or read timeout against Virlo — transient, so retried while budget lasts."""

    code: ClassVar[int] = ERROR_SERVER
    retryable: ClassVar[bool] = True


_BY_CODE: dict[int, type[VirloToolError]] = {
    cls.code: cls for cls in (VirloAuthError, VirloRateLimitError, VirloNotFoundError, VirloServerError)
}


def translate(exc: BaseException) -> BaseException:
    """Client side: returns the typed Virlo error for an `MCPError` a tool raised, else `exc`.

        try:
            data = await session.call_tool("get_top_videos", {"monitor_id": mid})
        except MCPError as exc:
            raise translate(exc) from exc      # -> VirloAuthError / VirloRateLimitError / ...
    """
    cls = _BY_CODE.get(getattr(exc, "code", 0))
    if cls is None:
        return exc
    return cls(str(exc))


def mcp_error(cls: type[VirloToolError], message: str, **data: Any) -> MCPError:
    """Server side: the wire form of a Virlo failure class — a protocol error, not a tool result."""
    return MCPError(cls.code, message, data or None)


__all__ = [
    "ERROR_AUTH", "ERROR_NOT_FOUND", "ERROR_RATE_LIMIT", "ERROR_SERVER", "TOOL_NAMES",
    "VirloAuthError", "VirloNotFoundError", "VirloRateLimitError", "VirloServerError",
    "VirloToolError", "mcp_error", "translate",
]
