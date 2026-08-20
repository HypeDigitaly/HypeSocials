# Carousel Fidelity + Gauntlet Loop — Masterplan (v2.2.0)

**Date:** 2026-08-14 · **Session:** H (next block in `plans/EXECUTION-ORDER.md`) · **Revision:** 2 (post 3-reviewer pass: architect, code-feasibility, prompt-design — ~60 findings folded in)
**Inputs:** Carousel Audit 08-14 (artifact `9065e5d1`, runs `…_59el` + `…_m39f`, 2/12 decks publishable) and The Gauntlet Loop technique (artifact `9db0bcf1`).
**Siblings:** `01-PRD-AMENDMENTS.md` (D15 amendment text, anchor-quoted), `02-GAUNTLET-SPEC.md` (frozen API + critic design).
**Baseline (measured):** 1219 tests collected · 25,899 lines / 41 files under `hypesocials/` (CLAUDE.md history line is stale — T3.2 re-bases it).

## Operator decisions (locked 2026-08-14)

| # | Decision | Choice |
|---|---|---|
| 1 | Loop placement | **In-pipeline**, automatic post-render gate, replaces FR-105 — every knob configurable (per-critic models & toggles, rounds, budgets) |
| 2 | Rounds / spend | **Max 3 rounds** per deck, failing slides only, hard per-deck re-render budget shown at Confirm (display, never cap-gating — FR-106a) |
| 3 | Critic model | **Sonnet** (new `models.critic` role; per-critic override available) |
| 4 | Non-converging deck | **BLOCKED** — never published, spend stops, `GAUNTLET_REPORT.yaml` written (craft-only failures never block — see spec §2 tiers) |
| 5 | Style vs verbatim | **Verbatim always wins** — `list_mode` is a *reflow trigger*, never a ceiling; no text ever dropped for style reasons |
| 6 | Run deadline | **60 min** (default AND the four shipped `configs/*.yaml`, which pin it explicitly) |
| 7 | Plan shape | Two phases: Phase 1 = audit fixes · Phase 2 = gauntlet |

## Root causes (audit → verified code) → fix home

| # | Audit defect | Verified root cause | Fix |
|---|---|---|---|
| 1 | Caption leaks niche config | `copywrite.py:2346 _fallback_caption` = topic name + niche_descriptor; 4 reachable paths (`:1746, :2155, :2201, :2318`) | T1.1 |
| 2 | Strip kills handles, not identities | consumer exists (`copywrite.py:1151` + `:1233` read `author_name` via getattr) but **no producer** — `SourcePost` field absent, Virlo adapter never maps it; `_scrubbed:1331` skips `_strip_cta`; CTA patterns (`:249-262`) miss dangling-promo sentences | T1.0+T1.1+T1.2 |
| 3 | Invented text becomes pixels | no closed-set post-render comparison exists | Phase 2 `brief` critic |
| 4 | List/table pair corruption | no pair-integrity check exists | Phase 2 `brief` critic (FR-329) |
| 5 | Vision gate doesn't gate | `vision_check.py:414` RETRIED_FAILED never blocks; **missing FORBIDDEN mark list** (REQUIRED semantics are deliberate D-A/v2.1.2 — keep them, add the forbidden side, FR-330) | Phase 2 |
| 6 | FR-315 crops broken | `carousel.py:394-435` crops+uploads ALL `intel.mark_boxes` (≤24), sanction gate only at attach; dedupe key mismatch (`logo_crops.py:112` raw vs `carousel.py:429` collapsed); no crop-content validation; no tool/apparel classification (GAP/Nike pass every existing filter) | T1.2+T1.3+T1.6 |
| 7 | Style budgets / FR-304 conflict | mapped panels face only `PANEL_SANITY_CHARS=1500` (`copywrite.py:330-342` — deliberate, keep); no style list treatment exists; `_budget_line:1251-1263` deliberately quotes no per-slide ceiling (keep — B6 regression) | T1.5+T1.6 |
| 8 | Re-render / wave-2 drift | re-renders carry anchor only (`carousel.py:694`); FR-95 fallback (`:370`) re-bursts all N reference-free; non-anchor result URLs discarded | T1.3 + Phase 2 |
| 9 | Provenance, bookkeeping, spend gates | `generate/__init__.py:790/770` read topic-P1 (`virlo.py:1266/1245`); **carousel+reel failure paths already write full fields** (`carousel.py:911-916`, `reel.py:587`) — the real gaps are `generate/__init__.py:936 _fail` (partial) + `:914 _abandon` (event_id only) + early skips `:343/:346/:352`; no runway check in `_submit:592`; no viability short-circuit (`_burst:437`) | T1.3 |
| 10 | Screen misses language/audience | `topic_filter.py:106 Verdict` lacks fields; strict schema `additionalProperties:false` (`:387`) — stale `prompts_dir` overrides will degrade fail-open (accepted; preflight warns) | T1.4+T1.6 |
| — | OCR carry-through | zero normalization by design; repair must respect the FR-100/101 byte-substring verifier — sanctioned repair boundary with raw bytes kept in provenance, and **truncation-suspect panels are flagged, never blanked** | T1.0+T1.1+T1.2 |
| — | Rotation repeats across runs | `styles.py:527` pick is pure function of `entry.order` | T1.5 |

