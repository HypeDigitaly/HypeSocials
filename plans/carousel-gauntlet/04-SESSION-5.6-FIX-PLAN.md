# Session 5.6 — F7 counter fidelity (small fix round + canary #2)

**Date:** 2026-08-19 · **Operator rulings (explicit consent, this session):** (1) Session 5.6 before Session 6; (2) F7 policy SPLIT — a wrong/missing counter (`counter_value`, brief critic) keeps BLOCKING; cosmetic placement inconsistency (`counter_placement`, system critic) DEGRADES and ships. Canary #2 spend (~$0.40–0.80) pre-approved; configs flip on ONLY on a green canary.

**Context:** Session 5.5 (closeout `plans/SESSION-5.5-CLOSEOUT.md`) fixed F1–F5 and verified them live on run `output/20260819_170148_2z4y`; the deck still BLOCKED 3/3 on F7 — gpt-image-2 oscillates the deck's own FR-313 counter across re-renders (chip vs plain vs missing), and re-renders fixing OTHER defects drop the counter as collateral. Critics verified correct against pixels.

## Fixes

**F7-A · Cosmetic tier (policy split, D15 amendment first).** `gauntlet.py:119-124`: new `COSMETIC_CODES = frozenset({"counter_placement"})`, removed from `CONTRACT_CODES`. Terminal policy (`gauntlet.py:780-805`): standing cosmetic codes alone (no leakage/contract) → the exact `fail_action: degrade` semantics — result `degraded`, `report.degraded_gate = True`, deck SHIPS with `GAUNTLET_DEGRADED` (`carousel.py:1385-1389` path already live). Re-render targeting unchanged: `counter_placement` still buys fix rounds (`_fails`), it just can't be the reason a deck dies. Vocabularies (spec §3) stay frozen — only the FR-325 tier assignment moves. PRD: `prds/10-pipeline.md` FR-325 tier table + `00-overview.md` echo + spec `02-GAUNTLET-SPEC.md` §2/§7 amended BEFORE code (D15; operator consent recorded above).

**F7-B · Anchor-lock the counter (first-render consistency).** `prompts/gpt-image-2/carousel_anchor_instruction.md` (currently 1,498 B, no counter mention): add one clause — copy the anchor's position-badge PLACEMENT and chip TREATMENT; only the number is this slide's own (it comes from the TEXT block; never copy the anchor's number). Constraint: the block stays **≤1,500 B including the clause** (re-compress elsewhere; net-zero so `tests/test_prompt_fit.py`'s `_TRIO_CUT_CEILING` 1,600 stays honest). `_BUILT_INS` twin resync.

**F7-C · Collateral-loss guard in the fix sheet.** `prompts/gauntlet_fix.md` closing/precedence: strengthen to name the badge — re-render applies ONLY the fixes listed; every other element, **including the position badge and every sanctioned mark**, stays exactly as rendered. (`fix_reserve` auto-recomputes from the loaded sheet — no constant to chase; fit tests derive from the accessor.) Built-in sheet twin in `gauntlet.py` resynced.

**F5-tail · Estimator completion re-base.** Canary #1 measured ≈434 completion tok/call at `reasoning: low` vs the provisional 5,000. `budget.py` `_CRITIC_COMPLETION_TOKENS` 5000 → **1000** (honest-high at ~2.3×). Spec §5 numbers + `tests/test_budget.py` pins recomputed.

## Waves (flat, conductor = main thread)

- **W0 · docs · technical-writer** (∥ W1): FR-325 cosmetic tier in `prds/10-pipeline.md` + `prds/00-overview.md`; spec §2/§7 tier text + §5 completion re-base. Historical plans untouched.
- **W1 · code · python-pro** (∥ W0): F7-A in `gauntlet.py` (+ the `degraded_gate` set), F5-tail in `budget.py`; minimal pin updates `tests/test_gauntlet.py`/`tests/test_budget.py`.
- **W2 · prompts · prompt-engineer** (after W1 barrier): F7-B + F7-C + twin resyncs (template twin in `prompts_engine.py`, sheet twin in `gauntlet.py` — string constants only).
- **W3 · tests · test-automator**: tier regressions (standing `counter_placement` alone → degraded + ships + tag; `counter_value` → blocks; leakage tier unaffected; cosmetic still re-rendered), fit-test still green with the new anchor bytes, fix-sheet closing pin.
- **W4 · canary #2 + flip:** same invocation as canary #1 (`--config hypedigitaly --carousels 1 --images 0 --reels 0 --history-days 0 --gauntlet --yes --verbose`). **Green =** deck delivered (pass or degraded-cosmetic-only), zero `hard_truncated=True`, no F1–F5 recurrence. Green → flip `gauntlet.enabled: true` in all four configs, drop SESSION 5 rollback comments, re-measure critic completion, append to `SESSION-5-LIVE-ACCEPTANCE.md`. Not green → configs stay off, findings recorded, stop. Then `plans/SESSION-5.6-CLOSEOUT.md` either way; Session 6 follows on sign-off.

**Barriers:** `.venv/Scripts/python.exe -m pytest -q` green at every wave boundary (baseline **1362**).

## Out of scope
Any further critic prompt tuning, reels gauntlet, style re-authoring, committing the tree.
