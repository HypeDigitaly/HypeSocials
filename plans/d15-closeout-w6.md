# D15 Close-Out — Plan §6 Expected-Amendments Status (Wave 6, 2026-08-09)

Every amendment the plan predicted (§6), plus the W1-barrier additions, with its current
status against the PRD Amendment Log (00-overview, v1.6.2–v1.6.8). Compiled so the operator
can close the D15 trail at the MVP-DONE barrier. **CLOSED** = amendment applied to PRD text
and (where applicable) built. **OPEN** = still needs the D15 cycle (operator approval → PRD
edit → regeneration).

## Original §6 list

| # | Item | Status |
|---|---|---|
| 1 | FR-124 char-budget key name added to 30 §2 | **CLOSED** — conductor-approved at W1, key landed in `config.py` (T1.1) and 30 §2 |
| 2 | 40 §3 FR-76 dangling "FR-236" pointer → FR-231 | **OPEN (editorial, one word)** — `prds/40-outputs-and-logging.md:88` still ends "(see FR-236 below)" |
| 3 | FR-25 "plain semaphore" → priority permit gate | **CLOSED** — v1.6.7 restated FR-25 as the built 2-tier permit gate (named starvation test green since W4) |
| 4 | NFR-7 / NFR-110 stale G2 wording | **PARTIALLY CLOSED — STALE AGAIN (editorial)** — both were updated to the v1.6.3 numbers ("~6,000 / 6,500": `prds/10-pipeline.md:454`, `prds/20-integrations.md:126`) but were not carried through v1.6.4–v1.6.8; current is ~13,200 / 13,500. Same stale "~3,000-line budget" phrase inside D21/D34 prose (`prds/20-integrations.md:458,464`). Substance (each G2 bump) is already operator-approved — the remaining fix is numeric-editorial |
| 5 | FR-59 vs FR-70 tension ("no output" vs run folder at launch) | **OPEN (editorial)** — `prds/30-configuration-and-run.md:359` still reads "no output written"; built behavior (folder + log survive a declined confirm, $0 spend, verified at W5 decline test) matches the plan's proposed resolution, not the current sentence |
| 6 | 30 §2 image price prose (two tiers) vs FR-258 (three tiers) | **OPEN (editorial, one line)** — `prds/30-configuration-and-run.md:142` prose still names only `1k`/`2k`; the §2 config example (line 288) and built `config.py` carry `1k/2k/4k` per FR-258 |
| 7 | Lever #4: D21 amendment (wrapper → official Virlo MCP) | **NEVER FIRED — N/A** — in-repo wrapper shipped and stayed inside G2; D21 swap path remains documented |

## W1-barrier additions (from spikes/RESULTS.md + live builds)

| # | Item | Status |
|---|---|---|
| 8 | Reel pricing (OQ-2): FR-258 shape + success metric + `reel_reference_max_s` | **CLOSED** — v1.6.6 (Session 4 decision №1): `reel_second` redefined as worst-case-honest per-output-second scalar; metric restated ($1.58–$2.85 @720p/5s); CONTENT_AUDIT degrade path added. v1.6.7 (Session 4 decision №2, W4/M2 barrier round): `reel_reference_max_s` 10 → 20 with rescaled scalars (720p 0.950, 480p 0.425) |
| 9 | `video_job_timeout_s` 300 → ≥600 | **CLOSED** — v1.6.7: FR-259 default 600, prose aligned, code defaults updated (live measurements 302 s / 378 s) |
| 10 | FR-129 temperature ("stable, configured temperature" unsupported by both shipped models; 404s under FR-125 `require_parameters`) | **OPEN (needs operator approval)** — `prds/20-integrations.md:206` (and §prose at :189/:197) still mandates configured temperature; built code omits it per spikes/RESULTS.md §E. Proposed wording (queued since W1): "omit unless the configured model advertises it" |
| 11 | 20 §3 tool-return table corrections (digest vs monitor-analysis field ownership, `images[{image_url,position}]`, no `panel_count`, intelligence gating, pagination idioms) | **OPEN (editorial)** — code follows live reality (RESULTS.md §A is authoritative per plan §5 risk 6); the 20 §3 table text was never amended |
| 12 | 10-pipeline §10 CONTENT_AUDIT failure class + silent-retry + DegradationTag | **CLOSED** — v1.6.6; built in W4 (`generate/reel.py`, tag `audio_dropped_content_audit`) |
| 13 | Virlo digest config gate ($0.25/run metered call) | **CLOSED AS DECLINED** — declined v1.6.4, declined again v1.6.8 (call-site gate only; `--preview-sources` keeps the digest; "zero **model** spend" stays the FR-139 claim) |

## Also part of the trail (decided after the plan was written)

| Item | Status |
|---|---|
| G2 ceiling escalations (6,500 → 10,000 → 12,000 → 13,000 → 13,500) | **CLOSED** — one operator decision per barrier (v1.6.3/1.6.4/1.6.5/1.6.7/1.6.8); final measured count recorded at the W6 barrier |
| FR-94 brand-leak exclusion clauses (M1 "EMIR AI LAB" finding) | **CLOSED** — v1.6.5, template-only fix |
| Estimator fidelity (analysis per assigned trend + FR-127 retry allowance) | **CLOSED** — v1.6.5 decision, built in T4.3, confirmed at M2 |
| FR-202 incomplete-deck clause; FR-5 theme-confidence; `{{brand_accent}}`; `source_hook` | **CLOSED** — v1.6.7 / v1.6.4 |
| `--sources` CLI flag (FR-65 parity) | **CLOSED** — approved v1.6.8 (30 §5 row added), built in W6 |
| `logwriter._digest` one-line violation (40 §4) | **CLOSED** — recorded v1.6.8, fixed in W6, xfail flipped to green |
| `ai-audit-cta` stays `override` (FR-145 blend path built, untested-by-example) | **CLOSED AS DECIDED** — v1.6.8; no blend brief mandated |

