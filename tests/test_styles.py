"""`hypesocials.styles` — the meta-style registry and its deterministic rotation.

Post-pivot (v2.0.0) the look of a creative is no longer re-derived per trend by an LLM: it is
AUTHORED once in `prompts/styles.yaml` and ASSIGNED by a deterministic scan (FR-290/291). Since
D46 (v2.1.0) that authored look is TEXT ONLY — the reference-image channel, its per-job window and
its magic-byte reader are gone (FR-17/18), and the absence is pinned here too. That moves three
failure modes out of the run and into pre-flight, and this suite is where each one is pinned:

* an unusable registry must refuse the run at pre-flight (FR-295 exit 2) rather than degrade —
  there is no built-in third tier, so a missing file is an error, never a silent default;
* an assignment must be a pure function of `entry.order`, so trimming one creative cannot
  reshuffle the styles of the creatives that survive (plan §1.3 — the reason there is no cursor);
* branding must be counted with `floor`, not `round`, over the FULL emitted plan (§1.4), because
  a ratio the operator set is a promise about how many posts carry the wordmark.

v2.4.0 (D56/D57) added a fourth, and it is an ABSENCE: this module stays offline and sync under
matched assignment. `assign_styles` is still the pure, content-blind FR-291 baseline every run
computes, `style_match` is a separate leaf module that may overwrite a winner afterwards, and the
only thing this module owes it is `match_profile_for` — one line per style saying what it SUITS,
authored where possible and derived from `render_prompt` where not. Nothing here awaits, calls a
model or learns what a topic is about, and a missing `match_profile` is an advisory warning rather
than an FR-295 refusal. Both halves of that are pinned below.

Everything here is offline and deterministic: no network, no API key, no `logs/`, no `output/`.
The only filesystem use is `tmp_path`. The API under test is pinned in
`plans/topic-first-pivot-contracts.md` item 5, which is this suite's source of truth — it was
written against the contract, in parallel with the module itself.
"""

from __future__ import annotations

import colorsys
import dataclasses
import math
import re
from pathlib import Path

import pytest
import yaml

from hypesocials import styles
from hypesocials.config import (
    CONFIGS_DIR,
    BrandingConfig,
    Config,
    RunConfig,
    StylesConfig,
    TextBudgets,
    load_config,
)
from hypesocials.generate import refs as refs_module
from hypesocials.models import LayoutZone, ListMode, MetaStyle, PlanEntry
from hypesocials.styles import StyleRegistry, StyleRegistryError

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- builders


def _style(key: str, **over) -> MetaStyle:
    """A style that validates CLEAN, so whatever a test asserts on is the defect it introduced.

    The default `render_prompt` is deliberately short and free of " or " / "either " / "Variant ",
    the three variant-leak spellings the registry warns about (§1.3/M9).

    `match_profile` carries a real line for the same reason (v2.4.0/D56): a style that never says
    what it is FOR earns its own advisory warning, and a builder that produced one would make
    every `warnings == []` baseline below a test about the builder rather than about the defect it
    introduced. The missing-profile warning has its own tests, on registries that omit it on
    purpose.
    """
    fields: dict[str, object] = {
        "render_prompt": "Flat graphic card, centred subject, hard shadow, wide margins.",
        "match_profile": "Suits short, single-idea sources with one clear subject.",
        "format_affinity": ["image", "carousel", "reel"],
    }
    fields.update(over)
    return MetaStyle(key=key, **fields)  # type: ignore[arg-type]


def _registry(*entries: MetaStyle, origin: str = "prompts/styles.yaml") -> StyleRegistry:
    return StyleRegistry(version=1, styles=list(entries), origin=origin,
                         content_hash="0123456789ab")


def _config(*, brand: str = "hypedigitaly", formats: dict[str, int] | None = None,
            enabled: list[str] | None = None) -> Config:
    return Config(run=RunConfig(formats=formats or {"image": 4, "carousel": 2, "reel": 0}),
                  branding=BrandingConfig(brand=brand),
                  styles=StylesConfig(enabled=list(enabled or [])))


def _entry(order: int, fmt: str = "image") -> PlanEntry:
    return PlanEntry(order=order, asset_id=f"a{order:02d}", creative_format=fmt,  # type: ignore[arg-type]
                     platform="linkedin", language="en", aspect_ratio="1:1")


def _entries(orders, fmt: str = "image") -> list[PlanEntry]:
    return [_entry(order, fmt) for order in orders]


def _keys(entries) -> list[str]:
    return [entry.style_key for entry in entries]


def _write_registry(folder: Path, entries: list[dict], *, version: int = 1) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "styles.yaml"
    path.write_text(yaml.safe_dump({"version": version, "styles": entries}, sort_keys=False),
                    encoding="utf-8")
    return path


#: The smallest YAML block that both PARSES and validates clean. `match_profile` is in it for the
#: same reason it is in `_style` above — D56's advisory warning fires without one, and a fixture
#: that earned a warning it never meant to test would blunt every `warnings == []` baseline here.
#: `_MINIMAL_NO_PROFILE` below is the deliberate opposite, used where the absence IS the subject.
_MINIMAL = {"key": "minimal", "render_prompt": "Flat card.", "format_affinity": ["image"],
            "match_profile": "Suits one-line hooks with no source panels behind them."}
#: A registry block authored BEFORE `match_profile` existed — the shape an operator's on-disk
#: `styles.yaml` really has after an engine upgrade. It must load, validate without errors and
#: assign exactly like any other style (D56); only the matcher is weaker for it.
_MINIMAL_NO_PROFILE = {key: value for key, value in _MINIMAL.items() if key != "match_profile"}


# --------------------------------------------------------------------------- load_registry


def test_fr174_the_first_directory_holding_a_registry_wins_and_is_named_as_the_origin(
    tmp_path: Path,
) -> None:
    """The registry resolves override-first through the SAME `prompts_dir` seam as the templates,
    and FR-184's attribution extends to it: an operator reading a run log must be able to see
    which file the run's looks came from, not just that some file was found."""
    override, base = tmp_path / "override", tmp_path / "base"
    _write_registry(override, [dict(_MINIMAL, key="over")])
    expected = _write_registry(base, [dict(_MINIMAL, key="base")])

    reg = styles.load_registry([override, base])

    assert [style.key for style in reg.styles] == ["over"]
    assert Path(reg.origin) == override / "styles.yaml"
    assert reg.version == 1

    # An override DIRECTORY that ships no registry is not an override: the seam looks for the
    # first HIT, not the first folder — otherwise `prompts_dir: my-tweaks/` would blank the run.
    (tmp_path / "empty").mkdir()
    fallen_back = styles.load_registry([tmp_path / "empty", base])
    assert [style.key for style in fallen_back.styles] == ["base"]
    assert Path(fallen_back.origin) == expected


def test_fr184_the_content_hash_identifies_the_bytes_and_not_the_folder(tmp_path: Path) -> None:
    """Same recipe as `prompts_engine._hash` (sha256[:12]): the same registry copied into another
    override folder is the same registry, and one edited character is a different one."""
    first, second, edited = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    _write_registry(first, [_MINIMAL])
    _write_registry(second, [_MINIMAL])
    _write_registry(edited, [dict(_MINIMAL, render_prompt="Flat card, wide margins.")])

    one, two, three = (styles.load_registry([folder]) for folder in (first, second, edited))

    assert len(one.content_hash) == 12
    assert all(char in "0123456789abcdef" for char in one.content_hash)
    assert one.content_hash == two.content_hash != three.content_hash
    assert one.origin != two.origin


def test_a_full_entry_normalizes_into_a_metastyle_with_typed_layout_zones(tmp_path: Path) -> None:
    """The registry is data; `MetaStyle` is the shape the rest of the code speaks (contracts item
    5). `layout_zones` in particular must arrive as `LayoutZone` objects carrying `role`, because
    `role: brand_slot` is what decides whether the signature zone is emitted at all (M11)."""
    _write_registry(tmp_path, [{
        "key": "hypelead-brand-card",
        "render_prompt": "Teal card on off-white ground.",
        "subject_mode": "scene_open",
        "layout_zones": [
            {"position": "upper third", "content": "headline", "text_treatment": "bold caps"},
            {"position": "lower margin", "content": "brand", "text_treatment": "small caps",
             "role": "brand_slot"},
        ],
        "format_affinity": ["image", "carousel"],
        "brand_affinity": ["hypelead"],
        "brand_slot": True,
        "text_density": "high",
        "max_onimage_chars": {"headline": 90, "subline": 60, "slide": 90},
        "motion_profile": "graphic",
        "palette": ["#0FCFC4", "#14130F"],
        "typography": "Geist, tight tracking",
        "text_placement": "upper third",
        "image_treatment": "flat vector",
        "visual_pacing": "one idea per frame",
        "per_format_guidance": {"carousel_cover": "full bleed", "carousel_role": "cover_only"},
        "exclusions": ["HypeLead"],
        "reference_images": ["hypedigitaly branding/HypeLead/post-square-a-1080x1080.png"],
    }])

    style = styles.load_registry([tmp_path]).styles[0]

    assert isinstance(style, MetaStyle) and style.key == "hypelead-brand-card"
    assert style.brand_slot is True and style.brand_affinity == ["hypelead"]
    assert style.max_onimage_chars == {"headline": 90, "subline": 60, "slide": 90}
    assert [type(zone) for zone in style.layout_zones] == [LayoutZone, LayoutZone]
    assert (style.layout_zones[0].role, style.layout_zones[1].role) == ("", "brand_slot")
    assert style.per_format_guidance["carousel_role"] == "cover_only"
    assert style.exclusions == ["HypeLead"]


@pytest.mark.parametrize("body", [
    pytest.param(None, id="nowhere"),
    pytest.param("version: 1\nstyles: [ {key: a\n", id="invalid-yaml"),
    pytest.param("just a string\n", id="not-a-mapping"),
    pytest.param("version: 1\nstyles: {key: a}\n", id="styles-not-a-list"),
])
def test_fr295_an_unusable_registry_refuses_the_run_in_one_line_instead_of_defaulting(
    tmp_path: Path, body: str | None,
) -> None:
    """§1.3's decision, stated as a test: unlike templates, the registry has NO built-in tier — a
    built-in copy would be eight styles of silent drift. So every unusable shape is exit-2
    material, and `str(e)` is the whole operator-facing line naming the file it looked for."""
    if body is not None:
        (tmp_path / "styles.yaml").write_text(body, encoding="utf-8")

    with pytest.raises(StyleRegistryError) as caught:
        styles.load_registry([tmp_path, tmp_path / "also-absent"])

    line = str(caught.value)
    assert "styles.yaml" in line
    assert line.strip() and "\n" not in line.strip()


# ------------------------------------------------------- FR-304b: the style's list treatment
#
# A REFLOW TRIGGER, never a ceiling (D50). Nothing below may drop, shorten or refuse a word: the
# only thing a tripped trigger changes is the layout prose `prompts_engine` appends to
# `{{layout_zones}}`, and the only thing a malformed block changes is that the run never starts.

_LIST_MODE = {
    "reflow_over_chars": 180,
    "max_rows": 6,
    "layout": "Rows set as one left-aligned column of label + value pairs inside a single card.",
    "overflow": "reflow",
}


def test_a_style_declaring_a_list_mode_parses_it_whole(tmp_path: Path) -> None:
    """The frozen §4b shape, read as authored — the four values reach `MetaStyle.list_mode` and
    `overflow` defaults to `reflow` when the author leaves it out."""
    _write_registry(tmp_path, [dict(_MINIMAL, list_mode=dict(_LIST_MODE)),
                               dict(_MINIMAL, key="defaulted",
                                    list_mode={k: v for k, v in _LIST_MODE.items()
                                               if k != "overflow"})])

    first, second = styles.load_registry([tmp_path]).styles

    assert first.list_mode is not None
    assert (first.list_mode.reflow_over_chars, first.list_mode.max_rows) == (180, 6)
    assert first.list_mode.layout.startswith("Rows set as one left-aligned column")
    assert first.list_mode.overflow == "reflow"
    assert second.list_mode is not None and second.list_mode.overflow == "reflow"


def test_a_style_with_no_list_mode_is_legal_and_simply_has_none(tmp_path: Path) -> None:
    """Absent is the norm — most styles have no list treatment, and the key's absence must never
    be a finding, a default or a refusal."""
    _write_registry(tmp_path, [dict(_MINIMAL)])

    style = styles.load_registry([tmp_path]).styles[0]

    assert style.list_mode is None
    clean = _registry(style, _style("b"), _style("c"))
    assert styles.validate(clean, _config(formats={"image": 1})) == ([], [])


@pytest.mark.parametrize("mode, id_", [
    ("not a mapping", "scalar"),
    ({**_LIST_MODE, "overflow": "truncate"}, "an overflow value that would drop text"),
    ({**_LIST_MODE, "overflow": "drop_rows"}, "another one"),
    ({k: v for k, v in _LIST_MODE.items() if k != "max_rows"}, "missing a trigger"),
    ({k: v for k, v in _LIST_MODE.items() if k != "layout"}, "missing the layout"),
    ({**_LIST_MODE, "layout": "   "}, "an empty layout"),
    ({**_LIST_MODE, "reflow_over_chars": "long"}, "a non-numeric threshold"),
    ({**_LIST_MODE, "max_rows": -1}, "a negative threshold"),
    ({**_LIST_MODE, "max_rows": True}, "a YAML boolean where a count belongs"),
])
def test_fr295_a_malformed_list_mode_refuses_the_run_at_zero_dollars(
    tmp_path: Path, mode: object, id_: str,
) -> None:
    """Every half-read `list_mode` fails the same way every other registry defect does: exit 2 at
    pre-flight, one operator-facing line naming the file, the style and the key. Two of these cases
    are the load-bearing ones — an `overflow` word outside the frozen pair would be a spelling of
    "lose a row", and D50 says no such spelling exists."""
    _write_registry(tmp_path, [dict(_MINIMAL, list_mode=mode)])

    with pytest.raises(StyleRegistryError) as caught:
        styles.load_registry([tmp_path])

    line = str(caught.value)
    assert "list_mode" in line and "minimal" in line, id_


def test_a_list_mode_that_can_never_fire_is_a_warning_not_a_refusal() -> None:
    """Both triggers off is a block with no effect — worth saying out loud, not worth refusing a
    run over: nothing renders differently because of it."""
    style = _style("dead", list_mode=ListMode(reflow_over_chars=0, max_rows=0,
                                                     layout="Rows in a card."))

    errors, warnings = styles.validate(_registry(style, _style("b"), _style("c")),
                                       _config(formats={"image": 1}))

    assert not errors
    assert any("no panel can ever be a list" in line for line in warnings)


def test_the_list_trigger_reads_length_and_rows_independently_and_zero_turns_one_off() -> None:
    """`is_list_panel` is the registry's own reading of its own thresholds, so the one consumer
    (`prompts_engine._style_zones`) never re-derives it. Either threshold fires alone; `0` disables
    its own trigger — the INVERTED sense of `max_onimage_chars`' "0 = no ceiling"."""
    long_only = _style("l", list_mode=ListMode(reflow_over_chars=20, max_rows=0,
                                                      layout="Card."))
    rows_only = _style("r", list_mode=ListMode(reflow_over_chars=0, max_rows=2,
                                                      layout="Card."))
    four_rows = "a\nb\nc\nd"

    assert styles.is_list_panel(long_only, "x" * 21) is True
    assert styles.is_list_panel(long_only, "x" * 20) is False
    assert styles.is_list_panel(long_only, four_rows) is False, "0 rows means no row trigger"
    assert styles.is_list_panel(rows_only, four_rows) is True
    assert styles.is_list_panel(rows_only, "x" * 500) is False, "0 chars means no length trigger"
    assert styles.is_list_panel(_style("plain"), "x" * 500) is False, "no list_mode, never a list"
    assert styles.is_list_panel(None, "x" * 500) is False, "no style at all (an override brief)"
    assert styles.is_list_panel(long_only, "   ") is False, "an empty panel is not a list"


# --------------------------------------------------------------------------- validate: errors


def test_a_clean_registry_of_three_styles_reports_nothing_at_all() -> None:
    """The baseline every matrix case below is a delta from — otherwise a validator that warned
    about everything would look like it was catching each defect."""
    errors, warnings = styles.validate(_registry(_style("a"), _style("b"), _style("c")), _config())

    assert not errors
    assert not warnings


def test_a_registry_with_no_style_usable_under_the_active_brand_is_a_refusal() -> None:
    """B3: `brand_affinity` filters the rotation, so a hypelead-only registry under `hypedigitaly`
    has an empty pool. Nothing can be assigned, so nothing can be rendered — the run must stop at
    pre-flight rather than discover it one creative at a time."""
    reg = _registry(_style("lead-a", brand_affinity=["hypelead"]),
                    _style("lead-b", brand_affinity=["hypelead"]))

    errors, _ = styles.validate(reg, _config(brand="hypedigitaly"))

    assert errors
    assert any("hypedigitaly" in error for error in errors)
    # Under its own brand the same registry is usable — the pool is empty, not the file.
    assert styles.validate(reg, _config(brand="hypelead"))[0] == []


def test_a_duplicate_key_is_an_error_naming_the_key() -> None:
    """Keys are how `style_for` resolves a persisted `PlanEntry.style_key` back to a style; two
    entries answering to one key means a meta.yaml can no longer say which look was rendered."""
    errors, _ = styles.validate(_registry(_style("twice"), _style("twice"), _style("c")),
                                _config())

    assert any("twice" in error for error in errors)


def test_an_empty_render_prompt_is_an_error_naming_the_style(tmp_path: Path) -> None:
    """`render_prompt` IS the style post-pivot: an empty one renders a creative with no visual
    instruction at all, which is the failure the registry exists to make impossible.

    A whitespace-only YAML value is the same defect wearing a block scalar, and it is caught by
    the SAME check because normalization strips at the load boundary — so `validate` never has to
    ask a second question about the same field.
    """
    errors, _ = styles.validate(_registry(_style("blank", render_prompt=""), _style("b"),
                                          _style("c")), _config())
    assert any("blank" in error for error in errors)

    _write_registry(tmp_path, [dict(_MINIMAL, key="blank", render_prompt="   \n  ")])
    loaded = styles.load_registry([tmp_path])

    assert loaded.styles[0].render_prompt == ""
    assert any("blank" in error for error in styles.validate(loaded, _config())[0])


@pytest.mark.parametrize("affinity", [[], ["video"], ["image", "story"]])
def test_a_format_affinity_that_is_empty_or_outside_the_vocabulary_is_an_error(
    affinity: list[str],
) -> None:
    """The vocabulary is closed at {image, carousel, reel}: a typo'd format silently removes the
    style from every rotation it was authored for, and an empty list removes it from all of them."""
    errors, _ = styles.validate(
        _registry(_style("odd", format_affinity=affinity), _style("b"), _style("c")), _config())

    assert any("odd" in error for error in errors)


def test_a_brand_affinity_outside_the_two_brands_is_an_error_naming_the_value() -> None:
    errors, _ = styles.validate(
        _registry(_style("odd", brand_affinity=["acme"]), _style("b"), _style("c")), _config())

    assert any("acme" in error for error in errors)


