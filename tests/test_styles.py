"""`hypesocials.styles` — the meta-style registry, its rotation and its reference windows.

Post-pivot (v2.0.0) the look of a creative is no longer re-derived per trend by an LLM: it is
AUTHORED once in `prompts/styles.yaml` and ASSIGNED by a deterministic scan (FR-290/291). That
moves three failure modes out of the run and into pre-flight, and this suite is where each one is
pinned:

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
import os
from pathlib import Path

import pytest
import yaml

from hypesocials import styles
from hypesocials.config import BrandingConfig, Config, RunConfig
from hypesocials.models import LayoutZone, MetaStyle, PlanEntry
from hypesocials.styles import StyleRegistry, StyleRegistryError

REPO = Path(__file__).resolve().parents[1]
#: Real magic bytes, because `_usable()` validates the CONTENT, not the name (a renamed .txt
#: would fail the Kie upload and cost the job a reference for nothing).
PNG = b"\x89PNG\r\n\x1a\n"
JPEG = b"\xff\xd8\xff"


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


def _config(*, brand: str = "hypedigitaly", formats: dict[str, int] | None = None) -> Config:
    return Config(run=RunConfig(formats=formats or {"image": 4, "carousel": 2, "reel": 0}),
                  branding=BrandingConfig(brand=brand))


def _entry(order: int, fmt: str = "image") -> PlanEntry:
    return PlanEntry(order=order, asset_id=f"a{order:02d}", creative_format=fmt,  # type: ignore[arg-type]
                     platform="linkedin", language="en", aspect_ratio="1:1")


def _entries(orders, fmt: str = "image") -> list[PlanEntry]:
    return [_entry(order, fmt) for order in orders]


def _keys(entries) -> list[str]:
    return [entry.style_key for entry in entries]


def _ref(path: Path) -> str:
    """`reference_images` entries are REPO-ROOT-relative (§1.3), so a `tmp_path` fixture is
    expressed as the relative hop out of the repo and back — the same string a shipped registry
    holds, resolved by the same join."""
    try:
        return Path(os.path.relpath(path, REPO)).as_posix()
    except ValueError:  # pragma: no cover - different drive; an absolute path joins the same way
        return path.as_posix()


def _image(folder: Path, name: str, body: bytes = PNG) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(body + b"\x00" * 64)
    return path


def _names(paths) -> list[str]:
    """Compare windows by file name: `ROOT / "../../tmp/x.png"` and `C:/tmp/x.png` are the same
    file and different strings, so the path FORM must not decide whether a test passes."""
    return [Path(path).name for path in paths]


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


def test_a_missing_or_unreadable_reference_image_warns_and_never_refuses(tmp_path: Path) -> None:
    """The degrade is deliberate (§1.3): a style whose pictures went missing still has its
    `render_prompt`, so it renders text-only and is tagged `style_refs_missing`. Making this an
    error would let one moved file cost a whole run."""
    good = _image(tmp_path, "good.png")
    garbage = tmp_path / "garbage.png"
    garbage.write_bytes(b"this is not an image at all")

    clean = _registry(_style("a", reference_images=[_ref(good)]), _style("b"), _style("c"))
    assert styles.validate(clean, _config()) == ([], [])

    for broken in (_ref(garbage), "Inspiration/definitely-not-here.png"):
        errors, warnings = styles.validate(
            _registry(_style("thin", reference_images=[broken]), _style("b"), _style("c")),
            _config())
        assert not errors, "a missing picture is a degrade, never an exit 2"
        assert any("thin" in warning for warning in warnings)


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


# --------------------------------------------------------------------------- reference windows


def test_the_window_rotates_by_reuse_index_and_wraps_around_the_usable_list(
    tmp_path: Path,
) -> None:
    """A17's mechanism, re-homed onto the style: `hypelead-brand-card` ships five pictures, and
    without the turn every creative on that style would attach the same two forever."""
    pictures = [_image(tmp_path, f"ref{index}.png") for index in range(5)]
    style = _style("cards", reference_images=[_ref(path) for path in pictures])

    assert _names(styles.pick_reference_window(style, 0, 2)) == ["ref0.png", "ref1.png"]
    assert _names(styles.pick_reference_window(style, 1, 2)) == ["ref1.png", "ref2.png"]
    assert _names(styles.pick_reference_window(style, 4, 2)) == ["ref4.png", "ref0.png"]
    assert _names(styles.pick_reference_window(style, 6, 3)) == ["ref1.png", "ref2.png", "ref3.png"]
    assert all(Path(path).is_file() for path in styles.pick_reference_window(style, 3, 2))


def test_a_style_with_fewer_pictures_than_the_window_returns_them_whole(tmp_path: Path) -> None:
    """Degenerate and NOT a bug: `refs_per_job` is a ceiling. Two pictures asked for four is two
    pictures, each listed once — never a duplicate reference sent to Kie to pad the count."""
    pictures = [_image(tmp_path, "one.png"), _image(tmp_path, "two.jpg", JPEG)]
    style = _style("pair", reference_images=[_ref(path) for path in pictures])

    window = styles.pick_reference_window(style, 3, 4)

    assert _names(window) == ["one.png", "two.jpg"]
    assert len(set(_names(window))) == len(window)


def test_only_files_that_are_really_images_reach_the_window(tmp_path: Path) -> None:
    """Ported from `inspiration._usable`: suffix, size and MAGIC BYTES. A renamed `.txt` passes a
    name check and then fails the Kie upload, costing the job a reference for nothing — so
    "validate" here means the bytes, and an empty file is not an image either."""
    good_png = _image(tmp_path, "keep.png")
    good_jpeg = _image(tmp_path, "keep.jpg", JPEG)
    (tmp_path / "caption.txt").write_bytes(PNG + b"\x00" * 8)  # right bytes, wrong kind of file
    (tmp_path / "empty.png").write_bytes(b"")
    (tmp_path / "garbage.png").write_bytes(b"not an image, just some words")

    style = _style("mixed", reference_images=[
        _ref(tmp_path / "caption.txt"), _ref(good_png), _ref(tmp_path / "empty.png"),
        _ref(tmp_path / "garbage.png"), _ref(good_jpeg), _ref(tmp_path / "gone.png")])

    assert _names(styles.pick_reference_window(style, 0, 6)) == ["keep.png", "keep.jpg"]
    assert _names(styles.pick_reference_window(style, 1, 1)) == ["keep.jpg"]


def test_a_style_with_no_usable_picture_answers_an_empty_window(tmp_path: Path) -> None:
    """The `style_refs_missing` degrade seen from the caller's side: text-only, never an
    exception — `refs.attach` has a reference-free path and this is how it is reached."""
    assert styles.pick_reference_window(_style("bare"), 0, 2) == []
    assert styles.pick_reference_window(
        _style("gone", reference_images=[_ref(tmp_path / "nope.png")]), 2, 3) == []


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
