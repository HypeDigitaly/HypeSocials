# PR body — SESSION I (v2.4.0, D56/D57)

**Branch:** `session-i-style-intelligence` → `main` · **Commit:** `9c36325`
**To open once `gh auth login` is done:**
`gh pr create --title "v2.4.0/D56-D57 SESSION I: style intelligence (registry 9→19, LLM-matched assignment, teal spine)" --body-file plans/SESSION-I-PR-BODY.md`

---

## What this is

Waves 1–4 of `plans/xmasterplan-style-intelligence.md`. Style assignment stops being content-blind rotation over a file-ordered pool and becomes a fit decision, and the registry grows the archetypes a census of real bound posts said were missing.

**Suite 1481 → 1567, zero failures** (green in fixed and randomized order). Production +1,631, tests +1,837. Live spend this session: **$0.27**.

## The three problems it closes

1. **Assignment was rotation, not fit.** Recent runs bound X-screenshot posts, lifestyle photos and dense infographics onto dark/graphic styles that suited none of them.
2. **The registry didn't cover what trends.** A census of 21 distinct bound source posts found ~48% are listicle/infographic decks — an archetype with zero coverage.
3. **No unifying colour.** Nine styles carried unrelated hand-authored palettes.

## What shipped

- **Registry 9 → 19.** `build-log-mono` + four census-driven archetype styles (`icon-ledger-carousel`, `circuit-atlas-dark`, `social-quote-card`, `terminal-mockup-deck`) + five `-teal` variants. Originals are **byte-untouched** — D57 duplicates rather than edits, which is exactly how standing decision D-G ("colour is curated by choosing styles, never by editing one") stays intact. All 19 author a `match_profile`.
- **Matched assignment (FR-334–337).** New leaf `hypesocials/style_match.py`: ONE batched fail-open `analysis` call at ASSIGN, returning a TOTAL mapping keyed by **asset_id, never ordinal**, that never raises. Ballots import `usable_styles` × `fmt_affine` rather than re-deriving them. `high`/`medium` accept; `low`, out-of-pool and missing rows keep the FR-291 baseline and preserve `wanted_archetype` for a console gap report; a whole-call failure puts every entry on baseline with `style_match_degraded`.
- **`assignment: rotation` restores pre-D56 behaviour byte-exactly** — proven by loading the pre-change `runner.py` from `HEAD` as a second module and diffing console output, picks and branding against it.
- **Teal spine.** 12-key `styles.enabled` + `assignment: matched` in the three brand configs; `default.yaml` documents the knob and keeps the engine default `rotation`.

## Live evidence

`--preview-analysis` ($0.27) matched **3/3 creatives at `high` fit**, with both winning styles being D56 archetypes authored in this session:

```
style_match: 3 of 3 creative(s) matched  matched=3 baseline=0 degraded=0 candidates=19  wanted=[]
    01 carousel  AI Agents for Business…  circuit-atlas-dark   matched/high
    02 carousel  AI Video Generation…     icon-ledger-carous…  matched/high
    03 carousel  Claude Opus & Sonnet…    circuit-atlas-dark   matched/high
```

An agent/systems explainer went to the dark tech-diagram style and a seven-panel lead-gen tutorial to the listicle icon-card style — the census gap being closed by content fit.

## Nine defects outside the plan, found and fixed

Two were operator-facing console truncations that hid the very instruction the line existed to give:

- **`menu.py`** — a two-digit style count pushed the picker's facts line from exactly 70 to 71, and truncation ate the `[4]` naming the cure, leaving `NOT RUNNABLE - pick…`.
- **`runner._assign_visuals`** — the degraded cause and "every creative kept a style" were joined and fitted together, so any real cause ate the reassurance whole.
- **Launch block** reported the style pool from `brand_ok` alone, ignoring `styles.enabled`: `18 usable` where the shipped config selects 12. Now pinned as an equality against `usable_styles(...)`, never a literal.
- **`social-quote-card` blew the Kie prompt wall** and the last-resort trim removed a *safety rule*. Caused by the conductor's own D-A carve-out edit (+188 chars) on a style that already had zero headroom; re-authored to the registry's DNA convergence with the carve-out kept and 102 chars of margin.
- **`social-quote-card` was the only style of 19 without the D-A TOOL MARKS carve-out**, so its blanket logo ban reached tool marks a render may legitimately show.
- **`AGENTS.md` was a broken hardlink**, 3.5 KB stale against CLAUDE.md — agents were reading outdated rules from the documented single source of truth.
- **`run_deadline_min` is 60, not 45.** CLAUDE.md was stale and the conductor propagated the error into the PRD artifact before catching it. Fixed in three places.
- **FR-140 under-counted `--preview-analysis` spend** as "filter + copy" (wrong since v2.1.0).
- **`ugc-tabletop-statement-teal` is `slides_only` too**, so effective carousel rotation under the 12-key pool is 10, not 11.

## ⚠️ Not done — needs the operator

**One paid run (2–3 carousels, low cap).** Deliberately not automated because its acceptance is visual: the Confirm-gate `style_match_call` line, the teal spine across styles, `build-log-mono`'s chrome grid, and **gauntlet green on `social-quote-card` and `terminal-mockup-deck`** — the two UI-grammar styles closest to other styles' no-platform-marks exclusions, and the riskiest authoring here.

Four operator decisions are also owed; `plans/SESSION-I-CLOSEOUT.md` §4/§6 lists them, the largest being that `letterpress-print-carousel-teal` carries teal on its cover slide only.