def test_a_requested_format_with_no_affine_style_is_an_error_naming_that_format() -> None:
    """The check that makes the rotation's defensive branch unreachable: if reels are requested and
    nothing is reel-affine, the scan would hand a reel entry an image style. Pre-flight refuses
    first, so the operator hears about it before any money moves."""
    reg = _registry(_style("a", format_affinity=["image", "carousel"]),
                    _style("b", format_affinity=["image"]),
                    _style("c", format_affinity=["carousel"]))

    assert styles.validate(reg, _config(formats={"image": 4, "carousel": 2, "reel": 0}))[0] == []

    errors, _ = styles.validate(reg, _config(formats={"image": 4, "carousel": 2, "reel": 1}))
    assert any("reel" in error for error in errors)


def test_the_brand_filter_emptying_one_formats_pool_is_the_same_error() -> None:
    """B3's second face: the registry covers every requested format, but only via styles the
    active brand cannot use. Counting affine styles BEFORE the brand filter would pass this file
    and then starve the carousel rotation at run time."""
    reg = _registry(_style("neutral-image", format_affinity=["image"]),
                    _style("lead-deck", format_affinity=["carousel"], brand_affinity=["hypelead"]))

    errors, _ = styles.validate(reg, _config(brand="hypedigitaly",
                                             formats={"image": 4, "carousel": 2, "reel": 0}))

    assert any("carousel" in error for error in errors)
    assert styles.validate(reg, _config(brand="hypelead",
                                        formats={"image": 4, "carousel": 2, "reel": 0}))[0] == []


def test_a_carousel_requested_with_only_slides_only_styles_is_an_error() -> None:
    """`carousel_role: slides_only` means the style can never anchor a deck, and under anchor
    chaining that means it never takes a carousel entry AT ALL (contracts item 5). So a registry
    whose only carousel-affine styles are slides-only cannot serve a requested carousel."""
    slides_only = _style("meme", format_affinity=["image", "carousel"],
                         per_format_guidance={"carousel_role": "slides_only",
                                              "carousel_slide": "panel grammar"})
    reg = _registry(slides_only, _style("shot", format_affinity=["image"]))

    errors, _ = styles.validate(reg, _config(formats={"image": 4, "carousel": 2, "reel": 0}))
    assert any("carousel" in error for error in errors)

    with_anchor = _registry(slides_only, _style("deck", format_affinity=["carousel"]),
                            _style("shot", format_affinity=["image"]))
    assert styles.validate(with_anchor,
                           _config(formats={"image": 4, "carousel": 2, "reel": 0}))[0] == []


# --------------------------------------------------------------------------- validate: warnings


def test_fewer_than_three_usable_styles_warns_without_refusing_the_run() -> None:
    """Two styles is a thin rotation, not a broken one: every creative in the run will look like
    one of two things. Worth saying out loud; not worth costing the operator the run."""
    errors, warnings = styles.validate(_registry(_style("a"), _style("b")), _config())

    assert not errors
    assert warnings

    # "Usable" is counted AFTER the brand filter — four styles, two of them another brand's, is
    # still a two-style rotation.
    brand_thinned = _registry(_style("a"), _style("b"),
                              _style("lead-a", brand_affinity=["hypelead"]),
                              _style("lead-b", brand_affinity=["hypelead"]))
    assert styles.validate(brand_thinned, _config(brand="hypedigitaly"))[1]


def test_a_render_prompt_over_120_words_warns_and_names_the_style() -> None:
    """§1.3 caps the prompt at 120 words because it is injected whole into every job on that
    style; past the cap the truncation order starts deciding what the picture looks like."""
    long_prompt = " ".join(["margin"] * 130)
    errors, warnings = styles.validate(
        _registry(_style("verbose", render_prompt=long_prompt), _style("b"), _style("c")),
        _config())

    assert not errors
    assert any("verbose" in warning for warning in warnings)


@pytest.mark.parametrize("prompt", [
    "Flat card with a teal or cobalt accent bar.",
    "Variant A: full-bleed photo. Variant B: framed photo.",
    "Use either a hard shadow, a soft one.",
])
def test_an_unresolved_variant_in_a_render_prompt_warns(prompt: str) -> None:
    """M9: a choice left in the prompt is a choice the image model makes DIFFERENTLY on every
    slide, which is exactly the deck-level inconsistency the registry was written to end. The
    heuristic is cheap (" or ", "Variant ", "either ") and only ever warns."""
    _, warnings = styles.validate(
        _registry(_style("leaky", render_prompt=prompt), _style("b"), _style("c")), _config())

    assert any("leaky" in warning for warning in warnings)


def test_validation_has_nothing_to_say_about_files_any_more() -> None:
    """D46/FR-18: the registry declares no pictures, so FR-295's file-existence and magic-byte
    clause has nothing to check — a clean three-style registry validates SILENTLY, and no finding
    may mention a reference image. The tag `style_refs_missing` keeps its slot in FR-73's
    vocabulary and is emitted by nothing; it is not this module's to raise."""
    errors, warnings = styles.validate(
        _registry(_style("a"), _style("b"), _style("c")), _config())

    assert (errors, warnings) == ([], [])
    assert not any("reference" in line.lower() for line in errors + warnings)


# ------------------------------ D56/FR-335: `match_profile`, the one line the matcher reads
#
# A style's `render_prompt` says how it LOOKS; a `match_profile` says what kind of SOURCE MATERIAL
# it SUITS. Those are different questions, and matched assignment (FR-334) is a decision about the
# second one — which is why the field exists, why `match_profile_for` is the single public answer
# to it (`style_match` describes every candidate through that one call), and why the fallback
# below is deliberately the weaker line rather than a blank.
#
# Nothing here is ever an ERROR. The whole field is optional by contract: a registry authored
# before it existed loads clean, assigns identically and renders identically — only the matcher is
# left reading the wrong field, and FR-295's exit-2 list is for defects that make a run IMPOSSIBLE.
# That distinction is asserted below rather than described, because promoting the advisory to an
# error would refuse every operator's on-disk registry on the day they upgrade the engine.


def test_d56_match_profile_round_trips_from_the_yaml_exactly_as_authored(tmp_path: Path) -> None:
    """The field is read at the load boundary like every other string in a style block: stripped,
    never re-wrapped, never re-punctuated. An engine that normalised it would be editing the
    operator's own sentence on its way to a model."""
    profile = ("Suits numbered listicle decks and tool round-ups — sources whose panels are short "
               "labelled rows rather than prose.")
    _write_registry(tmp_path, [dict(_MINIMAL, key="ledger", match_profile=f"  {profile}\n"),
                               dict(_MINIMAL_NO_PROFILE, key="legacy")])

    ledger, legacy = styles.load_registry([tmp_path]).styles

    assert ledger.match_profile == profile, "stripped at the boundary, and otherwise verbatim"
    assert legacy.match_profile == "", "absent is the empty string, never None and never a default"


def test_d56_match_profile_for_prefers_the_authored_line_and_derives_one_when_it_is_absent(
) -> None:
    """The two branches of the single public answer, exercised on a SYNTHETIC registry.

    It has to be synthetic: all twenty-six shipped styles author a real `match_profile` (pinned
    below), so the derivation branch is untaken against `prompts/styles.yaml` and a test that read
    the shipped file would measure nothing while looking like it measured everything.

    The derived line is the first sentence of `render_prompt`, and the sentence rule is what makes
    it usable rather than merely non-empty: a terminator only ends the sentence when a space or the
    end of the string follows it, so a ratio ("a 1.5:1 crop") and a decimal do not cut it in half,
    and a prompt written as one long unpunctuated instruction comes back whole rather than empty.
    """
    authored = _style("a", match_profile="Suits dense infographic sources with labelled diagrams.",
                      render_prompt="Near-black ground. Glowing teal circuit motifs.")
    derived = _style("b", match_profile="",
                     render_prompt="Near-black ground with glowing teal nodes. Big white headline "
                                   "top. Labelled icon chips below.")
    ratio = _style("c", match_profile="",
                   render_prompt="Shot on a 1.5:1 crop at f2.8 with a warm cast. Second sentence.")
    unpunctuated = _style("d", match_profile="",
                          render_prompt="Cream ground heavy geometric sans headline no photography")

    assert styles.match_profile_for(authored) == \
        "Suits dense infographic sources with labelled diagrams.", "the authored line always wins"
    assert styles.match_profile_for(derived) == "Near-black ground with glowing teal nodes."
    assert styles.match_profile_for(ratio) == \
        "Shot on a 1.5:1 crop at f2.8 with a warm cast.", "a decimal is not a sentence end"
    assert styles.match_profile_for(unpunctuated) == \
        "Cream ground heavy geometric sans headline no photography", \
        "no terminator returns the whole prompt — too much beats nothing for a matcher"


def test_d56_a_style_with_neither_field_answers_with_an_empty_string_and_never_raises() -> None:
    """The degenerate case, which `style_match._candidate_block` reads as "a candidate with no
    profile" and simply omits the `suits:` line for. Still nameable, just undescribed — and never
    an exception, because the matcher is fail-open by contract and a raise here would take out the
    whole call over one under-authored entry."""
    blank = _style("blank", match_profile="", render_prompt="")
    spaces = _style("spaces", match_profile="   ", render_prompt="   \n  ")

    assert styles.match_profile_for(blank) == ""
    assert styles.match_profile_for(spaces) == "", "whitespace is absence, on both fields"


def test_d56_a_missing_match_profile_is_an_advisory_warning_and_never_an_error() -> None:
    """The FR-295 line in the sand: this field can make a MATCH worse and can never make a RUN
    impossible.

    The warning names the style and says what to write, because "no match_profile" alone would
    leave an operator guessing whether the field is a look, a budget or a selector. And the errors
    list stays empty — promoting this to an exit 2 would refuse the run at $0 over a style that
    renders exactly as authored.
    """
    reg = _registry(_style("silent", match_profile=""), _style("b"), _style("c"))

    errors, warnings = styles.validate(reg, _config(formats={"image": 1}))

    assert errors == [], \
        "an under-described style still renders; FR-295 refuses only what is impossible"
    found = [line for line in warnings if "silent" in line]
    assert len(found) == 1, warnings
    assert "match_profile" in found[0] and "FR-334" in found[0]
    # …and the style is fully assignable, which is the half a warning could otherwise be read as
    # denying: the pool, the rotation and the render are all untouched by the missing sentence.
    entries = _entries(range(3))
    styles.assign_styles(entries, reg, "hypedigitaly")
    assert "silent" in _keys(entries)


def test_d56_a_registry_authored_before_match_profile_existed_loads_and_validates_clean(
    tmp_path: Path,
) -> None:
    """The upgrade path, end to end: an operator's on-disk `styles.yaml` written before v2.4.0.

    Every style in it lacks the field, so the file earns one advisory warning per style and ZERO
    errors — it loads, it validates, it assigns, and every creative gets a look. That is the same
    tolerance the withdrawn `reference_images` key gets (D46): a registry carrying a field a later
    version adds, or missing one a later version wants, still runs today. Anything stricter would
    turn "upgrade the engine" into "exit 2 until you re-author nine styles".
    """
    _write_registry(tmp_path, [dict(_MINIMAL_NO_PROFILE, key=f"old-{index}") for index in range(3)])

    registry = styles.load_registry([tmp_path])
    errors, warnings = styles.validate(registry, _config(formats={"image": 3}))

    assert [style.key for style in registry.styles] == ["old-0", "old-1", "old-2"]
    assert errors == [], f"an old registry must not refuse a run: {errors}"
    assert len(warnings) == 3 and all("match_profile" in line for line in warnings), warnings
    # And the matcher still has something to describe each candidate with — the derived line.
    for style in registry.styles:
        assert styles.match_profile_for(style) == "Flat card.", "derived from `render_prompt`"


# --------------------------------------------------------------------------- assign_styles


def test_the_same_plan_gets_the_same_styles_however_often_it_is_assigned() -> None:
    """Determinism is what makes a re-preview of the same topic set answerable: the operator sees
    the styles the run will actually use, and W5 re-runs the preview to prove it."""
    reg = _registry(_style("s0"), _style("s1"), _style("s2"))
    first, second = _entries(range(6)), _entries(range(6))

    styles.assign_styles(first, reg, "hypedigitaly")
    styles.assign_styles(first, reg, "hypedigitaly")  # idempotent: assigning twice changes nothing
    styles.assign_styles(second, reg, "hypedigitaly")

    assert _keys(first) == ["s0", "s1", "s2", "s0", "s1", "s2"]
    assert _keys(first) == _keys(second)


def test_a_gapped_order_picks_exactly_what_the_same_order_picks_in_a_dense_plan() -> None:
    """The v2.2 fix, stated as the invariant it buys: `entry.order` is GAPPED after `_confirm`
    trims and `_select` drops, and a shared cursor would accumulate those gaps into a different
    style for every survivor. Each pick is a pure function of the entry's own order, so a dropped
    creative never reshuffles anyone else's look."""
    reg = _registry(_style("s0"), _style("s1"), _style("s2"), _style("s3"))
    dense, gapped = _entries(range(6)), _entries([0, 2, 5])

    styles.assign_styles(dense, reg, "hypedigitaly")
    styles.assign_styles(gapped, reg, "hypedigitaly")

    dense_by_order = {entry.order: entry.style_key for entry in dense}
    assert _keys(gapped) == [dense_by_order[order] for order in (0, 2, 5)]
    assert dense_by_order[5] == gapped[-1].style_key == "s1"


def test_the_scan_steps_past_styles_that_do_not_serve_the_entrys_format() -> None:
    """The `for step in range(len(pool))` half of the scan: an entry lands on its order's slot and
    walks forward until a style that can serve its format — it never renders a carousel with a
    style authored for single images."""
    reg = _registry(_style("img", format_affinity=["image"]),
                    _style("deck", format_affinity=["carousel"]))

    images, decks = _entries([0, 1], "image"), _entries([0, 1], "carousel")
    styles.assign_styles(images, reg, "hypedigitaly")
    styles.assign_styles(decks, reg, "hypedigitaly")

    assert _keys(images) == ["img", "img"]
    assert _keys(decks) == ["deck", "deck"]


def test_a_carousel_entry_never_receives_a_slides_only_style() -> None:
    """M9/contracts item 5: `carousel_role: slides_only` styles (meme-caricature, ugc-tabletop)
    have a slide grammar and no cover grammar. Under anchor chaining slide 1 IS the deck's
    reference, so a slides-only anchor would set the look for every slide that follows it."""
    reg = _registry(_style("meme", format_affinity=["image", "carousel"],
                           per_format_guidance={"carousel_role": "slides_only"}),
                    _style("deck", format_affinity=["image", "carousel"]))

    decks, images = _entries(range(4), "carousel"), _entries(range(2), "image")
    styles.assign_styles(decks, reg, "hypedigitaly")
    styles.assign_styles(images, reg, "hypedigitaly")

    assert _keys(decks) == ["deck"] * 4
    assert _keys(images) == ["meme", "deck"], "for image the marker means nothing — plain affinity"


def test_a_brand_affine_style_never_serves_the_other_brand_while_neutral_styles_serve_both() -> None:
    """B3: `brand_affinity: [hypelead]` is a hard exclusion, not a preference — a HypeLead card
    rendered under the HypeDigitaly brand is a wrong-brand post, the one output no degrade path
    can rescue after the fact."""
    reg = _registry(_style("neutral"), _style("lead", brand_affinity=["hypelead"]))

    digitaly, lead = _entries(range(4)), _entries(range(4))
    styles.assign_styles(digitaly, reg, "hypedigitaly")
    styles.assign_styles(lead, reg, "hypelead")

    assert _keys(digitaly) == ["neutral"] * 4
    assert _keys(lead) == ["neutral", "lead", "neutral", "lead"]


# ------------------------------------------------- v2.2.0: the rotation's per-run seed (FR-291)


def test_the_default_and_the_fixed_mode_both_reproduce_the_pre_v220_rotation() -> None:
    """The escape hatch and the no-run-id default are the SAME rotation the module always had.

    Every caller with no run of its own (a harness, a re-derivation, every test above this line)
    keeps file order, and an operator who wants that back sets `styles.rotation: fixed`. Pinned
    because it is the fallback the seeded path is judged against.
    """
    reg = _registry(_style("s0"), _style("s1"), _style("s2"))
    default, fixed = _entries(range(6)), _entries(range(6))

    styles.assign_styles(default, reg, "hypedigitaly")  # no run id: offset 0
    styles.assign_styles(fixed, reg, "hypedigitaly", run_id="20260814_101500_ab12",
                         rotation="fixed")

    assert _keys(default) == _keys(fixed) == ["s0", "s1", "s2", "s0", "s1", "s2"]


def test_the_seeded_rotation_moves_where_a_run_starts_without_shuffling_what_follows() -> None:
    """The audit's "rotation repeats across runs" finding, fixed as an OFFSET, not a shuffle.

    Two runs of one config open on different styles; inside either run the pool is still walked in
    FILE order, consecutive orders still land on consecutive styles, and the assignment is still a
    pure function of `entry.order`. That last part is what keeps every other guarantee in this file
    true — a trim still cannot reshuffle a survivor.
    """
    reg = _registry(_style("s0"), _style("s1"), _style("s2"))
    monday, tuesday, again = _entries(range(6)), _entries(range(6)), _entries(range(6))

    styles.assign_styles(monday, reg, "hypedigitaly", run_id="20260814_090000_aaaa")
    styles.assign_styles(tuesday, reg, "hypedigitaly", run_id="20260814_090000_dddd")
    styles.assign_styles(again, reg, "hypedigitaly", run_id="20260814_090000_aaaa")

    assert _keys(monday) == _keys(again), "one run id is one assignment, always"
    # Two ids whose seeds land on different slots of a 3-style pool. Neighbouring run ids CAN
    # collide — an offset over N styles has N outcomes, and the point is that a batch stops always
    # opening on style 1, not that consecutive runs are guaranteed to differ.
    assert _keys(monday) != _keys(tuesday), "the seed must move where a run opens"
    for keys in (_keys(monday), _keys(tuesday)):
        assert keys[3:] == keys[:3], "still a rotation over the pool in FILE order"
        assert len(set(keys)) == 3, "an offset uses the whole pool, exactly like file order did"


def test_a_gapped_order_still_picks_what_that_order_picks_in_a_dense_seeded_plan() -> None:
    """The seed shifts the START of every scan by one shared amount, so the gap-proofness the
    no-cursor design bought survives it: `_confirm` trims and `_select` drops still cannot move a
    surviving creative's look."""
    reg = _registry(_style("s0"), _style("s1"), _style("s2"), _style("s3"))
    dense, gapped = _entries(range(6)), _entries([0, 2, 5])

    styles.assign_styles(dense, reg, "hypedigitaly", run_id="20260814_090000_aaaa")
    styles.assign_styles(gapped, reg, "hypedigitaly", run_id="20260814_090000_aaaa")

    dense_by_order = {entry.order: entry.style_key for entry in dense}
    assert _keys(gapped) == [dense_by_order[order] for order in (0, 2, 5)]


def test_the_seed_is_a_stable_checksum_and_never_pythons_salted_hash() -> None:
    """Cross-PROCESS determinism, which builtin `hash()` does not give for `str`: the same run id
    must seed identically in the run that assigned the styles and in anything re-deriving them
    later (a replay, a test, a second process reading meta.yaml)."""
    assert styles.rotation_seed("20260814_090000_aaaa") == 572_962_395  # crc32 of those bytes
    assert styles.rotation_seed("20260814_090000_aaaa", "fixed") == 0
    assert styles.rotation_seed("", "seeded") == 0
    assert styles.rotation_seed("  ", "seeded") == 0


