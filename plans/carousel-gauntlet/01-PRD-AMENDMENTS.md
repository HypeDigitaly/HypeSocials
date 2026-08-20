# PRD Amendments — D15 batch for v2.2.0 (Session H) — Revision 2

Operator approval of the masterplan = explicit D15 consent for this batch. Apply in Wave 0, before any code.
**Editing rules for T0.1:** every edit below is identified by its ANCHOR SENTENCE (quoted), not by line number — line numbers shift as you edit. Work bottom-up within each file. After all edits, run the contradiction grep (masterplan Wave-0 barrier) and reconcile every hit.

New decisions: **D49** Gauntlet gate supersedes FR-105/D3/NFR-4 no-loop doctrine · **D50** verbatim-wins list mode (reflow, never a ceiling, never a drop) · **D51** spend runway + deck-viability gates · **D52** seeded style rotation · **D53** D48 Pillow scope extended to crop *validation* (variance floor, content-rect detection on crop failure) — still no compositing/resizing/thumbnails.
Version → **v2.2.0**. New FR block: FR-322–330 (next free per `00-overview.md`).

---

## A. `prds/10-pipeline.md`

1. **TL;DR (both paragraphs).** Anchors: "Optional spell-check by eye… ships either way" and "**There are no quality gates.** The engine makes it once and gives it to you." → Rewrite plainly: every rendered creative now passes a three-critic quality gate (the Gauntlet); failing frames are re-rendered up to 3 rounds; a deck that never passes is BLOCKED and not published. (MEMORY rule: TL;DR stays super-simple plain English.)
2. **FR-20.** Anchor: "There is **no** cross-slide consistency QA, no re-render loop, no 'regenerate slide 3 to match slide 1'. This is an accepted MVP trade-off (D3)." → Replace with pointer to FR-322–327/D49.
3. **§ exclusions.** Anchor: "No claim gate, humanness critic, disclosure logic, or cross-slide consistency inspection loop." → keep claim-gate/humanness/disclosure; delete the consistency-loop clause.
4. **NFR-4.** Anchor: "Every retry in the pipeline is capped at one attempt. No render ladders, no escalating quality loops" → Rewrite: FR-317/FR-105-style *blind* retries stay capped at one; the Gauntlet's bounded, critic-directed rounds (≤ `rounds_max`, budget- and runway-gated) are the sanctioned exception (D49).
5. **D3 decision text.** Anchor: "Zero gates, one optional vision check… renders once and ships." → Mark superseded by D49 with date.
6. **NFR-1.** Anchor: "≈3 minutes" → expected-case unchanged for pass-first-round decks + honest worst case (3 rounds, 60-min deadline); reference spec §5 figures.
7. **NFR-25.** Anchor: the "only imaging library use" sentence (already stale vs D48) → restate the full sanctioned Pillow surface: FR-93 downscale, D48 crops, D53 crop validation.
8. **FR-27.** Four-state vision vocabulary → superseded; gauntlet vocabulary is `pass | blocked | degraded | budget_stop | deadline_stop | skipped` (FR-328); `run.vision_check` key removed (aliased to `run.gauntlet.enabled` with migration warning).
9. **FR-95.** Anchor: fallback sentence about fully independent reference-free generation → new order: ONE replacement-anchor attempt, then chain 2–N off it; reference-free burst only if the replacement also fails (logged). Re-render references = anchor + nearest delivered neighbor. Anchor contingency priced at 2 units (FR-107 coupling).
10. **FR-18.** Anchor: "sole image references" → the nearest delivered neighbor slide is a sanctioned *chained artifact* reference class (D46-compatible: our own render, never source bytes).
11. **FR-100/101 (verbatim verifier).** Add the sanctioned repair boundary: byte-substring assertions are evaluated against the ADMITTED bytes — i.e., after the logged OCR confusable repair (uppercase-token-scoped) applied identically to the quoted pool, the prompt payload, and `panel_map.source_text`; `panel_map.source_text_original` keeps raw bytes. No other mutation is sanctioned.
12. **FR-304.** Add: (a) style budgets NEVER drop mapped text (D50) — drop reasons stay exactly `empty` / `contains_handle_or_url` / `over_sanity_ceiling(1500)`; (b) styles may declare `list_mode` = a REFLOW TRIGGER (`reflow_over_chars`, `max_rows`, `layout` prose, `overflow: reflow|two_column`) consumed only as layout guidance in the render prompt; (c) a truncation-suspect panel (trailing-ellipsis / mid-word cut heuristic) renders normally but carries `panel_map.truncation_suspect: true`, handed to the gauntlet `brief` critic as contract data.
13. **FR-312.** Layer 1 extends to author display name (`SourcePost.author_name`, adapter-populated) + deck-recovered display forms; caption layer gains sentence-level dangling-promo removal (comment-bait, community/program pitches, self-referential achievement claims), each logged; degrade-tier `_scrubbed` applies the same scrub with pool/product byte-consistency; strip success is verified on pixels by the `brief` critic, not assumed.
14. **FR-99 + FR-307 caption forms.** The niche descriptor never appears in caption text on ANY path. Per-path safe forms: offer paths → bound post's post-strip hook + neutral attribution; refused-post path → topic name only (the refused post may not be quoted); no-model tier → top post caption else topic name + slug hashtags. Offer paths with nothing usable fail pre-spend (`NO_SAFE_CAPTION`).
15. **FR-105.** Superseded by FR-322–330 (D49); machinery + `vision_check_question.md` retired. `expected_text` referent construction and the verbatim-no-trim retry rule are inherited by the gauntlet.
16. **FR-108.** Anchor: "default 25" (stale) → 60, sized: 600 s image timeout + FR-317 resubmit + up to 3 gauntlet rounds. Add the runway rule (D51): no `discretionary`/`projected` submit when `remaining_s < kind timeout + grace`; `precommitted` is exempt (FR-106b). A runway refusal is unbilled, cause `NO_RUNWAY`, and never consumes FR-317's resubmit.
17. **FR-202 + §10 outcome table.** Add BLOCKED rows: BLOCKED deck ⇒ artifacts kept (FR-74), counted as a loss, exit 1 partial-success; "all decks blocked" ⇒ exit 1 with explicit summary line. Amend the partial-carousel clauses: partial decks still ship when the loss cause is abandonment (halted/no_runway/credits/disk); losses from render defects after FR-317 trigger the D51 viability skip instead. Vision-check outcome row ("broken checker never blocks") → replaced by FR-322's unavailable-critic semantics.
18. **FR-106a/FR-107.** Estimate enumerates the gauntlet allowance (per-deck budget × decks + critic LLM projection at realistic completion tokens) as `allowance=True` lines: displayed, provisioned in worst-case, **never** part of `expected_usd`, never trims creatives.
19. **New FR-322–330** (full text below, §D).

