"""A11 / A12 / A15 / A16 / A17 — the five operator steering levers that were wired but inert.

Each of these was a complete, allowlist-audited pipeline that simply never carried a value, or a
branch that looked like rotation and was not. They share a file because they share a failure mode:
nothing crashed, nothing was logged, and the output was quietly worse than the config asked for.

- **A11** `{{brand_accent}}` had been blank on every run this tool has ever made. It was welded to
  Notion, which is `off` in every shipped config and gated on a `NOTION_TOKEN` this workstation
  does not carry. `niche.brand.accent` / `niche.brand.product_nouns` give the operator the slot
  without the integration, and Notion still wins when it is energised.
- **A12** an `override` brief forces `variant="direct"`, which renders through `image_direct.md`,
  whose only subject slot was `{{content_sentence}}` — empty by construction when there is no
  trend. The image rode entirely on the BRIEF OVERLAY blob with a blank SUBJECT AND SCENE.
- **A15** `niche.visual_world` reached the image only in `analyzed` mode, and only if the analyst
  folded it into `render_prompt`. In `direct` mode the operator's standing art direction touched
  nothing at all.
- **A16** a `.txt` sitting beside a pooled Inspiration image — proven, human-written viral copy —
  was counted in `skipped` and thrown away.
- **A17** under `inspiration_mix: exclusive` `_pick` sliced `group[:count]`, so every creative in
  the run rendered from the same first three files.

Offline: config files, pooled files and run folders all live in `tmp_path`; the prompt engine is
a pure function; the one runner test substitutes `generate.create` so nothing is submitted.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hypesocials import generate, prompts_engine as pe, runner, sources
from hypesocials.budget import Budget
from hypesocials.config import BrandConfig, Config, NicheConfig, load_config
from hypesocials.copywrite import CopyResult
from hypesocials.models import Brief, CopySet, PlanEntry, StyleBrief, TrendItem
from hypesocials.outputs import Ledger
from hypesocials.prompts_engine import PromptEngine, build_context
from hypesocials.sources import inspiration
from hypesocials.util import Deadline

RENDER_PROFILE = "gpt-image-2"
#: The four gpt-image-2 roles FR-109 and A15 target, and the only ones either slot may reach.
RENDER_ROLES = ("image_single_post.md", "carousel_slide.md", "image_direct.md",
                "reel_seed_frame.md")
#: Every role that assembles a prompt for a RENDER model — the four above plus the two that carry
#: no brand or niche slot at all. Used for "resolves on no render role" assertions.
ALL_RENDER_ROLES = (*RENDER_ROLES, "carousel_anchor_instruction.md", "reel_director.md")

#: A real JPEG header, so `inspiration._usable`'s magic-byte check passes on a written file.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


class Log:
    """`LogWriter`'s three call shapes, remembering only what these tests assert on."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def event(self, event_type: str, message: str = "", **data: Any) -> str:
        self.records.append((event_type, message))
        return f"ev_{len(self.records):04d}"

    warn = event
    error = event


def config_file(folder: Path, text: str) -> Config:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "unit.yaml").write_text(text, encoding="utf-8")
    return load_config("unit", configs_dir=folder)


# ============================================================== A11 — the brand accent lands


def test_a11_the_niche_brand_block_parses_with_both_keys_and_defaults_to_empty(
    tmp_path: Path,
) -> None:
    cfg = config_file(tmp_path, """
niche:
  audience: operations leads at Czech SMBs
  visual_world: dark UI and dashboard screenshots on near-black
  brand:
    accent: "#C1391F"
    product_nouns: ["AI audit", "automation sprint"]
""")

    assert cfg.niche.brand.accent == "#C1391F"
    assert cfg.niche.brand.product_nouns == ["AI audit", "automation sprint"]
    # …and a config that says nothing about brand still loads, with the slot simply empty.
    bare = config_file(tmp_path / "bare", "niche:\n  audience: founders\n")
    assert bare.niche.brand == BrandConfig() == BrandConfig(accent="", product_nouns=[])


