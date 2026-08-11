"""Sources domain — the adapter seam Collect calls, and the only door to trend data (D14/D20).

Callers import from `hypesocials.sources` only, never from its modules (guidelines §3a/§18):

    await fetch(cfg, ...)   every adapter in `sources.active`, merged into ranked TrendItems
                            — a `TrendFeed`, i.e. that list with `.counters` (FR-155) attached
    Counters                the run's Virlo funnel: rows in, sets qualified, images attached
    await list_monitors(cfg) `--list-monitors`: the $0 Virlo setup aid, `(id, name)` rows (FR-245)
    reference_paths(urls)   local files for downloaded references (analysis bytes, packager refs/)
    reference_group(trend, k)       the k-th creative's coherent set, rotated per FR-91
    reference_group_index(trend, k) that set's index — what a brief records about itself
    brief_key(key, trend, k)        the (trend, reference group) pair a style brief is keyed by
    cleanup()               delete this run's downloaded references (FR-249)
    SOURCE_STATUS           every adapter the config vocabulary knows -> is it built yet (FR-121)

The adapter contract is deliberately one line wide (20 §4, v1.6.1): an adapter returns normalized
`models.TrendItem`s carrying a `strength` in 0-1 that it computed for its own items (FR-5) — that
number is the whole cross-source obligation. Items without usable images mark themselves
`text_only` and inherit FR-90's last-resort handling; nothing else crosses the seam.

Append-only list: W5 adds Notion brand context and the local Inspiration pool here; existing names
do not move. Neither is an `sources.active` adapter — Notion is brand context, Inspiration is an
additive influence pool (D13), so they join this facade without joining the picker.

`load_pool` returns TWO channels on one object (A16): `pool.groups`/`pool.images`, the reference
images every mix but `off` attaches, and `pool.exemplar_texts`, the captions found in `.txt` files
sitting beside those images. The texts are copy-side material only and must never be handed to a
render prompt — see `inspiration.InspirationPool.exemplar_texts` for why, and for why the prompt
vocabulary makes it structurally impossible to try.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from pathlib import Path
from typing import TYPE_CHECKING

from hypesocials.config import Config
from hypesocials.models import TrendItem
from hypesocials.sources import virlo as _virlo
from hypesocials.sources.inspiration import InspirationPool, Mix, apply_mix, load_pool
from hypesocials.sources.notion import BrandContext, fetch_brand_context
from hypesocials.sources.virlo import (
    Counters, TrendFeed, cleanup, list_monitors, reference_paths)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hypesocials.outputs import LogWriter

#: FR-121: future adapters stay VISIBLE in config and the menu picker, marked not-yet-implemented,
#: never silently hidden. The names match `config._SOURCES`; only `virlo` has an implementation.
SOURCE_STATUS: dict[str, bool] = {"virlo": True, "google_trends": False, "hacker_news": False}

_ADAPTERS = {"virlo": _virlo.fetch}

#: Separates a trend key from its reference-group index in `brief_key()`. A history key is an
#: agent id or a name slug, so this character never occurs inside one and the pair key stays
#: readable in a log line — which is the point: `virlo-9c96…#2` names the pictures on sight.
_BRIEF_KEY_SEPARATOR = "#"


def reference_group_index(trend: TrendItem | None, reuse_index: int) -> int:
    """FR-91's rotation, resolved ONCE for the whole codebase: which group creative *k* attaches.

    `reuse_index` is `PlanEntry.trend_reuse_index` — this creative's 0-based position among the
    creatives sharing its trend. The k-th creative attaches `reference_groups[k % len]`, so
    siblings on one trend get visually distinct source material while each set stays drawn from a
    single source ("one set = one source" is preserved; rotation picks a *different* coherent set,
    it never mixes across sets).

    Total by contract — no trend, no groups and an index past the group count all answer 0 rather
    than raising, because every caller is on a path where a missing group means "attach nothing",
    never "fail the creative". **This is the only `%` over the group count in the codebase**: a
    copy of it in `refs.py`, `runner.py`, `analyze.py` and `previews.py` would be four places to
    drift, and drift here means a creative steered by a brief describing pictures it is not
    attaching — the precise failure the pair-keyed brief (FR-9/FR-12) exists to prevent.
    """
    groups = trend.reference_groups if trend is not None else ()
    if not groups:
        return 0
    return max(int(reuse_index), 0) % len(groups)


def reference_group(trend: TrendItem | None, reuse_index: int) -> list[str]:
    """The CDN urls creative *k* on this trend attaches (FR-91) — a fresh list, safe to slice.

    Empty when the trend is absent or arrived without pictures (a `text_only` item); the caller
    then renders reference-free and marks it, exactly as before rotation existed (FR-18).
    """
    groups = trend.reference_groups if trend is not None else ()
    if not groups:
        return []
    return list(groups[reference_group_index(trend, reuse_index)])


def brief_key(trend_key: str, trend: TrendItem | None, reuse_index: int) -> str:
    """The `(trend, reference group)` pair a style brief is computed and looked up by (FR-9/12).

    One brief per pair, not per trend and not per creative: creatives that share a trend AND the
    group it rotated to share one brief and one vision call, while a sibling that attached a
    different group gets its own — the brief must describe the pictures the creative actually
    attaches. Stable and collision-free (a history key is unique per trend, the index is unique
    per group) and readable on a console line.

    Always answers, including for a trend with no groups at all: a text-only trend still gets a
    brief written from its text material alone, keyed at index 0.
    """
    return f"{trend_key}{_BRIEF_KEY_SEPARATOR}{reference_group_index(trend, reuse_index)}"


async def fetch(
    cfg: Config,
    *,
    cache_dir: Path | None = None,
    log: LogWriter | None = None,
    include_digest: bool = True,
    used_posts: Collection[str] | None = None,
    say: Callable[[str], None] | None = None,
) -> TrendFeed:
    """Run every active source adapter and return their items, strongest first.

    Args:
        cfg: the loaded run config; `sources.active` picks the adapters (FR-121).
        cache_dir: where reference images are downloaded; a private temp folder when omitted.
        log: the run's LogWriter, so every per-source degrade is on the record.
        include_digest: `False` skips Virlo's metered digest, keeping a preview honestly at $0.
        used_posts: post ids already used inside the history window, as one flat set — Virlo post
            ids are globally unique, so an adapter needs no per-trend split (FR-7, FR-153). An
            adapter picks a reference set whose posts are absent from it.
        say: the run's console seam, for the rare degrade an operator must see on screen and not
            only in `run.log` — an empty monitor list being the one that cost a real run.

    Returns:
        A `TrendFeed`: the normalized trend items from all active adapters, with every adapter's
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
        items = await adapter(cfg, cache_dir=cache_dir, log=log, include_digest=include_digest,
                              used_posts=used_posts, say=say)
        feed.extend(items)
        if isinstance(items, TrendFeed):  # an adapter that counts nothing still merges cleanly
            feed.counters.absorb(items.counters)
    feed.sort(key=lambda item: item.strength, reverse=True)
    return feed


__all__ = [
    "SOURCE_STATUS", "BrandContext", "Counters", "InspirationPool", "Mix", "TrendFeed",
    "apply_mix", "brief_key", "cleanup", "fetch", "fetch_brand_context", "list_monitors",
    "load_pool", "reference_group", "reference_group_index", "reference_paths",
]
