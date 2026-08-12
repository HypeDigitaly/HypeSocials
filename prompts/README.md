# prompts/ — editable prompt templates and the meta-style registry (D24)

Plain text files. Edit them in Notepad; the next run picks up the change with
no build step and no restart of anything but the run. Spec: `prds/50-promptcraft.md`.

**This file is documentation, not a template. The engine never loads it.**

**Final post-pivot state (topic-first pivot, v2.0.0/W3.5).** The three pre-pivot
templates (the visual-analysis role and the two image roles the merged
`image_post.md` replaced) left the disk, the registries and the built-in table
with the Wave 3.5 excision — eight shipped roles remain, and this table is a
complete description of them.

## Layout (FR-181)

```
prompts/
  styles.yaml                    the meta-style registry — 8 styles, the VISUAL AUTHORITY
  copywriter_system.md           global — Luna copy-selection system prompt
  vision_check_question.md       global — the two objective defect questions
  topic_filter_system.md         global — the batched competitor screen
  gpt-image-2/
    image_post.md                one single post creative
    carousel_slide.md            one carousel slide (style-DNA scaffold)
    carousel_anchor_instruction.md   block added when slide 1 is the PRIMARY reference
    reel_seed_frame.md           the still hook frame a reel is animated from
  seedance-2-5/
    reel_director.md             nine-section reel director prompt
```

`styles.yaml` is **not** a template and does not play by template rules. It has
**no built-in default tier**: a missing, unreadable or invalid registry is a
pre-flight refusal (FR-295, exit code 2), not a degradation. Everything else in
this folder falls back to a compiled built-in when it breaks (FR-183). The
registry's own editing rules live in the comment block at the top of the file.

## Placeholders (FR-182)

`{{name}}` is plain string substitution — no conditionals, no loops, no
expressions. The engine fills them from the assigned meta-style, the copy
selection, the branding config and a secret-free context object; an unfilled
placeholder fails that creative **before** anything is submitted, so never
invent a new `{{name}}`.

Two rules govern every row below, and the second is the one people forget:

1. A name must exist in `models.PLACEHOLDERS` — that is the vocabulary.
2. A name must be allowlisted **for the role it appears in** —
   `prompts_engine._ALLOWLIST`. A legal name in the wrong file does not
   resolve, and an unresolved placeholder fails the creative (FR-260/261).
   That is deliberate: it is how a copy-side slot is kept out of a render
   prompt.

