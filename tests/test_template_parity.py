"""FR-183 — the built-in default and its on-disk template are ONE prompt kept in TWO copies.

`prompts_engine._BUILT_INS` carries a compact copy of every shipped template, used when the file
under `prompts/` is missing, unreadable, or names a placeholder its role may not resolve. That is
a real requirement and a real second copy of the same text — and until this file existed there
was no test asserting the two agree about anything.

They drifted twice in one session (2026-08-11): once a built-in gained a new slot without the
guardrail sentence that ranks it below the attached references, and once a built-in missed a new
slot and its instruction entirely. Both would have shipped silently, because a fallback only fires
when a template file is already broken — the one moment nobody is reading the prompt.

Prose cannot be diffed mechanically and this file does not try. What CAN be checked is the part
that decides what data reaches the model: **the placeholder set**. A built-in that names fewer
slots than its file silently drops material (the operator's art direction, the brand accent, the
budget line); one that names more resolves values the file never asked for. Either way the
fallback renders a different prompt from the one the run was configured with.

Everything here is a pure read of `prompts/` and the module's own tables. No network, no run
folder, no temp files.

**Final post-pivot state (v2.0.0, W3.5).** The excision wave removed the three retired templates
from every surface, so the shipped count is the final 8 (3 global + 4 gpt-image-2 + 1 seedance)
and every name in `models.PLACEHOLDERS` must be reachable from some role — the W2 transitional
carve-outs are gone.
"""

from __future__ import annotations

from pathlib import Path

from hypesocials import prompts_engine as pe
from hypesocials.models import GLOBAL_TEMPLATES, PLACEHOLDERS, PROFILE_TEMPLATES

#: Every global role plus every role each render profile ships — DERIVED from the two registries
#: rather than retyped, and the same enumeration
#: `test_prompts_engine.test_every_shipped_template_stays_inside_its_role_allowlist` uses, so the
#: two files cannot disagree about what "shipped" means.
SHIPPED: list[tuple[str, str]] = (
    [("", role) for role in GLOBAL_TEMPLATES]
    + [(profile, role) for profile, names in PROFILE_TEMPLATES.items() for role in names])

#: The FINAL count (contracts item 4, set by the W3.5 excision): 3 global —
#: `copywriter_system.md`, `vision_check_question.md`, `topic_filter_system.md` — plus 4
#: gpt-image-2 (the merged `image_post.md` and its three siblings) plus 1 seedance.
SHIPPED_COUNT = 9


def _built_in_key(profile: str, role: str) -> str:
    return f"{profile}/{role}" if profile else role


def _on_disk(profile: str, role: str) -> Path:
    return pe.PROMPTS_DIR / profile / role if profile else pe.PROMPTS_DIR / role


def test_every_shipped_role_ships_both_a_file_and_a_built_in_default() -> None:
    """The precondition that stops the parity test below from passing vacuously.

    A role with no file has nothing to compare; a role with no built-in has no FR-183 fallback at
    all and would raise `MissingTemplateError` on the day its file went unreadable.
    """
    assert len(SHIPPED) == SHIPPED_COUNT, \
        "the shipped role set changed — the parity checks below need it"
    assert set(GLOBAL_TEMPLATES) == {"copywriter_system.md", "vision_check_question.md",
                                     "topic_filter_system.md", "slide_intel_question.md"}
    assert "image_post.md" in PROFILE_TEMPLATES["gpt-image-2"]
    for profile, role in SHIPPED:
        assert _on_disk(profile, role).is_file(), f"{_built_in_key(profile, role)}: no file"
        assert _built_in_key(profile, role) in pe._BUILT_INS, \
            f"{_built_in_key(profile, role)}: no built-in default (FR-183)"
    # And nothing extra hides in the table: a built-in for a role that no longer ships is a
    # fallback nobody can reach and a second copy nobody maintains.
    assert set(pe._BUILT_INS) == {_built_in_key(profile, role) for profile, role in SHIPPED}


def test_a_built_in_names_exactly_the_placeholders_its_on_disk_template_names() -> None:
    """The mechanically checkable half of FR-183 parity, and the one that has actually broken.

    Reported as a per-role diff rather than a bare inequality, because "the built-in is missing
    `niche_visual_world`" names the fix and "sets differ" does not.
    """
    drift: list[str] = []
    for profile, role in SHIPPED:
        key = _built_in_key(profile, role)
        on_disk = set(pe._names(_on_disk(profile, role).read_text(encoding="utf-8")))
        built_in = set(pe._names(pe._BUILT_INS[key]))
        if on_disk != built_in:
            drift.append(f"{key}: file-only={sorted(on_disk - built_in)} "
                         f"built-in-only={sorted(built_in - on_disk)}")
    assert not drift, "FR-183 built-in defaults drifted from their templates:\n" + "\n".join(drift)