## B. `prds/20-integrations.md`

- **FR-306.** Vision transcription passes the OCR repair boundary (repair + truncation flag, logged); mark rows gain `kind: tool|apparel|chrome|other`; only `kind=tool` marks are croppable (FR-315 coupling). Virlo-provided bytes still win §0.11; both channels receive the identical logged confusable repair at admission (see A.11).
- **FR-317.** Add: `NO_RUNWAY` refusals and gauntlet-round failures are not resubmittable events; gauntlet re-renders are fresh submissions on their own ledger rows — never a second poll window.
- New section: critic LLM calls (role `critic`, one multi-image call per critic per round, strict JSON, unavailable ⇒ one retry ⇒ critic dropped for the deck with `gauntlet_critic_unavailable` + `degraded_gate` tag; all critics unavailable ⇒ result `skipped`, ship-as-is tagged, never BLOCKED).

## C. `prds/30-configuration-and-run.md`, `40-outputs-and-logging.md`, `50-promptcraft.md`

- **30:** `run.run_deadline_min` default 60 (and note the shipped configs pin it); full `run.gauntlet.*` key table (spec §4) with bounds; `models.critic` role; `platforms.<name>.min_carousel_panels` (linkedin 3, others 2); `styles.rotation: seeded|fixed`; removal/aliasing of `run.vision_check`; CLI `--gauntlet/--no-gauntlet`.
- **40:** `meta.yaml.gauntlet` block + BLOCKED status (both `AssetStatus` and plan-entry level); `GAUNTLET_REPORT.yaml` + `BLOCKED.txt` contents; gallery BLOCKED badge; run-summary column; **a BLOCKED creative does not record trend-history use and does not satisfy `set_latest` on its own**; events vocabulary (`gauntlet_round`, `gauntlet_rerender`, `gauntlet_blocked`, `gauntlet_budget_stop`, `gauntlet_deadline_stop`, `gauntlet_critic_unavailable`, `gauntlet_fix_truncated`, `ocr_repaired`); FR-296 console lines.
- **50:** FR-315 gains requirement (e): crops cut only for sanctioned tool marks (`kind=tool`, allow-gated, never §0.12 flags/creator/chrome), full-frame fractions first, content-rect remap only on validation failure, validated non-degenerate (min edge, variance floor, collapsed-name dedupe) before upload; failure falls back per (d). New: the four gauntlet prompt artifacts (three critics + `gauntlet_fix.md`) — critic prompts carry per-critic defect enums; the fix template contains canned remedies keyed by (code, zone), the conflict-precedence block, and the fence-closing final line; **fix suffixes carry no critic free text and no source-derived strings** (FR-323 coupling).
- **Screen FRs (10/30 as owned):** verdict schema gains `language`, `audience_fit`; skip semantics; `{{audience_profile}}` placeholder sanctioned for `topic_filter_system.md` only (competitor-list precedent).

