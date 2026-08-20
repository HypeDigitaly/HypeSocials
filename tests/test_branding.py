"""Branding end to end — who gets signed, what a signature says, and where it may be said.

FR-292's two channels cross four modules, and no single module's suite can see the whole chain:
`styles.assign_branding` decides WHICH creatives are signed, `generate.refs` gates the decision per
job, `prompts_engine` renders the two channels, and `generate.carousel` decides which slide of a
deck may carry one. This file follows one wordmark all the way through, and pins the five things
that only break at the seams:

1. **The rotation is a floor predicate on `entry.order`, never a count.**
   `floor((order+1)·r) > floor(order·r)`, so the total over the FULL emitted plan is `floor(N·r)` —
   never `round` (N=7/r=0.5 is 3, N=3/r=0.3 is 0). Over the live subset after a trim the branded
   count is simply the surviving orders that satisfy it, so a trim can never re-brand a survivor.
2. **The wordmark travels in the TEXT block and nowhere else** (§1.4 B1). Every render template
   declares `{{onimage_text}}` the only source of renderable words and prohibits every other
   wordmark, so a signature named inside `{{branding_block}}` is a string the model was told twice
   not to draw.
3. **The two `never:` lists have different scopes** (M6). `never_always` are COLOUR guards and ride
   every branded prompt; `never_style` are MEDIUM guards and ride only a style that belongs to the
   active brand's own visual system — six of the seven neutral styles are legitimately photographic
   or hand-drawn, and a branded photoreal post must stay photoreal.
4. **One run is ONE brand** (the `brand` selector, B3). A hypelead creative that carries a single
   HypeDigitaly indigo hex is a wrong-brand post, which is the one output no downstream degrade can
   rescue — so the isolation is asserted over the whole assembled context, from the REAL compiled
   profiles and from the shipped `configs/*.yaml` that mirror them.
5. **A signature is placed once per artefact** — the carousel anchor alone (M12), a signature zone
   only when there is something to put in it (M11), and each local reference file uploaded once per
   run and never across runs (FR-200/244: Kie keeps an upload ~24 h, so a memoized URL that outlives
   its run is a reference that silently 404s mid-batch).

`test_styles.py` owns registry loading, validation and the style rotation; `test_prompts_engine.py`
owns the context vocabulary and the allowlist table; `test_carousel.py` owns the deck lifecycle.
This suite reuses their builders where they fit and asserts only the branding chain.

Everything here is offline and deterministic: no network, no API key, no spend, no `logs/` and no
`output/` — the only filesystem use is `tmp_path`, plus read-only parsing of the shipped configs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from hypesocials import prompts_engine as pe
from hypesocials import render, styles
from hypesocials.config import BrandingConfig, BrandProfile, Config
from hypesocials.generate import carousel as carousel_module
from hypesocials.generate import refs as refs_module
from hypesocials.models import (
    CopySet,
    DegradationTag,
    LayoutZone,
    MetaStyle,
    PlanEntry,
    TrendItem,
)
from hypesocials.prompts_engine import PromptEngine

# The style builder is REUSED from the registry suite rather than re-declared (Wave-4 brief): a
# second "clean style" fixture would drift from the one `test_styles.py` keeps warning-free, and
# then a branding assertion could fail for a registry reason. Registry loading and validation stay
# that file's business; nothing here re-tests them.
from tests.test_styles import _registry, _style

REPO = Path(__file__).resolve().parents[1]
CONFIGS = REPO / "configs"
#: Real PNG magic bytes. Nothing sniffs them since D46 (the registry declares no pictures at all),
#: but a brief photo that goes to Kie is a real file on disk in a live run and stays one here.
PNG = b"\x89PNG\r\n\x1a\n"
BRANDS = ("hypedigitaly", "hypelead")


# --------------------------------------------------------------------------- builders


def _entry(order: int = 0, *, branded: bool = False, fmt: str = "image", **over: Any) -> PlanEntry:
    entry = PlanEntry(order=order, asset_id=f"{order:04d}_{fmt}_linkedin", creative_format=fmt,  # type: ignore[arg-type]
                      platform="linkedin", language="en", aspect_ratio="1:1", branded=branded)
    for key, value in over.items():
        setattr(entry, key, value)
    return entry


def _entries(orders, **over: Any) -> list[PlanEntry]:
    return [_entry(order, **over) for order in orders]


def _branding(brand: str = "hypelead", **over: Any) -> BrandingConfig:
    """The REAL compiled profiles (`config._default_profiles`), with only run-level keys moved.

    Deliberately not a hand-built profile: FR-292's whole promise is that the operator's shipped
    brand facts are what reaches the model, so a hand-written stand-in would prove the renderer
    works on data the run never has.
    """
    branding = BrandingConfig(brand=brand)  # type: ignore[arg-type]
    for key, value in over.items():
        setattr(branding, key, value)
    return branding


def _hexes(colors: Any) -> set[str]:
    """Every hex a colour map declares, gradients flattened, upper-cased for comparison."""
    out: set[str] = set()
    for value in (colors or {}).values():
        stops = value if isinstance(value, (list, tuple)) else [value]
        out.update(str(stop).strip().upper() for stop in stops if str(stop).strip())
    return {value for value in out if value.startswith("#")}


def _image(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(PNG + b"\x00" * 64)
    return path


def _names(paths) -> list[str]:
    """Compare uploads by file NAME rather than by path string: an upload-count assertion is about
    HOW MANY distinct files went to Kie, and the path FORM must never decide whether it passes."""
    return [Path(path).name for path in paths]


class Log:
    """`outputs.LogWriter`'s three call shapes; remembers only what an assertion might read."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def event(self, event_type: str, message: str = "", **data: Any) -> str:
        self.records.append((event_type, message))
        return f"ev_{len(self.records):04d}"

    warn = event
    error = event

    def types(self) -> list[str]:
        return [event_type for event_type, _ in self.records]


