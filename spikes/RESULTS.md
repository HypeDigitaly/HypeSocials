# Day-One Spike Results (T0.3)

> **SPIKE — RETIRED after Wave 1. Never imported by production code.**
> Every file in `spikes/` carries that header. This document is **authoritative for T1.1 / T1.3 / T1.4**:
> where it contradicts a PRD statement, the PRD statement is a fact-error and needs a D15 amendment —
> the code follows this file for API shapes, and follows the PRD for behaviour.

**Executed:** 2026-08-09 · Windows 11, Python 3.13, `.venv` · repo root `C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials`
**Actual spend:** Kie **576 credits = $2.88** (start 9404.0 → end 8828.0) · OpenRouter **$0.00014** · Virlo **$0.25** of a $5.00 deposit.
Kie spend overshot the ~$2.50 guidance by $0.38 because the *unknown being measured* (Seedance's unit price) turned out to be ~5× the PRD's assumption. One 5 s render was authorised; one 5 s render was billed. See §C.

---

## TL;DR — Verdicts

| # | Spike | Verdict | One sentence |
|---|---|---|---|
| A | Virlo live smoke (5 endpoints) | **PASS** | All 5 endpoints 200; 3 real monitors recorded; **OQ-19 answered — Virlo meters per call in response headers** and only `/trends/digest` costs money ($0.25/call). |
| B | GPT Image 2 reference honoring (OQ-17 residual) | **PASS — strongly** | References drove palette, layout, typography, components and blob geometry into a different aspect ratio; **not** a stop flag. |
| C | Seedance image+video refs (OQ-21) | **PASS** | One job accepted **and successfully rendered** with `reference_image_urls` + `reference_video_urls` together; **not** a stop flag. |
| C | Seedance measured price (OQ-2) | **SETTLED — ⚠ PRD CONFLICT** | 5 s / 720p / 1 image ref / 10 s video ref = **570 credits = $2.85**, i.e. **~5× the PRD's $0.40–0.60 reel target**; billing charges *input video seconds too*. **D15 amendment required before reels are enabled.** |
| D | mkv upload spot-check + real mp4 upload | **PASS (with caveat)** | `.mkv` accepted by the upload API (HTTP 200) but returned as `application/octet-stream`; upload acceptance ≠ renderer decode support, and Seedance still documents mp4/mov only. |
| E | Luna strict schema + reasoning (OQ-22) | **PASS** | Strict `json_schema` composes with reasoning; **but `temperature` is unsupported by Luna *and* Sonnet 5 — sending it with `require_parameters` returns 404.** |
| F | Windows double-SIGINT on ProactorEventLoop | **PASS** | Exact working pattern proven twice; `loop.add_signal_handler` raises `NotImplementedError`; real Ctrl+C hits the whole console process group. |
| G | OQ-20 retention | **PARTIALLY SETTLED** | Upload URLs carry `cache-control: max-age=86400` (24 h, corroborates the claim); result URLs carry **no** expiry header at all — the ~14 d figure is undemonstrable from responses. |

### Stop-flag status

**NEITHER defined STOP FLAG fired.** References *are* honored (B), and Seedance *does* accept the image+video combo (C). The build may proceed.

**However, one blocker-class finding sits outside the two defined triggers and must not be smoothed over:**

> ⚠ **Reels cost ~5× what the PRD budgets, and the reference video is billed.**
> `Cost = unit × (input_video_seconds + output_seconds)` when a video reference is attached.
> With the shipped default `reel_reference_max_s: 28`, a single 5 s 720p reel costs **1254 credits = $6.27** —
> more than half the default $10 spend cap, for one creative. The PRD's success-metric target (reels
> $0.40–0.60) and `price_per_unit.reel_second` (a single scalar) cannot express the real pricing.
> **This needs a D15 amendment before `formats.reel` is raised above 0.** Details and the exact
> break-even rule in §C.

---

## A. Virlo live smoke — **PASS**

**VERDICT:** All five documented endpoints return HTTP 200 against `https://api.virlo.ai/v1` with `Authorization: Bearer <VIRLO_API_KEY>`; three real monitors exist; **OQ-19 is answered from response headers**; four of the five documented tool-return shapes differ from the PRD table in ways that change the wrapper's normalization code.

### Real monitor ids (needed for the Wave 3 live run)

| `virlo_monitor_ids` value | Name | Platforms | Keywords (n) | Last run | Intelligence |
|---|---|---|---|---|---|
| `9c96fddf-dc35-4be0-bbd9-12f4d22aea12` | AI Trends Tracker | youtube, tiktok, instagram | 12 | 2026-08-09T06:43:19Z | `data_intelligence_enabled: false`, but `analysis_data` fully populated |
| `623203a9-c09c-4763-85e0-1c177b5af760` | AI Trends Tracker v2 (intelligence) | youtube, tiktok, instagram | 7 | 2026-08-09T04:43:40Z | `data_intelligence_enabled: true` |
| `65bf412a-2a8a-4e95-bf35-9f21dca208a6` | CZ coverage probe – AI/business Czech market | youtube, tiktok, instagram | 5 (Czech) | 2026-08-06T20:34:21Z | — |

All three are `active: true`, `is_recurring: true`, weekly cadence `0 0 * * 0`.
**Sub-endpoints in this spike were exercised against `9c96fddf-…` only.** The `623203a9-…` monitor is the one flagged as the intelligence-enabled variant and is the better default if `intelligence_status: "ready"` coverage matters (see below).

### HTTP statuses & metering (OQ-19 — **ANSWERED**)

| Call | Status | `x-cost` | `x-credits-used` | Rate-limit headers |
|---|---|---|---|---|
| `GET /v1/agents` | 200 | `0.00` | `0` | `x-ratelimit-limit: 10000` |
| `GET /v1/agents/{id}` | 200 | `0.00` | `0` | `x-ratelimit-limit: 10000` |
| `GET /v1/agents/{id}/videos` | 200 | `0.00` | `0` | `x-ratelimit-limit: 10000` |
| `GET /v1/agents/{id}/slideshows` | 200 | `0.00` | `0` | `x-ratelimit-limit: 10000` |
| `GET /v1/trends/digest` | 200 | **`0.25`** | **`25`** | `x-ratelimit-limit: 50` |