## Phase structure

**Phase 1 (Waves 0–1d):** deterministic fixes — correctness before pixels + spend hygiene. **Phase 2 (Waves 2a–2c):** the gauntlet (3 fresh-context critics on rendered frames, canned-remedy fix loop, ≤3 rounds, three-tier terminal policy) replacing the FR-105 machinery outright (legacy path deleted — `run.gauntlet.enabled: false` means *no post-render gate*; cheap mode = brief-only, 1 round). **Wave 2c is a paid live acceptance run** (spend pre-approved). **Wave 3:** tests, docs, read-only review.

**Test policy (binding):** every code task fixes the existing tests its own diff breaks (suite must be green at each barrier); T3.1 authors *new* regression coverage only. Known mass-breakage: `test_config.py` (deadline 60), `test_styles.py` (seeded rotation), `test_logo_crops.py:258-273` (collapsed dedupe — intentional amendment), `test_template_parity.py` (new roles + template bytes), `test_carousel.py`/`test_generate_waves.py`/`test_reel.py` (gauntlet rewire, wave 2b).

**NAVIGATION policy (stated deviation):** each wave report carries its NAVIGATION.md delta; T3.2 is the single writer applying them. Deviation from per-barrier updates is deliberate (avoids shared-file churn across leaf agents); the deltas exist at every barrier.

---

## Waves & tasks

Flat-wave dispatch, conductor = main thread, depth ≤ 2. No wave exceeds 4 same-domain tasks; every cross-task contract is frozen in the spec (list_mode YAML shape, placeholder names, gauntlet API, mark-kind schema) — §9a triggers avoided by construction; prompt/template byte-twin work is sequenced into its own waves (1d, 2b) to keep `prompts_engine.py` single-writer per wave.

### Wave 0 — PRD amendments (D15) — 1 task

**T0.1 · technical-writer · `prds/*.md` + `prds/PRD.html`** — Apply `01-PRD-AMENDMENTS.md` (anchor-quoted edits, work bottom-up per file), then regenerate `prds/PRD.html` (the visual PRD companion) so it matches the amended PRDs: version v2.2.0, gauntlet stage in the flow diagram, BLOCKED branch, new FR-322–330 rows, D49–D53 in the decision log, plain-English TL;DR rewritten. Keep the diagram markup that renders natively (never raw mermaid text) and keep the page structure the artifact publish expects. Includes the full contradiction sweep: FR-20, `:503` exclusions, NFR-1/4/25, D3, both TL;DR paragraphs, FR-18 "sole references", FR-27, FR-99/FR-307 caption forms, FR-100/101 repair carve-out, FR-108 stale "default 25", FR-202 exit table + partial-ship clauses, §10 table, FR-107; new FR-322–330; decisions D49–D53.
**Barrier:** main-thread diff review + grep proof: `no re-render loop`, `no quality gates`, `one attempt`, `sole image references`, `ships either way`, `renders once` — every hit reconciled.

