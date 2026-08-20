# SESSION J — CLOSEOUT (contracts & render correctness — v2.5.0, D59)

**Date:** 2026-08-20 · **Plan:** `plans/xmasterplan-render-quality-and-language.md` §7 "SESSION J" (Waves 0J, 1, 2, 8 — all executed)
**Branch:** `session-j-render-contracts` off `main` (`6f85a0c`), tree clean at Step 0
**Suite:** 1568 → **1598 passed, 0 failed** (+30 ids)
**Growth:** production 34,745 → **34,989 (+244)** · tests 32,260 → **33,025 (+765)**
**Live spend this session:** **$0** (`--preview-sources` only). No paid run — none scheduled for J (§1: first checkpoint is after Session L).

## Wave status

| Wave | What | Outcome |
|---|---|---|
| 0J | PRD: D59 + reservation table (D59–D63, FR-338…355), FR-338/339/340 new, FR-313 amended, PRD.html D59 card, CLAUDE.md glossary, AGENTS.md hardlink | ✅ |
| 1 | `{{counter_rule}}` slot (FR-338) · FR-339 registry scrub · critic + fix-sheet amendments | ✅ barrier found the headroom interlock (see §"Defects") |
| 2 | FR-340 empty-zone rule on both image templates · phantom 4:5 band ×7 · icon-ledger one-part row · **measured headroom pass** | ✅ 0 of 19 styles outside target |
| 8 | FR-313 metadata: `CounterSpec.rule`, `meta.yaml.counter` | ✅ |
| Tests J | 9 guards (FR-339, FR-340, FR-350 pre-check, FR-338 exclusivity) + tier-A table re-measure | ✅ all 7 real guards proven to FAIL on pre-D59 bytes |
| Acceptance | `run.bat --config hypedigitaly-fresh --carousels 9 --preview-sources --yes` | ✅ exit 0 · `registry v1 · 19 styles · sha 1eb11d3a · 12 usable here` · 9 topics eligible · $0 |

## What shipped

- **FR-338 `{{counter_rule}}`.** 41st `PLACEHOLDERS` name, allowlisted on `carousel_slide.md` only, OUT of `_TRUNCATION_ORDER` and `_STYLE_TRIO`. `prompts_engine.counter_rule(style, *, slide_counter)` — five arms: `None` style → `""`; declared `counter_slot` + counted → that zone's line via the new shared `_zone_line()` formatter (`_style_zones` now uses the same helper with its ordinal prefixed, so renderer and critic read identical words — pinned by `test_counter_rule.py`); declared + uncounted → `_NO_COUNTER_LINE`; no zone + counted → `_HOUSE_COUNTER_LINE` (`counter <value>: small, body family, top-right inside the safe area; no chip, no badge` — the FR-350 spine a session early); neither → `""`; override brief → `""`. Template paragraph at `carousel_slide.md:96-100` replaced by `COUNTER RULE (ignore if empty): {{counter_rule}}` + the outranks-STYLE_DNA sentence (+7 chars), twin mirrored. `generate/carousel.py` needed NO change — it already passes `slide_counter` into `build_context`.
- **FR-339 scrub.** 37 regex hits across 10 styles moved out of `typography`/`text_placement`/`visual_pacing` into the gated `counter_slot`/`brand_slot` zones' `text_treatment` (all 8 counter zones 135–192 chars, bar 200). −685 chars off the DNA that `carousel_slide.md:8` replicates on every slide. Non-counter uses of the guarded words re-worded with synonyms (circuit-atlas "chip rings" → node labels, hypelead list "chip" → numeral disc, type-scale rungs `chip 1x` → `smallest label 1x`). Authoring block gained the FR-339 bullet and the stale `:102` "appended to {{layout_zones}}" comment is fixed. Two dangling back-references in `build-log-mono`'s zones ("on that same chrome line", "on the signature's baseline") re-anchored to absolute positions because the counter zone now ships ALONE under `{{counter_rule}}`.
- **FR-340.** `carousel_slide.md:159-162` and `image_post.md:96-101` + twins: the "renders empty or as a non-text graphic element (a rule, a bar, a shape, negative space)" licence is gone; a zone with nothing quoted is LEFT OUT, never a bar/rule/block/placeholder; a repeating device exists once per quoted line and not at all when none is quoted. Seven phantom "bottom 12% (4:5 crop)" bands → "all text inside the central 80% of a 1:1 frame" (`grep 4:5` empty). `icon-ledger-carousel`: rows only where lines are quoted, headline-only cover draws no ledger, **a one-part line sets as the title alone — never repeated under itself** (defect 3), exclusions point at the positive rules; authoring block states the one-part case for every two-part row rule.
- **FR-313 metadata.** `CounterSpec.rule: str = ""` (defaulted; frozen dataclass, so the four accept sites use `dataclasses.replace`) with the names `denominator | positional | leading_offset | constant_offset` as public constants. `AssetRecord.counter: dict | None` → `meta.yaml`: `{detected, rule, pattern, sample}` on every bound carousel (`detected: false` + empties when uncounted), `null` on images/reels/override briefs. Gate = `entry.source_post_id`, the plan's own "bound" fact. `_record_dict` needed no change.
- **Critic side.** `critic_system.md` `style_consistency` + `style_layout` clauses per FR-338; `gauntlet_fix.md`: `counter_value` `*`/`chip`/`full_frame` re-worded so none can read as "draw a chip", new `style_consistency | chip` row (40 rows), `counter_placement | chip` no longer points at "the chip STYLE_DNA describes" (it no longer does); `gauntlet.py` `_REMEDIES["counter_value"]` synced.

