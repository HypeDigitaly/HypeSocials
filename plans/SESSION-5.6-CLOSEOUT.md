# SESSION 5.6 — CLOSEOUT (F7 counter fidelity + canary #2)

**Date:** 2026-08-19 · **Plan:** `plans/carousel-gauntlet/04-SESSION-5.6-FIX-PLAN.md` · **Canary #2:** `output/20260819_181930_8e6d` ($0.85 of $10)
**Suite:** 1362 → **1371 passed, 0 failed** (green at every barrier). **Configs: gauntlet stays OFF** — canary #2 blocked, but on a NEW, marginal class (F8 below), not on anything F1–F7 owned.

## Fix status

| Fix | Status | Canary #2 evidence |
|---|---|---|
| F7-A cosmetic tier (FR-325 four tiers; `counter_placement` degrades, never blocks; still re-rendered) | ✅ SHIPPED | Not exercised live — **zero counter defects of either code in all 3 rounds** (canary #1 had 7 counter defects across rounds). Offline: full tier matrix pinned (6 new ids, negative-checked). |
| F7-B anchor badge-lock ("A QUOTED POSITION BADGE KEEPS IMAGE 1'S CORNER, CHIP AND SIZE; its digits alone are this slide's own") | ✅ SHIPPED | Counters visually identical on every slide (centered chip, correct N/7) — verified against pixels. Anchor file 1,498→1,409 B (clause added AND net shrink for trio headroom). |
| F7-C collateral guard (fix sheet: unnamed elements — badge and sanctioned marks included — stay as rendered) | ✅ SHIPPED | Re-renders no longer churned counters/marks: rounds converged 5 failed → 1 → 1 (canary #1: 4 → 4 → 4). `fix_reserve` 1,405→1,523; body budget 18,277. |
| F5-tail estimator (completion 5,000→1,000) | ✅ SHIPPED | Actual ≈327 completion tok/call (13 calls, 4,249 tok) — inside the 1,000 honest-high. Critic **$0.0287/call** actual vs $0.065 estimated. |

## Canary #2 table

| Metric | Canary #1 (`_2z4y`) | Canary #2 (`_8e6d`) |
|---|---|---|
| Hard truncation | 0 events (2 trims, 36 chars) | **0 events** (6 trims, floored, `hard_truncated: false`) |
| Counter defects | 7 across rounds (blocked on them) | **0** — F7 verified |
| Convergence | 4 → 4 → 4, blocked | 5 → 1 → 1, blocked |
| Deck re-render spend | $0.24 ≤ $0.30 | $0.21 ≤ $0.30 |
| Critic cost | $0.031/call | **$0.0287/call** ($0.373/deck, 13 calls) |
| Wall-clock | 13m58s | **10m35s** |
| Outcome | BLOCKED (counter_value + placement) | BLOCKED (**one** standing `style_consistency`, **confidence: low**) |

## New finding F8 (the remaining blocker — operator decision needed)

**Low-confidence system verdicts can block a deck on subjective micro-placement.** The single standing round-3 defect: "Obsidian logo placed inline beside headline rather than upper-right as on other frames" (frame 3, LOW confidence). Verified against pixels: marginal at best — slide 4 carries essentially the same inline placement and PASSED round 3; slide 2's standalone placement differs from both. Two structural observations:
1. The **craft** critic already has the rule "low-confidence craft never fails" by design (FR-326 area); the **system** critic has no such rule, so one hedged opinion about logo micro-placement kills a 7-slide deck.
2. There is a latent **FR-315 vs system-critic tension**: sanctioned tool marks are placed "where the source panel put them" — which may legitimately vary per slide — while `style_consistency` demands cross-frame uniformity. The two contracts can disagree by design.

Candidate dials (all need D15 consent, none applied): (a) extend the low-confidence non-failing rule to the system critic (symmetric with craft); (b) low-confidence system verdicts degrade instead of block (a second cosmetic-tier membership); (c) exempt sanctioned-mark placement from `style_consistency` (FR-315 precedence); (d) accept and re-run blocked decks.

## Conductor fixes this session
`runner.py` degraded-gate console fork (cosmetic vs D3 wording — the old line would have lied for cosmetic degrades); `generate/carousel.py` GAUNTLET_DEGRADED comment (two causes).

## Pre-existing gaps recorded (NOT touched, for Session 6)
- Tier-2 `fail_action: degrade` outcome ships with `degraded_gate is False` → **untagged** (predates 5.6; pinned as current behavior).
- `_gauntlet_rollup` console header counts a degraded deck under "stopped".
- `prompts/README.md` not re-checked against the new anchor clause (twins are parity-pinned; README prose may lag).

## Growth
Production 31,460 → **31,529 (+69)**: gauntlet.py +55 (tier + constants) · runner.py +6 (console fork) · budget.py +3 · carousel.py +1 · prompts_engine twins ±0 net +4. Tests 27,060 → **27,354 (+294)**, 9 new ids. PRDs: FR-325 four tiers (10-pipeline + 00-overview), spec §2/§4/§5. PRD conflicts: none.

## STOP point
Canary #2 not green → configs stay `enabled: false`. Next decision is F8's dial — then either canary #3 or Session 6.