### Wave 1a — shared schema (sequential) — 1 task

**T1.0 · python-pro · `hypesocials/models.py`, `hypesocials/config.py`, `configs/*.yaml`, `hypesocials/ocr_repair.py` (new), `hypesocials/sources/mark_names.py` (new), `hypesocials/budget.py` (micro), `hypesocials/generate/carousel.py` (import-swap only)**
- `models.py`: `SourcePost.author_name: str = ""`; `AssetStatus.BLOCKED` **and** `PlanEntryStatus.BLOCKED`; `AssetRecord.gauntlet: dict | None` (plain dict — models never imports gauntlet); `RenderFailCause.NO_RUNWAY`; `GLOBAL_TEMPLATES` + `PLACEHOLDERS` name rows for `critic_brief.md` / `critic_system.md` / `critic_craft.md` / `gauntlet_fix.md` (names only, per spec §3 placeholder sets); `MetaStyle.list_mode` (shape per spec §4b).
- `config.py`: `run.run_deadline_min` default 60; `run.gauntlet.*` block exactly per spec §4; `models.critic` role + `max_tokens`/floor rows; `PlatformConfig.min_carousel_panels` (linkedin default 3, others 2 = today's `MIN_DECK_SLIDES`); `_BOUNDS` rows; gauntlet advisory folded into `carousel_throughput_warning` (`config.py:1040-1069`).
- `configs/`: deadline 60 in all four pinned configs; gauntlet block in `default.yaml` with comments.
- `ocr_repair.py`: `repair_confusables(text) -> (text, list[Correction])` — word-boundary, uppercase-token-scoped confusables (`Al`→`AI` class, digit/letter); `truncation_suspect(text) -> bool`. Doctrine per amendment: applied only at the sanctioned admission boundary, raw bytes always kept in provenance.
- `mark_names.py`: extract `_mark_name` (`carousel.py:198-232`) + `_collapse` (`:241-247`) into `hypesocials/sources/mark_names.py`; carousel re-imports (no cycle: sources ← generate is the existing direction).
- `budget.py:353-359`: anchor contingency 1 → **2** units (FR-95 re-anchor shape is N+2 worst case).
- Fix all tests this breaks (config defaults, parity SHIPPED_COUNT if touched).
**Barrier:** suite green · wc-l attribution.

### Wave 1b — code fixes (parallel, 4 tasks, disjoint) — flat

**T1.1 · python-pro · `hypesocials/copywrite.py`**
- Caption fallback: **niche_descriptor never reaches caption text on any path.** Per-site scoping (reviewer-verified): `_written:1746` + `_mapped_fallback:2201` → bound post's best post-strip hook + neutral attribution; `_refused:2155` → topic name only (FR-307 forbids quoting the refused post); `_fallback_copy:2318` → top-post caption else topic name + slug hashtags. Nothing usable on the offer paths → fail pre-spend `NO_SAFE_CAPTION`.
- `_scrubbed` gains the CTA/promo scrub with **pool/product consistency** — the verifier pool (`:2260`) and the shipped caption (`:2312`) must see identical bytes, or `_verify:2450` false-flags `copy_not_verbatim`.
- Dangling-promo sentence patterns added to `_cta_pattern` set (comment-bait w/o keyword, community/program pitch, "you won't find this…", first-person achievement claims) — caption-only, each logged.
- `author_name` consumed at **both** `:1151` and `:1233`.
- OCR: `repair_confusables` at caption/hook admission and on the merged panel payload — the SAME repaired bytes feed the verifier pool, the prompt, and `panel_map.source_text`; raw bytes kept as `source_text_original` (field exists at `:1887`); every correction logged `ocr_repaired`. `truncation_suspect` panels: set `panel_map.truncation_suspect: true` — **never blanked** (they feed the brief critic as contract data).

**T1.2 · python-pro · `hypesocials/sources/logo_crops.py`, `hypesocials/sources/slide_intel.py`, `hypesocials/sources/virlo.py`**
- `crop_marks(source_dir, marks, allow)`: required `allow` = collapsed sanctioned names (via `mark_names`); unsanctioned boxes never cropped/written/uploaded. Dedupe by collapsed name; **returned dict keys stay RAW names** (documented contract). `_crop_valid`: min-edge (exists) + pixel-variance floor (near-uniform ⇒ refuse). Content-rect remap is a **fallback only** — first crop with today's full-frame fractions; remap against a detected letterbox content rect only when `_crop_valid` fails; before implementing, measure the actual m39f boxes/patches (`output/20260814_093619_m39f/source/*/marks/`) and record findings in the task report. (Pillow scope extension = D53.)
- `slide_intel.py`: `_SLIDE` mark row gains `kind: tool|apparel|chrome|other` — required of the model, parser-optional with default `"tool"` (today's behavior until the wave-1d prompt lands); `_mark_boxes` keeps only `kind=="tool"` AND not author-identity/chrome collapse-matched. `vision_text` through `ocr_repair` (repair + truncation flag, logged); Virlo bytes still win §0.11.
- `virlo.py`: map Virlo's display-name field into `SourcePost.author_name` — or, if the API exposes none, record that in the task report AND add a regression test pinning the `""` fallback. **"Populated or documented-absent" is a barrier item.**

**T1.3 · python-pro · `hypesocials/generate/__init__.py`, `hypesocials/generate/carousel.py`, `hypesocials/generate/reel.py`**
- **Runway gate** in the single metered door (`generate/__init__.py:592`, beside `env.halted`; `Deadline.remaining_s`, `Env.deadline` is Optional): refuse when `remaining_s < timeout_for_kind + GRACE_S` → unbilled FAIL with `RenderFailCause.NO_RUNWAY`. Applies to `discretionary` + `projected` only — **never `precommitted`** (FR-106b: bookkeeping must never split a deck). `NO_RUNWAY` excluded by name in BOTH resubmit predicates (`generate/__init__.py:378`, `carousel.py:550-553`) so FR-317's one-shot is never burned on it; fix the `carousel.py:588` decline-label to distinguish runway from cap.
- **Viability short-circuit:** a slide *permanently lost to a render defect* (terminal fail after FR-317; explicitly excluding halted/no_runway/credits/disk — those keep today's incomplete-ship behavior) ⇒ deck unsalvageable ⇒ submit **no further** work for the deck (never cancel already-submitted paid jobs — FR-29/FR-203), then `skip()` with full fields.
- **FR-95 re-anchor:** anchor dead → ONE new-anchor attempt → if it lands, chain 2–N normally; only if it also dies, reference-free burst (logged `carousel_anchor_fallback_unchained`). Contingency already re-priced in T1.0.
- **Neighbor refs:** retain each delivered slide's Kie result URL on the deck; re-render refs = anchor URL + nearest delivered neighbor URL (fallback `refs.upload_local` if stale) + patches.
- **Crops:** `_crop_patches` allowlist = `union(_sanctioned_marks(n) for n in 1..len(self.texts))` collapsed; boxes on non-rendered source panels never cropped.
- **Bookkeeping:** `_fail` (`:936`) adopts the full-field pattern (vision result, model_ids, native size); `_abandon` (`:914`) records cost/job/timestamps; early-skip paths (`:343/:346/:352`) record what exists. (Carousel `skip()` + reel already correct — do not refactor `package()`.)
- **Provenance:** `_record` reads `virlo_url`/`source_hook` from the bound post (`entry.source_post_id`); topic-P1 only as labeled fallback.

**T1.4 · python-pro · `hypesocials/topic_filter.py`, `hypesocials/plan.py`, `hypesocials/runner.py`**
- `Verdict` + `_answer_schema` gain `language: str`, `audience_fit: bool`; `_apply`: non-target language or `audience_fit=false` ⇒ `skip` (LLM layer stays fail-open; a stale `prompts_dir` override degrades to `filter_degraded` — accepted and warned, see T1.5 preflight). `build_context` (`topic_filter.py:375`) passes the frozen placeholder `{{audience_profile}}` (value = `NicheConfig.as_text()` — allowed here and only here, mirroring the competitor_list precedent).
- ASSIGN floor: binder becomes platform-aware (`fresh_source_post` signature + the `plan.py:534` closure + `_carousel_supply:521` + FR-307 console figure move together); floor = `platforms.<name>.min_carousel_panels`, reconciled with `MIN_DECK_SLIDES` (`plan.py:59`) as the global minimum.
- `runner.py`: verdict console cell shows language/audience; trend-history guard (`:1024`) and `set_latest` gate (`:1054`) treat `PlanEntryStatus.BLOCKED` as non-success (lands now, exercised in Phase 2).

**Barrier (1b):** suite green · wc-l attribution · virlo author_name populated-or-documented.

### Wave 1c — styles & budget plumbing (sequential) — 1 task

**T1.5 · python-pro · `hypesocials/styles.py`, `hypesocials/prompts_engine.py`, `hypesocials/preflight.py`**
- `styles.py`: parse+validate `list_mode` per spec §4b (absent = legal; malformed = FR-295 exit-2); seeded rotation — `pool[(order + step + run_seed) % n]`, `run_seed` = stable hash of run id, `styles.rotation: seeded|fixed` default seeded.
- `prompts_engine.py`: `list_mode.layout` appended to the assembled `{{layout_zones}}` value, gated on the slide's panel tripping `reflow_over_chars`/`max_rows` (the `_style_zones` gated-append pattern; no new placeholder, no template edits, `layout_zones` is in `_STYLE_TRIO` = uncuttable). `_budget_line` untouched for mapped panels (B6 stands). `topic_filter_system.md` allowlist row gains `audience_profile`.
- `preflight.py`: validate `list_mode`; warn when a `prompts_dir` override `topic_filter_system.md` lacks the new instructions.
- **`list_mode` is never consulted by `copywrite._panel_verdict`** — D50: no drop path gains a style input.

**T1.5b · ui-designer (read-only, parallel with T1.5) · reads `Inspiration/Tiktok and IG/` + `prompts/styles.yaml`** — Design-system audit: grade each of the 8 styles against the full design-system checklist (typography pairing + hierarchy, complete palette with roles, graphic language/motifs, layout & spacing rules, composition/pacing, list & data treatments) and against its Inspiration source material. Output: per-style gap report (missing/underspecified fields, contradictions, budget realism) → input for T1.6. No file edits.
**Barrier:** suite green + T1.5b gap report delivered.

### Wave 1d — prompt artifacts (sequential; sole `prompts_engine.py` writer this wave) — 1 task

**T1.6 · prompt-engineer · `prompts/styles.yaml`, `prompts/topic_filter_system.md`, `prompts/slide_intel_question.md`, `prompts/gpt-image-2/carousel_slide.md`, `prompts/gpt-image-2/carousel_anchor_instruction.md`, `hypesocials/prompts_engine.py` (`_BUILT_INS` byte-twins ONLY)**
- `styles.yaml`: apply T1.5b's design-system gap report (fill every underspecified style field so each style is a complete design system: typography, palette roles, graphic language, layout rules); `list_mode` blocks per spec §4b for list-capable styles; header authoring-rules block documents the field (reflow-not-ceiling, explicitly); `platform-showcase-card` greeking rule amended (greeked bars = background mock-up filler only; planned verbatim text always renders literally); `anime-noir-statement` sanctioned list treatment; budget-realism sweep of all 8 styles. (There is no cover template — cover behavior lives in `per_format_guidance.carousel_cover`.)
- `topic_filter_system.md`: language + audience-fit instructions using `{{audience_profile}}`.
- `slide_intel_question.md`: teach the `kind` classification (tool logo vs apparel/fashion vs platform chrome vs other) for mark rows.
- Template micro-fixes: constant scaffold text (counter labels etc.) can never read as renderable content.
- Sync every edited template's `_BUILT_INS` twin byte-exactly (parity test pins this).
**Barrier:** suite green incl. `test_template_parity.py`.

### Wave 2a — gauntlet build (parallel, 3 tasks) — flat

**T2.1 · python-pro · `hypesocials/gauntlet.py` (new), `hypesocials/vision_check.py`, `hypesocials/prompts_engine.py` (allowlist rows only)**
- Implement spec §§1–3 exactly (frozen types incl. `RerenderResult`, `FrameContract`, per-critic enums, unavailable-critic semantics, three-tier terminal, round-2 scoping, union-of-standing-defects, canned-remedy `fix_instruction` with `_neutralize` + blocklist + fence-close + 600-char cap).
- `vision_check.py`: promote `_load` → public `load_images()` (+`__all__`); `expected_text`/`retry_plan` stay public helpers; `check()` left intact this wave (deleted with its callers in 2b).
- `_ALLOWLIST` rows for the three critic roles + `gauntlet_fix.md` per spec §3 placeholder sets.

**T2.2 · prompt-engineer · `prompts/critic_brief.md`, `prompts/critic_system.md`, `prompts/critic_craft.md`, `prompts/gauntlet_fix.md`**
- Per spec §3: per-critic enum subsets in-schema; presence-vs-execution discipline lines; brief carve-outs (mark lettering, sanctioned illegibility, style glyphs, brief product-photo text); asymmetric strictness (leakage fail-when-unsure / craft publish-bar + confidence:low); wordless mandate text; enumerated `L1:`-row referent format; 2–3 worked verdict examples per critic; `gauntlet_fix.md` canned remedies keyed by (code, zone) + the conflict-precedence block + fence-closing final line.
- `_BUILT_INS` twins for these four files are added by T2.4 (sequential single-writer).

**T2.3 · python-pro · `hypesocials/budget.py`**
- `gauntlet_allowance` lines with `allowance=True` (**display, never gating** — acceptance test: `estimate().expected_usd` unchanged by enabling gauntlet; only `worst_case_usd` moves); critic LLM projection at realistic completion tokens (~700/call, spec §5 arithmetic); `_ROLE_PRICE_KEY["critic"] = "sonnet"`; preflight-consumable check that `models.critic` resolves to a priced block.

**Barrier:** suite green (gauntlet units against stubbed seams).

### Wave 2b — wire-in (sequential) — 1 task

**T2.4 · python-pro · `hypesocials/generate/carousel.py`, `hypesocials/generate/__init__.py`, `hypesocials/generate/reel.py`, `hypesocials/runner.py`, `hypesocials/preflight.py`, `hypesocials/cli.py`, `hypesocials/outputs/packager.py`, `hypesocials/outputs/gallery.py`, `hypesocials/prompts_engine.py` (built-in twins for T2.2's four files)**
- Carousel: `run_deck()` replaces `_check/_rerender/_verdicts/_log_rechecks` (deleted); anchor pre-gate = `run_single(anchor, …, critics=(brief,craft), rounds=1)`; `RerenderFn` closure owns refs/reserve/runway/FR-317-exclusion and returns `RerenderResult`. Image path: `_vision` → `run_single`. Reel: `_check_seed` → `run_single` (seed via Kie URL — `FrameUnderTest.source: Path|str`).
- Legacy deletion: `vision_check.check()` + `_SCHEMA`/`_carrier`/`_verdicts`; `run.vision_check` key removed with one-line migration warning (alias → `gauntlet.enabled`); `prompts/vision_check_question.md` retired.
- `runner.py`: `_role_settings` (`:573`) becomes a dict lookup incl. `critic`; llm role registration (`:567`); GAUNTLET console block replaces CHECK (`:1109-1115`), per-round FR-296-style lines; summary table + exit policy (any BLOCKED ⇒ exit 1); **new run-summary "LLM usage" table** — per role (screen/copy/analysis/critic): calls, input tokens, output tokens, USD, plus render spend row — sourced from the existing events/budget accounting (token monitoring, operator-visible per run).
- `packager.py`: `block()` terminal writer (keeps artifacts — FR-74; writes `BLOCKED.txt`); `gallery.py`: BLOCKED badge (not the failed-card path). `cli.py`: `--gauntlet/--no-gauntlet` mirror of the removed `--vision-check`.
- `preflight.py`: gauntlet config validation (critic prompts exist, ≥1 critic enabled, priced role, bounds).
**Barrier:** suite green · offline `--yes` dry-run with render+LLM seams stubbed ($0): loop, BLOCKED path, report files, exit codes.

### Wave 2c — LIVE ACCEPTANCE (conductor-run, paid; spend pre-approved) — no subagent

Run 2–3 carousels on the audited monitors. Measure: (a) each of the 10 audit defects absent/caught, (b) rounds-to-converge distribution, (c) actual critic $/deck + re-render $/deck vs spec §5 projections, (d) wall-clock vs 60-min deadline. **Rollback criterion:** >50% decks BLOCK on defect classes Phase 1 should have removed ⇒ set `gauntlet.enabled: false` in shipped configs, file findings, stop — do not tune live.
**Barrier:** operator reviews the run output + this measurement table before Wave 3.

### Wave 3 — tests, docs, review (parallel, 3 tasks) — flat

**T3.1 · test-automator · `tests/`** — NEW regression coverage: caption never contains niche text (all 4 paths); display-name + dangling-promo strips; crop allow/variance/letterbox-fallback + raw-key contract (amend `test_logo_crops.py:258-273` intentionally); NO_RUNWAY excluded from resubmits; viability short-circuit incl. the halted-exclusion; bound-post provenance; `_fail`/`_abandon` fields; screen language/audience + stale-override degrade; seeded rotation; list_mode parse/validate/gated-append; gauntlet: round loop, three tiers, unavailable-critic, budget/deadline stops, BLOCKED + trend-history exclusion, report schema, allowance-not-gating; template parity for the four new prompts.
**T3.2 · technical-writer · `NAVIGATION.md`, `README.md`, `CLAUDE.md` + `AGENTS.md`, `plans/EXECUTION-ORDER.md`, `plans/SESSION-H-CLOSEOUT.md`, `prds/PRD.html` (final sync)** — final `PRD.html` pass so it reflects the AS-BUILT system (config keys, model roles incl. `critic`, cost envelope, BLOCKED semantics), then the conductor republishes it to the canonical artifact URL (see Session 6 instructions) and verifies the diagram draws visually; apply accumulated NAVIGATION deltas; SESSION H block + closeout; operator docs (config keys, BLOCKED semantics, reading GAUNTLET_REPORT.yaml, rollback knob); CLAUDE.md: glossary (Gauntlet, list_mode, BLOCKED), media-libraries sentence (D53 Pillow scope), deadline 60, cost/latency envelope (~3 min → gauntleted expected-case, worst case honest), re-base the line-count history (25,899 baseline).
**T3.3 · code-reviewer (read-only) · whole diff** — implementation vs plan + amended PRDs; findings routed by conductor to owning agents.
**Barrier (final):** full suite green · lint · wc-l final attribution · session report per CLAUDE.md.

---

## Aggregating files — single writer per wave

| File | Writers (wave order) |
|---|---|
| `models.py`, `config.py`, `configs/*.yaml`, `mark_names.py`, `ocr_repair.py` | T1.0 only |
| `budget.py` | T1.0 (micro, 1a) → T2.3 (2a) |
| `generate/carousel.py` | T1.0 (import swap, 1a) → T1.3 (1b) → T2.4 (2b) |
| `generate/__init__.py`, `generate/reel.py` | T1.3 (1b) → T2.4 (2b) |
| `runner.py` | T1.4 (1b) → T2.4 (2b) |
| `prompts_engine.py` | T1.5 (1c) → T1.6 (built-ins only, 1d) → T2.1 (allowlist, 2a) → T2.4 (built-ins, 2b) |
| `preflight.py` | T1.5 (1c) → T2.4 (2b) |
| `styles.py`, `topic_filter.py`, `plan.py`, `copywrite.py`, `sources/*` | one task each (see waves) |
| `outputs/packager.py`, `outputs/gallery.py`, `cli.py`, `vision_check.py`, `gauntlet.py` | wave-2 owners as listed |
| `prompts/*` | T1.6 (1d) → T2.2 (2a, new files only) |
| `prds/*` | T0.1 only · `NAVIGATION.md`/plans | T3.2 only · `tests/` | blast-radius fixes by each code task, new coverage T3.1 |

## Wire-in — every new symbol

| Symbol | Producer | Consumers |
|---|---|---|
| `ocr_repair.repair_confusables` / `truncation_suspect` | T1.0 | `copywrite.py` (T1.1), `slide_intel.py` (T1.2) |
| `mark_names.mark_name` / `collapse` | T1.0 (extracted) | `carousel.py` (T1.0 import swap), `logo_crops.py` + `slide_intel.py` (T1.2) |
| `SourcePost.author_name` | `virlo.py` adapter (T1.2) | `copywrite.py:1151,:1233` (T1.1) |
| `RenderFailCause.NO_RUNWAY` | T1.0 | `generate/__init__.py:592` gate + both resubmit predicates (T1.3) |
| `PlatformConfig.min_carousel_panels` | T1.0 | `plan.py` binder (T1.4) |
| `MetaStyle.list_mode` | T1.0 + `styles.py` parse (T1.5) + `styles.yaml` (T1.6) | `prompts_engine` layout_zones gated append (T1.5) |
| `{{audience_profile}}` placeholder | allowlist row (T1.5), template (T1.6) | `topic_filter.build_context` (T1.4) |
| `slide_intel` mark `kind` | schema (T1.2), prompt (T1.6) | `_mark_boxes` filter (T1.2) |
| `AssetStatus.BLOCKED` + `PlanEntryStatus.BLOCKED` | T1.0 | `runner.py` history/`set_latest` guards (T1.4); `packager.block()` + gallery badge + exit policy (T2.4) |
| `gauntlet.run_deck` / `run_single` / `RerenderResult` / `FrameContract` | T2.1 | carousel/image/reel call sites (T2.4) |
| `vision_check.load_images` | T2.1 (promotion) | `gauntlet.py` (T2.1) |
| critic prompts + `gauntlet_fix.md` | T2.2 (files), T1.0 (name rows), T2.1 (allowlist), T2.4 (built-in twins) | `gauntlet.py` |
| `budget.gauntlet_allowance` + `_ROLE_PRICE_KEY["critic"]` | T2.3 | estimator/Confirm lines + preflight (T2.4) |
| `models.critic` role runtime | T1.0 (config) | `runner._role_settings` dict rewrite (T2.4); `gauntlet` resolves `models.critic or models.analysis` |

## Non-negotiables honored

- **PRD-first** (Wave 0 before code; contradiction sweep is a barrier).
- **Money after Confirm only**; gauntlet lines are `allowance=True` — shown, never cap-gating (FR-106a); runway gate never touches `precommitted` (FR-106b); paid jobs never cancelled (FR-29/FR-203); FR-317 one-shot never consumed by refusals.
- **No line ceiling** — measured with attribution at every barrier; baseline re-based to 25,899.
- **Async-only / ProactorEventLoop / junctions / D30 secrets** — untouched; critic calls ride `llm.py`; fix-suffix path is sanitized and carries no critic free text.
- **D46/D48 upload boundary** — narrowed, not widened (allow-gated crops; D53 covers the two new Pillow reads).
