# 50 — Promptcraft

## TL;DR — Plain English

This file answers one question: who actually writes the text that gets sent to the image model and the video model, and what does that text look like?

The short answer: nobody writes it fresh every time. An AI (Sonnet 5) studies the winning posts for each trend and writes down what makes them work — colours, layout, lettering, the shape of the hook. That analysis then drops into **templates**: ready-made, battle-tested prompt skeletons, one shape for a single image, one for a carousel slide, one for a reel. The templates live in an editable `prompts/` folder as plain text files, so a human can tune the wording without touching code. The engine's job is just to fill in the blanks — trend analysis here, the caption text there, the exclusion rules always — and send the result off. Nothing is invented on the fly.

- Sonnet 5 supplies the **substance** (what this trend looks like and why it works) — already specified in `10-pipeline.md`.
- The `prompts/` folder supplies the **shape** (how GPT Image 2 likes to be asked, how Seedance likes to be asked) — this is new, and it is editable.
- The engine supplies the **glue**: it fills the shape with the substance, deterministically, every time, and never adds words of its own.
- Each image model and video model gets its prompt written the way *that* model actually responds best to — that's the whole idea of this file.

---

This file is the single authoritative spec for the shape of every generation prompt the engine sends — how it is assembled, where its scaffolding lives, and the model-specific playbooks that scaffolding encodes. It extends `10-pipeline.md` (which owns the style brief itself, FR-92; the assembly rule, FR-17/FR-94; carousels, FR-95; reels, FR-24) rather than restating or contradicting it — this file cross-references those requirements throughout instead of duplicating them.

