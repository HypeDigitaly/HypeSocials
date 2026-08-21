# CLAUDE.md — HypeSocials Project Conductor

## How To Talk To The Operator

This overrides every other tone or style rule, here and anywhere else.

I hereby forbid you from 90% speaking to me in jargon. Try to avoid words like verbatim, interim, and all of this non sensical language.

Speak in ADHD friendly style. Assume i'm an idiot. Break lines, one line, one sentence, Try to cut it mostly. More than one sentence when you need to explain fully. Use emojis when starting a new line, or for important points.
*Use beginner–intermediate English.* Speak like you talk to someone who is new at English. Simple words, simple sentences. Not childish, just easy. (Or the language the user is speaking in)
When mentioning lots of things, or comparing. Put it in an easy to read table.

When you decide to speak in jargon. Etc. some word, or codename, shortcut for something. Explain it to me simply, in natural language. You can still use technicality. Eg. i know what a database is, no need to explain these terms. There is a fine threshold between words i can understand and jargon which i cant comprehend.

You shouldn't assume that I know everything you talk about - that is shortcuts, special words..
If you decide to mention jargon, always explain in brackets what it is: jargonWord(Short plain natural language explanation) - only say jargon when its needed to say that without saying something wrong.

**Note:** this rule is about how you TALK. It does not change what the code, the PRDs or the config comments say — those keep their exact technical wording.

---

## What This Is

Project configuration and agent coordination guide for HypeSocials MVP (Phase 1). Single-operator Windows CLI tool that generates viral social creatives (images, carousels, reels) from text-only Virlo topic trends: an LLM screens topics and selects copy verbatim from the topic's source posts, a local meta-style registry supplies the visual language, and Kie.ai renders. ~3 min (images/carousels only) or ~8–10 min (with reels); <$1 per post.

---

## Stack

**Core runtime:** Python 3.12+, asyncio with `ProactorEventLoop` (mandatory on Windows)

**Async I/O:** `httpx`, stdlib `asyncio`, stdlib `signal.signal` + `call_soon_threadsafe` for SIGINT (never `add_signal_handler` — unavailable on Windows)

**Config & serialization:** `pyyaml`, `python-dotenv`

**MCP:** `mcp` (official Python SDK), both stdio servers (Virlo wrapper in-repo, Notion via package) and HTTP transports

**System-level:** `pywin32` (Windows job objects for subprocess tree reaping, `win32job` module), `argparse` (CLI flags only, not menu)

**External services:** OpenRouter REST (LLM, metered default), Kie.ai REST (renders, metered default), Codex HTTP (LLM + renders, subscription optional; D64), Virlo REST (via MCP wrapper), Notion MCP

**Media libraries: Pillow for THREE sanctioned uses (D48, D65).** The topic-first pivot (D41–D45, 2026-08-12) removed Pillow and yt-dlp; D48 (2026-08-13) reinstated Pillow with a single sanctioned use — cropping tool-logo patches out of downloaded source slides for FR-315 pixel references. D65 (2026-08-21) added two more, both LOCAL and post-render, neither ever uploading anything: the alpha-halo guard (`outputs/alpha_halo.py` — detect a ragged semi-transparent frame edge, resubmit once, then flatten) and the exact-pixel screenshot paste (`outputs/screenshot_paste.py`, FR-370 — crop a real interface out of a source slide and composite it into a plate the render reserved). No other image processing, no resizing pipelines, and yt-dlp stays gone (reels use no video references). The upload ban is unchanged: `generate/refs.py:_sanctioned` still refuses every path under `source/` except `marks/`.

**No database.** State is files: config YAML, trend_history.json, run logs, asset metadata (meta.yaml per creative).

---

## Architecture

**Feature-first, not layer-first.** Module tree per plan §1: `hypesocials/` domain folders (sources, render, generate, outputs, etc.) each own their routes/service/models/schemas together. Module public API via `__init__.py`; deep modules hide complexity from callers.

**All I/O async.** No blocking I/O on the event loop. HTTP via `httpx`, subprocesses via `asyncio.create_subprocess_exec`, MCP tool calls via MCP SDK's async methods.

**Windows event loop:** `asyncio.ProactorEventLoop()` (required for subprocess support on Windows; default on Windows in Python 3.8+ but stated explicitly in code). SIGINT handling: `signal.signal(signal.SIGINT, handler)` + `loop.call_soon_threadsafe()` to enqueue the stop — never `loop.add_signal_handler()` (unavailable on Windows).

**Process reaping:** Subprocess trees (especially MCP stdio servers) are fully terminated on every exit path (success, failure, timeout, abort) via Windows job objects (`win32job.CreateJobObject` + `win32job.SetInformationJobObject` with kill-on-close). Fallback: `taskkill /T` sweep on orderly exits only.

**Junctions for directory symlinks:** `mklink /J` subprocess call (never `os.symlink`, which requires admin/DevMode). Used for `output/latest/` pointer.

**MCP clients:** One shared async MCP client (`mcp_client.py`) with per-server launch/env/timeout config, bounded session pools (Virlo pool default 3 per PRD FR-246/FR-259), per-server environment dicts (only the keys each server needs), and Windows-safe `.cmd`/`.exe` shim resolution.

**Reference images (D46/F3):** The style picture channel is EXCISED — a meta-style is text-only DNA and `styles.yaml` declares no images. The only inbound render references are a campaign brief's own product photos (uploaded to Kie via the file-upload API, host `kieai.redpandaai.co`, ~24 h retention; an upload memo guarantees each distinct file uploads once per run, URLs never persisted across runs) and the chained artifacts the pipeline itself rendered (carousel anchor, reel seed frame). Virlo media IS downloaded post-Confirm — but for ANALYSIS AND DISPLAY ONLY (D41 carve-out as amended by D46): slide intelligence reads the bytes and the gallery shows them from `output/<run>/source/<post_id>/`; nothing from `source/` may reach `render.upload_file` or any render payload — with ONE narrow D48 exception: tool-logo patches cropped from source slides (FR-315, `source/<post_id>/marks/`) may upload as render references; full slides and every other source byte remain forbidden, and no Virlo CDN host may ever appear in a render payload.

