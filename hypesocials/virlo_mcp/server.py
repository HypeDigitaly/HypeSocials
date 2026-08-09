"""The five-tool Virlo MCP stdio server (20 §3, FR-118/119/120/245, NFR-11/110).

Purpose: translate Virlo's REST API into exactly five MCP tools and nothing more. It runs as a
local stdio subprocess in this same virtual environment, spawned by `mcp_client` from the
`mcp_servers.virlo` config entry. Engine code never calls `api.virlo.ai` directly (NFR-11).

Public API: the five tools of `TOOL_NAMES`, plus `main()` for `python -m hypesocials.virlo_mcp`.

Invariants:
- No cache: every call re-hits Virlo. No ranking, no filtering, no derivation — field
  normalization only (unwrap the `data` envelope, flatten Virlo's `intelligence`/`author`
  sub-objects, rename `agent`->`monitor` per this project's vocabulary). Select owns judgement.
- HTTP status maps to one of four distinguishable MCP error classes (FR-119).
- Bounded retry with exponential backoff on 429/5xx/network only — never on auth or not-found
  (FR-120/NFR-14). Attempt cap is `VIRLO_HTTP_MAX_ATTEMPTS` (default 3), which the engine hands
  over as the per-server env dict from the config key `http_max_attempts`; the whole retry loop is
  further bounded by `VIRLO_HTTP_BUDGET_S` (default 25 s) so it can never outlast the caller's
  `mcp_call_timeout_s` (30 s) and turn a bounded retry into a hung call.

Do not: print to stdout (it is the JSON-RPC channel), log the API key, or add a sixth tool.
"""

from __future__ import annotations

import asyncio
import logging
import os
from time import monotonic
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

from . import (
    VirloAuthError,
    VirloNotFoundError,
    VirloRateLimitError,
    VirloServerError,
    VirloToolError,
    mcp_error,
)

BASE_URL = "https://api.virlo.ai/v1"  # verified against api.virlo.ai/openapi.json (2026-08-09)
_REQUEST_TIMEOUT_S = 20.0
_BACKOFF_BASE_S = 0.5

logger = logging.getLogger("hypesocials.virlo_mcp")

server: MCPServer = MCPServer(
    name="virlo",
    instructions="Read-only Virlo trend intelligence: monitors, their analysis, top videos and slideshows.",
    version="0.1.0",
    log_level="WARNING",  # this server's stderr lands in the engine's console: warnings and worse only
)

_client: httpx.AsyncClient | None = None


# ---------------------------------------------------------------------------------------------
# Tools — exactly five (FR-118). Docstrings are what the MCP client sees as tool descriptions.
# ---------------------------------------------------------------------------------------------


@server.tool()
async def get_trends() -> dict[str, Any]:
    """Global daily trend digest: theme name, confidence, video counts and momentum per trend."""
    groups = await _get("/trends/digest")
    return {
        "groups": [
            {
                "id": group.get("id"),
                "title": group.get("title"),
                "region": group.get("region"),
                "local_date": group.get("local_date"),
                "trends": [_norm_digest_trend(row) for row in group.get("trends") or []],
            }
            for group in groups or []
        ]
    }


@server.tool()
async def get_monitor_analysis(monitor_id: str) -> dict[str, Any]:
    """Why one monitored theme is working: the monitor's own analysis text, intent and keywords."""
    agent = await _get(f"/agents/{monitor_id}")
    return {
        "monitor_id": agent.get("id"),
        "name": agent.get("name"),
        "why_it_works": agent.get("analysis"),
        "intent": agent.get("intent"),
        "keywords": agent.get("keywords") or [],
        "platforms": agent.get("platforms") or [],
        "active": agent.get("active"),
        "last_run_at": agent.get("last_run_at"),
    }


@server.tool()
async def get_top_videos(monitor_id: str, limit: int | None = None) -> dict[str, Any]:
    """Top videos for one monitor: engagement, hooks, text overlays, thumbnails and authors."""
    data = await _get(f"/agents/{monitor_id}/videos", limit)
    return {
        "monitor_id": data.get("agent_id"),
        "monitor_name": data.get("agent_name"),
        "total": data.get("total"),
        "videos": [_norm_video(video) for video in data.get("videos") or []],
    }


