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

**W2 transitional state (v2.0.0).** The pivot's ADDITIVE-THEN-SUBTRACTIVE migration means the new
`image_post.md` and `topic_filter_system.md` ship BESIDE the three templates they retire, so every
count in this file is 11 rather than the final 8. `TRANSITIONAL_SHIPPED` and
`TRANSITIONAL_ORPHANS` below are the two places that number lives, and both are written to fail
loudly at W3.5 rather than to be quietly right.
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

#: The W2 TRANSITIONAL count (contracts item 4): 4 global — `style_brief_system.md`,
#: `copywriter_system.md`, `vision_check_question.md` and the new `topic_filter_system.md` — plus
#: 6 gpt-image-2 (the merged `image_post.md` shipping BESIDE the two files it replaces) plus 1
#: seedance. **W3.5 deletes `style_brief_system.md`, `image_single_post.md` and `image_direct.md`
#: from every surface and this number becomes 8** (3 global + 4 gpt-image-2 + 1 seedance); the
#: excision wave updates it here, and this assertion is what makes it notice.
TRANSITIONAL_SHIPPED = 11


def _built_in_key(profile: str, role: str) -> str:
    return f"{profile}/{role}" if profile else role


def _on_disk(profile: str, role: str) -> Path:
    return pe.PROMPTS_DIR / profile / role if profile else pe.PROMPTS_DIR / role


def test_every_shipped_role_ships_both_a_file_and_a_built_in_default() -> None:
    """The precondition that stops the parity test below from passing vacuously.

    A role with no file has nothing to compare; a role with no built-in has no FR-183 fallback at
    all and would raise `MissingTemplateError` on the day its file went unreadable.
    """
    assert len(SHIPPED) == TRANSITIONAL_SHIPPED, \
        "the shipped role set changed — the parity checks below need it"
    assert set(GLOBAL_TEMPLATES) == {"style_brief_system.md", "copywriter_system.md",
                                     "vision_check_question.md", "topic_filter_system.md"}
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


#: The two names that are IN the vocabulary and reachable from no role during the W2->W3.5
#: window. Both belong to withdrawn call paths — `style_brief_summary` described the vision
#: analysis to the copywriter, `inspiration_exemplars` carried A16's pooled `.txt` captions — and
#: contracts item 2 keeps the NAMES in `models.PLACEHOLDERS` until the W3.5 excision while T2.5's
#: rewritten `copywriter_system.md` and T2.6's allowlist already stopped naming them. Anything
#: else unreachable is a real defect: a slot built and wired that no template can ever show.
TRANSITIONAL_ORPHANS = frozenset({"style_brief_summary", "inspiration_exemplars"})


def test_no_placeholder_in_the_vocabulary_is_unreachable_except_the_two_transitional_orphans() -> None:
    """A name in `models.PLACEHOLDERS` that no role may resolve is dead vocabulary.

    Not fatal, but it is how a slot gets built, documented and wired into `build_context` while no
    template can ever show it to a model — which is precisely the shape A15 found `niche_descriptor`
    in for render roles. The two named exceptions are scheduled deletions, and the second assertion
    is what makes W3.5 come back here: once they leave the vocabulary this list must shrink to
    nothing rather than describe names that no longer exist.
    """
    reachable = set().union(*pe._ALLOWLIST.values())
    unreachable = PLACEHOLDERS - reachable

    assert unreachable <= TRANSITIONAL_ORPHANS, \
        f"placeholder(s) no role can resolve: {sorted(unreachable - TRANSITIONAL_ORPHANS)}"
    assert TRANSITIONAL_ORPHANS <= PLACEHOLDERS, \
        "the W3.5 excision landed — drop TRANSITIONAL_ORPHANS and require full reachability"
