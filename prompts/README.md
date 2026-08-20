# prompts/ — editable prompt templates and the meta-style registry (D24)

Plain text files. Edit them in Notepad; the next run picks up the change with
no build step and no restart of anything but the run. Spec: `prds/50-promptcraft.md`.

**This file is documentation, not a template. The engine never loads it.**

**Current state (D56/D57 style intelligence, v2.4.0).** Fourteen shipped roles:
nine global templates flat in `prompts/`, four `gpt-image-2` render templates,
one `seedance-2-5` director template — plus `styles.yaml`, which is not a
template, and `humanizer_skill.md`, which is not a template either (see below).
`style_match_system.md` is the ninth global and the newest (FR-334/335): the
registry grew to 19 styles at D56/D57, and one batched, fail-open analysis call
per run now decides which of them fits each creative, instead of rotation
deciding alone. (`prds/50-promptcraft.md` FR-181 counts *fifteen* roles rather
than fourteen because it counts the registry itself among its ten globals; this
file keeps `styles.yaml` outside the template count, because it plays by none of
the template rules.)
Two things changed under every file in this folder at v2.1.0 and are the reason
several sentences read the way they do:

- **No style reference images.** A render job carries a campaign brief's own
  product photo, the finished carousel anchor slide, a reel's seed frame — or
  nothing at all, which is the normal case. The house style reaches the model
  as *words*: `styles.yaml`'s `render_prompt` and its five DNA fields. Never
  re-introduce a "follow the attached house style picture" sentence.
- **Panel-mapped decks.** A carousel mirrors one source slideshow: our slide *i*
  renders that deck's panel *i* verbatim (FR-304), under a per-slide English
  `visual_brief` describing the FOREGROUND CONTENT that source slide *showed*
  (FR-308/316) — never its background, its colours or its chrome.

## Layout (FR-181)

```
prompts/
  styles.yaml                    the meta-style registry — 19 styles (9 originals + build-log-mono + 4 archetype + 5 -teal variants, D56/D57), the VISUAL AUTHORITY
  humanizer_skill.md             NOT a template — the vendored humanizer reference (see below)
  copywriter_system.md           global — Luna copy-selection system prompt (verbatim mode)
  copy_compress_system.md        global — Luna compression system prompt (compress mode, D54)
  topic_filter_system.md         global — the batched competitor / language / audience screen
  style_match_system.md          global — the matched style-assignment screen (v2.4.0, FR-334/335): one batched `analysis` call per run, fail-open
  slide_intel_question.md        global — per-slide transcription + foreground visual brief + deck mark boxes (FR-306/315/316)
  critic_brief.md                global — the gauntlet's CONTRACT critic: presence + leakage (D49/FR-322)
  critic_system.md               global — the gauntlet's STYLE critic: style contract + cross-frame consistency
  critic_craft.md                global — the gauntlet's EXECUTION critic: legibility, fit, logo fidelity
  gauntlet_fix.md                global — the CANNED remedy sheet (FR-323); resolves nothing, selected in code by (code, zone)
  gpt-image-2/
    image_post.md                one single post creative
    carousel_slide.md            one carousel slide (style-DNA scaffold + visual brief)
    carousel_anchor_instruction.md   block added when slide 1 is the PRIMARY reference
    reel_seed_frame.md           the still hook frame a reel is animated from
  seedance-2-5/
    reel_director.md             nine-section reel director prompt
```

