# SESSION B CLOSEOUT — Wave 1: additive contracts (2026-08-12)

**Status: COMPLETE and conductor-verified. Committed as `bf833cb`. Full suite 601 passed,
1 skipped (a deliberate W2 sentinel — see "W2 barrier obligations"). Next session: SESSION C
(Wave 2).**

## What shipped

1. **`plans/topic-first-pivot-contracts.md`** (conductor, BEFORE dispatch) — §1.8 items 1–16
   pinned from the actual code, plus a **W1 addendum** fixing T1.1's exact scope. Every W2
   dispatch prompt must quote its relevant section, same as W1's did. Conductor decisions
   recorded inside it (all disclosed, none silent):
   - `per_format_guidance` reserved marker `carousel_role: cover_only|slides_only` — the
     concrete encoding of §1.3's anchor-marker mechanism; `fmt_affine(s, "carousel")` excludes
     `slides_only` styles.
   - `SourcePost` gains `published_at` + `is_slideshow` beyond §1.6's list (FR-297b roster needs
     per-post age and type).
   - `TrendItem.topic_key`/`posts` added in W1 (models.py had its only wave writer now).
   - `CopySet.motion_beat` deferred to the W2 conductor micro-pass (do NOT add before the copy
     schema consumers are rewritten).
   - `source_hooks` placeholder is RE-PURPOSED in W2 as the §1.7 numbered-candidate slot — no
     new placeholder for candidates.
2. **T1.1 — models.py +141 (543→684), config.py +172 (791→963), ADDITIVE:** `MetaStyle`,
   `SourcePost`, `CopySelection`, `LayoutZone.role`, `PlanEntry.style_key/branded/topic_key`,
   `TrendItem.topic_key/posts`, tags `COPY_NOT_VERBATIM`/`COMPETITOR_STRIPPED`/
   `STYLE_REFS_MISSING`; `BrandingConfig` (both §1.4 profiles transcribed verbatim — conductor
   re-checked every hex/string), `StylesConfig(refs_per_job=2)`,
   `sources.virlo_topics_per_monitor=9` (−1 kill switch, 0 rejected), `_BOUNDS` + hex + brand-key
   validation. PLACEHOLDERS/PROFILE_TEMPLATES/GLOBAL_TEMPLATES untouched (verified by diff grep).
3. **T1.2 — NEW `hypesocials/styles.py` (471) + `hypesocials/topic_filter.py` (397):** full
   items 5/6 API. Rotation scan verified against the pinned pseudocode line-for-line
   (`styles.py:379-392`). `screen()`'s prompt path stubbed per the W1 scope note
   (`_system_prompt` raises `_FilterUnavailable`; the W2 wiring is written out in its docstring).
   `brand_ok`/`fmt_affine` exported (the pseudocode names them).
4. **T1.3 — NEW `tests/test_styles.py` (630, 37 ids) + `tests/test_topic_filter.py` (371,
   22 ids); DELETED `tests/test_reference_rotation.py` (451)** — the v2.2 blocker fix.
5. **Conductor barrier fixes:** the deleted file's one live invariant (retry-token parity with
   `llm.py`) re-homed verbatim into `tests/test_budget.py` (+28) and `budget.py:62`'s comment
   re-pointed (±0 lines); NAVIGATION.md §3 updated (new modules, new/deleted suites).

## Two barrier route-backs (both resolved in-wave)

1. **T1.1's `_coerce` isinstance guard** (needed — `branding.profiles` is the first
   `dict[str, dataclass]` field with pre-built defaults) initially made a PARTIAL profile
   override rebuild the profile from empty defaults, violating §1.4 "all overridable". Fixed via
   a generic dataclass-default unpack in `_merged`'s VALUE recursion (`config.py:699-728`,
   `_unpacked()`); placing it at `_merged`'s entry (the conductor's first sketch) would have
   destroyed FR-50 defaults-reporting — the agent proved that and shipped the narrower
   placement. Regression test:
   `test_config.py::test_fr292_a_partial_brand_profile_override_keeps_the_compiled_profile_around_it`.
2. **T1.3's 11 skipped guard tests** (gated on the W1-stubbed prompt path) were converted to run
   NOW by monkeypatching `topic_filter._llm_verdicts` — the wave table puts strip-guard coverage
   in W1, only the prompt path is T2.7's. The conversion immediately caught a wrong test
   expectation (duplicate LLM ordinals: the module defaults them to `keep` per contract; the
   test asserted `skip`) — exactly the defect class skips would have hidden until W2.

