# Session 5.7 — F8: low-confidence system verdicts never block (+ canary #3 gates the flip)

**Date:** 2026-08-19 · **Operator rulings (explicit consent):** (1) a LOW-confidence system-critic verdict still buys its re-render rounds but cannot block the deck at terminal — a deck whose only standing non-cosmetic defects are low-confidence system verdicts ships `degraded` (GAUNTLET_DEGRADED), whatever `fail_action` says; high-confidence system verdicts and all brief-critic contract codes keep blocking. (2) Canary #3 (~$0.40–0.85, pre-approved) gates the config re-enable: delivered (pass or degraded) + zero counter defects + zero hard truncation → flip `gauntlet.enabled: true` in all four configs and drop the SESSION 5 rollback comments.

**Context:** Canary #2 (`output/20260819_181930_8e6d`, closeout `plans/SESSION-5.6-CLOSEOUT.md`) blocked on ONE low-confidence `style_consistency` micro-placement verdict after F7 eliminated all counter defects. The craft critic already has a low-confidence non-failing rule; the system critic has no symmetric rule.

## Changes

**F8-A · Terminal demotion of low-confidence system verdicts** (`gauntlet.py`). The standing-codes partition in `_terminal` becomes confidence-aware for SYSTEM codes only: a standing system defect with `confidence: low` joins the cosmetic/degrade bucket instead of the contract bucket (exactly the cosmetic-tier outcome: result `degraded`, `degraded_gate = True`). High/medium-confidence system defects and all non-leakage brief defects stay contract tier. Re-render targeting (`_fails`) UNCHANGED — the craft critic's existing low-confidence rule (which suppresses failing entirely) is NOT copied; the system rule is terminal-only per the ruling ("still buys a re-render attempt"). Leakage precedence untouched.

**F8-B · Console wording** (`runner.py` degraded-gate fork): generalize the non-D3 line to cover both degrade causes (cosmetic tier / low-confidence system verdicts).

**F8-C · D15 docs first**: FR-325 (`prds/10-pipeline.md` + `00-overview.md` echo) — the cosmetic-tier sentence grows the low-confidence-system rule (or a sibling clause beside it); spec `02-GAUNTLET-SPEC.md` §2 terminal tiers + wherever §3/§4 documents the craft low-confidence rule gains the system twin with the re-render-still-bought distinction.

## Waves
- **W0 docs (technical-writer) ∥ W1 code (python-pro)** — disjoint. W1 owns gauntlet.py + runner.py + minimal pin fixes in tests/test_gauntlet.py / test_console_inventory.py.
- **W2 tests (test-automator):** standing low-conf system alone → degraded + tagged + shipped (both fail_action values); high-conf system → blocked; low-conf system + high-conf contract → blocked; low-conf system + cosmetic → degraded; low-conf system still re-renders; leakage untouched. Canary-#2-shaped regression: the `_8e6d` terminal set (one low-conf style_consistency) now ends degraded.
- **W3 canary #3 + flip:** same invocation (`--config hypedigitaly --carousels 1 --images 0 --reels 0 --history-days 0 --gauntlet --yes --verbose`). Green (delivered, zero counter defects, zero hard truncation, no F1–F5 recurrence) → flip all four configs (`enabled: true`, rollback comments out, pointer comments to the closeouts), verify configs load, then `plans/SESSION-5.7-CLOSEOUT.md`. Not green → configs stay off, findings recorded, stop.

**Barriers:** full suite green at every boundary (baseline **1371**).

## Out of scope
Brief-critic confidence rules, craft rule changes, `prompts/` edits, the pre-existing tier-2 untagged-degrade gap (Session 6), committing the tree.
