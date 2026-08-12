"""Meta-style registry — the post-pivot visual authority (FR-290/291/295).

Callers import `hypesocials.styles` and nothing under it. Six calls, one concept — which look
each creative wears, and which pictures prove it:

    registry = load_registry([config.prompts_dir, PROMPTS_DIR])   # once per run
    errors, warnings = validate(registry, config)                 # pre-flight; any error = exit 2
    assign_styles(live, registry, config.branding.brand)          # after plan.assign()
    assign_branding(live, config.branding.brand_ratio)
    style = style_for(registry, entry.style_key)                  # at assembly
    refs = pick_reference_window(style, entry.trend_reuse_index, config.styles.refs_per_job)

A style is authored once in `prompts/styles.yaml` and ASSIGNED, where the pre-pivot vision brief
was re-derived per trend by an LLM from whatever pictures that trend happened to carry. That is
the whole point of the pivot: the look is ours, the topic is theirs.

Invariants: the registry is resolved override-first through the FR-174 `prompts_dir` seam and has
**no built-in third tier** — a missing, unreadable or invalid registry is a `StyleRegistryError`
and an FR-295 pre-flight exit 2, never a silent default (a built-in copy would be eight styles of
invisible drift against the file the operator is editing). Registry order is FILE order and the
rotation depends on it. Every assignment is a pure function of `entry.order` over the
brand-filtered pool — no cursor, no shared state — so a trimmed or dropped entry never reshuffles
another entry's style, and a re-run of the same plan picks the same styles and the same pictures.
`reference_images` resolve against the REPO ROOT, not against the registry's own folder (the
briefs.py precedent), because one registry lists paths in two unrelated trees (`Inspiration/` and
`hypedigitaly branding/`) — the deviation is documented in the PRD.

I/O: `load_registry` reads one small local YAML file synchronously at startup, exactly as
`config.py` reads `configs/*.yaml` — that is the precedent, and neither runs on a hot event loop.
`pick_reference_window` stats and sniffs a handful of local files per job; nothing here downloads,
uploads or opens image pixels.

Do not: key the `brand_slot` rule off a style name (an override registry with its own keys must
keep the rule — B3); re-implement the `carousel_role` reading anywhere else (`fmt_affine` owns
it); render anything (`prompts_engine` owns rendering and its no-filesystem contract, this module
owns the files — §1.4 module split); upload the paths this module returns (`generate/refs.py`
does that through the `UploadMemo`).
"""

from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import ROOT, Config
from .models import LayoutZone, MetaStyle, PlanEntry
from .util import read_text

logger = logging.getLogger(__name__)

#: The one file name this module looks for inside each candidate folder (FR-290).
_REGISTRY_NAME = "styles.yaml"
_FORMATS = ("image", "carousel", "reel")
_BRANDS = ("hypedigitaly", "hypelead")
#: FR-295 warning thresholds. 120 words is `render_prompt`'s stated ceiling (§1.3); under three
#: usable styles the rotation stops being a rotation and every creative in a batch looks alike.
_MAX_RENDER_WORDS = 120
_MIN_USABLE_STYLES = 3
#: M9 either/or-leak heuristic, matched case-insensitively: an unresolved "teal or cobalt" reaches
#: the image model as a choice it makes differently on every slide of one deck.
# DISCLOSED W3.5 barrier-grep exemption (SESSION-D closeout): the middle marker is a FUNCTIONAL
# literal — §1.3's leak heuristic must match the word itself in an author's render_prompt, so the
# excision grep records this one line and ignores it rather than obfuscating the string.
_VARIANT_MARKERS = (" or ", "variant ", "either ")

# --- reference-image validation, ported from the retired local-pool module (W3.5) --------------
# Ported rather than imported: the source module was retired at W3.5 and this is the surviving reader
# of local reference bytes. Same rules, same reason — "validate" has to mean the bytes ARE an
# image, not just that the name says so (a renamed .txt fails the Kie upload and costs the job a
# reference for nothing).
_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"})
_MAGIC: tuple[bytes, ...] = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a",
                             b"RIFF", b"BM")
_MAX_BYTES = 30 * 1024 * 1024  # Kie's documented per-image ceiling (20 §8b)

