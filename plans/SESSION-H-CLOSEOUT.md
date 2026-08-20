# SESSION H — CLOSEOUT (compress mode + style doubling-down, v2.3.0 D54/D55)

**Date:** 2026-08-20 · **Plan:** `plans/xmasterplan-compress-mode-and-style-doubledown.md` (all five waves executed)
**Suite:** 1389 → **1481 passed, 0 failed** (+92 ids) · **Live spend this session:** $0.31 (preview-analysis) + $1.43 (paid run `output/20260820_030911_pls7`) = **$1.74**
**Growth:** production 31,728 → **33,114 (+1,386)** · tests 28,055 → **30,401 (+2,346)**

## Wave status — all green

| Wave | What | Outcome |
|---|---|---|
| W1 | PRD amendments (D54+D55, FR-331/332/333, 6 files) | ✅ 3 fix rounds (see deviations) — diagram rebuilt, drop taxonomy repaired, counts synced |
| W2 | Code: C-a config/CLI/menu · C-b copywrite core · C-c prompts | ✅ barrier: 11 failed/1381 passed, every failure a categorized W4-owed pin; $0 loads clean |
| W3 | S1 new style `quiet-luxury-night-photoreal` · S2 4-key `styles.enabled` | ✅ registry 9 styles, validate() 0 errors under all shipped configs, 3 effective carousel styles |
| W4 | Tests + conductor merges | ✅ 1481/0; CLAUDE.md glossary carve-outs + NAVIGATION.md refreshed |
| W5 | Live ladder | ✅ all five steps (below) |

## What shipped

- **`carousel_copy_mode: verbatim | compress`** (config Literal, default verbatim; three brand configs pin compress), `--copy-mode` CLI flag (flag-over-file), six-step wizard (`copy_mode` step joins `_live_steps`, drops out when carousels == 0).
- **Compress copy path** (`copywrite.py` +672): `_compress_wanted` partition in `_write_group`; `_call_compress` renders new `copy_compress_system.md` (byte-pinned built-in twin; `compress_panels` allowlisted there and nowhere else) against `models.CopyCompressed`; **`_compressed_deck` produces `slide_texts` + `panel_map` in ONE walk** (the gauntlet-consistency invariant, pinned end-to-end by `test_gauntlet_dryrun.py`). Engine backstops in order: blocklist strip fail-closed → `_social_mark` blank + `compress_scrub` → word-boundary trim `text_trimmed` → source-empty discard `compress_invented_text`. Failed call → `_mapped_fallback` verbatim deck + `copy_degraded`. `_verify` unchanged (compressed ships `quoted=()`).
- **Receipts:** meta `copy_mode`, panel_map rows `compressed: true` / empty `ref_label` / `source_text_original`; FR-309 gallery labels ("compressed from N chars" header + per-tile chip) and compress-aware receipt; mode-aware console surfaces (COPY stage line, previews header + `compressed` row, preflight FR-333 hint, FR-297c compress receipt) — every verbatim wording byte-identical.
- **Humanizer** vendored verbatim from github.com/blader/humanizer `main` (MIT, 30,409 B, byte-checked; reference-only — engine never loads it); the distilled ~14-pattern on-image subset lives in the template.
- **9th style `quiet-luxury-night-photoreal`** (penthouse desk / night skyline, scene_fixed, minimal density, slide budget 160) — authored to the registry's measured DNA convergence (~1,750–1,800 chars) after a first draft blew the `test_prompt_fit.py` trio ceiling; final cut@700 = 1,504 (under the pinned worst).

## Deviations from the plan (all resolved in-session)