def test_an_empty_pool_raises_rather_than_assigning_nothing() -> None:
    """Unreachable live — `validate` turns it into a pre-flight exit 2 — but the module must not
    answer an impossible question with a half-assigned plan if a caller ever skips validation."""
    reg = _registry(_style("lead", brand_affinity=["hypelead"]))

    with pytest.raises(StyleRegistryError):
        styles.assign_styles(_entries([0]), reg, "hypedigitaly")


# ---------------------------------------------------- FR-314: the operator's style selection
#
# `styles.enabled` is a SELECTOR over the registry, never registry content (D47/D-E). Everything
# below is about that distinction holding: the selector narrows the pool the rotation draws on and
# changes nothing else — not the file, not the order, not the determinism, not what a style says.


def test_fr314_an_empty_selection_is_every_style_and_assigns_exactly_what_it_did_before() -> None:
    """The compatibility clause, pinned as an equality rather than described: `enabled=[]` (the
    shipped default, and what every pre-FR-314 config means) must produce byte-identical
    assignments to the call that had no selector at all — otherwise the key's default would be a
    silent behaviour change for every existing config."""
    reg = _registry(_style("s0"), _style("s1"), _style("s2"))
    without, empty, twice = _entries(range(6)), _entries(range(6)), _entries(range(6))

    styles.assign_styles(without, reg, "hypedigitaly")
    styles.assign_styles(empty, reg, "hypedigitaly", enabled=[])
    styles.assign_styles(twice, reg, "hypedigitaly", enabled=[])
    styles.assign_styles(twice, reg, "hypedigitaly", enabled=[])  # still idempotent

    assert _keys(without) == ["s0", "s1", "s2", "s0", "s1", "s2"]
    assert _keys(empty) == _keys(twice) == _keys(without)
    assert styles.validate(reg, _config(enabled=[])) == ([], [])


def test_fr314_a_two_key_selection_assigns_only_those_two_and_stays_deterministic() -> None:
    """The selector's actual job: a batch wearing only the looks the operator picked.

    The reduced pool keeps FILE order, so the rotation over it is the same order-indexed scan —
    which is what makes a curated run as re-previewable as an uncurated one. `s2` is named first
    in the selection on purpose: the list is a membership test, not a running order, and letting a
    typed order re-sequence the registry would make the same selection two different rotations.
    """
    reg = _registry(_style("s0"), _style("s1"), _style("s2"), _style("s3"))
    first, second = _entries(range(6)), _entries(range(6))

    styles.assign_styles(first, reg, "hypedigitaly", enabled=["s2", "s1"])
    styles.assign_styles(second, reg, "hypedigitaly", enabled=["s2", "s1"])

    assert set(_keys(first)) == {"s1", "s2"}, "nothing outside the selection may be assigned"
    assert _keys(first) == ["s1", "s2", "s1", "s2", "s1", "s2"]  # file order, not typed order
    assert _keys(first) == _keys(second)


def test_fr314_the_selection_composes_with_the_brand_filter_rather_than_replacing_it() -> None:
    """Order of operations from the amendment: brand first (B3), then the selection, then FR-291's
    format scan. Selecting the other brand's style must not smuggle it into the rotation — a
    wrong-brand post is the one output no later step can rescue."""
    reg = _registry(_style("neutral"), _style("lead", brand_affinity=["hypelead"]))

    assert [style.key for style in styles.usable_styles(reg, "hypedigitaly", ["neutral", "lead"])] \
        == ["neutral"]
    assert [style.key for style in styles.usable_styles(reg, "hypelead", ["lead"])] == ["lead"]
    assert styles.selected(_style("neutral"), []) is True  # empty selection = everything
    assert styles.selected(_style("neutral"), ["other"]) is False

    entries = _entries(range(4))
    styles.assign_styles(entries, reg, "hypedigitaly", enabled=["neutral", "lead"])
    assert _keys(entries) == ["neutral"] * 4


def test_fr314_an_unknown_key_in_the_selection_is_an_error_naming_it_and_the_real_keys() -> None:
    """A mistyped selector is refused, never silently skipped: skipping it would thin the rotation
    by an amount the operator cannot see, and "that key is spelled wrong" would be indistinguishable
    from "that style is not brand-affine". The line carries the registry's actual keys because an
    override `prompts_dir` (FR-174) may define a completely different set from the shipped tree."""
    reg = _registry(_style("alpha"), _style("beta"), _style("gamma"))

    errors, _ = styles.validate(reg, _config(enabled=["alpha", "betta", "delta"]))

    unknown = [error for error in errors if "styles.enabled" in error]
    assert len(unknown) == 1, errors
    assert "betta" in unknown[0] and "delta" in unknown[0]
    assert "alpha" in unknown[0] and "beta" in unknown[0] and "gamma" in unknown[0]
    assert "FR-314" in unknown[0]
    # ... and a selection that is entirely real says nothing at all.
    assert styles.validate(reg, _config(enabled=["alpha", "gamma"]))[0] == []


def test_fr314_a_wholly_unknown_selection_reports_the_typo_once_and_not_its_consequences() -> None:
    """One mistyped `--styles` is ONE defect. Its empty pool and its empty per-format rotations are
    consequences of it, and printing all three would bury the only sentence that names the typo
    under two that merely repeat it. The moment any named key is real the selection is a genuine
    (if wrong) choice again, and the pool findings come back — they are then telling the operator
    something the unknown-key line does not."""
    reg = _registry(_style("alpha", format_affinity=["image"]), _style("beta"))

    only_typos, _ = styles.validate(reg, _config(enabled=["alfa"]))
    assert len(only_typos) == 1 and "alfa" in only_typos[0], only_typos

    mixed, _ = styles.validate(reg, _config(formats={"image": 0, "carousel": 0, "reel": 2},
                                            enabled=["alpha", "alfa"]))
    assert len(mixed) == 2, mixed  # the typo, AND the reel rotation the real key cannot serve
    assert any("alfa" in error for error in mixed)
    assert any("reel" in error for error in mixed)


def test_fr314_a_selection_that_empties_a_formats_pool_refuses_and_blames_itself() -> None:
    """FR-314's own refusal, and the reason it is worded separately from FR-295's: the registry is
    fine, the brand is fine, and the cure is a config line the operator just typed. The message has
    to say WHICH filter emptied the pool and name the keys that would fill it again — "no style is
    affine to carousel" would send someone to author a style that already exists."""
    reg = _registry(_style("shot", format_affinity=["image"]),
                    _style("deck", format_affinity=["carousel"]),
                    _style("both", format_affinity=["image", "carousel"]))
    config = _config(formats={"image": 4, "carousel": 2, "reel": 0}, enabled=["shot"])

    errors, _ = styles.validate(reg, config)

    carousel = [error for error in errors if "carousel" in error]
    assert len(carousel) == 1, errors
    assert "styles.enabled" in carousel[0] and "shot" in carousel[0]
    assert "deck" in carousel[0] and "both" in carousel[0]  # what to add back
    assert "run.formats.carousel" in carousel[0]  # FR-69: name the other line to edit
    # Widening the selection cures it without touching the registry.
    assert styles.validate(reg, _config(formats={"image": 4, "carousel": 2, "reel": 0},
                                        enabled=["shot", "deck"]))[0] == []


def test_fr314_a_selection_that_empties_the_whole_pool_names_what_the_brand_could_have_worn(
) -> None:
    """The pool-level twin of the format refusal. `assign_styles` must refuse the same run for the
    same reason if a caller ever skips validation — pre-flight is the door, not the only lock."""
    reg = _registry(_style("neutral"), _style("lead", brand_affinity=["hypelead"]))

    errors, _ = styles.validate(reg, _config(brand="hypedigitaly", enabled=["lead"]))

    assert any("styles.enabled" in error and "neutral" in error for error in errors), errors

    with pytest.raises(StyleRegistryError) as caught:
        styles.assign_styles(_entries([0]), reg, "hypedigitaly", enabled=["lead"])
    assert "styles.enabled" in str(caught.value) and "FR-314" in str(caught.value)


def test_fr314_the_thin_pool_warning_counts_the_selected_styles_not_the_authored_ones() -> None:
    """FR-291's "<3 usable styles repeats the same look" warning is about what the run will WEAR,
    so it has to see the selection: an eight-style registry narrowed to two is a two-style
    rotation, and the operator hears it before the batch, not after."""
    reg = _registry(_style("a"), _style("b"), _style("c"), _style("d"))

    assert styles.validate(reg, _config())[1] == []  # four usable, nothing to say

    errors, warnings = styles.validate(reg, _config(enabled=["a", "b"]))
    assert errors == []
    assert len(warnings) == 1 and "styles.enabled" in warnings[0], warnings


# --------------------------------------------------------------------------- assign_branding


@pytest.mark.parametrize("total", [1, 3, 7, 8, 10])
@pytest.mark.parametrize("ratio", [0.0, 0.3, 0.5, 1.0])
def test_the_branded_count_over_a_full_plan_is_floor_of_n_times_ratio(
    total: int, ratio: float,
) -> None:
    """v2.2's correction, pinned: `floor`, never `round`. N=8/r=0.5 gives the promised 4, but
    N=7/r=0.5 gives 3 and N=3/r=0.3 gives 0 — a ratio is a rate, and rounding it up would sign a
    post the operator never asked to be signed."""
    entries = _entries(range(total))

    styles.assign_branding(entries, ratio)

    assert sum(entry.branded for entry in entries) == math.floor(total * ratio)


def test_the_documented_corner_counts_are_the_ones_that_ship() -> None:
    """The four numbers §1.4 names by hand, because they are the ones an operator would call a
    bug: nothing at ratio 0, everything at ratio 1, and the two cases where `round` disagrees."""
    def branded(total: int, ratio: float) -> int:
        entries = _entries(range(total))
        styles.assign_branding(entries, ratio)
        return sum(entry.branded for entry in entries)

    assert branded(7, 0.5) == 3
    assert branded(8, 0.5) == 4
    assert branded(3, 0.3) == 0
    assert branded(10, 0.0) == 0
    assert branded(10, 1.0) == 10


@pytest.mark.parametrize("ratio", [0.0, 0.25, 0.3, 0.5, 0.75, 1.0])
def test_every_entry_matches_the_per_entry_predicate_on_its_own_order(ratio: float) -> None:
    """The predicate IS the contract (`floor((order+1)·r) > floor(order·r)`), not an implementation
    detail: T4.1 and the live session assert it per entry, because a count alone cannot tell a
    deterministic rotation from a lucky one."""
    entries = _entries(range(12))

    styles.assign_branding(entries, ratio)

    for entry in entries:
        expected = math.floor((entry.order + 1) * ratio) > math.floor(entry.order * ratio)
        assert entry.branded is expected, f"order {entry.order} at ratio {ratio}"


def test_a_trim_never_re_brands_a_creative_that_survived_it() -> None:
    """Deliberate (§1.4): over the live subset the branded count is simply the surviving orders
    that satisfy the predicate. Re-deriving the ratio over survivors would move the wordmark onto
    a creative the operator already saw in the plan without one."""
    full = _entries(range(10))
    styles.assign_branding(full, 0.5)
    before = {entry.order: entry.branded for entry in full}

    survivors = [entry for entry in full if entry.order in (0, 3, 7, 9)]
    styles.assign_branding(survivors, 0.5)

    assert {entry.order: entry.branded for entry in survivors} == {
        order: before[order] for order in (0, 3, 7, 9)}
    # And the live count is therefore NOT `floor(len(survivors) · ratio)` — three of these four
    # orders satisfy the predicate. Asserting a bare count over delivered meta.yaml would fail
    # here for the right reason, which is why §1.4 asserts the predicate instead.
    assert sum(entry.branded for entry in survivors) == 3 != math.floor(len(survivors) * 0.5)


# ------------------------------------------- FR-318: the branding master switch (v2.1.3, D48)
#
# `branding.enabled` ships FALSE (operator decision, 2026-08-13). Two things narrow when it is off
# and exactly two: `assign_branding` marks nothing, and `brand_ok` drops every `brand_slot: true`
# house-card style from the pool — a style whose whole grammar is a logo lockup and a CTA bar would
# otherwise render the brand's furniture around an empty slot, which is both M11's hallucination
# site and a self-branded creative on a run that asked for none.
#
# What does NOT narrow is the safety half. `branding.competitors` and every strip built on it
# (FR-294/FR-312) are about what may never appear in OUR frame; the switch is about how we sign it.
# That carve-out is pinned explicitly below, in both states, because it is the one place where
# "turn branding off" could be misread as "turn the blocklist off".


@pytest.mark.parametrize("ratio", [0.0, 0.3, 0.5, 1.0])
def test_fr318_with_the_switch_off_no_entry_is_branded_whatever_the_ratio_says(
    ratio: float,
) -> None:
    """The switch short-circuits the floor predicate entirely, and it WRITES `False` rather than
    skipping the loop.

    `entry.branded` has to be a stated fact on every entry: `refs.wordmark` and the render prompt's
    branding block both read it, and an unwritten value left over from an earlier pass would sign a
    creative on a run that asked for none.
    """
    entries = _entries(range(10))
    for entry in entries:
        entry.branded = True  # a stale value from an earlier pass

    styles.assign_branding(entries, ratio, enabled=False)

    assert [entry.branded for entry in entries] == [False] * 10
    assert all(entry.branded is False for entry in entries), "written, not merely falsy"


def test_fr318_switching_the_branding_on_restores_the_floor_predicate_exactly() -> None:
    """The default of `enabled=True` on the function is what keeps every pre-FR-318 caller and
    every test above this line meaningful — and the ON state has to be the SAME rotation it always
    was, not a re-derived one, or a config edit would move the wordmark between two runs of the
    same plan."""
    off, on = _entries(range(8)), _entries(range(8))

    styles.assign_branding(off, 0.5, enabled=False)
    styles.assign_branding(on, 0.5, enabled=True)

    assert sum(entry.branded for entry in off) == 0
    assert sum(entry.branded for entry in on) == math.floor(8 * 0.5) == 4
    for entry in on:
        assert entry.branded is (math.floor((entry.order + 1) * 0.5)
                                 > math.floor(entry.order * 0.5))


def test_fr318_a_house_card_style_leaves_the_pool_while_nothing_is_being_signed() -> None:
    """`brand_slot: true` means "this style IS a brand's own house card" — its layout is a logo
    lockup and its whole grammar is the signature.

    The drop happens in `brand_ok`, one filter, so the menu's count, the pre-flight refusal, the
    preview and the paid run all narrow identically. A second implementation at assignment time
    would let the picker promise eight styles for a run that can wear seven.
    """
    house = _style("hypelead-brand-card", brand_affinity=["hypelead"], brand_slot=True)
    neutral = _style("photoreal-ambient-caption")
    registry = _registry(neutral, house)

    assert styles.brand_ok(house, "hypelead", branding_enabled=True) is True
    assert styles.brand_ok(house, "hypelead", branding_enabled=False) is False
    assert styles.brand_ok(neutral, "hypelead", branding_enabled=False) is True, \
        "a brand-neutral style is unaffected — the switch drops house cards, not the pool"

    off = styles.usable_styles(registry, "hypelead", branding_enabled=False)
    on = styles.usable_styles(registry, "hypelead", branding_enabled=True)
    assert [style.key for style in off] == ["photoreal-ambient-caption"]
    assert [style.key for style in on] == ["photoreal-ambient-caption", "hypelead-brand-card"], \
        "FILE order, both ways — the rotation depends on it"


def test_fr318_the_house_card_is_never_assigned_while_the_switch_is_off() -> None:
    """The pool narrowing has to reach ASSIGNMENT, not just the count the picker prints. A run
    that assigned the brand card anyway would render a logo lockup with `wordmark=""`, which is
    the exact frame M11 exists to prevent: a described-but-unfilled signature zone."""
    house = _style("hypelead-brand-card", brand_affinity=["hypelead"], brand_slot=True)
    registry = _registry(_style("neutral-a"), house, _style("neutral-b"))
    off, on = _entries(range(6)), _entries(range(6))

    styles.assign_styles(off, registry, "hypelead", branding_enabled=False)
    styles.assign_styles(on, registry, "hypelead", branding_enabled=True)

    assert "hypelead-brand-card" not in _keys(off)
    assert set(_keys(off)) == {"neutral-a", "neutral-b"}
    assert "hypelead-brand-card" in _keys(on), "the card is back the moment signing is back"


def test_fr318_a_pool_emptied_by_the_switch_refuses_at_preflight_and_names_the_switch() -> None:
    """FR-295's refusal SHAPE is unchanged — exit 2 at $0 — and only the cure differs.

    Naming the wrong dial sends the operator to edit `brand_affinity` in a registry that was never
    the problem, so the line says `branding.enabled is false` and lists the house card(s) it
    removed. The switch is deliberately named only when it REALLY removed something: a registry
    with no house cards at all would otherwise be told to flip a dial that changes nothing.
    """
    only_house = _registry(_style("hypelead-brand-card", brand_affinity=["hypelead"],
                                  brand_slot=True))
    config = _config(brand="hypelead")

    config.branding.enabled = False
    errors, _ = styles.validate(only_house, config)
    assert errors, "an empty pool is a refusal, not a warning (FR-295)"
    assert "branding.enabled is false" in errors[0], errors
    assert "hypelead-brand-card" in errors[0] and "FR-318" in errors[0]

    config.branding.enabled = True
    assert styles.validate(only_house, config)[0] == [], "switch it on and the pool is fine"


def test_fr318_a_pool_emptied_by_the_brand_alone_does_not_blame_the_switch() -> None:
    """The complement, and the reason the naming is conditional: a registry of the OTHER brand's
    styles is empty under this brand whether anything is being signed or not. Telling the operator
    to flip `branding.enabled` there would send them to change a setting that cannot help."""
    other_brand = _registry(_style("hd-only", brand_affinity=["hypedigitaly"]))
    config = _config(brand="hypelead")
    config.branding.enabled = False

    errors, _ = styles.validate(other_brand, config)

    assert errors and "brand_affinity" in errors[0]
    assert not any("branding.enabled" in line for line in errors), \
        "the switch removed nothing here, so it is named nowhere"


