# ACCEPTANCE.md — Operator Final Acceptance Matrix (SESSION G / D46, v2.1.0)

Four scenarios, each ending with the same four standard checks. Run from the repo root
(`C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials`) in a normal console. Exit codes per
FR-202 (prds/10-pipeline.md §6): **0** all delivered · **1** partial (honest skips/losses) ·
**2** pre-flight/cap refusal, nothing spent · **3** fatal, nothing usable · **4** operator abort.

> **Recency note (D46):** The 30-day history window (`logs/trend_history.json`) tracks posts
> by ID, not just topics. When a post was used recently, it is dropped from the candidate pool.
> An exit 1 with `SKIP_REASON.txt` naming post-level famine (`no_fresh_post_available`) is
> HONEST behavior—the topic has posts, but all the fresh ones were quoted in the last 30 days.
> To reset for a test: rename `logs/trend_history.json` aside (restore it afterwards if you want
> the reuse guard back).

---

## The 4 standard checks (apply to EVERY scenario)

1. **Gallery provenance correct** — open `output\latest\gallery.html`:
   - Every delivered carousel asset has a three-part card:
     - **Provenance header:** author, views, publication date, Virlo post URL (permalink), original creator's caption (in source language)
     - **Source panel strip:** original slideshow slides in order (locally downloaded, never hotlinked), each with extracted on-image text (verbatim from the source) and visual brief (graphics/charts/icons description)
     - **Rendered slide alignment:** our generated slides beside their corresponding source slides, by panel index, enabling side-by-side fidelity review
   - Every image/reel card shows the quoted post (author, views, post ID) and caption
   - Skipped assets absent from cards but named in the run summary
   - All relative paths (no Virlo/Kie.ai URLs in the HTML)

