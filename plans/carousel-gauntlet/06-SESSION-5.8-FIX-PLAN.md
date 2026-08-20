# Session 5.8 — F9: final-round grace + anchor-baseline judging (+ canary #4 gates the flip)

**Date:** 2026-08-19 · **Operator ruling (explicit consent):** fix F9 with BOTH dials — (a) a standing defect FIRST discovered on the final round, on a frame never re-rendered this run, degrades instead of blocks (it never had its FR-324 fix chance); (b) the system critic judges cross-frame consistency against FRAME 1 (the anchor) as the FIXED reference, not against arbitrary siblings. Canary #4 (~$0.40–0.85, pre-approved) gates the config re-enable: delivered (pass or degraded) + zero counter defects + zero hard truncation → flip `gauntlet.enabled: true` in all four shipped configs, drop the SESSION 5 rollback comments.

**Context:** Canary #3 (`output/20260819_191734_0jc2`, closeout `plans/SESSION-5.7-CLOSEOUT.md`): re-rendering frames toward their siblings moved the consistency baseline; frame 4 (passed R1–R2, never re-rendered) was flagged high-confidence for the first time in round 3 with zero fix rounds left. Structural note: by FR-324's round scoping (brief/craft on re-rendered only in rounds ≥2; system on the full deck), a final-round discovery on a never-re-rendered frame can ONLY be a system verdict — the grace rule is de-facto system-scoped, but write it generally with an explicit leakage carve-out (leakage always blocks; all leakage codes are brief codes anyway).

## Changes

**F9-A · Final-round grace (gauntlet.py, D15 docs first).** In `_terminal`, a standing defect joins the degrade bucket (same outcome as cosmetic/low-conf: `degraded` + `degraded_gate True`, ships tagged) when: its frame is NOT in the union of all rounds' `rerendered` lists, AND its (frame, code) pair appears in NO round before the final one, AND its code is not leakage. New private helper beside `_lowconf_system` (e.g. `_final_round_discovery(...)`) reading the run's round history. Precedence chain otherwise identical; re-render targeting untouched (nothing to re-render — the run is over; the rule is terminal-only by nature). FR-325 + spec §2 gain the grace clause.

**F9-B · Anchor-baseline judging (prompts/critic_system.md + `_BUILT_INS` twin in prompts_engine.py).** The template names frame 1 as reference once (line ~19) but defines/illustrates `style_consistency` as sibling-relative throughout (~:61, :80, :139-141). Rewrite those spots: frame 1's treatment is the FIXED baseline for every consistency verdict; a frame fails `style_consistency`/`counter_placement`-class checks iff it deviates from FRAME 1; never flag frame A for disagreeing with frame B — name the frame that deviates from frame 1. Frame 1 itself is judged against the style contract only, never against its followers. Keep the vocabulary (spec §3 frozen), the JSON shape, and every example's format; adjust example B's details to the anchor-baseline framing.

## Waves (all three parallel, disjoint; conductor barriers)
- **W0 docs · technical-writer:** FR-325 grace clause (prds/10-pipeline.md ~:315 + 00-overview.md ~:261 echo), spec 02-GAUNTLET-SPEC.md §2 tier block + a §3/§4 note that the system critic's baseline is the anchor (matching F9-B).
- **W1 code · python-pro:** F9-A in gauntlet.py + minimal pin fixes (tests/test_gauntlet.py).
- **W2 prompt · prompt-engineer:** F9-B in prompts/critic_system.md + twin resync (prompts_engine.py string constant ~:2876 ONLY).
- **W3 tests · test-automator:** grace matrix (final-round discovery on virgin frame → degraded; same defect seen earlier → blocks; re-rendered frame's final-round defect → blocks; leakage final-round → blocks; canary-#3-shaped replay → degraded) + critic-template phrase pins (anchor-baseline stems, file + twin).
- **W4 canary #4 + flip:** same invocation. Green → flip all four configs, verify they load, closeouts + memory. Not green → configs stay off, findings recorded, STOP.

**Barriers:** full suite green at every boundary (baseline **1379**).

## Out of scope
Brief/craft critic templates, re-scoring rounds mid-run, extra rounds, the tier-2 untagged-degrade gap (Session 6), committing the tree.
