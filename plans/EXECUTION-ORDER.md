# Execution order — how to run the two plans across sessions

**Written 2026-08-11.** Read this before invoking `/xecutor` on either plan.

Two approved plans exist and they **share a path set**, so they cannot run concurrently:

| Plan | Scope |
|---|---|
| `plans/xmasterplan-virlo-throughput-and-fidelity.md` | Increment A (A1–A24, **minus superseded A22/A23/A25**), then Increment B |
| `plans/xmasterplan-copy-voice-transposition.md` | V1 + V2 — the copy-voice rebuild |

---

## The shape: wave-by-wave, parallel inside each wave

**Not all at once.** Three reasons, all evidenced in this repo:

1. **Barriers have already caught real defects.** The last Wave-0 agent on this project shipped a wrong FR,
   missed 5 required edits, and silently deleted a PRD abort cause. Adversarial review then refuted or
   corrected **14 claims** in the first plan draft, including two blockers and one runtime-breaking omission.
   Without a barrier those propagate into every downstream wave.
2. **Shared files would collide.** `runner.py`, `prompts_engine.py`, `models.py` and `copywrite.py` are each
   written by several waves. One writer per wave is the only thing keeping that safe.
3. **Later waves consume earlier output.** The funnel counters (A19) count what A2/A3 changed. The copy audit
   (V2a) imports `surface.py` from V1a. `target_chars` (V2b) needs V1c's builders.

**Parallel inside a wave** wherever path sets are disjoint — the plans already mark those with `‖`, and the
disjointness has been verified file by file.

**Flat dispatch throughout** (CLAUDE.md §9a). No orchestrating parent anywhere. The main thread is the sole
conductor, applies every wire-in itself, and owns the aggregating files (`runner.py`, `CLAUDE.md`,
`NAVIGATION.md`).

---

## ⏰ The one hard deadline

**The Virlo free trial expires ~2026-08-13.** After that, no live API calls.

Two consequences that drive the whole order:

1. **The sort fix must be verified live first.** It is the single biggest quality lever measured
   (766× median views, ~2× `intelligence{}` coverage) and **every downstream improvement operates on the
   material it selects.** Verifying it last would mean verifying nothing.
2. **Capture a fixture corpus before the trial dies.** Session 1 records real API responses to
   `tests/fixtures/virlo/` so Sessions 2–4 can be developed and tested entirely offline. This is cheap
   insurance nobody has budgeted for, and without it a lapsed trial blocks the remaining ~1,200 lines.

If the paid plan is activated, the deadline disappears but the order stays correct anyway.

---

# SESSION 1 — trial-critical foundation

**Goal: the sort fix and the LLM fixes, verified live, plus a fixture corpus.**
This is the smallest set that delivers the largest measured improvement, and the only set that genuinely
needs the live API.

**Paste this entire block as one message** — the `/xecutor` command is line 1. Do not paste the
surrounding triple backticks.