Metered calls additionally return `x-credits-remaining: 500` and `x-balance-remaining: 5.00` (USD).
Free calls omit the balance headers entirely.

**Consequences for the build:**
- `--preview-sources`'s "$0" claim is **literally true** for the four agent endpoints and **false by $0.25** if the run fetches the digest. Recommend the digest be gated (config key or preview-mode skip) — 20-integrations §3's join rule fetches it "once per run" for enrichment only, at 25× the cost of everything else combined.
- Remaining Virlo balance at end of spike: **$4.75** ≈ 19 further digest calls. Flag to the operator before the Wave-3/M1 live runs.
- Log `x-cost` / `x-credits-remaining` per Virlo call in `events.jsonl` — the metering answer is free and already in the response.

### Response shapes (top-level keys → one example item, values truncated)

**`GET /v1/agents` (`list_monitors`)**
```
{ code?, data: { limit: 50, page: 1, count: 3, agents: [
    { id, name, is_recurring, active, team_id, source, keywords[], platforms[],
      exclude_keywords[], exclude_keywords_strict, meta_ads_enabled,
      data_intelligence_enabled, english_only, intent, intent_keywords[],
      autonomy_level, autopilot_unlocked, cognition_enabled, cadence,
      next_run_at, last_run_at, is_processing, created_at, updated_at } ] } }
```
- **Surprise vs PRD:** the array is nested at `data.agents`, not at the top level. **Corrected 2026-08-11 (live probe):** `/agents`, `/videos` and `/slideshows` all paginate by **`page`** (1-indexed), not by two different idioms. There is ONE idiom. Requests that include `offset` as a parameter return HTTP 400 `{"message":["property offset should not exist"]}`.
- `list_monitors` must normalize away 20 fields to reach the documented `id + name`.

**`GET /v1/agents/{id}` (`get_monitor_analysis`)**
```
{ data: { id, name, …monitor config…, analysis, analysis_data: {
      themes: [ { name, tactics[], confidence, stable_key, video_count,
                  why_it_works, evidence_video_ids[] } ],
      overview: { avg_virality, total_videos },
      key_highlight, viral_tactics[], excluded_videos[],
      timing_analysis: { pattern, peak_hours[] },
      top_10_breakdown: { videos[{video_id, description}], intro_header, intro_subheader },
      connecting_thread },
    analysis_batch_start, analysis_batch_end, pending_jobs[], finalized,
    latest_run: { id, agent_id, status, total_videos_inserted, …, keyword_breakdown[] } } }
```
- **Surprise vs PRD (material):** `tactics[]`, `why_it_works`, `confidence`, `video_count`, `timing_analysis` and `connecting_thread` — the fields the PRD's table attributes to **`get_trends`** — actually live **here**, under `analysis_data`. The 20-integrations §3 tool-return table has these two rows swapped in substance.
- `analysis_data.themes[]` is 9 themes deep for this monitor and is the real raw material for a style brief's "why it works" context.

**`GET /v1/trends/digest` (`get_trends`)**
```
{ data: [ { id, title: "Trends for Aug 9", region: "global", local_date, trends: [
    { ranking, trend: { id, name, description, trend_type },
      momentum: { score, status, views_per_hour, updated_at },
      velocity_today_count, velocity_median_views, detected_at, last_seen_at,
      origin_region_codes, global_confidence, exemplar_count, scrape_status,
      id, trend_id, trend_group_id,
      top_exemplars: [ { video_id, url, platform, views, thumbnail_url,
                         publish_date, author: { username, avatar_url, verified } } ] } ] } ] }
```
- **Absent** (contra PRD): `tactics[]`, `why_it_works`, `timing analysis`, `connecting threads`, `video_count`. `global_confidence` is present but **`null`** for every one of the 15 trends.
- **Present and unclaimed:** `momentum.views_per_hour`, `velocity_median_views`, `exemplar_count`, and `top_exemplars[5]` with real post URLs + thumbnails — i.e. the digest *is* a usable media source, just not the one the PRD describes.
- Returns a *daily trend group* (15 ranked global trends), not per-monitor items — consistent with the PRD's "never creates trend items of its own".

**`GET /v1/agents/{id}/videos` (`get_top_videos`)**
```
{ data: { agent_id, agent_name, total: 2039, limit: 50, offset: 0, videos: [
    { id, url, description, platform, views, likes, shares, comments, bookmarks,
      publish_date,
      author: { country, username, verified, followers, avatar_url },
      hashtags[], thumbnail_url, keyword_found_by, is_duet, is_stitch,
      upload_region, upload_region_source,
      intelligence: { primary_topic, secondary_topics[], keywords[], category,
                      content_format, visual_format, background_type,
                      foreground_type, hook_text, hook_type, visual_hook_type,
                      transcript_quality, transcript_word_count, language_detected,
                      speaking_style, emotional_tone, sentiment, has_face_visible,
                      has_onscreen_captions, caption_style, has_text_overlay,
                      text_overlay_content, text_overlay_purpose, visual_complexity,
                      brand_safety_tier, is_nsfw, is_educational, is_sponsored,
                      brands_mentioned[], cta_usages[], trend_references[],
                      social_proof_used[], summary, low_confidence_fields[] },
      intent_match, sound, intelligence_status } ] } }
```
- Every PRD-claimed field is present. `hook_text`, `text_overlay_content`, `summary` are **nested inside `intelligence`** and exist **only when `intelligence_status == "ready"`** — in this 50-item sample that was **14/50 ready, 36/50 `"disabled"`**. The wrapper must treat them as optional, and Select's usability filter (FR-6) should account for a ~70 % miss rate on this monitor.
- **No `duration` field anywhere** → the yt-dlp metadata probe (FR-160) is genuinely load-bearing, not belt-and-braces.
- **Duplicates occur** in the returned array (`@marcinteodoru/video/7671470941230140702` appeared twice in the top 8 by views). The join rule needs a dedupe on video `id`/`url`.
- Platform mix in sample: tiktok 27, youtube 22, instagram 1.
- **Corrected 2026-08-11 (live probe):** Pagination response fields are `total: 2039`, `limit: 50`, `offset: 0` — these are **output echo fields only**, not accepted request parameters. Requests are paginated by **`page`** (1-indexed); the response echoes the derived `offset` for informational purposes.