1. **W1 needed three rounds.** Round 1 missed the Mermaid rebuild, added `text_trimmed` as a fourth drop reason (it is a tag — taxonomy stays 3), mis-scoped the 1500 sanity ceiling to verbatim (it is an input guard in BOTH modes), and left stale TL;DR/count claims. Round 2/3 fixed those plus NFR-16/FR-300 (five → six inputs) and FR-181's roster (fourteen roles / nine global; humanizer named a non-role).
2. **FR-332's drafted placeholder contract wrongly listed `{{competitor_list}}`** — corrected by the conductor to the exact 8-name allowlist row (`competitor_list` stays locked to the topic filter; the strip reaches compress via `_strip_brands` + the blocklist audit).
3. **Plan gap — `models.PLACEHOLDERS` / `GLOBAL_TEMPLATES`:** the vocabulary gate runs before the allowlist, so without `compress_panels` in PLACEHOLDERS every compress render would silently fall back to the built-in (FR-181 hot-loading dead). Found by C-c, landed by C-b mid-flight.
4. **Plan gap — `gallery.py` was in nobody's file set** while W1 amended FR-309 labels into the PRD. Caught at the W4 barrier (test-automator stopped rather than fake it); C-b implemented (+71) incl. the `_receipt_html` "Quoted post" mislabel fix; previews `_rows` gained a filled-column separator guard (+15; the "compressed" label had collided as `compressedp1` — a rename was blocked by an existing pin, so the real defect was fixed).
5. **Plan gap — `tests/test_prompt_fit.py`** pins the registry count/byte-budget and was absent from the plan's W4 list (found by S1).
6. **Menu counter denominator** (C-a, documented in `_live_steps`): on a carousel-free run the first two counters print /6 and the rest /5 — FR-300 amended to make the live-list shrink the compliant reading.
7. **`vision_check.py:71` is a prompt payload, not a comment** — left byte-identical (regression constraint outranks the plan's wording touch); explanatory comment added above it.
8. **`source_text_original` = `offer.panels_original`** (pre-strip, same as verbatim rows) — cross-mode column consistency chosen over a post-strip reading of FR-304(d).

## W5 live ladder evidence

1. `pytest` — **1481/0** (three independent runs).
2. `$0`: `--list-monitors` (3 monitors) and `--preview-sources --config hypedigitaly` — registry `9 styles · 8 usable here`, no exit 2, funnel clean.
3. `--preview-analysis --config hypedigitaly` ($0.31): 3 styles over 4 topics; compressed slides in the source language within min(config, style) budgets; no handles/URLs; `compressed <post>` receipts render. **Observed:** the model overshoots the budget on list-heavy panels — the engine backstop trimmed 2 of 4 creatives mid-sentence (`text_trimmed`); correct per FR-331 but a prompt-tuning follow-up (below).
4. **Paid run `20260820_030911_pls7`** ($1.43 of $2.00, 11m51s, exit 1 partial-success — gauntlet enabled + `fail_action: degrade`, the operator's F10 ruling of 2026-08-20):
   - `Ig_..._02` (**quiet-luxury-night-photoreal — the new style's first live deck**): DELIVERED degraded (`gauntlet_degraded` on style_layout). meta `copy_mode: compress`; 6 rows 1:1; originals 41–238 → shipped 40–138 (≤160); no `copy_not_verbatim`. The compressed caption came back empty (source post has NO caption) → `compress_caption_rejected` → FR-99/FR-307 self-caption fallback fired as designed.
   - `Li_..._01` (anime-noir): BLOCKED on `invented_text` s2/s3 — both are `contains_handle_or_url`-dropped wordless frames (originals 413/260 chars carrying marks), i.e. the pre-existing render-model-invents-filler mode on wordless frames, correctly caught. Rows: originals 30–490 → shipped ≤178 (≤180).
   - **Zero `translated`, zero `identity_leak`, zero `missing_text`** (the one-walk stop-condition) across both reports. Gallery: header + per-tile "compressed from N chars" labels and the "Compressed from post" receipt all render; blocked deck kept on disk with BLOCKED.txt.
5. This closeout.

## Growth attribution (rule 5)

Production +1,386: copywrite.py +672 · prompts_engine.py +356 · models.py +74 · menu.py +73 · outputs/gallery.py +71 · previews.py +34 · runner.py +24 · cli.py +18 · preflight.py +16 · config.py +13 · vision_check.py +13 · budget.py +10 · generate/__init__.py +8 · generate/carousel.py +4. Non-code: `prompts/copy_compress_system.md` +297 (new) · `prompts/humanizer_skill.md` +478 (vendored) · `prompts/styles.yaml` +85 · configs +75 · `hypesocials/wizard_help.md` +42 · README.md rows. Tests +2,346 across ten suites. No docstring, comment or error message shortened anywhere.

## PRD conflicts

None outstanding from this session (items 1–2 above were fixed in-wave, PRDs first per D15). **Pre-existing drift observed, NOT touched (needs its own D15 ruling):** (a) `prds/50-promptcraft.md:168` lists `{{source_panels}}`/`{{topic_texts}}`/`{{competitor_list}}` in copywriter_system's contract — none are in the engine allowlist; (b) FR-73's "caption + hashtags" meta.yaml claim vs the actual asset meta shape (no caption key — pre-dates this session, verified against run `2ard`).

## Follow-ups (none blocking)

1. **Compression overshoot:** the copy model exceeds per-panel budgets on list-heavy panels and the engine backstop trims mid-sentence (`text_trimmed` on 2/4 preview creatives; 0 on the paid run). Candidate: state the budget more aggressively per-panel in `compress_panels`, or an in-call retry.
2. **Dropped-row chip cosmetics:** a `contains_handle_or_url`-dropped row still carries `compressed: true` + a long `source_text_original`, so its gallery chip reads "compressed from 413 chars" over a wordless tile. Consider `compressed: false` on dropped rows or a "dropped (marks)" chip.
3. **Source-tile text** (C-b observation, pinned by `test_gallery.py`): a compressed tile shows the SHIPPED string under the `source ·` chip; showing the creator's original instead is a deliberate FR-309 shape change if wanted.
4. **§3a deep-module reviews owed:** copywrite.py 3,574 and menu.py 819 lines.
5. **Engine-side same-script language heuristic** (plan risk 1) — still prompt-only; the paid run showed zero `translated`.
6. CLAUDE.md rule-5 history table stops at 14,176 — session closeouts carry the growth record since; consider a re-base line.