def test_a11_the_niche_descriptor_deliberately_carries_no_brand_accent() -> None:
    """The boundary A11 rests on. `as_text()` feeds `{{niche_descriptor}}`, which the analyst and
    the copywriter allowlist and no render role does; the accent is render-side and travels in
    `{{brand_accent}}`. Folding one into the other would put brand text into copy prompts AND drag
    the audience line into render prompts — exactly the leak the per-role allowlists exist for."""
    niche = NicheConfig(audience="operations leads", vibe="plain and concrete",
                        visual_world="dark UI on near-black",
                        brand=BrandConfig(accent="#C1391F", product_nouns=["AI audit"]))

    text = niche.as_text()

    assert "operations leads" in text and "plain and concrete" in text
    assert "dark UI on near-black" in text
    assert "#C1391F" not in text, "the brand accent leaked into the copy-side descriptor"
    assert "AI audit" not in text
    assert text == NicheConfig(audience=niche.audience, vibe=niche.vibe,
                               visual_world=niche.visual_world).as_text()


def test_a11_the_accent_and_nouns_reach_all_four_render_prompts_and_no_copy_prompt() -> None:
    """The operator-visible half: a non-blank `BRAND INFLUENCE:` line, on every image role."""
    engine = PromptEngine()
    contexts = {
        "image_single_post.md": build_context(style_brief=_brief(), creative_format="image",
                                              **_brand_kwargs()),
        "image_direct.md": build_context(creative_format="image", **_brand_kwargs()),
        "carousel_slide.md": build_context(style_brief=_brief(), creative_format="carousel",
                                           slide_index="1 of 3", slide_text="Slide one",
                                           **_brand_kwargs()),
        "reel_seed_frame.md": build_context(style_brief=_brief(), creative_format="reel",
                                            **_brand_kwargs()),
    }

    for role, context in contexts.items():
        rendered = engine.render(role, context, profile=RENDER_PROFILE)
        line = next(text for text in rendered.splitlines() if "BRAND INFLUENCE" in text)
        assert line.split("BRAND INFLUENCE", 1)[1].strip(" :"), f"{role}: blank brand line"
        assert "#C1391F" in rendered and "AI audit" in rendered

    copy_prompt = engine.render("copywriter_system.md",
                                build_context(trend=_trend(), **_brand_kwargs()))
    assert "#C1391F" not in copy_prompt, "the render-side accent reached the copy call"


