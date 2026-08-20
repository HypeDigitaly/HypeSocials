"""FR-338 (D59) — `{{counter_rule}}`, the slide renderer's own channel for the position badge.

**The hole this closes.** A deck's counter is placed by a `counter_slot` LAYOUT ZONE, and layout
zones travel in `{{layout_zones}}` — a slot `carousel_slide.md` does not name. So the one role that
renders a mapped deck's slides was the one role never told where the badge goes, while the
gauntlet's `system` critic judged every one of those slides against the zone list
(`generate.contracts.deck_contract`). The renderer was left inferring a badge from whatever chip
STYLE_DNA happened to describe — on uncounted decks too, which is the invented-"01" defect D-D
already fixed once at the TEXT-block level. This is the same shape of bug F1-A found under
`{{list_treatment}}`, in the same role, and it is closed the same way: its own slot.

What this file pins is the truth table and the one property that makes the slot worth having —
**the renderer and the critic read the badge in identical words**, because both go through
`prompts_engine._zone_line`. A second hand-written rendering beside either reader would drift, and
drift reads from the critic's seat as a `style_layout` defect on every frame of the deck.

Synthetic styles for the table (a registry edit must not be able to break a truth table), the REAL
registry for the parity property (that one is only meaningful against shipped bytes).
"""

from __future__ import annotations

import pytest

from hypesocials import prompts_engine as pe
from hypesocials import styles
from hypesocials.models import PLACEHOLDERS, Brief, LayoutZone
from tests.test_prompts_engine import make_style

#: The zone a style declares when it wants the badge somewhere of its own choosing.
COUNTER_ZONE = LayoutZone("top-right corner", "slide-position badge",
                          "small mono uppercase, no chip", role="counter_slot")
HEADLINE_ZONE = LayoutZone("upper third", "headline", "all caps, extra bold")

#: A deck's badge string, in the shape `detect_counter` re-bases onto OUR length.
COUNTER = "07 / 12"


def declaring() -> object:
    """A style whose layout asks for the badge in a named place."""
    return make_style(layout_zones=[HEADLINE_ZONE, COUNTER_ZONE])


def silent() -> object:
    """A style that never asked for a badge at all — the majority of the registry."""
    return make_style(layout_zones=[HEADLINE_ZONE])


# ------------------------------------------------------------------- the five-arm truth table


def test_arm_a_no_style_says_nothing_about_a_counter() -> None:
    """An override brief replaced the style's layout outright (FR-144), so there is no zone to
    quote and no house spine to fall back on — exactly as `layout_zones` and `list_treatment`
    hand back `""` on the same input."""
    assert pe.counter_rule(None, slide_counter=COUNTER) == ""
    assert pe.counter_rule(None) == ""


def test_arm_b_a_declared_zone_on_a_counted_deck_quotes_the_zone() -> None:
    """The arm the slot exists for: the style said where the badge goes, so the renderer is told
    in the style author's own words — the same three fields, in the same order, as the numbered
    line the critic reads."""
    style = declaring()

    value = pe.counter_rule(style, slide_counter=COUNTER)

    assert value == "top-right corner — slide-position badge — small mono uppercase, no chip"
    assert pe._NO_COUNTER_LINE not in value


def test_arm_c_a_declared_zone_on_an_uncounted_deck_states_the_absence() -> None:
    """M11's argument, applied to the badge (D-D): a described-but-unfilled position chip is
    filled by these models with an invented "01", a page number, or a "3/7" matching no deck. The
    absence is STATED, and in the engine's own constant so the renderer and the critic cannot
    describe one uncounted deck in two different ways."""
    assert pe.counter_rule(declaring()) == pe._NO_COUNTER_LINE
    assert pe.counter_rule(declaring(), slide_counter="   ") == pe._NO_COUNTER_LINE, \
        "whitespace is not a counter"


def test_arm_d_no_declared_zone_on_a_counted_deck_gets_the_house_line() -> None:
    """The mirror-image hole, and the one nothing covered before D59. The counter is the SOURCE
    deck's convention, not the style's, so a numbered deck renders one whatever the registry says
    — and `generate.contracts` duly lists a `counter:` row to the critic on these styles. Until
    D59 the renderer got no placement for it at all. This is FR-350's house spine, stated here
    first so the two readers agree today."""
    value = pe.counter_rule(silent(), slide_counter=COUNTER)

    assert value == ("counter 07 / 12: small, body family, top-right inside the safe area; "
                     "no chip, no badge")
    assert COUNTER in value, "the house line names the actual badge string, never a placeholder"


