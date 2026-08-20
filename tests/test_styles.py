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

    It has to be synthetic: all nineteen shipped styles author a real `match_profile` (pinned
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

#: NINETEEN since v2.4.0. D55 brought the registry to nine; D56 added `build-log-mono` plus the
#: four census-driven archetype styles (`icon-ledger-carousel`, `circuit-atlas-dark`,
#: `social-quote-card`, `terminal-mockup-deck`); D57 added the five `-teal` spine variants. The
#: originals were left untouched by D57 on purpose — colour is curated by CHOOSING styles, never by
#: editing one (standing decision D-G), which is why a variant is a new key and not an edit.
SHIPPED_STYLES = 19
#: D57's selection, pinned as data: the twelve keys the three brand configs enable. The list is
#: here rather than read from a config so a config edit that silently drops a key fails a test with
#: a name instead of quietly narrowing the rotation. Twelve enabled styles are only coherent
#: BECAUSE those configs also pin `assignment: matched` (D56 decision 5) — the two settings are one
#: decision in one file, and the config test below asserts them together for that reason.
ENABLED_TWELVE = ["anime-noir-statement", "platform-showcase-card",
                  "letterpress-print-carousel-teal", "meme-caricature-panels-teal",
                  "quiet-luxury-night-photoreal-teal", "photoreal-ambient-caption-teal",
                  "ugc-tabletop-statement-teal", "build-log-mono", "icon-ledger-carousel",
                  "circuit-atlas-dark", "social-quote-card", "terminal-mockup-deck"]


def _shipped() -> StyleRegistry:
    """The real registry, loaded exactly as a run loads it (FR-174's `prompts_dir` seam)."""
    return styles.load_registry([REPO / "prompts"])


def test_d56_the_shipped_registry_parses_and_holds_nineteen_uniquely_keyed_styles() -> None:
    """There is NO fallback (FR-295): a registry that will not parse is exit 2 and $0, not a
    built-in default set. So "it parses" is a real assertion about the shipped bytes, and the
    count is what catches a style added or removed without anyone updating the configs that
    enable it.

    The three membership assertions are one per decision that put a style in this file — D55's
    photoreal entry, one of D56's archetype four, one of D57's spine variants — because a count
    alone passes for a style deleted and a different one added in the same edit, which is exactly
    the shape a registry re-organisation takes.
    """
    registry = _shipped()
    keys = [style.key for style in registry.styles]

    assert len(registry.styles) == SHIPPED_STYLES
    assert len(set(keys)) == SHIPPED_STYLES, f"duplicate style key in the registry: {keys}"
    assert "quiet-luxury-night-photoreal" in keys, "D55's style"
    assert "circuit-atlas-dark" in keys, "one of D56's four census-driven archetype styles"
    assert "ugc-tabletop-statement-teal" in keys, "one of D57's five teal-spine variants"
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


def test_d57_the_twelve_key_selection_validates_clean_under_the_shipped_brand() -> None:
    """The registry and the configs have to land in the SAME change: a `styles.enabled` key the
    registry lacks is a pre-flight exit 2 on EVERY run of that config (FR-314/FR-295). This is that
    barrier, asserted against the real registry and the real twelve-key list — no errors, and no
    warnings either.

    "No warnings" is the stronger half and covers more since D56: it means no style in the SHIPPED
    file is over the 120-word ceiling, leaks an unresolved either/or, declares a dead `list_mode`
    **or ships without a `match_profile`**. `validate` walks the whole registry for warnings, not
    just the selection, so this one assertion covers all nineteen entries.
    """
    registry = _shipped()
    config = _config(brand="hypelead", formats={"image": 0, "carousel": 6, "reel": 0},
                     enabled=ENABLED_TWELVE)

    errors, warnings = styles.validate(registry, config)

    assert errors == [], f"the shipped selection would refuse a run: {errors}"
    assert warnings == [], f"and it earns not even the thin-pool warning: {warnings}"
    assert [style.key for style in styles.usable_styles(registry, "hypelead", ENABLED_TWELVE)] == [
        "anime-noir-statement", "platform-showcase-card", "build-log-mono",
        "icon-ledger-carousel", "circuit-atlas-dark", "social-quote-card", "terminal-mockup-deck",
        "letterpress-print-carousel-teal", "meme-caricature-panels-teal",
        "quiet-luxury-night-photoreal-teal", "photoreal-ambient-caption-teal",
        "ugc-tabletop-statement-teal"], "FILE order, never the order the config typed"


def test_d56_every_shipped_style_authors_its_own_match_profile() -> None:
    """The matcher reads ONE line per candidate, and this is where the shipped file is held to
    writing it (D56/FR-335).

    `match_profile_for` never blanks a candidate out — it derives a weaker line from the first
    sentence of `render_prompt` — so a missing profile does not break a run and is deliberately
    only a warning. What it breaks is the QUALITY of every match on that style: `render_prompt`
    says how a look works ("near-black ground, glowing teal circuit motifs") where a
    `match_profile` says what source material it suits, and a matcher handed the first has to guess
    the second. With a twelve-key pool that guess is most of the decision, which is why every one
    of the nineteen shipped entries authors the real line and why the derivation is exercised
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


def test_d57_the_three_shipped_brand_configs_enable_those_twelve_keys_and_pin_matched() -> None:
    """The configs and the registry are one decision in two files; this is where they are checked
    against each other. Read through `load_config` rather than by parsing YAML, so a key that
    loads to something different from what it looks like on disk is caught here.

    `assignment: matched` is asserted in the same loop and not in a test of its own, because it is
    not a separate setting: twelve enabled styles under plain rotation would put twelve unrelated
    looks through one batch (D56 risk 3). The selection is only coherent BECAUSE the matcher is
    choosing, so a config that widened the pool and left `assignment` on the engine default would
    be a regression this pairing is here to catch.
    """
    registry = _shipped()
    registry_keys = {style.key for style in registry.styles}

    for name in ("hypedigitaly", "hypedigitaly-cs", "hypedigitaly-fresh"):
        config = load_config(name, configs_dir=CONFIGS_DIR)
        assert config.styles.enabled == ENABLED_TWELVE, f"{name} drifted from D57's selection"
        assert config.styles.assignment == "matched", \
            f"{name} widened the pool to twelve without the matcher that makes it coherent (D56)"
        assert set(config.styles.enabled) <= registry_keys, \
            f"{name} enables a style the registry does not define — exit 2 on every run"
        assert styles.validate(registry, config)[0] == [], f"{name} would refuse at pre-flight"


def test_d57_the_two_slides_only_keys_are_enabled_but_INERT_on_a_carousel_plan() -> None:
    """The operator kept both `slides_only` variants in the twelve knowing neither can be assigned
    while the configs are all-carousel: they are there to activate the day image posts return, and
    keeping them costs nothing because `fmt_affine` drops them per format. Same ruling as D55, now
    covering two keys instead of one (`ugc-tabletop-statement-teal` inherits the marker from its
    original exactly as `meme-caricature-panels-teal` does).

    So the effective carousel rotation is TEN of the twelve, and this pins that the two it excludes
    are the right two — a `slides_only` key that silently became assignable would put a caricature
    panel or a tabletop shot on a deck's ANCHOR slide, and under anchor chaining slide 1 sets the
    look for every slide that follows it.
    """
    registry = _shipped()
    inert = ("meme-caricature-panels-teal", "ugc-tabletop-statement-teal")
    pool = {style.key for style in styles.usable_styles(registry, "hypelead", ENABLED_TWELVE)}
    entries = _entries(range(24), fmt="carousel")

    styles.assign_styles(entries, registry, "hypelead", enabled=ENABLED_TWELVE)

    for key in inert:
        assert key in pool, f"{key}: selected and brand-clean…"
        assert styles.fmt_affine(styles.style_for(registry, key), "carousel") is False, \
            f"{key}: …and still never affine to a deck"
        assert key not in _keys(entries), f"{key}: an inert key was assigned to a carousel"
    assert set(_keys(entries)) == set(ENABLED_TWELVE) - set(inert), \
        "and every one of the other ten really is reachable — an inert THIRD key would be a bug"


def test_d57_the_brand_card_is_absent_from_the_selection_and_would_be_dropped_anyway() -> None:
    """Two independent reasons, and the test asserts both because either alone would be a
    coincidence. `hypelead-brand-card` is not in the twelve keys; and `branding.enabled` is false in
    all three shipped configs, so `brand_ok` drops a `brand_slot` style regardless. Branded
    entries sign through the TEXT block on any style (FR-318/FR-292), which is why excluding the
    card costs the run no signature it would otherwise have carried."""
    registry = _shipped()

    assert "hypelead-brand-card" not in ENABLED_TWELVE
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
    opening the file. A bare `assert not hits` over a registry of nineteen styles would say only
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
    shipped worst is `editorial-voxel-carousel` at 192, so this is a real bar and not a formality.

    The ROSTER is pinned rather than the count, because the failure that matters is a zone
    silently DISAPPEARING: a style that loses its `counter_slot` does not break, it quietly falls
    through to FR-338 arm (d) — the 86-character house-default line — and renders its counter in
    a place its own layout never described. Eight styles declare one; the other eleven are meant
    to be on the house default.
    """
    registry = _shipped()
    zoned = {style.key: zone for style in registry.styles for zone in style.layout_zones
             if zone.role == "counter_slot"}

    assert sorted(zoned) == ["build-log-mono", "circuit-atlas-dark", "editorial-voxel-carousel",
                             "icon-ledger-carousel", "letterpress-print-carousel",
                             "letterpress-print-carousel-teal", "social-quote-card",
                             "terminal-mockup-deck"], \
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
    deck (FR-189). The replacement is "all text inside the central 80% of a 1:1 frame", which is
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
        '("all text inside the central 80% of a 1:1 frame"):\n  ' + "\n  ".join(hits))


def test_fr350_the_guard_catches_a_planted_bottom_twelve_percent_band() -> None:
    """The FR-350 half of the same planted-defect discipline, and for the same reason.

    Both spellings are planted in one sentence because that is how they always shipped — the band
    and the crop it was reserved for were written as one phrase, and a guard that caught only the
    ratio would pass a style that said "bottom 12% clear" and nothing more.
    """
    clean = _style("planted", text_placement="All text inside the central 80% of a 1:1 frame.")
    assert _dna_hits(_CROP_BAND, clean, ("text_placement",)) == [], "the fixture must start clean"

    planted = dataclasses.replace(
        clean, text_placement="Headline in the upper third; bottom 12% clear (4:5 crop).")
    hits = _dna_hits(_CROP_BAND, planted, ("text_placement",))

    assert len(hits) == 2, f"the band and the ratio are two hits, not one: {hits}"
    assert "'bottom 12%'" in hits[0] and "'4:5'" in hits[1], hits
    assert all(hit.startswith("planted.text_placement: ") for hit in hits), hits
