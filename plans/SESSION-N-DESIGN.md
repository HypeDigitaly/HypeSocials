# SESSION N — design contract (v2.7.0 / D63): output language + final run

**Authority:** `plans/xmasterplan-render-quality-and-language.md` §5, §7 "SESSION N", §9; `plans/SESSION-M-CLOSEOUT.md`
"What SESSION N must do first". This file is the ONE interface every SESSION N executor builds against. Where
the master plan and this file disagree on a name or a signature, THIS file wins (it was written after reading
the shipped bytes); where they disagree on a RULE, the master plan wins and the conductor is told.

Read first: `CODING_GUIDELINES.md`, `CLAUDE.md`, `plans/SESSION-M-CLOSEOUT.md`. Standing rules (every
executor): `.venv/Scripts/python.exe` only; tests never touch real `logs/` or `output/`; no real API keys;
D30 secrets; every console line ≤ 78 chars; never shorten a docstring/comment/error; every `prompts/*.md`
has a byte-identical twin in `prompts_engine._BUILT_INS` (the CONDUCTOR splices twins — executors do not
edit `_BUILT_INS`); `AGENTS.md` is a hardlink to `CLAUDE.md` (conductor rebuilds it).

---

## 0. Operator decisions (locked, plan §1)

- **Translate only non-target posts.** A post already in the platform's configured language keeps byte-exact
  source words. Foreign topics are LET IN once translation exists.
- **Mode is config + CLI only** (`run.copy_language_mode`, `--copy-language`). No wizard step; shown on the
  confirm screen. Six wizard steps stay six (NFR-16).
- **Engine default `source`** (D58 shape: a default that re-behaves configs nobody opted in is wrong).
  The three brand configs pin `target`. `hypedigitaly-cs.yaml` flips symmetrically → Czech.
- **Translate BEFORE the auto budget test.** `copywrite._rows_over_budget(texts, budget)` is pure and runs
  on the TRANSLATED deck's texts.
- **No new LLM call for language detection.** Virlo sends `intelligence.language_detected` free; the vision
  pass may add a deck-level reading; otherwise the engine says "unknown" and ships verbatim with a warning.
  **No stopword/diacritics heuristic** (`topic_filter.fuzzy_strip` records why).

---

## 1. Vocabulary

