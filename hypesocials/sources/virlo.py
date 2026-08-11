"""Virlo adapter — MCP tool calls in, ranked `TrendItem`s with coherent reference sets out.

Callers import `hypesocials.sources`, never this module. Behind that facade:

- **Join rule (20 §3, corrected by spikes/RESULTS.md §A):** one item per configured monitor id.
  `get_monitor_analysis` gives name, `why_it_works`, themes/tactics, timing and connecting thread;
  `get_top_videos`/`get_top_slideshows` give media, hooks, panel texts and engagement for that same
  monitor; the global `get_trends` digest only enriches `cross_monitor_context` and creates no
  items. §A swaps the PRD table's digest vs monitor-analysis ownership — shapes follow RESULTS.md,
  behaviour follows the PRD.
- **Strength (FR-5):** views .35, median views .15, velocity .30, confidence .20, each min-max
  normalized inside the run's candidate pool. Hardcoded weights, by PRD decision.
- **Coherent reference sets (FR-91):** every group is ONE source — a single slideshow's panels (in
  `position` order) or one creator's thumbnails — built as `ReferenceSet` units, ALL of them.
- **Post-level freshness (FR-7):** `used_posts` picks the freshest unused set and EVERY field the
  creative is shaped by comes from that set; the same map picks the reel's motion reference (FR-24,
  three tiers, best-effort — tier 3 repeats a source rather than lose a paid reel).
- **Per-image download (FR-32/33/247):** independent per image; a dead URL drops that image only.

Invariants: no direct `api.virlo.ai` call (NFR-11); no retry on top of the wrapper's bounded retry
(FR-120) — only CDN downloads retry here; the digest is the ONLY metered call ($0.25, §A), so
`include_digest=False` keeps a preview at $0; `intelligence.*` is optional (~70% miss) and an item
stays usable without it; reels are OFF in W2 — `winning_video_url` is data, and no yt-dlp activity
happens here (that is W4's `video_ref.py`).

Do not: rank or filter for Select (it owns verdicts); mutate `models.py`; log an API key.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import statistics
import tempfile
from collections.abc import Callable, Collection, Mapping, Sequence
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from hypesocials.config import Config
from hypesocials.mcp_client import MCPClientError, MCPError, ServerConfig, Session, SessionPool
from hypesocials.models import ReferenceSet, TrendItem
from hypesocials.util import slugify
from hypesocials.virlo_mcp import VirloToolError, translate

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hypesocials.outputs import LogWriter

logger = logging.getLogger(__name__)

SERVER_NAME = "virlo"
_MEDIA_LIMIT = 50  # Virlo's own page size; one page is more than a run can use
_MIN_PANELS = 3  # RESULTS.md §A: 14/50 slideshows are single-image, so one panel isn't a set
_MIN_THUMBS = 2  # FR-91 wants 2-3 refs; a lone thumbnail is a last resort, not a coherent set
_MAX_EXEMPLARS = 5  # FR-100 wants 3-5 verbatim source hooks
_MAX_TACTICS, _MAX_THEMES, _WHY_MAX_CHARS, _CONTEXT_MAX_CHARS = 12, 3, 1200, 600  # §A: 9 themes deep
_DIGEST_ROWS, _DOWNLOAD_TIMEOUT_S, _MAX_PARALLEL, _BACKOFF_S = 8, 20.0, 8, 0.5
_TEMP_PREFIX = "hypesocials-refs-"
_SUFFIXES = (".webp", ".jpg", ".jpeg", ".png", ".gif")
#: FR-5's weights — stated in the PRD so the operator signed off on them, never a config knob.
_WEIGHTS = {"total_views": 0.35, "median_views": 0.15, "velocity": 0.30, "confidence": 0.20}
#: FR-91's frame screen. Unknown stays neutral: `intelligence.*` is absent unless
#: `intelligence_status == "ready"`, and sinking ~70% of live media would be worse than not screening.
_COMPLEXITY = {"low": 1.0, "simple": 1.0, "minimal": 1.0, "medium": 0.5, "moderate": 0.5,
               "high": 0.0, "complex": 0.0, "very_high": 0.0, "busy": 0.0}

_CACHE: dict[str, Path] = {}  # reference URL -> the local file this run downloaded it to
_CACHE_DIR: Path | None = None
_CACHE_DIR_OWNED = False


# ------------------------------------------------------------------------------- public API

async def fetch(cfg: Config, *, cache_dir: Path | None = None, log: LogWriter | None = None,
                include_digest: bool = True, used_posts: Collection[str] | None = None,
                say: Callable[[str], None] | None = None) -> list[TrendItem]:
    """Collect every configured monitor into ranked, reference-bearing trend items.

    Args:
        cfg: the loaded run config (`sources.*` and `mcp_servers.virlo` are what matter).
        cache_dir: where reference images land; a private temp folder when omitted. The caller
            owns cleanup and calls `cleanup()` on every exit path (FR-249).
        log: the run's LogWriter, so every degrade lands in run.log/events.jsonl.
        include_digest: `False` skips `get_trends`, the one metered call, leaving
            `cross_monitor_context` empty — how a preview stays honestly at $0.
        used_posts: post ids already used inside the `trend_history_days` window (FR-7) — a set,
            or the `posts` mapping itself, since iterating it yields its keys. Omitted means
            "nothing is used yet", which is also what a history without `posts` means.
        say: the console seam, for the one refusal an operator must not have to find in run.log.

    Returns:
        Items strongest first. A failed monitor contributes nothing and is logged; an empty list
        means Collect found nothing, and the caller decides whether that aborts the run.
    """
    ids = list(dict.fromkeys(str(i).strip() for i in cfg.sources.virlo_monitor_ids if str(i).strip()))
    if not ids:
        _warn(log, "virlo_no_monitors", "sources.virlo_monitor_ids is empty — run --list-monitors",
              say=say)
        return []
    used = frozenset(str(post) for post in used_posts or ())
    size = max(1, min(cfg.sources.virlo_session_pool, len(ids) + (1 if include_digest else 0)))
    async with SessionPool(_server(cfg), size, log=log) as pool:
        jobs: list[Any] = [_monitor_item(pool, mid, cfg, log, used) for mid in ids]
        if include_digest:
            jobs.append(_digest(pool, log))
        results = await asyncio.gather(*jobs, return_exceptions=True)

    items: list[TrendItem] = []
    context, confidences = "", {}
    for label, result in zip([*ids, "digest"], results, strict=True):
        if isinstance(result, asyncio.CancelledError):
            raise result
        if isinstance(result, BaseException):  # per-monitor degrade, never all-or-nothing (20 §10)
            _warn(log, "virlo_monitor_failed", f"monitor {label} returned no data: {result}",
                  monitor_id=label, error=type(result).__name__)
        elif isinstance(result, TrendItem):
            items.append(result)
        elif isinstance(result, tuple):
            context, confidences = result
    for item in items:  # global digest first, then this monitor's own timing/thread context
        item.cross_monitor_context = " · ".join(
            part for part in (context, item.cross_monitor_context) if part)
        if item.confidence is None:  # themes lead (FR-5 v1.6.4); the digest is the empty fallback
            item.confidence = _match_confidence(item.name, confidences)
    await _download_references(items, cfg, cache_dir, log)
    _score(items)
    items.sort(key=lambda item: item.strength, reverse=True)
    return items


async def list_monitors(cfg: Config) -> list[tuple[str, str]]:
    """Every monitor this key can see as `(id, name)` — the $0 setup aid behind `--list-monitors`
    (FR-245). Opens one session, enters no pipeline stage."""
    async with SessionPool(_server(cfg), 1) as pool, pool.acquire() as session:
        payload = await _call(session, "list_monitors")
    return [(str(row.get("id") or ""), str(row.get("name") or "")) for row in payload.get("monitors") or []]


def reference_paths(urls: Sequence[str]) -> list[Path]:
    """Local files behind already-downloaded reference URLs, in the order asked for.

    Analysis sends bytes (FR-40, downscaled per FR-93); renders send the URL itself, because Kie
    accepts Virlo's CDN directly (RESULTS.md §B). Unknown URLs are absent from the result.
    """
    return [_CACHE[url] for url in urls if url in _CACHE]


def cleanup() -> None:
    """Delete this run's downloaded references (FR-249). Never touches `output/`, never raises."""
    global _CACHE_DIR, _CACHE_DIR_OWNED
    for path in _CACHE.values():
        with suppress(OSError):
            path.unlink(missing_ok=True)
    if _CACHE_DIR_OWNED and _CACHE_DIR is not None:
        with suppress(OSError):
            _CACHE_DIR.rmdir()
    _CACHE.clear()
    _CACHE_DIR, _CACHE_DIR_OWNED = None, False


