# SESSION P — Render-quality round after the Codex pivot (v2.9.0, D65)

**Status:** PLANNED, not started. Written 2026-08-21 from a full visual + fidelity audit.
**Load this file in a fresh session and execute top to bottom.** Also read first:
`CLAUDE.md`, `plans/SESSION-O-CLOSEOUT.md`, and (skim) `plans/EXECUTION-ORDER.md` for barrier discipline.

**Operator decisions already taken (do NOT re-ask):**
- Real screenshots from source posts → **exact pixel paste** (Pillow composite after render), not an AI redraw.
- Style test = **17 enabled styles, one FULL deck each, all bound to the SAME source post**.
- Critics should be **softer on style, and the phantom required-marks problem fixed**.
- All work happens on the two subscriptions (Codex proxy + Claude Code); renders/LLM are $0 metered.

**Branch protocol:** branch off current head as `session-p-render-quality`; commit the clean state FIRST
(operator rule: commit everything before changes). Parent chain: J→K→L→M→N→O unmerged to main, merge together.

---

## 0. Context — why this session exists

After the D64 pivot to gpt-image-2 (run via local Codex proxy), the operator reviewed outputs and found:
blotchy/uneven teal, missing style variety, over-harsh critics, empty placeholder blocks, wrong logos, and
wanted real screenshots reused. A three-agent visual audit (~55 slides) plus a three-agent **panel-by-panel
source↔output fidelity audit** (every deck of run `20260821_030722_4344` (Kie, before pivot) and runs
`q745`/`pm3y`/`1zqv` (codex)) produced the findings below. The audits are the evidence base; the waves are
the fixes.

### Audit findings (condensed — full details were in the session transcript)

**F-A. The render CONTRACT (`panel_map.source_text`) is itself corrupt, and nothing validates it:**
- OCR digit/letter confusion baked in and rendered: `I6GB`/`I4B-3OB`/`7OB` (=16GB/14B-30B/70B),
  `I46K STARS` (=146K), `IOX` (=10X), `128GB→28GB`. In several cases `source_text_original` on the SAME
  panel_map row is correct — the corruption came from compression/transcription, and nobody diffs the two.
- Row misalignment: 4344 `Ig_car_claude-ai-for-productivity-and-business_08` slides 4/6/8 carry the
  PREVIOUS repo's compressed text while `source_text_original` holds the right one → repos #5/#7 never
  appear, #2/#4 appear twice with self-contradicting stats.
- Creator/third-party identity LOCKED IN as required verbatim text (`creator_stripped: false`):
  `Gbillington1 merged commit 859bdce into dev` (1zqv Li slide 5), `Clearform-Labs/tldr #125` (slide 3),
  `OPAL COLLECTION` (an incidental tote-bag brand → rendered as a logo lockup in OUR teal, slide 6).
- OCR duplicate rows kept (`Audio/Documents/Documents/AI`) — critics then DEMANDED the garbage be printed.
- Dangling fragments after handle-stripping (`ran the cheap experiment you asked for.` with no subject;
  headline `document markdown`; body ending `( src/types/in`); `truncation_suspect: true` set then ignored.
