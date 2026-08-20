# 40 — Outputs & Logging

**Amendment: v2.2.0 (2026-08-14, D49–D53)** — Gauntlet quality gate, BLOCKED status, GAUNTLET_REPORT.yaml, critic unavailable events, console lines, gallery BLOCKED badge. Prior: v2.1.3 (2026-08-13, D48) loud partial-delivery reporting, slides_ordered field.

## TL;DR — Plain English

Each run creates a timestamped folder on disk (`output/YYYYMMDD_HHMMSS_random/`) containing the finished images, carousel slides, videos, captions, and an offline HTML gallery. A single `gallery.html` file shows all creatives side by side with the style assigned to each, the brand applied, and the exact source post (with author, view count, post ID), platform badges, costs—reviewable in ~30 seconds. The folder also includes `run.log` (human-readable step-by-step narrative with stage headers and data tables) and `events.jsonl` (machine-parseable structured data for dashboards). A global `logs/trend_history.json` remembers which topics and posts were used recently to avoid repetition. Failed creatives still appear in the folder with a `SKIP_REASON.txt` file explaining why. Everything is self-contained: no external CDN, works offline, and ready to publish or archive.

**Requirement ranges owned by this file:** FR-70–89, FR-150–159, FR-230–239; NFR-20–24

## 1. Run Identity & Folder Structure (FR-70, FR-71, NFR-20)

**FR-70:** Every run receives a unique `run_id` with format `YYYYMMDD_HHMMSS_<4-char-random>`. Example: `20260808_143022_x7q2`. The run folder is created immediately at launch, before any API calls. If the run is aborted early, the folder remains with only run.log and events.jsonl inside. The disk-space pre-check is owned by 30-configuration FR-255: a test file written and deleted **inside the configured `output.dir`** (never a temp path on a possibly different volume); if that fails, the run aborts with an error before any spend.

**FR-71:** All output for a given run lives in `output/<run_id>/`. Within that folder, one subdirectory per generated creative uses the naming scheme `<asset_id>/`, where asset_id encodes: platform (Li, Ig, Tk), format (img, car, reel), a URL-safe slug of the source trend name (capped at 40 characters for Windows MAX_PATH safety), and a zero-padded per-run ordinal (e.g., `_01`, `_02`). Asset IDs are unique within a run; two creatives sharing platform + format + trend receive distinct ordinals to prevent silent folder overwrites. Example: `Li_car_dance-challenge_01/`. Brief-driven creatives (D26, override mode — no trend) define their packaging explicitly: slug derived from the brief name, meta contains `source: brief/<name>`, and the brief's own reference images (if supplied) are copied into the asset's `refs/` subfolder (brief-images only); the gallery displays a brief badge on the card. A separate global `refs/` folder at `output/<run_id>/refs/` stores brief reference images only — images as `refs/<brief_name>/image_1.jpg` etc. Note: the engine should tolerate and enable long paths in subsequent versions but must never assume Windows path limits are enforced. **Source slides store (declared v2.1.0):** Each assigned carousel draws its source slides from a run-level `source/<post_id>/` folder, containing (1) locally downloaded slides as `slide_NN.jpg` (analysis/display only, never uploaded) and (2) `source.yaml` with two provenance blocks: POST provenance `{post_id, url, author, views, published_at, caption}` and per-slide entries `{position, virlo_text, vision_text, visual_brief, brand_marks, image_file}` plus vision provenance `{model_id, status}`. This store persists across the run (deduplicated by post_id) and is referenced by meta.yaml's `panel_map`; never published (FR-72, FR-213).

**NFR-20:** The canonical latest-pointer is **`output/latest.txt`** — one line containing the `run_id` of the most recent run that successfully packaged at least one asset, written atomically (temp+rename). A junction at `output/latest/` is additionally maintained **best-effort** as a human convenience for Explorer navigation (a junction cannot be atomically replaced on Windows, which is why it is not the canonical pointer); programmatic consumers always resolve `latest.txt`. Aborted or log-only runs never claim either. Canonical locking and atomicity rules live in 30-configuration-and-run.md (FR-254).

---

## 2. Per-Asset Folders & Contents (FR-72, FR-73, FR-74, NFR-21)

**FR-72 — Publishable asset enumeration (amended v2.1.0):** Each successful asset folder contains: the final image file (JPG/PNG, zero-padded if carousel: `slide_01.jpg`, `slide_02.jpg`, etc.), a video file for reels (MP4) **plus, when the seed-frame path ran, the paid seed-frame image as `seed_frame.jpg`** (cover/thumbnail only), a `caption.txt` file holding the caption and hashtags (plain text, ready to paste into a social platform), and a `meta.yaml` file with structured metadata. **Canonical publishable set:** `slide_NN.*`, `image.*`, `reel.*`, and `seed_frame.*` (cover-only). **Never published:** the `source/` and `refs/` subfolders (FR-213 in 60-publishing) and any intermediate analysis artifacts. Only the enumerated asset files move to 60-publishing pipelines.

