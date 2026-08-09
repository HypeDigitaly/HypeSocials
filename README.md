# HypeSocials

A single-operator Windows CLI tool that generates viral social media creatives (images, carousels, reels) from Virlo trends. Fetches winning posts, analyzes their visual style and copy structure via LLM, and renders new assets matching that style. Images and carousels finish in ~3 minutes; batches with reels take ~8–10 minutes. Costs under $1 per post.

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
3. Run `run.bat --list-monitors` to get your Virlo monitor IDs and copy them into `configs/default.yaml` under `sources.virlo_monitor_ids`.
4. **If using Notion:** Open your Notion page/database in the browser and share it with the HypeSocials integration once (this is a one-time setup step in Notion's UI). The integration cannot fetch private pages unless you share them explicitly.
5. Optional: create an `Inspiration/` folder with reference images; list the path in `sources.inspiration_folders`.

## Running a Batch

**Interactive (default):**
```
run.bat
```
Shows a 7-step menu: pick config, trend source, format counts, spend cap, generation mode, briefs, then confirm. Cost estimate is shown before any money moves; decline to exit at $0.

**Unattended (Windows Task Scheduler, or programmatic runs):**
```
run.bat --config hypedigitaly.yaml --images 2 --carousels 1 --budget 2 --yes
```
Skips the menu entirely. If the estimate exceeds the cap, the plan auto-trims to fit instead of refusing.

**Preview modes (zero generation cost):**
- `--preview-sources`: Shows what trends Virlo returned and which the run would actually use — $0 (Virlo metering only, ~$0.25 per digest fetch if used).
- `--preview-analysis`: Also shows AI's style analysis and copy drafts — LLM cost only, no image/reel rendering.

## Important: Reel Pricing

Reels ship disabled by default (`formats.reel: 0`). When enabled, Kie bills Seedance at `unit_price × (reference_video_seconds + output_seconds)` — the motion reference's duration is billed too. **Measured live: a 5-second 720p reel with a 10-second motion reference costs $2.85** (spikes/RESULTS.md §C). The config key `reel_reference_max_s` is a **price lever**: attaching a reference beats no-reference only while the reference is shorter than ~0.65 × the output duration. `configs/hypedigitaly.yaml` ships `reel_reference_max_s: 20` with worst-case-honest `price_per_unit.reel_second` scalars already derived from the measurement (720p `0.950`/output-second ≈ $4.75 worst case per 5 s reel; actuals land lower) — enable per run with `--reels N`. If you change `reel_reference_max_s`, `reel_duration_s`, or resolution, recompute the scalars per the formula commented in that config file.

## Interactive vs. `--yes` Behavior at Confirm

**Interactive:** Declines the cost estimate and exits cleanly with no API calls made or money spent. No error, exit code 0.

**`--yes` mode:** If the estimate exceeds the spend cap, the plan is auto-trimmed to fit in reverse plan order (entries are dropped from the end of the plan; brief-requested creatives sit at the front, so they are trimmed last). Trims are logged and the run proceeds with what fits; if the cap is below the cost of any single creative, the run refuses with exit code 2 and spends nothing.

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
- **prds/10-pipeline.md** — Exit-code table (FR-202) and run-flow edge cases.
- **logs/trend_history.json** — Track of trends used in the last 7 days (prevent repeats, append-only).
- **CODING_GUIDELINES.md** — For contributors: code standards, PRD authority, subagent workflow.

## Troubleshooting

**Config or CLI flag error:** The run exits with one clear line naming the problem before any API call. Check your `.env` keys, config file spelling, and flag syntax.

**"Reel price not filled in":** `price_per_unit.reel_second` for your `reel_resolution` is empty. Fill it in or run without reels (`--reels 0` or set `formats.reel: 0` in config).

**Run stops with "exit code 2":** Pre-flight refusal (invalid config, bad profile, missing key). Read the error line and fix it before retrying.

**Exit code 1:** Partial success — some creatives shipped, others were skipped or trimmed. Read `run.log` for which ones and why.

**Exit code 3:** Fatal — zero usable trends or a dead source. Virlo trends change hourly; retry or try a different monitor.

---

Created 2026-08-09 (Wave 6, T6.2).
