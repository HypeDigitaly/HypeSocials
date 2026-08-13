# SESSION G CLOSEOUT — Slideshow Fidelity Waves 3–5 (2026-08-13)

Plan: `plans/xmasterplan-slideshow-fidelity.md` v2.1. Branch `topic-first-pivot`.
Commits: `256253b` (W3), `34e1576` (FR-99 ruling), `c8da628` (W4), plus this closeout
commit (W5 record + FR-307 measured figure). **Every barrier green; final suite
899 passed / 0 failed / 0 skipped.** Production 21,562 → **22,042** (W3 +417 with
per-file attribution in the commit, FR-99 ruling +~57; W4/W5 added no production code).
D46 is now fully implemented, documented (PRDs at v2.1.1, artifact republished and
verified) and LIVE-VERIFIED.

## What each wave delivered

**W3 — excision, registry, provenance.** Style PICTURE channel excised end to end:
`refs.attach()` is brief-photos-only (kinds `brief`/`chained`), `styles.py` lost the
window/rotation/image validation, `MetaStyle.reference_images` and `styles.refs_per_job`
REMOVED (stale operator configs get the unknown-key warning), run-level `refs/` re-scoped
to brief images (FR-71). `styles.yaml` re-authored text-only (raised caps make §0.5
effective via min(); file-free exclusions; ≤120 words, no M9 markers) + full template
re-author around `{{visual_brief}}`/`{{slide_panel_source}}`/§0.14b/§0.12.
FR-309 gallery: three-part cards with per-panel PAIRED tiles (`slide i ← source panel j`),
labelled gaps (never shifts), truncation notes, FR-75 hostile-path guard, override
fallback, `source/` skip. `generate._record()` provenance join (panel_map × intel,
nested ISO `source_post`, vision tags; unresolvable bound post → `{post_id}` alone).
FR-307 + §0.14e re-run at PRE-FLIGHT via public `config.windows_violation` /
`formats_sourcing_violation` (CLI overrides can no longer sneak past; §0.14d override
carve-out at entry granularity). Conductor: `_BUILT_INS` byte-mirrored for 6 roles (F20),
`_TRUNCATION_ORDER` flipped (style trio cut LAST — the words are the only carrier now),
`MAX_PROMPT_CHARS` 10k→16k (engine bound; slide prompts legitimately assemble ~13k),
runner brief-ref store + coverage-only render forecast + `source_post_id` roster mapping,
FR-97 ruling (a): no reference-free retry for a job that had no references.

**W4 — tests, docs, D15 batch.** +50 NEW regression tests (`tests/test_gallery.py` NEW,
29 ids incl. a real `_record`→packager→gallery E2E; `_record` join pins; no-repeat
pick-guard depth; §0.14b slot scoping; INTEL wiring order pins). README + ACCEPTANCE
re-based onto D46 (conductor fix: phantom `--include-videos` flag removed — the real
path is editing `sources.include_videos`). D15 docs batch v2.1.1 applied across the
PRDs (FR-13/99/107/90/73×5/305/295-tombstone/191) + artifact republished at the
canonical URL, SVG verified. **FR-99 ruling implemented in code**
(`copywrite._mapped_fallback`): a failed copy call on a BOUND deck ships its mapped
panels verbatim with full provenance; only through-line/narrative-arc are lost.

**W5 — live ladder (all rungs walked).**
- `--list-monitors`: 3 monitors. ✓
- `--preview-sources` ($0, run `20260813_143047_j1f8`): 300 newest slideshow rows →
  290 `dropped_stale` / 1 `dropped_used` / 0 `dropped_unenriched` → 9 posts, ALL inside
  the 30-day window (2026-07-15 → 2026-08-04); `videos: disabled` printed; roster
  authors overlap the Virlo grid (@appmillers, @mosedlat among them). ✓
- **FR-307 measured supply figure (recorded in the PRD): 9 usable slideshow posts per
  monitor per 30-day window, 7 deck-bindable (panel_count ≥ 2).** Far below the ~60–150
  pre-verification estimate. One weekly 6-carousel run nearly exhausts a monitor's
  month; daily on one monitor is NOT viable. ✓ (placeholder filled)
