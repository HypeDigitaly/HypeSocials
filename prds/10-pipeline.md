# 10 — Pipeline

## TL;DR — Plain English

You pick how many pictures, slide-decks and short videos you want, and press Enter. About three minutes later — eight to ten if you asked for videos — you have a folder of finished posts.

Here is what happens in between, in order:

- **Find what is going viral.** The engine asks Virlo for the trends that are winning right now, and downloads the actual images from those winning posts.
- **Pick the best ones.** It scores each trend on views, freshness and Virlo's own confidence, throws away anything it already used recently, and hands the strongest trends to the posts you asked for. Slide-deck trends go to slide-decks, video trends go to pictures and videos.
- **Study the winners.** For each trend it shows the real winning images to an AI that looks at them and writes down exactly *why* they look the way they do — where the text sits, what colours, what kind of lettering, how the eye moves. No fluffy words allowed.
- **Write the words.** Another AI writes the caption, the hashtags and the text that goes on the picture. It copies the *shape* of the original hook (same rhythm, same length), not the words.
- **Make the pictures.** All the picture jobs are sent off at the same time, each one with two or three of the real winning images attached so the result actually looks like the trend. For slide-decks, slide 1 is made first and then used as the template for the rest, so the deck looks like one deck.
- **Make the video (if you asked).** A picture with the hook text baked into it is made first, then the video model brings it to life while keeping that text still and readable. The video model also makes its own matching sound, so clips are not silent unless you ask for silence.
- **Videos can study the real winning clip too.** Where possible the engine grabs the actual short video that went viral and hands it to the video model as a movement-and-style example — not just the still pictures. If that grab fails for any reason, the video is still made from the pictures alone and the log says so.
- **Optional spell-check by eye.** If you switch it on, an AI looks at each finished picture — including the still hook frame a video is built from — and answers one question: is the text broken or does it have fake Instagram-looking junk on it? If yes, it gets one more try with shorter text. Then it ships either way. For slide-decks, slide 1 is checked *before* the other slides are made, so the whole deck copies a slide that already passed.
- **Package.** Everything lands in a folder with a browsable page, a full log of what happened, and a note of what it cost.

Things worth knowing:

- **Money is checked before anything is bought.** If the estimate is over your limit and you are sitting at the keyboard, the run refuses to start and offers you smaller numbers. If it was started unattended (scheduled, or with the "just do it" flag), it does not refuse — it drops posts from the end of the list until the plan fits, and tells you in the log and the cost summary exactly which ones it dropped.
- **Nothing is allowed to block the run.** If one post fails, that one post is marked as failed and everything else still ships. You always get told what broke.
- **You can stop it at any time.** Press Ctrl+C once and it stops ordering new work, gives whatever is already paid for a short moment to arrive, then packages everything it has. Press Ctrl+C twice and it quits on the spot. Work already ordered is billed either way — the log lists it so nothing is invisible.
- **You can also order specific post types** — like a HypeDigitaly AI-audit CTA — via small brief files that override or blend with the trend look.
- **You can look before you spend.** One mode shows you just the trends for free; another adds the analysis and the copy for the cost of the text AI only.
- **There are no quality gates.** The engine makes it once and gives it to you. You are the reviewer.

---

How a HypeSocials run turns a menu selection into finished creatives. This file owns stages 1 and 3–8 of the canonical pipeline: run plan resolution, trend selection, visual analysis, copywriting, image and reel generation, concurrency, the optional vision check, budget behaviour, and failure handling.

Stage 2 (Virlo MCP, Notion MCP, Inspiration folders, reference-image download) is specified in the integrations file (`20-…`), which also owns all transport-level failure behaviour. Config keys and the menu are specified in the configuration file (`30-…`). Folder layout, gallery and logs are specified in the output file (`40-…`). Nothing here duplicates those; where this file mentions a config value it assumes the definition lives there.

Requirement ranges owned by this file: **FR-1 … FR-29**, **FR-90 … FR-109** and — as an extension, because FR-110+ belongs to `20-…` and FR-150+ to `40-…` — **FR-141 … FR-149** (FR-148/FR-149 tombstoned v1.6.1), plus the further extension block **FR-200 … FR-209** (of which **FR-200 … FR-203** are now in use), plus **NFR-1 … NFR-9** and **NFR-25** (NFR-10–NFR-14 belong to `20-…`, NFR-15–NFR-19 to `30-…`, NFR-20–NFR-24 to `40-…`).

---

## 1. Run plan resolution

A run begins with a *run plan*: a flat, fully resolved list of planned creatives. Everything downstream — cost estimate, trend assignment, concurrency, budget accounting, packaging — operates on that list. Resolving it is deterministic and takes milliseconds; no model is called until the plan exists and the user (or `--yes`) has approved it.

The inputs are the chosen config file plus any menu or CLI overrides: which formats are enabled, how many of each to produce, which platforms are enabled, the generation mode, the Notion influence tier, and the spend cap. Which trend sources feed the run is itself a first-class choice: `sources.active` (default `[virlo]`, per D20) decides which adapters collect, and the menu exposes it.

The console also offers two inspection modes that execute a *prefix* of the same pipeline rather than a separate code path (D19): `--preview-sources` runs Launch + Collect **plus Select's filtering pass** and displays every returned trend with the verdict a paid run would reach — eligible / excluded (history) / unusable (reason) — alongside stats, hooks, panel texts and reference thumbnails, at **zero model spend** (30-configuration FR-139); `--preview-analysis` additionally runs the visual analysis and the copywriting and displays the style briefs and copy, spending **LLM cost only**, with no image or video generation. There is no separate dry-run mode.

**FR-1 — Plan expansion.** The engine expands the **requested count per format** into one plan entry per planned creative, assigning each entry's platform per FR-2's distribution rule — counts are per format, never multiplied across platforms (4 images across 3 platforms is 4 creatives, not 12). Each entry carries: a stable asset id, its platform, its format (`image`, `carousel`, `reel`), its language (from the per-platform language setting), its target aspect ratio, and — for carousels — the configured slide count. The plan is fixed before any spend occurs.

**FR-2 — Count distribution across platforms.** Counts are requested per format, not per platform. Distribution is governed by the **per-platform `formats:` allowlist**: a format is only ever distributed to platforms that enable it. When several eligible platforms exist, the engine distributes the requested count across them round-robin in config order; remainders go to the earlier platforms in config order. Reels are enabled on TikTok only by default, so a requested reel lands on TikTok without any special-casing in the assignment code. A user who wants an exact per-platform split runs one config per platform. **One language per platform per run** — a platform configured `cs` produces only Czech creatives that run; bilingual output for one platform is two configs (or two scheduled runs), the same answer as the per-platform split.

**FR-3 — Mode expansion.** In `both` mode every planned creative is duplicated into an *analyzed* variant and a *direct* variant sharing the same trend, the same platform/format, and the same copy where copy applies. The two variants are siblings for A/B comparison in the gallery, linked by a shared `pair_id`.

**Campaign-brief creatives in `override` mode are exempt from this expansion.** An override creative makes no analysis call at all (FR-144), so there is no analyzed-versus-direct distinction to draw and duplicating it would buy two renders and zero information. An override creative therefore renders **exactly once** in every mode and is labelled `variant: direct` with no `pair_id`. `blend` creatives are analyzed like any other creative and expand normally.

`both` therefore roughly doubles the generation count and the cost estimate for everything except override-brief creatives, which stay single — the menu states the resulting count and cost before the user confirms rather than quoting a flat "×2".

**FR-4 — Plan is the unit of accounting.** The pre-flight estimate, the budget tally, the progress display and the final summary all count planned creatives (and, inside carousels, planned slides). A creative that is skipped, fails, or is cut by the budget cap remains in the plan with a terminal status so the summary can report it rather than silently shrinking.

### Campaign briefs (ordered post types)

