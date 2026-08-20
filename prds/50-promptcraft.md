# 50 — Promptcraft

**Amendment: v2.2.0 (2026-08-14, D49–D53)** — Gauntlet prompt artifacts (four new template files), FR-315 crop validation and tool-mark specifics, verdict schema gains language/audience_fit.

## TL;DR — Plain English

This file answers one question: who actually writes the text that gets sent to the image model and the video model, and what does that text look like?

The short answer: nobody writes it fresh every time. A **local, versioned meta-style registry** (26 textual definitions) describes how each creative should look — colors, layout, typography, mood. The registry is your visual authority and is editable in `prompts/styles.yaml`. That style drops into **templates**: ready-made, battle-tested prompt skeletons, one shape for a single image, one for a carousel slide, one for a reel. The templates live in an editable `prompts/` folder as plain text files, so a human can tune the wording without touching code. The **copy** comes verbatim from the source posts (no rewriting). (Verbatim is the default and, since D58, is what the shipped brand configs use too; D54 compress mode for bound carousel decks — panel text LLM-compressed to the style budget in the source language per FR-332 — is still shipped and is enabled for a single run with `--copy-mode compress`.) The engine's job is just to fill in the blanks — style here, copy text there, the wordmark and exclusion rules always — and send the result off. Nothing is invented on the fly.

- The **meta-style registry** (`prompts/styles.yaml`) supplies the visual substance — colors, typography, layout, motion profile — already written once and reused (D41). Twenty-six textual style definitions (9 originals + build-log-mono + 4 archetype + 5 teal variants + 7 carousel-derived, D56–D57 + D61), deterministically rotated or matched per creative.
- The `prompts/` folder supplies the **shape** (how GPT Image 2 likes to be asked, how Seedance likes to be asked) — editable templates per model profile.
- The **copy text** is **verbatim from source posts** — selected by the engine's reference mechanism, not rewritten by any LLM (D42). (Verbatim is the default and, since D58, is what the shipped brand configs use too; D54 compress mode for bound carousel decks — panel text LLM-compressed to the style budget in the source language per FR-332 — is still shipped and is enabled for a single run with `--copy-mode compress`.)
- The engine supplies the **glue**: it fills the shape with style + copy, deterministically, every time, and never invents words.
- Each image model and video model gets its prompt written the way *that* model actually responds best to — that's the whole idea of this file.

---

This file is the single authoritative spec for the shape of every generation prompt the engine sends — how it is assembled, where its scaffolding lives, and the model-specific playbooks that scaffolding encodes. It extends `10-pipeline.md` (which owns the pipeline rules, FR-17/FR-94; carousels, FR-95; reels, FR-24) and `prds/30-configuration-and-run.md` (which owns the meta-style registry, FR-290) rather than restating or contradicting them — this file cross-references those requirements throughout instead of duplicating them.

