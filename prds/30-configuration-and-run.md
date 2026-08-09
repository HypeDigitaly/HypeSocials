# 30 — Configuration & Run Experience

Companion to **00-overview.md** (pipeline, decisions), **10-pipeline.md** (run flow, edge cases per stage), and **20-integrations.md** (MCP/REST details). This file owns everything about how a run is configured, launched, and controlled by a human or a scheduler.

**FR ranges owned by this file:** FR-50–69, FR-130–140 (original), FR-170–177, FR-250–259, and FR-280–289 (amendment cycles). FR-141+ is owned by 10-pipeline.md; FR-210–229 by 60-publishing-postiz.md.

**This file is the canonical owner of every config key name, every default value, and every CLI flag in HypeSocials.** Sibling files reference the names below verbatim; if a name appears here and elsewhere, this file wins.

## TL;DR — Plain English

You control HypeSocials with one settings file and one command. Copy the sample settings file, drop your API keys in a `.env` file, and run `run.bat`. A short menu asks a handful of questions — which settings file, which trend source, how many images/carousels/reels, your spend limit — shows you what it's about to cost, and only spends money after you say yes.

Before you burn a cent, you can ask it to just look: **Preview sources** shows you the trending content it found *and which of it the run would actually use*, for free. **Preview analysis** additionally shows the AI's style notes and draft captions, for a small AI cost, with nothing rendered yet.

- Settings live in YAML files in `configs/`; copy `default.yaml` to make your own.
- Secrets (API keys) go in a `.env` file, never in the settings file itself — not even as a `${PLACEHOLDER}`.
- The menu is optional — pass `--yes` plus flags and it runs unattended, perfect for Windows Task Scheduler.
- Nothing generates until you've seen the price and confirmed.
- Unattended runs never stop to ask. Too expensive → it trims down to your cap and tells you what it dropped. Reel price not filled in → it runs without reels. Anything else odd → logged, run continues.
- Reels stay switched off until you type a real price into the settings file. Nobody has published what Seedance costs, and HypeSocials refuses to guess with your money.
- Every model the engine uses is just a line of text in the settings file — the thinking model, the writing model, the image model, the video model. Swapping one for a close relative (a faster or cheaper version of the same model) is a one-line edit, nothing else changes.
- Jumping to a completely different model *family* also needs a matching "profile" — a small description of how that family wants to be talked to. If you name a model or profile the engine doesn't know, it stops before spending anything and tells you exactly what's missing.
- Prices you typed in stay exactly where you put them when you swap a model. The cost preview prints which model each price is assumed to belong to, so an old price attached to a new model is obvious instead of silently wrong.
- Every run gets its own timestamped folder with a full log, so you can always see exactly what happened and what it cost.
- Want a specific angle instead of pure trend-copying? Save a **brief** (message, CTA, visual direction) once and request it by name and count.
- Running more than one niche or brand? A niche is just **another settings file** that carries a short `niche:` description (audience, vibe, look) and points at its own folders for inspiration images, briefs, and prompt tweaks. Switching niche = picking that file. No special machinery.
- Don't know your Virlo monitor IDs? Run `--list-monitors` and it prints them.
- Czech text is safe everywhere — console and files are UTF-8, so diacritics never crash a run or turn into gibberish.
- Publishing straight to Postiz is coming in Phase 2 — the `--publish` flag and a menu action already exist now as honest placeholders that say so.
- API keys never touch a prompt, a template, or a log line — they only ever go into request headers.

## First-Run Setup

Work through this once, before your first `run.bat`:

1. **Get your API keys.** `VIRLO_API_KEY` (required — trend discovery; **note: Virlo's API also requires a payment method and a prepaid deposit in the Virlo billing dashboard before any call succeeds** — OQ-19), `OPENROUTER_API_KEY` (required — Sonnet 5 analysis + GPT 5.6 Luna copy), `KIE_API_KEY` (required — GPT Image 2 + Seedance 2.5 generation), `NOTION_TOKEN` (optional — only needed for `notion_influence: copy` or `full`).
2. **Put them in `.env`** in the repo root, one `KEY=value` line each. `run.bat` loads it automatically; keys never go in a config YAML file, in any form (see §2 Secrets handling below and 20-integrations.md §9).
3. **Find your Virlo monitor IDs — run `run.bat --list-monitors`.** A "monitor" is HypeSocials' name for a Virlo agent — the resource that watches a niche/topic for trends. The flag opens a Virlo MCP session, calls the wrapper's `list_monitors` tool (20-integrations.md §3), prints every monitor's id and name, and exits without spending anything; paste the ids you want into `sources.virlo_monitor_ids` in your config. *(Convenience alternative: the same ids are visible in the Virlo dashboard's monitors/agents list — exact navigation unverified, which is precisely why the flag exists.)*
4. **Share each configured Notion page with the integration, once**, if you plan to use Notion influence — Notion pages are private to integrations by default; open each page's share menu and add the HypeSocials integration, or the MCP fetch silently sees nothing.
5. **Optional: add Inspiration folders.** Drop reference images or proven-copy text under `Inspiration/`, list the paths under `sources.inspiration_folders` (D13). Leave empty to skip — off by default. (A niche config, Section 2 §Niches, simply lists its own folder here.)
6. **Run `run.bat`.** First run bootstraps the Python environment — including `yt-dlp`, a plain pip package used for the reel video-reference feature (D23), installed alongside every other dependency with no separate step for the operator; every run after that starts fast.
7. **Sanity-check before spending.** Pick "Preview sources" from the menu, or run `--preview-sources`, to see exactly what Virlo returned — trends, stats, hooks, thumbnails — plus which of those trends the run would actually use and which it would skip, at zero cost, before committing to a paid run.

`configs/default.yaml` ships fully annotated: every key in Section 2 appears there with an inline comment. Skim it once and the settings surface stops being a mystery.

## Summary

HypeSocials is driven entirely by YAML config files in `configs/`, layered with optional CLI flag overrides. `run.bat` boots the engine; with no `--yes` flag it opens a short interactive menu (D8) that lets the operator pick a trend source, tweak the run, and see a pre-flight cost estimate before any money is spent. Two zero-risk inspection modes — Preview sources and Preview analysis (D19) — let an operator look before spending anything at all. For unattended runs, the same behavior is available headless via CLI flags, so Windows Task Scheduler can call `run.bat` with a fixed argument line. There is no database, no fail-closed config validation regime, and no built-in scheduler — config problems produce one clear error line, missing keys quietly fall back to documented defaults, and recurrence is Task Scheduler's job.

## 1. Config Files