- `--preview-analysis` ($0.36): panel-mapped refs visible (`slide_1=P1.panel.1 …`),
  zero `P*.description`, §0.7 captions; INTEL runs $0-disabled pre-Confirm by design. ✓
- **ONE paid run** (`20260813_143420_oyo4`, all-carousels ×6, $4 cap): 6/6 decks
  delivered, **$1.27 total** ($0.37 LLM incl. slide_intel, $0.90 render), 735 s,
  exit 1 (honest losses, below). INTEL populated all six `source/<post_id>/` folders
  with slides + `source.yaml`. ✓
- **Byte-verify: 6/6 decks OK** — every non-empty `panel_map.source_text` byte-identical
  to `source.yaml`'s merged text, positions preserved, briefs joined, 30/30 source
  images present. ✓
- **Boundary checks: 30/30 render jobs on `gpt-image-2-text-to-image`; ZERO Virlo hosts
  in any payload; reference counts exactly per contract** (anchors 0 refs, body slides
  1 ref = the chained anchor). Gallery self-contained (30 paired tiles, 5 truncation
  notes, no scripts, all-relative srcs). ✓
- **NO-REPEAT PROOF: re-run `--preview-sources` → `dropped 7 used`** (the 6 quoted
  posts + 1 prior), 6 topics excluded by history, 3 eligible remain. ✓

## Honest losses in the paid run (exit 1)

1. **11 Kie slide jobs timed out** (stuck >180 s, $0 for stuck jobs, never resubmitted
   per 20-integrations §8) → 4 of 6 decks `incomplete` with `missing_slide_numbers`.
   A Kie capacity day, not a code defect; the abandon path behaved exactly as written.
2. **On-image hit-rate MISSED the §5 target (≥5/6): 4/6 decks carry ≥1 worded slide;
   per-slide quoted counts 0/0/1/5/1/2.** Root cause is structural, not a bug:
   vision `onimage_text` transcribes ALL text on a slide (headline + body, 300–1050
   chars measured) while the §0.5 `slide` cap (300, min()-ed with style caps 180–300)
   was calibrated for Virlo's headline-scale `panel_texts`. FR-100 never trims, so
   over-budget panels ship wordless. See "Decisions needed" #1.

## Decisions needed from the operator (D15 candidates)

1. **Vision transcription vs slide caps (THE fidelity lever).** Options:
   (a) `slide_intel_question.md` + schema split `onimage_text` into
   `{headline_text, body_text}` per slide; the offer quotes the headline tier and the
   visual_brief carries the body as content description — RECOMMENDED;
   (b) raise `text_budgets.slide` + style caps toward ~1000;
   (c) offer a fitting SUBSET of a slide's lines (§0.14b-adjacent; weakens "verbatim").
2. **Supply arithmetic**: with 9 posts/monitor/30d measured, either add the other two
   monitors to `virlo_monitor_ids`, drop `run.formats.carousel` below 6, or accept
   famine skips by week 2 of a weekly cadence.
3. **Kie stuck-job rate** (11/30 at 180 s): consider raising the per-job image timeout
   or accepting the loss rate; timeouts never resubmit by design either way.
4. Deferred splits (design grounds): `copywrite.py` ~1,79x, `virlo.py` ~1,6xx,
   `runner.py` ~1,9xx, `gallery.py` 608 (deep-module review notes in the W3 reports).
5. Cosmetic: `vision_check_question.md` `_BUILT_INS` mirror was already drifted
   pre-session (not re-mirrored — only the 6 re-authored roles were); reconcile in a
   future docs pass.

## Operator eyeball items (cannot be verified mechanically)

- The Virlo UI grid vs the roster of `20260813_143047_j1f8` (THE acceptance test —
  mechanical proxies passed: dates in-window, grid authors present).
- Visual quality of `output/20260813_143420_oyo4/gallery.html`: do the rendered slides
  visibly reproduce the source panels' CONTENT (briefs drove composition), and does the
  text-only styling hold fidelity (OQ-23)?

## Session dispatch note

D46 slideshow-fidelity is COMPLETE (W0–W5). Next session, if any: operator decisions
above → new D15 cycle; otherwise Phase-2 (Postiz) or the deferred module splits.