# --------------------------------------------------------------------------- MCP collection

def _server(cfg: Config) -> ServerConfig:
    """The wrapper's launch record; `http_max_attempts` travels as its retry budget (FR-120)."""
    return ServerConfig.from_mapping(
        SERVER_NAME,
        cfg.mcp_servers.servers.get(SERVER_NAME, {"command": "python -m hypesocials.virlo_mcp"}),
        startup_timeout_s=float(cfg.mcp_servers.startup_timeout_s),
        call_timeout_s=float(cfg.mcp_servers.call_timeout_s),
        extra_env={"VIRLO_HTTP_MAX_ATTEMPTS": str(cfg.models.http_max_attempts)},
    )


async def _monitor_item(pool: SessionPool, monitor_id: str, cfg: Config,
                        log: LogWriter | None = None,
                        used: Collection[str] = frozenset()) -> TrendItem:
    """One monitor's three calls on one borrowed session (FR-115 serializes them anyway)."""
    args = {"monitor_id": monitor_id, "limit": _MEDIA_LIMIT}
    async with pool.acquire() as session:
        analysis = await _call(session, "get_monitor_analysis", {"monitor_id": monitor_id})
        videos = await _call(session, "get_top_videos", args)
        shows = await _call(session, "get_top_slideshows", args)
    clips, panels = videos.get("videos") or [], shows.get("slideshows") or []
    item = _build_item(monitor_id, analysis, clips, panels, cfg, used=used, log=log)
    _payload_event(log, item, len(clips), len(panels))
    return item


