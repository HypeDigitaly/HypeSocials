# xmasterplan — Slideshow Fidelity Fix (D46, v2.1.0) — v2.1 APPROVED+REVISED+REVIEWED

**Status: §0.1–0.8 APPROVED 2026-08-13 (operator, D15 step 2). v2.0 added F5/F6/F7 with
§0.9–0.13 recon-settled defaults; v2.1 integrates a 25-finding adversarial review
(5 blockers fixed — wave ordering, Confirm-gate money boundary, estimator, F23-vs-panels,
barrier feasibility — plus 20 major/minor). §0.9–0.14 are flagged to the operator at
SESSION F dispatch; silence = consent.**

Settled §0 values: 0.1 `max_post_age_days: 30`, `fetch_pages: 3`, `created_at desc`;
0.2 videos off; **0.3 operator override: all-carousels `run.formats: {image: 0, carousel: 6,
reel: 0}`**; 0.4 deck length from Virlo `panel_count` at ASSIGN (see below); 0.5 budgets
headline 42→90, subline 60→160, new `slide` 300, seed 32→60 (effective only once W3
re-authors the style caps — the min() rule; hit-rate evidence is W5's job, not W1/W2's);
0.6 vision tier IN, on by default; 0.7 caption substance ≥25 non-hashtag chars;
0.8 SESSION F = W0–W2, SESSION G = W3–W5.

Written 2026-08-13 after the operator rejected run `20260813_093720_7hiu` against the
Virlo UI. Evidence: fresh MCP probes of monitor `9c96fddf-…` (§1) + three recon reports
(fetch/copy/refs; history/cadence; gallery/outputs) + one adversarial plan review.

---

## TL;DR (plain English)

The first paid run quoted the wrong posts (all-time winners, some from 2023), the wrong
text (under-post hashtag captions — once Virlo's own AI summary — instead of the words ON
the slides), and cloned the Inspiration images ~1:1. Recon also proved the no-repeat
protection is broken (a topic with one fresh post re-quotes yesterday's exact post). Fixes:

1. **F1 — Fetch this week, not all time.** Newest collection rounds, 30-day age cap,
   ranked by views within that pool.
2. **F2 — Quote the on-image words.** Panel texts/hooks/overlays first-class for pixels
   AND captions; Virlo's AI `description` banned from every output; budgets raised.
3. **F3 — Styles are guidelines, not templates.** No style reference images to the
   renderer; enriched textual style DNA carries the look. Brief images + anchor/seed stay.
4. **F4 — Slideshows in, carousels out.** v1 sources only slideshows; source slide N's
   text becomes OUR slide N's text, verbatim, position-preserving.
5. **F5 — Never repeat, on any cadence.** Repeat protection moves to stable post IDs,
   enforced at fetch AND at pick; history window auto-covers the fetch window. Weekly
   cadence recommended; daily allowed with measured supply arithmetic.
6. **F6 — Read every slide with AI eyes.** For each assigned source slideshow (after the
   Confirm gate — it costs money), download its slides (analysis only) and have Claude
   Sonnet 5 transcribe the exact text AND describe each slide's visuals (charts, icons,
   graphics, layout) so our render prompts reproduce the *content* in OUR style.
   Competitor logos are described-but-excluded.
7. **F7 — Show your work.** The gallery shows, per carousel: source-post provenance
   (author, views, date, permalink, original caption), each ORIGINAL slide with its
   extracted text, and OUR rendered slide aligned beside it.

PRDs (text + mermaid flow diagram) are amended first (D46, FR-301–309, v2.1.0), then code,
then a cheap-first live ladder.

---

## §0 — Decisions (0.1–0.8 operator-settled; 0.9–0.14 defaults set by recon + review)

