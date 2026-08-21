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

**Post-pivot state (v2.0.0, W3.5), and what has grown on it.** The excision wave removed the three
retired templates from every surface and left 8 shipped roles (3 global + 4 gpt-image-2 +
1 seedance); every name in `models.PLACEHOLDERS` has had to be reachable from some role ever
since — the W2 transitional carve-outs are gone. The count has since moved with the pipeline, not
with the rules: +4 for the v2.2.0 gauntlet artifacts, -1 for the retired `vision_check_question.md`
(D49), +1 for v2.3.0's `copy_compress_system.md` (D54), +1 for v2.4.0's `style_match_system.md`
(D56), +1 for v2.6.0's `cover_pick_system.md` (D62) and +1 for v2.7.0's
`copy_translate_system.md` (D63), which is **16** today. `SHIPPED_COUNT`
below is that number, and raising it is how a new role is ADMITTED to every check in this module.
"""

from __future__ import annotations

from pathlib import Path

from hypesocials import prompts_engine as pe
from hypesocials.models import (
    CRITIC_PLACEHOLDERS,
    GLOBAL_TEMPLATES,
    PENDING_TEMPLATES,
    PLACEHOLDERS,
    PROFILE_TEMPLATES,
)

#: Every global role plus every role each render profile ships — DERIVED from the two registries
#: rather than retyped, and the same enumeration
#: `test_prompts_engine.test_every_shipped_template_stays_inside_its_role_allowlist` uses, so the
#: two files cannot disagree about what "shipped" means.
#:
#: `PENDING_TEMPLATES` is subtracted (v2.2.0): the gauntlet's four prompt names are declared in
#: `GLOBAL_TEMPLATES` two waves before their files and their built-in twins are authored, so a
#: parity check that read them now would be reading a file that does not exist yet. Emptying that
#: set — which the wave authoring the four prompts does, in the same commit — is what puts them
#: under every check in this module, with no edit here.
SHIPPED: list[tuple[str, str]] = (
    [("", role) for role in GLOBAL_TEMPLATES if role not in PENDING_TEMPLATES]
    + [(profile, role) for profile, names in PROFILE_TEMPLATES.items() for role in names])

#: The count of roles that ship BYTES today: 11 global — `copywriter_system.md`,
#: `copy_compress_system.md` (v2.3.0/D54), `copy_translate_system.md` (v2.7.0/D63),
#: `topic_filter_system.md`, `style_match_system.md`
#: (v2.4.0/D56), `cover_pick_system.md` (v2.6.0/D62), `slide_intel_question.md` and the gauntlet's
#: four (`critic_brief.md`, `critic_system.md`, `critic_craft.md`, `gauntlet_fix.md`) — plus 4
#: gpt-image-2 (the merged `image_post.md` and its three siblings) plus 1 seedance.
#: `vision_check_question.md` is gone with the FR-105 machinery it asked for (v2.2.0/D49), and
#: `PENDING_TEMPLATES` is now empty, so this number is every shipped role there is.
SHIPPED_COUNT = 16

#: `prompts/humanizer_skill.md` ships in the same folder and is NOT a role: it is the vendored MIT
#: `SKILL.md` from github.com/blader/humanizer, kept as the reference the compress template's ~14
#: distilled on-image patterns are derived FROM. The engine never loads it, it has no
#: `GLOBAL_TEMPLATES` entry, no `_ALLOWLIST` row and no built-in twin — an allowlist row for a
#: non-template is exactly the dead-vocabulary drift `prompts_engine` warns about. Named here so
#: that anything in this module which ever enumerates `prompts/*.md` has one place to exempt it
#: from, with the reason attached rather than as a bare literal in a filter.
NOT_A_TEMPLATE = frozenset({"humanizer_skill.md"})


def _no_pending_role_has_already_landed() -> None:
    """The trip-wire that stops `PENDING_TEMPLATES` from outliving its own reason to exist.

    The set is a sequencing carve-out: it disarms every parity check in this module for the roles
    it names, which is correct only while their bytes genuinely do not exist. The failure mode it
    creates is silent — author the four prompts, forget to empty the set, and the suite stays green
    while four templates ship with no byte-parity and no placeholder checking at all. Nothing in a
    green suite would say so.

    So: the moment a pending role has BOTH a file and a built-in twin, it is no longer pending, and
    leaving it listed is the bug. This cannot fire before those bytes are authored, and it fires the
    first time they are.
    """
    landed = sorted(role for role in PENDING_TEMPLATES
                    if _on_disk("", role).is_file() and _built_in_key("", role) in pe._BUILT_INS)
    assert not landed, (
        f"{', '.join(landed)}: authored (file + built-in) but still in PENDING_TEMPLATES. "
        "Remove them from that frozenset and raise SHIPPED_COUNT — until you do, these templates "
        "ship with no parity or placeholder coverage.")


def _built_in_key(profile: str, role: str) -> str:
    return f"{profile}/{role}" if profile else role


def _on_disk(profile: str, role: str) -> Path:
    return pe.PROMPTS_DIR / profile / role if profile else pe.PROMPTS_DIR / role


def test_every_shipped_role_ships_both_a_file_and_a_built_in_default() -> None:
    """The precondition that stops the parity test below from passing vacuously.

    A role with no file has nothing to compare; a role with no built-in has no FR-183 fallback at
    all and would raise `MissingTemplateError` on the day its file went unreadable.

    The count and the ROSTER are both asserted, and neither is redundant: a count alone passes for
    a role deleted and a different one added in the same edit, and a roster alone would not notice
    a profile template going missing (`SHIPPED` spans both registries, `GLOBAL_TEMPLATES` only the
    global one). `style_match_system.md` is the ninth global role, added v2.4.0 (D56/FR-335) — it
    is a SCREEN like `topic_filter_system.md`, never a render prompt, and it earns its place here
    for the ordinary FR-183 reason: a matcher whose built-in twin went missing would raise on the
    one day its file is already broken, and FR-334's fail-open would then be answering for a defect
    it was never meant to cover. `cover_pick_system.md` is the TENTH, added v2.6.0 (D62/FR-352),
    and the same sentence applies to it word for word with `cover_pick`'s FR-351 fail-open in the
    place of FR-334's. `copy_translate_system.md` is the ELEVENTH, added v2.7.0 (D63/FR-344):
    the copy role's third contract, and a translate twin gone missing would silently route a
    `target`-mode deck to the FR-183 fallback the day its file broke — exactly FR-181's case.
    """
    assert len(SHIPPED) == SHIPPED_COUNT, \
        "the shipped role set changed — the parity checks below need it"
    assert set(GLOBAL_TEMPLATES) == {"copywriter_system.md", "copy_compress_system.md",
                                     "copy_translate_system.md", "topic_filter_system.md",
                                     "style_match_system.md", "cover_pick_system.md",
                                     "slide_intel_question.md", "critic_brief.md",
                                     "critic_system.md", "critic_craft.md", "gauntlet_fix.md"}
    assert PENDING_TEMPLATES <= set(GLOBAL_TEMPLATES), \
        "a pending name that is not even declared is a typo, not a sequencing carve-out"
    assert "image_post.md" in PROFILE_TEMPLATES["gpt-image-2"]
    _no_pending_role_has_already_landed()
    for profile, role in SHIPPED:
        assert _on_disk(profile, role).is_file(), f"{_built_in_key(profile, role)}: no file"
        assert _built_in_key(profile, role) in pe._BUILT_INS, \
            f"{_built_in_key(profile, role)}: no built-in default (FR-183)"
    # And nothing extra hides in the table: a built-in for a role that no longer ships is a
    # fallback nobody can reach and a second copy nobody maintains.
    assert set(pe._BUILT_INS) == {_built_in_key(profile, role) for profile, role in SHIPPED}


def test_the_vendored_humanizer_reference_is_not_a_role_on_any_surface() -> None:
    """v2.3.0/D54: `prompts/humanizer_skill.md` is a FILE in `prompts/`, and nothing else.

    It is the MIT `SKILL.md` from github.com/blader/humanizer, vendored so the ~14 on-image
    patterns distilled into `copy_compress_system.md` have a checkable source. The engine never
    loads it. That makes it the one `.md` in this tree that must fail every test in this module —
    it has no role name, no allowlist row, no built-in twin and no parity obligation, and giving it
    any of those would create a fallback nobody can reach and a second copy nobody maintains.

    Asserted rather than assumed, because the natural reflex on seeing a lone unregistered prompt
    file is to "fix" it by adding a row. The file's own header and `prompts/README.md` say why it
    is there; this is where the suite agrees.
    """
    for name in NOT_A_TEMPLATE:
        assert (pe.PROMPTS_DIR / name).is_file(), f"{name}: vendored reference is missing"
        assert name not in GLOBAL_TEMPLATES, f"{name} is not a role — it is a reference document"
        assert name not in pe._ALLOWLIST, f"{name}: an allowlist row for a non-template is drift"
        assert name not in pe._BUILT_INS, f"{name}: a built-in twin for a file nothing renders"
        assert name not in {role for _, role in SHIPPED}


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


def test_the_cover_pick_built_in_is_byte_identical_to_its_file() -> None:
    """v2.6.0 (D62, FR-352): the cover judge, held to FULL parity from its first commit.

    The placeholder-set check above already covers it — both copies name `cover_contract` and
    `cover_candidates` — and that is exactly the cover a drift would hide behind. What decides
    this call is not which slots it resolves but the JUDGING ORDER inside the prose: style
    contract first, thumbnail legibility second, stopping power only on a tie. A twin that lost
    that order would still name the right two slots while quietly picking the prettiest frame —
    on the one day the file it stands in for is already broken, and for the one frame every other
    slide of the deck is then built from.

    The two spot checks are the contract `cover_pick` parses rather than prose: the answer is a
    candidate ID (`_chosen` refuses anything else and the deck falls back to candidate 1), and
    `counter: none` has to mean "no badge at all" or an uncounted deck is judged by a rule D59
    deleted.
    """
    on_disk = _on_disk("", "cover_pick_system.md").read_text(encoding="utf-8")

    assert pe._BUILT_INS["cover_pick_system.md"] == on_disk, \
        "cover_pick_system.md: the built-in drifted from its file — re-sync it"
    flat = " ".join(on_disk.split())
    assert "`chosen` is one of the candidate ids listed in the block above, as an integer" in flat, \
        "the answer contract `cover_pick._chosen` polices is not in the prompt"
    assert "NO counter, page number, chip or badge anywhere at all when `counter:` says none" in \
        flat, "an uncounted deck's candidates are judged against nothing (D59/FR-338)"


def test_the_four_gauntlet_built_ins_are_byte_identical_to_their_files() -> None:
    """The gauntlet's prompts, held to FULL parity (v2.2.0, D49) — the successors of the retired
    `vision_check_question.md` check, which drifted for three waves under exactly this cover.

    Three of the four name placeholders and are therefore already covered by the set check above;
    `gauntlet_fix.md` names NONE, because its canned remedies are selected in code by
    `(code, zone)`, so the set check passes vacuously for it and byte parity is the only guarantee
    it can have. All four get it, and each is spot-checked on the ONE structural contract its
    parser or its schema depends on: the per-critic enums (`gauntlet._schema` is strict, so a
    fallback offering the wrong codes loses that critic for the whole deck), and the four `##`
    section headers `gauntlet._sheet()` splits the remedy file on.
    """
    for role in ("critic_brief.md", "critic_system.md", "critic_craft.md", "gauntlet_fix.md"):
        on_disk = _on_disk("", role).read_text(encoding="utf-8")
        assert pe._BUILT_INS[role] == on_disk, f"{role}: the built-in drifted from its file"
    brief = _on_disk("", "critic_brief.md").read_text(encoding="utf-8")
    assert "invented_text" in brief and "identity_leak" in brief, \
        "the brief critic's strict enum is not in its own prompt"
    craft = _on_disk("", "critic_craft.md").read_text(encoding="utf-8")
    assert "missing_text" not in craft, \
        "craft never reports a word missing — the enum partition is the whole discipline"
    sheet = _on_disk("", "gauntlet_fix.md").read_text(encoding="utf-8")
    for section in ("## PRECEDENCE", "## ORDER", "## REMEDIES", "## CLOSING"):
        assert section in sheet, f"gauntlet_fix.md: {section} is what the sheet parser splits on"


def _critic_system_copies() -> tuple[tuple[str, str], ...]:
    """The on-disk style critic and its built-in twin, as (origin, text) pairs."""
    path = _on_disk("", "critic_system.md")
    return ((str(path), path.read_text(encoding="utf-8")),
            ("built-in critic_system.md", pe._BUILT_INS["critic_system.md"]))


def test_both_critic_system_copies_judge_consistency_against_the_frame_1_baseline() -> None:
    """Session 5.8/F9-B at the parity level: WHO the style critic compares a frame to.

    Canary #3 (`output/20260819_191734_0jc2`) was blocked by a frame that had passed two rounds
    cleanly and was named for the first time in the third — because the template defined
    `style_consistency` as sibling-relative, so re-rendering frames 2 and 3 toward each other MOVED
    the baseline the untouched frame 4 was then judged against. A moving reference makes the whole
    fix loop chase itself: every round produces a new majority and a new deviant. F9-B pins the
    reference down — frame 1 is the anchor this deck was built from, every consistency verdict is
    measured against IT, and frame 1 answers to the style contract alone.

    Prose is not diffed here (see the module docstring); these four stems are the load-bearing
    sentences of that framing, matched against the FLATTENED text so a re-wrap of hand-wrapped
    prose cannot break a pin on a sentence that did not change. The `sibling` assertion is the
    regression that actually matters: the old wording is the natural way to write this rule, and
    it will creep back the first time somebody edits the section without knowing why it is worded
    the way it is. Both copies, because a fallback that judges by a different rule than its file
    fires at the one moment nobody is reading the prompt (FR-183).
    """
    for origin, text in _critic_system_copies():
        flat = " ".join(text.split())
        for phrase in ("FRAME 1 IS THE BASELINE",     # the rule, stated once and in full
                       "never from each other",       # the reference is fixed, not relative
                       "a majority never makes",      # …and a crowd cannot outvote the anchor
                       "departs from FRAME 1"):       # the `style_consistency` definition itself
            assert phrase in flat, f"{origin}: the anchor-baseline framing is missing ({phrase!r})"
        assert "sibling" not in flat.lower(), \
            f"{origin}: sibling-relative wording is back — F9-B's whole point is that a frame " \
            "is judged against frame 1, never against the other frames"


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


def test_both_carousel_copies_sanction_tool_marks_and_defer_to_the_counter_rule() -> None:
    """v2.1.2 (D-A/D-D) and D59/FR-338 at the parity level — contracts a placeholder-set check
    cannot see.

    D-A: `{{tool_marks}}` is worthless without the rule attached to it, so both copies must carry
    the block AND the sentence that makes a named mark render for real. D-D: the conditional badge
    instruction is DELETED, and a template that still tells the model to letter this slide's
    position "exactly as the FORMAT line states" re-opens the invented-counter defect the moment
    its file goes unreadable.

    **D59 moved the counter's WORDS out of the prose and into `{{counter_rule}}`**, so the absence
    sentence is no longer written here: it is `prompts_engine._NO_COUNTER_LINE`, delivered through
    the slot on the decks that need it, and a style that never described a chip now hears nothing
    about counters at all. What the prose still owes is the RANKING — the slot's line outranks
    every chip, badge and page-number device STYLE_DNA describes — because without it the model
    reconciles two descriptions of one thing per slide, which is how byte-identical instructions
    still produce a drifting deck (M9).
    """
    for origin, text in _carousel_slide_copies():
        # The templates are hand-wrapped prose, so every phrase is matched against the flattened
        # text: a sentence that survives a re-wrap is the thing worth pinning, not its line breaks.
        flat = " ".join(text.split())
        assert "{{tool_marks}}" in text, f"{origin}: the sanctioned-marks slot is missing"
        assert "TOOL MARKS (sanctioned real logos — ignore if empty):" in flat, \
            f"{origin}: the slot arrived without its labelled block"
        assert "in its own true brand colours" in flat, f"{origin}: the D-A rule is not attached"
        assert "renders as the real logo" in flat, f"{origin}: the D-A exception is not stated"
        assert "{{counter_rule}}" in text, f"{origin}: FR-338's counter slot is missing"
        assert "COUNTER RULE (ignore if empty):" in flat, \
            f"{origin}: the slot arrived without its labelled block"
        assert "outranks every chip, badge or page-number device STYLE_DNA describes" in flat, \
            f"{origin}: the slot arrived without the ranking that makes it binding"
        assert 'no chip, badge, page number or "N of M" on ANY slide, slide 1 included' in flat, \
            f"{origin}: an absence line is not told what an absence means"
        assert 'no position badge, no "N of M", no page' not in flat, \
            f"{origin}: the absence sentence belongs to `_NO_COUNTER_LINE`, not to the prose (D59)"
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

    The last two phrases are Session 5.6/F7-B's badge lock, and they are pinned HERE because this
    block is under a standing byte budget (`tests/test_prompt_fit.py`) and re-compression is the
    normal way it changes. Without the first, gpt-image-2 re-invents where the FR-313 position
    badge sits on every slide and the system critic reports `counter_placement` on a deck nobody
    mis-ordered; without the second, "copy the badge" reads as "copy the badge's DIGITS" and every
    slide claims to be slide 1.
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
                       "Image 1 wins; where they disagree about which content elements",
                       "A QUOTED POSITION BADGE KEEPS IMAGE 1'S CORNER",
                       "its digits alone are this slide's own"):
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
    # The critic vocabulary is exempt only while its roles are still `PENDING_TEMPLATES`: the names
    # are frozen in `models` one wave before the `_ALLOWLIST` rows that make them reachable exist.
    # The moment those four prompts ship, the exemption evaporates on its own and this test starts
    # demanding a row for every critic name — which is the point.
    pending = CRITIC_PLACEHOLDERS if PENDING_TEMPLATES else frozenset()
    unreachable = PLACEHOLDERS - reachable - pending

    assert not unreachable, f"placeholder(s) no role can resolve: {sorted(unreachable)}"
    assert CRITIC_PLACEHOLDERS <= PLACEHOLDERS, \
        "the frozen critic vocabulary names something outside models.PLACEHOLDERS"


# ------------------------------------------ D59: the empty-zone rule (FR-340) and the slot (338)
#
# Both copies again, and for the reason this whole module exists: a fallback fires only when the
# file it stands in for is already broken, so a built-in that still carries the RETIRED licence
# would re-open the defect at the one moment nobody is reading the prompt.

#: The licence D59 retired, in both spellings it ever shipped in. It read: a text zone with no
#: string quoted "renders empty or as a NON-TEXT GRAPHIC ELEMENT (a rule, a bar, a shape, negative
#: space)". Written to stop the model inventing WORDS, it turned out to license the model to
#: invent FURNITURE instead — the D59 census found empty chips, bare rules and blank cards drawn
#: where a style's row grammar described a device and this deck had quoted nothing to put in it.
#: FR-340's replacement removes the alternative altogether: the zone is left OUT of the frame.
_RETIRED_EMPTY_ZONE = ("non-text graphic element", "renders empty or as a non-text graphic")

#: FR-340's replacement, both halves. The first forbids the substitute object; the second is the
#: one that actually governs a repeating device (`icon-ledger-carousel`'s ledger rows, a card
#: grid, a chip row): it exists ONCE PER QUOTED LINE, so a cover quoting one headline draws one
#: row and a deck quoting nothing draws none.
_EMPTY_ZONE_RULE = ("never with a bar, rule, block or placeholder standing in for words",
                    "exists once per quoted line and not at all when none is quoted")

#: FR-338's slot, pinned as the WHOLE line rather than as the label alone: the label without its
#: placeholder is a heading over nothing, and the placeholder without its "(ignore if empty)" is
#: an instruction the model must obey on a deck where `counter_rule` renders to "".
_COUNTER_SLOT_LINE = "COUNTER RULE (ignore if empty): {{counter_rule}}"


def _copies(profile: str, role: str) -> tuple[tuple[str, str], ...]:
    """A role's on-disk bytes and its built-in twin, as (origin, FLATTENED text) pairs.

    Flattened for the reason `_carousel_slide_copies` above states: these templates are
    hand-wrapped prose, so a phrase that survives a re-wrap is the thing worth pinning and its
    line breaks are not. Generalised over (profile, role) because FR-340 lands on four roles at
    once and a fourth bespoke pair-builder would be three too many.
    """
    key = _built_in_key(profile, role)
    return ((str(_on_disk(profile, role)),
             " ".join(_on_disk(profile, role).read_text(encoding="utf-8").split())),
            (f"built-in {key}", " ".join(pe._BUILT_INS[key].split())))


def test_fr340_the_retired_empty_zone_licence_is_in_no_prompt_this_engine_can_load() -> None:
    """D59's deletion, checked as one — over EVERY prompt, not just the two that were edited.

    The licence was one sentence in `carousel_slide.md` and one in `image_post.md`, but the shape
    of the mistake is copy-paste: it is the natural thing to write when a template needs to say
    what happens to an unfilled zone, and the next render template authored will want to say it
    again. So the scan is the whole of `prompts/**/*.md` plus every `_BUILT_INS` value, which
    makes the guard cost nothing to keep and impossible to route around by adding a fifth image
    role.

    `prompts/README.md` is in scope on purpose although it is not a role (`NOT_A_TEMPLATE`, and
    the same reasoning applies to it): its "do not delete" list is what a future author reads
    BEFORE editing a template, so a retired rule left standing there is the licence coming back
    one commit later.

    One copy of the retired wording does survive, and it is named here rather than left to be
    rediscovered: `prompts_engine._EXCL` (`prompts_engine.py:1699`), a pre-F20 assembly fragment
    from when built-ins were composed from constants instead of being byte copies of their files.
    It has no callers left, which is exactly what the last assertion pins — the day someone
    assembles it into a template again, this fires, and the scrub becomes due.
    """
    stale: list[str] = []
    for path in sorted(pe.PROMPTS_DIR.rglob("*.md")):
        flat = " ".join(path.read_text(encoding="utf-8").split())
        stale += [f"{path}: {phrase!r}" for phrase in _RETIRED_EMPTY_ZONE if phrase in flat]
    for key, text in sorted(pe._BUILT_INS.items()):
        flat = " ".join(text.split())
        stale += [f"built-in {key}: {phrase!r}" for phrase in _RETIRED_EMPTY_ZONE if phrase in flat]

    assert stale == [], (
        "FR-340: the retired empty-zone licence is back. A text zone with nothing quoted for it "
        "is LEFT OUT of the frame — it is never filled with a stand-in object:\n  "
        + "\n  ".join(stale))
    assert not any(pe._EXCL in text for text in pe._BUILT_INS.values()), \
        "prompts_engine._EXCL is being assembled into a built-in again and it still carries the " \
        "pre-FR-340 licence ('leave it empty or fill it with a non-text graphic element') — " \
        "scrub the constant or delete it"


def test_fr340_both_image_templates_state_the_empty_zone_rule_in_both_copies() -> None:
    """The positive half: the licence is not merely gone, the rule that replaced it is present.

    A deletion on its own would leave the two image templates SILENT about an unfilled zone, and
    silence is what the licence was written to fix — the model fills the hole with whatever the
    style described. Both sentences are required on both templates: the first governs a single
    zone, the second governs a REPEATING device, and `icon-ledger-carousel`'s rows are the case
    that proved they are not the same rule (a deck can draw the right number of nothing and still
    draw eight empty ledger cards).

    `carousel_anchor_instruction.md` and `reel_seed_frame.md` are held to their own wordings in
    the test below rather than to these — they are not full render templates and never carried
    the licence.
    """
    missing: list[str] = []
    for role in ("carousel_slide.md", "image_post.md"):
        for origin, flat in _copies("gpt-image-2", role):
            missing += [f"{origin}: {phrase!r}"
                        for phrase in _EMPTY_ZONE_RULE if phrase not in flat]

    assert missing == [], \
        "FR-340: an image template lost half the empty-zone rule:\n  " + "\n  ".join(missing)


def test_fr340_the_anchor_block_leaves_the_zone_out_and_the_seed_frame_stays_wordless() -> None:
    """The two roles FR-340 touched differently, pinned so neither drifts toward the other.

    `carousel_anchor_instruction.md` is rendered OVER a reference role line (FR-190) and lives
    under a standing byte budget (`tests/test_prompt_fit.py`), so it states the rule in the short
    form — the zone "is left out — no bar, rule or placeholder in its place". Re-compression is
    the normal way this block changes, which is why the phrase is pinned here rather than trusted
    to survive the next squeeze.

    `reel_seed_frame.md` is UNCHANGED by D59 and that is the assertion: it already said an
    unquoted zone "stays wordless", which is the same rule for a frame that carries no repeating
    device and no counter at all. Pinning the absence of an edit is what stops a future wave from
    "harmonising" the four templates onto one sentence and quietly giving the seed frame a ledger
    grammar it has no use for.
    """
    for origin, flat in _copies("gpt-image-2", "carousel_anchor_instruction.md"):
        assert "no bar, rule or placeholder in its place" in flat, \
            f"{origin}: FR-340's short form is gone — a re-compression ate the rule"
    for origin, flat in _copies("gpt-image-2", "reel_seed_frame.md"):
        assert "stays wordless" in flat, f"{origin}: the seed frame's own empty-zone rule is gone"
        assert all(phrase not in flat for phrase in _RETIRED_EMPTY_ZONE), \
            f"{origin}: the seed frame never carried the licence and must not acquire it"


def test_fr338_the_counter_rule_slot_is_on_the_carousel_slide_and_on_no_other_template() -> None:
    """FR-338's placement, which is a decision and not an accident: SLIDES ONLY.

    A counter is a property of a DECK — "07 / 12" means nothing on a single image post and nothing
    on a reel's seed frame, and `prompts_engine.counter_rule` is only ever handed a
    `slide_counter` by `generate.carousel`. So the slot is in `_ALLOWLIST` for this one role, and
    a second template naming it would either resolve to a value nobody built (an
    `UnresolvedPlaceholderError` that fails the creative before submission, FR-260) or — worse, if
    somebody "fixed" that by widening the allowlist — start telling image posts where to put a
    page number.

    The presence half overlaps with the tool-marks test above by design: that one pins the
    RANKING sentence that makes the slot binding, this one pins the LINE, whole, and the
    exclusivity around it. `prompts/README.md` names the slot in prose and is correctly not in
    scope — it is documentation, not a role, and the loop below walks `SHIPPED`.
    """
    for origin, flat in _copies("gpt-image-2", "carousel_slide.md"):
        assert _COUNTER_SLOT_LINE in flat, \
            f"{origin}: FR-338's slot line is not intact — the label and the placeholder are " \
            "one line, and '(ignore if empty)' is what makes an uncounted deck legal"

    elsewhere: list[str] = []
    for profile, role in SHIPPED:
        if (profile, role) == ("gpt-image-2", "carousel_slide.md"):
            continue
        for origin, flat in _copies(profile, role):
            if "{{counter_rule}}" in flat:
                elsewhere.append(origin)

    assert elsewhere == [], (
        "FR-338: `{{counter_rule}}` is a carousel-slide slot. Nothing else is ever handed a "
        f"`slide_counter`, so this resolves to nothing and fails the creative: {elsewhere}")
    assert {role for role, allowed in pe._ALLOWLIST.items() if "counter_rule" in allowed} == \
        {"carousel_slide.md"}, "the allowlist is the gate; it must agree with the templates"
