# 40 — Outputs & Logging

## TL;DR — Plain English

Each run creates a timestamped folder on disk (`output/YYYYMMDD_HHMMSS_random/`) containing the finished images, carousel slides, videos, captions, and an offline HTML gallery. A single `gallery.html` file shows all creatives side by side (with source reference images for comparison), complete with platform badges, costs, and captions—reviewable in ~30 seconds. The folder also includes `run.log` (human-readable step-by-step narrative) and `events.jsonl` (machine-parseable structured data for dashboards). A global `logs/trend_history.json` remembers which trends were used recently to avoid repetition. Failed creatives still appear in the folder with a `SKIP_REASON.txt` file explaining why. Everything is self-contained: no external CDN, works offline, and ready to publish or archive.

**Requirement ranges owned by this file:** FR-70–89, FR-150–159, FR-230–239; NFR-20–24

## 1. Run Identity & Folder Structure (FR-70, FR-71, NFR-20)

**FR-70:** Every run receives a unique `run_id` with format `YYYYMMDD_HHMMSS_<4-char-random>`. Example: `20260808_143022_x7q2`. The run folder is created immediately at launch, before any API calls. If the run is aborted early, the folder remains with only run.log and events.jsonl inside. The disk-space pre-check is owned by 30-configuration FR-255: a test file written and deleted **inside the configured `output.dir`** (never a temp path on a possibly different volume); if that fails, the run aborts with an error before any spend.

**FR-71:** All output for a given run lives in `output/<run_id>/`. Within that folder, one subdirectory per generated creative uses the naming scheme `<asset_id>/`, where asset_id encodes: platform (Li, Ig, Tk), format (img, car, reel), a URL-safe slug of the source trend name (capped at 40 characters for Windows MAX_PATH safety), variant tag (analyzed or direct), and a zero-padded per-run ordinal (e.g., `_01`, `_02`). Asset IDs are unique within a run; two creatives sharing platform + format + trend + variant receive distinct ordinals to prevent silent folder overwrites. Example: `Li_car_dance-challenge_analyzed_02/`. In A/B mode, both variants share a `pair_id` in their meta.yaml but remain separate asset folders. Brief-driven creatives (D26, override mode — no trend) define their packaging explicitly: slug derived from the brief name, meta contains `source: brief/<name>`, and the brief's own reference images (if supplied) are copied into the asset's `refs/` subfolder; the gallery displays a brief badge on the card. A separate global `refs/` folder at `output/<run_id>/refs/` stores the actual reference media used per trend — images as `refs/<trend_key>/image_1.jpg` etc., and, when the D23 video-reference chain ran, the downloaded winning video as `refs/<trend_key>/video_1.mp4` so the gallery can show the motion source next to the generated reel. Note: the engine should tolerate and enable long paths in subsequent versions but must never assume Windows path limits are enforced.

**NFR-20:** The canonical latest-pointer is **`output/latest.txt`** — one line containing the `run_id` of the most recent run that successfully packaged at least one asset, written atomically (temp+rename). A junction at `output/latest/` is additionally maintained **best-effort** as a human convenience for Explorer navigation (a junction cannot be atomically replaced on Windows, which is why it is not the canonical pointer); programmatic consumers always resolve `latest.txt`. Aborted or log-only runs never claim either. Canonical locking and atomicity rules live in 30-configuration-and-run.md (FR-254).

---

## 2. Per-Asset Folders & Contents (FR-72, FR-73, FR-74, NFR-21)

**FR-72:** Each successful asset folder contains: the final image file (JPG/PNG, zero-padded if carousel: `slide_01.jpg`, `slide_02.jpg`, etc.), a video file for reels (MP4) **plus, when the seed-frame path ran, the paid seed-frame image as `seed_frame.jpg`** (useful as a cover/thumbnail at posting time), a `caption.txt` file holding the caption and hashtags (plain text, ready to paste into a social platform), and a `meta.yaml` file with structured metadata.

**FR-73:** The `meta.yaml` file is the canonical schema for all asset metadata. It records (grouped logically):

**Identity & sourcing:**
- source (trend key / "brief/<name>")
- source_name (human-readable trend or brief name)
- platform, format
- variant (analyzed | direct)
- pair_id (if A/B mode; pairs both-mode creatives for gallery side-by-side)
- asset_id (full folder name including ordinal)

