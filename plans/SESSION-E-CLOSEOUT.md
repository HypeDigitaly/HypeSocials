# SESSION E CLOSEOUT — Wave 4 + Wave 5 (2026-08-13)

**Status: COMPLETE — the Topic-First Pivot is fully executed and LIVE-VERIFIED. Four commits:
`d664066` (Wave 4), `cdc76cc` (W5 previews fix), `2e0c657` (W5 `import time` blocker),
`7c92c2a` (W5 roster fix). Final suite 763 passed, 0 failed, 0 skipped. Total session spend:
$1.94 render+LLM on the one approved paid run (8/8 delivered, exit 0) + ~$0.005 on the
approved analysis preview + Virlo digest metering on three previews. The paid run's estimator
was accurate to one cent (expected $1.95, billed $1.94).**

## Barrier evidence (conductor's own runs)

```
W4:  .venv/Scripts/python.exe -m pytest -q  -> 761 passed (0 failed, 0 skipped)
W5:  .venv/Scripts/python.exe -m pytest -q  -> 763 passed (0 failed, 0 skipped)
find hypesocials -name "*.py" | xargs wc -l | tail -1  -> 19,223
find tests -name "*.py" | xargs wc -l | tail -1        -> 15,045
git status logs/ output/  -> only the live runs' own folders (no test writes)
```

**Line attribution vs the pivot baseline 16,356:** the pivot lands at **19,223 net (+2,867)** —
W1 +? (see Session B), W2 (Session C), W3 +988 / W3.5 −1,978 (Session D), **W4 +0 production**
(docs + tests only), **W5 +15** (previews.py +9: registry-before-summary fix; runner.py +6:
`import time` + the roster-list fix comment). Tests 14,273 → **15,045** (+772: test_branding.py
727, `_with_pulse` execution regression +17, roster-verdict regression +28). Nothing anywhere
was shortened to improve a number.

## Wave 4 (flat wave: T4.1 ‖ T4.2, conductor merge, barrier)

1. **T4.1 — tests/test_branding.py, 24 tests → 64 ids, zero production defects found.** Floor
   predicate + `floor(N·ratio)` over 36 ratio×total combos incl. r=0/r=1 followed to the
   delivered wordmark; gapped-orders-after-trim asserting the per-entry predicate (with an
   explicit `3 != floor(5·0.5)` guard against the bare-count shortcut); profile blocks traced to
   profile keys; `never_always` on every branded block, `never_style` only brand-affine;
   wordmark + `_spell()` in the TEXT block ONLY; brand-slot collapse by flag with deliberately
   misleading keys both ways; cross-brand hex isolation derived from the real compiled profiles;
   M12 anchor-only signature driven through the real `carousel._Deck._prompt`; upload-memo
   once-per-run with failure-not-memoized; no cross-run URL reuse. Reuses `test_styles`
   builders; two documented non-defects recorded in the file.
2. **T4.2 + conductor fixes — README.md + ACCEPTANCE.md re-based.** The agent's sweep was clean
   (all dead terms out: inspiration source, yt-dlp, `--mode`, `--sources`, A/B, pair_id,
   7-step wizard), but conductor verification refuted five claims before accept:
   **(a) a fabricated reel-pricing sentence** — "Measured live: $1.57; worst-case $2.85 with an
   output buffer": $2.85 was the OLD with-motion-reference measurement; corrected to the
   published no-reference rates ($1.575/5 s @720p, $0.70 @480p, confirmed to the credit in
   spikes/RESULTS.md §C) and the per-second-scalar no-recompute rule from the config comment;
   (b) "No console output by default" on `--verbose` (false — the standard tier exists);
   (c) a garbled registry sentence ("same topic never renders the same way twice");
   (d) `--quick` still claiming a "source" question; (e) ACCEPTANCE's "reel actuals land well
   under the worst-case scalar" — post-pivot the scalar IS the exact rate, so a gap is a
   finding, not the design. Gallery-card item sharpened to the post-pivot fields; the
   `--preview-sources` Virlo-digest metering note (~$0.25) restored (FR-139 allows it —
   previews.py:34).
3. **Conductor merge — CLAUDE.md + NAVIGATION.md.** CLAUDE.md: Media & video stack line
   deleted; yt-dlp out of external services; a "No media libraries" note added; process-reaping
   line de-yt-dlp'd; the "Reference images" paragraph rewritten onto registry-declared local
   files + upload memo + no-Virlo-images; the FR-295 no-fallback note added; glossary re-based
   (Topic, Meta-style, Topic filter, Verbatim copy, Branding rotation, Motion beat in; Trend,
   Style brief, Hook pattern, Viral-video motion reference, Both-mode A/B out). NAVIGATION.md:
   §1 pivot status, §3 rows (README/ACCEPTANCE/Inspiration/configs/prompts/tests incl.
   test_branding), W4 narrative sentence.

## Wave 5 — live verification (operator present; each paid step explicitly approved)