2. **meta.yaml honest** — every asset folder's `meta.yaml` is terminal (`success` / `skipped`,
   never `pending`), `degradations: []` lists only what actually happened, costs present,
   `render_not_reproducible: true` stated, `brief_influence_mode` present on brief assets.
   **D46 amendments:** carousel entries include `source_panel_count` (integer, the source's panel count), `panel_map` (array of per-slide objects with slide, source_position, source_text, ref_label, visual_brief, source_image relative path), and `source_post` (nested provenance object with post_id, url, author, views, published_at, caption). Override-brief carousels have empty `panel_map` and null `source_post`.

3. **Spend ≈ estimate** — run.log's spend summary: actual ≤ pre-flight worst-case estimate, and
   in the expected ratio. Post-pivot the reel scalar IS the published no-reference per-second
   rate, so reel actuals should match the estimate almost exactly — a large gap in either
   direction is a finding. The estimator now includes a `slide_intel` line per assigned carousel
   (if `vision_transcribe: true`), estimated at ~$0.01–0.03/post, because this analysis runs
   post-Confirm and costs money. Cross-check the Kie/OpenRouter dashboards if in doubt.

4. **No orphan processes** — after exit: `tasklist | findstr /i "python node"` shows
   nothing from the run (one hit for your own console's python is fine only while it's still
   open); no stray `node.exe` (Notion MCP) remain.

---

## Scenario 1 — Tiny-budget refusal (interactive) + auto-trim (`--yes`) — $0

**1a. Interactive refusal (FR-28, human decides):**

```
run.bat --config hypedigitaly.yaml --carousels 2 --budget 0.02
```

Expected: full cost estimate + FR-282 provenance printed; refusal naming the gap
("estimate … exceeds the $0.02 spend cap by … — lower the counts, raise --budget, or re-run
with --yes"); **exit 2**; $0 spent; no render/LLM calls in `events.jsonl`; run folder + log
survive (FR-59 resolution) but contain no assets.

**1b. Auto-trim under `--yes` that cannot fit (FR-28 trim floor):**

```
run.bat --config hypedigitaly.yaml --carousels 2 --budget 0.02 --yes
```

Expected: trim summary line printed, then refusal "the $0.02 cap is below the cost of any
single creative — trimming cannot help; raise --budget"; **exit 2**; $0 spent.

**1c (optional, costs ~$0.10–0.20). Auto-trim that fits:**

```
run.bat --config hypedigitaly.yaml --carousels 3 --budget 0.30 --yes
```

Expected: reverse-plan trim drops entries until the estimate fits $0.30; the trimmed plan is
printed and runs; **exit 0 or 1**; spend ≤ $0.30. Then the 4 standard checks.

---

## Scenario 2 — Full-batch stress: 2 images + 2 carousels + 1 reel, `--yes` (~$5–6)

**Note: Images and reels require `sources.include_videos: true`; they are forbidden by default.**
**There is no CLI flag for it — edit `sources.include_videos: true` in the config first**
**(a run without that edit is refused at pre-flight, which is itself a §0.14e check worth seeing once).**

```
run.bat --config hypedigitaly.yaml --images 2 --carousels 2 --reels 1 --yes --budget 6
```

Expected:
- **With `include_videos` still false, pre-flight REFUSES (exit 2, $0):** the message names the requested counts and says "slideshow-first sourcing makes every topic slideshow-majority … set sources.include_videos: true or set those counts to 0 (§0.14e, FR-132)". Under `--yes` with only override-brief image/reel entries the guard does not fire (§0.14d).
- Once videos are on, estimate ≈ $5.3–5.7 worst case (reel priced at the honest 720p scalar $0.315/s × 5 s = $1.575 worst case; actual reel typically $1.70–2.85)
- Two-wave submission visible in run.log (carousel anchor + reel seed frame first; remaining carousel slides + animation second)
- **Slide intelligence (FR-306, D46):** For each assigned carousel, a Claude Sonnet 5 call runs post-Confirm, downloads the source slides, extracts on-image text verbatim and visual descriptions (graphics, layout, composition), and uses these extractions in render prompts. Estimator shows `slide_intel` line; actual cost ~$0.01–0.03/post.
- **Carousel panel-mapped (FR-304, D46):** source slide 1 → output slide 1, source slide 2 → output slide 2, verbatim, position-preserving. On-image text from the source panels (verbatim via vision analysis or Virlo's `panel_texts` field) becomes our on-image text.
- Wall clock inside the **≈8–10 min reel tier** (record it)
- **exit 0**, or **exit 1** with honest skip reasons (famine — see note above, now post-ID famine `no_fresh_post_available`; or task timeout)
- Then the 4 standard checks — pay extra attention to check 1 (provenance cards with source panels) and check 3 (slide_intel line in the estimate).

---

## Scenario 3 — Czech-language run with panel text proof (optional, ~$0.30–0.60)

One-time setup (copy the proven config, switch the three platform languages to Czech):

```
copy configs\hypedigitaly.yaml configs\hypedigitaly-cs.yaml
```

Edit `configs\hypedigitaly-cs.yaml` line `languages:` to:
`languages: { linkedin: cs, instagram: cs, tiktok: cs }`

Run:

```
run.bat --config hypedigitaly-cs.yaml --carousels 2 --budget 1
```

Expected:
- Pre-flight prints the **Czech vision-check hint** (30 §2 — vision check is off by default; the hint reminds you Czech on-image text benefits from it)
- Captions in Czech (the caption language per platform)
- On-image text in Czech (platform's language, or overridden by `onimage_text_language` config)
- Slide intelligence extracts Czech on-image text verbatim from source panels
- Confirm interactively with `y`
- **exit 0/1**
- Then the 4 standard checks — for check 1, verify that rendered on-image Czech has correct diacritics; for check 2, verify `panel_map` entries have `source_text` in Czech; for check 4, open the gallery and eyeball that source panels show Czech text and our rendered slides preserve it

---

## Scenario 4 — Preview-sources funnel proof (free, $0)

Audit which posts the funnel would keep/drop, including the new recency drops:

```
run.bat --config hypedigitaly.yaml --preview-sources
```

Expected:
- Topics table showing all fetched topics, their post counts, total/median views, computed strength, and filter verdict (keep/strip/skip)
- **Virlo funnel report** at DONE, showing:
  - `topics: N` (input count from Virlo)
  - `dropped_stale: N` (posts > 30 days old, dropped pre-rank)
  - `dropped_unenriched: N` (posts without panel_count or image_urls, dropped pre-rank)
  - `dropped_used: N` (posts quoted in the last 30 days per post-ID, dropped pre-rank)
  - `available: N` (posts ready to rank and pick)
- Per-topic post roster showing author, views, publication date (from Virlo's `published_at` field), post ID, and which posts would be quoted if this topic were selected
- **exit 0** (at least one usable topic) or **exit 3** (zero usable topics after filtering and recency)
- **$0 spent** (Virlo cost only, against your deposit)

This is the supply audit for cadence planning. If `dropped_used` is high, you're running too frequently for the topic's freshness. If `dropped_stale` is zero and `available` is high, the topic is hot and daily runs are feasible.

---

## Scenario 5 — Task Scheduler unattended run (~$0.30–0.60)

Create (one line; adjust the start time `/ST` a few minutes ahead):

```
schtasks /Create /TN "HypeSocials-Acceptance" /SC ONCE /ST 23:55 /TR "cmd /c cd /d C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials && run.bat --config hypedigitaly.yaml --carousels 2 --yes --budget 1"
```

Trigger it now instead of waiting, then watch:

```
schtasks /Run /TN "HypeSocials-Acceptance"
schtasks /Query /TN "HypeSocials-Acceptance" /V /FO LIST
```

Expected: run completes with **no console interaction** (`--yes` path: no confirm, no fidelity
rating — FR-232 is suppressed); "Last Result" in the query output is the run's exit code (0/1);
outputs land in `output\<run_id>\` and `output\latest` repoints. Then the 4 standard checks —
check 4 matters most here (Task Scheduler must leave no orphan tree behind).

Clean up:

```
schtasks /Delete /TN "HypeSocials-Acceptance" /F
```

(For a real nightly schedule replace `/SC ONCE /ST …` with e.g. `/SC DAILY /ST 07:00`.)

---

## Sign-off

| Scenario | Ran on | Exit | Gallery | meta.yaml | Spend≈est | No orphans |
|---|---|---|---|---|---|---|
| 1a interactive refusal | | | ☐ | ☐ | ☐ ($0) | ☐ |
| 1b --yes trim-refusal | | | ☐ | ☐ | ☐ ($0) | ☐ |
| 1c --yes trim-fits (opt) | | | ☐ | ☐ | ☐ | ☐ |
| 2 full-batch stress | | | ☐ | ☐ | ☐ | ☐ |
| 3 Czech run (opt) | | | ☐ | ☐ | ☐ | ☐ |
| 4 preview-sources audit | | | — | — | ☐ ($0) | ☐ |
| 5 Task Scheduler | | | ☐ | ☐ | ☐ | ☐ |

---

## Notes for reviewers

**D46 (v2.1.0, SESSION G — 2026-08-13) amendments:**

1. **Sourcing:** Fetch reaches back 30 days only (not all-time), ranked by views within that window. The first paid run quoted posts from 2023 because `order_by=views` spanned all time; the fix is `order_by=created_at desc` with a 30-day age cap (`max_post_age_days`).

2. **No-repeat invariant (FR-307):** Post-ID level, not topic level. History tracks individual posts (Virlo UUIDs). The invariant `trend_history_days ≥ max_post_age_days` is enforced at pre-flight refusal (both default 30).

3. **Text-only styles (D41/D46):** `prompts/styles.yaml` ships no style reference images. The registry carries palette, typography, and layout guidance as YAML. Brief images and carousel anchors still exist. Style reference images do not.

4. **Panel-mapped carousels (FR-304, D46):** Source slide N's on-image text becomes output slide N's on-image text, verbatim, position-preserving. Text is extracted from Virlo's `panel_texts` field or from vision analysis (if `vision_transcribe: true` post-Confirm). A source panel's text is never trimmed to fit a budget; if it doesn't fit, the panel is marked missing and the carousel ships incomplete with degradation tag `no_onimage_text`.

5. **Slide intelligence (FR-306, D46):** Post-Confirm, Claude Sonnet 5 reads each assigned carousel's source slides, extracting on-image text (verbatim) and visual descriptions (graphics, charts, layout). These enrich render prompts. Cost ~$0.01–0.03/post, included in pre-flight estimate. Toggle: `sources.vision_transcribe` (default true).

6. **Provenance gallery (FR-309, D46):** Carousel cards now show three parts: source provenance (author, views, URL), source slides with extracted text/briefs (local relative paths, no hotlinks), and our rendered slides aligned by index. Images and reels show single-card format (source post info + caption).

7. **`refs/` brief-images-only:** The run-level `output/<run_id>/refs/` folder now holds only brief images (supplied per brief). Style reference images and carousel references no longer go here (they don't exist as uploaded files—styles are text-only, carousel references are source posts analyzed locally).

8. **Formats guard (§0.14e):** If `sources.include_videos: false` (default) and you request image or reel counts, pre-flight refuses: "carousel format requires slideshow-sourced topics; image and reel require videos; but `sources.include_videos: false`. Enable videos or disable image/reel counts." This prevents silent rank-fallback onto video rows the run was never meant to use.

9. **Preview-sources funnel (FR-155, FR-305):** Shows the three post-level drop lines: stale (over max_post_age_days), unenriched (missing panel_count or images), used (in history). Enables operators to audit supply and plan cadence.

---

**First execution record:** Not yet run under D46 (v2.1.0). Earlier W6 acceptance runs (2026-08-09) predate the slideshow-fidelity amendments.

---

**Session G execution** (SESSION G / D46 re-base date: 2026-08-13):
- [ ] Scenario validation pending
