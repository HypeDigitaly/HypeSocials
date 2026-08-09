"""Notion brand context — the optional, always-degradable brand channel (D7, 20 §5).

Callers import `hypesocials.sources`, never this module. One call does everything:

    brand = await fetch_brand_context(cfg, log=run_log)   # once per run, at Collect (FR-36)
    ... copywrite.write_copy(..., brand_context=brand.text)                  # `copy` and `full`
    ... build_context(brand_accent=brand.accent, brand_product_nouns=brand.product_nouns)  # `full`

Behind it: influence gating (FR-34 — `off` opens no session and reads no page), one stdio session
on the pinned Notion MCP server, tool-name resolution across its 1.x/2.x vocabularies,
per-context-type assembly (FR-35) and a plain character cut per `notion_char_budgets` (FR-124 — a
cut, never a summarization call; FR-37 is withdrawn).

This module produces the DATA for two prompt slots and fills no template: `{{brand_context}}` is
`.text`, the copywriter-only block, and `{{brand_accent}}` is `.accent` + `.product_nouns` — the
ONLY render-side brand influence there is (FR-109). Never a brand font, never a brand layout: a
brand-templated render has stopped being a mimicry render, and mimicry is the product.

Invariants: Notion is optional, so every failure path returns a `BrandContext` instead of raising
— missing token, absent server, dead page, mid-run auth revocation, hung call (FR-47, 20 §10) —
and a mid-run auth failure is surfaced ONCE, not once per page. `NOTION_TOKEN` reaches only the
per-server env dict `mcp_client` builds (D30/NFR-112); its value is never read, logged or prompted.

Do not: open a session when influence is `off`; fetch twice per run (the returned object IS the
run's cache, FR-36); summarize with a model; put anything but accent + product nouns on the render
side; retry a page (the server owns its own transport retries).
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hypesocials.config import Config
from hypesocials.mcp_client import MCPClientError, MCPError, ServerConfig, Session, open_session

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hypesocials.outputs import LogWriter

logger = logging.getLogger(__name__)

SERVER_NAME = "notion"
TOKEN_VAR = "NOTION_TOKEN"
#: FR-35's four context types, in the order the assembled block presents them.
CONTEXT_TYPES: tuple[str, ...] = ("brand_voice", "offers", "icp", "topics")

_LABELS = {"brand_voice": "Brand voice", "offers": "Offers and products",
           "icp": "Ideal customer", "topics": "Topics"}
#: Used only when config carries no `mcp_servers.notion` entry; matches `configs/default.yaml`
#: (FR-113: the package is pinned and pre-installed, so `--no-install` never hits a registry).
_DEFAULT_SERVER = {"transport": "stdio", "env_vars": [TOKEN_VAR],
                   "command": "npx --no-install @notionhq/notion-mcp-server"}
#: Page-fetch tool candidates, best first, each with the argument name it takes. 2.x ships
#: `notion-fetch`; 1.x shipped `API-retrieve-a-page`. The pin (FR-113) makes one of them true;
#: trying the list is what keeps a version bump from being a silent no-data run.
_FETCH_TOOLS: tuple[tuple[str, str], ...] = (
    ("notion-fetch", "id"), ("notion_fetch", "id"), ("fetch", "id"),
    ("API-retrieve-a-page", "page_id"), ("retrieve-a-page", "page_id"))
_TEXT_KEYS = ("markdown", "content", "text", "plain_text", "title", "results", "page", "blocks")
_AUTH_HINTS = ("401", "403", "unauthorized", "invalid token", "api token is invalid",
               "restricted", "not authorized")
_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
_ACCENT_LINE = re.compile(
    r"(?im)^[\s\-*#>]*(?:brand\s+)?(?:accent|primary|main)\s*(?:colou?r)?\s*[:\-]\s*(.+)$")
_LIST_LINE = re.compile(r"(?m)^[\s>]*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)(.+)$")
_MARKDOWN = re.compile(r"[*_`#\[\]]")
_MAX_NOUNS, _MAX_NOUN_CHARS = 6, 40


@dataclass(slots=True)
class BrandContext:
    """One run's brand snapshot — the whole return of this module, cached by the caller (FR-36).

    The empty instance is the honest shape of every degrade (influence off, token absent, server
    unreachable, no pages configured, every page unreadable): callers never branch on *why*.
    """

    text: str = ""  # `{{brand_context}}` — labelled block, copywriter only (FR-109)
    accent: str = ""  # `{{brand_accent}}` half one: an accent colour, `full` influence only
    product_nouns: list[str] = field(default_factory=list)  # half two: nouns for on-image text
    sections: dict[str, str] = field(default_factory=dict)  # per context type, already truncated
    influence: str = "off"  # what actually applied, which is not always what config asked for
    pages_read: int = 0

    @property
    def available(self) -> bool:
        """True when a prompt would actually gain something — the one thing callers branch on."""
        return bool(self.text)


async def fetch_brand_context(cfg: Config, *, log: LogWriter | None = None) -> BrandContext:
    """Fetch, assemble and truncate this run's Notion brand context. Called ONCE, at Collect.

    Args:
        cfg: the loaded run config — `run.notion_influence` (D7), `notion_pages` (FR-35) and
            `notion_char_budgets` (FR-124) are what matter, plus `mcp_servers.notion`.
        log: the run's LogWriter, so every degrade is on the record.

    Returns:
        A `BrandContext`. `off` influence returns the empty one without opening a session or
        reading a page (FR-34); `copy` fills `.text` only; `full` additionally fills `.accent`
        and `.product_nouns`. Never raises — Notion is optional, so the run always continues.
    """
    influence = cfg.run.notion_influence
    if influence == "off":
        return BrandContext()
    if not os.environ.get(TOKEN_VAR, "").strip():  # backstop; pre-flight already forced `off`
        _note(log, "notion_token_missing", "warn",
              f"{TOKEN_VAR} is not set — this run has no brand context (FR-47)")
        return BrandContext()
    wanted = {ctx: [str(page).strip() for page in cfg.notion_pages.get(ctx) or [] if str(page).strip()]
              for ctx in CONTEXT_TYPES}
    if not any(wanted.values()):
        _note(log, "notion_no_pages", "warn",
              f"notion_influence is {influence!r} but notion_pages lists no page ids — nothing to "
              "fetch; add ids per context type and share each page with the integration (FR-123)")
        return BrandContext(influence=influence)

    sections: dict[str, str] = {}
    pages_read, warned = 0, set()
    try:
        async with open_session(_server(cfg)) as session:
            tool, argument = _fetch_tool(await session.tool_names())
            for ctx, ids in wanted.items():
                texts = []
                for page_id in ids:
                    if text := await _page_text(session, tool, argument, page_id, warned, log):
                        texts.append(text)
                        pages_read += 1
                if texts:
                    sections[ctx] = _truncate("\n\n".join(texts),
                                              cfg.notion_char_budgets.get(ctx), ctx, log)
    except (MCPClientError, MCPError, OSError, ValueError) as exc:
        # Server missing, npx absent, handshake failed, no fetch tool: brand context is simply
        # left out — whatever pages already answered are still assembled below (20 §10).
        _note(log, "notion_unavailable", "warn",
              f"Notion brand context unavailable ({type(exc).__name__}: {exc}) — the run continues "
              "without it", error=type(exc).__name__)

    accent, nouns = _brand_marks(sections) if influence == "full" else ("", [])
    brand = BrandContext(text=_assemble(sections), sections=sections, influence=influence,
                         pages_read=pages_read, accent=accent, product_nouns=nouns)
    _note(log, "notion_context", "info",
          f"brand context: {pages_read} page(s), {len(brand.text)} chars, influence {influence}"
          + (f", accent {brand.accent}" if brand.accent else ""),
          context_types=sorted(sections), product_nouns=brand.product_nouns)
    return brand


# --------------------------------------------------------------------------- MCP fetching


def _server(cfg: Config) -> ServerConfig:
    """The Notion server's launch record. Pool size is 1 by spec — one session, serialized calls."""
    entry = cfg.mcp_servers.servers.get(SERVER_NAME) or _DEFAULT_SERVER
    return ServerConfig.from_mapping(
        SERVER_NAME, entry,
        startup_timeout_s=float(cfg.mcp_servers.startup_timeout_s),
        call_timeout_s=float(cfg.mcp_servers.call_timeout_s))


