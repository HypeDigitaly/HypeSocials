# SESSION D CLOSEOUT — Wave 3 + Wave 3.5 (2026-08-12)

**Status: COMPLETE and conductor-verified. Two commits: `f8bf5cb` (Wave 3) and `30aa739`
(Wave 3.5). Full suite 697 passed, 0 failed, 0 skipped (W3 barrier ran at 711 before the
excision retired 14 legacy-subject test ids). $0 spent — no live API call anywhere; every
LLM/HTTP seam faked; fixtures only. Next session: SESSION E (Wave 4, then Wave 5 with the
operator).**

## Barrier evidence (conductor's own runs)

```
W3:   .venv/Scripts/python.exe -m pytest -q  -> 711 passed  (0 failed, 0 skipped)
W3.5: .venv/Scripts/python.exe -m pytest -q  -> 697 passed  (0 failed, 0 skipped)
      test_template_parity: SHIPPED == 8 (3 global + 4 gpt-image-2 + 1 seedance),
      full placeholder reachability (final vocabulary 25 — contracts items 2/4 exact)
      barrier grep (v2.2 right-unanchored terms) -> 0 hits, ONE disclosed exemption (below)
find hypesocials -name "*.py" | xargs wc -l | tail -1   -> 19,208
      (session start 20,198 -> W3 21,186 -> W3.5 19,208; pivot baseline 16,356)
find tests -name "*.py" | xargs wc -l | tail -1         -> 14,273  (start 13,168)
git status logs/ output/ -> clean both barriers (no repo-state writes from any test)
```

**W3 production +988 with per-task attribution:** runner.py +270 (conductor — pipeline
rewiring + ALL §1.10 surfaces), previews.py +148 + plan.py +96 (T3.1), menu.py +112 + cli.py +9
(T3.3), state.py +82 + gallery.py +37 + packager.py +7 (T3.2), generate/__init__.py +84 +
util.py +32 + render/__init__.py +24 + virlo.py +18 + copywrite/carousel/reel/preflight/
config/barrels small (conductor). **W3.5 −1,978:** three files deleted (939), virlo −447,
prompts_engine −301, config −32, models −98, cli −34, the rest sweep-sized. Nothing anywhere
was shortened by explaining less — every historical explanation was REWORDED onto the
post-pivot vocabulary, not stripped (diffs re-read at both barriers).

**Tests:** T3.5 rewrote 8 files (246 ids + re-bases incl. the real-corpus funnel arithmetic on
the live `_split_topics`), T3.6 rewrote 2 (15→33 and 30→40 ids, the §1.10 assertions). W3.5
route-backs re-based 6 test files onto the excised surfaces (below).

## What shipped (per task)

1. **T3.1 — plan.py 431→527, previews.py 275→423.** Single-entry `_emit`; asset id
   `<Pl>_<fmt>_<slug>_<NN>` (ordinal tail = the §1.10 short handle); A/B pair emission gone;
   `TrendVerdict` lost `text_only`; `assign()` stamps `entry.topic_key`; **FR-7 enforced at
   POST granularity in `select()`** (unscheduled but forced: the pre-pivot topic-level read
   excluded every previously-used topic wholesale AND would have gone AttributeError at W3.5 —
   disclosed, tested); FR-6 substance includes post text. previews: blocklist-only $0 sources
   preview; analysis preview = LLM verdicts → dry style/brand assignment →
   `_record_style_forecast` → verbatim copy; both share runner's `_topics_table`/`_post_roster`
   at `limit=None`; funnel prints LAST.
