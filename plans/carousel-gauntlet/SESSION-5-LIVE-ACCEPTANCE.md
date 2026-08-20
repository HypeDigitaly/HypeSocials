# SESSION 5 — Live Acceptance (Wave 2c) — Measurement & Rollback Record

**Date:** 2026-08-14 · **Run:** `output/20260814_224004_gcg5` · **Config:** `hypedigitaly` (same single Virlo monitor `AI Trends Tracker` 9c96fddf as audited runs `…_59el`/`…_m39f`) · **Invocation:** `--carousels 3 --images 0 --reels 0 --history-days 0 --yes --verbose`
**Pre-run barrier:** suite green (1305 passed). **Outcome:** 21/21 renders ok · **0 pass, 3 BLOCKED** · $2.11 of $10 cap · 22 m 43 s · exit 1.

## ROLLBACK APPLIED (criterion tripped)

Rule: >50% of decks BLOCK on defect classes Phase 1 should have removed. Result: **2/3 (67%)** —

- **Ig deck** blocked on a **polluted contract**: the SOURCE slideshow's own counter `01 / 06` (6-slide source) rode the panel text into `FrameContract.body_lines` as `L18`; our 5-slide render correctly shows `01 / 05`, so brief flagged `missing_text` on a *correct* frame. Chrome-text carry-through is Phase-1 territory (OCR carry-through row of the audit).
- **Li deck** blocked on **audit defect #7's class** (list treatment / style conflict): list panels oscillated across three treatments over three rounds. Root cause: enriched styles + verbatim list text blow Kie's 19,800-char cap — `prompt_hard_trimmed` on **17 of 21 submissions** (style trio cut `render_prompt −625, style_dna −2078`, plus 296–1,957 chars HARD truncation) — so the `list_mode` layout guidance Phase 1 added never reached the renderer.
- Tk deck's block (missing counter badge on the anchor) is a genuine render defect, correctly caught — it does NOT count toward the criterion.

**Action (per plan, no live tuning):** `run.gauntlet.enabled: false` set in all four shipped configs (`default.yaml`, `hypedigitaly.yaml`, `hypedigitaly-fresh.yaml`, `hypedigitaly-cs.yaml`), each with a pointer to this file.

## (a) The 10 audit defects (Carousel Audit 08-14)