def _fetch_tool(advertised: Sequence[str]) -> tuple[str, str]:
    """The page-fetch tool this server actually advertises, or fail naming what it offered."""
    for tool, argument in _FETCH_TOOLS:
        if tool in advertised:
            return tool, argument
    raise ValueError(
        "the Notion MCP server advertises no page-fetch tool this engine knows — it offered: "
        + (", ".join(advertised) or "nothing"))


async def _page_text(session: Session, tool: str, argument: str, page_id: str,
                     warned: set[str], log: LogWriter | None) -> str:
    """One page as plain text; an unreadable page contributes nothing and costs nothing else.

    An auth-class failure (token revoked or the page unshared mid-run) is surfaced ONCE per run
    naming `NOTION_TOKEN` — one loud warning beats n quiet "no data" lines (20 §10).
    """
    try:
        payload = await session.call_tool(tool, {argument: page_id})
    except (MCPError, MCPClientError) as exc:
        detail = str(exc)
        if any(hint in detail.lower() for hint in _AUTH_HINTS):
            if "auth" not in warned:
                warned.add("auth")
                _note(log, "notion_auth_failed", "warn",
                      f"Notion refused the request ({TOKEN_VAR} invalid, revoked, or the page is "
                      "not shared with the integration) — brand context is missing for the rest "
                      "of this run (FR-123, 20 §10)")
            return ""
        _note(log, "notion_page_failed", "warn",
              f"Notion page {page_id} returned no data: {type(exc).__name__}", page=page_id)
        return ""
    return _flatten(payload)


