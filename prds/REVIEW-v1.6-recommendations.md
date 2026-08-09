# v1.6 Review Report — Decision Record (closed 2026-08-09, v1.6.1)

## TL;DR — Plain English

On 2026-08-09 the whole PRD went through a four-way expert review. About ninety clear-cut fixes were applied as v1.6. The remaining recommendations were each a real product choice, so the operator was asked eleven direct questions — and answered all of them the same day. This file is now the **decision record**: what was cut, what was kept, and why, so none of it gets re-argued from memory. The applied cuts landed as amendment v1.6.1 (~590 estimated lines saved); the size goal is restated as **target ~3,000 lines, hard ceiling 4,500**.

---

## APPLIED (v1.6.1)

| # | Decision | Outcome |
|---|---|---|
| S-2 | Collapse meta.yaml's ~10 degradation booleans into one `degradations: []` tag list | **Applied** — 40-outputs FR-73; gallery badges render in one loop (~120 LOC) |
| S-3 | Delete the local crop/pad path | **Applied** — 10-pipeline FR-98 rewritten, NFR-25 down to one imaging use, D33 extended; Kie's ratio menu covers every default ratio natively (~80 LOC) |
| S-4 | Drop the declared media-richness contract + text-grounded mode | **Applied** — FR-148/149 and FR-168/169 tombstoned, D28 withdrawn; a future text-only adapter reuses the item-level `text_only` path (~90 LOC) |
| S-6 | One config shape — niches are ordinary configs with `briefs_dir`, `prompts_dir`, `sources.inspiration_folders` | **Applied** — D27 simplified; `--niche`, the dual picker, and pack validation removed; `niches/<name>/` stays as a folder convention the paths point into (~110 LOC) |
| S-8 | Budget trim = one rule via plan ordering (briefs emitted first; carousel and A/B pair are single plan entries) | **Applied** — 10-pipeline FR-106 (~40 LOC) |
| S-9 | One spend table instead of four | **Applied** — 40-outputs FR-84; events.jsonl carries dashboard-grade detail (~60 LOC) |
| S-10 | Delete the permanently-inert `image_quality_tier` key | **Applied** — OQ-7 closed with no tiers on Kie; FR-187 stays advisory for future profiles |
| S-11 | Phase-2 trims: drop `--assets`, `--force`, and FR-215's auto-reconciliation | **Applied** — markers are the filter; delete `PUBLISHED.marker` to re-publish; lingering attempt-markers are reported for a manual glance. Revisit reconciliation if `auto_publish: true` is ever enabled (~180 LOC) |

## KEPT (explicit operator choice — do not re-litigate without new facts)

| # | Decision | Outcome |
|---|---|---|
| S-1 | Cut `both` A/B mode | **Kept.** The operator wants one-run side-by-side pairs with shared copy. Its cross-cutting invariants (pair atomicity, one-reuse-per-pair, `pair_id` gallery pairing) stay load-bearing. |
| S-7 | Drop the provider seam + profile registry | **Kept.** The seam stays as cheap insurance for a future second provider (OQ-18 tracks Higgsfield). |
| S-5 | Merge/delete the preview modes | **Kept — both.** `--preview-sources` and `--preview-analysis` remain standalone actions alongside the new post-Collect plan restatement. |
| F-4 | Auto-enable `vision_check` on Czech runs | **Declined.** The startup hint stays; the default stays off everywhere. |
| F-1 | Loosen trend-reuse defaults | **Declined.** `max_trend_reuses_per_run: 2` and `trend_history_days: 7` stand; the required-vs-available startup line is the watch instrument. |
| G2 | Size goal | **Target ~3,000 / hard ceiling 4,500** (00-overview G2). Remaining cut candidates above are the lever if the build trends past the ceiling. |
| F-5 | Where the A/B verdict lives | One-line comment next to `generation_mode` in the config (00-overview Success Metrics). |

## Considered and NOT recommended (unchanged from v1.6)

- Switching Virlo to its official 49-tool MCP server (wrapper's 5-tool surface + churn insulation wins; official server stays the swap path).
- Adding Higgsfield now in any capacity (OAuth-only, Seedance 2.5 waitlisted, ~5–6× render cost, no upload API — 20-integrations §12a).
- Promoting `reference_audio_urls` / `return_last_frame` (music-video and multi-shot capabilities) into MVP — now technically possible on Kie, still rightly parked (D35): new creative surface, not missing plumbing.
