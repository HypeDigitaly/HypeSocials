# PR: Render quality, design system and output language — Sessions J → N (v2.5.0 → v2.7.0, D59–D63)

Branch `session-k-colour-type-spine` → `main` (J's `a6c2a75` is its ancestor via `session-j-render-contracts`). Six commits — one per session plus `04c8fa0` (plans/tools path fix) — each green and closed out
(`plans/SESSION-J-CLOSEOUT.md` … `plans/SESSION-N-CLOSEOUT.md`). Plan: `plans/xmasterplan-render-quality-and-language.md`.
Baseline `main` suite 1568 → **1910 passed, 0 failed**; production 34,745 → 39,614; PRDs v2.5.0 → v2.7.0.

## Why

Paid run `20260820_145809_4a0q` (9 carousels, $7.50) was rejected on sight: an invented page-number chip that cost a
whole deck, blank placeholder bars, duplicated row text, six of nine decks on one style, teal drifting by 30 RGB
(worst 69) across decks, and a German deck shipped under an English config. Each session closes one of those.

## What each session shipped

| Session | Decision | Summary |
|---|---|---|
| J | D59 v2.5.0 | `{{counter_rule}}` render slot (FR-338), gated-zone DNA rule (FR-339), empty-zone rule (FR-340), FR-313 counter metadata; critic templates no longer make an invented chip law |
| K | D60 v2.5.1 | palette contract (FR-347, hex-based, one accent ≤ 1/8), type contract (FR-348), DNA-wide variant scan (FR-349), house spine (FR-350), `image_resolution: 2k` per platform (FR-342) |
| L | D61 v2.5.2 | seven carousel-derived styles, registry 19 → 26 / enabled 12 → 17 (FR-341), ASSIGN concentration line (FR-355); 3-carousel checkpoint |
| M | D62 v2.6.0 | cover best-of-3 with a vision pick (FR-351/352, `cover_pick.py`), `carousel_copy_mode: auto` — compress only the rows that overflow (FR-353/354) |
| N | D63 v2.7.0 | output language: translate only non-target posts, never shorten (FR-343–346); Virlo `language_detected` channel; FR-313 bare-numeral rule; `big-number-editorial` profile narrowed |

## SESSION N in one screen

- `run.copy_language_mode: source | target` (engine default `source`; the three brand configs pin `target`), `--copy-language`,
  confirm-screen + launch-summary lines, pre-flight warning for the creatives translation cannot reach.
- Language ladder: Virlo `language_detected` → slide-intel deck `language` → unknown (verbatim + warning). No heuristics, no extra call.
- `copywrite._call_translate` + `prompts/copy_translate_system.md` (11th global template): one call per deck, `_translate_field` has no
  budget, the prompt never states a ceiling, a translation may be longer than its source. **Translate first, then the auto budget test
  on the translated texts, then compress.** Fail-open to the verbatim deck + `copy_degraded` + `copy_not_translated`.
- Receipts: `copy_language` / `source_language` / per-row `translated` in `meta.yaml`, gallery chips, console counts, estimator `translate_call` line.
- `source`-mode bind screen (`plan.off_language_post`) skips a post in a language the run does not write — the German-deck fix on its own.

## Verification

- Suite green at every wave barrier (J 1568 → … → N 1910, incl. a read-only review round whose 14 findings were fixed in-session). Registry tools: `registry_contract_check` TOTAL 0 · `measure_prompt_fit` 0 of 26 outside.
- N previews: `--preview-sources` $0, `--preview-analysis` $0.69 — 9/9 matched, **7 distinct styles, none above 2 of 9**, no concentration line.
- Final paid run `20260821_030722_4344` (`hypedigitaly-fresh`, 9 carousels, `--budget 15`): exit 1 (partial-success) · 38 m 45 s · **$7.77** · 7 delivered / 2 gauntlet-blocked · 6 distinct styles, none > 3 · `counter`/`copy_language`/`source_language`/`cover_pick`/per-row `compressed`+`translated` on all nine `meta.yaml` · cover pick 9/9 non-degraded · grounds at value extremes, sd ≤ 2.0, 2048 px (drift script). **Open finding (operator decision needed, not fixed here):** the gauntlet's critics fail at OpenRouter ("Request body could not be parsed as JSON") on decks with ≥ 8 frames at 2K — ≈ 60 MB of base64 in one body — so 6 of 9 decks shipped unjudged; options and a recommendation (Kie result URLs instead of base64, amending FR-40) are in the N closeout.

## Reviewer notes

- PRDs are amended BEFORE code in every session (D15); `prds/00-overview.md` amendment log has one entry per decision.
- `AGENTS.md` is a hardlink of `CLAUDE.md` (rebuilt each session; `cmp` identical).
- Every `prompts/*.md` has a byte-identical built-in twin; `plans/tools/splice_builtin_twin.py` (N) does the copy and asserts it.
- Known gaps carried forward are listed under "What the next session must do first" in `plans/SESSION-N-CLOSEOUT.md`
  (a live translate run has not happened yet — this week's pool was all-English).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