#: Local file path -> the Kie URL it was uploaded to, built ONCE per run and thrown away with the
#: run (FR-200/FR-244). Run-scoped on purpose: Kie's file host keeps an upload roughly 24 h, so a
#: URL memoized across runs is a reference that silently 404s mid-batch. Within one run the memo
#: is what makes a style's five brand cards upload once instead of once per job.
#: `generate/refs.py` performs the uploads and fills the memo (W2 — T2.3); this module only owns
#: the type and the discipline.
UploadMemo = dict[Path, str]


class StyleRegistryError(Exception):
    """Missing/unparseable registry or fatally invalid entry — FR-295 exit-2 material.

    `str(e)` is the whole operator-facing line: what was wrong, where, and what it costs.
    """


@dataclass(slots=True)
class StyleRegistry:
    """Every meta-style this run may assign, plus where it came from (FR-184 attribution)."""

    version: int
    styles: list[MetaStyle]  # stable FILE order — the rotation is defined over it
    origin: str  # resolved absolute path of the styles.yaml actually used
    content_hash: str  # sha256[:12] of the file text, same recipe as prompts_engine._hash

    def __len__(self) -> int:
        return len(self.styles)


# --------------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------------


def load_registry(dirs: Sequence[Path | str]) -> StyleRegistry:
    """The `styles.yaml` in force, resolved override-first: the FIRST folder that has one wins.

    Args:
        dirs: candidate folders in precedence order — callers pass
            `(config.prompts_dir, PROMPTS_DIR)`; falsy entries are skipped so an unset
            `prompts_dir` needs no caller-side branch (FR-174, the PromptEngine seam).

    Raises:
        StyleRegistryError: no `styles.yaml` in any folder, or the first one found is unreadable,
            is not valid YAML, is not a mapping, has no list-valued `styles:`, or carries an entry
            that is not a keyed mapping. There is no built-in fallback tier (§1.3 decision).
    """
    searched: list[str] = []
    for folder in dirs:
        if not folder:
            continue
        path = Path(folder) / _REGISTRY_NAME
        searched.append(str(path))
        if not path.is_file():
            continue
        try:
            text = read_text(path)
        except OSError as exc:
            raise StyleRegistryError(
                f"{path}: the style registry cannot be read ({exc.strerror or exc}) — there is no "
                "built-in fallback, so this run has no visual authority (FR-290/295)") from None
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise StyleRegistryError(f"{path}: the style registry is not valid YAML — "
                                     f"{_one_line(exc)} (FR-290/295)") from None
        if not isinstance(data, Mapping):
            raise StyleRegistryError(
                f"{path}: the style registry must be a mapping with `version:` and `styles:` at "
                "the top level (FR-290)")
        raw = data.get("styles")
        if not isinstance(raw, list):
            raise StyleRegistryError(
                f"{path}: `styles:` must be a list of style blocks — got "
                f"{type(raw).__name__ if raw is not None else 'nothing'} (FR-290)")
        styles = [_style(item, path, index) for index, item in enumerate(raw)]
        return StyleRegistry(version=_version(data.get("version")), styles=styles,
                             origin=str(path), content_hash=_hash(text))
    raise StyleRegistryError(
        f"no {_REGISTRY_NAME} found — looked in: {', '.join(searched) or '(nowhere)'}. The style "
        "registry has no built-in default: without it nothing can be rendered (FR-290/295)")