| Placeholder | Filled with | Used in |
|---|---|---|
| `{{render_prompt}}` | the assigned meta-style's ≤120-word executable style instruction; under an `override` brief, that brief's **visual** directives instead (M14) | image_post, carousel_slide, reel_seed_frame |
| `{{layout_zones}}` | the style's ordered frame regions — zone structure only, never a reference's literal wording. A zone tagged `role: brand_slot` is emitted **only** when the creative is branded; when it is not, the zone is dropped and one line says the lower margin is empty | image_post, reel_seed_frame |
| `{{style_dna}}` | the five style-DNA fields (palette, typography, text placement, image treatment, visual pacing), byte-identical on every slide of one deck | carousel_slide |
| `{{onimage_text}}` | the exact strings to render, resolved from the copy call's reference labels — plus, on a branded creative, the `wordmark (render verbatim): "…"` entry and its spelling aid | all render templates |
| `{{branding_block}}` | accent colours per `branding.mode`, font character, placement hint, background hint, and the profile's `never:` guards. **Never the wordmark** — that travels in the TEXT block. Empty when the creative is unbranded, and empty of extras when the assigned style is itself a brand style (`brand_slot: true`) | image_post, carousel_slide, reel_seed_frame |
| `{{text_budgets}}` | the on-image character budget **in force for this call** — the tighter of the style's `max_onimage_chars` and config `text_budgets` | copywriter_system + the three gpt-image-2 render templates |
| `{{reference_roles}}` | one line per **actually attached** reference: index · what it contributes · what it must not. Style images come first, brief images after — "follow the first one listed" therefore means the house style wins | image_post, carousel_slide, reel_seed_frame |
| `{{exclusions}}` | the style's literal exclusion strings, read off its own reference files. Scoped to those references; never a restriction on the TEXT block | image_post, carousel_slide, reel_seed_frame, reel_director |
| `{{content_sentence}}` | deterministic subject sentence, no LLM call (FR-96): reference-free jobs and override briefs | image_post |
| `{{through_line}}` | the copy call's one-line "what this clip is about" | reel_director |
| `{{motion_beat}}` | the copy call's ONE named physical action, dropped into the reel's Stage 2 | reel_director |
| `{{motion_profile}}` | the style's `photographic` \| `graphic` switch — selects the reel's LOOK/CAMERA paragraph | reel_director |
| `{{brief_directives}}` | campaign brief's directives; empty when none | render templates, copywriter_system |
| `{{slide_index}}` | this slide's position in the deck | carousel_slide |
| `{{seed_frame_ref}}` | one-line description of what the seed frame shows | reel_director |
| `{{audio_cue}}` | the whole AUDIO body — either the bracketed cue set or the silent-clip line | reel_director |
| `{{trend_texts}}` | the topic's hooks, panel texts, tactics and descriptions, fenced as data | copywriter_system |
| `{{source_hooks}}` | **the numbered candidate list** — every source string the engine is willing to render or caption, each with its `P<n>.<kind>[.<i>]` label. Re-purposed by the pivot: this used to be a few-shot exemplar block | copywriter_system |
| `{{sibling_list}}` | every creative sharing this copy call | copywriter_system |
| `{{platform_conventions}}` | tone/length/hashtag guidance per platform | copywriter_system |
| `{{brand_context}}` | Notion brand context; empty when influence is off | copywriter_system |
| `{{niche_descriptor}}` | audience / vibe / visual world; empty when unset | copywriter_system |
| `{{niche_visual_world}}` | the niche's `visual_world` line **alone** — standing art direction, no audience and no copy context; empty when unset | image_post, carousel_slide, reel_seed_frame |
| `{{topic_items}}` | the engine-numbered topic blocks for the competitor screen — ordinals 1..N in arrival order, never the topic's own key | topic_filter_system **only** |
| `{{competitor_list}}` | `branding.competitors`, the deterministic blocklist, for the same call | topic_filter_system **only** |

### Per-role allowlists, in full

This is the same information the table above carries, in the shape the engine
actually enforces. A role's set is exact: not a minimum, not a suggestion.

| role | allowed placeholders |
|---|---|
| `copywriter_system.md` | `niche_descriptor`, `brand_context`, `trend_texts`, `source_hooks`, `sibling_list`, `text_budgets`, `platform_conventions`, `brief_directives` |
| `vision_check_question.md` | *(none)* |
| `topic_filter_system.md` | `topic_items`, `competitor_list` |
| `image_post.md` | `render_prompt`, `layout_zones`, `onimage_text`, `reference_roles`, `exclusions`, `text_budgets`, `brief_directives`, `niche_visual_world`, `content_sentence`, `branding_block` |
| `carousel_slide.md` | `slide_index`, `style_dna`, `render_prompt`, `onimage_text`, `reference_roles`, `exclusions`, `text_budgets`, `brief_directives`, `niche_visual_world`, `branding_block` |
| `carousel_anchor_instruction.md` | *(none)* |
| `reel_seed_frame.md` | `render_prompt`, `layout_zones`, `onimage_text`, `reference_roles`, `exclusions`, `text_budgets`, `brief_directives`, `niche_visual_world`, `branding_block` |
| `reel_director.md` | `through_line`, `seed_frame_ref`, `onimage_text`, `audio_cue`, `exclusions`, `brief_directives`, `motion_beat`, `motion_profile` |

`reel_director.md` deliberately has **no** `branding_block`: the branding block
is a gpt-image-2 instruction set (accent colours, letterforms, placement), and
the only branding a video model needs to know about is the wordmark already
burnt into its seed frame — which reaches it inside `{{onimage_text}}`, under
the CONTINUITY rule that it persists unchanged.

**Why the niche reaches a render through a narrow slot.** `{{niche_descriptor}}`
also carries `audience`, which is copy context, and no render role may resolve
it — that boundary is the whole point of the allowlist. `{{niche_visual_world}}`
carries the `visual_world` line only: palette, type character, motif vocabulary,
treatment. It sits **under** the assigned style and the attached references in
authority — they decide layout and composition, the niche biases what they
leave open — and it never licenses inventing text.

