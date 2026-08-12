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
- Only the query parameters in `_QUERY_PARAMS` are ever sent, and they are validated locally
  before the first HTTP call (20 §3, verified live 2026-08-11). `offset` is not among them and
  never can be: Virlo answers it with HTTP 400 while *echoing* a derived `offset` in the response
  body, so the name reads as legitimate and is not.

Do not: print to stdout (it is the JSON-RPC channel), log the API key, or add a sixth tool.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
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

#: Every query parameter this server may put on the wire, checked once inside `_get` rather than at
#: each call site — which is what makes `offset` structurally unsendable rather than merely
#: undocumented. Virlo rejects `offset` as a request parameter with HTTP 400
#: (`{"message":["property offset should not exist"]}`) while returning a *derived* `offset` in its
#: response body, so a future caller reading a response would have every reason to try sending it back.
_QUERY_PARAMS: frozenset[str] = frozenset({"limit", "page", "order_by", "sort"})

#: Virlo's `order_by` enum, verified live 2026-08-11 — `order_by=engagement` returns HTTP 400.
_ORDER_BY: tuple[str, ...] = ("publish_date", "views", "created_at")
_SORT: tuple[str, ...] = ("asc", "desc")

#: Virlo silently clamps any larger `limit` to 100. This server refuses instead — see `_media_params`.
_MAX_LIMIT = 100

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
    """Global daily trend digest: theme name, confidence, video counts, momentum and, per trend,
    its `top_exemplars` — the real posts behind it, with thumbnails, permalinks and view counts.

    Global, not per monitor: these posts belong to whatever niche the trend came from.
    """
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
    """Why one monitored theme is working: analysis text, themes with tactics, timing and threads."""
    agent = await _get(f"/agents/{monitor_id}")
    # RESULTS.md §A: tactics[], per-theme why_it_works/confidence, timing_analysis and the
    # connecting thread — which 20 §3's table attributes to `get_trends` — live HERE, under
    # `analysis_data`, and are the style brief's real raw material. Absent-safe when there is none.
    data = agent.get("analysis_data") or {}
    timing = data.get("timing_analysis") or {}
    return {
        "monitor_id": agent.get("id"),
        "name": agent.get("name"),
        "why_it_works": agent.get("analysis"),
        "intent": agent.get("intent"),
        "keywords": agent.get("keywords") or [],
        "platforms": agent.get("platforms") or [],
        "active": agent.get("active"),
        "last_run_at": agent.get("last_run_at"),
        "themes": [_norm_theme(theme) for theme in data.get("themes") or []],
        "viral_tactics": data.get("viral_tactics") or [],
        "key_highlight": data.get("key_highlight"),
        "connecting_thread": data.get("connecting_thread"),
        "timing_pattern": timing.get("pattern"),
        "peak_hours": timing.get("peak_hours") or [],
    }


@server.tool()
async def get_top_videos(
    monitor_id: str,
    limit: int | None = None,
    page: int | None = None,
    order_by: str | None = None,
    sort: str | None = None,
) -> dict[str, Any]:
    """Top videos for one monitor: engagement, hooks, text overlays, thumbnails and authors.

    Ask for the ranking you want — unsorted, Virlo returns its own insertion order, which is not
    "top" anything. Measured live 2026-08-11 over 50 rows of a 2,039-row monitor: median 2,534
    views unsorted against 1,940,676 for `order_by="views", sort="desc"`, and twice the share of
    rows carrying enriched `intelligence` fields (Virlo enriches its winners first).

    Args:
        monitor_id: Virlo agent id — this project's "monitor".
        limit: rows per page, 1 to 100. 100 is Virlo's maximum; a larger value is refused here
            rather than silently clamped, so a caller never counts rows it did not receive.
        page: 1-indexed, and `limit`-relative — at `limit=100`, page 2 is rows 101-200.
        order_by: one of "publish_date", "views", "created_at".
        sort: "asc" or "desc".
    """
    data = await _get(f"/agents/{monitor_id}/videos", _media_params(limit, page, order_by, sort))
    return {
        "monitor_id": data.get("agent_id"),
        "monitor_name": data.get("agent_name"),
        "total": data.get("total"),
        "videos": [_norm_video(video) for video in data.get("videos") or []],
    }


