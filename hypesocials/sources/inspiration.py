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
does not render the same picture eight times, and the same plan picks the same images. Under
`exclusive` the rotation runs on two axes — which folder, and which window inside it (A17).

A pooled image may also carry a sibling `.txt` (`01.jpg` / `01.txt`): the post's real, proven,
human-written caption. Those land on `InspirationPool.exemplar_texts` for the COPY call and
nothing else (A16) — never a render prompt, for the reason the "no words" role line in
`generate/refs.py` exists. They ride the pool rather than the `Mix` because the copy call happens
a stage BEFORE `apply_mix` decides reference sets; the pool is the object both stages can see.

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
#: A16: a `.txt` sitting beside a pooled image, same stem, same folder — `01.jpg` / `01.txt`, the
#: shape `Inspiration/Linkedin/Viral posts/` ships. It is the post's real, human-written, proven
#: caption, and until now it was counted in `skipped` and thrown away. It does NOT make a file
#: pickable: no image, no exemplar. Only an image already in the pool can carry one.
_TEXT_SUFFIX = ".txt"
#: Per-file byte cap. A viral caption is a few hundred characters; 4 KB is generous enough that no
#: real one is cut and small enough that a stray pasted article cannot swallow the copy prompt.
_MAX_TEXT_BYTES = 4096
#: Run-wide exemplar cap. `_MAX_PER_FOLDER` x several folders could otherwise pool hundreds of
#: captions; the copy call wants a handful of proven examples, not a corpus.
_MAX_EXEMPLARS = 24
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
    skipped: int = 0  # files that were neither a usable image nor an exemplar — logged once
    #: A16 — the sibling `.txt` beside a pooled image: proven, human-written viral COPY, in folder
    #: order then file order, so a re-run pools it identically.
    #:
    #: ⚠️ THE COPY CALL AND NOTHING ELSE. This text must never reach a render prompt. Inspiration
    #: images are attached to renders under an explicit "no words" role line (`generate/refs.py`),
    #: and handing proven copy to an image model is how that copy ends up baked into pixels
    #: verbatim. Structurally it cannot: there is no `{{placeholder}}` for it in
    #: `models.PLACEHOLDERS` and therefore no render-role allowlist that could resolve one, and
    #: `prompts_engine.build_context` has no parameter that accepts it. Any future wire-in belongs
    #: to `copywrite.write_copy`, alongside `{{source_hooks}}`.
    exemplar_texts: list[str] = field(default_factory=list)

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
        An `InspirationPool`, carrying both channels this folder set can feed: the images every
        mix but `off` attaches, and `exemplar_texts` — the sibling `.txt` captions, for the COPY
        call only (A16). `off`, no folders, missing folders and folders holding no usable image
        all return an inactive pool — absence is a normal state, never an error.
    """
    mix = cfg.sources.inspiration_mix
    folders = [Path(str(entry)) for entry in cfg.sources.inspiration_folders if str(entry).strip()]
    if mix == "off" or not folders:
        return InspirationPool(mix=mix)
    groups, texts, skipped, absent = await asyncio.to_thread(_scan, folders)
    pool = InspirationPool(groups=groups, mix=mix, skipped=skipped, exemplar_texts=texts)
    _note(log, "inspiration_pool", "info",
          f"inspiration pool: {len(pool.images)} image(s) in {len(groups)} folder(s), mix {mix}"
          + (f"; {len(texts)} sibling caption(s) for the copy call" if texts else "")
          + (f"; {len(absent)} folder(s) missing or empty" if absent else "")
          + (f"; {skipped} non-image file(s) skipped" if skipped else ""),
          folders=[str(folder) for folder in folders], absent=[str(folder) for folder in absent],
          exemplars=len(texts))
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


def _scan(folders: Sequence[Path]) -> tuple[list[list[Path]], list[str], int, list[Path]]:
    """Blocking folder walk, run in a worker thread. One group per folder that yielded images.

    Returns `(groups, exemplar_texts, skipped, absent)`. Both channels come off the same single
    pass because they read the same directory listing: a second walk to find the `.txt` files
    would be a second chance for the two views to disagree about what is in the folder.
    """
    groups: list[list[Path]] = []
    texts: list[str] = []
    skipped, absent = 0, []
    for folder in folders:
        try:
            entries = [path for path in sorted(folder.iterdir()) if not path.is_dir()]
        except OSError:  # missing folder, or one this account cannot read
            absent.append(folder)
            continue
        images = [path for path in entries if _usable(path)]
        kept = images[:_MAX_PER_FOLDER]
        exemplars = _exemplars(kept, _MAX_EXEMPLARS - len(texts))
        texts.extend(exemplars)
        # A consumed `.txt` was neither an image nor waste, so it is not "skipped"; one that was
        # empty, unreadable or past the run-wide cap still is, and the log line stays honest.
        skipped += len(entries) - len(images) - len(exemplars)
        if images:
            groups.append(kept)
        else:  # an empty folder is absence, not an error (10 §10)
            absent.append(folder)
    return groups, texts, skipped, absent


def _exemplars(images: Sequence[Path], room: int) -> list[str]:
    """A16 — the sibling `.txt` beside each pooled image, read UTF-8 and size-capped.

    Args:
        images: the folder's pooled images, in the order they will be attached.
        room: how many more exemplars the run-wide `_MAX_EXEMPLARS` cap still allows; `<= 0`
            reads nothing, so a huge first folder cannot make the scan walk every later one.

    Returns:
        The captions found, in image order. A missing, empty or unreadable sidecar contributes
        nothing and is never an error — this whole channel is enrichment of an asset that was
        already pickable without it (`_usable` is untouched, so a lone `.txt` remains skipped).

    Decoded `utf-8-sig` with `errors="replace"`: these files are hand-authored on a Windows box,
    so a BOM is likely and a stray byte is possible, and neither is worth failing a free run over.
    Over the cap the text is cut at the last whitespace before it, never mid-word — the same rule
    the prompt engine applies, for the same reason (a mangled tail reads as a typo the copywriter
    might then imitate).
    """
    out: list[str] = []
    for image in images:
        if len(out) >= max(0, room):
            break
        sidecar = image.with_suffix(_TEXT_SUFFIX)
        try:
            with sidecar.open("rb") as handle:
                raw = handle.read(_MAX_TEXT_BYTES + 1)
        except OSError:  # absent (the common case), unreadable, or a directory named `01.txt`
            continue
        # CRLF -> LF: these are Notepad-authored files, and a stray `\r` inside a prompt line is
        # noise the model has to interpret. Line breaks are KEPT — a caption's shape (short lines,
        # deliberate stanza breaks) is part of what makes it worth showing the copywriter.
        text = (raw[:_MAX_TEXT_BYTES].decode("utf-8-sig", errors="replace")
                .replace("\r\n", "\n").replace("\r", "\n").strip())
        if len(raw) > _MAX_TEXT_BYTES:
            cut = max(text.rfind(" "), text.rfind("\n"))
            text = text[:cut].rstrip() if cut > 0 else text
        if text:
            out.append(text)
    return out


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
    """This asset's images: one coherent folder under `exclusive`, one rotating image otherwise.

    `index` is the asset's position in this run's sorted `asset_id` list, so the whole rotation is
    a pure function of the plan — a re-run of the same plan picks the same pictures.

    Under `exclusive` the folder rotates AND the window inside it rotates (A17). Rotating only the
    folder was the trap: the shipped `exclusive` branch sliced `group[:count]`, so with the one
    configured folder every creative in the run rendered from the same first three files — eight
    creatives, one set of pictures. The window advances once per full pass over the folders, so
    consecutive assets drawing on one folder get consecutive, non-overlapping windows until the
    folder wraps, and a folder smaller than `count` simply yields all of itself once.
    """
    if count > 1:
        group = pool.groups[index % len(pool.groups)]
        size = min(count, len(group))
        turn = index // len(pool.groups)  # how many times this folder has been drawn from already
        start = (turn * size) % len(group)
        return [group[(start + offset) % len(group)] for offset in range(size)]
    images = pool.images
    return [images[index % len(images)]]


def _trimmed(item: TrendItem, keep: int) -> TrendItem:
    """A render-side copy of one trend with its reference groups cut to `keep` (0 empties them).

    A copy, not an edit: Select's verdicts, `text_only` and the analysis call all read the
    originals, and only the render stage sees the room made for inspiration images.

    `chosen_post_ids` travels WITH the urls it belongs to (FR-7): under `exclusive` no trend image
    is attached at all, so the copy names no used posts and history cannot burn an id this run
    never showed anyone. A trimmed-but-present set is still that one chosen set — the set, not the
    individual url, is the unit FR-7 records, and splitting ids per url is exactly the index
    alignment `ReferenceSet` exists to abolish.
    """
    if not item.reference_groups or all(len(group) <= keep for group in item.reference_groups):
        return item
    groups = [group[:keep] for group in item.reference_groups if group[:keep]]
    return replace(item, reference_groups=groups,
                   chosen_post_ids=item.chosen_post_ids if groups else ())


def _note(log: LogWriter | None, event: str, level: str, message: str, **data: Any) -> None:
    """One line to the console logger, and to both run logs when a run owns one."""
    logger.log(logging.WARNING if level == "warn" else logging.INFO, "%s", message)
    if log is not None:
        log.event(event, message, level=level, **data)


__all__ = ["InspirationPool", "Mix", "apply_mix", "load_pool"]