```
/xecutor Execute plans/xmasterplan-virlo-throughput-and-fidelity.md — Increment A ONLY, waves A0
through A2, plus the fixture capture below. Do NOT start A2', A2'' or A2''' this session.
Read plans/EXECUTION-ORDER.md first for the standing rules that apply to every session.

Scope this session:
  Wave A0  - PRD amendments A-P3..A-P12 (technical-writer). A-P1/A-P2 are ALREADY APPLIED to
             CLAUDE.md and NAVIGATION.md - verify, do not redo.
  Wave A1  - A5,A6,A7,A8 (LLM token fixes) || A1 (wrapper: params + enum validation, never send
             `offset`). Two python-pro agents, one message.
  Wave A2  - A2 (adapter sort), A3 (reference rotation), A4 (per-group briefs), A10 (reuse cap 6),
             A13 (3 intelligence fields), A14 (real hashtags), A18 (digest exemplars). One python-pro.
  NEW      - FIXTURE CAPTURE, before any live verification: write tests/fixtures/virlo/ containing
             real responses for /agents, /agents/{id}, /agents/{id}/trends/latest, and
             /agents/{id}/videos + /slideshows at limit=100&order_by=views&sort=desc. Redact nothing
             except the key (which is never in a response body). These become the offline corpus for
             sessions 2-4.

Barriers are mandatory and non-negotiable:
  - After A0 the conductor RE-READS every amended PRD anchor against the file and diffs it against
    the plan's section 3.1. Reports are not evidence - the last Wave-0 agent on this repo shipped a
    wrong FR and deleted an abort cause.
  - After A1: pytest -q green, plus the OFFLINE truncation-ladder test (stub finish_reason=="length"
    on all attempts, content=="" on the last; assert a non-empty reason and only two attempts).
    No network, no spend.
  - After A2: pytest -q green.

Then live-verify, in this order, and report the real numbers:
  1. --list-monitors                                    -> exit 0
  2. --preview-sources --config hypedigitaly            -> view counts in the SORTED range
     (expect median around 1.9M for videos / 280k for slideshows, NOT 2.5k / 7k)
  3. --preview-analysis --config hypedigitaly           -> ZERO llm_truncated events (costs LLM spend)
  4. one paid run, low cap, 6 creatives                 -> 6 DIFFERENT reference image sets

Report the wc -l with per-task attribution using:
  find hypesocials -name "*.py" | xargs wc -l | tail -1
NEVER `wc -l hypesocials/**/*.py` - globstar is off in this shell and it counts 20 of 39 files.
```

**Success looks like:** sorted view counts, zero truncation, six visibly different image sets, and a fixture
corpus on disk. If step 2 still shows ~2,500 median views, the sort did not reach the wire — stop and
diagnose before continuing.

---

# SESSION 2 — the rest of Increment A · ✅ COMPLETE (2026-08-11)

**Goal: steering, visibility, and the plagiarism guardrails the copy plan depends on.**
Fully offline except the final check.

> ✅ **Done. Waves A2′, A2″, A2‴ and A3 all landed and all barriers were met.** Closeout, with everything
> Session 3 needs: **`plans/SESSION-2-CLOSEOUT.md` — read it before starting Session 3.**
>
> - 🔒 **A20 is GREEN, so Session 3 is unblocked.** Verified at the *assembled render prompt* across all
>   four image roles and all three formats: zero competitor strings, `onimage_text` slot empty.
> - Baselines for attribution: **522 tests passed** (from 425), `hypesocials/` **16,265** lines (from
>   14,930), `tests/` **10,724** (from 8,905).
> - ⚠️ **Three Session-2 contracts now live in files Session 3 edits** — `prompts/copywriter_system.md` is
>   **read by tests** (the A21 bar: 30 chars / 4 content words / five rejected phrases must match the code
>   constants both ways); `{{inspiration_exemplars}}` is allowlisted for that template alone and sits at
>   position 3 of `_TRUNCATION_ORDER`; and `_BUILT_INS` parity is now enforced by
>   `tests/test_template_parity.py`. See closeout §3.
> - ⚠️ **Forecasts ran 6–8× under** on the two biggest waves. Increment B's estimates were written by the
>   same method — recalibrate before trusting them. See closeout §2.
> - Four findings recorded and deliberately unfixed (closeout §5), incl. one the conductor **attempted and
>   reverted** with the reason written down.
> - **Live verification (plan §3.4 / wave A4) is still outstanding** and needs the trial (expires
>   ~2026-08-13).