| # | Audit defect | Verdict | Evidence (run gcg5) |
|---|---|---|---|
| 1 | Caption leaks niche config | **ABSENT** | All 3 captions are verbatim source text + hashtags; no niche descriptor on any path |
| 2 | Strip kills handles, not identities | **ABSENT** | `author_name` producer live: 9 creator lines dropped (`EMIR AI LAB` ↔ `emirailab`), `competitor_stripped`, 2 dangling-promo CTAs stripped (`comment_keyword_bare`, `link_in_bio`) |
| 3 | Invented text becomes pixels | **CAUGHT-BY-GAUNTLET** | Li round 1: `invented_text` on 4 frames (verified genuine — e.g. "AI Tools for" prepended to contracted words); all cleared by the round-2 re-renders |
| 4 | List/table pair corruption | **ABSENT / not observed** | No `pair_break` fired; rendered lists keep label+value rows paired. (List *placement* still broken — see #7) |
| 5 | Vision gate doesn't gate | **ABSENT (fixed)** | Gate blocks hard: 3 BLOCKED, nothing published, artifacts kept (FR-74), `BLOCKED.txt` + `GAUNTLET_REPORT.yaml` written, exit 1 |
| 6 | FR-315 crops broken | **ABSENT (fixed)** | Allow-gating live: Ig 1 box → 0 cropped (unsanctioned), Tk 7 → 1 (`Obsidian`), Li 21/21 sanctioned tool marks; no apparel/chrome uploads |
| 7 | Style budgets / FR-304 conflict | **STILL-PRESENT (mutated)** | Li blocked on exactly this class; root cause is now prompt overflow (see rollback section) — the fix exists but is truncated out of the payload |
| 8 | Re-render / wave-2 drift | **ABSENT (fixed)** | Gauntlet re-renders carry anchor + delivered-neighbor + patches (`references=5` on the slide-8 retry); anchor re-chain live |
| 9 | Provenance, bookkeeping, spend gates | **MOSTLY ABSENT** | Bound-post provenance in console/meta (`@emirailab`, `@appmillers`, `@theromanknox`); BLOCKED decks carry billed cost. ⚠ deck re-render spend hit **$0.33 vs `deck_budget_usd: 0.30`** — 11th re-render not declined (finding F4) |
| 10 | Screen misses language/audience | **ABSENT (fixed)** | Every verdict carries `language=en audience_fit=True`; promotional topic skipped (`skip_code=PROMO`) |

## (b) Rounds-to-converge per deck

| Deck | Slides | Rounds | Re-renders | Terminal | Standing codes (tier) |
|---|---|---|---|---|---|
| Li_car_claude-ai-for-coding-development_01 | 8 | 3/3 | 11 | **BLOCKED** | `style_consistency`, `style_layout` (contract) — craft `logo_fidelity` all `confidence: low`, correctly non-failing |
| Ig_car_claude-ai-for-productivity-and-business_02 | 5 (anchor only billed) | 1/1 (anchor pre-gate) | 0 | **BLOCKED** | `missing_text` (contract) — false positive from polluted contract |
| Tk_car_vibecoding-ai-demos-and-practices_03 | 7 (anchor only billed) | 1/1 (anchor pre-gate) | 0 | **BLOCKED** | `counter_value` (contract) — genuine missing counter, but pre-gate rounds=1 gives no fix chance |

No deck converged. The anchor pre-gate (rounds_max=1 by frozen spec) converts any anchor defect straight to BLOCKED with $0 re-render spend — cheap, but unforgiving (finding F3).

## (c) Cost actuals vs 02-GAUNTLET-SPEC.md §5

| Metric | Spec §5 | Actual | Ratio |
|---|---|---|---|
| Critic $/call | ~$0.028 | $1.30 / 15 calls = **$0.087 avg** (Li deck calls ≈ $0.11) | **3.1×** |
| Critic $/deck (3-round worst case) | ~$0.25 | Li **$1.24** · Ig $0.036 · Tk $0.028 | **5× on the full deck** |
| Completion tokens/call | ~700 | 75,417 / 15 ≈ **5,028** — 3 calls hit the 8k cap and retried at 16k | **~7×** |
| Re-render $/deck | ≤ $0.30 cap | Li **$0.33** (cap overshot), Ig/Tk $0 | cap not honored on last submit |
| Run total | — | **$2.11** ($1.48 LLM — critic $1.30 — + $0.63 render), $7.89 unused | within cap |

## (d) Wall-clock

**22 m 43 s** (1,363 s) vs 60-min deadline — 21 render jobs (3 wave-1 + 17 wave-2 incl. 11 gauntlet re-renders), no runway declines, no deadline stop.

## Findings for Session 6 (nothing tuned live)

- **F1 — Prompt budget crisis (root cause of the Li block, still-present #7):** 17/21 submissions `prompt_hard_trimmed`; the T1.6 style enrichment + verbatim list text exceed the 19,800-char cap, so style_dna/list_mode guidance is cut at submit. Fix belongs in styles.yaml budget realism / prompt assembly, not in the gauntlet.
- **F2 — Contract pollution by source chrome:** the source deck's own counter string (`01 / 06`) entered `body_lines`; needs a chrome-text strip (or counter-pattern flag) at panel admission, symmetric with the FR-330 chrome mark filter. Caused a false `missing_text` BLOCK on a correct render.
- **F3 — Anchor pre-gate has no fix path:** rounds_max=1 (frozen spec) means any anchor defect = instant deck BLOCK, zero re-render attempts; 2 of 3 blocks happened there. Consider one anchor re-render round.
- **F4 — `deck_budget_usd` off-by-one:** 11 × $0.03 = $0.33 > $0.30; the 11th re-render should have been `declined_deck_budget`.
- **F5 — Critic economics:** completion ~5k tokens/call (spec assumed 700); 3 `llm_truncated` retries at 16k. Spec §5 arithmetic and `max_tokens.critic` need re-basing; consider tighter per-frame `detail` discipline.
- **F6 — `critic_empty_fail` path exercised** (system, frame 8, round 3) — handled as designed (read as pass, logged).
- **Positive:** the loop itself works — invented text found and FIXED in one round; round-2 scoping, low-confidence craft non-failing, neighbor refs, allow-gated crops, BLOCKED bookkeeping, exit policy and the LLM-usage table all behaved to spec.

**Session 6 gate:** operator sign-off on this table required before Wave 3 (tests/docs/review) proceeds.

## RESOLVED BY SESSION 5.5 (2026-08-19)

Findings F1–F5 above were fixed, proven offline (suite 1305 → 1362) and re-measured live on canary run `output/20260819_170148_2z4y` (1 carousel, $0.79): **zero hard truncations** (was 17/21 submissions — F1), **zero chrome/counter contract pollution** (`// 01`–`// 04` stripped at admission with provenance — F2), pre-gate re-render granted per FR-324 (F3, exercised offline; canary anchor passed clean), deck re-render spend $0.24 ≤ $0.30 cap under reserve-then-submit (was $0.33 — F4), critic $0.031/call at `reasoning: low` vs $0.087 here (completion ≈434 vs ≈5,028 tokens/call — F5). The canary deck still **BLOCKED 3/3** — on a NEW genuine class (F7: FR-313 counter fidelity oscillating under re-render churn; verified against pixels, critics correct) — so `run.gauntlet.enabled` **stays false** in all four shipped configs pending the operator's ruling. Full table and F7 write-up: `plans/SESSION-5.5-CLOSEOUT.md`.

**Session 5.6 (same day):** F7 fixed (FR-325 cosmetic tier + anchor badge-lock + fix-sheet collateral guard) and verified on canary #2 `output/20260819_181930_8e6d` ($0.85): **zero counter defects**, convergence 5→1→1, critic $0.0287/call. Deck still blocked — one LOW-confidence `style_consistency` micro-placement verdict (new finding **F8**: low-confidence system verdicts block; craft's low-confidence rule has no system twin; FR-315 mark placement vs cross-frame consistency tension). Configs remain off. See `plans/SESSION-5.6-CLOSEOUT.md`.

**Session 5.7 (same day):** F8 fixed (FR-325: low-confidence system verdicts re-render but degrade at terminal, defect-level partition) and verified on canary #3 `output/20260819_191734_0jc2` ($0.57): the demotions fired correctly, counters byte-perfect, critic $0.024/call, cheapest run yet — but blocked by a HIGH-confidence `style_consistency` first raised on the FINAL round on a never-re-rendered frame = finding **F9** (consistency chasing: re-renders move the sibling baseline; final-round discoveries have zero fix rounds). Configs remain off. See `plans/SESSION-5.7-CLOSEOUT.md`.

**Session 5.8 (same day):** F9 fixed (FR-325 final-round grace, contract-tier, >= 2 rounds; anchor-baseline judging in critic_system.md) and verified on canary #4 `output/20260819_214018_xm28` ($0.66): anchor-baseline verdicts all frame-1-relative, F8 demotion held, counters/truncation clean — but blocked on two PIXEL-VERIFIED missing sanctioned Claude marks (brief, low-conf) on re-rendered frames = **F10, render-model reliability**: gpt-image-2 drops required elements on re-renders despite the F7-C guard. Four canaries, four blocks, each class fixed and each next block rarer and more genuine. Configs remain off; policy menu in `plans/SESSION-5.8-CLOSEOUT.md`.

## GAUNTLET RE-ENABLED (2026-08-20)

Operator ruling on F10: `fail_action: degrade`. All four shipped configs now `enabled: true, fail_action: degrade` — contract-tier defects ship TAGGED for gallery review; leakage still hard-blocks. Verified by canary #5 `output/20260820_000230_wv2f` (first delivered deck; caught-and-fixed invented_text, shipped degraded on missing marks, exit 0) and the 4-carousel style batch `output/20260820_001158_2ard` (2 pass / 1 degraded / 1 correctly BLOCKED on a pixel-verified creator-username leak). The untagged-degrade gap was closed the same day. This file's rollback is hereby fully resolved.