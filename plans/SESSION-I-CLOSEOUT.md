# SESSION I — CLOSEOUT (style intelligence: registry 9→19, LLM-matched assignment, teal spine — v2.4.0, D56/D57)

**Date:** 2026-08-20 · **Plan:** `plans/xmasterplan-style-intelligence.md` (W1–W4 executed; W5 partially — see §5)
**Suite:** 1481 → **1567 passed, 0 failed** (+86 ids; green in fixed AND randomized order)
**Growth:** production 33,114 → **34,745 (+1,631)** · tests 30,401 → **32,238 (+1,837)**
**Live spend this session:** **$0.27** (one `--preview-analysis`). No paid render run — see §5.

## Wave status

| Wave | What | Outcome |
|---|---|---|
| W1 | PRD amendments (D56+D57, FR-334/335/336/337, 6 files + artifact) | ✅ 3 rounds (§4 deviations 1–3) |
| W2 | Registry 9→19, `style_match_system.md`, README, configs | ✅ registry validates 0/0 under all four configs |
| W3 | Engine (10 tasks, 2 sub-waves) | ✅ barrier: 13 failures, all W4-owed pins, zero regressions |
| W4 | Tests + docs | ✅ **1567/0**; NAVIGATION + CLAUDE.md merged |
| W5 | Live ladder | ⚠️ rungs 1–4 done ($0.27); **the paid run is owed and needs the operator** |

## What shipped

- **Registry 9 → 19 styles.** `build-log-mono` (brutalist-editorial typographic system, two-ground alternating chrome grid) + 4 census-driven archetype styles (`icon-ledger-carousel`, `circuit-atlas-dark`, `social-quote-card`, `terminal-mockup-deck`) + 5 `-teal` variants of existing styles (originals byte-untouched — D-G honoured by DUPLICATING, never editing). Every one of the 19 carries an authored `match_profile`.
- **Matched assignment (FR-334).** New leaf `hypesocials/style_match.py` (+661): ONE batched fail-open `analysis` call at ASSIGN. `match(entries, registry, topics, cfg, llm) -> dict[asset_id, Match]` is TOTAL and never raises. Per-entry ballot = `usable_styles` × `fmt_affine`, **imported never re-derived**. Answers join on **asset_id, never ordinal**. `high`/`medium` accept; `low`/out-of-pool/missing keep the FR-291 baseline and preserve `wanted_archetype` for a console gap report; whole-call failure puts every entry on baseline with `style_match_degraded`. `assignment: rotation` restores pre-D56 behaviour byte-exactly.
- **Teal spine (D57).** 12-key `styles.enabled` + `assignment: matched` pinned in the three brand configs; `default.yaml` documents the knob and keeps the engine default `rotation`.
- **Provenance end to end.** `style_fit`/`style_reason`/`style_origin`/`style_wanted` on `PlanEntry` → `AssetRecord` → `meta.yaml` → gallery badge + wanted-archetype note. The packager needed no change — `_record_dict` serialises every dataclass field.
- **Budget + previews.** `style_match_call` + `style_match_retry_allowance` quoted at Confirm under matched only, override briefs excluded; `--preview-analysis` runs the matcher for LLM-only, `--preview-sources` stays $0.

## Defects found and fixed that the plan did not contain