**`GET /v1/agents/{id}/slideshows` (`get_top_slideshows`)**
```
{ data: { agent_id, agent_name, total: 635, limit: 50, offset: 0, slideshows: [
    { id, url, description, platform, views, likes, shares, comments, bookmarks,
      publish_date, author: { username, verified, followers, avatar_url },
      hashtags[], thumbnail_url,
      images: [ { image_url, position } ],
      keyword_found_by, is_eligible_for_commission, region,
      intelligence: { …, hook_text, narrative_arc, text_density, image_count,
                      panel_texts[], panel_text_full, panel_text_word_count,
                      panel_text_character_count, … },
      intelligence_status } ] } }
```
- **Surprise vs PRD (material, breaks naive code):** the PRD says `image_urls[]` (a string array). Reality is **`images[]` — an array of objects `{image_url, position}`**. `position` is the panel order and must be used for sorting; do not rely on array order.
- **`panel_count` does not exist**; the equivalent is `intelligence.image_count`.
- `panel_texts[]`, `hook_text`, `narrative_arc`, `text_density` all live under `intelligence` and exist only when `intelligence_status == "ready"` (**28/50** in the sample).
- Panel-count distribution in the sample: `{1: 14, 4: 3, 5: 4, 6: 5, 7: 10, 8: 10, 9: 3, 10: 1}` → **14/50 slideshows are single-image**, so FR-91's coherent-reference-set builder must require `len(images) >= 3` before treating a slideshow as a reference source.
- Panel images are served as **`.webp`** from `https://auth.virlo.ai/storage/v1/object/public/slideshow-images/<uuid>.webp` at **1122×1402 (4:5)**. GPT Image 2 accepted webp URLs in `input_urls` without complaint (§B).

### Live sample used downstream
Slideshow `2cb23ce9-e67c-4e47-8f51-96fb8298ebbf` — `https://www.tiktok.com/@emirailab/photo/7664493823665507614`, 298 174 views, 18 333 bookmarks, 8 panels, `intelligence.text_density: "text_dominant"`, `narrative_arc: "single_idea_expanded"`, `hook_text: "Best\nAI Tools\nin 2026\nSimple picks by category"`.

Raw capture: `spikes/artifacts/virlo_findings.json`.

---

## B. GPT Image 2 reference honoring (OQ-17 residual) — **PASS, strongly**

**VERDICT:** References are honored *emphatically* — the render reproduced the reference set's palette, background geometry, kicker treatment, headline typography and pill-card component system while re-flowing them into a different aspect ratio and substituting the requested headline text. The mimicry backbone (D2 / FR-18 / FR-241) is real. **No stop flag.**

### Exact request that worked

`POST https://api.kie.ai/api/v1/jobs/createTask` · `Authorization: Bearer <KIE_API_KEY>` · JSON body:

```json
{
  "model": "gpt-image-2-image-to-image",
  "input": {
    "prompt": "Recreate this visual template as a new social post. Mimic the reference images' layout structure, colour palette, typography weight and composition. Replace all headline copy with exactly this text, spelled correctly: SPIKE TEST. Do NOT copy any text, watermark, username, logo or platform UI element from the references. No TikTok/Instagram interface chrome. Clean edges, text fully inside frame.",
    "input_urls": [
      "https://auth.virlo.ai/storage/v1/object/public/slideshow-images/e9ec7832-….webp",
      "https://auth.virlo.ai/storage/v1/object/public/slideshow-images/59f99925-….webp",
      "https://auth.virlo.ai/storage/v1/object/public/slideshow-images/c24ec8fc-….webp"
    ],
    "aspect_ratio": "1:1",
    "resolution": "1K"
  }
}
```

- `input` keys are exactly `prompt`, `input_urls`, `aspect_ratio`, `resolution` — confirmed against Kie's OpenAPI (`spikes/artifacts/gpt-image-2-image-to-image.md`). Nothing else is accepted; `callBackUrl` sits at the **top level**, not inside `input`.
- `resolution` enum is the **string** `"1K" | "2K" | "4K"` (capital K). Documented constraint: **`aspect_ratio: "auto"` (or omitted) forces 1K, and 1:1 cannot be 4K** — otherwise *task creation fails*, not the render.
- `aspect_ratio` enum: `auto, 1:1, 3:2, 2:3, 4:3, 3:4, 5:4, 4:5, 16:9, 9:16, 2:1, 1:2, 3:1, 1:3, 21:9, 9:21`. 5:4 and 4:5 are 1K-only.
- `input_urls` maxItems **16**. Virlo's `.webp` CDN URLs were accepted directly — **no re-hosting needed for Virlo CDN images**.

### Response shapes

`createTask` → `{"code":200,"msg":"success","data":{"taskId":"…","recordId":"…"}}` (both ids identical in practice).

`GET https://api.kie.ai/api/v1/jobs/recordInfo?taskId=…` →
```
{ code, msg, data: { taskId, model, state, param, resultJson, failCode, failMsg,
                     costTime, createTime, completeTime, creditsConsumed } }
```
`resultJson` is a **JSON-encoded string**, not an object — `json.loads()` it before reading `resultUrls`.

### Observed poll states

| t+ | state |
|---|---|
| 0.0 s | `waiting` |
| 3.2 s | `generating` |
| 91.8 s | `success` |