class Folder:
    """`outputs.AssetFolder` as far as `refs.attach` can see it: one degradation sink."""

    def __init__(self) -> None:
        self.tags: list[Any] = []

    def mark(self, tag: Any) -> None:
        self.tags.append(tag)


@dataclass
class Env:
    """Duck-typed stand-in for `generate.Env` — exactly the fields the branding chain reads.

    Both consumers under test read the run through `getattr`, so this is the same surface the live
    `Env` presents to them; a real `Env` would drag a config load, a registry load and a log file
    into a suite that must touch neither.
    """

    config: Config = field(default_factory=Config)
    run_dir: Path = Path("run")
    engine: PromptEngine = field(default_factory=PromptEngine)
    log: Log = field(default_factory=Log)
    branding: BrandingConfig | None = field(default_factory=BrandingConfig)
    styles: Any = None  # `styles.StyleRegistry`
    trends: dict[str, Any] = field(default_factory=dict)
    copy: dict[str, CopySet] = field(default_factory=dict)
    local_refs: dict[str, list[tuple[Path, str]]] = field(default_factory=dict)
    campaign_briefs: dict[str, Any] = field(default_factory=dict)
    strip_brands: dict[str, tuple[str, ...]] = field(default_factory=dict)
    niche_descriptor: str = "Audience: founders · Vibe: blunt"
    niche_visual_world: str = ""
    llm_call: Any = None
    halted: bool = False
    credits_exhausted: bool = False
    disk_full: bool = False


@pytest.fixture(autouse=True)
def clean_memo():
    """The upload memo is process-lived and run-keyed, which is right for a run and wrong for a
    suite: one test's "uploaded once" must never be satisfied by another test's upload."""
    refs_module.reset_uploads()
    yield
    refs_module.reset_uploads()