async def test_a11_the_runner_lets_notion_win_and_falls_back_to_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-109/A11's precedence, asserted through `runner._create` rather than by reading it.

    Notion first because turning the integration on later must change nothing written down in the
    config; the config second because on this workstation it is the only source that ever fires.
    Both halves are checked, plus the empty case — a `BrandContext()` accent of `""` must fall
    through rather than blank the operator's own value.
    """
    seen: list[generate.Env] = []

    async def fake_create(entries: Any, env: generate.Env) -> generate.Report:
        seen.append(env)
        return generate.Report()

    monkeypatch.setattr(generate, "create", fake_create)
    config = Config(niche=NicheConfig(visual_world="dark UI on near-black",
                                      brand=BrandConfig(accent="#CONFIG",
                                                        product_nouns=["config noun"])))

    for brand in (sources.BrandContext(),  # Notion off: the config's own accent is what fires
                  sources.BrandContext(accent="#NOTION", product_nouns=["notion noun"])):
        await runner._create(_session(tmp_path, config, brand), [], [], {}, {}, CopyResult())

    assert [env.brand_accent for env in seen] == ["#CONFIG", "#NOTION"]
    assert [list(env.brand_product_nouns) for env in seen] == [["config noun"], ["notion noun"]]
    # A15 travels on the same call, and it is the config's alone — Notion has no visual world.
    assert {env.niche_visual_world for env in seen} == {"dark UI on near-black"}
    assert all("#CONFIG" not in env.niche_descriptor for env in seen)


def _session(run_dir: Path, config: Config, brand: sources.BrandContext) -> Any:
    """The attributes `runner._create` reads, and nothing else (it never touches the rest)."""
    return SimpleNamespace(
        config=config, run_dir=run_dir, engine=PromptEngine(), budget=Budget(1.0), log=Log(),
        ledger=Ledger(run_dir), pool=sources.InspirationPool(), brand=brand, campaign_briefs={},
        llm=None, video_refs=None, halted=False, control=SimpleNamespace(stop=asyncio.Event()),
        deadline=Deadline(60.0))


# ============================================================== A12 — the override-brief subject


def test_a12_an_override_brief_image_renders_a_non_blank_subject_and_scene() -> None:
    """The bug, at the level it was visible: `influence: override` forces `variant="direct"`, and
    a direct creative with no trend had `{{content_sentence}}` empty — so SUBJECT AND SCENE was a
    blank line and the whole image rode on the BRIEF OVERLAY blob, which also carries the COPY
    directives (`cta`, `tone`, `avoid`) into an image prompt."""
    brief = Brief(name="ai-audit-cta", description="a standing CTA card", influence="override",
                  visual_directives={"scene": "a laptop on a bare desk, one product card",
                                     "palette": "near-black ground, one electric accent"},
                  copy_directives={"message": "book an AI audit", "cta": "Book a slot"})
    context = build_context(trend=None, campaign_brief=brief, creative_format="image",
                            copy=CopySet("a1", "en", headline="Book the audit"))

    rendered = PromptEngine().render("image_direct.md", context, profile=RENDER_PROFILE)
    subject = rendered.split("SUBJECT AND SCENE:", 1)[1].split("BRIEF OVERLAY", 1)[0]

    assert context["content_sentence"] == "", "no trend, so FR-96's sentence is empty by design"
    assert subject.strip(), "SUBJECT AND SCENE is blank — the A12 defect is back"
    assert "a laptop on a bare desk" in subject
    assert "near-black ground" in subject
    assert "render_prompt" in pe.allowlist("image_direct.md"), \
        "the slot A12 opened is the one carrying the brief's visual directives to this role"


def test_a12_the_loader_is_what_makes_the_fix_total(tmp_path: Path) -> None:
    """The residual hole A12 would otherwise leave, and why it is closed.

    `build_context` only treats a brief as `override` when it HAS visual directives
    (`prompts_engine.py`'s `override = bool(... and campaign_brief.visual_directives)`). A brief
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


def test_a12_a_blend_brief_still_lets_the_trend_win_the_visuals() -> None:
    """FR-145's precedence is untouched by A12: only an `override` brief replaces `render_prompt`,
    and a trend-backed direct image still gets FR-96's deterministic subject sentence."""
    blend = Brief(name="ai-audit-cta", description="", influence="blend",
                  visual_directives={"scene": "a laptop on a bare desk"},
                  copy_directives={"message": "book an AI audit"})
    context = build_context(trend=_trend(), campaign_brief=blend, creative_format="image")

    rendered = PromptEngine().render("image_direct.md", context, profile=RENDER_PROFILE)
    subject = rendered.split("SUBJECT AND SCENE:", 1)[1].split("BRIEF OVERLAY", 1)[0]

    assert "AI tool stacks" in subject, "FR-96's content sentence still leads a trend-backed image"
    assert "a laptop on a bare desk" not in subject, "a blend brief does not replace the visuals"


# ============================================================== A15 — the niche's visual world


def test_a15_the_visual_world_resolves_on_exactly_the_four_gpt_image_2_roles() -> None:
    holders = {role for role in pe._ALLOWLIST if "niche_visual_world" in pe.allowlist(role)}

    assert holders == set(RENDER_ROLES)
    for role in ("style_brief_system.md", "copywriter_system.md", "vision_check_question.md",
                 "carousel_anchor_instruction.md", "reel_director.md"):
        assert "niche_visual_world" not in pe.allowlist(role), role


def test_a15_the_copy_side_slots_still_resolve_on_no_render_role_at_all() -> None:
    """The narrow slot exists precisely so `niche_descriptor` — which also names the AUDIENCE —
    stays copy-side. Widening `niche_descriptor` instead would have been the easy wrong fix."""
    for name in ("niche_descriptor", "brand_context"):
        holders = {role for role in pe._ALLOWLIST if name in pe.allowlist(role)}
        assert not holders & set(ALL_RENDER_ROLES), f"{name} reached {sorted(holders)}"
    assert {role for role in pe._ALLOWLIST if "niche_descriptor" in pe.allowlist(role)} == \
        {"style_brief_system.md", "copywriter_system.md"}
    assert {role for role in pe._ALLOWLIST if "brand_context" in pe.allowlist(role)} == \
        {"copywriter_system.md"}


def test_a15_the_new_slot_is_cuttable_under_the_length_cap() -> None:
    """`_TRUNCATION_ORDER` is 50 §7's cut list, and anything absent from it is UNCUTTABLE. A slot
    of standing art direction that a long prompt could never shrink would end up crowding out the
    trend's own style — the opposite of what A15 is for."""
    order = pe._TRUNCATION_ORDER

    assert "niche_visual_world" in order
    assert order.index("niche_visual_world") == order.index("niche_descriptor") + 1, \
        "it is the same kind of value as niche_descriptor and belongs beside it"
    assert "onimage_text" not in order and "exclusions" not in order and "text_budgets" not in order


def test_a15_direct_mode_is_the_case_the_slot_exists_for() -> None:
    """The measured defect: in `direct` mode the operator's only global art direction touched
    nothing at all, because there is no analyst to fold it into `render_prompt`."""
    world = "dark UI and dashboard screenshots, one electric accent on near-black"
    context = build_context(trend=_trend(), creative_format="image", niche_visual_world=world,
                            niche_descriptor="Audience: operations leads · Visual world: " + world)

    rendered = PromptEngine().render("image_direct.md", context, profile=RENDER_PROFILE)

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


# ============================================================== A16 — the sibling .txt exemplars


def pool_folder(root: Path, name: str, *, images: int, texts: dict[int, str] | None = None) -> Path:
    """One Inspiration folder: `01.jpg` … plus whichever `NN.txt` siblings were asked for."""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(1, images + 1):
        (folder / f"{index:02d}.jpg").write_bytes(JPEG)
    for index, text in (texts or {}).items():
        (folder / f"{index:02d}.txt").write_text(text, encoding="utf-8")
    return folder


def pool_config(*folders: Path, mix: str = "minority", per_job: int = 3) -> Config:
    cfg = Config()
    cfg.sources.inspiration_folders = [str(folder) for folder in folders]
    cfg.sources.inspiration_mix = mix
    cfg.sources.reference_images_per_job = per_job
    return cfg


async def test_a16_a_picked_images_sibling_txt_is_read_into_the_copy_exemplars(
    tmp_path: Path,
) -> None:
    folder = pool_folder(tmp_path, "viral posts", images=3,
                         texts={1: "Nobody measured the workflow.\n\nSo nobody fixed it.",
                                3: "Three tools. One bill. Zero owners."})

    pool = await inspiration.load_pool(pool_config(folder), log=Log())

    assert len(pool.images) == 3
    assert pool.exemplar_texts == ["Nobody measured the workflow.\n\nSo nobody fixed it.",
                                   "Three tools. One bill. Zero owners."]
    assert pool.skipped == 0, "a consumed .txt was neither an image nor waste"


async def test_a16_a_lone_txt_is_still_skipped_and_still_counted(tmp_path: Path) -> None:
    """The sidecar enriches an image that was already pickable; it never makes a file pickable.
    A folder of pure text is a folder with no usable image, which is absence, not a pool."""
    folder = tmp_path / "captions"
    folder.mkdir()
    (folder / "01.txt").write_text("a caption with no picture", encoding="utf-8")
    (folder / "notes.md").write_text("# notes", encoding="utf-8")

    pool = await inspiration.load_pool(pool_config(folder), log=Log())

    assert pool.groups == [] and pool.images == []
    assert pool.exemplar_texts == []
    assert pool.skipped == 2, "both non-images stay counted — the log line must stay honest"
    assert pool.active is False


async def test_a16_an_oversized_caption_is_cut_at_a_whitespace_boundary_never_mid_word(
    tmp_path: Path,
) -> None:
    """A mangled tail reads as a typo, and the copywriter is being shown this text as an example
    of good writing — so the cut follows the same word-boundary rule the prompt engine uses."""
    word = "workflow "
    huge = word * (inspiration._MAX_TEXT_BYTES // len(word) + 40)
    folder = pool_folder(tmp_path, "viral posts", images=1, texts={1: huge})

    pool = await inspiration.load_pool(pool_config(folder), log=Log())

    (text,) = pool.exemplar_texts
    assert len(text.encode("utf-8")) <= inspiration._MAX_TEXT_BYTES
    assert text.endswith("workflow"), "the tail was cut mid-word"
    assert "workfl\n" not in text and not text.endswith("workfl")
    assert set(text.split()) == {"workflow"}


async def test_a16_the_run_wide_exemplar_cap_holds_across_folders(tmp_path: Path) -> None:
    """`_MAX_PER_FOLDER` x several folders could pool hundreds of captions; the copy call wants a
    handful of proven examples, not a corpus."""
    folders = [pool_folder(tmp_path, f"folder-{n}", images=20,
                           texts={index: f"caption {n}-{index}" for index in range(1, 21)})
               for n in range(3)]

    pool = await inspiration.load_pool(pool_config(*folders), log=Log())

    assert len(pool.exemplar_texts) == inspiration._MAX_EXEMPLARS == 24
    assert pool.exemplar_texts[0] == "caption 0-1", "folder order then file order — deterministic"
    assert len(set(pool.exemplar_texts)) == 24


async def test_a16_the_exemplars_reach_the_copy_prompt_and_no_render_prompt(
    tmp_path: Path,
) -> None:
    """The whole point, plus the constraint that makes it safe: an Inspiration image is attached
    to a render under an explicit "no words" role line, and handing the image model that image's
    proven copy is how the copy ends up baked into pixels verbatim."""
    folder = pool_folder(tmp_path, "viral posts", images=1,
                         texts={1: "ZZQEXEMPLAR nobody measured the workflow"})
    pool = await inspiration.load_pool(pool_config(folder), log=Log())
    engine = PromptEngine()

    copy_prompt = engine.render("copywriter_system.md",
                                build_context(trend=_trend(),
                                              copy_exemplars=pool.exemplar_texts))

    assert "ZZQEXEMPLAR" in copy_prompt
    assert "[1]" in copy_prompt, "exemplars are numbered blocks, not one rambling document"
    for role in ALL_RENDER_ROLES:
        profile = RENDER_PROFILE if role in (*RENDER_ROLES, "carousel_anchor_instruction.md") \
            else "seedance-2-5"
        rendered = engine.render(role, build_context(
            trend=_trend(), style_brief=_brief(), copy=CopySet("a1", "en", headline="Hi"),
            creative_format="image", slide_index="1 of 2",
            copy_exemplars=pool.exemplar_texts), profile=profile)
        assert "ZZQEXEMPLAR" not in rendered, f"{role} resolved the copy-only exemplar slot"


# ============================================================== A17 — the exclusive rotation


async def test_a17_exclusive_mix_gives_successive_creatives_different_windows(tmp_path: Path) -> None:
    """The trap: `_pick`'s exclusive branch sliced `group[:count]` with no intra-folder rotation,
    so with the one configured folder EVERY creative in the run rendered from the same three
    files — eight creatives, one set of pictures."""
    folder = pool_folder(tmp_path, "viral posts", images=9)
    cfg = pool_config(folder, mix="exclusive", per_job=3)
    pool = await inspiration.load_pool(cfg, log=Log())
    entries = _entries(6)

    mix = inspiration.apply_mix(entries, {}, pool, cfg, log=Log())

    windows = [tuple(path.name for path in mix.local_refs[entry.asset_id]) for entry in entries]
    assert all(len(window) == 3 for window in windows)
    assert windows[0] != windows[1] != windows[2], "consecutive creatives share a window"
    assert len(set(windows[:3])) == 3, "three non-overlapping windows over nine files"
    assert set().union(*(set(window) for window in windows[:3])) == \
        {f"{n:02d}.jpg" for n in range(1, 10)}, "a full pass covers the folder exactly once"
    assert windows[3] == windows[0], "and then it wraps, deterministically"


async def test_a17_the_same_plan_picks_the_same_pictures_on_a_re_run(tmp_path: Path) -> None:
    """Determinism, not randomness: rotation is a pure function of the asset's position in the
    run's sorted asset-id list, so a re-run of the same plan reproduces the same sequence."""
    folder = pool_folder(tmp_path, "viral posts", images=7)
    cfg = pool_config(folder, mix="exclusive", per_job=3)
    pool = await inspiration.load_pool(cfg, log=Log())

    first = inspiration.apply_mix(_entries(8), {}, pool, cfg, log=Log())
    second = inspiration.apply_mix(_entries(8), {}, pool, cfg, log=Log())

    assert first.local_refs == second.local_refs
    assert first.mix == second.mix == "exclusive"
    assert first.ref_source == "inspiration", "FR-73's provenance: the pictures are the pool's"
    assert len({tuple(paths) for paths in first.local_refs.values()}) > 1


async def test_a17_two_folders_rotate_on_both_axes(tmp_path: Path) -> None:
    """Under `exclusive` the FOLDER rotates and the window inside it rotates. Only the first was
    ever implemented, which is why a single configured folder produced one set of pictures."""
    folders = [pool_folder(tmp_path, "folder-a", images=6),
               pool_folder(tmp_path, "folder-b", images=6)]
    cfg = pool_config(*folders, mix="exclusive", per_job=3)
    pool = await inspiration.load_pool(cfg, log=Log())
    entries = _entries(4)

    mix = inspiration.apply_mix(entries, {}, pool, cfg, log=Log())
    picks = [mix.local_refs[entry.asset_id] for entry in entries]

    assert [paths[0].parent.name for paths in picks] == ["folder-a", "folder-b"] * 2
    assert picks[0] != picks[2], "the same folder's second draw is a different window"
    assert {path.name for path in picks[0]} != {path.name for path in picks[2]}


async def test_a17_a_folder_smaller_than_the_job_size_yields_all_of_itself(tmp_path: Path) -> None:
    """Totality: `min(count, len(group))` and the wrap must not raise or return duplicates."""
    folder = pool_folder(tmp_path, "tiny", images=2)
    cfg = pool_config(folder, mix="exclusive", per_job=3)
    pool = await inspiration.load_pool(cfg, log=Log())

    mix = inspiration.apply_mix(_entries(4), {}, pool, cfg, log=Log())

    for paths in mix.local_refs.values():
        assert len(paths) == 2 and len(set(paths)) == 2


async def test_a17_minority_mix_still_attaches_exactly_one_rotating_image(tmp_path: Path) -> None:
    """The shipped configs use `minority`, so A17 must not have disturbed it: one image, attached
    last, rotating through the flat pool so eight creatives are not eight copies of `01.jpg`."""
    folder = pool_folder(tmp_path, "viral posts", images=4)
    cfg = pool_config(folder, mix="minority", per_job=3)
    pool = await inspiration.load_pool(cfg, log=Log())
    entries = _entries(5)

    mix = inspiration.apply_mix(entries, {}, pool, cfg, log=Log())
    picked = [mix.local_refs[entry.asset_id][0].name for entry in entries]

    assert all(len(mix.local_refs[entry.asset_id]) == 1 for entry in entries)
    assert picked == ["01.jpg", "02.jpg", "03.jpg", "04.jpg", "01.jpg"]
    assert mix.ref_source == "", "`minority` keeps the trend as the provenance"


# --------------------------------------------------------------------------- shared builders


def _entries(count: int) -> list[PlanEntry]:
    return [PlanEntry(order=index, asset_id=f"a{index}", creative_format="image",
                      platform="linkedin", language="en", aspect_ratio="16:9", trend_key="t1")
            for index in range(count)]


def _trend() -> TrendItem:
    return TrendItem(history_key="t1", monitor_id="m1", name="AI tool stacks",
                     why_it_works="numbers in the first line",
                     hook_texts=["Nobody tells you this"],
                     video_descriptions=["a creator lists seven tools"])


def _brief() -> StyleBrief:
    return StyleBrief(trend_key="t1", render_prompt="Near-black ground, one electric accent.",
                      palette=["#0B0B0C"], typography="extra-bold condensed sans",
                      hook_pattern="withheld-subject claim", content_angle="workflow first")


def _brand_kwargs() -> dict[str, Any]:
    return {"brand_accent": "#C1391F", "brand_product_nouns": ["AI audit"],
            "reference_roles": ["Image 1 — style reference"], "reference_image_count": 1}