Only **3 of the 5** documented states were observed across all four jobs in this spike; **`queuing` was never seen**, and Seedance never left `waiting` (§C). Treat state as terminal/non-terminal only — never as a progress indicator.

### Cost / timing fields

- `costTime: 90` (ms? no — **seconds**: 90 s, matching wall clock 91.8 s).
- **`creditsConsumed: 6.0`** ← undocumented but present, and exact.
- Credit delta 9404 → 9398 = **6 credits = $0.030** at Kie's published rate (`1 USD = 200 Credits`, "standard price is $0.005 per credit").
- Kie's published image table, verbatim: *"GPT-2 Image — now just 6 credits ($0.03) for 1 K, 10 credits ($0.05) for 2 K, and 16 credits ($0.08) for 4 K."* → **FR-258's three-tier image price table is confirmed exactly.**

### Qualitative verdict — what the downloaded image actually looks like

Artifacts: references `spikes/artifacts/ref_panel_{0,1,2}.png` · output `spikes/artifacts/spike_b_result_0.png` (1254×1254 PNG, 1.04 MB).

Transferred from the references, unmistakably:
- the cream/off-white background (**not** white), the **sage-green blob bleeding off the top-right corner** and the pale-grey blob at bottom-left — same shapes, re-cropped for the square;
- the small letter-spaced kicker with a short sage dash beneath it;
- the heavy geometric black sans headline at the same optical weight and centring;
- the **entire pill-card component system** — white rounded capsules, circular tinted icon chips, the same seven category icons, same two-then-two-then-one stagger, re-laid-out for 1:1;
- the exact accent hues (terracotta chip, sage chip, periwinkle chip).

Requested text substitution worked: the headline reads **"SPIKE TEST"**, correctly spelled, no garbling.
The forbidden platform chrome was correctly excluded — reference panel 0's "SWIPE LEFT" sticker did **not** appear.

**The one caveat, and it is a promptcraft finding, not a capability finding:** the render also copied the reference's **brand wordmark "EMIR AI LAB"** verbatim, and the literal category labels (Write/Research/Images/Video/Audio/Design/Automation) — despite the prompt saying "do NOT copy any text, watermark, username, logo". So:
- the honoring is closer to **template cloning** than to "style influence";
- FR-94's exclusion clauses must name **brand wordmarks / kicker text / any legible string in the reference** explicitly, not just "watermarks and usernames";
- the copy layer must supply replacement text for **every** text zone the template has, or GPT Image 2 fills the gaps from the references. This is a direct input to T1.6 (`prompts/`) and 50-promptcraft.

---

## C. Seedance 2.5 — combo (OQ-21) **PASS** · price (OQ-2) **SETTLED, ⚠ PRD CONFLICT**

**VERDICT (OQ-21):** One `createTask` accepted `reference_image_urls` **and** `reference_video_urls` simultaneously, and the job rendered to `state: success` with a downloadable mp4. The default reel shape (seed frame + winning-video motion reference) is buildable. **No stop flag.**

**VERDICT (OQ-2):** Measured — and the number breaks the PRD's reel economics. See the amendment note below.

### Two attempts, honestly recorded

| # | Config | Terminal | `creditsConsumed` | Notes |
|---|---|---|---|---|
| 1 | image ref + video ref, `generate_audio: true` | **`fail`** after **302 s** | **0.0** | `failCode: 400`, `failMsg: "Content security audit did not pass. The output audio may be related to copyright restrictions."` **Not billed.** |
| 2 | identical, `generate_audio: false` + explicit "silent clip" prompt clause | **`success`** after **379 s** | **570.0** | Downloaded 3 211 127 B mp4. |

Attempt 1 was billed **zero credits**, so re-running was not a double-spend; it is the only re-run in this spike and it is why the total is one billed Seedance render, as authorised.

### Exact request that succeeded

```json
{
  "model": "bytedance/seedance-2-5",
  "input": {
    "prompt": "Subject: the still frame in @Image1 comes alive. Camera: slow push-in, subtle handheld drift, matching the pacing and cut rhythm of @Video1. Motion: gentle parallax on the background, the on-frame text stays perfectly static, sharp and legible for the full clip. Lighting: keep the reference frame's palette and contrast. Silent clip — no music, no song, no melody, no vocals, no soundtrack of any kind. Do not add captions, watermarks or platform UI.",
    "reference_image_urls": ["https://tempfile.aiquickdraw.com/images/chatgpt/file_00000000fbcc81fda3e9d26e1cd3b224.png"],
    "reference_video_urls": ["https://tempfile.redpandaai.co/kieai/1241400/hypesocials-spike/spike_c_ref_video.mp4"],
    "duration": 5,
    "resolution": "720p",
    "aspect_ratio": "9:16",
    "generate_audio": false,
    "nsfw_checker": true,
    "output_format": "mp4"
  }
}
```

- **The spike-B result URL was passed straight into `reference_image_urls` with no re-upload** — D18's chaining assumption holds.
- The uploaded video URL came from the file-upload API (§D).
- Kie echoes the whole input back in `recordInfo`'s `data.param` as a JSON string — useful for the ledger, and it confirmed both reference arrays were retained server-side in attempt 1 too.
- `aspect_ratio` default is `adaptive`, so passing `9:16` explicitly (FR / D10) is required, not decorative.
- `duration` documented 4–30 (plus `-1` auto, never sent). `nsfw_checker` provider default is `false`; the engine sends `true` (FR-166).

### Result

`resultJson.resultUrls[0] = https://tempfile.aiquickdraw.com/seedance/1786276832084-wigf4z6c8km.mp4`
Verified locally **without ffmpeg** by parsing the ISO-BMFF box tree (`spikes/inspect_mp4.py`):
`mvhd` duration **5.042 s**, `tkhd` geometry **720×1280** (9:16, 720p as requested), handlers `['vide']` → **no audio track**, consistent with `generate_audio: false`.

### Observed poll states — a warning

| t+ | state |
|---|---|
| 0.0 s | `waiting` |
| 379.4 s | `success` |