```
/xecutor Execute plans/xmasterplan-virlo-throughput-and-fidelity.md — Increment A, waves A2' through A3.
Session 1 is complete; do not redo it. Use tests/fixtures/virlo/ instead of live calls.

  Wave A2'  - A11 (brand.accent -> {{brand_accent}}), A12 (blank-subject bug on override-brief
              images), A15 (niche.visual_world reaches direct mode via a NARROW visual-only slot,
              NOT by allowlisting the whole niche_descriptor), A16 (inspiration .txt files),
              A17 (exclusive-mix rotation).
              python-pro (config.py, sources/inspiration.py, prompts_engine.py)
              || prompt-engineer (prompts/**). Two agents, one message.
  Wave A2'' - A19 (the funnel report). Runs AFTER A2' because it counts what A2/A2' changed.
              One python-pro.
  Wave A2'''- A20 (no verbatim-hook fallback) and A21 (validate hook_pattern_used) ONLY.
              A22, A23 and A25 are SUPERSEDED - see the stop-notice at the top of that plan.
              Also A24 (console post inventory + the brief). One python-pro || one prompt-engineer.
  Wave A3   - test rework. test-automator, tests/** only.

Barriers:
  - A2': an assembled prompt shows a NON-BLANK "BRAND INFLUENCE:" line (it has been blank on every
    run ever made) and a non-blank "SUBJECT AND SCENE:" on an override-brief image.
  - A2'': every funnel line asserted <= 78 chars; counters reconcile (input - dropped = output at
    every stage); the block prints on --preview-sources.
  - A2''': a FORCED copy failure renders with EMPTY on-image text - never a scraped hook, never the
    source deck's panel copy. Asserted in a test.
  - A3: full pytest -q green.

Final check (offline against fixtures, then one cheap live run if the trial is still alive):
  --preview-sources and --preview-analysis print the funnel block and the post inventory.
```

⚠️ **A20 is the gate on Session 3.** The copy-voice plan puts 100% of the source text into the prompt; doing
that while the engine still renders scraped hooks verbatim would raise real reproduction risk. Do not start
Session 3 until A20 is green.

---

# ~~SESSION 3 — copy voice V1~~ CANCELLED (2026-08-12)

**This plan (xmasterplan-copy-voice-transposition.md) is superseded by the Topic-First Pivot (xmasterplan-topic-first-pivot.md). Sessions 3 and 4 are cancelled. The pivot removes A/B mode, vision analysis, and the copy-transposition work entirely. Copy is now verbatim-selection only (D42). See plans/xmasterplan-topic-first-pivot.md for the new session structure.**

---

# ~~SESSION 4~~ CANCELLED (2026-08-12)

**See SESSION 3 note above.**

---

# SESSION A — Wave 0 (PRD amendments, no code)

**Goal: Amend all seven PRDs for the topic-first pivot and rebuild the overview + HTML snapshot.** COMPLETE (2026-08-12)

```
/xecutor Execute plans/xmasterplan-topic-first-pivot.md — Wave 0 (PRD amendments only).

  T0.1 - Amend prds\10-pipeline.md + prds\20-integrations.md per §2 (technical-writer, prds/ only)
  T0.2 - Amend prds\30-configuration.md + prds\40-outputs.md + prds\50-promptcraft.md per §2
         (technical-writer, prds/ only)
  T0.3 - Amend prds\00-overview.md with D41–D45, rebuild pipeline diagram per spec,
         rebuild prds\PRD.html from amended sources, update plans\EXECUTION-ORDER.md
         (technical-writer, after T0.1 & T0.2 complete)

Barriers:
  - After T0.1 & T0.2: conductor re-reads every amended anchor; grep for dead FRs (FR-3/9/10/11/12/16/22/33/
    92/93/128/134/142/160–163/199/247, plus pair_id/text_only/both/style_brief/yt-dlp/video_ref).
  - After T0.3: Mermaid diagram in 00-overview.md parses; grep for dead terms → only amendment-log hits remain.
```

---

# SESSION B — Wave 1 (additive contracts; nothing deleted)

**Goal: new models/config symbols + styles.py + topic_filter.py + their test suites; full suite stays green.**

```
/xecutor Execute plans/xmasterplan-topic-first-pivot.md — Wave 1 only.

  FIRST (conductor, before any dispatch): write plans/topic-first-pivot-contracts.md per §1.8
  (items 1–16, from the actual code). Every W1/W2 dispatch prompt quotes its relevant section.

  T1.1 - models.py + config.py ADDITIVE ONLY per §3 (python-pro; sole writer of those files this wave;
         NO PLACEHOLDERS/PROFILE_TEMPLATES additions — those are W2 conductor work)
  T1.2 - new hypesocials\styles.py + hypesocials\topic_filter.py per §1.3/§1.5 + pinned API
         (python-pro, parallel; screen() prompt path ships stubbed per the W1 scope note)
  T1.3 - tests\test_styles.py + tests\test_topic_filter.py against the contracts doc
         (test-automator, parallel) + DELETE tests\test_reference_rotation.py (blocker fix)

Barrier (conductor):
  .venv\Scripts\python.exe -m pytest -q                      # FULL suite green
  find hypesocials -name "*.py" | xargs wc -l | tail -1      # growth w/ per-task attribution
```