Sometimes the run needs a *specific* post — an AI-audit CTA, a webinar announcement, a case-study teaser — rather than whatever the trends happen to be about. Campaign briefs (D26) cover that without a second pipeline: a brief is a small named file holding copy directives (message, CTA, structure), visual directives (optional, including its own reference images), the formats it applies to, and an **influence mode** of `override` or `blend`. The file shape and where briefs live (the active config's `briefs_dir`, default `briefs/`) are owned by `30-…`; how a brief's directives are placed into the model scaffolds is owned by `50-…`.

**FR-143 — Brief creatives are ordinary plan entries.** Briefs are requested by `--brief <name>:<count>` (repeatable) or by the equivalent menu step, and each requested copy expands into a normal plan entry carrying, in addition to the fields of FR-1, its **brief name** and the brief's **influence mode**. Distribution across platforms follows FR-2, restricted to the formats the brief declares. From that point on nothing is special-cased: brief creatives are counted in the pre-flight estimate, governed by the budget cap, logged like any other entry, and packaged into the same per-asset folders — the gallery simply shows a badge naming the brief (`40-…`). A brief creative that fails is a logged skip like any other.

**FR-144 — `override` mode skips trend assignment entirely.** An override creative **consumes no trend**. It is excluded from the ranked assignment of FR-8, does not count against `max_trend_reuses_per_run`, and never appears in trend history — the run's trend budget is untouched by it. Its inputs are exactly three: the brief's copy and visual directives, the brief's own reference images when it ships any, and the active niche descriptor (FR-147). No analysis call is made for it, so there is no style brief; the brief's visual directives take the place of `render_prompt` and `layout_zones` in prompt assembly (FR-17), while the mandatory clauses of FR-94 — exclusions, safe zone, re-flow, aspect-ratio-as-parameter — apply unchanged. Reference images, when the brief supplies them, attach exactly as trend references would.

**FR-145 — `blend` mode takes a trend, with the trend dominant on visuals.** A blend creative is assigned a trend by the normal rules of FR-8 and FR-90, is analyzed like any other creative, and counts toward reuse and history as usual. Its prompt assembly then adds the brief's directives alongside the style brief, under a **stated precedence: the trend's style brief wins on everything visual** — layout, palette, typography, treatment, composition — **and the brief wins on message, offer and CTA**, plus product nouns for the on-image text. This is the same precedence shape as FR-109's Notion `full` rule, and for the same reason: a creative that stops looking like the trend has stopped being a mimicry creative.

*Worked example.* Config enables LinkedIn, Instagram and TikTok; images are allowed on all three, carousels on LinkedIn and Instagram, reels on TikTok only. The user asks for 3 images, 2 carousels (5 slides each) and 1 reel, mode `analyzed`. The plan resolves to six creatives: LinkedIn image (16:9), Instagram image (4:5), TikTok image (9:16), LinkedIn carousel (5 × 1:1), Instagram carousel (5 × 1:1), and a TikTok reel (9:16) — the reel goes to TikTok because TikTok is the only platform whose `formats:` allowlist enables reels. That is 13 slide/image renders, plus one seed-frame render for the reel (FR-24), plus 1 video render; one analysis call per distinct assigned trend and one copy call per distinct (trend × language) pair. In `both` mode the same request becomes twelve creatives and roughly double the renders, with copy unchanged because variants share it — and **trend-reuse accounting unchanged too**, because each analyzed/direct pair counts as one use of its trend, not two (FR-8).

---

## 2. Trend selection

Selection turns the normalized trend items returned by the sources into an ordered shortlist and binds trends to planned creatives.

**FR-5 — Viral-strength ranking.** Ranking consumes a **`strength` value in 0–1 that each source adapter computes for its own items** — that one number is the cross-source contract (a future Google Trends or Hacker News adapter scores its items however suits its data; nothing in Select knows any source's internals). The Virlo adapter's strength is a simple, transparent score combining: total views (weight **0.35**) and median views (**0.15**) across the trend's top videos, a velocity/momentum signal (views relative to how recently the videos published, **0.30**), and Virlo's own confidence value (**0.20**) — *(amended v1.6.4)* sourced from the monitor analysis's per-theme confidence (the mean over the top themes consumed for the item), because the digest's `global_confidence` is null on every live trend (spikes/RESULTS.md §A); when no theme carries a confidence the component is absent and the remaining weights renormalize — each component **min-max normalized to 0–1 within the run's candidate pool** before weighting. The weights are **hardcoded at those defaults** — no config knob, because tuning weights is a false lever compared with the quality of the style brief — and they are stated here so the operator has signed off on them rather than a builder inventing them. The full ranked list with each component is written to the run log so a human can see exactly why a trend won.

The ranking is intentionally crude. Its job is to avoid picking a dud, not to find a global optimum. The defaults favour proven view volume with a meaningful recency tilt.

**FR-6 — Usability filter.** A trend is usable only if it carries enough material to drive mimicry: a name, at least one of `why_it_works` / `tactics` / a top-video description, and — preferably — at least one reference image (thumbnail or slideshow panel). Trends with no text substance at all are dropped. Trends with text but no images are kept and flagged `text_only` — an item-level flag (this particular trend arrived without pictures) that drives the last-resort rule of FR-90 and the reference-free render of FR-18. (The separate source-level media-richness concept was removed in v1.6.1 — see the FR-148/FR-149 tombstone.)

**FR-7 — History exclusion window.** Trends used within the last `trend_history_days` (per the trend-history state described in the output file) are excluded before assignment; `0` disables the window entirely. Exclusions are logged individually with the date the trend was last used, so a thin run is always explainable.

**FR-8 — Assignment to creatives.** Planned creatives are given trends from the ranked shortlist, strongest first, subject to the affinity rule below. **The effective batch ceiling is `usable_trends × max_trend_reuses_per_run`** — the plan can never deliver more creatives than that product, whatever was requested, so the operator sees "this plan needs N distinct trends; M are available after filtering" stated plainly. In an interactive run, when Select shrinks the confirmed plan (fewer usable trends than planned creatives), the console shows a one-line restatement — final creative count and revised estimate — before generation proceeds; under `--yes` the drop is logged and the run proceeds (FR-28). When the plan is longer than the shortlist, assignment wraps around and reuses the strongest trends — one trend legitimately powering an image, a carousel and a reel is a feature. Every reuse is logged as `trend_reused` with the count, bounded by `max_trend_reuses_per_run`; surplus creatives beyond that bound are dropped from the run and reported in the summary rather than generated off exhausted material. In `both` mode the analyzed and direct variants always share one trend — otherwise the A/B comparison is meaningless — and the pair counts as **exactly one unit** against `max_trend_reuses_per_run`. The pair is one logical creative rendered two ways; charging it two reuses would silently halve the effective reuse budget the moment `both` is switched on.

**FR-90 — Format affinity beats format weight.** Assignment matches trends to formats by the *shape of the source material*, not by a fixed "strongest trend gets the reel" ordering (that rule is withdrawn):

- Trends whose material is a **slideshow** (image panels + `panel_texts` + a narrative arc) are preferred for **carousels** — the source already is a carousel.
- Trends whose material is **video** (thumbnails, hook text, overlay text) are preferred for **images and reels**.
- When no affinity match remains for a format, assignment falls back to plain rank order.
- `text_only` trends (item-level, per FR-6) are the **last resort** for any format, and with `require_reference_image` at its default of `true` they are only used once no image-bearing trend is available at all. When one is selected, its render job runs **reference-free** under FR-18 and the asset is marked accordingly.

Every affinity decision — which trend went to which creative and whether it was an affinity match or a rank fallback — is logged with its reason, so an odd pairing is always explainable.

### Text-only sources

**FR-148 / FR-149 — removed (v1.6.1, operator decision).** The declared media-richness contract and text-grounded analysis mode were machinery for two adapters (Google Trends, Hacker News) that do not exist. When a text-only source is actually built, its adapter marks every item `text_only` (FR-6) and inherits the existing last-resort handling of FR-90 and the reference-free render of FR-18 — with the Inspiration pool (`inspiration_mix`) available as the curated visual channel. D28 is withdrawn with the same tombstone.

---

## 3. Visual analysis (analyzed mode)

Analysis runs only in `analyzed` and `both` modes, once per *selected trend* — not once per creative. Several creatives that share a trend share its style brief, which is both cheaper and more consistent.

**FR-9 — One vision call per trend, all concurrent.** The engine issues one Claude Sonnet 5 vision call per distinct selected trend, and issues all of them at the same time. Inputs: the trend's downloaded reference images (bounded by `media_download_cap`, per trend, default 6) plus the trend's text material — `hook_text`, `text_overlay_content`, slideshow `panel_texts` and `narrative_arc`, `tactics`, `why_it_works`, and the top videos' engagement numbers so the model knows what actually won.

**FR-91 — Coherent reference sets, not an engagement mix.** References are chosen as a **set that belongs together**, because a render conditioned on three unrelated images averages them into mush. Selection rules:

- A job receives **2–3 references** (`reference_images_per_job`, default 3) drawn from **one coherent source**: all panels of a *single* slideshow, or several thumbnails from a *single* creator or a single visual family. Never a top-engagement mix across unrelated posts.
- **Slideshow panels are preferred over video thumbnails**, because thumbnails are dense with platform UI, play buttons, usernames and engagement counters that the render model will happily copy.
- References **without a dominant human face** are preferred, because face-dominated references pull the render toward portrait reproduction and raise moderation-refusal risk.
- `media_download_cap` is the **primary per-trend cap** and governs both downloading and how many images enter the analysis call; `reference_images_per_job` governs only how many of those are attached to a render job.
- Inspiration images (D13) join per the **`inspiration_mix` config knob** (canonical in `30-…`; default `minority`): `minority` attaches at most 1 inspiration image as the **last** reference alongside 2 trend references, `exclusive` uses a coherent inspiration-only set, `off` attaches none. The mix actually used is recorded in the log. They are never blindly unioned into the Virlo pool.

**FR-93 — Analysis inputs are downscaled; render references are not.** Images sent to *analysis* vision calls are downscaled to roughly 1024 px on the long edge and re-encoded as JPEG, with about six images maximum per call — the analyst needs layout and palette, not pixels, and image tokens are a real cost line. The original full-resolution files are retained on disk and are what get attached as **render** references, where fidelity matters.

**FR-10 — The brief's job is mimicry.** The prompt instructs the model to act as a forensic analyst of a winning creative, not as a creative director. It must describe **what makes these specific images visually viral** in terms concrete enough to reproduce: layout and grid, focal point placement, foreground/background separation, colour palette with approximate values, typography character (weight, case, size relative to frame, outline/shadow treatment), text placement zones and density, image treatment (photo vs. graphic vs. screenshot, filters, borders, edge crops), and the visual pacing that carries the eye. Vague adjectives ("modern", "clean", "engaging") are explicitly disallowed; the prompt asks for reproducible description.

**FR-11 — Style brief contents.** Each brief covers: overall layout and composition rules; colour palette; typography treatment; on-image text placement and density; the hook pattern the original uses (what kind of statement, its length, its position); the content angle that made the trend work; and short per-format guidance — how the pattern translates to a single image, to a multi-slide carousel (including how a slideshow's narrative arc maps onto slides), and to a vertical reel.

**FR-92 — The brief is structured, not prose.** The model returns the brief as **structured JSON with named fields**, so the engine can inject parts of it precisely instead of pasting an essay into a render prompt. Required fields:

- `layout_zones` — an **ordered list of frame regions**, each naming its position (e.g. upper third, left gutter, lower-centre band), the content that occupies it (headline, subline, focal subject, negative space, badge), and the text treatment applied there (case, weight, relative size, outline/shadow).
- `exclusions` — everything present in the references that must **not** be reproduced: platform UI chrome, watermarks, usernames, engagement counters, captions belonging to the original post.
- `render_prompt` — a **compact instruction of ≤120 words** that alone is fit to be sent to the image model.
- Plus the descriptive fields of FR-11 (palette, typography, hook pattern, content angle, per-format guidance).

The forensic framing of FR-10 and the ban on vague adjectives apply verbatim to every field. The brief is written as if instructing an artist who will never see the originals — even though the render model *does* see them as reference inputs. Redundant conditioning is the point: prose and pixels reinforce each other. The **full brief is logged**; only `render_prompt` and `layout_zones` are ever injected into a render prompt (FR-94).

**FR-147 — The niche descriptor is standing context.** The active config may carry a short `niche:` descriptor block — who the audience is, what the vibe is, what visual world it lives in (D27 as simplified in v1.6.1; the block's shape is owned by `30-…`). That block is injected verbatim as **standing context** into both the analysis prompt (FR-9/FR-10) and the copy prompt (FR-14), so the analyst translates the trend into *this* niche's visual world and the copywriter writes to *this* niche's audience without either being told again per creative. It is context, not instruction: it never overrides the forensic-description rules of FR-10 or the structural-mimicry obligation of FR-100, and when the config has no `niche:` block the injection is simply absent.

**FR-12 — Brief reuse and absence.** A brief is computed once per trend per run and reused by every creative on that trend, across platforms and formats. If a trend's analysis call fails after its single retry, creatives on that trend fall back to direct-mode behaviour and are marked `analysis_missing` in their metadata and in the gallery; they are not skipped.

---

## 4. Copywriting

The copy model is GPT 5.6 Luna (OpenRouter id `openai/gpt-5.6-luna`, confirmed), and it is a **reasoning model**: it bills and reports reasoning tokens on top of the visible output, so config carries a reasoning-effort knob for the copy role that defaults to low/off — captions and hooks do not need deliberation — and the pre-flight estimate includes a reasoning-token allowance for every Luna call (FR-107).

**FR-99 — One copy call per (trend × language).** Copy is not written per creative. The engine issues **one GPT 5.6 Luna call per distinct (trend × language) pair**, and that single call produces copy for **all sibling creatives** on that trend in that language at once — the image, the carousel and the reel together. The prompt names each sibling and requires **explicitly distinct angles and distinct hook patterns** per sibling, so three creatives off one trend do not arrive as three paraphrases of one sentence. Fewer calls, less latency, and — because the model sees the siblings side by side — genuinely different outputs. All calls are issued concurrently.

**A failed group call is split, not surrendered.** Grouping is an efficiency, and an efficiency must never widen the blast radius: one failed call cannot be allowed to take four creatives down with it. So when a grouped (trend × language) call fails after its single retry, the engine **splits the group and issues one copy call per creative in it, one attempt each**, all concurrently. Only then can anything be declared lost, and only individually.

If a per-creative call also fails, that creative still renders: its on-image text becomes the **trend's own hook text** and its caption is a **minimal assembled caption** (trend name plus the platform's hashtag convention) built without any model call — the same deterministic string assembly FR-96 uses. The asset is marked `copy_degraded` in metadata, the log and the summary. A creative with borrowed words beats a creative with none, and the unit of loss stays one creative.

**FR-13 — Copy outputs per format.** Every creative gets a caption, a hashtag set, a hook line, and on-image text. Beyond that:
- **Image** — one on-image text block (headline plus optional subline), sized to the trend's observed text density.
- **Carousel** — per-slide text for every slide plus an explicit narrative arc across the slides (opening hook, escalation, payoff, closing call). **Per-slide word counts mirror the source `panel_texts`**: if the winning slideshow put four words on panel 1 and eleven on panel 3, the generated deck follows that rhythm. Slide texts are written as one coherent sequence, never slide-by-slide.
- **Reel** — the overlay/hook text to burn into the seed frame plus a one-line through-line for the video prompt.

**FR-14 — Copy inputs.** The prompt receives: the trend's hooks, panel texts, tactics, `why_it_works` and top-video descriptions; the style brief when one exists (so on-image text respects observed density and placement); the platform, format and language; the platform's tone and length conventions from config; Notion brand context when `notion_influence` is `copy` or `full`; the active niche descriptor as standing context (FR-147); the brief's copy directives when the creative came from a campaign brief (FR-146); and Inspiration text exemplars when configured, passed as voice examples to imitate in style, not content to copy.

**FR-100 — Structural mimicry is an obligation, not a suggestion.** The trend's hook is the asset; copying its words is plagiarism and paraphrasing it is waste. The prompt therefore requires a two-step move, in writing:

1. **Restate the abstract pattern** of the source hook — for example "negative-outcome claim, second person, seven words, no verb in the opening clause".
2. **Instantiate that pattern** on the new subject, matching its syntax, cadence and word count. When the source hook and the target creative are in **different languages** (EN source hooks, CS output), pattern matching is best-effort in the target language: syntax and cadence are the obligation, word count is guidance — a seven-word English pattern has no honest seven-word Czech equivalent.

The call is given **3–5 verbatim source hooks as few-shot exemplars** (real hook text from the trend's winning posts), and must return a `hook_pattern_used` field naming the pattern it followed. That field is written to the run log and the asset metadata, which makes structural mimicry auditable after the fact instead of merely requested.

**FR-146 — Brief-driven copy replaces or constrains the mimicry obligation.** For a creative that came from a campaign brief, the brief's copy directives — message, offer, CTA, required structure — enter the copy prompt and change what FR-100 asks for:

- In **`override`** mode the brief owns the copy outright. FR-100's hook-pattern mimicry is **relaxed to "follow the brief's stated structure"**; there is no source hook to abstract, no few-shot exemplars, and `hook_pattern_used` records the brief name and its declared structure instead of a source pattern.
- In **`blend`** mode FR-100 applies in full — the source hook's pattern is still abstracted and instantiated — but the instantiation must carry the brief's message and end on the brief's CTA. The pattern is the container; the brief is what goes in it.

Either way the copy call is still the one-per-(trend × language) call of FR-99 where a trend exists; override creatives, having no trend, are grouped by brief × language instead.

**FR-101 — Hard budget on on-image text.** On-image text carries a **hard character budget per text block**, stated in the prompt. Image models render a headline reliably and a paragraph unreliably; the budget is the cheapest available defence against garbled output.

The budget has **concrete ceilings**, not just a derivation. Defaults, held in config under `text_budgets` (canonical definition in `30-…`):

- **headline ≤ 42 characters** and **subline ≤ 60 characters** for single images and for every carousel slide;
- **headline ≤ 32 characters** for a reel seed frame, which is read at thumb size on a phone and animated afterwards.

The trend's observed text density then tightens these numbers **downward** — a source deck that put four words on a panel gets a budget well under 42 — but it can never raise them. The ceiling is the ceiling. The vision-check retry of FR-105 applies a **fixed −40% reduction** of whichever budget was in force for that asset, so the retry is a materially different request rather than a rounding change.

**Enforcement is two-layered, and the engine never cuts mid-word.** The budget is stated in the copy prompt as a hard constraint (layer one). If the model's output still exceeds it, the engine trims **at the last word boundary at or under the budget** before assembly — never mid-word, never with an ellipsis appended — and logs `text_trimmed` with the before/after strings (layer two). A mid-word cut baked into a render is precisely the garbled-text defect the vision check exists to catch; the engine must not manufacture it.

`onimage_text_language` may override the caption language for on-image text alone — useful when captions should be Czech but the render model is more reliable rendering English lettering. Runs whose on-image language is Czech print a **startup hint recommending `vision_check`**, since diacritics are where render models fail most often. The caption and the on-image text are additionally asked not to be the same sentence twice.

**FR-102 — External text is data, never instruction.** All externally sourced text — Virlo hooks, descriptions, panel texts, Notion page content, Inspiration files — is inserted into prompts inside explicit delimiters and introduced as *material to analyze, not instructions to follow*. One sentence in the prompt does the whole job; there is no scanner, no sanitizer and no gate.

**FR-15 — Conventions are guidance, never a gate.** Platform-specific length, tone and hashtag conventions live in config and are injected as instructions. The engine does **not** validate, truncate, re-prompt or reject output for violating them. If the model writes a long LinkedIn caption, that ships. Gates are what made the old system slow, and the user reviews the gallery before publishing.

**FR-16 — Copy is shared across mode variants.** In `both` mode the analyzed and direct variants of a creative use the same copy, so the A/B comparison isolates the visual approach rather than confounding it with different words.

---

## 5. Image generation

**FR-17 — Prompt assembly (analyzed mode).** An analyzed creative's image prompt is assembled deterministically from, in order: the style brief's compact `render_prompt` (≤120 words); its `layout_zones`; the copy's exact on-image text with an instruction to render it verbatim; and the mandatory clauses of FR-94. Assembly fills the model-specific scaffolds from the editable `prompts/` folder — the section order, text-locking phrasing, and per-model conventions are owned by `50-promptcraft.md` (D24/D25). The full style brief is **never** injected — it is logged instead. Prompts stay compact because long prompts dilute reference-image influence. The assembled prompt is logged in full for every job (to `events.jsonl`, per `40-…`'s logging split).

**FR-94 — Mandatory prompt clauses.** Every render prompt, in both modes, carries these four clauses:

1. **Exclusion clause (mandatory).** Never reproduce platform UI, watermarks, usernames, follower counts, engagement counters, progress bars, or any text visible in the reference images. The references inform **layout, palette, typography and treatment only** — never content, never chrome. The brief's `exclusions` field is appended to this clause when present.
2. **Safe-zone instruction.** All rendered text must sit within the **central ~80%** of the frame, so platform crops and UI overlays never amputate a headline.
3. **Re-flow instruction.** When the reference images' aspect ratio differs from the target ratio, the prompt explicitly instructs the model to **re-compose the layout for the target frame** rather than letterbox, stretch or crop the reference composition.
4. **Aspect ratio is an API parameter, never prompt text.** The target ratio is passed as a request parameter to the image model; writing "16:9" into the prompt text is forbidden, because models routinely render the string instead of obeying it.

**FR-18 — Reference images in both modes.** The actual winning Virlo images for the assigned trend are attached as **image inputs** to every GPT Image 2 job in **both** `analyzed` and `direct` mode. This is the visual-fidelity backbone of the product (D2). Which images and how many is governed by FR-91.

**The one standing exception is a trend that has no images to attach.** When an item-level `text_only` trend is selected as the last resort of FR-90, there is nothing to flow: the job runs **reference-free**, its subject supplied by FR-96's deterministic content sentence and its look by the written style description alone. The asset is marked `reference_free: true` in metadata, in the log and in the gallery, with a plain fidelity caveat — this creative mimics the trend's *topic and structure*, not its pixels. (FR-97's moderation fallback also strips references, but that is a recovery, not a selection outcome, and keeps its own `refs_dropped_moderation` marking.) "References always flow" therefore reads, precisely: references always flow **when references exist**, and their absence is always visible rather than silent.

**FR-200 — Local reference images are uploaded before they can be referenced.** Kie render jobs take references as **URLs**. Virlo CDN images and Kie-hosted results already have them; local files do not. Every locally held reference — Inspiration folder images (D13) and a campaign brief's own reference images (FR-144/FR-145) — is therefore **uploaded through Kie's file-upload API** (the same endpoint the video chain uses, FR-142 step 3; endpoints confirmed, OQ-5 closed — `20-…` §8b, including the ~24 h upload expiry, harmless within one run) to obtain a public URL before it is attached to a render job. Uploads for one job's reference set are issued concurrently; as transport-class calls they retry under `http_max_attempts` (default 3, `20-…` NFR-14), not the content-retry cap of 1.

**An upload failure degrades, it never blocks.** If one reference fails to upload, the job proceeds with whichever references did upload and the drop is logged by filename with its reason. If every reference in the set fails, the job proceeds reference-free under the FR-18 marking. A picture the operator curated is an input, not a prerequisite.

**FR-19 — Direct mode.** A direct-mode job carries the reference images plus a short instruction only: reproduce the visual style of the attached references for this platform and format, render this on-image text, obey the FR-94 clauses. No style brief, no analysis latency, no analysis cost. Direct mode exists to test whether the vision analysis earns its keep, which is what `both` mode measures.

**FR-96 — Direct mode gets a deterministic content sentence.** A pure style instruction with no subject produces generic output, so direct-mode prompts include one **minimal, deterministic content sentence** assembled **without any LLM call**: the trend name, a clause taken from the top video's description, and the target format. It is string assembly from data the engine already holds — cheap, reproducible, and enough to give the render something to be *about*. The same sentence is reused, in any mode, whenever a job runs reference-free (FR-18), for the same reason: a prompt with no pixels and no subject renders nothing in particular.

**FR-97 — Moderation-refusal fallback.** Provider content-policy refusals are detected as their **own failure class**, distinct from transient errors and timeouts (transport-level detection is specified in `20-…`). On a policy-class failure the job is **resubmitted exactly once with all reference images removed**, keeping the prompt otherwise identical, and the result is marked `refs_dropped_moderation` in the asset metadata and the log. Face-heavy references are the usual cause, which is why FR-91 avoids them up front. If the reference-free resubmission also fails, the creative is a logged skip.

**FR-20 — Carousels.** A carousel is generated as N slide jobs. Every slide shares the same style brief and the same reference set and adds its own slide text. There is **no** cross-slide consistency QA, no re-render loop, no "regenerate slide 3 to match slide 1". This is an accepted MVP trade-off (D3): the gallery shows the deck and the user judges it. On-disk slide naming and ordering are specified in the output file (`40-…`).

**FR-95 — Anchor chaining and the slide-count ceiling.** Per D17, `carousel_anchor` (default `true`) changes the submission shape:

- **Slide 1 is generated first, alone.** It establishes the template.
- **When `vision_check` is on, slide 1 is checked before slides 2–N are submitted** — and re-rendered at most once if it is flagged (FR-105). Slide 1 is a **chained artifact**: every other slide will copy it, so a garbled headline or a fake follower counter on slide 1 propagates into the whole deck. Checking it afterwards would mean discovering the defect N renders too late. The deck always anchors to the *final* slide 1.
- **Slides 2–N are then submitted concurrently** with the finished slide 1 attached as the **PRIMARY reference image**, ahead of the trend references, plus a **fixed template-lock instruction**: reproduce this exact template, palette, typography, margins and text placement; change only the text and the focal element.
- **If slide 1 fails**, the carousel falls back to independent generation of all slides from the trend references alone, and the fallback is logged. If slide 1 is flagged and its single re-render also comes back flagged, it **ships as the anchor anyway** — one retry is the cap everywhere, and a flagged anchor still beats an unanchored deck.

The cost is one extra round trip per carousel — two when the vision check is on — and the return is a deck that reads as one deck. With `carousel_anchor: false` all slides go out in a single burst, which is the A/B control.

Slide count comes from config per platform (`platforms.<name>.carousel_slides`, canonical in `30-configuration-and-run.md` FR-257). **The config value is the ceiling and the estimate basis.** When the assigned trend is a slideshow, its source panel count may **reduce** the slide count — mimicking the original's pacing — but may never raise it above the configured ceiling, so the pre-flight estimate can never be exceeded by a surprisingly long source deck.

**FR-21 — Aspect ratios (this file owns the defaults).** Aspect ratio is derived from platform and format and is settable per platform in config. Defaults: LinkedIn 16:9 single images, 1:1 carousel slides; Instagram 4:5 single images, 1:1 carousel slides; TikTok 9:16 images, **1:1 carousel slides** (TikTok photo posts accept 1:1, and the default allowlist enables carousels there — a format with no ratio would be an unbuildable default). The chosen ratio is recorded in asset metadata and passed as an API parameter (FR-94). The configuration file cross-references these defaults rather than restating them.

**Reels are 9:16 on every platform**, not merely on TikTok. TikTok is simply the only platform whose `formats:` allowlist enables reels by default; the ratio is a property of the *format*, and enabling reels elsewhere does not make them 16:9. Consequently **a reel's seed frame always inherits the reel's 9:16**, never the platform's image ratio — a 16:9 seed frame handed to a 9:16 video is a guaranteed re-composition, which is exactly the fidelity the seed frame exists to protect.

**FR-98 — Aspect handling: request the native ratio, ship what comes back (v1.6.1 — local crop/pad deleted).** Image models expose a fixed menu of output sizes, and Kie's verified `aspect_ratio` menu (20-integrations §8c) directly contains every default platform ratio this PRD uses (16:9, 4:5, 1:1, 9:16). The engine therefore requests the target ratio as an API parameter (FR-94), **ships the render exactly as it comes back**, and records the requested and received ratio in metadata. There is **no local crop, pad, or geometric post-processing of any kind** — the operator decided (v1.6.1) that a near-never-exercised safety net was not worth its code, its subtle chained-artifact exception, and an imaging-library use. If a future profile's menu lacks an exact ratio, the engine requests the nearest native size, records the mismatch in metadata and the log, and still ships as-is; platforms re-crop on upload anyway. Chained artifacts (the reel seed frame, FR-24; the carousel anchor, FR-95) were already required to render natively at their exact ratio — that rule survives unchanged and is now simply the same rule as everything else. Nothing is drawn, laid out or assembled locally; the old system's compositing path stays deleted.

**FR-22 — `both` mode output.** In `both` mode each planned creative produces two rendered outputs with identical copy, trend and aspect ratio, labelled `variant: analyzed` and `variant: direct` and sharing a `pair_id` in the asset metadata so the gallery places them side by side. There are no other variant tokens. If one variant fails, the other still ships and the pair is marked incomplete.

**FR-109 — Notion `full` precedence and seed capture.** When `notion_influence` is `full`, brand context reaches image prompts but with a **strict precedence rule: the trend's layout, typography and treatment always win.** Brand influence is limited to (a) substituting an accent colour within the trend's own palette structure and (b) supplying product/offer nouns for the on-image text. Brand fonts, brand layouts and brand templates are never injected — a brand-templated render is not a mimicry render, and mimicry is the product. Separately, and now settled: **Kie's responses expose no generation seeds.** Renders are therefore **not reproducible**, and the asset metadata says so plainly. What metadata does record is everything the engine itself holds — model id, the resolved job parameters it sent, the full prompt, the reference set and the aspect ratio — which is enough to re-run a render, just never to re-produce an identical one.

---

## 6. Reel generation

**FR-23 — One Seedance 2.5 clip per reel.** A reel is exactly one generated clip from Seedance 2.5, with the style driven by the trend analysis. The video prompt is assembled from the style brief's motion and palette guidance (or a short style instruction in direct mode), the overlay text, and the content through-line — filled into the **reel director-format scaffold whose section list, section order and per-@tag conventions are owned by `50-promptcraft.md` FR-194** (nine sections; D25). That enumeration lives there and is deliberately **not** restated here — two copies of a section list is one copy too many, and this file has no way to stay in step with it. Fixed request parameters:

- **Aspect ratio 9:16, passed explicitly** as a request parameter. The provider's `adaptive` option is never used — a reel that quietly comes back in the wrong shape is a wasted render.
- **Resolution from `reel_resolution`, default 720p.** 480p is documented as the deliberate cheap-test setting, nothing more. The estimate prices the reel at the *configured* resolution, never at a hardcoded one (FR-107).
- **Output format mp4.**
- The provider's own safety toggle is passed straight through from config at the provider default. It is a provider knob, not an engine gate — HypeSocials adds no gate of its own (D3).

No ffmpeg, no stitching, no local audio work, no stitched voiceover or music track — named future phases (D10).

**FR-24 — Reel text via seed frame (default).** Per D18, `reel_overlay_text` takes one of three values:

- **`seed_frame` (default)** — GPT Image 2 first renders a still hook frame **with the hook text burned into it**, using the same style brief, the same reference set and the same FR-94 clauses as any image. Because that seed frame is generated through Kie, the provider returns it as a **Kie-hosted public result URL**; that URL is passed **directly** into Seedance's reference-image list, and the prompt points at it using the model's `@Image1` prompt-reference syntax. **There is no upload step and no local file handling in this chain** — the engine never re-uploads the frame it just paid for, and Virlo CDN reference images can be handed over as URLs in exactly the same way. The animate instruction states explicitly that **the on-frame text stays static, unmoved and legible** while the surrounding scene moves. Image models render text far better than video models do; this buys legible reel text for the price of one extra image render, which the estimate already counts.
- **`in_model`** — the video model renders the overlay text itself. Retained for A/B testing.
- **`none`** — clean clip, no on-frame text.

**Two distinct failures, one identical degradation.** The seed-frame chain can break in two different places and the log must say which:

- **`seed_frame_render_failed`** — the seed-frame image job never produced an asset (terminal failure, moderation refusal after FR-97's reference-free retry, or timeout).
- **`seed_frame_url_unreachable`** — the seed frame rendered and was paid for, but its Kie-hosted URL could not be used at Seedance submission time: expired, 404, or rejected by the video model's reference validation.

Both degrade the reel to **`in_model` overlay text**, with the specific reason logged and written to asset metadata. Neither is ever allowed to surface as a generic whole-reel failure: the reel is still generated, still packaged, and still counted as delivered — it simply has its text drawn by the video model instead of baked in. A lost seed frame costs legibility, not a clip. (The old `reel_seed_image` toggle is removed — superseded by this key.)

**FR-141 — Reel audio is generated in-model.** Seedance 2.5 produces synchronized audio natively, so `reel_audio` (default `true`) simply maps to the provider's `generate_audio` flag and nothing else happens locally. Set to `false`, the reel ships **silent**, which is the right choice when the plan is to lay a platform-native trending sound over it at posting time. **There is no audio pipeline in the engine** — no extraction, no mixing, no music library, no ffmpeg. One API boolean is the whole feature (D22).

**Content-security audit degrade (v1.6.6, spikes/RESULTS.md §C).** When `generate_audio` is `true` and the motion reference carries copyrighted music, Kie's content-security audit can fail the job **after** the full render time (~5 minutes, billed at **zero** credits). This is its own failure class — `content_audit` — distinct from moderation refusal on imagery: the remedy is **silencing the clip**, never stripping references (FR-97's reference-free retry would throw away the motion reference for nothing). The engine retries **once** with `generate_audio: false` plus an explicit silent-clip prompt clause; the retry is the same pre-approved clip re-submitted (the failed attempt billed $0, so this is not a double-spend), and the delivered reel is tagged `audio_dropped_content_audit` in metadata, log and gallery. A second failure is a normal failed render. Retry cap of one per class is unchanged (NFR-4).

**FR-142 — Viral-video motion references.** When `reel_video_reference` is `true` (default), the reel additionally studies the **actual winning video** of its assigned trend, not just its still frames. **The chain starts concurrently with the Analyze stage** — it depends only on trend assignment, which is known before analysis begins, so its 15–60 s of probe/download/upload latency overlaps analysis and copy instead of extending the reel's critical path; its result is awaited (with a short bounded wait) only at Seedance submission time, and if it is not ready by then the degrade path below applies. The chain:

1. **Download.** The trend's top post video is downloaded with yt-dlp.
2. **Qualify.** Duration is read from **yt-dlp's own metadata — no ffmpeg** — and the candidate qualifies only if it runs within `reel_reference_max_s`, **default 28 s** (OQ-6 closed 2026-08-09: Kie's `bytedance/seedance-2-5` route serves the full tier, total reference video ≤ 30 s; canonical key in `30-…`). The 200 MB and mp4/mov (mkv spot-check) constraints apply. **Nothing is ever trimmed**: trimming would require ffmpeg, which the project does not carry. A longer video is simply not used.
3. **Upload.** The qualifying file is uploaded through Kie's file-upload API (exact endpoint marked *verify-at-build*, OQ-5) to obtain a public URL, because a downloaded video has no usable public URL of its own. This is the **same upload path** local reference images take under FR-200 — one mechanism, two callers.
4. **Reference.** That URL is passed as a Seedance reference video and the prompt points at it with the model's @-syntax, so the render mimics the winning clip's **motion, pacing and camera language** on top of the style brief's look.

**Every failure in this chain degrades, never blocks.** Download blocked or unavailable, no candidate under the duration limit, upload failure, malformed metadata — any of them drops the reel back to **seed frame plus image references only**, logs the specific reason, and the reel is generated exactly as it would have been without the feature. The video reference is an upgrade, never a dependency.

*Risk note.* Downloading videos from TikTok/Instagram for use as model references sits in a **terms-of-service gray zone**; leaving `reel_video_reference` on is the operator's explicit acceptance of that, and turning it off removes the behaviour entirely.

**FR-103 — Duration is validated and clamped at pre-flight.** Seedance 2.5 accepts a **continuous integer range of 4–30 seconds** (verified 2026-08-09; the provider's `-1` auto value is never sent), default **5** — not a discrete menu of allowed lengths. The configured reel duration is validated **before the run starts**: an out-of-range value is **clamped to the nearest end of the range with a logged warning** and the run proceeds; nothing is silently sent to the provider to fail after payment. (Total duration is also what the reference-video limit of FR-142 is measured against.)

**FR-104 — removed** (drafted as a separate seed-frame requirement; folded into FR-24 to keep all reel-text behaviour in one place).

---

## 7. Concurrency model

**FR-25 — Everything concurrent within a stage.** Per D5, each stage fans out fully: all trend analyses at once, all copy calls at once, all render jobs whose inputs are ready at once. Stages are ordered only by real data dependency (analysis → copy → generation), and inside the generation stage the only dependency is the chained artifact, which splits submission into **two waves** rather than a single burst. Within a wave nothing waits for a sibling. `max_inflight_llm_calls` and `max_inflight_render_jobs` bound the fan-out to respect provider rate limits.

**Permit granularity — the deadlock rule.** The render-concurrency permit is acquired **per submitted job** and released the moment that job reaches terminal status; **no task may hold a permit while awaiting a dependency.** The obvious wrong implementation — one coroutine per creative that takes a permit, submits its anchor or seed frame, and holds the permit while awaiting it — deadlocks the moment `max_inflight_render_jobs` carousels/reels are in flight (every permit held by a parent waiting on a child that can never acquire one). Implement as a small **2-tier priority permit gate** acquired inside the submit-and-poll function only, never around a creative: a released permit is handed to a waiting wave-2 acquirer (pre-committed, FR-106b) before ANY queued wave-1 acquirer, FIFO within each tier, and a held permit is never preempted. A plain FIFO semaphore is explicitly insufficient — wave-2 work queued behind a burst of wave-1 acquisitions would be starved, producing exactly the half-built decks FR-106b forbids (v1.6.7; the gate carries a named starvation test).

A six-creative analyzed run makes: one burst of analysis calls, one burst of copy calls, then **render submission in two waves** — *wave 1* carries every standalone image, every carousel anchor slide 1 and every reel seed frame; *wave 2* carries carousel slides 2–N and the Seedance video jobs, each released the moment its own prerequisite lands rather than when the slowest sibling does. Four round trips of latency, not fifty. The waves exist for one reason only — a chained artifact must exist before the job that references it (FR-95, FR-24) — and they are the same two waves the budget cap is enforced against (FR-106). Nothing else inside a creative is serialized, and no creative's wave 2 waits on another creative's wave 1.

**FR-26 — Batch submission and async polling.** Kie.ai has **no dedicated batch endpoint** — the "batch" simply *is* a burst of concurrent create-task calls, one per job, all issued at once within a wave (FR-25). Behaviour is unchanged from the original intent; only the wording is now honest. Status is then polled asynchronously across all outstanding jobs with backoff, and results are consumed as they complete. **Polling stays** because the provider's callback-URL option is unusable on a local workstation, which has no public endpoint to be called back on. Each job has its own timeout (`image_job_timeout_s`, `video_job_timeout_s`). **The batch never serializes on one slow job** — no stage waits for its slowest member before letting completed members proceed to download and packaging.

**FR-108 — Global run deadline.** Beyond per-job timeouts there is a **whole-run deadline**, `run_deadline_min` (default **25**, canonical in `30-configuration-and-run.md`). When it elapses, every outstanding job is **abandoned**, the run stops waiting, and it packages whatever exists — assets, gallery, log, spend summary — marking abandoned entries with their reason. A run must have a guaranteed end time; the per-job timeout alone does not provide one, because a chain of retries and a slow provider can outlast any single job's budget.

Two refinements make abandonment honest rather than merely fast:

- **One final grace poll.** At the deadline, outstanding jobs get **one short grace poll (~30 s)** before they are let go. Work that was seconds from completing is work already paid for, and thirty seconds is a cheap price for not throwing it away. After the grace poll, whatever is still unfinished is left to complete **unclaimed at Kie** — an accepted, stated cost — and is logged as `abandoned` together with its `taskId` (FR-203).
- **All timeouts and deadlines are measured on monotonic time**, never on wall-clock time. This is a workstation product: the PC sleeps, wakes, and has its clock stepped by NTP. Wall-clock timing would either trip the deadline instantly on wake or freeze it forever mid-sleep, and both failure modes are silent.

### Run lifecycle: interruption, exit codes, in-flight ledger

A run spends real money on a remote provider, which makes "how it ends" as much a requirement as "what it makes". Three behaviours cover every ending.

**FR-201 — Ctrl+C is a graceful stop, then a hard one.** The engine handles SIGINT in two stages:

- **First Ctrl+C** — the run **stops submitting new work immediately** and enters the abandon-and-package path of FR-108: in-flight jobs are drained, or grace-polled to the same ~30 s bound if draining would outlast it; every finished asset is packaged; the gallery, the run log and the spend summary are written; trend history is flushed for trends that already produced a packaged creative; and the MCP subprocess tree is killed. The console says plainly what it is doing and that a second Ctrl+C will not wait.
- **Second Ctrl+C** — the process **kills its child processes and exits at once**, without further packaging.

Stated plainly, because it is the thing operators get wrong: **work already submitted is billed regardless of when you interrupt.** Ctrl+C stops ordering, not spending. What it protects is your time; what FR-203 protects is your visibility into what you already bought.

**FR-202 — Exit codes are a contract.** Unattended runs are driven by Windows Task Scheduler, which can only read an exit code, so the codes are stable and mean exactly one thing each:

| Code | Meaning |
|---|---|
| **0** | Every planned creative was delivered. |
| **1** | Partial success — the run completed but at least one creative was skipped, failed, budget-trimmed or abandoned, **or a delivered carousel shipped incomplete** (missing slides, FR-20/§10 — a lost slide is a loss even when the deck ships; v1.6.7). |
| **2** | Pre-flight refusal or config error — **including a missing API key**. Detected before Collect; **nothing was spent.** |
| **3** | Fatal after Collect began — zero usable trends (for a plan needing trends; see the brief-only carve-out in §10) or a transport-dead source. Virlo calls may have been made; no LLM or render spend occurred. |
| **4** | Interrupted by SIGINT (FR-201). |

Code 1 is a *successful* run with losses and must not be treated as an error by a scheduler; codes 2 and 3 are the ones worth alerting on, and both guarantee zero LLM/render spend (2 additionally guarantees no external call at all). Standalone actions share the vocabulary: the preview modes exit 0 on success, 2 on config error, 3 on a transport-dead source; `--list-monitors` with a missing `VIRLO_API_KEY` exits 2 naming the variable.

**FR-203 — Outstanding-task ledger.** Every Kie submission is recorded in a small **ledger file in the run folder using an intent-before-call pattern**: a line carrying the creative id and a client-generated request token is appended **before** the `createTask` call goes out, and the `taskId` is appended once the response arrives. A submission whose response is lost (connection drop after Kie accepted the request — billed work with no taskId in hand) therefore still has a ledger line, marked `submit_unknown`, instead of being invisible — which is the exact case the ledger exists for. The ledger is written on submission — not on completion — because the entire point is to survive an ending the run did not plan for.

On deadline abandonment (FR-108) or interruption (FR-201) the ledger records which tasks were left **in flight**, so billed-but-unclaimed work is at least *visible* in the run folder and a later manual or best-effort re-poll is architecturally possible. That is the whole scope: a record, not a feature. **There is no automatic resume** — D12 stands; state is a trend-history file plus a log and nothing more. The ledger's exact filename and on-disk shape are owned by `40-…`.

---

## 8. Optional vision check

**FR-27 — Single pass, one retry, then ship.** When `vision_check` is enabled (off by default, D3), each finished image gets one Claude Sonnet 5 vision pass with a single narrow question. Nothing else is judged — no aesthetics, no brand, no claims, no "humanness". The outcome (`passed`, `retried_passed`, `retried_failed`, `not_checked`) is written to the asset metadata and the run log. All checks run concurrently.

**FR-105 — Check scope, carousel batching, and a retry that changes something.**

- **The question is widened** to two defects: *is the on-image text garbled, misspelled, cut off or otherwise broken?* **and** *does the image contain fake social-media UI, watermarks, usernames or engagement counters?* Both are objectively answerable and both are things a human cannot post around.
- **Check inputs are never downscaled.** FR-93's ~1024 px downscale applies to *analysis* calls only. A vision-check image is sent at native render resolution (or ≥1536 px long edge at minimum), losslessly or at high JPEG quality — a 42-character headline on a 1024 px re-encode is exactly where a model stops distinguishing a malformed glyph from compression, and Czech diacritics (the motivating case) are the first casualty. FR-107 prices check calls accordingly.
- **A carousel is checked in one multi-image call** covering all its slides, returning **per-slide verdicts**. N slides do not cost N calls. The estimate must price it the same way — **one call per carousel**, not one per slide (FR-107).
- **The anchor slide is checked before the deck is built.** When `carousel_anchor` is on, slide 1 is checked on its own — and re-rendered at most once if flagged — *before* slides 2–N are submitted (FR-95). That is a second check call for that carousel, and the estimate counts it.
- **Reel seed frames are in scope.** A seed frame is checked exactly like any other image, because legible burnt-in text is the entire reason the seed frame exists (FR-24); shipping an unchecked one would leave the feature's only claim untested. The check runs **before** the frame's URL is chained into Seedance, so a re-render replaces the frame the video is built from rather than arriving after the clip is paid for.
- **The retry changes the INPUT, not the plea.** Re-sending the same prompt with "please fix the text" appended repeats the failure. The retry re-renders with a **materially different input**: on-image text cut by a **fixed −40% of the character budget in force for that asset** (FR-101), fewer text blocks, and an instruction for larger type. At most one retry; then the asset ships regardless.
- **Finished video clips are excluded from the check — a stated decision.** Checking a clip would require extracting frames, and frame extraction means ffmpeg, which the project explicitly does not carry (D10). With seed frames now inside the check, the residual gap is narrow and named: it is only `reel_overlay_text: in_model` reels, whose text the video model draws and nobody inspects. The `seed_frame` default keeps that gap off the happy path.

---

## 9. Budget behaviour

**FR-28 — Estimate, tally, cap, report.** Before the run starts the engine computes an estimated cost from the plan and shows it against the spend cap. During the run actual spend is tallied from known unit prices and reported token usage. There are no day caps, no ledgers and no balance reconciliation (D11).

What happens when the estimate exceeds the cap depends on whether anyone is at the keyboard:

- **Interactive runs refuse.** The run does not start; the menu states the estimate, the cap and the gap, and offers reduced counts. A human who can decide should decide.
- **Non-interactive runs (`--yes`) auto-trim.** A scheduled 03:00 run that refuses produces nothing and tells nobody — the worst available outcome. So an over-budget unattended plan is **trimmed to fit** using the deterministic order of FR-106 rather than refused, and the run proceeds with what survives. The trim is reported in three places: the run log (every trimmed entry with its reason), the spend summary (a line naming the original estimate, the cap and the count trimmed), and the exit code (**1**, partial success, per FR-202). Trimmed entries stay in the plan as `skipped_budget` (FR-4), so the summary reports them instead of pretending they were never requested.

A `--yes` run only refuses outright when trimming cannot help — an unpriced format (FR-107) or a cap so low that nothing at all fits.

**FR-107 — What the estimate must include.** The estimate enumerates every **conditional contributor**, not just the obvious renders, because an estimate that omits half the spend is worse than no estimate:

- **vision-check calls** when `vision_check` is on. A carousel is **one multi-image call for the whole deck** (FR-105), not one call per slide — but that call is priced with the **vision image tokens of every slide it carries**, so an eight-slide deck costs one call's overhead and eight slides' worth of image tokens. Where `carousel_anchor` is on, the deck also costs a **second** call for the anchor check of slide 1;
- **seed-frame image renders** for every reel under `reel_overlay_text: seed_frame`, plus a **vision check per seed frame** when `vision_check` is on (FR-105);
- a **retry allowance** covering the worst-case **compound** per checked asset: **one moderation retry (FR-97) plus one vision-check re-render (FR-105)**. These are independent failure classes and an asset can genuinely hit both, so the allowance is sized for both rather than for whichever is larger. The cap of one attempt per class is unchanged (NFR-4);
- an **anchor-failure contingency for carousels**. When slide 1 fails, the deck falls back to independent generation of all N slides (FR-95) — and the failed slide-1 job is still billed, because spend tallies on submission. A carousel's worst case is therefore **N + 1 renders**, and the estimate carries that contingency rather than discovering it;
- **vision image tokens** — analysis calls priced at the downscaled size of FR-93; **vision-check calls priced at native render resolution**, because check inputs are never downscaled (FR-105);
- a **reasoning-token allowance for every Luna copy call**, because Luna is a reasoning model and bills reasoning tokens on top of visible output; the allowance scales with the configured reasoning-effort setting for the copy role. It also covers the **split per-creative copy calls** of FR-99, which are a real conditional contributor;
- **per-platform resolution**, since price scales with output size;
- carousel slides at the configured ceiling (FR-95);
- **reels priced as `price_per_unit.reel_second` × the configured duration in seconds, at the configured `reel_resolution`** — duration is a per-second cost lever, not a flat fee, and the resolution used for pricing is whatever config says, never a hardcoded 720p.

`price_per_unit.reel_second` is the canonical key name everywhere it appears — here, in the config file that owns it (`30-…`, FR-131), and in the failure table below. It **ships null/unset**, because Seedance pricing is still unpublished, and the estimate consequently **refuses to plan reels at all while it is unset**: the menu reports the missing price and offers the run without reels rather than guessing. An unpriced format is an unbounded format.

**Unpriced non-reel lines participate at $0 and say so.** LLM and image rates ship with real defaults (`30-…` FR-258), but when any rate is unset or zero, that line contributes $0 to the projection, the tally and the trim math — and the estimate, the spend summary and any `--yes` auto-trim report **"governance partial — N lines unpriced"** so a $0.42 estimate with an unpriced LLM line is never mistaken for a complete one. Only the reel rate blocks planning outright; a text call is bounded by token limits in a way a video render is not.

**FR-106 — When the cap actually bites.** Because renders go out in bursts, a cap checked "as spend accumulates" would arrive after the money is gone. But renders do **not** all go out in one burst — FR-25's wave model means there are three distinct moments where money leaves, and each needs its own answer.

**(a) Wave 1 — projection of the whole batch at expected cost.** Wave 1 carries every standalone image, every carousel anchor slide 1 and every reel seed frame. Before a single job is submitted, the engine checks the **projected cost of the entire batch at expected cost — wave 1 plus wave 2, without the retry allowance** — against the cap. Wave 1 is released only if that projection fits. If it does not, the plan is trimmed first and the trimmed entries are marked `skipped_budget` **before** anything is submitted. The worst-case figure including the FR-107 retry allowance is **displayed** in the estimate ("worst case: $X") but does not gate the release — retries are defended at spend time by the atomic reservation of (c), and gating on the compound worst case would systematically delete real creatives to reserve money for contingencies that mostly never happen.

**(b) Wave 2 — pre-committed spend, submitted unconditionally.** Wave 2 carries carousel slides 2–N and the Seedance video jobs. These are **already approved**: their cost was inside the wave-1 projection, and their prerequisites have been paid for. They therefore **always submit once their prerequisite completes, regardless of the interim cap state.** This is deliberate. Re-checking the cap between waves would produce carousels with slide 1 and slide 2 and nothing else, and reels with a seed frame and no video — half-built artifacts that cost most of the money and deliver none of the value. Cap bookkeeping must never be the thing that splits a deck.

**(c) The discretionary tail — checked against the remaining cap.** Vision-check re-renders, moderation retries and LLM retries are the only genuinely optional spend, and they are the only spend the cap can still decline. Seed frames are **not** in this list — they are wave-1 work, projected up front.

**Enforcement is by atomic reservation, never check-then-submit.** Before a discretionary submission is issued, its projected cost is **reserved** — decremented from the remaining cap — and only then is the job sent. If the reservation would take the remainder below zero it fails and the submission never happens. Reading the remaining cap, deciding, and then submitting are three separate moments, and the pipeline is fully concurrent (D5): a dozen vision retries all reading "$1.40 remaining" at once would all conclude they fit, and would jointly spend $6. The reservation makes the decision and the debit one indivisible step, so concurrent retries can never jointly exceed the cap. A reservation whose job then fails to submit at all is released. **Reservations reconcile to actuals:** when a job (or LLM call) reaches terminal status and its actual cost is known from reported usage, the difference `(actual − reserved estimate)` is applied to the remaining cap under the same lock — so the remainder tracks reality instead of drifting on estimates, and Luna's variable reasoning-token bills cannot silently overspend the cap.

**Trimming is one rule, made sufficient by plan ordering (v1.6.1).** When a plan must be reduced — at pre-flight, or under the auto-trim of FR-28 — entries are removed **from the end of the plan, in reverse plan order**, and that single rule does everything the old three rules did, because plan expansion (FR-1) is required to emit entries so that it holds: **brief creatives are emitted first** (so they are trimmed last — a run that drops the AI-audit CTA it was launched to produce has failed at its job), **a carousel is one plan entry** (slides are sub-items, so a deck can never be half-trimmed), and **a `both`-mode pair is one plan entry rendered two ways** (so a pair can never be split). Deterministic means two identical over-budget runs trim identically. Every trimmed entry is logged individually with its reason and its estimated cost.

Spend is tallied **on submission**, not on success: any job reaching a terminal status counts, **including failures**, because the provider bills submitted work. The pre-flight refusal or auto-trim (FR-28) remains the primary defence; this is the backstop.

**FR-29 — Cap reached mid-run.** When the cap is reached, the engine stops submitting **discretionary** work. Jobs already in flight finish and are packaged normally — cancelling paid work wastes money — and pre-committed wave-2 work still goes out, because it was approved in the wave-1 projection and abandoning it would leave half-built decks and clip-less reels (FR-106b). Every unsubmitted creative is marked `skipped_budget`, and the final summary states the cap, the actual spend, which creatives were skipped or trimmed and why, and — when wave-2 commitments carried the run past the cap — by how much.

---

## 10. Edge cases and failure modes

The governing philosophy: **degrade and report, never block the run.** A failed creative is a logged skip with a reason, not an exception that kills the batch.

Three rules make that concrete:

1. **Failure is scoped to one plan entry.** The unit of loss is one creative, or one slide. Where the engine batches work for efficiency — one copy call covering several siblings (FR-99), one vision call covering a deck (FR-105) — a failure of the batch is **split back into per-entry attempts** before anything is declared lost. An efficiency may never widen the blast radius.
2. **Every degradation is visible in three places** — the run log gets the detail, the asset metadata gets a machine-readable status, the final summary gets a human-readable line.
3. **The run only aborts before spending.** Once money has been spent, the run always finishes and always packages.

**Failed creatives keep their already-paid artifacts.** A creative whose render failed still ships its folder containing the caption, hashtags and a meta file with the failed status, alongside a `SKIP_REASON.txt`. The copy was paid for; deleting it saves nothing.

This table covers **plan-entry consequences only**. Transport-level behaviour — retries, backoff, rate limits, download integrity, MCP outages, stuck job ids — is owned by `20-…`; the on-disk shape of gallery, logs and folders is owned by `40-…`. Two cases appear here as well as there, because they have a genuine plan-entry consequence and stating it only in the output file would hide it from the pipeline's own failure story: **disk-write failure** (which plan entry fails, and that downloads stop) and **interruption** (which entries end up abandoned, per FR-201). `40-…` owns what those two write to disk; this file owns what they do to the plan. Retry cap everywhere is 1.

| Situation | Plan-entry consequence |
|---|---|
| Virlo MCP will not start (subprocess spawn or transport failure) | The run **aborts after writing the log**, exit code 3. This is a *distinct* case from "returned nothing usable": nothing was ever asked, so no widening of any window can help. The message names the MCP error class and the transport, not the trend counts. |
| Virlo dies partway through Collect (some monitors answer, others fail) | **Per-monitor degrade**: the run proceeds with the trends the answering monitors returned, and logs exactly which monitor ids failed and with what error. A partial source is thin material, not a dead run. If *no* monitor answered, this becomes the transport-failure row above. |
| Virlo returns nothing usable | **Only the trend-dependent portion of the plan dies.** Creatives that need a trend are dropped with the reason; **override-brief creatives (FR-144) proceed normally** — they consume no trend and their inputs are intact. A plan that was *entirely* override-briefs never opens a Virlo session at all (Collect is skipped). Exit code: 3 when every planned creative needed a trend (nothing deliverable), 1 when brief creatives shipped, 0 when the plan was brief-only and all delivered. The abort message **distinguishes the four causes and only suggests the remedy that fits**: transport failure (names the MCP error class and the tool called), monitor id not found (names the id), history exclusion (states how many trends were excluded and *only here* suggests widening or disabling `trend_history_days`), usability rejection (states how many were rejected and why). Suggesting a wider history window when the real problem is a typo'd monitor id sends the operator down a dead end. |
| Fewer usable trends than planned creatives | Strongest trends are reused up to `max_trend_reuses_per_run` (FR-8); surplus creatives are dropped and reported. |
| Trend has text but no images | Kept as `text_only` and used only as a last resort (FR-90). No references attach; the job runs **reference-free** on FR-96's deterministic content sentence and the written style description, and is marked `reference_free: true` with a fidelity caveat in metadata, log and gallery (FR-18). |
| Analysis call fails after its retry | Creatives on that trend degrade to direct-mode behaviour, marked `analysis_missing` (FR-12). Never skipped. |
| Grouped copy call fails after its retry | The group is **split**: one copy call per creative, one attempt each (FR-99). A group failure never skips a group. |
| Per-creative copy call also fails | That creative still renders, using the **trend's own hook text** as on-image text and a minimal assembled caption, marked `copy_degraded`. Only if the render then fails is it a skip. |
| Render job reaches a terminal failure | The plan entry is marked failed and keeps its paid artifacts. All other entries continue untouched. Transport handling in `20-…`. |
| Kie reports state `success` but `resultUrls` is empty, missing, or the URL is dead | Treated **exactly as a failed job** — logged skip with its own reason, paid artifacts kept (FR-74 in `40-…`). A success flag with nothing behind it is a failure that lies; it is never allowed to produce an empty asset folder that looks delivered. |
| Disk write fails mid-run, after the pre-flight space check passed | That creative fails with reason `disk_full`; **further downloads stop** rather than thrashing a full disk; the run packages whatever already exists and exits 1. Log flushing is written so that it **cannot itself crash** on a failed write — losing the log is losing the explanation. |
| Provider content-policy refusal | Detected as its own class; one reference-free resubmission (FR-97), marked `refs_dropped_moderation`. A second failure is a logged skip. |
| Seedance content-security/copyright audit fails the clip (music-bearing motion reference with `generate_audio: true`) | Detected as its own class (`content_audit` — billed $0 by Kie, spikes/RESULTS.md §C); **one retry with `generate_audio: false`** plus a silent-clip prompt clause, marked `audio_dropped_content_audit` (FR-141, v1.6.6). References are **kept** — this is never the FR-97 path. A second failure is a logged skip. |
| Carousel anchor slide 1 fails | Fallback to independent slide generation for the whole deck, logged (FR-95). |
| Carousel partially completes | Completed slides ship; metadata records `incomplete` with the missing slide numbers; the gallery labels it. Explicitly **not** all-or-nothing (D3). |
| Seed frame for a reel fails to render | The reel falls back to `in_model` overlay text, logged as `seed_frame_render_failed` (FR-24). If a viral-video reference qualified for that reel, **the reel keeps it** — losing the seed frame does not cost the motion reference. |
| Seed frame rendered but its Kie URL is unreachable at Seedance submission | Same degradation: `in_model` overlay text, logged as `seed_frame_url_unreachable` (FR-24). Explicitly **not** a whole-reel failure — the clip is still generated, packaged and counted as delivered. |
| Local reference image fails to upload to Kie | The job proceeds with its remaining references and the dropped file is logged by name (FR-200). If every reference in the set fails, the job runs reference-free with the FR-18 marking. |
| Viral-video reference chain fails (download blocked, no video within the duration limit, or upload failure) | The reel proceeds **without a video reference**, using its seed frame and image references only. The specific failing step is logged. Never blocks, never skips, never retried beyond the standard cap (FR-142). |
| `price_per_unit.reel_second` unset in config | Reels are not planned at all; the menu reports the missing price and offers the run without them (FR-107). |
| One `both`-mode variant fails | The surviving variant ships; the pair is marked incomplete via its `pair_id`. |
| Budget cap reached | In-flight work completes, pre-committed wave-2 work still submits, further discretionary submissions stop, skips reported as `skipped_budget` (FR-29, FR-106). |
| Estimate exceeds the cap under `--yes` | The plan is **auto-trimmed** to fit using FR-106's reverse-plan-order rule (briefs first in plan = trimmed last; carousels and pairs are single entries, never split) and the run proceeds. Every trimmed entry is logged and named in the spend summary; exit code 1 (FR-28, FR-202). |
| Run deadline elapses | Outstanding jobs get one ~30 s grace poll, then are abandoned with their `taskId` recorded in the ledger; the run packages what exists (FR-108, FR-203). |
| Operator presses Ctrl+C | New submissions stop; in-flight work is drained or grace-polled; everything finished is packaged and the ledger records what was left in flight; exit code 4. A second Ctrl+C exits at once (FR-201). Already-submitted work is billed either way. |
| Brief file missing or malformed at plan time | That brief's creatives are **dropped pre-flight**, before any spend, with a clear message naming the brief and the problem. The rest of the plan resolves and runs normally; the estimate is recomputed without them. |
| Brief in `override` mode whose referenced images are missing | The creative **proceeds with directives only** — no reference images attach — and the missing files are logged by name. An override brief's directives are sufficient on their own; missing pictures are a downgrade, not a blocker. |
| Notion context unavailable | The run continues with Notion influence effectively `off` for the missing pages, logged as a warning. Brand context is an enhancement, never a prerequisite. |
| Inspiration folder missing or empty | Treated as absent, logged once at info level; `inspiration_mix` simply contributes nothing that run. |
| Vision check itself errors | Treated as `not_checked`; the asset ships. A broken checker must never block delivery. |
| Missing API key for a required service | Detected at startup, before any spend, naming the environment variable. |

---

## 11. Non-functional requirements

**NFR-1 — Batch wall clock, two tiers.** The target is stated as two numbers, never one, because video generation is an order of magnitude slower than image generation and a single blended figure would be wrong for both: an image/carousel-only batch of ~8 creatives completes in **≈3 minutes** (images-only; anchored carousels add one render round trip, and `vision_check` adds the anchor-check round trip on top, so a carousel-heavy checked batch honestly lands **≈3–5 minutes**); a batch including reels completes in **≈8–10 minutes**, with the gallery written incrementally so images are reviewable while reels finish. Every speed claim anywhere in this file resolves to one of these two tiers.

**NFR-2 — Deterministic stages are instant.** Plan resolution, ranking, history filtering and assignment complete in well under a second combined, and are pure functions of their inputs.

**NFR-3 — No serialization by accident.** No stage may block on its slowest member before releasing completed members downstream, and no polling loop may be synchronous. The old system's 93 blocking status polls per run is the explicit anti-pattern. The sanctioned exceptions are the chained artifacts of FR-25's wave model — anchor chaining, seed framing, and the anchor's pre-deck vision check when `vision_check` is on — each scoped to a single creative and never to the batch.

**NFR-4 — Bounded retries.** Every retry in the pipeline is capped at one attempt. No render ladders, no escalating quality loops, no unbounded backoff chains.

**NFR-5 — Full observability.** Every stage logs: rankings with components, affinity decisions, every prompt in full, the full style brief, `hook_pattern_used`, every model and job id, per-item spend, every skip with its reason, per-stage timings. **Where each lands is owned by `40-…`:** full prompts and payloads always go to `events.jsonl`; `run.log` carries one-line digests and the human narrative. Any creative's provenance must be reconstructable from the two log files alone.

**NFR-6 — Cost predictability.** Actual run cost stays within a small margin of the pre-flight estimate whenever no failures occur, and the summary always shows estimate versus actual.

**NFR-7 — Leanness.** The whole pipeline fits inside the project's G2 line budget (target ~6,000, hard ceiling 6,500 — 00-overview v1.6.3), as a handful of small modules with no framework abstraction layers, no plugin registries and no strategy hierarchies.

**NFR-8 — Resource discipline.** Reference images and generated assets are streamed to disk rather than accumulated in memory; analysis inputs are downscaled (FR-93); concurrency limits keep in-flight requests within provider rate limits without manual tuning.

**NFR-9 — No unhandled crash.** Any single-creative failure is contained: the run finishes, packages what succeeded, writes the log, and exits with the status code that matches the outcome (FR-202). Missing credentials refuse at pre-flight (exit 2, nothing spent); the only fatal conditions (exit 3) are zero usable trends for a trend-dependent plan and a transport-dead source, both arising before any LLM/render spend.

**NFR-25 — One pinned imaging library, one permitted use (v1.6.1).** The pipeline carries exactly one imaging dependency, pinned, and it is used for **only** one thing: the analysis downscale/re-encode of FR-93. It is **not** used for cropping, padding, compositing, layout, text placement or image synthesis of any kind — FR-98's crop/pad was deleted in v1.6.1, and naming the single permitted use here is what keeps a geometry helper from quietly regrowing into the old system's 3,658-line fallback.

---

## 12. Design Decisions

**D2 — Dual mimicry modes, reference images always attached.** Mimicry quality is the product. A style brief is a *description* of what won; the winning images are the *evidence*. Attaching real Virlo creatives as image inputs in both modes conditions the render on ground truth rather than prose about it. `analyzed` adds interpretation and per-format translation; `direct` tests whether that interpretation helps; `both` renders the pair so the answer is empirical. Identical copy across variants keeps the comparison honest.

**D3 — Zero gates, one optional vision check, no all-or-nothing carousels.** The old system spent five to eleven sequential model calls per image on a QA ladder and still delivered three images in nineteen minutes. HypeSocials renders once and ships. The only defects a human genuinely cannot tolerate are garbled on-image text and fake platform chrome, so those get one narrow optional check whose retry changes the input rather than begging the model. Partial carousels ship because a labelled incomplete deck beats nothing.

**D5 — Concurrency everywhere.** In the old system 99% of wall clock sat in three serialized model stages. Fanning out every stage converts wall clock from *sum of latencies* to *max of latencies*. Per-job timeouts and the global run deadline are what make this safe.

**D10 / D18 — Reels are one Seedance 2.5 clip, with text on a seed frame.** Stitching, ffmpeg and local audio editing are a video-editing product, not a trend-mimicry product. One clip covers the use case. Text goes on a seed frame by default because image models render lettering far better than video models — and because the seed frame comes back from Kie as a hosted URL, chaining it into the video model costs **no upload and no local file handling at all**, just a URL and an @-reference in the prompt. One extra image render is a trivially cheap way to buy legible reel text — and because that frame is an image, the vision check *can* inspect it, so the seed frame is checked while the finished clip is not (FR-105). 9:16 is always passed explicitly rather than letting the provider adapt — on every platform, since the ratio belongs to the format and not to TikTok — and `reel_resolution` defaults to 720p because that is where the model is designed to run.

**D22 — Audio comes from the model, not from a pipeline.** Seedance 2.5 generates synchronized audio natively, so `reel_audio: true` is a single API boolean and the engine gains **zero** audio code — no ffmpeg, no mixing, no music library. That is the entire rationale: sound for free, or as close to free as a feature gets. Off is a real setting, not an afterthought, because a silent clip is exactly what you want when a platform-native trending sound will be laid over it at posting time.

**D23 — Reels study the winning video, not only its stills.** Mimicry is the product, and a still frame carries look while a clip carries **motion, pacing and camera language** — the half of virality a thumbnail cannot express. Feeding the trend's actual winning video in as a reference is therefore the single highest-leverage fidelity upgrade available to reels, and it costs one download plus one upload. It is built as a strictly optional upgrade path: duration is read from yt-dlp metadata so no ffmpeg enters the project, the qualifying bound is `reel_reference_max_s` (**default 28 s** — OQ-6 closed: Kie serves the full ≤30 s reference tier), nothing is ever trimmed (trimming would require ffmpeg), and **every** failure in the chain silently degrades to the seed-frame-plus-images behaviour with a logged reason. The honest caveat: downloading platform videos is a terms-of-service gray zone, which the operator accepts by leaving the toggle on and removes by turning it off.

**D17 — Carousel anchor chaining.** Shared briefs and shared references get a deck *near* consistency; attaching the finished slide 1 as the primary reference gets it *to* consistency, for one extra round trip and zero inspection calls. Slide 1 failing is the only risk, and it degrades to the previous behaviour rather than to nothing.

**D11 — Estimate up front, cap at the wave boundaries, report skips.** Refusing to start above the cap prevents the expensive surprise — except on an unattended run, where refusing produces nothing and tells nobody, so there the plan is trimmed to fit instead (FR-28). Because renders leave in waves rather than in one burst, the cap is checked at three points and not one: the whole-batch projection before wave 1, nothing at all before wave 2 (that spend is already committed and interrupting it would yield half-built decks), and an atomic reservation per discretionary retry thereafter (FR-106). Tallying on submission — failures included — matches how providers actually bill.

**D19 / D20 — Preview before spend, and choose your sources.** Preview modes execute genuine pipeline prefixes rather than a parallel dry-run implementation, so what you preview is what will run. `sources.active` makes the source set an explicit choice rather than a hardcoded assumption, which is what makes future adapters a config change instead of a rewrite.

**D26 — Campaign briefs are plan entries, not a second pipeline.** A content engine that can only post about whatever is trending cannot run a campaign. Briefs fix that with the smallest possible mechanism: a text file the operator edits in Notepad, requested by count like any other format, flowing through the exact same estimate, budget, logging and packaging path. The two influence modes exist because the two real needs are different — sometimes the post must say a specific thing regardless of what is trending (`override`, so the trend is not even consumed and the run's trend budget is preserved for creatives that need it), and sometimes the campaign message should ride a trend's look to earn attention (`blend`, where the trend keeps the visuals and the brief keeps the point). Relaxing hook mimicry under `override` is deliberate: mimicking a source hook you are deliberately not using would be mimicry theatre.

**D27 — The niche descriptor rides along with every prompt** *(simplified v1.6.1)*. Trend material tells the models what won; it does not tell them who is reading. Two sentences of standing context — audience, vibe, visual world — sitting in both the analysis and copy prompts is the cheapest available way to keep a trend translation on-brand without a brand-grounding stack. It lives in the niche's config file rather than in the engine, so switching niches is picking a different config.

**D28 — withdrawn (v1.6.1).** The declared media-richness contract was machinery for adapters that don't exist; see the FR-148/FR-149 tombstone in §2. A future text-only adapter marks its items `text_only` and inherits the existing handling.

**What is deliberately absent.** No template or style-system selection layer (the old system had 29 style systems and ~7,300 lines to pick one; the style brief replaces all of it). No compositing, Pillow fallback, or local crop/pad of any kind — renders ship exactly as the model returns them (FR-98). No multi-model comparison harness. No claim gate, humanness critic, or disclosure logic. No cross-slide consistency inspection loop. No gallery rating widgets — the `both`-mode verdict is the operator's eyeball plus logged cost and time deltas, recorded when concluded as a comment next to `generation_mode` in the config. Render providers are reached through D34's deliberately tiny four-operation seam — a thin wrapper, not the old system's provider-neutral abstraction layers. Each absence was considered and rejected on the same grounds: it costs latency and lines, and the gallery review it replaces is free.