**Seedance stayed in `waiting` for the entire render, on both attempts** (polled every 10 s after the first minute). It never reported `queuing` or `generating`. A progress UI keyed on state will show nothing for six minutes.

### ⚠ Timeout finding — `video_job_timeout_s: 300` is too small

`costTime` was **302 s** (attempt 1) and **378 s** (attempt 2). **Both** Seedance jobs exceeded the PRD's default `video_job_timeout_s: 300`. Under that default the engine would have declared both jobs stuck at 300 s — and per 20-integrations §8 a timed-out job is **never resubmitted** and its spend is counted, so the run would have paid $2.85 and thrown the result away 79 seconds before it arrived.
**Recommendation for T1.1: `video_job_timeout_s` default ≥ 600.** (`image_job_timeout_s: 180` vs a measured 90 s image is comfortable enough.)

### OQ-2 — the measured price, and the formula

Credit delta 9398 → 8828 = **570 credits**. `data.creditsConsumed: 570.0`. At $0.005/credit → **$2.85 for one 5 s 720p reel.**

Kie's published Seedance 2.5 price string, verbatim from `kie.ai/seedance-2-5`:

> Pricing:
> 480P: **17 credits/s ($0.085/s, with video)** | **28 credits/s ($0.140/s, no video)**
> 720P: **38 credits/s ($0.190/s, with video)** | **63 credits/s ($0.315/s, no video)**
> 🔸Note🔸: "With video input" has a lower unit price due to a different calculation method: **No video = Price × Output; With video = Price × (Input + Output)**
> High-tier top-ups include a +10% bonus, making effective pricing approximately 10% lower than listed. Prices are currently in beta and may be adjusted in the future.

The measurement matches **exactly**: `38 credits/s × (10 s input video + 5 s output) = 570 credits`. The reference video's duration is billed at full rate.

**Derived cost table (credits · $ at $0.005/credit, 1 USD = 200 credits):**

| Config | Formula | Credits | USD |
|---|---|---|---|
| 720p, 5 s, **no** video ref | 63 × 5 | 315 | **$1.575** |
| 720p, 5 s, 10 s video ref *(measured)* | 38 × 15 | 570 | **$2.850** |
| 720p, 5 s, **28 s** video ref *(shipped default `reel_reference_max_s`)* | 38 × 33 | 1254 | **$6.270** |
| 480p, 5 s, no video ref | 28 × 5 | 140 | **$0.700** |
| 480p, 5 s, 10 s video ref | 17 × 15 | 255 | **$1.275** |
| 480p, 4 s, no video ref | 28 × 4 | 112 | **$0.560** |
| 480p, 4 s, 3 s video ref | 17 × 7 | 119 | **$0.595** |

**Per-second derived rates for the measured job:** $2.85 / 5 s output = **$0.57 per output second**; $2.85 / 15 s billed = **$0.19 per billed second**.

**The break-even rule (this is the actionable one).** Attaching a video reference is cheaper than not attaching one **iff** `input_seconds < 0.65 × output_seconds` — identical ratio at both resolutions (480p: 17·(I+O) < 28·O ⇒ I < 0.647·O; 720p: 38·(I+O) < 63·O ⇒ I < 0.658·O). For a 5 s reel that means a reference of **≤ 3 seconds**. The shipped default of 28 s makes a 5 s reel **3.98× more expensive** than the same reel with no reference at all.

### PRD conflicts raised by §C (all need D15)

1. **Success metric "reels ~$0.40–0.60 ea."** (00-overview) is unreachable at 720p under any duration; it is reachable only at **480p, ≤4 s, with a ≤3 s reference or none**. Either the metric changes or the default reel profile does.
2. **`price_per_unit.reel_second` is the wrong shape** (FR-258 / 30-configuration). A single scalar cannot express `resolution × has_video_reference` unit prices **plus** the `(input + output)` basis. T1.1 needs a small table, e.g.
   `reel: { "480p": {with_video: 0.085, no_video: 0.140}, "720p": {with_video: 0.190, no_video: 0.315} }`
   and the estimator must add the **qualifying reference video's probed duration** to the billed seconds — a number that is only known *after* the yt-dlp probe, i.e. **after** the pre-flight estimate is shown. The estimator must therefore either price the worst case (`reel_reference_max_s`) or defer.
3. **`reel_reference_max_s: 28` (FR-161)** is a cost trap, not a safety bound. Recommend defaulting to a value derived from the break-even rule (≈ `0.65 × duration`, i.e. **3 s** for the default 5 s reel), with the 28 s figure retained only as the provider's hard ceiling.
4. **"Spend is counted at submission" (§8 / FR-242 / 10-pipeline budget rules)** is conservative but not what Kie does: the failed job consumed **0 credits**. `data.creditsConsumed` is present on every terminal record and is the exact figure to reconcile FR-106's reservation against. (Undocumented in Kie's OpenAPI — treat as best-effort, fall back to the price table when absent.)
5. **`generate_audio: true` (D22, the shipped default) failed content audit** when the motion reference was a music-bearing TikTok clip. That is the default reel configuration, and the failure arrives **after** ~5 minutes of render time (though at zero cost). 10-pipeline needs a degrade path: on `failMsg` containing a content-security/copyright signal, retry once with `generate_audio: false` — or default reels to silent when a video reference is attached. This is a new failure class, distinct from moderation refusal on imagery.

### yt-dlp / video-reference chain — a hard constraint the PRD does not carry

Kie's `reference_video_urls` documents: mp4/mov · 480p/720p · aspect 0.4–2.5 · width & height 300–6000 px · **total pixels within `[409 600, 927 408]`** · ≤200 MB · fps 24–60 · 2–30 s each · ≤30 s total.

**A raw TikTok download is 1080×1920 = 2 073 600 px — over 2× the ceiling, and would be rejected.** The engine must select the format at download time. Probed format tables (8 TikTok candidates, `spikes/artifacts/ytdlp_probes.json`) consistently offer:

| Format | Geometry | Pixels | Usable |
|---|---|---|---|
| `*_540p_*` | 576×1024 | 589 824 | ✅ |
| `*_720p_*` | 720×1280 | 921 600 | ✅ (just under the 927 408 ceiling) |
| `*_1080p_*` | 1080×1920 | 2 073 600 | ❌ |

Working recipe (used here, no ffmpeg, no format merging — TikTok serves progressive mp4 with audio):
1. `yt-dlp --skip-download --dump-single-json <url>` → read `duration` **and** `formats[]`.
2. Keep formats where `300 ≤ w,h ≤ 6000` and `409600 ≤ w*h ≤ 927408` and `acodec != "none"`; prefer `h264` over `bytevc1`/HEVC.
3. `yt-dlp -f <exact format_id> -o <dest> <url>`.

Result: `h264_720p_1459099-0`, 720×1280, 1 854 333 B, `rc=0`, no cookies required. Probed durations across the 8 candidates: 10, 17, 30, 45, 56, 144, 308 s → **only 2 of 8 qualified under a 28 s bound**, and 0 of 8 would qualify under a 3 s bound. The "degrade to seed-frame-only" path (FR-163) will be the common case, not the exception.

Artifacts: `spikes/artifacts/seedance_report_1.json`, `seedance_report_2.json`, `spike_c_result_2_0.mp4`, `spike_c_ref_video.mp4`, `ytdlp_probes.json`.

---

## D. Kie file-upload API — mkv spot-check **PASS (with caveat)** + real mp4 upload

**VERDICT:** `POST https://kieai.redpandaai.co/api/file-stream-upload` accepted both a real 1.85 MB mp4 and a 4 100-byte junk `.mkv`, HTTP 200 each. **The mkv result proves the upload API does not filter by extension — it proves nothing about whether any renderer can decode mkv, and the file uploaded was deliberately not a playable video.**

### Exact request

Multipart `POST https://kieai.redpandaai.co/api/file-stream-upload` · `Authorization: Bearer <KIE_API_KEY>`
- `file` — binary part
- `uploadPath` — **required**, no leading/trailing slashes (used `hypesocials-spike`)
- `fileName` — optional

### Response shape (identical for both files)

```json
{ "success": true, "code": 200, "msg": "File uploaded successfully",
  "data": { "success": true,
            "fileName": "spike_c_ref_video.mp4",
            "filePath": "kieai/1241400/hypesocials-spike/spike_c_ref_video.mp4",
            "downloadUrl": "https://tempfile.redpandaai.co/kieai/1241400/hypesocials-spike/spike_c_ref_video.mp4",
            "fileSize": 1854333,
            "mimeType": "video/mp4",
            "uploadedAt": "2026-08-09T11:47:36.377Z" } }
```

| | real mp4 | junk `.mkv` |
|---|---|---|
| HTTP | 200 | 200 |
| `data.mimeType` | `video/mp4` | **`application/octet-stream`** |
| `data.fileSize` | 1 854 333 | 4 100 |
| URL fetchable afterwards | yes (200) | yes (200) |

**Findings for the build:**
- The public URL host is **`tempfile.redpandaai.co`** — different from the API host `kieai.redpandaai.co`. Do not construct URLs; always read `data.downloadUrl`.
- The returned path embeds an account id (`kieai/1241400/…`) — nothing secret, but don't log it as if it were a stable public identifier.
- `mimeType` is sniffed, and mkv sniffs to `application/octet-stream`. Since Seedance's route documents **mp4/mov only** for `reference_video_urls`, the safe engine posture stays: accept upload success, but keep selecting mp4 at yt-dlp format-selection time. mkv acceptance is a non-blocker, not a green light.
- No stated expiry in the response body (see §G).

Artifacts: `spikes/artifacts/mkv_upload.json`, `spikes/artifacts/test.mkv`.

---

## E. Luna strict structured output (OQ-22) — **PASS**

**VERDICT:** OpenRouter strict `json_schema` mode composes cleanly with Luna's reasoning — schema-valid JSON returned, `finish_reason: "stop"`, at both low and medium reasoning effort. **But the first attempt returned HTTP 404 because `temperature` is not a supported parameter on Luna (or on Sonnet 5), and that directly contradicts FR-129.**

### Exact request that worked

`POST https://openrouter.ai/api/v1/chat/completions` · `Authorization: Bearer <OPENROUTER_API_KEY>`

```json
{
  "model": "openai/gpt-5.6-luna",
  "messages": [ {"role":"system","content":"…"}, {"role":"user","content":"…"} ],
  "response_format": { "type": "json_schema", "json_schema": {
      "name": "social_copy", "strict": true,
      "schema": { "type":"object",
        "properties": { "hook":{"type":"string"}, "caption":{"type":"string"},
                        "hashtags":{"type":"array","items":{"type":"string"}} },
        "required": ["hook","caption","hashtags"], "additionalProperties": false } } },
  "reasoning": { "effort": "low" },
  "max_tokens": 1200,
  "provider": { "require_parameters": true },
  "usage": { "include": true }
}
```

### ⚠ The landmine — `temperature` is unsupported

The **first** attempt was identical except it also carried `"temperature": 0.7`. Result:

```
HTTP 404
{"error":{"message":"No endpoints found that can handle the requested parameters.
 To learn more about provider routing, visit: …/routing/provider-selection","code":404}}
```

OpenRouter's model catalog (`GET /api/v1/models`, $0) confirms why:

| Model | `supported_parameters` |
|---|---|
| `openai/gpt-5.6-luna` | `include_reasoning, max_completion_tokens, max_tokens, reasoning, reasoning_effort, response_format, seed, structured_outputs, tool_choice, tools` |
| `anthropic/claude-sonnet-5` | `include_reasoning, max_completion_tokens, max_tokens, reasoning, reasoning_effort, response_format, stop, structured_outputs, tool_choice, tools, verbosity` |

**Neither model lists `temperature`.** With FR-125's `provider.require_parameters: true` — which the PRD mandates — sending a temperature makes the request unroutable and it fails with a 404 that looks like a model-not-found error.

