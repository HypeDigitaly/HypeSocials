"""Sources domain — the adapter seam Collect calls, and the only door to topic data (D14/D44).

Callers import from `hypesocials.sources` only, never from its modules (guidelines §3a/§18):

    await fetch(cfg, ...)   every adapter in `sources.active`, merged into ranked topic items
                            — a `TrendFeed`, i.e. that list with `.counters` (FR-155) attached
    Counters                the run's Virlo funnel: rows in, topics out, filter/render forecast
    await list_monitors(cfg) `--list-monitors`: the $0 Virlo setup aid, `(id, name)` rows (FR-245)
    STRENGTH_WEIGHTS        the FR-5 scoring weights, re-exported so FR-297a's table caption
                            reads the very numbers the adapter ranks with (one definition)
    BrandContext / fetch_brand_context / apply_brand_overrides
                            the Notion channel (FR-34/36, D43): fetched once at Collect; under
                            `notion_influence: full` the snapshot folds into the ACTIVE branding
                            profile — dormant until a NOTION_TOKEN exists
    SOURCE_STATUS           every adapter the config vocabulary knows -> is it built yet (FR-121)

The adapter contract is deliberately one line wide (20 §4, v2.0.0): an adapter returns normalized
`models.TrendItem` TOPIC items — text only, with their view-ranked `SourcePost` lists — carrying a
`strength` in 0-1 that it computed for its own items (FR-5/FR-293). That number is the whole
cross-source obligation. Post-pivot every source is text-only by design (D41): no adapter
downloads media, and the reference-set/local-pool machinery this facade used to host died with
the topic-first pivot's Wave 3.5.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from typing import TYPE_CHECKING

from hypesocials.config import Config
from hypesocials.sources import virlo as _virlo
from hypesocials.sources.notion import BrandContext, apply_brand_overrides, fetch_brand_context
from hypesocials.sources.virlo import Counters, TrendFeed, list_monitors
#: FR-297a: the topics table's caption states the strength formula by READING the adapter's own
#: weights — one definition, so the printed sentence can never drift from the scoring code.
from hypesocials.sources.virlo import _WEIGHTS as STRENGTH_WEIGHTS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hypesocials.outputs import LogWriter

#: FR-121: future adapters stay VISIBLE in config and the menu picker, marked not-yet-implemented,
#: never silently hidden. The names match `config._SOURCES`; only `virlo` has an implementation.
SOURCE_STATUS: dict[str, bool] = {"virlo": True, "google_trends": False, "hacker_news": False}

_ADAPTERS = {"virlo": _virlo.fetch}


async def fetch(
    cfg: Config,
    *,
    log: LogWriter | None = None,
    include_digest: bool = True,
    used_posts: Collection[str] | None = None,
    say: Callable[[str], None] | None = None,
) -> TrendFeed:
    """Run every active source adapter and return their topic items, strongest first.

    Args:
        cfg: the loaded run config; `sources.active` picks the adapters (FR-121).
        log: the run's LogWriter, so every per-source degrade is on the record.
        include_digest: `False` skips Virlo's metered digest, keeping a preview honestly at $0.
        used_posts: post ids already QUOTED inside the history window, as one flat set — Virlo
            post ids are globally unique, so an adapter needs no per-topic split (FR-7, FR-153).
            Post-pivot the adapter annotates rather than filters; Select owns the verdict.
        say: the run's console seam, for the degrades an operator must see on screen and not
            only in `run.log` (FR-296 collect liveness — the four virlo `_warn` sites ride it).

    Returns:
        A `TrendFeed`: the normalized topic items from all active adapters, with every adapter's
        funnel `Counters` folded into one run-wide rollup on `.counters` (FR-155). Select
        (`plan.py`) owns every verdict from here — usability, history window, affinity — so
        nothing is filtered out here.
    """
    feed = TrendFeed()
    for name in dict.fromkeys(cfg.sources.active):
        adapter = _ADAPTERS.get(name)
        if adapter is None:
            message = f"source {name!r} is not implemented yet — skipped for this run"
            if log is not None:
                log.warn("source_not_implemented", message, source=name)
            continue
        items = await adapter(cfg, log=log, include_digest=include_digest,
                              used_posts=used_posts, say=say)
        feed.extend(items)
        if isinstance(items, TrendFeed):  # an adapter that counts nothing still merges cleanly
            feed.counters.absorb(items.counters)
    feed.sort(key=lambda item: item.strength, reverse=True)
    return feed


__all__ = [
    "SOURCE_STATUS", "STRENGTH_WEIGHTS", "BrandContext", "Counters", "TrendFeed",
    "apply_brand_overrides", "fetch", "fetch_brand_context", "list_monitors",
]
