"""Sources domain — the adapter seam Collect calls, and the only door to trend data (D14/D20).

Callers import from `hypesocials.sources` only, never from its modules (guidelines §3a/§18):

    await fetch(cfg, ...)   every adapter in `sources.active`, merged into ranked TrendItems
    await list_monitors(cfg) `--list-monitors`: the $0 Virlo setup aid, `(id, name)` rows (FR-245)
    reference_paths(urls)   local files for downloaded references (analysis bytes, packager refs/)
    cleanup()               delete this run's downloaded references (FR-249)
    SOURCE_STATUS           every adapter the config vocabulary knows -> is it built yet (FR-121)

The adapter contract is deliberately one line wide (20 §4, v1.6.1): an adapter returns normalized
`models.TrendItem`s carrying a `strength` in 0-1 that it computed for its own items (FR-5) — that
number is the whole cross-source obligation. Items without usable images mark themselves
`text_only` and inherit FR-90's last-resort handling; nothing else crosses the seam.

Append-only list: W5 adds Notion brand context and the local Inspiration pool here; existing names
do not move. Neither is an `sources.active` adapter — Notion is brand context, Inspiration is an
additive influence pool (D13), so they join this facade without joining the picker.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hypesocials.config import Config
from hypesocials.models import TrendItem
from hypesocials.sources import virlo as _virlo
from hypesocials.sources.inspiration import InspirationPool, Mix, apply_mix, load_pool
from hypesocials.sources.notion import BrandContext, fetch_brand_context
from hypesocials.sources.virlo import cleanup, list_monitors, reference_paths

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hypesocials.outputs import LogWriter

#: FR-121: future adapters stay VISIBLE in config and the menu picker, marked not-yet-implemented,
#: never silently hidden. The names match `config._SOURCES`; only `virlo` has an implementation.
SOURCE_STATUS: dict[str, bool] = {"virlo": True, "google_trends": False, "hacker_news": False}

_ADAPTERS = {"virlo": _virlo.fetch}


async def fetch(
    cfg: Config,
    *,
    cache_dir: Path | None = None,
    log: LogWriter | None = None,
    include_digest: bool = True,
) -> list[TrendItem]:
    """Run every active source adapter and return their items, strongest first.

    Args:
        cfg: the loaded run config; `sources.active` picks the adapters (FR-121).
        cache_dir: where reference images are downloaded; a private temp folder when omitted.
        log: the run's LogWriter, so every per-source degrade is on the record.
        include_digest: `False` skips Virlo's metered digest, keeping a preview honestly at $0.

    Returns:
        Normalized trend items from all active adapters. Select (`plan.py`) owns every verdict
        from here — usability, history window, affinity — so nothing is filtered out here.
    """
    items: list[TrendItem] = []
    for name in dict.fromkeys(cfg.sources.active):
        adapter = _ADAPTERS.get(name)
        if adapter is None:
            message = f"source {name!r} is not implemented yet — skipped for this run"
            if log is not None:
                log.warn("source_not_implemented", message, source=name)
            continue
        items.extend(await adapter(cfg, cache_dir=cache_dir, log=log, include_digest=include_digest))
    items.sort(key=lambda item: item.strength, reverse=True)
    return items


__all__ = [
    "SOURCE_STATUS", "BrandContext", "InspirationPool", "Mix", "apply_mix", "cleanup", "fetch",
    "fetch_brand_context", "list_monitors", "load_pool", "reference_paths",
]
