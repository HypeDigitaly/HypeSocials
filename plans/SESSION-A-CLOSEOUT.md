# SESSION A CLOSEOUT — Wave 0: PRD amendments (2026-08-12)

**Status: COMPLETE and conductor-verified. No code was touched. Next session: SESSION B (Wave 1).**

## What shipped

- All 7 PRDs amended to **v2.0.0** (2026-08-12) for the topic-first pivot:
  - `prds\10-pipeline.md` — TL;DR rewritten; FR-3/16/22/92/142 withdrawn; FR-5/6/7/8/13/14/17/18/20/23/24/90/94/95/96/99/100/101/102/107/109/141/144/145/146/147/202 re-based; NEW **FR-290/FR-291/FR-294** (registry, rotation incl. pinned pseudocode, competitor filter); §10 failure table rewritten (analysis/text_only/motion/pair rows out; filter_degraded + registry-exit-2 rows in); D2 re-stated, D23 withdrawn, D28 restatement re-based.
  - `prds\20-integrations.md` — §3 topic-extraction rewrite + NEW **FR-293** (SourcePost, per-topic strength, history_key migration); FR-32 media clause + FR-33/FR-247 + FR-160–163 + NFR-160 + FR-128 withdrawn; FR-129 re-worded; FR-168/169 removed; §8a/§8b motion chain deleted; §8c premise rewritten; §10/§11 tables re-based; FR-200/244 = run-scoped upload memo.
  - `prds\30-configuration-and-run.md` — NEW **FR-292** (full branding schema) / **FR-295** (registry exit-2) / **FR-299** (verbosity+heartbeats) / **FR-300** (menu 7→5 inputs); FR-133/170/173/259 amended (dead keys out); FR-134 withdrawn; FR-139/140 preview split; reel price = no-reference scalar; `--mode` dead, `--verbose` added; own failure-table analysis row removed.
  - `prds\40-outputs-and-logging.md` — NEW **FR-296/FR-297/FR-298** (stage narration; topics table/post roster/provenance; forensic events + `copy_source_refs`); FR-73 meta.yaml field swap; FR-77/80/81 re-based (`reference_choice` withdrawn, `kie_job_submitted.reference_sources` examples rewritten — W5 payload check reads these); FR-150 → style adherence; FR-153 history migration + post URLs; FR-155 funnel-once-at-DONE.
  - `prds\50-promptcraft.md` — §1 premise rewritten (registry is layer (a)); FR-181–184/189/191/194–197 re-based; FR-199 withdrawn; §5 rewritten (reference-selection mandate, topic-filter + branding playbooks); reel example de-@Video1'd.
  - `prds\00-overview.md` — TL;DR/Goals/Non-Goals/Walkthrough rewritten; **new mermaid diagram** per the pinned spec (SPLIT→FILT→SEL→ASSIGN→COPY, two waves, STY/BR inputs, no INSP/BRIEF/RANK); **D41–D45 added**; FR-Range Registry row (FR-296/297/298 → 40-outputs, FR-299/300 → 30-config) + "Next fresh block: FR-301+"; v2.0.0 amendment-log entry.
  - `prds\PRD.html` — rebuilt current (backlog cleared), **published as artifact**: https://claude.ai/code/artifact/b4c59a8d-f7ed-456a-a1b0-31297f48203e (diagram verified rendering; publish from a stripped copy — no doctype/head/body; favicon 📋; same URL on republish).
- `plans\EXECUTION-ORDER.md` — sessions 3–4 cancelled; **SESSION A–E blocks added** (B=Wave 1, C=Wave 2, D=Wave 3+3.5, E=Wave 4+5).

## Governing documents for Session B

1. **`plans\xmasterplan-topic-first-pivot.md` (v2.3)** — THE plan. §1.8 = contracts doc spec (items 1–16); §3 Wave 1 table; §1.10 + D45 = console observability mandate.
2. **`plans\topic-first-pivot-console-ux-v1.md`** — binding console mockups (W3 consumes them; W1 doesn't).
3. **`plans\topic-first-pivot-meta-styles-v1.yaml` + `plans\topic-first-pivot-branding-v1.yaml`** — fill-in inputs for T2.5/T3.4 (W2/W3).
4. PRDs are amended FIRST and are current — code that conflicts with them is a bug.

## Session B (Wave 1) — exact scope

**Conductor FIRST, before any dispatch:** write `plans\topic-first-pivot-contracts.md` per plan §1.8 items 1–16 **from the actual code** (real `build_context` signature at `prompts_engine.py:345-369`, real `PLACEHOLDERS`/`PROFILE_TEMPLATES` in `models.py`, `Env` in `generate\__init__.py`, etc.). Every W1/W2 dispatch prompt quotes its relevant section.

Then dispatch (flat wave, no orchestrating parent — §9a):
- **T1.1** (python-pro): `models.py` + `config.py` ADDITIVE ONLY (MetaStyle, SourcePost, PlanEntry fields, LayoutZone.role, 3 new tags, CopySelection, BrandingConfig, StylesConfig, virlo_topics_per_monitor). NO PLACEHOLDERS/PROFILE_TEMPLATES additions (those are W2 conductor work — B1/B2). Old keys stay silently (no deprecation plumbing).
- **T1.2** (python-pro, parallel): NEW `hypesocials\styles.py` + `hypesocials\topic_filter.py` per §1.3/§1.5 + pinned API. `topic_filter.screen()`'s prompt-render path ships written-to-contract but stubbed (two W1 guards block it: PLACEHOLDERS membership + missing allowlist key); first e2e test is T2.7's.
- **T1.3** (test-automator, parallel): `tests\test_styles.py` + `tests\test_topic_filter.py` against the contracts doc **+ DELETE `tests\test_reference_rotation.py`** (BLOCKER fix: its whole-tree `% len(` policy scan goes red the moment styles.py lands).

**Barrier:**
```
.venv\Scripts\python.exe -m pytest -q                       # FULL suite green
find hypesocials -name "*.py" | xargs wc -l | tail -1        # NEVER the globstar variant
```
Growth reported with per-task attribution vs baseline **16,356** production / 10,899 test lines.

## Warnings from this session (conductor experience)

- **Do NOT trust subagent self-verification.** All three Wave-0 writers reported "grep clean" while my independent greps found ~25 real leftovers. Re-grep every deliverable yourself at the barrier.
- Agents may stall mid-file asking "continue?" — resume them with explicit "finish everything now" instructions; they are pre-approved.
- venv Python only: `.venv\Scripts\python.exe` (bare `python` has no `mcp` and fakes a broken tree).
- Spend is pre-approved for spikes + live barriers, but Wave 1 needs $0.

## Verification evidence (this session)

- Dangling-concept greps run per file after each agent; leftovers fixed by conductor directly (FR-144/145, worked example, FR-259, D28 ×2, adapter-interface line, FR-128 note, kie examples, FR-139/140, reel price block, @Video1 example, PRD.html FR-block table + line chip).
- Artifact fetched post-publish; SVG diagram confirmed present and rendering; no raw mermaid text.