def _payload_event(log: LogWriter | None, item: TrendItem, videos: int, slideshows: int) -> None:
    """FR-77's per-trend Virlo payload summary, written once at join time: key, name, video count
    and the top engagement stats — enough to tell a thin trend from a strong one in run.log."""
    if log is None:
        return
    newest = item.newest_published_at.date().isoformat() if item.newest_published_at else "-"
    likes = int(item.engagement.get("likes", 0))
    log.event("virlo_payload",
              f"{item.name}: {videos} videos, {slideshows} slideshows, {item.total_views:,} views, "
              f"{likes:,} likes, newest {newest}",
              trend=item.history_key, name=item.name, videos=videos, slideshows=slideshows,
              views=item.total_views, likes=likes, newest_published=newest)


async def _digest(pool: SessionPool, log: LogWriter | None) -> tuple[str, dict[str, float]]:
    """Cross-monitor context plus any confidence values the daily digest carries.

    THE ONLY METERED VIRLO CALL ($0.25/run, RESULTS.md §A). It creates no trend items (20 §3) and
    its failure is never fatal — the run simply carries no cross-monitor context.
    """
    try:
        async with pool.acquire() as session:
            payload = await _call(session, "get_trends")
    except (MCPClientError, MCPError, VirloToolError, ValueError) as exc:
        _warn(log, "virlo_digest_failed", f"trend digest unavailable: {exc}", error=type(exc).__name__)
        return "", {}
    rows = [row for group in payload.get("groups") or [] for row in group.get("trends") or []]
    rows.sort(key=lambda row: _num(row.get("ranking")) or 10_000)
    lines, confidences = [], {}
    for row in rows[:_DIGEST_ROWS]:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        parts = [f"#{row['ranking']} {name}" if row.get("ranking") else name]
        parts += [str(row["momentum_status"])] if row.get("momentum_status") else []
        parts += [f"{int(_num(row['views_per_hour'])):,}/h"] if row.get("views_per_hour") else []
        lines.append(" ".join(parts))
        if row.get("confidence") is not None:
            confidences[slugify(name, 0)] = float(_num(row["confidence"]))
    return ("Global trend digest today: " + "; ".join(lines) if lines else ""), confidences


