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
SHIPPED_COUNT = 8


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
                                     "topic_filter_system.md"}
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