## Barrier evidence (conductor's own runs, not agent claims)

```
.venv\Scripts\python.exe -m pytest -q      -> 601 passed, 1 skipped in 6.34s
find hypesocials -name "*.py" | xargs wc -l | tail -1   -> 17,537   (baseline 16,356)
find tests -name "*.py" | xargs wc -l | tail -1         -> 11,502   (baseline 10,899)
```

**Production +1,181 with per-task attribution:** models.py +141 (T1.1), config.py +172 (T1.1,
incl. +21 route-back), styles.py +471 (T1.2), topic_filter.py +397 (T1.2), budget.py ±0
(conductor comment re-point). T1.2's files are over the plan's ~280/~140 sketches; the excess is
house-style module contracts and operator-facing error text, not logic sprawl — reviewed and
accepted (CLAUDE.md rule 5: growth reported, never capped; nothing explains less).

**Tests +603:** test_styles.py +630, test_topic_filter.py +371, test_reference_rotation.py −451
(T1.3); test_config.py +25 (T1.1 route-back); test_budget.py +28 (conductor).

Independent conductor greps: models.py diff has ZERO removed lines; config.py's only removals
are the `__all__` reflow; PLACEHOLDERS/PROFILE_TEMPLATES/GLOBAL_TEMPLATES byte-untouched; both
§1.4 profiles verbatim; rotation pseudocode faithful.

## W2 (SESSION C) barrier obligations — carry these into the next session prompt

1. **`pytest tests/test_topic_filter.py -q` must show 0 skips at the W2 barrier.** The one
   remaining skip (`test_the_prompt_path_is_still_stubbed_and_w2_must_unskip_this`) flips to a
   real end-to-end pass when T2.5's `topic_filter_system.md` + T2.6's placeholders/allowlist
   land. Still skipping = the wire-in is wrong.
2. **W2 conductor micro-pass on models.py** (per contracts items 2/4/10/14): PLACEHOLDERS
   ±per item 2 additions, `PROFILE_TEMPLATES["gpt-image-2"] += image_post.md`,
   `GLOBAL_TEMPLATES += topic_filter_system.md` (hygiene), `CopySet.motion_beat`,
   `AssetRecord.copy_source_post_id/copy_source_refs`; plus `config.py:179-182`/`:186-187`
   comment re-base. Transitional SHIPPED count 11 (T2.7 sets it).
3. **T2.2 inherits a pinned asymmetry** (T1.3 flag, conductor-endorsed): blocklist (layer-1)
   hits are deliberately UNGUARDED by M15 — a configured competitor that IS the topic's name is
   still stripped (fail-closed); only LLM-proposed strips pass the guards.
   `copywrite._apply_strip` must mirror this.
4. **T2.4 note:** `budget.py:62`'s parity comment now names `test_budget` — do not re-point it
   again during the T2.4 rewrite; the parity test lives at the end of `tests/test_budget.py`.
5. **Candidate-strings universe** (T1.2 disclosure, accepted): the topic filter's <15-char guard
   and blocklist scan run over each `SourcePost`'s caption/description/hooks/text_overlays/
   panel_texts PLUS topic-level `hook_texts`/`text_overlay_contents`/`panel_texts` (they still
   reach prompts via `{{trend_texts}}`). T2.2's offerable-candidate numbering uses the
   SourcePost set only (§1.7).
6. `prompts/styles.yaml` does not exist yet — T2.5 authors it per the §1.3 normalization table.
   Until then a live run would correctly exit 2 at FR-295. Nothing is wired into
   runner/preflight/generate yet (W2/W3 wire-in registry in plan §3 W5 table).

## Warnings for Session C (conductor experience, this session)

- The Wave-0 lesson held: BOTH route-backs found real gaps that agent self-reports called green.
  Re-grep and re-run everything yourself at the barrier.
- Route-backs work well: resume the SAME agent (SendMessage) with a precise fix spec — both
  agents corrected the conductor's sketch where the code proved it wrong, which is the point of
  giving them the why, not just the what.
- Parallel writers + parallel test authors against one pinned contract worked: zero file
  conflicts, one semantic disagreement (duplicate ordinals), and the contract text settled it.
- venv python only (`.venv\Scripts\python.exe`); $0 held ($0 spent this session).
