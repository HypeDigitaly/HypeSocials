# SESSION 5.5 — CLOSEOUT (gauntlet fixes F1–F5 + live canary)

**Date:** 2026-08-19 · **Plan:** `plans/carousel-gauntlet/03-SESSION-5.5-FIX-PLAN.md` · **Canary run:** `output/20260819_170148_2z4y` ($0.79 of $10 cap)
**Suite:** baseline 1305 → **1362 passed, 0 failed** (green at every wave barrier). **Configs: gauntlet stays OFF in all four shipped configs** (canary deck blocked — see verdict).

---

## Per-fix status

| # | Fix | Status | Live canary evidence |
|---|---|---|---|
| F1 | Prompt budget repair + `{{list_treatment}}` wire | ✅ SHIPPED | **0 hard-truncation events** (Session 5: 17/21 submissions). 2/13 submissions trio-tail-trimmed a total of **36 chars** each (`render_prompt −16, style_dna −20`, floors respected, `hard_truncated: false`). List guidance reached the renderer (20 events; deck rendered true list rows). Slide template 12,310→10,880 B, anchor block 4,203→**1,500** B, all 8 assembled `style_dna` ≤1,800 (was 2,450–3,997), `_spell` echoes accented words only, F1-E safety-first constraint order, body budget identical on first renders and re-renders (19,800 − `fix_reserve` 1,405 = 18,395; plan's 1,402 estimate corrected — joins undercounted by 3). |
| F2 | Counter/chrome strip at admission | ✅ SHIPPED | `panel_counter_stripped` fired once: `// 01`–`// 04` dropped from slides 2–5 at admission, originals kept in `source_text_original`, `chrome_counter_stripped: true` on 4 panel rows, **zero contract pollution** — the brief critic's counter expectations were correctly OUR `NN / 05`, never the source's `/ 06` chrome. No `missing_text` false positive. |
| F3 | Anchor pre-gate one re-render (FR-324) | ✅ SHIPPED | `rounds_max=2, rounds_max_image=2` at the pre-gate. Canary anchor passed round 0 clean, so the re-render path wasn't exercised live; verified offline (regression: a failing anchor buys exactly one wave-1 re-render before slides 2–N submit; a second failure is final). |
| F4 | Deck budget reserve-then-submit | ✅ SHIPPED | 8 gauntlet re-renders billed **$0.24 ≤ $0.30 cap** — no overshoot (Session 5: $0.33 raced past the cap). `_Deck.gauntlet_lock` + `_claim`/`_settle`; offline regression pins 8×$0.03 vs $0.20 → exactly 6 ship. |
| F5 | Critic bounded reasoning + honest estimator | ✅ SHIPPED | Critics sent `reasoning: {effort: low}` (`models.critic_reasoning_effort`, default in code, configs byte-unchanged). **$0.031/call actual vs $0.105 estimated** (honest-high ✓) vs $0.087 Session 5. Completion **≈434 tok/call vs ≈5,028** in Session 5 (−91%). Input ≈13.5k/call vs 18,300 constant (honest-high ✓). Estimator re-based `budget.py`: 18300/5000; the 5,000 completion constant is now measured to be conservative post-low-effort — a Session 6 candidate for re-base to ~1,000. |

## Canary measurement table (Session 5's four metrics)

| Metric | Session 5 (3 decks) | Session 5.5 canary (1 deck) |
|---|---|---|
| (a) Fixed defect classes | F1/F2 classes caused 2/3 blocks | **Both ABSENT.** 0 hard truncations; 0 chrome false positives. The pipeline defects F1–F5 did not reproduce. |
| (b) Rounds-to-converge | No deck converged | **Did not converge — BLOCKED 3/3** on a *different, genuine* class: FR-313 counter fidelity (see F7 below). 8 re-renders across rounds 1–2. |
| (c) Cost | Critic $0.087/call; Li deck $1.24 critics; re-render cap overshot $0.33 | Critic **$0.031/call** ($0.344/deck, 11 calls); re-renders $0.24 (cap honored); run total **$0.79** ($0.40 LLM + $0.39 render) — above the ~$0.35–0.70 estimate only because the deck went the full 3 rounds. |
| (d) Wall-clock | 22m43s (3 decks) | **13m58s** (838.6 s, 1 deck, 13 render jobs) — well under the 60-min deadline. |

**Verdict: canary NOT passed** (0 delivered), therefore per plan step 3 the four shipped configs keep `run.gauntlet.enabled: false` with their rollback comments intact. But the block is **not** a recurrence of F1–F5: verified against the actual pixels, the final deck genuinely has no page counter on slide 3 and an inconsistent counter treatment on slide 2 — the critics were right, at low reasoning effort, in every spot-checked verdict. The gauntlet is doing exactly its job on a render-model weakness.

## New finding F7 (for Session 6 / operator decision)

**FR-313 counter fidelity under re-render churn:** gpt-image-2 oscillates the deck's own counter across re-renders — chip vs plain-footer vs missing entirely, and round 1 rendered "6 REPOS" *inside* the counter chip. Round-2 re-renders fixed counters but dropped the sanctioned Claude starburst marks; round 3's re-renders restored marks but lost slide 3's counter. Each individual verdict was correct; the deck chased its tail across the round budget. Options to weigh: a counter-targeted fix-sheet line, counter zone in the anchor lock, tolerating `counter_placement` as degrade-not-block, or accepting that some decks lose the render lottery. **Not tuned live** — per plan discipline, nothing was changed after the canary.

## Deviations from the plan (disclosed)

1. **F1-D numeric bars not met at the plan's extreme recipe** (found by Wave 4, encoded honestly): at the full worst-case assembly (anchor + neighbour + 2 patches + 21 marks + counter + list panel), trio cut at the 700-char tier is 693–1,524 (plan wanted 0), and the 1,500-char extreme still hard-truncates 437–988 on 7/8 styles — the plan's Q3 arithmetic under-counted the reference stack. What the shipped `tests/test_prompt_fit.py` pins instead: `hard_truncated is False` at live shapes, **all 11 CONSTRAINTS bullets always survive**, panels byte-verbatim, floors respected, and any extreme-tier truncation eats exactly the droppable tail in F1-E order (prefix invariant). The live canary confirms the live-shaped claim: 36-char trims only. Pathological all-accented 1,500-char panels remain out of reach and are pinned as a named measurement.
2. **FIX_RESERVE is 1,405, not the plan's 1,402** (join undercount); reservation is unconditional (held even with the gauntlet off) to keep body budgets config-independent.
3. Wave 1 T1 touched `tests/test_copywrite.py` (2 mechanical pin hunks) outside its assigned set — disclosed by the agent, verified harmless.

## Growth attribution (no ceiling; measured, attributed)

Production `hypesocials/`: 31,086 → **31,460 (+374)** — copywrite.py +105 (F2 strip + provenance) · generate/carousel.py +120 (F3/F4/F1-C) · gauntlet.py +46 (fix_reserve + constants + docstrings) · slide_intel.py +42 (counter_line) · prompts_engine.py net −15 (+47 wiring/spell − twin shrink with compressed templates) · runner.py +18 · budget.py +17 · models.py +17 · config.py +14 · llm.py +5 · styles.py +1. Nothing absorbed by trimming prose.
Tests: 26,100 → **27,053 (+953)** — NEW `test_prompt_fit.py` (467, F1-D) + NEW `test_role_settings.py` (150, F5) + F2/F3/F4/F1-C regressions and pin renegotiations across 8 existing suites. 56 new test ids.

## Docs / PRD state

- **PRD conflicts: none.** Wave 0 synced FR-324 ("one extra round", `prds/10-pipeline.md`, `00-overview.md`), `prds/30` (critic_reasoning_effort — corrected: no per-critic reasoning knob exists), `prds/40` (`chrome_counter_stripped` + `panel_counter_stripped`), `prds/50` (spelled-out example), spec `02-GAUNTLET-SPEC.md` §1/§4b/§5/money-seam.
- **NAVIGATION.md:** Session 5.5 chronology entry added (§13 tail) naming the two new test suites; the file still predates the v2.2.0 gauntlet build itself — full re-base owed by Session 6 T3.2.
- `prompts/README.md` re-based (list_treatment row, conditional spell echo).

## STOP point

Per plan: Session 6 (original Wave 3 — T3.1 regression suite, T3.2 docs/PRD.html republish, T3.3 read-only review) starts **only on operator sign-off** on this canary table, including a ruling on F7 (counter fidelity) and on whether a second canary should gate the config re-enable.
