"""Local Inspiration pool — the operator's own images as additive style references (D13, FR-91).

Callers import `hypesocials.sources`, never this module. Two calls, one concept:

    pool = await load_pool(cfg, log=run_log)                    # Collect: scan + validate
    mix = apply_mix(live_entries, trends, pool, cfg, log=run_log)
    generate.Env(..., trends=mix.trends, local_refs=mix.local_refs)

Inspiration is NOT a `sources.active` adapter (20 §4): it yields no trend items and no verdicts,
only a place in a render job's reference set. `inspiration_mix` (30 §2) says how, and FR-91 says
these images are never blindly unioned into the Virlo pool:

- `off` — nothing attaches; the reference set is exactly what Virlo supplied.
- `minority` (default) — at most ONE inspiration image, attached LAST, alongside
  `reference_images_per_job - 1` trend references, so the trend still dominates the render.
- `exclusive` — a coherent inspiration-only set: one folder's images, no trend references.

Coherence (FR-91) is per folder — one folder is one visual family, as one slideshow's panels are
in `virlo.py`. Assets rotate deterministically through the pool, so a batch of eight creatives
does not render the same picture eight times, and the same plan picks the same images.

Invariants: pure local I/O — the scan runs off the event loop and nothing is uploaded here
(`generate/` owns FR-200/FR-244's upload of these paths); a missing or empty folder is absence,
not an error (10 §10); a non-image, unreadable or oversized file is skipped, never sent.

Do not: mutate the `TrendItem`s Collect produced (the trimmed copies are the render-side view
only, so Select's verdicts, `text_only` and the analysis inputs stay as Virlo built them); upload;
read image pixels (Pillow's one sanctioned use is FR-93's downscale, NFR-25).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hypesocials.config import Config
from hypesocials.models import PlanEntry, TrendItem

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hypesocials.outputs import LogWriter

logger = logging.getLogger(__name__)

_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"})
#: Magic-byte prefixes, so "validate" means the bytes are an image and not just the name (a
#: renamed .txt would fail the Kie upload and cost the job a reference for no reason).
_MAGIC: tuple[bytes, ...] = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a",
                             b"RIFF", b"BM")
_MAX_BYTES = 30 * 1024 * 1024  # Kie's documented per-image ceiling (20 §8b)
_MAX_PER_FOLDER = 60  # a coherent set never needs more; keeps a stray photo dump out of the pool


@dataclass(slots=True)
class InspirationPool:
    """Every usable local image this run may draw on, grouped by folder (one folder = one family)."""

    groups: list[list[Path]] = field(default_factory=list)
    mix: str = "off"  # what config asked for; `active` says whether it can be honoured
    skipped: int = 0  # files that were not usable images — logged once, never per file

    @property
    def images(self) -> list[Path]:
        """The flat global pool (30 §2: `inspiration_folders` is one pool, not per platform)."""
        return [path for group in self.groups for path in group]

    @property
    def active(self) -> bool:
        """True when this run's references will actually gain an image."""
        return self.mix in ("minority", "exclusive") and bool(self.groups)


@dataclass(slots=True)
class Mix:
    """The reference-set decision for one run — the whole return of `apply_mix`."""

    local_refs: dict[str, list[Path]] = field(default_factory=dict)  # asset_id -> images to attach
    trends: dict[str, TrendItem] = field(default_factory=dict)  # the RENDER-side view of Collect
    mix: str = "off"  # the mix actually used, which FR-91 requires in the log
    ref_source: str = ""  # `AssetRecord.ref_source` override: "inspiration" under `exclusive`


async def load_pool(cfg: Config, *, log: LogWriter | None = None) -> InspirationPool:
    """Scan `sources.inspiration_folders` and return the validated pool.

    Args:
        cfg: the loaded run config — `sources.inspiration_folders` and `inspiration_mix`.
        log: the run's LogWriter; a missing or empty folder is logged once at info level.

    Returns:
        An `InspirationPool`. `off`, no folders, missing folders and folders holding no usable
        image all return an inactive pool — absence is a normal state, never an error.
    """
    mix = cfg.sources.inspiration_mix
    folders = [Path(str(entry)) for entry in cfg.sources.inspiration_folders if str(entry).strip()]
    if mix == "off" or not folders:
        return InspirationPool(mix=mix)
    groups, skipped, absent = await asyncio.to_thread(_scan, folders)
    pool = InspirationPool(groups=groups, mix=mix, skipped=skipped)
    _note(log, "inspiration_pool", "info",
          f"inspiration pool: {len(pool.images)} image(s) in {len(groups)} folder(s), mix {mix}"
          + (f"; {len(absent)} folder(s) missing or empty" if absent else "")
          + (f"; {skipped} non-image file(s) skipped" if skipped else ""),
          folders=[str(folder) for folder in folders], absent=[str(folder) for folder in absent])
    return pool


