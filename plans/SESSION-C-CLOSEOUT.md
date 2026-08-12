# SESSION C CLOSEOUT — Wave 2: consumer rewrites (2026-08-12)

**Status: COMPLETE and conductor-verified. Committed as `35a793b`. Full suite 669 passed,
0 failed, 0 skipped (Session B baseline: 601 + 1 skip). Next session: SESSION D (Wave 3 +
Wave 3.5).**

Both Session-B barrier obligations landed: `pytest tests/test_topic_filter.py -q` → **27 passed,
0 skips** (the W1 sentinel flipped skip→pass the moment T2.5's template + T2.6's
placeholders/allowlist + the prompt-path unstub connected), and `test_template_parity` runs at
**TRANSITIONAL_SHIPPED == 11** (final 8 set at W3.5).

## What shipped (per task)

1. **T2.1 — `sources/virlo.py` 1,186→1,780 (+594).** `_themes`/`_split_topics` (one monitor →
   up to `virlo_topics_per_monitor` topics, exclusive post allocation, `-1` kill switch = the
   pre-pivot item shape byte-for-byte, `#2` slug-collision suffix), `SourcePost` extraction with
   the field map written INTO `_source_post`'s docstring (tests parse it — doc and code cannot
   drift), per-topic strength over each topic's own posts, `_digest` → 2-tuple, `_MAX_THEMES`
   deleted (both roles re-based), Counters per contracts item 15 (`add_topics`,
   `duplicates_dropped`, `record_filter` fields), FR-298 events `topic_posts`/`virlo_fields`/
   `topic_ranked` (the last NOT verbose_only — FR-5 wants it in the run log). Media bodies
   remain on disk unreachable under a "legacy, W3.5" banner.
2. **T2.2 — `copywrite.py` 596→1,210 (+614, incl. route-back).** Full §1.7: `_offer_for`
   candidate tables (`P<n>.<kind>[.<i>]` grammar), `CopySelection` call, ref→bytes resolution
   (budgets bypassed for ref-resolved fields; out-of-scope refs re-pointed to the assigned
   post), `_apply_strip` with the **pinned asymmetry** (layer-1 blocklist unguarded/fail-closed;
   only LLM strips pass M15), verifier tags `copy_not_verbatim` and never fails a creative,
   `_fallback_copy` ships the top post's caption VERBATIM + wordless frame, sibling *k* quotes
   `posts[reuse_index % len(posts)]`, `CopyProvenance(post_id, refs)` for FR-298.
   `_NEVER_ON_IMAGE = ("description",)` — Virlo's AI summary is caption material only
   (route-back, see below).
3. **T2.3 — `generate/refs.py` 128→291, `carousel.py` 443→484, `reel.py` 519→514 (+199 net,
   incl. route-back).** Style-window attach through the run-scoped `UploadMemo` (one upload per
   file per run, keyed by `run_dir`), `style_of`/`branding_block`/`wordmark`/`reset_uploads`
   public, F19 role line verbatim, M14 override suppression, `STYLE_REFS_MISSING`; carousel
   `_guided()` cover/slide guidance + anchor-only signature (M12 — slide 1 signs even unanchored
   decks, a disclosed and accepted deviation: the literal reading left fallback decks unsigned);
   reel = seed frame + Seedance, zero `video_urls`, director gets `reel_beats=beats_for(...)`
   and no branding block (M13 continuity rides `onimage_text`).
