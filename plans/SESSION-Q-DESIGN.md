# SESSION Q — Visual-identity round: accent, marks, counter, scenes, emphasis, portrait, visual paste, matrix (v2.10.0, D66)

**Status:** PLANNED, not started. Written 2026-08-22 from the SESSION P closeout, a fresh re-read of run
`output/20260821_234534_3pa5` (17-style test), a 12-question operator grill, three read-only code sweeps and
a three-reviewer critique (architecture, python feasibility, prompt/registry feasibility — every finding is
folded in below; where a reviewer measured a number, the number is theirs).
**Load this file in a fresh session and execute top to bottom.** Also read first: `CLAUDE.md`,
`plans/SESSION-P-CLOSEOUT.md`, and (skim) `plans/EXECUTION-ORDER.md` for barrier discipline.

**Operator decisions already taken (do NOT re-ask) — the grill of 2026-08-22:**
1. **Accent colour:** TEST three candidates side by side — A deep teal (the existing `#0A7F78`), B emerald
   `#059669`, C indigo `#4F46E5` — and the session RECOMMENDS the winner on UX/UI/graphic grounds with a
   written rationale. The near-neon teals `#0FCFC4`/`#57E6DC`/`#8BF2E9` leave render use permanently.
2. **One logo per slide, the style's zone decides WHERE** (option B). A second rendition is a critic defect
   that buys a re-render.
3. **Paste EVERY non-text visual** from the source slide as exact pixels (option C — screenshot, table, chart,
   illustration, photo). The source's own branding, watermarks and creator faces are still cut out or the
   plate is skipped. Live canaries on several real posts that contain screenshots/tables are owed.
4. **Photographic styles: same world, new scene each slide** (option A). Slide 1 stays the style/mood/type
   reference; every later slide gets a fresh setting and camera angle. Graphic styles keep chaining.
5. **Emphasis words: the copy call names them** (option A): 1–3 per slide, kinds restricted to product/model
   name, company name, number, ONE strong adjective; verbatim text untouched; renderer lights them with the
   style's accent device; critic checks (checks — not blocks).
6. **Portrait carousels:** LinkedIn 4:5, Instagram 4:5, TikTok 9:16 (option A). One render, local crop/pad.
7. **Matrix:** 10 source kinds × all 26 styles, 4:5, ~260 decks, $0, pre-sorted gallery + per-style score
   (raised from 5 kinds by the operator on 2026-08-22).
8. **Counter:** the MODEL renders it — much stronger instruction, head of every slide prompt; a missing
   counter keeps buying a re-render. NOT drawn by code.
9. **Duplicate line → `duplicate_text`, contract tier** (re-render, then ship flagged), not leakage.
10. **Compress protects facts:** numbers, units, product/company names are never cut; if they cannot fit, the
    row ships longer (verbatim) rather than lose a fact.
11. **Style test shortens once per source post** to the smallest budget in the matrix and reuses it.
12. **Order:** visual fixes → portrait → paste-everything + canaries → matrix + recommendations.

**Branch protocol:** branch off `session-p-render-quality` head as `session-q-visual-identity`; commit the
clean state FIRST. Parent chain J→K→L→M→N→O→P unmerged to `main`, merge together. Rollback tag from O
still stands: `pre-codex-pivot` = `b6eac4d`.

**Money & quota:** every LLM call and render under the Codex subscription — $0 metered. The real
constraints: (a) the proxy's daily image quota — this plan orders ~350 decks / ~2,400 renders across its
barriers (W2 canary 17 + accent runs 3×17 + W3 ~6 + W4 3×4 + W5 10×26); spread them over the sessions as
written, never back-to-back on one day; (b) **Virlo is metered** — every run Collects afresh; (c) wall clock
(`3pa5`: 17 decks in 1,124 s; `_STYLE_TEST_DEADLINE_MIN = 240`, `cli.py:69`). A `--pin-post` refusal happens
AFTER Collect, so it is "Virlo spent, $0 renders", and the console must say so.

---

## 0. Context — the evidence

### 0.1 What the 3pa5 re-read found (beyond the P closeout)

- **Counter absence is the #1 defect by an order of magnitude.** Of ~330 critic findings across the 11
  delivered decks, ~190 are "the position badge is absent" (`counter_value` 95 + `style_layout` ~80 + ~12
  "slide-position marker absent"). Only 4 of 11 covers show `1/7`. 6 of 17 enabled styles fall through to
  the 84-char HOUSE arm (`prompts_engine.py:1377`); the `{{counter_rule}}` slot sits at the ~53% mark of the
  slide template (`prompts/gpt-image-2/carousel_slide.md:97`), AFTER the panel-text paragraphs — and the
  FORMAT block at the very top says the slide number "is never lettered, numbered, badged or drawn anywhere
  inside the picture" (`:1-6`), a head-on contradiction the model reads first.
- **3 of 6 blocks are the same small defect at the top tier.** "Its most powerful model yet." printed twice
  on the cover of `platform-showcase-card`, `meme-caricature-panels-teal`, `circuit-atlas-dark` → coded
  `invented_text` (`critic_brief.md:154-156` DUPLICATION rule) → `LEAKAGE_CODES` (`gauntlet.py:155-156`) →
  hard block past `fail_action: degrade`, after the cover pre-gate's single re-render.
- **The style test was not on identical text.** Compress runs once per GROUP but prints one section per
  creative at that creative's own `min(text_budgets.slide, style.max_onimage_chars.slide)` ceiling
  (`copywrite.py:2485-2565`, `:2552`), so slide 3 shipped in FIVE versions (824 verbatim on
  `anime-noir-statement` / 154 / 128 / 101 / 78 chars). The 78-char styles kept 2 of 4 benchmark numbers.
- **The only deck allowed to draw the full table blocked on it** (`anime-noir`: `52.9%` invented, `57.9%`
  missing) — the table class is exactly what a model cannot redraw.