1. **`menu.py` FR-286 truncation (real, operator-facing).** The picker's facts line was at exactly 70/70; a two-digit style count pushed it to 71 and `_fit` ate the tail — which is where the cure lives: the row printed `NOT RUNNABLE - pick…` and the `[4]` naming the fix was gone. `_FACTS_WIDTH` 70→71 (line 77 of 78; the picker LABEL line above already runs to the full 78 with no slack, so this is still the more conservative of the two).
2. **Launch-block under-reported the style pool.** `runner._launch_block` computed "N usable here" from `brand_ok` alone, ignoring FR-314's `styles.enabled` — the exact "second copy" that `usable_styles`' own docstring warns makes the menu, pre-flight, the preview and the paid run disagree. It read `18 usable` where the shipped config selects 12 (and `8` under SESSION H's four-key list). Now calls the public predicate; verified live as `12 usable here`. Pinned in `test_console_inventory.py` as an **equality against `usable_styles(...)`**, never a literal.
3. **`_assign_visuals` degraded warning truncated its own reassurance.** The cause and "the FR-291 rotation baseline stands, every creative kept a style" were joined and fitted to 74 together; the clause alone is 67, so any real cause pushed the join past 120 and `fit` ate the reassurance whole — the operator read that the matcher died with no word that every creative still wears a style. Split into two lines (58 and 66 with indents). Found by the W4 test author, who pinned the defect as measured truth rather than asserting it away; the pin now asserts the fix.
4. **`social-quote-card` blew the Kie prompt wall — caused by the conductor.** Adding the required D-A TOOL MARKS carve-out (+188 chars) tipped it over, and the last-resort trim ate a SAFETY rule ("the every-legible-character rule"). Isolated by restoring the original text (all 19 pass) — **my edit, not W2's authoring**. Root cause was deeper: the entry had ZERO headroom, DNA 2,052 vs the registry's 1,750–1,860 convergence. Re-authored to DNA 1,856 / exclusions 1,082 with the carve-out KEPT; at the tier-B extreme the truncation is now confined to the droppable tail with the last safety rule 102 chars inside the cap — a net headroom gain over even the pre-carve-out state. All 30 numeric/hex tokens and both FIXED/MAY-CHANGE sets audited present after.
5. **`social-quote-card` was the only style of 19 missing the D-A carve-out**, so its blanket "every other service … their logos" ban reached GitHub — a `kind == "tool"` mark in 4 census posts, sanctionable on a render's TOOL MARKS line. The registry header forbids exactly this ("a blanket 'no real logos' now contradicts the render template it is pasted into"). All 19 now carry it.
6. **`AGENTS.md` was a broken hardlink**, 3.5 KB stale against CLAUDE.md — so any agent reading the documented single source of truth got outdated rules. Hardlink restored, content verified identical.
7. **`run_deadline_min` doc drift, and the conductor propagated it.** CLAUDE.md claimed "default 45 min since v2.1.3/D48". The real default is **60**, raised 45→60 in v2.2.0/D49 and pinned by all four shipped configs (`config.py:234`, `prds/30-configuration-and-run.md:88`). The conductor "corrected" the PRD artifact chip to 45 on CLAUDE.md's authority, making it wrong. Fixed in CLAUDE.md (both places), PRD.html, and a third stale claim of **25** at `prds/20-integrations.md:244`.
8. **FR-140 under-counted preview spend.** It said `--preview-analysis` spends "filter + copy" — already wrong since v2.1.0 when slide intelligence joined the deep preview, and D56 adds a fourth. Amended to name all four LLM stages.
9. **`ugc-tabletop-statement-teal` is `slides_only` too.** Plan §4.4 names only `meme-caricature-panels-teal` as inert. **Effective carousel rotation under the 12-key pool is 10, not 11.** Found by the W4 test author; test re-based to the truth.

## Deviations accepted (with reasons)

1. **Nothing-in-scope does NOT degrade.** When every entry is an override brief, or every pool has ≤1 style, the matcher makes no call and returns all-`rotation`, not `rotation_fallback` — even with `llm=None`. A matcher with nothing to choose between has not failed, and degrading there would raise a false warning and tag every asset. Deviates from the plan's literal "EVERY entry"; accepted and pinned so it is not "fixed" back.
2. **`build-log-mono`'s literal chrome lettering was not authored as lettering.** Plan §4.1 specifies `"THE BUILD_"`, `"STEP NN"`, `"NN / NN"`, `"SWIPE →"`. Any of those printed unquoted is `invented_text` in the gauntlet's own vocabulary (and `counter_value` for an invented badge). Two existing entries already carry DELIBERATE comments ruling this out for the same reason. Resolved the established way: every chrome slot letters only what the TEXT block quotes; the underscore survives as a drawn teal cursor, the swipe cue as a drawn arrow. The plan's literal strings would have shipped a deck that fails its own critics.
3. **`letterpress-print-carousel-teal` carries teal on the COVER only.** Plan §4.3 says "terracotta ink → teal ink", but terracotta is that style's body-slide GROUND and the plan's own method rule says grounds stay native. Re-roling the black second ink to teal would put the spine on body slides, but black-on-terracotta is high contrast and teal-on-terracotta would be muddy. **Operator decision owed — visible directly in the W5 paid run's teal-spine check.**
4. **Two acceptance criteria the conductor over-specified**, corrected by the executors: "zero `prompt_hard_trimmed` warnings at both tiers" is unreachable for any dense style (the event fires whenever the trim runs at all); and "matched-off baseline byte-equal to pure `assign_styles`" is not testable inside `style_match`, which deliberately never reads `config.styles.assignment` — the mode gate lives at the call site.
5. **No `styles_matched` funnel counter.** `Counters.record_render` has a fixed keyword signature in a file W3 did not own, and the renderer would need a row. The matched/baseline split is already on the ASSIGN summary line and in the `style_match` event. Reasoning documented in `_record_style_forecast`'s docstring.

## W5 ladder — evidence so far

1. **`pytest` 1567/0**, fixed and randomized order.
2. **`--list-monitors`** exit 0, 3 monitors. **`--preview-sources --config hypedigitaly`** ($0): `registry v1 · 19 styles · sha 04f12fea · 12 usable here`, no exit 2, funnel clean (286 stale / 7 used dropped, 9 topics).
3. **`--preview-analysis --config hypedigitaly` ($0.27) — THE MATCHER RAN LIVE AND MATCHED WELL:**
   ```
   style_match: 3 of 3 creative(s) matched  matched=3 baseline=0 degraded=0 candidates=19  wanted=[]
   Assignment — 3 creative(s), 2 style(s), 0 branded
     registry v1 · 19 style(s) · sha 04f12fea71e1
     matched 3 of 3 creative(s) (3 high)
         01 carousel  AI Agents for Business…  circuit-atlas-dark  plain
                matched/high    agent/systems explainer with six panels, no…
         02 carousel  AI Video Generation…     icon-ledger-carous… plain
                matched/high    seven text-heavy tutorial panels match dense…
         03 carousel  Claude Opus & Sonnet…    circuit-atlas-dark  plain
                matched/high    model performance/insights topic matches…
   ```
   Both winning styles are **D56 census-driven archetypes authored this session** — the agent/systems explainer went to the dark tech-diagram style and the seven-panel lead-gen tutorial to the listicle icon-card style. That is the 48% listicle/infographic gap being closed by content fit, where content-blind rotation would have picked by file order. Repeats are correct by design (two creatives, same archetype, same style). Zero degraded, no gap report (nothing wanted).
4. **Rotation regression: proven OFFLINE and more rigorously than a live preview could.** The W3 runner task loaded the pre-change `runner.py` from `HEAD` as a second module and ran both against an identical 6-carousel plan: byte-identical console output, byte-identical picks, byte-identical branding, zero LLM calls.
5. **PAID RUN — OWED, OPERATOR REQUIRED.** See below.
6. This closeout.

## ⚠️ What SESSION J (or the operator) must do first

**One paid run, 2–3 carousels, low cap.** It is the only rung left and it is deliberately not automated, because its acceptance criteria need human eyes:
- the Confirm estimate shows `style_match_call` + `style_match_retry_allowance` (previews skip the Confirm gate, so this line has only ever been verified by test);
- `meta.yaml` carries the four provenance fields and the gallery shows matched labels;
- **visually confirm the teal spine across styles** — including deviation 3 above (`letterpress-print-carousel-teal` is teal on the cover only; decide whether that is enough);
- **visually confirm `build-log-mono`** (fixed chrome grid, alternating grounds, accent under 5%);
- **gauntlet green on the two UI-grammar styles** (`social-quote-card`, `terminal-mockup-deck`) — no platform-mark leakage. These sit closest to other styles' exclusions and are the highest-risk new authoring in this session.

## Growth attribution (rule 5)

**Production +1,631:** `style_match.py` **+661 (new)** · `prompts_engine.py` +204 · `runner.py` +210/−11 · `previews.py` +165/−2 · `budget.py` +112/−8 · `models.py` +98 · `outputs/gallery.py` +81/−2 · `styles.py` +70/−3 · `config.py` +28 · `generate/__init__.py` +20 · `menu.py` +10/−2.
**Tests +1,837:** NEW `test_style_match.py` +663 · `test_console_inventory.py` +370/−4 · `test_styles.py` +266/−45 · `test_gallery.py` +235 · `test_prompts_engine.py` +132/−8 · `test_budget.py` +94 · `test_config.py` +82 · `test_prompt_fit.py` +86/−47 · `test_template_parity.py` +26/−13.
**Non-code:** `prompts/styles.yaml` +~950 (10 new styles + 19 match profiles + header re-base) · `prompts/style_match_system.md` +143 (new) · `prompts/README.md` +25 · configs · six PRDs + PRD.html.
No docstring, comment or error message was shortened anywhere.

## PRD conflicts

None outstanding. Items 7–8 above were PRD drift found and fixed in-session (D15: PRDs first).
**Pre-existing, NOT touched, still owed a D15 ruling** (carried from SESSION H): (a) `prds/50-promptcraft.md:168` lists `{{source_panels}}`/`{{topic_texts}}`/`{{competitor_list}}` in copywriter_system's contract — none are in the engine allowlist; (b) FR-73's "caption + hashtags" meta.yaml claim vs the actual asset meta shape; (c) `prds/50-promptcraft.md` FR-263's "three global role templates" is stale (there are ten) — left byte-identical this session because it sits outside the amended scope.

## Follow-ups (none blocking)

1. **ASSIGN receipt cannot distinguish a `-teal` variant from its original.** The style column is `fit(…, 19)` but D56 keys run to 33, so `quiet-luxury-night-photoreal-teal` and `quiet-luxury-night-photoreal` both print `quiet-luxury-night…`. Widening it would break the byte-identical rotation guarantee; the full key IS in `meta.yaml` and on the gallery card. Operator call.
2. **Dropped-row gallery chip cosmetics** (carried from SESSION H, unchanged).
3. **`meme-caricature-panels` sets `max_onimage_chars.headline: 110` above the config's 90** — a dead cap that can never bind, now inherited by its `-teal` variant. Pre-dates this session.
4. **`photoreal-ambient-caption-teal`'s render_prompt still names "pale oak"** while its palette ACCENT row is teal. Not a contradiction (oak survives as a room tone), just no longer roled.
5. **A URL inside model-authored `style_reason` renders as escaped inert text** in the gallery, which is safe but sits oddly beside the FR-75 "every http is inside an `<a href>`" rule. If stripping model-text URLs is wanted, it is a `gallery._style_html` change.
6. **§3a deep-module reviews owed and widening:** `copywrite.py` 3,574 · `budget.py` 1,260 · `previews.py` 650 · `menu.py` 819 · `style_match.py` 661 (new; ~230 executable).
7. **Artifact URLs on this account keep dying.** The canonical PRD URL served v2.4.0 content twice this session and then 404'd within the hour, never appearing in `action: "list"`. Third occurrence. New URL and the recovery procedure are in the `hypesocials-prd-artifact` memory.
   Current: **https://claude.ai/code/artifact/b9c8b299-d409-4b85-bc50-ed7dbad4e716**
8. **Conductor process note.** A styles.yaml agent was respawned while still alive, briefly giving one file two writers, because a session-limit notification for its siblings led to assuming it had died. The second agent detected the live writer, refused to write, and converted itself to a read-only review — which is how defects 4/5 and follow-up 3 were found. Verify an agent is actually dead before respawning.