---

# SESSION C — Wave 2 (consumer rewrites; legacy symbols still importable)

**Goal: virlo topic split, verbatim copywrite, refs/carousel/reel, budget/preflight, prompts + styles.yaml, prompts_engine, test rewrites.**

```
/xecutor Execute plans/xmasterplan-topic-first-pivot.md — Wave 2 only.

  T2.1 virlo.py topic split (+ topic_posts/virlo_fields/topic_ranked events)     T2.5 prompts\** + styles.yaml
  T2.2 copywrite.py reference-selection verbatim (+ copy_source_refs)            T2.6 prompts_engine.py
  T2.3 generate\refs.py + carousel.py + reel.py                                  T2.7 test rewrites (T2.7 list)
  T2.4 budget.py (incl. siblings_of fix) + preflight.py + sources\notion.py      T2.8 render-path test suites

  Conductor wire-in AFTER children (per §3 W2 list): models.py micro-pass (placeholders/templates),
  config.py comment re-base, generate\__init__.py Env diff, barrels.

Barrier: full pytest green + line attribution.
```

---

# SESSION D — Wave 3 + Wave 3.5 (orchestration, surfaces, then the excision)

**Goal: plan/previews/gallery/state/cli/menu + conductor runner rewiring + §1.10 console surfaces; then the conductor-only excision of all legacy code.**

```
/xecutor Execute plans/xmasterplan-topic-first-pivot.md — Wave 3, then Wave 3.5.

  T3.1 plan.py + previews.py       T3.4 configs\*.yaml + niches\**      (§3 wave-3 table)
  T3.2 gallery/packager/state      T3.5 the 8 test files (quote the pipeline stage order VERBATIM)
  T3.3 cli.py + menu.py (FR-300)   T3.6 console-inventory + menu tests (§1.10 assertions)

  Conductor wire-in LAST: runner.py pipeline + §1.10 surfaces (stage headers, topics table,
  provenance block, note() seam, heartbeats in generate\__init__.py, funnel-once, collect liveness,
  root-logger fix, gallery path lines).

  Wave 3.5 (conductor only, no subagents): the complete excision list in §3 W3.5 incl. the
  stale-prose sweep; then the word-boundary barrier grep (v2.2 terms) → 0 hits; full pytest green.
```

---

# SESSION E — Wave 4 + Wave 5 (hardening, docs, live verification)

**Goal: branding tests + docs; then the operator-present paid verification run.**

```
/xecutor Execute plans/xmasterplan-topic-first-pivot.md — Wave 4, then Wave 5 with the operator.

  T4.1 tests\test_branding.py (floor-predicate assertions per §1.4 v2.2)
  T4.2 README.md + ACCEPTANCE.md; conductor merges NAVIGATION.md + CLAUDE.md
       (stack: yt-dlp AND Pillow out; registry no-fallback note; glossary)

  Wave 5 (operator present, cheapest first, per §5): --list-monitors → --preview-sources ($0) →
  --preview-analysis (LLM only) → ONE paid run (8 creatives incl. 1 carousel + 1 reel,
  brand hypelead, ratio 0.5, low cap) against the §5 checklist INCLUDING the v2.3 observability
  items; wc -l with attribution vs 16,356; deep-module re-review recorded in the closeout.

Each session writes plans/SESSION-<X>-CLOSEOUT.md; the next session reads it first.
```

---

# SESSION F — Slideshow Fidelity Waves 0–2 (D46 amendments + sources + copy)

**Goal: PRD amendments per the APPROVED plan, then the fetch-window/slideshow-only source
layer and the on-image/panel-mapped copy layer.**
Plan: `plans/xmasterplan-slideshow-fidelity.md` (v2.1 APPROVED+REVIEWED 2026-08-13 — §0
defaults are SETTLED there incl. the operator's all-carousels override and §0.9–0.14;
flag §0.9–0.14 once at dispatch, then proceed).