## D. New FR text (FR-322–330) — home `10-pipeline.md`, cross-referenced per registry

- **FR-322 — Three-critic gate.** After a deck's frames are delivered (and per standalone image / reel seed frame), up to three independent fresh-context critics — `brief`, `system`, `craft` — judge the RENDERED FRAMES against contract data only (per-frame expected lines, counters, signature, wordless mandates, required/forbidden mark lists, style DNA, layout zones, list_mode, sanctioned-illegibility note, platform). Critics never receive the assembled render prompt, the reference set, the builder's reasoning, or each other's verdicts within a round. (They DO receive style DNA/layout zones — the same words the prompt uses; this is stated honestly: it is the only possible style referent.) Verdict = strict JSON, per-critic defect-code enum, `zone` + `confidence` per defect, bounded output; `frame` indexes the attachment slot and is re-mapped via the shared image-loading positions. A critic that returns nothing parseable is retried once, then dropped for the deck (`degraded_gate`); all-critics-unavailable ⇒ `skipped` (ship tagged), never BLOCKED.
- **FR-323 — Fail list → targeted re-render.** A frame fails a round if any enabled critic reports a defect on it (empty-defect fails are logged `critic_empty_fail` and treated as pass). Only failing frames re-render. The fix suffix is composed EXCLUSIVELY from canned per-(code, zone) remedy sentences + the precedence block + the closing fence line; it is `_neutralize`d, competitor/creator-stripped, capped at 600 chars, carries the union of the frame's standing defect codes across rounds, and counts inside the prompt cap. Verbatim text is never trimmed by the loop. Re-render references: anchor + nearest delivered neighbor + patches.
- **FR-324 — Rounds & convergence.** Pass = all enabled critics pass every judged frame in the same round. `rounds_max` (deck, default 3), `rounds_max_image` (default 1). Round 0 (anchored decks) = single-frame brief+craft check of the anchor before slides 2–N submit (replaces the FR-95 anchor vision check; ≤1 anchor re-render, on the deck budget). From round 2, `brief` and `craft` judge only re-rendered frames; `system` always judges the full deck (cross-frame consistency).
- **FR-325 — Terminal policy, three tiers.** Defect tiers: **leakage** (`identity_leak`, `forbidden_mark`, `platform_chrome`, `invented_text`, `translated`) — standing on the final round ⇒ ALWAYS BLOCKED regardless of config; **contract** (other `brief` codes + all `system` codes) ⇒ per `fail_action` (`block` default | `degrade` ⇒ SUCCESS + degradation tag); **craft** (all `craft` codes) ⇒ never blocks — SUCCESS + `GAUNTLET_CRAFT` tag (knob `run.gauntlet.craft_blocks`, default false). BLOCKED: artifacts kept, `GAUNTLET_REPORT.yaml` + `BLOCKED.txt` written, excluded from trend-history use, gallery-badged, counted as loss, exit 1.
- **FR-326 — Spend & runway.** Gauntlet re-renders are `discretionary` (run cap + per-deck `deck_budget_usd`; either refusal ⇒ `budget_stop`, verdict stands). No gauntlet submit under the D51 runway rule. Worst-case gauntlet spend enumerated pre-Confirm as allowance lines (never gating, never trimming).
- **FR-327 — Configurability.** `enabled`, `rounds_max`, `rounds_max_image`, `deck_budget_usd`, `fail_action`, `craft_blocks`, per-critic `{enabled, model}`, `models.critic` (+max_tokens), all bounded and preflight-validated. `enabled: false` = no post-render gate.
- **FR-328 — Bookkeeping.** Per-round per-frame per-critic verdicts, costs, terminal outcome persist in `meta.yaml.gauntlet` + events on every terminal path.
- **FR-329 — Pair-integrity.** `brief` verifies row bindings on list/table frames against enumerated expected lines (label↔value stay paired; no invented rows; `pair_break` code).
- **FR-330 — Mark direction.** Contract carries REQUIRED (sanctioned tool marks; absence = defect — D-A semantics preserved) and FORBIDDEN (unsanctioned brand_marks, §0.12 flags, creator identity, competitor names; presence = defect). This ADDS the forbidden side the old check lacked; it does not remove the required side.