**Step 1** `--list-monitors` → exit 0, 3 monitors, $0.
**Step 2** `--preview-sources --config hypedigitaly` → exit 0. 9 topics from 1 monitor, `strn`
column non-increasing (the sort proof), blocklist-only verdicts labelled as such, funnel
reconciles (200 posts → 9 topics → 9 kept → 9 eligible), zero stderr bytes (NullHandler's
first live test — held).
**Step 3** `--preview-analysis --config hypedigitaly-cs` (approved) → after the blocker fix:
exit 0, LLM verdicts live (8 keep, 1 skip:PROMO with reason), style+brand assignment printed,
verbatim copy in the source language untouched (English posts under the Czech config — F22 by
design), zero Kie calls. Cost ~$0.005 (7 Luna calls). **Assignment determinism verified live:**
two independent runs printed byte-identical Assignment blocks (6 creatives, same styles, same
3 branded at orders 1/3/5 = `floor(6·0.5)`).
**FR-295 probe ($0)**: registry renamed → exit 2, refusal names the file and searched path,
$0 spent, restored.
**Step 4 — THE paid run** (approved): `--config hypedigitaly --images 6 --carousels 1
--reels 1 --budget 4 --yes` → **exit 0, 8/8 delivered, $1.94 of $4.00 (expected $1.95 —
one-cent accuracy), 481 s.**

### §5 checklist walk (observed on the transcript + artifacts, not assumed)

- ✅ **No Virlo CDN in any payload**; 13 jobs, `reference_count` ≤ 2 everywhere; references are
  run-uploads of registry files + the anchor/seed chain's own Kie result URLs (FR-20/24).
- ✅ **Style rotation:** 6 distinct `style_key` over 8 meta.yaml (≥5 required);
  `hypelead-brand-card` correctly absent (pool math); offline probe: the hypedigitaly rotation
  can never pick it (6 vs 7 usable styles printed per brand).
- ✅ **Branding:** branded = exactly orders 1/3/5/7 (creatives 02/04/06/08) = the floor
  predicate; 4 = `floor(8·0.5)` over the full plan (no trims occurred); every branded
  gpt-image-2 prompt carries `wordmark (render verbatim): "HypeLead"` + `_spell()` in the TEXT
  block and the `never_always` guards; zero `#34288B`/`#2B3F8E` in any payload; zero HypeLead
  tokens in unbranded prompts; zero competitor strings.
- ✅ **Verbatim:** engine verifier raised zero `copy_not_verbatim`; caption bytes match the
  copy-call offer wherever the offer displays untruncated; 6/8 `no_onimage_text` (see finding 4).
- ✅ **Reel:** no-reference billing confirmed on the bill ($1.575 clip + $0.03 seed = $1.61);
  seed-frame reference only; no video reference anywhere; branded seed frame carries the
  wordmark and the director's CONTINUITY names it.
- ✅ **Funnel:** printed once at DONE; reconciles at every stage; no reference/download rows.
- ✅ **Gallery:** 8 cards with topic/style/brand+signed/receipt ("Quotes P1… verbatim")/source
  URL; zero pair machinery; FR-150 footer; mid-run gallery-path line printed when the first
  card landed.
- ✅ **History:** 8 entries keyed `<mid>::<topic_key>`, posts as `{post_id: {date, url}}`.
- ✅ **Exit codes:** clean → 0 (live); registry renamed → 2 + FR-295 line + $0 (live).
  ⚠ **Over-cap-trim → exit 1 NOT probed live** (it would be a second paid run; asserted by
  tests) — disclosed.
- ✅ **Observability (D45):** stage headers `[n/N]` with in→out counts (8 stages); the
  `collecting trends from 1 monitor(s)` opener + closing form (Session-D obligation 4 — live at
  last); topics table with all 9 topics + non-increasing `strn`; roster `P` ordinals ≡
  meta.yaml `copy_source_refs` (all P1 this run); per-job terminal lines with wave/elapsed/cost;
  provenance block maps all 8 to topic+post(author/views/id)+style+signed+cost; zero bare
  stderr end-to-end.
  ⚠ Two deviations, both explained: **heartbeat gap 91 s** — the run was `--yes`, whose design
  cadence is 90 s (`runner.py:345`: 15 verbose / 90 yes / 30 interactive); the checklist's
  "30 s" describes the interactive tier. **`--verbose` live delta not observed** — its console
  delta (uncapped roster, 15 s beats) is a paid-run surface and a `--verbose` paid run would be
  a second paid run; verified structurally + by tests, and the event-log policy invariance WAS
  verified live ($0 verbose preview: event-type census byte-identical to the non-verbose run,
  stderr 0 bytes).
- **N/A this run (disclosed):** two-creatives-one-topic `copy_source_post_id` divergence — the
  pool gave 8 topics for 8 creatives, so no topic was shared (FR-7 working as intended);
  carousel anchor-only wordmark — the one carousel drew `plain` (unbranded), so the M12 gate
  is test-verified only (T4.1 drives the real `_Deck._prompt`).

### Findings & fixes (all fixed in-session, each with a regression test where testable)