**Consequences for T1.4 / T1.1:**
- **FR-129 ("Analysis and copy calls SHALL use a stable, configured temperature") is unimplementable as written** for both shipped models. `llm.structured_call()` must omit `temperature` unless the configured model advertises it. Reproducibility instead rests on `seed` (Luna supports it; Sonnet 5 does not) plus the fixed per-role system prompt. **D15 amendment needed.**
- The catalog's `supported_parameters` is the correct pre-flight guard: if a config swaps in a new model id (D34), check the sampled params against it and drop/refuse rather than emitting a 404 mid-run.
- A 404 from OpenRouter is **not** necessarily "unknown model" — it can mean "unroutable parameter set". Error handling should surface the message body, not just the status.

### Measured results

| Reasoning effort | HTTP | `finish_reason` | prompt tok | completion tok | **reasoning tok** | `usage.cost` | schema-valid |
|---|---|---|---|---|---|---|---|
| `low` | 200 (1.99 s) | `stop` | 93 | 80 | **0** | **$0.0000573** | ✅ |
| `medium` | 200 | `stop` | 93 | 115 | **37** | **$0.0000783** | ✅ |

- `native_finish_reason: "completed"`, `message.refusal: null`, `message.reasoning: null` (reasoning text is not returned unless `include_reasoning` is set).
- Cost breakdown is returned inline under `usage` when `{"usage":{"include":true}}` is sent — `usage.cost`, `usage.cost_details.{upstream_inference_cost, upstream_inference_prompt_cost, upstream_inference_completions_cost}`, and `usage.completion_tokens_details.reasoning_tokens`. **No cost/billing information appears in response headers** — read it from the body.
- Catalog pricing confirms OQ-1: prompt `$0.0000001`/tok = **$0.10/Mtok**, completion `$0.0000006`/tok = **$0.60/Mtok**; a >272 k-token prompt tier doubles it. Context 1 050 000, `max_completion_tokens` 128 000.
- **Reasoning-allowance guidance for the estimator (NFR-18 / FR-107):** at `effort: low`, reasoning tokens were **exactly 0**; at `medium`, ~32 % of completion tokens. Budget the reasoning allowance per effort level, not as a flat constant.

Artifacts: `spikes/artifacts/luna_response.json`, `spikes/artifacts/luna_effort_sweep.json`.

---

## F. Windows double-SIGINT on ProactorEventLoop — **PASS** ($0)

**VERDICT:** The mandated pattern works, twice over, on Windows 11 / Python 3.13. `loop.add_signal_handler` is unavailable, as the PRD assumes. One extra gotcha was uncovered that will otherwise crash the shutdown path.

### One-line proof that `add_signal_handler` is unusable

```python
loop = asyncio.ProactorEventLoop()
loop.add_signal_handler(signal.SIGINT, lambda: None)
# -> NotImplementedError
```
Observed exactly: `loop.add_signal_handler(SIGINT) -> NotImplementedError: NotImplementedError()`.

### The working pattern (copy this into `runner.py`)

```python
loop = asyncio.ProactorEventLoop()          # explicit, never rely on the platform default
asyncio.set_event_loop(loop)

stop, hard = asyncio.Event(), asyncio.Event()
hits = 0

def on_stop() -> None:                       # runs ON the loop thread
    global hits
    hits += 1
    (stop if hits == 1 else hard).set()

def handler(signum, frame) -> None:          # runs on the MAIN thread, between bytecodes
    loop.call_soon_threadsafe(on_stop)       # never touch loop state directly here

signal.signal(signal.SIGINT, handler)
```

- `asyncio.create_subprocess_exec` works on this loop (a real subprocess was spawned and reaped in every run).
- First SIGINT → graceful flag; second → hard stop. Both delivered promptly (handler fired at t+3.93 s for an event sent at ≈t+4.0 s).

### Which delivery mechanism actually works on Windows 11 / Python 3.13

| Mechanism | Works? | Notes |
|---|---|---|
| `signal.raise_signal(signal.SIGINT)` from a **worker thread** | ✅ | Simplest way to *simulate* Ctrl+C in a test. Delivered at t+2.01 s and t+4.01 s with zero latency; the Proactor loop woke immediately. Only the current process is signalled — **child processes are untouched**. |
| `os.kill(child_pid, signal.CTRL_C_EVENT)` from a parent | ✅ **but conditional** | Requires the child be spawned with `subprocess.CREATE_NEW_PROCESS_GROUP` (0x00000200) **and** the child to re-enable Ctrl+C for itself via `ctypes.windll.kernel32.SetConsoleCtrlHandler(None, False)` — a brand-new process group has Ctrl+C **disabled** by default. Both sends returned success; the child's handler fired both times. |
| `loop.add_signal_handler(...)` | ❌ | `NotImplementedError` on Proactor. |

Caveat for anyone reproducing this: `GenerateConsoleCtrlEvent` needs an attached console. `SetConsoleCtrlHandler(NULL, FALSE)` returned `1` (success) here; a return of `0` means no console is attached and the mechanism is unavailable.

### ⚠ The gotcha this spike uncovered — CTRL_C is a **process-group** event

Under the real-Ctrl+C mechanism, the engine's *own* subprocess also received the event and died on its own (exit code **3221225786 = 0xC000013A = STATUS_CONTROL_C_EXIT**) before the engine got to kill it. The unguarded `proc.kill()` then raised **`ProcessLookupError`**, which propagated out of `run_until_complete` and blew up the orderly-shutdown path.

**Therefore, binding for T4.3:**
- Every cleanup `proc.kill()` / `terminate()` must be wrapped: `except ProcessLookupError: pass` — the child may already be gone.
- A real Ctrl+C reaches **yt-dlp and every MCP stdio server too**, because they share the console. Do not assume the engine is the only recipient; do assume some children are already dead by the time cleanup runs.
- This is precisely why the Windows **job object** (kill-on-close, FR-111) is the primary reaper and `.kill()` is only best-effort belt-and-braces.