def test_the_slide_intel_built_in_is_byte_identical_to_its_file() -> None:
    """The one role where parity can be checked in full, so it is (FR-306).

    `slide_intel_question.md` carries ZERO placeholders — the images are the whole variable input —
    so the placeholder-set check above passes vacuously for it and would have kept passing while
    the two copies asked for different things. They did: the file gained item 2, CHROME TEXT, and
    the built-in went on asking for three items, which matters because `sources.slide_intel` sends
    a STRICT schema that REQUIRES `chrome_text` on every slide. A fallback that asks for the wrong
    shape loses the whole vision pass at the one moment its file is already broken.
    """
    on_disk = _on_disk("", "slide_intel_question.md").read_text(encoding="utf-8")

    assert pe._BUILT_INS["slide_intel_question.md"] == on_disk
    assert "chrome_text" in on_disk, "the strict schema requires it; the prompt must ask for it"


def test_the_vision_check_built_in_is_byte_identical_to_its_file() -> None:
    """The second placeholder-free role, held to the same full parity (FR-105, v2.1.1).

    `vision_check_question.md` names ZERO placeholders — the images and the carrier turn are the
    whole variable input — so the placeholder-set check above passes vacuously for it, and the two
    copies drifted for three waves under that cover (SESSION C and SESSION G both noted it, and
    nothing failed). It stopped being cosmetic when the question grew its third defect: the
    built-in went on asking two questions while `vision_check._SCHEMA` began REQUIRING
    `text_mismatch` on every verdict, so the fallback would lose the whole check at the one moment
    its file is already broken.
    """
    on_disk = _on_disk("", "vision_check_question.md").read_text(encoding="utf-8")

    assert pe._BUILT_INS["vision_check_question.md"] == on_disk
    assert "TEXT MISMATCH" in on_disk, "the strict schema requires it; the prompt must ask for it"
    assert "(none)" in on_disk, "the carrier sends that token for a wordless-by-design image"


def test_the_carousel_copies_both_teach_the_panel_text_label() -> None:
    """B6 (2026-08-13) at the parity level: `_onimage_text` emits a `panel_text` block for a mapped
    slide, and a template that never names that label leaves the model to guess what it is.

    Prose is not diffed here (see the module docstring), but a LABEL is not prose — it is the
    contract between `prompts_engine._onimage_text` and the template, exactly the kind of drift a
    placeholder-set check cannot see. Both copies must also keep the TEXT-block contract intact.
    """
    for origin, text in ((str(_on_disk("gpt-image-2", "carousel_slide.md")),
                          _on_disk("gpt-image-2", "carousel_slide.md").read_text(encoding="utf-8")),
                         ("built-in gpt-image-2/carousel_slide.md",
                          pe._BUILT_INS["gpt-image-2/carousel_slide.md"])):
        assert "panel_text" in text, f"{origin}: never names the label the TEXT block emits"
        assert "no character budget" in text, f"{origin}: still prices the panel text"
        assert "ONLY source of renderable words" in text, f"{origin}: TEXT-block contract lost"


def _carousel_slide_copies() -> tuple[tuple[str, str], ...]:
    """The on-disk slide template and its built-in twin, as (origin, text) pairs."""
    path = _on_disk("gpt-image-2", "carousel_slide.md")
    return ((str(path), path.read_text(encoding="utf-8")),
            ("built-in gpt-image-2/carousel_slide.md",
             pe._BUILT_INS["gpt-image-2/carousel_slide.md"]))


def test_both_carousel_copies_sanction_tool_marks_and_state_the_counter_absence() -> None:
    """v2.1.2 (D-A/D-D) at the parity level — two contracts a placeholder-set check cannot see.

    D-A: `{{tool_marks}}` is worthless without the rule attached to it, so both copies must carry
    the block AND the sentence that makes a named mark render for real. D-D: the conditional badge
    instruction is DELETED, and a template that still tells the model to letter this slide's
    position "exactly as the FORMAT line states" re-opens the invented-counter defect the moment
    its file goes unreadable. The absence line is asserted against the engine's own constant, so
    the prompt and `_style_zones` cannot describe an uncounted deck in two different ways.
    """
    absence = 'no position badge, no "N of M", no page number anywhere in the frame.'
    assert pe._NO_COUNTER_LINE.endswith(absence)
    for origin, text in _carousel_slide_copies():
        # The templates are hand-wrapped prose, so every phrase is matched against the flattened
        # text: a sentence that survives a re-wrap is the thing worth pinning, not its line breaks.
        flat = " ".join(text.split())
        assert "{{tool_marks}}" in text, f"{origin}: the sanctioned-marks slot is missing"
        assert "TOOL MARKS (sanctioned real logos — ignore if empty):" in flat, \
            f"{origin}: the slot arrived without its labelled block"
        assert "in its own true brand colours" in flat, f"{origin}: the D-A rule is not attached"
        assert "renders as the real logo" in flat, f"{origin}: the D-A exception is not stated"
        assert absence in flat, f"{origin}: an uncounted deck is not told the counter is absent"
        assert "counter (render verbatim)" not in flat, \
            f"{origin}: the label belongs to the TEXT block the engine builds, not to the prose"
        assert "exactly as the FORMAT line states" not in flat, \
            f"{origin}: the deleted badge instruction came back (D-D)"
        assert "position badge excepted" not in flat, \
            f"{origin}: the TEXT block is the only source of renderable words, full stop (D-D)"