```
/xecutor Read plans/SESSION-E-CLOSEOUT.md first, then execute SESSION F (Waves 0-2) of
plans/xmasterplan-slideshow-fidelity.md.

  W0  T0.1 conductor: apply §2 in full across prds/*.md (D46, FR-301..309, v2.1.0);
      rebuild 00-overview mermaid + BOTH FR-range surfaces + amendment log; republish the
      PRD artifact (same URL); barrier = sibling-consistency read + artifact RENDERS.
  W1  T1.1 sources/virlo.py + models.py SourcePost block (window, triple gate, counters
      incl. funnel lines, index-aligned panels) · T1.2 config.py+configs (keys, 30/30
      invariant, §0.14e guard, budgets, all-carousels, t2i default) · T1.3
      sources/slide_intel.py + prompts/slide_intel_question.md + packager store_source()
  W2  T2.1 copywrite.py + models.py PlanEntry/AssetRecord (grammar-level description
      removal, §0.14b, panel mapping, bound-post, reuse-index retirement) · T2.2
      plan.py+carousel.py+budget.py (ASSIGN-time binding, deck length, estimator,
      no_fresh_post_available) · T2.3 conductor: runner/previews/prompts_engine/menu +
      parity-keeping template stubs; slide_intel wired POST-CONFIRM

  Barriers: W1/W2 = full pytest green — each task updates the tests its change breaks
  IN-WAVE (break-map in plan §4); line report w/ attribution.
```

---

# SESSION G — Slideshow Fidelity Waves 3–5 (styles, tests/docs, live ladder)

**Goal: style-ref excision + registry re-author; test/doc re-base; operator-present ladder.**

```
/xecutor Read plans/SESSION-F-CLOSEOUT.md first, then execute SESSION G (Waves 3-5) of
plans/xmasterplan-slideshow-fidelity.md.

  W3  T3.1 refs.py/styles.py/preflight.py excision · T3.2 prompt-engineer: styles.yaml
      re-author (text-only DNA, raised caps — §0.5 becomes effective here) + full template
      re-author · T3.3 gallery.py + generate/__init__.py (FR-309 provenance cards,
      override fallback, _record() provenance join)
  W4  T4.1 NEW regression tests only (no-repeat guard, invariant, §0.14 edges, gallery,
      slide_intel mocked, panel-map E2E) · T4.2 README+ACCEPTANCE
      · conductor: NAVIGATION.md + CLAUDE.md merge
  W5  (operator present, cheapest first, per plan §5): --list-monitors → --preview-sources
      ($0 — topics must mirror the Virlo UI grid; THE acceptance test; record the measured
      supply figure into FR-307's placeholder) → --preview-analysis (panel-mapped copy +
      visual briefs visible, no P*.description) → ONE paid run (all-carousels mix, low cap)
      → byte-verify panel_map + source.yaml → NO-REPEAT PROOF (re-run --preview-sources,
      quoted posts now under dropped_used) → closeout + PR.
```

---

# SESSION H — Carousel Copy Compress Mode + Style Doubling-Down (v2.3.0, D54/D55)

**Goal: operator-toggled compress+humanize copy mode for panel-mapped carousels; style registry
doubled down to 4 keys incl. the new `quiet-luxury-night-photoreal` style.**