@server.tool()
async def get_top_slideshows(monitor_id: str, limit: int | None = None) -> dict[str, Any]:
    """Top slideshows for one monitor: panel image URLs, panel texts, hook and narrative arc."""
    data = await _get(f"/agents/{monitor_id}/slideshows", limit)
    return {
        "monitor_id": data.get("agent_id"),
        "monitor_name": data.get("agent_name"),
        "total": data.get("total"),
        "slideshows": [_norm_slideshow(show) for show in data.get("slideshows") or []],
    }


@server.tool()
async def list_monitors() -> dict[str, Any]:
    """Every monitor this API key can see, as id + human-readable name (setup aid, FR-245)."""
    data = await _get("/agents")
    return {
        "monitors": [
            {"id": agent.get("id"), "name": agent.get("name")} for agent in data.get("agents") or []
        ]
    }


# ---------------------------------------------------------------------------------------------
# Field normalization — reshaping only: no derivation, no ranking, no filtering (FR-118).
# ---------------------------------------------------------------------------------------------


def _norm_digest_trend(row: dict[str, Any]) -> dict[str, Any]:
    """One digest row. `top_exemplars` is dropped: the digest only enriches context (20 §3)."""
    trend = row.get("trend") or {}
    momentum = row.get("momentum") or {}
    return {
        "name": trend.get("name"),
        "description": trend.get("description"),
        "trend_type": trend.get("trend_type"),
        "ranking": row.get("ranking"),
        "confidence": row.get("global_confidence"),
        "video_count": row.get("velocity_today_count"),
        "median_views": row.get("velocity_median_views"),
        "momentum_score": momentum.get("score"),
        "momentum_status": momentum.get("status"),
        "views_per_hour": momentum.get("views_per_hour"),
        "detected_at": row.get("detected_at"),
        "last_seen_at": row.get("last_seen_at"),
        "exemplar_count": row.get("exemplar_count"),
    }


def _norm_video(video: dict[str, Any]) -> dict[str, Any]:
    intelligence = video.get("intelligence") or {}
    author = video.get("author") or {}
    return {
        "id": video.get("id"),
        "url": video.get("url"),
        "platform": video.get("platform"),
        "description": video.get("description"),
        "thumbnail_url": video.get("thumbnail_url"),
        "publish_date": video.get("publish_date"),
        "views": video.get("views"),
        "likes": video.get("likes"),
        "shares": video.get("shares"),
        "comments": video.get("comments"),
        "bookmarks": video.get("bookmarks"),
        "author_username": author.get("username"),
        "author_followers": author.get("followers"),
        "hashtags": video.get("hashtags") or [],
        "hook_text": intelligence.get("hook_text"),
        "text_overlay_content": intelligence.get("text_overlay_content"),
        "summary": intelligence.get("summary"),
        # Frame-composition signals the coherent-reference-set builder screens on (FR-91, T2.1):
        # face-dominant refs are avoided, text-dense/UI-busy ones are deprioritised. Like every
        # other `intelligence` field they are absent (None) until `intelligence_status == "ready"`.
        "has_face_visible": intelligence.get("has_face_visible"),
        "has_text_overlay": intelligence.get("has_text_overlay"),
        "visual_complexity": intelligence.get("visual_complexity"),
        "intelligence_status": video.get("intelligence_status"),
    }


def _norm_slideshow(show: dict[str, Any]) -> dict[str, Any]:
    intelligence = show.get("intelligence") or {}
    author = show.get("author") or {}
    panels = sorted(show.get("images") or [], key=lambda image: image.get("position") or 0)
    image_urls = [image["image_url"] for image in panels if image.get("image_url")]
    return {
        "id": show.get("id"),
        "url": show.get("url"),
        "platform": show.get("platform"),
        "description": show.get("description"),
        "thumbnail_url": show.get("thumbnail_url"),
        "publish_date": show.get("publish_date"),
        "views": show.get("views"),
        "likes": show.get("likes"),
        "shares": show.get("shares"),
        "comments": show.get("comments"),
        "bookmarks": show.get("bookmarks"),
        "author_username": author.get("username"),
        "author_followers": author.get("followers"),
        "hashtags": show.get("hashtags") or [],
        "image_urls": image_urls,
        "panel_count": len(image_urls),
        "panel_texts": intelligence.get("panel_texts") or [],
        "hook_text": intelligence.get("hook_text"),
        "narrative_arc": intelligence.get("narrative_arc"),
        "text_density": intelligence.get("text_density"),
        "summary": intelligence.get("summary"),
        "intelligence_status": show.get("intelligence_status"),
    }