@pytest.mark.parametrize("enabled", [False, True])
def test_fr318_the_competitor_blocklist_is_identical_in_both_states(enabled: bool) -> None:
    """THE safety carve-out, pinned in both states because it is the misreading that would hurt.

    "Turn branding off" means "do not sign our creatives"; it has never meant "stop filtering
    competitors". `branding.competitors` is FR-294/FR-312's layer-1 blocklist — a fact about what
    may never appear in our frame — and nothing in `styles.py` reads `enabled` on its way to it.
    An operator disabling self-branding to try a neutral batch must not thereby ship a competitor's
    brand name on it.
    """
    registry = _registry(_style("neutral-a"), _style("neutral-b"), _style("neutral-c"))
    blocklist = ["Zzqcorp", "Jasper"]

    def graded(competitors: list[str]) -> tuple[list[str], list[str], list[str]]:
        config = _config(brand="hypelead")
        config.branding.enabled = enabled
        config.branding.competitors = list(competitors)
        entries = _entries(range(6))
        styles.assign_styles(entries, registry, config.branding.brand,
                             branding_enabled=config.branding.enabled)
        styles.assign_branding(entries, config.branding.brand_ratio,
                               enabled=config.branding.enabled)
        errors, warnings = styles.validate(registry, config)
        assert config.branding.competitors == list(competitors), "nothing here edits the list"
        return _keys(entries), errors, warnings

    # The blocklist changes NOTHING about the pool, the rotation or the refusals — in either
    # switch state — because it is not a fact about styles at all. That is the separation: this
    # module owns which look a creative wears and whether it is signed; §1.5's strip layers own
    # which words may appear on it, and they are consulted where text is assembled, not here.
    assert graded(blocklist) == graded([])
    # And the switch really is doing its one job in this run, so the equality above is not
    # holding because nothing was exercised.
    entries = _entries(range(6))
    styles.assign_branding(entries, 0.5, enabled=enabled)
    assert any(entry.branded for entry in entries) is enabled


# ------------------------------------------------------------------ the retired picture channel


def test_the_module_offers_no_way_to_turn_a_style_into_a_picture(tmp_path: Path) -> None:
    """D46/FR-18, asserted as absence: a meta-style is TEXT, and this module is the only place a
    style could ever have handed a file path to an uploader. `pick_reference_window` and the
    magic-byte reader behind it are gone, and the public surface must not grow either back — a
    re-introduced window is a style picture in a render payload, which is the whole thing the
    amendment removed.

    `tmp_path` is unused on purpose: there is no file for this module to look at any more.
    """
    assert not hasattr(styles, "pick_reference_window")
    assert "pick_reference_window" not in styles.__all__ and "UploadMemo" not in styles.__all__
    # The upload memo went WITH the uploads, to the only module that still performs them.
    assert isinstance(refs_module.UploadMemo, type(dict[Path, str]))


def test_a_stale_registry_that_still_lists_pictures_loads_clean_and_ignores_them(
    tmp_path: Path,
) -> None:
    """An operator's on-disk `styles.yaml` may predate D46. The dead key must not become a shape
    error: the file loads, the style is assignable, and the pictures are simply never read."""
    _write_registry(tmp_path, [
        {"key": f"legacy-{index}",
         "render_prompt": "Flat graphic card, centred subject, hard shadow.",
         "format_affinity": ["image"],
         # A profile on each, so the ONE finding this test could produce is a reference-image one.
         # A registry that predates D56 as well as D46 is a different fixture — see
         # `test_d56_a_registry_authored_before_match_profile_existed_loads_and_validates_clean`.
         "match_profile": "Suits plain single-subject sources with very little text.",
         "reference_images": ["Inspiration/definitely-not-here.png"]}
        for index in range(3)])  # three, so the FR-291 thin-pool warning stays out of the way

    registry = styles.load_registry([tmp_path])

    assert [style.key for style in registry.styles] == ["legacy-0", "legacy-1", "legacy-2"]
    assert styles.validate(registry, _config(formats={"image": 1})) == ([], []), (
        "a picture that cannot exist is not a finding: nothing reads the key")


# --------------------------------------------------------------------------- style_for


def test_style_for_answers_the_exact_key_and_names_an_unknown_one(tmp_path: Path) -> None:
    """`PlanEntry.style_key` is persisted to meta.yaml, so a key that no longer resolves means a
    registry changed under a run's feet: the operator gets the key AND the file that was searched,
    not a KeyError."""
    reg = _registry(_style("a"), _style("wanted"), origin=str(tmp_path / "styles.yaml"))

    assert styles.style_for(reg, "wanted").key == "wanted"

    with pytest.raises(StyleRegistryError) as caught:
        styles.style_for(reg, "vanished")
    assert "vanished" in str(caught.value)


# ----------------------------------------- D55-D57: the SHIPPED registry, read as it ships
#
# Every test above builds a synthetic registry, deliberately: a suite whose assertions move when a
# style is re-authored is a suite that stops being run. These few read `prompts/styles.yaml`
# itself, because the facts they pin are not properties of the module at all — they are the
# operator's decisions of 2026-08-20 (D55, then D56/D57), and the run refuses at pre-flight
# (FR-295, exit 2, $0) the day the file and the shipped configs disagree about them.

#: TWENTY-SIX since v2.5.2. D55 brought the registry to nine; D56 added `build-log-mono` plus the
#: four census-driven archetype styles (`icon-ledger-carousel`, `circuit-atlas-dark`,
#: `social-quote-card`, `terminal-mockup-deck`); D57 added the five `-teal` spine variants; D61
#: added the seven carousel-derived styles authored from the operator's own reference decks
#: (`big-number-editorial`, `contrast-verdict-deck`, `photo-poster-statement`,
#: `mono-cutout-editorial`, `neon-glass-dark`, `paper-editorial-carousel`, `aurora-white-deck`).
#: The originals were left untouched by D57 on purpose — colour is curated by CHOOSING styles,
#: never by editing one (standing decision D-G), which is why a variant is a new key and not an
#: edit; D61's seven carry the same rule one step further and ship NO `-teal` twins at all,
#: because five of them were authored on the house teal from the first line.
SHIPPED_STYLES = 26
#: D61's selection, pinned as data: the seventeen keys the three brand configs enable — D57's
#: twelve plus the five D61 styles that carry the brand teal. The list is here rather than read
#: from a config so a config edit that silently drops a key fails a test with a name instead of
#: quietly narrowing the rotation. Seventeen enabled styles are only coherent BECAUSE those
#: configs also pin `assignment: matched` (D56 decision 5) — the two settings are one decision in
#: one file, and the config test below asserts them together for that reason.
#:
#: Two D61 styles are deliberately ABSENT: `paper-editorial-carousel` (vermilion accent) and
#: `mono-cutout-editorial` (no accent at all) are off the teal spine, so they stay in the registry
#: for `default.yaml` and an empty selector and out of the brand selection — see the D61 test at
#: the foot of this file, which is where that absence is asserted rather than assumed.
ENABLED_SEVENTEEN = ["anime-noir-statement", "platform-showcase-card",
                     "letterpress-print-carousel-teal", "meme-caricature-panels-teal",
                     "quiet-luxury-night-photoreal-teal", "photoreal-ambient-caption-teal",
                     "ugc-tabletop-statement-teal", "build-log-mono", "icon-ledger-carousel",
                     "circuit-atlas-dark", "social-quote-card", "terminal-mockup-deck",
                     "big-number-editorial", "contrast-verdict-deck", "photo-poster-statement",
                     "neon-glass-dark", "aurora-white-deck"]
#: D61's seven, in REGISTRY FILE ORDER — they were appended to the foot of `prompts/styles.yaml`
#: in exactly this sequence and the D61 test at the end of this file asserts that they are still
#: the file's tail. Named as a constant because five separate guards need to say "the newcomers"
#: (the mono roster, the counter-zone roster, the archetype map, the off-spine pair and the tail
#: check) and a roster spelled five times is a roster that drifts in four of them.
_D61_STYLES = ["big-number-editorial", "contrast-verdict-deck", "photo-poster-statement",
               "mono-cutout-editorial", "neon-glass-dark", "paper-editorial-carousel",
               "aurora-white-deck"]
#: The two of D61's seven that stay OUT of the brand selection, and why they are a pair: neither
#: carries the house teal. `paper-editorial-carousel` keeps its source's native vermilion and
#: `mono-cutout-editorial` carries no accent hue at all, so both are off the D57 teal spine while
#: still being fully valid registry entries an operator can enable from `default.yaml`.
_D61_OFF_SPINE = ["paper-editorial-carousel", "mono-cutout-editorial"]


def _shipped() -> StyleRegistry:
    """The real registry, loaded exactly as a run loads it (FR-174's `prompts_dir` seam)."""
    return styles.load_registry([REPO / "prompts"])


def test_d56_the_shipped_registry_parses_and_holds_twenty_six_uniquely_keyed_styles() -> None:
    """There is NO fallback (FR-295): a registry that will not parse is exit 2 and $0, not a
    built-in default set. So "it parses" is a real assertion about the shipped bytes, and the
    count is what catches a style added or removed without anyone updating the configs that
    enable it.

    The four membership assertions are one per decision that put a style in this file — D55's
    photoreal entry, one of D56's archetype four, one of D57's spine variants, one of D61's
    seven carousel-derived entries — because a count alone passes for a style deleted and a
    different one added in the same edit, which is exactly the shape a registry re-organisation
    takes.
    """
    registry = _shipped()
    keys = [style.key for style in registry.styles]

    assert len(registry.styles) == SHIPPED_STYLES
    assert len(set(keys)) == SHIPPED_STYLES, f"duplicate style key in the registry: {keys}"
    assert "quiet-luxury-night-photoreal" in keys, "D55's style"
    assert "circuit-atlas-dark" in keys, "one of D56's four census-driven archetype styles"
    assert "ugc-tabletop-statement-teal" in keys, "one of D57's five teal-spine variants"
    assert "contrast-verdict-deck" in keys, "one of D61's seven carousel-derived styles"
    # D57's mechanism, pinned as the absence of the alternative: a variant is a NEW KEY beside an
    # untouched original (D-G), never an edit to the original's palette. Both must be present.
    assert "ugc-tabletop-statement" in keys, "D57 duplicated the style; it did not move it"
    assert registry.origin.endswith("styles.yaml") and registry.content_hash


def test_d55_the_new_style_is_a_full_density_registry_entry_and_not_a_stub() -> None:
    """The style was authored from two Inspiration frames, TEXT ONLY (D46/F3: the inspiration
    informs the authorship and never becomes a render reference), so every field a run reads has
    to be filled in words — there is no picture behind it to make up the difference.

    `subject_mode: scene_fixed` is the load-bearing one: this is ONE resolved scene (the penthouse
    desk before a night skyline), and a deck of it is the same room from a different distance
    rather than a new room per slide. `text_density: minimal` is what makes it a compress-mode
    style at all — one small sentence in a dark frame is exactly the look a 1,000-character panel
    destroys, which is the measurement D54 was adopted from.
    """
    style = styles.style_for(_shipped(), "quiet-luxury-night-photoreal")

    assert style.subject_mode == "scene_fixed"
    assert style.text_density == "minimal"
    assert style.motion_profile == "photographic"
    assert style.brand_affinity == [] and style.brand_slot is False, "no brand owns this look"
    for field in ("render_prompt", "typography", "text_placement", "image_treatment",
                  "visual_pacing"):
        assert len(str(getattr(style, field)).strip()) > 40, f"{field} is a stub"
    # The registry's palette convention is `ROLE name #HEX: where it goes` per colour, plus any
    # number of rule lines that name no colour at all ("no saturated hue; …"). Both shapes are
    # legitimate, so the assertion counts the ones that carry a hex rather than demanding one of
    # every entry — a rule line is what stops the model reading the list as a licence.
    hexed = [entry for entry in style.palette if "#" in entry]
    assert len(hexed) >= 4, f"a full-density palette names its colours: {style.palette}"
    assert all(":" in entry for entry in hexed), \
        "each colour states WHERE it goes, per the registry's own convention"
    assert style.layout_zones and all(isinstance(zone, LayoutZone) for zone in style.layout_zones)
    assert len(style.exclusions) >= 4
    assert style.per_format_guidance.get("carousel_cover")
    assert style.per_format_guidance.get("carousel_slide")


def test_d55_the_new_styles_budgets_are_minimal_density_and_the_slide_cap_is_the_tightest() -> None:
    """`max_onimage_chars` is half of the `min(config, style)` arithmetic FR-259 enforces and the
    number D54's compress prompt asks the model to fit, so it is the one field where a typo is
    money: a slide cap left at a headline's size would make every compressed line trip the
    engine's backstop trim, and one left wide would defeat the whole reason this style exists."""
    caps = styles.style_for(_shipped(), "quiet-luxury-night-photoreal").max_onimage_chars

    assert set(caps) == {"headline", "subline", "slide", "overlay"}
    assert all(isinstance(value, int) and value > 0 for value in caps.values()), caps
    assert caps["slide"] == 160
    assert caps["slide"] < TextBudgets().slide, \
        "a style may only LOWER the config ceiling, never raise it (FR-259)"
    assert caps["headline"] <= TextBudgets().image_headline
    assert caps["overlay"] <= caps["slide"], "the reel overlay is the smallest slot on this look"


def test_d55_the_new_style_carries_a_list_mode_so_a_list_panel_reflows_rather_than_overflows(
) -> None:
    """FR-304b/FR-329: a source panel that is a LIST has to be set as one, or the render model
    breaks label/value pairs across lines and the craft critic reports a defect nobody caused.
    Every carousel-affine style needs the treatment; this pins the new one's trigger and shape."""
    style = styles.style_for(_shipped(), "quiet-luxury-night-photoreal")

    assert isinstance(style.list_mode, ListMode)
    assert style.list_mode.reflow_over_chars == 110 and style.list_mode.max_rows == 4
    assert len(style.list_mode.layout.strip()) > 40, "the layout instruction is prose, not a flag"
    # The trigger is a real predicate over a real panel, so it is asserted as one.
    assert styles.is_list_panel(style, "1. One\n2. Two\n3. Three\n4. Four\n5. Five") is True
    assert styles.is_list_panel(style, "One short line.") is False


def test_d55_the_new_style_is_carousel_affine_and_may_anchor_a_deck() -> None:
    """Carousel affinity alone is not enough: under anchor chaining slide 1 IS the deck's style, so
    a `carousel_role: slides_only` entry is never assigned to a carousel at all. This style has no
    such marker, which is what makes it one of the three keys the shipped rotation can actually
    draw for a deck."""
    style = styles.style_for(_shipped(), "quiet-luxury-night-photoreal")

    assert "carousel" in style.format_affinity
    assert style.per_format_guidance.get("carousel_role") is None
    assert styles.fmt_affine(style, "carousel") is True
    assert styles.fmt_affine(style, "image") is True and styles.fmt_affine(style, "reel") is True


def test_d61_the_seventeen_key_selection_validates_clean_under_the_shipped_brand() -> None:
    """The registry and the configs have to land in the SAME change: a `styles.enabled` key the
    registry lacks is a pre-flight exit 2 on EVERY run of that config (FR-314/FR-295). This is that
    barrier, asserted against the real registry and the real seventeen-key list — no errors, and no
    warnings either.

    "No warnings" is the stronger half and covers more with every session. Since D56 it means no
    style in the SHIPPED file is over the 120-word ceiling, leaks an unresolved either/or out of
    `render_prompt`, declares a dead `list_mode` **or ships without a `match_profile`**. Since D60
    it also means none of them names more type families than a reader can tell apart (FR-348) and
    none of them leaves a CHOICE open in any DNA field, not just in `render_prompt` (FR-349) — and
    because `_PALETTE_CONTRACT_ENFORCED` is `True`, the `errors == []` line above now additionally
    means every palette in the file obeys the one-accent-hue, one-eighth-of-frame contract
    (FR-347). `validate` walks the whole registry for warnings, not just the selection, so this one
    assertion covers all twenty-six entries; the D60 test at the foot of this file says the same
    thing from the other end, under both brands and with nothing enabled.

    The ordered list is the point of the last assertion and the reason D61's five newcomers are
    APPENDED to it rather than slotted in: `usable_styles` answers in REGISTRY FILE order, never
    in the order the config happens to type its keys, and the seven D61 entries were appended to
    the foot of `styles.yaml`. A newcomer that turned up in the middle of this list would mean
    someone re-ordered the registry, which silently re-seeds FR-291's deterministic rotation for
    every run of every config.
    """
    registry = _shipped()
    config = _config(brand="hypelead", formats={"image": 0, "carousel": 6, "reel": 0},
                     enabled=ENABLED_SEVENTEEN)

    errors, warnings = styles.validate(registry, config)

    assert errors == [], f"the shipped selection would refuse a run: {errors}"
    assert warnings == [], f"and it earns not even the thin-pool warning: {warnings}"
    assert [style.key
            for style in styles.usable_styles(registry, "hypelead", ENABLED_SEVENTEEN)] == [
        "anime-noir-statement", "platform-showcase-card", "build-log-mono",
        "icon-ledger-carousel", "circuit-atlas-dark", "social-quote-card", "terminal-mockup-deck",
        "letterpress-print-carousel-teal", "meme-caricature-panels-teal",
        "quiet-luxury-night-photoreal-teal", "photoreal-ambient-caption-teal",
        "ugc-tabletop-statement-teal", "big-number-editorial", "contrast-verdict-deck",
        "photo-poster-statement", "neon-glass-dark",
        "aurora-white-deck"], "FILE order, never the order the config typed"


def test_d56_every_shipped_style_authors_its_own_match_profile() -> None:
    """The matcher reads ONE line per candidate, and this is where the shipped file is held to
    writing it (D56/FR-335).

    `match_profile_for` never blanks a candidate out — it derives a weaker line from the first
    sentence of `render_prompt` — so a missing profile does not break a run and is deliberately
    only a warning. What it breaks is the QUALITY of every match on that style: `render_prompt`
    says how a look works ("near-black ground, glowing teal circuit motifs") where a
    `match_profile` says what source material it suits, and a matcher handed the first has to guess
    the second. With a seventeen-key pool that guess is most of the decision, which is why every
    one of the twenty-six shipped entries authors the real line and why the derivation is exercised
    against a SYNTHETIC registry (below) rather than here — there is nothing to derive from in this
    file, and a test that silently measured nothing would be worse than no test.
    """
    registry = _shipped()

    missing = [style.key for style in registry.styles if not style.match_profile]
    assert missing == [], f"shipped style(s) with no `match_profile`: {missing}"
    for style in registry.styles:
        assert styles.match_profile_for(style) == style.match_profile, \
            f"{style.key}: the authored line must win over the derived one"
        assert len(style.match_profile.split()) >= 8, \
            f"{style.key}: `match_profile` is a stub, not one or two usable sentences"


def test_d61_the_three_shipped_brand_configs_enable_those_seventeen_keys_and_pin_matched() -> None:
    """The configs and the registry are one decision in two files; this is where they are checked
    against each other. Read through `load_config` rather than by parsing YAML, so a key that
    loads to something different from what it looks like on disk is caught here.

    `assignment: matched` is asserted in the same loop and not in a test of its own, because it is
    not a separate setting: seventeen enabled styles under plain rotation would put seventeen
    unrelated looks through one batch (D56 risk 3). The selection is only coherent BECAUSE the
    matcher is choosing, so a config that widened the pool and left `assignment` on the engine
    default would be a regression this pairing is here to catch — and D61 widened it again,
    12 -> 17, for the opposite reason to the one that reads first: the 2026-08-20 run put six of
    nine decks on `icon-ledger-carousel` because it was the only enabled style whose profile
    claimed numbered decks at all. A thin pool does not spread a matcher out, it concentrates it.
    """
    registry = _shipped()
    registry_keys = {style.key for style in registry.styles}

    for name in ("hypedigitaly", "hypedigitaly-cs", "hypedigitaly-fresh"):
        config = load_config(name, configs_dir=CONFIGS_DIR)
        assert config.styles.enabled == ENABLED_SEVENTEEN, f"{name} drifted from D61's selection"
        assert config.styles.assignment == "matched", \
            f"{name} widened the pool to seventeen without the matcher that keeps it coherent"
        assert set(config.styles.enabled) <= registry_keys, \
            f"{name} enables a style the registry does not define — exit 2 on every run"
        assert styles.validate(registry, config)[0] == [], f"{name} would refuse at pre-flight"