```
/xecutor Read plans/SESSION-5.8-CLOSEOUT.md first, then execute ALL waves of
plans/xmasterplan-compress-mode-and-style-doubledown.md (SESSION H).

  W1  PRD amendments FIRST (D15): D54+D55 rulings, FR-331/332/333 blocks,
      FR-99/100/101/302/303/304(d) amendments, FR-73 meta keys, FR-56 six prompts,
      FR-259, FR-133, diagram rebuild + amendment log v2.3.0
  W2  Code: C-a python-pro config/cli/menu (carousel_copy_mode key + compress pinned in the
      three brand configs, --copy-mode flag, wizard step + wizard_help)
      · C-b python-pro copywrite core (mode threading, group split by mode, _call_compress,
        _compressed_deck ONE-walk texts+panel_map, quoted=() receipts, fallback to the
        verbatim mapped deck) + models.CopyCompressed + AssetRecord.copy_mode + runner
        + console surfaces (runner:925, previews:356, preflight:605/622, FR-297c block)
      · C-c prompt-engineer (copy_compress_system.md + _BUILT_INS twin + _ALLOWLIST row
        + _budget_line compress branch; vendor prompts/humanizer_skill.md from
        github.com/blader/humanizer SKILL.md, MIT, verbatim)
  W3  Styles, SAME change: author quiet-luxury-night-photoreal in prompts/styles.yaml
      + styles.enabled 4-key list in all three brand configs
  W4  Tests re-base (copywrite, copy_verbatim_filter, config, menu, styles, prompts_engine,
      template_parity, gauntlet dry-run one-walk invariant, gallery marker, console_inventory,
      preflight/previews wordings) · conductor: CLAUDE.md glossary D54 carve-out + NAVIGATION.md
  W5  (operator present, cheapest first): pytest -> --list-monitors / --preview-sources ($0)
      -> --preview-analysis (LLM-only: compressed texts within min(config,style) budgets,
      source language kept, humanized, no handles/URLs) -> ONE paid run (2 carousels, low cap)
      -> meta.yaml / gallery / gauntlet inspection (zero translated/identity_leak, no
      missing_text) -> SESSION-H-CLOSEOUT.md
```

---

# SESSION I — Style Intelligence: archetype expansion + LLM-matched assignment + teal spine (v2.4.0, D56/D57) · ✅ W1–W4 COMPLETE (2026-08-20)

> ✅ **Waves 1–4 landed; suite 1481 → 1567, zero failures.** Closeout:
> **`plans/SESSION-I-CLOSEOUT.md` — read it before starting the next session.**
>
> ⚠️ **W5's PAID RUN IS STILL OWED and deliberately not automated.** Rungs 1–4 are green for
> $0.27 (`--preview-analysis` proved the matcher live: 3/3 matched at `high`, both winning
> styles D56 archetypes authored this session). The paid run is the last rung because its
> acceptance is visual and human: the Confirm-gate `style_match_call` line, the teal spine
> across styles, `build-log-mono`'s chrome grid, and **gauntlet green on `social-quote-card`
> and `terminal-mockup-deck`** — the two UI-grammar styles closest to other styles'
> no-platform-marks exclusions, and the highest-risk authoring in the session.
>
> Nine defects outside the plan were found and fixed (two FR-286 console truncations that hid
> operator instructions, a launch block under-reporting the style pool 18-vs-12, a broken
> `AGENTS.md` hardlink, and `run_deadline_min` doc drift the conductor initially propagated).
> Closeout §4 has all of them; §6 lists the four operator decisions owed.

**Goal: registry 9→19 (build-log-mono + 4 census-driven archetype styles + 5 teal variants), an LLM
matcher at ASSIGN that picks the best-fitting enabled style per creative (rotation fallback + gap
report), and the teal-spine color unification — 12-key enabled pool, `styles.assignment: matched`
pinned in the three brand configs.**