- **Logo twice on one slide** is structural: the template fixes ONE placement ("INSIDE the TEXT block,
  beside the panel title", `carousel_slide.md:70-73`) while four styles order a subject-derived hero object
  ("its subject taken from the cover's own content" — `neon-glass-dark:2327`, `build-log-mono:1069`,
  `icon-ledger-carousel:1156`; `aurora-white-deck:2501` says "its subject from the cover's own content") and
  four styles order the REAL mark into a style-owned device (neon header `:2264-2266`, icon-ledger circle
  `:1137`, aurora square `:2482`, `editorial-voxel` tile `:379`). `critic_brief.md:75-80` then sanctions a
  required mark "for this whole set", so a second copy is invisible to the brief critic. No rule anywhere
  says ONCE.
- **Brand teal is near-neon and hard-coded.** `#0FCFC4` on 9 registry lines, `#57E6DC` on 3 (header
  `styles.yaml:13-20`; `hypelead-brand-card` ALSO carries hexes inside `render_prompt` and
  `per_format_guidance`); config `hypelead.colors` carries four teals (`configs/hypedigitaly.yaml:265-271`).
  Saturated light cyan is where gpt-image-2 blooms and bands; the P colour lock fixed mottling, not hue.
- **Registry nits with named causes:** `aurora-white-deck` orders a filled deep-teal square per card
  (`:2433`, `:2445`, `:2493`) AND the real mark into it (`:2482`) AND "no legible content in it" (`:2505`) →
  teal-recoloured Claude mark + empty squares; `social-quote-card` draws a heart/bubble/arrow row by mandate
  (`:1265`, `:1281-1282`, `:1299`, `:1313`, `:1319`, `:1334`, `:1338`, `:1341`); `big-number-editorial` has no
  mark zone (`:1882-1895`) so the template's "beside the panel title" lands the logo mid-headline.
- **Live receipts of P's guards:** alpha halo fired 2× and repaired; `panel_kind: graphic` ×7 recorded in
  `source.yaml`; one system-critic call died on a proxy error and failed open.

### 0.2 Hard facts an executor needs (verified by three read-only sweeps + three reviews)

- **The Codex proxy IGNORES `size`**: every render landed 1254×1254 (60/60 in `output/2026082*`;
  `codex_images.py:39-41`, `preflight.py:713-737`). Portrait under subscription = square render + LOCAL
  reframe. Kie honours ratios natively but `4:5` is 1K-only (`profiles.py:48`; `9:16` stays 2K).
- **The ONE landing seam** for every carousel frame is `generate/carousel.py:1390-1469 _store()`: `:1437`
  `store_render` → `:1468 _paste` → `:1469 _alpha_guard` (recurses into `_store` on a resubmit, each pass
  downloading a FRESH file). Cover candidates do NOT pass through `_store` (`_store_candidates`, `:1186`);
  only the winner lands there. Single images store bare at `generate/__init__.py:544,689`.
- **Pillow is sanctioned in exactly three modules** (`outputs/screenshot_paste.py:33-37`). A reframe is a
  FOURTH, local, post-render, never-uploading use — a D48/D65 carve-out amendment. **It also reverses FR-98
  ("no local crop, pad, or geometric post-processing of any kind", `prds/10-pipeline.md:298`) and FR-94
  clause 3 ("never letterbox, stretch or crop", `:255`) — both v1.6.1 operator rulings; D66 re-decides them
  because "ship what comes back" now means "ship the wrong shape".**
- **`PLATE = (0.08, 0.20, 0.84, 0.58)`** is square-derived (`screenshot_paste.py:78-90`) and pinned literally
  (`tests/test_screenshot_paste.py:224`, `:557` "8% to 92%"). Its x-span 8–92% falls OUTSIDE a centre crop
  to 4:5 (which keeps 10–90% of the width).
- **"inside the central 80% of the 1:1 frame"** is word-for-word in all 26 `text_placement` rows and pinned
  THREE times: `tests/test_styles.py:2314, 2449-2466, 2603-2620`, `plans/tools/measure_one_style.py:41`
  (`SAFE_AREA`), and the authoring rule `styles.yaml:177-182`; `test_styles.py:1686-1705` asserts the bytes
  `4:5` appear NOWHERE in `styles.yaml`.
- **Prompt budget is linear:** 1 char of uncuttable template prose = 1 char of `cutA`. Worst style
  `hypelead-brand-card` cutA 1,540 vs ceiling 1,600 (`tests/test_prompt_fit.py:60-90`); min slackB 302
  (`neon-glass-dark`). `counter_rule`, `onimage_text`, `tool_marks`, `screenshot_plate`, `exclusions`,
  `list_treatment`, `slide_index`, `brief_directives` are UNCUTTABLE (`_TRUNCATION_ORDER`,
  `prompts_engine.py:110-130`) — cuttability is BY NAME, not by position; only the degenerate hard truncation
  (`_fit`, `:543`) eats the tail. An unlabelled slot costs 1 char when absent; a labelled one ~33–38 on EVERY
  slide. `gauntlet.fix_reserve()` is subtracted from the body budget, so new REMEDIES rows also raise cutA.
- **Templates exist twice**: `prompts/**/*.md` + byte-identical built-ins in `prompts_engine.py`, spliced by
  `plans/tools/splice_builtin_twin.py`, pinned by `tests/test_template_parity.py` (`SHIPPED_COUNT` at `:68`).
- **Defect-code tiers are a frozen partition** (`gauntlet.py:130-176`; `CONTRACT_CODES` is DERIVED as
  `(BRIEF − LEAKAGE) ∪ (SYSTEM − COSMETIC)`). A new code touches EXACTLY: the code tuple (`:130-147`), the
  "All twenty-one codes" comment (`:151`), `_PRECEDENCE` (`:236-242`) + `gauntlet_fix.md:54` ORDER line
  (byte-mirror), `_REMEDIES` (`:252-317`) + `gauntlet_fix.md` REMEDIES rows (≥ one `*` row per code), the
  critic template code list + its twin, `tests/test_gauntlet.py:371-402` (partition), **`:1562`
  (`len(sheet.order) == 21`) and `:1564` (`len(sheet.remedies) == 42`) — hard integer pins**,
  `test_gauntlet_dryrun.py:109`. `_OPTIONAL`, `_BUILT_IN_SHEET` and `_schema` DERIVE and need no edit.
  `_REMEDIES`' substitution set is `{zone}`, `{chars}`, `[ … ]` only — no `{detail}`.
- **`layout_zones.role` is NOT validated** (`styles.py:247-253`); unknown role → silently always-emitted
  (`prompts_engine.py:1477-1478`). `_style_zones` is called ONCE PER DECK by `contracts.py:269` — it has no
  frame number, so nothing per-frame may be gated there (that was FR-366's phantom-mark bug).
- **Branding block reaches SLIDE 1 ONLY under chaining** (`carousel.py:2209`); it is CUTTABLE.
- **`load_registry(dirs)` takes folders only and returns inside its loop** (`styles.py:148-191`); callers
  `validate()` separately at 5 sites (`menu.py:537`, `preflight.py:795`, `previews.py:143,407`,
  `runner.py:509`). `StyleRegistry.content_hash` hashes the FILE (`:191`; logged `runner.py:515`).
- **Copy wire schemas are generated from dataclasses** (`prompts_engine.json_schema_for`, `:1160-1189`):
  `list[list[str]]` and NESTED DATACLASSES work, `list[dict]` does not; every property is `required` with
  `additionalProperties: False` — a field the model omits is a whole-call failure unless parsed leniently.
  `_guarded` copies rows dict-wise (`contract_guard.py:855`) but writes back only `panel_map`/`slide_texts`
  (`copywrite.py:5049-5050`); the RENDER reads `CopySet` (`carousel.py:598`), so any new per-row field must
  be copied onto the copyset there. `guard_deck` skips wordless rows before any guard (`:864`).
- **On a bound deck the copy model never answers `slide_refs`** (`CopySelection` doc, `models.py:566-570`)
  and candidates are listed by REF LABEL (`_candidate_block`), not by our slide position; the compress /
  translate blocks list by source POSITION (`copywrite.py:2544-2552`).
- **`_compressed_deck` already holds the verbatim bytes**: `source = offer.panels[position-1]`
  (`copywrite.py:3311`, == what `_mapped_deck` ships) and `original = offer.panels_original[position-1]`
  (`:3312`, PRE-strip: still carries the creator's name and any competitor name the blocklist removed).
  `_auto` recomputes its row set from the ENTRY's budget (`:3560`) and `_auto_deck` discards lines for
  positions outside it (`:3670-3673`). `_Run` has no `style_test` field (`:887-940`).
- **Style test pins ONE post** at `plan.py:636-637` (the first carousel group's ordinary pick — a live Virlo
  ranking, NOT stable across runs); matrix size is hard-wired to `len(--styles)` at `cli.py:440,448`;
  `--styles` is checked key-by-key against the registry (FR-314) — there is no `all`; `assign_styles_fixed`
  cycles `keys[index % len]` (`styles.py:1096-1105`). The pin branch (`plan.py:592-598`) bypasses `_pick`
  AND every eligibility test.
- `MetaStyle.motion_profile` DEFAULTS to `"photographic"` (`models.py:519`) and `tests/test_carousel.py`'s
  `make_style` (`:389-414`) never sets it — EVERY existing carousel fixture is photographic. 8 registry styles
  are photographic (`styles.yaml:259, 585, 664, 924, 1635, 1719, 1796, 2100`); no carousel code reads it.
- `cover_pick.reason` is never rendered by design (`cover_pick.py:24-26`).
- `.claude/skills/hypesocials-run/` (`hs-deck-critic`, `hs-operator`) reference screenshot/counter language.

---

## 1. WAVE 0 — Foundations: PRDs, budget, pin-post, accent plumbing, probe. No registry prose edits.

**Shape:** flat-wave (a). Disjoint paths. Executors: `prompt-engineer` (PRDs; the slide-template budget
pass + twin), `python-pro` ×2 (A: accent override + neon config + measure tool; B: `--pin-post` + `--styles
all` + probe), `test-automator`.

1. **PRD amendments FIRST (D15)** — §8. Audit the writer's diff FR by FR before any code (the P lesson).
2. **Prompt-budget rebalance on `carousel_slide.md` (+ twin) — `prompt-engineer`. Free ≥ 1,400 chars of
   UNCUTTABLE prose, measured.** The reviewer's measured cut list (≈ 1,325 freed, harness in the scratchpad
   `…\scratchpad\prompts_q\gpt-image-2\carousel_slide.md` + `measure_all.py` — reproduce, do not trust):
   (a) TOOL MARKS "PLACEMENT IS FIXED" paragraph `:70-73` (298) → one 74-char line pointing at the MARK SLOT
   (−224); (b) the COUNTER RULE slot + its enforcement **`:97-101` (344, NOT `:97-102` — `:102` opens the
   never-shorten rule)** removed here (the head takes it) (−327); (c) `panel_text` label paragraph `:84-88`
   merged with "THIS INSTRUCTION'S OWN WORDS" `:116-121` into one ~530-char block (−250); (d) REFERENCES
   prose `:126-132` 594 → ~370 (−224); (e) "Source furniture the brief describes…" `:44-49` folded into the
   CONSTRAINTS platform-UI bullet (−280); (f) **FORMAT `:1-6` gains the bridge clause** "pacing: it is never
   lettered, badged or drawn inside the picture EXCEPT as the COUNTER line below orders" (+20). Also
   `carousel_slide.md:40` ("background … on a body slide, from the anchor") gains "except on a scene-free
   deck". Prove with a draft-template harness over all 26 styles: after W0 alone worst cutA ≈ 405; after the
   W2 additions (counter head ≤ 460 incl. zone line, MARK SLOT ≤ 450, emphasis ≤ 130, SCENE ≤ 150, accent row
   219, fix_reserve growth ~650) **worst cutA ≤ 1,450 and slackB ≥ 400** — those are the W0 barrier numbers.
   Nothing moves INTO `_TRUNCATION_ORDER`.
3. **Accent override (FR-371) — `python-pro` A:**
   - `config.py` `BrandingConfig.accent_override: AccentOverride | None` = `{hex: "#RRGGBB", name: "<word>"}`
     (hex validated like `colors`; name `[a-z][a-z -]{1,19}`); CLI `--accent HEX --accent-name WORD` (both or
     neither; CLI over file; `run.style_test` not required). Printed on the confirm screen as
     `accent override: emerald #059669` and on the `--yes` summary; `meta.yaml.accent_override`; gallery title
     suffix; the `style_registry` log line gains `accent_override` beside `content_hash`.
   - `styles.substitute_accent(registry, override) -> StyleRegistry` — PURE, **HEX-ONLY, no prose
     word-swap** (the reviewer listed 11 places a `teal→emerald` swap corrupts ground prose, two-stop
     gradients, `-teal` keys and ban lists). For every style: every saturated hex (`_saturated`) within
     `_HUE_FAMILY_DEGREES` of the teal anchor 177° on a NON-background palette line AND inside `render_prompt`
     / `per_format_guidance.*` / `list_mode.layout` / zone `text_treatment` (the `hypelead-brand-card` case) →
     `override.hex`; background-role lines untouched (`#061F1E`, `#DDF3F1` already excluded by `_saturated`).
     Brand profile `colors` teal family → `override.hex` likewise. `dataclasses.replace`, never in place.
     Two-stop gradients collapse to one hex (documented: the override is a TEST instrument; the winner is
     baked by hand in SESSION R).
   - **Seam: caller-side, AFTER `validate()`, at the five load sites** (`menu.py:537`, `preflight.py:795`,
     `previews.py:143,407`, `runner.py:509`), via one helper `styles.load_for_run(dirs, config)` that loads,
     validates the shipped registry (FR-295 as today), substitutes, then validates the SUBSTITUTED registry
     separately — an error there refuses the OVERRIDE (`--accent #… breaks <style>'s palette contract; run
     without it`, exit 2, $0), never the registry.
   - **One injected `accent_override` row** in `style_dna()` directly after the FR-364 colour row, only when
     an override is set (219 chars, byte-identical to renderer + brief + system critics):
     `accent_override: read every "teal" in the lines below as {name} — the one accent hue in this deck is
     {hex}. GROUND, SURFACE, DEPTH and SHADOW hexes are literal and do not move, whatever their name says.`
   - Invariants (tests): the shipped registry × each candidate validates clean (`errors == [] and warnings
     == []`) — the reviewer simulated it: no style straddles the 30° window and the only saturated grounds
     are 28–34° browns; `style_dna()` grows ≤ +40 chars (`hypelead-brand-card` +40 under "deep teal") —
     the W0 budget harness is run WITH the override applied; `test_styles.py:1394, 1977` gain substituted
     twins (not edits); `branding_block` prints the override.
4. **Neon retirement in CONFIG — `python-pro` A:** `configs/*.yaml` + `config.py:623 _default_profiles`
   `hypelead.colors`: DELETE `teal_bright`, `teal_mid`, `teal_light`; KEEP `teal_deep: "#0A7F78"`, `dark`,
   `offwhite` (key name kept — `test_config.py:140-144` pins it); `never_always` += `"no light or neon teal
   (#0FCFC4, #57E6DC, #8BF2E9)"`; `styles.py:538` authoring doc; one line on `sources/notion.py:192`
   (`profile.colors["accent"]` from Notion is ALSO substituted when an override is set). Tests that move:
   `tests/test_branding.py:623-652`, `test_carousel.py:854-890`, `test_prompts_engine.py:212,962`,
   `test_reel.py:420-455`, `test_console_inventory.py` (new confirm fact line, width-asserted `:311`),
   `test_menu.py`, `test_style_test_mode.py:174-283` ("touches nothing else"), `test_preflight.py`.
5. **`plans/tools/measure_one_style.py` — `python-pro` A:** `SAFE_AREA` constant follows W2's phrase; new
   PASS/FAIL lines: exactly one `mark_slot` zone (`text_treatment` ≤ 200), `scene_rotation` length ≥ 7 on
   photographic styles, `emphasis_device` ≤ 80; `--template-dir` option so a draft template can be measured
   (the W0.2 harness).
6. **`--pin-post ID[,ID…]` + `--styles all` (FR-381 half 1) — `python-pro` B:** CLI-only (`config.py`
   rejects a file value like `style_test`, `:1399-1407`); requires `--style-test`; CLI checks SHAPE only
   (non-empty, no duplicates). `plan.py:569` `pinned` becomes a list; the reuse branch (`:592-598`) indexes
   `pinned[carousel_group_index % len]`; the pin-set (`:636-637`) becomes "look each id up in the collected
   pool, in order"; **refusal lives in `plan.assign()` right after `_carousel_supply` (`:571`)** — before the
   Confirm gate and any render — with the truthful line `--pin-post <id> is not in this run's collected
   posts (Virlo already spent; $0 renders)`, exit 2. A pinned post skips the four eligibility tests by
   design; a pinned post with no panels (a video) logs `pinned_post_has_no_panels` and the plan refuses the
   same way. `--styles all` = the registry's 26 keys in file order (sentinel resolved at `cli.py:314-330`).
   `cli.py:440,448` become `carousel = len(styles) × len(pins)`, reuse ceiling likewise.
7. **Codex size probe — `python-pro` B:** `plans/tools/probe_codex_size.py` submits one $0 render with
   `size=1024x1536`, records the landed size in `plans/SESSION-Q-PROBES.md`. Honoured → W3's reframe is a
   no-op on codex and the note in §11 applies; ignored (expected) → W3 as written.

**Barrier W0:** suite green; the budget harness table committed under `plans/SESSION-Q-BUDGET.md` (26 rows ×
{today, after-W0, after-W0+W2-additions} with the override applied — worst cutA ≤ 1,450); probe recorded;
`--style-test --styles all --pin-post <id> --accent #059669 --accent-name emerald --preview-plan` prints the
matrix and the override line at $0 (Virlo only). Commit.

---

## 2. WAVE 1 — Copy contract: emphasis, fact protection, compress-once, new critic codes

**Shape:** flat-wave; ONE sequencing note — `prompts_engine.py` carries logic AND twins: python tasks land
first, then `prompt-engineer` splices (sub-barrier). Executors: `python-pro` ×2 (copy side / critic side,
disjoint files), `prompt-engineer`, `test-automator`.

### 2.1 Emphasis words (FR-375) — `python-pro` copy side — `models.py`, `copywrite.py`, `contract_guard.py`

- Answer shape: a nested dataclass `EmphasisRow(ref: str, words: list[str])`; `CopySelection`,
  `CopyCompressed`, `CopyTranslated` gain `emphasis: list[EmphasisRow]` — on the SELECTION walk `ref` is the
  candidate's ref label (`P3.panel.1`, the only thing the model is shown on a bound deck); on compress /
  translate `ref` is the source POSITION string (`"3"`). The engine resolves ref → our slide position
  through the panel map. **Parsed LENIENTLY**: missing/malformed field → `[]` per row + one
  `emphasis_unparsed` warning, NEVER a call failure. `CopySet.emphasis: list[list[str]]` (position-indexed,
  engine-built) is what the renderer reads; `_free_text_schema` (reels/briefs) gains it too (state it).
- All four walks write `panel_map[i]["emphasis"]` (auto: compress answer for spliced rows, selection answer
  for kept rows). `_guarded` copies `written.copyset.emphasis = [row.get("emphasis") or [] …]` beside
  `copywrite.py:5050`; `guard_deck` clears `row["emphasis"] = []` on wordless rows before its `continue`
  (`contract_guard.py:864`).
- **Guard 10 `guard_emphasis(row)`** — runs LAST (after 1–9 so a replaced row cannot orphan a word): keep
  only case-sensitive substrings of the FINAL `source_text`, cap 3, dedupe, drop whole-line matches; warning
  `emphasis_dropped`; never a tag. A second, SEPARATE re-check beside `_compress_field`'s trim backstop
  (`copywrite.py:3457`) — distinct function from the fact-aware trim below.
- `CopyProvenance` per-row `emphasis`; `AssetRecord.panel_map` row contract (`models.py:760-792`) documents
  the key; `gallery.py` underlines the emphasised words in the "ours" text column.

### 2.2 Fact protection (FR-377) — same `python-pro` copy side

- **`guard_facts(shipped, admitted, *, exclude) -> FactFinding`** in `contract_guard.py`, placed in the
  `guard_deck` ladder as **guard 1b, BEFORE guard 4 (identity scrub)** — the comparison base is the
  POST-strip admitted panel (`offer.panels[position-1]` / the row's pre-splice `source_text`), NEVER
  `source_text_original` (pre-strip: a creator handle or a stripped competitor name would read as a "lost
  name" and restore an un-scrubbed row). `exclude` = `identifiers ∪ marks ∪ run blocklist terms`, casefolded.
  Numeric side: `numeric_tokens(admitted)` each with a `digits_of`-equal counterpart in `shipped`
  (separator-tolerant). NAME side — the reviewer's predicate, tested over 544 real panels
  (`output/2026082*`): per LINE, `shouty = share of upper-case letters > 0.8`; per token
  `[A-Za-z][A-Za-z0-9'\-.]*` stripped of `.,`: skip `len < 3` or casefold in `exclude`; keep if any digit
  (`GPT-5.6`, `s3`); keep if `-` inside and capital-initial (`MBPP-Plus`); if `shouty` → skip (an ALL-CAPS
  line proves nothing); keep if any inner capital (`HumanEval`, `GitHub`); keep if capital-initial AND not
  sentence-initial AND not in `_STOP` (`The, This, Your, How, Step, Save, More, End, You, For, Of, To, …`).
  Counterpart = case-insensitive substring. `AI`/`CI`/`PR` fall out on `len < 3` — by design.
- **Outcome on a COMPRESSED / AUTO row that lost a fact — "long beats lossy":** ship the admitted verbatim
  panel (`text = source` in `_compressed_deck`, `copywrite.py:3311`; the row's pre-splice `source_text` in
  `_auto_deck`, `:3684`), `compressed: false`, `ref_label` restored, `fact_restored: true`; tag
  `copy_fact_lost` (`DegradationTag`, warning class, NOT in the FR-248 `llm_starved` set, `runner.py:2402`);
  console `copy_fact_lost: <asset> slide N — verbatim restored (lost: 57.9%, ExploitBench)`. On a TRANSLATED
  row (no restorable bytes): ship, tag, loud. `PANEL_SANITY_CHARS` 1500 stays the only wordless ceiling.
- **Fact-aware trim** (separate small function from the emphasis re-check): `_compress_field`'s word-boundary
  backstop (`copywrite.py:3456-3466`) is skipped when the cut would remove a numeric/NAME token —
  `copy_fact_kept_long` warning instead of `text_trimmed`.

### 2.3 Compress once per source post in a style test (FR-378) — same `python-pro` copy side

- `_Run.style_test: bool` threaded from `write_copy`. In `_write_group`, when set and ≥ 2 compress/auto
  entries bind the same `post_id`: `budget_min = min(entry slide budgets)`; `auto_rows` computed ONCE with
  `budget_min`; **the compress call is built with `entries=[representative]` only** (so `_sibling_list` and
  the schema tell the truth), and the payload dict is cloned onto every sibling; **the shared row set is
  THREADED into `_auto(…, over=auto_rows[asset_id])`** (default = today's recompute) so `_auto_deck` never
  discards the shared lines (`:3670-3673`); headline/caption are trimmed at `budget_min`'s headline budget
  too (state it — cover headlines byte-identical across the matrix). Receipts: sibling `panel_map`s
  byte-identical; one `style_test_copy_shared` event (post, budget, count). Outside style-test: byte-identical
  path. Estimator: one `copy_call` per group, unchanged.

### 2.4 Critic side: three codes + emphasis contract — `python-pro` critic side — `gauntlet.py`, `generate/contracts.py`, `generate/carousel.py` (contract builder only)

- **`duplicate_text`** (FR-376): `BRIEF_CODES` +=; not leakage/cosmetic → contract tier by derivation.
  `_PRECEDENCE` directly after `invented_text`. Remedy `*`: "Print each quoted line ONCE: remove every second
  copy of the same words from the {zone} area, under any label, heading or card." + a `full_frame` row.
- **`duplicate_mark`** (FR-372): `CRAFT_CODES` += (the `empty_element` precedent). `_PRECEDENCE` after
  `logo_fidelity`. Remedy: "Draw the sanctioned mark ONCE, in its MARK SLOT: remove every second rendition of
  it in the {zone} area - hero object, tile, square, avatar, device screen or glyph."
- **`emphasis_miss`** (FR-375): **`CRAFT_CODES`** (decision 5 says checks, not blocks; `gauntlet.py:129`:
  the brief vocabulary is "PRESENCE, never quality" — set-apart-ness is treatment). `_PRECEDENCE` after
  `duplicate_mark`. Remedy (no `{detail}` — not in the substitution set): "Set the words named on this
  frame's emphasis row apart in this style's accent device; every other word stays in the body treatment,
  and no letter changes." The craft critic's allowlist (`prompts_engine.py:344-360`) gains `expected_blocks`
  so it can read the `emphasis:` row — or, if that widens its world too far, the emphasis row is passed to
  craft alone via a narrow `{{emphasis_rows}}`; executor measures and picks, states why.
- `FrameContract.emphasis: tuple[str, ...]`; `contracts.frame_contract()` fills it; `_expected_blocks` emits
  `  emphasis: "Fable 5" · "fastest"` only when non-empty. `DeckContract.scene_free: bool` (W2 reads it).
- Update the "twenty-one" comment, `tests/test_gauntlet.py:371-402, 1019, 1077, 325-326, 1156, **1562
  (order == 24), 1564 (remedies == 42 + new rows)**`, `test_gauntlet_dryrun.py:109`, template parity.

### 2.5 Templates (`prompt-engineer`, AFTER 2.1/2.4; splices twins) — the reviewer's drafted text is the starting point

- `copywriter_system.md` (OUTPUT `:228-242` + a carve-out under `:244-246`: "`emphasis` is the ONE field here
  that carries text, not a label: its strings are copied out of the candidate lines the refs point at,
  character for character; every other field stays a ref"), `copy_compress_system.md` (OUTPUT `:279-291`),
  `copy_translate_system.md` (OUTPUT `:216-229`, "a substring of the TRANSLATED line"): the shared 383-char
  `emphasis` rule (position-indexed / ref-keyed, verbatim substring, kinds, "an empty list is a fine answer,
  and most slides deserve one").
- `copy_compress_system.md` rule 1 (`:85-93`): DELETE "one character over is a failure"; last sentence →
  "If the panel cannot survive the ceiling without losing a number, a unit, a product, a model or a company
  name, EXCEED the ceiling by the smallest amount that keeps every one of them. Rule 14 outranks this rule.
  A line that lost a fact to fit is discarded and the verbatim panel ships in its place." Rule 14
  (`:168-172`) += "the budget yields to a fact, never the other way round". HARD BANS unchanged (competitor
  names are still stripped — that is the `exclude` set).
- `critic_brief.md`: DUPLICATION `:154-156` → `duplicate_text` ("the words are the contract's own, so this is
  never `invented_text` — the fault is the second copy"); codes list `:195-207` += `duplicate_text`; NEW
  EMPHASIS block (465 chars, ends "A row with no `emphasis:` line has nothing to check. **When unsure,
  PASS.**") naming `emphasis_miss` as the CRAFT critic's code; `:75-80` += "TWO renditions of one mark on
  ONE frame are the craft critic's `duplicate_mark`, never yours."
- `critic_craft.md`: `duplicate_mark` (285 chars) and `emphasis_miss` definitions beside `empty_element`.
- `gauntlet_fix.md`: ORDER line (byte-mirror) + four REMEDIES rows (`duplicate_text *`, `duplicate_text
  full_frame`, `duplicate_mark *`, `emphasis_miss *`). **Count the fix_reserve growth (~650 chars) in the
  budget harness.**
- `carousel_slide.md` (+twin): the scaffolding paragraph names the `emphasis` label; `_onimage_text`
  (python, `prompts_engine.py:1568-1583`) emits, only when non-empty, the UNLABELLED line
  `  emphasis (set these exact words in this style's {emphasis_device}, in place, letters unchanged): "Fable 5" · "fastest"`
  (≤ 130 chars typical; 0 when absent; ASCII words cost nothing in `_spell`).

**Barrier W1:** suite green (new: `tests/test_emphasis.py`, `tests/test_fact_guard.py` incl. the 544-panel
false-positive corpus as a fixture sample, compress-once in `tests/test_style_test_mode.py`, tier partition +
integer pins); `--preview-copy` on a bound topic shows `emphasis` per row at $0; budget harness re-run (the
fix_reserve growth + emphasis line) still ≤ 1,450. NAVIGATION §5/§9. Commit.

---

## 3. WAVE 2 — Render side: registry, one mark per slide, counter head, fresh scenes, nits. THE 17-DECK CANARY + THE ACCENT A/B/C RUNS.

**Shape:** trigger (c) — `styles.yaml` and `prompts_engine.py` each carry several concerns → ONE owner per
file and a fixed ORDER inside the wave: **T2.2 python (role validation, new fields) → T2.1 registry → T2.3
templates → T2.4 tests**. No orchestrator; sub-barriers (suite + measure) between steps.

### 3.1 T2.2 Python FIRST (`python-pro`) — `styles.py`, `models.py` (MetaStyle), `prompts_engine.py` (logic), `generate/carousel.py`, `generate/contracts.py`

- **Zone-role vocabulary (FR-372):** `_zones()` accepts `role ∈ {"", "brand_slot", "counter_slot",
  "mark_slot"}`; any other non-empty role → FR-295 error (exit 2). Missing `mark_slot` → advisory WARNING
  (engine default slot line used); > 1 → error. `MetaStyle` += `scene_rotation: list[str]`,
  `emphasis_device: str` (≤ 80, default "the accent colour"). FR-349 variant scan reads `scene_rotation`.
- **MARK SLOT line (`prompts_engine._mark_slot(style, frame_marks)`):** non-empty ONLY on frames whose
  per-frame `frame_marks` is non-empty (D65): `MARK SLOT: {zone line} — the named mark renders here EXACTLY
  ONCE and nowhere else on this frame: not as the hero object, not on a tile, device, avatar or glyph.`
  Emitted inside the existing `tool_marks` value (no new placeholder; 0 cost on mark-free frames; ≤ 450
  incl. the zone line). **`_style_zones` is NOT gated on marks** (deck-level call) — the zone is listed
  ungated to the system critic and its own text says "nothing is drawn here when no mark is sanctioned".
- **Counter at the HEAD (FR-373):** `_counter_rule()` returns, for a COUNTED deck, `_MANDATORY_PREFIX +
  zone_line` where the prefix is the constant `COUNTER — MANDATORY on this frame: render the TEXT block's
  counter string once, legible at thumbnail size, exactly here: ` (≈ 140 chars; **`{value}` is NOT
  interpolated — the string is already a locked TEXT entry, and stating it twice invites `duplicate_text`**);
  arm (d) house: the same prefix + today's `_HOUSE_COUNTER_LINE` words; arms (a)(c)(e) byte-unchanged. The
  zone line stays BYTE-IDENTICAL inside the value; `tests/test_counter_rule.py:123-141` is rewritten from
  "renderer string ⊂ critic list" to "both quote the same `_zone_line`"; head value ≤ 460 incl. a 280-char
  zone line. Slot moves to template line 2, UNLABELLED (blank line on arms a/e, 1 char).
- **Fresh scenes (FR-374) — gated on `style.scene_rotation` being non-empty, NOT on `motion_profile`**
  (every test fixture is photographic by default): `carousel.py:2191-2193` swaps `ROLE_ANCHOR` for
  `ROLE_ANCHOR_SCENE_FREE = "carousel_anchor_scene_free.md"` on slides 2..N; `build_context` gains `scene`
  (allowlisted on `carousel_slide.md`, uncuttable by default, ≤ 150 with its label): slide 1 =
  `scene_rotation[0]`; slides 2..N = `scene_rotation[(number-2) % (len-1) + 1]` — **scene 0 is reserved for
  the cover so a 12-slide deck never repeats frame 1's setting** (the reviewer's bug); registry requires
  `len ≥ 7`. The anchor image is STILL attached (`_refs` unchanged). `DeckContract.scene_free = bool(
  style.scene_rotation)`; override briefs never.
- Emphasis render line (python half of §2.5, `emphasis_device` substituted); accent override wiring
  (`load_for_run` at the 5 sites — W0 built it); `meta.yaml.accent_override`.

### 3.2 T2.1 Registry (`prompt-engineer`, `prompts/styles.yaml` ONLY; measure after every style with the W0 tool; log to `plans/SESSION-Q-REGISTRY-LOG.md`)

1. **Neon retirement:** `#0FCFC4` (9 lines incl. `hypelead-brand-card`'s `render_prompt`) and `#57E6DC`
   (3) → `#0A7F78`; header `:13-20` → the one-shade family; `hypelead-brand-card:860` "two-stop teal" prose
   → one shade; `build-log-mono:1034` "on dark / on cream" keeps one hex.
2. **`mark_slot` zone on all 26 (FR-372):** `role: mark_slot`, `content: "sanctioned tool mark"`,
   `text_treatment ≤ 200` (the LINE may be 240–300 — today's counter lines already are), every one ending
   on the FR-340 sentence "nothing is drawn here when no mark is sanctioned". The reviewer's drafts for the
   eight special cases are the starting text: `neon-glass-dark` (RE-TAG of the existing `:2264-2266` zone),
   `social-quote-card` (RE-TAG of the avatar zone `:1278`), `icon-ledger-carousel` circle, `editorial-voxel`
   tile, `aurora-white-deck` square ("with no mark sanctioned no square is drawn and the card opens on its
   text" — fixes the empty squares + the teal mark), `big-number-editorial` ("flush left on the hairline at 11
   percent, before the kicker" — NEVER the words "top-left": FR-350 item 3 scans a YAML dump),
   `hypelead-brand-card` (lockup line), default for the other 18 ("in the text block, immediately before the
   first line's first word, one cap high"). The old prose that placed the mark in `image_treatment` /
   `list_mode` (`icon-ledger:1137`, `aurora:2482`, `voxel:379`) now POINTS at the zone, never duplicates it.
3. **Hero-object clarification — 4 styles** (`neon-glass-dark:2327`, `build-log-mono:1069`,
   `icon-ledger-carousel:1156`, `aurora-white-deck:2501` — wording differs, no blind find/replace;
   `editorial-voxel` has no such phrase, its tile is covered by 2): "its subject is an abstract form of the
   cover's CONTENT — never a brand or tool mark, never lettered; a sanctioned mark renders in the MARK SLOT
   alone and is never this object" (183 chars, in `carousel_cover` guidance → 0 body-slide cost).
4. **`social-quote-card` glyph row retired:** `:1265`, `:1281-1282` (zone), `:1299` (palette line
   re-worded), `:1313`, `:1319`, `:1334`, `:1338`, `:1341` (re-read the arrows exclusion vs the swipe cue);
   deliberate note rewritten.
5. **Safe-area phrase (FR-379 prep):** "inside the central 80% of the 1:1 frame" → **"inside the central
   70% of the frame's width and 80% of its height"** on all 26 `text_placement` rows + authoring rule
   `:177-182` (the 4:5 centre crop keeps 10–90% of the width, so text at 15–85% survives with margin;
   prompts still never state a shape — FR-94 clause 4). Never the bytes `4:5`.
6. **`counter_slot` zones on all 26** (the 6 HOUSE-arm styles gain their own): `text_treatment ≤ 200`,
   "top-right, inside the safe area" stated on every one.
7. **`scene_rotation` on the 8 photographic styles:** ≥ 7 one-line settings (≤ 90 chars, no colour words,
   no brand/product names, no " or "), entry 0 = the cover's scene. The reviewer's lists for
   `ugc-tabletop-statement-teal` and `quiet-luxury-night-photoreal-teal` are the models; their non-teal twins
   share them.
8. **`emphasis_device`** where native: letterpress(-teal) "set in the reversed black bar", icon-ledger "set in
   the accent colour with a thin underline", build-log-mono / contrast-verdict "set in the accent colour",
   big-number "set in the accent colour under the thick underline", aurora "set in the accent colour, one
   word at a time"; others default.

### 3.3 T2.3 Templates (`prompt-engineer`, after T2.1; splices twins)

- `carousel_slide.md`: line 2 = `{{counter_rule}}` (unlabelled); FORMAT bridge clause (W0); TOOL MARKS →
  the one-line MARK SLOT pointer; `scene` slot (unlabelled, empty on graphic); scaffolding paragraph; `:40`
  anchor clause "except on a scene-free deck".
- NEW `prompts/gpt-image-2/carousel_anchor_scene_free.md` (+twin, `SHIPPED_COUNT` 16→17): the reviewer's
  1,140-char draft ("PRIMARY for LOOK, never for SCENE … CHANGE THE SCENE: this slide is shot in the setting
  the SCENE line names … never Image 1's room, desk, table, street or skyline, and never a setting an
  earlier slide already used … A QUOTED POSITION BADGE KEEPS IMAGE 1'S CORNER AND SIZE; its digits alone are
  this slide's own") — shorter than the original 1,427, so photographic decks GAIN budget.
- `critic_system.md:99-106` `style_consistency` += the 366-char `scene_free: yes` clause ("a different room,
  table, street or skyline is CORRECT and never this code … a frame that repeats FRAME 1's setting is the
  defect"). No new code.

### 3.4 T2.4 Tests (`test-automator`) — `test_styles.py` (role vocabulary; `mark_slot` on 26; `scene_rotation`
≥ 7 on the 8; neon hexes gone; safe-area phrase ×3 pins + `measure_one_style.py:41`; `:1686-1705` still no
`4:5` bytes; `:2403/2430` counter placement; `:2488-2503` photographic count), `test_counter_rule.py`
(rewritten identity, head value ≤ 460, arms a/c/e unchanged), `test_carousel.py` (scene-free role + SCENE
line ONLY when `scene_rotation` set; `:1061-1118` unchanged for rotation-less fixtures), `test_prompt_fit.py`
(table re-baselined against the harness), `test_template_parity.py` (17), `test_style_match.py`
(`mark_slot` fixtures), `test_role_settings.py`, `test_prompts_engine.py:367, 388-393` (context keys,
allowlists).

**Barrier W2 (three steps, all $0 renders; Virlo metered):**
1. Suite green; `measure_one_style.py` over 26: cutA ≤ 1,450, slackB ≥ 400, owned ≤ 4,700, DNA ≤ 2,000,
   `mark_slot` present, scene ≥ 7 on the 8.
2. **The visual-fix canary:** `--style-test --styles <17 enabled> --pin-post <the 3pa5 post
   62998e11-9a27-4255-bc58-f1200401100f>` (comparable to P's table), 1:1 still. Tally: counter-shaped
   findings < 20% of all (was ~60%); `duplicate_mark` fires where two logos appear; no `invented_text` for a
   repeated line; delivery ≥ 13/17. A single dominating code is a regression — fix inside W2.
3. **The accent A/B/C runs:** three `--style-test` runs, SAME `--pin-post`, the 12 teal-bearing enabled
   styles + 5 controls: A `--accent #0A7F78 --accent-name "deep teal"`, B `--accent #059669 --accent-name
   emerald`, C `--accent #4F46E5 --accent-name indigo`. Measure per deck (local Pillow, `plans/tools/
   measure_accent.py`): hue spread across slides, accent coverage share, WCAG contrast of accent type on
   both grounds, standing critic counts, a contact sheet per run. Write `plans/SESSION-Q-ACCENT-RESULTS.md`
   with the RECOMMENDATION and rationale (UX: contrast on cream and near-black; UI: distinct from Claude
   orange / OpenAI black / Gemini blue / Meta blue; graphic: renders flat under gpt-image-2; brand: distance
   from the HypeLead kit). **Baking the winner into the registry prose and hexes by hand = SESSION R** (or
   W6 if the operator confirms in-session).
Commit. NAVIGATION §3/§5/§8.

---

## 4. WAVE 3 — Portrait carousels: plan ratios + local reframe (FR-379; FR-21, FR-98, FR-94 c3 amended)

**Shape:** flat-wave (a). `python-pro` ×1 (render/outputs path), `test-automator` ×1.

- `plan.py`: `_CAROUSEL_RATIOS = {"linkedin": "4:5", "instagram": "4:5", "tiktok": "9:16"}`, fallback
  `4:5`; config override precedence kept; `configs/default.yaml:441-453` comments.
- **NEW `hypesocials/outputs/reframe.py` (4th sanctioned Pillow use; local; never uploads):**
  `reframe(path, target_ratio, *, mode, ground=None) -> ReframeResult(ok, reason, native_size, framed_size,
  op)`. **Geometry is explicit per target:** `4:5` ← square: **CENTRE CROP** to 1003×1254 (keeps 10–90% of
  the width — the W2 safe area of 15–85% survives with margin); `9:16` ← square: crop to 4:5 THEN **PAD**
  top/bottom to 1003×1783 with an OPAQUE ground = median of the landed frame's 2% edge ring (fallback: the
  style's first GROUND hex, then white). **Safety valve `run.portrait_reframe: crop | pad` (default `crop`;
  `pad` = square padded to 1254×1567 / 1254×2229, nothing composed is ever cut)** — the W3 canary decides
  whether the default holds. Idempotent (target ratio already met → no-op). Native frame backed up under
  `<asset>/native/slide_NN_native.ext` (never globbed, never published). Import guard (no `render`/
  `generate`). Square text composition is what the model draws regardless (codex ignores size); under Kie
  a native-ratio frame is a no-op.
- **Wire at the ONE seam — LAST inside `carousel._store`, AFTER `_alpha_guard` returns** (so the halo check
  reads the NATIVE edge ring, the paste reads PLATE fractions of the frame the model actually drew, and the
  recursion's inner `_store` reframe is a no-op for the outer one); `await asyncio.to_thread(...)` like
  `_paste`. Single images at `generate/__init__.py:544,689`. Cover candidates stay native (documented:
  `cover_pick` judges the native frame). Event `frame_reframed` (op, sizes); `meta.yaml`
  `native_size_rendered` (pre-reframe) + `framed_size`; PRD 40 key list.
- **`screenshot_paste.PLATE` → `(0.12, 0.20, 0.76, 0.58)`** — ONE constant, inside the 4:5 crop band; no
  `plate_for(ratio)`; `plate_zone()` prose follows; tests' literal pins move (`:224`, `:402-403`, `:557`).
- `preflight.py:713-737`: "codex renders square ~1254 px; N creative(s) asked for 4:5/9:16 and are
  REFRAMED locally (crop / pad) after the critics' frame lands"; `_non_square_ratios` docstring.
- `budget.py`: Kie `4:5` carousel slides priced at 1K (existing clamp) — `tests/test_budget.py:177-197,
  1281+, 1296, 1485-1496` re-baselined; `9:16` stays 2K; codex $0.
- Gallery: no CSS change (`gallery.py:1006`); facts line prints requested vs native vs framed.

**Barrier W3:** suite green (`tests/test_reframe.py`: both ops, idempotence, opaque pad vs `alpha_halo`,
twice through `_store`, import guard; `test_plan.py:135-155`; `test_preflight.py:1421-1447`;
`test_carousel.py:2956`; `test_pixels.py`); a $0 run `formats.carousel: 3` over the three platforms →
Li/Ig 1003×1254, Tk 1003×1783 on disk, natives under `native/`, counters and mark slots INSIDE the frame on
every slide. A `counter_value` spike vs the W2 canary = the crop cut it → flip `portrait_reframe: pad` in the
three brand configs and re-run before closing the wave (the decision is recorded, not deferred). Commit.

---

## 5. WAVE 4 — Visual paste: every non-text visual is exact pixels (FR-380, FR-370 widened) + LIVE CANARIES

**Shape:** flat-wave (a). `python-pro` ×1 (sources + generate gate), `prompt-engineer` ×1
(`slide_intel_question.md` + critic wording, after python), `test-automator` ×1.

- `slide_intel.py`: `PANEL_KINDS = ("text", "screenshot", "table", "chart", "illustration", "photo",
  "graphic")`, default `graphic`; `screenshot_box` → `visual_box` (cache alias reads the old key), parsed for
  EVERY kind except `text`; per-slide `faces: bool`; schema + `source.yaml`. `prompts/slide_intel_question.md
  :101-127` item 6: "name the MAIN non-text visual region (interface, table, chart, drawn illustration, photo)
  and box it TIGHT; leave out the creator's headline, arrows, handle, watermark, counter, swipe cue, caption;
  `text` when the panel is type alone; `faces: true` when a real human face is inside the box".
- `carousel._paste_slides()` gate: (2) `panel_kind != "text"`, (3) `visual_box` parsed, (5) identity screen
  += `faces` and OVERLAP against the source author's own mark boxes (`_is_author_mark`) and `chrome_boxes`
  (watermark/handle) → `visual_paste_skipped_identity`. Config key **`run.screenshot_reuse` KEPT** (doc:
  "every non-text visual"; alias `visual_reuse` accepted; PRD 30 row; `configs/*.yaml` comments). Plate
  block "VISUAL PLATE" (same geometry, same exception); `screenshot_zone` → `visual_zone`;
  `_WORDLESS_SCREENSHOT` → `_WORDLESS_VISUAL`; gallery chip `ours · visual`; receipts `pasted`, `paste_box`,
  `paste_reason`, `paste_kind`. Photographic styles paste too (a screenshot on a desk reads as a card) —
  listed in §11 as a watch item. **Named risk (operator decision 3):** a third party's illustration or
  photo lands in a PUBLISHED creative; the screens are identity + faces + watermark; nothing else.
- Critic: `critic_brief.md:100` and `critic_craft.md` `empty_element` carve-outs generalised.

**Barrier W4 — THE LIVE CANARIES ($0 renders):** three `--style-test --styles <4 styles> --pin-post <id>`
runs on posts chosen from `--preview-sources` containing (i) a real app/tweet screenshot, (ii) a benchmark
TABLE, (iii) a chart/diagram. Success = plate reserved wordless, crop at exact pixels inside it (identity
test + visual read), critics sanction it, identity skips fire on a creator-own screenshot. Record in
`plans/SESSION-Q-CANARIES.md`. Commit.

---

## 6. WAVE 5 — The matrix (FR-381 half 2) + recommendations

**Shape:** `python-pro` ×1 (aggregator tool + gallery filter), then the conductor runs and writes.

- `plans/tools/style_matrix.py <run_dir>...` → `plans/SESSION-Q-STYLE-MATRIX.md`: rows = 26 styles, columns =
  the 10 pinned posts (kind label), cell = `shipped | blocked(<tier>) | n/a`, top-3 standing codes, re-render count,
  counter presence share, `duplicate_mark`/`emphasis_miss`/`copy_fact_lost` counts, hue spread; per-style
  totals + rank; **METHOD section states the compress-once caveat (every deck carries the SMALLEST style's
  text) and records each deck's OWN budget beside its score.** Reads `meta.yaml`, `GAUNTLET_REPORT.yaml`,
  `BLOCKED.txt`, slide files (local Pillow).
- Gallery: style filter + post-major grouping under `--style-test`.
- **Runs:** 10 × `--style-test --styles all --pin-post <id> --platform instagram` (4:5) — ONE post per run,
  26 decks each (~35–45 min; deadline floor 240 min). Posts = TEN kinds, picked from `--preview-sources`:
  numbered tips list · single big statement · tool walkthrough with screenshots · benchmark/comparison table ·
  before/after story · step-by-step tutorial · news/announcement · opinion/hot take · listicle of tools ·
  data/chart explainer; ≥ 2 in DE/CS so translate is covered; ≥ 3 with real screenshots so the visual paste
  is exercised at scale. Spread over ≥ 3 days for the image quota. The conductor writes per-kind style RECOMMENDATIONS and the
  proposed `match_profile` / `styles.enabled` changes (edits = SESSION R).

**Barrier W5:** matrix file written; galleries open; `logs/trend_history.json` md5 unchanged; `output/
latest.txt` untouched.

---

## 7. WAVE 6 — Docs + closeout (`technical-writer` + conductor)

NAVIGATION.md §3/§5/§8/§9/§11; CLAUDE.md Stack (Pillow: FOUR uses), Architecture (portrait reframe;
FR-98 re-decided), Glossary (accent override, mark slot, counter head, scene rotation, emphasis,
duplicate_text/duplicate_mark, fact protection, visual paste, pin-post, matrix); AGENTS.md re-synced;
`prompts/README.md`; `.claude/skills/hypesocials-run/` agents (`hs-deck-critic`, `hs-operator`) updated for
visual plates / counter head / mark slot; `plans/SESSION-Q-CLOSEOUT.md` (tallies per barrier, accent
recommendation, matrix summary, open items). Memory note.

---

## 8. PRDs & docs (D15: amend PRDs FIRST, in W0)

| FR | Title | PRD | Amends |
|---|---|---|---|
| FR-371 | Accent override (`branding.accent_override`, `--accent/--accent-name`, hex-only substitution + injected DNA row, `load_for_run`) + neon-teal retirement | 30, 50 | D57 teal spine, FR-347 (substituted registry validated separately), FR-364 row order |
| FR-372 | One mark per slide: `mark_slot` zone role (validated vocabulary), per-frame MARK SLOT line, `duplicate_mark` craft code, hero-object clarification | 50, 10 | FR-339, FR-366, FR-325 tiers |
| FR-373 | Counter at the head: MANDATORY prefix + byte-identical zone line, ≤ 460, arms (a)–(e) kept, FORMAT bridge clause | 50 | FR-338 |
| FR-374 | Scene rotation: `scene_rotation` (≥ 7, entry 0 = cover), `carousel_anchor_scene_free.md`, `scene_free` contract | 50, 10 | **FR-311 (anchor scene wins) carved out for scene-rotation styles; FR-308/FR-316 (brief supplies no scenery) — the SCENE line is registry, not brief**; FR-190; FR-189 (scene line is not DNA) |
| FR-375 | Emphasis words: `EmphasisRow` answer, lenient parse, guard 10, render line, `emphasis_device`, `emphasis_miss` CRAFT | 50, 10, 40 | FR-331 (letters never change) |
| FR-376 | `duplicate_text` contract-tier code | 10, 50 | FR-325, FR-367 |
| FR-377 | Fact protection: `guard_facts` (guard 1b, pre-scrub base), verbatim restore, `copy_fact_lost`, fact-aware trim, rule-1/14 precedence | 10, 50 | FR-353/354, FR-331 compress carve-out |
| FR-378 | Style test compresses once per source post (representative call, threaded row set) | 30, 10 | FR-369 |
| FR-379 | Portrait carousels: FR-21 matrix 4:5/4:5/9:16, `outputs/reframe.py` crop/pad + `run.portrait_reframe`, PLATE narrowed, receipts | 10, 20, 40, 30 | **FR-21, FR-98, FR-94 clause 3** (v1.6.1 rulings re-decided, rationale recorded), D48/D65 Pillow list, FR-342 pricing (Kie 4:5 = 1K), FR-350 safe area 70%/80%, FR-352 (cover pick judges the native frame) |
| FR-380 | Visual paste: every non-text kind, `visual_box`, `faces`, identity overlap, VISUAL PLATE, `screenshot_reuse` widened | 10, 50, 40, 30 | FR-370, FR-306 |
| FR-381 | `--pin-post` (post-Collect refusal), `--styles all`, `plans/tools/style_matrix.py`, post-major gallery | 30, 40 | FR-369, FR-314 |

`00-overview.md`: D66 entry, amendment log, pipeline diagram (reframe step after halo, before critics).
Version bump v2.10.0 on all PRDs.

---

## 9. Aggregating files & wire-in (single-writer-LAST)

| File | Why shared | ONE owner | Wave |
|---|---|---|---|
| `hypesocials/prompts_engine.py` | logic (python-pro) + built-in twins (prompt-engineer splice) | python first, then the splice task; never in one parallel fan-out | W0, W1, W2, W4 |
| `prompts/styles.yaml` | 8 concerns in W2 | `prompt-engineer` T2.1 only, AFTER T2.2's role validator | W2 |
| `hypesocials/gauntlet.py` | codes + FrameContract | `python-pro` critic-side (W1) | W1 |
| `hypesocials/generate/carousel.py` | contract builder (W1), scene/mark/counter (W2), `_store` reframe (W3), paste gate (W4) | one python-pro per wave | W1–W4 |
| `hypesocials/models.py` | copy dataclasses (W1), MetaStyle (W2) | per wave, one owner | W1, W2 |
| `hypesocials/styles.py` | `substitute_accent`/`load_for_run` (W0), role vocabulary + fields (W2) | per wave, one owner | W0, W2 |
| `hypesocials/plan.py` | `--pin-post` (W0), ratios (W3) | per wave | W0, W3 |
| `hypesocials/outputs/__init__.py` | re-exports (`reframe`) | W3 python-pro | W3 |
| `configs/*.yaml` | neon retirement (W0), `portrait_reframe` if flipped (W3) | per wave | W0, W3 |
| `plans/tools/measure_one_style.py` | W0 extensions | W0 python-pro A | W0 |
| `NAVIGATION.md`, `CLAUDE.md`, `AGENTS.md` | docs | technical-writer, last | W6 |

**Wire-in:** `load_for_run` ← the 5 registry load sites (W0/W2); `_mark_slot` ← `build_context` `tool_marks`
value (W2); counter head ← template line 2 (W2); `carousel_anchor_scene_free.md` ← `carousel.py:2191` role
swap when `scene_rotation` (W2); `scene` ← `build_context` + allowlist (W2); `guard_facts` (1b) /
`guard_emphasis` (10) ← `contract_guard.guard_deck` ladder (W1); `copyset.emphasis` ← `_guarded` (W1);
`duplicate_text`/`duplicate_mark`/`emphasis_miss` ← code tuples + `_PRECEDENCE` + `_REMEDIES` + templates +
integer pins (W1); `reframe` ← `carousel._store` LAST + `generate/__init__.py` (W3); `PLATE` narrowed ←
`_SCREENSHOT_PLATE_BLOCK` via `plate_zone()` (W3); `--pin-post`/`--styles all` ← `cli.py` →
`config.run.pinned_posts` → `plan.assign` (W0); `style_matrix.py` ← stand-alone (W5).

---

## 10. Execution & dispatch notes

- **§9 model policy:** never pass `model`. Effort inherited.
- **Leaf-wave-first:** every wave is dispatched by the main thread. W2's shared files are handled by single
  ownership + ORDER (python → registry → templates → tests), not an orchestrator.
- **Every template edit** ships both copies (`splice_builtin_twin.py`) in one commit; **every registry
  edit** is measured one style at a time with the extended tool; the per-style log is committed.
- **Budget is proven BEFORE W2's registry work starts** (W0 harness), re-proven after W1 (fix_reserve) and at
  W2's first sub-barrier. A red `test_prompt_fit` at W2's end is a W0 defect, fixed by freeing more template
  prose — never by shrinking a zone line.
- **Live runs launch detached** (`hypesocials-paid-runs-launch-detached`); read tallies from `BLOCKED.txt` /
  `GAUNTLET_REPORT.yaml`; compare against P's table (`kfb6` 6/17, `3pa5` 11/17, `forbidden_mark` 0) — W2's
  canary pins the SAME post as `3pa5`.
- **Line growth** measured at every barrier with per-task attribution; no docstring/comment trimmed.
- **Session sizing:** W0–W2 is one session (canary + three accent runs ≈ 2 h machine time); W3–W4 the next;
  W5 a third and fourth (10 runs, ≥ 3 days for quota). Stop at wave boundaries only.

---

## 11. Open items for the operator (surface at session end, do not block on them)

1. The accent WINNER — the session recommends; the operator confirms; SESSION R bakes it into registry prose
   and hexes by hand (or W6 if confirmed in-session).
2. Per-kind style recommendations from the matrix → `match_profile` / `styles.enabled` edits (SESSION R).
3. `run.portrait_reframe`: `crop` (true portrait, 10% of each side lost) vs `pad` (nothing lost, bands) —
   the W3 canary sets the default; the operator may override per config.
4. Kie path: 4:5 carousels are 1K-only at Kie — accept, or pin `platforms.<p>.aspect_ratios.carousel: "1:1"`
   when running metered.
5. If the codex proxy starts honouring `size` (W0 probe), the slide prompts may compose for portrait and the
   reframe becomes a no-op — a one-line PRD note then.
6. Visual paste on photographic styles (a plate on a full-bleed photo) — watch the W4/W5 output; a per-style
   `paste: false` is a one-field follow-up if it reads wrong.
7. Caption voice rewrite (P item 6) still tag-only.