Artifacts: `spikes/artifacts/signal_results.json`; harness `spikes/signal_child.py`.

---

## G. OQ-20 — upload / result URL lifetime — **PARTIALLY SETTLED**

**VERDICT:** The ~24 h upload expiry is corroborated by a real response header; the ~14 d result retention is **not** observable from any response and remains a docs-only claim. No multi-day test is possible in a one-day spike.

`HEAD` against every live URL produced in this spike:

| URL | Host | Status | Expiry-bearing headers |
|---|---|---|---|
| Image result (spike B) | `tempfile.aiquickdraw.com` | 200 | none — only `date`, `last-modified`, `etag`, `content-length` |
| Video result (spike C) | `tempfile.aiquickdraw.com` | 200 | none — same set |
| Uploaded mp4 | `tempfile.redpandaai.co` | 200 | **`cache-control: public, max-age=86400`** (= exactly 24 h) |
| Uploaded mkv | `tempfile.redpandaai.co` | 200 | **`cache-control: public, max-age=86400`** |

Documented claims (Kie docs, re-read 2026-08-09): uploads auto-delete after **24 h** (one page says 3 days — the engine must use 24 h); generated **outputs** retained **~14 days**. Neither `Expires`, `x-amz-expiration`, nor any custom retention header is emitted.

**Rules the build should adopt (unchanged from the PRD, now with evidence):**
- Treat every `file-stream-upload` URL as **same-run-only**. The `max-age=86400` header is the only in-band corroboration, and it is a *cache* directive, not a deletion guarantee — do not lengthen the assumption on its strength.
- A wave-1 → wave-2 gap is minutes; both chaining windows measured here (image result → Seedance reference, ~3 minutes) are trivially inside any of these bounds. **No retention risk exists inside a single run.**
- Anything touching a Kie-hosted asset *later* (a re-render, a Phase 2 publish) must **download-then-re-upload**; it may not reuse a stored URL. Nothing observed contradicts this, and nothing observed proves the 14-day figure either — so the conservative rule stands on its own merits, not on the docs.

Artifact: `spikes/artifacts/oq20_retention_probe.json`.

---

## Consolidated action list for Wave 1

**T1.1 (`config.py` + `configs/`)**
- `video_job_timeout_s` default **300 → ≥600** (measured renders: 302 s, 378 s). §C
- Reel price cannot be a scalar `price_per_unit.reel_second`; needs `resolution × with_video/no_video` and an `(input + output)` seconds basis. §C
- Image price table confirmed exactly as FR-258: 1K $0.03 / 2K $0.05 / 4K $0.08. §B
- `reel_reference_max_s: 28` is a 4× cost multiplier — recommend ≈`0.65 × duration`. §C
- Do **not** put a `temperature` key in any LLM role block for the shipped models. §E
- Consider a config gate for `/v1/trends/digest` — it is the only metered Virlo call ($0.25/run). §A
- Real monitor id for live runs: `9c96fddf-dc35-4be0-bbd9-12f4d22aea12`. §A

**T1.3 (`render/`)**
- `input` shapes for both profiles are recorded verbatim in §B and §C — copy them, do not re-derive.
- `resultJson` is a JSON **string**; `data.creditsConsumed` is present on terminal records and is the reconcile-to-actual figure (0.0 on failure). §B, §C
- Poll classification must not depend on seeing `generating`/`queuing`; Seedance never leaves `waiting`. §C
- Video-reference format selection must enforce the `[409 600, 927 408]` pixel window. §C
- Add a content-security/copyright failure class distinct from moderation refusal. §C

**T1.4 (`llm.py`)**
- Omit `temperature`; keep `provider.require_parameters: true`; strict `json_schema` + `reasoning.effort` verified working. §E
- Read cost from `usage` in the body (`{"usage":{"include":true}}`), not from headers. §E
- Reasoning allowance is effort-dependent: 0 tokens at `low`, ~32 % of completion at `medium`. §E

**T1.5 (`mcp_client.py` + `virlo_mcp/`)**
- Normalization deltas in §A: `data.agents` nesting, **`page`-based pagination (not `offset` — corrected 2026-08-11)**, `images[{image_url, position}]` not `image_urls[]`, `intelligence.*` optionality gated on `intelligence_status == "ready"`, no `panel_count` (use `intelligence.image_count`), duplicates in `videos[]`, no `duration` field anywhere.
- The digest/monitor-analysis field ownership is swapped relative to the PRD's tool table. §A
- Surface `x-cost` / `x-credits-remaining` into the event log. §A

**T1.6 (`prompts/`)**
- FR-94 exclusion clauses must name brand wordmarks and *any legible reference text*, and every text zone needs supplied copy — otherwise GPT Image 2 clones the reference's words. §B
- Seedance prompts that ship with `generate_audio: false` should say "silent clip" explicitly; audio-on reels with music-bearing references fail content audit. §C

**T4.3 (`runner.py` two-stage Ctrl+C)**
- Use the §F pattern verbatim; wrap every cleanup kill in `except ProcessLookupError`.

---

## Files in `spikes/`

| File | Purpose |
|---|---|
| `day_one.py` | All spikes A–F behind subcommands (`virlo`, `virlo_monitor`, `probe`, `image`, `seedance`, `mkv`, `luna`, `signals`, `credit`, `docs`). |
| `signal_child.py` | Spike F child harness (ProactorEventLoop + subprocess + double-SIGINT). |
| `scrape_price.py` | Kie credit→USD rate and Seedance unit-price scrape (OQ-2 desk half). |
| `inspect_mp4.py` | ffmpeg-free ISO-BMFF verification of the rendered mp4. |
| `artifacts/` | Raw captures: Virlo JSON, Kie records, the rendered PNG/MP4, yt-dlp probes, doc snapshots, spend tally. |

Every `.py` file above opens with `SPIKE — RETIRED after Wave 1. Never imported by production code.`
