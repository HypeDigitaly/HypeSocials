# xmasterplan — Carousel Copy Compress Mode + Style Doubling-Down (v2.3.0, D54/D55)

**Session:** H · **Approved by operator:** 2026-08-20 (plan-mode review, all decisions recorded below)
**Read first in a fresh session:** `plans/SESSION-5.8-CLOSEOUT.md` (latest closeout), then this file end to end.
**Standing rules:** the "Standing rules for every session" block at the bottom of `plans/EXECUTION-ORDER.md`
applies verbatim to every wave and every subagent prompt of this session.

---

## 1. Context (why)

**Problem.** The operator's preferred styles are minimal-density (one bold statement + a small support
block per slide), but FR-304 panel-mapped decks copy each bound source panel verbatim and deliberately
bypass style budgets (D50 "reflow, never shorten"; only the 1,500-char `PANEL_SANITY_CHARS` gate applies).

Measured evidence:
- Run `20260820_001158_2ard` shipped panels of **1,048 / 1,023 / 1,018 chars onto `anime-noir-statement`**
  (declared slide budget **180** — 5.8x over): walls of text, cluttered UI recreations.
- Same run, `Li_car_claude-ai-for-coding-development_01` was **gauntlet-blocked**: `invented_text` on two
  *wordless* frames (over-budget panels drop to wordless per FR-304 and the render model invents filler)
  plus an `identity_leak` (source author handle rendered from verbatim panel text).
- The liked runs (`20260819_214018_xm28` anime-noir, `20260819_191734_0jc2` letterpress) carried
  219–532-char panels on 180/300 budgets and were also gauntlet-blocked.

**Operator decisions (2026-08-20) — settled, do not re-litigate:**
1. New **compress mode** is a config/menu **toggle** (never automatic). Engine-wide default stays
   `verbatim`; the **three brand configs pin `compress` ON**.
2. **1:1 panel alignment kept** — source panel *i* -> our slide *i*; per-panel compression, no deck redesign.
3. **Scope: carousels only** (bound, non-override, panel-mapped decks). Images/reels/override
   briefs/unbound decks unchanged.
