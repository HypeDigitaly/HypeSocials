# HypeSocials

A single-operator Windows CLI tool that generates viral social media carousels (and images/reels) from Virlo trends. Fetches trending topics from the last 30 days (newest first, ranked by views within that window), extracts panel texts verbatim from each source slideshow, analyzes source slides with Claude Sonnet 5 to understand their visuals, and renders creatives in a local text-only meta-style (no reference images attached to styles—just visual DNA in YAML). Carousels and images finish in ~3 minutes; batches with reels take ~8–10 minutes. Costs under $1 per post.

## First-Run Setup

**Prerequisites:**
- Python 3.12 or later
- Virlo API key (with a prepaid deposit in the Virlo billing dashboard)
- OpenRouter API key
- Kie.ai API key
- Node.js / `npx` (only if using Notion for brand context — optional, Phase 2)

**Setup steps:**
1. Copy `.env.example` to `.env` and fill in your API keys from your dashboards.
2. Run `run.bat` — bootstraps the Python environment automatically on first run.
3. The tool opens an interactive menu. Pick **[4] print my Virlo monitor ids** on the first screen. This connects to Virlo, lists every monitor you own, and exits at $0.
4. Copy the monitor IDs you want to use into one of the shipped configs:
   - **`hypedigitaly.yaml`** — English captions, LinkedIn-led (recommended for most runs)
   - **`hypedigitaly-cs.yaml`** — Czech captions and on-image text
   - Or customize **`default.yaml`** — a neutral template you can edit to your own niche
5. **If using Notion:** Open your Notion page or database in the browser and share it with the HypeSocials integration once (one-time setup). The integration cannot fetch private pages unless you share them explicitly.
6. **Meta-style registry setup:** The tool's visual language comes from a local TEXT-ONLY style registry (`prompts/styles.yaml`) with eight predefined styles. Each style carries palette, typography rules, and layout guidance—all as YAML definitions with no reference images attached to the styles themselves. Brief images and carousel anchor images still exist; style reference images do not. Styles are assigned to creatives by deterministic rotation — re-previewing the same topic set picks the same styles, and creatives sharing a topic get different styles. The registry has no fallback: if it is missing or invalid, the run refuses with exit code 2 before spending anything. You can customize it by editing the YAML, treating it like version-controlled code.

The tool **deliberately ships `default.yaml` with an empty monitor-ids list** — it is a neutral template, not a working config. The wizard will show it as `NOT RUNNABLE` until you add ids. The first time through, action **[4]** is the fastest path to a working setup.

## Running a Batch

**Interactive (default):**
```
run.bat
```
Shows the action choice, then a 5-step wizard: config, format counts, spend cap, briefs (optional), and confirm. Cost estimate is shown before any money moves; decline to exit at $0.

**Quick run (skip the questions):**
```
run.bat --quick
```
Picks the first ready config automatically, prints which one, then goes straight to the cost estimate and confirm gate. Still interactive — you still approve before spend.

**Unattended (Windows Task Scheduler, or programmatic runs):**
```
run.bat --config hypedigitaly --carousels 6 --budget 2 --yes
```
Skips the menu entirely. The plan is estimated and checked against the cap automatically; if it exceeds the cap, the plan auto-trims to fit.

**Preview modes (zero image/reel generation cost):**
- `run.bat --preview-sources --config hypedigitaly` — Shows the topics Virlo returned in the 30-day window, the deterministic brand-safety verdicts (keep/strip/skip), and which topics the run would use. Shows the three drop lines: stale posts (over 30 days old), unenriched posts (missing panel text or image URLs), and used posts (quoted in the last 30 days). Zero LLM cost (the verdicts are blocklist-only; the LLM screen runs in `--preview-analysis`). Virlo's trend digest still meters against your Virlo deposit (~$0.25 per fetch).
- `run.bat --preview-analysis --config hypedigitaly --carousels 2` — Also runs the copy selector and shows assigned styles and verbatim copy quotes from the source posts' panel texts, hooks, and captions. LLM cost only, no image/reel rendering.

**Useful flags:**
- `--verbose` / `-v` — Show per-topic and per-post detail on the console (all topics in the table, the full post roster, every filter verdict). Off by default; the standard console already shows stage headers, tables and heartbeats. The run.log and events.jsonl content policy is unchanged either way — verbosity moves only the console tier.
- `--quick` — Skips the wizard's questions, picks the first runnable config, then shows the cost estimate interactively. The confirm gate is always shown. Mutually exclusive with `--yes`.
- `--history-days N` — Overrides the recency exclusion window for this run only. The no-repeat protection works at post-ID level: any post (by its Virlo UUID) quoted in the last N days is skipped. `0` disables the window. Any value outside the allowed range (0 and above) is refused with one line before the config is loaded, never silently clamped. The **invariant rule:** `trend_history_days ≥ max_post_age_days` (defaults both 30). If the history window is shorter than the fetch window, the run refuses pre-flight and names both keys.