def _flatten(payload: Any, depth: int = 0) -> str:
    """Page content as text, whichever shape the server returned (markdown, blocks, or JSON)."""
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, Mapping):
        parts = [_flatten(payload[key], depth + 1) for key in _TEXT_KEYS if key in payload]
        joined = "\n".join(part for part in parts if part)
        if joined or depth:
            return joined
        return json.dumps(payload, ensure_ascii=False, default=str)  # honest last resort
    if isinstance(payload, Sequence) and not isinstance(payload, (bytes, bytearray)):
        return "\n".join(part for part in (_flatten(item, depth + 1) for item in payload) if part)
    return ""


# --------------------------------------------------------------------------- assembly (FR-35/124)


def _truncate(text: str, budget: int | None, ctx: str, log: LogWriter | None) -> str:
    """FR-124's plain cut, taken at a word boundary so no prompt ever ends mid-word."""
    text = text.strip()
    if not budget or budget < 1 or len(text) <= budget:
        return text
    cut = text[:budget]
    boundary = max(cut.rfind("\n"), cut.rfind(" "))
    _note(log, "notion_truncated", "info", f"{_LABELS[ctx]} exceeded notion_char_budgets.{ctx}="
          f"{budget} and was cut, not summarized (FR-124)")
    return (cut[:boundary] if boundary > budget // 2 else cut).rstrip()


def _assemble(sections: Mapping[str, str]) -> str:
    """The `{{brand_context}}` block: labelled, ordered, and empty when nothing was readable."""
    return "\n\n".join(f"{_LABELS[ctx]}:\n{sections[ctx]}"
                       for ctx in CONTEXT_TYPES if sections.get(ctx))


def _brand_marks(sections: Mapping[str, str]) -> tuple[str, list[str]]:
    """FR-109's two render-side values, extracted deterministically — no model call, no fonts.

    Accent: a labelled accent/primary colour line, else the first hex value anywhere. Nouns: the
    headings and list items of the offers page (topics as fallback), which is how a brand page
    names its products; anything sentence-length is not a noun and is dropped. Empty is the
    common, correct answer — a brand that states neither contributes neither.
    """
    text = "\n".join(sections.values())
    if match := _ACCENT_LINE.search(text):  # hex first: the markdown strip would eat its `#`
        value = match.group(1).strip()
        accent = (found.group(0) if (found := _HEX.search(value))
                  else _MARKDOWN.sub("", value).strip()[:_MAX_NOUN_CHARS])
    else:
        accent = found.group(0) if (found := _HEX.search(text)) else ""
    nouns: list[str] = []
    for source in (sections.get("offers", ""), sections.get("topics", "")):
        for line in _LIST_LINE.findall(source):
            noun = re.split(r"[:—–]", _MARKDOWN.sub("", line), maxsplit=1)[0].strip(" .-")
            if 2 <= len(noun) <= _MAX_NOUN_CHARS and noun.lower() not in {n.lower() for n in nouns}:
                nouns.append(noun)
        if nouns:
            break
    return accent, nouns[:_MAX_NOUNS]


def _note(log: LogWriter | None, event: str, level: str, message: str, **data: Any) -> None:
    """One line to the console logger, and to both run logs when a run owns one."""
    logger.log(logging.WARNING if level == "warn" else logging.INFO, "%s", message)
    if log is not None:
        log.event(event, message, level=level, **data)


__all__ = ["CONTEXT_TYPES", "SERVER_NAME", "TOKEN_VAR", "BrandContext", "fetch_brand_context"]