- `configs/default.yaml` ships with the repo and is the baseline: sensible, annotated defaults for every setting described in Section 2.
- Users create variants by copying `default.yaml` to a new name inside `configs/`, e.g. `reels-only.yaml`, `czech-ig.yaml`, `weekend-budget.yaml`. A variant only needs to contain the keys it overrides — everything else is inherited from documented defaults, not from `default.yaml` textually (the engine does not merge two files; it applies defaults key-by-key).
- Config load is deliberately simple, not fail-closed:
  - **Missing file** (the `--config` name doesn't exist in `configs/`): the engine prints one clear error naming the file it looked for and the full list of files it found in `configs/`, then exits. No run starts.
  - **Missing keys** within an otherwise valid file: each key not present falls back to its documented default, and the engine notes which defaults were applied in the run log (not on-screen, to keep the menu uncluttered). This replaces the old system's fail-closed validation regime — HypeSocials favors "start with sane defaults and report" over "refuse to run."
  - **Present but malformed value** (wrong type, out-of-range, unknown enum): one clear error naming the offending key, the value found, and the expected form (see Section 8). This is the one case that does stop the run before any spend.
- The **first two lines** of every config file are structural, not free-form comments: **line 1** is a short human-readable description shown by the menu's config picker (e.g. `# Balanced default run across all three platforms`); **line 2** points at this PRD section (`# See prds/30-configuration-and-run.md §2 for the full field reference`). Everything after that stays comment-light — the documentation lives here, not scattered through YAML.
- **There is exactly one config shape (v1.6.1).** A "niche" is an ordinary config file in `configs/` that carries a `niche:` descriptor block and points at its own asset folders via three ordinary keys (`sources.inspiration_folders`, `briefs_dir`, `prompts_dir` — Section 2 §Niches). The picker shows it like any other config (its `niche:` line as the description); `--config <name>` selects it non-interactively. Keeping a niche's assets together under one folder (e.g. `niches/hypedigitaly/`) is a recommended *organizational convention* the paths point into — not engine machinery.

## 2. Config Surface

Every setting below is a config key with a documented default; CLI flags (Section 5) can override the subset that makes sense per-run. Key names and defaults here are canonical for the whole PRD — sibling files reference them by name rather than repeating them.

**Run defaults**
- Formats to produce: `image`, `carousel`, `reel` (any combination), plus a per-format count.
- Platforms to target: LinkedIn, Instagram, TikTok (D6) — any subset.
- Language per platform: EN or CS (D6).
- Generation mode: `analyzed`, `direct`, or `both` (D2).
- Notion influence level: `off`, `copy`, or `full` (D7), plus the Notion page list.
- Vision check toggle (`vision_check`, default **false**, D3); when on, at most one retry per flagged image or slide. When any enabled platform's language is `cs`, the engine prints a one-line startup hint recommending `vision_check: true` — Czech diacritics are the one place GPT Image 2 visibly struggles — but this is a hint, never a gate.
- Spend cap for the run, in dollars (D11).
- Trend-history window (`trend_history_days`, default **7**; `0` disables it) (D12).
- `max_trend_reuses_per_run` (default **2**) — caps how many planned creatives may share one trend; see 10-pipeline.md FR-8 for the assignment behavior this bounds.
- `carousel_anchor` (default **true**, D17) — slide 1 renders first and becomes the primary reference for slides 2–N.
- `reel_overlay_text` (`seed_frame | in_model | none`, default **seed_frame**, D18).
- `reel_audio` (default **true**, D22) — maps to Seedance's `generate_audio`; the model generates synchronized AI audio natively, no ffmpeg or audio pipeline. `false` ships a silent clip for platform-native sound overlay instead.
- `reel_video_reference` (default **true**, D23) — for maximum motion mimicry, the winning post's video is pulled via yt-dlp, uploaded through Kie's file-upload API, and passed to Seedance as a motion/style reference. *Downloading source video sits in a platform-ToS gray zone, accepted by the operator.* Any failure in that chain (download blocked, no qualifying clip, upload failure) silently degrades that reel to seed-frame + image references only, logged, never blocking the run.
- `reel_duration_s` (default **5**, integer **4–30** — Seedance 2.5's verified range; the provider's `-1` auto is never sent) — out-of-range values are clamped to that range at pre-flight with a logged warning, not rejected.
- `reel_reference_max_s` (default **28**) — the qualifying duration bound for the viral-video motion reference (10-pipeline FR-142; OQ-6 closed: Kie serves the full ≤30 s reference tier, and 28 leaves headroom under the ceiling). **Cost warning (v1.6.6):** a qualifying reference's seconds are billed at the full with-video rate (spikes/RESULTS.md §C), so this key is a **price lever**, not just a safety bound — attaching a reference is cheaper than not attaching one only while `input_s < 0.65 × output_s` (≈3 s for the default 5 s reel), and the worst-case-honest `reel_second` scalar scales directly with this value.
- `reel_resolution` (`480p | 720p`, default **720p**) — `480p` is documented as the cheap option for test runs.
- `nsfw_checker` (default **true**, explicitly sent) — a provider-side content-safety knob forwarded to Seedance as-is, not an engine gate. The engine's default is a deliberate `true`; the provider's own default is `false` (verified 2026-08-09), which is why the value is always sent rather than omitted.
- `require_reference_image` (default **true**) — a `text_only` trend is last resort for a creative unless disabled.
- `onimage_text_language` — per-platform override of the language used for on-image/slide/overlay text specifically, separate from caption language; defaults to the platform's configured language when unset.
- `text_budgets` — the character ceilings for text that gets *rendered into* an image, enforced when the copy model's output is assembled into a render prompt (10-pipeline.md FR-101 consumes these): `image_headline` (default **42**), `image_subline` (default **60**), `reel_seed_headline` (default **32**), and `retry_reduction_pct` (default **40**) — the percentage by which a budget is cut when a vision-check retry re-renders with shorter text. These are engine-enforced ceilings, not prompt hints: over-long copy is trimmed before submission rather than sent and hoped for — always at the last word boundary at or under the budget, never mid-word, logged as `text_trimmed` (10-pipeline.md FR-101 owns the two-layer rule).
- `run_deadline_min` (default **25**) — a soft elapsed-time ceiling for the whole run, measured on the monotonic clock (10-pipeline FR-108; never wall clock — the PC sleeps and NTP steps). *Rationale for the default:* a slow reel can legitimately occupy its full `video_job_timeout_s` (300 s) after a slow seed-frame chain, and a moderation retry plus a vision-check re-render can each add a render round trip; the batch target is ≈3 minutes for image/carousel-only runs and ≈8–10 minutes once reels are in play — 25 minutes leaves the worst realistic case inside the deadline instead of tripping it on a normal bad day. (A timed-out render job is never resubmitted — 20-integrations §8.)

**Niche packs (D27)**
- **A niche is a config file, not a special folder type (v1.6.1, operator decision).** It is an ordinary `configs/*.yaml` carrying three things beyond the usual keys: a `niche:` descriptor block (audience, vibe, visual world — injected into the Analyze and Write prompts; 10-pipeline.md FR-147), `sources.inspiration_folders` pointing at its curated images, and the two optional path keys **`briefs_dir`** (default: the repo's top-level `briefs/`) and **`prompts_dir`** (default: unset — global `prompts/` only). There is no separate picker path, no `--niche` flag, no bundle-activation step: picking the config *is* switching the niche.
- Keeping a niche's assets together in one folder (e.g. `niches/hypedigitaly/` holding `Inspiration/`, `briefs/`, `prompts/`) remains the **recommended organizational convention** — the config's paths simply point into it. The engine never scans `niches/`; only the paths in the active config matter.
- Template resolution with `prompts_dir` set: that folder first, then the global `prompts/`, then the built-in default (50-promptcraft.md owns the order). Briefs resolve from `briefs_dir` only — one folder per run, no cross-folder name-collision rules.
- *Shipped first niche (operator decision, 2026-08-09):* **`configs/hypedigitaly.yaml`** — the AI-agency / HypeDigitaly marketing niche — ships as the default picker selection, pointing at `niches/hypedigitaly/` (its `Inspiration/` seeded from the repo's existing top-level `Inspiration/` material). Restaurant-UGC and psychedelic-esoteric stay documented example niches.

A niche config looks like any other config, plus:

```yaml
niche:
  audience: "solo SaaS founders, EN + CS"
  vibe: "no-fluff, contrarian, founder-to-founder"
  visual_world: "dark UI screenshots, neon accent, handwritten notes"
sources:
  inspiration_folders: ["niches/hypedigitaly/Inspiration"]
briefs_dir: "niches/hypedigitaly/briefs"
prompts_dir: "niches/hypedigitaly/prompts"   # optional; falls back to global prompts/
```

**Sources (D20)**
- `sources.active` — which source(s) feed this run, default `[virlo]`. `google_trends` and `hacker_news` are named future adapters, visible in the menu's source picker (Section 4) marked *not yet implemented* — selecting one is rejected with a clear message, never a silent no-op.
- `sources.virlo_monitor_ids` — one or more; see First-Run Setup for how to find them.
- `media_download_cap` (default **6**) — maximum reference **images** fetched **per trend** (the D23 winning-video reference is bounded separately: one per reel, by `reel_reference_max_s`); this same cap governs how many images are attached to the vision-analysis call for that trend (20-integrations.md).
- `reference_images_per_job` (default **3**) — references attached per single render job, chosen as a coherent set (mixed shot types from the same trend), not simply the top-N by engagement.
- `sources.inspiration_folders` — a **flat list of local folder paths** (D13; the earlier "per platform" scoping is dropped — one global pool), off/empty by default. A niche config lists its own folder here (§Niches).
- `inspiration_mix` (`off | minority | exclusive`, default **minority**) — how Inspiration images join a render job's reference set (10-pipeline FR-91): `minority` attaches at most 1 inspiration image as the last reference alongside 2 trend references, with the mix logged; `exclusive` uses a coherent inspiration-only set; `off` never attaches them (they may still inform analysis text exemplars).

**Campaign briefs (D26)**
- The active config's **`briefs_dir`** (default: the repo's top-level `briefs/`) holds small named brief files, one per post type (e.g. `ai-audit-cta`). One folder per run — a niche config simply points the key at its own folder (§Niches above); there are no cross-folder collision rules (v1.6.1).
- Each brief file states, in plain fields: a **name**; a one-line **description** (shown wherever briefs are listed); the **format(s)** it applies to (`image` / `carousel` / `reel`, any subset); an **influence mode** — `override` (the brief fully replaces the trend inputs for that creative; the trend at most lends palette/energy if the brief asks) or `blend` (the trend's visual look stays dominant; the brief steers message/CTA only); **copy directives** (message, call-to-action, structure); **visual directives** (specific style/layout instructions); and optional **reference image paths** the brief supplies itself, instead of or alongside trend references.
- Briefs are requested per run via the repeatable CLI flag `--brief <name>:<count>` (e.g. `--brief ai-audit-cta:2 --brief customer-story:1`) or via the menu's Briefs step (Section 4) — none requested by default.
- A brief-driven creative is an ordinary plan entry: it counts toward the pre-flight cost estimate exactly like a trend-driven creative of the same format, appears in the run log and gallery the same way, and is subject to the same spend cap and skip-on-failure handling as any other creative (10-pipeline.md).
- A brief named in a request that doesn't exist, or whose file is malformed (missing a required field, an unrecognized influence mode, a format outside `image`/`carousel`/`reel`), produces one clear pre-flight error naming the exact brief file, before any billable call — the same posture as a malformed config value (Section 8). Under `--yes` the same error is logged but only that brief's creatives are dropped, so an unattended batch is never lost to one stale brief (FR-252).
- A brief that carries its own images is a **folder** rather than a loose file — `briefs/<name>/` holding the brief file plus the images it points at, with the folder name serving as the brief name. Everything else about it is identical: same fields, same request syntax, same plan treatment.
- Briefs are plain text/YAML, tunable in Notepad — the same editing model as `prompts/` (D24).

*Worked example — a product ad from your own photos (D35).* An operator who wants ads for a physical product creates `briefs/product-ad/`, drops their own product photographs in beside the brief file, and lists those paths as the brief's reference images. The brief's influence mode is `override` (the product, not the trend, is the subject — the trend at most lends palette and energy), its copy directives state the offer, the hook angle and the CTA, and its visual directives spell out the "high-retention product ad" look the operator wants: tight product framing, hard-cut pacing, bold on-image claim, no lifestyle filler. It is then requested like any other brief — `--brief product-ad:3`, or the menu's Briefs step. **This adds nothing to the engine.** The brief machinery from D26 already accepts brief-supplied reference image paths; local files already reach the render model through the existing local-reference upload path (D32, 20-integrations.md FR-244); the resulting creatives are ordinary plan entries, priced in the same pre-flight estimate, subject to the same spend cap, logged and galleried like everything else. The example is here because product ads are the most common thing operators ask for beyond pure trend mimicry, and it is worth stating plainly that they are already possible with zero new features.

*Shipped first brief (operator decision, 2026-08-09):* **`niches/hypedigitaly/briefs/ai-audit-cta/`** (reached via `configs/hypedigitaly.yaml`'s `briefs_dir`) — a CTA post promoting HypeDigitaly's free AI audit — ships as the first real brief: influence mode `override`, formats `image` + `carousel`, copy directives carrying the audit offer, hook angle and CTA, visual directives for a bold direct-response look. Requested as `--brief ai-audit-cta:N` or via the menu's Briefs step. It doubles as the living reference implementation of the brief file format.

**Platform format allowlist & carousel size**
- Each platform declares which formats it may receive (`platforms.<name>.formats`); default allows `image` + `carousel` everywhere and **`reel` only on TikTok**. A requested reel for a platform outside its allowlist is dropped from the plan with a logged reason, not an error — count distribution round-robins only across platforms that enable that format (10-pipeline.md FR-2).
- `platforms.<name>.carousel_slides` (default **5**) — **the one canonical carousel slide-count key in the whole PRD.** It is simultaneously (a) the per-deck ceiling that 10-pipeline.md FR-95 applies when generating a carousel, and (b) the slide count the pre-flight estimate multiplies by the image unit price (10-pipeline.md FR-107). A trend's own panel count may only **reduce** the deck below this number, never raise it above it. For Instagram the value SHOULD stay within **2–10**, Instagram's own platform ceiling, so that a Phase 2 publish never silently drops slides (60-publishing-postiz.md FR-221). Nothing else in the PRD names a slide count — any other file needing one references this key.

**Models (D34)**
- **Four canonical model keys, one place.** Every model the engine calls is a plain config string, editable in Notepad, requiring no code change: `models.analysis` (default **`anthropic/claude-sonnet-5`**, via OpenRouter — visual trend analysis and the optional vision check), `models.copy` (default **`openai/gpt-5.6-luna`**, via OpenRouter — captions, hooks, on-image and slide text), `models.image` (default **`gpt-image-2-image-to-image`**, via Kie — images and carousel slides; this is the reference-bearing route, OQ-17 closed 2026-08-09 — the profile automatically uses the `gpt-image-2-text-to-image` sibling for reference-free jobs, 20-integrations §8c), and `models.video` (default **`bytedance/seedance-2-5`**, via Kie — reels). These four names and defaults are canonical for the whole PRD; earlier drafts named the last two `models.copywriting` and `models.reel`, and those spellings are retired in favour of `models.copy` and `models.video` — one setting, one name, in this file.
- **Swapping a model inside the same profile is a config edit and nothing else.** Both OpenRouter models sit on the same chat endpoint and both Kie models on the same job-submission route, so an id or route string is genuinely the only thing that changes: no code change, no prompt-template change, no other config key. Trading `bytedance/seedance-2-5` for a faster sibling, or `anthropic/claude-sonnet-5` for another OpenRouter model, is one line (20-integrations.md, D34).
- **Model profiles — `models.image_profile` (default `gpt-image-2`) and `models.video_profile` (default `seedance-2-5`).** A profile is the small description of how a model *family* wants to be talked to — parameter names and mapping, reference-input limits, and which `prompts/` template set applies (owned by 20-integrations.md FR-272; template sets by 50-promptcraft.md). These two keys say which profile interprets the configured render model. **They only change when the model family changes** (Seedance → Kling, GPT Image → something else); a same-family swap never touches them. A profile the engine doesn't implement, or a model/profile pair it can't resolve, is a pre-flight refusal naming what's missing — never a mid-run surprise (FR-281).
- Role-suffixed knobs follow the canonical role names: `temperature.analysis` / `temperature.copy`, `max_tokens.analysis` / `max_tokens.copy`.
- Temperature and max-token knobs per text-generating model — the practical use case is **cost control**: lowering `max_tokens` on the analysis call directly caps that call's contribution to the LLM line of the pre-flight estimate on high-volume runs, independent of any quality concern. **Defaults are sized for the grouped calls, not single answers:** `max_tokens.copy` defaults to **3000** — one FR-99 call returns caption + hashtags + hook + on-image text for an image, per-slide text for a 5-slide deck, and reel overlay + through-line, comfortably 1,500–3,000 tokens; an 800-token cap would truncate nearly every multi-sibling trend and pay for FR-127's retry as the normal path. `max_tokens.analysis` defaults to **2000** for the same reason (FR-92's full field list).
- `reasoning_effort` — `models.copy` role only, default **low** (effectively off). Luna is a reasoning model; its reasoning tokens are billed and reported in usage, so this knob controls cost, and the pre-flight LLM estimate includes a reasoning-token allowance for the copywriting line.
- ~~`image_quality_tier`~~ — **removed (v1.6.1)**. OQ-7 closed: Kie exposes no quality tier on either `gpt-image-2` route, so the key was permanently inert and is deleted rather than shipped dead. If a future profile's provider exposes tiers, the key returns with that profile (50-promptcraft FR-187 stays as the advisory rule: medium/high whenever on-image text is present).
- `price_per_unit` — the estimator's entire price table (D11), informational and never billing-authoritative. It is **not** two scalars: the things HypeSocials buys are priced in three different units, so the table has three shapes.
  - **LLM tokens, per model role**: `price_per_unit.llm.sonnet.input_per_mtok` / `.output_per_mtok` for the analysis + vision-check model, and `price_per_unit.llm.luna.input_per_mtok` / `.output_per_mtok` / `.reasoning_per_mtok` for the copy model — Luna bills reasoning tokens separately, so they get their own rate rather than being folded into output.
  - **Images, per resolution tier**: `price_per_unit.image.1k` and `price_per_unit.image.2k`. Price scales with output size, so the estimator looks up the tier the platform's resolution actually maps to instead of applying one flat image price.
  - **Reels, per second per resolution**: `price_per_unit.reel_second.480p` and `price_per_unit.reel_second.720p`. **This is the canonical reel price key name** (`price_per_unit.reel_second`), and a reel's estimated cost is that per-second rate × `reel_duration_s`. **The scalar is worst-case-honest, not a provider rate (v1.6.6, OQ-2 measured — spikes/RESULTS.md §C):** Kie bills Seedance with-video jobs at `unit × (input_video_s + output_s)` and per resolution (720p $0.190/s with a video reference, $0.315/s without; 480p $0.085/$0.140), which one scalar cannot express — and the reference's real duration is only known after the yt-dlp probe, i.e. **after** the pre-flight estimate is shown. The operator therefore derives the scalar as `unit_with_video × (reel_reference_max_s + reel_duration_s) / reel_duration_s` — the worst case that config can produce — deliberately overstating the cheaper branches (no reference at all, or a shorter one), because understating is the one unacceptable estimator error (D11/FR-282). `configs/hypedigitaly.yaml` documents the arithmetic inline.
  - **Prices follow the model, not the provider (D34).** Every rate in this table belongs to whichever model was configured when the operator typed it in. Swapping a render model does **not** clear, rename, or auto-adjust any of it — the estimator keeps using the numbers that are there, because guessing a new model's price would be exactly the dishonesty the unpriced-line rule exists to prevent. What changes is visibility: the pre-flight cost summary prints, for each priced line, which configured model that price is being assumed for (e.g. *image 1k $0.03 — assumed for `gpt-image-2-text-to-image`*). A swapped model still carrying its predecessor's rates is therefore something the operator can see on screen before confirming, not something they discover on the invoice (FR-282).
  - **Unset or zero rates are reported, never silently treated as free.** Any estimate line whose rate is missing or zero prints as *unpriced* alongside the total, so an operator can tell "$0.42 estimated" from "$0.42 estimated, LLM line unpriced". Reels are the one case where an unpriced line blocks planning outright (FR-131) — an unpriced reel is unbounded in a way an unpriced text call is not.
  - **Both `reel_second` values ship as empty (`null`) in `configs/default.yaml`, deliberately.** Seedance 2.5 pricing is unpublished (OQ-2), so there is no honest default to ship — a fabricated number would silently mis-estimate every reel run. Until the operator looks up the real rate and types it in, reels are simply not planned (FR-131). The annotated comment in `default.yaml` says exactly this.

**Platform conventions**
- Caption length/tone and hashtag-count hints per platform — prompt guidance only, never enforcement (D3/D4); a caption running long is never blocked or retried for that reason alone.
- **Aspect ratio per platform × format is not set here.** 10-pipeline.md owns the platform default ratios (FR-21); this file only offers an optional per-platform × format **override** for a run that needs to deviate from those defaults.

**Integrations — MCP servers**
This is the only place in the PRD that sketches `mcp_servers` config shape; 20-integrations.md cross-references it rather than repeating it.
- `virlo` — stdio transport, launches the Python Virlo MCP wrapper shipped in the same virtual environment (`python -m hypesocials.virlo_mcp`, D21) — no Node toolchain needed for this one.
- `notion` — stdio transport, launches the self-hosted Notion MCP server via `npx`, authenticated with `NOTION_TOKEN` passed through an explicit per-server `env` map that the engine builds at spawn time (D21, §Secrets handling below — the map is never written into the YAML).
- Any HTTP-transport server entry carries an `auth_env` field naming the environment variable holding its bearer token.
- `postiz` — streamable-HTTP transport, optional, ops-query only, unused in MVP (D9; 20-integrations.md §6, 60-publishing-postiz.md).
- MCP timing: `mcp_startup_timeout_s` (default **20**) — how long a spawned server has to become usable before the engine gives up on it — and `mcp_call_timeout_s` (default **30**) — the ceiling on any single tool call. They are separate keys because a slow *launch* and a hung *call* are different failures with different fixes (20-integrations.md §2, §10).
- Kie.ai job timing: `image_job_timeout_s` (default **180**), `video_job_timeout_s` (default **300**), `poll_interval_s` (default **3**) — the gap between `recordInfo` polls for every in-flight job (20-integrations.md FR-43). *Rationale for 300:* the previous 600 s ceiling let one stuck reel eat the entire run deadline; at 300 s a reel that hangs still leaves room for its one retry inside `run_deadline_min`.
- `http_max_attempts` (default **3**) — the hard attempt ceiling on **every** bounded-retry path in the engine: OpenRouter calls, Kie.ai submissions and polls, Virlo tool calls, and (Phase 2) Postiz calls. One number, one meaning, no per-provider retry dialects (20-integrations.md NFR-14).
- Concurrency ceilings: `max_inflight_llm_calls` (default **8**) and `max_inflight_render_jobs` (default **8**) — these exist to respect **provider account concurrency limits**, not to slow the engine deliberately. Set them at or under whatever your OpenRouter/Kie.ai account allows (Kie's default account limit is ~20 new tasks per 10 s, and Kie **rejects** the excess with 429 rather than queueing — the engine's bounded backoff absorbs occasional 429s, but a ceiling set above the account limit converts every burst into retry churn). The render permit is held per submitted job, never across a dependency wait (10-pipeline FR-25's deadlock rule).

**Prompt templates (D24)**
- All model-facing prompt scaffolds live as editable plain-text template files in `prompts/` (style brief, copywriter, image/carousel/reel scaffolds, vision-check question) — hot-loaded per run, tunable without code changes; a missing or corrupt template falls back to the built-in default with a logged warning. Template contract, placeholders, and per-model playbooks are specified in `50-promptcraft.md`.
- When the active config sets `prompts_dir` (D27, v1.6.1), template resolution checks that folder first, falls back to the global `prompts/` folder, then to the built-in default — the same missing-template warning applies at each fallback step. Exact resolution order specified in `50-promptcraft.md`.

**Secrets handling (D30)**
- API keys live **only** in `.env` (or real process environment variables) — never in a config YAML file, never committed, never hardcoded.
- **A config YAML never contains a secret in any form — including a placeholder form.** There is no `${VAR}` interpolation feature in config loading, and none is planned: the loader reads YAML literally, so a `${NOTION_TOKEN}` written into a config file would be passed through as that literal string of characters, not expanded into a key. The absence of the feature is the guarantee — an operator cannot half-implement the leak by copying a pattern that "usually works".
- **Per-server MCP `env` dictionaries are constructed by engine code at spawn time**, reading the named variables directly from the loaded `.env`/process environment and handing them to the subprocess. The config file declares only *which* server needs *which* variable name (the stdio server's identity, or an HTTP entry's `auth_env`); the value is joined to the name in memory, in code, at launch — never on disk.
- Keys are **never interpolated into any LLM prompt or template**: the prompt-template contract (D24, above; `50-promptcraft.md`) has no placeholder that can resolve to a secret, so there is no template path that could leak one even by operator error.
- Keys are **redacted from both log files** — `run.log` and `events.jsonl` capture full prompts and payload summaries (§Output below, `log_verbosity`), so Authorization headers and any key-shaped value are stripped at the logging boundary before a line is ever written (40-outputs-and-logging.md owns the redaction detail).
- Keys flow into exactly two places at runtime: HTTP `Authorization`/API-key headers for the OpenRouter and Kie.ai REST calls, and the per-server `env` map passed to stdio MCP servers (Virlo, Notion) or the `auth_env`-named variable for HTTP-transport MCP servers (§Integrations above, 20-integrations.md).

**Output**
- Output directory root (default `output/`).
- Gallery options: **`gallery.title` only.** Grouping and an A/B display toggle were considered and cut — A/B side-by-side is automatic whenever `both` mode ran, paired by the shared `pair_id` in each variant's metadata, so there is nothing left to toggle.
- Log verbosity: **`normal` or `verbose` only** — no `debug` level, no `debug/` folder. `verbose` adds full prompt text and raw API payload summaries to `events.jsonl`; `run.log` always carries one-line digests regardless of verbosity (40-outputs-and-logging.md).

**Publishing (Phase 2, D29)**
- Config gains a `postiz:` section — a pointer, not a full spec: a channel map (which Postiz channel each platform's assets publish to), schedule slots (e.g. the next free 09:00/18:00 per platform), and `auto_publish` (default **off** — the operator approves in the Postiz UI unless explicitly turned on). The authoritative shape of `postiz:` is owned by `60-publishing-postiz.md`; this file only establishes that the key exists and where it plugs in.
- This is distinct from the `postiz` entry already sketched under `mcp_servers` above (transport/auth for the MCP connection itself) — `postiz:` here is publish-behavior config, `mcp_servers.postiz` is connection config.
- MVP ships without any of this wired up; the section can be present in a config file and stays unused until the Phase 2 build lands (see §5 CLI Flags and §4 Interactive Menu for the `--publish` placeholder).

**FR-50** The engine SHALL load run configuration from exactly one source per run — a named YAML file in `configs/` (a niche's config is an ordinary such file, v1.6.1) — applying documented defaults for any key absent from that file.

**FR-51** The engine SHALL expose every setting in this section as a config key with a documented default value, requiring no code change to adjust any of them — with the sole intentional exception of trend-ranking weights, which are hardcoded in 10-pipeline.md's Select stage, not configurable.

**FR-52** Aspect ratio, caption length, tone, and hashtag-count conventions SHALL be treated purely as prompt guidance and SHALL NOT block, retry, or reject a generated creative.

**FR-130** The `mcp_servers` config block SHALL be the sole PRD-wide sketch of MCP server configuration, supporting stdio entries (launch command, plus the names of the environment variables that server needs) and HTTP entries (URL plus `auth_env`); the Postiz entry is streamable-HTTP, optional, and ops-query only (20-integrations.md §6, 60-publishing-postiz.md). Per-server `env` dictionaries SHALL be assembled by engine code from the environment at spawn time and SHALL NOT appear, in value or placeholder form, in any config file.

**FR-131** The cost estimator SHALL refuse to include any reel in the run plan while `price_per_unit.reel_second` for the run's configured `reel_resolution` is unset, and SHALL name that exact key rather than assuming a price. Both `reel_second` entries SHALL ship unset in `configs/default.yaml`, since Seedance pricing is unpublished (OQ-2).

**FR-132** Each platform SHALL declare an explicit formats allowlist (`platforms.<name>.formats`); a requested format outside a platform's allowlist SHALL be dropped from the plan with a logged reason instead of being generated or erroring the run.

**FR-133** `media_download_cap`, `reference_images_per_job`, `max_trend_reuses_per_run`, `carousel_anchor`, `platforms.<name>.carousel_slides`, `reel_overlay_text`, `require_reference_image`, `onimage_text_language`, `text_budgets`, `run_deadline_min`, `image_job_timeout_s`, `video_job_timeout_s`, `poll_interval_s`, `mcp_startup_timeout_s`, `mcp_call_timeout_s`, `http_max_attempts`, `briefs_dir`, `prompts_dir`, `max_inflight_llm_calls` (default 8), and `max_inflight_render_jobs` (default 8) SHALL each be exposed as a documented, independently overridable config key, at the defaults stated in Section 2 (`image_quality_tier` was removed in v1.6.1).

**FR-134** Gallery configuration SHALL expose only `gallery.title`; grouping and A/B display SHALL NOT be config keys — A/B pairing SHALL be automatic and driven by `pair_id`. Log verbosity SHALL accept only `normal` or `verbose`.

**FR-170** `reel_audio`, `reel_video_reference`, `reel_reference_max_s`, `reel_duration_s`, `reel_resolution`, `nsfw_checker`, `inspiration_mix`, and `reasoning_effort` (copywriting role) SHALL each be exposed as documented, independently overridable config keys, defaulting per D22/D23 and Section 2 — no code change required to adjust any of them.

**FR-171** The engine SHALL accept campaign-brief requests via the repeatable CLI flag `--brief <name>:<count>` and via the menu's Briefs step, and SHALL fold every resulting brief-driven creative into the run plan and pre-flight cost estimate identically to a trend-driven creative of the same format (D26).

**FR-172** A brief file SHALL define a name, a one-line description, its applicable format(s), an influence mode of `override` or `blend`, copy directives, visual directives, and optional reference image paths; a requested brief that is missing or fails this shape SHALL produce one pre-flight error naming the exact brief file, before any billable call — halting the run interactively, and dropping only that brief's creatives under `--yes` (FR-252).

**FR-173** *(simplified v1.6.1)* The config/menu picker SHALL list the YAML files in `configs/`, showing each file's line-1 description — or its `niche:` descriptor line when one exists. There is no separate niche-pack entry type; selecting a niche's config activates everything it points at (`niche:` block, `sources.inspiration_folders`, `briefs_dir`, `prompts_dir`) because those are ordinary config keys (D27).

**FR-174** Prompt-template resolution SHALL check the active config's `prompts_dir` (when set) before the global `prompts/` folder before the built-in default, applying the existing missing/corrupt-template fallback and logging at each step; the full resolution order is authoritative in `50-promptcraft.md`.

**FR-175** The CLI SHALL accept `--publish <run_id>` (including the literal value `latest`) and the menu SHALL offer a "Publish a finished run" action; both SHALL be Phase 2 placeholders in MVP — invoking either SHALL report clearly that publishing is not yet implemented and exit without error, deferring the full flow to `60-publishing-postiz.md`.

**FR-176** Config SHALL expose a `postiz:` section (channel map, schedule slots, `auto_publish` defaulting to off) as a configuration pointer only, distinct from the `mcp_servers.postiz` connection entry; its authoritative shape and behavior are owned by `60-publishing-postiz.md`.

**FR-177** API keys SHALL never be interpolated into any LLM prompt, template, or model-facing payload, and SHALL be redacted from `run.log` and `events.jsonl` at the logging boundary; keys SHALL flow only into HTTP `Authorization`/API-key headers and per-server MCP `env` maps.

**FR-257** `platforms.<name>.carousel_slides` (default **5**) SHALL be the single PRD-wide config key expressing carousel slide count, serving as both the per-deck generation ceiling (10-pipeline.md FR-95) and the slide count used by the pre-flight estimate (10-pipeline.md FR-107); a source trend's panel count MAY reduce a deck below this value and SHALL NEVER raise it above. For Instagram the value SHOULD remain within 2–10 (60-publishing-postiz.md FR-221).

**FR-258** `price_per_unit` SHALL be structured as per-model LLM token rates (`llm.sonnet.input_per_mtok`/`output_per_mtok`; `llm.luna.input_per_mtok`/`output_per_mtok`/`reasoning_per_mtok` — shipped at OpenRouter's published 2026-08-09 rates), image prices keyed by resolution tier (`image.1k`, `image.2k`, `image.4k`), and reel prices keyed by resolution as a per-second rate (`reel_second.480p`, `reel_second.720p`); the shipped `configs/default.yaml` SHALL leave both `reel_second` values unset with an inline comment naming OQ-2 as the reason. The `reel_second` scalars are **worst-case-honest per-output-second rates derived by the operator from Kie's measured `(input + output) × resolution` billing** (v1.6.6; formula and rationale in Section 2), never provider list prices.

**FR-259** `poll_interval_s` (3), `mcp_startup_timeout_s` (20), `mcp_call_timeout_s` (30), `http_max_attempts` (3), `virlo_session_pool` (3 — the bounded pool of Virlo wrapper sessions for Collect-stage concurrency, 20-integrations.md FR-246), `reel_reference_max_s` (28), and `text_budgets` (`image_headline` 42, `image_subline` 60, `reel_seed_headline` 32, `retry_reduction_pct` 40) SHALL each be exposed as documented config keys at those defaults; `video_job_timeout_s` SHALL default to **300** and `run_deadline_min` to **25**. `http_max_attempts` SHALL govern every bounded-retry path in the engine. (`image_quality_tier` removed v1.6.1 — OQ-7 closed with no tiers exposed.)

**FR-280** Every model the engine calls SHALL be selected by a plain config string, and `models.analysis` (default `anthropic/claude-sonnet-5`), `models.copy` (default `openai/gpt-5.6-luna`), `models.image` (default `gpt-image-2-image-to-image` — the reference-bearing route; the profile routes reference-free jobs to `gpt-image-2-text-to-image`, 20-integrations FR-241) and `models.video` (default `bytedance/seedance-2-5`) SHALL be the sole PRD-wide names for those four settings. Replacing any of them with another model served by the same model profile SHALL require a config edit only — no code change, no prompt-template change, and no change to any other config key, including the profile keys and `price_per_unit` (D34).

**FR-281** `models.image_profile` (default `gpt-image-2`) and `models.video_profile` (default `seedance-2-5`) SHALL name the model profile (20-integrations.md FR-272) that interprets the configured render model — its parameter mapping, reference-input limits, and prompt-template set. A profile the engine does not implement, or a model/profile pair it cannot resolve, SHALL produce a pre-flight refusal exiting with code `2` and naming what is missing (the profile, its template set, or both) together with the key that selected it, before any billable call. A swap within an already-shipped profile SHALL NOT require either key to change.

**FR-282** `price_per_unit` values SHALL be treated as belonging to the model configured when they were entered, and SHALL NOT be cleared, renamed, or auto-adjusted when a model is swapped; the estimator SHALL continue using the values present in config. The pre-flight cost summary SHALL print, for every priced line, which configured model that price is being assumed for, so a swapped model carrying stale prices is visible before confirmation rather than silently mis-estimated. Unset or zero rates SHALL continue to print as *unpriced*, and reels SHALL continue to refuse planning while `price_per_unit.reel_second` for the configured resolution is unset (FR-131, FR-258).

### Illustrative config sketch (minimal, non-normative)

```yaml
run:
  formats: { image: 4, carousel: 2, reel: 0 }   # reels ship OFF by default: raise after entering price_per_unit.reel_second (FR-131)
  platforms: [linkedin, instagram, tiktok]
  languages: { linkedin: en, instagram: en, tiktok: en }   # all-EN default (operator decision); cs is one edit away
  generation_mode: analyzed        # analyzed | direct | both
  notion_influence: off            # off | copy | full
  vision_check: false              # cs platforms get a startup hint to enable this
  spend_cap_usd: 10.00             # operator default (2026-08-09); roomy enough for a full batch incl. reels
  trend_history_days: 7
  max_trend_reuses_per_run: 2
  carousel_anchor: true
  reel_overlay_text: seed_frame    # seed_frame | in_model | none
  reel_audio: true                 # Seedance generate_audio; false = silent clip
  reel_video_reference: true       # yt-dlp -> Kie upload -> Seedance reference; degrades on failure
  reel_reference_max_s: 28         # motion-reference duration bound (full tier <=30s, OQ-6 closed)
  reel_duration_s: 5               # 4-30 (Seedance verified range), clamped at pre-flight if out of range
  reel_resolution: 720p            # 480p | 720p (480p = cheap test option)
  nsfw_checker: true                # engine default true, explicitly sent (provider's own default is false)
  require_reference_image: true
  onimage_text_language: {}        # per-platform override, else platform language
  text_budgets:                    # on-image character ceilings, enforced before submission
    image_headline: 42
    image_subline: 60
    reel_seed_headline: 32
    retry_reduction_pct: 40        # cut budgets by this % on a vision-check retry
  run_deadline_min: 25             # soft elapsed-time ceiling (monotonic clock); sized for the worst realistic reel path
sources:
  active: [virlo]                  # google_trends, hacker_news: named, not built yet
  virlo_monitor_ids: ["mon_123", "mon_456"]
  media_download_cap: 6            # per trend, images only; the D23 video reference is bounded separately (1 per reel)
  reference_images_per_job: 3
  inspiration_folders: []          # flat global list of local folders (D13)
  inspiration_mix: minority        # off | minority | exclusive — how inspiration images join render references
platforms:
  linkedin:  { formats: [image, carousel], carousel_slides: 5 }
  instagram: { formats: [image, carousel], carousel_slides: 5 }   # keep within Instagram's own 2-10
  tiktok:    { formats: [image, carousel, reel], carousel_slides: 5 }   # reels default to TikTok only
models:
  analysis: anthropic/claude-sonnet-5       # OpenRouter chat id
  copy: openai/gpt-5.6-luna                 # OpenRouter chat id; reasoning model
  image: gpt-image-2-image-to-image         # Kie job route, reference-bearing (input_urls <=16); profile falls back to
                                            #   gpt-image-2-text-to-image for reference-free jobs (OQ-17 closed)
  video: bytedance/seedance-2-5             # Kie job route; price_per_unit.reel_second required before reels plan
  # Profiles change ONLY when you switch model FAMILY (e.g. Seedance -> Kling).
  # A same-family swap is just the line above; leave these alone. Unknown profile = pre-flight refusal (exit 2).
  image_profile: gpt-image-2                # param mapping + reference limits + prompts/ set (20-integrations FR-272)
  video_profile: seedance-2-5
  reasoning_effort: low             # models.copy role only; Luna is a reasoning model
  temperature: { analysis: 0.4, copy: 0.8 }
  max_tokens: { analysis: 2000, copy: 3000 }   # sized for the grouped FR-99 copy call and FR-92's full brief; too-small caps just buy truncation retries
  price_per_unit:                    # estimator inputs only, never billing-authoritative
                                     # these belong to the models named above; a swap leaves them untouched
                                     # and the pre-flight prints which model each price is assumed for (FR-282)
    llm:                             # per-million-token rates, from OpenRouter's price page 2026-08-09; re-verify periodically
      sonnet: { input_per_mtok: 2.00, output_per_mtok: 10.00 }
      luna:   { input_per_mtok: 0.10, output_per_mtok: 0.60, reasoning_per_mtok: 0.60 }   # reasoning bills at the output rate
    image: { 1k: 0.03, 2k: 0.05, 4k: 0.08 }    # per resolution tier; 2k/4k third-party corroborated, verify at build
    reel_second:
      480p: null                     # UNSET ON PURPOSE: Seedance 2.5 pricing is unpublished (OQ-2).
      720p: null                     # Reels are not planned until a real number is entered (FR-131).
  image_job_timeout_s: 180
  video_job_timeout_s: 300           # lowered from 600 so one stuck reel can't eat run_deadline_min
  poll_interval_s: 3                 # gap between Kie recordInfo polls
  http_max_attempts: 3               # every bounded-retry path: OpenRouter, Kie, Virlo, Postiz
  max_inflight_llm_calls: 8
  max_inflight_render_jobs: 8
mcp_servers:
  # No secrets here, in any form: the engine builds each server's env dict from .env at spawn time.
  # There is no ${VAR} interpolation in config loading, so a placeholder would stay a literal string.
  mcp_startup_timeout_s: 20
  mcp_call_timeout_s: 30
  virlo: { transport: stdio, command: "python -m hypesocials.virlo_mcp" }
  notion: { transport: stdio, command: "npx -y @notionhq/notion-mcp-server" }
  postiz: { transport: streamable_http, url: "", auth_env: POSTIZ_API_KEY }   # optional, ops-query only (20-integrations §6)
output:
  dir: output/
  gallery: { title: "HypeSocials Run" }
  log_verbosity: normal              # normal | verbose
```

## 3. run.bat

`run.bat` is the single entry point on the Windows workstation:

1. Checks for a Python virtual environment in the repo (creates and installs dependencies on first run if missing — bootstrap is idempotent, safe to run repeatedly) and verifies the active interpreter meets the minimum Python version required by D5; a mismatch is reported plainly and the run does not start (see FR-138).
2. **Switches the console to UTF-8 before launching anything** — `chcp 65001` for the console code page plus `PYTHONIOENCODING=utf-8` for the Python process. Czech is a first-class language here (D6), and the Windows default code page mangles diacritics: without this step a `ě` or `ř` in a hook line either prints as mojibake or raises an encoding error mid-run and takes the run down with it.
3. Activates the venv and launches `python -m hypesocials`, passing through every argument the user or scheduler supplied unchanged.
4. On exit — success, error, or user cancel — pauses (`pause` / "press any key to continue") so the console window stays open and readable when launched by double-click — **but only on interactive runs.** When `--yes` is among the forwarded arguments, `run.bat` exits immediately with the engine's exit code: a paused console under Task Scheduler would hang every scheduled run forever, never surface the exit code, and make overlapping-run collisions (FR-254) the norm.

**FR-53** `run.bat` SHALL bootstrap a Python virtual environment automatically on first run if one does not already exist, and SHALL reuse it on subsequent runs without reinstalling dependencies unnecessarily.

**FR-54** `run.bat` SHALL forward all command-line arguments it receives to the Python entry point unmodified.

**FR-55** `run.bat` SHALL pause before closing the console window on every **interactive** exit path (no `--yes` present), so double-click launches remain readable; when `--yes` is present it SHALL exit immediately, propagating the engine's exit code, so scheduled runs never hang on a pause.

**FR-256** `run.bat` SHALL set the console code page to UTF-8 (`chcp 65001`) and export `PYTHONIOENCODING=utf-8` before launching the engine, and every file the engine writes — `run.log`, `events.jsonl`, `caption.txt`, `meta`, `gallery.html`, `logs/trend_history.json` — SHALL be opened with an explicit UTF-8 encoding rather than the platform default. Czech captions, hooks, and on-image text SHALL never raise an encoding error, truncate, or produce mojibake in a console line or an on-disk file.

## 4. Interactive Menu

Exactly as decided in D8, refined by D19/D20/D26/D27/D29. When the engine starts without `--yes` and without `--publish`, it first offers a one-key action choice — **Start a new run** (default, continues below) or **Publish a finished run** (D29) — then, for the default path, shows a short, fixed sequence of numbered prompts:

1. **Config picker** — lists every `*.yaml` file in `configs/` with its line-1 description (a niche's config shows its `niche:` descriptor line instead, §Niches). Operator picks by number; the chosen file becomes the base for every pre-fill below (D27, v1.6.1 — no separate pack entries).
2. **Source picker** — lists every source in `sources.active` plus any named-but-unimplemented adapter (Google Trends, Hacker News — D20), the latter clearly marked *not yet implemented*. Enter accepts the config's current `sources.active`.
3. **Formats & counts** — one grouped prompt showing current formats/counts as a single pre-filled line (e.g. `images=4 carousels=2 reels=2`); the operator edits the whole line or presses Enter to keep it.
4. **Spend cap** — current value from config, Enter to keep or type a new number.
5. **Mode & Notion influence** — one grouped prompt for generation mode (analyzed/direct/both) and Notion influence level (off/copy/full), both pre-filled, Enter to keep both.
6. **Briefs** — optional; pick brief name(s) and a count each (e.g. `ai-audit-cta:2`) from the active config's `briefs_dir` (D26). Blank/Enter = none, the default for most runs — this step never blocks progress.
7. **Confirm** — after the pre-flight cost estimate (below) is shown, a final yes/no. "No" exits cleanly with no API calls made.

**Platforms are deliberately not a menu question.** Platform selection is a config-file decision (Section 2) with a CLI override (`--platforms`, Section 5) for one-off runs — kept out of the interactive path because it rarely changes run-to-run, and an extra grouped prompt would break the "roughly seven inputs" promise below.

**Publishing a finished run is a separate menu action, not part of this sequence.** Selecting "Publish a finished run" from the entry-point action choice bypasses steps 1–7 entirely and goes straight to run selection (`run_id` or `latest`); in MVP it is a Phase 2 placeholder that reports publishing isn't implemented yet and exits (D29, `60-publishing-postiz.md`).

**Pre-flight, before the confirm prompt:**
- The **cost estimate** is computed and displayed (D11): image/carousel/reel unit prices × counts plus an LLM cost estimate for analysis and copywriting, including conditional contributors (vision-check calls, seed frames, retry allowance) — brief-driven creatives (D26) are folded into these counts identically to trend-driven ones, at the same per-format unit price.
- The engine validates: the active Python version (run.bat's own check, D5); Node's presence, **only** if a configured MCP server command uses `npx`/`node` (`yt-dlp` is a Python package bundled in the venv, D23 — it never triggers a Node check); that `price_per_unit.reel_second.<reel_resolution>` is set **if** reels were requested (Section 2, FR-131); that `models.image_profile` and `models.video_profile` name profiles the engine actually implements and that the configured render models resolve against them (FR-281); that `reel_duration_s` sits within **4–30**, clamping and logging a warning rather than refusing when it doesn't; that every requested brief resolves to a valid file (Section 2 §Campaign briefs, FR-172); and that the spend cap clears the minimum single-creative cost floor (Section 8).

Navigation rules: every choice is a number key or a bare Enter to accept the pre-filled default — never free-text requiring exact spelling. The entire menu is skippable in one shot via `--yes` (Section 5).

**One honesty rule after the confirm:** Collect and Select run *after* the confirmation, and trend supply can shrink the plan (10-pipeline FR-8's ceiling of `usable_trends × max_trend_reuses_per_run`). When that happens in an interactive run, the console shows a one-line restatement — final creative count and revised estimate — before generation proceeds, so the operator never confirms 8 creatives and silently receives 5. Under `--yes` the shrink is logged and reported in the summary (FR-252).

**FR-56** *(simplified v1.6.1)* The interactive menu SHALL present a config picker listing all YAML files in `configs/` with their line-1 descriptions (a config with a `niche:` block shows that descriptor line instead), before any other prompt. There is no separate niche-pack listing (FR-173).

**FR-57** Each per-run override prompt SHALL display the value currently in effect from the chosen config and SHALL accept a bare Enter to keep that value.

**FR-58** The menu SHALL display a computed pre-flight cost estimate before the final confirmation prompt, and SHALL NOT make any billable API call prior to confirmation.

**FR-59** Declining the final confirmation prompt SHALL exit the run with no MCP or REST calls made and no output written.

**FR-60** The `--yes` flag SHALL suppress the entire interactive menu and proceed directly to the collect stage using config values as overridden by any other CLI flags supplied, resolving every would-be prompt per FR-252.

**FR-135** The interactive menu SHALL present a source picker, populated from `sources.active` plus any named-but-unimplemented adapters, immediately after the config picker; selecting an unimplemented adapter SHALL be rejected with a clear message rather than silently accepted.

**FR-136** The menu SHALL present formats and their counts as a single grouped prompt, editable as one line, rather than one prompt per format.

**FR-137** Platform selection SHALL NOT appear as an interactive menu prompt; it SHALL remain reachable only via the config file or the `--platforms` CLI flag.

**FR-138** Pre-flight SHALL validate, before the confirm prompt and before any billable call: the Python interpreter version, Node/npx availability when required by a configured MCP server command (`yt-dlp` never counts toward this check — it installs as a Python dependency, no separate Node requirement), presence of `price_per_unit.reel_second` for the configured resolution when reels are requested, `reel_duration_s` clamped into the 4–30 range with a logged warning if it was out of bounds, sufficient disk space inside `output.dir` for the estimated run footprint (FR-255), and that the spend cap is at or above the minimum single-creative cost derived from `models.price_per_unit`.

## 5. CLI Flags

All flags override the loaded config for that run only (they never rewrite the config file). The menu is shown only when `--yes` is absent; when any other flag is supplied without `--yes`, the menu still runs but pre-fills from the flag values instead of the raw config, so the operator sees and can adjust exactly what will be used. Four flags are standalone actions that never show the menu at all and never start a run: `--list-monitors`, `--preview-sources`, `--preview-analysis`, and `--publish`.

| Flag | Effect |
|---|---|
| `--config <name>` | Selects the config file from `configs/` (skips the config-picker menu step). |
| ~~`--niche <name>`~~ | **Removed (v1.6.1)** — a niche is an ordinary config file, so `--config <name>` covers it (FR-250 tombstone). |
| `--list-monitors` | Connects to Virlo through the MCP wrapper's `list_monitors` tool, prints every monitor's id and name, and exits. Zero billable calls, no run folder, no generation — a setup utility (FR-251). |
| `--images N` | Overrides image count. |
| `--carousels N` | Overrides carousel count. |
| `--reels N` | Overrides reel count. (The CLI keeps counts as separate flags even though the menu groups them into one prompt, FR-136.) |
| `--platforms <list>` | Overrides the platform list (comma-separated) — CLI-only, no menu equivalent (FR-137). |
| `--budget X` | Overrides the spend cap in dollars. |
| `--mode <analyzed|direct|both>` | Overrides generation mode. |
| `--notion <off|copy|full>` | Overrides Notion influence level. |
| `--vision-check` | Enables the optional vision-check pass (D3). |
| `--brief <name>:<count>` | Requests a named campaign brief with a creative count; repeatable for multiple briefs (e.g. `--brief ai-audit-cta:2 --brief customer-story:1`). Folds into the plan and pre-flight estimate like any other creative; a missing/malformed brief is a pre-flight error naming the file (D26, FR-171/FR-172). |
| `--yes` | Skips the interactive menu entirely; run starts immediately after the pre-flight estimate is logged (not shown interactively, but still computed and still enforced against the spend cap). Every decision the menu would have raised resolves to a documented non-blocking outcome — see FR-252. |
| `--preview-sources` | Runs Collect **and Select's filters**, then prints every trend with the verdict a paid run would reach — `eligible`, `excluded (history, last used <date>)`, or `unusable (<reason>)` — and exits. Zero billable calls, zero yt-dlp downloads, zero Kie uploads (D19, FR-139). |
| `--preview-analysis` | Runs Collect → Select → Analyze → Write, then prints the resulting style briefs and drafted copy for inspection, and exits. Spends only analysis/copywriting LLM cost — no image or reel generation, no Kie.ai spend (D19). |
| `--publish <run_id>` (or `--publish latest`) | **Phase 2 placeholder.** Intended to push a finished run's assets to Postiz as drafts (D29, `60-publishing-postiz.md`). Not built in MVP — prints that publishing isn't implemented yet and exits cleanly, making no billable call. |
| `--promote <run_id>` | **Phase 2.** Flips already-created Postiz drafts from that run into Postiz's schedule queue, at the next free configured schedule slot per platform unless `--at <ISO datetime>` supplies an explicit time. Deliberately a separate command, never a side effect of `--publish`. Behavior owned by `60-publishing-postiz.md` (FR-218); MVP treats it as the same honest placeholder as `--publish`. |
| `--at <ISO datetime>` | **Phase 2.** Optional explicit schedule time for `--promote`; without it, promote computes the next free configured slot (60-publishing FR-218/FR-219). |
| ~~`--assets <filter>`~~ | **Removed (v1.6.1)** — the `SELECTED.marker`/`publish.txt` selection is the filter (60-publishing FR-211). |
| ~~`--force`~~ | **Removed (v1.6.1)** — re-publish deliberately by deleting the asset's `PUBLISHED.marker` (60-publishing FR-227). |

**FR-61** Every CLI flag SHALL take precedence over the corresponding config value for the current run only; the underlying config file SHALL remain unmodified.

**FR-62 — removed** (the single `--dry-run` flag conflated two different questions; superseded by `--preview-sources` and `--preview-analysis`, D19 — see FR-139, FR-140).

**FR-63** An unrecognized flag SHALL cause the engine to exit immediately with a one-line error naming the unknown flag, before any config load or API call.

**FR-64** When a flag and a config value conflict (e.g. `--mode direct` with `notion_influence: full` in config, which is harmless, versus `--images 0 --carousels 0 --reels 0` combined with a config that also nets zero creatives), the engine SHALL apply flags over config per FR-61 and, if the resulting plan requests zero total creatives, SHALL exit with a one-line explanation rather than starting an empty run.

**FR-139** `--preview-sources` SHALL execute the Collect stage **and Select's filtering pass** against the currently active source(s), and SHALL display every returned trend labelled with the verdict a paid run would reach: `eligible`, `excluded (history, last used <date>)`, or `unusable (<reason>)` — where a reason is a concrete disqualifier such as no usable reference media under `require_reference_image`, or a format the plan does not request. Preview must show what a paid run would actually *use*, not merely what the source returned; an operator who previews ten trends and gets three creatives should have seen exactly which seven were going to fall away and why. It SHALL make zero LLM or render calls, perform **no yt-dlp video download** and **no Kie file upload**, and SHALL NOT run ranking-dependent assignment beyond what the labels require. (Virlo API calls themselves may carry metered cost against the operator's Virlo deposit — OQ-19; "free"/"$0" claims about this mode read precisely as "zero model spend".)

**FR-140** `--preview-analysis` SHALL execute Collect, Select, Analyze and Write, display the resulting style briefs and copy, and exit before any image or video generation call — spending only LLM cost.

**FR-253** Both preview modes SHALL write a **log-only run folder** — a normal `run_id` folder containing `run.log` and `events.jsonl` and nothing else — and SHALL NOT repoint `output/latest` under any circumstances. `output/latest` is the target `--publish latest` resolves against (60-publishing-postiz.md FR-210); a free look must never silently become the thing a later publish command picks up.

**FR-250 — removed (v1.6.1):** `--niche` is withdrawn along with the niche-pack machinery; `--config <name>` selects a niche's config like any other, and the `--config`/`--niche` mutual-exclusion rule disappears with it.

**FR-251** The CLI SHALL accept `--list-monitors`, which opens a Virlo MCP session, calls the wrapper's `list_monitors` tool (20-integrations.md §3), prints each monitor's id and name, and exits — making no billable call, creating no run folder, and requiring no valid run plan or spend cap.

**FR-252** Every decision point that the interactive menu would raise SHALL have a defined, non-blocking outcome under `--yes`, so an unattended run never waits on a human and never silently produces less than it reports:

| Situation | `--yes` outcome |
|---|---|
| Estimate exceeds the spend cap | The plan is **auto-trimmed to fit the cap** using 10-pipeline.md's deterministic trim order (never a random or count-order drop). What was trimmed, and the pre- and post-trim estimates, are written to `run.log` and repeated in the end-of-run spend summary. |
| `price_per_unit.reel_second` unset for the configured resolution | The run **proceeds without reels**; every requested reel is dropped as a logged warning naming the missing key (FR-131). Images and carousels still run. |
| `reel_duration_s` out of range, or any similar clamp | Clamped to the documented range, logged as a warning, run proceeds (FR-138). |
| A requested brief fails to resolve | **That brief's creatives are dropped**, one logged error naming the brief file; the rest of the plan runs. (Interactively this is a pre-flight refusal — unattended, one bad brief must not cost a whole scheduled batch.) |
| Any other menu prompt | Uses the config value as overridden by CLI flags; no prompt is ever emitted. |

A trimmed, reduced, or partially-dropped unattended run is a **partial success** and exits with the partial-success code (Section 6) — never a silent full-success exit.

## 6. Scheduling

HypeSocials ships no built-in scheduler (D8, D12). Recurring or unattended runs are configured entirely through **Windows Task Scheduler**, which is pointed at `run.bat` with a fixed argument line, always including `--yes` so no interactive prompt blocks the scheduled task. A typical scheduled action looks like: `run.bat --config czech-ig.yaml --budget 5 --yes`, or, for a niche, `run.bat --config hypedigitaly.yaml --budget 5 --yes` (v1.6.1 — a niche is just a config). Because every menu-level decision has a corresponding CLI flag (Section 5), any interactive run can be turned into a scheduled run by copying its final flag combination into a Task Scheduler action.

**What the exit code means.** A scheduled task's only feedback channel is the process exit code, so the engine's codes are stable and meaningful. They are defined in 10-pipeline.md and repeated here for the operator setting up the Task Scheduler action:

| Code | Meaning | Typical Task Scheduler response |
|---|---|---|
| `0` | Full success — every planned creative produced output. | None. |
| `1` | Partial success — some creatives were skipped, trimmed, or dropped; the rest shipped. | None automatic; read the spend summary. |
| `2` | Pre-flight refusal or config error — including a missing API key. Nothing was generated, nothing was spent. | Fix the config, flags, or `.env`; retrying unchanged will fail identically. |
| `3` | Fatal after Collect began — zero usable trends (for a trend-dependent plan) or a transport-dead source. No LLM/render spend occurred. | Investigate; a retry may succeed (trends change hour to hour). |
| `4` | Interrupted (Ctrl-C, shutdown). | Safe to rerun — a fresh `run_id` is assigned and there is no partial state to reconcile. |

**Concurrent runs and shared state.** Each run is assigned its own `run_id` (`YYYYMMDD_HHMMSS_<4-char-random>` — see 40-outputs-and-logging.md) the moment it starts, so two scheduled runs with identical parameters, even triggered in the same second, still get distinct run folders. **Output folders do not collide — but two things outside them are genuinely shared, mutable, and can:** `logs/trend_history.json` (global, read at Select and rewritten at Package) and the `output/latest.txt` pointer (updated at Package). Both are written by every run that finishes, so two overlapping scheduled runs *can* collide on them, and the rules below are what make that collision harmless. Distinct `run_id`s solve the output-folder problem only — they say nothing about these two shared files.

- **Every write to `logs/trend_history.json` and the latest-pointer is atomic** — write a temp file in the same directory, then rename over the target. A run interrupted mid-write leaves the previous good file intact; a torn or half-written trend history is never possible.
- **The canonical latest-pointer is a file, not a link: `output/latest.txt`**, one line containing the `run_id`, written by temp+rename (truly atomic on Windows — a directory junction cannot be renamed over, so a junction-only design would have a delete-then-create window in which `--publish latest` resolves to nothing). The `output/latest/` junction is still created **best-effort as a human convenience** for Explorer navigation; every programmatic consumer (`--publish latest`, 60-publishing FR-210) resolves `latest.txt`.
- **`logs/trend_history.json` is guarded by an advisory lock file.** A run takes the lock to read-modify-write it. A second run that finds the lock held waits briefly; if the lock does not clear, it **proceeds read-only** — it uses the history it can read for filtering, skips its own history update, and logs one clear warning saying so. A busy lock never blocks or fails a run. **Stale locks break, they don't linger:** the lock file carries the holder's pid and a timestamp, and any lock older than **60 seconds** is treated as stale and removed — otherwise one crashed or hard-killed run would silently disable history updates for every future run, which is the quiet death of repeat-prevention (D12).
- **The latest-pointer is updated only by a run that packaged at least one asset.** A run that produced nothing — pre-flight refusal, zero-creative plan, every creative skipped — and both preview modes (FR-253) leave the pointer where it was, so `--publish latest` always resolves to the newest run that actually has assets.

**FR-65** Every setting reachable through the interactive menu SHALL also be reachable through a CLI flag — including config selection (`--config`, which covers niche configs too, v1.6.1) — so **every** run configuration can be reproduced unattended with no interactive input.

**FR-254** `logs/trend_history.json` and the latest-pointer SHALL be treated as shared mutable state across concurrent runs. The canonical latest-pointer SHALL be `output/latest.txt` (one line, the `run_id`), with the `output/latest/` junction maintained best-effort for human convenience only; every programmatic consumer SHALL resolve `latest.txt`. Every write to either shared file SHALL be performed atomically (temp file in the same directory, then rename). `logs/trend_history.json` SHALL be guarded by an advisory lock file carrying pid + timestamp; a run that cannot acquire the lock within a short wait SHALL proceed read-only for history, skip its own history update, and log one warning, never blocking or failing — and any lock older than 60 seconds SHALL be treated as stale and broken. The latest-pointer SHALL be updated only by a run that packaged at least one asset.

**FR-255** Before any billable call, the engine SHALL perform a disk pre-check by writing and deleting a test file **inside the configured `output.dir`** — not `%TEMP%`, which is frequently on a different drive and therefore proves nothing about where output actually lands — and SHALL compare available free space on that volume against an estimated footprint for the run, derived from the resolved plan and the per-asset size figures in 40-outputs-and-logging.md FR-86. Insufficient space or an unwritable directory SHALL abort with one clear line naming the path, the estimate, and the space available, before any spend. Mid-run disk exhaustion is a separate case, owned by 10-pipeline.md's failure table.

**FR-66** The engine SHALL treat `--yes` as a hard requirement for unattended operation: without it, any run invoked with no attached console input SHALL still attempt to show the menu and SHALL fail with a clear "no interactive terminal available, use --yes" error rather than hang.

## 7. Extensibility — Source Adapters (D14, D20)

Source selection is itself a first-class, config-and-menu choice (D20): `sources.active` names which source(s) feed a given run (default `[virlo]`), and the menu's source picker (Section 4) surfaces the same list plus named future adapters. Virlo and the local Inspiration folder are the two MVP sources, both implemented behind one small source-adapter concept so a future source is additive, not a rewrite:

- **What a new source must provide**: a fetch step returning a list of normalized trend items, each carrying a title/summary, associated text (captions, hooks, panel texts, or article text), engagement or ranking metrics where available, and media references (remote URLs or local paths) that can join the reference-image pool.
- **How it's enabled**: add an entry under `sources` naming the adapter and its adapter-specific settings, then add its name to `sources.active`.
- **Named future adapters**: Google Trends (topic/query-based discovery) and Hacker News (tech-audience trending discussion) — visible in the source picker, explicitly marked not yet implemented, not built in MVP (D14, D20).
- **Model extensibility follows the same principle**: a new image or video model is a config string under `models` plus, when it belongs to a new family, a model profile and its prompt-template set (Section 2 §Models, FR-280/FR-281) — the Generate stage dispatches by config value.
- **Parked future capabilities (D35):** extension chaining (stitching shots into videos longer than 30 seconds) and audio-reference music videos are named future capabilities tied to the render-provider seam — no provider API exposes them today, so they are not configurable now and no config key is reserved for them.

**Design decision (revised, D34):** swapping a model — even across model families — stays a config edit: an id or route string, plus a profile name when the family changes. Adding a whole new *provider* remains a deliberate code change: 20-integrations.md defines a deliberately minimal render-provider seam (submit job → poll → result URLs → file upload) with Kie as the only built implementation, and a second provider is written against that seam, never configured into existence. The seam exists to make a model swap boring and a provider swap possible — not to resurrect the old system's provider-neutral abstraction layers, which cost lines and flexibility they never used.

**FR-67** A new trend/content source SHALL be addable by implementing the source-adapter contract (normalized items: title, text, metrics, media references), registering it under the `sources` config section and adding it to `sources.active`, without modifying the Select, Analyze, or Write stages.

**FR-68 — removed** (provider-abstraction requirement retired; see Design decision above — model swaps stay config-driven, a new provider is a deliberate code change, not a config-only extension point).

## 8. Edge Cases

- **Invalid config value**: the engine prints one line naming the offending key, the value it found, and the expected form (e.g. `spend_cap_usd: "five dollars" — expected a positive number`), then exits before any API call.
- **Unknown CLI flag**: exits immediately with the flag name echoed back, per FR-63, before config is even loaded — the one case with nothing written to disk, since no `run_id` has been assigned yet.
- **Conflicting flags vs config**: flags always win (FR-61); if the resulting combination is self-contradictory or produces a zero-creative plan, the engine explains and exits per FR-64 rather than guessing intent.
- **Spend cap below the minimum single-creative cost**: the engine computes the cheapest possible single creative from `models.price_per_unit` and refuses to start if the cap is below that floor, naming exactly where the number came from (e.g. "spend cap $0.01 is below the minimum single-creative cost of $0.03, derived from models.price_per_unit.image.1k in your config — raise --budget or spend_cap_usd").
- **Reels requested without `price_per_unit.reel_second` configured for the run's resolution**: the estimator refuses to include reels in the plan and names that exact key, rather than estimating with an assumed price (FR-131). This is the shipped default state — Seedance pricing is unpublished (OQ-2) — so it is an expected first-run message, not a fault.
- **Unknown model profile, or a render model no profile can interpret** (e.g. `models.video_profile: kling-2` with no such profile built, or a `models.image` route the configured profile doesn't know how to submit): one pre-flight line naming the key, the value found, and what is missing — a profile implementation, its prompt-template set, or both — then exit code `2`, before any billable call (FR-281). A swap within a profile the engine already ships never reaches this path; this message means a *family* change was attempted without its profile.
- **A model swapped without updating its prices**: not an error and not blocked — the estimate uses the prices in config and states which model each one is assumed for, so the operator sees a stale pairing before confirming (FR-282). Only a genuinely unset reel rate stops planning (FR-131).
- **Kie 402 (insufficient balance) mid-run**: the pre-flight estimate can't catch a provider account that runs dry between submission and completion; when Kie returns 402, all remaining in-flight and not-yet-submitted renders for that run are skipped and logged with a "top up your Kie.ai credits" message, and the run finishes with whatever already completed (transport-level handling detailed in 20-integrations.md).
- **`configs/` empty**: the config picker (menu) or `--config` lookup (CLI) reports that no config files were found and points the operator at `configs/default.yaml` as the file that should exist in a healthy checkout; the run does not start.
- **Missing venv, missing Python, or Python below the required version**: `run.bat` reports the specific failure plainly and pauses so the message is visible; no partial run is attempted.
- **Node/npx missing when a configured MCP server needs it**: caught by the same pre-flight validation pass (FR-138), reported before any spend.
- **Named brief missing or malformed** (`--brief unknown-name:2`, or a brief file missing a required field / using an unrecognized influence mode / naming a format outside `image`/`carousel`/`reel`): one clear pre-flight error naming the exact brief file and what's wrong with it, before any billable call (FR-172) — the same posture as a malformed config value. Under `--yes` the error is logged and only that brief's creatives are dropped, so one stale brief file cannot cost a whole scheduled batch (FR-252).
- ~~`--niche` and `--config` both supplied~~: case removed with `--niche` (v1.6.1, FR-250 tombstone).
- **Not enough disk space for the estimated run footprint**, or `output.dir` unwritable: caught by the pre-check inside `output.dir` itself before any spend, naming the path, the estimated footprint and the free space found (FR-255).
- **A second run finds `logs/trend_history.json` locked**: it waits briefly, then continues read-only — filtering against the history it can read, skipping its own update, logging one warning. Never a failure, never a hang (FR-254).
- **Czech (or any non-ASCII) text in a caption, hook, or trend name**: printed and written as-is under UTF-8 on every path; an encoding error is a defect, not an accepted degradation (FR-256).
- **A niche config's paths point at missing or empty folders** (`briefs_dir`, `prompts_dir`, or an `inspiration_folders` entry that doesn't exist): not an error — the missing contribution is simply absent for that run, logged once at info level; briefs requested from a missing `briefs_dir` fail as unresolvable briefs (FR-172). (v1.6.1 — the old niche-pack validation cases disappeared with the pack machinery.)
- **`--publish` invoked in MVP**: the placeholder reports that publishing isn't implemented yet and points at `60-publishing-postiz.md` for the Phase 2 spec, then exits cleanly with no billable call (FR-175).
- **Run aborted after a `run_id` exists** (malformed config value found mid-load, zero-creative plan, pre-flight refusal, budget-floor failure, Ctrl-C before Collect): the run folder for that `run_id` stays on disk, containing only the log up to the abort point — every invocation that got far enough to have an identity is traceable, even ones that spent nothing. See 40-outputs-and-logging.md for the on-disk record of aborted and interrupted runs; rerunning after any interruption is safe and cheap — a fresh `run_id` is assigned, and the only state outside the run folder (`logs/trend_history.json`, `output/latest`) is written atomically and therefore never left half-updated to reconcile (FR-254).

**FR-69** Every config or flag validation failure SHALL produce exactly one plain-English error line identifying the offending key or flag and the expected form, and SHALL exit before any billable API call is made.

**NFR-15** Config load and validation (file read, default application, single-value checks) SHALL complete in under 200ms so the menu appears near-instantly after launch.

**NFR-16** The interactive menu SHALL require no more than seven operator inputs — config/niche pick, source pick, formats/counts, spend cap, mode/Notion, briefs, confirm — to reach a started run; every input is skippable via Enter except the final confirm, and the briefs step in particular defaults to none and is skipped with a bare Enter.

**NFR-17** All CLI flags SHALL be parseable independent of order and SHALL combine freely with `--yes`, `--preview-sources`, and `--preview-analysis` without special-casing in the parser (the former `--config`/`--niche` exclusivity rule disappeared with `--niche`, v1.6.1).

**NFR-18** The cost estimator SHALL compute the pre-flight estimate using only local config values (no network call), so the estimate appears before any external service is contacted.

**NFR-19** Adding a new config key SHALL never be a breaking change for existing config files: any file predating the new key continues to load successfully using that key's documented default.

## Design Decisions

- **D8 — run.bat → interactive Python menu.** `run.bat` only launches the engine; the menu (config picker → source picker → grouped overrides, all pre-filled from config, Enter accepts) exists so a manual operator can double-check source, scope and spend before any money moves, while full CLI flags give scheduled/unattended runs the exact same control surface with zero prompts. One code path serves both the human and the scheduler — no separate "batch mode" implementation to maintain.
- **D11 — Budget = pre-flight estimate + run cap, enforced at D31's three points.** The spend cap is primarily a **pre-flight control**: config carries per-unit prices purely as estimator inputs, the menu shows the estimate before commit, and an interactive run refuses to start above the cap — while a `--yes` run **auto-trims to fit** instead of refusing (10-pipeline FR-28). Once submission begins, enforcement follows D31/FR-106: the whole-batch expected-cost projection before wave 1, unconditional release of pre-committed wave-2 work, and an atomic per-submission reservation (reconciled to actuals) for the discretionary tail — vision-check re-renders, moderation retries, LLM retries. Seed frames are wave-1 work, not tail. This stays far simpler than the old ledger/balance-reconciliation system: one number and one in-memory reservation float, no persistent accounting.
- **D13 — Inspiration folder = optional local source.** Local folders are just another entry in the sources config, off by default, held as one flat global pool (`sources.inspiration_folders`; the earlier per-platform scoping was dropped as complexity without a consumer), joined into render references per the `inspiration_mix` knob. This lets an operator inject their own curated reference material (images and proven copy) without touching code, keeping the "everything configurable" principle consistent across remote (Virlo) and local sources.
- **D14 — Source adapters for future growth.** Naming Google Trends and Hacker News now, without building them, keeps the config surface (and this PRD) honest about what exists today while making clear the seams are already in place: a new source is a fetch function plus a config entry, not a pipeline rewrite. The same additive pattern extends to models, so both "more trend sources" and "more generation models" are config-only growth paths.
- **D19 — Preview modes instead of `--dry-run`.** A single `--dry-run` flag conflated two very different questions — "what did Virlo actually find?" and "is the analysis/copy any good?" — behind one flag that stopped before either was fully answered. Splitting into `--preview-sources` (free — the raw data *and* the eligibility verdict each trend would get in a paid run, FR-139) and `--preview-analysis` (small LLM cost, the actual creative judgment call) lets an operator sanity-check exactly the thing they're unsure about without ever paying for image or video generation. Neither mode touches `output/latest`, so looking is never mistaken for producing (FR-253).
- **D20 — Source selection is first-class.** Making `sources.active` a config key and a menu step, rather than an implicit "whatever's implemented," keeps the door open for Google Trends and Hacker News without pretending they exist today — the picker shows them, labelled honestly, so the config surface never lies about what a run can actually do.
- **D22/D23 — Reel audio and video-reference default ON.** `reel_audio` (Seedance's native `generate_audio`) and `reel_video_reference` (winning-post video pulled via yt-dlp and passed to Seedance as a motion reference) both default to **true** because maximum visual/motion fidelity to the viral source is the product's whole point — the same "reference images always flow to the image model" backbone from D2, extended to reels. Both are one config boolean each, no new pipeline: `reel_audio` is a single API field, and `reel_video_reference` fails soft — any break in the yt-dlp → Kie-upload → Seedance chain silently degrades that reel to seed-frame-only and is logged, never blocking the run, consistent with the lean "degrade and report, never block" philosophy running through this whole file.
- **D26 — Campaign briefs.** Pure trend-mimicry doesn't cover every post a team needs — a recurring CTA post, a customer story — so a brief lets the operator specify exactly that content once, by name, with an explicit override/blend knob deciding whether the brief replaces the trend entirely or just steers message/CTA on top of the trend's look. Brief-driven creatives ride the same plan, estimate, log, and gallery machinery as trend-driven ones; there is no parallel pipeline to maintain.
- **D27 — Niches are configs, not machinery (simplified v1.6.1).** Once an operator runs more than one niche or brand, everything a niche needs — its `niche:` descriptor, inspiration images, briefs, prompt tweaks — is expressed by ordinary config keys (`sources.inspiration_folders`, `briefs_dir`, `prompts_dir`) inside one ordinary config file, so switching niche is picking a config. Keeping the niche's assets together under one folder is a recommended convention the paths point into, not a separate config shape: same UX as the original pack idea, ~110 fewer lines, one less concept.
- **D29 — Postiz publish flow spec'd now, built later.** `--publish` and the menu's publish action exist as honest placeholders now, mirroring the D14/D20 pattern already used for named-but-unbuilt source adapters, so the config surface and CLI never claim capability this file doesn't have; the full publish behavior is fully specified in `60-publishing-postiz.md` and lands in Phase 2.
- **D34 — Config-swappable models, profiles only for family changes.** Model releases move faster than this PRD does, so every model identifier is a plain config string and a same-family swap costs one line — the alternative, a code edit per model release, would make the engine stale by default. What a swap cannot silently change is *how* a model is addressed: parameter names, reference limits and prompt shape differ per family, so those live in a named model profile and the config says which profile applies. Naming an unknown profile fails at pre-flight rather than mid-run, because a render that dies after the batch is in flight has already cost money, while a refusal before the first call costs nothing. Prices stay attached to whatever the operator typed them for and the estimate says so out loud — the engine will not invent a price for a model nobody has published rates for, and it will not hide that the rates on screen may belong to yesterday's model (FR-280–282).
- **D35 — Product ads are a brief, not a feature.** The most-requested "make it do X" — ads built from the operator's own product photos — needs no engine change at all: a brief in `override` mode with its own reference images is exactly that, so it ships as a worked example in §2 rather than as machinery. Extension chaining and audio-reference music videos genuinely cannot ship today (no provider API exposes them), so they are named as parked capabilities tied to the provider seam and given no config surface — naming an unbuilt capability is honest, configuring one is a lie.
- **D30 — Secrets hygiene is absolute.** Keys are a fixed, small attack surface by design: `.env`-only, never templated into a prompt, always redacted from both log files, flowing only into HTTP auth headers and into MCP `env` dictionaries that engine code assembles at spawn time. Config loading has no `${VAR}` interpolation feature at all, which is the point: a config YAML cannot carry a secret even in placeholder form, so no code path exists in this file's config or menu/CLI layer where a secret could reach a model call, a config file, or an on-disk log line.

## Cross-References

- **10-pipeline.md** — how the resolved run plan (from this file's config/menu/CLI layer) flows through Collect → Select → Analyze → Write → Generate → Check → Package; trend assignment and reuse limits (FR-8); platform default aspect ratios (FR-21); the carousel ceiling that consumes `carousel_slides` (FR-95) and the estimate that prices it (FR-107); the `text_budgets` enforcement point (FR-101); the **deterministic over-budget trim order** and the **exit-code definitions** referenced by FR-252 and Section 6; the mid-run disk-full case; per-stage failure handling; how a config's `niche:` descriptor and a brief's directives (D26/D27) modify the Analyze/Write/Generate stages.
- **20-integrations.md** — behavior once an MCP session from this file's `mcp_servers` config is open (Virlo §3 incl. the `list_monitors` tool behind `--list-monitors`, Notion §5, Postiz §6); OpenRouter/Kie.ai REST auth, polling and bounded-retry behavior governed by `poll_interval_s` and `http_max_attempts`; the render-provider seam and the model profiles (FR-272) that this file's `models.image_profile` / `models.video_profile` keys select; the secrets table.
- **40-outputs-and-logging.md** — how `output.dir`, `gallery.title`, and log verbosity settings from this file's Output config section translate into on-disk artifacts; `run_id` format; the `output/latest` pointer this file's FR-254 constrains; the per-asset size figures FR-255's disk estimate is derived from (FR-86); `pair_id` pairing for both-mode gallery display; the on-disk record of aborted/interrupted runs; secret redaction at the logging boundary (D30).
- **50-promptcraft.md** — the prompt-template override resolution order (config's `prompts_dir` → global `prompts/` → built-in default, D24/D27) and the per-model prompt playbooks referenced by this file's Prompt templates config.
- **60-publishing-postiz.md** — the full `--publish` / menu publish flow and the behavior of the Phase 2 flags this file's table lists (`--promote` + `--at`, FR-218; `--assets`/`--force` removed v1.6.1); Postiz draft creation, channel mapping, schedule-slot resolution behind this file's `postiz:` config pointer, and the Instagram 2–10 slide ceiling `carousel_slides` should respect (FR-221) (D29, Phase 2).
