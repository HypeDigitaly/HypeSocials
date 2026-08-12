# HypeSocials

A single-operator Windows CLI tool that generates viral social media creatives (images, carousels, reels) from Virlo trends. Fetches trending topics with their top posts, applies a deterministic visual style from a local registry, selects verbatim copy from the posts' captions and hooks, and renders new assets. Images and carousels finish in ~3 minutes; batches with reels take ~8–10 minutes. Costs under $1 per post.

## First-Run Setup

**Prerequisites:**
- Python 3.12 or later
- Virlo API key (with a prepaid deposit in the Virlo billing dashboard)
- OpenRouter API key
- Kie.ai API key
- Node.js / `npx` (only if using Notion for brand context)

**Setup steps:**
1. Copy `.env.example` to `.env` and fill in your API keys from your dashboards.
2. Run `run.bat` — bootstraps the Python environment automatically on first run.
3. The tool opens an interactive menu. Pick **[4] print my Virlo monitor ids** on the first screen. This connects to Virlo, lists every monitor you own, and exits at $0.
4. Copy the monitor IDs you want to use into one of the shipped configs:
   - **`hypedigitaly.yaml`** — English captions, LinkedIn-led (recommended for most runs)
   - **`hypedigitaly-cs.yaml`** — Czech captions and on-image text
   - Or customize **`default.yaml`** — a neutral template you can edit to your own niche