**Provenance & degradations (collapsed to one list, v1.6.1):**
- generation_mode (analyzed | direct)
- hook_pattern_used (**string** — names the hook pattern the copy followed, or the brief name + declared structure for override briefs; 10-pipeline FR-100/FR-146)
- ref_source (e.g., "virlo", "brief", "inspiration"; source of reference images used)
- **degradations** — a single list of tags, empty on a clean asset, replacing the former per-flag booleans. Defined vocabulary (each tag's behavior owned by the FR that emits it): `analysis_missing` (FR-12), `copy_degraded` (FR-99; Notion unavailability is a logged warning, never a tag), `reference_free` (FR-18), `refs_dropped_moderation` (FR-97), `text_trimmed` (FR-101), `incomplete` (partial carousel, FR-20/95), `skipped_budget` (FR-106), `abandoned` (FR-108), `seed_frame_render_failed` / `seed_frame_url_unreachable` (FR-24), and the video-reference chain reasons `probe_failed` / `no_qualifying_video` / `download_failed` / `upload_failed` / `malformed_metadata` (FR-142/160). The gallery renders every tag as a badge in one loop; new tags need no schema change.

**Brief overrides (D26):**
- brief_name (if brief-driven)
- brief_influence_mode (override | blend)

**Model & generation:**
- model_ids (the configured model id(s) and route(s) actually used, per 30-configuration's `models.*` keys)
- render_not_reproducible (true; Kie exposes no generation seeds — OQ-4 closed, so there is no seed field at all)
- aspect_ratio_requested (the target platform/format ratio, FR-21)
- native_size_rendered (the model-native size actually requested/received, FR-98)

**Cost & timing:**
- estimated_cost_usd, actual_cost_usd
- estimated_tokens, actual_tokens
- job_submission_timestamp, job_completion_timestamp (ISO 8601)
- kie_job_id(s)

**Quality & skip reasons:**
- vision_check_result (passed | retried_passed | retried_failed | not_checked — 10-pipeline FR-27's four-state vocabulary; three states cannot express "retried")
- status (pending | success | failed — pending only between folder creation and terminal rewrite, NFR-21)
- skip_reason (one line, e.g., "kie_timeout", "disk_full", "moderation_permanent_fail"; the machine-readable cause also appears as a `degradations` tag)

**Format-specific:**

*Carousel:*
- slide_count (actual slides delivered)
- missing_slide_numbers (array of 1-indexed slide ordinals that failed; the `incomplete` tag in `degradations` marks the condition)

*Reels:*
- reel_audio (true | false)
- reel_video_reference_url (if video reference was used; chain failures appear as `degradations` tags)

**Posting (Phase 2):**
- postiz_draft_id, postiz_post_id, postiz_state (uploaded | scheduled | published | draft)
- postiz_media_ids (array of Postiz media resource ids)

**Logging & audit:**
- event_id (pointer to events.jsonl record, e.g., "ev_20260808_1234")
- virlo_url (if trend-sourced)

**FR-74:** If a creative fails to generate or is skipped (e.g., Kie.ai job timeout, budget exhausted), the asset folder still exists and contains: the already-paid artifacts (caption.txt and meta.yaml with status: failed) alongside a `SKIP_REASON.txt` file with a one-line reason. Example: `SKIP_REASON.txt` contains "Kie job timeout after 180s (job id kie_xyz789)". This ensures the run log can always reference a folder, and the user sees why assets are incomplete.

**NFR-21:** Asset folder creation is atomic: the folder and its `SKIP_REASON.txt` (if needed) are written immediately after a decision to skip; final image/video is copied only after successful generation and optional vision-check. **`meta.yaml` is written at folder creation with `status: pending` and rewritten by temp-file+rename at terminal status** — a kill between image download and metadata write must never leave an asset folder containing media but no meta, because the gallery and the Phase 2 publisher both read it. This avoids partial-asset confusion.

---

## 3. Gallery HTML File (FR-75, FR-76, FR-150, NFR-22)

**FR-75:** One HTML file per run, named `gallery.html`, resides at `output/<run_id>/gallery.html`. It is **entirely self-contained**: all CSS is inlined in a `<style>` block, all images/videos are referenced via relative paths to sibling asset folders (e.g., `./Li_car_dance_analyzed_01/slide_01.jpg`) or the `refs/` folder, and no external CDN resources are loaded. Small inline scripts are allowed; no external resources, no rating widgets. The file works offline in any browser. **Atomic writing:** every incremental rewrite uses a temporary file + rename, ensuring that a crash mid-write never leaves a truncated file for an open browser tab.

**FR-76:** The gallery is written **incrementally**: as soon as images land from Kie.ai, a first version is written to disk, allowing the user to review finished images while reel generation continues. The gallery is refreshed at run end with final counts and any newly completed reels. Each card displays: a preview (image thumbnail; reels render as `<video preload="metadata">` so the browser shows the first frame itself — **no poster-frame extraction, which would need ffmpeg** — with `seed_frame.jpg` as the `poster` attribute when it exists), the caption text, platform/format badges, estimated cost, source reference image(s) from `output/<run_id>/refs/`, the source hook text, and a link to the source Virlo URL. When A/B mode was used, both variants are automatically placed side by side and paired by `pair_id` (no configuration needed). **Pair-integrity badge:** when a both-mode pair has one side carrying `analysis_missing: true`, the gallery labels the pair "A/B invalid — analysis fell back to direct" instead of presenting a misleading comparison. The gallery title is set from config value `gallery.title` only; no grouping, toggle, or ranking widgets. The gallery header documents the selection mechanism (see FR-236 below).

**FR-150:** Fidelity is judged in the gallery by comparing each creative against its source reference images shown alongside.

**NFR-22:** Gallery generation never blocks asset delivery: if HTML generation fails (e.g., a template error), the run completes and assets remain on disk; the run log notes the failure and points to the asset folders. Color scheme uses `prefers-color-scheme` CSS media query only (no user toggle).

---

## 4. Run Log: Human-Readable Narrative (FR-77, FR-78, NFR-23)

**Logging ownership:** This file owns the logging specification. Verbosity is controlled by enum `normal|verbose` only (no debug level or debug folder). Full prompts and full payloads are ALWAYS written to `events.jsonl` (machine-readable); `run.log` carries one-line digests and the complete chronological human narrative.

**FR-77:** Every run writes `output/<run_id>/run.log`, a chronological human-readable narrative log including:
- Launch summary: run_id, launch timestamp, chosen config file, resolved run parameters (formats, counts, spend cap, generation mode, Notion influence, platforms/languages).
- Each MCP server call (name, operation, duration, brief result summary; e.g., "Virlo MCP: trends → 27 trends found, top 5 confidence ≥ 0.82").
- Each OpenRouter or Kie.ai API call (endpoint, model, duration, tokens, cost).
- Virlo payload summary (per trend: key, name, video count, top 3 stats—views, likes, publish date).
- Trend selection & ranking: why each trend was selected or skipped (e.g., "Dance-Challenge: 4.2M views, ranked #1, selected"; "RetroMeme: last used 2026-08-02, skipped, history window 7 days").
- **Per-creative narrative:** source trend, platform/format, generation mode, full prompt text, Kie.ai job id, poll timeline (T0, T0+2s [pending], T0+5s [ready]), download time, result (success with cost, or failure reason).
- **Format-affinity decisions** (why a slideshow trend went to carousel vs. image).
- **Anchor-chain decisions** (carousel slide 1 generated first, slides 2–N chained to it, or fallback to independent).
- **Moderation fallbacks** (references dropped on retry, marked `refs_dropped_moderation`).
- Vision-check verdicts (pass/fail, reason, retry action).
- **Preview-mode outputs** (if `--preview-sources` or `--preview-analysis` was used).
- Budget tally after each spend: running total, remaining cap, percentage spent.
- Final summary: total creatives generated, total spend, skipped count and reason summary, warnings/errors, wall-clock time, success/partial-success/failed status.

**FR-78:** Timestamps use ISO 8601 format (e.g., `2026-08-08T14:23:47.123Z`); durations are in milliseconds (e.g., `342ms`).

**NFR-23:** The run log is flushed to disk after every event (Virlo fetch, trend ranked, creative submitted, job polled, etc.), ensuring that if the run is interrupted, the log tail is always truthful and reflects the last known state. Logs live in `output/<run_id>/` (run.log + events.jsonl); `logs/trend_history.json` stays global.

---

## 5. Structured Events Log (FR-80, FR-81)

**FR-80:** Every run writes `output/<run_id>/events.jsonl`, a newline-delimited JSON file with one JSON object per event. Each event contains: timestamp, event_type (e.g., "virlo_fetch_complete", "trend_ranked", "creative_submitted", "job_polled", "vision_check_result"), and a `data` object with all relevant fields. This includes full prompts, full API payloads, and all metadata—enabling future dashboards and cost analytics to parse runs programmatically.

**FR-81:** Both run.log and events.jsonl are written concurrently as each event fires; they are always in sync. **Writes are serialized through a single writer** (all writes on the event loop with no `await` inside a write, or one lock) so concurrent tasks can never interleave partial lines — a torn JSONL line breaks every downstream parser of events.jsonl.

**FR-152 — Secret redaction at the logging boundary (D30).** No API key or Authorization header ever reaches run.log or events.jsonl: auth headers are stripped from logged request/response payloads before writing, and any value matching a configured secret is replaced with `[REDACTED]`. Since prompts are logged in full, this pairs with D30's guarantee that secrets are never interpolated into any prompt or template in the first place — redaction is the backstop, not the primary defense.

---

## 6. Trend History & Recency Exclusion (FR-82, FR-83, NFR-24)

**FR-82:** The file `logs/trend_history.json` is a simple JSON object where keys are trend keys (Virlo agent id when present, else the normalized name slug defined in 20-integrations §3's normalization spec) and values are objects containing: first_used (ISO 8601 date), last_used (ISO 8601 date), and run_ids (array of run IDs, **capped at the most recent 5**). **A trend is recorded in history ONLY if at least one creative on that trend was packaged successfully** (i.e., final image/video/carousel delivered to the asset folder, not skipped). This file is read at trend-selection time and updated after packaging. **On every write, entries whose `last_used` is older than `max(trend_history_days, 90)` days are pruned** — the file is a rolling window, not an unbounded archive rewritten under a lock on every run.

**FR-83:** If `trend_history.json` does not exist or is corrupted, the engine logs a warning ("trend_history.json missing or invalid; starting fresh") and proceeds without penalties. It never crashes due to history state. The file is created fresh if missing.

**NFR-24:** The recency window is configured via `trend_history_days` (default 7; cross-ref 30-configuration.md); at selection time, any trend with `last_used` within the past N days is skipped. **When a run is interrupted, rerunning safely skips only successfully-packaged trends** (those in history) and tries remaining trends again.

---

## 7. Spend Summary & Budget Tally (FR-84, FR-85)

**FR-84 (simplified v1.6.1):** At the end of every run, the summary opens with one headline line — **"requested N creatives, delivered M"** — so a scheduled run that was trimmed, shrunk by trend supply, or dropped reels is legible at a glance without decoding the exit code. Below it, **one** spend table is printed to the console and written to run.log: one row per creative with **estimated** vs. **billed-attempts** (tallied on submission, failures included) vs. **delivered**, a subtotal row per format, and a grand-total row splitting LLM vs. render spend (reasoning tokens included). Closing lines state: budget cap status, counts skipped by budget/deadline with reason summary, and any "governance partial — N lines unpriced" banner. The former separate per-category, per-platform and per-format tables are deleted — events.jsonl carries everything a future dashboard would need.

**FR-85:** Unknown costs (where provider did not return billing data) are marked **"estimated"** (no "pending reconciliation" language).

---

## 8. Retention & Disk Management (FR-86)

**FR-86:** No output is automatically deleted. The user manually deletes old run folders or archives them as needed. Disk estimates: one image ≈ 100–300 KB, one carousel ≈ 400–800 KB, one reel ≈ 5–20 MB; logs add ≈ 50–200 KB per run.

---

## 9. Phase 2 Hook: Publishing via Postiz (FR-87, FR-88)

**FR-87:** (Phase 2, MVP does not implement.) Phase 2 adds `--publish` to 30's flag table. A `--publish` flag or menu option reads asset folders from a completed run and pushes drafts to Postiz via Postiz's public REST API (see 60-publishing-postiz.md for full specification): per-platform captions, channel mapping from config, optional schedule slots, operator approval in the Postiz UI before auto-publish.

**FR-88:** After publishing, the asset folder's `meta.yaml` receives entries: `postiz_draft_id`, `postiz_post_id`, `postiz_state` (uploaded | scheduled | published | draft), and `postiz_media_ids` (array of Postiz media resource IDs).

---

## 10. Edge Cases & Failure Modes (FR-89)

**FR-89 — Output-owned failure cases only** (transport/pipeline failures cross-reference 10 and 20):
- **Disk full or unwritable:** Pre-check happens inside `output.dir` (owned by 30-configuration); mid-run disk-full marks the creative failed with `disk_full` and the run packages what exists (owned by 10-pipeline). See 30-configuration for pre-flight checks and 10-pipeline for mid-run behavior.
- **Gallery generation failure:** Assets remain on disk; run.log notes the error and points the user to the asset folders.
- **Interrupted run (Ctrl+C):** Ctrl+C mid-poll forfeits nothing that finished; the run.log is flushed per event, so the log tail is always truthful. In-flight Kie.ai work that was billed is recoverable via the outstanding-task LEDGER: a file at `output/<run_id>/LEDGER.txt`, **append-only** — a line `<asset_id>,<request_token>` is appended *before* each `createTask` call (intent-before-call, 10-pipeline FR-203), a line with the `taskId` is appended when the response arrives, and terminal statuses append a further line for the same taskId; **the last line for a taskId wins** (no in-place updates — an appended CSV cannot be edited without a rewrite). This enables the operator to query billed task IDs against Kie later, including submissions whose response was lost (`submit_unknown`). No resume feature; the user reruns (which is cheap and fast). Rerunning safely skips trends already packaged (via trend_history.json). The ledger is owned by 10-pipeline (submission and status updates); 40-outputs documents it here as a run-folder artifact.

---

## 11. Publishing Handoff & Asset Metadata (FR-230–232)

**FR-230:** `caption.txt` in each asset folder defines the exact publishing contract: it contains the caption body, one blank line, then hashtag line(s). The publish step (60-publishing-postiz.md) sends the file contents verbatim as the platform caption — operator edits to this file after generation are honored. **This is the ONE hand-editable asset file;** all others (images, video, meta.yaml) are read-only from the gallery.

**FR-231:** The gallery→publish journey uses a lightweight selection artifact. **After the run, during gallery review**, the operator marks assets for publishing by creating an empty **`SELECTED.marker`** file in an asset folder (`output/<run_id>/<asset_id>/SELECTED.marker` — the `.marker` suffix matches the `PUBLISH_ATTEMPTED.marker`/`PUBLISHED.marker` family in 60-publishing) or by listing asset IDs in a `publish.txt` at the run root (`output/<run_id>/publish.txt`, one asset_id per line). Both mechanisms are supported; the marker file is preferred. `--publish` publishes exactly the selected set, **or everything if nothing is selected — a deliberate, blessed default** (drafts are reviewed once more inside Postiz, so an unfiltered push is loud, not dangerous; the `--assets` filter was removed in v1.6.1 — the markers are the filter). The gallery HTML header documents this selection mechanism.

**FR-232:** The end-of-run spend summary line printed to console and logged records: total cost, grand total time, count of creatives generated, count skipped (with reason summary), run success/partial-success/failed status, **and the process exit code**. Interactive runs may additionally prompt for an optional 3-point operator fidelity rating (skippable, absent under `--yes` or headless mode): **one rating per run** — how well the batch as a whole matched the trends visually/tonally — recorded in run.log and consumed by 00-overview's success metric, which is correspondingly stated per run ("≥80% of rated runs score 2+"), not per creative. Operator eyeball; no aggregate scoring.

---

## Design Decisions

**D9 — Output = per-asset folders + gallery.html:** Self-contained asset folders enable easy share/archive/republish; the gallery provides a single-page overview. Simple folders + structured logs reduce complexity.

**D12 — State = trend-history JSON + full run log:** Trend history (dates + keys) enables simple recency checks without a database. Full human-readable + machine-parseable logs enable audit trails and future analytics without a query interface.

---

## Summary

Output and logging are user-centric and transparent. Each run is self-contained in a timestamped folder; every creative is traceable to its source and parameters; the gallery enables instant visual review with fidelity judged against source references. The lean strategy (text + JSONL + global trend history) avoids over-engineering while supporting future analytics. Budget accountability, error reporting, and incomplete-result handling follow: **degrade and report, never silently fail.**