4. **T2.4 — `budget.py` 756→791, `preflight.py` 359→477, `notion.py` 271→319 (+201).**
   Style-brief pricing lines out, vision-check `analysis` pricing stays, `filter_call` at the
   worst-case topic bound **plus `filter_retry_allowance`** (deliberate extension — FR-107
   mandates a retry allowance per call; PRD beats the plan's singular wording), `siblings_of()`
   re-based off `pair_id` (the v2.2 blocker), `budget.py` parity comment untouched; preflight
   FR-295 registry refusal (exit 2, no built-in tier), branding backstop checks scoped to the
   active profile (config loader already hard-fails hex/selector — verified first), F22
   language-hint re-base; notion re-pointed at `BrandingConfig` override slots (dormant,
   `apply_brand_overrides` has NO caller yet — wire or drop at W3).
5. **T2.5 — `prompts/`.** NEW `styles.yaml` (8 styles, normalization table verified
   column-by-column, zero variant leaks, validates clean under the REAL W1 validator for BOTH
   brands, `carousel_role` markers, M8 literal exclusion strings quoted from the actual image
   files — every reference file was opened), NEW `topic_filter_system.md` (fence + ordinals +
   per-block isolation sentence + M15 guidance), NEW merged `gpt-image-2/image_post.md` (B2 +
   M7 + F23 + reworded wordmark prohibition), carousel/reel/copywriter templates re-based,
   README as co-maintained allowlist spec. Old templates untouched on disk (W3.5).
6. **T2.6 — `prompts_engine.py` 1,157→2,162 (+1,005; 629 of it the byte-mirrored `_BUILT_INS`)
   + `topic_filter.py` +19 (declared path-set extension: the W1 stub's `raise` replaced by its
   own docstringed wiring).** Item-1 `build_context` + addendum params (`wordmark`,
   `reel_beats`), public `branding_block()` (never_always/never_style split, brand-slot
   collapse), M6 `_strip_brands` over the five fields (lazy import of `apply_blocklist` — one
   policy, no cycle; `topic_filter` imports `prompts_engine` at module level), `_topic_items`
   ordinals + `_neutralize`, `style_dna(MetaStyle)` five rows no layout_grid, `beats_for`,
   `_source_hooks` → `""` (copywrite owns the slot), truncation order per F18, built-ins
   byte-identical to all 7 templates T2.5 touched (conductor re-verified byte-for-byte).
7. **T2.7 — core suites.** `test_virlo_refs.py` → `test_topic_split.py` (29 ids),
   `test_copy_no_verbatim.py` → `test_copy_verbatim_filter.py` (26 ids — the A20 polarity flip,
   verified at the assembled render prompt with a leak control), `test_prompts_engine` 27→47,
   `test_copywrite` 13→26, `test_virlo_data_channel` re-based (2-tuple digest, exemplar tier
   gone), `test_template_parity` at 11 + `TRANSITIONAL_ORPHANS` carve-out, fence assertions
   added to `test_topic_filter.py` (additive, sentinel untouched).
8. **T2.8 — render-path suites.** `test_steering_fixes` pruned to A12+A15 (A11/A16/A17 dead
   with their subjects — A11/A17 were beyond the literal prune list, disclosed and
   conductor-confirmed), `test_carousel` 32 ids, `test_reel` 25 ids, `test_generate_waves` 15
   ids on the post-pivot Env. Its wire-in-simulation plugin predicted the conductor wire-in's
   effect exactly (81/81).
9. **Conductor.** models.py micro-pass (PLACEHOLDERS +5, PROFILE_TEMPLATES += image_post.md,
   GLOBAL_TEMPLATES += topic_filter_system.md, `CopySet.motion_beat`, `AssetRecord` +=
   `copy_source_post_id`/`copy_source_refs` **+ the FR-73 identity quartet
   `style_key`/`brand`/`branded`/`topic_key`** — item 14 was short those four, PRD-confirmed,
   addendum item 7), config.py:188-196 comment re-base (values unchanged),
   `generate/__init__.py` Env diff (−4 fields −`brief_for`, +`styles`/`branding`/
   `copy_provenance`), `_assemble` → `ROLE_IMAGE` + item-1 call (content-sentence splice dead —
   the merged template carries the slot), `_record` writes the quartet + FR-298 receipt,
   `_ref_source` → `"style" | "brief"` via `refs.style_of`, `refs.branding_block` by-name seam
   collapsed to a direct call, `motion_profile` defaults `"photographic"` when style is None
   (disclosed decision + one test assertion updated), `virlo_mcp/server.py::_norm_theme` +=
   `evidence_video_ids` (activates the T2.1 evidence pre-pass; unscheduled micro-edit,
   disclosed), prompts/README two re-points, contracts **W2 addendum items 1–8**, NAVIGATION.md
   (§ modules, § tests, the A20 paragraph reversed, the split-threshold table). Barrels needed
   NO changes (`fetch` signature unchanged; nothing new exported; recorded, not skipped).

## Conductor decisions & disclosed deviations (all in the contracts W2 addendum)

1. **Micro-pass rescheduled to wave START** (plan said "after children"): `CopySet.motion_beat`,
   the placeholders and `Env.styles/branding` were hard dependencies of T2.2/T2.3/T2.6.
   Lockstep held — the wave is atomic and the barrier is at its end. Mid-wave reds were
   predicted exactly (5) and converged.
2. **`build_context` gained `wordmark: str = ""` and `reel_beats: str = ""`** (addendum 1/3) —
   item 1 had no branded channel and F24a's beats had no placeholder. Branded ⇔ wordmark
   non-empty, gated at the caller.
3. **Candidate numbering is single-source in `copywrite`** (addendum 4, supersedes its own first
   draft — T2.2's implementation decided it; copywrite overwrites `context["source_hooks"]`).
4. **T2.4's path set extended** with minimal `tests/test_budget.py`/`test_preflight.py`
   co-changes — a genuine plan sequencing gap: both suites are T3.5's (W3) but assert surfaces
   T2.4 changes, and the W2 barrier demands full green. Full rewrites stay T3.5.
5. **`filter_retry_allowance`** shipped beside the plan's singular "filter line" (PRD FR-107).
6. **Trendless-brief copy keeps a free-text path** (T2.2's resolution of T2.5's reference-only
   prompt vs §1.7.5): override briefs use the legacy `CopySet` schema + FR-101 trim; shipping
   them wordless would regress FR-144/146. The copywriter template treats it via
   `_sibling_list`'s slot. Revisit when W3/W4 touches the template.

## Route-backs (three, all resolved in-wave)

1. **T2.3 + addendum:** wordmark/beats call sites added after the contracts amendment (the
   agent's slide-1-always deviation accepted).
2. **T2.2 (barrier fix):** T2.7's strict-xfail caught `P<n>.description` offerable as on-image
   text — the cross-module contract virlo's docstring assigns to copywrite. Fixed
   (`_NEVER_ON_IMAGE`), xfail removed, one stale expectation in `test_copywrite.py` corrected.
   The Wave-0 lesson held AGAIN: an agent-green wave still carried a real cross-module gap that
   only an independent test author + conductor barrier surfaced.
3. **Conductor's own collision:** my `motion_profile="photographic"` default landed after T2.7
   froze its assertion — one test updated with the decision comment.

## Barrier evidence (conductor's own runs)

```
.venv/Scripts/python.exe -m pytest -q                    -> 669 passed in 5.56s   (0 failed, 0 skipped)
.venv/Scripts/python.exe -m pytest tests/test_topic_filter.py -q -> 27 passed, 0 skips (sentinel PASSED)
find hypesocials -name "*.py" | xargs wc -l | tail -1    -> 20,198   (baseline 17,537)
find tests -name "*.py" | xargs wc -l | tail -1          -> 13,168   (baseline 11,502)
```

**Production +2,661 with per-task attribution:** virlo.py +594 (T2.1), copywrite.py +614
(T2.2), prompts_engine.py +1,005 + topic_filter.py +19 (T2.6), refs/carousel/reel +199 (T2.3),
budget/preflight/notion +201 (T2.4), models.py +34 / generate/__init__.py −11 / config.py ±0 /
virlo_mcp/server.py +6 (conductor). ~403 of virlo's lines are unreachable legacy awaiting W3.5;
629 of prompts_engine's are the byte-mirror table. Nothing anywhere was shortened by explaining
less (models.py/config.py deletions re-verified comment-only by diff).

**Tests +1,666:** T2.7 +1,111 across 7 files (two renames), T2.8 +374 across 4, T2.4 +183
co-changes, conductor +route-back deltas ±small.

**Independent conductor verification (not agent claims):** styles.yaml re-validated with the
real `styles.validate` under BOTH brands (zero errors/warnings — T2.4's mid-wave variant-leak
sighting was a stale snapshot of T2.5's in-progress file); built-ins re-diffed byte-for-byte
against all 7 touched templates; wordmark/reel_beats call sites grepped; budget parity comment
grepped; models/config diffs re-read line-by-line; git status clean of stray files (no logs/ or
output/ writes).

## PRD/plan conflicts recorded (D15 follow-ups owed, none blocking)

1. **`prds/50-promptcraft.md` §5 copywriter placeholder list** names `topic_texts` (real name:
   `trend_texts`) and `competitor_list` (pinned to the filter role only) — needs a D15
   correction. (T2.5)
2. **`prds/30-configuration-and-run.md:73` `cs` hint** not re-based by Wave 0; T2.4 shipped a
   superset (config trigger kept verbatim + verbatim-copy trigger added). Amend or accept.
3. **FR-18 "default 3" vs `StylesConfig.refs_per_job = 2`** (contracts/W1 value, from operator
   decision #3 "1–2 per style"). Also FR-18's "3 total" reading vs refs_per_job-as-style-window
   (implemented per contracts item 13). Both need one D15 sentence. (T2.3)
4. **`_WEIGHTS` conflict resolved PRD-ward** (engagement 0.20 weighs the rank; theme
   `confidence` populated/logged but unweighted — FR-5/FR-293 explicit). One-line revert exists
   if the operator wants the plan's reading. (T2.1)
5. **`BrandProfile.hypelead.background_hint` carries an unresolved "…, or …" variant** — §1.4
   verbatim transcription, M9-shaped defect, dormant (`mode` defaults `overlay`). Decide at
   T3.4 when configs land. (T2.6)
6. **`vision_check_question.md` built-in has pre-existing prose drift** from its file
   (placeholder sets match — both empty; parity test passes). Not from this wave; reconcile
   whenever that template is next touched. (T2.6)

## W3 (SESSION D) obligations — carry into the next session prompt

1. **Runner call deltas are pinned in the T2.2/T2.4/T2.6 reports and this file:** `_write` drops
   `style_briefs`/`copy_exemplars`, gains `styles=`/`competitors=`/`strip_brands=` (keyed by
   trend_key — the runner maps `_screen_topics`' ordinal-keyed verdicts); Env construction adds
   `styles=registry`, `branding=config.branding`, `copy_provenance=copy_result.provenance`;
   `runner._posts_used` currently reads fields virlo no longer fills → history records NOTHING
   until T3.2 re-bases it onto `SourcePost` (silent, known).
2. **LLM-proposed `brands_to_strip` do not reach render prompts yet** — `_assemble` passes only
   `branding.competitors` (fail-closed layer). W3's runner must thread verdict brands into the
   generate path (Env field or per-entry mapping) to fully honour M6 at the prompt for
   LLM-discovered brands. CopySet-level strips DO already carry them (copywrite).
3. **`Counters.record_filter` has no caller** until `runner._screen_topics` (item 9). The funnel
   block still prints media rows as structural zeros until the W3 re-shape.
4. **`_free_text_schema` excludes `"hook_pattern_used"`** (copywrite) — drop the entry when the
   field dies at W3.5. **W3.5 excision list additions:** virlo's `_build_item` (do NOT delete
   before T3.5 re-bases `test_funnel_report._tallied()` — collection-time failure otherwise),
   the five motion-chain DegradationTags (contracts item 7 note), `_NEVER_ON_IMAGE` stays.
5. **`prompts/README.md:136`** still shows the truncation tail with `source_hooks` after
   `content_sentence` — T2.6 matched it; fine — but the §7 table must be re-checked at W3.5 when
   six placeholders die.
6. **test_budget.py / test_preflight.py carry fenced W2 sections with T3.5 pointers** — T3.5
   folds them into its rewrite, it does not duplicate them.
7. **apply_brand_overrides (notion.py) has no caller** — wire at Collect under `influence ==
   "full"` + barrel export, or delete the helper (T2.4 offered both).
8. **Deep-module reviews owed post-W5:** virlo.py (~1,377 post-excision), copywrite.py 1,210
   (candidate/resolution sibling module named), prompts_engine.py 2,162 (shrinks at W3.5).

## Warnings for Session D (conductor experience, this session)

- **The barrier caught a real defect an all-green agent wave missed** (description-on-image) —
  because a test author was independent of the implementer and the conductor ran everything
  again. Keep doing both.
- **Batch 2 concurrency worked but cost three small collisions** (T2.6 read pre-route-back
  files; T2.7 froze an assertion my late decision changed; T2.2's route-back needed one line in
  T2.7's file). All cheap, all caught — but sequence the conductor's OWN decisions before
  dispatching test authors next time.
- Route-backs by SendMessage to the SAME agent remain the right tool: all three resumed with
  full context and shipped surgical diffs.
- venv python only; **$0 spent** (no live API call anywhere in the wave; every LLM/HTTP seam
  faked; fixtures used for Virlo payloads).
