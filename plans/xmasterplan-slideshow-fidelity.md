# xmasterplan — Slideshow Fidelity Fix (D46, v2.1.0) — v1.1 APPROVED

**Status: APPROVED 2026-08-13 (operator, D15 step 2) — §0 decisions settled, §2 amendment
text consented; Wave 0 may run.** Settled §0 values: 0.1 as proposed (`max_post_age_days: 30`,
`fetch_pages: 3`); 0.2 as proposed (videos off); **0.3 OVERRIDDEN by operator: all-carousels
default, `run.formats: {image: 0, carousel: 6, reel: 0}`**; 0.4–0.5 as proposed; 0.6 as
proposed (vision tier IN, on by default); 0.7 as proposed; 0.8 as proposed (SESSION F =
W0–W2, SESSION G = W3–W5).
Written 2026-08-13 after the operator rejected run `20260813_093720_7hiu` against the Virlo UI.
Evidence for every defect: fresh MCP probes of monitor `9c96fddf-…` (this session), recorded in §1.

---

## TL;DR (plain English)

The first paid run quoted the wrong posts (all-time winners, some from 2023, instead of this
week's crop), the wrong text (under-post captions full of hashtags — once even Virlo's own
AI summary — instead of the words written ON the slides), and cloned the Inspiration images
nearly 1:1 instead of just borrowing their design language. This plan fixes all four things:

1. **F1 — Fetch this week, not all time.** Pull the monitor's newest collection rounds
   (`created_at desc`), cap post age, and rank by views *within* that recent pool.
2. **F2 — Quote the on-image words.** Slide panel texts, hooks and overlays become the
   first-class verbatim source for pixels AND captions; Virlo's AI `description` summary is
   banned from every output; character budgets are raised so real viral hooks actually fit.
3. **F3 — Styles are guidelines, not templates.** No style reference images are ever sent
   to the renderer again; each style's *textual* definition (enriched) carries the look.
   Brief images and anchor/seed-frame chaining keep working.
4. **F4 — Slideshows in, carousels out.** v1 sources only slideshows; each source
   slideshow's slide-N text becomes OUR carousel's slide-N text, verbatim, in order.
   Fallback: an analysis-only AI vision step transcribes slides Virlo hasn't extracted yet.

PRDs are amended first (D46, FR-301+, v2.1.0), then code, then a cheap-first live ladder.

---

## §0 — Operator decisions needed BEFORE Wave 0 (defaults proposed)

| # | Decision | Proposed default | Notes |
|---|---|---|---|
| 0.1 | Recency mechanism | Fetch `get_top_slideshows` with `order_by=created_at, sort=desc`, `sources.fetch_pages` (default **3** → up to 300 rows), then drop rows with `publish_date` older than `sources.max_post_age_days` (default **30**, `0` disables), then rank by views. | Virlo rows do NOT echo `created_at`, so the window is "newest collection rounds by page depth + a publish-date staleness cap". This reproduces the UI's Most-Recent grid (probe-verified: same authors). "Last week" purism (`max_post_age_days: 7`) would drop most of the UI's own cards — they were published in July, *collected* 3–9 Aug. |
| 0.2 | Videos in v1 | `sources.include_videos: false` (new key). `get_top_videos` is NOT called; funnel prints `videos: disabled (v1 slideshow-first)`. | Reversible per config. Reels then seed from slideshow hooks/panels. |
| 0.3 | Default format mix | **SETTLED (operator): `run.formats: {image: 0, carousel: 6, reel: 0}`** in shipped configs (was 4/2/0) — all-carousels v1. | Pure slideshow mirror. Cost note: ~6 decks × up to `carousel_slides` renders each ≈ 30+ image jobs/run; estimator + spend cap govern as always. Images/reels remain available per config/CLI. |
| 0.4 | Deck length | Slide count = **source panel count**, clamped to `[2, platforms.<p>.carousel_slides]`; ceiling stays the estimate basis (FR-257 keeps "never raise above"). Truncation policy when source > ceiling: keep panels 1..N (cover + first body panels). | Operator may raise `carousel_slides` (Instagram hard max 10, FR-221). |
| 0.5 | Text budgets | `run.text_budgets`: `image_headline` 42→**90**, `image_subline` 60→**160**, new `slide` key **300**, `reel_seed_headline` 32→**60**. Per-style `max_onimage_chars` re-authored upward in the same pass (registry task T3.2). Precedence codified: config = global ceiling, style may only LOWER it (today's min() semantics, now stated in the PRD). | Root cause of 6/8 `no_onimage_text`. Multi-line allowed for `slide`/`panel` kinds only. |
| 0.6 | Vision fallback (Tier 2) | **IN scope**, behind `sources.vision_transcribe: true` (default true). When a slideshow's `intelligence_status` isn't ready or `panel_texts` is empty/mismatched, download its `image_urls` **for analysis only** and transcribe per-slide text + a one-line visual note via an OpenRouter vision call (one call per post, ~$0.005). Analysis-only carve-out written into D46: no Virlo URL or byte ever enters a render payload. | Without it, most fresh posts are unusable (probe: most recent rows had empty panels). |
| 0.7 | Caption policy | Publish caption = the source post's real caption when it has substance after hashtag-split (≥ 25 non-hashtag chars); else assembled from panel/hook material + platform hashtag convention. `description` never. | Kills hashtag-spam captions. |
| 0.8 | Session split | SESSION F = Waves 0–2, SESSION G = Waves 3–5 (live ladder in G, operator present). | One-session execution possible if preferred. |

---

## §1 — Evidence (probes 2026-08-13, monitor `9c96fddf-…`)

- `views desc` page (what the run fetched): slideshows span **2023-11 → 2026-07-20**, **0/100**
  in the UI week 3–9 Aug; videos **5/100**. The 8 quoted posts date Dec 2023 – Jul 2026.
- `created_at desc` page returns the UI grid's own authors (@appmillers, @mosedlat,
  @promprkhvzf, @orod215, @theaiplaybook101, @larpking47 …). Rows do not echo `created_at`.