# ---------------------------------------------------------------------------------------------
# REST access: one bounded-retry GET, one status->class translation (FR-119/120).
# ---------------------------------------------------------------------------------------------


async def _get(path: str, limit: int | None = None) -> Any:
    """GETs `path` under the `data` envelope, retrying only what a retry can fix.

    Raises:
        MCPError: carrying one of the four FR-119 class codes.
    """
    params = {"limit": limit} if limit else None
    deadline = monotonic() + _budget_s()
    attempts = _max_attempts()
    failure: VirloToolError = VirloServerError(f"{path}: no attempt completed")
    for attempt in range(1, attempts + 1):
        try:
            response = await _http().get(path, params=params)
        except httpx.HTTPError as exc:  # connect failure, read timeout, protocol error
            failure = VirloServerError(f"{path}: {type(exc).__name__}")
        else:
            if response.is_success:
                return _unwrap(response, path)
            failure = _classify(response, path)
            if not failure.retryable:  # auth / not-found: never retried (FR-120)
                raise mcp_error(type(failure), str(failure), http_status=response.status_code)
        delay = _BACKOFF_BASE_S * 2 ** (attempt - 1)
        if attempt == attempts or monotonic() + delay >= deadline:
            break
        logger.warning("virlo %s attempt %d/%d failed (%s); retrying", path, attempt, attempts, failure)
        await asyncio.sleep(delay)
    raise mcp_error(type(failure), f"{failure} (after {attempts} attempts)")


def _classify(response: httpx.Response, path: str) -> VirloToolError:
    """Maps a Virlo HTTP status onto its MCP error class (FR-119)."""
    status = response.status_code
    detail = f"{path}: HTTP {status}"
    if status in (401, 403):
        return VirloAuthError(f"{detail} — check VIRLO_API_KEY")
    if status == 429:
        return VirloRateLimitError(detail)
    if status == 404 or (status == 400 and "uuid" in response.text.lower()):
        return VirloNotFoundError(f"{detail} — unknown monitor id")
    return VirloServerError(detail)


def _unwrap(response: httpx.Response, path: str) -> Any:
    """Strips Virlo's `{"data": ...}` envelope; a body that isn't JSON is a server-class failure."""
    try:
        payload = response.json()
    except ValueError as exc:
        raise mcp_error(VirloServerError, f"{path}: response was not JSON ({exc})") from exc
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _http() -> httpx.AsyncClient:
    """The one shared async client, built on first use so it binds to the running event loop."""
    global _client
    if _client is None:
        key = os.environ.get("VIRLO_API_KEY", "")
        if not key:
            raise mcp_error(VirloAuthError, "VIRLO_API_KEY is not set in this server's environment")
        _client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {key}"},  # the key lives in this header and nowhere else
            timeout=_REQUEST_TIMEOUT_S,
        )
    return _client


def _max_attempts() -> int:
    return max(1, _env_int("VIRLO_HTTP_MAX_ATTEMPTS", 3))


def _budget_s() -> float:
    return float(max(1, _env_int("VIRLO_HTTP_BUDGET_S", 25)))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        logger.warning("%s is not an integer; using %d", name, default)
        return default


def main() -> None:
    """Entry point for `python -m hypesocials.virlo_mcp` — serves the five tools over stdio."""
    # httpx logs every request at INFO with its full URL; clamp it so a run's console stays readable
    # (the key is never in a URL — it travels in the Authorization header only, D30/NFR-112).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    server.run("stdio")