```
/xecutor Read plans/SESSION-H-CLOSEOUT.md first, then execute ALL waves of
plans/xmasterplan-style-intelligence.md (SESSION I).

  W1  PRD amendments FIRST (D15): D56+D57 rulings (census table as rationale, no-real-platform-marks
      brand-safety note), FR-334/335/336/337 blocks, FR-290/291 amendments, FR-73 meta keys,
      style-count re-base 9->19 in all sibling files, diagram STY/ASSIGN nodes,
      amendment log v2.4.0, PRD.html rebuild + artifact republish (diagram must render)
  W2  Registry+prompts+configs: T2.1/T2.1b prompt-engineer prompts/styles.yaml (build-log-mono,
      5 teal variants, 4 archetype styles, match_profile on all 19 — ONE writer, sequential)
      · T2.2 prompt-engineer style_match_system.md · T2.3 prompts/README.md
      · T2.4 configs (12-key styles.enabled + assignment: matched in the three brand configs;
        default.yaml documents assignment + D57 pointer)
  W3  Engine: T3.1 models.py (match_profile, PlanEntry/AssetRecord provenance fields,
      DegradationTag, PLACEHOLDERS, GLOBAL_TEMPLATES) · T3.2 styles.py (parse + match_profile_for
      + advisory warning) · T3.3 NEW style_match.py (batched fail-open matcher, asset_id join,
      pool validation, topic_filter pattern) · T3.4 config.py knob · T3.5 prompts_engine
      allowlist + built-in twin · T3.6 runner.py (_assign_visuals async + matched branch +
      receipt columns + gap report + degraded warn) · T3.7 previews deep-stage wiring
      · T3.8 budget.py style_match lines · T3.9 generate/_record mapping + tag
      · T3.10 gallery label + wanted note
  W4  Tests (test_styles, template_parity 8->9, test_prompt_fit pin 9->19, test_budget,
      test_config, console_inventory, test_gallery, NEW test_style_match offline suite)
      · conductor: CLAUDE.md glossary matched-mode carve-out + NAVIGATION.md
  W5  (operator present, cheapest first): pytest -> --list-monitors / --preview-sources ($0,
      19-entry registry validates) -> --preview-analysis (LLM-only: matcher picks visible with
      origin/fit/reason, gap report, style_match_call estimate line; then once more with
      assignment: rotation -> byte-identical to pre-session picks) -> ONE paid run (2-3
      carousels, low cap) -> meta.yaml provenance fields + gallery labels + teal-spine visual
      check + gauntlet green on the two UI-grammar styles -> SESSION-I-CLOSEOUT.md
```

---

# SESSIONS J–N — Render quality, design system, and language (v2.5.0 → v2.7.0, D59–D63) · ✅ COMPLETE (2026-08-20 → 2026-08-21)