**Style registry has NO fallback (FR-295):** a missing, unparseable, or invalid `styles.yaml` — including a registry left with zero styles usable under the active brand/format — is a pre-flight refusal: exit 2, $0 spent. There is no built-in default style set to fall back to.

**Render provider seam (D34):** One small interface (submit → poll → result URLs → upload) with Kie.ai built-in. Each render model (gpt-image-2, seedance-2-5) carries a profile (param mapping, reference limits, template set). Unknown profile fails at pre-flight.

**Two-wave generation:** Carousel anchor + reel seed frames submitted wave-1 (checked + referenced by wave-2); remaining slides/animation submitted wave-2 once wave-1 completes (or pre-committed if budget allows). Priority permit gate: wave-2 acquisitions before queued wave-1 (prevents FIFO starvation).

**Subscription backends (D64, FR-356–361):** Two billing modes via config keys: (1) **Metered** (default) — `models.llm_backend: openrouter` + `models.render_provider: kie`, pre-flight calculates cost, Confirm gate shows estimate, API keys in `.env`; (2) **Subscription** (opt-in) — `models.llm_backend: codex` + `models.render_provider: codex`, pre-flight probes local Codex proxy (`npx openai-oauth` + ~/.codex/auth.json), zero cost to operator, runs identical creatives, outputs to local `file://` paths. Model allowlist (gpt-5.6-sol/terra/luna, gpt-image-2 latest only); reel generation refused under subscription (exit 2, $0). Reasoning effort (`low|mid|high|xhigh`) — xhigh available codex-only. Rollback path: `git tag pre-codex-pivot` (b6eac4d); revert config to metered.

---

## Non-Negotiable Rules

**1. Async-only I/O.** No blocking calls on the event loop. All HTTP, subprocess, and MCP I/O must be non-blocking.

**2. ProactorEventLoop on Windows.** Explicitly set in `__main__.py`. SIGINT via `signal.signal` + `call_soon_threadsafe`, never `add_signal_handler`.

**3. PRD authority.** Functional requirements live in `prds/*.md` (source of truth). Code that conflicts with a PRD requirement is a bug. Amendments via D15 cycle (CODING_GUIDELINES §1).

**4. Secrets hygiene (D30).** API keys only in `.env` file or environment variables. Never:
- Interpolated into prompts, templates, or prompt payloads
- Sent to any LLM or logged
- Stored in git or config files
- Leaked via error messages
Redaction boundary enforced in logwriter; full prompts logged only to events.jsonl, never run.log.

**5. No line ceiling. Line growth is measured and reported, never capped (v2.0.0, operator decision 2026-08-11).** The G2 numeric ceiling is **withdrawn**. What the ceiling was actually protecting — visibility into where the code is growing, and a bar against silent bloat — is now enforced directly:

- **Measure at every wave barrier** with `find hypesocials -name "*.py" | xargs wc -l | tail -1`. **Never `wc -l hypesocials/**/*.py`** — globstar is off in this shell, so that glob silently counts only ~20 of 39 files (5,844 of 14,176 lines) and misses every file at depth 3.
- **Report growth with per-task attribution**, never a bare total. "+217 (virlo.py +135, server.py +43, models.py +14, …)" is a report; "now at 14,393" is not.
- **Never absorb growth by trimming docstrings, comments or error messages.** That was true under the ceiling and it is the part that still binds. Code that got longer because it does more is fine; code that looks shorter because it explains less is a regression.
- **A file over ~500 lines is still a splitting candidate** (CODING_GUIDELINES §3a) and a deep-module review is still owed (§18) — but on design grounds, not arithmetic.

History for reference: Wave 1 ended at 3,919, Wave 2 at 7,868, Wave 3 at 9,993, Wave 4 at 11,519, Wave 5 at 12,931, MVP at 13,471, post-MVP at 13,486, first-run usability round at 14,176 (corrected measurement).

**6. Junctions, not symlinks.** Windows: `mklink /J` only. Never `os.symlink`.

**7. Money moves only after Confirm gate.** Pre-flight cost estimate shown and approved before any API spend. Under `--yes`, auto-trim to cap if over; refuse-and-exit under interactive mode.

**8. Single operator, Windows workstation.** No multi-user concurrency, no database, no cluster/queue semantics beyond local MCP session pools.

---

## Naming & Quality Standards

See CODING_GUIDELINES.md §18 (Code Quality). Pointer:
- `snake_case` (Python), names describe intent.
- Docstrings on public functions, complex flows, non-obvious decisions.
- Deep modules over shallow (§18 "Deep Modules over Shallow").
- Public API via module `__init__.py`; callers never import internals.
- Single responsibility: one purpose, substantial functionality behind a simple interface.

---

## Operational Constraints

**Single operator.** Manual menu-driven runs or Windows Task Scheduler + `--yes` flag for unattended. No concurrent runs (one `run.bat` instance at a time; any prior process should exit cleanly).

**Windows workstation only.** No Linux/macOS target. ProactorEventLoop, `mklink /J`, `win32job` are Windows-specific.

**MCP session pools:** Virlo default 3 concurrent sessions (bounded, per PRD FR-246), Notion 1 (per spec), Postiz 1 (Phase 2). Unbounded subprocess spawning is a defect.

**Subprocess timeouts:** MCP server startup `mcp_startup_timeout_s` (default 20 s), per-tool-call `mcp_call_timeout_s` (default 30 s), render job timeouts `image_job_timeout_s` (default 600 s, D48) and `video_job_timeout_s`. Timed-out IMAGE jobs are resubmitted exactly once on their own ledger (FR-317, D48); a second timeout is final. Video timeouts never resubmit, and no job ever gets a second poll window for the same task id (20-integrations §8).

