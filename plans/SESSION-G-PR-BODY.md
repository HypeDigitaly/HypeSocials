# PR: Topic-first pivot + D46 slideshow fidelity (SESSIONS B-G)

Base: `main` · Head: `topic-first-pivot`
(Stored here because `gh` was unauthenticated at session end; create with
`gh pr create --base main --head topic-first-pivot --title "Topic-first pivot + D46 slideshow fidelity (SESSIONS B-G)" --body-file plans/SESSION-G-PR-BODY.md`
after `gh auth login`, then delete this file.)

## Summary

The full topic-first pivot (D41-D45) plus the D46 slideshow-fidelity overhaul (v2.1.0 -> v2.1.1), implemented across SESSIONS B-G and live-verified against real Virlo data and one paid render run.

### D46 slideshow fidelity (SESSIONS F+G, this week)
- **Fetch this week, not all time**: newest collection rounds, 30-day age cap, views ranked within the window; triple gate (`dropped_stale` / `dropped_unenriched` / `dropped_used`) with funnel lines
- **Quote the on-image words**: panel texts first-class, Virlo's AI `description` banned at grammar level, caption substance rule, deterministic position-preserving panel->slide mapping bound to ONE fresh post per deck
- **Styles are words, not pictures**: style reference-image channel excised; `styles.yaml` re-authored as text-only visual DNA with raised caps; render jobs attach brief photos + chained anchors only
- **Post-ID no-repeat**: enforced at fetch AND pick; `trend_history_days >= max_post_age_days` invariant refused at pre-flight (CLI overrides included); live-proven (re-preview shows all quoted posts under `dropped_used`)
- **Slide intelligence** (FR-306): post-Confirm Sonnet-5 pass per bound deck; source slides downloaded once into `source/<post_id>/` (analysis + gallery only, hard boundary against render payloads)
- **Provenance gallery** (FR-309): three-part carousel cards - source-post header, original slide strip with extracted text + visual briefs, our slides paired index-by-index

### Verification
- Suite: **899 passed / 0 failed / 0 skipped**
- Live ladder (plan §5): $0 previews green; ONE paid all-carousels run ($1.27 under a $4 cap); byte-verify 6/6 decks (panel_map == source.yaml, position-preserving); 30/30 jobs text-to-image with zero Virlo hosts in payloads; no-repeat proof passed
- **FR-307 measured supply figure**: 9 usable posts/monitor/30d (7 deck-bindable) - recorded in the PRD with honest cadence arithmetic
- Known findings for the operator (D15 candidates in `plans/SESSION-G-CLOSEOUT.md`): vision-transcription length vs slide caps (on-image hit-rate 4/6 vs >=5/6 target), Kie stuck-job rate, supply arithmetic

PRDs amended first throughout (D15 cycle, v2.1.1); artifact republished and verified.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