1. **Previews announced a healthy registry as "unavailable — pre-flight will refuse"**
   (`cdc76cc`). The launch summary reads `session.registry`; previews printed before loading
   (sources never loaded at all). Now the same tolerant `_load_registry` runs before the
   summary, same order as the paid path; verified live.
2. **BLOCKER: `import time` missing from runner.py** (`2e0c657`). `_with_pulse` (FR-299) calls
   `time.monotonic()`; the W3.5 excision swept the import with its other users. **Every paid
   run would have died at COPY.** Caught by the approved analysis preview — the cheapest-first
   ordering did exactly its job. No test had ever *executed* the wrapper (Pulse arithmetic was
   tested directly) — regression test now awaits through the real wrapper. An AST sweep found
   no other used-but-unimported stdlib module in the package.
3. **Roster verdicts off-by-one after a filter skip** (`7c92c2a`). Verdict ordinals are
   screen-assigned over the pre-filter list; `_pipeline` passed the post-filter `kept` list, so
   the paid run printed `skip:PROMO` on a kept-and-quoted topic. Now the screened list is
   passed (the roster's assigned-only filter keeps skips out of the printout); regression test
   pins a kept-topic-after-a-skip reading its own verdict.
4. **Observation, not a defect: 6/8 creatives shipped `no_onimage_text`.** Each creative may
   quote only its one assigned post (§1.7 sibling divergence); on this corpus most P1 hooks are
   long/emoji-laden and fail the style budgets (`headline ≤ 34` etc.), so the caption-only
   degrade fired legitimately (creative 01 got "Hello, can you hear me?", the reel got its
   overlay). **Operator lever:** raising `max_onimage_chars` in styles.yaml, or offering
   candidates from more of the topic's posts, would raise the on-image hit rate — a product
   decision, not a bug. Also noted: "LLM spend $0.00" in the analysis preview is the repo's
   2-decimal money vocabulary rendering ~$0.005 — consistent with decision W3-10, left as is.

## Deep-module re-review (§1.2 statements, per the W5 obligation)

- **prompts_engine.py 1,926** — the biggest file; still ONE deep module: `build_context` +
  `branding_block` public, no-filesystem contract intact, the bulk is the 8 built-in template
  mirrors (data, parity-asserted). Split candidate: none that doesn't fork the template
  vocabulary. Keep; re-review if Increment B adds roles.
- **runner.py 1,669** — lifecycle conductor + the D45 console surfaces. The console blocks
  (`_topics_table`/`_post_roster`/`_provenance_block`/`_funnel_block`/`_stage`, ~430 lines) are
  a coherent seam and the named split candidate (`outputs/console.py`) **if** runner grows
  again; not split now — the W5 roster bug shows the blocks' coupling to pipeline state is
  exactly where the risk lives, and a move would not have prevented it.
- **virlo.py 1,252 / copywrite.py 1,222** — both cohesive deep modules post-excision (topic
  split; offer→selection→resolution→verify). No action.
- **menu.py 727** — T3.3's named cut (steps / picker / console) still stands as the next
  refactor IF menu grows; FR-300's five-step shape is stable, so deferred deliberately.
- **styles.py 474, previews.py 434** — comfortably deep; no action.

## PRD conflicts

No NEW conflicts found this session. Sessions C+D's thirteen recorded D15 items still stand
(see SESSION-D-CLOSEOUT §"PRD conflicts"), plus one plan-nuance recorded here for the next §5
revision: the checklist's "never silent longer than 30 s" should read "past the resolved
heartbeat cadence (30 interactive / 90 `--yes` / 15 verbose)".

## Open items / handoff

1. **The thirteen D15 amendments** (C: 6, D: 7) remain the only owed follow-up work.
2. **Over-cap-trim exit-1** and **`--verbose` paid-run console delta**: test-verified,
   live-unobserved — fold into any future paid session's checklist.
3. **On-image hit rate** (finding 4): operator lever documented above.
4. **AGENTS.md does not exist** (CLAUDE.md's governance section says the conductor creates it
   as a hardlink at setup — it never was). One `fsutil hardlink create AGENTS.md CLAUDE.md`
   away; needs re-creating after any CLAUDE.md edit anyway (edits break the link).
5. **Virlo trial expires ~today (2026-08-13).** The pivot is live-verified under the trial;
   fixtures from 2026-08-11 remain the offline corpus.

## Warnings for the next session (conductor experience)

- **Cheapest-first is not ceremony.** The $0.005 analysis preview caught a defect that would
  have burned the paid run at COPY. Never skip the ladder.
- **A test suite can be 761-green around a function nobody executes.** When a wrapper exists
  only to wrap I/O waits, write the test that AWAITS THROUGH it, not just the arithmetic
  beside it.
- **Two call sites, one positional contract = the next off-by-one.** The roster bug existed
  because previews and the pipeline passed different lists to the same display block. When a
  mapping is keyed on ordinals, pass the sequence that MINTED the ordinals, or re-key by
  identity.
- Doc agents fabricate plausible numbers under rewrite pressure — T4.2's "$2.85 with an output
  buffer" was invented. Verify every figure in an operator doc against its primary source.