def _style(item: Any, path: Path, index: int) -> MetaStyle:
    """One YAML block as a `MetaStyle`. Shape errors raise; CONTENT is `validate()`'s business.

    The split matters: a block that is not a keyed mapping cannot become an object at all, while
    an empty `render_prompt` or a bogus `format_affinity` is a normal, reportable pre-flight
    finding the operator should see listed with all the others rather than one at a time.
    """
    if not isinstance(item, Mapping):
        raise StyleRegistryError(f"{path}: styles[{index}] is not a mapping — every style is a "
                                 "block of key/value pairs (FR-290)")
    key = str(item.get("key") or "").strip()
    if not key:
        raise StyleRegistryError(f"{path}: styles[{index}] has no `key` — a style without a key "
                                 "cannot be assigned, logged or looked up (FR-290)")
    return MetaStyle(
        key=key,
        render_prompt=str(item.get("render_prompt") or "").strip(),
        subject_mode=str(item.get("subject_mode") or "scene_open").strip(),
        layout_zones=_zones(item.get("layout_zones")),
        # Affinities are lower-cased here so `[Image]` in a hand-edited override is a style that
        # works, not a pre-flight error about a capital letter.
        format_affinity=[value.lower() for value in _strings(item.get("format_affinity"))],
        brand_affinity=[value.lower() for value in _strings(item.get("brand_affinity"))],
        brand_slot=bool(item.get("brand_slot")),
        text_density=str(item.get("text_density") or "minimal").strip(),
        max_onimage_chars=_int_map(item.get("max_onimage_chars")),
        motion_profile=str(item.get("motion_profile") or "photographic").strip(),
        palette=_strings(item.get("palette")),
        typography=str(item.get("typography") or "").strip(),
        text_placement=str(item.get("text_placement") or "").strip(),
        image_treatment=str(item.get("image_treatment") or "").strip(),
        visual_pacing=str(item.get("visual_pacing") or "").strip(),
        per_format_guidance=_str_map(item.get("per_format_guidance")),
        exclusions=_strings(item.get("exclusions")),
        reference_images=_strings(item.get("reference_images")),
    )


def _zones(value: Any) -> list[LayoutZone]:
    """`layout_zones:` as ordered `LayoutZone`s; `role: brand_slot` marks the signature zone."""
    return [LayoutZone(position=str(item.get("position") or "").strip(),
                       content=str(item.get("content") or "").strip(),
                       text_treatment=str(item.get("text_treatment") or "").strip(),
                       role=str(item.get("role") or "").strip())
            for item in (value if isinstance(value, list) else []) if isinstance(item, Mapping)]


def _strings(value: Any) -> list[str]:
    """A YAML sequence of scalars as stripped strings; a bare scalar counts as one entry."""
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [text] if (text := str(value).strip()) else []
    if isinstance(value, Sequence):
        return [text for item in value if (text := str(item).strip())]
    return []


def _int_map(value: Any) -> dict[str, int]:
    """`max_onimage_chars:` — non-numeric values are dropped, so a typo is a missing cap (which
    `prompts_engine` then takes from config) rather than a crash mid-assembly."""
    out: dict[str, int] = {}
    for name, raw in (value.items() if isinstance(value, Mapping) else ()):
        try:
            out[str(name)] = int(raw)
        except (TypeError, ValueError):
            logger.debug("styles: %s = %r is not a character count, ignored", name, raw)
    return out


def _str_map(value: Any) -> dict[str, str]:
    return {str(name): str(raw).strip()
            for name, raw in (value.items() if isinstance(value, Mapping) else ())}