| Name | Value / shape | Owner |
|---|---|---|
| `RunConfig.copy_language_mode` | `Literal["source", "target"] = "source"` — beside `carousel_copy_mode` (`config.py:237`) | Agent C |
| `--copy-language {source,target}` | CLI flag, flag-over-file, `applied.append("run.copy_language_mode=…")` | Agent C |
| `SourcePost.language: str = ""` | ISO 639-1 code from Virlo's `intelligence.language_detected`, normalised by `topic_filter.language_code` (`"English"`→`en`, `"unknown"`→`""`) | Wave 1 (9a) |
| `SourcePost.multilingual: bool = False` | Virlo's `intelligence.is_multilingual` | Wave 1 (9a) |
| `SlideIntel.language: str = ""` | the vision pass's ONE deck-level reading (new optional top-level key on `slide_intel._SCHEMA`, NOT on `_SLIDE`) | Wave 1 (B) |
| `CopyTranslated` (models.py) | `asset_id, headline, caption, hashtags, slide_texts, through_line, narrative_arc, source_language` = `CopyCompressed` + `source_language: str = ""` | conductor skeleton, Agent A docstring |
| `CopyProvenance.copy_language: str = "source"` | `"target"` ONLY when a translation actually shipped on the deck | conductor skeleton, Agent A |
| `CopyProvenance.source_language: str = ""` | the ladder's answer for the bound post, recorded on EVERY bound deck where known, both modes | conductor skeleton, Agent A |
| `AssetRecord.copy_language`, `.source_language` | same two, straight into `meta.yaml` (dataclass field order, beside `copy_mode`) | conductor skeleton, Agent D (`generate/__init__._record`) |
| `panel_map[*].translated: bool` | new row key on EVERY walk (`_mapped_deck`, `_compressed_deck`, `_auto_deck` inherits, `_translated_deck`); `True` only on a row whose shipped text is the model's translation | Agent A |
| `DegradationTag.COPY_NOT_TRANSLATED = "copy_not_translated"` | translation was WANTED (mode `target`, bound deck, foreign language known) and the deck shipped its source language anyway (translate call failed → `_mapped_fallback`; or the creative ended on `_refused`/a degrade path) | conductor skeleton |
| `DegradationTag.TRANSLATE_LENGTH_DRIFT = "translate_length_drift"` | a shipped translated line measured < 0.5× or > 2.0× its source panel's length; audit only, ships (A20 polarity) | conductor skeleton |
| `prompts/copy_translate_system.md` | ELEVENTH global role template / SIXTEENTH shipped role; `SHIPPED_COUNT 15 → 16` | prompt-engineer (file), conductor (twin + registry rows) |
| `{{translate_panels}}` | the translate work order — allowlisted for `copy_translate_system.md` ALONE, on the `compress_panels` precedent; added to `models.PLACEHOLDERS` | conductor (allowlist/PLACEHOLDERS), Agent A (`_translate_block`) |
| `write_copy(..., copy_language_mode="source", post_languages=None)` | `post_languages: Mapping[str, str]` = `{post_id: SlideIntel.language}` from the runner | conductor skeleton, Agent A (`_Run` fields), Agent D (runner call site) |
| `topic_filter.language_code(value) -> str` | PUBLIC name for today's `_language_code` (keep `_language_code = language_code` alias) | Wave 1 (9a) |
| `topic_filter.target_languages(cfg) -> set[str]` | PUBLIC name for today's `_target_languages` (alias kept) | Wave 1 (9a) |
| `slide_intel.counter_line(text, *, position=0)` | FR-313: when `position > 0`, a line that is ONLY a 1–2-digit numeral equal to `position` (any zero-padding) is ALSO a counter line | Wave 1 (B) |

---

## 2. The language ladder (9c) — `copywrite._source_language(offer, run) -> str`