def apply_mix(
    entries: Sequence[PlanEntry],
    trends: Mapping[str, TrendItem],
    pool: InspirationPool,
    cfg: Config,
    *,
    log: LogWriter | None = None,
) -> Mix:
    """Decide every job's reference set for this run — FR-91's `inspiration_mix` semantics.

    Args:
        entries: the plan entries that will actually render; `trends`: `trend_key -> TrendItem` as
        Collect produced them, never mutated; `pool`: `load_pool`'s result; `cfg`: the run config,
        whose `reference_images_per_job` is the set size FR-91 caps at.

    Returns:
        A `Mix`. `local_refs` goes to `generate.Env(local_refs=...)`, where FR-200 uploads each
        path and attaches it LAST; `trends` goes to `generate.Env(trends=...)` with the trend
        references trimmed to make room (`minority`) or removed (`exclusive`). An inactive pool
        returns the untouched originals, so wiring this in costs an `off` run nothing.
    """
    if not pool.active or not entries:
        return Mix(trends=dict(trends), mix=pool.mix if pool.groups else "off")
    per_job = max(1, cfg.sources.reference_images_per_job)
    exclusive = pool.mix == "exclusive"
    keep = 0 if exclusive else max(0, per_job - 1)  # `minority`: at most 1 inspiration image
    local = {asset_id: _pick(pool, index, per_job if exclusive else 1)
             for index, asset_id in enumerate(sorted({entry.asset_id for entry in entries}))}
    _note(log, "inspiration_mix", "info",
          f"inspiration mix {pool.mix}: {'inspiration-only reference sets' if exclusive else 'one inspiration image last'}"
          f", {keep} trend reference(s) per job (FR-91)",
          assets=len(local), pool=len(pool.images))
    return Mix(local_refs=local, trends={key: _trimmed(item, keep) for key, item in trends.items()},
               mix=pool.mix, ref_source="inspiration" if exclusive else "")


# --------------------------------------------------------------------------- internals


def _scan(folders: Sequence[Path]) -> tuple[list[list[Path]], int, list[Path]]:
    """Blocking folder walk, run in a worker thread. One group per folder that yielded images."""
    groups: list[list[Path]] = []
    skipped, absent = 0, []
    for folder in folders:
        try:
            entries = [path for path in sorted(folder.iterdir()) if not path.is_dir()]
        except OSError:  # missing folder, or one this account cannot read
            absent.append(folder)
            continue
        images = [path for path in entries if _usable(path)]
        skipped += len(entries) - len(images)
        if images:
            groups.append(images[:_MAX_PER_FOLDER])
        else:  # an empty folder is absence, not an error (10 §10)
            absent.append(folder)
    return groups, skipped, absent


def _usable(path: Path) -> bool:
    """Suffix, size and magic bytes — cheap enough per file, honest enough to call validation."""
    if path.suffix.lower() not in _SUFFIXES:
        return False
    try:
        if not 0 < path.stat().st_size <= _MAX_BYTES:
            return False
        with path.open("rb") as handle:
            header = handle.read(8)
    except OSError:
        return False
    return header.startswith(_MAGIC)


def _pick(pool: InspirationPool, index: int, count: int) -> list[Path]:
    """This asset's images: one coherent folder under `exclusive`, one rotating image otherwise."""
    if count > 1:
        group = pool.groups[index % len(pool.groups)]
        return group[:count]
    images = pool.images
    return [images[index % len(images)]]


def _trimmed(item: TrendItem, keep: int) -> TrendItem:
    """A render-side copy of one trend with its reference groups cut to `keep` (0 empties them).

    A copy, not an edit: Select's verdicts, `text_only` and the analysis call all read the
    originals, and only the render stage sees the room made for inspiration images.
    """
    if not item.reference_groups or all(len(group) <= keep for group in item.reference_groups):
        return item
    return replace(item, reference_groups=[group[:keep] for group in item.reference_groups
                                           if group[:keep]])


def _note(log: LogWriter | None, event: str, level: str, message: str, **data: Any) -> None:
    """One line to the console logger, and to both run logs when a run owns one."""
    logger.log(logging.WARNING if level == "warn" else logging.INFO, "%s", message)
    if log is not None:
        log.event(event, message, level=level, **data)


__all__ = ["InspirationPool", "Mix", "apply_mix", "load_pool"]