`humanizer_skill.md` is **not** a template and the engine **never loads it**. It
is `SKILL.md` from [github.com/blader/humanizer](https://github.com/blader/humanizer)
(MIT, Copyright (c) 2025 Siqi Chen), vendored verbatim under an added provenance
header — 35 patterns distilled by WikiProject AI Cleanup from Wikipedia's "Signs
of AI writing". It has no `_ALLOWLIST` row, no `_BUILT_INS` twin and no
placeholder contract, because an allowlist row for a non-template is a name no
builder produces and no file resolves — the exact drift `prompts_engine.py`'s
table exists to prevent. Nothing interpolates it into a prompt. It is here for a
human: the ~14-pattern ON-IMAGE subset that the copy model is actually told about
lives inside `copy_compress_system.md` (and its built-in twin), and its editor
keeps the two in step — re-vendor this file first, re-derive the subset there in
the same commit.

`styles.yaml` is **not** a template and does not play by template rules. It has
**no built-in default tier**: a missing, unreadable or invalid registry is a
pre-flight refusal (FR-295, exit code 2), not a degradation. Everything else in
this folder falls back to a compiled built-in when it breaks (FR-183). The
registry's own editing rules live in the comment block at the top of the file —
including the one number that matters most, `max_onimage_chars`: the budget in
force is `min(config text_budgets, this style's cap)`, so a low cap here is what
actually decides whether a source panel can be quoted at all. Since v2.4.0 they
also cover the one entry field that never reaches a render model:
**`match_profile`** — one or two sentences naming what kind of source material
this style suits ("a numbered how-to deck", "a dense benchmark chart", "a single
large statement"), which is what FR-334's matcher judges every candidate on. It
is advisory, not required: a style that omits it raises a warning, never an
error, and the matcher falls back to a stand-in derived from the first sentence
of that style's `render_prompt` — a sentence that says how the style LOOKS, not
what it SUITS, so an authored line beats the fallback every time.
Since v2.5.1 (D60) pre-flight also reads the `palette` lines as DATA, not prose:
every `#RRGGBB` is parsed to HSV and the FR-347 palette contract is an ERROR —
one accent hue family, a coverage clause of at most 1/8 on every accent line,
background roles (`GROUND`/`SURFACE`/`DEPTH`/`SHADOW`) exempt, zero accents legal
— while the FR-349 variant scan (an unresolved "A or B" in any DNA field, negated
ban-lists excepted) and the FR-348 type-family count (more than two families,
a third `mono` tolerated) stay warnings. The house spine (FR-350: counter
top-right, ground at a value extreme, text inside the central 80% of the 1:1
frame) is enforced by test guards over the shipped file, not at load.

**FR-183's second copy.** Every shipped template also exists as a compiled
built-in in `prompts_engine._BUILT_INS`, used when the file is missing,
unreadable or names a placeholder its role may not resolve. `tests/
test_template_parity.py` mechanically pins the *placeholder sets* of the two
copies; the prose is on the editor. Change a file, copy it into the built-in in
the same commit.

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
| `{{render_prompt}}` | the assigned meta-style's ≤120-word executable style instruction — for a carousel slide, with that style's `per_format_guidance.carousel_cover` (slide 1) or `carousel_slide` (slides 2–N) appended; under an `override` brief, that brief's **visual** directives instead (M14) | image_post, carousel_slide, reel_seed_frame |
| `{{layout_zones}}` | the style's ordered frame regions — zone structure only, never literal wording. A zone tagged `role: brand_slot` is emitted **only** when the creative is branded; when it is not, the zone is dropped and one line says the lower margin is empty | image_post, reel_seed_frame |
| `{{style_dna}}` | the five style-DNA fields (palette, typography, text placement, image treatment, visual pacing), byte-identical on every slide of one deck. Post-D46 this block plus `render_prompt` is the **sole** carrier of the look — there is no style picture to fall back on | carousel_slide |
| `{{visual_brief}}` | that slide's English **foreground-content** directive from slide intelligence (FR-306/308/316): the chart, table, code block, icon grid, list, diagram, arrows and quantities the source slide showed — **never** its background or scenery, never a colour, typeface or gradient, never platform chrome or pagination widgets, never a creator name. Ranked below `style_dna` on every question of look; competitor marks in it are genericized and the whole value takes the competitor strip; cuttable under truncation; empty when intelligence degraded | carousel_slide **only** |
| `{{slide_panel_source}}` | FR-304's position line — `source panel 3 of 7` — so the model knows this slide mirrors one specific source slide. Empty for an unbound or override-brief deck | carousel_slide **only** |
| `{{list_treatment}}` | FR-304b's list layout for **this frame**: the assigned style's `list_mode.layout` prose plus its `overflow` sentence, led by *"This frame's text is a LIST and is set as one:"*. Fired per slide, off that slide's own mapped panel (`styles.is_list_panel`); **empty** on a panel that trips no trigger, on a style with no `list_mode`, and under an override brief. Never a ceiling — it changes how the rows are LAID OUT, never what the panel says — and never cuttable under truncation | carousel_slide **only** |
| `{{counter_rule}}` | FR-338's counter line for **this deck**: where the assigned style's `counter_slot` zone puts the position badge (the zone's own words, from the same formatter the critic's `{{layout_zones}}` uses), the house corner — *small, body family, top-right inside the safe area; no chip, no badge* — when the style declares no such zone, or the flat statement that this deck carries **no** counter at all. **Empty** on a style-less context, under an override brief, and on an uncounted deck whose style never asked for a badge. It exists because this role names no `{{layout_zones}}` slot: the zone that PLACES the badge reached the critic and never the deck renderer. Never cuttable under truncation | carousel_slide **only** |
| `{{onimage_text}}` | the exact strings to render, resolved from the copy call's reference labels — plus, on a branded creative, the `wordmark (render verbatim): "…"` entry (with a spelling aid only where a word carries a non-ASCII character). On a mapped deck this is the source panel's own text, emoji, line breaks and `#` tokens included (§0.14b) | all render templates |
| `{{branding_block}}` | accent colours per `branding.mode`, font character, placement hint, background hint, and the profile's `never:` guards. **Never the wordmark** — that travels in the TEXT block. Empty when the creative is unbranded, and empty of extras when the assigned style is itself a brand style (`brand_slot: true`) | image_post, carousel_slide, reel_seed_frame |
| `{{text_budgets}}` | the on-image character budget **in force for this call** — the tighter of the style's `max_onimage_chars` and config `text_budgets`. On a CAROUSEL the wording forks on `build_context(carousel_copy_mode=…)` (D54): verbatim states the headline ceiling and says a `panel_text` string carries none (B6), compress states the headline ceiling **and** the real per-slide `min(config.slide, style.slide)` figure, because a compressed line is ours and is measured against it | copywriter_system, copy_compress_system + the three gpt-image-2 render templates |
| `{{reference_roles}}` | one line per **actually attached** reference: index · what it contributes · what it must not. Post-D46 the provenances are a brief's product photo, the carousel anchor slide, a reel's seed frame and (v2.1.3, FR-315) a **mark patch** — a tool logo cropped from the source slide, the one attachment whose own lettering may be copied — and most image jobs attach nothing at all | image_post, carousel_slide, reel_seed_frame |
| `{{exclusions}}` | the style's own forbid-list from `styles.yaml`: self-contained rules (platform chrome, watermarks, real logos, faces, legible text outside the declared zones), readable without any picture. Never a restriction on the TEXT block | image_post, carousel_slide, reel_seed_frame, reel_director |
| `{{content_sentence}}` | deterministic subject sentence, no LLM call (FR-96): reference-free jobs and override briefs | image_post |
| `{{through_line}}` | the copy call's one-line "what this clip is about" | reel_director |
| `{{motion_beat}}` | the copy call's ONE named physical action, dropped into the reel's Stage 2 | reel_director |
| `{{motion_profile}}` | the style's `photographic` \| `graphic` switch — selects the reel's LOOK/CAMERA paragraph | reel_director |
| `{{brief_directives}}` | campaign brief's directives; empty when none | render templates, copywriter_system, copy_compress_system |
| `{{slide_index}}` | this slide's position in the deck — METADATA for orientation, never rendered as words (FR-313) | carousel_slide |
| `{{tool_marks}}` | the sanctioned real-logo list for this slide (FR-310/315): third-party tool marks named by the slide's text or seen on the source slide, competitor/creator/platform marks already filtered out. Each is a **required** element and renders as the real mark in true brand colours, palette-exempt — pixel-faithfully when a cropped MARK PATCH rides in `reference_roles` — inside the TEXT block beside its panel title, in the same position on every slide of the deck; empty = no sanctioned marks | carousel_slide **only** |
| `{{slide_counter}}` | the deck's source-mirrored counter string for this slide (FR-313), e.g. `03 / 08`; normally reaches the model as the locked `counter` TEXT entry + `counter_slot` zone rather than through this raw slot — allowlisted so an override template may name it; empty = unnumbered deck | carousel_slide **only** |
| `{{seed_frame_ref}}` | one-line description of what the seed frame shows | reel_director |
| `{{audio_cue}}` | the whole AUDIO body — either the bracketed cue set or the silent-clip line | reel_director |
| `{{trend_texts}}` | the topic's hooks, panel texts, tactics and Virlo's own summary, fenced as data. The summary (`description`) is **context only** — FR-303 bans it from every output, and FR-331 keeps it out of a compressed line too: compression is authored from the panel above it, never from Virlo's description | copywriter_system, copy_compress_system |
| `{{source_hooks}}` | **the numbered candidate list** — one section per creative, that creative's bound post only, source-deck panels first, each string with its `P<n>.<kind>[.<i>]` label. Kinds are `panel`, `overlay`, `hook`, `caption`; `description` is not a kind (FR-302/303) | copywriter_system |
| `{{compress_panels}}` | **the compression work order** (D54/FR-331/332) — one section per creative naming its language, its caption source and its admitted panels, each led by its SOURCE POSITION and that position's own `min(config.slide, style.slide)` ceiling. A position the block does not print carries no source text and ships wordless: compression never fills a vacuum. Written by `copywrite._compress_block` onto the built context, on the `source_hooks` precedent (one implementation of the numbering, and the same walk builds the `panel_map`). Allowlisted for `copy_compress_system.md` **only** | copy_compress_system **only** |
| `{{sibling_list}}` | every creative sharing this copy call, with its bound post and whether its slides are engine-mapped; on a compress call, each deck's slide count — the length its `slide_texts` answer must have | copywriter_system, copy_compress_system |
| `{{platform_conventions}}` | tone/length/hashtag guidance per platform | copywriter_system, copy_compress_system |
| `{{brand_context}}` | Notion brand context; empty when influence is off | copywriter_system, copy_compress_system |
| `{{niche_descriptor}}` | audience / vibe / visual world; empty when unset | copywriter_system, copy_compress_system |
| `{{niche_visual_world}}` | the niche's `visual_world` line **alone** — standing art direction, no audience and no copy context; empty when unset | image_post, carousel_slide, reel_seed_frame |
| `{{topic_items}}` | the engine-numbered topic blocks for the competitor screen — ordinals 1..N in arrival order, never the topic's own key | topic_filter_system **only** |
| `{{competitor_list}}` | `branding.competitors`, the deterministic blocklist, for the same call | topic_filter_system **only** |
| `{{style_candidates}}` | **the run's candidate styles, as fenced data** (v2.4.0, FR-334/335) — one entry per style usable anywhere in this run, each described by its `key` (the engine's identifier, and the exact string an answer copies), its `match_profile` (that style's own one-or-two-sentence claim about what source material it suits — the field the match is actually made against) and the formats it is meant for. The vocabulary, not the ballot: the keys answerable for any one creative are the shorter per-entry list inside `{{match_entries}}`. Fenced on the `{{topic_items}}` precedent, because style text is prose written *at* a render model in imperatives — "use a cream ground", "never show platform chrome" — and the screen must read it as a description of a look, never as orders | style_match_system **only** |
| `{{match_entries}}` | **the match work order** (v2.4.0, FR-334/335) — one section per planned creative, opened by its engine-assigned `asset_id`: the only identity a creative has in this call, and the only key its answer row is joined on. A section carries that creative's format; its source signals — topic `strength`, Virlo's own `hook_types` / `visual_hook_types` / `emotional_tones`, the bound post's caption / hook / overlay / panel-text **lengths**, `panel_count`, `views`, and the `deck_length` and `usable_panel_slots` we are building against; and that entry's OWN candidate pool, the only keys it may be answered with. Fenced for the second `{{topic_items}}` reason as well: every line in it is either a number the engine measured or text scraped from a third-party post | style_match_system **only** |

### Per-role allowlists, in full

This is the same information the table above carries, in the shape the engine
actually enforces. A role's set is exact: not a minimum, not a suggestion.

| role | allowed placeholders |
|---|---|
| `copywriter_system.md` | `niche_descriptor`, `brand_context`, `trend_texts`, `source_hooks`, `sibling_list`, `text_budgets`, `platform_conventions`, `brief_directives` |
| `copy_compress_system.md` | `niche_descriptor`, `brand_context`, `trend_texts`, `compress_panels`, `sibling_list`, `text_budgets`, `platform_conventions`, `brief_directives` |
| `topic_filter_system.md` | `topic_items`, `competitor_list`, `audience_profile` |
| `style_match_system.md` | `style_candidates`, `match_entries` |
| `critic_brief.md` | `expected_blocks`, `forbidden_terms`, `list_mode`, `required_marks`, `sanctioned_illegible`, `style_dna` |
| `critic_system.md` | `expected_blocks`, `layout_zones`, `list_mode`, `required_marks`, `style_dna` |
| `critic_craft.md` | `expected_blocks`, `platform`, `required_marks`, `sanctioned_illegible` |
| `gauntlet_fix.md` | *(none)* |
| `slide_intel_question.md` | *(none)* |
| `image_post.md` | `render_prompt`, `layout_zones`, `onimage_text`, `reference_roles`, `exclusions`, `text_budgets`, `brief_directives`, `niche_visual_world`, `content_sentence`, `branding_block` |
| `carousel_slide.md` | `slide_index`, `style_dna`, `render_prompt`, `onimage_text`, `reference_roles`, `exclusions`, `text_budgets`, `brief_directives`, `niche_visual_world`, `branding_block`, `visual_brief`, `slide_panel_source`, `tool_marks`, `slide_counter`, `list_treatment`, `counter_rule` |
| `carousel_anchor_instruction.md` | *(none)* |
| `reel_seed_frame.md` | `render_prompt`, `layout_zones`, `onimage_text`, `reference_roles`, `exclusions`, `text_budgets`, `brief_directives`, `niche_visual_world`, `branding_block` |
| `reel_director.md` | `through_line`, `seed_frame_ref`, `onimage_text`, `audio_cue`, `exclusions`, `brief_directives`, `motion_beat`, `motion_profile` |

`slide_intel_question.md` deliberately has **no** placeholders: the attached
slide images are the variable input, and the question must read identically for
every post so transcriptions are comparable across a run.

`reel_director.md` deliberately has **no** `branding_block`: the branding block
is a gpt-image-2 instruction set (accent colours, letterforms, placement), and
the only branding a video model needs to know about is the wordmark already
burnt into its seed frame — which reaches it inside `{{onimage_text}}`, under
the CONTINUITY rule that it persists unchanged.

`visual_brief`, `slide_panel_source`, `list_treatment` and `counter_rule` are
allowlisted for `carousel_slide.md` and nowhere else. A single image, a reel frame and the
anchor block have no source panel to mirror, so a template that drifted into
naming one of them there fails loudly (FR-260) instead of rendering a blank
line. `list_treatment` joined them at Session 5.5 (F1-A): it used to ride as a
gated append onto `{{layout_zones}}` — a slot the slide role does not name — so
the one role that maps source panels was the only one never told to set a list
as one, while the `system` critic judged slides against exactly that rule.
`counter_rule` joined them at D59 (FR-338) with the same story and the same
slot: the deck's position badge is placed by a `counter_slot` LAYOUT ZONE, the
slide role names no `{{layout_zones}}`, and so the renderer was left inferring a
badge from whatever chip STYLE_DNA described — on uncounted decks too.

**Why the niche reaches a render through a narrow slot.** `{{niche_descriptor}}`
also carries `audience`, which is copy context, and no render role may resolve
it — that boundary is the whole point of the allowlist. `{{niche_visual_world}}`
carries the `visual_world` line only: palette, type character, motif vocabulary,
treatment. It sits **under** the assigned style in authority — the style decides
layout and composition, the niche biases what it leaves open — and it never
licenses inventing text.

**Why the filter's two slots are locked to one file.** `{{topic_items}}` and
`{{competitor_list}}` are allowlisted for `topic_filter_system.md` and nowhere
else. A competitor list inside a render prompt is a list of brand names handed
to an image model, which is the exact shape of the failure it exists to
prevent; and topic blocks are third-party text that belongs behind a fence, in
the one call whose entire job is to read them as data.

**Why the matcher's two slots are locked to one file.** `{{style_candidates}}`
and `{{match_entries}}` are allowlisted for `style_match_system.md` and nowhere
else, for both of the reasons above at once. `{{match_entries}}` is scraped
third-party post text and engine measurements, and it belongs behind a fence in
the one call that reads them as data. `{{style_candidates}}` is a menu of every
*other* enabled style's authored prose: a render role that could resolve it
would be told to draw one look while reading a dozen descriptions of others —
the two-art-directors failure the visual-brief rule exists to prevent, with the
second director speaking in the same imperative voice as the first. Nothing on
either slot becomes pixels: the match call decides which style a creative is
assigned, and its `reason` and `wanted_archetype` are read by a person in the
run log and the gallery, never by a render model (FR-334/335).

**Why the two copy roles never share a slot.** `copywriter_system.md` and
`copy_compress_system.md` are the same role (Luna, the `copy` LLM role, the same
estimator) under two contracts, and the one slot that differs is the one that
decides which. `{{source_hooks}}` says *pick a label and the engine ships those
bytes*; `{{compress_panels}}` says *shorten this panel to this ceiling and the
engine ships your words*. Each is allowlisted for its own file alone, so a
template that drifts into naming the other fails loudly (FR-260) instead of
handing a quote-only mandate a block of prose to rewrite — which is D50's rule
running backwards. `{{compress_panels}}` is locked down for the `{{topic_items}}`
reason as well: it is the only slot in the vocabulary that carries third-party
source text to a call that is *asked* to author new bytes from it, and a render
role that could resolve it would be handed a wall of panel prose to letter.

**Truncation.** When an assembled prompt exceeds the model's length limit the
engine trims placeholder *values* (never the template's own prose) in the fixed
order of `_TRUNCATION_ORDER` in `prompts_engine.py`; everything absent from that
tuple — on-image text, exclusions, budgets, reference roles — is untouchable.
The order is: `trend_texts`, `brand_context`, `platform_conventions`,
`seed_frame_ref`, `niche_descriptor`, `niche_visual_world`, **`branding_block`**,
`content_sentence`, `source_hooks`, **`visual_brief`**, `layout_zones`,
`render_prompt`, `style_dna`. So the topic material yields first, standing art
direction next, the brand's accent instructions after that, then the slide's
content guidance — and the style trio survives longest, because post-D46 those
words are the only carrier of the look. `{{visual_brief}}` joined the cuttable
set at v2.1.3 (FR-316): it is guidance, not pixels, and a block that could never
shrink is a block that can push a prompt over the limit with nothing to give.
The locked text block, including the wordmark entry that lives inside
`{{onimage_text}}`, is never touched at all. `{{compress_panels}}` is absent from
that tuple and stays absent: it IS the content the call exists to compress, so a
pass that trimmed it would silently drop slides from the answer.

## Editing rules

- **Do not delete the exclusion clause, the safe-zone line or the re-flow
  line** from a render template. They are mandatory (FR-94) and they are what
  keeps fake follower counts and amputated headlines out of the output.
- **Do not write an aspect ratio, a resolution or a pixel size into a
  template.** The frame is an API parameter; models render the string instead
  of obeying it.
- **Keep the text block a locked asset.** "Render exactly, add nothing,
  repeat nothing" is why headlines come back readable.
- **Do not tell a slide to clean up its quoted panel text.** A source panel
  legitimately carries emoji, line breaks and `#` tokens — that is the deck's
  own voice, and our slide is their slide (§0.14b). `@handles` and
  **social-platform** URLs are the only things excluded, and the copy stage has
  already removed them; a **technical** URL — a code host, a docs site, a
  package registry, a repository or file path, a shell command — is ordinary
  content and renders byte-exact (FR-319), so no render template may carry a
  blanket "no URL" line. A template that says "no emoji" on the slide role
  silently empties half a deck.
- **Do not re-introduce style reference images.** No sentence in any template
  may assume an attached house-style picture ("follow the first reference
  listed as the style", "reproduce the reference's palette"). The style is
  written, in `styles.yaml`; the only attachments are a brief's product photo,
  the anchor slide and the seed frame, and each already carries its own role
  line.
- **Keep the visual brief subordinate, and foreground-only.** `{{visual_brief}}`
  says WHAT a slide shows; `{{style_dna}}` says how everything looks. A template
  that lets the brief name a colour, a typeface or a mood hands the deck two art
  directors. Under FR-316 the brief is authored as FOREGROUND CONTENT ONLY —
  charts, tables, code blocks, icons, lists, diagrams, quantities — and never
  describes a background, a room, a photograph, a colour, a gradient, platform
  chrome or a creator name. Both halves of that contract are load-bearing: the
  slide-intel question forbids writing those words, and the slide template tells
  the model to read past any that survive ("the deck's palette and typography
  ALWAYS win"). Do not delete either half; a live deck came back with a
  "red-to-orange gradient heading" and an "outdoor pool area" because a brief
  was obeyed as art direction.
- **Do not loosen the tool-mark rules.** A mark on the `{{tool_marks}}` line is
  a REQUIRED element (FR-315): it renders as the real logo in true brand
  colours, pixel-faithfully when a MARK PATCH reference is attached, inside the
  TEXT block beside its panel title, in the same spot on every slide of the
  deck — never floating in the scene, never on an in-scene screen. The
  "generic unlettered shape" instruction still governs every mark that is NOT
  on that line. The anchor block locks the mark's position the same way it
  locks the text block's.
- **Do not delete the TEXT PRECEDENCE clause** from a render template, and
  never quote a reference's own wording anywhere else in one. GPT Image 2
  reads any quoted string as content to letter, wherever it sits — a live run
  cloned a wordmark because the layout description spelled it out
  (`spikes/RESULTS.md` §B). The rule: the TEXT block is the only source of
  renderable words; every other section describes structure; a text zone with
  no quoted replacement is left out of the frame — never a bar, rule, block or
  placeholder standing in for words (FR-340, D59).
- **Do not delete the exclusions-scope line** ("The exclusions below are this
  house style's own forbid-list. They never restrict the TEXT block above…").
  A brand's own house style forbids its own wordmark among its exclusions;
  without that line an exclusion list and a TEXT-block wordmark contradict each
  other and the model picks a winner at random.
- **Do not re-generalise the wordmark prohibition.** It reads "no brand
  wordmark, logotype or signature line **other than one quoted in the TEXT
  block above**" for a reason: branded creatives sign themselves through the
  TEXT block, and the old absolute prohibition told the model to drop the one
  string we asked it to draw.
- **Do not let `copy_compress_system.md` become a writing brief.** Its four
  load-bearing rules are the per-panel ceiling, the source language, the
  empty-stays-empty position and the ban on adding a fact the panel never made
  (FR-331/332). Softening any of them turns compression into authorship, which
  is the failure D50 named and D54 opened exactly one operator-opted door in.
  The `~14` humanizer patterns in it are a distillation of
  `prompts/humanizer_skill.md`; when that vendored file changes, re-derive them
  here rather than pointing the model at the file — no prompt loads it.
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
  `image_subline`, `slide`, `reel_seed_headline`) — change the style or the
  config, not a template. `retry_plan()` still re-computes it for a caller
  that cuts free-composed text, where the budget in force is cut by
  `retry_reduction_pct`; the gauntlet's own fix re-render never cuts a word,
  so it restates the same budget the first attempt carried.
- **`{{reference_roles}}`** lists only the references actually attached to
  *this* job — sometimes a brief's own picture, sometimes the anchor slide,
  usually nothing. Writing "Image 1, Image 2, Image 3" by hand describes a job
  that may not exist. When the carousel anchor is on, the anchor block is
  prepended ahead of this list and its Image 1 role wins over everything in it.
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
| Reference role lines — one per attached reference: **brief subject**, **carousel anchor**, **reel seed frame**, and (v2.1.3, FR-315) a **mark patch** — a sanctioned tool logo cropped from the source slide, the one reference whose own lettering is copied rather than greeked. The style provenance was removed by D46 | `{{reference_roles}}` | `generate/refs.py`, `generate/carousel.py`, `generate/reel.py` |
| Gauntlet fix suffix — the `FIX —` header, up to three CANNED remedy sentences keyed by `(code, zone)`, the conflict-precedence block and the fence-closing line (FR-323). A critic's own `detail` never appears in it | appended to the assembled render prompt on a fix re-render | `prompts/gauntlet_fix.md`, selected by `gauntlet.py` `fix_instruction` |
| On-image text block — `headline (render verbatim): "…"` plus a **conditional** `spelled out (accented words): V-ě-t-š-i-n-a` line (FR-186 diacritics defence). Since Session 5.5 (F1-B) the echo carries **only the words holding a non-ASCII character**, and a value where no word does — an English headline, a `01 / 06` counter, most wordmarks — omits the line entirely. Echoing pure-ASCII words taught nothing and doubled the one block no length pass may touch | `{{onimage_text}}` | `prompts_engine.py` `_onimage_text` / `_spell` |
| Wordmark entry — `wordmark (render verbatim): "HypeLead"`, plus the spelling aid only when the wordmark itself carries a non-ASCII character; emitted only when the creative is branded (FR-292 channel 1) | `{{onimage_text}}` | `prompts_engine.py` `_onimage_text` |
| Branding block — accent instructions per `mode`, font character, placement hint, background hint, and the profile's `never_always` / `never_style` guards (FR-292 channel 2) | `{{branding_block}}` | `prompts_engine.py` `branding_block` (public — `generate/refs.py` gates it on `entry.branded`) |
| Empty-signature line — *"This frame carries no signature zone: the lower margin is empty."*, appended when a `role: brand_slot` zone is dropped on an unbranded creative | `{{layout_zones}}` | `prompts_engine.py` |
| Numbered candidate list — one section per creative, its bound post's offerable strings with their `P<n>.<kind>[.<i>]` labels, source-deck panels first | `{{source_hooks}}` | `copywrite.py` (owns numbering AND resolution — one implementation; it overwrites the slot after `build_context` returns) |
| Compression work order — one section per creative: its language-mirror line, its caption source, and its admitted panels numbered by SOURCE POSITION with each position's own character ceiling (D54/FR-331) | `{{compress_panels}}` | `copywrite.py` `_compress_block` (same seam as `source_hooks`: written onto the built context, and the same walk that builds this block builds the `panel_map`) |
| `source panel i of N` position line and the per-slide visual brief | `{{slide_panel_source}}`, `{{visual_brief}}` | `generate/carousel.py` `_panel_source_line` / `_visual_brief`, fed by `sources/slide_intel.py` |
| Numbered topic blocks for the competitor screen, ordinals 1..N | `{{topic_items}}` | `prompts_engine.py` `_topic_items` |
| Candidate-style block — one entry per style usable somewhere in this run, each printed as `key` + `match_profile` + the formats it is meant for, the profile falling back to the first sentence of `render_prompt` where a style declares none (FR-334/335) | `{{style_candidates}}` | `style_match.py`, off `styles.py`'s own pool predicates (`usable_styles` / format affinity — imported, never re-derived) |
| Match entries — one section per planned creative keyed by `asset_id`: its format, its measured source signals, and its own candidate pool (FR-334/335) | `{{match_entries}}` | `style_match.py` (same seam as the two `copywrite.py` blocks: written onto the built context) |
| Campaign-brief context — the `Campaign brief "<name>" — influence: …` header, its directives, and the precedence sentence (`override` vs blend, FR-144/145) | `{{brief_directives}}` | `prompts_engine.py` `_brief_directives` |

Changing any of these means changing the constant in code (and the
requirement behind it), not editing a file in this folder.
