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

# SESSION 2 — the rest of Increment A

**Goal: steering, visibility, and the plagiarism guardrails the copy plan depends on.**
Fully offline except the final check.

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

# SESSION 3 — copy voice V1

**Goal: replace abstraction with transposition. This is where the robotic register actually gets fixed.**

```
/xecutor Execute plans/xmasterplan-copy-voice-transposition.md — waves V0 through V1d. STOP before V1e.
Increment A is complete. Both operator decisions are locked in section 2: the `voice` influence mode
is IN (D-1), and V1+V2 ship together (D-2).

  Wave V0   - D15 amendments (technical-writer, prds/**): FR-100 exemplar count 3-5 -> configurable;
              a new FR for the transposition contract and the audit fields; the voice-precedence rule
              in 50-promptcraft; max_tokens.copy 6000 in 30-configuration; the new `voice` influence
              mode.
  Wave V1a  - models.py (transposition_map/surface_carried/claim_swap, Exemplar, PLACEHOLDERS,
              2 DegradationTags), config.py (max_tokens.copy 6000, Transposition), configs/*.yaml,
              AND surface.py - the new pure stdlib-only measurement module, authored and unit-tested
              here because it is the V2 barrier.
              || Wave V1a' - the `voice` influence mode: briefs.py enum + validation, plan.py
              handling, ai-audit-cta/brief.yaml -> influence: voice.
              Two python-pro agents, one message. Path sets are disjoint.
  Wave V1b  - wrapper (9 slideshow + 8 video keys incl. panel_text_full) and adapter (_by_views real
              merge, _exemplars, _set fields, source_script). One python-pro.
  Wave V1c  - builders: _source_script with the "| " line protocol, _source_exemplars, the
              _trend_texts cut (literal rows leave), allowlist + truncation-order entries.
              One python-pro, prompts_engine.py only.
  Wave V1d  - the prompt template rebuild + prompts/README.md mapping table + the built-in fallback
              kept in sync. One prompt-engineer, prompts/** only.

Barriers:
  - V0: conductor re-reads every amended anchor against the file.
  - V1a: pytest -q; pytest -q tests/test_surface.py; assert json_schema_for(CopySet) still generates.
  - V1a': a `voice` brief consumes exactly ONE trend and its {{source_script}} renders non-empty;
    an `override` brief still consumes none.
  - V1b: total_views / median_views / engagement BYTE-IDENTICAL to pre-change (the merge must not
    move any FR-5 strength value); view-ranked order correct across a video-heavy + slideshow fixture.
  - V1c: panel-boundary truncation NEVER cuts mid-panel; every new slot resolves.
  - V1d: all slots resolve; transposition_map capped at 4 entries IN THE TEMPLATE; the
    source-owns-surface / brand-owns-lexicon rule stated explicitly.

One decision to surface, not settle by default (plan section 8.5): is `source_script` allowlisted for
the ANALYST as well? Without it the style brief loses input it has today. Ask before deciding.
```

---

# SESSION 4 — copy voice V2, wire-in, and the acceptance test

**Goal: verify the voice fix actually held, then prove it on real output.**

```
/xecutor Execute plans/xmasterplan-copy-voice-transposition.md — waves V2a through V1g.

  Wave V2a  - the audit tier in copywrite.py: CopyAudit, echo-before-drift order, EXACTLY ONE
              re-ask, CopyResult sets, _to_copyset.
              || Wave V2b - prompts_engine.py: per-role fence families (so >>> survives unmangled),
              target_chars wiring into _budget_line, the trim_words function-word fix, and the
              _BUILT_INS extraction into prompt_builtins.py.
              Two python-pro agents, one message.
  Wave V2c  - wire-in and operator surfaces. CONDUCTOR ONLY, never delegated: generate/__init__.py,
              outputs/gallery.py, previews.py, runner.py, budget.py.
  Wave V1f  - tests. test-automator, tests/** only.
  Wave V1g  - the acceptance test, below.

Barriers:
  - V2a: a stubbed-call test proves ONE re-ask and never two; echo outranks drift; the audit runs
    BEFORE _apply_budgets.
  - V2b: a panel containing >>> renders unmangled under [[[ fences AND is still mangled where a
    template uses chevrons; trim_words('Book the free AI audit at', 26) leaves no dangling
    function word.
  - V2c: tmp_path-only test that a drifted asset's meta.yaml carries style_drift and the gallery
    renders the badge. No real logs/ or output/, no API key in env.
  - V1f: full pytest -q green; find-based wc -l with per-task attribution.

THE ACCEPTANCE TEST (plan section 7) - this is the whole point, do not skip or soften it:
  1. Pull the top slideshow and top video (sorted, free) with panel_text_full.
  2. Render the REAL copywriter_system.md through PromptEngine with the real context.
  3. One real copy call per sample (~$0.005 total).
  4. Assert by hand: line count matches the source block; casing profile matches; contractions land
     in the source's slots; emoji present iff the source has them; NO shared opening word; every
     noun ours; the CTA ours; transposition_map and surface_carried specific and checkable.
  5. Count the measured tells against the 34-caption baseline:
       "Most ..." openers    18/34 today -> must be 0 unless the source did it
       negation frames       22/34       -> 0 unless the source did it
       em-dash appositives   21/34       -> 0 unless the source did it
       4-item parallel lists  8/34       -> 0 unless the source did it
       emoji                  0/34       -> present iff the source has them

If step 5 still shows the tells, SAY SO PLAINLY. V1 did not work and V2 cannot save it - the problem
would be deeper than the prompt and the next lever is a different copy model, not more instruction.
Do not declare success on a partial result.
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