def test_arm_e_no_zone_and_no_counter_says_nothing_at_all() -> None:
    """Nothing to place and nothing to suppress. The template region reads "(ignore if empty)"
    for precisely this case, and it is the commonest one in the registry."""
    assert pe.counter_rule(silent()) == ""


def test_arm_f_an_override_brief_empties_the_slot_through_build_context() -> None:
    """The sixth case, and the one only `build_context` can show: the override gate is applied
    beside the value, exactly as it is for `layout_zones` and `list_treatment`. A brief that
    replaced the style's whole layout (FR-144) cannot leave one zone of it standing."""
    brief = Brief(name="ai-audit-cta", description="AI audit CTA", influence="override",
                  visual_directives={"scene": "laptop on a desk, one product card"})
    style = declaring()

    overridden = pe.build_context(style=style, campaign_brief=brief, creative_format="carousel",
                                  slide_counter=COUNTER)
    plain = pe.build_context(style=style, creative_format="carousel", slide_counter=COUNTER)

    assert overridden["counter_rule"] == ""
    assert overridden["layout_zones"] == "", "the neighbouring gate is the precedent, not a copy"
    assert plain["counter_rule"] != "", "…and without the brief the zone still reaches the slide"


# ------------------------------------------------- the property the slot exists for: one wording


@pytest.mark.parametrize("style_key", ["icon-ledger-carousel", "editorial-voxel-carousel",
                                       "letterpress-print-carousel", "terminal-mockup-deck"])
def test_the_renderer_and_the_critic_read_the_badge_in_identical_words(style_key: str) -> None:
    """Measured on SHIPPED registry bytes, because that is the only place the property can fail.

    `style_zones` builds what the `system` critic is shown; `counter_rule` builds the one line of
    it a slide renderer sees. Both come out of `_zone_line`, so the renderer's line is a literal
    substring of the critic's list — ordinal aside, which is a position in the critic's list and
    means nothing on a slot carrying one zone alone.
    """
    registry = styles.load_registry([pe.PROMPTS_DIR])
    style = styles.style_for(registry, style_key)

    rendered = pe.counter_rule(style, slide_counter=COUNTER)
    critic_sees = pe.style_zones(style, slide_counter=COUNTER)

    assert rendered, f"{style_key} declares a counter_slot zone, so the renderer must hear about it"
    assert rendered in critic_sees, \
        f"{style_key}: the renderer and the critic describe the badge differently"
    assert not rendered[0].isdigit(), "no ordinal — it is a position in a list this slot has not"


def test_a_registry_style_with_no_counter_slot_still_gets_a_placement() -> None:
    """`anime-noir-statement` declares no `counter_slot` zone, so before D59 a numbered deck in it
    carried a badge in its TEXT block and no instruction anywhere about where to put it."""
    registry = styles.load_registry([pe.PROMPTS_DIR])
    style = styles.style_for(registry, "anime-noir-statement")

    assert "counter_slot" not in {zone.role for zone in style.layout_zones}
    assert pe.counter_rule(style, slide_counter=COUNTER).startswith("counter 07 / 12:")
    assert pe.counter_rule(style) == ""


# --------------------------------------------------------------------- the slot's own contract


def test_the_slot_is_in_the_vocabulary_and_out_of_every_cut_list() -> None:
    """Uncuttable, like the TEXT block whose badge it places (FR-338). A shrink pass that emptied
    this value would hand a slide a `COUNTER RULE (ignore if empty):` label with nothing behind
    it — which is the described-but-unfilled slot the whole feature exists to close."""
    assert "counter_rule" in PLACEHOLDERS
    assert "counter_rule" in pe.allowlist("carousel_slide.md")
    assert "counter_rule" not in pe._TRUNCATION_ORDER
    assert "counter_rule" not in pe._STYLE_TRIO
    for role in ("image_post.md", "reel_seed_frame.md", "reel_director.md", "critic_system.md"):
        assert "counter_rule" not in pe.allowlist(role), \
            f"{role} resolves `{{layout_zones}}` or judges it — it needs no second channel"


def test_the_zone_formatter_is_shared_rather_than_copied() -> None:
    """`_zone_line` is the seam. A zone with an empty `content` or `text_treatment` must still
    render byte-identically through both callers — that is what the shared `rstrip(" —")` buys,
    and it is the case a hand-written second copy would get wrong first."""
    bare = LayoutZone("top-right corner", "", "", role="counter_slot")
    style = make_style(layout_zones=[HEADLINE_ZONE, bare])

    assert pe.counter_rule(style, slide_counter=COUNTER) == "top-right corner"
    assert pe.style_zones(style, slide_counter=COUNTER).splitlines()[1].strip() == \
        "2. top-right corner"
