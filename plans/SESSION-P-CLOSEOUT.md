# SESSION P — CLOSEOUT (render-quality round — v2.9.0, D65)

**Date:** 2026-08-21/22 · **Plan:** `plans/SESSION-P-DESIGN.md`, executed top to bottom, all six waves.
**Branch:** `session-p-render-quality` (parent: O's `41e9b1a` on `session-o-codex-pivot`). J → K → L → M → N → O → P are unmerged to `main` and merge together. Rollback tag from O still stands: **`pre-codex-pivot`** = `b6eac4d`.
**Commits (12):** `d03effa` PRDs · `bf30f91` W0 guards · `3b24134` W0 tests + root-cause fixes · `c8232c0` W1 colour/alpha · `14dc7a6` critic effort · `ab6c653` W3 purge · `9e922b7` W4 style-test · `60de562` W2 critics · `cb2db1d` docs · `1f67d70` W5 paste · `9ce3f4a` NAVIGATION · `92b1a09` W2 live fix.
**Suite:** 2020 → **2191 passed, 0 failed** (+171: 68 contract guards, 56 screenshot paste, 30 style-test, 6 marks/critics, 11 assorted).
**Growth:** production 41,550 → **45,472 (+3,922)** — `outputs/screenshot_paste.py` +470 (new), `generate/carousel.py` +612, `contract_guard.py` +1,145 (new), `outputs/alpha_halo.py` +292 (new), `sources/slide_intel.py` +219, `prompts_engine.py` +224, `cli.py` +116, `runner.py` +137, `gauntlet.py` +60, `styles.py` +52, `models.py` +46, `plan.py` +32, `config.py` +42, `contracts.py` +27, `outputs/__init__.py` +45, `gallery.py` +32, `copywrite.py` +124, others +9. No docstring, comment or error message trimmed. Registry PROSE was cut deliberately (below).
**Live spend:** every LLM call and every render **$0.00** (subscription); Virlo metering only. Two full 17-deck runs.

## What shipped

- **FR-362/363 contract guards** (`hypesocials/contract_guard.py`, new): nine pure guards over the finished `panel_map` at ONE seam (`copywrite._guarded`) covering all four copy walks — digit repair + drift, row realignment, line dedupe, identity scrub, truncation gate, coverage assertion, watermark-as-chrome, caption scrub, caption voice tag. Packaging now BLOCKS an incomplete carousel (`incomplete_deck`) that used to ship as `success`.
- **FR-364/365 colour + params**: a shared `colour_rendering` row PREPENDED in `style_dna()` (reaches renderer + brief critic + system critic identically); codex `quality: "high"`; new `outputs/alpha_halo.py` edge-band guard with one resubmit then flatten.
- **FR-366/367 critics**: marks fixed at the root (backwards author test, cropped-patch-only REQUIRED, per-frame demand), `platform_chrome` narrowed, brief critic gains when-unsure-PASS + content-fidelity rules (numerals, duplication, ordinals, wordless), system critic told measurements are not its subject, effort `xhigh → high`.
- **FR-368 empty elements**: 9,955 chars of greeking and restatement out of `styles.yaml`; new CRAFT code `empty_element`.
- **FR-369 `--style-test`**: 17 decks, one per style, one pinned post, no history written, `output/latest` untouched.
- **FR-370 screenshot paste**: slide-intel detection, reserved plate, local post-render Pillow composite before the critics look, identity skip, `plates/` backups, full receipts.
- **Docs:** PRDs v2.9.0 (00/10/20/30/40/50), CLAUDE.md glossary + stack, NAVIGATION.md §3/§5/§9/§11 + the wave blocks, AGENTS.md re-synced (it had silently drifted to v2.7.0).

## Three root causes found that the plan did not know about

1. **The engine was MANUFACTURING the OCR corruption it was being blamed for.** `ocr_repair._IN_UPPER` maps `1→I`, `0→O`, `5→S` inside any all-caps token of 3+ chars, and `_is_acronym` accepted `16GB`, `146K`, `10X`, `70B`, `128GB`. So correct Virlo panels became `I6GB`/`I46K`/`IOX`/`7OB` **at admission** and rendered that way — FR-362's guard 1 was built to undo our own damage. A digit run followed by a known unit is now a measurement and keeps its digits; a genuine mis-read (`0PENAI`) still repairs. Found by the test agent writing the fixture, not by the audit.
2. **`subject_marks` vouched for a watermark using its own row**, so the `EVOLVING AI` hero-line class was only ever stripped when the watermark was the row's ENTIRE text. The corpus is per LINE now.
3. **A moved decimal separator read as digit drift** and, on a translated row (never restorable to source bytes), shipped the slide WORDLESS. `1,5 %` and `1.5%` are one measurement.

## The live run, and the regression it caught

Two 17-deck runs on one pinned post, both $0.

| | run 1 `kfb6` | run 2 `3pa5` |
|---|---|---|
| delivered | 6 of 17 | **11 of 17** |
| `forbidden_mark` | 21 | **0** |
| wall clock | 1,317 s | 1,124 s |

**Run 1 blocked 11 decks on "Unrequested Claude logo"** — on slides 4–7 of a Claude-topic deck whose cover legitimately carries that logo with a cropped patch. My own W2 per-frame marks change caused it: telling the critic which frame OWES a mark fixed the phantom `missing_mark`, but nothing told it that a mark on the REQUIRED list is sanctioned for the whole set. Slides 2–N chain off the cover, so the cover's logo carries through, and the critic read every one as unsanctioned — leakage tier, which blocks past `fail_action: degrade`. One paragraph in `critic_brief.md` (`92b1a09`) fixed it. **No test would have caught this; only the live run did.**

Run 2's six remaining blocks are all genuine and all in the classes W2 was written to catch: a fabricated benchmark value (`table shows unquoted value 52.9%`), a dropped one (`expected 57.9% is absent`), the same sentence printed twice on three decks, and hallucinated code/lines on a wordless frame. Blocking those is the system working.

**Measured colour (the operator's original complaint):** `icon-ledger-carousel`, which the audit found mottled in EVERY deck, now holds **4.3° of hue spread across 7 slides** — better than the 6° cream baseline in `styles.yaml`'s prior art, against 30° measured on saturated fields before. Discs render flat. `big-number-editorial` holds value to 0.007 across the deck (its 20° hue figure is a near-grey artifact and means nothing at that saturation).

**Barrier receipts, both runs:** `logs/trend_history.json` md5 byte-identical before and after; `output/latest.txt` still points at `20260821_121514_q745`. A style test costs no source material.

## Open for the operator

1. **Pick the styles.** THE deliverable: `output/20260821_234534_3pa5/gallery.html`, 11 styles rendered full on identical material. Blocked at the cover (1 slide each, so ~30 slides of render were never bought): `platform-showcase-card`, `meme-caricature-panels-teal`, `circuit-atlas-dark`, `terminal-mockup-deck`, `photo-poster-statement`. Blocked after a full deck: `anime-noir-statement`.
2. **The screenshot paste never fired, and the scoping question is real.** The pinned source's panels classified as `graphic`, correctly — they are designed layouts, not captured interfaces. But the deck's slide 3 is a 40-number benchmark table, which is exactly where the audit found 15 fabricated numbers, and exactly what an image model cannot redraw faithfully. FR-370 is scoped to "captured real interface"; the highest-value case may be "any dense data table". Widening `panel_kind` is a PRD amendment, not a code tweak. **Barrier W5's live canary is still owed** — it needs a topic whose source actually has screenshot panels.
3. **`style_layout` is still the top standing code** (8 in run 2, 46 in run 1). Sampled, they are legitimate — the model draws a flowchart where the style prescribes single-column rows, and drops the slide counter. Contract tier, so they degrade rather than block. If delivery matters more than layout fidelity, that is the next lever.
4. **`input_fidelity` does not exist on this proxy.** HTTP 400 on both image routes; shipping it per the plan would have failed every image-to-image render and burnt FR-317's resubmit on a guaranteed refusal. Held behind `_INPUT_FIDELITY_SUPPORTED = False`, one line to flip. PRD records the measurement.
5. **Prompt budget is genuinely tight.** W1's colour row cost enough trim budget to strip FR-340 off five styles' longest panels; W3's purge repaid it (worst cut 1,540 against a 1,600 ceiling that was never raised). There are 60 characters of slack. Anything added to a render template from here needs a measurement first.
6. **Caption voice is v1 = TAG ONLY** (`caption_voice_review`). Rewriting a first-person creator caption into our voice is an FR-331 verbatim amendment and needs your decision.
7. Reels remain refused under codex — unchanged.

## Handoff

Next session reads this file first. `plans/SESSION-P-DESIGN.md` §9 lists the operator questions this session was told not to block on; items 1, 2 and 6 above are the live ones. The gallery is the thing to look at.
