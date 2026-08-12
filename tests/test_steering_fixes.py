"""A12 / A15 — the two operator steering levers the topic-first pivot KEEPS.

The five levers this file was written for (A11, A12, A15, A16, A17) were each a complete,
allowlist-audited pipeline that simply never carried a value. Three of them are gone with
v2.0.0, and their pruning is recorded here rather than in a commit message, because "this
assertion disappeared" and "this behaviour disappeared" have to be told apart later:

- **A11 (`{{brand_accent}}` + `niche.brand`) — PRUNED.** D43/§1.4 absorbs `niche.brand` into
  the top-level `branding:` section and routes render-side brand influence through two new
  channels (`{{branding_block}}` and the TEXT-block wordmark). `build_context` loses the
  `brand_accent`/`brand_product_nouns` parameters in the same wave, so every A11 assertion is
  about a channel that no longer exists. Its successor coverage is `tests/test_branding.py`
  (plan §3 T4.1), which asserts the per-profile block, the `never:` lines, the wordmark's
  TEXT-block route and the ratio determinism.
- **A16 (Inspiration `.txt` copy exemplars) — PRUNED.** The digest/exemplar channel is dead
  (operator decision 1); `copy_exemplars` leaves `build_context` and `inspiration.py` is
  deleted at W3.5. Keeping the assertions would have made this whole module a collection-time
  ImportError the moment that file goes.
- **A17 (Inspiration window rotation) — PRUNED, re-homed not lost.** The rotation mechanism
  survives as `styles.pick_reference_window`, where it now rotates a META-STYLE's own reference
  images; `tests/test_styles.py` asserts it there (T1.3). What is pruned is the *Inspiration
  pool's* copy of it, for the same reason A16 goes: `inspiration.apply_mix` is W3.5 excision.
- **A20 / A21** never lived in this file; A20's polarity is reversed by D42 and re-asserted in
  `tests/test_copy_verbatim_filter.py`, and A21 (hook-pattern validation) is deleted outright.

What remains is the pair the pivot did not touch:

- **A12** an `override` brief's image had `{{content_sentence}}` empty by construction (no
  trend), so SUBJECT AND SCENE was a blank line and the whole image rode on the BRIEF OVERLAY
  blob — which also carries the COPY directives (`cta`, `tone`, `avoid`) into an image prompt.
  Post-pivot the override brief also suppresses the assigned meta-style entirely (FR-144/M14),
  which makes its own visual directives the *only* subject the frame has — so the fix matters
  more than it did, not less. Re-based onto the merged `image_post.md` (F16).
- **A15** `niche.visual_world` — the operator's standing art direction — reaches the gpt-image-2
  render roles through one narrow slot, while the wider `{{niche_descriptor}}` (which also names
  the AUDIENCE) stays copy-side. The slot is unchanged by the pivot; only the role list moved,
  because `image_single_post.md` + `image_direct.md` merged into `image_post.md`.

Offline: config files and briefs live in `tmp_path`; the prompt engine is a pure function.
Nothing here spends money, opens a socket or writes the repo's `logs/` or `output/`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hypesocials import prompts_engine as pe
from hypesocials.config import NicheConfig
from hypesocials.models import PROFILE_TEMPLATES, Brief, CopySet, TrendItem
from hypesocials.prompts_engine import PromptEngine, build_context

RENDER_PROFILE = "gpt-image-2"
#: The merged single-image role (F16). `image_single_post.md` and `image_direct.md` still sit on
#: disk through W2/W3 and leave every surface at W3.5 — named here once so the transition is
#: visible rather than implied by a role string buried in an assertion.
IMAGE_ROLE = "image_post.md"
#: The gpt-image-2 roles that describe a LOOK, and therefore the only ones A15's slot may reach.
LOOK_ROLES = (IMAGE_ROLE, "carousel_slide.md", "reel_seed_frame.md")
#: Every role that assembles a prompt for a RENDER model, derived from the registry rather than
#: retyped: this list changes twice more (W3.5 drops three names) and a hardcoded copy would go
#: quietly stale exactly when the "no copy-side leak" assertion below matters most.
ALL_RENDER_ROLES = tuple(role for roles in PROFILE_TEMPLATES.values() for role in roles)


# ============================================================== A12 — the override-brief subject


def test_a12_an_override_brief_image_renders_a_non_blank_subject_and_scene() -> None:
    """The bug, at the level it was visible: an override brief with no trend had
    `{{content_sentence}}` empty, so SUBJECT AND SCENE was a blank line.

    Post-pivot the same brief ALSO suppresses the assigned meta-style (FR-144/M14: prompt and
    pictures both), so `render_prompt` carrying the brief's visual directives is now the only
    thing standing between an override creative and an empty subject.
    """
    brief = Brief(name="ai-audit-cta", description="a standing CTA card", influence="override",
                  visual_directives={"scene": "a laptop on a bare desk, one product card",
                                     "palette": "near-black ground, one electric accent"},
                  copy_directives={"message": "book an AI audit", "cta": "Book a slot"})
    context = build_context(trend=None, campaign_brief=brief, creative_format="image",
                            copy=CopySet("a1", "en", headline="Book the audit"))

    rendered = PromptEngine().render(IMAGE_ROLE, context, profile=RENDER_PROFILE)
    subject = rendered.split("SUBJECT AND SCENE:", 1)[1].split("BRIEF OVERLAY", 1)[0]

    assert context["content_sentence"] == "", "no trend, so FR-96's sentence is empty by design"
    assert subject.strip(), "SUBJECT AND SCENE is blank — the A12 defect is back"
    assert "a laptop on a bare desk" in subject
    assert "near-black ground" in subject
    assert "render_prompt" in pe.allowlist(IMAGE_ROLE), \
        "the slot A12 opened is the one carrying the brief's visual directives to this role"


def test_a12_the_loader_is_what_makes_the_fix_total(tmp_path: Path) -> None:
    """The residual hole A12 would otherwise leave, and why it is closed.

    `build_context` only treats a brief as `override` when it HAS visual directives
    (`prompts_engine`'s `override = bool(... and campaign_brief.visual_directives)`). A brief
    with `influence: override` and no visual block would therefore resolve `render_prompt` to ""
    AND `content_sentence` to "" — a blank SUBJECT AND SCENE all over again, A12 unfixed for that
    shape. It is unreachable only because `briefs.load()` REFUSES that file, so this is the
    assertion holding the fix together, and it belongs next to A12 rather than in the brief tests.
    """
    from hypesocials import briefs

    folder = tmp_path / "no-visuals"
    folder.mkdir(parents=True)
    (folder / "brief.yaml").write_text(
        "name: no-visuals\n"
        "description: an override brief that forgot its visual directives\n"
        "influence: override\n"
        "formats: [image]\n"
        "copy_directives:\n  message: book an AI audit\n",
        encoding="utf-8")

    with pytest.raises(briefs.BriefError) as caught:
        briefs.load("no-visuals", tmp_path)

    assert "visual_directives" in str(caught.value)
    # …and the shape that *would* have been blank is exactly the one the loader turns away.
    blank = build_context(trend=None, creative_format="image",
                          campaign_brief=Brief(name="no-visuals", description="d",
                                               influence="override", visual_directives={},
                                               copy_directives={"message": "book an AI audit"}))
    assert blank["render_prompt"] == "" and blank["content_sentence"] == ""


def test_a12_a_blend_brief_still_lets_the_house_style_win_the_visuals() -> None:
    """FR-145's precedence is untouched by A12 and re-pointed by the pivot: only an `override`
    brief replaces `render_prompt`; under `blend` the assigned META-STYLE keeps the visuals and
    the trend-backed creative still gets FR-96's deterministic subject sentence."""
    blend = Brief(name="ai-audit-cta", description="", influence="blend",
                  visual_directives={"scene": "a laptop on a bare desk"},
                  copy_directives={"message": "book an AI audit"})
    context = build_context(trend=_trend(), campaign_brief=blend, creative_format="image")

    rendered = PromptEngine().render(IMAGE_ROLE, context, profile=RENDER_PROFILE)
    subject = rendered.split("SUBJECT AND SCENE:", 1)[1].split("BRIEF OVERLAY", 1)[0]

    assert "AI tool stacks" in subject, "FR-96's content sentence still leads a trend-backed image"
    assert "a laptop on a bare desk" not in subject, "a blend brief does not replace the visuals"


# ============================================================== A15 — the niche's visual world


def test_a15_the_visual_world_resolves_on_exactly_the_roles_that_describe_a_look() -> None:
    """The slot's whole value is its narrowness, so the assertion is two-sided: every role that
    describes a LOOK carries it, and every other role — the copy calls, the anchor block, the
    Seedance director, the topic filter — resolves it to nothing at all.

    Stated against the gpt-image-2 SET rather than a retyped list of four names, because the
    merge of `image_single_post.md` + `image_direct.md` into `image_post.md` (F16) changes the
    count twice: five holders through W2/W3, three after the W3.5 excision.
    """
    holders = {role for role in pe._ALLOWLIST if "niche_visual_world" in pe.allowlist(role)}

    assert set(LOOK_ROLES) <= holders, "a look role lost the operator's standing art direction"
    assert holders <= set(PROFILE_TEMPLATES["gpt-image-2"]), \
        f"niche_visual_world reached a non-image role: {sorted(holders - set(LOOK_ROLES))}"
    for role in ("copywriter_system.md", "vision_check_question.md", "topic_filter_system.md",
                 "carousel_anchor_instruction.md", "reel_director.md"):
        assert "niche_visual_world" not in pe.allowlist(role), role


def test_a15_the_copy_side_slots_still_resolve_on_no_render_role_at_all() -> None:
    """The narrow slot exists precisely so `niche_descriptor` — which also names the AUDIENCE —
    stays copy-side. Widening `niche_descriptor` instead would have been the easy wrong fix."""
    for name in ("niche_descriptor", "brand_context"):
        holders = {role for role in pe._ALLOWLIST if name in pe.allowlist(role)}
        assert not holders & set(ALL_RENDER_ROLES), f"{name} reached {sorted(holders)}"
        assert name in pe.allowlist("copywriter_system.md"), \
            f"{name} is the copywriter's context and it stopped arriving"


def test_a15_the_new_slot_is_cuttable_under_the_length_cap() -> None:
    """`_TRUNCATION_ORDER` is 50 §7's cut list, and anything absent from it is UNCUTTABLE. A slot
    of standing art direction that a long prompt could never shrink would end up crowding out the
    house style's own instruction — the opposite of what A15 is for."""
    order = pe._TRUNCATION_ORDER

    assert "niche_visual_world" in order
    assert order.index("niche_visual_world") == order.index("niche_descriptor") + 1, \
        "it is the same kind of value as niche_descriptor and belongs beside it"
    assert "onimage_text" not in order and "exclusions" not in order and "text_budgets" not in order


def test_a15_a_creative_with_no_house_style_is_the_case_the_slot_exists_for() -> None:
    """The measured defect, re-pointed: the operator's only global art direction used to touch
    nothing in `direct` mode, because there was no analyst to fold it into `render_prompt`. The
    same hole is now a creative whose registry lookup produced no style — the slot is what keeps
    art direction on the frame regardless."""
    world = "dark UI and dashboard screenshots, one electric accent on near-black"
    context = build_context(trend=_trend(), style=None, creative_format="image",
                            niche_visual_world=world,
                            niche_descriptor="Audience: operations leads · Visual world: " + world)

    rendered = PromptEngine().render(IMAGE_ROLE, context, profile=RENDER_PROFILE)

    assert world in rendered
    assert "Audience: operations leads" not in rendered, "copy-side context leaked into a render"
    line = next(text for text in rendered.splitlines() if "NICHE VISUAL WORLD" in text)
    assert line.split("NICHE VISUAL WORLD", 1)[1].strip(" :()ignoreifempty")


def test_a15_a_folded_yaml_scalar_becomes_one_prompt_line() -> None:
    """`visual_world` is authored as a long YAML scalar and arrives folded. A value that wrapped
    would push the rest of the labelled line into an unlabelled continuation the model reads as a
    new instruction."""
    context = build_context(niche_visual_world="dark UI\nand dashboards\n\n  one accent  ")

    assert context["niche_visual_world"] == "dark UI and dashboards one accent"
    assert build_context(niche_visual_world="   \n  ")["niche_visual_world"] == ""


def test_a15_the_descriptor_deliberately_carries_no_visual_world_of_its_own() -> None:
    """The boundary the two slots rest on, kept from A11's pruned half because it is the reason
    `niche_visual_world` had to exist at all: `as_text()` feeds `{{niche_descriptor}}`, which the
    copywriter allowlists and no render role does — so an audience line and an art-direction line
    can never be folded into one value without breaking one of the two allowlists."""
    niche = NicheConfig(audience="operations leads", vibe="plain and concrete",
                        visual_world="dark UI on near-black")

    text = niche.as_text()

    assert "operations leads" in text and "plain and concrete" in text
    assert "dark UI on near-black" in text


# --------------------------------------------------------------------------- shared builders


def _trend() -> TrendItem:
    return TrendItem(history_key="t1", monitor_id="m1", name="AI tool stacks",
                     why_it_works="numbers in the first line",
                     hook_texts=["Nobody tells you this"],
                     video_descriptions=["a creator lists seven tools"])
