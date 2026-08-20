# xmasterplan — Style Intelligence: archetype registry expansion, LLM-matched assignment, teal-spine unification (v2.4.0, D56/D57)

**Session:** I · **Approved by operator:** 2026-08-20 (plan-mode review; all decisions recorded below)
**Read first in a fresh session:** `plans/SESSION-H-CLOSEOUT.md` (latest closeout), then this file end to end.
**Standing rules:** the "Standing rules for every session" block at the bottom of `plans/EXECUTION-ORDER.md`
applies verbatim to every wave and every subagent prompt of this session.
**A plan is evidence, not authority.** Every file:line below was verified 2026-08-20 but the tree moves —
verify against the code and surface conflicts instead of following blindly.

---

## 1. Context (why)

Three connected problems, one session:

1. **Style assignment is rotation, not fit.** `styles.assign_styles` (`hypesocials/styles.py:613-659`,
   `_scan` :688-708) is a pure function of `entry.order` + crc32(run_id) over the FILE-ordered usable pool —
   content-blind by construction. Recent runs bound X-screenshot posts, lifestyle photos and dense
   infographics onto dark/graphic styles that fit none of them.
2. **The registry doesn't cover what actually trends.** A census of 21 distinct bound source posts from
   recent `output/<run>/source/` stores (§2) shows ~48% are listicle/infographic decks — an archetype the
   registry has zero styles for. The operator additionally wants the @courseprinter "build log" visual
   system reproduced as a style.
3. **No brand unification.** The 9 styles carry unrelated hand-authored palettes; `branding.enabled` is
   false everywhere and `branding_block` is subordinate to style DNA (`prompts_engine.py:854-908`,
   "Ranked BELOW the style"). The feed has no unifying color.

### Source-post census (measured 2026-08-20, the data behind every style decision here)

21 distinct posts, all with `vision.status: ok` in their `source/<post_id>/source.yaml`; two decks
(`ee92cdcb` run `20260820_093516_fybg`, `bd391d14` run `20260820_030557_f2zj`) verified slide-by-slide
visually. All 21 are TikTok photo slideshows; 18/21 text-heavy (>800 on-slide chars); median 7 panels.

| Archetype (primary) | Count | Registry coverage before this session |
|---|---|---|
| Listicle card deck (numbered icon-card rows, footer strip) | 6 | none |
| Dense infographic/diagram (light corporate clay-3D; dark neon circuit) | 4 | none |
| Tool-UI / app-mockup decks (fabricated chat/app windows) | 3 | partial (platform-showcase-card) |
| Terminal / code-card decks | 2 | partial (build-log-mono is typographic, not code-UI) |
| Social-screenshot reposts (X, Reddit, GitHub captures) | 2 | none |
| Lifestyle/POV photo decks | 2 | photoreal pair (re-enabled by this session) |
| Big-type text card | 1 | letterpress / build-log-mono |
| Mixed sales-poster | 1 | — |

Recurring tool marks in sources: Claude/Anthropic (8 posts), ChatGPT (5), GitHub (4), n8n/Notion/Canva/
Gemini (2 each) — FR-315 tool-logo patching stays load-bearing. Apparel/platform chrome noise (Nike, GAP,
IG badge, TikTok watermark) is already filtered by the `kind == "tool"` gate in `slide_intel._mark_boxes`
(`sources/slide_intel.py:169-175`) — no action.

---

## 2. Operator decisions (2026-08-20) — settled, do not re-litigate