4. Compressed copy stays in the **source post's language** (mirror of the verbatim language rule).
5. **Caption is also compressed + humanized** (comment/follow CTA bait stripped; hashtags blocklist-checked).
6. Humanization = instruction set from **github.com/blader/humanizer** (MIT, `SKILL.md` at repo root,
   35 patterns from Wikipedia's "Signs of AI writing"), vendored + distilled into the compress prompt.
7. **Styles**: `styles.enabled: [anime-noir-statement, letterpress-print-carousel, meme-caricature-panels,
   quiet-luxury-night-photoreal]` in all three brand configs. `meme-caricature-panels` is
   `carousel_role: slides_only` -> **inert on carousel-only configs; operator chose to keep it inert for
   now** (activates if image posts return). New style `quiet-luxury-night-photoreal` authored from
   `Inspiration/Tiktok and IG/Informative_Photorealistic_Carousel_01.webp` + `_03.webp` (text-only DNA per
   D46 — inspiration informs authorship only, never becomes a render reference). Neither existing
   photoreal style is wanted. `hypelead-brand-card` deliberately excluded (`branding.enabled` is false in
   the shipped configs so `brand_ok` drops it anyway; branded entries sign via the TEXT block on any style
   — verified `styles.py:711-728`, `prompts_engine.py:842-857`).

**Architecture key.** `copywrite.py:1698` already derives a group-scoped `verbatim: bool` switching between
the reference-selection schema (`_selection_schema` :1950) and an existing free-text schema
(`_free_text_schema` :1969) with budget-trim machinery (`_free_text` :2432 -> `_apply_budgets` :2781).
Compress = a third contract: source strings in the payload + free text out. **The gauntlet needs NO
change**: `_expected_blocks` (`gauntlet.py:1136-1163`) is built from `CopySet.slide_texts`, so compressed
strings flow through iff `slide_texts` and `panel_map` are produced by ONE walk.

**Doctrine.** D54 is a deliberate, operator-dated partial reversal of D50/FR-100/FR-101 for opted-in runs
(precedent: the A20 reversal, `copywrite.py:9-13`). D50 still governs verbatim mode. FR-303 stands:
compression is authored from the post's **actual panel strings** (post-strip, post-vision-merge), never
from Virlo's machine description. Per D15: **PRDs amended before code.**

**Numbering (verified):** decisions -> **D54** (compress mode), **D55** (style doubling-down); FRs ->
**FR-331** (10-pipeline), **FR-332** (50-promptcraft), **FR-333** (30-configuration); next fresh block
becomes FR-334+.

---

## W1 — PRD amendments (D15: strictly before any code; technical-writer or main thread)

1. **`prds/00-overview.md`** — append D54 + D55 rulings (dated 2026-08-20; D54 names the compress
   contract, scope, fallback-to-verbatim-mapped-deck on call failure tagged `copy_degraded`, humanizer
   vendoring; D55 records the 4-key list, the caricature-inert fact, the brand-card exclusion). Append one
   D50 carve-out sentence at the D50 entry (:189): "D54 (2026-08-20) adds an operator-opted compress mode
   for bound carousel decks; D50's reflow-never-shorten rule continues to govern verbatim mode, which
   remains the default, and no drop path gains a budget input in either mode." FR-Range registry: FR-331 ->
   10-pipeline, FR-332 -> 50-promptcraft, FR-333 -> 30-configuration; "Next fresh block: FR-334+"
   (:248-255). Amendment log entry v2.3.0 (:285). COPY-stage note + Mermaid diagram rebuild.
2. **`prds/10-pipeline.md`** — amend FR-99 (:153, "never free-text copy" gains the D54 exception; the
   fallback for a failed compress call is the FR-304 verbatim mapped deck), FR-13 (:170 carousel bullet),
   FR-100/FR-101 (:178, compress is a second operator-opted boundary; blocklist stays absolute/fail-closed;
   FR-319/FR-312 marks never ship), FR-302 (:203, compressed slides carry no ref labels; provenance = the
   panel_map row), FR-303 (:205, distinction: compression is authored from the bound post's actual panel
   strings under our style budget; Virlo's description stays fenced context, never seeds a compressed
   line), FR-304 (:257, new clause **(d)**: row structure / deck length at ASSIGN / position preservation /
   the 3 drop reasons IDENTICAL to verbatim; admitted panels LLM-compressed to
   `min(text_budgets.slide, style max_onimage_chars.slide)`, source language, humanized, engine-scrubbed,
   backstop-trimmed; rows keep `source_text_original`, gain `compressed: true`, `source_text` stays "what
   ships"). New **FR-331** block after FR-304: the full normative spec incl. caption rule and
   verifier/gauntlet interaction.
3. **`prds/30-configuration-and-run.md`** — §2 run keys: document `carousel_copy_mode`
   (`verbatim | compress`, default verbatim) + cost note; FR-133 (:205) key list; FR-259 (:237) budgets
   clause amendment ("...in verbatim mode; under FR-331 the same min(config, style) slide arithmetic is the
   compression TARGET and the engine's backstop trim"); menu §4/FR-56 (:379-401): five -> **six** prompts
   (new step 3 "carousel copy mode", Enter keeps config value) + NFR-16 bound; §5 CLI: `--copy-mode` row;
   new **FR-333** block (validation like `notion_influence`, flag-over-config per FR-61, pre-flight summary
   prints the mode when carousels are planned).
4. **`prds/50-promptcraft.md`** — §5a (:158) new "Carousel compress playbook (D54, FR-332)" + **FR-332**
   block: template `copy_compress_system.md` (+ built-in twin), placeholder contract, compression mandate
   (preserve facts/numbers/tool names, mirror language, never invent, never emit handles/URLs/added
   hashtags/emoji in slide text, empty positions stay empty), humanizer clause (vendored
   `prompts/humanizer_skill.md` = reference-only, never engine-loaded; the distilled ~14-pattern on-image
   subset lives in the template and is kept in step with the vendored file by its editor).
5. **`prds/40-outputs-and-logging.md`** — FR-73: meta.yaml gains top-level `copy_mode`
   (`verbatim | compress`); `panel_map` rows gain `compressed` (bool). FR-309 gallery note: a compressed
   deck's card labels the slide column ("compressed from N chars") using `source_text_original` length.

No `prds/20-integrations.md` change (no new role/model/endpoint — compress rides the existing `copy` role).

**W1 barrier:** PRD diffs read clean against this plan; diagram renders; amendment log entry present.

---

## W2 — Code (after W1; three leaf tasks, disjoint paths, no orchestrating parent — §9a)

### Task C-a (python-pro): config / CLI / menu
- `config.py`: `RunConfig.carousel_copy_mode: Literal["verbatim","compress"] = "verbatim"` beside
  `notion_influence` (:183 precedent; `_coerce` validates Literal — no `_BOUNDS` entry needed; a bad value
  refuses at load).
- `configs/default.yaml`: document the key (verbatim + comment block per FR-133). **Three brand configs
  (`hypedigitaly.yaml`, `-cs.yaml`, `-fresh.yaml`): pin `carousel_copy_mode: compress`** + comment.
- `cli.py`: `Options.copy_mode: str | None = None`; `--copy-mode {verbatim,compress}` beside `--notion`
  (:153); `apply_overrides` (:265) sets it when present + applied-note.
- `menu.py`: `_WIZARD_STEPS` (:76) -> `("config","counts","copy_mode","cap","briefs","confirm")`; new
  `_pick_copy_mode` (Enter keeps config value, `1`/`2`, `?` help); pre-flight summary prints the mode when
  carousels > 0. `_QUICK_STEPS` untouched. `wizard_help.md`: `## purpose.copy_mode` + `## copy_mode`.

### Task C-b (python-pro): copywrite core + models + runner + console surfaces
- `copywrite.py`:
  - Thread mode: `write_copy(..., carousel_copy_mode="verbatim")`; `_Run` field; `runner.py:892` passes
    `config.run.carousel_copy_mode` (single production call site; covers `--preview-analysis`).
  - Predicate `_compress_wanted(entry, offer, run)` = mode is compress AND `_panel_mapped(entry, offer)`
    (:1861).
  - **Group split by mode** in `_write_group` (:1678): partition `askable`; verbatim partition -> existing
    `_call_copy` unchanged; compress partition -> new `_call_compress` (renders `copy_compress_system.md`,
    sets `context["compress_panels"] = _compress_block(...)` — per creative: admitted panels numbered by
    source position with text + per-slide budget from `offer.budgets["slide"]` (already min(config,style)
    via `_slot_budgets` :1136), caption source string, per-creative language-mirror line; uses
    `_compress_schema()` from `models.CopyCompressed`; existing `COPY_ROLE` — no new role, no estimator
    change). Per-creative split fallback (:1700-1707) re-dispatches per mode. Rationale for split over a
    combined schema: copywriter_system is a selection mandate end to end; the shipped configs are
    all-carousel so a pure-compress group is still ONE call; independent failure/degradation.
  - New `_compressed()` resolution branch (selected at :1722-1725) -> **`_compressed_deck()`: ONE walk
    producing `texts` + `panel_map`** (the gauntlet-consistency invariant): per position 1..slide_count,
    `_panel_verdict` on the SOURCE panel text exactly as `_mapped_deck` (:2245 — empty /
    contains_handle_or_url / >1500 -> wordless in position, same three `_warn` blocks;
    `PANEL_SANITY_CHARS` stays an INPUT guard); admitted positions take `slide_texts[position-1]` then
    engine backstops in order: (1) blocklist strip via `apply_blocklist` (fail-closed), (2) `_social_mark`
    check — a violating compressed line is BLANKED + `compress_scrub` warn, (3) word-boundary trim to
    `offer.budgets["slide"]` (tag `TEXT_TRIMMED`), (4) model text for a source-empty position DISCARDED +
    warned (compression fills no vacuums).
  - `panel_map` rows: same fields as :2194-2217, `source_text_original` = admitted source panel,
    `source_text` = shipped compressed string, `ref_label: ""`, **`compressed: True`**.
  - Caption: compressed+humanized from payload (blocklist strip; `_social_mark` -> fall back
    `_offer_caption`); hashtags blocklist-checked; headline trimmed to `budgets["headline"]`.
  - **`_verify` needs NO code change** (verified :2862): half 1 runs only `if written.quoted`, so
    `_compressed()` returns `_Written(quoted=())` — the byte-substring audit is skipped exactly like the
    precedented free-text creatives (:1668-1669) while the blocklist half (:2860) still audits every
    shipped string incl. compressed slides, caption and hashtags (:2850-2855). Do NOT add a
    `compressed_slots` mechanism — `quoted=()` + `CopyProvenance.copy_mode="compress"` + the panel_map
    `compressed: true` rows are the receipts.
  - `CopyCompressed` keeps `headline` + `hashtags` (verified models.py:416-419: a bound carousel's model
    chooses the deck's cover headline, caption and hashtags; compress authors the same three).
  - One-walk invariant is natural (verified :2157-2168, :2176-2180): creator/chrome/competitor strips run
    in `_offer_for` BEFORE any deck walk, so payload block and resolution walk both consume the same
    pre-stripped `offer.panels` / `offer.panels_original`.
  - Failed compress call -> existing :1717-1721 branch -> `_mapped_fallback` (:2511) = today's verbatim
    mapped deck, tagged `copy_degraded`. No new fallback code.
  - Module header gains the D54 paragraph (A20-reversal precedent :9-13). `_sibling_list` gets
    compress-call variant lines (written by `_call_compress`, not a flag inside the verbatim function).
- `models.py`: new `@dataclass CopyCompressed` (`asset_id, headline, caption, hashtags, slide_texts,
  through_line, narrative_arc`; position-indexed docstring) beside CopySelection (:401);
  `AssetRecord.copy_mode: str = "verbatim"` (FR-73 v2.3.0); panel_map field comment names `compressed`.
  `generate/__init__._record()`: copy `provenance.copy_mode` onto the record.
- `runner.py`: pass the key (:892); COPY stage line (:925 — "N call(s) -> N creative(s) quoted verbatim")
  becomes mode-aware.
- **Console surfaces (FR-296–299; all pinned by `tests/test_console_inventory.py`) — update together:**
  - `previews.py:356` — "Copy — N creative(s), quoted verbatim in the language..." -> mode-aware wording.
  - `preflight.py:605, :622` — "on-image text is quoted verbatim from the source post..." -> compress
    variant ("compressed from the source post's panels to the style's budget, in the post's own
    language") — this also satisfies FR-333's pre-flight display rule.
  - FR-297c/FR-298 provenance console block ("the exact bytes it quoted"): compressed creatives quote
    nothing — render a compress variant ("compressed from P<n>'s panels; see panel_map") instead of refs.
- Render-side doctrinal comments saying "the strings are a verbatim quote" (`generate/carousel.py:609,
  :1203`, `vision_check.py:36, :71`) stay behaviorally correct — touch wording to "locked contract strings
  (verbatim quote, or D54-compressed text)". No logic change.
- `budget.py`: one-line comment at :582 — copy calls billed per trend_key at the FULL `max_tokens.copy`
  completion ceiling (:609) so compress output cost is covered; the mode split adds a second call only for
  a MIXED-format group (impossible under the shipped all-carousel configs).

### Task C-c (prompt-engineer): prompts
- `prompts/humanizer_skill.md`: download `SKILL.md` from github.com/blader/humanizer **verbatim** (MIT;
  attribution + "engine never loads this file" note in `prompts/README.md`; NO `_ALLOWLIST` row — an
  allowlist row for a non-template is the drift `prompts_engine.py:156-159` warns against). Fallback if
  GitHub is unreachable: the local `humanizer` Claude skill carries the same instruction set — source the
  text from it and note the provenance.
- `prompts/copy_compress_system.md` + byte-matching built-in in `prompts_engine._BUILT_INS` (:1548+,
  template-parity rule): role statement (compress, never invent — the panels are the content authority),
  fenced `{{trend_texts}}` + `{{compress_panels}}`, per-panel budget obedience, language mirroring,
  empty-stays-empty, hard bans (@handles, URLs, added hashtags/emoji in slide text, creator names,
  competitor names, comment/follow CTA bait in the caption), and the **distilled humanizer subset**
  (~14 on-image patterns): no inflated importance; no sales language; no "not X but Y"; no forced
  triplets; no em-dash overuse; plain verbs (never leverage/harness/unlock/elevate); no stock AI words
  (delve/tapestry/landscape/realm/journey); no hedging/filler; no chatbot phrases; no editorializing
  intensifiers; no summary openers; no Title Case/ALL-CAPS/markdown-bold artifacts; no vague attribution;
  keep concrete numbers/tool names/claims — cut padding, never facts.
- `prompts_engine.py`: `_ALLOWLIST` row for the template (`niche_descriptor, brand_context, trend_texts,
  compress_panels, sibling_list, platform_conventions, brief_directives, text_budgets`; `compress_panels`
  allowlisted here and nowhere else); `build_context(..., carousel_copy_mode="verbatim")` threaded to
  `_budget_line` (:1408): compress-mode carousel branch states the REAL per-slide ceiling instead of the
  current "no per-slide ceiling" line (:1432-1444) — the flag is per-CALL, not per-run (the verbatim
  partition of a compress-mode run still passes "verbatim"). `prompts/README.md` mapping-table rows for
  both files (the table is the allowlist's documented source of truth).

**W2 barrier:** targeted pytest files green; `wc -l` checkpoint with per-task attribution.

---

## W3 — Styles (parallel to W2 after W1; S1+S2 MUST land in the SAME change — an enabled key the registry lacks is a pre-flight exit 2 on every run)

### S1 (prompt-engineer): new style `quiet-luxury-night-photoreal` in `prompts/styles.yaml`
Photorealistic candid night quiet-luxury; ONE scene resolved per M9 (the penthouse desk before a
floor-to-ceiling night skyline; the villa-kitchen inspiration frame is knowingly out of scope — DELIBERATE
comment, `:126-132` precedent). Fill to full registry DNA density:
- `subject_mode: scene_fixed`; single centered caption zone (vertical band 40-55%, medium-weight neutral
  sans, white, sentence case, subtle soft shadow, cap height 3-3.5%, 2-6 centred lines of 12-28 chars,
  never headline-scale); `format_affinity: [image, carousel, reel]`; `text_density: minimal`;
  `max_onimage_chars: {headline: 80, subline: 80, slide: 160, overlay: 60}`.
- Palette (roles + coverage): night black ground #0A0C10; charcoal surfaces #1C2026; warm-white skyline
  #E8E2D4 under 15%; amber practical #C89055 under 8%; white #FFFFFF text only.
- Image treatment: available light only, high-ISO sensor grain, crushed shadows, no HDR/studio/staging;
  screens dark or dim abstract glow, never readable.
- `visual_pacing`: FIXED per deck (room, window, camera height, palette, caption treatment); MAY CHANGE
  (crop distance, desk objects, skyline weather).
- `list_mode` (reflow_over_chars ~110, max_rows 4): compact centred column in the caption band, one source
  line per row, number welded to row, rows shrink together, no row dropped, region behind darkens.
- `per_format_guidance`: carousel_cover (widest view, caption at its one standard size — never scales up);
  carousel_slide (SAME room/window/skyline, one step closer at most, "THIS SCENE OUTRANKS THE SLIDE'S
  VISUAL BRIEF" clause per the anime-noir precedent at styles.yaml:502).
- Exclusions per T1.6/D-A conventions: platform chrome/watermarks/handles/counters; identifiable faces
  (people from behind only); competitor/creator/platform marks (TOOL MARKS line sanction respected);
  legible text outside the caption zone; graphic furniture (stickers, arrows, gradients, flares).

### S2 (python-pro, SAME change): `styles.enabled` in the three brand configs
Replace the commented block (`hypedigitaly.yaml:101-102`, `-fresh:102-103`, `-cs:117-118`) with:
```yaml
styles:
  enabled: [anime-noir-statement, letterpress-print-carousel, meme-caricature-panels, quiet-luxury-night-photoreal]
  # meme-caricature-panels is carousel_role: slides_only — inert while this config runs
  # carousels only (operator: keep for now; activates if image posts return).
  # hypelead-brand-card deliberately absent: branding.enabled is false here (brand_ok drops
  # it anyway); branded entries sign through the TEXT block on any style (FR-318/FR-292).
```
Effective carousel rotation = 3 styles; `validate()` yields at most the repeat-look warning, no error
(verified `styles.py:509-536`).

**W3 barrier:** any $0 entry (`--list-monitors`) loads without exit 2; registry parses (9 styles).

---

## W4 — Tests + conductor merges (test-automator; after W2+W3)

- `tests/test_copywrite.py`: compress call uses new schema/template; mixed group splits into two calls;
  1:1 alignment (short/long model list padded/truncated; source-empty stays "" even when the model
  answered); drop taxonomy identical to verbatim; scrub (handle/URL blanks + warns; competitor stripped
  fail-closed); backstop trim tags `text_trimmed`; panel_map rows (`compressed: true`, `source_text` ==
  shipped == `CopySet.slide_texts[i]`, `source_text_original` == source, `ref_label` == ""); provenance
  `copy_mode == "compress"`; failed call -> verbatim mapped deck + `copy_degraded`; **verbatim mode
  byte-identical regression**.
- `tests/test_copy_verbatim_filter.py`: header claims amended (compressed creatives ship `quoted=()` and
  are exempt from the substring audit; the blocklist half is mode-independent and fail-closed) + sentinel:
  a competitor brand seeded into a compress payload never reaches CopySet or the assembled render prompt.
- `tests/test_config.py`: default/parse/override/bad-value refusal; `--copy-mode` override.
- `tests/test_menu.py`: six-step counter; copy_mode step Enter-keeps/pick/help; wizard_help sections exist.
- `tests/test_styles.py`: registry parses with 9 styles; new style fields valid (list_mode, budgets <=
  config, carousel-affine); the 4-key enabled list validates clean under brand hypelead; meme-caricature
  never assigned to a carousel.
- `tests/test_prompts_engine.py`: allowlist row; `compress_panels` unresolvable in every other role;
  `_budget_line` compress-carousel branch states the real ceiling.
- `tests/test_template_parity.py`: new template file/built-in parity (add to roster if enumerated).
- Gauntlet dry-run test (nearest gauntlet test home): `DeckContract` expected body_lines for a compressed
  deck == the compressed `slide_texts` (the one-walk invariant end to end).
- Gallery test: `compressed` marker survives into meta.yaml/card.
- **`tests/test_console_inventory.py`** (pins every console surface W2 changes): update/extend pins for
  the mode-aware COPY stage line (`runner.py:925`), the previews copy header (`previews.py:356`), the
  pre-flight verbatim hint (`preflight.py:605/:622`), and the FR-297c provenance block's compress variant.
  78-column / no-ANSI / `->`-only house rules apply to the new wordings.
- `tests/test_preflight.py` / `tests/test_previews.py`: same wording updates if those lines are asserted.
- **Conductor merges (main thread):** CLAUDE.md glossary ("Verbatim copy", "Panel map") gains the D54
  carve-out; "Last updated" line; NAVIGATION.md updated (stale navigation is a bug).

**W4 barrier:** full `pytest` green; `wc -l` with attribution.

---

## W5 — Live verification ladder (operator present; cheapest first)

1. `.venv/Scripts/python.exe -m pytest tests/ -x -q` (venv python — bare `python` lacks `mcp`).
2. **$0**: `run.bat --list-monitors`, `run.bat --preview-sources` — pre-flight loads under the new configs.
3. **LLM-only spend**: `run.bat --preview-analysis --config hypedigitaly` (compress pinned in config):
   4-style assignment table (3 effective), compressed slide texts within min(config, style) budgets
   (160/180/300 by style), source language kept, no handles/URLs, humanized tone.
4. **ONE paid run, low cap**: `run.bat --config hypedigitaly --carousels 2 --budget 2`. Inspect:
   - `meta.yaml`: `copy_mode: compress`; rows 1:1 with `source_position`; `compressed: true`;
     `source_text_original` long / `source_text` within budget; no `copy_not_verbatim` tag.
   - `events.jsonl`: rendered compress prompt; any `compress_scrub` / `text_trimmed` events.
   - Gallery card: meaning preserved vs the source strip; no walls of text; caption humanized, CTA-free.
   - Gauntlet report: zero `translated` / `identity_leak`; `invented_text` reduced vs the baseline runs
     (fewer wordless frames); `missing_text` ABSENT (presence = slide_texts/panel_map divergence — stop).
5. Closeout: write `plans/SESSION-H-CLOSEOUT.md` (waves green, measurements, deviations, wc -l).

---

## Recheck verdicts (edge cases explicitly accounted for — verified against code 2026-08-20)

- `slide_count` > source panel count -> positions beyond the source ship wordless (`:2176` pattern; the
  compress walk mirrors it). Model output list shorter/longer than `slide_count` -> pad/truncate engine-side.
- Model returns text for a source-empty/dropped position -> DISCARDED + warned (compression fills no
  vacuums; the `invented_text` gauntlet contract stays honest).
- Unbound carousels (no post) and override briefs in a compress-mode run -> untouched paths
  (`_selected_deck` / `_free_text`); `_compress_wanted` requires `_panel_mapped`.
- Empty compress partition (mode on, nothing panel-mapped) -> no compress call issued.
- Compress-call failure -> existing `:1717-1721` branch -> `_mapped_fallback` (:2511) = today's verbatim
  mapped deck, tagged `copy_degraded`. Deterministic, $0 extra.
- Quick menu path (`_QUICK_STEPS = ("confirm",)`, menu.py:78) -> untouched; the new step is wizard-only.
- `build_context`'s mode flag is per-CALL, not per-run.
- Hashtags and caption from a compress payload are blocklist-audited by the unchanged `_verify` half 2
  (:2850-2855). CTA-bait stripping in captions is prompt-enforced; gallery review is the check.
- `copy_source_refs` empty for compressed decks -> meta writer already handles empty refs (free-text
  precedent, CopyProvenance docstring :454-455).

## Risks

1. **`translated` blocks always** — language drift in compression kills a deck. Mitigation: per-creative
   language-mirror line in `compress_panels`; top W5 check. Engine-side same-script heuristic = follow-up.
2. **panel_map/slide_texts divergence -> gauntlet `missing_text`**: closed structurally (one-walk
   `_compressed_deck`; both sides consume the same pre-stripped `offer.panels`) + the dry-run parity test.
3. **Estimator**: verified safe — completion billed at the full `max_tokens.copy` ceiling per group
   (budget.py:609); prompt side comparable to the verbatim candidate table. Only the mixed-group
   split-call count needs the one-line comment (W2/C-b).
4. Notion influence, trend_history/no-repeat, through_line/narrative_arc/motion_beat: untouched.
5. `PANEL_SANITY_CHARS` (1500) stays an INPUT guard even in compress mode.

## Critical files

- `hypesocials/copywrite.py` — mode threading, group split, `_call_compress`, `_compressed_deck` (core)
- `prds/10-pipeline.md` — FR-99/100/101/302/303/304 + FR-331 (the D15 gate)
- `hypesocials/prompts_engine.py` — allowlist, `_BUILT_INS`, `_budget_line` compress branch
- `prompts/styles.yaml` (new style) + `configs/*.yaml` (`styles.enabled`, `carousel_copy_mode: compress`)
- `hypesocials/config.py`, `cli.py`, `menu.py` + `wizard_help.md`, `models.py`, `runner.py`,
  `previews.py`, `preflight.py`, `budget.py`
- `prompts/copy_compress_system.md` (new), `prompts/humanizer_skill.md` (vendored), `prompts/README.md`
