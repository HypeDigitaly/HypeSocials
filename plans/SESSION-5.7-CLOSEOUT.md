# SESSION 5.7 — CLOSEOUT (F8 low-confidence rule + canary #3)

**Date:** 2026-08-19 · **Plan:** `plans/carousel-gauntlet/05-SESSION-5.7-FIX-PLAN.md` · **Canary #3:** `output/20260819_191734_0jc2` ($0.57 of $10)
**Suite:** 1371 → **1379 passed, 0 failed**. **Configs: gauntlet stays OFF** — canary #3 blocked on a NEW structural pattern (F9 below). Cumulative canary spend (3 runs): $2.21.

## Fix status

| Fix | Status | Canary #3 evidence |
|---|---|---|
| F8-A low-confidence system demotion (defect-level partition, terminal-only) | ✅ SHIPPED & VERIFIED LIVE | Round 1's low-confidence `style_consistency` (f2) did NOT block; round 3's `counter_placement` (high) correctly went to the cosmetic bucket. The block came only from a HIGH-confidence `style_consistency` — exactly the policy as ruled. 8 offline matrix ids incl. the canary-#2 replay (now `degraded`). |
| F8-B console fork wording | ✅ SHIPPED | "cosmetic/low-confidence defect(s) stand and ship (FR-325)". |
| FR-325 docs (four tiers + low-confidence rule) | ✅ SYNCED | 10-pipeline, 00-overview, spec §2 + craft-rule twin note. |

**All prior fixes held:** zero counter_value defects (counters byte-perfect on every slide), zero hard truncation, deck re-renders $0.09 ≤ $0.30, critic **$0.024/call** (completion ≈230 tok/call), wall-clock 9m39s — the cheapest, fastest canary yet. Rounds: 2 failed → 1 → 1.

## New finding F9 — consistency chasing + final-round discovery (the remaining structural blocker)

Round-by-round (letterpress deck, 5 slides, style `letterpress-print-carousel`):
- R1: f2 `style_consistency` low (demoted ✓), f3 high → re-render f2, f3.
- R2: f3 again (layout high + low) → re-render f3.
- R3: **f4** — a frame that PASSED rounds 1–2 and was never re-rendered — now flagged high (`counter_placement` chip border → cosmetic ✓; `style_consistency` headline treatment → **BLOCK**). No rounds left.

Two structural mechanics, verified against the artifacts and pixels:
1. **The consistency baseline moves.** The system critic judges the FULL deck every round; re-rendering frames toward their siblings shifts what "the siblings" look like, so a previously-consistent frame can become the outlier. Convergence is not guaranteed by construction.
2. **Final-round discovery is unfixable.** A defect first raised in the last round on a never-re-rendered frame has zero fix opportunities — the block fires without the deck ever having had a chance to correct it (asymmetric with FR-324's whole philosophy).

The f4 verdict itself is defensible-but-strict (headline treatment genuinely differs from siblings; the deck is visually good and the source deck's own slides vary).

## Candidate dials for F9 (operator decision, none applied)
- **(a) Final-round grace:** a defect first discovered on the final round on a never-re-rendered frame degrades instead of blocks (it never had its FR-324 chance). Small terminal rule, symmetric with existing philosophy.
- **(b) Anchor-baseline judging:** critic prompt tells the system critic to judge consistency against frame 1 (the anchor) only, not all-pairs — freezes the moving target at its source.
- **(c) `fail_action: degrade` in shipped configs:** every non-leakage deck ships tagged; operator reviews the gallery. Zero code, but also waters down high-confidence real defects.
- **(d) Accept the block rate** (~1 blocked deck per run at current quality, $0.4–0.9 each) and just re-run.

## Growth
Production 31,529 → **31,597 (+68)**: gauntlet.py +62 (defect-level partition + helper + docs) · runner.py +6. Tests 27,354 → **27,604 (+250)**, +8 ids. PRD conflicts: none. NAVIGATION.md: chronology note owed at next docs pass (Session 6 T3.2 still owns the full re-base).

## STOP point
Canary #3 not green → configs stay `enabled: false`. Next: operator rules on F9 (a/b/c/d or combination) → then canary #4 or Session 6.
