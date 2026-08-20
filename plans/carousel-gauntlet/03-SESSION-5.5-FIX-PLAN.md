# Session 5.5 — Gauntlet Fix Plan (post live-acceptance rollback)

> **HANDOFF — how to run this in a fresh session**
>
> This file is the repo master (saved 2026-08-19 from the planning session). Paste this as the session prompt:
>
> ```
> 🟧 SESSION 5.5 — Gauntlet fixes F1–F5 (code + prompts; 💰 small paid canary at the end)
>
> /xecutor
>
> SESSION 5.5 of the carousel-gauntlet block (HypeSocials v2.2.x).
> Plan: plans/carousel-gauntlet/03-SESSION-5.5-FIX-PLAN.md (THIS file) - read it IN FULL first;
> it is self-contained (root causes, file:line anchors, wave structure, test list).
> Python = .venv/Scripts/python.exe. Execute waves 0-5 with the barriers as written.
> Wave 5 spends real money (ONE canary carousel, ~$0.35-0.70, pre-approved; --gauntlet via
> CLI, shipped configs stay off until the canary passes). Then write
> plans/SESSION-5.5-CLOSEOUT.md and STOP — Session 6 (original Wave 3: tests/docs/review)
> only after operator sign-off on the canary table.
> ```
>
> **Prerequisites (verify before Wave 0, $0):**
> - Suite green at baseline: `.venv/Scripts/python.exe -m pytest -q` → **1305 passed** (post-rollback state, verified 2026-08-19).
> - All four `configs/*.yaml` carry `run.gauntlet: enabled: false` with SESSION 5 rollback comments — this plan REMOVES them only in Wave 5 step 3, only on a green canary.
> - The whole v2.2.0 gauntlet build is **uncommitted working-tree state** on `main` — do not commit/revert anything unless the operator asks; work on top of it.
> - Evidence base if needed: `plans/carousel-gauntlet/SESSION-5-LIVE-ACCEPTANCE.md` (measurement table + findings F1–F6) and run `output/20260814_224004_gcg5/` (events.jsonl, GAUNTLET_REPORT.yaml per deck).

## Context

Session 5's live acceptance run (`output/20260814_224004_gcg5`, 3 carousels, $2.11) blocked **all 3 decks** and tripped the rollback rule — `gauntlet.enabled: false` is now set in all four shipped configs. Forensics established that **the critic loop itself works** (it found genuine invented text and fixed it in one re-render round; low-confidence craft never blocked; crops/strips/bookkeeping behaved) — the blocks came from upstream/config defects F1–F5. This plan fixes them, proves the fixes offline, runs ONE live canary deck, and re-enables the gauntlet. All designs below are grounded in three code-exploration reports + an adversarial design review (2026-08-19); every anchor verified.

| # | Defect | One line |
|---|---|---|
| F1 | Prompt budget crisis + missing list-treatment wire | Li deck: critics judged list rules the renderer never received; every slide hard-truncated |
| F2 | Source-chrome counter pollutes the contract | Ig deck: source's `01 / 06` became expected line L18 → false `missing_text` BLOCK |
| F3 | Anchor pre-gate forbids the re-render the PRD grants | Tk deck: fixable missing counter → instant BLOCK; FR-324 already allows ≤1 anchor re-render |
| F4 | Deck budget check-before-reserve race | 11 × $0.03 = $0.33 shipped against $0.30 cap |
| F5 | Critic thinks unbidden at full effort | $1.30 critic spend, 3 truncation-retries; estimator constants fantasy (700 vs ~5,000 completion tokens) |

---

## Fix F1 — Prompt budget repair + wiring list treatment into the slide prompt

**Root causes (both verified):**
1. `carousel_slide.md` has **no `{{layout_zones}}` placeholder** (`prompts_engine.py:180-195` allowlist) — the T1.5 list-treatment gated append (`_style_zones` → `_list_treatment`, `prompts_engine.py:1152-1206`) reaches only image/reel/critic paths and the gauntlet contract (`contracts.py:233-234`). The critic judged list layout the renderer could never see.
2. Worst-case slide assembly measures **~25–27k chars** against the 19,800 provider wall (`render/profiles.py:74`): template fixed prose 11,838 + style_dna (T1.6 grew it to 2,450–3,997) + anchor block 4,122 inside untrimmable `{{reference_roles}}` + the `_spell` verbatim echo (~2,600 on a 1,500-char panel, `prompts_engine.py:1274-1281`) + exclusions. Hard truncation eats the assembled TAIL = the CONSTRAINTS back half (@handle/URL ban, exclusions, text-budgets, no-duplicate rule). Re-renders lose a further 924–1,248 chars to the fix-suffix reservation → each round rendered with less rulebook → oscillation → BLOCK.