async def _call(session: Session, tool: str, args: dict[str, Any] | None = None) -> Mapping[str, Any]:
    """One tool call, its wire error translated into the typed class callers branch on (FR-119)."""
    try:
        payload = await session.call_tool(tool, args or {})
    except MCPError as exc:
        raise translate(exc) from exc
    if isinstance(payload, str):
        with suppress(ValueError):
            payload = json.loads(payload)
    if isinstance(payload, Mapping) and set(payload) == {"result"}:
        payload = payload["result"]
    return payload if isinstance(payload, Mapping) else {}


# --------------------------------------------------------------------------- normalization

def _build_item(monitor_id: str, analysis: Mapping[str, Any], videos: list[Any], shows: list[Any],
                cfg: Config, *, used: Collection[str] = frozenset(),
                log: LogWriter | None = None) -> TrendItem:
    """Assemble one normalized trend item from this monitor's three tool returns (20 §3).

    One `ReferenceSet` is chosen here — the freshest unused candidate (FR-7) — and every field the
    creative is shaped by is read off THAT set, so a second run against the same monitor changes
    the headline, the panel rhythm and the layout, not only three CDN urls.
    """
    videos, shows = _dedupe(videos), _dedupe(shows)  # RESULTS.md §A: the live arrays repeat posts
    name = str(analysis.get("name") or "").strip() or f"monitor {monitor_id}"
    chosen, ordered, fresh = _pick_set(_reference_groups(videos, shows, cfg, monitor_id), used)
    media = [*videos, *shows]
    views = [_num(entry.get("views")) for entry in media]
    motion = _pick_motion([(row, _post_id(row, monitor_id, index))
                           for index, row in enumerate(videos, start=len(shows))], chosen, used)
    why, tactics, context, confidence = _analysis_fields(analysis)
    item = TrendItem(
        history_key=str(monitor_id) or slugify(name, 0),  # agent id, else the name slug (20 §3)
        monitor_id=str(monitor_id),
        name=name,
        confidence=confidence,  # FR-5 v1.6.4: mean of the consumed themes' confidence
        why_it_works=why,
        tactics=tactics,
        cross_monitor_context=context,  # `fetch` prefixes the global digest onto this
        hook_texts=_texts(media, "hook_text"),
        text_overlay_contents=_texts(videos, "text_overlay_content"),
        panel_texts=list(chosen.panel_texts),
        narrative_arc=chosen.narrative_arc,
        text_density=chosen.text_density,
        video_descriptions=_texts(media, "description"),
        reference_groups=[list(candidate.urls) for candidate in ordered],  # group 0 = the chosen set
        is_slideshow=chosen.is_slideshow,  # drives FR-90's carousel affinity
        text_only=not ordered,  # provisional: a dead CDN URL can still empty this (FR-247)
        winning_video_url=str(motion[0]["url"]) if motion else None,
        winning_video_post_id=motion[1] if motion else None,
        # FR-7 is already enforced when this is non-empty; empty means the monitor-level window
        # decides (a `text_only` item, or a monitor whose every candidate set is used up).
        chosen_post_ids=chosen.post_ids if fresh else (),
        virlo_url=chosen.source_url or (str(motion[0]["url"]) if motion else None),
        total_views=int(sum(views)),
        median_views=int(statistics.median(views)) if views else 0,
        newest_published_at=max((when for when in map(_when, media) if when), default=None),
        engagement={key: int(sum(_num(entry.get(key)) for entry in media))
                    for key in ("likes", "shares", "comments", "bookmarks")},
    )
    # Raw component values are STAGED here and replaced by their normalized 0-1 values in `_score`
    # (min-max needs the whole pool); what reaches the log is the normalized set (FR-5).
    item.strength_components = {"total_views": float(item.total_views),
                                "median_views": float(item.median_views),
                                "velocity": _velocity(media)}
    if log is not None:  # FR-7/FR-24: a repeat, of a set or of a motion source, stays explainable
        log.event("reference_choice",
                  f"{name}: {'fresh' if fresh else 'repeat'} set of {len(ordered)} candidate(s), "
                  f"motion {motion[2] if motion else 'none'}",
                  trend=item.history_key, candidate_sets=len(ordered), set_fresh=fresh,
                  post_ids=list(item.chosen_post_ids), motion_post=item.winning_video_post_id,
                  motion_tier=motion[2] if motion else "none")
    return item