2. **T3.2 — gallery 338→375, packager 338→345, state 330→412.** Pair machinery + FR-231 badge
   deleted; cards show topic/style/brand+signed/source URL + the FR-298 receipt ("Quotes
   P1.hook.2 verbatim…"); FR-150 footer = style adherence + topical accuracy.
   `save_reference(run_dir, key, data, *, index, suffix)` re-keyed trend→style (`kind` param
   dropped — dead D23 channel). History: entries keyed `<mid>::<topic_key>`; posts values
   `{date, url}`; readers accept THREE legacy shapes (mapping, bare date, `"date|url"` — see
   PRD conflict 1); `record_use(logs_dir, uses: Mapping[str, Sequence[tuple[post_id, url]]],
   run_id, *, history_days, log)`; D44 migration by design.
3. **T3.3 — cli 421→430, menu 615→727, wizard_help.md re-based.** `--mode` out; `--verbose/-v`
   in (`Options.verbose`, deliberately no `apply_overrides` line). FR-300: wizard =
   `("config", "counts", "cap", "briefs", "confirm")` with counters DERIVED from list position
   (`--quick` = `1/1`); config-picker rows `{lang} · {N} mon · {i}/{c}/{r} · {brand} · {N}
   styles` with `NO STYLES` REPLACING the count (same `styles.load_registry`+`validate`
   resolution as preflight — a row can never disagree with the exit-2 it predicts;
   `_READINESS` memoized on (path, mtime, size), `menu._READINESS.clear()` is the test escape
   hatch); brand/ratio display-only confirm fact; durations re-derived ("about 3 minutes" /
   "5-8 minutes"); `_quiet_probe` stops the picker's stderr leakage.
4. **T3.4 — configs ×3 + niche brief.** Full `branding:` blocks with the v2 artifact's exact
   tokens in all three configs; `styles.refs_per_job: 2`; `virlo_topics_per_monitor: 9`; dead
   keys removed; **reel_second collapsed to the no-reference rates 720p 0.315 / 480p 0.140**
   (PRD anchor 30-config:144, arithmetic checked against the measured credit tiers);
   `output.console_verbosity` documented in default.yaml. All three configs load with ZERO
   warnings. Brief: palette "cyan-to-violet" → "cyan-to-teal" (collided with hypelead's
   never_always), hardcoded "English" tone removed.
5. **T3.5 — the 8 suites, 246 ids + 1 finding.** Pipeline-order assertion via
   `inspect.getsource` on the REAL `_pipeline`/`_assign_visuals`; FR-295 exit-2 through real
   `preflight.check`; `llm_starved == {COPY_DEGRADED}` pinned; five-row funnel + real-corpus
   reconciliation; `(post_id, url)` history round-trips incl. both legacy read shapes;
   `console_verbosity`; `--mode` asserted GONE; `--sources` coverage dropped (flag died W3.5).
   **Its strict-xfail caught a REAL FR-286 defect in my funnel header** (see route-backs).
6. **T3.6 — console-inventory 15→33 ids, menu 30→40 ids.** Stage-header grammar with computed
   `[n/N]` over three stage-list shapes; `strn` monotonicity over a deliberately unsorted
   input; caption weights proven read from `sources.STRENGTH_WEIGHTS` by monkeypatching them;
   ordinal-vs-rank disambiguation; roster `-> NN` from `trend_reuse_index % len(posts)`;
   provenance rows + receipts + loss lines; `Pulse` suppression windows; a REAL fast `_drain`
   printing no heartbeat; funnel-once at source level; note() tiers; per-job line shapes; the
   full FR-300 menu matrix. **Found the `_halt` blocker** (see route-backs).
7. **Conductor — W3 wire-in (the §1.10 mandate, all surfaces).** runner.py: pipeline confirm →
   collect → `_screen_topics` → select → `_assign_visuals` (styles+branding, per-creative
   receipts) → `_record_style_forecast` → roster → `_store_references` (style-keyed) →
   `_write` (4-arg) → `_create` → `_package`; `_live_stages` computed N; `_stage` header
   grammar; `_topics_table` (caption reads `sources.STRENGTH_WEIGHTS` = 0.35/0.15/0.30/0.20 —
   the mockup's 0.45/0.25/0.20/0.10 was illustrative); `_post_roster` (P-ordinals ≡ §1.7
   labels); `_provenance_block` + `_quoted_bytes` (receipt slot order pinned to gallery's);
   `_screen_topics` (verdict events, strip/skip detail lines, keeps via `note()`, ONE
   filter_degraded warning, `session.strip_brands`); funnel re-shaped + printed ONCE at DONE;
   `_posts_used` → (post_id, url) off `copy_source_post_id`; FR-202 analyzed clause deleted;
   `_launch_summary` styles/branding fact lines; exit block gains the gallery path;
   `_with_pulse` LLM heartbeats; `Preflight.report` wraps at the printer (T3.1's 272-char
   hint). generate/__init__.py: Env say/pulse/heartbeat_s/jobs_* seams, `_drain` silence-breaker
   heartbeat + mid-run gallery-path line + grace-line say, `_job_line` per-job terminals,
   `_abandon` console line, `Env.strip_brands` + `competitor_strings_for` (M6 at EVERY render
   prompt — carousel/reel duck-typed). render: `RenderGate.stats()` + `gate_stats()`
   (read-only). util: `Pulse`. virlo: `topics_synthesized` counter, `say` threaded to the four
   `_warn` sites, `record_render` re-based (style_refs/topics_used/styles_used). copywrite:
   `progress` seam. __main__: `_configure_logging()` NullHandler (stderr leakage ends).
   config: `output.console_verbosity` (wave-start micro-pass) + hypelead `background_hint`
   variant resolved to the light surface. Barrel re-points. Contracts doc **W3 addendum items
   1–13**.
8. **Conductor — W3.5 (no subagents).** The full §3 excision list + the W3-addendum additions:
   three files + test_video_ref + three templates deleted; models/config/virlo/prompts_engine/
   cli/kie excisions; stale-prose sweep (profiles, render, llm, __main__ scratch note, notion,
   menu, reel, refs, budget, preflight, runner, styles, sources barrel); `menu._options_from`
   lost its dead kwarg; `_free_text_schema` entry dropped; five motion-chain tags deleted
   (contracts item 7 note — their last emitter died with video_ref.py); Counters media groups
   out; `prompts/README.md` at the final 8-role spec; parity at SHIPPED == 8; Pillow + yt-dlp
   out of pyproject.toml (CLAUDE.md stack lines follow in W4/T4.2 per plan).

## Conductor decisions & disclosed deviations (all in the contracts W3 addendum unless noted)

1. **Batch sequencing (Session-C warning applied): test authors ran AFTER the conductor
   wire-in**, not beside it. "Wire-in LAST" held relative to the code children; T3.5/T3.6 then
   asserted real, final surfaces. It worked: zero frozen-assertion collisions in W3 — the two
   real findings were genuine production defects, not drift.
2. **Funnel header re-shaped for FR-286** (T3.5's xfail): `total_available` prints compact
   (`2.7K`), clauses join on `·`, `wrapped()` fallback. Deviation from the mockup's raw
   comma-joined number — the raw figure stays in `collect_funnel`.
3. **`_write` is 4-arg** (`…, strip_brands`) per the pin T3.1 coded against; the runner passes
   `session.strip_brands`, previews their own.
4. **M6 closed end-to-end** (Session-C obligation 2): `Env.strip_brands` + one resolver; every
   `build_context` call in the render package now carries config competitors + the topic's
   guarded LLM strips.
5. **`apply_brand_overrides` WIRED** at Collect under `notion_influence == "full"` (obligation
   7 — kept, not deleted, per the operator's standing Notion intent; dormant without a token).
6. **`topics_synthesized`** added to Counters for FR-296's `N synth` clause (collided with one
   frozen W2 assertion in test_topic_split — updated with a decision comment).
7. **Roster prints after ASSIGN's receipts** (it needs `-> NN`, which needs assignment); "after
   SELECT" in §1.10 is satisfied loosely and disclosed.
8. **FILTER drops only `skip`**; `strip` topics proceed with brands recorded — the console-ux
   §2 mockup's `11` into SELECT is illustrative (T3.1's reading, adopted).
9. **Topics-table legend prints only codes that can occur** (`PROMO`; blocklist hits surface as
   `strip:N`) — the mockup's `BLOCK`/`THIN` codes have no post-pivot producer.
10. **Provenance costs use the repo's one `_money` formatter** (`$0.04`), not the mockup's
    3-decimal shape — one money vocabulary beats a per-surface fork.
11. **Barrier-grep exemption, exactly one:** `styles.py:71` `_VARIANT_MARKERS = (" or ",
    "variant ", "either ")` — a FUNCTIONAL literal §1.3's leak heuristic mandates; obfuscating
    it would be worse than recording it. Everything else was reworded to zero hits.
12. **Verbose heartbeat cadence (15 s) is clamped by the 20 s render suppression window** for
    the FIRST beat only — contracts item 16's two rules compose; disclosed, asserted by T3.6.
13. **W3.5 additions beyond the plan's list** (all recorded in the addendum): `--sources` flag
    (T3.3's finding), the five motion-chain DegradationTags, `menu._options_from`'s kwarg,
    `_STANDING`/`_BRAND` built-in scaffolding (orphaned by the built-in deletions), README's
    dead rows, the six W3.5 test-file re-bases.

## Route-backs / defects caught (all resolved in-session)

1. **T3.6 BLOCKER — my W3 deletion pass orphaned `runner._halt`'s body** (the `def` line went
   with an adjacent block; every run would have been a runtime NameError at COPY). Restored;
   T3.6 also flagged a truncated comment and a mid-word `[:78]` slice in `_job_line` — both
   fixed (`fit()`), plus the same deletion pass was found to have swallowed
   `_FUNNEL_WIDTH`/`_money` (caught by collection + my provenance smoke test). **Lesson
   recorded below.**
2. **T3.5 strict-xfail — FR-286 funnel-header overflow at real-corpus scale** (`total_available`
   sums across monitors to seven digits; 79–84 chars). Fixed (decision 2); the xfail flipped to
   a plain pass + an Increment-B-scale sweep.
3. **prompts_engine excision corruption, caught before commit:** a text-splice helper searched
   end-markers from position 0 and DUPLICATED a region when the end preceded the start.
   Restored from HEAD, redone with position-safe cuts, byte-verified (8 allowlist rows, 8
   built-ins). Nothing corrupted ever reached a commit.
4. **W3.5 landing after the test authors** red-shifted six suites exactly as the wave order
   implies; all re-based with decision comments (test_config's closed-vocab/YAML-1.1 examples
   moved to surviving keys; test_exit_codes' dead-tag references to `hasattr`-absence +
   TEXT_TRIMMED; test_prompts_engine's three transitional tests to final-state; parity to 8;
   test_funnel_report's populate-the-dead-counters test to structural absence — the stronger
   post-excision guarantee).

## PRD conflicts recorded (D15 follow-ups owed, none blocking; adds to Session C's list)

1. **FR-153 post-entry shape** (40-outputs:129) spells a pipe-joined STRING
   (`"date|url"`); contracts item 14 pins a `{date, url}` mapping. Shipped the mapping; the
   reader accepts the pipe form too. One D15 sentence picks one. (T3.2)
2. **FR-71 + FR-75 were never amended** — still "variant tag (analyzed or direct)", the
   `pair_id` sentence, `refs/<trend_key>/...` and a `..._analyzed_01` example. Code follows
   the plan + operator decision #2. (T3.1, T3.2)
3. **FR-76's card list** wants the quoted post's author + views on the gallery card; meta.yaml
   carries post id + ref labels (author/views live in the FR-297b roster). Either amend FR-76
   or add two AssetRecord fields — operator's call. (T3.2)
4. **NFR-16 (30-config:530) and FR-284 (:439) still enumerate SEVEN inputs** incl. the dead
   source/mode pickers, contradicting the amended FR-56/FR-300 (five). (T3.3)
5. **FR-300's `--quick` sentence** ("skips the config-picker step only") misdescribes shipped
   FR-285 behaviour (quick asks nothing before the price). (T3.3)
6. **`styles.refs_per_job` default: FR-18 says 3, code/contracts/configs say 2** (re-confirms
   Session C conflict #3); and 30-config §2's sketch teaches `styles: registry_file:`, a key
   that does not exist, while omitting `refs_per_job`. (T3.4)
7. **`brand: hypelead` in both niche configs** is a T3.4 reading of plan §1.4/§5 (default.yaml
   keeps `hypedigitaly`) — flagged as a decision, revisit if the operator wants corporate
   branding on the agency niche. (T3.4)

## W4/W5 (SESSION E) obligations

1. **T4.2/conductor: CLAUDE.md stack + "Reference images" paragraph** still name Pillow ("image
   downscale only per FR-93") and yt-dlp — pyproject already dropped both in W3.5; the doc
   half is W4's by plan. NAVIGATION §8 is already re-based; CLAUDE.md is NOT.
2. **T4.1 test_branding.py** per the §3 W4 row (floor-predicate + gapped orders, cross-brand
   hex isolation, anchor-only wordmark, upload-memo single-upload, no URL persistence).
3. **Deep-module reviews at the W5 closeout** (§1.2 statements): prompts_engine 1,926, runner
   1,663, virlo 1,252, copywrite 1,222 — plus **menu.py 727** (T3.3 named the cut: steps /
   picker / console) and gallery+state grew.
4. **W5 live checklist additions from this session:** the §5 observability items now have real
   surfaces to watch; verify the roster's `P` ordinals against meta.yaml `copy_source_refs` on
   the paid run; `--verbose` re-run invariant (run.log byte-policy unchanged); check the
   `collecting trends from N monitor(s)...` opener and zero bare-stderr lines end-to-end (the
   NullHandler decision's first live test).
5. **Session C's D15 list still stands** (six items) plus this session's seven above.
6. **`.env.example`/README may still document the dead keys** — T4.2's sweep should check
   operator docs for `generation_mode`/inspiration/yt-dlp mentions (production and prompts are
   clean; only W4-owned docs remain).

## Warnings for Session E (conductor experience, this session)

- **Mechanical line-range deletion is where this session's only two self-inflicted defects came
  from** (the orphaned `_halt` def-line; the marker-order duplication in prompts_engine). Both
  were caught — one by an independent test author, one by immediate re-verification — but the
  lesson is: splice by UNIQUE MARKERS searched from the cut's own position, verify by parse AND
  by symbol grep after every batch, and never trust a line number twice after the first splice.
- **The independent-test-author barrier caught a real conductor bug AGAIN** (W0, W2, now W3's
  `_halt`). Keep the sequencing: conductor decisions → code → wire-in → INDEPENDENT test
  authors → conductor re-verification.
- **T3.5's strict-xfail discipline is worth repeating**: a finding pinned as `xfail(strict)`
  cannot rot in either direction and hands the fixer a ready-made regression test.
- Route-backs by fixing in-conductor (this wave had no SendMessage round-trips — the two
  agent-found defects were conductor-owned code) — cheap because the reports carried file:line.
- venv python only; **$0 spent**; no logs/ or output/ writes at any point (checked at both
  barriers).