- Slideshow rows carry `panel_texts` (Virlo's per-slide extraction), `panel_count`,
  position-sorted `image_urls`, `intelligence_status` — the last three currently **dropped**
  by the adapter (`virlo.py:972-975`). Many fresh rows have empty `panel_texts` (Tier 2 need).
- Quoted copy: 6× `P1.caption` (hashtag spam), 1× `P1.description` (**Virlo's AI summary**,
  published as our caption), 1× hook+caption. 6/8 creatives rendered with no on-image text
  (real hooks vs 34–42-char budgets). Every render was `gpt-image-2-image-to-image` over the
  style's Inspiration files → ~1:1 clones.

---

## §2 — D46 PRD amendment spec (Wave 0; apply only after operator approval)

**One decision, one version:** `D46 — Slideshow fidelity: recent-window sourcing, on-image
verbatim copy, text-only styles, panel-mapped carousels (v2.1.0, operator mandate
2026-08-13).` Supersedes **D2** (style refs attached) and the fetch clause of **D37**
(views-desc fetch; give it a body or supersede inline), amends **D42** (drop `description`
from the quotable set; degrade path re-based on §0.7), restates **D45**'s "sorted by views"
as "sorted by views within the recent window". New FRs from **FR-301**; bump registry
"Next fresh block"; amendment-log entry v2.1.0 per format; rebuild diagram; republish the
PRD artifact (same URL); every touched sibling re-verified. New OQ numbers from **OQ-23**.

### New FRs (FR-301+, homes in parentheses)
- **FR-301 (20-integrations §3)** — Fetch strategy: slideshows-only when
  `sources.include_videos: false`; `order_by=created_at desc`, pages `1..sources.fetch_pages`,
  dedupe by post id; client-side staleness cap `sources.max_post_age_days` on `publish_date`;
  rank by views among survivors. Passes stay inside the FR-246 session pool.
- **FR-302 (10-pipeline §4)** — The reference-label grammar `P<n>.<kind>[.<i>]`, normatively:
  kinds `hook | overlay | panel | caption`; `panel` indices are **source slide positions**,
  1-based, position-preserving (an unusable panel keeps its index; later panels never shift).
  (Also fixes the dangling `§1.x` citations.)
- **FR-303 (10-pipeline §4)** — `description` (Virlo's AI summary) is context-only: fenced
  into LLM prompts, recorded under `virlo_fields`, **never offered, rendered, or captioned**.
  Defines the verbatim-verifier requirement the dangling `copy_not_verbatim (FR-233)`
  citation points at (allocate as FR-303 or re-cite).
- **FR-304 (10-pipeline §5)** — Panel-mapped decks: for a carousel entry the assigned post
  MUST be a slideshow with usable per-slide text; our slide i renders source panel i's text
  verbatim; deck length per §0.4; meta.yaml gains `source_panel_count` + `panel_map`.
- **FR-305 (20-integrations §3 + 10-pipeline §3)** — Slideshow enrichment gate: rows lacking
  ready intelligence or with `len(panel_texts) ≠ panel_count` are ineligible as carousel
  copy sources; funnel counts `dropped_unenriched` / `dropped_stale` (FR-155 one-place rule).
- **FR-306 (20-integrations, new §)** — Tier-2 vision transcription (per §0.6): analysis-only
  ingestion of a slideshow's `image_urls`; output = per-slide transcribed text (treated as the
  post's `panel_texts`, provenance-tagged `vision_transcribed`) + one-line visual notes;
  **no Virlo URL/byte in any render payload** (D41 carve-out: download-for-analysis allowed,
  download-for-render still forbidden).

### Per-file edit list (from PRD recon; the executor applies ALL of these)
- **00-overview.md** — TL;DR (3 spots: "descriptions" in the pick list; "two reference
  images"; "reference images attached so results match"); G4; §Problem; walkthrough step 6;
  mermaid `STY` node + dotted-edge label + caveats paragraph; D32 (style-image clauses out);
  D41 ("1–2 reference images each" out); D42/D45 as above; Non-Goals adds "no image-to-image
  style references (D46)"; FR-Range Registry + Next-fresh-block; Amendment Log v2.1.0;
  Build-Time checklist item 5 note; OQ-17 closed-moot, add OQ-23 ("does text-only styling
  hold fidelity?" — answered by Wave 5's paid run).
- **10-pipeline.md** — FR-5 (components over window-filtered posts; recency-tilt prose
  re-based); FR-6 (+no in-window posts → dropped); FR-7 (disambiguate `trend_history_days`
  vs new sources keys); FR-8 (post-window supply); FR-13 (invert caption-first wording;
  fix "that fourth post's actual words" garble; carousel bullet cites FR-304); FR-14,
  FR-99/100/101/102 (offer set per F2; trimming contradiction resolved: never trim verbatim,
  30-config wording fixed); FR-105 (retry reduction against raised budgets); FR-17/18 (D2
  reversal; `styles.refs_per_job` tombstoned or re-scoped to briefs); FR-90 (affinity on
  windowed posts; carousel fallback to non-slideshow = famine, not silent bind); FR-91
  withdrawn (both copies); FR-94/95/97 (text-only rewrite; anchor stays sole image ref);
  FR-144/145 (brief-only attach); FR-290 (registry schema: `reference_images` removed,
  exclusions re-justified, rotation + upload-memo clauses die); §10 failure table (fifth
  Virlo cause "window emptied pool"; style-ref rows out); §12 D2 superseded; NFR-25 Pillow
  remnant fixed; stale §1.x citations → FR-302.
- **20-integrations.md** — §3 tool table (+FR-301; `description` marked context-only in
  both rows; slideshow-majority carve-out kept); FR-293 both copies: SourcePost gains
  **`published_at`**, `panel_texts` documented position-preserving, "ranked by views within
  the recency window"; §3 Invariants ("never fewer items" re-scoped pre-window); FR-32
  (videos call conditional); §8a/8b/8c (style-upload clauses out; stale "winning Virlo
  images" + `reference_images_per_job` fixed; §8c risk note cited as D46 evidence);
  FR-240/241 (default route = text-to-image absent brief refs); FR-271/272 (seam's upload
  verb scoped to briefs + artifacts); new §for FR-306.
- **30-configuration-and-run.md** — `sources:` gains `include_videos`, `fetch_pages`,
  `max_post_age_days`, `vision_transcribe` (+FR-170 registration, bounds, FR-138 pre-flight,
  FR-285-style refusal); `run.text_budgets` per §0.5 (+`slide` key; FR-259/FR-133/FR-188
  lockstep; trimming wording fixed); `run.formats` default mix §0.3; FR-257 band per §0.4;
  FR-280 default model route note; §7 Inspiration-folder + "reference-image pool" remnants
  out; stale seven-vs-five prompts (NFR-16/FR-284), FR-252 `analysis_missing`,
  `video_job_timeout_s` 600-vs-1800 — reconciled in passing.
- **40-outputs-and-logging.md** — FR-71/75 (refs/ = brief images only; A/B + D23 remnants
  out); FR-73 (carousel meta + `source_panel_count`/`panel_map`; degradation list: casing,
  `no_onimage_text` citation FR-227→FR-100, `copy_not_verbatim`→FR-303); §5 event shapes
  (`virlo_payload` post-window counts; `kie_job_submitted` style example out; `topic_posts`
  gains date; `virlo_fields` notes description-as-context); FR-155 funnel vocabulary +
  window/enrichment drop lines; FR-296/297 (caption states the window; roster age column now
  backed by data); FR-299 ("per-upload style-file lines" out, also in 30-§5).
- **50-promptcraft.md** — FR-181/§1(a)/§6(a) (worked example rewritten: no attached panels,
  no style refs); FR-188 (new values); FR-189/193 strengthened as the sole consistency
  mechanism; FR-191 scoped to brief/anchor/seed refs; placeholder list (+ on-image sibling
  of `{{source_hooks}}`, per-slide panel slot for FR-304); copywriter playbook (panel-first
  offer, description ban, deterministic slide mapping).
- **60-publishing-postiz.md** — no change (FR-221 cited by FR-257 band).

---

## §3 — Architecture (code anchors from recon; executors follow these seams)

**F1+F4 sources (`hypesocials/sources/virlo.py`, `virlo_mcp` untouched):** params builder
loops pages (wrapper already accepts `page`, `created_at`); videos call skipped per §0.2;
new gate pass between `_dedupe` and `_source_rows` (staleness, enrichment, panel-count
reconciliation) feeding new `Counters` fields (as_event/summary_line/funnel block);
`_source_post` keeps `panel_texts` **index-preserving** (empty panels keep their slot;
today's compaction at `virlo.py:832` is the F4 hazard) and consumes `intelligence_status`,
`panel_count`, `image_urls` (`_CONSUMED_POST` updated); `SourcePost.published_at` already
exists — FR-293's doc catches up; rank stays views-desc within survivors (the `P<n>`
alphabet, roster and sort proof keep their meaning); strength components now computed over
the windowed set (no formula change). Tier-2 vision (`FR-306`): new small module
`sources/transcribe.py` — httpx download to run temp dir, one OpenRouter vision call per
gated post, output written back onto the row as `panel_texts` + provenance flag; hard rule:
no downloaded path/URL reaches `generate/`.

**F2 copy (`hypesocials/copywrite.py` + `prompts_engine.py`):** `_CAPTION_KINDS` loses
`description` (kind survives in `_KIND_FIELDS` for parse-compat, `_lookup` refuses it);
offer order panels→overlays→hooks first-class; caption substance rule §0.7 in `_offer_for`;
`_fitting_slots` allows newlines for `slide` kind only; `_slot_budgets` gains `slide` budget
key; prompts_engine `_budget_line` stays in lockstep; carousel slide refs become
**deterministic panel mapping** (position-preserving resolution replaces gap-closing at
`copywrite.py:832-842`; LLM still picks cover headline + caption; `slide_refs` pinned to
panel order or bypassed); provenance `slide_<n>` keys become the panel map.

**F3 refs (`generate/refs.py`, `styles.py`, `prompts/styles.yaml`):** `_wanted` drops the
style channel (brief images + anchor/seed chains stay; `_MEMOS` survives for briefs);
`profiles.py` auto-routes text-to-image when no refs (already built); `styles.yaml`
re-authored: `reference_images` removed, `render_prompt`/DNA fields enriched to stand alone
(prompt-engineer, MAY read Inspiration files as authoring input), `max_onimage_chars`
raised per §0.5, exclusions reworded as plain negative constraints; `pick_reference_window`
+ `_store_references` + refs forecast row retired; `ref_source` re-based ("style" =
house-styled, attach count lives in `reference_set` event); preview `refs/` cleanup follows.

**F4 plan/deck (`plan.py`, `generate/carousel.py`, `config.py`):** carousel entries bind
slideshow posts hard (`_affinity` from tiebreak → constraint for carousels; famine message
gains the cause); `_emit`/`_Deck` take slide count from the assigned post's usable panel
count clamped per §0.4 (estimator keeps the ceiling); `_Deck` fallback-repeat replaced by
"render slide without text" for empty panels; per-slide prompt context gains
`source panel i of N`; format mix defaults per §0.3.

**Console (`runner.py`, `previews.py`):** topics-table caption names the window; funnel
gains `dropped_stale`/`dropped_unenriched`/`videos disabled` lines; roster unchanged
(age column now truthful); previews inherit via shared helpers.

---

## §4 — Waves and tasks

| Wave | Task | Owner | Files (disjoint) | Summary |
|---|---|---|---|---|
| **W0** | T0.1 | conductor + operator | `prds/*.md`, PRD artifact | Apply §2 in full; rebuild overview + diagram + log; republish artifact (same URL); sibling re-verify. |
| **W1** | T1.1 | python-pro | `sources/virlo.py`, `sources/__init__.py` | F1 window + F4 slideshow-only + gates + counters + index-preserving panels + consumed fields. |
| | T1.2 | python-pro | `config.py`, `configs/*.yaml` | New `sources.*` keys, `text_budgets` §0.5, formats §0.3, bounds + refusals. |
| | T1.3 | python-pro | `sources/transcribe.py` (new) | Tier-2 vision transcription per FR-306 (module + wiring seam only; called from T1.1's gate). |
| **W2** | T2.1 | python-pro | `copywrite.py`, `models.py` | Description ban, offer priority, caption rule, slide budget, deterministic panel mapping, position-preserving resolution. |
| | T2.2 | python-pro | `plan.py`, `generate/carousel.py` | Hard slideshow bind, source-driven deck length, empty-panel slides, famine cause. |
| | T2.3 | conductor | `runner.py`, `previews.py`, `prompts_engine.py` | Console window/funnel lines; budget-line lockstep; per-slide context. |
| **W3** | T3.1 | python-pro | `generate/refs.py`, `styles.py`, `preflight.py`, `outputs/gallery.py` | Style-ref excision end to end; `ref_source`/forecast/refs-folder re-base. |
| | T3.2 | prompt-engineer | `prompts/styles.yaml`, `prompts/**/*.md` | Registry re-author (text-only DNA, raised budgets, reworded exclusions); template updates (panel slot, ref-role scoping). |
| **W4** | T4.1 | test-automator | `tests/*` | Rework the ~14 mapped files (fetch contract, description ban, budgets min(), refs suites → brief fixtures, panel-mapping + window + gate regressions). |
| | T4.2 | technical-writer | `README.md`, `ACCEPTANCE.md` | Doc re-base. |
| | — | conductor | `NAVIGATION.md`, `CLAUDE.md` | Merge + glossary re-base; line report w/ attribution. |
| **W5** | T5.x | conductor + operator | — | Ladder: `--list-monitors` → `--preview-sources` (topics must now mirror the UI grid — the acceptance test) → `--preview-analysis` (panel-mapped copy visible) → ONE paid run (carousel-heavy, low cap) → closeout. |

**Barriers:** W0 = sibling-consistency read + artifact renders. W1/W2/W3 = full pytest green
+ line report per rule 5. W4 = suite green, zero skips. W5 = §checklist + operator sign-off.
Conductor owns aggregating files (`runner.py`, NAVIGATION, CLAUDE.md); no task shares a file.

---

## §5 — Wave-5 checklist (delta over the pivot's §5)

1. `--preview-sources`: every listed post's age ≤ `max_post_age_days`; authors overlap the
   Virlo UI's Most-Recent grid; funnel prints window/enrichment drops + `videos: disabled`.
2. `--preview-analysis`: carousel entries show `P1.panel.i → slide i` mappings; no
   `P*.description` anywhere; captions pass §0.7; vision-transcribe provenance visible when
   it fired.
3. Paid run: decks render source panel texts in order (byte-verify vs `topic_posts`+meta
   `panel_map`); on-image hit-rate ≥ 6/8; no `gpt-image-2-image-to-image` job without a
   brief/anchor reference; no Virlo host in any render payload (grep events); style
   adherence judged from gallery (OQ-23).
4. Ledger/estimator sanity with carousel-heavy mix; final `wc -l` vs 19,223 with attribution.

---

*Approval gates: §0 decisions → then W0 may run; §2 text → operator per D15; W5 spend →
Confirm gate as always.*