def _reference_groups(videos: list[Any], shows: list[Any], cfg: Config,
                      monitor_id: str) -> list[ReferenceSet]:
    """FR-91's coherent-set builder: EVERY qualifying candidate as a `ReferenceSet`, best first.

    Panels lead thumbnails; a slideshow qualifies only at `_MIN_PANELS`+ (RESULTS.md §A); a creator
    family needs `_MIN_THUMBS`+ once face-dominant frames are dropped, and UI-dense/complex frames
    sink inside it. `reference_images_per_job` caps ONE set. `media_download_cap` is deliberately
    NOT applied here: it bounds downloads, and gating candidates on it left exactly two sets per
    monitor where a live monitor qualifies ~36 (spikes/RESULTS.md:163) — FR-7 chooses among all.
    """
    per_job = max(1, cfg.sources.reference_images_per_job)
    ranked: list[tuple[int, float, float, ReferenceSet]] = []
    for index, show in enumerate(shows):
        panels = [url for url in show.get("image_urls") or [] if isinstance(url, str) and url]
        if len(panels) >= _MIN_PANELS:  # the wrapper already sorted them by `position`
            ranked.append((2, 1.0, _num(show.get("views")),
                           _set(panels[:per_job], [(show, _post_id(show, monitor_id, index))], True)))

    families: dict[str, list[tuple[Any, str]]] = {}
    for index, video in enumerate(videos, start=len(shows)):
        if isinstance(video.get("thumbnail_url"), str) and video["thumbnail_url"]:
            families.setdefault(str(video.get("author_username") or video.get("id")), []).append(
                (video, _post_id(video, monitor_id, index)))
    for family in families.values():
        order = sorted(family, key=lambda p: (_frame_quality(p[0]), _num(p[0].get("views"))),
                       reverse=True)
        picked = ([p for p in order if p[0].get("has_face_visible") is not True] or order)[:per_job]
        if len(picked) >= _MIN_THUMBS:
            ranked.append((1, sum(_frame_quality(row) for row, _ in picked) / len(picked),
                           _num(picked[0][0].get("views")),
                           _set([row["thumbnail_url"] for row, _ in picked], picked, False)))

    if not ranked:  # last resort: any image at all beats a text_only trend (FR-6/FR-90)
        loose = [(row["thumbnail_url"], (row, _post_id(row, monitor_id, index)))
                 for index, row in enumerate(videos, start=len(shows))
                 if isinstance(row.get("thumbnail_url"), str) and row["thumbnail_url"]]
        loose += [(url, (show, _post_id(show, monitor_id, index)))
                  for index, show in enumerate(shows)
                  for url in show.get("image_urls") or [] if isinstance(url, str) and url]
        if loose:
            ranked.append((0, 0.0, 0.0, _set([url for url, _ in loose[:per_job]],
                                             [row for _, row in loose[:per_job]], False)))
    return [candidate for *_key, candidate in sorted(ranked, key=lambda row: row[:3], reverse=True)]


def _set(urls: list[str], rows: Sequence[tuple[Any, str]], is_slideshow: bool) -> ReferenceSet:
    """One candidate built as a UNIT — urls, the posts behind them, and everything the creative
    derives from choosing it. `rows` are `(row, post_id)` pairs; the FIRST row is the set's own
    source, so a slideshow's panel metadata and a family's leading thumbnail agree by construction
    instead of by a hand-kept index alignment.
    """
    lead: Mapping[str, Any] = rows[0][0] if rows else {}
    return ReferenceSet(
        urls=[str(url) for url in urls],
        post_ids=tuple(dict.fromkeys(post for _, post in rows)),
        is_slideshow=is_slideshow,
        panel_texts=[str(text) for text in lead.get("panel_texts") or []],
        narrative_arc=str(lead.get("narrative_arc") or ""),
        text_density=str(lead.get("text_density") or ""),
        source_url=str(lead.get("url") or "") or None,
        author=str(lead.get("author_username") or "") or None)


def _post_id(row: Mapping[str, Any], monitor_id: str, index: int) -> str:
    """This post's identity for FR-7's window: Virlo's own stable `id` (20 §3), else its url, else
    its monitor-scoped position — `index` runs across slideshows THEN videos, so the two arrays
    cannot collide. NEVER `id(row)`: `_dedupe`'s memory-address fallback differs on every run and
    would silently turn freshness off while reporting success.
    """
    return str(row.get("id") or row.get("url") or f"{monitor_id}:{index}")