def _version(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def _hash(text: str) -> str:
    """Same recipe as `prompts_engine._hash` — one attribution vocabulary for prompts and styles."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _one_line(exc: Exception) -> str:
    return " ".join(str(exc).split())


# --------------------------------------------------------------------------------------------
# Predicates — the registry's own vocabulary, so no caller re-derives it
# --------------------------------------------------------------------------------------------


def brand_ok(style: MetaStyle, brand: str) -> bool:
    """Is this style assignable under `brand`? An empty `brand_affinity` is brand-neutral (B3)."""
    return not style.brand_affinity or brand in style.brand_affinity


def fmt_affine(style: MetaStyle, creative_format: str) -> bool:
    """Can this style take a `creative_format` entry?

    Plain membership for `image` and `reel`. For `carousel` the marker key
    `per_format_guidance.carousel_role` narrows it: a `slides_only` style (meme-caricature,
    ugc-tabletop) may never anchor a deck, and under anchor-chaining slide 1 IS the deck's style —
    so slides-only means the style is never assigned to a carousel entry at all. `cover_only`
    styles stay affine: their grammar is the anchor's, which is exactly what gets assigned.
    """
    if creative_format not in style.format_affinity:
        return False
    if creative_format == "carousel":
        return style.per_format_guidance.get("carousel_role") != "slides_only"
    return True


# --------------------------------------------------------------------------------------------
# Pre-flight validation (FR-295)
# --------------------------------------------------------------------------------------------


def validate(reg: StyleRegistry, config: Config) -> tuple[list[str], list[str]]:
    """Everything wrong with this registry for THIS run, as `(errors, warnings)`.

    Any error is a pre-flight exit 2 (FR-295): the registry is the visual authority, and a run
    that cannot dress a requested format has nothing to render. Warnings are printed and the run
    continues — notably a missing reference image, which only degrades its style to text-only
    (tag `style_refs_missing`) and must never cost the operator a batch.
    """
    errors: list[str] = []
    warnings: list[str] = []
    brand = config.branding.brand
    seen: set[str] = set()
    for style in reg.styles:
        where = f"style {style.key!r} ({reg.origin})"
        if style.key in seen:
            errors.append(f"{where}: duplicate key — style keys are how entries, meta.yaml and "
                          "the gallery refer to a look, so they must be unique (FR-290)")
        seen.add(style.key)
        if not style.render_prompt:
            errors.append(f"{where}: `render_prompt` is empty — a style with no instruction "
                          "renders nothing (FR-290)")
        if not style.format_affinity:
            errors.append(f"{where}: `format_affinity` is empty — name at least one of "
                          f"{', '.join(_FORMATS)} (FR-290)")
        if bad := [value for value in style.format_affinity if value not in _FORMATS]:
            errors.append(f"{where}: unknown format_affinity {', '.join(sorted(bad))} — allowed: "
                          f"{', '.join(_FORMATS)} (FR-290)")
        if bad := [value for value in style.brand_affinity if value not in _BRANDS]:
            errors.append(f"{where}: unknown brand_affinity {', '.join(sorted(bad))} — allowed: "
                          f"{', '.join(_BRANDS)} (FR-290)")
        warnings.extend(_style_warnings(style, where))
    usable = [style for style in reg.styles if brand_ok(style, brand)]
    if not usable:
        errors.append(f"{reg.origin}: no style is usable under brand {brand!r} — every entry names "
                      "a different brand in `brand_affinity`, so nothing can be assigned (FR-295)")
    elif len(usable) < _MIN_USABLE_STYLES:
        warnings.append(f"{reg.origin}: only {len(usable)} style(s) usable under brand {brand!r} — "
                        "a batch of creatives will repeat the same look (FR-291)")
    for fmt, count in sorted(config.run.formats.items()):
        if count > 0 and not any(fmt_affine(style, fmt) for style in usable):
            errors.append(
                f"{reg.origin}: {count} {fmt}(s) requested but no style under brand {brand!r} is "
                f"affine to {fmt} — either add one or set run.formats.{fmt} to 0 (FR-295)")
    return errors, warnings


def _style_warnings(style: MetaStyle, where: str) -> list[str]:
    """Advisory findings: over-long prompt, unresolved variants, unusable reference images."""
    out: list[str] = []
    if (words := len(style.render_prompt.split())) > _MAX_RENDER_WORDS:
        out.append(f"{where}: `render_prompt` is {words} words — over the {_MAX_RENDER_WORDS}-word "
                   "ceiling the tail competes with the TEXT block for the model's attention")
    lowered = style.render_prompt.lower()
    if leaks := [marker.strip() for marker in _VARIANT_MARKERS if marker in lowered]:
        out.append(f"{where}: `render_prompt` still offers a choice ({', '.join(leaks)}) — the "
                   "image model resolves it differently on every slide of one deck; resolve it to "
                   "one value (M9)")
    for path in _resolved(style):
        if not _usable(path):
            out.append(f"{where}: reference image {path} is missing or is not a usable image — "
                       "this style degrades to text-only for this run (tag style_refs_missing)")
    return out


# --------------------------------------------------------------------------------------------
# Assignment — pure functions of `entry.order` (FR-291)
# --------------------------------------------------------------------------------------------


def assign_styles(entries: Sequence[PlanEntry], registry: StyleRegistry, brand: str) -> None:
    """Set `entry.style_key` on every entry, by stateless order-indexed scan over the pool.

    There is deliberately NO shared cursor: each entry's pick is a pure function of its own
    `entry.order` over the brand-filtered pool, so a trimmed or dropped sibling never reshuffles
    anyone else's style, and a re-preview against the same topic set reproduces the assignment
    exactly. `entry.order` is assigned once at plan build and is GAPPED over live entries after
    `_confirm` trims and `_select` drops — the scan is defined over the order VALUE, so gaps are
    harmless by construction.

    Raises:
        StyleRegistryError: the brand filter left an empty pool. Unreachable in a live run —
            `validate()` makes that an FR-295 pre-flight exit 2 — and defensive here for the same
            reason the exhausted scan below is: this function must never assign a key that is not
            in the registry.
    """
    pool = [style for style in registry.styles if brand_ok(style, brand)]
    if not pool:
        raise StyleRegistryError(
            f"{registry.origin}: no style is usable under brand {brand!r} — assignment has nothing "
            "to draw on (FR-291; pre-flight should have refused this run, FR-295)")
    for entry in sorted(entries, key=lambda item: item.order):
        entry.style_key = _scan(pool, entry.order, entry.creative_format, entry.asset_id).key


def _scan(pool: Sequence[MetaStyle], order: int, creative_format: str, asset_id: str) -> MetaStyle:
    """The order-indexed scan itself: start at `order`, walk the pool once, take the first style
    affine to this format. An exhausted scan keeps the LAST candidate rather than leaving the entry
    style-less — defensive only, since `validate()` refuses a run whose requested format has no
    affine style at all.
    """
    cand = pool[order % len(pool)]
    for step in range(len(pool)):
        cand = pool[(order + step) % len(pool)]
        if fmt_affine(cand, creative_format):
            return cand
    logger.debug("styles: no %s-affine style for %s, falling back to %r",
                 creative_format, asset_id, cand.key)
    return cand


def assign_branding(entries: Sequence[PlanEntry], ratio: float) -> None:
    """Set `entry.branded` — the deterministic wordmark rotation (FR-291/292).

    Branded iff `floor((order + 1) * ratio) > floor(order * ratio)`: supply-independent, keyed on
    the entry's own order, so the exact count over the FULL emitted plan is `floor(N * ratio)` —
    never `round` (N=7, ratio=0.5 gives 3, not 4). Over the live subset after trims the branded
    count is simply the surviving orders satisfying the predicate: a trim never re-brands a
    creative that survived it.
    """
    for entry in entries:
        entry.branded = math.floor((entry.order + 1) * ratio) > math.floor(entry.order * ratio)


def style_for(reg: StyleRegistry, key: str) -> MetaStyle:
    """The style behind an `entry.style_key`.

    Raises:
        StyleRegistryError: unknown key. Names the key and the registry file, because the only way
            to get here is a stale `style_key` (a meta.yaml re-read, an edited registry mid-run)
            and the operator needs to know WHICH file no longer has it.
    """
    for style in reg.styles:
        if style.key == key:
            return style
    raise StyleRegistryError(
        f"{reg.origin}: no style named {key!r} — the registry defines "
        f"{', '.join(style.key for style in reg.styles) or '(nothing)'} (FR-290)")


# --------------------------------------------------------------------------------------------
# Reference images — the A17 window rotation, re-homed from the Inspiration pool
# --------------------------------------------------------------------------------------------


def pick_reference_window(style: MetaStyle, reuse_index: int, refs_per_job: int) -> list[Path]:
    """This job's slice of the style's own reference images, as local paths.

    `reuse_index` is the creative's turn among the siblings sharing its topic
    (`PlanEntry.trend_reuse_index`), so consecutive siblings drawing on one style get consecutive
    windows instead of the same first two files — which is the whole reason a style may list five
    (hypelead-brand-card does). Deterministic: same plan, same pictures.

    Unusable entries (wrong suffix, empty/oversized, bytes that are not an image) are dropped
    silently here; `validate()` is where the operator hears about them, once, at pre-flight. An
    empty result is the legitimate text-only degrade (`style_refs_missing`), never an error.
    """
    usable = [path for path in _resolved(style) if _usable(path)]
    width = min(refs_per_job, len(usable))
    if width <= 0:
        return []
    if len(usable) <= width:
        return usable
    return [usable[(reuse_index + offset) % len(usable)] for offset in range(width)]


def _resolved(style: MetaStyle) -> list[Path]:
    """Registry paths against the REPO ROOT (§1.3) — the registry spans two unrelated trees."""
    return [ROOT / raw for raw in style.reference_images]


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


__all__ = ["StyleRegistry", "StyleRegistryError", "UploadMemo", "assign_branding", "assign_styles",
           "brand_ok", "fmt_affine", "load_registry", "pick_reference_window", "style_for",
           "validate"]