def test_d57_the_two_slides_only_keys_are_enabled_but_INERT_on_a_carousel_plan() -> None:
    """The operator kept both `slides_only` variants in the selection knowing neither can be
    assigned while the configs are all-carousel: they are there to activate the day image posts
    return, and keeping them costs nothing because `fmt_affine` drops them per format. Same ruling
    as D55, now covering two keys instead of one (`ugc-tabletop-statement-teal` inherits the
    marker from its original exactly as `meme-caricature-panels-teal` does).

    So the effective carousel rotation is FIFTEEN of the seventeen, and this pins that the two it
    excludes are the right two — a `slides_only` key that silently became assignable would put a
    caricature panel or a tabletop shot on a deck's ANCHOR slide, and under anchor chaining slide 1
    sets the look for every slide that follows it. None of D61's seven is a third: they were all
    authored cover-capable, which is what a deck-derived style has to be.
    """
    registry = _shipped()
    inert = ("meme-caricature-panels-teal", "ugc-tabletop-statement-teal")
    pool = {style.key for style in styles.usable_styles(registry, "hypelead", ENABLED_SEVENTEEN)}
    entries = _entries(range(24), fmt="carousel")

    styles.assign_styles(entries, registry, "hypelead", enabled=ENABLED_SEVENTEEN)

    for key in inert:
        assert key in pool, f"{key}: selected and brand-clean…"
        assert styles.fmt_affine(styles.style_for(registry, key), "carousel") is False, \
            f"{key}: …and still never affine to a deck"
        assert key not in _keys(entries), f"{key}: an inert key was assigned to a carousel"
    assert set(_keys(entries)) == set(ENABLED_SEVENTEEN) - set(inert), \
        "and every one of the other fifteen really is reachable — an inert THIRD key is a bug"


def test_d57_the_brand_card_is_absent_from_the_selection_and_would_be_dropped_anyway() -> None:
    """Two independent reasons, and the test asserts both because either alone would be a
    coincidence. `hypelead-brand-card` is not in the seventeen keys; and `branding.enabled` is
    false in all three shipped configs, so `brand_ok` drops a `brand_slot` style regardless.
    Branded entries sign through the TEXT block on any style (FR-318/FR-292), which is why
    excluding the card costs the run no signature it would otherwise have carried."""
    registry = _shipped()

    assert "hypelead-brand-card" not in ENABLED_SEVENTEEN
    with_switch_off = styles.usable_styles(registry, "hypelead", branding_enabled=False)
    assert "hypelead-brand-card" not in {style.key for style in with_switch_off}
    for name in ("hypedigitaly", "hypedigitaly-cs", "hypedigitaly-fresh"):
        assert load_config(name, configs_dir=CONFIGS_DIR).branding.enabled is False


# ------------------------------------------------- FR-339 / FR-350: what the shipped DNA may say
#
# Two AUTHORING contracts on the file above, both new in v2.5.0/D59, both enforced here and
# deliberately nowhere else. FR-339 says so in as many words — "enforced by a test guard; a
# registry-load error is NOT added (FR-295 shape untouched)" — and the reason is the same for
# both: these are rules about the registry WE ship, not about the one an operator may author.
# A `validate` warning would fire on every third-party registry that ever wrote the word "badge",
# and an FR-295 error would refuse that operator's run at exit 2 over our house style.

#: FR-339's regex, spelled exactly as the PRD spells it. Every one of the six words names a device
#: that gets DRAWN, and every one of them is GATED somewhere else in the prompt: the wordmark on
#: the TEXT block (FR-292), the counter on `{{counter_rule}}` (FR-338), the signature on the
#: `brand_slot` zone. Named in the three DNA fields below it is UNGATED — those are reproduced
#: byte-identically into `{{style_dna}}` on every slide of every deck no matter what the TEXT
#: block quotes (FR-189/M9), so a `typography` line describing "a small page-number chip top-right"
#: orders nine chips onto a nine-slide deck that quoted no counter at all. That is the M9 defect
#: this rule exists to prevent, and it is invisible from any single slide's prompt.
_GATED_DEVICE = re.compile(r"\b(chip|badge|counter|page number|signature|lockup)\b", re.IGNORECASE)

#: The three fields FR-339 governs, and only those three. `image_treatment` and `palette` carry
#: exactly the same unconditional weight but describe SURFACES and COLOUR rather than what gets
#: lettered, and a rule that swept every DNA field would forbid a palette line from saying "a chip
#: of teal". The three listed are the ones that say what type is set and where it sits — which is
#: the only place a device can be ordered into existence by accident.
_UNGATED_DNA = ("typography", "text_placement", "visual_pacing")

#: FR-350's retired crop band. Frames render 1:1 (`generate/plan.py`), so a style still reserving
#: "the bottom 12% (4:5 crop)" is holding an eighth of every slide clear for a frame shape this
#: pipeline stopped producing — dead space the render model reads as a compositional instruction.
#: Both spellings are one pattern because they always shipped as one phrase.
_CROP_BAND = re.compile(r"4:5|bottom\s+12\s*%", re.IGNORECASE)


def _dna_hits(pattern: re.Pattern[str], style: MetaStyle, fields: tuple[str, ...]) -> list[str]:
    """Every match of `pattern` in `style`'s `fields`, named so the failure message IS the fix.

    One hit reads `icon-ledger-carousel.typography: 'chip' in …a small counter chip top-right…`:
    the style, the field, the offending word and enough of the sentence around it to edit without
    opening the file. A bare `assert not hits` over a registry of twenty-six styles would say only
    that something, somewhere, said "badge".

    A test-module helper rather than a `hypesocials.styles` function on purpose — see the section
    comment above. Nothing in production may grow an opinion about these words.
    """
    found: list[str] = []
    for field_name in fields:
        text = str(getattr(style, field_name) or "")
        for match in pattern.finditer(text):
            excerpt = " ".join(text[max(0, match.start() - 60):match.end() + 60].split())
            found.append(f"{style.key}.{field_name}: {match.group(0)!r} in …{excerpt}…")
    return found


def test_fr339_no_shipped_style_names_a_gated_device_in_its_unconditional_dna() -> None:
    """D59's registry scrub, held in place (FR-339).

    The bug this closes is one no single prompt shows you. A style's `typography`,
    `text_placement` and `visual_pacing` become `{{style_dna}}`, which FR-189 requires to be
    IDENTICAL on every slide of a deck — so a device described there is described on all of them,
    unconditionally, whether or not this deck quoted anything for it. The gated channels are the
    opposite by construction: `{{counter_rule}}` is empty on an uncounted deck (FR-338), the
    `brand_slot` zone is omitted from `{{layout_zones}}` on an unbranded creative (FR-292), and
    the TEXT block is the only source of renderable words at all. Two descriptions of one device,
    one conditional and one not, is how a byte-identical instruction still produces a drifting
    deck — the model reconciles them per slide and reconciles them differently.

    Every hit is reported, not just the first: a scrub half-done reads exactly like a scrub done.
    """
    hits = [hit for style in _shipped().styles
            for hit in _dna_hits(_GATED_DEVICE, style, _UNGATED_DNA)]

    assert hits == [], (
        "FR-339: a gated device is described in prose that renders on every slide. Move the "
        "spec into the zone whose role gates it — `counter_slot` for a counter, `brand_slot` "
        "for a signature or lockup — and delete it from the DNA field:\n  " + "\n  ".join(hits))


def test_fr339_every_counter_slot_zone_states_its_counter_inside_the_two_hundred_char_bar() -> None:
    """The other half of FR-339: the spec moved, and it has to stay small where it landed.

    A `counter_slot` zone line is rendered whole into `{{counter_rule}}` by `prompts_engine`, and
    that slot is UNCUTTABLE — it is in no truncation set and it is not the style trio, so every
    character it carries is a character the last-resort trio trim has to find somewhere else
    (`tests/test_prompt_fit.py` measures exactly that trade). 200 is the PRD's number and the
    shipped worst is `editorial-voxel-carousel` at 192 — with D61's own tightest,
    `contrast-verdict-deck`, right behind it at 190 — so this is a real bar and not a formality.

    The ROSTER is pinned rather than the count, because the failure that matters is a zone
    silently DISAPPEARING: a style that loses its `counter_slot` does not break, it quietly falls
    through to FR-338 arm (d) — the 86-character house-default line — and renders its counter in
    a place its own layout never described. FIFTEEN styles declare one since D61 — the eight that
    always did plus all seven of D61's carousel-derived entries, which were authored from decks
    whose source chrome numbered every slide and so state their own counter zone rather than
    inheriting the house default; the other eleven are still meant to be on the house default.
    """
    registry = _shipped()
    zoned = {style.key: zone for style in registry.styles for zone in style.layout_zones
             if zone.role == "counter_slot"}

    assert sorted(zoned) == ["aurora-white-deck", "big-number-editorial", "build-log-mono",
                             "circuit-atlas-dark", "contrast-verdict-deck",
                             "editorial-voxel-carousel", "icon-ledger-carousel",
                             "letterpress-print-carousel", "letterpress-print-carousel-teal",
                             "mono-cutout-editorial", "neon-glass-dark",
                             "paper-editorial-carousel", "photo-poster-statement",
                             "social-quote-card", "terminal-mockup-deck"], \
        "a `counter_slot` zone appeared or vanished — a vanished one falls through to " \
        f"FR-338's house-default line silently, and is not an error: {sorted(zoned)}"
    over = [f"{key}: {len(zone.text_treatment)} chars" for key, zone in sorted(zoned.items())
            if len(zone.text_treatment) > 200]
    assert over == [], (
        "FR-339: a `counter_slot` zone's `text_treatment` is over the 200-character bar, and "
        "`{{counter_rule}}` is uncuttable — every character here is taken off the style trio "
        f"instead: {', '.join(over)}")


def test_fr339_the_guard_catches_a_chip_planted_in_a_styles_typography() -> None:
    """The arm that stops the guard above from passing because it matches nothing.

    A regex guard over bytes that are already clean is indistinguishable from a regex that is
    silently broken — a stray escape, a lost `re.IGNORECASE`, a field name typo'd in
    `_UNGATED_DNA` — and the day someone re-authors a style is the day it would have mattered.
    So the predicate is fired at a style built to be caught, through `dataclasses.replace` on a
    clean fixture so the ONLY difference between passing and failing is the planted sentence.

    The second half is the scope, asserted as an absence: the same words in `image_treatment` are
    NOT a hit. That is deliberate (see `_UNGATED_DNA`) and it is the kind of decision that gets
    "fixed" by a future reader widening the tuple, which would forbid a palette line from
    describing a chip of colour.
    """
    clean = _style("planted")
    assert _dna_hits(_GATED_DEVICE, clean, _UNGATED_DNA) == [], "the fixture must start clean"

    planted = dataclasses.replace(
        clean, typography="Grotesk caps, tight tracking; a chip top-left states the page number.")
    hits = _dna_hits(_GATED_DEVICE, planted, _UNGATED_DNA)

    assert len(hits) == 2, hits
    assert all(hit.startswith("planted.typography: ") for hit in hits), \
        f"a hit must name the style AND the field it came from: {hits}"
    assert "'chip'" in hits[0] and "'page number'" in hits[1], \
        f"…and the offending word itself, or the message is not a fix: {hits}"
    assert "chip top-left states the page number" in hits[0], "the sentence rides along"
    # Scope, pinned as the absence it is: the same prose in a surface field is legal.
    assert _dna_hits(_GATED_DEVICE, dataclasses.replace(
        clean, image_treatment="Matte card with a chip of teal at the corner."),
        _UNGATED_DNA) == [], "FR-339 governs three fields; widening the tuple is a decision"


def test_fr350_no_shipped_style_reserves_a_band_for_a_crop_this_pipeline_stopped_making() -> None:
    """FR-350's pre-check, done at the registry rather than at the frame (D59, ahead of Session K).

    Seven styles used to end their `text_placement` with "bottom 12% clear (4:5 crop)". The
    pipeline renders 1:1 (`generate/plan.py`), so that sentence reserved an eighth of every slide
    for a crop nobody takes — and it did it in a DNA field, which means on every slide of every
    deck (FR-189). The replacement is "all text inside the central 80% of the 1:1 frame", which is
    the same protection stated in the frame we actually produce.

    The raw file is read as BYTES as well as through the parsed styles, and neither check is
    redundant: `4:5` in a `per_format_guidance` block, an `exclusions` line or a comment reaches a
    render prompt or a future reader just as well as one in `text_placement` does, and the parsed
    scan would never see it.
    """
    raw = (REPO / "prompts" / "styles.yaml").read_text(encoding="utf-8")
    hits = [hit for style in _shipped().styles
            for hit in _dna_hits(_CROP_BAND, style, ("text_placement",))]

    assert "4:5" not in raw, \
        "FR-350: `prompts/styles.yaml` still names the 4:5 crop somewhere — frames render 1:1"
    assert hits == [], (
        "FR-350: a style still reserves the retired crop band. Replace it with the 1:1 wording "
        '("all text inside the central 80% of the 1:1 frame"):\n  ' + "\n  ".join(hits))


def test_fr350_the_guard_catches_a_planted_bottom_twelve_percent_band() -> None:
    """The FR-350 half of the same planted-defect discipline, and for the same reason.

    Both spellings are planted in one sentence because that is how they always shipped — the band
    and the crop it was reserved for were written as one phrase, and a guard that caught only the
    ratio would pass a style that said "bottom 12% clear" and nothing more.
    """
    clean = _style("planted", text_placement="All text inside the central 80% of the 1:1 frame.")
    assert _dna_hits(_CROP_BAND, clean, ("text_placement",)) == [], "the fixture must start clean"

    planted = dataclasses.replace(
        clean, text_placement="Headline in the upper third; bottom 12% clear (4:5 crop).")
    hits = _dna_hits(_CROP_BAND, planted, ("text_placement",))

    assert len(hits) == 2, f"the band and the ratio are two hits, not one: {hits}"
    assert "'bottom 12%'" in hits[0] and "'4:5'" in hits[1], hits
    assert all(hit.startswith("planted.text_placement: ") for hit in hits), hits


# ---- D60 -------------------------------------------------------------------------------------
# The COLOUR and TYPE contracts (FR-347/348/349) and the FR-350 house spine.
#
# D59 closed the question "which channel may describe a device"; D60 closes the three questions
# under it — how many accent HUES a style may carry and how much frame they may take (FR-347),
# how many type FAMILIES it may name (FR-348), and whether any DNA field may still hand the
# render model a CHOICE (FR-349). The first is an FR-295 error since the shipped nineteen were
# re-authored clean; the other two are warnings over prose and always will be.
#
# The split below is the same one the FR-339 section above makes and for the same reason: what
# the VALIDATOR does is tested through `styles.validate` against synthetic styles, and what the
# SHIPPED FILE says is tested by guards that live in this module and never in `hypesocials/`.
# A house rule about which corner our counter sits in is not a property of the registry format,
# and a third-party override registry that puts its page number elsewhere is not defective.


def _validated(subject: MetaStyle, *, brand: str = "hypedigitaly") -> tuple[list[str], list[str]]:
    """`validate` over a registry of `subject` plus two clean fillers, as `(errors, warnings)`.

    The fillers are not decoration: `_MIN_USABLE_STYLES` is 3, so a one-style registry earns the
    thin-pool warning on every call and every `warnings == []` assertion below would be measuring
    that instead of the defect under test. Two clean siblings put the pool at three and take the
    thin-pool line off the board, and they carry no palette and no type prose of their own, so
    they can never contribute a finding.
    """
    registry = _registry(subject, _style("filler-one"), _style("filler-two"))
    return styles.validate(registry, _config(brand=brand))


# ------------------------------------------------------------- FR-347: the palette contract


def test_fr347_accent_hexes_in_two_hue_families_are_an_error_naming_both_and_their_angles(
) -> None:
    """The defect FR-347 was written for: a deck wearing two accents reads as two brands.

    Both lines here are otherwise perfect — each states its own `under 1/8` bound — so the ONLY
    thing wrong is that a teal at 177° and an orange at 15° are 162° apart, and a hue family is
    30° wide. That isolation is the point: the finding must be about the pair, not a side effect
    of a missing coverage clause on one of them.

    The message has to name both HEXES and both ANGLES because "your accents span two families"
    is a diagnosis an author cannot act on — `palette` lines are prose and a style may carry five
    of them, so the fix is only obvious once the line says which two colours it means.
    """
    subject = _style("subject", palette=[
        "ACCENT teal #0FCFC4: rules, marks and the payoff phrase, under 1/8 of frame",
        "CONTRAST orange #E8501E: the kicker and the drawn arrow, under 1/8 of frame"])

    errors, warnings = _validated(subject)

    assert len(errors) == 1, errors
    assert "span more than one hue family" in errors[0]
    assert "#0FCFC4 at 177°" in errors[0] and "#E8501E at 15°" in errors[0]
    assert "(FR-347)" in errors[0] and "style 'subject'" in errors[0]
    assert "prompts/styles.yaml" in errors[0], "the registry ORIGIN rides every finding (FR-184)"
    assert warnings == [], f"a hue-family error is not also a warning: {warnings}"


def test_fr347_an_accent_line_with_no_coverage_bound_is_an_error_naming_that_line() -> None:
    """"Sparingly" is not a number, and an accent the model is not held to spreads over the frame.

    One accent, one hue, nothing else wrong — the line simply never says how much of the frame it
    may take. The finding quotes the LINE rather than the style, because that is the string the
    author has to go and edit, and a style may carry several accent-candidate lines.
    """
    subject = _style("subject", palette=[
        "GROUND cream #F6F0E4: flat, edge to edge",
        "ACCENT teal #0FCFC4: rules, marks and the payoff phrase"])

    errors, warnings = _validated(subject)

    assert len(errors) == 1, errors
    assert "states no coverage bound" in errors[0]
    assert '"ACCENT teal #0FCFC4: rules, marks and the payoff phrase"' in errors[0]
    assert "`under 1/8`" in errors[0], "the message carries the spelling of the fix"
    assert warnings == []


@pytest.mark.parametrize("clause", ["under 1/8", "under 8%", "max 1/8", "≤ 1/8", "at most 1/8"])
def test_fr347_every_authored_spelling_of_a_coverage_clause_satisfies_the_accent_line(
    clause: str,
) -> None:
    """Five spellings, one regex, no finding — because an author writes prose, not a schema.

    The vocabulary is fixed in `styles._COVERAGE` and repeated in `styles.yaml`'s authoring block,
    and this is the test that stops those two drifting apart: a spelling the block invites and the
    regex has never heard of would refuse a correctly authored registry at exit 2 (FR-295), which
    is the most expensive possible way to be pedantic about wording.

    `under 8%` is in the list on purpose — it is 0.08, comfortably under the ceiling, and it is
    the percentage branch of the regex, which divides by 100 where the others divide one integer
    by another.
    """
    subject = _style("subject", palette=[f"ACCENT teal #0FCFC4: rules and marks, {clause}"])

    errors, warnings = _validated(subject)

    assert errors == [], f"{clause!r} is a legal coverage clause: {errors}"
    assert warnings == []