def _pick_set(sets: list[ReferenceSet],
              used: Collection[str]) -> tuple[ReferenceSet, list[ReferenceSet], bool]:
    """FR-7's choice: the freshest unused candidate, then the other fresh ones, then the used ones.

    `sets` arrives strongest-first, so "freshest unused" is the strongest candidate none of whose
    posts appear in the history window — deterministic on identical input. Returns that set (an
    empty `ReferenceSet` when the monitor offered no candidate at all, so callers branch on nothing),
    the candidate list reordered so the chosen set is group 0 and top-ups prefer fresh material, and
    whether the choice was actually fresh. When every candidate is used the strongest is still chosen
    — an image-less trend is worse than a repeated one — but reported stale, so `chosen_post_ids`
    stays empty and the monitor-level window decides the exclusion.
    """
    fresh, stale = [], []
    for candidate in sets:
        (stale if any(post in used for post in candidate.post_ids) else fresh).append(candidate)
    ordered = fresh + stale
    return (ordered[0] if ordered else ReferenceSet()), ordered, bool(fresh)


def _pick_motion(videos: Sequence[tuple[Any, str]], chosen: ReferenceSet,
                 used: Collection[str]) -> tuple[Mapping[str, Any], str, str] | None:
    """The reel's motion reference (FR-24) as `(row, post_id, tier)`, in three tiers of preference:

    1. `fresh_same_creator` — an unused video by the chosen set's own creator: fresh AND topically
       coherent, so a slideshow's copy is not animated by a stranger's clip;
    2. `fresh` — else the highest-viewed unused video;
    3. `repeat` — else the highest-viewed video regardless, logged as a repeat.

    **Tier 3 is the point.** Freshness must never cost a reel: a repeated motion source is a
    cosmetic loss, a failed reel is a paid one ($4.78 measured). This returns None only when no
    video carries a url at all — never because everything has been used.
    """
    ranked = sorted((pair for pair in videos if pair[0].get("url")),
                    key=lambda pair: _num(pair[0].get("views")), reverse=True)
    fresh = [pair for pair in ranked if pair[1] not in used]
    handle = chosen.author or ""
    same = [pair for pair in fresh
            if handle and str(pair[0].get("author_username") or "") == handle]
    for tier, pool in (("fresh_same_creator", same), ("fresh", fresh), ("repeat", ranked)):
        if pool:
            return pool[0][0], pool[0][1], tier
    return None


def _analysis_fields(analysis: Mapping[str, Any]) -> tuple[str, list[str], str, float | None]:
    """`why_it_works`, tactics, this monitor's own context and its confidence, from `analysis_data`.

    RESULTS.md §A puts all four on the monitor, not on the digest 20 §3 credits — so this is where
    FR-9/FR-14's tactics and timing inputs come from, and (FR-5 v1.6.4) where the 0.20 confidence
    component is sourced: the MEAN over the consumed themes, since the digest's `global_confidence`
    is null on every live trend. Absent-safe, and bounded: these reach prompts.
    """
    themes = analysis.get("themes") or []
    consumed = themes[:_MAX_THEMES]
    scored = [float(t["confidence"]) for t in consumed
              if isinstance(t.get("confidence"), (int, float)) and not isinstance(t["confidence"], bool)]
    why = " · ".join(part for part in [
        str(analysis.get("why_it_works") or "").strip(),
        *(f"{t.get('name')}: {t['why_it_works']}" for t in consumed if t.get("why_it_works")),
    ] if part)[:_WHY_MAX_CHARS]
    tactics: list[str] = []
    for value in [t for theme in themes for t in theme.get("tactics") or []] + list(
            analysis.get("viral_tactics") or []):
        text = str(value).strip()
        if text and text not in tactics:
            tactics.append(text)
    parts = [f"Timing: {analysis['timing_pattern']}"] if analysis.get("timing_pattern") else []
    if analysis.get("peak_hours"):
        parts.append("Peak hours: " + ", ".join(str(hour) for hour in analysis["peak_hours"][:6]))
    parts += [f"{label}: {analysis[key]}" for key, label in
              (("connecting_thread", "Connecting thread"), ("key_highlight", "Key highlight"))
              if analysis.get(key)]
    return (why, tactics[:_MAX_TACTICS], " · ".join(parts)[:_CONTEXT_MAX_CHARS],
            statistics.fmean(scored) if scored else None)