## Understanding the Menu (5 Steps)

1. **Config** — Niche, language, and monitor set. Each row shows the language, monitor count, and format counts. A row marked `NOT RUNNABLE` has no monitor IDs yet — use action **[4]** to fetch them.
2. **Formats & counts** — How many creatives to build. The v2.1.0 default is **carousels only** (`images=0 carousels=6 reels=0`), because sourceshows are text-only and carousels are the natural format for panel-mapped creatives. A carousel deck is multiple slides (5 by default), so 2 carousels = 10 images. If you enable images or reels, you must also enable videos (`sources.include_videos: true`), or the run refuses pre-flight—slideshows are the only format available by default. Any count you leave out keeps its current value.
3. **Spend cap** — The ceiling for this run. Shown as a limit, not a target; the run spends what it needs up to this cap.
4. **Briefs** (optional) — Your own visual directives or message overrides. Blank/Enter = none. A brief can skip trends entirely (`override` mode), so it runs even with zero monitor IDs.
5. **Confirm** — The cost estimate and final yes/no. Nothing has been billed yet; declining costs nothing. Notion influence (`off` / `copy` / `full`) is shown here from the config and edited only in the file (requires `NOTION_TOKEN` in `.env` for `full` mode).

**At any prompt, press `?` to see help for that step.** The help explains what the step does and what a good value is. Pressing `?` re-asks the question — it does not advance.

## Sourcing & No-Repeat Protection

The tool fetches trending topics from **the last 30 days** (configurable per run with `--history-days N` for memory, or `--max-post-age-days` for fetch window), ranked by views within that window. The first paid run proved that all-time ranking pulls stale posts (some from 2023); the new behavior ensures fresh, timely content.

**No-repeat protection works at the post-ID level** — individual posts, not just topics. The tool tracks which posts you've used over the history window and skips them, so even if one topic has fresh posts, you won't repeat yesterday's post from that topic. The history is stored per post (Virlo UUID) in `logs/trend_history.json`, with an optional `posts` map for each trend. An entry without that map reads as "no posts tracked yet", so old history files work without any change.