**FR-73** *(amended v2.0.0, v2.1.0, v2.1.2, v2.3.0, v2.4.0)*: The `meta.yaml` file is the canonical schema for all asset metadata. It records (grouped logically):

**Identity & sourcing (v2.1.0 amendments: added source_panel_count, panel_map, source_post, ref_source; v2.1.2 amendments: panel_map rows gain creator_stripped; v2.3.0 amendments: top-level copy_mode, panel_map rows gain compressed; v2.4.0 amendments: four style-match fields):**
- **`copy_mode`** (v2.3.0, new) — `verbatim` or `compress`, tracking which copy contract this asset used (D54, FR-331).
- **`style_fit`** (v2.4.0, new) — high|medium|low, result of matched-mode fit assessment; empty if `assignment: rotation` (FR-334).
- **`style_reason`** (v2.4.0, new) — short prose explaining the fit; empty if rotation-baseline pick.
- **`style_origin`** (v2.4.0, new) — rotation | matched | rotation_fallback; rotation_fallback when matched-mode call fails (FR-334, D56).
- **`style_wanted`** (v2.4.0, new) — wanted_archetype from matched-mode assessment when `fit == low`, else empty; used for gap reporting (D56).
- source (topic key / "brief/<name>")
- source_name (human-readable topic or brief name)
- platform, creative_format
- topic_key (stable slug of the topic name, for post-level recency)
- style_key (assigned style from the registry, e.g., "photoreal-ambient-caption")
- brand (the active brand selector, e.g., "hypelead")
- branded (boolean — whether this creative received a wordmark)
- copy_source_post_id (which SourcePost was quoted, e.g., "abc123def")
- copy_source_refs (v2.0.0: `{headline: "P1.hook.2", caption: "P1.caption"}` — which exact strings were quoted, for gallery provenance; **v2.3.0:** empty for compressed decks)
- source_panel_count (integer: the slideshow's original panel count, 0 for non-carousel or override-brief)
- panel_map (array [optional]: per carousel slide, `{slide, source_position, source_text_original, source_text, drop_reason, creator_stripped, chrome_counter_stripped, ref_label, **compressed**, visual_brief, source_image}` (relative path); empty for override-brief carousels. `source_text_original` is the pre-gate source text; `drop_reason` is one of: empty / contains_handle_or_url / over_budget / creator_stripped (v2.1.2; **v2.1.3 refinement per FR-319: `contains_handle_or_url` fires only for social marks; technical-URL panels are no longer dropped**); `creator_stripped` is boolean, true when the source panel line matched creator identity/chrome per FR-312 and was removed; `chrome_counter_stripped` is boolean, true when a full-line page-counter chrome (e.g. `01 / 06`, `// 02`) was dropped from the admitted panel bytes; **`compressed` is boolean (v2.3.0, D54), true when source_text was LLM-compressed; `ref_label` is empty string for compressed rows**; `source_text` is the final rendered text (or "" if dropped))
- source_post (nested object [optional, null for override-brief]: when bound post id is resolvable, `{post_id, url, author, views, published_at, caption}` — the original slide deck's provenance; when post id is bound but unresolvable from the roster, the object is `{post_id}` alone with other keys absent, marking the post as "unknown")
- ref_source (string: `"brief"` when the creative's reference images came from a brief's own supplied files, empty string `""` for all other cases — style references no longer attach post-D46)
- asset_id (full folder name including ordinal)

**Provenance & degradations (collapsed to one list, v1.6.1; v2.1.0 amendments: degradation vocabulary expanded; cite fixes applied):**
- **degradations** — a single list of tags, empty on a clean asset. Defined vocabulary (each tag's behavior owned by the FR that emits it, v2.1.0 list): `copy_not_verbatim` (FR-303), `competitor_stripped` (FR-202), `copy_degraded` (FR-99: LLM copy selection failed; bound panel-mapped carousels render panels verbatim and ship bound post's caption with loss of angle selection; images/reels render minimal sourced text), `style_refs_missing` (FR-295: **HISTORICAL** — no emitter since D46 removed the style picture channel; tag remains for gallery rendering of older runs), `no_onimage_text` (FR-100: no candidate fit the style's text budget, caption-only creative), `refs_dropped_moderation` (FR-97: brief-supplied reference images removed on content-policy retry), `text_trimmed` (FR-101: assembled text exceeded budget, trimmed at word boundary), `incomplete` (partial carousel, FR-20/95), `skipped_budget` (FR-106), `abandoned` (FR-108), `seed_frame_render_failed` / `seed_frame_url_unreachable` (FR-24), `vision_transcribed` (FR-306: on-image text supplied by vision analysis), `vision_unavailable` (FR-306: vision analysis failed or timed out, Virlo panels retained), `panels_truncated` (FR-304: carousel deck truncated to platform max), `no_fresh_post_available` (FR-307: **Two emitters:** `plan.assign` skips a creative group when a topic's fresh slideshow posts are exhausted during assignment; `copywrite` refuses a burnt bound post when the bound post ID is absent from the current topic's roster, creating a missing post condition — in either case, entry skipped). The gallery renders every tag as a badge in one loop; new tags need no schema change.
- **Event vocabulary amendment (FR-73 5b — decision):** When a bound carousel post ID cannot be resolved from the current roster, the event is emitted as `copy_post_refused` with reason string `bound_post_missing`. This is **not** a degradation tag — it is the cause string for the skip reason. The creative surfaces `no_onimage_text` (no caption, no on-image text generated) and is logged as a skip.

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
- kie_job_ids

**Quality & skip reasons:**
- gauntlet.result (pass | blocked | degraded | budget_stop | deadline_stop | skipped — 10-pipeline FR-328's vocabulary, which replaced FR-27's four vision-check states in v2.2.0; the `vision_check_result` field is retired with the machinery)
- status (pending | success | failed | **blocked** — v2.2.0 new: BLOCKED when gauntlet terminal verdict is BLOCKED; pending only between folder creation and terminal rewrite, NFR-21)
- skip_reason (one line, e.g., "kie_timeout", "disk_full", "moderation_permanent_fail", "gauntlet_blocked"; the machine-readable cause also appears as a `degradations` tag)
- **gauntlet** (v2.2.0 new, when enabled): result (pass | blocked | degraded | budget_stop | deadline_stop | skipped), degraded_gate (boolean, critic dropped as unavailable), rounds (per-round verdicts: round number, per-critic fail counts, failed frame numbers, rerendered frame count), rerenders (total rerender count for this deck), rerender_cost_usd, critic_cost_usd — the full per-round per-frame per-critic defects persist in the run's `GAUNTLET_REPORT.yaml` file

**Format-specific:**

*Carousel:*
- slide_count (actual slides delivered)
- slides_ordered (integer: total slides ordered at ASSIGN, per FR-95 deck-length rule; **new v2.1.3, FR-321**)
- missing_slide_numbers (array of 1-indexed slide ordinals that failed; the `incomplete` tag in `degradations` marks the condition. **Enumeration expanded v2.1.0:** all missing slides listed, not capped at 3)

*Reels:*
- reel_audio (true | false)

**Posting (Phase 2):**
- postiz_draft_id, postiz_post_id, postiz_state (uploaded | scheduled | published | draft)
- postiz_media_ids (array of Postiz media resource ids)

**Logging & audit:**
- event_id (pointer to events.jsonl record, e.g., "ev_20260808_1234")
- virlo_url (if trend-sourced)

**FR-74:** If a creative fails to generate or is skipped (e.g., Kie.ai job timeout, budget exhausted), the asset folder still exists and contains: the already-paid artifacts (caption.txt and meta.yaml with status: failed or **blocked**) alongside a `SKIP_REASON.txt` file with a one-line reason. **v2.2.0 amendment (D49):** When a deck is BLOCKED by the gauntlet (leakage tier defects standing after final round), the assets are **kept** (FR-74 applies: artifacts preserved), `meta.yaml` records `status: blocked`, and a `BLOCKED.txt` file contains one plain-language paragraph describing the defect(s) found, plus a pointer to `GAUNTLET_REPORT.yaml` for full defect details. Example: `SKIP_REASON.txt` contains "Gauntlet defect: identity_leak on slide 3 (creator name detected)" and `BLOCKED.txt` expands with context. A BLOCKED creative does not record trend-history use (§8 below) and does not satisfy `set_latest` on its own.

**FR-322–330 gauntlet outputs (v2.2.0):** When gauntlet is enabled, every deck after RENDER stage (before CHECK/PACKAGE) passes through three independent fresh-context critics (`brief`, `system`, `craft`). The run-level `GAUNTLET_REPORT.yaml` carries full per-frame per-critic defects (code/zone/confidence/detail) for every round and deck, formatted as YAML for operator review. Console line per round (see FR-296 below). Defect codes, zones, and confidence levels per critic defined in `20-integrations.md` FR-322–330. Outcomes: PASS (no defects), BLOCKED (leakage tier defects standing, deck not published), DEGRADED (contract-tier defects handled per `fail_action`), BUDGET_STOP/DEADLINE_STOP (spend/runway gate), SKIPPED (all critics unavailable, ships tagged). When any critic is unavailable (LLM error → retry → failure), the deck is tagged `degraded_gate` and the run continues with remaining critics; all critics unavailable → SKIPPED (ship as-is, tagged, never BLOCKED).

**FR-337 — Style-match provenance in outputs (v2.4.0, new; D56).** When matched assignment is enabled, every asset carries four new metadata fields in `meta.yaml` (FR-73 amendments v2.4.0): `style_fit` (high|medium|low), `style_reason` (short prose), `style_origin` (rotation | matched | rotation_fallback), `style_wanted` (wanted_archetype when `fit == low`, else empty). Gallery card labels show assigned style with origin annotation: `style: X · matched/high` (matched-mode pick) or `style: X · rotation` (rotation baseline or fallback). On fallback cards (when matched-mode call fails or entry receives `low` fit), the `style_wanted` field is displayed as a note for operator review ("wanted archetype: listicle card deck"). ASSIGN console receipt gains origin/fit/reason columns per entry. One gap-report block appears after the ASSIGN loop, listing all distinct `wanted_archetype` values found in low-fit entries, so the operator can plan missing styles deliberately. New events.jsonl event type: `style_match` (per-run, captures matcher call outcomes and any degradation; detail-only, never console).

**NFR-21:** Asset folder creation is atomic: the folder and its `SKIP_REASON.txt` (if needed) are written immediately after a decision to skip. **`meta.yaml` is written at folder creation with `status: pending` and rewritten by temp-file+rename at terminal status; the final image/video is stored to disk afterward, and any optional vision-check reads from disk and overwrites in place on retry.** The core invariant: media is never present in a folder without its corresponding `meta.yaml`, because the gallery and the Phase 2 publisher both read it. This avoids partial-asset confusion.

---

## 3. Gallery HTML File (FR-75, FR-76, FR-150, NFR-22)

**FR-75 — Self-contained gallery (amended v2.1.0):** One HTML file per run, named `gallery.html`, resides at `output/<run_id>/gallery.html`. It is **entirely self-contained**: all CSS is inlined in a `<style>` block, all images/videos are referenced via relative paths only — sibling asset folders (e.g., `./Li_car_dance_01/slide_01.jpg`), the `refs/` folder, or the `source/<post_id>/` folder — and no external CDN resources are loaded. Hotlinks to Virlo, Kie.ai, or any cloud URL are forbidden. Small inline scripts are allowed; no external resources, no rating widgets. The file works offline in any browser. **Atomic writing:** every incremental rewrite uses a temporary file + rename, ensuring that a crash mid-write never leaves a truncated file for an open browser tab.

**FR-76** *(amended v2.2.0, D49)*: The gallery is written **incrementally**: as soon as images land from Kie.ai, a first version is written to disk, allowing the user to review finished images while reel generation continues. The gallery is refreshed at run end with final counts and any newly completed reels. Each card displays: a preview (image thumbnail; reels render as `<video preload="metadata">` so the browser shows the first frame itself — **no poster-frame extraction, which would need ffmpeg** — with `seed_frame.jpg` as the `poster` attribute when it exists), the caption text, platform/format/brand badges, the assigned style key, estimated cost, the source topic name, the quoted post author/views/post-id (from meta.yaml provenance block), and relevant source details per FR-309. **v2.2.0 amendment:** BLOCKED decks receive a distinct visual badge (e.g., "BLOCKED: [reason]") in the gallery, separate from the failed-card rendering, with a link to `BLOCKED.txt` for full defect details. For carousel cards, a three-part structure shows provenance, source slides, and rendered slides aligned by index (FR-309). For images and reels, the current single-card format applies. The gallery title is set from config value `gallery.title` only; no grouping or ranking widgets. The gallery header documents the selection mechanism (see FR-231 below). Gallery path printed both at first card land and in exit block (FR-296/FR-297). **Run-summary column (v2.2.0):** the gallery header/summary line enumerates delivered items distinctly: e.g., "delivered 4 images, 1 complete carousel, 1 partial carousel, 1 BLOCKED deck".

**FR-309 — Carousel provenance gallery (v2.1.0, new; amended v2.3.0):** For each carousel asset, the gallery displays a three-part card structure:

1. **Provenance header:** Author, publisher URL (permalink), view count, publication date, and the original creator's caption (in source language). Virlo's AI-generated summary text, if present in data, may appear only as labeled context, never attributed to the original creator. **v2.3.0 amendment (D54):** when `meta.yaml.copy_mode == "compress"`, the header gains a label "compressed from N chars" (computed from the maximum `source_text_original` length across all rows in `panel_map`, representing the LLM's starting point).

2. **Source panel strip:** A horizontal sequence showing each original slideshow slide in order (locally downloaded, never hotlinked), with its extracted text and visual brief displayed below. Slide positions match the source deck exactly. Text extraction reflects the on-image words (verbatim from the source panel where present, or from vision transcription); visual briefs are concise descriptions of graphics/charts/icons/layout for reproduction context. All references are relative paths into `./source/<post_id>/…`, never external URLs.

3. **Rendered slide alignment:** Our generated slides rendered beside their corresponding source slides (by panel index), enabling side-by-side fidelity review. **v2.3.0 amendment:** per-slide rendering labels on compressed rows show "compressed from N chars" (using that row's `source_text_original` length).

**Override-brief carousels** (brief_influence == "override", no source post) fall back to the current single-card format (no source panels; panel_map empty, source_post null in meta.yaml). **Images and reels** retain their current card layout (single preview, caption, metadata). Both formats may display a source URL and caption if from a trend, but they carry no panel-mapped structure. All gallery references use relative paths only; no Virlo, Kie.ai, or cloud URLs appear in the rendered HTML. Cross-refs: FR-71 (source/<post_id>/ storage), FR-72 (publishable enumeration excludes source/), FR-75 (self-contained offline requirement).

**FR-150** *(amended v2.1.0)*: Gallery footer SHALL state the fidelity rating rationale: "judge **style adherence**, **topical accuracy**, and **panel fidelity**" — does this creative match the assigned visual style, the source topic/post, and the original slides' words and visuals (for carousels)? The footer clarifies that our slide texts and visuals are sourced from the original deck and reproduced in our house style, not cloned from reference images.

**NFR-22:** Gallery generation never blocks asset delivery: if HTML generation fails (e.g., a template error), the run completes and assets remain on disk; the run log notes the failure and points to the asset folders. Color scheme uses `prefers-color-scheme` CSS media query only (no user toggle).

---

## 4. Run Log: Human-Readable Narrative (FR-77, FR-78, NFR-23)

**Logging ownership:** This file owns the logging specification. Verbosity is controlled by enum `normal|verbose` only (no debug level or debug folder). Full prompts and full payloads are ALWAYS written to `events.jsonl` (machine-readable); `run.log` carries one-line digests and the complete chronological human narrative.

**FR-77** *(amended v2.0.0)*: Every run writes `output/<run_id>/run.log`, a chronological human-readable narrative log including:
- Launch summary: run_id, launch timestamp, chosen config file, resolved run parameters (formats, counts, spend cap, platforms/languages, brand + ratio).
- **Stage headers** (FR-296, v2.1.0): `[n/N] STAGE_NAME (window: <descriptor>)  in_count -> out_count  elapsed` for each pipeline stage (COLLECT, TOPICS, FILTER, SELECT, ASSIGN, COPY, RENDER, CHECK, DONE), with the N computed from the resolved plan (brief-only runs have fewer stages; `vision_check: false` omits CHECK). Every header states counts in → counts out, so a drop is arithmetic. COLLECT stage header includes recency window description (e.g., "within 30 days" per max_post_age_days setting).
- **Topics table** (v2.0.0, after FILTER): ranked list with topic name, monitor, post count, total views, median views, computed strength, and filter verdict (`keep`, `strip: <names>`, or `skip: <reason>`).
- **Per-topic post roster** (FR-297, v2.1.0, after SELECT): for paid topics, top 3 posts × top 3 topics default, showing author, views, publication date/age (backed by real published_at from Virlo), post ID, and which creative quoted it (sibling divergence proof). Age column now reflects Virlo's published_at timestamp, resolving prior inconsistencies.
- Each MCP server call: name, operation, duration, and result summary that carries the count — e.g., "Virlo MCP: 2 monitors → 14 topics, cap 9/monitor". The count is required, not decorative.
- **Per-creative narrative:** topic, platform/format, style assigned, brand yes/no, full prompt text, Kie.ai job id, poll timeline, download time, result (success with cost, or failure reason).
- **Moderation fallbacks** (references dropped on retry, marked `refs_dropped_moderation`).
- Vision-check verdicts (pass/fail, reason, retry action).
- **Preview-mode outputs** (if `--preview-sources` or `--preview-analysis` was used).
- Budget tally after each spend: running total, remaining cap, percentage spent.
- **Provenance block** (v2.0.0, before spend summary): per creative, topic, style, brand, source post (author, views, post ID), and quoted text for verbatim copy.
- **Funnel** (v2.0.0, once at DONE): topics collected, filter verdicts (keep/strip/skip counts), branded count.
- Final summary: total creatives generated, total spend, skipped count and reason summary, warnings/errors, wall-clock time, success/partial-success/failed status, gallery path.

**FR-78:** Timestamps use ISO 8601 format (e.g., `2026-08-08T14:23:47.123Z`); durations are in milliseconds (e.g., `342ms`).

**NFR-23:** The run log is flushed to disk after every event (Virlo fetch, trend ranked, creative submitted, job polled, etc.), ensuring that if the run is interrupted, the log tail is always truthful and reflects the last known state. Logs live in `output/<run_id>/` (run.log + events.jsonl); `logs/trend_history.json` stays global.

---

## 5. Structured Events Log (FR-80, FR-81)

**FR-80** *(amended v2.2.0, D49–D53)*: Every run writes `output/<run_id>/events.jsonl`, a newline-delimited JSON file with one JSON object per event. Each event contains: timestamp, event_type (e.g., "virlo_fetch_complete", "topic_ranked", "topic_posts", "topic_filter_verdict", "virlo_fields", "stage_complete", "creative_submitted", "job_polled", "vision_check_result", **"gauntlet_round", "gauntlet_rerender", "gauntlet_blocked", "gauntlet_budget_stop", "gauntlet_deadline_stop", "gauntlet_critic_unavailable", "gauntlet_fix_truncated", "critic_empty_fail", "ocr_repaired", "panel_counter_stripped"**), and a `data` object with all relevant fields. New v2.2.0 gauntlet events (all detail-only, never console): `gauntlet_round` (per round: deck id, round number, per-critic fail counts, failed frame numbers, re-render trigger decision), `gauntlet_rerender` (per rerender: frame, fix suffix applied, cost), `gauntlet_blocked` (terminal BLOCKED verdict: deck id, reason summary), `gauntlet_budget_stop`/`gauntlet_deadline_stop` (gauntlet halted early), `gauntlet_critic_unavailable` (critic dropped), `gauntlet_fix_truncated` (fix suffix exceeded 600 chars), `critic_empty_fail` (critic returned empty defect, treated as pass), `ocr_repaired` (logged confusable-token repair applied pre-admission), `panel_counter_stripped` (logged per creative when page-counter chrome is stripped from a carousel panel at panel admission, with line details). Prior v2.0.0 events: `topic_ranked`, `topic_posts`, `topic_filter_verdict`, `virlo_fields`, `stage_complete`.

**FR-81:** Both run.log and events.jsonl are written concurrently as each event fires; they are always in sync. **Writes are serialized through a single writer** (all writes on the event loop with no `await` inside a write, or one lock) so concurrent tasks can never interleave partial lines — a torn JSONL line breaks every downstream parser of events.jsonl. Verbosity (FR-299: `log_verbosity` vs `console_verbosity`) does not affect events.jsonl; it always contains full detail.

**FR-152 — Secret redaction at the logging boundary (D30).** No API key or Authorization header ever reaches run.log or events.jsonl: auth headers are stripped from logged request/response payloads before writing, and any value matching a configured secret is replaced with `[REDACTED]`. Since prompts are logged in full, this pairs with D30's guarantee that secrets are never interpolated into any prompt or template in the first place — redaction is the backstop, not the primary defense.

**FR-153** *(amended v2.1.0)*: Post recency tracking in trend history. The file `logs/trend_history.json` carries an optional `posts` key holding a map of post IDs (Virlo UUIDs) used on that trend. **Canonical mapping form:** `"posts": { "<post_id>": { "date": "2026-08-10", "url": "https://virlo.ai/post/xyz" }, ... }`. **Legacy pipe-delimited form** (still parsed for backward compatibility during reads): `"<post_id>": "2026-08-10|https://virlo.ai/post/xyz"` is recognized but not written (one-way migration). This tracks post-level recency; the feature is fully backward compatible — an entry without the `posts` key reads as "no post-level recency tracked" and requires no migration. When this key is present, it is pruned on the same pass as entries, against the same `max(trend_history_days, 90)` horizon. Writing is serialized through a single lock, ensuring atomic updates and never two concurrent writes.

**FR-155** *(amended v2.1.0)*: Virlo funnel report. A **run-wide rollup** emitted once per run showing topic input, filter verdicts, post-level drops, and branded count — printed **once at DONE** (v2.0.0 FR-297 replaced the funnel's per-stage placement with stage headers; the funnel is a summary-only line). The report lives in `events.jsonl` as a machine-readable `collect_funnel` event with nested objects. Printed lines ≤78 chars per FR-286. Input/output vocabulary: INPUT (Virlo evidence): topics, posts, slideshows; OUTPUT (generated): images, carousels, reels, creatives. **Post-level drop vocabulary (FR-305, printed as three lines with zero-count lines included):** `dropped_stale` (age > max_post_age_days), `dropped_unenriched` (missing panel_count or usable text), `dropped_used` (already quoted in history window). **NOT in the pre-flight cost estimate** — Collect happens after Confirm, so no Virlo number exists when the estimate prints. Funnel counting: topics in → topics kept/stripped/skipped; a number appears in exactly ONE of {stage header, topics table, funnel, spend row}.

**Event-shape amendments (v2.1.0 updates):**
- **`virlo_payload` event (FR-301):** Include three fields to the `data` object: (1) `rows_fetched` (integer: count of rows returned by endpoint before any filtering), (2) `dropped_stale` (integer: rows excluded by age cap), (3) `dropped_unenriched` (integer: rows without panel_count or image_urls), (4) `dropped_used` (integer: rows already quoted in trend history). The message field explicitly states the post-dedupe and post-filter state: "After dedup and filtering: X slideshows available" — matching the count that enters the topic pool.
- **`kie_job_submitted` event:** Add (1) `reference_count` (integer: how many reference images attached to this job), (2) `reference_sources` (array of strings describing each source, one per reference image, e.g. `["brief logo.png (upload)"]` — no "Virlo post", "motion video", or "style reference" entries; reference_count 0 is the normal case for text-only renders).
- **`topic_posts` event (FR-305):** Emitted per topic after SELECT, listing all SourcePosts ranked. Each post entry includes `{post_id, url, author, views, published_at, format, panel_count, image_count}` and a `vision_status` flag. This event exposes every candidate post, enabling forensic verification of the pick-time selection.
- **`virlo_fields` event (FR-306):** Per monitor, lists `{fields_present, fields_consumed, fields_ignored}`. The `description` field is deliberately context-only (consumed by prompts for context, never output or rendered in any caption or on-image text).

---

## 6. Trend History & Recency Exclusion (FR-82, FR-83, NFR-24)

**FR-82 — History key format (amended v2.2.0, D49):** The file `logs/trend_history.json` is a simple JSON object where keys are trend keys with format `<monitor_id>::<topic_key>` (the colon pair separates the Virlo monitor from the normalized topic slug defined in 20-integrations §3) and values are objects containing: first_used (ISO 8601 date), last_used (ISO 8601 date), run_ids (array of run IDs, **capped at the most recent 5**), and optionally posts (an object mapping post IDs to their last-used date — FR-153). **A trend is recorded in history ONLY if at least one creative on that trend was packaged successfully as non-BLOCKED** (i.e., final image/video/carousel delivered to the asset folder with status `success` or `degraded`, not `blocked`, not skipped — v2.2.0 amendment: BLOCKED creatives do not consume trend/post history, so a BLOCKED deck never precludes future use of the same trend/post). This file is read at trend-selection time and updated after packaging. **On every write, entries whose `last_used` is older than `max(trend_history_days, 90)` days are pruned, and the `posts` map within each entry is also pruned on the same pass** — the file is a rolling window, not an unbounded archive rewritten under a lock on every run. An entry without the `posts` key reads as "no posts recorded for this trend" and requires no migration. **Binding sentence (v2.2.0):** a BLOCKED creative does not record trend-history use and does not satisfy `set_latest` on its own (40-outputs FR-74).

**FR-83:** If `trend_history.json` does not exist or is corrupted, the engine logs a warning ("trend_history.json missing or invalid; starting fresh") and proceeds without penalties. It never crashes due to history state. The file is created fresh if missing.

**NFR-24** *(amended v2.1.0)*: The no-repeat window is configured via `trend_history_days` (default **30**, invariant `≥ sources.max_post_age_days` per FR-307; cross-ref 30-configuration-and-run.md); at selection time, any trend or post with `last_used` within the past N days is excluded. **When a run is interrupted, rerunning safely skips only successfully-packaged trends and posts** (those recorded in history) and tries remaining trends and unused posts again — the interrupted-run resume property applies at both trend and post granularity because both dimensions share the same history file.

---

## 7. Spend Summary & Budget Tally (FR-84, FR-85)

**FR-84 (simplified v1.6.1, amended v2.1.0):** At the end of every run, the summary opens with one headline line — **"requested N creatives, delivered M"** — so a scheduled run that was trimmed, shrunk by trend supply, or dropped reels is legible at a glance without decoding the exit code. Below it, **one** spend table is printed to the console and written to run.log: one row per creative with **estimated** vs. **actual** (tallied on submission, failures included) vs. **delivered**, a subtotal row per format, and a grand-total row splitting LLM vs. render spend (reasoning tokens included). Actual spend reconciles to Kie-reported cost; timed-out jobs reconcile at the provider-reported amount (0.0 when none reported). Closing lines state: budget cap status, counts skipped by budget/deadline with reason summary, and any "governance partial — N lines unpriced" banner. The former separate per-category, per-platform and per-format tables are deleted — events.jsonl carries everything a future dashboard would need.

**FR-85:** Unknown costs (where provider did not return billing data) are marked **"estimated"** (no "pending reconciliation" language).

---

## 7a. Partial-Delivery Reporting (FR-321)

**FR-321 — Loud partial-delivery reporting and retry verdict provenance (new, v2.1.3).** Incomplete carousels are made audible in four places:

1. **meta.yaml dual recording:** Every carousel carries both `slide_count` (actual slides delivered) and `slides_ordered` (the deck length at ASSIGN per FR-95) in the metadata, making partial delivery machine-readable: "7 of 8 slides" is the report.

2. **Spend table per-carousel delivery marking:** When slides are missing, the spend table per-carousel row displays either `7/8` or a `partial` badge instead of a bare `yes`. A deck missing any slides **must never read as an unqualified success** — the spend table is where the operator first scans the result.

3. **Gallery header partial-deck count:** The gallery's opening summary counts delivered items including partial carousels distinctly (e.g., "delivered 4 images, 1 complete carousel, 1 partial carousel").

4. **Post-gauntlet logging:** The gauntlet-driven verdict and re-render history (FR-322–330) is logged to `events.jsonl` as `gauntlet_round` / `gauntlet_rerender` / `gauntlet_blocked` events; the metadata field records the full `gauntlet` block with per-round outcomes (40-outputs §2). Legacy `vision_check_result` field (from v2.1) is deprecated in favor of gauntlet tracking.

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

**FR-154** *(amended v1.8.0, v2.0.0)*: Preview-mode exit codes. `--preview-sources` and `--preview-analysis` SHALL exit 0 (success) when at least one topic is eligible for a run; they SHALL exit 3 (fatal — zero usable topics) when zero topics are eligible after filtering; they SHALL exit 2 on config error or missing credentials, matching the general exit-code vocabulary of FR-202. A preview mode that returns topics but all are excluded (history, usability) is a zero-eligible situation and exits 3.

**FR-296** *(amended v2.2.0, D49)*: Stage narration and console liveness. The run SHALL emit numbered stage headers for every pipeline stage: `[n/N] STAGE_NAME  in -> out  elapsed`, with N computed from the resolved plan (brief-only runs have fewer stages; gauntlet: false omits GAUNTLET). Every header states counts in → counts out, so a drop is arithmetic. Stages with waits print the header twice (opening `...` form on submit, closing form with elapsed). **Gauntlet stage headers (v2.2.0):** `[7/N] GAUNTLET deck Li_car_… round 2/3 — 2 frame(s) failed (brief: invented_text s4; craft: contrast s2) — re-rendering 2` — one line per round, showing deck id, round number, per-critic defect summary, and rerender count. Collect liveness: a `collecting from N monitor(s)...` opener and the four virlo warning sites routed through the same `say` seam (no bare stderr leakage). Root logger decision in __main__.main so logger.warning stops leaking to stderr (FR-286 established the 78-col ceiling; FR-296 establishes the liveness principle).

**FR-297** *(v2.0.0, new)*: Sort-proof identity surfaces. (a) **Topics table**, printed once after FILTER, ALL topics one line each, showing rank, topic name, monitor, post count, total views, median views, computed strength, and filter verdict (`keep`, `strip: <brands>`, or `skip: <reason>`). Rows ≤78 cols; compact numbers (12.4M, 980K); caption states the strength formula and that views/median are the topic's OWN posts, min-maxed across the full pool — the monotonically non-increasing `strn` column IS the sort proof. (b) **Per-topic post roster** after SELECT, for paid topics (top 3×3 default; `--verbose`/previews uncapped): `P1  @author  4.9M  2d  <post_id>  <format>  -> 01` — the `P` ordinals are EXACTLY the reference labels offered to the copy LLM, and `-> NN` names the creative that quoted it (makes sibling divergence observable). Permalink alone on its own line. (c) **Provenance block** at DONE, before the spend table: per creative `id · format · topic · style · sig(branded) · cost · ok` + a verbatim receipt line `quoted P1 @author 4.9M <post_id> "<first ~24 chars>"` + a third line only on loss. (d) Funnel (FR-155) prints once at DONE, replacing per-stage placement.

**FR-298** *(v2.0.0, new)*: Forensic events and provenance fields. New events.jsonl events: `topic_ranked` (full table rows incl. raw components), `topic_posts` (per topic, every SourcePost `{post_id, url, author, views, published_at, format, panel_count, image_count, vision_status}` in rank order — field set amended v2.1.0), `topic_filter_verdict` (`{ordinal, topic_key, verdict, brands_to_strip, reason}`), `virlo_fields` (per monitor: `{fields_present, fields_consumed, fields_ignored}`), `stage_complete` (per stage). meta.yaml += `copy_source_refs` (`{headline: "P1.hook.2", caption: "P1.caption"}` — which exact strings were quoted, so gallery shows "quotes P1.hook.2 verbatim"). `trend_history.json` post entries gain the post URL beside the date.

---

## Design Decisions

**D9 — Output = per-asset folders + gallery.html:** Self-contained asset folders enable easy share/archive/republish; the gallery provides a single-page overview. Simple folders + structured logs reduce complexity.

**D12 — State = trend-history JSON + full run log:** Trend history (dates + keys, plus an optional post-recency map per trend — FR-153) enables simple recency checks without a database. Full human-readable + machine-parseable logs enable audit trails and future analytics without a query interface.

---

## Summary

Output and logging are user-centric and transparent. Each run is self-contained in a timestamped folder; every creative is traceable to its source and parameters; the gallery enables instant visual review with fidelity judged against source references. The lean strategy (text + JSONL + global trend history) avoids over-engineering while supporting future analytics. Budget accountability, error reporting, and incomplete-result handling follow: **degrade and report, never silently fail.**