def _frame_quality(video: Mapping[str, Any]) -> float:
    """FR-91's frame screen: a dominant face is the heavy penalty (portrait pull + moderation
    risk), on-screen text and visual complexity the lighter ones (platform UI gets copied)."""
    quality = _COMPLEXITY.get(str(video.get("visual_complexity") or "").lower(), 0.5)
    quality -= 2.0 if video.get("has_face_visible") is True else 0.0
    return quality - (0.5 if video.get("has_text_overlay") is True else 0.0)


def _dedupe(rows: list[Any]) -> list[Any]:
    """Drop repeated posts, keyed by id then url (RESULTS.md §A saw live duplicates)."""
    seen: set[str] = set()
    kept = []
    for row in rows:
        key = str(row.get("id") or row.get("url") or id(row)) if isinstance(row, Mapping) else ""
        if key and key not in seen:
            seen.add(key)
            kept.append(row)
    return kept


def _texts(rows: list[Any], key: str) -> list[str]:
    """Deduped, non-empty values of one optional field, capped at the few-shot budget."""
    out: list[str] = []
    for row in rows:
        value = str(row.get(key) or "").strip()
        if value and value not in out:
            out.append(value)
    return out[:_MAX_EXEMPLARS]


def _when(row: Mapping[str, Any]) -> datetime | None:
    """`publish_date` as an aware UTC datetime; unparseable or absent is None."""
    with suppress(ValueError):
        parsed = datetime.fromisoformat(str(row.get("publish_date") or "").replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _velocity(media: list[Any]) -> float:
    """FR-5's momentum signal: views relative to how recently the posts published."""
    now = datetime.now(timezone.utc)
    ages = ((_num(row.get("views")), _when(row)) for row in media)
    return sum(views / (max(0.0, (now - when).total_seconds() / 86400.0) + 1.0 if when else 31.0)
               for views, when in ages)


def _match_confidence(name: str, confidences: Mapping[str, float]) -> float | None:
    """Virlo's own confidence for this theme when the digest named it (usually null — §A)."""
    slug = slugify(name, 0)
    return next((value for other, value in confidences.items()
                 if other and (other in slug or slug in other)), None)


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


# --------------------------------------------------------------------------- ranking (FR-5)

def _score(items: list[TrendItem]) -> None:
    """Strength in place: min-max each component across the run's candidate pool, then weight.

    Weights are renormalized over the components that actually exist, so a missing confidence
    (RESULTS.md §A: `global_confidence` is null for every live trend) drags nobody toward zero —
    it just leaves 0.20 of weight to be shared by the components that arrived.
    """
    if not items:
        return
    for item in items:
        if item.confidence is not None:
            item.strength_components["confidence"] = float(item.confidence)
    columns = {name: _minmax([item.strength_components.get(name) for item in items])
               for name in _WEIGHTS if any(name in item.strength_components for item in items)}
    for index, item in enumerate(items):
        parts = {name: column[index] for name, column in columns.items()
                 if name in item.strength_components}
        weight = sum(_WEIGHTS[name] for name in parts) or 1.0
        item.strength = round(sum(_WEIGHTS[n] * v for n, v in parts.items()) / weight, 4)
        item.strength_components = {name: round(value, 4) for name, value in parts.items()}


def _minmax(values: list[float | None]) -> list[float]:
    """0-1 within the pool; an absent value stays 0 and a tied pool scores 1 (0 when all-zero)."""
    present = [value for value in values if value is not None]
    low, high = (min(present), max(present)) if present else (0.0, 0.0)
    if high - low <= 0:
        return [0.0 if value is None else (1.0 if high > 0 else 0.0) for value in values]
    return [0.0 if value is None else (value - low) / (high - low) for value in values]


# --------------------------------------------------------------------------- CDN downloads

async def _download_references(items: list[TrendItem], cfg: Config, cache_dir: Path | None,
                               log: LogWriter | None) -> None:
    """Fetch the chosen set first, top up to `media_download_cap`, then prune what died.

    The chosen set (group 0, FR-7) is downloaded whole so the render job's own set is never the
    part that got rationed; the remaining candidates — fresh ones first, since `_pick_set` ordered
    them that way — top the trend up to `media_download_cap`, which is what keeps the analysis call
    at FR-9's six images. One dead image removes itself and nothing else (FR-32/33/247); a group
    that ends up short still ships and the shortfall is logged; a trend left with zero images
    becomes `text_only` (FR-6/FR-90).
    """
    cap = max(1, cfg.sources.media_download_cap)
    queued: list[str] = []
    for item in items:
        budget = cap
        for group in item.reference_groups:  # group 0 is the chosen set and is never trimmed here
            queued += group[:max(0, budget)]
            budget -= len(group)
    wanted = [url for url in dict.fromkeys(queued) if url not in _CACHE]
    if wanted:
        target, limiter = _cache_dir(cache_dir), asyncio.Semaphore(_MAX_PARALLEL)
        attempts = max(1, cfg.models.http_max_attempts)

        async def one(url: str) -> tuple[str, Path | None]:
            async with limiter:
                return url, await _download(client, url, target, attempts, log)

        async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_S, follow_redirects=True) as client:
            for url, path in await asyncio.gather(*(one(url) for url in wanted)):
                if path is not None:
                    _CACHE[url] = path

    per_job = max(1, cfg.sources.reference_images_per_job)
    for item in items:
        alive = [[url for url in group if url in _CACHE] for group in item.reference_groups]
        chosen = alive[0] if alive else []  # the CHOSEN set, judged before the empties are dropped
        item.reference_groups = [group for group in alive if group]
        item.text_only = not item.reference_groups
        if not chosen:  # its urls all died, so none of its posts was attached to anything
            item.chosen_post_ids = ()
        judged = chosen or (item.reference_groups[0] if item.reference_groups else [])
        if item.text_only:
            _warn(log, "trend_text_only", f"{item.name}: no usable reference image — last-resort "
                  "trend (FR-6/90)", trend=item.history_key)
        elif len(judged) < per_job:
            _warn(log, "reference_shortfall", f"{item.name}: {len(judged)} of {per_job} references "
                  "survived — the job proceeds with fewer (FR-247)", trend=item.history_key)