## Defects found and fixed that the plan did not contain

1. **The plan's headroom arithmetic was wrong, and Wave 1 proved it at the barrier.** "The DNA scrub pays for the template delta" assumed the scrub REMOVES chars. It MOVES them — from the cuttable `style_dna` into the uncuttable `{{counter_rule}}` slot: 203–279 chars on the 8 zone styles, 86 on the other 11 (+2,727 registry-wide, none of it cuttable). After Wave 1 alone, six styles hard-truncated INTO the every-legible-character safety rule at the 1,500-char panel extreme and `anime-noir-statement` sat at 1,640 over the 1,600 tier-A ceiling; Wave 2's FR-340 paragraph (+132 uncuttable) would have made it 10 of 19. **Resolution:** Wave 2 was given a measured target (tier-A cut ≤ 1,540; ≥ 60 chars of slack past the safety marker at tier B) and a scratch measuring script; the room came from deduplicating each style's `exclusions` against bans the template already states on every slide (−2,690 registry-wide; style-specific clauses kept, generic restatement dropped). Result: worst tier-A cut `icon-ledger-carousel` 1,499 (was `anime-noir` 1,554 before the session), ceiling 1,600 unchanged, 17 of 19 still hard-truncate at tier B (unchanged count) but every one now loses only droppable tail.
2. **The fix-sheet PRECEDENCE block preserved an invented chip.** "everything else stays as rendered, the position badge and every sanctioned mark included" is emitted into EVERY fix suffix, so any re-render that did not name `counter_value` was told to keep the invented chip — the exact ping-pong that killed a deck in `4a0q`. Narrowed to "**a quoted** position badge" in the file, the `gauntlet.PRECEDENCE_BLOCK` twin and the F7-C test pin. Side effect: `fix_reserve()` 1,523 → 1,528, so the effective body budget is **18,272** (was 18,277; `MAX_PROMPT_CHARS` 19,800 unchanged) — re-pinned in `test_prompt_fit.py` and stated in FR-338.
3. **`carousel_anchor_instruction.md:17-19` carried the same FR-340 licence** ("renders empty or as a non-text graphic") and ships on every chained slide — outside the plan's "both image render templates" wording. Fixed (+16 chars, twin mirrored, FR-340 text amended, guard test covers it).
4. **`icon-ledger-carousel`'s critic-only body zone** said "one grey description line under the title" unconditionally — the critic could fail a CORRECT one-part row as `style_layout`. Now "… only where the quoted line has a second part". (`{{layout_zones}}` never reaches the slide renderer, so this could not cause defect 3 itself.)
5. **`test_gauntlet.py` pinned the sheet at 39 rows** — re-based to 40 with the D59 reason in the docstring.
6. **`prompts_engine._EXCL`**, a dead pre-F20 assembly constant with no callers, still held the old licence — re-worded to FR-340 shape and pinned unreachable by the new parity test (`assert not any(pe._EXCL in text for text in pe._BUILT_INS.values())`). Deleting the five dead constants (`_FRAME`, `_LOCK`, `_REFS`, `_EXCL`, `_EXCL_OBSERVED`) is owed on design grounds — not done here (out of scope).
7. **Conductor process defect, caught before damage:** the first version of the twin-mirroring script rewrote `prompts_engine.py` from CRLF to LF; the file was reverted from git before any agent touched it and the script fixed (`newline="\r\n"`). Every mirrored twin was verified byte-identical by `test_template_parity.py`.

## Deviations accepted (with reasons)

1. **`worst_slide()` was NOT given a `counter_rule` stamp.** Plan §7 "Tests J" said every parametrised case would raise `UnresolvedPlaceholderError` otherwise. False: the fixture already passes `slide_counter="07 / 12"` into `build_context`, which fills the slot; a second hand-written value would be a second implementation. Docstring says so.
2. **`test_prompt_fit.py:448-449` untouched** (as ordered): `set(cuts) <= {"render_prompt", "style_dna"}` still holds — `counter_rule` never enters the trio.
3. **"Net negative chars" for the 4:5 removal was wrong** — the replacement sentence is longer at every site (+110 total). The exclusions dedup absorbed it.
4. **Compensating trims on `anime-noir` / `quiet-luxury` ×2 landed at −97 / −123**, not ≈170 — further cuts would have removed a device or a number; the measured outcome is far past target anyway (`anime-noir` 1,767 → 1,416 at tier A).
5. **The meme-caricature pair now trims at tier A (0 → 234 / 217)** — purely the 86-char house-default counter line on a counted fixture deck; correct by design (a no-zone style used to get no placement at all).
6. **`letterpress` `Chips:` (plural) escapes the guard regex's `\bchip\b`** — scrubbed anyway; if the guard should also catch plurals, widen it in `test_styles.py` (one token).
7. **Optional item skipped:** the three D15 rulings carried from Session H (`SESSION-I-CLOSEOUT.md:87`: `copywriter_system` contract placeholders, FR-73 meta shape, FR-263 "three" vs ten role templates) remain owed.