**Run deadline:** `run_deadline_min` (default **60 min**, raised 45→60 in v2.2.0/D49 — sized so the 600 s image timeout, FR-317's single resubmit behind it, AND up to three gauntlet re-render rounds all fit inside it; all four shipped configs pin it explicitly. Measured on monotonic clock — never wall-clock, because sleep/NTP steps corrupt wall-clock timing). Soft ceiling; grace-poll aftermath may exceed it if the batch is already submitted. *(This file said 45 until 2026-08-20; that was stale from v2.1.3/D48 and never caught up with the gauntlet raise. `hypesocials/config.py:234` and `prds/30-configuration-and-run.md:88` are the authorities and both say 60.)*

**State files:** `output/latest.txt` (canonical run pointer, atomic temp+rename), `output/latest/` (convenience junction, best-effort), `logs/trend_history.json` (append-only + pruning per window), per-run `meta.yaml` (written pending → terminal via temp+rename).

---

## PRD Governance

**PRDs in `prds/` are the source of truth.** Amendments via D15 cycle:
1. Propose amendment with rationale.
2. Operator approves via explicit consent.
3. Amend PRD file(s) first.
4. Rebuild `00-overview.md` diagram and amendment log.
5. Implement code to match amended PRD.

**Sibling PRDs:** 00-overview (TL;DR, decisions, pipeline diagram), 10-pipeline (run flow, edit cases), 20-integrations (MCP/REST), 30-configuration (config schema, CLI), 40-outputs (folder structure, gallery, logs), 50-promptcraft (prompt playbooks), 60-publishing (Phase 2 Postiz).

**`prd/` vs `prds/` resolution:** CODING_GUIDELINES.md references `prd/` paths (e.g., `prd/_template.md`). **In this repo, the PRD folder is `prds/`** — every `prd/` reference in CODING_GUIDELINES means `prds/`. This repo does not use `prd/`, only `prds/`.

**Root `AGENTS.md`:** Hardlink to CLAUDE.md (the conductor creates it at project setup). Single source of truth for all agent config.

---

## Subagent Guide

| When | Agent | Spawn? | Notes |
|---|---|---|---|
| Python implementation (routes, services, models, tests) | `python-pro` | Yes (leaf) | Owns production code. Multiple concurrent tasks fan to distinct path sets. |
| Prompt templates (playbooks, prompt files) | `prompt-engineer` | Yes (leaf) | Owns `prompts/` and brief examples. Independent of code changes. |
| Test automation, test authoring | `test-automator` | Yes (leaf) | Owns `tests/`. Runs pytest, reports coverage. |
| Code review, technical audit | `code-reviewer` | Yes (read-only leaf) | Reads only; reports findings; never edits. |
| Documentation, user guides, technical writing | `technical-writer` | Yes (leaf) | Owns README, NAVIGATION.md, docstrings in code (via python-pro). |
| Read-only search, exploration, codebase discovery | `Explore` | Implicit | Built-in leaf; never spawns children. Use for open-ended code search. |
| Orchestration across >5 tasks in one domain or shared-file conflicts | (conductor parent) | Sparingly | Wave orchestrator only when flat-wave conditions can't apply (§9a triggers). |

**Model policy (§9):** Never pass `model` parameter when spawning. Agent file's pin is authoritative. Effort inherited from dispatcher.

---

## § 9 — Model & Effort Policy

**Never pass a `model` param when spawning any agent.** The agent definition's pinned model is authoritative. Effort is inherited from the calling context; do not override it.

**Default dispatch is LEAF-WAVE-FIRST.** Main thread launches leaf executors directly (python-pro, prompt-engineer, test-automator) wave by wave from the plan, keeping aggregating-file writes and wire-in for itself. An intermediate orchestrating parent appears **ONLY** on the three conditions below (§9a).

---

## § 9a — Three Triggers for Orchestrating Parent (Direct Quote from CODING_GUIDELINES §21)

An intermediate parent hops in **ONLY** when **any one** of these three conditions holds:

1. **Decomposition unknowable up front** — The work breaks into independent chunks only after exploring the codebase; you cannot carve the plan before starting (e.g., "refactor billing system" without knowing which modules are coupled).

2. **≥5 tasks in one domain in a wave** — Five or more tasks own distinct files within the same module/domain in a single wave, and their execution order is independent. Fan to children; parent aggregates.

3. **Tasks sharing a file or a new shared module that must be designed during the work** — Two or more tasks write to the same file (not their disjoint paths), or they must collaboratively design a new shared module's public API before any implementation starts (a design spike). Orchestrate the spike, then fan to children for parallel implementation behind the designed interface.

**Not a reason:** A task is "heavy" or "important." Heaviness alone does not justify an extra hop.

**Red flag:** "An orchestrator that only re-splits an already-split plan is a defect, not diligence." If you can carve disjoint path sets upfront and dispatch leaf executors directly, do so.

---

## § 9b — /quickfix Review Routing

Exactly ONE review round. Main session is the gate (per CODING_GUIDELINES §21 Review routing). No subagent review cycle; the main thread reviews its own changes inline.

---

## CODING_GUIDELINES Link

Full coding standards: `C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials\CODING_GUIDELINES.md`

Key sections:
- §1 PRD Superiority
- §3a Folder Structure (feature-first, 3 levels max)
- §18 Code Quality (deep modules, naming, linting)
- §19 Definition of Done
- §21 Subagents (spawn triggers, depth caps, FLAT-WAVE-FIRST)

---

## Session Reporting

End every task with:
- **Files changed** — absolute paths, line numbers if relevant
- **What changed** — bullets, what logic was added/modified
- **Wire-in points** — where new code is called from
- **Reused code** — what existing patterns/modules were extended
- **Tests/checks run** — pytest green, lint clean, wc -l checkpoint
- **PRD conflicts** — none / described
- **NAVIGATION.md status** — updated (§X) / no update required

**NAVIGATION.md:** Updated at every wave barrier (§3/§4/§5/§6/§7/§8/§10/§11 affected). Stale navigation is a bug.

---

## Glossary (per PRD)

- **Topic:** A themed, text-only cluster of viral posts from one Virlo monitor — topic name, strength, and view-ranked `SourcePost`s (captions, hooks, overlays, panel texts, engagement). No media, no reference images. Keyed `<monitor>::<topic_key>` in history.
- **Meta-style:** One entry in the local style registry (`styles.yaml`): render prompt, palette, layout zones, typography, text budgets, and a `match_profile` — TEXT-ONLY visual DNA (D46/F3: no reference images; the words alone carry the look). The registry has no fallback (missing/invalid → exit 2, $0). **26 entries since D61 (v2.5.2, 2026-08-20):** 9 originals + `build-log-mono` + 4 census-driven archetype styles + 5 `-teal` variants carrying the brand teal spine (19 at D56/D57) + 7 carousel-derived styles authored born-compliant in SESSION L (`big-number-editorial`, `contrast-verdict-deck`, `photo-poster-statement`, `mono-cutout-editorial`, `neon-glass-dark`, `paper-editorial-carousel`, `aurora-white-deck`; no `-teal` twins); the three shipped brand configs enable a 17-key subset (the D57 twelve + the five teal-accented newcomers — `paper-editorial-carousel` is vermilion and `mono-cutout-editorial` has no accent, so both stay off the teal-spine selection). Chip, badge, counter, and signature specs live ONLY in gated `layout_zones` (per FR-339), never in the unconditional `typography`/`text_placement`/`visual_pacing` fields. **Since D60 (v2.5.1, 2026-08-20) every style also obeys the palette contract (FR-347: one accent hue family, ≤ 1/8 of frame, coverage stated on the line, grounds at a value extreme), the type contract (FR-348: two families, mono utility only for the three code/terminal styles) and the house spine (FR-350) — see the entries below.** Assignment is deterministic rotation (FR-291) by default, and under `styles.assignment: matched` (D56, pinned in the shipped brand configs) an LLM matcher OVERLAYS that baseline — see below.
- **Matched assignment (FR-334, D56):** One batched, fail-open `analysis` call at ASSIGN picks the best-fitting enabled style per creative from that creative's own pool (`usable_styles` × `fmt_affine`, imported never re-derived), answering on **asset_id, never ordinal**. `high`/`medium` are accepted; `low`, an out-of-pool key or a missing row keeps the FR-291 baseline and preserves the `wanted_archetype` for the console gap report; a whole-call failure puts every entry on baseline with `style_match_degraded`. Provenance (`style_fit`, `style_reason`, `style_origin`, `style_wanted`) rides `PlanEntry` → `AssetRecord` → `meta.yaml` → gallery. **Matched picks are not reproducible run-to-run — the rotation baseline underneath stays a pure function, and `assignment: rotation` restores pre-D56 behaviour byte-exactly.** Note the neighbouring `styles.rotation` (`seeded|fixed`, D52) is a DIFFERENT knob: it chooses where the deterministic scan starts, not which algorithm runs.
- **Topic filter:** Two layers between Collect and Select — a deterministic competitor blocklist (fail-closed) and one batched LLM screen returning `keep | strip | skip` verdicts with strip guards (fail-open, `filter_degraded` on failure).
- **Verbatim copy:** The copy LLM returns *references* (`P1.hook.2`, …) into a topic's source posts; the engine resolves them to bytes. Never retyped, trimmed, or translated — source language kept; free text is allowed only where nothing becomes pixels (`through_line`, `narrative_arc`, `motion_beat`) D54 carve-out (2026-08-20): an operator-opted `compress` mode for bound carousel decks (`carousel_copy_mode`; **NOT shipped-on — D58 withdrew that pin the same day; since D62 (v2.6.0, 2026-08-21) all three brand configs ship `auto` (see Auto copy mode below), the engine default stays `verbatim`, and full compress is reached per run with `--copy-mode compress`**) has the copy LLM compress admitted panel texts to the min(config, style) slide budget — humanized, source language kept, never invented; the engine scrubs (blocklist fail-closed, social marks blanked, word-boundary trim) and a failed compress call falls back to the verbatim mapped deck tagged `copy_degraded`. Verbatim stays the engine default (FR-331). **D63 carve-out (2026-08-21, FR-343):** under `run.copy_language_mode: target` a bound deck in a language the platform does not write is TRANSLATED (never shortened) — the THIRD copy boundary, and the only one where a shipped slide string may be longer than its source; see "Output language" below.
- **Panel map (FR-304):** The deterministic, position-preserving mapping from a bound slideshow post's panels onto OUR deck: source panel *i*'s text becomes our slide *i*'s text, verbatim; an empty/unusable/over-budget panel yields a wordless slide that KEEPS its position (the row is the alignment). Persisted per creative in `meta.yaml.panel_map`. Under D54 compress mode the SAME single walk maps positions but ships LLM-compressed text: rows carry `compressed: true`, `source_text_original` (the source bytes) and `source_text` (the shipped compressed string), `ref_label` empty; the three drop reasons and position preservation are identical to verbatim (FR-304d).
- **Slide intelligence (FR-306):** The post-Confirm Sonnet-5 vision pass over each assigned carousel's source slides — verbatim `onimage_text` transcription (fills empty Virlo panels, never overwrites them), an English `visual_brief` per slide (content directive for FR-308 rendering), `brand_marks` for §0.12 safety. Fail-open (§0.14c); one call per post.
- **Source store (§0.13):** Run-level `output/<run>/source/<post_id>/` — the bound posts' slides downloaded once (`slide_NN.jpg`) plus `source.yaml` provenance. Feeds vision analysis and the offline gallery; never published. Never uploaded to Kie except the D48 carve-out: cropped tool-logo patches (`marks/`, FR-315).
- **Counter rule (FR-338, D59):** The five-arm logic governing whether a render slot displays a counter, a "no counter" placeholder, or nothing: (a) no style → silent; (b) style declares `counter_slot` AND deck is counted → render that zone's line; (c) zone declared but uncounted → "no counter" line; (d) no zone but counted → house-default line (small, body font, top-right, no chip/badge); (e) neither → silent. Override briefs always silent. Counters detected from source chrome (numerals matching position, constant offset, unnumbered leading slides); source-mirrored on output slides, position-preserving (FR-313).
- **Gated-zone rule (FR-339, D59):** Registry authoring contract — a style's `typography`, `text_placement`, `visual_pacing` prose MUST NOT describe chips, badges, counters, page numbers, signatures or lockups. Those specs belong ONLY in the `layout_zones` section, gated by zone role (`counter_slot`, `brand_slot`, etc.), never unconditionally. Enforced by test guard on shipped styles.
- **Empty-zone rule (FR-340, D59):** Text zones with no string quoted are LEFT OUT of the frame — never filled with invented words or graphic elements (bars, rules, blocks, placeholders). Repeating devices (rows, cards, chips) exist only where lines are quoted, never as empty placeholders or default graphics.
- **Palette contract (FR-347, D60):** The hex-based registry rule `styles.py` checks at pre-flight. Every `#RRGGBB` in a style's `palette` lines is parsed to HSV; a hex is *saturated* when S ≥ 0.45 and 0.15 ≤ V ≤ 0.95. A line's leading uppercase token is its ROLE: background roles (`GROUND`/`GROUNDS`/`SURFACE`/`DEPTH`/`SHADOW`) may carry a saturated photographic cast and are never accents; every other line's saturated hexes are ACCENTS and must (a) sit in ONE hue family (every pair within 30° on the colour wheel), (b) state a coverage clause on that same line (`under 1/8`, `under 8%`, `max 1/8`) with a bound ≤ 1/8 of frame, and (c) contrast with any saturated ground (> 30° apart). Zero accents is legal (pure monochrome). Shipped in warning mode (`_PALETTE_CONTRACT_ENFORCED = False`) until all 19 styles were clean, then flipped to an FR-295 error (exit 2, $0). Role vocabulary: Background = GROUND/SURFACE/DEPTH/SHADOW · Primary = TEXT/SUPPORT/MUTED · Accent = ACCENT.
- **Type contract (FR-348, D60):** One display family + one body family per style ("if it has personality it is wrong"); a third family only as a MONO utility and only for a code/terminal identity (`build-log-mono`, `circuit-atlas-dark`, `terminal-mockup-deck`). The validator counts five family classes (serif · sans · mono · script · woodtype/display) over the non-negated clauses of `typography` and every zone's `text_treatment` and WARNS above two (a third `mono` tolerated); it is a heuristic over prose, so it is a warning, never an error — a test guard pins the mono-utility list.
- **Variant scan (FR-349, D60):** The M9 either/or check (`" or "`, `"variant "`, `"either "`) now reads every DNA field — `palette`, `typography`, `text_placement`, `image_treatment`, `visual_pacing`, `list_mode.layout`, `per_format_guidance` — not just `render_prompt`. Clause rule: a clause (split on `; ` `. ` `: `) containing a marker is a leak UNLESS it also carries a negation word (`no`, `not`, `never`, `nothing`, `none`, `nor`, `neither`, `without`, `rather than`), so "no serif, script or display face" is a ban list and passes while "mono or tracked caps" is a choice and warns. `exclusions` and `layout_zones` are not scanned. Warning only.
- **House spine (FR-350, D60):** What EVERY carousel-affine style shares, and nothing more: exactly one accent hue ≤ 1/8 with its coverage stated · ground at a value extreme (near-white/cream or near-black; V ≥ 0.85 or ≤ 0.20 for `motion_profile: graphic`, photographic casts exempt) · counter **top-right** · all text inside the central 80% of the 1:1 frame (no `4:5` band) · two type families. FREE per style: margins, type scale, ground hex, motif, accent hue. The swipe cue stays wordless. Enforced by test guards over the shipped registry, not by a load-time error. Consequences in D60: `icon-ledger-carousel`'s full-width mid-teal footer strip retired (hairline + type), `letterpress-print-carousel` ×2 terracotta body ground retired (cream cover and body — settles the Session I ruling: teal on cream), three top-left counters flipped to top-right.
- **Image resolution (FR-342, D60):** `platforms.<name>.image_resolution: 1k | 2k` (engine default `1k`; the three brand configs pin `2k` on every platform for colour accuracy — render $0.03→$0.05 per slide, critic vision tokens 1,398→3,278 per frame, ≈ +$3–6 per 9-carousel run). ONE accessor, `Config.image_resolution(platform)`, feeds both the estimator's `price_per_unit.image.<tier>` lookup and `RenderParams.resolution` at the five image render sites (carousel slides, image post + its gauntlet re-render, reel seed frame + its re-render), so the Confirm-gate estimate and the bytes ordered can never disagree. `4k` is refused at config load (FR-192: never requested).
- **Registry supply (FR-341, D61; handoff table amended D63):** *(D63: the M preview `20260821_010802_0wfg` put `big-number-editorial` on 5 of 9 because its `match_profile` claimed ANY one-item-per-panel deck; it is narrowed to panels that OPEN on their own ordinal, with unnumbered one-statement panels handed to `photo-poster-statement`, one tool per panel at review length to `neon-glass-dark`, corporate short rows to `aurora-white-deck` — profile prose only, measurements unchanged.)* Why the 2026-08-20 run put six of nine decks on one style: `icon-ledger-carousel` was the only ENABLED style whose `match_profile` claimed numbered decks at all — a supply fault, not a matcher fault. D61 answers it with seven carousel-derived styles (19 → 26) whose `match_profile`s are mutually exclusive by archetype (FR-341's handoff table: many-rows-on-one-frame → `icon-ledger-carousel`, one numbered step per panel → `big-number-editorial`, technical numbered process → `build-log-mono`, before/after → `contrast-verdict-deck`, big statement over photo → `photo-poster-statement`, manifesto → `mono-cutout-editorial`, object-led SaaS tour → `neon-glass-dark`, editorial explainer → `paper-editorial-carousel`, corporate short rows → `aurora-white-deck`), `icon-ledger-carousel` and `circuit-atlas-dark` narrowed to hand off what they used to swallow, and `styles.enabled` 12 → 17. Each new style was measured ONE AT A TIME with `plans/tools/measure_one_style.py` (owned ≤ 4,700 · `style_dna` ≤ 2,000 · cutA ≤ 1,540 · slackB ≥ 60) before the next was authored.
- **Concentration line (FR-355, D61):** One arithmetic warning under the ASSIGN receipts, in `matched` AND `rotation` mode, ≤ 78 chars, never a refusal: prints when one style takes more than half the styled creatives (`concentration: <style> 6/9 (>1/2) - pool may be starved`) or fewer than three distinct styles cover a plan of five or more. It is the console half of the FR-337 gap report for the case the gap block cannot see — the matcher answered `high` everywhere and the pool was simply starved (`style_wanted` empty on all nine decks of run `4a0q`). Logged as `style_concentration`. Override briefs (no style) are excluded from both numbers.
- **Cover best-of-3 (FR-351/FR-352, D62):** `run.cover_candidates` (1–3, engine default 1, the three brand configs pin 3). Above 1 the chained carousel's anchor stage submits that many IDENTICAL slide-1 jobs at once (wave-1 `projected` spend; each candidate is its own FR-317 resubmit ledger), keeps every landed candidate under `<asset>/covers/cover_candidate_<N>.jpg` (never uploaded, never a render reference, never globbed as a slide), and ONE vision `analysis` call (`prompts/cover_pick_system.md`, `hypesocials/cover_pick.py` on the `style_match.py` fail-open shape) picks the anchor by candidate id — judging style-contract adherence → legibility at thumbnail size → stopping power, in that order. The winner is committed as `slide_01`/`anchor_url` and passes through the unchanged FR-325 pre-gate; any pick failure commits candidate 1 and tags `cover_pick_degraded`; a lost loser never dooms the deck; zero landed → the old FR-95 single re-anchor. `meta.yaml.cover_pick = {candidates, chosen, reason, degraded}` feeds a gallery strip. Estimator: a `cover_candidates` render line (N−1, expected spend) and a `cover_pick_call` analysis line + retry allowance per chained deck (≈ +$1.60 per 9-deck run at 3 and 2K). No extra covers are ordered when no metered call is wired (`cover_candidates_unjudged`).
- **Auto copy mode (FR-353/FR-354, D62):** `carousel_copy_mode: auto` — the FR-304 verbatim mapped deck is built first and unchanged, then the PURE `copywrite._rows_over_budget(texts, budget)` (Session N calls it on the translated deck) names the positions whose admitted text exceeds min(`text_budgets.slide`, style `max_onimage_chars.slide`); ONLY those go through the existing compress call (the panel block lists just those positions; the template's "unprinted position answers an empty string" rule carries the rest) and are spliced back by position with `compressed: true`, `source_text_original`, an empty `ref_label`. Rows that fit keep their bytes AND their `ref_label`; the caption/headline are the call's (compressed, humanised). A deck with nothing over budget makes NO call and is byte-identical to verbatim (`copy_mode: verbatim`); a deck that took the call records `copy_mode: auto`; whole-call failure → verbatim + `copy_degraded`; an over-budget row answered empty keeps its verbatim bytes (`auto_row_kept_verbatim`, no tag). The gallery reads compression per ROW (`_any_compressed`), never from mode equality. Menu step 3 `1 verbatim · 2 auto · 3 compress` (six steps stay six), `--copy-mode {verbatim,auto,compress}`, launch summary prints `carousels   copy mode: auto · cover candidates: 3 · anchor chained`.
- **Output language (FR-343/FR-345/FR-346, D63):** `run.copy_language_mode: source | target` (engine default `source`; the three brand configs pin `target`; `--copy-language` flag over file; config + CLI only, NEVER a wizard step — shown as a `copy language:` fact on the confirm screen and a `language` line on the `--yes` launch summary). Under `target` a BOUND, panel-mapped carousel whose source post is in a known language other than its platform's configured one (`run.languages[platform]`) takes ONE translate call of its own (`copywrite._call_translate`, `prompts/copy_translate_system.md` — the eleventh global role template / sixteenth shipped role, `{{translate_panels}}` allowlisted to it alone) that translates and NEVER shortens: `_translate_field` has no budget parameter, `{{text_budgets}}` takes its verbatim branch so no `(at most N characters)` is ever stated, only `PANEL_SANITY_CHARS` gates a line, and a translation may be LONGER than its source. Posts already in the platform's language stay byte-verbatim under both values; an unknown language ships verbatim with one `translate_language_unknown` warning. **Translate runs BEFORE the auto budget test** — `_rows_over_budget` measures the TRANSLATED texts and only then does the compress call run on those rows. Already-target backstop (the model says the panels were already in the target language and changed a line → source bytes ship), length-drift audit (< 0.5× / > 2.0× → `translate_length_drift`, ships). Whole-call failure → the FR-304 verbatim mapped deck + `copy_degraded` + `copy_not_translated` (loud on the console like `copy_degraded`, never in the exit-1 set). Scope is bound carousel decks only — images, reels, override briefs and unbound decks ship their source language and pre-flight says so. Under `source` the German-deck fix is the bind-time screen: `plan.off_language_post` skips a post whose known language the run does not write (`fresh_source_post`'s fourth eligibility test, `_carousel_supply` agreeing), and the topic filter's LANG skip still fires; under `target` both let foreign material in. Receipts: `CopyProvenance`/`meta.yaml` `copy_language` (`source|target` — the LANGUAGE axis, orthogonal to `copy_mode`, the LENGTH axis: a translated deck that compressed nothing is `copy_mode: verbatim, copy_language: target`), `source_language` (recorded on every bound deck where known, both modes), per-row `panel_map[*].translated`; gallery card line + per-row `translated from de` chip; previews/runner count translated decks; estimator `translate_call` line per deck (worst case every carousel until ASSIGN binds posts whose language is known and already the platform's).
- **Language ladder (FR-343, D63):** how the engine learns a bound post's language without paying for it — 1) `SourcePost.language` (Virlo's free `intelligence.language_detected`, forwarded by both wrapper normalisers, normalised to ISO 639-1 by `topic_filter.language_code` at the adapter; `SourcePost.multilingual` rides beside it) → 2) `SlideIntel.language` (ONE deck-level key on the slide-intelligence answer, `""` allowed; the runner hands it to `write_copy(post_languages=…)`) → 3) the FR-294 topic screen's own `Verdict.language` for the post's topic (`write_copy(topic_languages=…)`, keyed by trend — the evidence the `source`-mode LANG skip reads, so `target` can never be blinder than `source`) → 4) `""` = unknown. **No stopword/diacritics heuristic, no extra LLM call** (`topic_filter.fuzzy_strip` records why).
- **Bare-numeral counter (FR-313 amended, D63):** the checkpoint deck `20260820_234620_j867` `_03` carried a bare `01`…`07` LINE inside every panel's words and detected no counter. `slide_intel.detect_counter` rule 2 (positional) now also accepts a line that is ONLY a 1–2-digit numeral equal to its slide position on ≥ 2 slides — bare candidates take part in rule 2 ALONE, never rules 1/3/4 (a stray content numeral must not manufacture a constant offset) — and the admission strip drops such a line into `chrome_counter_stripped` through `counter_line(text, position=<ordinal>)` (`position=0` switches the bare shape off entirely). `source_text_original` keeps the line.
- **Parity grounds (SESSION M ruling, D62):** Under anchor chaining slides 2–N take slide 1 as their primary reference and the template says "match STYLE_DNA exactly", so a style whose ground is keyed to the slide number never renders that way — `big-number-editorial` and `contrast-verdict-deck` now declare ONE ground per deck (`# DELIBERATE`), and `big-number-editorial`'s big numeral and row disc exist only where the quoted line opens on a number (no invented position numerals).
- **Provenance gallery (FR-309):** The per-carousel three-part card — source-post provenance header, ORIGINAL slide strip with extracted text + visual briefs, OUR slides aligned index by index; judged on style adherence, topical accuracy and panel fidelity (FR-150).
- **Match profile:** One or two authored sentences per style saying what SOURCE MATERIAL it suits (not what it looks like). Read by the FR-334 matcher alone — never by a render prompt, a budget line or a drop path. Missing is legal: it draws an advisory warning and falls back to the first sentence of `render_prompt`, never an FR-295 refusal.
- **Contract guards (FR-362/FR-363, D65):** Nine deterministic checks (`hypesocials/contract_guard.py`) run over a creative's finished `panel_map` at ONE seam in `copywrite`, covering all four copy walks: digit repair + drift (`copy_digit_drift`), row realignment (`panel_map_realigned`), line dedupe, identity scrub (creator handles, `owner/repo`, `#N`, commit lines, unsanctioned brand marks — beheaded rows go wordless rather than ship an orphan), truncation gate, coverage assertion (`panel_dropped_unmapped`), watermark-as-chrome, plus the caption scrub and first-person `caption_voice_review` tag. They exist because the CONTRACT itself was corrupt and nothing validated it — the renderer was obeying its orders. Packaging separately BLOCKS a carousel delivering fewer slides than it ordered (`incomplete_deck`), which used to ship as `success`.
- **Measurement is not an acronym (D65):** `ocr_repair` mapped `1→I`, `0→O`, `5→S` inside any all-caps token, so admission MANUFACTURED `I6GB`, `I46K`, `IOX`, `7OB` out of correct Virlo panels and rendered them. A digit run followed by a known unit now keeps its digits; a genuine mis-read (`0PENAI`) still repairs.
- **Colour lock (FR-364, D65):** A shared `colour_rendering` row PREPENDED inside `prompts_engine.style_dna()` (230 chars, and the length is load-bearing — the 288-char draft cost enough trio-trim budget to strip FR-340 off five styles' longest panels). It reaches the renderer AND both the brief and system critics in byte-identical words. Codex sends `quality: "high"`; `input_fidelity` is NOT sent — the proxy answers HTTP 400 for it on both image routes.
- **Phantom required marks (FR-366, D65):** The gauntlet demanded logos that were never cropped, on frames whose source panel never carried them — and the renderer INVENTED marks to comply. Three fixes: the author test was backwards (handle `devrush01` is never a substring of mark `DevRush`) and is now bidirectional; REQUIRED marks are only marks with an actually-cropped patch; and the demand is PER FRAME, not a deck-wide union. `required_marks` survives as the deck-wide EXEMPTION list.
- **Critic rebalance (FR-367, D65):** Softer on style, harder on content. The brief critic gains when-unsure-PASS for non-leakage codes (leakage keeps when-unsure-FAIL) and new rules for numeral fidelity, duplication, ordinal ladders, wordless frames and mid-clause truncation; the system critic is told measurements are not its subject and that content failures outrank a few per cent off grid; "an invented app UI" leaves tier-1 `platform_chrome` for craft. `critic_reasoning_effort` drops `xhigh` → `high` in the three brand configs (at `xhigh`, run pm3y shipped 0 of 3 decks).
- **Empty-element purge (FR-368, D65):** 9,955 characters of positive "greeking" prose (instructions telling the model to draw grey filler bars) removed from the registry — the reason 7 of 8 codex decks shipped empty cards and circles. A repeating device exists only around QUOTED text; a greek allowance survives only where the mock-up IS the identity (`terminal-mockup-deck`, `platform-showcase-card`). New CRAFT code `empty_element` buys a re-render and never blocks.
- **`--style-test` (FR-369, D65):** Diagnostic mode — one full carousel deck per named style, every deck bound to ONE pinned source post, so styles are compared on identical material. The `--styles` list ORDER is the matrix (`styles.assign_styles_fixed`, not the D52 `rotation: fixed` knob, which walks registry order and silently skips). Refuses without `--styles`. Writes NO trend history and leaves `output/latest` alone.
- **Screenshot paste (FR-370, D65):** A real interface in a source slide is reused as EXACT PIXELS, never redrawn. Slide intelligence answers `panel_kind` + `screenshot_box`; the render reserves an empty plate; `outputs/screenshot_paste.py` composites the crop locally AFTER the render lands and BEFORE any critic looks, so re-renders are re-pasted. Source bytes still never reach a render payload. Skipped when the screenshot is of the creator's OWN post (the definitional identity leak); third-party content inside the zone is the whole point and is sanctioned for the critics.
- **Branding rotation:** `entry.branded` is set by the floor predicate `floor((order+1)·ratio) > floor(order·ratio)` at `branding.brand_ratio`; a full plan of N carries exactly `floor(N·ratio)` branded entries. The wordmark renders through the TEXT block (never the branding block); a carousel is signed on the anchor slide only.
- **Anchor chaining:** Carousel slide 1 renders first, becomes primary reference for slides 2–N.
- **Seed frame:** GPT Image 2 render of the selected on-image text (baked-in), used as both an asset and a Seedance reference.
- **Motion beat:** One named physical action returned by the copy call, driving the reel's animation stage. Reels use no video references (no-reference billing; yt-dlp is gone).
- **Brief / niche:** Small override file (message, visual directives) or config-file niche descriptor (audience, vibe).
- **Wave-1 / Wave-2 renders:** Wave-1 = carousel anchor + reel seed frames (checked, referenced); Wave-2 = remaining slides/animation (submitted after wave-1 completes or pre-committed).
- **Permit gate:** 2-tier priority semaphore ensuring wave-2 work isn't starved by queued wave-1 jobs.
- **Run deadline:** Soft elapsed-time ceiling (default 60 min since v2.2.0/D49, monotonic clock).
- **Subscription backends (D64, FR-356–361):** Two billing modes — metered (OpenRouter LLM + Kie.ai renders, default) and subscription (Codex LLM + renders, opt-in via config keys `models.llm_backend` and `models.render_provider`). Codex probed at pre-flight via local HTTP proxy, returns zero cost, reel generation refused, reasoning effort gains `xhigh` tier, outputs to local `file://` paths. Fallback: `git tag pre-codex-pivot` (b6eac4d).
- **Autopilot (D64, FR-361):** Claude Code skill (`.claude/skills/hypesocials-run/`) offering post-run advisory review. Entry via `autopilot.bat` or `menu.py` option 6. Agents `hs-operator` (run legality + FR scope) and `hs-deck-critic` (visual fidelity per deck) produce `CLAUDE_REVIEW.md` and `AUTOPILOT_LOG.md` in run output folder. Scope: design violations, visual contract breaches, missing gallery cards; failsafe always silent (no operator blocker; suggestions only).

---

**Last updated:** 2026-08-21 (v2.9.0/D65, SESSION P: render-quality round — panel-map contract guards + incomplete-deck block (`hypesocials/contract_guard.py`, FR-362/363); the `ocr_repair` root cause (a measurement is not an acronym — admission was manufacturing `I6GB`/`I46K`/`IOX` itself); colour lock row in `style_dna` + codex `quality: high` (`input_fidelity` refused by the proxy, HTTP 400) + alpha-halo guard (`outputs/alpha_halo.py`, FR-364/365); phantom-marks fix — backwards author test, cropped-patch-only REQUIRED marks, per-frame demand (FR-366); critic rebalance softer on style and harder on content, `critic_reasoning_effort` xhigh→high (FR-367); empty-element purge — 9,955 chars of greeking out of the registry + new craft code `empty_element` (FR-368); `--style-test` mode (FR-369); exact-pixel screenshot paste (`outputs/screenshot_paste.py`, FR-370). Prior: 2026-08-21 (v2.8.0/D64, SESSION O: subscription backends + autopilot — two billing modes via `models.llm_backend` and `models.render_provider` config keys (openrouter/kie metered default, codex subscription opt-in; brand configs pin codex), pre-flight proxy probe + model allowlist (gpt-5.6-sol/terra/luna, gpt-image-2), reel refusal, reasoning effort gains `xhigh`, zero cost confirm gate, local `file://` results, `hypesocials/codex_proxy.py` + `hypesocials/render/codex_images.py`, `.renders/` storage (FR-356–360); Claude Code autopilot skill `.claude/skills/hypesocials-run/` with `hs-operator` and `hs-deck-critic` agents, `autopilot.bat` entry, advisory review post-run (FR-361); NAVIGATION.md § 11 backend switching task, § 3/5/8/9/13 amendments, CLAUDE.md Stack/Architecture/Glossary amendments (prds v2.8.0 D64 complete). Prior: v2.7.0/D63, SESSION N: output language — `run.copy_language_mode` source|target (brand configs `target`), `--copy-language`, language ladder (Virlo detected → slide-intel → unknown), `copywrite._call_translate` + `prompts/copy_translate_system.md` (SHIPPED_COUNT 16), translate-before-auto, `copy_language`/`source_language`/per-row receipts (FR-343–346); FR-313 bare-numeral; `big-number-editorial` match narrowed (FR-341). Prior: v2.6.0/D62 SESSION M (cover best-of-3, auto copy mode, FR-351–354); v2.5.2/D61 SESSION L (seven carousel styles, FR-355); v2.5.1/D60 SESSION K (palette/type contracts, house spine, 2K image tier); v2.5.0/D59 SESSION J (FR-338/339/340).
