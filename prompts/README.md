# prompts/ — editable prompt templates (D24)

Plain text files. Edit them in Notepad; the next run picks up the change with
no build step and no restart of anything but the run. Spec: `prds/50-promptcraft.md`.

**This file is documentation, not a template. The engine never loads it.**

## Layout (FR-181)

```
prompts/
  style_brief_system.md          global — Sonnet 5 visual-analysis system prompt
  copywriter_system.md           global — Luna copywriting system prompt
  vision_check_question.md       global — the two objective defect questions
  gpt-image-2/
    image_single_post.md         analyzed single image
    carousel_slide.md            one carousel slide (style-DNA scaffold)
    carousel_anchor_instruction.md   block added when slide 1 is the PRIMARY reference
    image_direct.md              direct mode (no style brief)
    reel_seed_frame.md           the still hook frame a reel is animated from
  seedance-2-5/
    reel_director.md             nine-section reel director prompt
```

## Placeholders (FR-182)

`{{name}}` is plain string substitution — no conditionals, no loops, no
expressions. The engine fills them from the style brief, the copy output and a
secret-free context object; an unfilled placeholder fails that creative
**before** anything is submitted, so never invent a new `{{name}}`.

| Placeholder | Filled with | Used in |
|---|---|---|
| `{{render_prompt}}` | style brief's compact ≤120-word instruction | image_single_post, carousel_slide, reel_seed_frame |
| `{{layout_zones}}` | style brief's ordered frame regions — zone structure only, never a reference's literal wording | image_single_post, reel_seed_frame |
| `{{style_dna}}` | the fixed palette/type/grid block, identical on every slide | carousel_slide |
| `{{onimage_text}}` | the exact text to render, already inside its character budget | all render templates |
| `{{text_budgets}}` | the on-image character budget **in force for this call**, sourced from config `text_budgets` | copywriter_system + the four gpt-image-2 render templates |
| `{{reference_roles}}` | one line per **actually attached** reference: index · source kind · what it contributes · what it must not | image_single_post, carousel_slide, image_direct, reel_seed_frame |
| `{{exclusions}}` | style brief's "must not be reproduced" list | image_single_post, carousel_slide, reel_seed_frame, reel_director |
| `{{content_sentence}}` | deterministic subject sentence, no LLM call (FR-96): direct mode and any reference-free job | image_direct |
| `{{through_line}}` | the copywriter's one-line "what this clip is about" | reel_director |
| `{{brief_directives}}` | campaign brief's directives; empty when none | render templates, copywriter_system |
| `{{brand_accent}}` | filled with the brand accent-colour + product-noun line (Notion `full` influence only; empty when off) | image_single_post, carousel_slide, image_direct, reel_seed_frame |
| `{{slide_index}}` | this slide's position in the deck | carousel_slide |
| `{{seed_frame_ref}}` | one-line description of what the seed frame shows | reel_director |
| `{{audio_cue}}` | the whole AUDIO body — either the bracketed cue set or the silent-clip line | reel_director |
| `{{reference_image_count}}` | how many references the analyst is looking at | style_brief_system |
| `{{trend_texts}}` | trend hooks, panel texts, tactics, descriptions | style_brief_system, copywriter_system |
| `{{engagement_numbers}}` | what actually won, and by how much | style_brief_system |
| `{{output_format}}` | the required style-brief JSON field list | style_brief_system |
| `{{niche_descriptor}}` | audience / vibe / visual world; empty when unset | style_brief_system, copywriter_system |
| `{{source_hooks}}` | 3–5 verbatim source hooks (few-shot exemplars) | copywriter_system |
| `{{style_brief_summary}}` | short form of the brief for the copywriter | copywriter_system |
| `{{platform_conventions}}` | tone/length/hashtag guidance per platform | copywriter_system |
| `{{brand_context}}` | Notion brand context; empty when influence is off | copywriter_system |
| `{{sibling_list}}` | every creative sharing this copy call | copywriter_system |

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
- Change wording freely; change section *labels* only if you mean it — the
  labelled scaffold is what makes a bad render debuggable from the log.
- A broken or deleted file is not fatal: the engine falls back to its built-in
  default for that role and logs a warning naming the file (FR-183). A newly
  registered render profile has no built-in, so its whole set must be present.
- **Never hardcode a character budget or a reference list.** Both change per
  call; the placeholders exist so a template can never go stale (see below).

## Three placeholders that are computed per call, not fixed

- **`{{text_budgets}}`** is filled from config `text_budgets`
  (`image_headline`, `image_subline`, `reel_seed_headline`) — change the
  numbers in config, not here. The engine also re-computes it for a
  vision-check retry, where the budget in force is cut by
  `retry_reduction_pct`, so the same template renders a tighter constraint on
  the second attempt.
- **`{{reference_roles}}`** lists only the references actually attached to
  *this* job — two or three trend images, sometimes an Inspiration image last,
  sometimes a brief's own picture, sometimes none. Writing "Image 1, Image 2,
  Image 3" by hand describes a job that may not exist. When the carousel
  anchor is on, the anchor block is prepended ahead of this list and its
  Image 1 role wins over everything in it.
- **`{{audio_cue}}`** is the entire AUDIO body of the reel prompt, in one of
  two shapes: the normal cue set — `(music/ambience matched to the trend)`
  plus at most one `<sound effect>`, per the bracket taxonomy — or, when
  `reel_audio` is off (or audio was dropped after the run degraded), the
  silent-clip line: *"Silent clip — no music, no melody, no vocals, no
  soundtrack of any kind."* Brackets `{ }` (dialogue) and `【 】` (generated
  subtitles) are never used.

`{{through_line}}` carries the copywriter's reel through-line;
`{{content_sentence}}` stays reserved for FR-96's deterministic direct-mode /
reference-free sentence and is the fallback fill for the reel through-line
when no copy exists.