def test_the_two_carousel_built_ins_are_byte_identical_to_their_files() -> None:
    """Both carousel copies are maintained as one text, so the cheap check is the full one.

    Nothing forces a built-in to be byte-identical to its file (FR-183 allows a compact copy), but
    these two ARE, and a wave that edits the slide template without re-syncing the twin ships a
    fallback describing a different deck — one that still letters a position badge, or one that
    knows nothing about sanctioned marks. Byte identity is the cheapest way to keep the two copies
    honest, and re-syncing is a copy-paste.
    """
    for profile, role in (("gpt-image-2", "carousel_slide.md"),
                          ("gpt-image-2", "carousel_anchor_instruction.md")):
        key = _built_in_key(profile, role)
        assert pe._BUILT_INS[key] == _on_disk(profile, role).read_text(encoding="utf-8"), \
            f"{key}: the built-in drifted from its file — re-sync it"


def test_the_anchor_instruction_locks_the_scene_not_only_the_layout() -> None:
    """v2.1.2 task 2: Image 1 is the deck's SCENE as well as its grid.

    The anchor slide is the only picture of this deck that exists, and a body slide that kept the
    palette but moved to another room read as a different deck. The visual brief describes the
    SOURCE deck's slide, so it may name a scene this deck never had — hence the explicit
    precedence rather than a general "Image 1 wins".
    """
    for origin, text in ((str(_on_disk("gpt-image-2", "carousel_anchor_instruction.md")),
                          _on_disk("gpt-image-2", "carousel_anchor_instruction.md")
                          .read_text(encoding="utf-8")),
                         ("built-in gpt-image-2/carousel_anchor_instruction.md",
                          pe._BUILT_INS["gpt-image-2/carousel_anchor_instruction.md"])):
        flat = " ".join(text.split())
        for phrase in ("the same room", "the same camera position", "the same background",
                       "this slide's text block sits exactly where Image 1's text block sits",
                       "THE SCENE IS IMAGE 1'S", "CONTENT ELEMENTS only",
                       "Image 1 wins; where they disagree about which content elements"):
            assert phrase in flat, f"{origin}: the scene lock is missing ({phrase!r})"


def test_every_placeholder_in_either_copy_is_in_vocabulary_and_in_that_roles_allowlist() -> None:
    """Both copies obey FR-260/261, checked together.

    A built-in that names an out-of-role placeholder cannot render at all: `render()` treats it as
    unresolved and fails the creative — at the exact moment the file it was standing in for is
    already broken. `test_prompts_engine` asserts this for the built-ins alone; here both copies
    are held to it in one pass, so a file and its fallback cannot pass separately and disagree.
    """
    for profile, role in SHIPPED:
        key = _built_in_key(profile, role)
        allowed = pe.allowlist(role)
        for origin, text in ((str(_on_disk(profile, role)),
                              _on_disk(profile, role).read_text(encoding="utf-8")),
                             (f"built-in {key}", pe._BUILT_INS[key])):
            names = set(pe._names(text))
            assert names <= PLACEHOLDERS, f"{origin}: unknown placeholder(s) " \
                                          f"{sorted(names - PLACEHOLDERS)}"
            assert names <= allowed, f"{origin}: out-of-role placeholder(s) " \
                                     f"{sorted(names - allowed)}"


def test_the_allowlist_table_itself_names_nothing_outside_the_placeholder_vocabulary() -> None:
    """`_ALLOWLIST` is the gate; a typo inside it is a slot that can never resolve for anyone.

    `_unresolvable_names` checks a template against BOTH the vocabulary and the allowlist, so a
    misspelled allowlist entry never fails loudly — it just silently allows a name no builder
    produces, and the template that dared to use it falls back to its built-in instead.
    """
    for role, allowed in pe._ALLOWLIST.items():
        assert allowed <= PLACEHOLDERS, f"{role}: allowlists unknown name(s) " \
                                        f"{sorted(allowed - PLACEHOLDERS)}"


def test_no_placeholder_in_the_vocabulary_is_unreachable() -> None:
    """A name in `models.PLACEHOLDERS` that no role may resolve is dead vocabulary.

    Not fatal, but it is how a slot gets built, documented and wired into `build_context` while no
    template can ever show it to a model — which is precisely the shape A15 found `niche_descriptor`
    in for render roles. Full reachability is required since the W3.5 excision dropped the two
    W2 transitional orphans from the vocabulary itself.
    """
    reachable = set().union(*pe._ALLOWLIST.values())
    unreachable = PLACEHOLDERS - reachable

    assert not unreachable, f"placeholder(s) no role can resolve: {sorted(unreachable)}"