- Silent panel drops: 4344 Ig_02 source panels 11-12 have NO panel_map row and NO drop_reason; run says success.
- Compression nondeterministic run-to-run on the same panel (q745 dropped the `5. ENTERPRISE AI` heading,
  pm3y kept it; q745 compressed panel 6, pm3y didn't).

**F-B. Render-level content failures (both renderers, worse under codex):**
- Hallucination into empty/dropped slots: fake install scripts (4344 Li_01 slide 3), invented product ads +
  fabricated stats attributed to REAL companies (Notion, Higgsfield "300+ actions", six invented Photoshop
  features), invented repo owners (`anthropics/git-mcp`, `jlowin/fastmcp` vs real `idosal`/`PrefectHQ`).
- DATA FABRICATION: pm3y Ig slide_03 invented 15 of 20 benchmark numbers (source `1.5%` became `13.8%`).
- Duplication: one sentence rendered ×6 (pm3y Tk slide_04); whole paragraph printed twice on one frame
  (4344 Ig_02 slides 4/10); bullet card ×2 (pm3y Li).
- Ordinal/counter chaos: invented 1-10 ladder with slide 4 showing "2" and slide 10 nothing (4344 Ig_05);
  ordinal ladders missing one step in 4 codex decks; counter on 3 of 8 slides (4344 Ig_08).
- Creator watermark promoted to hero headline ("EVOLVING A", 4344 Ig_02 slide 1) — and `cover_pick`
  SELECTED FOR the bug because the corrupted contract required the phrase.
- Sponsor lockup "Jason AI · by Reply" carried on all 7 slides as required text (4344 Tk_03).
- Semantic colour inversion: negative "X" marks in the positive brand teal; "Purple column = Opus 5"
  shipped on a teal, column-less slide.
- Real people replaced by synthesized faces (invented headshots where real maintainers' avatars stood).
- Captions: source creator's first-person life story published verbatim as our voice (4344 Ig_05, all Li decks).
- Marks stamped per-deck not per-panel (Claude+NVIDIA lockup on 6 slides; source had it on panel 1 only).

**F-C. Colour (the operator's "hideous green / skvrny"):**
- Before pivot (Kie): 9/9 decks machine-flat teal. After (gpt-image-2): mottling inside flat teal discs in
  EVERY icon-ledger deck, cream grounds drifting warm/cool between slides of one deck, three different teals
  in one frame (aurora decks), one deck uniform but hue-shifted to mint (#0FD3C2 vs #1BC9BD).
- Prior art: `prompts/styles.yaml:1495-1497` records measured 30-point hue drift on full-frame saturated
  mid-tones under gpt-image-2 (vs 6 on cream).
- `codex_images.py` sends NO `quality` and NO `input_fidelity` param; `resolution` is dropped (fixed 1254px;
  the 2K config pin is inert under codex).
- One critical artifact: q745 Li slide_01 shipped with a ragged semi-transparent alpha halo on all 4 edges —
  while that deck's cover candidates rendered CLEAN (a bad candidate/re-render was promoted).

**F-D. Critics (gauntlet) — blocking good decks for style, passing bad content:**
- Phantom required marks: `required_marks` derives from `slide_intel.brand_marks` via
  `carousel._sanctioned_marks()` — NOT from the actually-cropped `marks/` patches. `carousel.py:2050`
  `if author and author in collapse(name)` is BACKWARDS (handle "devrush01" is never a substring of mark
  "devrush") so the source creator's own mark stays REQUIRED while the handle is FORBIDDEN — blocked two
  good decks twice each. `_CHROME_WORDS` lacks `x`/`x.com` → "X.com wordmark" demanded on 3 decks. Critic
  gets a DECK-WIDE union of marks but judges per-frame → marks demanded on slides that never had them → the
  render then INVENTED an Opus/Anthropic mark on slides 02/03/07 to satisfy it.
- `platform_chrome` (tier-1 hard block) also covers "an invented app UI" → a stylised illustration hard-blocks
  past `fail_action: degrade`.
- ~2/3 of standing defects are layout pedantry (band heights, card widths), while the audits' worst content
  failures went UNFLAGGED: the 15 fabricated numbers, "The AI Playbook" identity leak on pm3y Ig 08,
  OPAL COLLECTION, mid-sentence truncations, orphan headlines, the alpha-halo artifact.
- Brief critic has no "when unsure, PASS" bar (system + craft have one).
- No critic checks empty placeholder elements at all (FR-340 is render-side only).

**F-E. Empty blocks:** 7 of 8 codex decks ship empty cards/circles/buttons/lorem bars (vs 2 of 9 Kie).
Root cause is DUAL: gpt-image-2's habit AND `styles.yaml`'s POSITIVE "greeking" rule (40 mentions telling
the model to draw grey filler bars as mock-up texture).

**Key architecture facts an executor needs (verified):**
- Critic prompts + render templates exist TWICE: `prompts/*.md` + byte-identical built-ins in
  `hypesocials/prompts_engine.py`. EVERY edit ships both copies via `plans/tools/splice_builtin_twin.py`
  in the same commit; `tests/test_template_parity.py` pins parity.
- Style text reaches the slide prompt ONLY via `prompts_engine.style_dna()` (`prompts_engine.py:858-877`,
  five rows) + `render_prompt`. `style_dna` also feeds critic_brief/critic_system → a global rule placed
  there is seen by renderer AND critics. PREPEND new rows (trio-trim eats the tail, floor 40%).
- Defect-code tiers are a frozen, test-pinned partition (`gauntlet.py:130-166`,
  `tests/test_gauntlet.py:371-391`). Moving/adding a code touches: the code list, tier set, `_REMEDIES`
  (`gauntlet.py:241-295`), `_PRECEDENCE` (`gauntlet.py:226-231`), `prompts/gauntlet_fix.md` + twin, tier test.
- Source-byte ban (D41/D46/D48): `refs._sanctioned` (`refs.py:305-314`) refuses any path under `source/`
  except `marks/`. Pillow is sanctioned ONLY in `sources/logo_crops.py`. Feature 5 adds a SECOND sanctioned
  Pillow use that never uploads anything (local composite after render).
- Config: three brand configs pin `llm_backend: codex`, `render_provider: codex`, critics gpt-5.6-sol at
  `critic_reasoning_effort: xhigh`, `gauntlet: {enabled: true, fail_action: degrade}`, 17 `styles.enabled`.

---

## 1. WAVE 0 — Contract integrity: deterministic guards (highest yield, no LLM cost)

Where panel_map rows are built/finalised (`hypesocials/copywrite.py`; some checks in
`hypesocials/generate/carousel.py` / packaging). All guards are pure functions with unit tests.

1. **Digit repair + drift check.** Per row, diff `source_text` tokens against `source_text_original`.
   Inside numeric-ish tokens (`[IlOo0-9]+` optionally suffixed `GB|B|K|X|%|STARS…` and bare numerals):
   repair `I/l→1`, `O/o→0` when the original has the digit at that position. Any remaining CHANGED digit
   vs the original → ship the original bytes for that token (or whole row if structure differs), tag
   `copy_digit_drift`. Catches: I6GB, I46K, IOX, 28GB, the dropped leading `7`.
2. **Row-alignment check.** A row whose `source_text` token-overlap with its OWN `source_text_original`
   falls under a floor (start ~0.3 Jaccard on content words; tune with the 4344 Ig_08 fixture) is
   misaligned → replace with the verbatim original (or wordless if over budget), tag `panel_map_realigned`.
   Refuse duplicate `source_position` values outright.
3. **Dedupe.** Collapse identical repeated lines inside one row's `source_text` before contract + critics.
4. **Identity scrub on `source_text`.** Run the existing handle/competitor scrub machinery over every row
   BEFORE it becomes the contract: creator handles + variants, `owner/repo` and `#N` issue refs, commit
   lines (`merged commit <hex>`), and any string matching a `brand_marks` entry that was never sanctioned
   as a tool mark. If stripping beheads the row (leading clause lost → subjectless fragment), drop the row
   to wordless rather than ship the orphan. Fixes the Gbillington1/Clearform/OPAL class at the ROOT — the
   renderer was obeying orders.
5. **Truncation gate.** `truncation_suspect: true` = gate, not note: ship the un-truncated original or go
   wordless. Also a cheap end-of-row heuristic (ends in `(`, `,`, dangling `N.` list marker → same handling).
6. **Coverage assertion.** `len(panel_map) + len(drops_with_reason) == source_panel_count`; violation →
   loud `panel_dropped_unmapped` console warning + meta receipt (never silent).
7. **Incomplete-deck block.** At packaging: `slide_count < slides_ordered` ⇒ never delivered as success —
   blocked with reason `incomplete_deck`, regardless of critic verdicts.
8. **Caption guard.** Captions take the same identity scrub; a caption in first-person creator voice
   (pronoun heuristic: leading `I`/`my`/`i'm` density) is tagged `caption_voice_review`, loud on console +
   gallery card. Caption STAYS verbatim (FR-331) — the operator sees and decides.
9. **Watermark-as-chrome.** A contract row (or row prefix) that equals a source `brand_marks`/watermark
   string ("EVOLVING AI" class) is stripped into chrome like counters are (kept in `source_text_original`).
   Also fixes `cover_pick` selecting FOR the bug — it reads expected text from the same contract.

Tests: fixtures modelled on the real defects named above (I6GB→16GB, I46K→146K, IOX→10X, 28GB→128GB,
Ig_08 misalignment shape, Documents/Documents dedupe, Gbillington1/`Clearform-Labs/tldr #125`/OPAL scrub,
orphan-fragment beheading→wordless, `( src/types/in` truncation, coverage assertion, incomplete-deck block,
caption first-person tag, EVOLVING-AI watermark strip).

**Barrier W0:** full suite green; `--preview-analysis` on a real topic shows scrubbed/repaired panel_map.

---

## 2. WAVE 1 — Colour lock + render params

1. **Global colour row in `prompts_engine.style_dna()`** (`prompts_engine.py:858-877`): PREPEND a fixed
   `colour_rendering` row (NOT appended — trio-trim eats the tail):
   *"Where this style declares a flat colour field, render it as ONE uniform, evenly mixed colour edge to
   edge — no mottling, speckle, noise, vignette or tonal drift inside the field, and the SAME hex on every
   slide of this deck. A gradient exists only where the style explicitly declares one."*
   Reaches slide prompt + brief/system critics automatically. Re-measure style budgets
   (`plans/tools/measure_one_style.py` bars: owned ≤ 4700, style_dna ≤ 2000, cutA ≤ 1540, slackB ≥ 60).
2. **`render/codex_images.py`:** send `quality: "high"` on `/images/generations` AND `/images/edits`;
   send `input_fidelity: "high"` on `/images/edits` (helps logo 1:1 and anchor colour match). Probe once
   with a $0 test call to confirm the proxy accepts both params before wiring (it may ignore them — fine).
3. **Alpha-halo guard.** After a render result is stored (`codex_images._store` or the landing path):
   Pillow check for non-opaque alpha at the frame edges → treat as a failed render with ONE FR-317-style
   resubmit on its own ledger; if the resubmit also fails the check, flatten onto opaque and tag
   `alpha_flattened`. (Root cause of q745 Li slide_01's unpublishable halo.)
4. **Render-prompt constraints** (template CONSTRAINTS in `prompts/gpt-image-2/carousel_slide.md` +
   `image_post.md`, near the top, both copies): icons/glyphs must match the meaning of the line they mark —
   never decorative invention; never a synthesized human face where the source showed a real person
   (non-human glyph or nothing); negative markers (X, cross, "loses") never in the positive accent colour.

**Barrier W1:** suite green; template parity green; one $0 probe render showing flat fill improvement.

---

## 3. WAVE 2 — Critics: softer on style, harsher on content

**Marks root fix (code):**
1. `carousel._sanctioned_marks` (`carousel.py:2016-2054`):
   (a) fix the backwards author test at `:2050` — bidirectional, `mark_name`-normalised comparison with the
   `slide_intel._identity` semantics (handle `devrush_01` must kill mark `DevRush`);
   (b) extend `_CHROME_WORDS` (`carousel.py:261-263`) with `x`, `x.com`, `reddit`, `threads`, `bluesky`;
   (c) **REQUIRED marks = only marks with an actually-cropped patch** (join the sanction list to
   `self.patches` from `_crop_patches`) — a mark seen in the source but never cropped is NEITHER required
   NOR forbidden (neutral). This also stops the renderer being pushed to INVENT marks to satisfy the critic.
2. **Per-frame marks:** `DeckContract` gains a per-frame required-marks map (which source panel actually
   carried each mark, from `slide_intel` positions); `gauntlet._context` renders `frame N: mark, mark` lines
   so absence is a defect only where the panel carried it. Render side already per-slide (`carousel.py:1655`).
3. **`platform_chrome` narrowed** (`critic_brief.md:73-75`): only REAL platform chrome/watermarks/UI of the
   social platform itself. "Invented generic app UI" moves OUT of tier-1 → covered by `empty_element`/craft.
   Update tier partition test.

**Prompt rebalance (all three critic templates + `gauntlet_fix.md`, BOTH copies each):**
4. Brief critic gets a "when unsure, PASS" bar for non-leakage codes (mirror the system/craft wording;
   leakage keeps its when-unsure-FAIL at `critic_brief.md:80-88`).
5. **Numeral fidelity:** every numeral legible on the frame must exist in the TEXT block, and every TEXT
   numeral must appear unaltered; a table/chart carrying numbers NOT in the TEXT block = `invented_text`
   high. (Would have caught the 15 fabricated benchmark values and the invented "300+ actions".)
6. **Duplication:** a quoted line printed more than once on a frame, or the same sentence under multiple
   labels = `invented_text`. (The ×6 sentence, the twice-printed paragraphs.)
7. **Ordinal ladder:** headline ordinals across the deck must form a complete run; a break is
   `missing_text` on the gap frame (brief critic sees the whole deck in round 1).
8. **Wordless frames:** a frame whose contract quotes NO text must carry ZERO legible characters — any
   lettering = `invented_text`. (Kills the hallucinated install-script/product-ad class.)
9. **Truncation:** a line ending mid-clause/mid-token = `truncated` high confidence.
10. **Style-pedantry damping:** system-critic bar reworded — geometry judgement calls (band heights, card
    widths, start-percentages) PASS unless flagrant; content-fidelity codes explicitly outrank layout ones.
11. **Config:** `critic_reasoning_effort: xhigh → high` in all three brand configs.

**Barrier W2:** suite green (tier test updated); a 2-3 deck $0 canary shows: no phantom `missing_mark`,
delivery rate up, and a seeded fabricated-number fixture caught in a critic dry-run (prompt-level test).

---

## 4. WAVE 3 — Empty-element purge

1. **Registry (`prompts/styles.yaml`):** strip/narrow the 40 POSITIVE greeking instructions for the enabled
   styles: a repeating device or mock-up interior exists only around QUOTED text; standalone empty cards,
   buttons, circles, bars banned. Keep a minimal greek allowance ONLY where a mock-up IS the style identity
   (`terminal-mockup-deck`, `platform-showcase-card`, `neon-glass-dark` object screens), constrained to
   low-contrast + small share. Re-run `plans/tools/registry_contract_check.py` + measurement bars per touched style.
2. **Template:** one constraint line in `carousel_slide.md` (+ twin): no empty container of any kind
   without quoted text or a sanctioned mark inside it.
3. **New craft defect code `empty_element`** (CRAFT tier → buys a re-render, never blocks):
   code list + tier + `_REMEDIES` + `_PRECEDENCE` + `gauntlet_fix.md` remedy + `critic_craft.md` definition,
   both copies each, tier-partition test updated.

**Barrier W3:** suite green; registry contract check green; canary deck free of empty scaffolding.

---

## 5. WAVE 4 — `--style-test` mode + THE 17-STYLE TEST RUN

Mechanism (diagnostic mode, isolation over elegance — touches NO prompt template):
1. `cli.py`: `--style-test` flag (`action="store_true"`); refuse without `--styles` (exit 2) — the
   `--styles` list order IS the test matrix. `Options.style_test`.
2. `cli.apply_overrides`: when set — `formats = {image:0, carousel:len(styles), reel:0}`; single platform
   (first of `run.platforms` unless `--platforms` names exactly one); `max_trend_reuses_per_run = len(styles)`;
   `cover_candidates = 1`; `gauntlet.fail_action = "degrade"`; `run_deadline_min = max(existing, 240)`;
   one `applied` note per override (launch summary shows the whole mode).
3. `config.py`: `RunConfig.style_test: bool = False` (CLI-only; `_validate` warns if a yaml sets it).
4. `plan.assign` (`plan.py:566-617`): under the mode, the FIRST carousel group picks normally (top-ranked
   fresh post); the `(trend, post)` pair is then PINNED and reused by every later carousel group; skip
   `burnt.add(post.post_id)` under the mode. `AssignmentDecision.detail` notes `style_test: post pinned`.
5. `runner._assign_visuals` (`runner.py:545-577`): bypass rotation AND matched — new pure
   `styles.assign_styles_fixed(entries, keys)` maps entry order → `--styles` order 1:1 (NOT
   `rotation: fixed`, which walks registry file order and silently skips). `style_origin` stays
   `"rotation"`; `style_reason = "style_test"`. Console: `style test: 01→key, 02→key, …`.
6. **History skip:** guard `record_use` (`runner.py:1727-1729`) AND `set_latest` (`runner.py:1734-1735`)
   with `not style_test` — trend history never learns the run (next-day autopilot unaffected);
   `output/latest` untouched. Gallery title gets ` — STYLE TEST` suffix.
7. `slide_intel` already dedupes by post → ONE vision call for all 17 decks (free bonus of the pinned post).

**Then RUN IT** (after W0-W3 land, so the test shows the improved behaviour):
```
run.bat --config configs/hypedigitaly-fresh.yaml --style-test --yes ^
  --styles anime-noir-statement,platform-showcase-card,letterpress-print-carousel-teal,meme-caricature-panels-teal,quiet-luxury-night-photoreal-teal,photoreal-ambient-caption-teal,ugc-tabletop-statement-teal,build-log-mono,icon-ledger-carousel,circuit-atlas-dark,social-quote-card,terminal-mockup-deck,big-number-editorial,contrast-verdict-deck,photo-poster-statement,neon-glass-dark,aurora-white-deck
```
Launch detached via the cmd-wrapper idiom (see memory: paid runs launch detached; call run.bat by full
path), wait in chunks, then verify: 17 decks on ONE `copy_source_post_id`, gallery says STYLE TEST,
`logs/trend_history.json` byte-identical before/after, `output/latest` unchanged.
**Deliverable to operator: the gallery — they pick which styles to double down on.**

**Barrier W4:** the run itself + the three receipts above.

---

## 6. WAVE 5 — Screenshot exact pixel paste (the D65 headline feature)

Source bytes STILL never reach a render payload — compositing is local, post-render, output-side.
`refs._sanctioned` and both other guards untouched.

1. **Detection (`sources/slide_intel.py` + `prompts/slide_intel_question.md` + twin):** question item 6
   "PANEL KIND & SCREENSHOT BOX" — `panel_kind: screenshot | graphic | photo` (screenshot = captured real
   interface: tweet/X post, Discord/Slack chat, GitHub page, code editor/terminal, real tool or website UI);
   when `screenshot`, also `screenshot_box [x,y,w,h]` in the mark-box fraction vocabulary, TIGHT around the
   interface, EXCLUDING the creator's own chrome (footer handle, page counter). `SourceSlide` += both
   fields; new `_screenshot_box()` parser — NO `_MARK_BOX_MAX_SPAN` ceiling (screenshots legitimately span
   the panel; the box is never uploaded), floor ~0.15 span per axis. Schema + parity + tests.
2. **Reserved plate:** deterministic geometry in code — `PLATE = (0.08, 0.20, 0.84, 0.58)` of the 1254px
   canvas. New `{{screenshot_plate}}` slot in `carousel_slide.md` (+ allowlist in `prompts_engine`, + twin):
   *"Reserve one EMPTY plate: a flat single-colour rounded rectangle in this deck's surface colour, from 8%
   to 92% of width and 20% to 78% of height, with NOTHING drawn, lettered or textured inside. Compose
   everything else around it."* FR-340 constraint gains the one-exception sentence for this ordered plate.
   The paste slide's render text is BLANKED via the existing wordless-panel branch
   (`wordless_reason="screenshot_paste"`) — the screenshot IS the content; panel_map/copy untouched.
3. **Compositor — second sanctioned Pillow carve-out:** new `hypesocials/outputs/screenshot_paste.py`:
   `paste_screenshot(slide_path, source_slide, box, *, plate=PLATE, corner_radius_px=24) -> PasteResult`
   (frozen dataclass: ok, reason, zone, source_image, box, raw_backup). Behaviour: back up the raw render
   to `plates/slide_NN_raw.<ext>`; crop box (+ small pad); FIT-scale into the plate preserving aspect
   (centred letterbox — invisible against the rendered plate colour); rounded-corner mask + 1px border;
   temp+replace atomic write. Never raises (fail-open PasteResult). Sync function, caller wraps
   `asyncio.to_thread`. Import pin test: module never imports `render`/`refs`.
4. **Hook point:** the single landing seam where `self.paths[number]` is set after `store_render`
   (`carousel.py` ~:1046, after `delivered.add`) — covers first render, FR-317 resubmit AND every gauntlet
   re-render, so critics ALWAYS judge the composited frame and re-renders are re-pasted. `self.pastes:
   dict[int, PasteResult]`.
5. **Critic sanction:** `FrameContract.screenshot_zone: str` (gauntlet.py:334 area) filled from
   `self.pastes[n]` ONLY when ok; `gauntlet._expected_blocks` emits a `screenshot: <zone prose>` row through
   the EXISTING `{{expected_blocks}}` channel (no new critic placeholder). `critic_brief.md`: everything
   INSIDE the named zone (text, chrome, logos, handles, faces) is sanctioned — never `invented_text` /
   `platform_chrome` / `identity_leak` / `forbidden_mark` / `translated`, never counted for `missing_text`;
   OUTSIDE the zone every rule stands; stated BEFORE the when-unsure-FAIL leakage paragraph. One line each in
   `critic_system.md` (zone occupies the content region by mandate — never a consistency defect) and
   `critic_craft.md` (judge the plate's integration, not the screenshot's internal quality). Both copies each.
6. **Gate + identity policy:** `RunConfig.screenshot_reuse: bool = False`; three brand configs pin `true`.
   Per-slide predicate computed BEFORE prompting (`paste_slides: set[int]`): gate on ∧ panel_kind screenshot
   ∧ valid box ∧ source file exists ∧ **identity screen — SKIP the paste (normal redraw, no plate) when any
   creator identity form appears in the slide's text/chrome or a chrome-kind detection overlaps the box**
   (a screenshot of the creator's OWN post is the definitional identity leak; blur is v2). Third-party
   content inside the zone is exactly what the feature exists for — sanctioned. Log
   `screenshot_paste_skipped_identity` per skip.
7. **Receipts:** panel_map rows += screenshot paste details (pasted, source_image, box, ok, reason);
   `DegradationTag` += `screenshot_paste_failed`; gallery card "screenshot" chip; `plates/` raw linkable.
   A failed paste ships the empty plate JUDGED as the defect it is + the tag.

**Barrier W5:** suite green; a live $0 canary on a topic whose source has screenshot panels — verify
`plates/` backup exists, composited pixels byte-match the source crop, critics pass the zone, receipts
present, `reference_source_store_refused` never fires.

---

## 7. PRDs & docs (D15: amend PRDs FIRST, each wave)

- `prds/00-overview.md`: D65 decision entry + new FR block (suggest FR-362…FR-370: contract guards,
  colour row + params, alpha guard, marks derivation, critic rebalance, empty_element, style-test mode,
  screenshot paste, caption guard) + amendment log + pipeline diagram touch-up.
- `prds/10-pipeline.md`: Wave-0 guard stage, paste stage ordering (paste before judging), style-test mode,
  incomplete-deck rule.
- `prds/30-configuration-and-run.md`: `run.screenshot_reuse`, `run.style_test` (CLI-only), effort change,
  the style-test override table.
- `prds/40-outputs-and-logging.md`: `plates/`, panel_map fields, new tags, gallery chips, STYLE TEST title.
- `prds/50-promptcraft.md`: colour_rendering row, critic rebalance rules, plate slot + FR-340 exception,
  slide_intel item 6, greeking narrowing.
- `prds/20-integrations.md`: quality/input_fidelity params; one paragraph restating the upload ban is
  UNCHANGED and naming the second Pillow carve-out.
- `CLAUDE.md` + `AGENTS.md` glossary/stack notes; `NAVIGATION.md` at every barrier.
- Close with `plans/SESSION-P-CLOSEOUT.md` per the handoff protocol.

## 8. Execution & dispatch notes

- Leaf-wave-first per CLAUDE.md §9: python-pro (code), prompt-engineer (templates/registry/critic prompts),
  test-automator (tests); conductor keeps wire-ins + aggregating files. Never pass `model` when spawning.
- EVERY template/critic-prompt edit ships BOTH copies (`plans/tools/splice_builtin_twin.py`) in the SAME
  commit as its test updates.
- Measure lines at every barrier: `find hypesocials -name "*.py" | xargs wc -l | tail -1` (never the glob),
  report growth with per-file attribution.
- Suite baseline: **2020 passed / 0 failed**. Venv: `.venv/Scripts/python.exe` (bare `python` lacks `mcp`).
- Live runs: $0 metered under codex (Virlo metering only). Launch paid/long runs detached (cmd wrapper,
  full path to run.bat); previews never print the estimate table.
- Wave order is dependency order: W0 (contract) → W1 (colour/params) → W2 (critics) → W3 (empty) →
  W4 (style-test run = live proof of W0-W3) → W5 (screenshot paste). W1-W3 can overlap in one dispatch wave
  if file sets stay disjoint; W0 first ALWAYS (critics' new numeral/duplication rules assume a clean contract).

## 9. Open items for the operator (surface at session end, do not block on them)

1. After the W4 style-test gallery: which styles to keep/disable (the whole point of the run).
2. Caption voice: v1 only TAGS first-person creator captions (`caption_voice_review`). If the operator wants
   them rewritten (third-person via the copy LLM), that is a verbatim-principle (FR-331) amendment — ask then.
3. Colour still blotchy after W1 + W4 evidence? Then propose the post-render colour-quantise pass (a third
   Pillow use) as its own amendment. Measure first.
4. Reels remain refused under codex (no subscription video path) — unchanged.
5. Virlo topic clustering sometimes mislabels decks (`ai-video-generation-trends` folder carrying a
   lead-gen deck) — known, out of scope here.