> ✅ **All five sessions landed on branch `session-k-colour-type-spine` (J → K → L → M → N, one commit each), suite 1568 → 1910, registry 19 → 26 / enabled 12 → 17, PRDs v2.5.0 → v2.7.0 (D59–D63).** Closeouts: `plans/SESSION-J-CLOSEOUT.md` … `plans/SESSION-N-CLOSEOUT.md` (N carries the final 9-carousel paid run's acceptance against plan §9 and the drift numbers). Design contract for N: `plans/SESSION-N-DESIGN.md`. New tool: `plans/tools/splice_builtin_twin.py` (prompt twins).

> Plan: **plans/xmasterplan-render-quality-and-language.md** (v3, verified 2026-08-20). Read its §0–§5 before
> any session; §5 is the corrected file:line table, §7 the per-session briefs, §11 the paste-ready prompts.
> Five sessions in strict order J → K → L → M → N. Each ends green + committed + `plans/SESSION-<X>-CLOSEOUT.md`.
> Paid spend: ONE 3-carousel checkpoint after L (~$4–5), ONE 9-carousel run after N (`--budget 15`).

| Session | Waves | Owns | Spend |
|---|---|---|---|
| J | 0J, 1, 2, 8 | `{{counter_rule}}` slot (FR-338/339), empty-zone rule (FR-340), phantom 4:5 band, icon-ledger rows, FR-313 counter metadata | $0 |
| K | 0K, 4, 5 | palette re-work + one-accent rule + hex validator (FR-347/349), type rule (FR-348), house spine (FR-350), 2K (FR-342) | $0 |
| L | 0L, 3 | seven carousel-derived styles (FR-341, 19→26, enabled 12→17), icon-ledger narrowing, concentration line (FR-355) | $0.30 preview + checkpoint |
| M | 0M, 6, 7 | best-of-3 cover + `cover_pick.py` (FR-351/352), `carousel_copy_mode: auto` (FR-353/354) | $0 |
| N | 0N, 9 | translate to config language (FR-343–346), final paid run, docs pass | $0.30 preview + final run |

Paste blocks (one per fresh session):

```
SESSION J
/xecutor Read plans/SESSION-I-CLOSEOUT.md, then plans/xmasterplan-render-quality-and-language.md
in full (§0–§5 first, then §7 "SESSION J"). Step 0: verify git status is clean and branch from main.
Execute Session J = Waves 0J, 1, 2, 8 exactly as written, using the corrected file:line table in §5.
Suite green after every wave; $0 barriers only. Finish with plans/SESSION-J-CLOSEOUT.md and a commit.
```
```
SESSION K
/xecutor Read plans/SESSION-J-CLOSEOUT.md, then plans/xmasterplan-render-quality-and-language.md
(§0–§5, §3, then §7 "SESSION K"). Execute Session K = Waves 0K, 4, 5 (palette re-work, one-accent rule,
hex-based validator, type rule, house spine, 2K). Bring all 19 styles into compliance in warning mode
before switching the errors on. Suite green; $0 barriers. Close with SESSION-K-CLOSEOUT.md + commit.
```
```
SESSION L
/xecutor Read plans/SESSION-K-CLOSEOUT.md, then plans/xmasterplan-render-quality-and-language.md
(§3 style specs, §5, §7 "SESSION L"). Author the seven new styles one at a time (validate + prompt-fit
after each), narrow icon-ledger, add the FR-355 concentration line, enabled 12->17. Barriers:
--preview-sources ($0), --preview-analysis (~$0.30), then the 3-carousel paid checkpoint
(--budget 5) in the background; run the §9 drift script on it and record the numbers.
Close with SESSION-L-CLOSEOUT.md + commit.
```
```
SESSION M
/xecutor Read plans/SESSION-L-CLOSEOUT.md, then plans/xmasterplan-render-quality-and-language.md
(§5, §7 "SESSION M"). Execute Waves 0M, 6, 7: cover best-of-3 (new hypesocials/cover_pick.py on the
style_match.py shape, fail-open) and carousel_copy_mode auto with a pure _rows_over_budget(). Budget lines
first, then code. Suite green; --preview-analysis shows the new estimate. Close with
SESSION-M-CLOSEOUT.md + commit.
```
```
SESSION N
/xecutor Read plans/SESSION-M-CLOSEOUT.md, then plans/xmasterplan-render-quality-and-language.md
(§5, §7 "SESSION N", §9). Ship 9a alone first (suite green), then 9b–9i. Translate runs BEFORE the auto
budget test. Then --preview-sources, --preview-analysis, and the final 9-carousel run (--budget 15) in the
background; accept against §9; run the drift script. Docs pass (NAVIGATION.md, prompts/README.md,
CLAUDE.md, EXECUTION-ORDER.md), SESSION-N-CLOSEOUT.md, commit, PR body.
```

---

## Standing rules for every session

Restate these verbatim in every subagent prompt — they have been load-bearing on this project:

- **Secrets (D30):** API keys only in `.env` or the environment. Never interpolated into a prompt, never
  sent to an LLM, never logged, never in git or a config file, never in an error message.
- **Money (rule 7):** no spend before the Confirm gate. Barrier commands that cost money must be labelled as
  such; `--preview-analysis` costs LLM spend, `--list-monitors` and `--preview-sources` do not.
- **Tests:** never write the repo's real `logs/trend_history.json` or `output/`. All filesystem work through
  `tmp_path`. No real API key — monkeypatched dummies only.
- **Line growth (rule 5, v2.0.0):** no ceiling. Measure with
  `find hypesocials -name "*.py" | xargs wc -l | tail -1` and report **with per-task attribution**, never a
  bare total. **Never** shorten a docstring, comment or error message to make a number look better.
- **PRD authority (§1):** `prds/` is the source of truth. Amend the PRD *before* the code, via D15.
- **Model policy (§9):** never pass a `model` parameter when spawning. The agent file's pin is authoritative.
- **Barrier discipline:** verify each wave before starting the next. A failed barrier is fixed **within**
  the current wave by routing back to its executor — never carried forward.
- **NAVIGATION.md** is updated at every wave barrier. Stale navigation is a bug.

---

## If a session runs short

Stop at a **wave boundary**, never mid-wave. Report: which waves are green, which barrier is next, and the
current `wc -l` with attribution. A half-finished wave with a red barrier is worse than an unstarted one,
because the next session cannot tell what was verified.

## If something contradicts a plan

Say so and stop. Both plans have already been wrong in specific, documented ways — the first draft had 14
claims refuted, and A23 contained a paragraph that instructed the exact opposite of the operator's decision.
**A plan is evidence, not authority.** Verify against the code and surface the conflict.