## E. `00-overview.md` rebuild checklist

- Registry: FR-322–330 rows with owners; FR-27/FR-105 marked superseded; amendment-log entry for v2.2.0 naming D49–D53 + this plan folder.
- Pipeline diagram: GAUNTLET stage (3 critics × ≤3 rounds) between render waves and packaging; BLOCKED branch.
- Version stamps + "Last updated" in every touched PRD.
- TL;DR of `00-overview.md` itself updated (plain-English gate description).

## F. `prds/PRD.html` — the visual PRD companion (T0.1 regenerates, T3.2 finalizes)

`PRD.html` is the operator-facing rendering of the PRD set and is published as a Claude artifact. It is **normatively part of this amendment batch** — a stale PRD.html is a bug (D15).

Required updates:
- Version chip / title / footer → **v2.2.0**.
- **Flow diagram:** insert the GAUNTLET stage (3 critics × ≤3 rounds, targeted re-render loop) between the render waves and packaging, plus the **BLOCKED** branch out to outputs. The diagram must **draw visually** — keep the natively-rendered markup; raw diagram source shipped as text is a defect, not a cosmetic issue.
- New FR rows FR-322–330; FR-27/FR-105 marked superseded.
- Decision log: D49–D53 with dates.
- TL;DR block rewritten in plain English: creatives now pass a three-critic quality gate; failing slides re-render up to 3 rounds; a deck that never passes is BLOCKED and not published.
- Config surface section: `run.gauntlet.*`, `models.critic`, `run_deadline_min: 60`, `platforms.*.min_carousel_panels`, `styles.rotation`, removal/aliasing of `run.vision_check`.
- Cost/latency envelope updated (expected vs worst case, per `02-GAUNTLET-SPEC.md §5`).

**Publish (conductor, Session 6, after T3.2's final pass):** republish to the CANONICAL artifact URL — do not create a new one — from a stripped copy of `PRD.html` (no doctype/head/body wrapper; `<title>` + `<style>` + body content, because the artifact runtime supplies its own skeleton). Favicon 📋, stable. After publishing, verify the page renders and the flow diagram draws.