**Changes (review-corrected):**

- **F1-A · `{{list_treatment}}` placeholder in `carousel_slide.md`**, placed INSIDE the SLIDE CONTENT region with an "(ignore if empty)" label (the template's ":16 only SLIDE CONTENT and TEXT change" sentence amended). Value = existing `_list_treatment(style, slide_text)`; empty for non-list panels. Wiring set (all in one commit — template lagging `build_context` fails every carousel test loudly): `build_context` emits the key with the same override gate as layout_zones (`"" if override else …`, `prompts_engine.py:685`); allowlist row; `models.PLACEHOLDERS` row (`models.py:797` — else `_unresolvable_names` silently falls back to the old built-in); `prompts/README.md` mapping table; `_BUILT_INS` twin. **NOT** added to `_STYLE_TRIO` (preserves `test_prompts_engine.py:1105/:1135` pins) — i.e. uncuttable; budgeted for in F1-D. The now-fully-dead `_style_zones` gated append (`prompts_engine.py:1190-1191` — no remaining caller passes `slide_text`) is **removed** and spec §4b's "consumed ONLY as a gated append to `{{layout_zones}}`" line rewritten to name the slide template's `{{list_treatment}}`.
- **F1-B · Prose compression, aimed at the big numbers (review inverted my original priority):**
  - `carousel_slide.md` fixed prose 11,838 → target **−1.5–2k** (same edit pass as F1-A/E; twin resync; `test_template_parity.py` is placeholder-set-based, safe).
  - `carousel_anchor_instruction.md` 4,122 → target **≤1,500** (mandatory, not conditional — the Q3 math fails without it).
  - `styles.yaml`: every `style_dna` → **≤1,800 chars** and every `list_mode.layout` compressed (503–934 today; it now ships in list slides via F1-A). Keep T1.6's design-system content, compressed. `render_prompt` untouched. No existing test pins shipped styles bytes (all styles tests use synthetic registries).
  - `_spell` echo policy (`prompts_engine.py:1274-1281`): spell only words that need it (non-ASCII/diacritics — its stated FR-186 purpose) instead of echoing everything — saves 1–2.6k on exactly the worst slides.
- **F1-C · Fix-suffix reservation, corrected formula** at `carousel.py:1178-1181`: `max_chars = (cap − FIX_RESERVE) + (len(fix) + 2 if fix else 0)`, capped at `cap` — body budget becomes IDENTICAL on first renders and re-renders (my draft's "cap − RESERVE on both passes" double-subtracted on re-renders). `FIX_RESERVE` computed per run from the LOADED fix sheet (`len(header) + 600 + len(sheet.precedence) + len(sheet.closing) + joins + 2`) because `gauntlet_fix.md` is operator-overridable with uncapped precedence/closing sections (`gauntlet.py:953-987`); shipped sheet ⇒ 1,402. Carousel role only — image/reel suffix callers (`generate/__init__.py:905-912`, `reel.py:615-618`) already count their suffixes correctly and are untouched.
- **F1-D · Per-style fit acceptance test** (new; the enforcement that drives F1-B's numbers — today NOTHING asserts "nothing was lost"; `test_prompts_engine.py:1167` passes with the production failure). For each of the 8 shipped styles, assemble via the real engine (pure string work, verified no network) a worst realistic slide: real template bytes, anchor block, neighbour + 2 patch roles, 21-mark tool line, counter, a LIST-triggering panel, at TWO panel lengths. Two-tier assertion (review: single-tier is unreachable at the sanctioned extreme): **`hard_truncated is False` always**; **trio cut == 0** at the live-shaped worst (~700-char panel); **trio cut ≤ floor-room** at the `PANEL_SANITY_CHARS` (1,500) extreme.
- **F1-E · Constraint reorder** in the same template pass: `{{exclusions}}`, the @handle/URL ban, the `{{text_budgets}}`/panel-no-budget rule and the no-duplicate-headline rule move ABOVE decorative constraints; tail ends with the most droppable prose; "The exclusions below" cross-references fixed after the move.

## Fix F2 — Counter/chrome strip at panel admission

**Verified leak path:** `virlo._panels` (`virlo.py:1187-1197`) passes `panel_texts` verbatim (the adapter has no `chrome_text` field; vision is the only chrome producer, `slide_intel.py:804`) → §0.11 merge lets Virlo bytes win (`slide_intel.py:305-308`) → `copywrite._offer_for` admits with no counter rule → `offer.panels`/verifier pool (`copywrite.py:863/:875`) → `panel_map.source_text` (`:2099`) → `carousel.self.texts` (`carousel.py:362`) → `contracts.frame_contract` splitlines (`contracts.py:146`) → `gauntlet._expected_blocks` L-lines (`gauntlet.py:862-864`) → false `missing_text`.

**Change (single site):** in `_offer_for`'s `kind == "panel"` branch between `_apply_strip` (`copywrite.py:828`) and the `kept[]=`/`haystack.append` pair (`:863/:875`), drop any panel **line whose entire content** matches a counter shape — reuse `slide_intel._COUNTER_TOKEN`/`_PREFIX_TOKEN` via a promoted public helper (e.g. `slide_intel.counter_line(text) -> bool`); full-line match only ("3/4 of teams…" is content and stays).
- **Byte-consistency invariant:** strip before BOTH `:863` and `:875` so panel_map, prompt, and the FR-100/101 verifier pool see identical bytes (else `copywrite.py:2757` false-flags `copy_not_verbatim`).
- `source_text_original` (from `pre_creator`, `:833`) KEEPS the counter line (provenance doctrine).
- New row flag `chrome_counter_stripped: true` in `_mapped_deck`'s row literal (`:2095-2112`) + WARN log — NOT `creator_stripped` (that would tag the creative `DegradationTag.COMPETITOR_STRIPPED`, `:1984-1995`).

## Fix F3 — Anchor pre-gate gets its one re-render (code-to-PRD alignment)

`prds/10-pipeline.md:313` (FR-324) already grants "≤1 anchor re-render, on the deck budget"; the code forbids it (`carousel.py:813-817` forces `rounds_max=1`; `gauntlet.py:555-557` breaks before `_rerender_all` on the last round). Per CLAUDE.md rule 3 this is a bug, not an amendment.

**Change:** `carousel.py:813` → `rounds_max=2, rounds_max_image=2` (run_single takes the MIN, `gauntlet.py:804-809`). No new machinery: the RerenderFn closure is already wired at the pre-gate (`carousel.py:861-864`), handles frame 1 (`:980`), and anchor spend already accrues into `deck_budget_usd` (`:330, :865-871`). Sync `02-GAUNTLET-SPEC.md:12-15` + tighten FR-324 wording to "one extra round".

## Fix F4 — Deck budget: reserve-then-submit

**Verified root cause:** check-before-reserve race — `gauntlet._rerender_all` (`gauntlet.py:698-700`) gathers all failing frames concurrently; every closure reads stale `self.gauntlet_spend` (`carousel.py:967-977`) before any accrual (`:993-994`). Reproduces the live $0.33 exactly (8 checks at $0.00, then 3 at $0.24). Float drift and estimate-vs-billed ruled out.

**Change:** adopt the run-cap's own pattern (`Budget.reserve`, `budget.py:1011-1023`): `asyncio.Lock` + reserved-sum on `_Deck`; under the lock, `gauntlet_spend + reserved + projected > cap` → `declined_deck_budget`, else reserve; after the await, release reservation and accrue billed cost.

## Fix F5 — Critic cost: bounded reasoning + honest estimator

**Verified:** critic requests set no `reasoning` param (`llm.py:367-368`; `runner.py:656` grants `reasoning_effort` to `copy` only) → Sonnet-5 thinks unbidden, billed inside `completion_tokens` (documented, `config.py:344-349`); truncated attempt + 16k retry BOTH billed by design (`llm.py:506-515`). Estimator constants `_CRITIC_PROMPT_TOKENS=1500`/`_CRITIC_COMPLETION_TOKENS=700` (`budget.py:94-95`) vs measured ≈18.3k in / ≈5.0k out per call.

**Changes:** (1) per-role reasoning control — critic requests `reasoning: {effort: low}` via a config row consistent with existing idioms (`config.py:337`, `runner._role_settings` `runner.py:638-658`); (2) re-base `budget.py:94-95` + spec §5 (`02-GAUNTLET-SPEC.md:194-197`) to measured numbers (completion re-measured at the canary after low effort lands); (3) keep `max_tokens.critic: 8000` + the widen ladder as the safety valve. Update `test_budget.py:662` (pins 700) and `:637` (allowance formula).

---

## Execution shape (flat waves, conductor = main thread)

**Wave 0 · docs (parallel with Wave 1) · technical-writer:** PRD/spec sync — FR-324 "one extra round" (`prds/10-pipeline.md:313`, `00-overview.md:260`), spec §1 pre-gate comment (`:12-15`), §4b list_mode consumption line, §5 cost re-base (`:194-197`), money-seam paragraph (deck-budget reservation). Duplicate FR text in `01-PRD-AMENDMENTS.md:53` / `00-MASTERPLAN.md:60` noted as historical (do not drift-edit plans).

**Wave 1 · code (parallel, disjoint) · python-pro ×3:**
- T1 `copywrite.py` + `sources/slide_intel.py`: F2 (helper promotion + admission strip + row flag).
- T2 `generate/carousel.py` (+ `gauntlet.py` fix-sheet length accessor if needed): F3 one-liner, F4 lock, F1-C corrected reservation.
- T3 `runner.py` + `config.py` + `llm.py` + `budget.py`: F5 (reasoning row, estimator constants, preflight-visible pricing unchanged).

**Wave 2 · prompts engine (sequential, single writer) · python-pro:** T4 `prompts_engine.py` + `models.py` — `{{list_treatment}}` wiring (build_context + override gate, allowlist, PLACEHOLDERS row), `_spell` echo policy, remove dead `_style_zones` append. (Everything except the template/styles bytes themselves.)

**Wave 3 · prompt artifacts (sequential, single writer) · prompt-engineer:** T5 `carousel_slide.md` (slot + reorder F1-E + prose compression −1.5–2k), `carousel_anchor_instruction.md` (→ ≤1,500), `styles.yaml` (dna ≤1,800, list_mode.layout compressed), `prompts/README.md` table; then `_BUILT_INS` byte-twin resync in `prompts_engine.py` (twins only).

**Wave 4 · tests · test-automator:** F1-D fit test (two panel lengths, two-tier assertion, list-triggering panel) + F2/F3/F4/F5 regression coverage. Known renegotiations: `test_copy_verbatim_filter.py:909-928` (1/8-chrome-echo pin), `test_gauntlet.py:427`, `test_carousel.py:826/:852` + pre-gate round-index comments (`:1427-1428, :1460, :1479-1480`), `test_carousel.py:1540` (extend with concurrent multi-frame round), `test_budget.py:637/:662`. Full suite green.

**Wave 5 · verification (paid canary):**
1. Offline stubbed dry-run ($0): pre-gate re-render round, concurrent deck-budget decline, counter-strip contract, body-budget pass-parity.
2. **ONE live carousel** (same monitor, gauntlet via `--gauntlet` CLI — shipped configs stay `false`): assert zero `hard_truncated=True` events, no counter false-positives, critic $/call vs re-based estimate, rounds-to-converge. (~$0.35–0.70.)
3. Canary passes → flip `gauntlet.enabled: true` in the four shipped configs, drop the SESSION 5 rollback comments, append results to `SESSION-5-LIVE-ACCEPTANCE.md`. Canary fails → configs stay off, findings appended, stop.

## Verification summary

- `.venv/Scripts/python.exe -m pytest -q` green at every wave barrier (baseline 1305 + new).
- F1-D fit test = the standing guarantee no style/template edit can reintroduce silent truncation.
- Live canary re-measures Session 5's four metrics before any config re-enable.

## Closeout (required before the session ends)

- `plans/SESSION-5.5-CLOSEOUT.md`: per-fix status (F1–F5), canary measurement table (same four metrics as Session 5: defects absent/caught, rounds-to-converge, critic+re-render $/deck vs re-based estimate, wall-clock), config re-enable state, wc-l growth attribution, NAVIGATION.md delta (or "none"), PRD conflicts (expected: none — Wave 0 syncs them).
- Update `plans/carousel-gauntlet/SESSION-5-LIVE-ACCEPTANCE.md` with a one-paragraph "resolved by Session 5.5" addendum linking the closeout.
- **STOP after the closeout** — present the canary table to the operator; Session 6 (original masterplan Wave 3: T3.1 regression suite, T3.2 docs/PRD.html republish, T3.3 read-only review) starts only on explicit sign-off.

## Out of scope (explicitly)

- Reels/finished-video gauntlet, critic prompt re-tuning beyond the reasoning knob, Virlo adapter chrome_text field (the admission strip covers the leak), Session 6 (original Wave 3 tests/docs/review — follows after this session), committing the working tree.