**Why the filter's two slots are locked to one file.** `{{topic_items}}` and
`{{competitor_list}}` are allowlisted for `topic_filter_system.md` and nowhere
else. A competitor list inside a render prompt is a list of brand names handed
to an image model, which is the exact shape of the failure it exists to
prevent; and topic blocks are third-party text that belongs behind a fence, in
the one call whose entire job is to read them as data.

**Truncation.** When an assembled prompt exceeds the model's length limit the
engine trims placeholder *values* (never the template's own prose) in the fixed
order of `_TRUNCATION_ORDER` in `prompts_engine.py`; everything absent from that
tuple — on-image text, exclusions, budgets, reference roles — is untouchable.
The order is: `niche_descriptor`, `niche_visual_world`, **`branding_block`**,
`content_sentence`, `source_hooks`. So standing art direction yields first, the
brand's accent instructions yield next, and the locked text block — including
the wordmark entry, which lives in `{{onimage_text}}` — is never touched at
all. A creative that loses its accent colours is still on-brand enough to ship;
one that loses its signature string is not.

## Editing rules

- **Do not delete the exclusion clause, the safe-zone line or the re-flow
  line** from a render template. They are mandatory (FR-94) and they are what
  keeps fake follower counts and amputated headlines out of the output.
- **Do not write an aspect ratio, a resolution or a pixel size into a
  template.** The frame is an API parameter; models render the string instead
  of obeying it.
- **Keep the text block a locked asset.** "Render exactly, add nothing,
  repeat nothing" is why headlines come back readable.
- **Do not delete the TEXT PRECEDENCE clause** from a render template, and
  never quote a reference's own wording anywhere else in one. GPT Image 2
  reads any quoted string as content to letter, wherever it sits — a live run
  cloned the reference's wordmark because the layout description spelled it
  out (`spikes/RESULTS.md` §B). The rule: the TEXT block is the only source of
  renderable words; every other section describes structure; a text zone with
  no quoted replacement renders empty.
- **Do not delete the exclusions-scope line** ("The exclusions below concern
  the attached reference images. They never restrict the TEXT block above…").
  A style's exclusions quote the literal strings printed on its own reference
  images, and a brand's own house style quotes its own wordmark among them.
  Without that line, an exclusion list and a TEXT-block wordmark contradict
  each other and the model picks a winner at random.
- **Do not re-generalise the wordmark prohibition.** It reads "no brand
  wordmark, logotype or signature line **other than one quoted in the TEXT
  block above**" for a reason: branded creatives sign themselves through the
  TEXT block, and the old absolute prohibition told the model to drop the one
  string we asked it to draw.
- Change wording freely; change section *labels* only if you mean it — the
  labelled scaffold is what makes a bad render debuggable from the log.
- A broken or deleted template is not fatal: the engine falls back to its
  built-in default for that role and logs a warning naming the file (FR-183).
  A newly registered render profile has no built-in, so its whole set must be
  present. **`styles.yaml` is the exception — it has no built-in and a broken
  registry stops the run at pre-flight.**
- **Never hardcode a character budget or a reference list.** Both change per
  call; the placeholders exist so a template can never go stale (see below).

## Computed per call, not fixed — and where each one lives

Some prompt text is assembled by the engine at call time instead of sitting in
a template. Every such line is enumerated below with the constant that owns it.
They are **FR-180 clause-(c) mandatory lines**: they belong to the requirement,
not to a template, so **they are editable only in code** — there is no file
here to change, and none of them is a hidden fourth prompt layer.

- **`{{text_budgets}}`** is filled from the tighter of the assigned style's
  `max_onimage_chars` and config `text_budgets` (`image_headline`,
  `image_subline`, `reel_seed_headline`) — change the style or the config, not
  a template. The engine also re-computes it for a vision-check retry, where
  the budget in force is cut by `retry_reduction_pct`.
- **`{{reference_roles}}`** lists only the references actually attached to
  *this* job — the assigned style's own image window, sometimes a brief's own
  picture, sometimes none. Writing "Image 1, Image 2, Image 3" by hand
  describes a job that may not exist. When the carousel anchor is on, the
  anchor block is prepended ahead of this list and its Image 1 role wins over
  everything in it.
- **`{{audio_cue}}`** is the entire AUDIO body of the reel prompt, in one of
  two shapes: the normal cue set — `(music/ambience matched to the topic)`
  plus at most one `<sound effect>`, per the bracket taxonomy — or, when
  `reel_audio` is off (or audio was dropped after the run degraded), the
  silent-clip line: *"Silent clip — no music, no melody, no vocals, no
  soundtrack of any kind."* Brackets `{ }` (dialogue) and `【 】` (generated
  subtitles) are never used.
- **The reel's real-second beats** ("0.0-1.0s hold; 1.0-4.0s the action;
  4.0-5.0s settle") are computed from the duration actually requested for that
  clip and arrive inside one of `reel_director.md`'s existing slot values.
  There is no separate placeholder for them and none may be added: the
  template's STAGES section names the three stages and defers to whatever
  seconds the prompt states.

`{{through_line}}` carries the copy call's reel through-line;
`{{content_sentence}}` stays reserved for FR-96's deterministic reference-free
sentence and is the fallback fill for the reel through-line when no copy
exists. `image_post.md` holds **both** subject lines, one under the other:
`{{content_sentence}}` keeps its FR-96 job, and `{{render_prompt}}` covers the
case FR-96 cannot — an override brief has no topic, so the deterministic
sentence is empty and the brief's visual directives are the only subject there
is. Whichever comes back blank is dropped by the template's closing *"ignore
any labelled line above that is empty"* line.

### The full list of engine-built lines (FR-180 clause (c))

| Line | Where it goes | Source constant |
|---|---|---|
| Reel audio cue — `(music or ambience matched to the topic's vibe …)` + at most one `<sound effect>` | `{{audio_cue}}` in `reel_director.md` | `generate/reel.py` `_AUDIO_CUE` |
| Silent-clip line, when `reel_audio` is off or audio was dropped after a content-audit failure | `{{audio_cue}}` | `generate/reel.py` `SILENT_CLIP_CLAUSE` |
| `@Image1` description — "the 9:16 still hook frame … hook text already burnt in" | `{{seed_frame_ref}}` | `generate/reel.py` `_SEED_REF_LINE` |
| The two seed-frame-less variants: render the hook text in-model, or a clip with no lettering at all (`reel_overlay_text: in_model` / `none`) | `{{seed_frame_ref}}` | `generate/reel.py` `_IN_MODEL_REF_LINE`, `_CLEAN_CLIP_REF_LINE` |
| Reference role lines — one per attached reference, per provenance (**style**, **brief subject**) | `{{reference_roles}}` | `generate/__init__.py`, `generate/carousel.py`, `generate/reel.py` |
| Vision-check retry instruction — "re-render of an image whose text came back broken … one text block only, maximum legible size" (FR-105's third lever) | appended to the assembled render prompt on a retry | `vision_check.py` `RETRY_INSTRUCTION` |
| On-image text block — `headline (render verbatim): "…"` plus its `spelled out: H-e-a-d` line (FR-186 diacritics defence) | `{{onimage_text}}` | `prompts_engine.py` `_onimage_text` / `_spell` |
| Wordmark entry — `wordmark (render verbatim): "HypeLead"` + spelling aid, emitted only when the creative is branded (FR-292 channel 1) | `{{onimage_text}}` | `prompts_engine.py` `_onimage_text` |
| Branding block — accent instructions per `mode`, font character, placement hint, background hint, and the profile's `never_always` / `never_style` guards (FR-292 channel 2) | `{{branding_block}}` | `prompts_engine.py` `branding_block` (public — `generate/refs.py` gates it on `entry.branded`) |
| Empty-signature line — *"This frame carries no signature zone: the lower margin is empty."*, appended when a `role: brand_slot` zone is dropped on an unbranded creative | `{{layout_zones}}` | `prompts_engine.py` |
| Numbered candidate list — every offerable source string with its `P<n>.<kind>[.<i>]` label, pre-filtered per slot | `{{source_hooks}}` | `copywrite.py` (owns numbering AND resolution — one implementation; it overwrites the slot after `build_context` returns; contracts W2 addendum item 4) |
| Numbered topic blocks for the competitor screen, ordinals 1..N | `{{topic_items}}` | `prompts_engine.py` `_topic_items` |
| Campaign-brief context — the `Campaign brief "<name>" — influence: …` header, its directives, and the precedence sentence (`override` vs blend, FR-144/145) | `{{brief_directives}}` | `prompts_engine.py` `_brief_directives` |

Changing any of these means changing the constant in code (and the
requirement behind it), not editing a file in this folder.
