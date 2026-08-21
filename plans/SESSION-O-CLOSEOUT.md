# SESSION O — CLOSEOUT (subscription backends + Claude Code autopilot — v2.8.0, D64)

**Date:** 2026-08-21 · **Operator decision:** move every paid call onto the two subscriptions already owned (ChatGPT/Codex Max 20×, Claude Max 20×), no human in the loop, scheduled.
**Branch:** `session-o-codex-pivot` (parent: N's `b6eac4d` on `session-k-colour-type-spine`). Rollback tag **`pre-codex-pivot`** = `b6eac4d`. J → K → L → M → N → O are unmerged to `main` and merge together.
**Commits:** `320e4b1` config keys · `7139a63` brand configs · `548819f` image provider + autopilot scaffolding · `2f4d6b4` LLM door + runner wiring · `e477560` PRD D64 · `5c491b5` proxy lifecycle + pre-flight · `013f944` as_uri fix · `e2adc66` review-fix round · `7352baa` skill wait fix.
**Suite:** 1910 → **2020 passed, 0 failed** (+110: 19 llm codex, 32 render codex, 20 codex_proxy, 13+3 preflight, 6 budget, 3 vision_check, …).
**Growth:** production 39,614 → **41,550 (+1,936)** — `render/codex_images.py` +543 (new), `codex_proxy.py` +460 (new), `llm.py` +329, `preflight.py` +311, `budget.py` +96, `render/__init__.py` +57, `runner.py` +~50, `packager.py` +29, `vision_check.py` +14, `config.py` +30, `cli.py`/`previews.py` +~12. No docstring, comment or error message trimmed.
**Live spend this session:** every LLM call and every render **$0.00** (subscription); Virlo metering only. Probes, `--preview-analysis`, canaries `t91p` (crashed at first render, fixed), `1zqv` (29 renders OK, 9.5 min), `pm3y` (49 renders OK, 20 min), plus the final headless autopilot run (see below).

## What shipped

- **FR-356 codex LLM door** (`llm.py`): `LLMClient(backend=, base_url=)`; under `codex` every structured call rides `POST /v1/responses` (the proxy's `/chat/completions` refuses base64 images), strict `text.format` json_schema, `max_output_tokens`, `reasoning.effort` incl. `xhigh`; both bounded retries (FR-41 nudge on `input`, FR-127 widen on `max_output_tokens`) preserved; no Authorization header; usage has no cost; connect failures say "is `npx openai-oauth@latest` running?". Metered path byte-identical (diffed against `pre-codex-pivot`).
- **FR-357 proxy lifecycle + pre-flight** (`codex_proxy.py`, `preflight.py`): `ensure_proxy` probes `GET /v1/models`, starts `npx openai-oauth@latest --port N` under a kill-on-close job object when absent (stdin detached, output → `logs/codex_proxy.log`), loopback-only guard; runner awaits `preflight.ensure_backends` before `check()` and stops an owned proxy at `_cleanup`; pre-flight refuses a configured model id the proxy does not list, refuses reels under the codex provider, warns on non-1:1 plans, prints the fixed ~1254 px note and the `llm:`/`render:` provider lines; `OPENROUTER_API_KEY`/`KIE_API_KEY` required only by their own door.
- **FR-358 codex image provider** (`render/codex_images.py` behind the D34 seam): `/images/generations` (no refs) and `/images/edits` multipart `image[]` (refs, anchor first); always `model: gpt-image-2`; MODERATION only on 400/422; STUCK/TIMEOUT past `timeout_s`; `task_id = codex-<uuid>`; `cost_usd 0`; atomic write off the loop.
- **FR-359 `file://` carve-out:** `upload_file` → `file://` URI (no network); results under `<run>/.renders/` (pruned after packaging, kept on a crash); `packager._download`, `vision_check.load_images` read them. Nothing from `source/` but `marks/` reaches a payload — unchanged.
- **FR-360 $0 estimate:** LLM, image, video, job projections and the gauntlet allowance price `0.0` with key `codex`, origin "subscription (Codex OAuth) — $0 metered"; Confirm table prints `$0.00 — subscription`; the spend cap guards Virlo only.
- **FR-361 autopilot:** `.claude/skills/hypesocials-run/SKILL.md` (detached engine launch → chunked foreground waits → receipts → one `hs-deck-critic` per deck → `CLAUDE_REVIEW.md` + `logs/autopilot/AUTOPILOT_LOG.md`; never publishes/edits/deletes), agents `hs-operator`, `hs-deck-critic`, `autopilot.bat` (`claude -p "/hypesocials-run" --dangerously-skip-permissions`), `plans/tools/register_autopilot_task.ps1` — **registered: "HypeSocials Autopilot", daily 07:00, interactive token, RunLevel Limited.**
- **Configs:** the three brand configs pin `llm_backend: codex`, `render_provider: codex`, `analysis: gpt-5.6-terra`, `copy: gpt-5.6-luna`, `critic: gpt-5.6-sol`, `critic_reasoning_effort: xhigh`; engine defaults unchanged (`openrouter`/`kie`).
- **Docs:** PRDs v2.8.0 (00-overview D64 + FR-356–361 registry + log; 20-integrations §7a/§8f/§9/§11/§12; 30-configuration keys + pre-flight + autopilot; 40-outputs `.renders/`, `CLAUDE_REVIEW.md`, `logs/autopilot/`), NAVIGATION §3/§4/§5/§8/§9/§11/§13, CLAUDE.md Stack/Architecture/Glossary/Last updated.

## Measured facts (2026-08-21)

| Fact | Value |
|---|---|
| Proxy models | gpt-5.6-sol, -terra, -luna, gpt-5.5, gpt-5.4, gpt-5.4-mini, gpt-image-2 (operator rule: 5.6 family + gpt-image-2 only) |
| JSON chat | 3 s; vision + schema via `/responses` 3–5 s |
| Image generation | 15–20 s; edit with reference 26–34 s; **always 1254×1254 px** whatever `size`/`quality` (Kie 2K was 2048) |
| Second reference (logo patch) | honoured — Opus 5 lockup placed pixel-faithful (probe `two_ref_test.png`) |
| `codex exec -i … --output-schema` | works, 22 s — slower than the proxy; not used |
| Canary `1zqv` (2 decks) | 29 renders OK 9m32s · LLM $0 · 1 delivered, 1 blocked (real identity leak) |
| Run `pm3y` (3 decks) | 49 renders OK 20m11s · $0.00 · **0 delivered, 3 blocked** (missing_mark / invented_text / missing_text at xhigh) |
| Headless `claude -p` | ends its turn when a Monitor is armed → skill now waits with ≤ 9-min foreground Bash slices |

## Open for the operator (not defects of the door)

1. **Gauntlet strictness at `xhigh` on gpt-5.6-sol:** `pm3y` shipped 0 of 3 — all three standing defects are leakage-tier (`missing_mark` where no patch exists, e.g. "DevRush"; `invented_text`; `missing_text`), which `fail_action: degrade` cannot ship by design. Run `4344` (Sonnet, Kie) looked better partly because 5 of 9 decks were never judged (the 60 MB base64 problem — gone now, frames are local). Options: `critic_reasoning_effort: high`, relax FR-315's "marks required" when no patch was cropped, or accept fewer, cleaner decks. Decision is the operator's.
2. **Resolution:** 1254 px vs 2048 px — fine for platform display (≤ 1080), slightly softer if zoomed.
3. **Reels:** no subscription path renders video; `formats.reel` must stay 0 under codex (pre-flight refuses otherwise).
4. **`llm.py` is 873 lines** — §3a splitting candidate (`llm_codex.py` for the eight `_codex_*` helpers).
5. `_check_prices`' cap floor still derives from the metered image table (a tiny `spend_cap_usd` under codex could be refused as "below the minimum single-creative cost").

## Handoff

Next session reads this file first. The autopilot's own receipts live in `logs/autopilot/` (gitignored): `<stamp>.claude.log`, `<stamp>.console.log`, `AUTOPILOT_LOG.md`, `NEEDS_HUMAN_<run>.md`. Each reviewed run carries `output/<run>/CLAUDE_REVIEW.md`.