5. **If using Notion:** Open your Notion page or database in the browser and share it with the HypeSocials integration once (one-time setup). The integration cannot fetch private pages unless you share them explicitly.
6. **Meta-style registry setup:** The tool's visual language comes from a local style registry (`prompts/styles.yaml`) with eight predefined styles, each backed by its own local reference images (paths resolve from the repo root; the shipped set points into `Inspiration/` and `hypedigitaly branding/`). Styles are assigned to creatives by deterministic rotation — re-previewing the same topic set picks the same styles, and creatives sharing a topic get different styles. The registry has no fallback: if it is missing or invalid, the run refuses with exit code 2 before spending anything. You can customize it by editing the YAML and swapping reference images, treating it like version-controlled code.

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
run.bat --config hypedigitaly --images 2 --carousels 1 --budget 2 --yes
```
Skips the menu entirely. The plan is estimated and checked against the cap automatically; if it exceeds the cap, the plan auto-trims to fit.

**Preview modes (zero image/reel generation cost):**
- `run.bat --preview-sources --config hypedigitaly` — Shows the topics Virlo returned, the deterministic brand-safety verdicts (keep/strip/skip), and which topics the run would use. Zero LLM cost (the verdicts are blocklist-only; the LLM screen runs in `--preview-analysis`). Virlo's trend digest still meters against your Virlo deposit (~$0.25 per fetch).
- `run.bat --preview-analysis --config hypedigitaly --images 1` — Also runs the copy selector and shows assigned styles and verbatim copy quotes from the source posts. LLM cost only, no image/reel rendering.

**Useful flags:**
- `--verbose` / `-v` — Show per-topic and per-post detail on the console (all topics in the table, the full post roster, every filter verdict). Off by default; the standard console already shows stage headers, tables and heartbeats. The run.log and events.jsonl content policy is unchanged either way — verbosity moves only the console tier.
- `--quick` — Skips the wizard's questions, picks the first runnable config, then shows the cost estimate interactively. The confirm gate is always shown. Mutually exclusive with `--yes`.
- `--history-days N` — Overrides the recency exclusion window for this run only. `0` disables the window. Any value outside the allowed range (0 and above) is refused with one line before the config is loaded, never silently clamped.

## Understanding the Menu (5 Steps)

1. **Config** — Niche, language, and monitor set. Each row shows the language, monitor count, and format counts. A row marked `NOT RUNNABLE` has no monitor IDs yet — use action **[4]** to fetch them.
2. **Formats & counts** — How many creatives to build: `images=4 carousels=2 reels=1`. A carousel deck is multiple slides (5 by default), so 2 carousels = 10 images. Reels are the priciest. Any count you leave out keeps its current value.
3. **Spend cap** — The ceiling for this run. Shown as a limit, not a target; the run spends what it needs up to this cap.
4. **Briefs** (optional) — Your own visual directives or message overrides. Blank/Enter = none. A brief can skip trends entirely (`override` mode), so it runs even with zero monitor IDs.
5. **Confirm** — The cost estimate and final yes/no. Nothing has been billed yet; declining costs nothing. Notion influence (`off` / `copy` / `full`) is shown here from the config and edited only in the file (requires `NOTION_TOKEN` in `.env` for `full` mode).

**At any prompt, press `?` to see help for that step.** The help explains what the step does and what a good value is. Pressing `?` re-asks the question — it does not advance.

## Trend Freshness & History

The tool tracks which posts you've used over the last 7 days (configurable per run with `--history-days N`) to avoid repeating them. This history is stored per *individual post*, not per monitor, so the tool can deliver multiple creatives from the same monitor if they use different images or videos.

**No migration is needed.** The history file `logs/trend_history.json` now has an optional `posts` map for each trend. An entry without that map reads as "no posts tracked yet", so old history files work without any change.

## Important: Reel Pricing (Post-Pivot)

Reels ship disabled by default (`formats.reel: 0`). When enabled, Kie bills Seedance at `unit_price × output_seconds` only — the reel renders from a seed frame alone, no motion reference is attached, so nothing but the output is billed. At Kie's published no-reference rates (confirmed to the credit against a live measurement — see `spikes/RESULTS.md` §C) that is **$1.575 for a 5-second 720p reel ($0.315/s) and $0.70 at 480p ($0.140/s)**; the shipped `price_per_unit.reel_second` scalars are exactly those rates. Enable reels per run with `--reels N`. The scalars are per-second, so changing `reel_duration_s` needs no recomputation — only a Kie price change or a model-family swap does (the formula is commented in the config file).

## Interactive vs. `--yes` Behavior at Confirm

**Interactive:** Decline the cost estimate and exit cleanly with no API calls made or money spent. Exit code 0.

**`--yes` mode:** If the estimate exceeds the spend cap, the plan is auto-trimmed to fit in reverse plan order (brief-requested creatives sit at the front and trim last). Trims are logged and the run proceeds with what fits. If the cap is below the cost of any single creative, the run refuses with exit code 2 and spends nothing.

## Outputs

Every run gets its own timestamped folder under `output/<run_id>/`:
- `.png` images and numbered carousel slide decks
- `.mp4` reels with audio
- `gallery.html` — side-by-side review of your creatives and their source trends
- `meta.yaml` per asset — honest metadata (status, degradations, cost); `caption.txt` — the hand-editable publishing caption
- `run.log` — spend, timing, any errors (no secrets)
- `events.jsonl` — detailed per-call log (full prompts, redacted keys)

`output/latest/` is a convenience shortcut to the most recent run. `output/latest.txt` is the canonical pointer.

## Key Resources

- **NAVIGATION.md** — Directory map, secrets hygiene, external services, common tasks.
- **prds/** — Full PRD files (source of truth): 00-overview, 10-pipeline, 20-integrations, 30-configuration-and-run, 40-outputs-and-logging, 50-promptcraft.
- **prds/30-configuration-and-run.md** — Complete config schema and CLI reference.
- **prds/10-pipeline.md** — Exit-code table (exit codes 0–4 and what they mean) and run-flow edge cases.
- **logs/trend_history.json** — Track of posts used in the last 7 days (prevent repeats; has an optional `posts` map per trend).
- **CODING_GUIDELINES.md** — For contributors: code standards, PRD authority, subagent workflow.

## Troubleshooting

**"NOT RUNNABLE" on a config row:** The config has no Virlo monitor IDs. Run action **[4]** from the menu (or `run.bat --list-monitors` from the command line) to fetch your monitor IDs and paste them into that config's `sources.virlo_monitor_ids` list.

**Config or CLI flag error:** The run exits with one clear line naming the problem before any API call. Check your `.env` keys, config file spelling, and flag syntax. Flag errors (e.g., `--history-days 400`) refuse with one line at the flag boundary.

**"Reel price not filled in":** `price_per_unit.reel_second` for your `reel_resolution` is empty. Fill it in or run without reels (`--reels 0` or set `formats.reel: 0` in config).

**Run stops with "exit code 2":** Pre-flight refusal — invalid config, bad profile, or unmet dependency. Read the error line and fix it before retrying.

**Exit code 1:** Partial success — some creatives shipped, others were skipped or trimmed. Read `run.log` for which ones and why.

**Exit code 3:** Fatal — zero usable trends or a dead source. Virlo trends change hourly; retry or try a different monitor.

---

**First updated:** 2026-08-10 (Wave 6, technical-writer pass — §1 setup via action [4] + readiness rows, §2 walkthrough, §3 trend history, §4 flags, all three configs named)

**Re-based:** 2026-08-12 (T4.2 — Topic-First Pivot: local meta-style registry, verbatim copy from Virlo topics, no motion references, 5-step wizard, no generation mode picker)