@pytest.mark.parametrize(("clause", "share"), [("under 1/5", "20.0%"), ("under 1/6", "16.7%"),
                                               ("under 25%", "25.0%")])
def test_fr347_a_coverage_bound_over_one_eighth_is_the_ceiling_error_not_a_missing_clause(
    clause: str, share: str,
) -> None:
    """A bound that IS stated but is too generous is its own finding, and says so.

    The distinction matters to the author: "you wrote no bound" and "you wrote 1/5" need different
    edits, and a validator that collapsed them into one message would send someone to add a clause
    that is already on the line. The reported share is the PARSED number, not the author's words,
    so a `1/6` and a `16%` that mean the same thing report the same way.
    """
    subject = _style("subject",
                     palette=[f"ACCENT teal #0FCFC4: rules and marks, {clause} of frame"])

    errors, warnings = _validated(subject)

    assert len(errors) == 1, errors
    assert f"allows {share} of frame" in errors[0]
    assert "the ceiling is 1/8 (12.5%)" in errors[0]
    assert "states no coverage bound" not in errors[0], "a stated bound is not a missing one"
    assert warnings == []


def test_fr347_a_saturated_ground_cast_is_legal_until_it_shares_the_accents_hue_family() -> None:
    """Plan 4a rule 6, both halves: a photographic style's ground may be a COLOUR, and the accent
    it carries has to be a different one.

    Honey wood at #B07C4A is saturated (S 0.58) and is `ugc-tabletop-statement`'s real tabletop,
    chosen so this test cannot pass on a colour no style would ever use. Against a teal accent
    148° away it is exactly what the rule permits. Against a vermilion accent 16° away it is the
    defect: the accent has nothing to be seen against, and a viewer reads the frame as one warm
    wash rather than as a ground with something on it.

    The clean half runs FIRST and asserts zero findings, because the failing half proves nothing
    if a saturated ground turns out to be reported always.
    """
    ground = "GROUND honey wood #B07C4A: the table, the largest surface"
    contrasting = _style("subject", palette=[
        ground, "ACCENT glazed teal #0FCFC4: one ceramic object, under 1/8 of frame"])

    assert _validated(contrasting) == ([], []), "a warm cast under a cool accent is the rule"

    clashing = _style("subject", palette=[
        ground, "ACCENT vermilion #E2522B: the payoff phrase, under 1/8 of frame"])
    errors, warnings = _validated(clashing)

    assert len(errors) == 1, errors
    assert "the saturated ground #B07C4A at 29°" in errors[0]
    assert "does not contrast with its ground cast" in errors[0]
    assert warnings == []


def test_fr347_a_palette_with_no_saturated_accent_at_all_is_silently_legal() -> None:
    """Zero accents is a LOOK, not a defect — and this is the precondition Session L needs.

    `mono-cutout-editorial` arrives in Session L with a palette of exactly this shape: a near-white
    ground, a near-black text ink and one warm grey for support, and nothing in it that clears the
    S ≥ 0.45 saturation floor. If FR-347 had been written to DEMAND an accent, that style could not
    be authored at all — it would refuse every run of every config that enabled it (exit 2, $0),
    and the cure would be to invent a colour the design does not want.

    So the assertion is the ABSENCE of all four findings: no hue-family line (there is no family),
    no coverage line (there is nothing to bound), no ceiling line and no ground-clash line. Not one
    warning either — a monochrome palette is not even advised about.
    """
    subject = _style("subject", palette=[
        "GROUND paper #F5F5F5: flat, edge to edge, most of frame",
        "TEXT ink #1A1A1A: headline, paragraph, rules",
        "SUPPORT warm grey #9B9A96: captions, hairlines, the swipe cue"])

    errors, warnings = _validated(subject)

    assert errors == [], f"a monochrome palette states no accent to bound: {errors}"
    assert warnings == []
    # And the reason, pinned at the predicate rather than inferred from the silence above: not one
    # of those three hexes is a colour doing accent work, so no accent rule has anything to apply
    # to. A future saturation-floor change that made warm grey an "accent" fails HERE, with the
    # hex named, instead of surfacing as a mysterious refusal three tests further down.
    assert [value for value in ("F5F5F5", "1A1A1A", "9B9A96") if styles._saturated(value)] == []


@pytest.mark.parametrize(("line", "is_background"), [
    ("GROUND honey wood #B07C4A: the table", True),
    ("GROUNDS warm paper #B07C4A: bands, gutter, margins", True),
    ("GROUND + CAPTION BANDS warm paper #B07C4A: bands and margins", True),
    ("SURFACE top panel sepia #B07C4A: the upper panel's cast", True),
    ("DEPTH bronze #B07C4A: the recessed plane", True),
    ("SHADOW umber #B07C4A: cast shadow under the subject", True),
    ("FOCAL violet #B07C4A: the subject's jacket", False),
    ("PRACTICAL amber #B07C4A: the lamp in shot", False),
    ("ACCENT teal #B07C4A: rules and marks", False),
    ("warm ochre #B07C4A with no role token at all", False),
])
def test_fr347_a_lines_role_is_read_off_its_leading_token_and_decides_ground_from_accent(
    line: str, is_background: bool,
) -> None:
    """The vocabulary that decides whether a saturated hex is a CAST or an ACCENT.

    Every case carries the SAME hex, so nothing about the answer can come from the colour: the
    only variable is the word the line opens with. `GROUNDS` and `GROUND + CAPTION BANDS` are in
    the list because two shipped styles really open lines that way, and a background rule that
    only knew the singular would hold `meme-caricature-panels`' panel casts to the accent rules.

    The last four are the DEFAULT, and it is deliberately the strict one: `FOCAL`, `PRACTICAL`,
    `ACCENT` and a line with no capitalised opening at all are accent CANDIDATES. An author opts
    INTO the background vocabulary and never falls into it by writing prose, because a rule that
    let an unrecognised word mean "ground" would let one typo silence the whole contract.
    """
    assert styles._is_background_role(line) is is_background

    # …and the consequence, through the public door: an unbounded ACCENT line is a finding, an
    # unbounded GROUND line is not, on identical bytes but for the leading word.
    errors, _ = _validated(_style("subject", palette=[line]))
    assert (errors == []) is is_background, errors