Requirement range owned by this file: **FR-180 … FR-199, FR-260–269**; **NFR-180 … NFR-185 are reserved for this file and currently unused** (none defined yet — stated so the range claim doesn't imply lost content).

---

## 1. Who designs the prompt

Three cooperating layers each own what they are best at. None of them is redundant with another, and none of them requires an extra model call beyond what `10-pipeline.md` already specifies.

**(a) The Sonnet 5 style brief — creative substance, per trend.** Specified in full in `10-pipeline.md` FR-9–FR-12, FR-92. It supplies `layout_zones`, palette, typography, `render_prompt`, `exclusions` and the rest of the brief's fields. This is the analysis: *what does this specific winning creative actually look like, in reproducible terms.*

**(b) Editable prompt templates — model-specific scaffolding.** New in this file (D24). A `prompts/` folder holds one small text file per prompt role — the style-brief system prompt, the copywriter system prompt, the image single-post scaffold, the carousel slide scaffold, the carousel anchor-slide instruction, the reel director scaffold, the vision-check question. Each file is the *shape* a given model responds best to, with named placeholders where run-specific content drops in. These templates encode the model playbooks in sections 3–4 below — they are the expertise, written down once and reused every run.

**(c) Deterministic assembly — the engine's glue.** Plain code fills each template's placeholders from the style brief's fields, the copy text, and the mandatory clauses of FR-94, then sends the result. Assembly never invents content, never asks a model to improvise the scaffold, and never adds an LLM call: the templates already encode what an LLM call would have re-derived every time. This is the same principle FR-17 already states for image prompts — this file generalizes it to every model.

**FR-180 — No hidden fourth layer.** Every render prompt sent by the engine is fully accounted for by (a) a style brief field, (b) a template file, or (c) a mandatory clause defined in this file or in `10-pipeline.md`. There is no prompt text that exists only in engine code and nowhere else — if it isn't in a template or a brief, it doesn't belong in a prompt.

---

## 2. The `prompts/` folder (D24)

**FR-181 — Templates are files, hot-loaded per run, in a two-level layout.** The nine prompt roles split by what owns them:

- **Three global role templates, flat in `prompts/`** — `style_brief_system.md`, `copywriter_system.md`, `vision_check_question.md`. These belong to the OpenRouter LLM roles, not to any render-model profile, and exist exactly once.
- **Per-profile render template sets, under `prompts/<profile>/`** — for `gpt-image-2`: `image_single_post.md`, `carousel_slide.md`, `carousel_anchor_instruction.md`, `image_direct.md`, `reel_seed_frame.md`; for `seedance-2-5`: `reel_director.md`. A second render profile added later gets its own subfolder with its own complete set; flat filenames could never hold two profiles' sets simultaneously.

Files are read fresh at the start of each run (not compiled or cached across runs), so an edit takes effect on the very next run with no build step, no restart of anything beyond the run itself. `image_direct.md` is the direct-mode render scaffold (FR-96's deterministic content sentence expressed as a placeholder-filled template line, so operators can tune direct mode in Notepad); `reel_seed_frame.md` is the seed-frame image render scaffold.

**FR-182 — Named placeholders, filled by assembly only.** Each template contains named placeholders (for example `{{render_prompt}}`, `{{layout_zones}}`, `{{onimage_text}}`, `{{exclusions}}`, `{{style_dna}}`, `{{slide_index}}`, `{{seed_frame_ref}}`, `{{audio_cue}}`) that the assembly step in section 1(c) fills from the style brief, the copy output, and config. Placeholders are plain string substitution — no expression language, no conditionals, no loops inside a template. If a template needs a field the assembly step doesn't provide, that is a template bug, caught at fill time (FR-260).

**FR-183 — Missing or corrupt template falls back to the built-in default.** Every template file has a built-in default compiled into the engine that implements the playbook rules in sections 3–4; the worked examples in section 6 are illustrative only, not the canonical built-in text. If a file is missing, unreadable, or fails to parse its placeholders, the engine uses the built-in default for that role and writes a warning to the run log naming the file and the reason. The run never stops for a bad template — a prompt template is content, not infrastructure, and content degrades rather than blocks (matching the pipeline-wide philosophy).

**FR-184 — Templates are logged for attribution.** Every run log records, once per template role actually used, the template's file name and a content hash. This makes every generated asset's prompt attributable to a specific template version — if a user tunes `carousel_slide.md` between two runs, the log shows which run used which wording, without needing full-file diffs in the log.

**FR-262 — Template sets are per model profile.** Every render-model profile (20-integrations FR-272; shipped profiles: `gpt-image-2` and `seedance-2-5`) owns a complete template set under `prompts/<profile>/` (FR-181's layout; a config's `prompts_dir`, when set, is checked first per FR-174 — v1.6.1 wording, formerly "niche pack prompts/"). The playbooks encoded in sections 3–4 of this file are explicitly the playbooks OF those two profiles, not universal truths applicable to all models. Swapping a model ID within the same profile (e.g., `gpt-image-2` to `gpt-image-2-pro`, if both route through the same profile) requires no template changes — templates belong to the profile, not the specific model. Adopting a new render-model family (Kling, Veo, etc.) requires registering a new profile and authoring a complete template set per that model's vendor guidance (this is the promptcraft half of 20-integrations' one-page model-onboarding recipe, FR-273; D34).

**FR-263 — Missing templates: fallback for shipped profiles, refusal for new ones.** This rule and FR-183 divide cleanly by whether a **compiled built-in default** exists:

- **Shipped profiles (`gpt-image-2`, `seedance-2-5`) and the three global role templates have built-in defaults compiled into the engine** — for them, FR-183 governs: a missing, unreadable, or unparseable file falls back to the built-in with a logged warning, and the run never stops for a bad template.
- **A newly registered profile has no built-ins**, so its template set on disk *is* its only implementation — for it, pre-flight validates that the profile's complete set under `prompts/<profile>/` is present, readable, and parseable, and refuses with exit code 2 naming the profile and the missing file(s) if not (the template-set half of the FR-281 profile check).

The two rules never apply to the same file, so there is no contradiction: fallback where a default exists, refusal where none can. Either way FR-260 holds — no malformed prompt reaches a paid API (D34).

**Campaign-brief note.** The product-ad campaign brief (worked example in 30-configuration, D35) and all other campaign briefs use the standard `gpt-image-2` and `seedance-2-5` template sets — no special brief-specific templates exist. Brief copy directives (message, CTA, structure) and visual directives flow through the existing brief-influence placeholders and are filled into the standard templates; the influence model (`override` or `blend`) determines whether brief inputs replace or augment trend inputs.

---

## 3. GPT Image 2 profile playbook (images and carousel slides)

Sourced from GPT Image 2 vendor docs and community practice (graded OFFICIAL/COMMUNITY in research), this section states the rules as plain-English requirements the `image_single_post.md` and `carousel_slide.md` templates must encode.

**FR-185 — Fixed section order, labeled segments.** Every image prompt is assembled in a fixed order — use-case/format, then scene/subject, then the exact text block, then style, then constraints — as short labeled segments (line breaks between them), never one long paragraph. This is templating discipline, not model magic (see the JSON verdict below): a labeled scaffold is easier to fill correctly and easier to debug from the log than free prose.

**FR-186 — Text is a locked asset.** Every literal string that must appear on the image is quoted in the prompt, its typography stated (weight, case, placement), and followed by an explicit instruction to render it verbatim with no extra characters and no duplicated text. **Czech diacritics and brand names are additionally spelled out letter-by-letter** in the prompt (e.g. "Rychlejší růst" *and* "R-y-c-h-l-e-j-š-í r-ů-s-t") — the cheapest available defence against the render model silently dropping or flattening diacritics, and the reason `onimage_text_language` and the CS `vision_check` hint exist in `10-pipeline.md` FR-101.

**FR-187 — Quality tier follows text presence (advisory; no config key on the shipped profile).** Any job with on-image text requests quality tier `medium` or `high`; `low` is reserved for layout-only drafts with no text, since low degrades text first. **OQ-7 closed (2026-08-09): Kie exposes no quality tier on either `gpt-image-2` route**, so the `image_quality_tier` config key was removed in v1.6.1 — this rule binds only future profiles whose provider exposes tiers, at which point the key returns with that profile.

**FR-188 — Short headlines are a rendering rule, not just a copy rule.** `10-pipeline.md` FR-101 is the behavior owner and hard-enforcer of character budgets on on-image text at the copy stage; this file states the render-side reason they exist — long or dense text degrades reliably on this model, and a paragraph is an overlay problem, not a generation problem. The concrete budget values (image_headline 42 chars, image_subline 60 chars, reel_seed_headline 32 chars, retry_reduction_pct 40) live in `30-configuration.md`'s `text_budgets` key; this file's requirement is only that the render prompt embeds the applicable budget as a hard constraint.

**FR-189 — Style-DNA scaffold, repeated verbatim across slides.** For carousels, a fixed block — palette hexes, typography rules, layout grid, mood, brand motif, all sourced from the style brief's `layout_zones` and descriptive fields — is repeated **verbatim** in every slide's prompt; only the content fields (headline, body text, slide index) change between slides. This is what makes a deck read as one deck: drift prevention through templating, not through any per-slide consistency check (`10-pipeline.md` FR-20 explicitly has none).

**FR-190 — Stateless calls, explicit anchor reference.** Every slide job is an independent, stateless API call — never a conversational thread across slides. Chaining slides through one chat session lets earlier images leak spatial structure into later ones ("same-chat ghosting"), which defeats the purpose of the style-DNA scaffold. Consistency across slides comes from the repeated scaffold (FR-189) plus, when `carousel_anchor` is on, the finished slide 1 attached as an explicit reference image with a role label (`10-pipeline.md` FR-95) — never from shared conversational state.

**FR-191 — Every reference image gets a labeled role.** Every reference image attached to a job is introduced in the prompt by index and role, with an explicit statement of what it must *not* contribute — for example "Image 1: style and layout reference only — do not copy its text, logos, watermark or UI." The model is never left to infer what a reference is for. This is the render-side statement of the same discipline `10-pipeline.md` FR-91 applies to reference *selection*; the mandatory exclusion clause itself is FR-94 and is not restated here.

**FR-192 — Production ceiling and aspect handling.** Resolution requests stay at or below 2K (2560×1440); above that the model is documented as unstable. Aspect ratio is passed as an API parameter, never as prompt text — already stated as mandatory clause 4 of `10-pipeline.md` FR-94, restated here only because it is part of this playbook's discipline, not a new rule.

**FR-193 — Retries repeat the full preserve list.** When a render is close but needs one change (shorter headline, different focal element), the retry prompt describes only that one change but **repeats the entire style-DNA scaffold and exclusion clause in full** rather than assuming the model remembers the previous attempt. Drift is the default behaviour on a single-change follow-up that omits context; repeating the preserve list is the cheap defence. This governs `10-pipeline.md`'s single retry paths (FR-97 moderation resubmission, FR-105 vision-check retry) as well as any manual re-render.

**On the JSON question.** Research shows structured, JSON-shaped prompts are one valid format among several for this model — there is no evidence JSON itself makes the model render better than an equally labeled prose scaffold would. Its real value for this project is engineering discipline: reproducibility, easy parameterization per slide, and drift prevention. The templates in `prompts/` are therefore structured, labeled blocks — JSON-shaped where that's convenient for the placeholder contract — not because the model parses JSON specially, but because a labeled scaffold is what makes FR-189's "verbatim except content fields" rule mechanically enforceable.

**Note — Thinking-Mode multi-image batch: dropped (OQ-7 closed 2026-08-09).** The reported ≤8-consistent-images-per-call mode is **not present anywhere in Kie's documentation**, so the build-time experiment is cancelled. Anchor chaining (`10-pipeline.md` FR-95) is the only carousel path.

---

## 4. Seedance 2.5 profile playbook (reels)

Sourced from BytePlus/Dreamina official guidance plus converged community practice, this section states the rules the `reel_director.md` template must encode, wrapping the model's official formula — six elements counting Subject and Action separately (Subject, Action, Scene, Style, Camera, Audio) — in a fuller director structure.

**FR-194 — Director-format structure.** Every reel prompt follows nine labeled sections in order: **GOAL** (what a successful clip looks like), **REFERENCES** (every `@`-tag explained), **CONTINUITY** (what must stay fixed across the clip), **SCENE** (location/setting), **STAGES** (the shot list), **LOOK** (format, grain, lighting, mood), **CAMERA & PERFORMANCE** (the actual camera move, named), **AUDIO** (bracketed cues), **RULES** (the closing exclusion block). This is the community wrapper around the model's official formula, and it is what the `reel_director.md` template's section headings look like. `00-overview` D25 and `10-pipeline` FR-23 defer to this requirement by reference.

**FR-195 — One sentence per `@`-tag: contribution and exclusion.** Every referenced asset (`@Image1`, `@Video1`) gets exactly one sentence stating what it contributes to the render and one clause stating what it must *not* contribute. The model is never left to infer a reference's role — the same discipline as FR-191 for images, applied to Seedance's tagging syntax.

**FR-196 — `@Image1` is the seed frame and locks the aspect ratio.** Per `10-pipeline.md` FR-24, the seed frame (rendered by GPT Image 2 with the hook text baked in) is `@Image1` and is described in the prompt as the first-frame anchor. The seed frame is **requested from GPT Image 2 at a model-native size of exactly 9:16** — 9:16 is on Kie's verified `aspect_ratio` menu (20-integrations §8c), so "exactly" is achievable on the shipped profile; FR-98's nearest-size fallback exists only for a future profile whose menu lacks the ratio. No local crop; crop/pad applies only to terminal delivery assets, because the Kie-hosted public URL returned by the image job is what Seedance receives and must lock the reel to 9:16 — reels stay 9:16 on every platform.

**FR-197 — Hook text is protected via CONTINUITY and RULES, never via the generative subtitle bracket.** Seedance's bracket taxonomy routes different content differently: `( )` for music/ambience, `< >` for sound effects, `{ }` for spoken dialogue, and `【 】` for model-*generated* on-screen subtitles. The seed frame's baked-in hook text is pixels the model inherited from its first frame, not a protected layer — protecting it means stating explicitly, in CONTINUITY and again in RULES, that the on-frame text stays fixed in position, size, font and content, and must not animate, fade, warp, shift or reword. **The hook text is never routed through `【 】`** — doing so would ask the model to *generate* a subtitle, duplicating or drifting from the baked text instead of preserving it.

**FR-198 — Bracket taxonomy for audio (MVP scope).** The AUDIO section uses only `( )` for music/ambience and `< >` for sound effects in the MVP — `{ }` dialogue brackets are not used, because HypeSocials generates no spoken dialogue by default. If a future config ever enables dialogue, the language must be declared in the prompt before the first dialogue bracket, per the model's own requirement — noted here for completeness, not built.

**FR-199 — `@Video1` is the winning viral video, scoped to motion and pacing only.** Per `10-pipeline.md` FR-142, when a qualifying viral-video reference is available it is `@Video1`, and its REFERENCES sentence states explicitly that it contributes **only** cut pacing, handheld rhythm and beat timing — with an exclusion clause naming everything it must *not* contribute: its people, wardrobe, location, captions, logos, music and voice. This is the render-side statement of FR-142's "motion, not content" framing.

**Additional playbook rules, encoded but not separately numbered (each maps to an existing FR or is pure template wording, not new engine behaviour):**

- **STAGES** get 2–4 timed beats for any clip over 5 seconds, each beat naming one primary change and its rough timing (e.g. "0–1.5s — hook hold — static frame, text legible"). Motion is always described explicitly and qualitatively ("small natural handheld shake"), never as a numeric parameter — Seedance has none.
- **UGC realism vocabulary** — "handheld, phone-camera look, available light, slight grain, no 3D, no cartoon, no VFX" — is applied in LOOK whenever the assigned trend is UGC-class, sourced from the style brief's content-angle field.
- **AUDIO stays lean**: one ambience/music cue matched to the trend's vibe, plus at most one sound effect. This maps directly onto `10-pipeline.md` FR-141 (`reel_audio`, provider-native) — no new audio mechanism, just the prompt wording that shapes what the model generates.
- **RULES closes every prompt** with the standard exclusion block: no new on-screen text or subtitles beyond the protected hook, no logos or watermarks, no duplicate subject, no hard location cuts, no movement or rewording of the protected text.
- **Duration stays in the 5–10 second sweet spot** by default, consistent with `10-pipeline.md` FR-103's clamp to the 4–30 s range — this is a template default, not a new validation rule.
- **Draft-cheap-then-finalize** (validate short/low-res before committing to a full-price render) maps onto the project's existing preview/estimate philosophy (`10-pipeline.md` D19, FR-28) — no new mechanism is introduced for it here.
- **`return_last_frame`** (extracting a clip's final frame to seed a follow-up clip) is noted as a future lever for series-style content across multiple runs. Not used in MVP; no requirement created for it.

---

## 5. Copy-model prompts (Luna) and style-brief prompts (Sonnet 5)

The system prompts for Luna (copywriting) and Sonnet 5 (visual analysis) also live in `prompts/` as `copywriter_system.md` and `style_brief_system.md`, following the same load/fallback/logging rules as sections 2–4. This file owns only *where those templates live and their placeholder contract* — the substantive obligations they must encode are already specified in `10-pipeline.md` and are not restated here, only cross-referenced:

- The forensic-analyst framing and ban on vague adjectives for the style brief — `10-pipeline.md` FR-10.
- The structural-mimicry obligation for hooks (restate the abstract pattern, then instantiate it) and the 3–5 verbatim source hooks supplied as few-shot exemplars — `10-pipeline.md` FR-100.
- The distinct-angles requirement across siblings sharing one copy call — `10-pipeline.md` FR-99.

`copywriter_system.md`'s placeholder contract includes `{{sibling_list}}`, `{{source_hooks}}`, `{{style_brief_summary}}`, `{{platform_conventions}}`, `{{brand_context}}` (empty when `notion_influence` is `off`). `style_brief_system.md`'s placeholder contract includes `{{reference_image_count}}`, `{{trend_texts}}`, `{{engagement_numbers}}`, `{{output_format}}` (the required JSON field list of FR-92). Neither template introduces any field not already defined in `10-pipeline.md`.

---

## 6. Worked examples (non-normative)

These two examples are illustrative only — adapted from research, kept short — and exist solely to make the playbooks above concrete. They are not additional requirements; nothing here overrides sections 3–4.

**(a) Carousel slide scaffold (slide 3 of 6, `carousel_slide.md` filled):**

```
FORMAT: Instagram carousel slide, 1:1, slide 3 of 6.

STYLE_DNA (verbatim across all 6 slides):
  palette: #1B1F3B background, #F4C95D accent, #FFFFFF text
  typography: bold condensed sans, headline ~64px, sentence case
  layout_grid: centered subject, headline upper-third, badge lower-right
  brand_motif: thin accent-colour rule under every headline
  mood: high-contrast, energetic, screenshot-adjacent

REFERENCE IMAGES:
  Image 1 — finished slide 1 of this deck. PRIMARY reference: reproduce
    this exact template, palette, typography, margins. Do not copy its
    text or its focal subject — only its structure.
  Image 2, 3 — trend slideshow panels. Style/layout reference only —
    do not copy their text, logos, watermark or platform UI.

SLIDE CONTENT:
  slide_number_badge: "3/6"
  headline (render verbatim, no extra characters): "Většina lidí to dělá špatně"
    spelled out: V-ě-t-š-i-n-a l-i-d-í t-o d-ě-l-á š-p-a-t-n-ě
  body_text: none this slide
  focal_element: single upward arrow icon, accent colour

CONSTRAINTS: match STYLE_DNA exactly; render all text verbatim including
  diacritics; no watermark, no platform UI, no usernames, no engagement
  counters; keep grid identical to Image 1; text within central 80% of frame.
```

**(b) Reel director-format prompt (`reel_director.md` filled):**

```
GOAL: A 7-second vertical reel that opens on a static hook frame with
  legible text, then shows the product in quick, energetic motion —
  matching the pacing of the trend's winning clip.

REFERENCES:
  @Image1 — the seed frame (9:16). Defines subject, framing, background,
    and the static hook text "Toto nikdo neříká" in the top third. This
    is the first frame. Do not change composition; do not move, resize,
    reword or remove the text.
  @Video1 — winning viral clip. Provides ONLY cut pacing, handheld
    rhythm and beat timing. Exclude its people, wardrobe, location,
    captions, logos, music and voice.

CONTINUITY: Hook text stays fixed in position, size, font and content —
  a static graphic layer, not a subtitle. Subject and background from
  @Image1 persist unchanged in colour and identity throughout.

SCENE: Same setting as @Image1 — a plain interior, no added elements.

STAGES:
  Stage 1 (0–1.5s) — hook hold — frame static, hook text fully legible.
  Stage 2 (1.5–5s) — reveal — subject animates naturally, camera drifts in.
  Stage 3 (5–7s) — payoff — slight push-in, motion settles to a stop.

LOOK: handheld phone-camera look, available light, slight grain,
  no 3D, no cartoon, no VFX.

CAMERA & PERFORMANCE: slow handheld push-in, no cuts, natural micro-shake.

AUDIO: (upbeat trending-style instrumental matched to @Video1 tempo)
  <soft camera-shutter click at 0s> — no copyrighted lyrics.

RULES: keep hook text exactly as specified in CONTINUITY; no new
  on-screen text or subtitles; no logos or watermarks; no duplicate
  subject; no hard location cuts; 9:16 throughout.
```

---

## 7. Edge cases and failure modes

Consistent with the pipeline-wide philosophy in `10-pipeline.md` section 10: degrade and report, never block.

| Situation | Consequence |
|---|---|
| Template file missing or corrupt | Built-in default used for that role; warning logged with file name and reason (FR-183). |
| A placeholder is left unresolved after assembly | That creative fails **before submission** — the engine never sends a prompt containing a raw placeholder token to a paid API. The failure is a logged skip like any other plan-entry failure (`10-pipeline.md` section 10). |
| Assembled template exceeds a model's prompt length limit | The style-DNA / descriptive portion is truncated first. The exact text block and the exclusion clauses are **never** truncated — a prompt that renders the wrong style is a lesser failure than one that renders the wrong text or skips the exclusion clause. |
| Kie's Seedance tier exposes fewer reference slots than the full 2.5 budget (OQ-6) | The engine caps reference counts (images/videos/audio) at whatever limit is verified at build for the routed tier; excess references are simply not attached, logged. |
| Kie does not expose GPT Image 2 quality tiers or the Thinking-Mode batch (OQ-7 — confirmed) | The `image_quality_tier` config key was removed (v1.6.1); FR-187 stays advisory for future profiles. The multi-image batch experiment is dropped and anchor chaining remains the only carousel path. |

---

## 8. Placeholder Resolution & Template Safety (FR-260–269)

**FR-260 — Unresolved placeholder = template bug, caught before submission.** If a template placeholder remains unresolved after assembly (the placeholder syntax is present in the filled template but the assembly process could not provide a value for it), that is a template bug: the creative fails before submission with a clear template error message, the engine never sends a prompt containing a raw `{{...}}` token to any paid API, and the failure is logged as a plan-entry skip (per `10-pipeline.md` section 10).

**FR-261 — Placeholders resolve from secret-free context only.** Template placeholder resolution reads exclusively from a purpose-built prompt-context object containing only (a) fields from the style brief (layout, palette, typography, mood, etc.), (b) copy output (captions, hooks, on-image text, hashtags), and (c) an allowlisted set of non-secret config values (e.g. brand name, product names, platform identifiers — never API keys, secrets, or raw config trees). The engine never interpolates process environment variables, raw config trees, or any value marked secret into template placeholders. This architecture is the guarantee behind D30's "no placeholder can resolve to a secret." A placeholder that attempts to reference anything outside the context object is an unresolved placeholder (FR-260).

---

## 9. Design Decisions

**D24 — Editable `prompts/` folder.** Prompt quality is the single biggest lever on this product's output quality — bigger than any code change. Putting the model-facing scaffolding in plain, editable text files (rather than embedding it in engine code) lets the user tune wording, add a missed exclusion, or adjust a section order without touching Python or waiting for a release. The fallback-to-default rule (FR-183) means an editing mistake degrades gracefully instead of breaking the run, so the folder is safe to hand to a non-engineer.

**D25 — Model-specific playbooks, codified once, applied every run.** GPT Image 2 and Seedance 2.5 each respond best to a distinct prompt shape, drawn from official vendor docs, community-converged practice, and the operator's own transcripted experience (source-graded in the underlying research). Writing that expertise into the `prompts/` templates once means every run benefits automatically — the engine does not re-derive "how does this model like to be asked" per creative, it just fills a scaffold that already encodes the answer.

**D34 — Model profiles with per-profile prompt template sets.** Every render model is accessed through a model profile (20-integrations FR-272): a configuration bundle defining parameter mappings, reference limits, and which `prompts/` template set that profile uses. This architecture lets model IDs be swappable within a profile without changing templates (e.g., `seedance-2-5` to `seedance-2-5-fast`). Two profiles ship: `gpt-image-2` (with playbook FR-185–193, section 3) and `seedance-2-5` (with playbook FR-194–199, section 4). Adopting a new model family (Kling, Veo, etc.) requires registering the new profile and authoring its template set per the vendor's guidance; this is the promptcraft half of the model-onboarding recipe (20-integrations FR-273). Unknown profiles are refused at pre-flight (FR-263), never at runtime.

**D35 — Campaign briefs use standard template sets.** Product-photo-to-ad and other campaign-brief use cases (D26, 30-configuration) overlay copy and visual directives on trend-based generation, using the same `gpt-image-2` and `seedance-2-5` template sets as all other runs. Brief directives (message, CTA, style tweaks) flow through existing template placeholders; the influence model (`override` or `blend`) determines priority. No separate brief-specific templates are required or created.

---

## 10. Open questions

- **OQ-6 — CLOSED (2026-08-09).** Kie's `bytedance/seedance-2-5` route serves the full-2.5 budget: 30 reference images (<30 MB each), 10 reference videos totalling ≤30 s (<200 MB each), 10 reference audio clips totalling ≤30 s. The engine caps at these documented limits (edge-case table, section 7, now moot on the shipped profile).
- **OQ-7 — CLOSED (2026-08-09).** Kie exposes **no** GPT Image 2 quality tiers on either route (the `image_quality_tier` key was removed in v1.6.1; FR-187 is advisory for future profiles) and the Thinking-Mode multi-image batch appears nowhere in Kie's docs (experiment dropped; section 3 note).