@server.tool()
async def get_top_slideshows(
    monitor_id: str,
    limit: int | None = None,
    page: int | None = None,
    order_by: str | None = None,
    sort: str | None = None,
) -> dict[str, Any]:
    """Top slideshows for one monitor: panel image URLs, panel texts, hook and narrative arc.

    Same ranking caveat as `get_top_videos`, measured on the same monitor: unsorted median 7,088
    views against 279,757 for `order_by="views", sort="desc"`. Unsorted is insertion order.

    Args:
        monitor_id: Virlo agent id — this project's "monitor".
        limit: rows per page, 1 to 100. 100 is Virlo's maximum; a larger value is refused here
            rather than silently clamped, so a caller never counts rows it did not receive.
        page: 1-indexed, and `limit`-relative — at `limit=100`, page 2 is rows 101-200.
        order_by: one of "publish_date", "views", "created_at".
        sort: "asc" or "desc".
    """
    data = await _get(f"/agents/{monitor_id}/slideshows", _media_params(limit, page, order_by, sort))
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
    """One digest row, including its `top_exemplars` — the real posts behind the trend.

    `/trends/digest` is the only Virlo endpoint that bills ($0.25 a run), and this normalizer used
    to throw its exemplars away: up to five posts per trend, each with a thumbnail, a permalink and
    its view count. The engine decides whether to use them (it offers them as its last-resort
    reference tier, never above a monitor's own posts); the wrapper's job is only to stop
    discarding what the run already paid for.
    """
    trend = row.get("trend") or {}
    momentum = row.get("momentum") or {}
    return {
        "top_exemplars": [_norm_exemplar(post) for post in row.get("top_exemplars") or []],
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


def _norm_exemplar(post: dict[str, Any]) -> dict[str, Any]:
    """One `top_exemplars[]` post, flattened the way `_norm_video` flattens a video.

    Same field names, same shapes — `author` is the handle string rather than the nested object
    Virlo sends — so an exemplar reads like every other post in this codebase instead of starting
    a second vocabulary for the same idea. `thumbnail_url` is ONE still per post, exactly like a
    video's: it is a frame, never a panel set.
    """
    author = post.get("author") or {}
    return {
        "post_id": post.get("video_id"),
        "url": post.get("url"),
        "platform": post.get("platform"),
        "views": post.get("views"),
        "thumbnail_url": post.get("thumbnail_url"),
        "publish_date": post.get("publish_date"),
        "author": author.get("username") if isinstance(author, dict) else author,
    }


def _norm_theme(theme: dict[str, Any]) -> dict[str, Any]:
    """One `analysis_data.themes[]` entry, kept to the six fields the topic split consumes.

    `evidence_video_ids` (W2 wire-in, FR-293): activates `virlo._allocate`'s evidence pre-pass —
    posts Virlo itself filed under a theme are claimed by that topic before the stride deal
    shares out the rest (measured on the fixture corpus: 12 of 154 ids resolve in one page).
    """
    return {key: theme.get(key)
            for key in ("name", "tactics", "why_it_works", "confidence", "video_count",
                        "evidence_video_ids")}


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
        # Virlo's own classification of the winner's opening move. The copywriter is asked to
        # DERIVE a hook pattern the source has already labelled (`tutorial_promise`, `question`),
        # so these three travel as the source's own vocabulary. Per row, never per agent: an agent
        # reporting `data_intelligence_enabled: false` still carries them on rows enriched before
        # the flag flipped (34 of 50 measured on exactly such an agent).
        "hook_type": intelligence.get("hook_type"),
        "visual_hook_type": intelligence.get("visual_hook_type"),
        "emotional_tone": intelligence.get("emotional_tone"),
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
        # The same three labels as `_norm_video`, read per row and absent-safe. Slideshows carry
        # no `visual_hook_type` in any live response seen so far — it stays here because the field
        # is Virlo's to add, and a caller that reads one shape for both media kinds cannot drift.
        "hook_type": intelligence.get("hook_type"),
        "visual_hook_type": intelligence.get("visual_hook_type"),
        "emotional_tone": intelligence.get("emotional_tone"),
        "intelligence_status": show.get("intelligence_status"),
    }


# ---------------------------------------------------------------------------------------------
# Query parameters: validated here, locally, before anything is spent on an HTTP round trip.
# ---------------------------------------------------------------------------------------------


