"""Meta-style registry — the post-pivot visual authority, TEXT-ONLY (FR-290/291/295, D46).

Callers import `hypesocials.styles` and nothing under it. Five calls, one concept — which look
each creative wears, written down in words:

    registry = load_registry([config.prompts_dir, PROMPTS_DIR])   # once per run
    errors, warnings = validate(registry, config)                 # pre-flight; any error = exit 2
    assign_styles(live, registry, config.branding.brand,          # after plan.assign()
                  enabled=config.styles.enabled,
                  branding_enabled=config.branding.enabled,
                  run_id=session.run_id,                          # v2.2.0 rotation seed
                  rotation=config.styles.rotation)
    assign_branding(live, config.branding.brand_ratio,
                    enabled=config.branding.enabled)
    style = style_for(registry, entry.style_key)                  # at assembly

`assign_styles_fixed(live, config.styles.enabled)` is the sixth call and the odd one out: the
FR-369 `--style-test` diagnostic replaces the rotation with a 1:1 walk of the `--styles` list, so
deck N wears the Nth style the operator typed. It is never reached on an ordinary run.

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
rotation depends on it. Every assignment is a pure function of `entry.order` and the run's own
rotation offset over the filtered pool — no cursor, no shared state — so a trimmed or dropped
entry never reshuffles another entry's style, and re-assigning the same plan inside one run picks
the same styles every time.

**The rotation is SEEDED per run (v2.2.0).** `rotation_seed()` turns the run id into one offset
that shifts where every scan STARTS, so two runs of the same config do not open with the same style
and a daily batch stops publishing the registry in the same marching order. Within a run nothing
about the old guarantees changes — same pool, same FILE order, same gap-proof pure function of
`entry.order` — and `styles.rotation: fixed` (or any caller that passes no run id) pins the offset
at 0, which is exactly the pre-v2.2.0 behaviour. The corollary an operator should know: a $0
preview seeds off the PREVIEW's own id, so under `seeded` it forecasts the rotation's shape, not
the paid run's key-by-key assignment; `fixed` restores that exact agreement.

**The pool is filtered twice, never edited (FR-314/D-E, FR-318).** `brand_ok` drops what the active
brand cannot wear (B3) plus — while `branding.enabled` is false — every `brand_slot` house-card
style, then `selected` keeps only what `config.styles.enabled` names — an operator's
per-run curation of the authored looks, empty meaning all of them. `usable_styles` is the one
place those two are composed, so the menu's count, the pre-flight refusal, the preview and the
paid run cannot disagree. The selector is a CONFIG key naming registry keys; it carries no style
content and no render text, so the registry remains the sole visual authority.

**This module stays OFFLINE and sync under matched assignment (D56/FR-334).** `assign_styles` is
the BASELINE every run computes — a pure function of `entry.order`, unchanged — and `style_match`
may then overwrite a winner per entry from one LLM call. The matcher lives in its own leaf module
and IMPORTS the predicates above (`usable_styles`, `fmt_affine`, `brand_ok`, `selected`) so a
candidate pool is narrowed by exactly the rules the rotation is narrowed by; the only thing this
module owes it is `match_profile_for`, the one sentence describing what a style is FOR. Nothing
here awaits, calls an LLM or learns what a topic is about.

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

import colorsys
import hashlib
import logging
import math
import re
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import Config
from .models import LayoutZone, ListMode, MetaStyle, PlanEntry
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
#: FR-304b (v2.2.0) — the frozen `list_mode:` shape (plan spec §4b). The first three are REQUIRED
#: once the key is present at all: a list treatment with no `layout` prose has nothing to set the
#: rows into, and a trigger pair that is not stated is a trigger pair that cannot be reviewed.
_LIST_MODE_REQUIRED = ("reflow_over_chars", "max_rows", "layout")
#: The two ways more rows may be LAID OUT. Neither loses a row, and no third value is accepted —
#: this enum is the structural guarantee behind "a reflow trigger, never a ceiling" (D50): there is
#: no spelling of `overflow` that drops, shortens or refuses text.
_LIST_MODE_OVERFLOWS = ("reflow", "two_column")


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
        # FR-290/FR-335 (D56): one or two sentences saying what KIND OF SOURCE MATERIAL this style
        # suits — the line the matcher reads when it picks a style for a creative. OPTIONAL by
        # contract, and deliberately so: a registry authored before the field existed loads clean
        # here and gets a weaker derived line from `match_profile_for` below, with one advisory
        # warning from `_style_warnings`. A missing match profile makes the MATCHER weaker; it
        # never makes a run impossible, so it is never an FR-295 error.
        match_profile=str(item.get("match_profile") or "").strip(),
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
        # FR-304b: absent is legal and means "no list treatment"; present-but-malformed raises,
        # because a half-parsed layout rule silently changes what a paid deck looks like.
        list_mode=_list_mode(item.get("list_mode"), path, key),
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


def _list_mode(value: Any, path: Path, key: str) -> ListMode | None:
    """`list_mode:` as a `ListMode` — the style's list treatment, or `None` when it declares none.

    This is a SHAPE check and therefore raises rather than reporting through `validate()`, exactly
    like a style block that is not a mapping: the value either becomes a `ListMode` or it cannot
    become one at all, and both routes end at the same FR-295 pre-flight exit 2 with $0 spent
    (`preflight._check_styles` catches `StyleRegistryError` and grades it as a refusal).

    Refusing is the conservative answer here, not the strict one. `list_mode` is the only registry
    field that changes how a MAPPED PANEL is set, and every failure mode of a half-read one is
    silent: a typo'd `max_rows` would leave the trigger permanently off, an unknown `overflow` word
    would leave the model to invent what "does not fit" means, and either way the operator finds
    out from a paid deck rather than from a refusal. So the four keys are read strictly:

    - `reflow_over_chars`, `max_rows`: required, whole numbers, `>= 0`. **`0` disables that
      trigger** — the INVERTED sense of `max_onimage_chars`' "0 = no ceiling", because this is a
      trigger and that is a ceiling (spec §4b says so out loud, and the `styles.yaml` authoring
      block repeats it). `max_rows: 0` disabling the row trigger is the same reading: a threshold
      that fires on "more than zero rows" would make every panel a list, which is not a trigger.
    - `layout`: required, non-empty — the prose the render prompt executes. A list treatment with
      nothing to set the rows INTO is a declaration with no effect.
    - `overflow`: optional, defaulting to `ListMode`'s own `reflow`; one of `_LIST_MODE_OVERFLOWS`
      when present. Both values lay MORE ROWS OUT; neither drops one (D50).

    Unknown keys are ignored with a debug line rather than refused — the same tolerance the
    withdrawn `reference_images` key gets in `_style` above, so a registry carrying a field a later
    version adds still runs today.
    """
    if value is None:
        return None
    where = f"{path}: style {key!r} `list_mode`"
    if not isinstance(value, Mapping):
        raise StyleRegistryError(
            f"{where} is not a mapping — it is a block of "
            f"{', '.join(_LIST_MODE_REQUIRED)} (+ optional overflow) key/value pairs, or it is "
            "absent entirely, which is legal and means this style has no list treatment "
            "(FR-304b/295)")
    for name in _LIST_MODE_REQUIRED:
        if value.get(name) is None:
            raise StyleRegistryError(
                f"{where} has no `{name}` — a list treatment states both triggers and the layout "
                f"it sets rows into; required keys are {', '.join(_LIST_MODE_REQUIRED)} "
                "(FR-304b/295)")
    layout = str(value.get("layout") or "").strip()
    if not layout:
        raise StyleRegistryError(
            f"{where}.layout is empty — it is the prose the render prompt executes when a panel "
            "trips a trigger, so an empty one is a list treatment that treats nothing (FR-304b)")
    overflow = str(value.get("overflow") or "reflow").strip().lower()
    if overflow not in _LIST_MODE_OVERFLOWS:
        raise StyleRegistryError(
            f"{where}.overflow is {overflow!r} — allowed: "
            f"{', '.join(_LIST_MODE_OVERFLOWS)}. Both lay more rows out; there is deliberately no "
            "value that drops, shortens or refuses a row (FR-304b/D50)")
    for name in value:
        if str(name) not in (*_LIST_MODE_REQUIRED, "overflow"):
            logger.debug("styles: %s.%s is not a list_mode key, ignored", where, name)
    return ListMode(reflow_over_chars=_list_int(value, "reflow_over_chars", where),
                    max_rows=_list_int(value, "max_rows", where),
                    layout=layout, overflow=overflow)


def _list_int(value: Mapping[Any, Any], name: str, where: str) -> int:
    """One `list_mode` threshold: a whole number `>= 0`, or an FR-295 refusal naming the key.

    `bool` is rejected before `int` because `True` is an `int` in Python and `max_rows: yes` is a
    YAML shape an author can genuinely write — it would arrive as the threshold `1`.
    """
    raw = value.get(name)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise StyleRegistryError(
            f"{where}.{name} is {raw!r} — it must be a whole number of "
            f"{'characters' if name == 'reflow_over_chars' else 'rows'}, 0 or more, where 0 turns "
            "this trigger off (FR-304b)")
    return raw


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


def _snippet(text: str, limit: int = 60) -> str:
    """The opening of some prose, whitespace-collapsed and cut to `limit` characters with an
    ellipsis when it was cut — enough for an operator to find the line in `styles.yaml` without
    printing a paragraph into a console the caller wraps at 78 characters."""
    flat = " ".join(text.split())
    return f"{flat[:limit]}…" if len(flat) > limit else flat


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


def is_list_panel(style: MetaStyle | None, panel_text: str) -> bool:
    """Does THIS panel's text trip THIS style's list trigger (FR-304b)?

    The registry's vocabulary, beside `brand_ok` and `fmt_affine`, for the same reason: the reading
    of a `list_mode` threshold belongs to the module that parses it, so `prompts_engine` — the one
    caller — asks a question instead of re-deriving an answer.

    True means "this panel is a LIST and must be SET as one". It never means "this panel is too
    long": nothing downstream of this predicate may drop, shorten or refuse a word, and the only
    thing a True answer changes is the layout prose the slide template receives in its own
    `{{list_treatment}}` slot (Session 5.5/F1-A; formerly a gated append to `{{layout_zones}}`). That is also
    why `copywrite._panel_verdict` never calls it (D50) — no drop path gains a style input.

    Either threshold fires independently, and `0` turns its own trigger off (`_list_mode`). A style
    with no `list_mode`, or an empty panel, is never a list.
    """
    mode = style.list_mode if style is not None else None
    if mode is None or not (body := panel_text.strip()):
        return False
    if 0 < mode.reflow_over_chars < len(body):
        return True
    return 0 < mode.max_rows < len(body.splitlines())


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


def match_profile_for(style: MetaStyle) -> str:
    """What this style is FOR, in one line — the sentence the FR-334 matcher matches on.

    The registry's vocabulary again, beside `brand_ok` and `fmt_affine`: `style_match` describes
    each candidate to the LLM through this one call, so there is a single answer to "what does this
    style suit" and a caller cannot invent a second one.

    Authored `match_profile` wins whenever there is one. Otherwise the answer is DERIVED from the
    first sentence of `render_prompt` (FR-290/FR-335), and that derivation is deliberately the
    weaker line: `render_prompt` describes how a style LOOKS — its ground, its typography, its
    motifs — where a `match_profile` says what kind of SOURCE MATERIAL it suits. Those are
    different questions, and a matcher handed the first one has to guess the second: "near-black
    ground, glowing teal circuit motifs" tells it nothing about whether a numbered listicle deck
    belongs there. So the fallback keeps the matcher running against an old or half-authored
    registry rather than blanking a candidate out of its own pool — it is not a substitute for
    writing the real line, and `_style_warnings` says so once per style that needs it.

    Never raises and never returns `None`. A style with neither field yields `""`, which a caller
    renders as a candidate with no profile — still nameable, just undescribed.
    """
    if profile := style.match_profile.strip():
        return profile
    return _first_sentence(style.render_prompt)


def _first_sentence(text: str) -> str:
    """The first sentence of some prose, whitespace-collapsed; the whole of it if it has no end.

    A terminator only counts when a space or the end of the string follows it, so a decimal ("a
    1.5:1 crop") and a ratio do not cut the sentence in half. Prose with no terminator at all
    returns whole — a `render_prompt` written as one long unpunctuated instruction still yields
    something the matcher can read, and returning "" there would be worse than returning too much.
    """
    body = " ".join(text.split())
    for index, char in enumerate(body):
        if char in ".!?" and (index + 1 == len(body) or body[index + 1] == " "):
            return body[:index + 1]
    return body


# --------------------------------------------------------------------------------------------
# Palette contract (FR-347) — the accent rule, read off the hexes an author really wrote
# --------------------------------------------------------------------------------------------

#: FR-347's ONE switch. `False` is WARNING MODE: the palette findings ride `validate`'s warnings
#: list, the operator sees them at pre-flight and the run continues. `True` makes the same
#: findings ERRORS — FR-295 exit-2 material, $0 spent, in the same list and the same wording as
#: an empty `render_prompt`; nothing about the refusal's shape changes, only which list the lines
#: land in (`preflight._check_styles` grades whatever comes back in `errors`).
#:
#: It was born `False` because the contract was written AFTER the nineteen shipped styles were:
#: flipping it before their prose was re-authored would have refused every run of every config on
#: day one, a self-inflicted outage rather than a guard rail. SESSION K's Wave 4 brought all 19
#: shipped styles clean in warning mode and then flipped this one line to `True` (D60, 2026-08-20):
#: from here on a palette that breaks the accent rule cannot reach a paid render. Set it back to
#: `False` only to triage a registry edit, never to ship one.
_PALETTE_CONTRACT_ENFORCED = True
#: A `#RRGGBB` anywhere in a palette line, case-insensitive and word-bounded so a range written
#: `#0FCFC4-#57E6DC` reads as the two colours it names.
_HEX = re.compile(r"#([0-9A-Fa-f]{6})\b")
#: The ROLE token a palette line opens with: its leading run of capitals (plus spaces, `+` and
#: `/`), ending at the first lowercase letter, `#` or `:` on the line. `ACCENT teal #0C8897: …`
#: yields `ACCENT`, `GROUND + CAPTION BANDS cream …` yields the whole compound.
_ROLE = re.compile(r"^([A-Z][A-Z +/]*?)(?=\s*(?:[a-z#:]|$))")
#: Role words that name a BACKGROUND — the frame's own cast rather than something sitting on it.
#: A saturated hex under one of these is legal and is NOT counted as a second accent: a
#: photographic style's ground is allowed to be warm or cold (plan 4a rule 6). It is measured for
#: one thing only, that it contrasts with the accent family below.
_BACKGROUND_ROLES = ("GROUND", "GROUNDS", "SURFACE", "DEPTH", "SHADOW")
#: The spellings of a coverage clause an author may write on an accent line — `under 1/8`,
#: `under 10%`, `max 1/8`, `at most 1/8`, `<= 1/8`, `≤ 1/8`. One regex, so the validator and the
#: authoring block in `styles.yaml` cannot drift into two different vocabularies.
_COVERAGE = re.compile(
    r"under\s+(\d+)\s*/\s*(\d+)|under\s+(\d+)\s*%|(?:≤|<=|max|at most)\s*1\s*/\s*(\d+)", re.I)
#: Saturation floor for "this hex does ACCENT work". Under 0.45 a colour reads as a tinted
#: neutral — a warm grey, a sepia cast, an oak ground — and no viewer calls it the accent; the
#: shipped palettes' real accents all sit well above it and their casts well below.
_ACCENT_SATURATION_FLOOR = 0.45
#: Value band for the same question. Under 0.15 the hue is black in practice and over 0.95 it is
#: glare, and neither end can carry an accent's job of being the one thing the eye lands on.
_ACCENT_VALUE_BAND = (0.15, 0.95)
#: How wide one hue FAMILY is, in degrees. Two hues inside 30° read as one colour to a viewer
#: (teal at 176° and teal at 186° is one accent, not two); past it the second hue reads as
#: another brand on the same deck, which is the defect this contract exists to stop.
_HUE_FAMILY_DEGREES = 30.0
#: The share of frame an accent may take: 1/8. Past that it stops being an accent and becomes the
#: ground — the "one accent, used sparingly" rule stated as a number the author writes on the
#: palette line itself, so the render prompt carries the bound instead of implying it.
_MAX_ACCENT_COVERAGE = 0.125


def _hsv(hex6: str) -> tuple[float, float, float]:
    """`RRGGBB` (no `#`, either case) as `(hue in degrees, saturation, value)`.

    Hue comes back in degrees rather than `colorsys`' 0-1 turn because every rule above is stated
    in degrees, and one conversion in one place beats three at the call sites.
    """
    red, green, blue = (int(hex6[index:index + 2], 16) / 255 for index in (0, 2, 4))
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    return hue * 360, saturation, value


def _saturated(hex6: str) -> bool:
    """Is this hex a COLOUR doing accent work, rather than a tint, a cast or a near-neutral?

    The whole palette contract turns on this one predicate: a hex that answers `True` on a
    non-background line is an ACCENT and is held to the accent rules, and everything else is
    furniture the contract says nothing about.
    """
    _, saturation, value = _hsv(hex6)
    floor, ceiling = _ACCENT_VALUE_BAND
    return saturation >= _ACCENT_SATURATION_FLOOR and floor <= value <= ceiling


def _hue_distance(first: float, second: float) -> float:
    """Circular distance between two hues in degrees — 350° and 10° are 20° apart, not 340°."""
    gap = abs(first - second) % 360
    return min(gap, 360 - gap)


def _palette_role(line: str) -> str:
    """The role token a palette line opens with (`ACCENT`, `GROUND + CAPTION BANDS`), or `""`.

    A line with no capitalised opening — an author writing plain prose — yields `""`, which is an
    accent candidate: the contract's default is to HOLD a saturated hex to the accent rules and
    to let the `GROUND`/`SURFACE` vocabulary be the thing an author opts into.
    """
    match = _ROLE.match(line.strip())
    return match.group(1).strip() if match else ""


def _is_background_role(line: str) -> bool:
    """Does this palette line describe the ground, rather than something sitting on it?

    A compound role counts when it STARTS with a background word (`GROUND + CAPTION BANDS` is a
    ground), because the leading word is the one that says what the hex mostly covers.
    """
    role = _palette_role(line)
    return any(role == word or role.startswith(f"{word} ") or role.startswith(f"{word}+")
               for word in _BACKGROUND_ROLES)


def _coverage_bound(line: str) -> float | None:
    """The share of frame this line allows itself as a fraction (`under 1/8` → 0.125), or `None`.

    `None` means the line states no bound at all, which is a finding of its own — an accent the
    model is not held to is an accent it will spread, and "sparingly" is not a number.
    """
    match = _COVERAGE.search(line)
    if not match:
        return None
    if match.group(1):
        return int(match.group(1)) / int(match.group(2))
    if match.group(3):
        return int(match.group(3)) / 100
    return 1 / int(match.group(4))


def _palette_findings(style: MetaStyle, where: str) -> list[str]:
    """FR-347: what this style's `palette` gets wrong about its accent — one line per defect.

    Four findings, all read off the HEXES rather than off the prose around them, so the answer is
    the same whatever vocabulary an author reaches for:

    1. the accent hexes span more than one hue family (names the hexes and their hue angles);
    2. a line carrying an accent hex states no coverage clause;
    3. an accent line's coverage bound is over 1/8 of frame;
    4. a saturated GROUND hex sits inside the accent's own hue family, so the accent has nothing
       to contrast against (plan 4a rule 6 — a cast is legal, a cast in the accent's hue is not).

    **Zero accent hexes is silently legal.** A style may be built entirely of neutrals; that is a
    look, not a defect, and the contract has nothing to say about it.

    Which LIST these lines land in is `_PALETTE_CONTRACT_ENFORCED`'s decision, not this function's
    — it returns findings and `validate` files them as warnings or as errors.
    """
    out: list[str] = []
    accents: list[tuple[str, float]] = []
    grounds: list[tuple[str, float]] = []
    for line in style.palette:
        hexes = [value.upper() for value in _HEX.findall(line) if _saturated(value)]
        if not hexes:
            continue  # a line of neutrals is furniture: no accent rule applies to it
        if _is_background_role(line):
            grounds.extend((value, _hsv(value)[0]) for value in hexes)
            continue
        accents.extend((value, _hsv(value)[0]) for value in hexes)
        bound = _coverage_bound(line)
        if bound is None:
            out.append(f'{where}: the accent line "{_snippet(line)}" states no coverage bound — '
                       "an accent the model is not held to spreads over the frame; write the "
                       "share on the line itself (`under 1/8`) (FR-347)")
        # Floats: `under 2/16` lands on 0.125 exactly, but a percentage clause divides by 100 and
        # can land a hair either side of it, so the epsilon keeps a bound that IS 1/8 out of the
        # report instead of failing an author for arithmetic they never did.
        elif bound > _MAX_ACCENT_COVERAGE + 1e-9:
            out.append(f'{where}: the accent line "{_snippet(line)}" allows {bound:.1%} of frame '
                       f"— the ceiling is 1/8 ({_MAX_ACCENT_COVERAGE:.1%}), past which the accent "
                       "IS the ground (FR-347)")
    hues = [hue for _, hue in accents]
    if any(_hue_distance(one, two) > _HUE_FAMILY_DEGREES for one in hues for two in hues):
        named = ", ".join(f"#{value} at {round(hue)}°" for value, hue in accents)
        out.append(f"{where}: the accent hexes span more than one hue family ({named}) — one "
                   "style carries ONE accent hue, and a second one reads as a different brand on "
                   f"the same deck (a family is {_HUE_FAMILY_DEGREES:.0f}° wide) (FR-347)")
    for value, hue in grounds:
        if hues and all(_hue_distance(hue, other) <= _HUE_FAMILY_DEGREES for other in hues):
            out.append(f"{where}: the saturated ground #{value} at {round(hue)}° sits inside the "
                       "accent's own hue family, so the accent does not contrast with its ground "
                       "cast — cool the ground or move the accent (FR-347)")
    return out


# --------------------------------------------------------------------------------------------
# DNA prose scans (FR-349 unresolved choices, FR-348 type families)
# --------------------------------------------------------------------------------------------

#: The words that turn a marker into a BAN LIST instead of a choice. "no serif, script or display
#: face" names three families it forbids and is exactly what a well-written rule looks like;
#: "small mono or tracked caps" is a decision the author left to the image model. Word-bounded,
#: so `nothing` counts and `nonsense` does not.
_NEGATION = re.compile(r"\b(no|not|never|nothing|none|nor|neither|without|rather than)\b", re.I)
#: FR-348's five type CLASSES and the words that name them. Word-bounded and case-insensitive,
#: and a hyphen IS a boundary in Python's `\b` — so `sans-serif` names two classes (which is what
#: an author writing it means) and `monogram` names none.
_TYPE_FAMILIES = {
    "serif": re.compile(r"\b(serif|didone|slab)\b", re.I),
    "sans": re.compile(r"\b(sans|grotesque|geometric|humanist|gothic)\b", re.I),
    "mono": re.compile(r"\b(mono|monospace)\b", re.I),
    "script": re.compile(r"\b(script|handwritten|hand-lettered|marker)\b", re.I),
    "woodtype": re.compile(r"\b(woodtype|display face|display type)\b", re.I),
}
#: FR-348's ceiling: one display family and one body family. Two is what a reader tells apart at
#: a glance and what a render model holds across a deck; a third family is a third set of shapes
#: competing for the same slide, and the styles that shipped with four looked like four different
#: decks stapled together.
_MAX_TYPE_FAMILIES = 2


def _clauses(text: str) -> list[str]:
    """Some prose as the CLAUSES a marker or a negation is judged inside.

    Whitespace is collapsed first, then the text splits on `; `, `. `, `: ` and newlines — the
    four places an author ends one thought and starts another. The clause is the unit because the
    negation rule needs it: "no serif, script or display face" must keep its `no` and its `or` in
    one string, and the sentence three sentences later must not borrow that `no`.

    (The collapse consumes newlines before the split sees them, so the newline branch only fires
    if a caller ever hands this raw multi-line text. It is kept because the rule is stated with
    it, and a split that quietly loses a case is worse than an alternative that rarely fires.)
    """
    flat = " ".join(str(text).split())
    return [clause for clause in re.split(r";\s+|\.\s+|:\s+|\n", flat) if clause]


def _leaky(clause: str) -> bool:
    """Does this clause leave the image model a CHOICE it should have been handed resolved?

    The same `_VARIANT_MARKERS` the `render_prompt` rule uses, padded so a clause ending on "or"
    is caught too, minus every clause that also carries a negation — which is how a ban list is
    written, and a ban list is never a choice (FR-349).
    """
    padded = f" {clause.lower()} "
    return any(marker in padded for marker in _VARIANT_MARKERS) and not _NEGATION.search(clause)


def _dna_prose(style: MetaStyle) -> list[tuple[str, str]]:
    """Every field the FR-349 scan reads, as `(field name, prose)` in the order it reports them.

    This is the prose an image model EXECUTES — the five DNA fields plus the list layout and the
    per-format notes — and deliberately nothing else. `exclusions` are out because a ban list is
    WRITTEN with the marker words ("no serif, script or display face") and scanning it would warn
    about correct authoring. `layout_zones` are out because a zone is gated by role (FR-339) and
    is not unconditional DNA. `render_prompt` is out because it already has its own rule in
    `_style_warnings`, unchanged since M9 — one field, one message, never a double report.
    """
    prose = [("palette", line) for line in style.palette]
    prose += [("typography", style.typography), ("text_placement", style.text_placement),
              ("image_treatment", style.image_treatment), ("visual_pacing", style.visual_pacing)]
    if style.list_mode is not None:
        prose.append(("list_mode.layout", style.list_mode.layout))
    prose += [(f"per_format_guidance.{name}", value)
              for name, value in style.per_format_guidance.items()]
    return prose


def _choice_warnings(style: MetaStyle, where: str) -> list[str]:
    """FR-349: one line per DNA clause that still offers the render model a choice.

    The `render_prompt` heuristic (M9) was always right and was always looking at ONE field. The
    DNA fields reach the model just as literally — `style_dna` ships them byte-identically across
    a deck (FR-189) — so "a teal or cobalt rule" in `text_placement` buys exactly the slide-by-
    slide drift M9 was written to stop.
    """
    return [f'{where}: `{field}` leaves a choice open — "{_snippet(clause)}" — the image model '
            "resolves it differently on every slide of one deck; settle it on one value, or say "
            "what decides it (FR-349)"
            for field, text in _dna_prose(style) for clause in _clauses(text) if _leaky(clause)]


def _type_family_warning(style: MetaStyle, where: str) -> list[str]:
    """FR-348: does this style name more type families than a reader can tell apart? (0 or 1 line)

    Counted over the non-negated clauses of `typography` and of every zone's `text_treatment`,
    because those are the two places a style specifies type at all. A clause that BANS a family
    ("no script, no woodtype") does not name one for the purposes of this count.

    The carve-out: a THIRD family is tolerated when it is `mono`, because a code or terminal
    identity needs a monospace utility for the thing it is imitating and that utility is not a
    third voice. The PRD limits the carve-out to those identities by name (`build-log-mono`,
    `circuit-atlas-dark`, `terminal-mockup-deck`) and a TEST guard pins that list, not this
    function — the validator reads words and cannot know whether a style IS a terminal, and a
    heuristic that guessed would fail the honest styles and pass the dishonest ones.

    A heuristic, therefore a warning and never an error: a style naming three families still
    renders, and FR-295's exit 2 is for registries that cannot render at all.
    """
    named: set[str] = set()
    for text in [style.typography, *(zone.text_treatment for zone in style.layout_zones)]:
        for clause in _clauses(text):
            if _NEGATION.search(clause):
                continue
            named |= {name for name, pattern in _TYPE_FAMILIES.items() if pattern.search(clause)}
    if len(named) <= _MAX_TYPE_FAMILIES or (len(named) == _MAX_TYPE_FAMILIES + 1
                                            and "mono" in named):
        return []
    return [f"{where}: `typography` and the layout zones name {len(named)} type families "
            f"({', '.join(sorted(named))}) — one display family + one body family; a third family "
            "only as a mono utility (FR-348)"]


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

    FR-347 (D60) is the one finding set with TWO MODES, and `_PALETTE_CONTRACT_ENFORCED` is the
    whole of the difference. In warning mode (`False`, what ships) a palette that breaks the
    accent contract prints at pre-flight and the run proceeds; enforced (`True`) the identical
    lines are errors and the registry refuses at $0 like any other FR-295 defect. Nothing else
    moves with that flag — same checks, same wording, same exit path — so the day the shipped
    nineteen are re-authored clean is a one-line change with no second behaviour to re-test.

    The two other D60 contracts are warnings by construction and have no mode: FR-348 counts the
    type families a style names and FR-349 scans every DNA field for an unresolved choice. Both
    are heuristics over prose, both leave a style that still renders exactly as authored, and
    `_style_warnings` carries them beside the M9 `render_prompt` rule they generalise.
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
        # FR-347's findings ride ONE switch: warnings while the shipped registry is being
        # re-authored, errors the day `_PALETTE_CONTRACT_ENFORCED` flips. Computed the same way
        # either side of it, so the flip changes where the lines print and nothing else.
        findings = _palette_findings(style, where)
        (errors if _PALETTE_CONTRACT_ENFORCED else warnings).extend(findings)
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
    """Advisory findings about the WORDS — an over-long prompt, an unresolved variant choice, a
    style that never says what it is for.

    Everything here is a WARNING and none of it is ever promoted to an error: FR-295's exit-2 list
    is for defects that make a run impossible (no render instruction, no affine format, an empty
    pool), and none of these do. A style with no `match_profile` still renders exactly as authored
    — only the matcher that has to choose between styles is left reading the wrong field (D56).

    D60 widens the same idea twice. FR-348 counts the TYPE FAMILIES a style names across
    `typography` and its zones' `text_treatment`, and FR-349 takes M9's either/or heuristic off
    `render_prompt` alone and runs it over every DNA field the model executes. The M9 rule below
    is untouched and stays separate: it reads one field with its own message, and the two new
    scans deliberately do not read that field, so no style is reported twice for one sentence.
    """
    out: list[str] = []
    if (words := len(style.render_prompt.split())) > _MAX_RENDER_WORDS:
        out.append(f"{where}: `render_prompt` is {words} words — over the {_MAX_RENDER_WORDS}-word "
                   "ceiling the tail competes with the TEXT block for the model's attention")
    mode = style.list_mode
    if mode is not None and not mode.reflow_over_chars and not mode.max_rows:
        out.append(f"{where}: `list_mode` sets both triggers to 0, so no panel can ever be a list "
                   "for this style and its `layout` prose will never reach a render prompt — set "
                   "`reflow_over_chars` or `max_rows` to a real threshold, or drop the block "
                   "(FR-304b)")
    if not style.match_profile:
        out.append(f"{where}: no `match_profile` — matched assignment (FR-334) falls back to the "
                   "first sentence of `render_prompt` for this style, which says how it LOOKS and "
                   "not what it SUITS; write one or two sentences naming the kinds of source "
                   "material it fits (FR-290/335)")
    lowered = style.render_prompt.lower()
    if leaks := [marker.strip() for marker in _VARIANT_MARKERS if marker in lowered]:
        out.append(f"{where}: `render_prompt` still offers a choice ({', '.join(leaks)}) — the "
                   "image model resolves it differently on every slide of one deck; resolve it to "
                   "one value (M9)")
    out.extend(_type_family_warning(style, where))
    out.extend(_choice_warnings(style, where))
    return out


# --------------------------------------------------------------------------------------------
# Assignment — pure functions of `entry.order` (FR-291)
# --------------------------------------------------------------------------------------------


def assign_styles(entries: Sequence[PlanEntry], registry: StyleRegistry, brand: str,
                  enabled: Sequence[str] = (), *, branding_enabled: bool = True,
                  run_id: str = "", rotation: str = "seeded") -> None:
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
        run_id: this run's id (`session.run_id`), the seed material for the v2.2.0 rotation OFFSET.
            Empty — the default every caller that has no run keeps — is offset 0, i.e. exactly the
            pre-v2.2.0 rotation.
        rotation: `config.styles.rotation`. `"seeded"` (the default) offsets the whole rotation by
            a stable hash of `run_id`; `"fixed"` pins the offset at 0.

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
    seed = rotation_seed(run_id, rotation)
    for entry in sorted(entries, key=lambda item: item.order):
        entry.style_key = _scan(pool, entry.order, entry.creative_format, entry.asset_id,
                                seed=seed).key


def assign_styles_fixed(entries: Sequence[PlanEntry], keys: Sequence[str]) -> list[tuple[str, str]]:
    """FR-369: walk `keys` 1:1 in plan order — the style test's matrix, and nothing else.

    Pure and total. It reads no registry, no brand, no format affinity and no run id, it makes no
    call, and it raises nothing: entry *i* in plan order gets `keys[i]`, full stop. That bluntness
    is the whole feature. The style test asks "what does each of these seventeen styles look like
    on one real post", and the only way an answer is readable is if deck 03 is *the third key the
    operator typed* — not the third key that survived a filter, not the third that happened to be
    affine, and not the third the file happened to list.

    **Why this is not `styles.rotation: "fixed"`.** That knob (D52, `rotation_seed`) pins the
    rotation OFFSET at 0 and then runs `_scan` exactly as always: `_scan` walks the pool in
    REGISTRY FILE order, not in `--styles` order, and it silently steps past any candidate that is
    not affine to the entry's format. So `rotation: fixed` answers a different question ("start the
    normal rotation at the top") and it can quietly skip a style, repeat a style once the pool is
    shorter than the plan, and reorder the whole matrix relative to what was typed — three ways for
    a diagnostic to produce a grid whose labels do not match its pictures. There is no shared code
    to reuse here, because the thing being removed IS the shared code.

    Skipping affinity is deliberate and safe in this direction: `cli._style_test_overrides` makes
    the plan carousels-only, and `styles.validate` has already refused at pre-flight (exit 2, $0)
    any `--styles` key that is unknown or leaves the carousel pool empty. A key that is somehow
    non-affine anyway still renders as itself and shows the operator exactly the mismatch they
    would otherwise never see — which, in a diagnostic, is information rather than a defect.

    Args:
        entries: the live entries to dress. Sorted by `entry.order` here, so a caller that hands
            them over in report order or dict order still gets plan order, and `entry.order`'s gaps
            (trims, drops) are irrelevant — POSITION in the sorted list is the index, not the value.
        keys: the style keys in the exact order `--styles` named them. Shorter than `entries`
            wraps by modulo, which cannot happen through the CLI (the deck count IS `len(keys)`)
            and is defined anyway so no entry can come out of here style-less. Empty leaves every
            entry untouched.

    Returns:
        `(asset_id, style_key)` in the order assigned — the console's `style test:` line reads this
        rather than re-deriving the mapping, so what is printed cannot drift from what was set.
    """
    if not keys:
        return []
    assigned: list[tuple[str, str]] = []
    for index, entry in enumerate(sorted(entries, key=lambda item: item.order)):
        entry.style_key = keys[index % len(keys)]
        assigned.append((entry.asset_id, entry.style_key))
    return assigned


def rotation_seed(run_id: str, rotation: str = "seeded") -> int:
    """The rotation's per-run OFFSET into the pool — a pure function of the run id (v2.2.0).

    The pre-v2.2.0 pick was a pure function of `entry.order` alone, which made it a pure function
    of NOTHING ELSE: every run of the same config opened with the same style, the second creative
    always wore the second style, and a daily batch published the registry in the same marching
    order forever. The audit read that as the registry being too small; it was the rotation being
    too fixed. Offsetting the whole rotation by the run id keeps every determinism property that
    matters — one run's assignment is still reproducible, still gap-proof, still a pure function of
    `entry.order` WITHIN the run — while moving where the run starts.

    `zlib.crc32` over the id's UTF-8 bytes, deliberately, and never the builtin `hash()`: that one
    is salted per process for `str`, so the same run id would seed differently in the run that
    assigned the styles and in anything that later re-derived them (a replay, a test, a second
    process reading `meta.yaml`). A checksum is not a good hash and does not need to be — the id
    already varies per second (`util.new_run_id`), and all this has to do is scatter.

    `rotation="fixed"` and an empty `run_id` both return 0, which IS the pre-v2.2.0 rotation: the
    escape hatch for an operator who wants the registry walked in file order, and the reason every
    caller with no run of its own needs no branch.
    """
    if rotation != "seeded" or not (seed_text := run_id.strip()):
        return 0
    return zlib.crc32(seed_text.encode("utf-8"))


def _scan(pool: Sequence[MetaStyle], order: int, creative_format: str, asset_id: str, *,
          seed: int = 0) -> MetaStyle:
    """The order-indexed scan itself: start at `order + seed`, walk the pool once, take the first
    style affine to this format. An exhausted scan keeps the LAST candidate rather than leaving the
    entry style-less — defensive only, since `validate()` refuses a run whose requested format has
    no affine style at all.

    `seed` shifts the START of every scan by the same amount (`rotation_seed`), so it rotates the
    whole assignment rather than shuffling it: the pool keeps FILE order, consecutive orders still
    land on consecutive styles, and a gapped order still picks what that order would have picked in
    a dense plan.
    """
    start = order + seed
    cand = pool[start % len(pool)]
    for step in range(len(pool)):
        cand = pool[(start + step) % len(pool)]
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
           "assign_styles_fixed", "brand_ok", "fmt_affine", "is_list_panel", "load_registry",
           "match_profile_for", "rotation_seed", "selected", "style_for", "usable_styles",
           "validate"]