1. **Unifying palette = shared teal spine.** The teal family both brand profiles already ship:
   #00A59A / #0C8897 (HypeDigitaly gradient teals) + #0FCFC4 / #57E6DC / #0A7F78 / #8BF2E9 (HypeLead).
   **No indigo** (#34288B / #2B3F8E), no other accent hues. Existing accents already inside the family
   qualify as on-spine (verified: anime-noir #17B7B0, platform-showcase #0C8897, editorial-voxel #0C8897).
2. **Mechanism = brand-tinted duplicate styles.** New `-teal` variant keys; originals untouched;
   `styles.enabled` switched to the variants. This *conforms to* standing decision D-G ("colour is curated
   by choosing styles, never by editing a style", `configs/default.yaml:196-197`, `prds/00-overview.md:310`)
   — D-G is NOT superseded.
3. **No-fit path = rotation fallback + gap report.** Never runtime style synthesis (would violate FR-295
   registry authority and FR-189 sole-consistency-mechanism). The matcher's "wanted archetype" note is
   persisted so the operator authors missing styles deliberately.
4. **Four census-driven archetype styles approved** (all four options taken): icon-listicle infographic,
   dark tech-diagram infographic, generic social-post card, chat/terminal mockup deck.
5. **Enabled pool = 12 keys** (§4.4); matched assignment is what keeps a 12-style pool coherent.
6. **`styles.assignment: matched` pinned in the three shipped brand configs**; engine default stays
   `rotation` (FR-291 remains the invariant substrate).

**Numbering (verified against `prds/00-overview.md:281`, next fresh block FR-334+):**
decisions → **D56** (registry expansion: build-log-mono + 4 archetype styles, count re-base 9→19),
**D57** (teal-spine unification via variants + 12-key enabled set); FRs → **FR-334** (matched assignment,
10-pipeline), **FR-335** (style-match prompt artifact, 50-promptcraft), **FR-336** (assignment config,
30-configuration), **FR-337** (match provenance in outputs, 40-outputs). Next fresh block becomes FR-338+.

---

## 3. Architecture keys (verified 2026-08-20)

- **Pipeline order** (`runner.py:376` `_pipeline`): preflight :401 → **CONFIRM :410 (before Collect!)** →
  COLLECT :418 → FILTER (one batched LLM screen, fail-open, `topic_filter.py:386`) → SELECT :427 (topics
  bound; `entry.trend_key` + `by_key[TrendItem]` in scope at the ASSIGN call site but NOT passed in today —
  the plumbing gap) → **ASSIGN :435** (`_assign_visuals` :480-505) → forecast :437 → INTEL :449 (FR-306,
  carousels only, fail-open) → COPY :450 → RENDER :451 → GAUNTLET. A matcher LLM call at ASSIGN is
  post-Confirm spend, priced pre-Confirm like `slide_intel` (`budget.py:501`).
- **Signals at ASSIGN (text-only, $0):** SourcePost (`models.py:135`): caption, hooks, text_overlays,
  panel_texts (+lengths), is_slideshow, panel_count, views. TrendItem (`models.py:191`): strength,
  why_it_works, hook_texts, **hook_types / visual_hook_types / emotional_tones (`models.py:234-236` —
  Virlo's own classification, currently read by NOTHING — free signal)**, engagement, hashtags. Derived:
  `plan.source_panel_count` :642, `plan.usable_panel_slots` :654, `plan.deck_length` :725.
- **LLM seam:** all calls via `llm.structured_call` (`llm.py:153`) wrapped by `runner._metered` (:1786 —
  cost tally, budget reconcile, events.jsonl). Roles `_ROLE_MODEL` runner.py:617, defaults
  `config.py:325-334` (analysis = claude-sonnet-5). Fail-open precedents: `topic_filter.py:211-220`,
  `slide_intel.py:778-783` (never raises).
- **New-template checklist:** PLACEHOLDERS names in `models.py`; `_ALLOWLIST` row `prompts_engine.py:148-219`;
  template file + `_BUILT_INS` twin (:1597); `GLOBAL_TEMPLATES` in `models.py:792-813`;
  `tests/test_template_parity.py` count pin.
- **Registry schema:** parsed key-by-key `styles.py:197-223` (unknown top-level keys silently dropped —
  authoring `match_profile` before the parser learns it is SAFE); dataclass `models.py:371-397`; validation
  `styles.py:456-536` (FR-295 exit 2 via `preflight.py:452-489`); `usable_styles` :393-408 + `fmt_affine`
  :435-448 own the pool predicates incl. `carousel_role: slides_only` — the matcher must IMPORT them, never
  re-derive.
- **Style → prompt:** `prompts_engine.build_context` :583-798 (mapping table :716-736); DNA joined by
  `style_dna` :799-817; budgets `min(config, style.max_onimage_chars)` :1438-1477; truncation trio
  `_STYLE_TRIO` :136; Kie hard cap 19,800 chars.
- **Plan-agent corrections already folded in (do not rediscover):** `_record_style_forecast` (runner.py:1711)
  only counts — per-entry console columns go on the ASSIGN receipt lines in `_assign_visuals` (:511-517);
  `_assign_visuals` must become **async** (awaited at :435); previews do NOT share it — deep preview wires
  the matcher separately in `previews._deep_stages` (:183-243, already spends metered LLM), plain
  `--preview-sources` has no ASSIGN stage; matcher answers join on **asset_id**, never ordinal (the
  ordinal-join pattern caused the W5 renumbering bug — see runner.py:438-447 comment); fit/reason/origin
  travel on **PlanEntry fields** (that's what `_record()` `generate/__init__.py:923` can see);
  `tests/test_prompt_fit.py:333` pins `len(set(STYLE_KEYS)) == 9` → bump to 19;
  `tests/test_console_inventory.py` pins console vocabulary → new lines need rows;
  `tests/test_branding.py:298-372` is unaffected (config profiles untouched).

---

## 4. Registry work (D56 + D57)

### 4.1 New style `build-log-mono` (extracted from @courseprinter carousels — full DNA spec, images not available to this session)

Two-ground brutalist-editorial typographic system:
- **Grounds:** near-black #0D0D0D and warm cream #F2F0EA, alternating per slide; anchor always dark.
- **Accent (teal spine):** #0FCFC4 on dark grounds, #0A7F78 on cream — micro-labels ONLY (series kicker
  with trailing-underscore cursor motif, e.g. "THE BUILD_"; "STEP NN" eyebrows). Palette states
  "accent under 5% of frame". Accent never in headlines or body.
- **Typography:** bold monospace/technical-grotesque ALL-CAPS headlines, 2-4 short lines, tight leading,
  wide tracking, cream-on-dark / near-black-on-cream; humanist sans body in mid-gray ~#9A9A9A, sentence
  case, 2-5 short lines; mono caps micro-labels with wide tracking.
- **layout_zones (fixed chrome grid every slide):** kicker top-left; "NN / NN" pagination top-right with
  `role: counter_slot`; headline block upper-third; body block below; @handle bottom-left with
  `role: brand_slot`; "SWIPE →" cue bottom-right.
- **per_format_guidance:** `carousel_cover` = dark ground + ONE hero 3D studio-render object (glass/chrome/
  matte, teal glow element; subject from content — `subject_mode: scene_open`); `carousel_slide` = pure
  typography, alternating grounds, optional STEP eyebrow. `visual_pacing` FIXES chrome, palette, type
  treatment per deck; MAY CHANGE ground (alternation), headline length, presence of eyebrow.
- `text_density: high`; generous `max_onimage_chars`; a full `list_mode` block (all three required fields —
  step decks are lists); `format_affinity: [image, carousel]`; `brand_affinity: []`; `motion_profile:
  graphic`; exclusions: no photographic scenes, no faces, no platform UI, no second accent hue.
  M9: no "or"/either-or in `render_prompt` (≤120 words).

### 4.2 Four archetype styles (census-driven; all teal spine; each with its own `match_profile`)

1. **`icon-ledger-carousel`** (icon-listicle infographic; covers the 6-post listicle cluster + light
   corporate infographics): light ecru ground; bold condensed near-black headline block; numbered rounded
   icon-card rows (flat/clay glyph in teal circle + bold row title + one-line grey description); footer
   banner strip; one 3D clay hero object on the cover. `text_density: high`; `list_mode` mandatory (the
   rows ARE the list panel); generous slide budgets.
2. **`circuit-atlas-dark`** (dark tech-diagram infographic; covers the neon/benchmark cluster): near-black/
   deep-charcoal ground; glowing teal circuit/node motifs; hub-and-spoke diagrams with labeled icon chips;
   "What it is / Why it matters" card pairs; big white headline top. DNA caps diagram node count (~6 labeled
   nodes max) and greeks all unlabeled chip text — many-node labeled diagrams are gpt-image-2's weakest
   render; the cap is load-bearing. `text_density: high`; `list_mode`.
3. **`social-quote-card`** (generic social-post card; covers X/Reddit/GitHub repost archetypes): stylized
   post-screenshot — soft-shadow rounded card on a calm ground; abstract avatar circle (never a real person
   or logo); bold handle line + muted meta line; the post text as the large headline device; generic
   engagement glyphs (heart/arrow/bubble shapes) in a muted row. **Exclusions are load-bearing: no real
   platform names, logos, chrome or counters (X/Reddit/Discord/IG all banned) — evoke the format, never
   imitate a platform** (gauntlet leakage hard-blocks; §0.12). Any rendered handle is OUR handle or blank,
   per the social-marks scrub rules. `text_density: moderate`.
4. **`terminal-mockup-deck`** (chat/terminal mockup; covers tool-UI mockups + code-card decks): dark IDE
   aesthetic — generic window chrome (plain traffic-dot bar, no OS/app branding); greeked-or-sanctioned code
   blocks; prompt-example boxes (bad/good pattern); chat-bubble pairs; teal syntax-accent + cursor motif.
   Complements build-log-mono (typographic) and platform-showcase-card (browser/product). Same
   no-real-platform exclusions as social-quote-card. `text_density: high`; `list_mode`.

### 4.3 Five `-teal` variants (D57; originals untouched, D-G intact)

Copy each original; re-role ONLY the accent palette entries onto spine hexes; grounds/surfaces/type stay
native; coverage limits and "teal is accent only, never full-bleed" respected; accents in photographic
styles stay physical (objects, light casts) — never graphic overlays:
`letterpress-print-carousel-teal` (terracotta ink → teal ink), `meme-caricature-panels-teal`,
`quiet-luxury-night-photoreal-teal` (city-light accents → teal cast), `photoreal-ambient-caption-teal`
(pale-oak accent object → teal ceramic/glass object), `ugc-tabletop-statement-teal` (accent prop → teal
object). Each gets its own `match_profile`. NO variants for anime-noir-statement / platform-showcase-card /
editorial-voxel-carousel / hypelead-brand-card (already on-spine or brand-slot).

**Registry final count: 19** (9 originals + build-log-mono + 4 archetype + 5 variants). Every one of the
19 entries gets a `match_profile:` (1-2 sentences: "what sources this style suits").

### 4.4 New `styles.enabled` (12 keys, all three shipped brand configs)

`anime-noir-statement`, `platform-showcase-card`, `letterpress-print-carousel-teal`,
`meme-caricature-panels-teal`, `quiet-luxury-night-photoreal-teal`, `photoreal-ambient-caption-teal`,
`ugc-tabletop-statement-teal`, `build-log-mono`, `icon-ledger-carousel`, `circuit-atlas-dark`,
`social-quote-card`, `terminal-mockup-deck`.
(`meme-caricature-panels-teal` inherits `carousel_role: slides_only` — inert on carousel-only plans, kept
deliberately, same ruling as D55.)

---

## 5. Matched assignment (FR-334-337)

- **New leaf module `hypesocials/style_match.py`** (~300 lines), mirror of `topic_filter.py`: ONE batched
  fail-open LLM call per run, role `analysis` (Sonnet 5), own template, own hand-built answer schema,
  never raises. styles.py stays sync/offline (only gains the `match_profile` parse + `match_profile_for()`
  helper + advisory missing-field warning at `_style_warnings` :588).
- **Flow at ASSIGN:** compute the FR-291 rotation baseline first via the existing `assign_styles()`
  (unchanged); when `config.styles.assignment == "matched"`, call
  `style_match.match(styled_entries, registry, topics_by_key, config, llm)`; overwrite winners in place;
  stamp provenance. Per-entry candidate pool = `usable_styles(...)` × `fmt_affine(entry.creative_format)`
  (imported predicates). Prompt carries per-entry sections keyed by asset_id: format, source signals (§3),
  candidate pool described by each style's `match_profile`.
- **Answer per asset_id:** `style_key` (validated ∈ that entry's pool) + `fit: high|medium|low` + short
  `reason` + `wanted_archetype` (only when low). `medium` ACCEPTS the pick. `low` / invalid key / missing
  row → entry keeps its rotation-baseline pick, `style_origin: "rotation"`, `style_wanted` preserved.
  Whole-call failure → ALL entries on baseline, `style_origin: "rotation_fallback"`, degradation tag
  `style_match_degraded`, one console warn, run continues.
- **Provenance:** new `PlanEntry` + `AssetRecord`/meta.yaml fields `style_fit`, `style_reason`,
  `style_origin`, `style_wanted` (FR-73 mirror); gallery card label `style: X · matched/high` + wanted-
  archetype note on fallback cards; ASSIGN receipt lines gain origin/fit/reason columns; a gap-report block
  after the loop lists distinct `wanted_archetype` strings (D45 console rules).
- **Config:** `StylesConfig.assignment: Literal["rotation","matched"] = "rotation"` (`config.py:561-597`;
  generic loader gives parse + Literal validation free). Shipped `hypedigitaly*.yaml` pin `matched`.
- **Budget:** new `_style_match_lines()` called from `_llm_lines` (`budget.py:579`), gated on
  `assignment == "matched"`, excluding override-brief entries (they are never styled — runner.py:495):
  one `style_match_call` line (role analysis, reasoning 0) + `style_match_retry_allowance` (2,
  `_widened_cap`). Quoted at Confirm per rule 7.
- **Previews:** matched branch in `previews._deep_stages` after its `assign_styles` (:206-216) with
  `_metered(session)`; `_assign_block` receipt gains the same columns. `--preview-analysis` therefore
  exercises the matcher for $LLM-only.
- **Determinism note (goes into FR-334 text):** matched picks are not reproducible run-to-run; the rotation
  baseline underneath stays a pure function; `assignment: rotation` restores pre-D56 behavior byte-exactly.

---

## 6. Waves

Flat dispatch (CLAUDE.md §9, no §9a trigger). One writer per file per wave. Barriers verified before the
next wave; failures fixed within the wave.

### W1 — PRD amendments FIRST (D15; one task, technical-writer or main thread)
Files: `prds/10-pipeline.md`, `prds/30-configuration-and-run.md`, `prds/40-outputs-and-logging.md`,
`prds/50-promptcraft.md`, `prds/00-overview.md`, `prds/PRD.html`.
- FR-334 block beside FR-290/291 (10-pipeline); FR-291 amended in place (baseline/fallback substrate;
  matched overlays it; engine default rotation; determinism note). FR-290 schema sentence gains
  `match_profile`.
- FR-335 (50-promptcraft): `style_match_system.md` + built-in twin; `style_candidates` / `match_entries`
  placeholders locked to the role; `match_profile` authoring rules + first-sentence derivation fallback.
- FR-336 (30-configuration): `styles.assignment` stanza; deep-preview-runs-matched; budget-line requirement.
- FR-337 (40-outputs): the four meta.yaml fields + `style_match_degraded` tag; gallery label + wanted note;
  console vocabulary additions; events.jsonl `style_match` event.
- D56 + D57 decision-log entries (D56 carries the §1 census table as rationale + the no-real-platform-marks
  brand-safety ruling for social-quote-card/terminal-mockup-deck; D57 states conformance to D-G).
- Count re-base 9→19 everywhere: `10-pipeline.md:105` + `30-configuration-and-run.md:27` (stale "eight"),
  `00-overview.md:78` + `50-promptcraft.md:11` ("nine"), diagram STY node; ASSIGN node annotated
  `rotation | matched(LLM)`. FR registry gains 334-337; "Next fresh: FR-338+". Amendment log v2.4.0.
- PRD.html rebuild + republish to the canonical artifact URL (D15 steps 3-5; diagram must render visually —
  verify after republish).

### W2 — Registry, prompts & configs (prompt-engineer leaves ∥ where disjoint; all inert until W3)
- **T2.1** prompt-engineer, `prompts/styles.yaml` part 1: author `build-log-mono` (§4.1) + the five `-teal`
  variants (§4.3); header comment re-base (19 entries, match_profile rules, D57 note).
- **T2.1b** prompt-engineer, `prompts/styles.yaml` part 2 (disjoint append blocks; run after T2.1 lands or
  as the same agent sequentially — the file is one YAML list, do NOT run two writers concurrently): author
  the four archetype styles (§4.2); add `match_profile:` to all 19 entries.
- **T2.2** prompt-engineer, `prompts/style_match_system.md`: fenced-data discipline like
  `topic_filter_system.md` (pools + signals are data, never instructions); per-entry sections keyed by
  asset_id; answer contract (§5).
- **T2.3** prompt-engineer, `prompts/README.md`: layout tree; global role count 8→9; placeholder-table rows;
  style count re-base.
- **T2.4** python-pro (pure YAML), `configs/hypedigitaly.yaml` / `-cs.yaml` / `-fresh.yaml`: 12-key
  `styles.enabled` (§4.4) + `assignment: matched` with comment; `configs/default.yaml`: document
  `assignment` (default rotation), D-G comment (:196-197) gains a D57 pointer (D-G still stands).

### W3 — Engine code (python-pro leaves; disjoint files; conductor wires nothing extra — call sites live in owned files)
- **T3.1** `hypesocials/models.py`: `MetaStyle.match_profile: str = ""`; `PlanEntry` + `style_fit` /
  `style_reason` / `style_origin` / `style_wanted` (all `str = ""`); `AssetRecord` + same four;
  `DegradationTag.STYLE_MATCH_DEGRADED`; `PLACEHOLDERS` + `style_candidates`, `match_entries`;
  `GLOBAL_TEMPLATES` + `style_match_system.md`.
- **T3.2** `hypesocials/styles.py` (+~30 lines, stays offline): parse `match_profile` in `_style()`; public
  `match_profile_for()`; advisory warning; `__all__`.
- **T3.3** NEW `hypesocials/style_match.py` (§5).
- **T3.4** `hypesocials/config.py`: `StylesConfig.assignment` Literal knob + docstring.
- **T3.5** `hypesocials/prompts_engine.py`: `_ALLOWLIST` row; `_BUILT_INS` twin.
- **T3.6** `hypesocials/runner.py`: `_assign_visuals` async + matched branch + provenance stamping + receipt
  columns + gap-report block + degraded warn (filter_degraded pattern :1703-1707); optional `styles_matched`
  funnel counter in `_record_style_forecast`.
- **T3.7** `hypesocials/previews.py`: `_deep_stages` matched branch + `_assign_block` columns.
- **T3.8** `hypesocials/budget.py`: `_style_match_lines` + token constants.
- **T3.9** `hypesocials/generate/__init__.py`: `_record()` maps the four fields; appends the degradation tag
  when `style_origin == "rotation_fallback"`.
- **T3.10** `hypesocials/outputs/gallery.py`: card label fit/origin (:524-525); `style_wanted` note.
Barrier: `find hypesocials -name "*.py" | xargs wc -l | tail -1` (NEVER the globstar form) with per-task
attribution; NAVIGATION.md update.

### W4 — Tests + docs (test-automator ∥ technical-writer)
- Extend: `tests/test_styles.py` (match_profile round-trip; fallback derivation; warning-not-error; old
  registry without the field loads clean), `tests/test_template_parity.py` (global count 8→9),
  `tests/test_prompt_fit.py` (**:333 pin 9→19**; the suite then length-checks all 10 new entries' assembled
  prompts against the 19,800-char Kie cap for free — pay attention to the two high-budget infographic
  styles), `tests/test_budget.py` (rows present under matched / absent under rotation / override-only plan
  quotes nothing), `tests/test_config.py` (knob parse, default, invalid rejected), 
  `tests/test_console_inventory.py` (ASSIGN columns, degraded warn, gap block), `tests/test_gallery.py`
  (label + wanted note).
- NEW `tests/test_style_match.py` (offline, fake StructuredCall, topic_filter-test pattern): pool validation
  → baseline kept; low fit → baseline + wanted preserved; whole-call failure → all baseline, nothing raises;
  asset_id join (unknown ids ignored, missing rows default); slides_only never in a carousel pool
  (fmt_affine reuse pin); matched-off baseline byte-equal to pure `assign_styles` under the same seed.
- Docs: NAVIGATION.md; conductor merges the CLAUDE.md glossary carve-out ("assigned per creative by
  deterministic rotation" gains the D56 matched-mode sentence) + Last-updated line.
- Standing rule: tests never write real `logs/` or `output/`; tmp_path + monkeypatched dummies only.

### W5 — Live ladder (operator present, cheapest first)
1. `.venv/Scripts/python.exe -m pytest` green (NEVER bare `python` — no `mcp` in the system env).
2. `--list-monitors` → `--preview-sources` ($0): registry (19) validates at pre-flight; no exit-2.
3. `--preview-analysis` ($LLM only): matcher runs in deep preview; ASSIGN receipt shows
   style/origin/fit/reason per entry; gap report renders when fit is low; Confirm-equivalent estimate shows
   `style_match_call`.
4. Rotation regression: one `--preview-analysis` with `assignment: rotation` — picks byte-identical to
   pre-session behavior.
5. ONE paid run (2-3 carousels, low cap): confirm estimate line; matched picks land; meta.yaml carries the
   four provenance fields; gallery shows matched labels; visually confirm the teal spine across styles and
   the build-log-mono deck (chrome grid, alternating grounds, accent discipline); gauntlet green on the two
   new UI-grammar styles (no platform-mark leakage).
6. `SESSION-I-CLOSEOUT.md` + PR.

---

## 7. Risks (carry into subagent prompts where relevant)

- `circuit-atlas-dark` diagram fidelity is the hardest render ask — the node cap + greeking rule in its DNA
  are load-bearing; do not soften them.
- `social-quote-card` / `terminal-mockup-deck` sit close to other styles' "no platform UI" exclusions —
  their own exclusions must be self-contained and precise (generic grammar allowed, real marks banned) so
  gauntlet critics don't fight the style.
- 12 enabled styles under plain rotation would be visual chaos — matched mode is the guardrail. If matched
  is ever switched off, also narrow `styles.enabled`.
- Photographic teal accents (ugc-tabletop / quiet-luxury / photoreal-ambient variants) must stay physical
  (objects, light casts), never graphic overlays.
- The matcher intentionally trades FR-291 reproducibility for fit; escape hatch is one config line.