## Growth attribution (rule 5)

**Production +244:** `prompts_engine.py` +127 (engine code +110: `_counter_rule`, `counter_rule`, `_zone_line`, `_HOUSE_COUNTER_LINE`, allowlist, `build_context`, docstrings; +17 from the mirrored twins growing) · `models.py` +41 (`PLACEHOLDERS` +22, `AssetRecord.counter` +19) · `generate/carousel.py` +36 (`_counter_meta`, `package()` row) · `sources/slide_intel.py` +36 (rule constants, `CounterSpec.rule`, four `replace` sites) · `generate/contracts.py` +9 (docstring) · `gauntlet.py` ±0 (two strings re-worded).
**Tests +765:** NEW `test_counter_rule.py` · `test_styles.py` +189 · `test_template_parity.py` +164 · `test_carousel.py` ~+120 · `test_slide_intel.py` ~+55 · `test_prompt_fit.py` docstring re-base · `test_gauntlet.py` +10 · `test_prompts_engine.py` +7.
**Non-code:** `prompts/styles.yaml` −2,193 chars net (scrub −685 DNA, exclusions −2,690, headroom + 4:5 + authoring block +558 comment) · `carousel_slide.md` +139 · `image_post.md` +71 · `carousel_anchor_instruction.md` +16 · `critic_system.md` +622 · `gauntlet_fix.md` +345 · `prompts/README.md` · five PRDs + `PRD.html` · `CLAUDE.md`/`AGENTS.md` · `NAVIGATION.md` §3/§11/§13.
No docstring, comment or error message was shortened anywhere.

## PRD conflicts

None outstanding. FR-338 and FR-340 were amended in-session for items 2–3 above (D15: PRD first, then code). Pre-existing, still owed (carried from Sessions H and I): the three D15 rulings in deviation 7.

## ⚠️ What SESSION K must do first

1. Read this file, then plan §3 (the seven styles must pass what K builds) and §7 "SESSION K".
2. **Budget reality for K's validators and prose:** every uncuttable char added to a dense style costs 1:1 at tier B. Run the headroom script before and after any registry prose change — `tests/test_prompt_fit.py` enforces the 1,600 ceiling and the safety-marker survival; the worst style has 101 chars of tier-A slack (`icon-ledger-carousel`), the tightest tier-B slack is `social-quote-card` at 135. **Session L's seven new styles must be measured one at a time against the same bars.**
3. `build-log-mono`'s `render_prompt` still says "a position chip top-right, a signature slot at the foot" unconditionally — `render_prompt` is outside FR-339's three fields but ships as STYLE_DNA on every slide; FR-338's "outranks every chip…STYLE_DNA describes" line is the designed mitigation. Worth a `when one is quoted` clause in K's prose pass. Near-misses the guard will never catch: `platform-showcase-card` `Footer:` type spec (duplicate of its `brand_slot`), `social-quote-card` `Handle:`, `icon-ledger` `footer strip` sentences — K retires the footer strip anyway (Wave 4a rule 1).
4. K's FR-347 hex validator: `mono-cutout-editorial` (L) needs zero accents legal; `letterpress-teal` settles the owed Session I ruling (teal on cream, cover and body).
5. The `_REMEDIES` dict in `gauntlet.py` mirrors only the `*` rows of `gauntlet_fix.md` — any future `*`-row wording change needs both.

## Follow-ups (none blocking)

1. Delete the five dead pre-F20 assembly constants in `prompts_engine.py` (`:1680-1715`) — §3a design ground; pinned unreachable meanwhile.
2. `prompts/README.md` still describes `{{layout_zones}}`' brand-slot gating but not the counter gate in the same row — cosmetic.
3. `pytest-randomly` is not installed; "green in randomized order" could not be re-checked this session (all new tests are pure reads).
4. Artifact republish of `PRD.html` (v2.5.0) not done this session — the canonical URL procedure is in the `hypesocials-prd-artifact` memory; it keeps dying on this account.
5. Carried: ASSIGN receipt cannot distinguish `-teal` variants (19-col fit); dropped-row gallery chip cosmetics; `meme-caricature-panels` dead 110-char headline cap; §3a deep-module reviews (`copywrite.py` 3,574 · `budget.py` 1,260 · `prompts_engine.py` now 3,972 lines · `menu.py` 819 · `style_match.py` 661).