@pytest.fixture
def uploads(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """`render.upload_file`, faked — the call log IS the assertion for FR-200's one-upload rule."""
    calls: list[Path] = []

    async def _upload(path: Path) -> str:
        calls.append(Path(path))
        return f"https://kie.test/upload/{Path(path).name}"

    monkeypatch.setattr(render, "upload_file", _upload)
    return calls


# ----------------------------------------------------- (1) the ratio rotation, per entry


@pytest.mark.parametrize("total", [1, 3, 7, 8, 12, 20])
@pytest.mark.parametrize("ratio", [0.0, 0.2, 0.3, 0.5, 0.75, 1.0])
def test_every_entry_carries_the_floor_predicates_answer_and_the_plan_carries_floor_n_times_ratio(
    total: int, ratio: float,
) -> None:
    """§1.4's rotation, asserted the way the plan says to assert it: the PER-ENTRY predicate first,
    and the total only as its consequence.

    The predicate `floor((order+1)·r) > floor(order·r)` is supply-independent — it reads one
    entry's own order and nothing else — which is what makes the choice survive a trim and a
    re-preview. The total that falls out of it is `floor(N·r)`, never `round(N·r)`: at ratio 0
    nothing is signed and at ratio 1 everything is, and in between a ratio is a rate the operator
    set, not a promise to round up into an extra signed post.
    """
    entries = _entries(range(total))

    styles.assign_branding(entries, ratio)

    for entry in entries:
        expected = math.floor((entry.order + 1) * ratio) > math.floor(entry.order * ratio)
        assert entry.branded is expected, f"order {entry.order} at ratio {ratio}"
    assert sum(entry.branded for entry in entries) == math.floor(total * ratio)


@pytest.mark.parametrize("ratio,signed", [(0.0, False), (1.0, True)])
def test_the_two_extreme_ratios_reach_the_prompt_as_every_post_or_no_post(
    ratio: float, signed: bool,
) -> None:
    """The ends of the range, followed past the predicate to the string a model would draw.

    Ratio 0 and ratio 1 are the two settings an operator will read as absolutes ("never sign
    anything", "sign everything"), so the assertion is not that a boolean flipped but that the
    wordmark itself did or did not reach the creative through the gate that decides it.
    """
    entries = _entries(range(6))
    env = Env(branding=_branding("hypelead"))

    styles.assign_branding(entries, ratio)

    assert [entry.branded for entry in entries] == [signed] * 6
    assert [refs_module.wordmark(entry, env) for entry in entries] == \
        ["HypeLead" if signed else ""] * 6


# ----------------------------------------------------- (2) gapped orders after a trim


def test_a_trim_leaves_every_survivors_signature_exactly_where_the_full_plan_put_it() -> None:
    """Gapped `entry.order` values are the normal post-trim shape (`_confirm` trims, `_select`
    drops), and re-deriving the ratio over the survivors would move the wordmark onto a creative
    the operator already approved without one.

    So the assertion is the per-entry predicate over the SURVIVING orders — never a bare count over
    what was delivered, which is the check §1.4 explicitly forbids because it would fail here for
    entirely the wrong reason.
    """
    full = _entries(range(12))
    styles.assign_branding(full, 0.5)
    before = {entry.order: entry.branded for entry in full}

    survivors = [entry for entry in full if entry.order in (0, 3, 4, 9, 11)]
    styles.assign_branding(survivors, 0.5)  # the live subset is re-assigned, exactly as the run does

    for entry in survivors:
        expected = math.floor((entry.order + 1) * 0.5) > math.floor(entry.order * 0.5)
        assert entry.branded is expected and entry.branded is before[entry.order]
    branded_orders = [entry.order for entry in survivors if entry.branded]
    assert branded_orders == [3, 9, 11], "the survivors that satisfied the predicate, and only those"
    assert len(branded_orders) != math.floor(len(survivors) * 0.5), \
        "a bare count over the live subset is NOT the contract — this is why the predicate is"


def test_a_plan_that_was_never_dense_signs_the_same_orders_as_one_that_was() -> None:
    """The same invariant from the other side: a plan built with gaps from the start (an override
    brief's entries interleaved, a format the operator zeroed) must sign the same ORDERS a dense
    plan would have signed at those positions. The rotation reads one number and never a position
    in a list, so the two agree by construction — and this is the test that would catch it if some
    later refactor started counting instead."""
    dense, gapped = _entries(range(10)), _entries([0, 1, 5, 8, 9])

    styles.assign_branding(dense, 0.3)
    styles.assign_branding(gapped, 0.3)

    dense_by_order = {entry.order: entry.branded for entry in dense}
    assert [entry.branded for entry in gapped] == [dense_by_order[entry.order] for entry in gapped]


# ----------------------------------------------------- (3) per-profile block content


@pytest.mark.parametrize("brand", BRANDS)
def test_each_profiles_block_is_written_out_of_that_profiles_own_shipped_values(
    brand: str,
) -> None:
    """FR-292 channel 2, built from the compiled defaults both shipped configs mirror.

    Every claim in the block has to be traceable to a profile key — accents to `colors`, the
    letterform sentence to `font_character` (a render model cannot install a font, so the typeface
    is DESCRIBED, F21), the placement hint to `branding.placement` — because the operator edits
    those keys and expects the prompt to change with them.
    """
    branding = _branding(brand)
    profile = branding.profiles[brand]

    block = pe.branding_block(branding, _style("neutral-photoreal"))

    for value in _hexes(profile.colors):
        assert value in block.upper(), f"{brand} lost its own {value}"
    assert profile.font_character in block
    assert "placement hint for the signature: bottom-center" in block
    assert "Substitute them inside the style's own palette structure" in block, \
        "FR-109's inversion: branding substitutes inside the style, it never replaces the style"
    assert profile.wordmark not in block, "B1: the signature is a TEXT-block string, never this one"


@pytest.mark.parametrize("brand", BRANDS)
def test_the_colour_guards_ride_every_branded_block_and_the_medium_guards_only_a_brand_own_style(
    brand: str,
) -> None:
    """M6's split, on the real profiles. `never_always` is a colour rule and holds whatever the
    style; `never_style` is a MEDIUM rule ("no photography/stock/3D", "no serif") and would ban
    most of the registry if it rode every branded prompt — a branded photoreal post stays
    photoreal and gets the accents and the signature.

    `hypedigitaly` ships an empty `never_style` on purpose (the corporate system defends no medium
    of its own), so for that brand the affine block simply carries the colour guards too — which is
    exactly what "the split is read off the profile" means.
    """
    branding = _branding(brand)
    profile = branding.profiles[brand]
    neutral = _style("neutral-photoreal")
    affine = _style("house-card", brand_affinity=[brand])

    on_neutral = pe.branding_block(branding, neutral)
    on_affine = pe.branding_block(branding, affine)

    for guard in profile.never_always:
        assert guard in on_neutral and guard in on_affine, "a colour guard is unconditional"
    for guard in profile.never_style:
        assert guard not in on_neutral, "a medium guard must not reach a neutral style"
        assert guard in on_affine
    if profile.never_always or profile.never_style:
        assert "never: " in on_neutral


def test_a_style_affine_to_the_other_brand_gets_only_the_colour_guards() -> None:
    """The third case the two above do not reach: the run signs hypelead, the assigned style
    belongs to hypedigitaly's system. It is not this brand's own visual system, so the medium
    guards stay out — the same answer a neutral style gets, and for the same reason."""
    branding = _branding("hypelead")
    foreign = _style("hd-corporate", brand_affinity=["hypedigitaly"])

    block = pe.branding_block(branding, foreign)

    assert "no indigo or violet" in block, "the colour guards hold regardless"
    assert "no photography/stock/3D" not in block
    assert "no serif or handwritten type" not in block


def test_an_unconfigured_or_unknown_brand_renders_no_block_rather_than_half_of_one() -> None:
    """Two run shapes that must not crash the assembly of a creative: a run with no branding config
    at all (previews, tests) and a config naming a brand with no profile behind it — the latter is
    an FR-292 pre-flight error, and reaching a render prompt with half a brand's facts would be a
    worse outcome than reaching it with none."""
    assert pe.branding_block(None, _style("neutral")) == ""
    assert pe.branding_block(_branding("hypelead", profiles={}), _style("neutral")) == ""


# ----------------------------------------------------- (4) the wordmark in the TEXT block


@pytest.mark.parametrize("brand", BRANDS)
def test_the_wordmark_is_quoted_with_its_spelling_aid_inside_the_text_block_only(
    brand: str,
) -> None:
    """B1's channel, both directions. The signature is quoted in `{{onimage_text}}` under exactly
    the verbatim contract the headline gets — spelling aid included, because a wordmark rendered
    with the wrong letterform is a wrong wordmark — and it appears in no other slot of the
    assembled context, least of all the branding block that describes everything else about the
    brand."""
    branding = _branding(brand)
    signature = branding.profiles[brand].wordmark
    style = _style("neutral-photoreal")

    context = pe.build_context(
        style=style, copy=CopySet("a1", "en", headline="Wired backwards", subline="Here is why"),
        creative_format="image", branding_block=pe.branding_block(branding, style),
        wordmark=signature)

    assert f'wordmark (render verbatim): "{signature}"' in context["onimage_text"]
    assert pe._spell(signature) in context["onimage_text"], "FR-186's diacritics defence, verbatim"
    assert context["onimage_text"].index("headline") < context["onimage_text"].index("wordmark"), \
        "a signature is read last: the creative's own words come first"
    elsewhere = {name: value for name, value in context.items() if name != "onimage_text"}
    assert not [name for name, value in elsewhere.items() if signature in value], \
        f"{signature} reached a slot other than the TEXT block"


def test_an_unsigned_creative_has_no_wordmark_entry_at_all() -> None:
    """Empty wordmark is the whole "unbranded" signal (W2 addendum item 1), so the block must not
    grow an empty labelled entry: a `wordmark (render verbatim): ""` line is an instruction to
    render a blank signature, which the models answer by inventing one."""
    copy = CopySet("a1", "en", headline="Wired backwards")

    context = pe.build_context(copy=copy, creative_format="image", wordmark="")

    assert "wordmark" not in context["onimage_text"]
    assert 'headline (render verbatim): "Wired backwards"' in context["onimage_text"]
    # And a whitespace-only wordmark is unsigned too — otherwise a stray space in a config file
    # would sign a creative with nothing.
    assert "wordmark" not in pe.build_context(
        copy=copy, creative_format="image", wordmark="   ")["onimage_text"]


# ----------------------------------------------------- (5) brand slot + conditional zones


def test_a_brand_slot_style_collapses_the_block_under_its_own_brand_by_flag_and_never_by_key() -> None:
    """B3's data-driven rule, asserted with the keys deliberately misleading in both directions.

    A style whose key says nothing about a brand but carries `brand_slot: true` collapses the block
    (the style IS the brand: its own `render_prompt` already states the palette, the ground and the
    letterforms, so a second set of colour instructions can only argue with it). A style whose KEY
    reads like a brand card but sets no flag keeps its block. An override registry is free to name
    its brand style anything, and the rule must survive that.
    """
    branding = _branding("hypelead")
    flagged = _style("aurora-plate", brand_affinity=["hypelead"], brand_slot=True)
    key_only = _style("hypelead-brand-card", brand_affinity=["hypelead"])
    other_brands_slot = _style("hd-plate", brand_affinity=["hypedigitaly"], brand_slot=True)

    assert pe.branding_block(branding, flagged) == ""
    assert pe.branding_block(branding, key_only) != "", "a suggestive KEY is not a brand slot"
    assert pe.branding_block(branding, other_brands_slot) != "", \
        "another brand's house style is not ours; it needs our accents like any neutral style"


def test_a_collapsed_brand_slot_still_signs_itself_through_the_text_block() -> None:
    """The half of the collapse that would be a silent regression: the block goes, the SIGNATURE
    does not. A brand's own house style with no wordmark on it is an unsigned post in brand
    colours, which is precisely the artefact the rotation exists to produce on purpose — never by
    accident."""
    branding = _branding("hypelead")
    style = _style("aurora-plate", brand_affinity=["hypelead"], brand_slot=True)

    context = pe.build_context(style=style, creative_format="image",
                               branding_block=pe.branding_block(branding, style),
                               wordmark=branding.profiles["hypelead"].wordmark)

    assert context["branding_block"] == ""
    assert 'wordmark (render verbatim): "HypeLead"' in context["onimage_text"]


def test_the_signature_zone_is_emitted_only_when_there_is_a_signature_to_put_in_it() -> None:
    """M11 — a described-but-unfilled brand slot is the single biggest hallucination site the
    render models have: told about a lower-margin signature zone and given no string for it, they
    invent a logotype. So an unsigned creative gets the zone DROPPED, the remaining zones
    renumbered (a gap in the list is itself a description of something missing), and one explicit
    line stating that the margin is empty."""
    style = _style("badged", layout_zones=[
        LayoutZone("upper third", "headline", "all caps, extra bold"),
        LayoutZone("lower margin", "brand signature", "small caps", role="brand_slot")])

    signed = pe.build_context(style=style, wordmark="HypeLead")["layout_zones"]
    unsigned = pe.build_context(style=style, wordmark="")["layout_zones"]

    assert "2. lower margin — brand signature" in signed
    assert pe._NO_SIGNATURE_LINE not in signed
    # The zone itself is gone — "lower margin" survives only inside the M11 line that replaces it.
    assert "2. lower margin" not in unsigned and "small caps" not in unsigned
    assert unsigned.startswith("1. upper third") and unsigned.endswith(pe._NO_SIGNATURE_LINE)


def test_a_style_with_no_signature_zone_says_nothing_about_signatures_either_way() -> None:
    """The M11 line is a correction for a zone that WAS declared and is not being filled. On a
    style that never described one there is nothing to correct, and the line would be the same
    kind of unprompted claim about the lower margin it exists to prevent."""
    plain = _style("plain", layout_zones=[LayoutZone("upper third", "headline", "all caps")])

    for mark in ("HypeLead", ""):
        assert pe._NO_SIGNATURE_LINE not in pe.build_context(style=plain, wordmark=mark)[
            "layout_zones"]


# ----------------------------------------------------- (6) cross-brand hex isolation


@pytest.mark.parametrize("brand", BRANDS)
def test_a_branded_creative_never_carries_one_hex_of_the_other_brand(brand: str) -> None:
    """The selector's whole point (B3): one run is one brand, never a mix. A hypelead post carrying
    HypeDigitaly's indigo is a wrong-brand post — the one output no downstream degrade can rescue,
    because the pixels are already paid for and already wrong.

    Asserted over the WHOLE assembled context rather than the branding block alone: the block is
    only the loudest channel, and the profiles also reach the prompt through the guards, the
    background hint and the letterform sentence.
    """
    other = next(name for name in BRANDS if name != brand)
    branding = _branding(brand, mode="both")  # `both` = accents AND the background hint: max surface
    mine, theirs = (_hexes(branding.profiles[name].colors) for name in (brand, other))
    style = _style("neutral-photoreal")
    entry = _entry(0, branded=True)
    env = Env(branding=branding)

    context = pe.build_context(
        style=style, copy=CopySet("a1", "en", headline="Wired backwards"), creative_format="image",
        branding_block=refs_module.branding_block(entry, env, style),
        wordmark=refs_module.wordmark(entry, env))
    assembled = "\n".join(context.values())

    assert all(value in assembled.upper() for value in mine), \
        "the active brand's own colours must actually be there for the exclusion to mean anything"
    for foreign in theirs - mine:
        assert foreign not in assembled.upper(), f"{other}'s {foreign} reached a {brand} creative"
    assert branding.profiles[brand].wordmark in assembled, "the creative signs itself…"
    assert branding.profiles[other].wordmark not in assembled, \
        "…and never with the other brand's name (a product noun is a copy-side fact, never a " \
        "signature, and it has no channel into a render prompt)"


def test_the_shipped_configs_declare_two_disjoint_colour_systems() -> None:
    """The isolation above can only hold if the SOURCE data is disjoint, and the source is the
    operator's own file: `configs/*.yaml` spell the profiles out so they are editable there rather
    than only in code. A hex pasted into both profiles during an edit would make every isolation
    assertion in this suite vacuously true, so the files themselves are checked — read-only."""
    checked = 0
    for path in sorted(CONFIGS.glob("*.yaml")):
        profiles = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get(
            "branding", {}).get("profiles") or {}
        declared = {name: _hexes(block.get("colors")) for name, block in profiles.items()
                    if block.get("colors")}
        if len(declared) < 2:
            continue
        checked += 1
        for name, values in declared.items():
            for other, others in declared.items():
                if other != name:
                    assert not values & others, f"{path.name}: {name} and {other} share a hex"
    assert checked, "no shipped config declares both profiles — the check above proved nothing"


def test_the_compiled_defaults_and_the_shipped_default_config_name_the_same_hexes() -> None:
    """`config._default_profiles` is what a run gets when the file says nothing, and
    `configs/default.yaml` is what the operator reads to find out what that is. When they disagree,
    the documentation is wrong about the pixels — and the branding block is built from the code
    side."""
    declared = (yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8")) or {}).get(
        "branding", {}).get("profiles") or {}
    compiled = BrandingConfig().profiles

    for name, block in declared.items():
        assert _hexes(block.get("colors")) == _hexes(compiled[name].colors), \
            f"configs/default.yaml and config._default_profiles disagree about {name}"
        assert block.get("wordmark") == compiled[name].wordmark


# ----------------------------------------------------- (7) the caller gate + carousel anchor


def test_the_gate_answers_only_for_a_branded_entry_and_never_raises_on_a_bare_run() -> None:
    """`refs.wordmark` / `refs.branding_block` are the seam where the rotation becomes a string:
    the format modules are the only callers that know which prompt is being assembled, and both
    functions must answer "" — never raise — for the runs that carry no branding at all (previews
    and tests), because an unsigned frame is a valid frame and a crash is not."""
    style = _style("neutral-photoreal")
    branded, plain = _entry(0, branded=True), _entry(1, branded=False)
    env = Env(branding=_branding("hypelead"))

    assert refs_module.wordmark(branded, env) == "HypeLead"
    assert refs_module.branding_block(branded, env, style) != ""
    assert refs_module.wordmark(plain, env) == ""
    assert refs_module.branding_block(plain, env, style) == "", \
        "an unbranded creative gets neither channel — not an empty-ish one"
    bare = Env(branding=None)
    assert refs_module.wordmark(branded, bare) == ""
    assert refs_module.branding_block(branded, bare, style) == ""
    # A brand with no profile behind it is a pre-flight error, not an exception here.
    assert refs_module.wordmark(branded, Env(branding=_branding("hypelead", profiles={}))) == ""


def _deck(tmp_path: Path, *, branded: bool, anchored: bool = True) -> Any:
    """One carousel deck positioned at the M12 gate, with nothing submitted and nothing spent.

    The gate is `_Deck._prompt`'s two arguments (`branding_block=` and `wordmark=`), so the deck is
    driven straight to prompt assembly: the deck LIFECYCLE — anchor chain, checks, packaging — is
    `test_carousel.py`'s subject and running it here would only add a render seam to fake.
    """
    entry = PlanEntry(order=0, asset_id="0001_carousel_linkedin", creative_format="carousel",
                      platform="linkedin", language="en", aspect_ratio="1:1", trend_key="t1",
                      style_key="neutral-photoreal", slide_count=3, branded=branded)
    copyset = CopySet(asset_id=entry.asset_id, language="en", headline="Wired backwards",
                      slide_texts=["Wired backwards", "Two", "Three"])
    env = Env(run_dir=tmp_path, branding=_branding("hypelead"),
              styles=_registry(_style("neutral-photoreal", format_affinity=["image", "carousel"])),
              copy={entry.asset_id: copyset})
    env.config.run.carousel_anchor = anchored
    return carousel_module._Deck(entry, env, Folder(), None)


def test_m12_the_carousel_signs_slide_one_and_never_a_slide_that_follows_it(
    tmp_path: Path,
) -> None:
    """A deck signed once reads as designed; signed N times it reads as a watermark. On a CHAINED
    deck slide 1 carries both channels and slides 2–N carry neither — they inherit the signature
    from the picture they reproduce, and `carousel_anchor_instruction.md` tells them never to
    refill the zone."""
    deck = _deck(tmp_path, branded=True)

    prompts = {number: deck._prompt(number, anchor=number > 1, refs=[])
               for number in (1, 2, 3)}

    assert all(prompt is not None for prompt in prompts.values()), "FR-260: nothing failed to fill"
    # Every slide really assembled — otherwise the three absence assertions below would hold for
    # the wrong reason (an empty prompt contains no wordmark either).
    assert [text in prompts[number] for number, text in
            zip((1, 2, 3), ("Wired backwards", "Two", "Three"))] == [True] * 3
    assert "HypeLead" in prompts[1] and "#0FCFC4" in prompts[1]
    for number in (2, 3):
        assert "HypeLead" not in prompts[number], "M12: slide 2–N never refills the signature zone"
        assert "#0FCFC4" not in prompts[number], "the anchor already carries the accents"


def test_m12_holds_on_an_independent_deck_where_every_slide_needs_the_colour_block(
    tmp_path: Path,
) -> None:
    """The strict half. With no anchor to inherit from (`carousel_anchor: false`, or the FR-95
    fallback after a lost anchor) every slide needs the colour instructions — but the WORDMARK is
    still slide 1's alone, whatever shape the deck took to get there."""
    deck = _deck(tmp_path, branded=True, anchored=False)

    prompts = {number: deck._prompt(number, anchor=False, refs=[])
               for number in (1, 2, 3)}

    assert all("#0FCFC4" in prompt for prompt in prompts.values()), "no anchor to inherit from"
    assert [number for number, prompt in prompts.items() if "HypeLead" in prompt] == [1]


def test_an_unsigned_deck_reaches_the_model_with_neither_channel(tmp_path: Path) -> None:
    """`entry.branded` is the rotation's own answer, and an unsigned deck must carry no trace of
    the brand: no TEXT-block wordmark and no accent block, on any slide, chained or not."""
    deck = _deck(tmp_path, branded=False)

    for number, text in zip((1, 2, 3), ("Wired backwards", "Two", "Three")):
        prompt = deck._prompt(number, anchor=number > 1, refs=[])
        assert prompt is not None and text in prompt, "the slide assembled, brand or no brand"
        assert "HypeLead" not in prompt and "#0FCFC4" not in prompt


# ------------------------------------------ (7a) FR-318's master switch, at the render prompt


@pytest.mark.parametrize("enabled", [False, True])
def test_fr318_the_competitor_strip_reaches_the_render_prompt_in_both_switch_states(
    tmp_path: Path, enabled: bool,
) -> None:
    """The safety carve-out at the level that actually spends money (§1.5 layer 1, M6).

    `branding.enabled` and `branding.competitors` live in the same config block, which is exactly
    why this is worth an explicit pin in both states: an operator who switches self-branding off to
    try a neutral batch must not thereby ship a competitor's brand name inside a frame they paid
    for. The switch is about how WE sign a creative; the blocklist is about what may never appear
    on one, and `build_context`'s strip pass never consults the first on its way to the second.
    """
    deck = _deck(tmp_path, branded=enabled)
    deck.env.branding.enabled = enabled
    deck.env.branding.competitors = ["Zzqcorp"]
    deck.env.trends = {"t1": TrendItem(
        history_key="t1", monitor_id="m1", topic_key="zzqcorp-stacks",
        name="Zzqcorp tool stacks", why_it_works="Zzqcorp keeps raising its prices",
        hook_texts=["Zzqcorp raised prices again"])}

    prompt = deck._prompt(1, anchor=False, refs=[])

    assert prompt is not None and "Wired backwards" in prompt, "the slide really assembled"
    assert "Zzqcorp" not in prompt, "layer 1 is unguarded and untouched by FR-318"
    assert ("HypeLead" in prompt) is enabled, "the SELF-branding half is what the switch moves"


def test_fr318_an_unsigned_run_carries_neither_channel_through_the_caller_gate() -> None:
    """`assign_branding(..., enabled=False)` writes `entry.branded = False` on every entry, and
    these two functions read exactly that — so with the switch off the wordmark channel and the
    accent block are both empty at the seam, before any prompt is assembled.

    Asserted at the GATE rather than only in the prompt because that is where a future caller
    would reintroduce the leak: `refs.wordmark` is the one signal that says "this creative is
    signed", and a non-empty string here would sign a run that asked for none however carefully
    the template behaved.
    """
    style = _style("neutral-photoreal")
    entries = _entries(range(4))
    env = Env(branding=_branding("hypelead", enabled=False))

    styles.assign_branding(entries, env.branding.brand_ratio, enabled=env.branding.enabled)

    assert [entry.branded for entry in entries] == [False] * 4
    for entry in entries:
        assert refs_module.wordmark(entry, env) == ""
        assert refs_module.branding_block(entry, env, style) == ""


# ----------------------------------------------------- (8/9) the upload memo, per run


def _brief_refs(entries, picture: Path) -> dict[str, list[tuple[Path, str]]]:
    """`env.local_refs` as the runner builds it post-D46: one brief photo per creative, kind
    `"brief"`. The STYLE channel is gone (FR-18) — a meta-style ships prose, never pixels — so this
    is the only way a local file still reaches the upload memo."""
    return {entry.asset_id: [(picture, "brief")] for entry in entries}


async def test_one_local_file_is_uploaded_once_per_run_however_many_jobs_want_it(
    tmp_path: Path, uploads: list[Path],
) -> None:
    """FR-200/244: one brief's product photo is attached to every creative that brief ordered, and
    uploading it per job would multiply a run's upload traffic by its batch size. The memo is what
    makes a four-creative brief cost one upload for the whole run instead of four."""
    picture = _image(tmp_path / "brief-refs", "card.png")
    entries = [_entry(order, style_key="neutral-photoreal", brief_name="launch")
               for order in range(4)]
    env = Env(run_dir=tmp_path, styles=_registry(_style("neutral-photoreal")),
              local_refs=_brief_refs(entries, picture))

    for entry in entries:
        attached = await refs_module.attach(entry, env, Folder())
        assert [ref.url for ref in attached] == ["https://kie.test/upload/card.png"]
        assert [ref.kind for ref in attached] == ["brief"], "the only provenance left (FR-18)"

    assert _names(uploads) == ["card.png"], "four jobs, one upload — the memo is what does that"


async def test_a_file_that_failed_to_upload_is_retried_rather_than_memoized_as_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only SUCCESSES are memoized. A transient upload error must not cost a brief its photos for
    the rest of the run — one retry per job is cheaper than teaching the memo to remember failures,
    and a failed upload is one fewer reference, never a failed job (FR-18/200)."""
    picture = _image(tmp_path / "brief-refs", "card.png")
    first_entry = _entry(0, style_key="neutral-photoreal", brief_name="launch")
    second_entry = _entry(1, style_key="neutral-photoreal", brief_name="launch")
    env = Env(run_dir=tmp_path, styles=_registry(_style("neutral-photoreal")),
              local_refs=_brief_refs([first_entry, second_entry], picture))
    attempts: list[Path] = []

    async def _upload(path: Path) -> str:
        attempts.append(Path(path))
        if len(attempts) == 1:
            raise RuntimeError("kie upload timed out")
        return f"https://kie.test/upload/{Path(path).name}"

    monkeypatch.setattr(render, "upload_file", _upload)

    first = await refs_module.attach(first_entry, env, Folder())
    second = await refs_module.attach(second_entry, env, Folder())

    assert first == [] and "reference_upload_failed" in env.log.types()
    assert [ref.url for ref in second] == ["https://kie.test/upload/card.png"]
    assert _names(attempts) == ["card.png"] * 2, "the failure was retried, not remembered"


async def test_a_second_run_re_uploads_because_a_kie_url_does_not_outlive_its_run(
    tmp_path: Path, uploads: list[Path],
) -> None:
    """The memo is keyed by `run_dir` and thrown away with the run on purpose: Kie's file host keeps
    an upload roughly 24 h, so a URL carried into a later run is a reference that silently 404s
    mid-batch — a job that renders without the operator's own product and reports success.

    Both seams are asserted, because a process can outlive a run either way: a NEW run directory,
    and `reset_uploads()` for anything that reuses one.
    """
    picture = _image(tmp_path / "brief-refs", "card.png")
    entry = _entry(0, style_key="neutral-photoreal", brief_name="launch")
    registry = _registry(_style("neutral-photoreal"))
    local = _brief_refs([entry], picture)

    def _env(run_dir: Path) -> Env:
        return Env(run_dir=run_dir, styles=registry, local_refs=local)

    first_run, second_run = tmp_path / "run-2026-08-12-0900", tmp_path / "run-2026-08-12-1500"
    await refs_module.attach(entry, _env(first_run), Folder())
    await refs_module.attach(entry, _env(second_run), Folder())
    assert _names(uploads) == ["card.png"] * 2, "a new run re-uploads; the old URL is expiring"

    refs_module.reset_uploads()
    await refs_module.attach(entry, _env(first_run), Folder())
    assert _names(uploads) == ["card.png"] * 3, "the reset seam forgets every run's memo"


async def test_a_style_driven_creative_attaches_nothing_and_is_not_degraded(
    tmp_path: Path, uploads: list[Path],
) -> None:
    """D46/FR-18: text-to-image is the DEFAULT route, so a creative whose only visual authority is
    its meta-style attaches no reference at all — and that is not a degradation. `reference_free`
    is reserved for a loss (a brief shipped photos and none survived), which is why the tag and the
    warning must both stay silent here."""
    entry = _entry(0, style_key="neutral-photoreal")
    env = Env(run_dir=tmp_path, styles=_registry(_style("neutral-photoreal")))
    folder = Folder()

    assert await refs_module.attach(entry, env, folder) == []
    assert uploads == [], "nothing local was uploaded: a style is words now"
    assert folder.tags == [] and env.log.types() == [], "no tag, no warning — nothing was lost"


async def test_a_brief_that_loses_every_photo_is_marked_reference_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of FR-18: brief images are an input, not a prerequisite — the job proceeds on
    the style's written guidance — but a creative that EXPECTED pictures and got none has lost
    something, and the loss is marked in metadata and logged by name."""
    picture = _image(tmp_path / "brief-refs", "card.png")
    entry = _entry(0, style_key="neutral-photoreal", brief_name="launch")
    env = Env(run_dir=tmp_path, styles=_registry(_style("neutral-photoreal")),
              local_refs=_brief_refs([entry], picture))
    folder = Folder()

    async def _upload(path: Path) -> str:
        raise RuntimeError("kie upload timed out")

    monkeypatch.setattr(render, "upload_file", _upload)

    assert await refs_module.attach(entry, env, folder) == []
    assert DegradationTag.REFERENCE_FREE in folder.tags
    assert "reference_free" in env.log.types()


async def test_a_local_reference_of_any_other_kind_is_dropped_with_a_line(
    tmp_path: Path, uploads: list[Path],
) -> None:
    """`env.local_refs` is the BRIEF channel and nothing else post-D46. A stale caller handing back
    a `style`-kinded file must not have it uploaded to a job the operator is paying for — it is
    dropped, and the drop is logged rather than swallowed."""
    picture = _image(tmp_path / "style-refs", "card.png")
    entry = _entry(0, style_key="neutral-photoreal")
    env = Env(run_dir=tmp_path, styles=_registry(_style("neutral-photoreal")),
              local_refs={entry.asset_id: [(picture, "style")]})
    folder = Folder()

    assert await refs_module.attach(entry, env, folder) == []
    assert uploads == [], "the kind vocabulary is the gate, not the file"
    assert "reference_kind_unknown" in env.log.types()
    assert folder.tags == [], "nothing was EXPECTED, so nothing was lost (FR-18)"


# --------------------------------- (10) `upload_local`: the source store's ONE sanctioned door
#
# FR-244 as amended v2.1.3/D48. `output/<run>/source/` is analysis-and-display-only (D46) and
# `upload_local` is the single opening in it: an FR-315 logo patch, written by `logo_crops` into
# the post's own `marks/` subfolder. The gate is on the PATH, not on the bytes, so a caller cannot
# smuggle a full slide through by renaming its variable — and it is the same public seam a format
# module uses for any local file it made itself, so the memo and the failure posture come with it.


def _patch(tmp_path: Path, post_id: str = "p1", name: str = "notion.png") -> Path:
    """One cropped logo patch where `logo_crops` writes it: `source/<post_id>/marks/<slug>.png`."""
    return _image(tmp_path / "source" / post_id / "marks", name)


def _slide(tmp_path: Path, post_id: str = "p1", name: str = "slide_01.webp") -> Path:
    """One stored SOURCE slide — the archived original, which may never reach a render payload."""
    return _image(tmp_path / "source" / post_id, name)


async def test_a_logo_patch_used_on_eight_slides_is_uploaded_once_for_the_whole_run(
    tmp_path: Path, uploads: list[Path],
) -> None:
    """FR-200/FR-244: `upload_local` shares `attach()`'s run memo by construction.

    A mark boxed on every panel of a deck is one logo, cropped once by `logo_crops` and then asked
    for once per slide by `carousel._patch_refs`. Uploading it per slide would multiply a deck's
    upload traffic by its length for pixels Kie already holds, so the memo is what makes the
    per-slide call cheap enough for the format module to make it without thinking about it.
    """
    patch = _patch(tmp_path)
    env = Env(run_dir=tmp_path)

    urls = [await refs_module.upload_local(patch, env, label=f"deck slide {n}") for n in range(8)]

    assert urls == [f"https://kie.test/upload/{patch.name}"] * 8
    assert _names(uploads) == ["notion.png"], "eight slides, one upload — the memo does that"


async def test_a_patch_upload_that_fails_costs_the_mark_its_pixels_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-315d: `""` plus a warned line, never an exception and never a lost slide.

    The empty string is the whole contract with the caller — it reads as "this reference does not
    exist" and the mark then renders from its name and the template's written description, which
    is the documented fallback. Anything that raised here would take a deck down for a failed
    upload of an optional upgrade.
    """
    patch = _patch(tmp_path)
    env = Env(run_dir=tmp_path)

    async def _upload(path: Path) -> str:
        raise RuntimeError("kie upload timed out")

    monkeypatch.setattr(render, "upload_file", _upload)

    assert await refs_module.upload_local(patch, env, label="0001_carousel mark patch Notion") == ""
    assert "reference_upload_failed" in env.log.types()


async def test_the_source_store_refuses_everything_that_is_not_a_mark_patch(
    tmp_path: Path, uploads: list[Path],
) -> None:
    """The carve-out's width, asserted as a path rule: `marks/` passes, the rest of `source/` does
    not, and the refusal happens BEFORE anything is sent.

    D46 made the source store analysis-and-display-only because a Virlo slide reaching a render
    payload is the failure the whole boundary exists to prevent — the gallery may show it, the
    vision pass may read it, nothing may upload it. D48 opened one door for small logo patches and
    no more: a full slide, a panel crop, or a patch written beside `marks/` instead of inside it
    is refused, and the refusal names why.
    """
    env = Env(run_dir=tmp_path)
    slide, patch = _slide(tmp_path), _patch(tmp_path)

    assert await refs_module.upload_local(slide, env, label="0001_carousel") == ""
    assert uploads == [], "refused UNSENT — the check is on the path, before the transport"
    assert "reference_source_store_refused" in env.log.types()

    assert await refs_module.upload_local(patch, env) == f"https://kie.test/upload/{patch.name}"
    assert _names(uploads) == ["notion.png"], "the one sanctioned class of file went"


@pytest.mark.parametrize(
    ("parts", "sanctioned"),
    [
        # Inside a `source/` tree, only `marks/` passes.
        (("source", "p1", "marks", "notion.png"), True),
        (("source", "p1", "slide_01.webp"), False),
        (("source", "p1", "slide_01.jpg"), False),
        (("source", "p1", "source.yaml"), False),
        # Deeper nesting on either side of the rule changes nothing: the test is on the segments.
        (("output", "20260813_r1", "source", "p1", "marks", "figma.png"), True),
        (("output", "20260813_r1", "source", "p1", "slide_03.jpg"), False),
        # Outside a `source/` tree everything is ordinary — a brief photo, a rendered artifact,
        # and a file that merely has "source" in its NAME rather than as a path segment.
        (("brief-photos", "card.png"), True),
        (("0001_carousel_linkedin", "slide_01.jpg"), True),
        (("refs", "source-material.png"), True),
    ])
async def test_the_sanction_gate_reads_path_segments_not_filenames(
    tmp_path: Path, uploads: list[Path], parts: tuple[str, ...], sanctioned: bool,
) -> None:
    """One table for the gate, because it is the boundary the whole D46 carve-out rests on.

    `marks/` and `source/` are matched as PATH SEGMENTS, case-folded — so a run folder nested any
    number of levels deep behaves identically, and a file called `source-material.png` outside the
    store is an ordinary local file rather than a near-miss the gate has to guess about.
    """
    path = _image(tmp_path.joinpath(*parts[:-1]), parts[-1])
    env = Env(run_dir=tmp_path)

    url = await refs_module.upload_local(path, env)

    assert bool(url) is sanctioned
    assert bool(uploads) is sanctioned
    assert ("reference_source_store_refused" in env.log.types()) is not sanctioned