async def _download(client: httpx.AsyncClient, url: str, target: Path, attempts: int,
                    log: LogWriter | None) -> Path | None:
    """One reference image, bounded by `http_max_attempts`; None means "drop this image only"."""
    suffix = Path(url.split("?", 1)[0]).suffix.lower()
    path = target / f"{hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]}{suffix if suffix in _SUFFIXES else '.img'}"
    if path.exists():
        return path
    reason = "no attempt completed"
    for attempt in range(1, attempts + 1):
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            reason = type(exc).__name__
            if getattr(getattr(exc, "response", None), "status_code", None) in (401, 403, 404, 410):
                break  # a retry cannot fix a dead or forbidden URL
        else:
            if response.content:
                path.write_bytes(response.content)
                return path
            reason = "zero-byte body"
        if attempt < attempts:
            await asyncio.sleep(_BACKOFF_S * 2 ** (attempt - 1))
    _warn(log, "reference_image_dropped", f"reference image dropped ({reason})", url=url, reason=reason)
    return None


def _cache_dir(requested: Path | None) -> Path:
    """Where downloads land: the caller's folder when it names one, else a private temp dir."""
    global _CACHE_DIR, _CACHE_DIR_OWNED
    if requested is not None:
        _CACHE_DIR, _CACHE_DIR_OWNED = Path(requested), False
    elif _CACHE_DIR is None:
        _CACHE_DIR, _CACHE_DIR_OWNED = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX)), True
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def _warn(log: LogWriter | None, event: str, message: str, *,
          say: Callable[[str], None] | None = None, **data: Any) -> None:
    """One degrade line: to the console logger, to both run logs when a run owns one, and — when
    the caller passed the console seam — to the operator's screen, because a misconfiguration they
    must fix is worth nothing buried in run.log."""
    logger.warning("%s", message)
    if say is not None:
        say(message)
    if log is not None:
        log.warn(event, message, **data)