| # | Decision | Setting | Rationale |
|---|---|---|---|
| 0.4′ | Deck length (review fix #4) | Slide count = **Virlo `panel_count`** (free, known at fetch) clamped `[2, platforms.<p>.carousel_slides]`, fixed at ASSIGN, feeding the estimate BEFORE Confirm. Vision output never changes deck length — it is additive content. Truncation when source > ceiling: **first N panels, indices preserved, degradation tag `panels_truncated`**. | Kills the estimate-vs-deck circularity; Confirm gate stays honest (rule 7). |
| 0.9 | Run cadence | **Weekly recommended** (Task Scheduler + `--yes`); daily permitted. FR-307 documents the supply arithmetic **as a W5-measured figure** (the ~60–150/monitor estimate is unverified until the new funnel counts it — placeholder in the PRD until then). | Matches Virlo's weekly rounds; honest famine over silent repeats. |
| 0.10 | No-repeat identity & invariant | **Post-ID-level**, enforced twice: fetch gate drops used posts before ranking (`dropped_used`) AND pick-time guard (plan binds a specific fresh `post_id`; copywrite refuses burnt). Topic gate stays as backstop. **Invariant `run.trend_history_days ≥ sources.max_post_age_days`, pre-flight refusal. Defaults 30/30.** When a topic's fresh slideshow posts are exhausted mid-plan, the entry **skips with `no_fresh_post_available`** (funnel-counted) — never wraps, never repeats. `trend_reuse_index` is retired with its consumers (post pick + ref-window rotation both die; docstring + the copy-prompt "prefer a different post per sibling" sentence at `prompts_engine.py:1234` go with it). | Topic keys drift; post IDs are stable. |
| 0.11 | Slide intelligence scope & model | Vision runs for **every assigned carousel source post** (≤6/run), **after the Confirm gate, before COPY** (it is paid LLM spend — estimator gains a `slide_intel` line). One Claude Sonnet 5 call (existing OpenRouter "analysis" role) with all slide images. Returns per slide: `onimage_text` (verbatim transcription), `visual_brief` (graphics/charts/icons/composition, described for reproduction, **always in English** — render prompts are English; on-image text stays source-language), `brand_marks`. Virlo `panel_texts` preferred VERBATIM source when present; vision fills gaps (`vision_transcribed` provenance). Prompt file: **`prompts/slide_intel_question.md`** (FR-174 seam, parity-tracked). | Cost ~$0.01–0.03/post; estimated pre-Confirm from panel counts. |
| 0.12 | Brand safety for extracted visuals | `visual_brief` = CONTENT directive under the meta-style's look. Competitor logos/wordmarks (blocklist + `brand_marks`): genericized, never "reproduce X's logo"; competitor filter runs over vision text exactly as over Virlo text. Platform chrome/watermarks excluded outright. | Words verbatim; other brands' pixels never cloned. |
| 0.13 | Source-slide storage | Run-level `output/<run>/source/<post_id>/`: `slide_NN.jpg` (downloaded once via packager's client `packager.py:322`; same bytes feed vision) + `source.yaml`. Deduped across siblings. `meta.yaml.panel_map` holds relative pointers + resolved text. Gallery references relatively (FR-75 amended); **never published** (FR-213), **never uploaded to Kie** (`render.upload_file` is the carve-out boundary). | Self-contained offline gallery; Virlo CDN expires. |
| 0.14 | Edge rules (review fix #5/#25) | (a) **Panel usability**: `panel_texts` ingested index-aligned to `panel_count` (empty slots padded, never compacted); a panel slot is usable iff non-empty after merge(Virlo, vision); deck-eligible iff ≥2 usable slots. (b) **F23 exclusions for `panel`-sourced slide text**: emoji, newlines and `#`-tokens ALLOWED (they are the source deck's own voice); `@handles` and URLs still excluded (identity/link leakage). Other kinds keep full F23. (c) **Slide-intel degrade matrix (fail-open, never aborts)**: vision call fails/times out → keep Virlo panels, tag `vision_unavailable`; download 404 → that slide has no source image in the gallery, brief absent; fewer briefs than slides → align by position, missing = absent. (d) **Override-brief carousels** (`brief_influence == "override"`) bind no source post: FR-304 does not apply, `panel_map` empty, `source_post` null, gallery falls back to today's card layout. (e) **Formats guard**: pre-flight refusal when `sources.include_videos: false` and `formats.image + formats.reel > 0` (every topic is slideshow-majority; images/reels would silently rank-fallback forever). | Closes every two-ways-to-implement gap the review named. |

---

## §1 — Evidence (probes 2026-08-13, monitor `9c96fddf-…`)

- `views desc` (what the run fetched): slideshows span **2023-11 → 2026-07-20**, **0/100**
  in the UI week; videos **5/100**. The 8 quoted posts date Dec 2023 – Jul 2026.
- `created_at desc` returns the UI grid's own authors (@appmillers, @mosedlat,
  @promprkhvzf, @orod215 …). Rows do not echo `created_at` (window = page depth + age cap).
- Slideshow rows carry `panel_texts`, `panel_count`, position-sorted `image_urls`,
  `intelligence_status` — the last three currently dropped by the adapter. Many fresh rows
  have empty `panel_texts` (vision tier need).
- Quoted copy: 6× hashtag-spam captions, 1× Virlo's AI summary as our caption, 6/8 with
  no on-image text, every render i2i over Inspiration files.
- History: topic-gate over post evidence; pick history-blind (`copywrite.py:406`); topic
  keys drift (live file shows key-format mix).

---

## §2 — D46 PRD amendment spec (Wave 0; operator-consented)

**One decision:** `D46 — Slideshow fidelity: recent-window sourcing, on-image verbatim
copy, text-only styles, panel-mapped carousels, post-level no-repeat, analysis-only slide
intelligence, provenance gallery (v2.1.0, operator mandate 2026-08-13).`
Supersedes **D2**; supersedes the fetch clause of **D37** (no §-body exists — one line in
D46); amends **D42**; restates **D45**'s "sorted by views" as views-within-window;
**extends D41** with the analysis carve-out (downloading Virlo media FOR ANALYSIS/DISPLAY
allowed; any Virlo byte/URL in a render payload forbidden — code boundary
`render.upload_file`). New FRs **FR-301–309**, each with ONE owning file (cross-refs
elsewhere; fix the FR-293 dual-listing discrepancy in the registry in the same pass);
registry bullet list AND the "Files in this PRD" table's `FR blocks:` column updated;
"Next fresh block" → FR-310+; amendment-log entry v2.1.0; **mermaid rebuilt** (STY
text-only; new nodes: Collect history gate, post-Confirm slide-intelligence step,
run-level `source/` store feeding the gallery; style-upload edge removed); PRD artifact
republished same URL, verified to render; siblings re-verified. New OQs from OQ-23.

### New FRs (owning file first; cross-ref files in parentheses)
- **FR-301 — 20-integrations §3** (10-pipeline xref) — Fetch strategy: slideshows-only
  when `sources.include_videos: false`; `order_by=created_at desc`, pages
  `1..fetch_pages`, dedupe by post id; staleness cap on `publish_date`; **used-post drop
  in the same gate pass (FR-307)**; rank by views among survivors; FR-246 pool unchanged.
- **FR-302 — 10-pipeline §4** (50-promptcraft xref) — Label grammar `P<n>.<kind>[.<i>]`,
  kinds `hook | overlay | panel | caption` (**`description` removed from the grammar
  itself** — `_REF`/`_KIND_FIELDS`, not just the caption list); `panel` indices = source
  positions, 1-based, position-preserving. Fixes dangling `§1.x` cites.
- **FR-303 — 10-pipeline §4** (40-outputs xref) — `description` context-only: fenced into
  prompts, ledgered in `virlo_fields`, never offered/rendered/captioned; formalizes the
  verbatim verifier (`copy_not_verbatim` cite).
- **FR-304 — 10-pipeline §5** (40-outputs xref) — Panel-mapped decks: a non-override
  carousel entry binds a slideshow post with ≥2 usable panel slots (§0.14a); slide i
  renders source panel i verbatim; deck length per §0.4′ (panel_count at ASSIGN;
  `panels_truncated` on ceiling cut); override briefs exempt (§0.14d); meta gains
  `source_panel_count` + `panel_map`.
- **FR-305 — 20-integrations §3** (10-pipeline xref) — Eligibility gates: stale /
  unenriched (per §0.14a predicate) / used rows dropped pre-rank; funnel counts
  `dropped_stale` / `dropped_unenriched` / `dropped_used` (FR-155 one-place rule).
- **FR-306 — 20-integrations, new §** (50-promptcraft xref) — Slide intelligence per
  §0.11/0.14c: post-Confirm, analysis-role Sonnet 5, one call per assigned post;
  downloads to `source/<post_id>/` (§0.13); prompt `prompts/slide_intel_question.md`;
  estimator line; **no Virlo URL/byte in any render payload**.
- **FR-307 — 30-configuration §6** (10-pipeline FR-7 xref) — Cadence & no-repeat:
  post-ID exclusion at gate AND pick; `no_fresh_post_available` skip (§0.10); invariant
  `trend_history_days ≥ max_post_age_days` refused at pre-flight; defaults 30/30; weekly
  recommendation + supply figure (W5-measured placeholder); famine causes.
- **FR-308 — 50-promptcraft** (10-pipeline xref) — Visual-brief rendering: each slide
  prompt carries its brief (English) as content directive under the style DNA;
  brand-safety per §0.12.
- **FR-309 — 40-outputs §3, after FR-76** — Provenance gallery: three-part carousel card
  (provenance header; source panel strip, local relative copies, never hotlinked, each
  with extracted text/brief; our slides aligned by index); override-brief fallback
  (§0.14d); cites amended FR-71/72/75.

### Per-file edit list (W0 applies ALL; ⊕ = added in v2.0/v2.1)
- **00-overview.md** — TL;DR ×3 + ⊕"skips topics it already used recently" → post-level;
  G4; ⊕G8; §Problem; walkthrough step 6; mermaid per above + caveats; D32; D41 carve-out
  into D-body; D42/D45/⊕D37 line; Non-Goals + "no image-to-image style references";
  ⊕BOTH FR-range surfaces (table `FR blocks:` column at :204-212 AND registry list at
  :215-222, incl. FR-293 discrepancy fix) + Next-fresh-block FR-310+; Amendment Log
  v2.1.0; Build-checklist item 5; OQ-17 moot, ⊕OQ-23. ⊕Success-metric fidelity line
  untouched (FR-232's 3-point scale is kept — review #17; the new judging criterion goes
  in FR-150 only).
- **10-pipeline.md** — FR-5 (windowed; recency-tilt re-based); FR-6; ⊕FR-7 (pick-time
  clause; per-post logging honoured); FR-8; FR-13 (invert caption-first; fix garble;
  cite FR-304); FR-14; FR-99/100/101/102 (offer set; ⊕§0.14b panel-kind F23 relaxation
  written into FR-100; trimming contradiction resolved); FR-105; FR-17/18
  (`styles.refs_per_job` tombstoned); FR-90 (windowed; carousel fallback → famine;
  ⊕§0.14e guard); FR-91 withdrawn ×2; FR-94/95/97 (text-only; anchor sole image ref;
  ⊕FR-95 slide prompt carries visual_brief per FR-308 xref); ⊕FR-107 (estimate basis:
  panel_count-at-ASSIGN deck lengths + slide_intel line); FR-144/145; FR-290 (schema
  minus `reference_images`; rotation/upload-memo clauses die); §10 failure table (fifth+
  sixth Virlo causes); §12 D2 superseded; NFR-25; §1.x → FR-302.
- **20-integrations.md** — §3 tool table (+FR-301; description context-only ×2;
  slideshow-majority carve-out); FR-293 ×2 (+`published_at` documented; `panel_texts`
  position-preserving ⊕index-aligned to `panel_count`; `image_urls`/`panel_count`/
  `intelligence_status` consumed; views-within-window); §3 Invariants re-scoped; FR-32
  (videos conditional; ⊕§0.14e); §8a/8b/8c fixes + §8c risk note as D46 evidence;
  FR-240/241 (default route text-to-image — ⊕the CODE change is `config.py:165`
  `models.image` default, owned by T1.2); FR-271/272 (upload verb: briefs + generated
  artifacts, ⊕never `source/`); ⊕new § FR-306.
- **30-configuration-and-run.md** — `sources:` + `include_videos`, `fetch_pages`,
  `max_post_age_days`, `vision_transcribe` (FR-170, bounds, FR-138, refusal posture);
  ⊕`trend_history_days` 30 + invariant + disambiguation; `run.text_budgets` §0.5
  (+`slide`; FR-259/133/188 lockstep; trimming wording); ⊕`run.formats` all-carousels
  (sample YAML :238 + **FR-132/§2** — NOT FR-133, review #20); FR-257 band §0.4′;
  FR-280 route note; ⊕§6 gains FR-307; §7 stale lines; seven-vs-five prompts, FR-252,
  `video_job_timeout_s` reconciled; `--history-days` invariant note; ⊕models section
  notes the analysis-role slide-intel usage + estimator line.
- **40-outputs-and-logging.md** — FR-71 (refs/ = brief only; A/B+D23 out; ⊕declares
  `source/<post_id>/` + `source.yaml` schema: post provenance {post_id, url, author,
  views, published_at, caption}, per-slide {position, virlo_text, vision_text,
  visual_brief, brand_marks, image_file}, vision provenance + model id); ⊕FR-72
  (publishable enumeration; `source/`+`refs/` excluded); FR-73 (+`source_panel_count`,
  `panel_map`, nested `source_post`; degradation vocabulary: casing, cite fixes,
  ⊕`vision_transcribed`, `vision_unavailable`, `panels_truncated`,
  `no_fresh_post_available`); FR-75 (⊕`source/` as allowed relative root; hotlink ban
  stays); ⊕FR-76 (implements its promised author/views/post-id + FR-309 xref); ⊕FR-150
  (third judging criterion: panel fidelity; footer clause rewritten) — FR-232 scale
  UNCHANGED; ⊕FR-82 key-format truth-up + FR-153 mapping-vs-pipe reconciled; §5 event
  shapes (`virlo_payload` post-window counts; `kie_job_submitted` style example out;
  `topic_posts` + `published_at` + panel/image counts + vision provenance;
  `virlo_fields` note); FR-155 vocabulary + three drop lines; FR-296/297; FR-299.
- **50-promptcraft.md** — FR-181/§1(a)/§6(a) (worked example: no attached panels/style
  refs; ⊕visual_brief-driven slide prompt example); FR-188 (new values); FR-189/193
  strengthened; FR-191 scoped; placeholders (⊕`{{visual_brief}}` + per-slide panel slot +
  on-image sibling of `{{source_hooks}}`; FR-182/183 tables incl.
  ⊕`prompts/slide_intel_question.md`); copywriter playbook (panel-first, description ban,
  deterministic mapping, burnt-post refusal, ⊕no "prefer a different post per sibling").
- **60-publishing-postiz.md** — ⊕FR-213: publishable set = FR-72's enumeration;
  `source/`+`refs/` never uploaded.

---

## §3 — Architecture (code anchors; review-corrected)

**F1+F4+F5 sources (`sources/virlo.py` + `models.py` SourcePost block):** SourcePost
gains `image_urls`, `panel_count`, `intelligence_status` fields **in W1** (T1.1 owns the
SourcePost block of models.py; T2.1 owns PlanEntry/AssetRecord in W2 — split ownership,
different waves). Params builder loops pages; videos call skipped; ONE gate pass between
`_dedupe` (:744) and `_source_rows` (:761): staleness → enrichment (§0.14a) → used-post
drop (the `used` frozenset at :401 finally consumed); each a `Counters` field WITH its
`as_event`/`summary_line` lines (same file, T1.1 — zeros print, review #21);
`_source_post` keeps `panel_texts` **index-aligned to panel_count** (padding, never
compaction — :832 fixed); `_CONSUMED_POST` (:972) updated; rank views-desc within
survivors; strength over the windowed set.

**F6 slide intelligence (new `sources/slide_intel.py` + `prompts/slide_intel_question.md`):**
runs **after the Confirm gate, before COPY** (paid; estimator line lands with T2.2's
budget.py work; deck lengths were already fixed at ASSIGN from panel_count, §0.4′). Per
assigned post: download slides via packager client (:322) into
`output/<run>/source/<post_id>/` (one download, two uses: vision input + gallery), ONE
StructuredCall (analysis role, vision_check `_load`/schema/prompt pattern) →
`{onimage_text, visual_brief(EN), brand_marks}` per slide; degrade matrix §0.14c; write
`source.yaml`; competitor filter over vision text. Nothing from `source/` reaches
`generate/refs.py` or `render.upload_file`.

**F2 copy (`copywrite.py` + `prompts_engine.py`):** `_REF`/`_KIND_FIELDS` drop
`description` (grammar-level, review #19); `_CAPTION_KINDS` shrinks; offer order
panels→overlays→hooks; caption substance §0.7; `_fitting_slots` per §0.14b (panel-kind:
emoji/newline/# allowed, @/URL excluded); `_slot_budgets` + `_budget_line` lockstep with
`slide` key; **pick consumes the plan-bound post id** (modulo pick at :406 retired with
`trend_reuse_index`, incl. `prompts_engine.py:1234`'s sibling sentence); deterministic
position-preserving panel mapping replaces gap-closing (:832-842); provenance `slide_<n>`
keys = panel map. W2 placeholder work: `models.PLACEHOLDERS` (T2.1), engine slots (T2.3),
and a minimal template edit adding the new placeholders to the carousel-slide templates
(T2.3 carve-out) so `test_template_parity` stays green at the W2 barrier; full template
re-author remains T3.2.

**F3 refs (`generate/refs.py`, `styles.py`, `preflight.py`, registry):** style channel
out; brief images + anchor/seed stay; **`config.py:165` `models.image` default flips to
the t2i route (T1.2)** — profiles already dual-route; registry re-authored text-only with
raised caps (W3; §0.5 note); rotation/forecast retired; `ref_source` re-based.

**F4 plan/deck (`plan.py`, `generate/carousel.py`, `budget.py`, `menu.py`):** carousel
entries bind a **specific fresh slideshow post id** at ASSIGN (PlanEntry gains the field;
affinity constraint for carousels; `no_fresh_post_available` skip per §0.10); deck length
= panel_count clamped §0.4′ set at ASSIGN; `_Deck` renders empty-usable panels as
no-text slides; per-slide context gains `source panel i of N` + visual_brief;
**`budget.py`: slide pricing from the entry's bound deck length + `slide_intel` estimate
line (T2.2)**; **`menu.py`: formats step + "2 order {2×slides} images" wizard prose
re-based (T2.3)**; famine causes extended.

**F7 outputs (`models.py` AssetRecord — T2.1, `outputs/packager.py` — T1.3,
`outputs/gallery.py` + `generate/__init__.py` — T3.3):** AssetRecord gains `source_post`
(nested, ISO strings), `source_panel_count`, `panel_map` (slide, source_position,
source_text, ref_label, visual_brief, source_image relpath) — real dataclass fields
(`AssetFolder.update()` rejects unknowns, :186); `_record()` joins `env.trends[...]`
posts by bound post id. Packager: `store_source()` reusing `_download` (:322) +
`store_bytes` under run-level `source/`. Gallery: `_load` skips `source/` (:122);
FR-309 three-part carousel cards + override fallback; footer/criterion updated; template
placeholders added to `.format()` (:110); CSS braces doubled.

**Console (`runner.py`, `previews.py`):** stage wording, window in captions, famine
messages (funnel counter LINES live in virlo.py with T1.1); previews inherit.

**History (`outputs/state.py`):** schema unchanged; doc truth-up only.

---

## §4 — Waves and tasks (single-writer per wave; test updates are IN-WAVE)

**Barrier rule (review #2):** every W1–W3 task UPDATES the tests its change breaks, in the
same wave (the recon break-map: fetch-contract ×4, `_MEDIA_ORDER_BY` pin, description-
caption test, budgets min() suite, refs/rotation suites, template parity, funnel/console
inventory, plan affinity, state/history). W4 adds NEW regression tests + the sweep.
Barriers stay "full pytest green".

| Wave | Task | Owner | Files (disjoint per wave) | Summary |
|---|---|---|---|---|
| **W0** | T0.1 | conductor + operator | `prds/*.md`, PRD artifact | Apply §2 in full; rebuild diagram + BOTH registry surfaces + log; republish artifact (renders!); sibling read. |
| **W1** | T1.1 | python-pro | `sources/virlo.py`, `sources/__init__.py`, `models.py` (SourcePost block ONLY) | Window + slideshow-only + triple gate + counters WITH funnel lines + index-aligned panels + consumed fields + SourcePost fields. |
| | T1.2 | python-pro | `config.py`, `configs/*.yaml` | New `sources.*` keys; `trend_history_days` 30 + invariant refusal; §0.14e formats guard; budgets §0.5; formats §0.3; `models.image` t2i default flip; bounds. |
| | T1.3 | python-pro | `sources/slide_intel.py` (new), `prompts/slide_intel_question.md` (new), `outputs/packager.py` | F6 module + prompt file + `store_source()`; §0.14c degrade matrix; wiring seam consumed in W2. |
| **W2** | T2.1 | python-pro | `copywrite.py`, `models.py` (PlanEntry/AssetRecord/PLACEHOLDERS) | Grammar-level description removal; offer priority; §0.14b; caption rule; budgets; deterministic panel mapping; bound-post consumption + burnt refusal; `trend_reuse_index` retirement; AssetRecord fields. |
| | T2.2 | python-pro | `plan.py`, `generate/carousel.py`, `budget.py` | ASSIGN-time post binding + deck length; `no_fresh_post_available`; empty-panel slides; estimator (deck basis + slide_intel line); famine causes. |
| | T2.3 | conductor | `runner.py`, `previews.py`, `prompts_engine.py`, `menu.py`, minimal `prompts/**` placeholder carve-out | Console/stage wording; budget-line lockstep; per-slide context + visual_brief slot; slide_intel invocation post-Confirm; menu prose; parity-keeping template stubs. |
| **W3** | T3.1 | python-pro | `generate/refs.py`, `styles.py`, `preflight.py` | Style-ref excision; `ref_source`/forecast re-base. |
| | T3.2 | prompt-engineer | `prompts/styles.yaml`, `prompts/**/*.md` (full re-author) | Registry text-only DNA + raised caps (§0.5 becomes effective HERE); reworded exclusions; template re-author. |
| | T3.3 | python-pro | `outputs/gallery.py`, `generate/__init__.py` | FR-309 cards + override fallback + source-skip; `_record()` provenance join. |
| **W4** | T4.1 | test-automator | `tests/*` (new tests only) | NEW regressions: no-repeat pick guard, invariant refusal, §0.14 edges, gallery cards, slide_intel mocked, panel mapping E2E. |
| | T4.2 | technical-writer | `README.md`, `ACCEPTANCE.md` | Re-base incl. cadence guidance + gallery. |
| | — | conductor | `NAVIGATION.md`, `CLAUDE.md` | Merge + glossary; line report w/ attribution. |
| **W5** | T5.x | conductor + operator | — | Ladder per §5. |

**Barriers:** W0 = sibling-consistency + artifact renders. W1–W3 = full pytest green +
line report. W4 = suite green, zero skips. W5 = §5 + operator sign-off.

---

## §5 — Wave-5 live checklist

1. `--preview-sources`: every post age ≤ 30d; authors overlap the Virlo UI grid; funnel
   prints the three drop lines + `videos: disabled`; **record the measured usable-supply
   figure into FR-307's placeholder (W0 leaves it marked)**.
2. `--preview-analysis`: carousel entries show `P1.panel.i → slide i`; no
   `P*.description`; captions pass §0.7; slide-intel provenance + visual briefs visible.
3. ONE paid run (all-carousels, low cap): decks render source panel texts in order
   (byte-verify vs `panel_map` + `source.yaml`); on-image hit-rate ≥ 5/6; briefs visibly
   drove slide content (spot-check vs source slides in the gallery); no i2i job without
   brief/anchor ref; no Virlo host in any render payload (grep events);
   `source/<post_id>/` populated; gallery provenance + aligned strips work offline.
4. **No-repeat proof:** re-run `--preview-sources` ($0) — every post the paid run quoted
   appears under `dropped_used`; the plan would bind different posts.
5. Ledger/estimator sanity (incl. the slide_intel line, one-cent standard); final `wc -l`
   vs 19,223 with attribution; deep-module re-review of virlo/copywrite/gallery.

---

*Approval gates: §0.9–0.14 flagged at SESSION F dispatch; §2 operator-consented (D15);
W5 spend → Confirm gate as always.*