Requirement range owned by this file: **FR-180 … FR-199, FR-260–269**; **NFR-180 … NFR-185 are reserved for this file and currently unused** (none defined yet — stated so the range claim doesn't imply lost content).

---

## 1. Who designs the prompt

Two cooperating layers each own what they are best at. None of them is redundant with another, and none of them requires an extra model call beyond what `10-pipeline.md` already specifies.

**(a) The meta-style registry — visual substance, per creative.** Specified in full in `prds/30-configuration-and-run.md` and 20-integrations.md §3 (FR-290/291). A `prompts/styles.yaml` registry holds nineteen textual style definitions (9 originals + build-log-mono + 4 archetype + 5 teal variants; D56–D57), each supplying palette (named color hex values), typography (font names and character descriptions), layout zones (positions and text treatment), and motion profile (for reels). The registry is the visual authority — it is deterministically rotated (not randomly selected) or matched per the brand-filtered style pool. This is the substance: *what does this specific style look like, in reproducible terms.*

**(b) Editable prompt templates — model-specific scaffolding and copy contract.** A `prompts/` folder holds one small text file per prompt role — the copywriter system prompt, the image render scaffold, the carousel slide scaffold, the carousel anchor-slide instruction, the reel director scaffold, the vision-check question, the topic-filter system prompt. Each file is the *shape* a given model responds best to, with named placeholders where run-specific content drops in (style + copy text + mandatory clauses). These templates encode the model playbooks in sections 3–5 below — they are the expertise, written down once and reused every run (D24). The copywriter returns **reference selections** (which exact source strings to render), and the engine **resolves the references to bytes** — the verbatim-copy contract lives here (D42, §1.7) (or, under D54 compress mode, compressed panel text per FR-332 — same call discipline, free text instead of references).

**(c) Deterministic assembly — the engine's glue.** Plain code fills each template's placeholders from the assigned style, the copy references and resolved text, the branding block, and the mandatory clauses, then sends the result. Assembly never invents content, never asks a model to improvise the scaffold, and never adds an LLM call: the templates already encode what expertise an LLM call would have re-derived every time. This is the principle FR-17 already states for image prompts — this file generalizes it to every model.

**FR-180 — No hidden fourth layer.** Every render prompt sent by the engine is fully accounted for by (a) a style brief field, (b) a template file, or (c) a mandatory clause defined in this file or in `10-pipeline.md`. There is no prompt text that exists only in engine code and nowhere else — if it isn't in a template or a brief, it doesn't belong in a prompt. The mandatory clause-(c) lines generated by engine code — including audio cues, @Image reference descriptions, reference role instructions, vision-check retry guidance, and brand/brief context lines — are enumerated in `prompts/README.md`'s table.

---

## 2. The `prompts/` folder (D24)

**FR-181** *(amended v2.2.0, D49; v2.3.0, D54; v2.4.0, D56)*: Templates are files, hot-loaded per run, in a two-level layout. The fifteen prompt roles split by what owns them:

- **Ten global role templates, flat in `prompts/`** — `copywriter_system.md` (verbatim copy reference selection), **`copy_compress_system.md`** (D54 compress-mode copy system prompt, FR-332), `topic_filter_system.md` (competitor filter screen), `slide_intel_question.md` (per-slide transcription + visual brief, v2.1.0), **`style_match_system.md`** (D56 matched style assignment screen, FR-334/335, v2.4.0), **`critic_brief.md`, `critic_system.md`, `critic_craft.md`** (v2.2.0 — three-critic gate verdicts, fresh-context per round per-frame-level contract inspection), **`gauntlet_fix.md`** (v2.2.0 — canned remedy sentences keyed by defect code + zone, conflict-precedence block, fence-closing line), and the **meta-style registry `styles.yaml`** (19 textual style definitions; 9 originals + build-log-mono + 4 archetype + 5 teal variants, D56–D57). `vision_check_question.md` was the ninth until v2.2.0 and is **retired with the FR-105 machinery** (D49) — the three critic templates replace it. These belong to OpenRouter LLM roles, the gauntlet logic, or the visual authority, not to any render-model profile, and exist exactly once (or built-in default for fallback). **Note:** `prompts/humanizer_skill.md` also lives flat in `prompts/` but is NOT a prompt role — it is a vendored reference document (MIT, github.com/blader/humanizer) the engine never loads. The distilled subset of humanization patterns lives inside `copy_compress_system.md` (FR-332).
- **Per-profile render template sets, under `prompts/<profile>/`** — for `gpt-image-2`: `image_post.md`, `carousel_slide.md`, `carousel_anchor_instruction.md`, `reel_seed_frame.md`; for `seedance-2-5`: `reel_director.md`. A second render profile added later gets its own subfolder with its own complete set; flat filenames could never hold two profiles' sets simultaneously.

Files are read fresh at the start of each run (not compiled or cached across runs), so an edit takes effect on the very next run with no build step, no restart of anything beyond the run itself. `reel_seed_frame.md` is the seed-frame image render scaffold. Gauntlet templates (`critic_*.md`, `gauntlet_fix.md`) are new in v2.2.0 and carry per-critic defect enums (FR-322–327).

**FR-182** *(amended v2.0.0, v2.1.0)*: Named placeholders, filled by assembly only. Each template contains named placeholders (for example `{{style_dna}}`, `{{onimage_text}}`, `{{visual_brief}}`, `{{exclusions}}`, `{{branding_block}}`, `{{wordmark}}`, `{{topic_items}}`, `{{competitor_list}}`, `{{motion_profile}}`, `{{motion_beat}}`, `{{slide_index}}`, `{{slide_panels}}`, `{{source_hooks}}`, `{{seed_frame_ref}}`, `{{audio_cue}}`) that the assembly step in section 1(c) fills from the assigned style, the copy references and resolved text, the branding config, and the mandatory clauses. Per-slide placeholders include `{{visual_brief}}` (content directive, English) and `{{slide_panels}}` (candidate text from source slides, position-aligned). Placeholders are plain string substitution — no expression language, no conditionals, no loops inside a template. If a template needs a field the assembly step doesn't provide, that is a template bug, caught at fill time (FR-260).

**FR-183** *(amended v2.0.0)*: Missing or corrupt template falls back to the built-in default (except styles.yaml). Every template file has a built-in default compiled into the engine that implements the playbook rules in sections 3–5; the worked examples in section 6 are illustrative only, not the canonical built-in text. If a file is missing, unreadable, or fails to parse its placeholders, the engine uses the built-in default for that role and writes a warning to the run log naming the file and the reason. **The registry `prompts/styles.yaml` is EXEMPT — it has no built-in tier, so a missing or broken registry is a pre-flight refusal (FR-295), not a degradation.** Template (not registry) roles degrade rather than block (matching the pipeline-wide philosophy).

**FR-184** *(amended v2.0.0)*: Templates and registry are logged for attribution. Every run log records: once per template role actually used, the file name and a content hash (enabling future attribution of generated assets to specific versions); once per run, the registry version, file name, and content hash (enabling future tracking of visual style drift). This makes every generated asset's prompt and style attributable to specific versions — if a user tunes `carousel_slide.md` or edits `styles.yaml` between runs, the log shows which run used which wording/styling.

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

**FR-188 — Short headlines are a rendering rule, not just a copy rule.** `10-pipeline.md` FR-101 is the behavior owner and hard-enforcer of character budgets on on-image text at the copy stage; this file states the render-side reason they exist — long or dense text degrades reliably on this model, and a paragraph is an overlay problem, not a generation problem. The concrete budget values (image_headline 90 chars, image_subline 160 chars, slide 300 chars, reel_seed_headline 60 chars, retry_reduction_pct 40) live in `prds/30-configuration-and-run.md`'s `text_budgets` key; this file's requirement is only that the render prompt embeds the applicable budget as a hard constraint.

**FR-189** *(amended v2.1.0)*: Style-DNA scaffold, sole mechanism for visual consistency. For carousels, a fixed block — palette hexes, typography rules, layout grid, mood, and motion profile (the textual style definition fields from the `MetaStyle` registry record) — is repeated **verbatim** in every slide's prompt; only the content fields (headline, body text, slide index, visual brief) change between slides. **This textual scaffold is the SOLE visual-consistency mechanism** — no style reference images are attached to render jobs. Drift prevention works through templating the scaffold itself, not through reference images or per-slide consistency checks (`10-pipeline.md` FR-20 explicitly has none).

**FR-190 — Stateless calls, explicit anchor reference.** Every slide job is an independent, stateless API call — never a conversational thread across slides. Chaining slides through one chat session lets earlier images leak spatial structure into later ones ("same-chat ghosting"), which defeats the purpose of the style-DNA scaffold. Consistency across slides comes from the repeated scaffold (FR-189) plus, when `carousel_anchor` is on, the finished slide 1 attached as an explicit reference image with a role label (`10-pipeline.md` FR-95) — never from shared conversational state.

**FR-191** *(amended v2.0.0, v2.1.0)*: **Reference images: labeled role for brief, anchor, and seed frames only.** When a reference image is attached (brief images per FR-145, carousel anchor slide per FR-95, reel seed frame per FR-24), it is introduced in the prompt by index and role, with an explicit statement of what it must *not* contribute — for example "Image 1: anchor slide reference — reproduce this exact template, palette, typography, margins. Do not copy its text or focal subject — only its structure." The model is never left to infer what a reference is for. This is the render-side statement of the same discipline `10-pipeline.md` FR-18 applies to reference *attachment*; the mandatory exclusion clause itself is FR-94 and is not restated here. **Style reference images are not used** — the textual style-DNA scaffold (FR-189) carries the look (D46 decision).

**FR-192 — Production ceiling and aspect handling.** Resolution requests stay at or below 2K (2560×1440); above that the model is documented as unstable. Aspect ratio is passed as an API parameter, never as prompt text — already stated as mandatory clause 4 of `10-pipeline.md` FR-94, restated here only because it is part of this playbook's discipline, not a new rule.

**FR-193** *(amended v2.0.0)*: **Retries repeat the full style-DNA scaffold and exclusion clause in full.** When a render is close but needs one change (shorter headline, different focal element), the retry prompt describes only that one change but **repeats the entire textual style-DNA scaffold and exclusion clause verbatim**, carrying the visual brief unchanged. Drift is the default behaviour on a single-change follow-up that omits context; repeating the full scaffold is the cheap defence. This governs `10-pipeline.md`'s single retry paths (FR-97 moderation resubmission, FR-105 vision-check retry) as well as any manual re-render.

**FR-308 — Visual-brief rendering: content directive subordinate to style DNA (amended v2.1.3, D48).** Each carousel slide's render prompt carries that slide's `visual_brief` (per-slide content directive, returned by the slide-intelligence step per `20-integrations.md` FR-306) as a distinct, labeled section positioned between STYLE_DNA and CONSTRAINTS. The brief describes the visual *content* of that slide in English — layout, graphics, icons, charts, composition — *not* the style/look/treatment, which the style DNA already governs. The brief must comply with FR-316's content contract (foreground-only, no scenery/colors/chrome). **Brand safety (amended v2.1.3, D48):** when a third-party tool/product logo is named in the on-image TEXT or detected in the slide's `brand_marks` list (D-A), the pipeline crops that mark's actual pixels from the source slide and attaches the cropped patch as a render reference with explicit pixel-faithful copy instruction (FR-315); if no usable patch exists, the mark falls back to name + written description. Competitor logos (from `branding.competitors` + strip list) are genericized ("a generic chat-app logo shape"), never reproduced, only when no sanctioned mark exists for that name (FR-315 fallback). Platform chrome, watermarks, and usernames are excluded outright from render directives. On-image text (from source panels) stays verbatim in the source language and is never genericized.

**FR-310 — Tool-mark fidelity and vision-check sanction list (v2.1.2, D-A).** When a third-party tool or product name (Claude, Notion, Canva, Midjourney, n8n, Zapier, etc.) appears in the on-image text or is detected in the slide's `brand_marks` list extracted by vision analysis (FR-306), the render instruction lists that mark as a **sanctioned mark** — the image model is explicitly instructed to render it as the real, recognizable logo in its true brand colors, exempt from the assigned style's palette constraints. The prompt carries the sanctioned mark list; the vision-check question (FR-27) exempts marks named in that list and the expected on-image text from the `fake_ui` and text-mismatch defect categories. Competitor marks and platform chrome remain genericized and excluded per FR-308.

**FR-311 — Deck scene continuity: anchor instruction and per-slide visual briefs (v2.1.2, D-B; amended v2.1.3, D48).** The carousel anchor slide 1 establishes the **scene, camera angle, background environment, and text-block position** as the fixed template for the entire deck. Every subsequent slide's `visual_brief` (FR-308) describes the visual *content* — product features, data, graphics — that is **placed INTO that anchor's established scene**, never a different scene. When the brief describes scenery that conflicts with the anchor's background, the **anchor's established scene wins** — the visual brief's content directive is composed into the existing spatial structure. This ensures the deck remains visually coherent across all N slides. **Image-to-image enforcement (v2.1.3, D48):** the lock is now enforced by submitting every reference-bearing render (anchor, slides with pixel-reference tool marks, reel seed frame) to the image-to-image route rather than text-to-image; previously such jobs were mis-routed to text-to-image, which weakened reference adherence — this was a defect. Tool-mark placement (FR-315) is part of the locked frame: the mark renders in the same spatial position on every slide as it does on the anchor slide 1. Cross-reference: carousel anchor chaining (FR-95) provides the locked template at the image level; FR-311 reinforces the same discipline at the prompt level.

**FR-313 — Source-mirrored slide counter: locked engine-owned slot (v2.1.2, D-D).** When the source slideshow deck is numbered (detected from `chrome_text` lines like "01 / 06", "3/6", or leading "// 01" in-text prefixes, with denominator validation against `panel_count`), the render prompt instructs the model to render a **locked counter slide slot** in the **same format and visual position on every slide**, re-based to the output deck's length. Counter detection occurs in the vision-intelligence step (FR-306, 20-integrations §8d); rendering is owned by the template's presentation (50-promptcraft). The counter is an engine-owned template artifact — included in the vision check's expected text as a required element when present, omitted when absent — never an optional badge or invented element. When the source had no counter: the prompt explicitly states this, preventing the model from inventing slide-number headers or badges.

**Amended FR-105 — Vision-check re-render with defect callout (v2.1.2, D-F).** When a render is close but needs one change, the retry prompt describes the detected defect(s) explicitly — "the headline is garbled: '_...r_' should read 'faster'", "the UI counters are fake: '3 OF 8' never appeared on the original slide" — and repeats the entire textual style-DNA scaffold and exclusion clause verbatim. Invented strings are quoted back with the instruction "render them nowhere", ensuring the model understands what to remove and what to preserve. The [full] style-DNA scaffold and exclusion clause are never truncated by the ordinary cuttable pass; the defect description itself is the only thing that changes between attempts. *(Bounded by the provider ceiling, post-glz0 hotfix: when a retry assembly exceeds the hard prompt limit (19,800 chars — Kie refuses at >20,000), the last-resort trim may tail-trim the style scaffold above a 40% floor rather than submit a guaranteed-refused prompt; every such trim is logged `prompt_hard_trimmed`. The exclusion clause and the TEXT block remain absolute.)* Mapped panel-mapped text is a carve-out: it is never trimmed on retry — the −40% retry reduction applies to free-composed text only (captions, hooks), measured against that text's own governing slot per 10-pipeline FR-304 precedence (D-F, D-B context).

**FR-315 — Tool-mark pixel fidelity (amended v2.2.0, D49–D53).** For every sanctioned tool mark on a slide (a third-party tool or product name named in the slide's TEXT block and listed in `brand_marks`, per FR-306 and FR-310), the pipeline crops the mark's actual pixels from the source slide using the vision pass's bounding box and attaches the cropped patch as a render reference with a role instruction to copy the mark exactly — pixel-faithful, true brand colors, no redesign, no re-lettering. Requirements: **(a)** a mark named by the slide's TEXT block is a REQUIRED visual element — the vision check verifies every sanctioned mark is present, and a missing mark is a retryable defect; **(b)** fixed placement — the mark renders inside the TEXT block adjacent to the panel title in the SAME position on every slide of the deck (the anchor slide's placement wins), never floating in the scene; **(c)** URLs and bare domains are never sanctioned as tool marks; **(d)** if no usable patch exists (bad/missing bounding box, source image unavailable), the mark falls back to name + written description — fail-open, never blocks the slide. **(e) NEW v2.2.0 (D53):** crops are cut **only for sanctioned tool marks** (`kind=tool`, allow-gated via FR-310 list, never for §0.12 safety flags / creator identity / platform chrome). Full-frame fractions are tried first; content-rect remap (bounding-box crop) occurs only on validation failure. Cropped patches are validated non-degenerate before upload: minimum edge length, pixel-variance floor, collapsed-name deduplication (the same mark name appearing twice on one slide yields one unique crop). Validation failure falls back per requirement (d) — name + written description, never blocks. The residual risk noted in D47 (render model may still mangle marks; text_broken covers garble) persists but is now mitigated by pixel references and validation.

**FR-316 — Visual-brief content contract (v2.1.3, D48).** The `visual_brief` (per-slide content directive, returned by the vision-intelligence step per FR-306 and consumed per FR-308) is a **FOREGROUND-CONTENT-ONLY** directive: it may describe charts, tables, code/terminal blocks, icons, lists, diagrams, quantities and directions. It must NEVER describe: background scenery, rooms, photography or backdrop of the source slide; colors, typography, gradients or art direction; platform chrome, pagination widgets, watermarks, swipe cues; creator/account names. A deliberately-wordless slide (a panel dropped by the copy stage) carries a content-free brief so the brief cannot re-introduce text or invented widgets. At consumption time the brief additionally passes through the competitor/creator strip (FR-312 identifiers + the configured competitor terms) and participates in prompt truncation like every other context field (defense-in-depth for briefs stored by older runs).

**FR-338 — `{{counter_rule}}` render slot (new, v2.5.0, D59).** A new placeholder `{{counter_rule}}` on `gpt-image-2/carousel_slide.md` (and its byte-identical built-in twin), in the `_ALLOWLIST` for that template only, NEVER in `_TRUNCATION_ORDER` or the style trio. Rendered by `prompts_engine.counter_rule(style, slide_counter=...)` with a five-arm truth table: (a) no style → `""`; (b) style declares a `counter_slot` zone AND the deck is counted → that zone's line rendered by the SAME formatter the critic's `{{layout_zones}}` uses (renderer and critic read identical words); (c) declared zone but uncounted → the existing "no counter" absence line; (d) NO declared zone but counted → the house-default line `counter <value>: small, body family, top-right inside the safe area; no chip, no badge` (anticipates FR-350 house spine, Session K); (e) neither → `""`. Override briefs get `""`. The template line reads `COUNTER RULE (ignore if empty): {{counter_rule}}` followed by the sentence that this line outranks every chip/badge/page-number device STYLE_DNA describes: a zone line means the quoted counter renders there once and nowhere else; an absence line means no chip, badge, page number or "N of M" on ANY slide, slide 1 included. Critic amendments (FR-322–327): `style_consistency` gains "a chip, badge or signature that no frame's contract row calls for is never a reason to fail the frames that omit it; frame 1 carrying one it was not ordered is frame 1's own defect", and `style_layout` may not fail a carousel frame for a zone that reached no render channel; `gauntlet_fix.md`'s `counter_value | chip` remedy is re-worded so it cannot read as "draw a chip" when no counter is quoted, plus a new `style_consistency | chip` row refusing to propagate an unmandated chip (40 remedy rows, was 39). The sheet's PRECEDENCE block (emitted verbatim into every fix suffix, code twin `gauntlet.PRECEDENCE_BLOCK`) is narrowed by one word — "everything else stays as rendered, **a quoted** position badge and every sanctioned mark included" — because the unnarrowed sentence preserved an INVENTED chip across every re-render that did not name `counter_value`; the F7-C collateral-loss guard it carries protects the badge the TEXT block quotes, and a chip the TEXT block never quoted falls under precedence item 1. Since `fix_reserve()` is a pure function of that sheet, the effective slide body budget moves 18,277 → 18,272 (`MAX_PROMPT_CHARS` 19,800 unchanged).

**FR-340 — Empty-zone rule (new, v2.5.0, D59).** Both image render templates (`carousel_slide.md`, `image_post.md` + twins) replace the "renders empty or as a non-text graphic element (a rule, a bar, a shape, negative space)" licence with: a text zone with no string quoted is LEFT OUT of the frame — never filled with invented words, and never with a bar, rule, block or placeholder standing in for words; a repeating device (a row, a card, a chip) exists once per quoted line and not at all when none is quoted. The anchor-reference instruction (`carousel_anchor_instruction.md`, rendered over the primary reference's role line on every chained slide) carried the same licence ("renders empty or as a non-text graphic") and now says the zone "is left out — no bar, rule or placeholder in its place, never refilled from Image 1 or invented"; a guard test asserts the old phrase survives in no `prompts/*.md` and no built-in twin. (`reel_seed_frame.md` already says "stays wordless" — unchanged.) Registry consequences: the 7 "bottom 12% (4:5 crop)" band reservations become "all text inside the central 80% of a 1:1 frame" (frames render 1:1, `plan.py:83`); `icon-ledger-carousel`'s rows exist only where lines are quoted, a cover with only a headline draws no ledger rows, and **a line with no second part sets as the title alone and draws no description line — the title is never repeated under itself**; the styles.yaml authoring block states that any two-part row rule must state the one-part case.

**On the JSON question.** Research shows structured, JSON-shaped prompts are one valid format among several for this model — there is no evidence JSON itself makes the model render better than an equally labeled prose scaffold would. Its real value for this project is engineering discipline: reproducibility, easy parameterization per slide, and drift prevention. The templates in `prompts/` are therefore structured, labeled blocks — JSON-shaped where that's convenient for the placeholder contract — not because the model parses JSON specially, but because a labeled scaffold is what makes FR-189's "verbatim except content fields" rule mechanically enforceable.

**Note — Thinking-Mode multi-image batch: dropped (OQ-7 closed 2026-08-09).** The reported ≤8-consistent-images-per-call mode is **not present anywhere in Kie's documentation**, so the build-time experiment is cancelled. Anchor chaining (`10-pipeline.md` FR-95) is the only carousel path.

---

## 4. Seedance 2.5 profile playbook (reels)

Sourced from BytePlus/Dreamina official guidance plus converged community practice, this section states the rules the `reel_director.md` template must encode, wrapping the model's official formula — six elements counting Subject and Action separately (Subject, Action, Scene, Style, Camera, Audio) — in a fuller director structure.

**FR-194** *(amended v2.0.0)*: Director-format structure. Every reel prompt follows eight labeled sections in order (v2.0.0: removed @Video1 reference section): **GOAL** (what a successful clip looks like), **REFERENCES** (@Image1 only in v2.0.0), **CONTINUITY** (what must stay fixed), **SCENE** (location/setting), **STAGES** (the shot list with timed beats), **LOOK** (format, grain, lighting, mood — selects photographic vs graphic per style), **CAMERA & PERFORMANCE** (the camera move), **AUDIO** (bracketed cues), **RULES** (the closing exclusion block). This is the wrapped structure for the model's official elements, and it is what the `reel_director.md` template's section headings look like. `00-overview` D25 and `10-pipeline` FR-23 defer to this requirement by reference.

**FR-195** *(amended v2.0.0)*: One sentence per `@`-tag: contribution and exclusion. Every referenced asset (`@Image1` — v2.0.0: @Video1 motion reference removed) gets exactly one sentence stating what it contributes to the render and one clause stating what it must *not* contribute. The model is never left to infer a reference's role — the same discipline as FR-191 for images.

**FR-196** *(amended v2.0.0)*: `@Image1` is the seed frame and locks the aspect ratio. Per `10-pipeline.md` FR-24, the seed frame (rendered by GPT Image 2 with the hook text baked in) is `@Image1` and is described in the prompt as the first-frame anchor. The seed frame is **requested from GPT Image 2 at a model-native size of exactly 9:16** — 9:16 is on Kie's verified `aspect_ratio` menu, so "exactly" is achievable on the shipped profile. No local crop; the Kie-hosted URL returned by the image job is what Seedance receives and must lock the reel to 9:16 — reels stay 9:16 on every platform.

**FR-197** *(amended v2.0.0)*: Hook text is protected via CONTINUITY and RULES, never via the generative subtitle bracket. Seedance's bracket taxonomy routes different content differently: `( )` for music/ambience, `< >` for sound effects, `{ }` for spoken dialogue, and `【 】` for model-*generated* on-screen subtitles. The seed frame's baked-in hook text is pixels the model inherited from its first frame — protecting it means stating explicitly, in CONTINUITY and RULES, that the on-frame text stays fixed in position, size, font and content, and must not animate, fade, warp, shift or reword. **The hook text is never routed through `【 】`** — doing so would ask the model to *generate* a subtitle instead of preserving the baked-in text.

**FR-198 — Bracket taxonomy for audio (MVP scope).** The AUDIO section uses only `( )` for music/ambience and `< >` for sound effects in the MVP — `{ }` dialogue brackets are not used, because HypeSocials generates no spoken dialogue by default. If a future config ever enables dialogue, the language must be declared in the prompt before the first dialogue bracket, per the model's own requirement — noted here for completeness, not built.

**FR-199** *(v2.0.0: WITHDRAWN — `@Video1` motion reference removed in the topic-first pivot).* The reel generation path no longer downloads viral-video references via yt-dlp. Reels use only the seed frame (baked-in hook text) and the assigned style's motion profile; the motion-reference billing tier is not used (10-pipeline D23/D44, 20-integrations §8b).

**Additional playbook rules, encoded but not separately numbered (each maps to an existing FR or is pure template wording, not new engine behaviour):**

- **STAGES** get 2–4 timed beats for any clip over 5 seconds, each beat naming one primary change and its rough timing (e.g. "0–1.5s — hook hold — static frame, text legible"). Motion is always described explicitly and qualitatively ("small natural handheld shake"), never as a numeric parameter — Seedance has none.
- **UGC realism vocabulary** — "handheld, phone-camera look, available light, slight grain, no 3D, no cartoon, no VFX" — is applied in LOOK when the assigned style's `image_treatment` field or the topic texts signal a UGC aesthetic (v2.0.0: no content-angle field; read from the style registry directly).
- **AUDIO stays lean**: one ambience/music cue matched to the trend's vibe, plus at most one sound effect. This maps directly onto `10-pipeline.md` FR-141 (`reel_audio`, provider-native) — no new audio mechanism, just the prompt wording that shapes what the model generates.
- **RULES closes every prompt** with the standard exclusion block: no new on-screen text or subtitles beyond the protected hook, no logos or watermarks, no duplicate subject, no hard location cuts, no movement or rewording of the protected text.
- **Duration stays in the 5–10 second sweet spot** by default, consistent with `10-pipeline.md` FR-103's clamp to the 4–30 s range — this is a template default, not a new validation rule.
- **Draft-cheap-then-finalize** (validate short/low-res before committing to a full-price render) maps onto the project's existing preview/estimate philosophy (`10-pipeline.md` D19, FR-28) — no new mechanism is introduced for it here.
- **`return_last_frame`** (extracting a clip's final frame to seed a follow-up clip) is noted as a future lever for series-style content across multiple runs. Not used in MVP; no requirement created for it.

---

## 5. Gauntlet critic playbooks (v2.2.0)

Three fresh-context critics judge every deck's rendered frames (after delivery, before check/package) against a contract-only specification — per-frame expected text, counters, marks, style consistency, layout fidelity (FR-322–327). Each critic operates independently with zero knowledge of the others' verdicts or the assembled prompt. Templates: `critic_brief.md` (contract fidelity + leakage — presence/absence, never quality), `critic_system.md` (style contract + cross-frame consistency), `critic_craft.md` (execution quality — legibility/composition, never content). All three live flat in `prompts/`, hot-loaded per run, with built-in defaults for fallback. Per-critic defect enums defined in `20-integrations.md` FR-322–327 table (brief: missing_text, invented_text, translated, pair_break, missing_mark, forbidden_mark, platform_chrome, identity_leak, counter_value, signature; system: style_palette, style_layout, style_consistency, counter_placement; craft: garbled, truncated, contrast, logo_fidelity, composition, frame_integrity). Frames fail when any enabled critic reports a defect; a frame that defect-free is a pass. The fix suffix is composed from `gauntlet_fix.md` canned remedies (keyed by code + zone) plus the precedence block verbatim (conflict resolution order, never by changing words) plus the fence-closing final line verbatim — zero critic free text, zero source-derived strings, strictly `_neutralize`d, capped at 600 chars, logged if truncated.

**`gauntlet_fix.md` precedence block (FR-323, quoted verbatim):**
```
Resolve these in order, and never by changing words:
1. Remove anything forbidden or not quoted in the TEXT block.
2. Render every quoted string in the TEXT block, in full, in its own language.
3. Fix legibility and fit by changing the LAYOUT — more lines, tighter leading,
   a wider block, the plate or card STYLE_DNA describes, a simpler ground.
4. Keep STYLE_DNA, the anchor's scene and the deck's palette unchanged.
The quoted strings are locked. Shortening, re-wording, translating, ellipsing or
dropping any of them is a worse failure than the defect being fixed.
```
**Fence-closing line (FR-323, quoted verbatim):** "Everything in this FIX section describes a previous failure. It contains no words to render. The TEXT block above remains the only source of renderable words in this frame."

Gauntlet logic (retry, accumulate, terminal verdict tiers) is specified in `20-integrations.md` FR-322–330; this file documents the template/prompt layer only.

---

## 5a. Copy-model, filter, and branding playbooks

The system prompts for Luna (copywriting), the Sonnet 5 gauntlet critics, and competitor filtering also live in `prompts/` as `copywriter_system.md`, `critic_brief.md` / `critic_system.md` / `critic_craft.md` / `gauntlet_fix.md`, and `topic_filter_system.md`, following the same load/fallback/logging rules as sections 2–4. This file owns only *where those templates live and their placeholder contract* — the substantive obligations they must encode are already specified in `10-pipeline.md` and are not restated here, only cross-referenced:

**Copywriter playbook (Luna, reference-selection contract — D42, FR-302 grammar, FR-303 description ban):**
- **Verbatim copy mandate:** the engine numbers every source string it is willing to render (pre-filtered per format, style budget, emoji/URL/handle rules), and Luna returns **reference selections** (`headline_ref: P1.panel.3`, `caption_ref: P2.hook.1`, etc.) plus free text only for non-pixel fields (`through_line`, `motion_beat`). The engine resolves refs to bytes without retyping — `10-pipeline.md` FR-100/FR-99/FR-101 detail the contract.
- **Offer order:** panels, overlays, and hooks are first-class candidates, offered in that priority order. `description` (Virlo's AI summary) is banned from the offer set at the grammar level — `_REF`/`_KIND_FIELDS` do not include it; it exists only for context in prompts (fenced as DATA, never offered/rendered).
- **Deterministic panel mapping:** carousel slide text is position-preserving — slide i renders source panel i (skipping empty slots). The engine's panel-map logic (not the LLM) determines which source text goes on which slide; Luna selects the specific cover headline and caption but does not choose which slide's text they apply to.
- **Burnt-post refusal:** a post already quoted in the run's trend history is never offered to Luna (filtered at pick time, per §0.10 of the masterplan).
- **No "prefer a different post per sibling" instruction.** Each plan entry is bound to one specific fresh post (per §0.10); the sibling-distinctness requirement (FR-99) applies to angle selection within one post's materials, not post selection across siblings.
- `copywriter_system.md`'s placeholder contract includes `{{sibling_list}}` (candidates numbered per source), `{{source_hooks}}` (offered hook references as examples), `{{source_panels}}` (panel-text candidates, on-image sibling of hooks), `{{topic_texts}}` (fenced topic info as data), `{{platform_conventions}}`, `{{competitor_list}}` (brands to skip). No `style_brief_summary`, no `engagement_numbers`, no `description`, no `output_format` — those are deleted or fenced as context-only.

**Vision-check playbook — retired (v2.2.0, D49).**
- `vision_check_question.md` carried a binary quality judgment: pass, or suggest a specific re-render change. It is **retired with the FR-105 machinery**, not kept as a fallback lane — there is no path that re-enables it, because `run.gauntlet.enabled: false` means *no post-render gate at all*, not "the old check instead". Its two durable ideas are inherited by the Gauntlet: the `expected_text` referent construction and the verbatim-no-trim retry rule. **Its defect categories survive, redistributed across the per-critic enums (FR-322):** `text_broken` includes illegible, garbled, or low-contrast on-image text (e.g., dark text on dark background, letters rendered as noise or symbol soup, headlines unreadable even if letterforms are technically well-formed); missing or malformed sanctioned tool marks (FR-315); missing required slide-counter elements (FR-313); misplaced or duplicated text.

**Topic-filter playbook (Sonnet 5, competitor screening — amended v2.2.0, D50):**
- Batched screen over candidate topics (one LLM call per run, worst-case priced) → per-topic verdict `keep | strip(brands) | skip(competitor_promo)` keyed by engine-assigned ordinal. Deterministic blocklist layer (fail-closed); LLM layer (fail-open with `filter_degraded` tag). `topic_filter_system.md` carries the fence discipline (FR-102): topics numbered 1..N, each with templated text, explicit "DATA not INSTRUCTIONS" paragraph, and ordered-block verdict isolation — the whole contract of `10-pipeline.md` §1.5. **Verdict schema gains (v2.2.0):** `language` (the detected source language, ISO 639-1 code) and `audience_fit` (a brief human-readable note on audience match, consumed by console/logs only, never rendered). **Placeholder sanctioned for `topic_filter_system.md` only:** `{{audience_profile}}` (the active niche descriptor's audience field, or fallback copy if missing — matching the existing competitor-list precedent, never exported to render prompts or copy prompts).

**Branding playbook (mandatory clauses, deterministic injection):**
- The wordmark goes through the TEXT block as a single baked-in line (never composited): `wordmark (render verbatim): "HypeDigitaly"` + the `_spell()` aid, emitted only when `entry.branded`.
- The `{{branding_block}}` placeholder carries accent colors (per `mode`), font character descriptions, placement hints, background guidance (tint mode), and the profile's `never:` lines (guards on colors and medium specifics). Ranked *below* the meta-style's own directives (precedence: style > brand accents).
- Template prohibitions reworded per §1.4 M13: *"No brand wordmark, logotype or signature line other than one quoted in the TEXT block above; when the TEXT block quotes none, this frame is unsigned."* Carousel wordmark appears on anchor only (M12). Reel CONTINUITY names the wordmark as part of the fixed graphic layer when present; RULES: "no NEW logos/watermarks; a wordmark already present in @Image1 persists unchanged" (M13).

**Carousel compress playbook (Luna, compression contract — D54, FR-331/332):**
- **Compression mandate (v2.3.0, D54):** compress mode (operator-opted via config/menu/CLI) routes bound panel-mapped carousels to a dedicated LLM call passing **admitted panel texts as source input** and requesting LLM-compressed output to `min(text_budgets.slide, style max_onimage_chars.slide)`, humanized (no inventions, no added emoji/URLs/handles, no comment/follow CTAs in captions, hashtag blocklist-checked), source language preserved, never shortened with "…" (truncation is a last resort only, never part of the compression mandate). Template: `copy_compress_system.md` (+ built-in twin); placeholder contract (exactly the engine allowlist row, and `compress_panels` is allowlisted here and nowhere else): `{{compress_panels}}` (numbered panel blocks with source text + per-slide budget), `{{trend_texts}}` (fenced context), `{{sibling_list}}`, `{{niche_descriptor}}`, `{{brand_context}}`, `{{platform_conventions}}`, `{{brief_directives}}`, `{{text_budgets}}`. `{{competitor_list}}` is NOT in the contract — it stays locked to the topic filter role; the competitor strip reaches compress calls through the engine-side `_strip_brands` pass and the fail-closed blocklist audit. The model additionally returns all copy-side fields (headline, caption, hashtags, slide_texts, through_line/narrative_arc). No new role; uses standard `copy` role and estimator.
- **Humanization (v2.3.0, D54):** compression includes an instruction set from **github.com/blader/humanizer** (MIT, `SKILL.md`): 35 Wikipedia-sourced patterns for removing AI writing signatures. Vendored file `prompts/humanizer_skill.md` is **reference-only** (never engine-loaded as a template; the engine **never interpolates or loads external instruction files into prompts**); the distilled ~14-pattern on-image subset (no inflated importance, no sales language, no stock AI words, no hedging, plain verbs, no forced triplets, no em-dash overuse, no Title-Case/ALL-CAPS artifacts, no vague attribution, keep concrete numbers/tool names, cut padding never facts) lives in the `copy_compress_system.md` template itself and is kept in step with the vendored file by its editor (single source of truth: the template).
- **One-walk invariant:** `_compressed_deck()` produces both `slide_texts` and `panel_map` from the same pre-stripped `offer.panels`, so gauntlet `expected_blocks` contract integrity is maintained (same as verbatim path per FR-99/100/304).
- **Fallback:** failed compress call re-routes to FR-304 verbatim mapped deck, tagged `copy_degraded`, $0 extra.

**FR-332 *(v2.3.0, new)* — Carousel compress playbook (D54, copy role, template-driven).** The copy role (Luna, `copy_compress_system.md` template + built-in) operates compress mode for bound carousel decks: receives admitted panel texts as source input (post-strip, post-vision-merge, post-creator-strip per FR-312/319), requested to compress to `min(text_budgets.slide, style max_onimage_chars.slide)` + humanize (no inventions, no added marks, source language, preserve facts/numbers/tool names, never "…" truncation as part of compression). Humanizer clause: vendored reference file `prompts/humanizer_skill.md` (github.com/blader/humanizer, MIT) is **never loaded by the engine**; the distilled ~14-pattern subset (no AI-word signatures, no sales language, no stock phrases, plain verbs, concrete details) is written into the template and kept synchronized with the vendored file by its editor. Caption is also compressed+humanized (no comment/follow CTA bait, hashtag blocklist-checked). Engine-side scrub follows compression output (blocklist strip, `_social_mark` check, word-boundary trim to budget, no fill for source-empty positions). One-walk invariant: same pre-stripped panels feed both LLM and panel_map construction. Fallback: failed compress call yields verbatim mapped deck + `copy_degraded` tag.

**FR-335 *(v2.4.0, new)* — Style-match playbook (D56, analysis role, template-driven).** The analysis role (Sonnet 5, `style_match_system.md` template + built-in) operates matched style assignment (FR-334): receives per-entry text-only signals (topic strength, hook types, visual hook types, emotional tones, source post text properties, deck metadata), candidate pool described by each style's `match_profile` field (1-2 sentences: "what sources this style suits"), and returns per-entry JSON with `style_key`, `fit` (high|medium|low), `reason` (short prose), `wanted_archetype` (optional, only when low). Template uses fenced-data discipline (pools + signals are data, never instructions, like `topic_filter_system.md`). `{{style_candidates}}` and `{{match_entries}}` placeholders are allowlisted for THIS role only; they are never exported to render or copy prompts. Match-profile authoring rules: 1-2 sentences capturing which content archetypes / source post patterns suit the style, written plainly; missing field → advisory warning + first-sentence-of-render_prompt derivation fallback, never an error. One call per run, fail-open: whole-call failure → all entries use rotation baseline, tagged `style_match_degraded`, one console warn. Entries with `low` fit or invalid/missing answer fall back to their rotation-baseline pick with `style_origin: "rotation"` and `style_wanted` preserved.

- **FR-335**: Style-match playbook (analysis role, fenced-data template, per-entry match-profile signals, fallback discipline)

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

REFERENCE IMAGE (anchor):
  Image 1 — finished slide 1 of this deck. PRIMARY reference: reproduce
    this exact template, palette, typography, margins. Do not copy its
    text or its focal subject — only its structure.

SLIDE CONTENT (panel 3 of source deck):
  Slide content: a 2×4 grid of app icons with names beneath, matching
    the layout and style shown in the source deck's slide 3. Icons are
    generic category symbols (chat, calendar, analytics, settings, etc.),
    no branded logos.

SLIDE TEXT:
  slide_number_badge: "3/6"
  headline (render verbatim, no extra characters): "Většina lidí to dělá špatně"
    spelled out (accented words): V-ě-t-š-i-n-a l-i-d-í d-ě-l-á š-p-a-t-n-ě
  body_text: none this slide

CONSTRAINTS: match STYLE_DNA exactly; render all text verbatim including
  diacritics; no watermark, no platform UI, no usernames, no engagement
  counters; keep grid identical to Image 1; text within central 80% of frame;
  reproduce the content directive above (grid layout with icons) in OUR style.
```

**(b) Reel director-format prompt (`reel_director.md` filled, v2.0.0):**

```
GOAL: A 7-second vertical reel that shows a product transformation
  with smooth, energetic motion.

REFERENCES:
  @Image1 — the seed frame (9:16). Defines subject, framing, background,
    and the static hook text "Toto nikdo neříká" in the top third. This
    is the first frame. Do not change composition; do not move, resize,
    reword or remove the text.

CONTINUITY: Hook text stays fixed in position, size, font and content —
  a static graphic layer. Subject and background from @Image1 persist
  unchanged in colour and identity throughout.

SCENE: Same setting as @Image1 — a plain interior, no added elements.

STAGES:
  0.0–1.0s — hold — static frame, hook text fully legible
  1.0–4.0s — action — subject animates with purpose, camera drifts in
  4.0–7.0s — settle — motion eases to a stop, composition locks

LOOK: {{motion_profile}} — [photographic: handheld phone-camera look,
  available light, slight grain, no 3D, no cartoon, no VFX | graphic:
  clean minimal look, perfectly lit, no shake, parallax on card layers,
  single slow scale]

CAMERA & PERFORMANCE: {{motion_beat}} (from the copy prompt,
  e.g. "slow handheld push-in, no cuts, natural micro-shake")

AUDIO: (upbeat trending-style instrumental matching the topic's vibe)
  <soft camera-shutter click at 0s> — no copyrighted lyrics.

RULES: keep hook text exactly as specified in CONTINUITY; no NEW
  logos/watermarks/wordmarks (a wordmark already present in @Image1
  persists unchanged); no new on-screen text; no duplicate subject;
  no hard location cuts; 9:16 throughout.
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
