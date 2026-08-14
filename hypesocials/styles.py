"""Meta-style registry — the post-pivot visual authority, TEXT-ONLY (FR-290/291/295, D46).

Callers import `hypesocials.styles` and nothing under it. Five calls, one concept — which look
each creative wears, written down in words:

    registry = load_registry([config.prompts_dir, PROMPTS_DIR])   # once per run
    errors, warnings = validate(registry, config)                 # pre-flight; any error = exit 2
    assign_styles(live, registry, config.branding.brand,          # after plan.assign()
                  enabled=config.styles.enabled,
                  branding_enabled=config.branding.enabled)
    assign_branding(live, config.branding.brand_ratio,
                    enabled=config.branding.enabled)
    style = style_for(registry, entry.style_key)                  # at assembly

A style is authored once in `prompts/styles.yaml` and ASSIGNED, where the pre-pivot vision brief
was re-derived per trend by an LLM from whatever pictures that trend happened to carry. That is
the whole point of the pivot: the look is ours, the topic is theirs.

**A style is words, never pictures (D46/FR-18).** The registry's PICTURE channel is withdrawn:
there is no `reference_images` field, no per-job window, no rotation and no upload — a style
qualifies its render through `render_prompt`, `layout_zones`, `palette`, `typography`,
`text_placement`, `image_treatment` and `visual_pacing` alone (FR-17). The only images any render
job still attaches are a campaign brief's own product photos (FR-144/145) and the chained
artifacts the format modules produce themselves — the carousel anchor (FR-95) and the reel seed
frame (FR-24). Nothing in this module reads, stats, sniffs or returns a file path.

Invariants: the registry is resolved override-first through the FR-174 `prompts_dir` seam and has
**no built-in third tier** — a missing, unreadable or invalid registry is a `StyleRegistryError`
and an FR-295 pre-flight exit 2, never a silent default (a built-in copy would be eight styles of
invisible drift against the file the operator is editing). Registry order is FILE order and the
rotation depends on it. Every assignment is a pure function of `entry.order` over the filtered
pool — no cursor, no shared state — so a trimmed or dropped entry never reshuffles another entry's
style, and a re-run of the same plan picks the same styles.

**The pool is filtered twice, never edited (FR-314/D-E, FR-318).** `brand_ok` drops what the active
brand cannot wear (B3) plus — while `branding.enabled` is false — every `brand_slot` house-card
style, then `selected` keeps only what `config.styles.enabled` names — an operator's
per-run curation of the authored looks, empty meaning all of them. `usable_styles` is the one
place those two are composed, so the menu's count, the pre-flight refusal, the preview and the
paid run cannot disagree. The selector is a CONFIG key naming registry keys; it carries no style
content and no render text, so the registry remains the sole visual authority.

I/O: `load_registry` reads one small local YAML file synchronously at startup, exactly as
`config.py` reads `configs/*.yaml` — that is the precedent, and neither runs on a hot event loop.
That single read is the whole of this module's filesystem contact.

Do not: key the `brand_slot` rule off a style name (an override registry with its own keys must
keep the rule — B3); re-implement the `carousel_role` reading anywhere else (`fmt_affine` owns
it); render anything (`prompts_engine` owns rendering and its no-filesystem contract, this module
owns the one file — §1.4 module split); reintroduce a style picture channel in any shape — the
upload memo and the brief-photo attachment now live entirely in `generate/refs.py`.
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

from .config import Config
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
        # No `reference_images`: the picture channel is withdrawn (D46/FR-18/FR-290). A stale
        # registry that still lists the key loads clean and the key is simply ignored — an
        # operator editing an old file gets a run, not a shape error over a dead field.
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


def brand_ok(style: MetaStyle, brand: str, *, branding_enabled: bool = True) -> bool:
    """Is this style assignable under `brand`? An empty `brand_affinity` is brand-neutral (B3).

    `branding_enabled=False` (FR-318's master switch) additionally drops every `brand_slot: true`
    style. That flag means "this style IS a brand's own house card" — its layout is a logo lockup
    and a CTA bar, and its whole grammar is the signature. Leaving it in the pool with the wordmark
    switched off would render the brand's furniture around an empty slot, which is both the M11
    hallucination site and a self-branded creative on a run that asked for none. Dropping it here
    rather than at assignment keeps ONE definition of the pool: the menu count, the pre-flight
    refusal, the preview and the paid run all narrow identically.
    """
    if not branding_enabled and style.brand_slot:
        return False
    return not style.brand_affinity or brand in style.brand_affinity


def selected(style: MetaStyle, enabled: Sequence[str]) -> bool:
    """Is this style inside the operator's FR-314 selection? An empty selection is everything.

    The second of the two filters that narrow the rotation, and deliberately the same SHAPE as
    `brand_ok` beside it: a membership test with a permissive empty case, so a config that says
    nothing about styles rotates over exactly the pool it rotated over before FR-314 existed.

    Where `brand_ok` is a fact about the style (a HypeLead card cannot be signed HypeDigitaly),
    this is a fact about the RUN — the operator curating which authored looks today's batch wears
    (D47/D-E). It never edits, reorders or reweights the registry: the pool keeps FILE order, so a
    selection of three styles rotates in the order those three appear in `styles.yaml` and the
    order-indexed scan stays as deterministic as it is over the full registry.
    """
    return not enabled or style.key in enabled


def usable_styles(registry: StyleRegistry, brand: str, enabled: Sequence[str] = (), *,
                  branding_enabled: bool = True) -> list[MetaStyle]:
    """The rotation pool this run actually draws on: brand filter, then FR-314 selection.

    ONE definition of "usable", because four callers ask the question and a second copy is how the
    menu's style count, the pre-flight refusal, the preview and the paid run start disagreeing
    about which styles a config can wear. Order is FILE order throughout (`assign_styles` depends
    on it).

    `branding_enabled` is FR-318's switch, folded into the FIRST filter (`brand_ok`) rather than
    added as a third: "a house-card style needs the wordmark" is a fact about the style under this
    run's brand settings, which is exactly what `brand_ok` already answers.
    """
    return [style for style in registry.styles
            if brand_ok(style, brand, branding_enabled=branding_enabled)
            and selected(style, enabled)]


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
    continues — a thin brand pool, an over-long `render_prompt`, an unresolved either/or choice.

    Post-D46 there is no reference-image check left to make: the registry declares no pictures, so
    FR-295's file-existence and magic-byte clause is moot (its wording still stands in
    `30-configuration-and-run.md`, a documented tombstone against FR-290's amended schema).

    FR-314 adds the SELECTOR's own findings on top: an unknown key in `styles.enabled` is an error
    naming both the key and everything the registry really defines, and every pool check below is
    computed over the SELECTED pool — so a selection that empties a requested format's rotation
    refuses at $0 exactly like a brand that empties it, and says which of the two did it.

    FR-318 joins the same arithmetic through `brand_ok`: with `branding.enabled` false the pool
    loses its `brand_slot: true` house cards, and a run that has nothing left keeps the ordinary
    FR-295 refusal shape — exit 2 at $0 — with the switch named as the cause.
    """
    errors: list[str] = []
    warnings: list[str] = []
    brand = config.branding.brand
    signing = config.branding.enabled  # FR-318 — the pool shrinks when self-branding is off
    enabled = list(config.styles.enabled)
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
    if selector := _selector_errors(reg, enabled):
        errors.extend(selector)
        if not any(style.key in enabled for style in reg.styles):
            # NOTHING the operator named is a real key — almost always one mistyped `--styles`.
            # The line above is the complete diagnosis, and the empty pool and every empty format
            # below are its consequences, not three separate defects. Reporting them all would bury
            # the one sentence that names the typo under two that repeat it.
            return errors, warnings
    branded_pool = [style for style in reg.styles
                    if brand_ok(style, brand, branding_enabled=signing)]
    usable = [style for style in branded_pool if selected(style, enabled)]
    if not usable:
        errors.append(_empty_pool_error(reg, brand, enabled, branded_pool, signing=signing))
    elif len(usable) < _MIN_USABLE_STYLES:
        warnings.append(f"{reg.origin}: only {len(usable)} style(s) usable under brand {brand!r}"
                        f"{_selection_note(enabled)} — a batch of creatives will repeat the same "
                        "look (FR-291)")
    for fmt, count in sorted(config.run.formats.items()):
        if count <= 0 or any(fmt_affine(style, fmt) for style in usable):
            continue
        # WHICH filter emptied this format decides the whole cure, so the message asks: were there
        # affine styles under the brand that only the selection removed? Then it is the selector's
        # doing and the operator wants those key names, not "add a style to the registry".
        blocked = [style.key for style in branded_pool if fmt_affine(style, fmt)]
        if enabled and blocked:
            errors.append(
                f"{reg.origin}: {count} {fmt}(s) requested but styles.enabled "
                f"({', '.join(enabled)}) leaves no {fmt}-affine style under brand {brand!r} — the "
                f"registry offers {', '.join(blocked)} for {fmt}; add one of those to "
                f"styles.enabled, clear the selector to use them all, or set run.formats.{fmt} to "
                "0 (FR-314/295)")
        else:
            errors.append(
                f"{reg.origin}: {count} {fmt}(s) requested but no style under brand {brand!r} is "
                f"affine to {fmt} — either add one or set run.formats.{fmt} to 0 (FR-295)")
    return errors, warnings


def _selector_errors(reg: StyleRegistry, enabled: Sequence[str]) -> list[str]:
    """FR-314: every key named in `styles.enabled` must exist in the registry that is in force.

    Refused rather than skipped, and it names the registry's ACTUAL keys in the same line: a
    mistyped selector otherwise thins the rotation silently, and the operator has no way to see
    the difference between "that key is spelled wrong" and "that style was authored differently
    than I remember". The origin matters too — an override `prompts_dir` (FR-174) may define a
    completely different key set from the shipped tree.
    """
    if not enabled:
        return []
    known = {style.key for style in reg.styles}
    unknown = [key for key in dict.fromkeys(enabled) if key not in known]
    if not unknown:
        return []
    return [f"{reg.origin}: styles.enabled names {', '.join(repr(key) for key in unknown)}, which "
            f"this registry does not define — it defines "
            f"{', '.join(style.key for style in reg.styles) or '(nothing)'}. The selector picks "
            "from the registry, it cannot add to it (FR-314)"]


def _empty_pool_error(reg: StyleRegistry, brand: str, enabled: Sequence[str],
                      branded_pool: Sequence[MetaStyle], *, signing: bool = True) -> str:
    """Nothing left to assign — worded by WHICH filter emptied it: brand, the FR-314 selector, or
    FR-318's master switch. The refusal SHAPE is one line and an exit 2 either way; only the cure
    differs, and naming the wrong dial sends the operator to edit a file that was never the
    problem."""
    # Named only when the switch REALLY removed something: a registry with no house cards at all
    # would otherwise be told to flip a dial that changes nothing about its empty pool.
    dropped = [] if signing else [style.key for style in reg.styles if style.brand_slot]
    off = (f" (branding.enabled is false, which removed the house-card style(s) "
           f"{', '.join(dropped)} — FR-318)") if dropped else ""
    if enabled and branded_pool:
        return (f"{reg.origin}: styles.enabled ({', '.join(enabled)}) leaves no style usable under "
                f"brand {brand!r}{off} — this brand can use "
                f"{', '.join(style.key for style in branded_pool)}; name at least one of those or "
                "clear styles.enabled to use them all (FR-314/295)")
    if dropped:
        return (f"{reg.origin}: no style is usable under brand {brand!r}{off} — set "
                "branding.enabled to true, or add a style this brand can wear (FR-318/295)")
    return (f"{reg.origin}: no style is usable under brand {brand!r} — every entry names "
            "a different brand in `brand_affinity`, so nothing can be assigned (FR-295)")


def _selection_note(enabled: Sequence[str]) -> str:
    """" and the styles.enabled selection", or nothing — so one warning serves both shapes."""
    return f" and the styles.enabled selection ({', '.join(enabled)})" if enabled else ""


def _style_warnings(style: MetaStyle, where: str) -> list[str]:
    """Advisory findings about the WORDS — an over-long prompt, an unresolved variant choice."""
    out: list[str] = []
    if (words := len(style.render_prompt.split())) > _MAX_RENDER_WORDS:
        out.append(f"{where}: `render_prompt` is {words} words — over the {_MAX_RENDER_WORDS}-word "
                   "ceiling the tail competes with the TEXT block for the model's attention")
    lowered = style.render_prompt.lower()
    if leaks := [marker.strip() for marker in _VARIANT_MARKERS if marker in lowered]:
        out.append(f"{where}: `render_prompt` still offers a choice ({', '.join(leaks)}) — the "
                   "image model resolves it differently on every slide of one deck; resolve it to "
                   "one value (M9)")
    return out


# --------------------------------------------------------------------------------------------
# Assignment — pure functions of `entry.order` (FR-291)
# --------------------------------------------------------------------------------------------


def assign_styles(entries: Sequence[PlanEntry], registry: StyleRegistry, brand: str,
                  enabled: Sequence[str] = (), *, branding_enabled: bool = True) -> None:
    """Set `entry.style_key` on every entry, by stateless order-indexed scan over the pool.

    There is deliberately NO shared cursor: each entry's pick is a pure function of its own
    `entry.order` over the filtered pool, so a trimmed or dropped sibling never reshuffles anyone
    else's style, and a re-preview against the same topic set reproduces the assignment exactly.
    `entry.order` is assigned once at plan build and is GAPPED over live entries after `_confirm`
    trims and `_select` drops — the scan is defined over the order VALUE, so gaps are harmless by
    construction.

    Args:
        entries: the live plan entries to dress; each gets its own `entry.order`'s pick.
        registry: the loaded `styles.yaml` — its FILE order IS the rotation order.
        brand: `config.branding.brand`, the B3 filter.
        enabled: `config.styles.enabled`, the FR-314 selector. Empty (the default) means the whole
            brand-filtered registry, which is what every pre-FR-314 caller meant. A NARROWER pool
            is a different rotation by construction — that is the point of the selector, not a
            determinism break: the same plan against the same selection assigns the same styles.
        branding_enabled: `config.branding.enabled`, FR-318's master switch. False drops the
            `brand_slot` house cards from the pool, for the same reason and with the same
            determinism as the two filters above it.

    Raises:
        StyleRegistryError: the filters left an empty pool. Unreachable in a live run —
            `validate()` makes that an FR-295/FR-314/FR-318 pre-flight exit 2 — and defensive here
            for the same reason the exhausted scan below is: this function must never assign a key
            that is not in the registry.
    """
    pool = usable_styles(registry, brand, enabled, branding_enabled=branding_enabled)
    if not pool:
        raise StyleRegistryError(
            f"{registry.origin}: no style is usable under brand {brand!r}"
            f"{_selection_note(enabled)}"
            f"{'' if branding_enabled else ' with branding.enabled false (FR-318)'}"
            " — assignment has nothing to draw on (FR-291/FR-314; "
            "pre-flight should have refused this run, FR-295)")
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


def assign_branding(entries: Sequence[PlanEntry], ratio: float, *, enabled: bool = True) -> None:
    """Set `entry.branded` — the deterministic wordmark rotation (FR-291/292/318).

    Branded iff `floor((order + 1) * ratio) > floor(order * ratio)`: supply-independent, keyed on
    the entry's own order, so the exact count over the FULL emitted plan is `floor(N * ratio)` —
    never `round` (N=7, ratio=0.5 gives 3, not 4). Over the live subset after trims the branded
    count is simply the surviving orders satisfying the predicate: a trim never re-brands a
    creative that survived it.

    `enabled=False` (FR-318's master switch, the shipped default) short-circuits the predicate
    entirely: every entry is plain, whatever `ratio` says. Writing `False` rather than skipping the
    loop is deliberate — `entry.branded` must be a stated fact on every entry, since `refs.wordmark`
    and the render prompt's branding block both read it and an unwritten value from an earlier pass
    would sign a creative on a run that asked for none.
    """
    for entry in entries:
        entry.branded = enabled and (
            math.floor((entry.order + 1) * ratio) > math.floor(entry.order * ratio))


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
# Retired here (D46/FR-18): `pick_reference_window` and its magic-byte reader. A style declares no
# pictures any more, so there is no window to rotate and nothing to sniff. The run-scoped
# `UploadMemo` type moved WITH the uploads it disciplines, into `generate/refs.py`, which is now
# the only module that turns a local file into a Kie URL (brief photos, FR-144/145).
# --------------------------------------------------------------------------------------------


__all__ = ["StyleRegistry", "StyleRegistryError", "assign_branding", "assign_styles",
           "brand_ok", "fmt_affine", "load_registry", "selected", "style_for", "usable_styles",
           "validate"]
