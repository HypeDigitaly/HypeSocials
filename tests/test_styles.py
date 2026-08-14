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

Everything here is offline and deterministic: no network, no API key, no `logs/`, no `output/`.
The only filesystem use is `tmp_path`. The API under test is pinned in
`plans/topic-first-pivot-contracts.md` item 5, which is this suite's source of truth — it was
written against the contract, in parallel with the module itself.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from hypesocials import styles
from hypesocials.config import BrandingConfig, Config, RunConfig, StylesConfig
from hypesocials.generate import refs as refs_module
from hypesocials.models import LayoutZone, MetaStyle, PlanEntry
from hypesocials.styles import StyleRegistry, StyleRegistryError

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- builders


def _style(key: str, **over) -> MetaStyle:
    """A style that validates CLEAN, so whatever a test asserts on is the defect it introduced.

    The default `render_prompt` is deliberately short and free of " or " / "either " / "Variant ",
    the three variant-leak spellings the registry warns about (§1.3/M9).
    """
    fields: dict[str, object] = {
        "render_prompt": "Flat graphic card, centred subject, hard shadow, wide margins.",
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


_MINIMAL = {"key": "minimal", "render_prompt": "Flat card.", "format_affinity": ["image"]}


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