def test_fr347_the_enforcement_switch_moves_the_same_findings_between_errors_and_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_PALETTE_CONTRACT_ENFORCED` is ONE line and changes ONE thing — which list holds the
    findings. Nothing about their content, count, order or wording moves with it.

    That is the whole design of the switch and why it earns a test of its own. It shipped `False`
    because the contract was written after the nineteen styles were, and flipping it early would
    have refused every run of every config on day one; it is `True` today because Session K
    re-authored all nineteen clean. Set back to `False` it must still be a working TRIAGE mode —
    an operator editing the registry sees the same lines at pre-flight and the run continues — and
    a triage mode that reported different things than the enforcing mode would be worthless.

    Two defects are planted at once so the ORDER survives the move as well: a finding list at
    pre-flight is read top to bottom.
    """
    subject = _style("subject", palette=[
        "ACCENT teal #0FCFC4: rules and marks, under 1/5 of frame",
        "CONTRAST orange #E8501E: the kicker, under 1/8 of frame"])

    assert styles._PALETTE_CONTRACT_ENFORCED is True, "D60 flipped it; this test is not the flip"
    enforced_errors, enforced_warnings = _validated(subject)
    assert len(enforced_errors) == 2 and enforced_warnings == []

    monkeypatch.setattr(styles, "_PALETTE_CONTRACT_ENFORCED", False)
    warned_errors, warned_warnings = _validated(subject)

    assert warned_errors == [], "in warning mode a palette defect cannot refuse a run"
    assert warned_warnings == enforced_errors, \
        "the same lines, in the same order, in the same words — only the list changed"


def test_fr347_the_whole_shipped_registry_is_clean_under_both_brands_with_the_switch_on() -> None:
    """All TWENTY-SIX, not just the seventeen the configs enable — with FR-347 enforcing.

    The D61 test above validates the seventeen-key SELECTION and is the barrier that catches a
    config drifting from the registry. This one is the other axis: `validate` walks every entry
    in the file for findings whether or not the run can assign it, so a style enabled by nobody
    today and re-enabled next month is held to the same contract now, while the person who
    authored it is still in the room.

    Both brands are checked because `brand_ok` filters the POOL and not the walk — but a
    brand-filtered pool is what decides whether the empty-pool and per-format arms fire, and those
    would bury a palette finding under a refusal about something else entirely.

    `enabled=[]` means "every style this brand can wear", which is the widest pool the selector
    can produce and therefore the strictest reading of "the registry is clean".
    """
    registry = _shipped()
    assert len(registry.styles) == SHIPPED_STYLES, "the walk has to cover all of them"
    assert styles._PALETTE_CONTRACT_ENFORCED is True, \
        "with the switch off this test would pass on a registry full of palette defects"

    for brand in ("hypedigitaly", "hypelead"):
        config = _config(brand=brand, formats={"image": 0, "carousel": 6, "reel": 0}, enabled=[])

        errors, warnings = styles.validate(registry, config)

        assert errors == [], f"brand {brand!r}: the shipped registry would refuse a run: {errors}"
        assert warnings == [], f"brand {brand!r}: {warnings}"
        # Said again by NAME, so a future reader can see which three contracts this covers even
        # after some unrelated finding starts appearing in one of these lists.
        for finding in [*errors, *warnings]:
            assert not any(tag in finding for tag in ("FR-347", "FR-348", "FR-349")), finding


# ------------------------------------------------- FR-349: the variant scan over every DNA field

#: The planted CHOICE every FR-349 case below uses. One string, so a test that fails names a
#: clause a reader can find instantly, and so the parametrised field sweep is measuring the FIELD
#: and never the sentence. It is a real one: `letterpress-print-carousel`'s counter zone said
#: exactly this until Session K resolved it to tracked caps of the body family.
_PLANTED_CHOICE = "small mono or tracked caps"


def test_fr349_a_choice_planted_in_typography_warns_and_names_the_field_and_the_clause() -> None:
    """M9's heuristic, off `render_prompt` and onto the prose the model executes just as literally.

    `style_dna` ships `typography` byte-identically to every slide of a deck (FR-189), so "small
    mono or tracked caps" is not one decision left open — it is one decision left open NINE TIMES,
    resolved independently on each slide, which is precisely the drift M9 was written to stop. The
    field is the only thing that changed; the consequence did not.

    The message names the FIELD and quotes the CLAUSE because a style carries seven scanned fields
    and any of them may be a paragraph: "this style leaves a choice open" is not a fix.
    """
    subject = _style("subject",
                     typography=f"Body grotesque at 4% cap height; {_PLANTED_CHOICE}.")

    errors, warnings = _validated(subject)

    assert errors == [], "FR-349 is a warning; a style that names two type sizes still renders"
    assert len(warnings) == 1, warnings
    assert "`typography` leaves a choice open" in warnings[0]
    assert f'"{_PLANTED_CHOICE}."' in warnings[0], "the clause is quoted, not summarised"
    assert "(FR-349)" in warnings[0] and "style 'subject'" in warnings[0]


def test_fr349_a_negated_clause_is_a_ban_list_and_a_ban_list_is_never_a_choice() -> None:
    """The rule that makes the scan usable at all: "no serif, script or display face" is EXACTLY
    what a well-written type rule looks like, and it is built out of the same word the scan hunts.

    Without the negation carve-out FR-349 would warn about correct authoring on nearly every style
    in the file, an author would learn to ignore its output within a week, and the one real leak it
    exists to catch would print in the middle of eleven false ones. The negation is judged per
    CLAUSE, so a `no` three sentences earlier cannot launder a genuine choice — the second half
    below is that half of the rule, with both spellings in one style.
    """
    banning = _style("subject", typography="One grotesque family; no serif, script or display face.")

    assert _validated(banning) == ([], []), "a ban list is authoring, not a defect"

    # The `no` belongs to its own clause and does not reach across the `; ` boundary.
    mixed = _style("subject", typography=(
        "No serif, script or display face; the counter sets in " + _PLANTED_CHOICE + "."))
    _, warnings = _validated(mixed)

    assert len(warnings) == 1, f"the ban clause passes and the choice clause warns: {warnings}"
    assert _PLANTED_CHOICE in warnings[0] and "no serif" not in warnings[0].lower()


@pytest.mark.parametrize("field", ["exclusions", "layout_zones"])
def test_fr349_the_two_fields_deliberately_left_out_of_the_scan_stay_out_of_it(field: str) -> None:
    """Two absences, both decisions, both the kind a future reader "fixes" by widening a tuple.

    `exclusions` is out because it is a BAN LIST by construction and scanning it would report
    every style in the file for being written correctly — the negation rule already covers the
    prose that reads like a ban, and a list whose whole purpose is banning does not need to be
    read one clause at a time to be understood.

    `layout_zones` is out because a zone is GATED by role (FR-339): a `counter_slot` zone reaches
    the render prompt only on a deck that quoted a counter, so a choice inside it is not the
    unconditional every-slide instruction the DNA fields are. It is also the field FR-339 asked
    authors to move their device specs INTO, and a scan that punished them there would undo D59.
    """
    over = ({"exclusions": [_PLANTED_CHOICE]} if field == "exclusions" else
            {"layout_zones": [LayoutZone("top-right corner", "counter", _PLANTED_CHOICE,
                                         role="counter_slot")]})
    subject = _style("subject", **over)

    errors, warnings = _validated(subject)

    assert errors == [] and warnings == [], f"FR-349 does not read `{field}`: {warnings}"


def test_fr349_leaves_the_render_prompt_rule_exactly_where_m9_left_it() -> None:
    """`render_prompt` keeps its OWN rule, its own message and its own single report.

    The two scans deliberately do not overlap. M9's rule is older, it is stated at the field level
    rather than the clause level, and its message names the markers it found rather than quoting a
    clause — so a style whose `render_prompt` says "a teal or cobalt ground" must still produce the
    one M9 line it always produced, and must NOT also produce an FR-349 line about the same
    sentence. One defect, one line: two reports of one sentence train an operator to skim.

    The second half proves the absence is scoped rather than accidental — the same style's
    `text_placement` gets its own FR-349 line, so the scan is running and is simply not reading
    `render_prompt`.
    """
    subject = _style("subject", render_prompt="A flat card on a teal or cobalt ground.")

    _, warnings = _validated(subject)

    assert len(warnings) == 1, warnings
    assert "`render_prompt` still offers a choice (or)" in warnings[0], "M9's wording, untouched"
    assert warnings[0].endswith("(M9)"), "the M9 rule is not re-badged as FR-349"

    both = _style("subject", render_prompt="A flat card on a teal or cobalt ground.",
                  text_placement=f"Headline upper third; {_PLANTED_CHOICE}.")
    _, pair = _validated(both)

    assert len(pair) == 2 and pair[0].endswith("(M9)") and pair[1].endswith("(FR-349)")


@pytest.mark.parametrize(("field", "over", "reported_as"), [
    ("palette", {"palette": [f"ACCENT teal #0FCFC4: rules {_PLANTED_CHOICE}, under 1/8 of frame"]},
     "palette"),
    ("typography", {"typography": f"Body grotesque; {_PLANTED_CHOICE}."}, "typography"),
    ("text_placement", {"text_placement": f"Headline upper third; {_PLANTED_CHOICE}."},
     "text_placement"),
    ("image_treatment", {"image_treatment": f"Flat vector, hard shadow; {_PLANTED_CHOICE}."},
     "image_treatment"),
    ("visual_pacing", {"visual_pacing": f"One idea per frame; {_PLANTED_CHOICE}."},
     "visual_pacing"),
    ("list_mode.layout", {"list_mode": ListMode(reflow_over_chars=110, max_rows=4,
                                                layout=f"Rows flush left; {_PLANTED_CHOICE}.")},
     "list_mode.layout"),
    ("per_format_guidance", {"per_format_guidance": {
        "carousel_cover": f"Cover: one full-bleed statement; {_PLANTED_CHOICE}."}},
     "per_format_guidance.carousel_cover"),
])
def test_fr349_every_scanned_field_reports_the_same_planted_choice_under_its_own_name(
    field: str, over: dict, reported_as: str,
) -> None:
    """All seven scanned fields, one planted clause, seven distinct field names in the output.

    The sweep is here because the field LIST is the requirement — FR-349 names exactly these seven
    and deliberately excludes two others (the test above), so a field silently dropped from
    `_dna_prose` is a hole nothing else in the suite would notice. Every one of them reaches the
    render model: `palette`, `typography`, `text_placement`, `image_treatment` and `visual_pacing`
    are `style_dna` itself, `list_mode.layout` fires into `{{list_treatment}}` on a list slide, and
    `per_format_guidance` is what separates a cover from a body slide.

    `per_format_guidance` reports under its own KEY (`per_format_guidance.carousel_cover`) rather
    than under the block name, because the block holds several entries and the author needs to know
    which one to edit — that specificity is asserted here and nowhere else.
    """
    subject = _style("subject", **over)

    errors, warnings = _validated(subject)

    assert errors == [], errors
    assert len(warnings) == 1, f"{field}: {warnings}"
    assert f"`{reported_as}` leaves a choice open" in warnings[0]
    assert _PLANTED_CHOICE in warnings[0]


# ---------------------------------------------------------------- FR-348: the type contract


def test_fr348_three_families_named_in_typography_warn_in_the_rules_own_words() -> None:
    """One display family plus one body family is what a reader tells apart at a glance and what a
    render model holds across a deck. A third set of shapes is a third voice competing for the
    same slide, and the styles that shipped with four looked like four different decks stapled
    together — which is the measurement FR-348 was adopted from.

    Serif, grotesque and script is the shape `editorial-voxel-carousel` really shipped with before
    Session K resolved its script annotation into a drawn mark. The warning has to carry the RULE
    TEXT and not just a count, because "3 type families" is a fact and "one display family + one
    body family; a third family only as a mono utility" is the decision the author has to make.
    """
    subject = _style("subject", typography=(
        "A Didone serif headline, a grotesque body, one script annotation per slide."))

    errors, warnings = _validated(subject)

    assert errors == [], "FR-348 is a heuristic over prose and never refuses a run"
    assert len(warnings) == 1, warnings
    assert "name 3 type families (sans, script, serif)" in warnings[0]
    assert "one display family + one body family; a third family only as a mono utility" \
        in warnings[0]
    assert warnings[0].endswith("(FR-348)")


def test_fr348_a_third_family_is_tolerated_when_it_is_the_mono_utility() -> None:
    """The carve-out, on bytes identical to the test above but for the third family's class.

    A code or terminal identity needs a monospace utility for the thing it is imitating — a build
    log, a shell prompt, a chip of version string — and that utility is not a third VOICE: nobody
    reads a mono label as a second display face. The three shipped styles that use it are named in
    the PRD and pinned by a guard further down; the validator itself cannot know whether a style IS
    a terminal, and a heuristic that guessed would fail the honest styles and pass the dishonest.
    """
    subject = _style("subject", typography=(
        "A Didone serif headline, a grotesque body, a mono chip label at the foot."))

    assert _validated(subject) == ([], []), "serif + sans + mono is the tolerated three"

    # Four is four, carve-out or not: the exception is one family wide and is not a licence.
    four = _style("subject", typography=(
        "A Didone serif headline, a grotesque body, a mono chip label, one script annotation."))
    _, warnings = _validated(four)

    assert len(warnings) == 1 and "name 4 type families" in warnings[0], warnings


def test_fr348_a_family_named_only_in_a_layout_zone_counts_toward_the_same_two() -> None:
    """A style specifies type in two places, so both are counted.

    `typography` is the obvious one; a zone's `text_treatment` is the one that hides a family, and
    it hides it in the field FR-339 asked authors to MOVE their device specs into. A counter zone
    reading "small grey mono uppercase" is a real third family arriving through the door D59 just
    opened, and a count that only read `typography` would report the registry as clean while the
    slides carried three faces.

    The third family here is `script` rather than `mono` on purpose: mono is the carve-out (test
    above), so a mono zone would prove nothing about whether zones are read at all. Note this
    corrects the K contract's own example — "grotesque in typography, serif + mono in a zone"
    is three classes WITH mono, which FR-348 tolerates by design.
    """
    subject = _style("subject",
                     typography="A Didone serif headline over a grotesque body.",
                     layout_zones=[LayoutZone("lower margin", "annotation",
                                              "a script hand-lettered aside, one line")])

    errors, warnings = _validated(subject)

    assert errors == []
    assert len(warnings) == 1, warnings
    assert "`typography` and the layout zones name 3 type families (sans, script, serif)" \
        in warnings[0]


def test_fr348_a_family_a_style_forbids_is_not_a_family_it_names() -> None:
    """The negation rule again, on the count instead of on the choice — same clause splitter, same
    reason. A style that says "never a serif, a script or a woodtype face" has named three classes
    and USES none of them; counting them would make the clearest possible authoring the loudest
    possible warning, and the author's only cure would be to delete the rule.
    """
    subject = _style("subject", typography=(
        "One grotesque family at three weights; never a serif, a script or a woodtype face."))

    assert _validated(subject) == ([], []), "a banned family is not a named one"

    # The same three words without the `never` are the ordinary three-family warning, so the
    # difference above is the negation and not the sentence.
    named = _style("subject", typography=(
        "One grotesque family at three weights, a serif pull-quote, a script signature."))
    _, warnings = _validated(named)

    assert len(warnings) == 1 and "name 3 type families" in warnings[0], warnings


def test_fr348_the_only_shipped_styles_naming_the_mono_class_are_the_four_that_may() -> None:
    """The guard the validator cannot be: WHICH shipped styles get the mono carve-out.

    FR-348's exception exists for a code/terminal identity, and the PRD names three of them —
    `build-log-mono`, `circuit-atlas-dark`, `terminal-mockup-deck`. The shipped file has a FOURTH,
    and it is not a drift: `hypelead-brand-card` is the HypeLead house card and its brand type
    stack is literally Geist + Geist Mono, so the word `mono` on its kicker line names the brand's
    own typeface rather than an extra voice borrowed for effect. It also does not spend the
    carve-out — Geist and Geist Mono are `sans` + `mono`, two classes, so that style would pass
    FR-348 with the exception deleted. The three terminal identities are the ones actually leaning
    on it, and all four are pinned here so a fifth style quietly reaching for a mono utility shows
    up as a named failure rather than as one more warning nobody reads.

    **D61 left this roster alone and that is asserted, not assumed.** Seven styles joined the
    registry and NONE of them names a mono class: each was authored on exactly two families
    (a display face and a body face), so the carve-out is still spent by the three code/terminal
    identities it was written for. Seven new styles is precisely the moment a carve-out gets
    borrowed by something that is not a terminal, so the roster is re-asserted whole below and
    the seven are named again in their own check.

    Counted through the module's OWN predicates (`_clauses`, `_NEGATION`, `_TYPE_FAMILIES`) rather
    than by grepping for the word: "no mono anywhere" is a ban, not a use, and a grep would report
    every style that forbids one.
    """
    naming_mono = []
    for style in _shipped().styles:
        prose = [style.typography, *(zone.text_treatment for zone in style.layout_zones)]
        for text in prose:
            clauses = [clause for clause in styles._clauses(text)
                       if not styles._NEGATION.search(clause)]
            if any(styles._TYPE_FAMILIES["mono"].search(clause) for clause in clauses):
                naming_mono.append(style.key)
                break

    assert naming_mono == ["hypelead-brand-card", "build-log-mono", "circuit-atlas-dark",
                           "terminal-mockup-deck"], \
        ("FR-348's mono carve-out is for a code/terminal identity plus HypeLead's own Geist Mono "
         f"brand stack. A style outside that set reached for a monospace utility: {naming_mono}")
    assert not set(naming_mono) & set(_D61_STYLES), \
        ("D61 added seven styles on two families each and none of them is a terminal identity, "
         f"so none may name a mono utility: {sorted(set(naming_mono) & set(_D61_STYLES))}")


# ------------------------------------------- FR-350: the house spine, guarded over shipped bytes
#
# Five items shared by EVERY carousel-affine style and nothing more (30 §FR-350). Items 1 and 5
# are FR-347 and FR-348 and are enforced by `validate` above; items 2, 3 and 4 are house prose
# with no validator behind them at all, on purpose — "our counter lives top-right" is a decision
# about OUR deck, not a property of the registry format, and an override registry that puts its
# page number in the other corner is not defective. So they are guarded HERE, exactly like the
# FR-339 scrub, and every guard below has a planted-failure twin or is paired with a predicate
# assertion, because a regex over bytes that are already clean is indistinguishable from a regex
# that is silently broken.

#: J's exact safe-area wording (FR-350 item 4). One string, quoted once, so the guard and any
#: future re-authoring cannot drift into two spellings of the same rule — and so a style that
#: paraphrases it ("keep text well inside the frame") fails rather than passing on a synonym.
_SAFE_AREA_PHRASE = "inside the central 80% of the 1:1 frame"

#: The devices FR-350 item 3 places, as opposed to FR-339's wider list of devices it GATES. A
#: signature and a lockup are not here: `hypelead-brand-card` really does sit its logo lockup
#: top-left and that is its brand's own layout, not the counter corner this item is about.
_CORNER_DEVICE = re.compile(r"\b(chip|badge|counter|page number)\b", re.IGNORECASE)


def _counter_zones(style: MetaStyle) -> list[LayoutZone]:
    """This style's `counter_slot` zones — the gated channel FR-338 renders a counter through."""
    return [zone for zone in style.layout_zones if zone.role == "counter_slot"]


def _left_corner_devices(style: MetaStyle) -> list[str]:
    """Every CLAUSE of this style's authored text that puts a counter-ish device at the top-LEFT.

    Read off a YAML dump of the whole style rather than off a field list, because item 3 says
    "no prose ANYWHERE": a `per_format_guidance` note, an `exclusions` line and a zone's
    `text_treatment` all reach a render prompt or a future author just as well as `text_placement`
    does, and a field-by-field scan would have to be kept in step with the schema forever.

    Scoped to the CLAUSE — the dump split on `;`, `,`, `.` and newlines — and that scope is the
    whole design. Two shipped styles legitimately say "top-left" in a sentence that also names a
    device somewhere else in it: `build-log-mono`'s `render_prompt` reads "a mono micro-label
    top-left …, a position chip top-right", which is the rule being FOLLOWED. A window-based
    proximity scan would report it, an author would delete a correct sentence to silence the
    guard, and the counter would end up somewhere worse.
    """
    dump = yaml.safe_dump(dataclasses.asdict(style), allow_unicode=True, sort_keys=False)
    return [" ".join(clause.split()) for clause in re.split(r"[;,.\n]", dump)
            if "top-left" in clause.lower() and _CORNER_DEVICE.search(clause)]


def _ground_value(style: MetaStyle) -> float | None:
    """The HSV *value* of the first `GROUND` palette line's first hex, or `None` if it has neither.

    `colorsys` rather than `styles._hsv` on purpose: item 2 is a claim about a colour, and a guard
    that measured it with the module's own helper would agree with that helper even if the helper
    were wrong about what "value" means.
    """
    for line in style.palette:
        if not styles._palette_role(line).startswith("GROUND"):
            continue
        found = styles._HEX.findall(line)
        if not found:
            continue
        red, green, blue = (int(found[0][index:index + 2], 16) / 255 for index in (0, 2, 4))
        return colorsys.rgb_to_hsv(red, green, blue)[2]
    return None


def test_fr350_every_shipped_style_is_carousel_affine_which_is_what_puts_it_under_the_spine(
) -> None:
    """The precondition the four guards below all rest on, asserted rather than assumed.

    FR-350 binds "every carousel-affine style and nothing more", and it spells out what that means
    in the same breath: `format_affinity` contains `carousel`. Today that is all twenty-six, so
    the guards can each walk the whole registry — but that is a FACT about the shipped file in
    August 2026, not a property of the spine, and the day an image-only or reel-only style is
    authored, the guards below start holding it to rules it was never under. This test is where that shows
    up: it fails with the new style named, and the fix is to filter the guards rather than to
    widen the spine.

    Read off `format_affinity` and NOT through `styles.fmt_affine`, which is a stricter question
    and a different one. `fmt_affine` additionally drops the four `carousel_role: slides_only`
    entries (`meme-caricature-panels`, `ugc-tabletop-statement` and their teal twins), because
    under anchor chaining a style that cannot set slide 1 is never ASSIGNED to a deck at all.
    Those four still render carousel SLIDES when a deck is built from them by hand, they still
    ship `carousel` in their affinity, and their counters, safe areas and grounds are read by a
    viewer swiping the same batch — so the spine binds them, and using the assignment predicate
    here would quietly exempt four of the twenty-six from the house rules.
    """
    registry = _shipped()

    not_affine = [style.key for style in registry.styles
                  if "carousel" not in style.format_affinity]

    assert not_affine == [], (
        "FR-350 binds the carousel-affine styles only. These are not, so the four guards below "
        f"must start filtering instead of walking the whole registry: {not_affine}")
    # The narrower predicate, pinned as the difference it is: four of the twenty-six are inert on
    # a carousel PLAN (D57) and are still under the spine. A future reader swapping one for the
    # other above would silently drop them from every guard in this section.
    inert = [style.key for style in registry.styles
             if not styles.fmt_affine(style, "carousel")]
    assert inert == ["meme-caricature-panels", "ugc-tabletop-statement",
                     "meme-caricature-panels-teal", "ugc-tabletop-statement-teal"], inert


def test_fr350_every_shipped_counter_slot_zone_places_its_counter_top_right() -> None:
    """Item 3, first half: one corner, registry-wide, so a reader learns where to look ONCE.

    A counter that moves corner by style is the defect — a viewer swiping a batch of our decks
    reads the position as meaning something, and it means nothing. Three styles sat theirs
    top-left before Session K (`editorial-voxel-carousel`, `letterpress-print-carousel` and its
    teal twin); this is what stops the fourth.

    D61's seven were the first real test of that: five of the seven reference decks number their
    slides top-LEFT, and every one of the seven was authored top-right anyway, which is the whole
    point of a house spine — the source is read for its shape, never copied for its chrome.

    The zone `position` is the string that becomes `{{counter_rule}}`, so it is the only place the
    corner is actually stated to a render model — a style whose `text_placement` says "top-right"
    and whose zone says "top-left" renders top-left.
    """
    zoned = {style.key: zone for style in _shipped().styles for zone in _counter_zones(style)}
    assert len(zoned) == 15, f"the FR-339 roster is fifteen styles; this guard sees {len(zoned)}"

    misplaced = [f"{key}: {zone.position!r}" for key, zone in sorted(zoned.items())
                 if "top-right" not in zone.position.lower()]

    assert misplaced == [], (
        "FR-350 item 3: the counter is top-right on every deck we ship, so a reader learns the "
        f"position once. Move the zone's `position`:\n  " + "\n  ".join(misplaced))


def test_fr350_no_shipped_style_puts_a_chip_badge_or_counter_at_the_top_left() -> None:
    """Item 3, second half: the corner is also not contradicted anywhere ELSE in the style.

    The zone guard above reads the gated channel. This one reads everything — `render_prompt`,
    the DNA fields, `per_format_guidance`, `exclusions`, every zone — because a style that says
    top-right in its zone and "the page chip sits top-left" in its cover guidance has told the
    model both, and FR-189 ships both to every slide. That is the same two-descriptions-of-one-
    device defect FR-339 exists to prevent, aimed at the position rather than at the existence.

    Reported per style with the clause quoted, so the failure IS the edit.
    """
    hits = [f"{style.key}: {clause}" for style in _shipped().styles
            for clause in _left_corner_devices(style)]

    assert hits == [], (
        "FR-350 item 3: a counter, chip or badge is placed top-left in a style's prose. The "
        f"counter corner is top-right registry-wide:\n  " + "\n  ".join(hits))


def test_fr350_every_shipped_style_states_the_safe_area_in_the_frame_we_actually_render() -> None:
    """Item 4: one sentence, in `text_placement`, in J's exact words, on all twenty-six.

    This replaced "bottom 12% clear (4:5 crop)", which reserved an eighth of every slide for a crop
    this pipeline stopped taking (the FR-350 pre-check further up asserts that band is gone). The
    replacement has to be in `text_placement` specifically: that field is `style_dna`, so the rule
    reaches every slide of every deck unconditionally, which is the only way a safe area works.

    The phrase is pinned VERBATIM rather than by keyword because paraphrase is how a rule stops
    being a rule — "keep text well inside the frame" is advice, "inside the central 80% of the 1:1
    frame" is a measurement a render model can execute.
    """
    missing = [style.key for style in _shipped().styles
               if _SAFE_AREA_PHRASE not in style.text_placement]

    assert missing == [], (
        f'FR-350 item 4: `text_placement` must carry "{_SAFE_AREA_PHRASE}" word for word — a '
        f"paraphrase is advice, not a measurement: {missing}")


def test_fr350_every_graphic_shipped_style_grounds_itself_at_a_value_extreme() -> None:
    """Item 2: a flat graphic look puts its type on near-white or near-black, never on a mid-tone.

    A ground at V 0.5 is where legibility goes to die — the accent stops reading as an accent, the
    text needs an outline it should not need, and the craft critic reports a contrast defect nobody
    authored. Both extremes are allowed because both work; the middle is what is banned.

    PHOTOGRAPHIC styles are exempt and the exemption is the whole of plan 4a rule 6: a photographed
    room HAS a cast, and demanding a value extreme of it would mean lighting every scene to the same
    two exposures. The eight exempt today are `photoreal-ambient-caption`, `anime-noir-statement`,
    `ugc-tabletop-statement`, `quiet-luxury-night-photoreal`, the three teal twins
    (`quiet-luxury-night-photoreal-teal`, `photoreal-ambient-caption-teal`,
    `ugc-tabletop-statement-teal`) and D61's `photo-poster-statement`, which is the only one of
    the seven newcomers built on a full-bleed photograph — its asphalt-black street ground would
    pass the extreme anyway at V 0.08, and it is exempt because it is a photograph, not because it
    needed the exemption. `ugc-tabletop-statement`'s honey-wood table at V 0.69 is
    exactly the mid-tone ground this rule would otherwise forbid, and it is the right ground for a
    photograph of a table.

    The exempt count is asserted too: if a style flips `motion_profile` to `photographic` to escape
    this guard, the roster below changes and says so.
    """
    registry = _shipped()
    exempt = [style.key for style in registry.styles if style.motion_profile == "photographic"]
    assert len(exempt) == 8, f"the photographic roster moved: {exempt}"
    assert "photo-poster-statement" in exempt, \
        "D61's one photographic newcomer flipped to `graphic` — the roster arithmetic is stale"

    mid_toned = [f"{style.key}: V {_ground_value(style):.2f}" for style in registry.styles
                 if style.motion_profile == "graphic"
                 and not (_ground_value(style) is not None
                          and (_ground_value(style) >= 0.85 or _ground_value(style) <= 0.20))]

    assert mid_toned == [], (
        "FR-350 item 2: a `motion_profile: graphic` style grounds at V >= 0.85 or V <= 0.20. A "
        f"mid-tone ground is where an accent stops reading and type needs an outline:\n  "
        + "\n  ".join(mid_toned))


def test_fr350_icon_ledger_retired_its_footer_strip_for_a_hairline_that_draws_nothing_when_empty(
) -> None:
    """Wave 4a rule 1, on the one style it was written about.

    `icon-ledger-carousel` used to close every slide with a solid teal banner strip across the
    foot. Two things were wrong with it and the second is the expensive one: the strip was a slab
    of the accent hue, which broke FR-347's 1/8 bound on its own, and it was drawn UNCONDITIONALLY
    — a deck that quoted no signature still got the band, so the style reserved a strip of every
    frame for a string that was not there. The replacement is a hairline rule plus the quoted
    signature, and nothing at all when nothing is quoted, which is FR-340's empty-zone rule stated
    inside the zone that owns it.

    Both spellings are checked over the WHOLE style, because the strip was described in five
    places (`render_prompt`, `text_placement`, `visual_pacing`, `per_format_guidance`,
    `exclusions`) and a scrub that left one of them would put the band back on every slide.
    """
    style = styles.style_for(_shipped(), "icon-ledger-carousel")
    dump = yaml.safe_dump(dataclasses.asdict(style), allow_unicode=True).lower()
    brand_zones = [zone for zone in style.layout_zones if zone.role == "brand_slot"]

    assert "strip" not in dump and "banner" not in dump, \
        "the retired footer band is described somewhere in this style again (wave 4a rule 1)"
    assert len(brand_zones) == 1, brand_zones
    assert "hairline" in brand_zones[0].text_treatment, \
        f"the signature sits on a hairline rule now, not a band: {brand_zones[0].text_treatment}"
    assert "nothing at all is drawn here when nothing is quoted" in brand_zones[0].text_treatment, \
        "FR-340: an empty zone is LEFT OUT of the frame, never filled with a default graphic"


@pytest.mark.parametrize("key", ["letterpress-print-carousel", "letterpress-print-carousel-teal"])
def test_fr350_the_letterpress_pair_retired_its_terracotta_body_ground(key: str) -> None:
    """The owed SESSION-I ruling, settled by wave 4a and pinned here (rules 1 and 2).

    Both letterpress styles used to run a cream COVER and a terracotta BODY — two grounds in one
    style, the second of them (#B5573C) a saturated warm mid-tone. That is three separate spine
    breaks at once: a second ground, a ground the accent cannot contrast against, and a mid-tone
    for a `motion_profile: graphic` look. Settled as cream everywhere, cover and body alike, with
    the ink carrying the difference — vermilion on the plain style, deep teal on the twin.

    Exactly ONE `GROUND` line is the structural half of that and is what a re-authoring would undo
    first: a style that grows a second ground line has grown a second look, whatever the hexes say.
    The retired hex is checked over the whole style AND over the raw file, because a `# DELIBERATE`
    comment reintroducing it as an option would not survive parsing into any field.
    """
    style = styles.style_for(_shipped(), key)
    raw = (REPO / "prompts" / "styles.yaml").read_text(encoding="utf-8").upper()
    grounds = [line for line in style.palette if styles._palette_role(line).startswith("GROUND")]

    assert "B5573C" not in yaml.safe_dump(dataclasses.asdict(style)).upper(), \
        f"{key}: the retired terracotta body ground is back in the style"
    assert "B5573C" not in raw, "…or is back in the file as a comment offering it as an option"
    assert len(grounds) == 1, f"{key}: one ground, cover and body alike — got {grounds}"
    assert "cover and body alike" in grounds[0], \
        f"{key}: the ground line says out loud that it is the same on both — {grounds[0]}"


def test_fr350_the_top_right_guards_catch_a_counter_planted_in_the_wrong_corner() -> None:
    """The arm that stops both item-3 guards from passing because they match nothing.

    Same discipline as the FR-339 planted twin above and for the same reason: a guard over bytes
    that are already clean is indistinguishable from a regex with a lost `re.IGNORECASE` or a
    field name typo'd out of the scan, and the day someone re-authors a style is the day it would
    have mattered. Both halves of item 3 are fired at a style built to be caught, through
    `dataclasses.replace` on a clean fixture, so the ONLY difference between passing and failing is
    the planted sentence.

    The last block is the SCOPE, asserted as an absence: a device named top-left in one clause and
    a corner named in ANOTHER is not a hit. That is `build-log-mono`'s real `render_prompt` shape,
    and it is the decision a future reader is most likely to "fix" by widening the scan to a
    character window — which would report the one style in the file that states the rule correctly.
    """
    clean = _style("planted")
    assert _counter_zones(clean) == [] and _left_corner_devices(clean) == [], \
        "the fixture must start clean, or the plant below proves nothing"

    zoned = dataclasses.replace(clean, layout_zones=[
        LayoutZone("top-left corner, on the first baseline", "slide counter",
                   "small tracked caps", role="counter_slot")])
    assert [zone for zone in _counter_zones(zoned)
            if "top-right" not in zone.position.lower()], "the zone guard missed a top-left counter"

    prosed = dataclasses.replace(
        clean, per_format_guidance={"carousel_slide": "A page-number chip top-left on every body "
                                                      "slide, above the headline."})
    hits = _left_corner_devices(prosed)
    assert len(hits) == 1, hits
    assert "top-left" in hits[0] and "chip" in hits[0], hits

    # Scope: the device and the corner in two different clauses is the rule being FOLLOWED.
    following = dataclasses.replace(clean, render_prompt=(
        "A mono micro-label top-left closing on a cursor block, a position chip top-right."))
    assert _left_corner_devices(following) == [], \
        "a label top-left beside a chip top-right is correct authoring, not a hit"


def test_fr350_the_safe_area_guard_catches_a_style_that_paraphrases_the_sentence() -> None:
    """The same planted-defect discipline for item 4, aimed at the failure that actually happens.

    Nobody deletes a safe-area rule; they REWRITE it, and a paraphrase is what a rewrite produces.
    So the plant is not an empty `text_placement` — it is a style that says the right thing in the
    wrong words, which a keyword guard ("80%", "safe area") would wave straight through and which
    a render model cannot execute.
    """
    clean = _style("planted", text_placement=f"Margins 7%; all text {_SAFE_AREA_PHRASE}.")
    assert _SAFE_AREA_PHRASE in clean.text_placement, "the fixture must start clean"

    paraphrased = dataclasses.replace(
        clean, text_placement="Margins 7%; keep all text well inside the frame, 80% of it.")
    dropped = dataclasses.replace(clean, text_placement="Margins 7%; headline in the upper third.")

    for style in (paraphrased, dropped):
        assert _SAFE_AREA_PHRASE not in style.text_placement, \
            f"the guard would pass this style: {style.text_placement}"


# ---- D61 -------------------------------------------------------------------------------------
# SUPPLY: the registry goes 19 -> 26 and the brand selection 12 -> 17 (FR-341).
#
# D59 and D60 were both about what a style may SAY. D61 is about how many styles there are, and
# it was forced by a measurement rather than by a contract: the 2026-08-20 acceptance run put SIX
# of nine decks on `icon-ledger-carousel`, because it was the only enabled style whose
# `match_profile` claimed numbered decks at all. The matcher did its job perfectly. The pool was
# the defect — a matcher can only spread work across archetypes that somebody CLAIMED.
#
# So the seven new styles are not seven more looks. They are seven archetype CLAIMS, authored
# from the operator's own reference carousels, and the tests below are shaped by that: the file
# tail (what shipped), the archetype map (that no two of them claim the same source shape), the
# off-spine pair (that two of them deliberately stay out of the brand selection) and the two
# narrowed incumbents (that `icon-ledger-carousel` and `circuit-atlas-dark` gave those claims up
# in writing rather than merely having them taken away).
#
# Every one of them reads the SHIPPED registry, like the D59 and D60 sections above and for the
# same reason: these are facts about the file we ship, not properties of the registry format.


#: The nine archetypes of FR-341's handoff table (plan §3), each mapped to the ONE style that may
#: claim it, and each named by a keyword that appears in that style's own `match_profile`.
#:
#: The keywords are deliberately narrow, and every one of them was chosen by reading the shipped
#: profiles rather than by paraphrasing the plan. "round-up" would have been the obvious word for
#: `icon-ledger-carousel` and it is unusable: `paper-editorial-carousel` legitimately claims
#: "curated round-ups written as prose", which is a DIFFERENT archetype wearing the same noun.
#: "manifesto" is unusable for the same reason (`letterpress-print-carousel-teal` claims the
#: printed poster manifesto, `photo-poster-statement` the one-line kind). What the map holds is
#: therefore the phrase that names the SHAPE OF THE SOURCE, never the shape of the output.
_ARCHETYPE_CLAIMS = {
    "many rows on one frame": "icon-ledger-carousel",
    "countdown": "big-number-editorial",
    "build log": "build-log-mono",
    "x versus y": "contrast-verdict-deck",
    "over a photograph": "photo-poster-statement",
    "agency manifesto": "mono-cutout-editorial",
    "feature tour": "neon-glass-dark",
    "editorial explainer": "paper-editorial-carousel",
    "business explainer": "aurora-white-deck",
}

#: The verbs a profile uses when it POINTS somewhere instead of claiming. Naming another style's
#: key counts too and is checked separately — today every shipped handoff does both, and the verbs
#: are here for the day one is written without a key ("that goes to the diagram style").
_HANDOFF_VERBS = ("goes to", "hands", "→")


def _profile_clauses(text: str) -> list[str]:
    """`text` split into clauses on `;`, `.` and the em dash — never on the comma.

    The comma is excluded on purpose and that exclusion is the whole design of the archetype test
    below. A profile's disclaim reads "wrong for numbered steps, tool round-ups and screenshot
    sources": splitting on commas would cut "tool round-ups" away from the "wrong for" that
    qualifies it and turn a disclaim into what reads like a claim. The em dash IS included,
    because these profiles use it as a full stop that keeps its breath.
    """
    return [" ".join(part.split()) for part in re.split(r"[;.—]", text) if part.strip()]


def _normalised(text: str) -> str:
    """Lower-cased, back-ticks dropped, hyphens and slashes flattened to spaces.

    ONE normaliser for the keyword, the clause AND the style keys, so that `big-number-editorial`
    in a handoff sentence and "big number editorial" in prose are the same string to this file.
    Without it, "Hands a many-rows-on-one-frame round-up to …" would not match the keyword
    "many rows on one frame" that the owning style states in plain words.
    """
    return re.sub(r"\s+", " ", text.lower().replace("`", "").replace("-", " ").replace("/", " "))


def _claiming_styles(registry: StyleRegistry, keyword: str, scanned: list[str]) -> list[str]:
    """The `scanned` styles that CLAIM `keyword` — i.e. name it outside a handoff clause.

    A clause is a handoff when it carries one of `_HANDOFF_VERBS` or names another style's key.
    Everything else that mentions the archetype is a claim, and two claims on one archetype is
    the supply defect D61 exists to fix: the matcher then has to choose between them on prose
    alone, and it will choose the same one every time.

    Returned in `scanned` order and at most once per style, so a failure message reads as a
    roster rather than as a count.
    """
    keys = [style.key for style in registry.styles]
    claimants: list[str] = []
    for key in scanned:
        profile = _normalised(styles.style_for(registry, key).match_profile)
        for clause in _profile_clauses(profile):
            if _normalised(keyword) not in clause:
                continue
            partners = [other for other in keys if other != key and _normalised(other) in clause]
            if not partners and not any(verb in clause for verb in _HANDOFF_VERBS):
                claimants.append(key)
                break
    return claimants


def test_d61_the_seven_carousel_derived_styles_ship_and_are_the_file_tail() -> None:
    """What D61 added, asserted as the TAIL of the registry rather than as bare membership.

    Position is load-bearing here in a way membership is not. `usable_styles` answers in FILE
    order and FR-291's rotation scans that order, so where a style sits in `styles.yaml` decides
    which creative of a plan wears it. Appending is the only edit that leaves every existing
    assignment where it was; inserting a style in the middle silently re-styles every run of every
    config, and no other test in this file would notice. The seven are pinned in their authored
    order for that reason.

    The rest of the assertions are the born-compliant checklist from plan §3, checked once at the
    door so the D59 and D60 guards above never have to special-case a newcomer:

    * **No `-teal` twin.** D57's mechanism was to duplicate a style and re-role its accent. D61's
      five spine styles were authored on the house teal from their first line instead, so there is
      no original to drift away from and the registry does not grow a second pair of near-copies.
    * **Carousel-affine and cover-capable.** Every one was read off a real deck, so every one has
      to be able to set slide 1 — under anchor chaining the anchor decides the look of every slide
      after it, and a `slides_only` marker here would make the style unassignable to the very
      format it was authored for.
    * **`brand_slot: false`, `brand_affinity: []`.** None of the seven is a house card. A
      `brand_affinity` would hide the style from the other brand for no reason, and a `brand_slot`
      would put it under `branding.enabled`, which is false in all three shipped configs.
    * **A `list_mode` and a `counter_slot` zone.** Both are what a DECK style owes: the list mode
      is FR-304b's reflow trigger for a panel that arrives with rows in it, and the counter zone
      is what keeps the style off FR-338's 86-character house-default line, which would otherwise
      place a counter the style's own layout never described.
    """
    registry = _shipped()
    keys = [style.key for style in registry.styles]

    assert keys[-7:] == _D61_STYLES, (
        "D61's seven must be the FILE TAIL, in this order — appending is the only edit that does "
        f"not re-seed FR-291's rotation for every existing config: {keys[-7:]}")
    assert not set(_D61_STYLES) & set(keys[:-7]), "…and each of them appears exactly once"

    for key in _D61_STYLES:
        style = styles.style_for(registry, key)
        assert not key.endswith("-teal"), \
            f"{key}: D61 authored its teal in place; it ships no D57-style twins"
        assert "carousel" in style.format_affinity, \
            f"{key}: authored from a deck and affine to everything but one"
        assert styles.fmt_affine(style, "carousel") is True, \
            f"{key}: a `slides_only` marker would stop a deck-derived style from anchoring a deck"
        assert style.brand_slot is False, f"{key}: none of the seven is a house card"
        assert style.brand_affinity == [], f"{key}: brand-locking it hides it from the other brand"
        assert style.list_mode is not None, f"{key}: a deck style owes FR-304b a reflow trigger"

        zones = [zone for zone in style.layout_zones if zone.role == "counter_slot"]
        assert len(zones) == 1, f"{key}: exactly one `counter_slot` zone, got {len(zones)}"
        assert "top-right" in zones[0].position.lower(), (
            f"{key}: FR-350 item 3 — the counter corner is top-right registry-wide, not wherever "
            f"the reference deck happened to put it: {zones[0].position!r}")


def test_d61_match_profiles_are_mutually_exclusive_by_archetype() -> None:
    """The actual fix for the six-of-nine concentration, stated as a property of the PROSE.

    Adding styles does not spread a matcher out on its own. `icon-ledger-carousel` took six of
    nine decks while eleven other styles were enabled, because it was the only profile that
    CLAIMED a numbered deck — the other eleven described looks the matcher had no reason to reach
    for. So the property that matters is not "there are more styles now", it is "each archetype in
    FR-341's handoff table is claimed by exactly one of them".

    The hard part is that every one of these profiles also NAMES its neighbours: `big-number-
    editorial` says "Hands a many-rows-on-one-frame round-up to `icon-ledger-carousel`", which
    mentions `icon-ledger-carousel`'s archetype in as many words. A test that searched a profile
    as one string would call that a collision, and would be telling the authors to delete the
    handoffs — the single most useful sentence in each profile. So the search is per CLAUSE, and a
    clause carrying a handoff verb or naming another style's key is a POINTER, never a claim.

    The scanned set is the seventeen enabled keys plus the two off-spine owners. Enabled is the
    set that matters — a style nobody enabled cannot starve a pool it is not in — and the two
    owners join it because they own an archetype without being selectable, which is exactly the
    state that would let a future config enable one and collide in silence.

    The last block is the planted arm and it is not optional: a mutual-exclusivity test over prose
    that is already exclusive passes identically to one whose normaliser has quietly broken.
    """
    registry = _shipped()
    scanned = [*ENABLED_SEVENTEEN, *_D61_OFF_SPINE]

    assert len(set(_ARCHETYPE_CLAIMS.values())) == len(_ARCHETYPE_CLAIMS), \
        "two archetypes routed to one style is a map that cannot spread anything"

    for keyword, owner in _ARCHETYPE_CLAIMS.items():
        profile = _normalised(styles.style_for(registry, owner).match_profile)
        assert _normalised(keyword) in profile, \
            f"{owner} no longer claims its own archetype {keyword!r}: {profile}"
        claimants = _claiming_styles(registry, keyword, scanned)
        assert claimants == [owner], (
            f"FR-341: the {keyword!r} archetype must be claimed by exactly ONE style, or the "
            "matcher chooses between them on prose alone and chooses the same one every run. "
            f"Claimed by: {claimants}")

    # The planted arm: a second style claiming a mapped archetype has to be REPORTED. Asserted
    # through the same predicate, on a registry whose only difference is the planted sentence.
    poached = dataclasses.replace(styles.style_for(registry, "social-quote-card"),
                                  match_profile="Suits any source built as a feature tour.")
    planted = dataclasses.replace(
        registry, styles=[poached if style.key == "social-quote-card" else style
                          for style in registry.styles])
    assert _claiming_styles(planted, "feature tour", scanned) == ["social-quote-card",
                                                                 "neon-glass-dark"], \
        "the predicate cannot see a second claim — the normaliser or the clause split is broken"

    # …and the scope, pinned as the absence it is: the same words behind a handoff are not a claim.
    pointed = dataclasses.replace(poached, match_profile=(
        "Suits quote-led sources. A feature tour goes to `neon-glass-dark`."))
    rerouted = dataclasses.replace(
        planted, styles=[pointed if style.key == "social-quote-card" else style
                         for style in planted.styles])
    assert _claiming_styles(rerouted, "feature tour", scanned) == ["neon-glass-dark"], \
        "a handoff clause must never read as a claim, or the authors are told to delete them"


def test_d61_the_two_off_spine_styles_are_in_the_registry_but_not_in_the_brand_selection() -> None:
    """D-G, applied to SUPPLY rather than to colour: a style is excluded, never re-painted.

    `paper-editorial-carousel` and `mono-cutout-editorial` are the two of D61's seven that do not
    carry the house teal, and the standing decision says what happens to them — colour is curated
    by CHOOSING styles, never by editing one. So they ship whole, they validate clean, they are
    reachable from `default.yaml` with an empty selector, and they are simply absent from the
    three brand configs' `styles.enabled`. Re-roling their accents to teal was the other answer
    and it is the one D-G forbids: it would produce two more near-copies of styles that are only
    interesting BECAUSE they are not teal.

    Their palettes are read through `styles._HEX` / `styles._saturated` — the module's own FR-347
    predicates — rather than by eyeballing the hexes on the line, because "has no accent" is a
    claim about SATURATION and a grep would have to re-implement the threshold to check it.
    `mono-cutout-editorial` is the zero-accent case FR-347 explicitly allows (pure monochrome is
    legal and the validator was written so that it stays legal); `paper-editorial-carousel` is a
    one-accent style whose one accent is its source's native vermilion.
    """
    registry = _shipped()
    default = load_config("default", configs_dir=CONFIGS_DIR)
    reachable = {style.key for style in styles.usable_styles(
        registry, default.branding.brand, default.styles.enabled,
        branding_enabled=default.branding.enabled)}

    for key in _D61_OFF_SPINE:
        assert styles.style_for(registry, key) is not None, f"{key} left the registry"
        assert key in reachable, (
            f"{key}: an empty selector means 'every style this brand can wear', and this one "
            "cannot be worn at all")
        assert key not in ENABLED_SEVENTEEN, \
            f"{key}: off the teal spine, so it stays out of the brand selection (D-G)"
    assert styles.validate(registry, default) == ([], []), \
        "`default.yaml` has to load both of them clean — they are ordinary registry entries"

    accents = {key: [hex6 for line in styles.style_for(registry, key).palette
                     for hex6 in styles._HEX.findall(line) if styles._saturated(hex6)]
               for key in _D61_OFF_SPINE}

    assert accents["mono-cutout-editorial"] == [], (
        "FR-347 allows zero accents and `mono-cutout-editorial` is the shipped proof that it "
        f"does — a saturated hex here gives it one hue nobody chose: {accents}")
    assert accents["paper-editorial-carousel"] == ["E8481F"], (
        "the vermilion is this style's whole reason to exist off the spine, and it is ONE hue: "
        f"{accents['paper-editorial-carousel']}")


def test_d61_icon_ledger_and_circuit_atlas_hand_off_their_narrowed_archetypes() -> None:
    """The other half of the supply fix, and the half that is easy to forget.

    Seven new claims are worth nothing while the incumbent still claims the same ground. Before
    D61, `icon-ledger-carousel`'s profile read as "any deck with rows in it", which is why it took
    six of nine; `circuit-atlas-dark`'s "card pair" clause reached every before/after source and
    every product hero object. Both were NARROWED — and narrowing a profile by deletion would have
    been the wrong edit, because a matcher reading the narrowed line still has to send that source
    somewhere. So both of them now name their successors in writing.

    Asserted by successor KEY rather than by the wording around it. The sentence will be re-worded
    the first time somebody re-reads it; what has to survive is that the pointer exists at all and
    that it points at the style D61 authored to receive the work.

    The last assertion is the floor under the narrowing: a profile that gave away everything would
    pass the two above and be unmatchable. Both incumbents must still CLAIM their own archetype.
    """
    registry = _shipped()
    handoffs = {"icon-ledger-carousel": ("big-number-editorial", "contrast-verdict-deck"),
                "circuit-atlas-dark": ("contrast-verdict-deck", "neon-glass-dark")}

    for key, successors in handoffs.items():
        profile = styles.style_for(registry, key).match_profile
        for successor in successors:
            assert successor in profile, (
                f"{key} was narrowed but never says where the work it gave up goes. A matcher "
                f"reading it still has to place that source: name `{successor}`.\n  {profile}")

    assert _claiming_styles(registry, "many rows on one frame", ["icon-ledger-carousel"]) == \
        ["icon-ledger-carousel"], "icon-ledger gave away the one archetype it was narrowed TO"
    assert _claiming_styles(registry, "benchmark", ["circuit-atlas-dark"]) == \
        ["circuit-atlas-dark"], "circuit-atlas gave away the benchmark decks it was narrowed to"