**Weekly cadence is recommended** — roughly the fetch window (3 pages of Virlo results is one week's activity at normal volume). Daily runs are permitted if you have enough fresh content. Use `--preview-sources` to see which posts the funnel would drop as stale, unenriched, or already used; that's your supply audit. **No famine fallback** — when a topic's fresh posts are exhausted, the entry is skipped with `no_fresh_post_available`, never wrapped or repeated. Honest reporting over silent repeats.

## Copy & Slides

Every carousel's panel text is **quoted verbatim from the source slideshow**—source panel 1's text becomes output slide 1's text, position-preserving, in the source's original language. No retyping, no translation, no trimming (verbatim quotes are never shortened to fit a budget; if a real panel text won't fit, that panel is marked missing and the creative ships incomplete and tagged `no_onimage_text`).

Copy selection pulls from:
1. Panel texts (on-image words)
2. Hooks (call-to-action overlays)
3. Captions (the source post's own caption)

**Descriptions are never rendered.** Virlo's AI-generated summary text is used only as context for the copy model, never as a caption or on-image text.

For slide analysis, **after you approve the budget** (Confirm gate), the tool downloads each assigned source slideshow's images and has Claude Sonnet 5 read them, extracting:
- On-image text verbatim
- Visual descriptions (charts, icons, layout, composition—anything that shapes what "this slide looks like")

These extractions feed directly into the render prompts so our slides reproduce the **content** of the original deck in our own visual style (not by cloning reference images, but by understanding what was there and rendering it in our house style). This analysis costs ~$0.01–0.03 per post and is included in the pre-flight estimate.

## Visual Styles

Styles are **text-only.** The `prompts/styles.yaml` registry ships eight predefined styles, each carrying:
- Palette (named colors and their hex values)
- Typography rules (font names, character descriptions)
- Layout guidance (composition, zones, hierarchy)

No style carries reference images. Brief images still exist (optional override images supplied per brief). Carousel anchor images and seed frames still exist. But styles are pure textual definitions, treated like code, editable in Notepad, versioned in the repo.

The engine applies each style deterministically per creative so the same topic never looks the same way twice in a single run. A style missing or the registry broken → exit 2, $0 spent.

## Branding

A configurable fraction of posts get your wordmark (HypeDigitaly or HypeLead, never mixed)—placed consistently and rendered as text, not a composite image. The `brand_ratio` setting in the config determines what fraction (e.g., 0.5 = half). The wordmark rotates deterministically across creatives so the same run always produces the same branded set.

## Important: Reel Pricing (Post-Pivot)

Reels ship disabled by default (`formats.reel: 0`). When enabled, Kie bills Seedance at `unit_price × output_seconds` only—the reel renders from a seed frame alone (no motion reference video), so nothing but the output seconds are billed. At Kie's published no-reference rates (confirmed against a live measurement in `spikes/RESULTS.md` §C): **$1.575 for a 5-second 720p reel ($0.315/s) and $0.70 at 480p ($0.140/s)**. The shipped `price_per_unit.reel_second` scalars are exactly those rates. Enable reels per run with `--reels N`. The scalars are per-second, so changing `reel_duration_s` needs no recomputation — only a Kie price change or a model-family swap does (the formula is commented in the config file).

## Interactive vs. `--yes` Behavior at Confirm

**Interactive:** Decline the cost estimate and exit cleanly with no API calls made or money spent. Exit code 0.

**`--yes` mode:** If the estimate exceeds the spend cap, the plan is auto-trimmed to fit in reverse plan order (brief-requested creatives sit at the front and trim last). Trims are logged and the run proceeds with what fits. If the cap is below the cost of any single creative, the run refuses with exit code 2 and spends nothing.

## Outputs

Every run gets its own timestamped folder under `output/<run_id>/`:
- `.png` images and numbered carousel slide decks
- `.mp4` reels with audio
- `source/<post_id>/` — locally downloaded source slides (for analysis and gallery display; never published)
- `gallery.html` — three-part carousel cards showing source provenance (author, views, post URL), original slides with extracted text, and our rendered slides aligned by index
- `meta.yaml` per asset — honest metadata (status, degradations, cost); `caption.txt` — the hand-editable publishing caption
- `run.log` — spend, timing, any errors (no secrets)
- `events.jsonl` — detailed per-call log (full prompts, redacted keys)

`output/latest/` is a convenience shortcut to the most recent run. `output/latest.txt` is the canonical pointer.

## Key Resources

- **NAVIGATION.md** — Directory map, secrets hygiene, external services, common tasks.
- **prds/** — Full PRD files (source of truth): 00-overview, 10-pipeline, 20-integrations, 30-configuration-and-run, 40-outputs-and-logging, 50-promptcraft.
- **prds/30-configuration-and-run.md** — Complete config schema and CLI reference.
- **prds/10-pipeline.md** — Exit-code table (exit codes 0–4 and what they mean) and run-flow edge cases.
- **logs/trend_history.json** — Track of posts used in the last 30 days (prevent repeats; has an optional `posts` map per trend with post IDs and their last-used dates).
- **CODING_GUIDELINES.md** — For contributors: code standards, PRD authority, subagent workflow.

## Troubleshooting

**"NOT RUNNABLE" on a config row:** The config has no Virlo monitor IDs. Run action **[4]** from the menu (or `run.bat --list-monitors` from the command line) to fetch your monitor IDs and paste them into that config's `sources.virlo_monitor_ids` list.

**Config or CLI flag error:** The run exits with one clear line naming the problem before any API call. Check your `.env` keys, config file spelling, and flag syntax. Flag errors (e.g., `--history-days 400`) refuse with one line at the flag boundary.

**"Reel price not filled in":** `price_per_unit.reel_second` for your `reel_resolution` is empty. Fill it in or run without reels (`--reels 0` or set `formats.reel: 0` in config).

**Run stops with "exit code 2":** Pre-flight refusal — invalid config, bad profile, missing registry, or unmet dependency. Read the error line and fix it before retrying.

**Exit code 1:** Partial success — some creatives shipped, others were skipped or trimmed. Read `run.log` for which ones and why.

**Exit code 3:** Fatal — zero usable trends for a plan that needed them, or a transport-dead source. Virlo trends change hourly; retry or try a different monitor.

---

**First updated:** 2026-08-10 (Wave 6, technical-writer pass)

**Re-based:** 2026-08-12 (T4.2 — Topic-First Pivot Wave 4)

**D46 re-base:** 2026-08-13 (SESSION G, T4.2 — Slideshow fidelity: 30-day recency window, post-ID no-repeat invariant, text-only styles, panel-mapped carousels, slide intelligence post-Confirm, provenance gallery, `refs/` brief-images-only)