def _media_params(
    limit: int | None, page: int | None, order_by: str | None, sort: str | None
) -> dict[str, Any]:
    """Validates the media tools' query parameters and returns exactly what may be sent.

    Validating locally is the point (FR-119). A client typo has to come back as a *classified*
    MCP error naming the parameter and its allowed values, not as an opaque upstream 400 whose
    prose the caller would have to parse — and not after a network round trip that told Virlo
    nothing useful. The enum lives here rather than in a `Literal` annotation on the tools for the
    same reason: a `Literal` would hand enforcement to the SDK's pydantic argument validation,
    which raises its own error shape and would put a bad argument outside the four FR-119 classes.

    A bad argument is raised as `VirloNotFoundError` — the honest fit of those four. It is the
    non-retryable caller-fault class: `VirloServerError` and `VirloRateLimitError` are `retryable`,
    so an engine backoff would repeat an identical doomed call until the budget ran out, and both
    would blame Virlo for our own argument; `VirloAuthError` names the wrong secret entirely.
    `_classify` below already routes Virlo's own "that is not an id" 400 to this class, so
    "the caller named something Virlo has no such thing of" is already what it means.

    `limit` above 100 is REFUSED, never clamped, following FR-285's rule for `--history-days`
    (`30-configuration-and-run.md`): a silently corrected typo hides exactly the mistake the check
    exists to surface. The reasoning is if anything stronger for a machine caller than a human one
    — Virlo *does* clamp silently, so a caller that asked for 500 and quietly got 100 would go on
    to page, count and report a funnel against a number it never received.
    """
    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = _bounded("limit", limit, 1, _MAX_LIMIT)
    if page is not None:
        params["page"] = _bounded("page", page, 1, None)  # 1-indexed; Virlo documents no upper page
    if order_by is not None:
        params["order_by"] = _one_of("order_by", order_by, _ORDER_BY)
    if sort is not None:
        params["sort"] = _one_of("sort", sort, _SORT)
    return params


def _one_of(name: str, value: str, allowed: tuple[str, ...]) -> str:
    """An enum check whose message is the documentation — a typo must diagnose itself."""
    if value not in allowed:
        raise mcp_error(
            VirloNotFoundError,
            f"{name}={value!r} is not supported; allowed values are {', '.join(allowed)}",
        )
    return value


def _bounded(name: str, value: int, low: int, high: int | None) -> int:
    """An integer range check, refusing (never clamping) anything outside `low`..`high`."""
    # `bool` is a subclass of `int` in Python, so without this `limit=True` would sail through as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise mcp_error(VirloNotFoundError, f"{name}={value!r} is not an integer")
    if value < low or (high is not None and value > high):
        allowed = f"{low} to {high}" if high is not None else f"{low} or greater"
        raise mcp_error(
            VirloNotFoundError, f"{name}={value!r} is out of range; allowed values are {allowed}"
        )
    return value


# ---------------------------------------------------------------------------------------------
# REST access: one bounded-retry GET, one status->class translation (FR-119/120).
# ---------------------------------------------------------------------------------------------


async def _get(path: str, params: Mapping[str, Any] | None = None) -> Any:
    """GETs `path` under the `data` envelope, retrying only what a retry can fix.

    `params` carries already-validated query parameters (`_media_params`); the three tools that
    take no arguments pass none. Every key is screened against `_QUERY_PARAMS` here, at the single
    exit to Virlo, rather than trusted per call site — that screen is what makes `offset`
    unsendable by construction: it is not in the set, and there is no other way out of this module.

    Raises:
        MCPError: carrying one of the four FR-119 class codes.
    """
    query = {key: value for key, value in (params or {}).items() if value is not None}
    unsendable = sorted(set(query) - _QUERY_PARAMS)
    if unsendable:  # unreachable from any tool signature, so this is our bug, not the caller's
        raise mcp_error(
            VirloServerError,
            f"{path}: refusing to send query parameter(s) Virlo does not accept: {', '.join(unsendable)}",
        )
    deadline = monotonic() + _budget_s()
    attempts = _max_attempts()
    failure: VirloToolError = VirloServerError(f"{path}: no attempt completed")
    for attempt in range(1, attempts + 1):
        try:
            response = await _http().get(path, params=query or None)
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