1. `offer.post.language` (Virlo, free) →
2. `run.post_languages.get(post_id, "")` (the vision pass's deck-level reading) →
3. `run.topic_languages.get(entry.trend_key, "")` (the FR-294 screen's `Verdict.language` for the post's topic — added after the SESSION N code review: under `target` the LANG skip is off, so the evidence that would have skipped the topic must reach the translator) →
4. `""` = unknown.

Codes are two-letter, already normalised at the adapter (rung 1) and by `language_code` at rung 2.
Recorded as `CopyProvenance.source_language` on every bound deck (`_resolve`, `_compressed`, `_auto`,
`_mapped_fallback`, `_translated`) whether or not anything translates.

---

## 3. When a creative translates — `copywrite._translate_wanted(entry, offer, run) -> bool`

All of: `run.copy_language_mode == "target"` · `_panel_mapped(entry, offer)` · ladder answer `lang`:

- `lang == ""` → **False**; ONE warning per creative `translate_language_unknown` naming the asset and the
  post id ("ships verbatim in whatever language the post is in; Virlo sent no language and the vision pass
  read none").
- `lang == entry.language` (the platform's configured language — `run.languages[platform]`) → **False**, no
  call, quoted verbatim (byte-identical to a `source`-mode run), `source_language` recorded.
- otherwise → **True**.

Images, reels, override briefs, unbound decks: never (scope = `_panel_mapped`, plan 9d). Pre-flight warns
about them under `target` mode (§9 below).

---

## 4. The partition in `_write_group` (9g — one call per creative, never grouped)

```
translating = {id for entry in askable if _translate_wanted(...)}
compressing = {id for entry in askable if _compress_wanted(...) and id not in translating}
selecting   = askable − compressing − translating
```
Calls: `_call_copy(selecting)` + `_call_compress(compressing)` as today, PLUS one `_translate_and_fit(group,
entry, run, offers)` per translating entry, all under the same `asyncio.gather`. `_call_copy`,
`_call_compress`, `_compressed`, `_auto`, `_resolve` and their tests are UNTOUCHED (branches 1–4 of
`_sibling_list` untouched — the pinned tests at `test_copywrite.py:1000,:1015,:1588,:1590,:1609` and
`test_prompts_engine.py:67` green unchanged are the regression proof).

### 4a. `_call_translate(group, entry, run, offers) -> dict[str, dict]`
Shaped like `_call_compress`: role `COPY_ROLE`, template `_TRANSLATE_TEMPLATE = "copy_translate_system.md"`,
carrier turn `_TRANSLATE_CARRIER_TURN`, schema `_translate_schema()` from `json_schema_for(CopyTranslated,
exclude={"asset_id"})`, same `copy_prompt_failed` → `{}` door, `_answers` envelope.
`build_context(... carousel_copy_mode=MODE_VERBATIM ...)` so `_budget_line` takes its verbatim branch —
**the rendered translate prompt never contains `(at most`** (test). `sibling_list` = FIFTH branch of
`_sibling_list` (`translate_to: str = ""` keyword): `· translate post P<n>'s panels from <src> to <target>;
keep every fact, number, name and claim; never shorten, never summarise`.
`context["translate_panels"] = _translate_block(entry, offer, run)`.

### 4b. `_translate_block(entry, offer, run) -> str`
```
CREATIVE <asset_id> — translate to: <target code> (<English name>); source language: <src code>
caption source: <that post's own caption, or the "(none …)" sentence>
1. <source panel 1, folded, IN FULL, no budget>
3. <source panel 3>
```
Only ADMITTED positions (`_panel_verdict` == ""), numbered by SOURCE POSITION, `_folded`, never
`_display`-truncated. No per-line budget — ever.

### 4c. `_translate_field(text, brands, entry, run, *, where, blanked_into=None) -> tuple[str, bool]`
`(text, stripped)`. **No `budget` parameter** (`inspect.signature` test). Gates, in order: blocklist strip
(fail-closed, `apply_blocklist`), FR-319 social-mark → BLANK (not edit), then the ONLY length gate:
`len(out) > PANEL_SANITY_CHARS` → `""` + `translate_over_sanity` warning. No `trim_words`, no
`text_trimmed` from a slide. (The cover HEADLINE is ours and keeps its budget: run it through the existing
`_compress_field(..., offer.budgets["headline"], ...)`.)

### 4d. `_translated_deck(entry, payload, offer, run, brands) -> _PanelDeck`
ONE walk, `_compressed_deck`'s shape (same `_panel_verdict` gate on the SOURCE panel first, same three
drop-reason warnings, position-preserving). Per admitted position:
- model line → `_translate_field`; empty → that slide renders WORDLESS (plan 9g), collected into ONE
  `translate_no_text` warning per creative.
- **already-target backstop (9f):** if `payload["source_language"]` (normalised) == `entry.language` and the
  line ≠ source bytes → ship the SOURCE bytes, `translated: False`, one `translate_already_target` warning
  per creative.
- **length-ratio audit (9e):** `len(line) / len(source)` < 0.5 or > 2.0 → `translate_length_drift`
  warning naming the slide and both lengths, `deck.drifted = True` (new `_PanelDeck` field), ships.
- a model line for a DROPPED position → discarded, `translate_invented_text` warning.
Row: `source_text` = what ships, `source_text_original` = pre-layer-3 source panel (as every walk),
`ref_label ""`, `drop_reason`, `creator_stripped`, `chrome_counter_stripped`, `truncation_suspect`,
`compressed: False`, `translated: True` where the translation shipped.

### 4e. `_translate_and_fit(group, entry, run, offers) -> _Translation | None` (async)
```
payload = (await _call_translate(...)).get(id)        # None → caller: _mapped_fallback + COPY_DEGRADED + COPY_NOT_TRANSLATED
deck    = _translated_deck(...)
fit     = None
if run.carousel_copy_mode in (MODE_AUTO, MODE_COMPRESS):
    budget = offer.budgets.get("slide", 0)
    over = (_rows_over_budget(deck.texts, budget) if MODE_AUTO
            else [i for i, t in enumerate(deck.texts, 1) if t.strip()])
    if over:
        offer2 = dataclasses.replace(offer, panels=tuple(deck.texts), stripped_panels=frozenset())
        comp = await _call_compress(group, [entry], run, {id: offer2}, only={id: over})
        fit = (comp.get(id), offer2, over)            # comp.get(id) None → compress failed
return _Translation(payload=payload, deck=deck, fit=fit)
```
`_rows_over_budget` MUST be called on `deck.texts` (the translated strings) — a test asserts the call order
(translate call first, then the compress call, and the compress block lists the ENGLISH panels).

### 4f. `_translated(entry, translation, offer, group, run) -> _Written`
- Deck: if `fit` and its payload is not None → `deck2 = _auto_deck(entry, comp_payload, offer2, run, brands,
  over)`; then for every row *i*: `row["translated"] = translation.deck.panel_map[i]["translated"]`,
  `row["ref_label"] = ""`; `deck2.refs = {}`; `deck2.stripped |= translation.deck.stripped`. `copy_mode` =
  `MODE_AUTO` if any row `compressed` else `MODE_VERBATIM` (auto mode) / `MODE_COMPRESS` (compress mode).
  If `fit` exists but its payload is None → ship `translation.deck` uncompressed, `translate_compress_failed`
  warning, tag `COPY_DEGRADED`, `copy_mode: verbatim`. No `fit` → `translation.deck`, `copy_mode: verbatim`.
- Caption / hashtags / headline ALWAYS from the TRANSLATE payload (the compress call's caption is ignored):
  headline via `_compress_field(..., offer.budgets["headline"])`, caption + hashtags via the existing
  `_compressed_caption(payload, offer, entry, run, brands, own_words)`.
- Tags: `NO_ONIMAGE_TEXT` (nothing on any slide and no headline), `TEXT_TRIMMED` (headline or a compressed
  splice trimmed), `COMPETITOR_STRIPPED`, `TRANSLATE_LENGTH_DRIFT` if `drifted`.
- `CopyProvenance(post_id, refs={}, panel_map, source_panel_count, copy_mode, copy_language="target",
  source_language=<ladder>)`, `quoted=()` → `_verify` half 1 self-skips, blocklist half still runs.

### 4g. Failure and degrade paths
- Any entry in `translating` whose `_Written` did NOT come from `_translated` (translate call `{}` →
  `_mapped_fallback`; or `_refused`) gets `DegradationTag.COPY_NOT_TRANSLATED` appended in `_write_group`,
  beside whatever the path already earned (`COPY_DEGRADED` on the fallback). Its provenance keeps
  `copy_language="source"` and the ladder's `source_language`. Console: loud, like `copy_degraded`
  (Agent D, runner). Gallery badge (the enum loop already renders any tag).
- `_offer_caption` / `_refused` captions ship source language — a known bounded gap, stated in FR-343.

### 4h. Events (all `_warn`): `translate_language_unknown`, `translate_no_text`, `translate_already_target`,
`translate_length_drift`, `translate_invented_text`, `translate_scrub`, `translate_over_sanity`,
`translate_compress_failed`, `translate_list_truncated`, `copy_not_translated`.

---

## 5. Bind-time screen under `source` mode (9b) — Agent C, `plan.py`
`fresh_source_post(trend, config, burnt, *, platform)` gains a FOURTH eligibility test, applied ONLY when
`config.run.copy_language_mode == "source"`: skip a post whose `post.language` is non-empty and not in
`topic_filter.target_languages(config)`. The SAME screen in `_carousel_supply`. Under `target` the test is
off (foreign posts are bound and translated). Log the skip like the other three (`plan` events vocabulary).
Beware an import cycle `plan ↔ topic_filter`; if one exists, move `target_languages` to `config.py` as
`Config.target_languages()` and have `topic_filter` call it.

## 6. Topic filter (9g) — Agent C, `topic_filter.py`
The engine LANG skip (`_apply`, `:544-548`) fires ONLY under `copy_language_mode == "source"`. Under `target`
the model's `language` is still recorded on the verdict and nothing is skipped for it. Rewrite the module
docstring `:30-37` and `_apply`'s `:513-517` — "there is no translation path" is false after D63; the new
sentence says translation exists for bound carousel decks under `target` and the screen therefore only
skips off-language topics when the run keeps source language.

## 7. Config / CLI / menu — Agent C
- `config.py`: field + comment (D58 shape: engine default `source`; brand configs pin `target`); `_coerce`
  Literal refusal at load (same as `carousel_copy_mode`).
- `cli.py`: `--copy-language` beside `--copy-mode` (`:49,:81-85,:126-128,:164-168,:302-307` shape).
- `menu.py:340-350`: one more `facts` line when the plan has carousels: `copy language: target - bound decks
  translated to <lang>` / `copy language: source - posts keep their own language` (`_fit`, ≤ `_FACTS_WIDTH`).
  `hypesocials/wizard_help.md`: a paragraph under `## copy_mode` (or a sibling `## copy_language` section
  if the menu reads one) saying the language mode is config/CLI only.
- Four configs: `default.yaml` documents `copy_language_mode: source` beside `carousel_copy_mode`; the three
  brand configs pin `target`. `hypedigitaly-cs.yaml`: rewrite the comments at `:127` ("what ships is English
  text under a Czech language slot") and `:156` — under `target` an English bound deck IS translated to Czech.

## 8. Pre-flight — Agent C, `preflight.py`
New `_check_language_mode(config, entries, hints/warnings)` beside `_check_language_hint` (`:600-641`):
under `target`, when the plan holds images / reels / override carousels, ONE warning: those creatives ship
their source language — translation reaches bound carousel decks only (FR-345). ≤ 78 chars per line. Add
a `test_preflight.py` arm (the `:366` neighbourhood shape).

## 9. Estimator — Agent D, `budget.py` `_llm_lines` (`:679-760`)
Under `target`: one extra `copy` call per non-override carousel, UNLESS its bound post's language is known
AND equals the entry's language (D11: an unknown language is priced — the vision pass may still supply
one). Line label `translate (1 call per deck)`; prose at `:693-695` rewritten (the (topic × language)
grouping sentence gains the per-creative translate exception); `copy_split_allowance` (`:754-760`) widened
by the translating count. `test_budget.py:180,:268,:270,:927` build `PlatformConfig`-shaped objects — read
them before touching the config surface.

## 10. Runner / previews / gallery / record — Agent D
- `runner.py`: `write_copy(..., copy_language_mode=config.run.copy_language_mode,
  post_languages={pid: intel.language for pid, intel in session.slide_intel.items()} or None)`.
  COPY closing line (`:1197-1210`, `_stage` body 54 cols) gains a translated count; keep every shape ≤ 78.
  `copy_not_translated` is LOUD on the console exactly like `copy_degraded` (find the `copy_degraded`
  console site and add the sibling). Launch summary (`:2195-2207`): a NEW line, only when the plan has
  carousels: `  language    copy: target · bound decks translated to en` / `  language    copy: source ·
  posts keep their own language` (≤ 78). Provenance block (`:1905-1922`): a `translated` row shape
  `translated P1 @handle views <id> <src>-><tgt> -> panel_map`.
- `previews.py` `_copy_block` / `_source_rows` (`:520-600`): header counts `N deck(s) translated`; row kind
  `translated` (wider than `_ROW_LABEL` like `compressed` — `_rows` already guarantees a separator).
- `outputs/gallery.py`: `_any_translated(meta)` on the `_any_compressed` pattern; a card-level line
  `Copy: translated from de to en — …`; a per-row chip `translated from de` beside the `compressed from N
  chars` chip (`:421-434`); the `copy_language`/`source_language` facts in the provenance header
  (`:500-545`). Tolerant of pre-D63 documents (no keys → nothing printed).
- `generate/__init__.py` `_record` (`:930-1003`): `copy_language=prov.copy_language if prov else "source"`,
  `source_language=prov.source_language if prov else ""`; `_panel_map` (`:1076+`) must pass `translated`
  through (check whether it copies a fixed key list).

## 11. FR-313 bare numeral (SESSION M must-do #3) — Wave 1 agent B (`slide_intel.py`) + Agent A (`copywrite.py`)
Fixture: `output/20260820_234620_j867/Tk_car_claude-ai-for-coding-development_03/meta.yaml` —
`panel_map[*].source_text_original` = `"Jason AI\nby Reply\n01\nPersonal Assistant\n…"` on every one of 7
panels, `counter.detected: false`.
- **B:** `_BARE_TOKEN = re.compile(r"^\s*(\d{1,2})\s*$")`. `_bare_candidates(panel_texts)`: a LINE that is
  only a 1–2-digit numeral (≤ `_MAX_COUNT`) → `_Candidate(position, number, spec=CounterSpec(pad=_pad(d),
  numerator_only=True))`. **Bare candidates take part in RULE 2 ONLY** (`number == position` on ≥ 2 distinct
  slides); rules 1, 3 and 4 never see them (a stray content numeral must not manufacture a constant offset).
  `counter_line(text, *, position=0)`: `position > 0` and the line is a bare numeral equal to `position` →
  True. Docstrings say why bare numerals are the weakest shape and why the position is required.
- **A:** `_strip_counter_lines(text, *, position=0)` forwards `position` to `counter_line`; `_offer_for`
  passes `position=ordinal` at the `:999` call. The dropped line lands in `chrome_counter_panels` /
  `chrome_counter_stripped` exactly as a paired counter does; `panel_counter_stripped` warning unchanged.
  Test on the j867 panels: all seven `01…07` lines dropped, `detect_counter` → `RULE_POSITIONAL`, and a
  panel reading `"5 tools I use\nto ship faster"` keeps every byte.

## 12. Registry (SESSION M must-do #4) — prompt-engineer, `prompts/styles.yaml`
Run `20260821_010802_0wfg` put `big-number-editorial` on 5 of 9 decks; the ASSIGN receipts read "business
hacks/tutorial hook suggests numbered…", "12 one-tool-per-panel reviews, longer text than…", "business hacks
deck, one item per panel though…" — the profile is claiming ANY one-item-per-panel deck. Narrow
`big-number-editorial.match_profile` to decks whose panels OPEN on their own ordinal (a numbered step per
panel — the FR-341 handoff row), and hand the rest off explicitly: unnumbered short one-statement panels →
`photo-poster-statement`; one tool/product per panel, review-length text → `neon-glass-dark`; corporate
short rows → `aurora-white-deck`. Adjust those three profiles so each CLAIMS what it is handed (profiles
stay mutually exclusive by archetype). Prose only; no DNA field changes. After EVERY edit:
`plans/tools/measure_one_style.py <key>` (owned ≤ 4,700 · style_dna ≤ 2,000 · cutA ≤ 1,540 · slackB ≥ 60),
then `plans/tools/registry_contract_check.py` → `TOTAL 0` and `plans/tools/measure_prompt_fit.py` →
`0 of 26 outside target`. Record the numbers in the report.

## 13. Prompts — prompt-engineer
- **`prompts/copy_translate_system.md` (new).** Sibling of `copy_compress_system.md` in structure (ROLE ·
  STANDING CONTEXT · MATERIAL as DATA with `{{trend_texts}}` and `{{translate_panels}}` fenced · THE PANEL
  BLOCK AND ITS NUMBERS · the rules · HOW IT MUST SOUND (the same fourteen bans, verbatim) · HARD BANS ·
  CAPTION/HASHTAGS/HEADLINE · free-text fields · SIBLINGS · `{{text_budgets}}` · `{{platform_conventions}}`
  · `{{brief_directives}}` · OUTPUT). Placeholders EXACTLY: `niche_descriptor`, `brand_context`,
  `trend_texts`, `translate_panels`, `sibling_list`, `text_budgets`, `platform_conventions`,
  `brief_directives`. The rules that differ from compress: (1) TRANSLATE, never shorten, never summarise,
  never "compress" — every fact, number, name, claim, line break and list item survives; a translation is
  allowed to be LONGER than its source; (2) a position NOT printed gets `""`; (3) a panel ALREADY in the
  target language comes back BYTE-IDENTICAL and `source_language` says so; (4) `source_language` = the
  two-letter code of the language the panels are written in; (5) the caption is translated AND humanised
  (CTA bait removed, as compress); hashtags translated/topical; headline = the deck's cover line in the
  target language within the headline ceiling. The JSON shape in OUTPUT: `asset_id, headline, caption,
  hashtags, slide_texts, through_line, narrative_arc, source_language`. Target ≤ 6,500 chars.
- **`prompts/slide_intel_question.md`:** one sentence asking for a deck-level `language` (two-letter ISO 639-1
  code of the language the slides' words are written in, `""` when there are no words or you cannot tell;
  the majority language when mixed). Agent B adds the key to `_SCHEMA` and `SlideIntel`; the conductor
  splices the twin. Keep the template otherwise byte-identical.
- **`prompts/README.md`:** `copy_translate_system.md` in the layout (eleventh global / sixteenth shipped),
  `{{translate_panels}}` in the placeholder table + the per-role allowlist table + the engine-built-lines
  list (same three places `compress_panels` appears), the "two copy roles never share a slot" paragraph
  becomes three roles, editing rule "do not let `copy_translate_system.md` become a shortening brief".

## 14. PRDs (Wave 0N) — technical-writer
Version **v2.7.0**, decision **D63**, date 2026-08-21. Amend BEFORE code (D15).
- `00-overview.md`: D63 paragraph after D62 (`:231`); decisions table row `:237` — fix `v2.5.4` → `v2.7.0`
  and tick ✅ with the FR list; TL;DR bullet (plain English: "translate only posts not in your language;
  posts already in it stay word-for-word"); FR-Range Registry (`:284-297`) — FR-343 → 10-pipeline, FR-344 →
  50-promptcraft, FR-345 → 30-configuration, FR-346 → 40-outputs; the per-FR summary block after `:304`;
  "Next fresh block" `:327` (FR-343–346 now filled; FR-356+ stays next); amendment-log entry at the TOP of
  the log (`:342` shape, v2.7.0); header line `:3` shape → a v2.7.0 line above it.
- `10-pipeline.md`: **FR-343 translate pipeline** (ladder, `_translate_wanted`, one call per creative, the
  no-shortening guarantee, the already-target backstop, length-drift audit, wordless on empty, translate →
  auto ordering, fail-open to the verbatim mapped deck + `copy_degraded` + `copy_not_translated`, known
  bounded gaps: degrade-path captions ship source language, images/reels/override never translate); amend
  **FR-294** (`:149` the LLM screen: the LANG skip is mode-gated — only under `source`), **FR-100/101**
  (`:182`: translation is the THIRD copy boundary beside verbatim and compress — the one path where a
  string may legitimately be LONGER than its source), **FR-313** (bare-numeral rule 2 + admission strip).
- `20-integrations.md`: amend **FR-293** (`:110-117`: `SourcePost.language` / `.multilingual` from Virlo's
  `intelligence.language_detected` / `is_multilingual`, forwarded by the wrapper's two normalisers),
  **FR-306** (`:376`: optional deck-level `language`).
- `30-configuration-and-run.md`: **FR-345** (`run.copy_language_mode`, CLI `--copy-language`, confirm-screen
  line, launch-summary line, pre-flight warning, brand configs pin `target`, cs flips, engine default
  `source`; NFR-16 six steps unchanged); amend the `§2` run-key list, the menu §4 confirm notice, the CLI §5
  flag table; **FR-341** handoff table row for `big-number-editorial` narrowed.
- `40-outputs-and-logging.md`: **FR-346** (`meta.yaml.copy_language`, `source_language`, per-row
  `translated`, gallery chips/lines, console COPY line and provenance row, previews); amend **FR-73**
  (`:25`: `copy_language`, `source_language`, the two new tags `copy_not_translated` and
  `translate_length_drift` in the degradation vocabulary).
- `50-promptcraft.md`: **FR-344** translate playbook (eleventh global template, `{{translate_panels}}`
  allowlisted alone, the rules above, `SHIPPED_COUNT 16`); amend the §2 roster (eleven → twelve globals,
  fifteen → sixteen shipped roles), **FR-181** hot-editing list.
- `PRD.html`: header line + one `dcard` for D63 under `#decisions` (pattern: the D62 card).
Keep every existing FR number and every existing sentence that is still true; add, never rewrite history.

---

## 15. Waves and ownership (disjoint path sets — single writer per file)

| Wave | Agent | Owns |
|---|---|---|
| 1 | python-pro "9a" | `hypesocials/virlo_mcp/server.py`, `hypesocials/sources/virlo.py`, `hypesocials/models.py` (SourcePost ONLY), `hypesocials/topic_filter.py` (ONLY the two public renames + aliases), `tests/test_virlo_topics.py`, `tests/test_virlo_mcp*.py` |
| 1 | python-pro "B" | `hypesocials/sources/slide_intel.py`, `tests/test_slide_intel.py` |
| 1 | prompt-engineer | `prompts/copy_translate_system.md`, `prompts/slide_intel_question.md`, `prompts/README.md`, `prompts/styles.yaml` |
| 1 | technical-writer | `prds/*` |
| — | conductor | twins in `prompts_engine._BUILT_INS`, `_ALLOWLIST` row, `GLOBAL_TEMPLATES`, `PLACEHOLDERS`, `SHIPPED_COUNT`, interface skeleton (§1) |
| 2 | python-pro "A" | `hypesocials/copywrite.py`, `hypesocials/models.py` (CopyTranslated/CopyProvenance docstrings), `tests/test_copywrite.py`, `tests/test_models*.py` |
| 2 | python-pro "C" | `hypesocials/config.py`, `hypesocials/cli.py`, `hypesocials/menu.py`, `hypesocials/wizard_help.md`, `hypesocials/preflight.py`, `hypesocials/plan.py`, `hypesocials/topic_filter.py`, `configs/*.yaml`, their tests |
| 2 | python-pro "D" | `hypesocials/budget.py`, `hypesocials/runner.py`, `hypesocials/previews.py`, `hypesocials/outputs/gallery.py`, `hypesocials/generate/__init__.py`, their tests (`test_budget`, `test_runner*`, `test_console_inventory`, `test_previews`, `test_gallery`, `test_generate*`) |

Barrier after every wave: `.venv/Scripts/python.exe -m pytest tests/ -q` green (baseline **1762 passed**),
`find hypesocials -name "*.py" | xargs wc -l | tail -1` with per-file attribution.
