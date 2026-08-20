# SESSION 5.8 — CLOSEOUT (F9 grace + anchor baseline + canary #4)

**Date:** 2026-08-19 · **Plan:** `plans/carousel-gauntlet/06-SESSION-5.8-FIX-PLAN.md` · **Canary #4:** `output/20260819_214018_xm28` ($0.66)
**Suite:** 1379 → **1389 passed, 0 failed**. **Configs: gauntlet stays OFF** — canary #4 blocked on genuine (verified in pixels) missing sanctioned marks. Cumulative canary spend: $2.87 across 4 runs.

## Fix status

| Fix | Status | Canary #4 evidence |
|---|---|---|
| F9-A final-round grace (contract-tier only, ≥2 rounds, never-re-rendered frame, first-seen pair) | ✅ SHIPPED | Correctly did NOT fire — the standing frames (4, 5) were re-rendered in R2, so they had their fix chance. Offline: canary-#3 replay ships degraded; single-round gates keep full tier behavior (conductor-ruled guard); 9 matrix ids + direct-predicate coverage, mutation-checked. |
| F9-B anchor-baseline judging | ✅ SHIPPED & VISIBLY WORKING | Every consistency verdict in the run names frame 1 as the reference ("frame 1 shows hooded human figure", "frame 1's teal gift box"). No sibling-relative churn; only 1 defect in R1 (vs 5 in #2's R1). Template pins guard the wording (incl. zero occurrences of "sibling"). |
| F8 low-confidence system demotion | ✅ held | R3's low-conf `style_consistency` (f5) was demoted — did not contribute to the block. |
| F7/F1–F5 | ✅ held | Zero counter defects, zero hard truncation, re-renders $0.15 ≤ $0.30, critic $0.027/call, 8m45s. |

## Why canary #4 still blocked (and why that's the system working)

R3 standing: `missing_mark` (brief) on frames 4 and 5 — "No CLAUDE wordmark visible". **Pixel-verified TRUE**: both slides carry no Claude mark though the contract requires it (source deck's sanctioned mark). The frames were re-rendered in R2 for other defects and the re-render dropped the marks — despite F7-C's explicit "every sanctioned mark stays" guard in the fix sheet. Brief verdicts are never confidence-demoted (5.7 ruling) and the frames had fix chances (no grace) → correct BLOCK under current policy.

## The empirical picture after 4 canaries ($2.87)

| # | Blocked on | Verdict quality | Class |
|---|---|---|---|
| 1 | counters + truncation + churn | correct | fixed (F1–F7) |
| 2 | 1 low-conf logo micro-placement | marginal | fixed (F8) |
| 3 | final-round consistency discovery | defensible | fixed (F9) |
| 4 | 2 real missing sanctioned marks | **correct** | render-model reliability |

Each fix eliminated its class and the next block moved to a rarer, more genuine defect. The residual failure mode is now irreducible by policy: **gpt-image-2 loses some required element on a nontrivial fraction of re-renders**, and with ~10–14 verdicts per deck one standing brief/high-conf defect blocks. The critics were right in every pixel-checked case since #2.

## Options for the operator (none applied — plan says STOP on a failed canary)

1. **Accept the block rate** and flip on: expect a meaningful fraction of decks blocked (~$0.4–0.9 each); blocked decks stay on disk and are often manually usable.
2. **`fail_action: degrade`** in shipped configs: non-leakage decks always ship tagged; the gallery is the review gate. Leakage (competitor logos, invented text) still blocks hard. Given the operator publishes manually anyway, this fits the single-operator workflow.
3. **Demote low-confidence BRIEF verdicts too** (both #4 standing marks were `low`): one more policy notch; high-conf brief still blocks. Would have shipped canary #4 degraded.
4. **Mark-preservation hardening** (prompt work): bake the sanctioned-marks line into the re-render fix suffix more aggressively (e.g. repeat the tool_marks line inside the fix). Diminishing returns territory.

## Growth
Production 31,597 → **31,722 (+125)**: gauntlet.py +121 (grace helper + guard + docs) · prompts_engine.py +4 net (critic template twin +185 B). Tests 27,604 → **28,055 (+451)**, +10 ids (1389 total). Docs: FR-325 grace clause (three conductor corrections applied: invented leakage exception removed, re-render note scoped, contract-tier + ≥2-rounds conditions synced). PRD conflicts: none.

## STOP
Per plan. The four closeouts (5.5 → 5.8) are the complete record. Session 6 (docs/tests/review) can proceed independently of the F-policy decision.