## Audit-discovered PRD-text items (Wave 6 FR audit, 2026-08-09)

The T6.1 audit closed every code-side gap it could; these are the findings where the PRD text
is what's wrong (code is correct as built, or the choice is the operator's). All NEW to the
trail:

| Item | What the audit found | Proposed disposition |
|---|---|---|
| FR-23 (10-pipeline) | "safety toggle at the provider default" is stale — engine default is `true`, provider's own default is `false`; FR-166 (corrected) and 30 §2 already say so | Editorial: restate FR-23's bullet |
| FR-92 / FR-17 (10-pipeline) | "only `render_prompt` and `layout_zones` are ever injected" contradicts FR-189's mandated `style_dna` (six brief fields) — code follows FR-189 | Editorial: add a `style_dna` carve-out naming FR-189 |
| 10 §10 brief-missing row | says the rest of the plan "runs normally"; built behavior (and FR-172) is an interactive halt | Editorial: align the row to FR-172 |
| FR-139 (30-config) | names `unusable (no reference media)` verdict; built labelling is the more honest `eligible (text_only — last resort)` | Operator choice; recommend the label stays and the PRD example list moves |
| NFR-16 / FR-56 (30-config) | menu is 7 inputs *after* a pre-wizard action choice (8 total), and the config pick follows that choice | Editorial: restate both |
| FR-73 (40-outputs) | PRD schema says `format` / `kie_job_id(s)`; built meta writes `creative_format` / `kie_job_ids` | Editorial: align spelling to built names |
| FR-73 token fields | `estimated_tokens`/`actual_tokens` can only be filled by apportioning shared per-trend LLM calls | **Operator decision**: apportion-and-document, or delete the two fields |
| NFR-21 (40-outputs) | "copied only after … vision-check" — built order is store-then-check (check reads disk; retry overwrites in place); the real invariant (never media without meta) holds | Editorial: restate the clause |
| NFR-13 (20-integrations) | image resolution is not configurable per platform; needs a new `platforms.<n>.image_resolution` key in 30 §2 (budget.py already reads it defensively) | **Operator decision**: add the key (D15) or amend NFR-13 to the reel half only |
| FR-270 vs FR-241 (20-integrations) | "no literal model ids in engine code" vs FR-241's two-route profile requirement — the reference-free route has no config key by design; price-table family keys (`sonnet`/`luna`) are also literals | Editorial: carve out profile declarations + price-table family keys as sanctioned homes |
| 20 §8 reel seed-URL retry | a FOURTH paid resubmission not on 20 §8's sanctioned list — but 10-pipeline:422 and 20-integrations:370 explicitly MANDATE it ("explicitly not a whole-reel failure"): a genuine **PRD-vs-PRD contradiction**. The money defect is fixed in W6: the retry was `precommitted` (cap could not refuse a second ~$4.75 clip) and is now `discretionary` (FR-106c, cap-refusable; a declined retry keeps the honest terminal reason) | **Operator decision**: amend 20 §8 to name this third sanctioned resubmission (v1.6.6 precedent), or delete the retry (4-line change + one test) |
| FR-180 clause-(c) (50-promptcraft) | engine-built prompt lines (audio cue, @Image lines, reference roles, retry instruction, brand/brief lines) are clause-(c) mandatory text; now enumerated in prompts/README.md | Optionally add one naming sentence to 50 §2; closed-as-documentation otherwise |

## What remains open for the operator (the whole remaining D15 trail)

> **UPDATE 2026-08-10 (PRD v1.7.0):** the editorial batch below has been **APPLIED**, and the
> reel-retry decision was taken (**delete** — the resubmission is gone, FR-24 and both failure
> rows amended). Two acceptance findings were also closed by code: the reel job timeout
> (600 → 1800 s, deadline 45 min on reel-capable configs) and the LLM retry allowance
> (now `base + 2 × widened` per call). **Five items remain open**, listed at the very bottom.

**One editorial batch (pre-approved in substance, could ride a single v1.6.9 entry) — APPLIED v1.7.0:**
№2 (FR-76 pointer) · №4 (G2 numbers in NFR-7/NFR-110/D21/D34 prose) · №5 (FR-59 wording) ·
№6 (30 §2 two-tier prose) · plus the audit's editorial rows above (FR-23, FR-92/17 carve-out,
10 §10 row, NFR-16/FR-56, FR-73 spellings, NFR-21, FR-270 carve-out, FR-180 sentence).

**Still needing an explicit operator yes — FIVE items (v1.7.0 status):**
№10 (FR-129 temperature) · №11 (20 §3 tool-return table) · FR-139 verdict labelling ·
FR-73 token fields (apportion vs delete) · NFR-13 image-resolution key.
*(The 20 §8 reel retry left this list on 2026-08-10 — the operator chose deletion.)*

**One new item raised by that deletion (not urgent, not a bug):** the PRD's original promise
was that a rejected seed-frame URL still ships a clip with `in_model` text. That is only
achievable with a **pre-submission URL reachability check**, which was never built. Today the
case is an honest logged failure. Build the pre-check if delivered-clip-always matters more
than the ~20 lines it costs.

Per v1.6.3 precedent, the deferred full PRD.html/artifact republish comes due with whichever
content-level amendment closes these.
