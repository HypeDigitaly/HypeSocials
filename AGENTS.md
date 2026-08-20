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

**External services:** OpenRouter REST (LLM), Kie.ai REST (renders), Virlo REST (via MCP wrapper), Notion MCP

**Media libraries: Pillow for logo-patch cropping ONLY (D48).** The topic-first pivot (D41–D45, 2026-08-12) removed Pillow and yt-dlp; D48 (2026-08-13) reinstated Pillow with a single sanctioned use — cropping tool-logo patches out of downloaded source slides for FR-315 pixel references. No other image processing, no compositing, no resizing pipelines, and yt-dlp stays gone (reels use no video references).

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
- **Meta-style:** One entry in the local style registry (`styles.yaml`): render prompt, palette, layout zones, typography, text budgets, and a `match_profile` — TEXT-ONLY visual DNA (D46/F3: no reference images; the words alone carry the look). The registry has no fallback (missing/invalid → exit 2, $0). **19 entries since D56/D57 (2026-08-20):** 9 originals + `build-log-mono` + 4 census-driven archetype styles + 5 `-teal` variants carrying the brand teal spine; the three shipped brand configs enable a 12-key subset. Chip, badge, counter, and signature specs live ONLY in gated `layout_zones` (per FR-339), never in the unconditional `typography`/`text_placement`/`visual_pacing` fields. **Since D60 (v2.5.1, 2026-08-20) every style also obeys the palette contract (FR-347: one accent hue family, ≤ 1/8 of frame, coverage stated on the line, grounds at a value extreme), the type contract (FR-348: two families, mono utility only for the three code/terminal styles) and the house spine (FR-350) — see the entries below.** Assignment is deterministic rotation (FR-291) by default, and under `styles.assignment: matched` (D56, pinned in the shipped brand configs) an LLM matcher OVERLAYS that baseline — see below.
- **Matched assignment (FR-334, D56):** One batched, fail-open `analysis` call at ASSIGN picks the best-fitting enabled style per creative from that creative's own pool (`usable_styles` × `fmt_affine`, imported never re-derived), answering on **asset_id, never ordinal**. `high`/`medium` are accepted; `low`, an out-of-pool key or a missing row keeps the FR-291 baseline and preserves the `wanted_archetype` for the console gap report; a whole-call failure puts every entry on baseline with `style_match_degraded`. Provenance (`style_fit`, `style_reason`, `style_origin`, `style_wanted`) rides `PlanEntry` → `AssetRecord` → `meta.yaml` → gallery. **Matched picks are not reproducible run-to-run — the rotation baseline underneath stays a pure function, and `assignment: rotation` restores pre-D56 behaviour byte-exactly.** Note the neighbouring `styles.rotation` (`seeded|fixed`, D52) is a DIFFERENT knob: it chooses where the deterministic scan starts, not which algorithm runs.
- **Topic filter:** Two layers between Collect and Select — a deterministic competitor blocklist (fail-closed) and one batched LLM screen returning `keep | strip | skip` verdicts with strip guards (fail-open, `filter_degraded` on failure).
- **Verbatim copy:** The copy LLM returns *references* (`P1.hook.2`, …) into a topic's source posts; the engine resolves them to bytes. Never retyped, trimmed, or translated — source language kept; free text is allowed only where nothing becomes pixels (`through_line`, `narrative_arc`, `motion_beat`) D54 carve-out (2026-08-20): an operator-opted `compress` mode for bound carousel decks (`carousel_copy_mode`; **NOT shipped-on — D58 withdrew that pin the same day, all three brand configs ship `verbatim`; reach it per run with `--copy-mode compress`**) has the copy LLM compress admitted panel texts to the min(config, style) slide budget — humanized, source language kept, never invented; the engine scrubs (blocklist fail-closed, social marks blanked, word-boundary trim) and a failed compress call falls back to the verbatim mapped deck tagged `copy_degraded`. Verbatim stays the engine default (FR-331).
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
- **Provenance gallery (FR-309):** The per-carousel three-part card — source-post provenance header, ORIGINAL slide strip with extracted text + visual briefs, OUR slides aligned index by index; judged on style adherence, topical accuracy and panel fidelity (FR-150).
- **Match profile:** One or two authored sentences per style saying what SOURCE MATERIAL it suits (not what it looks like). Read by the FR-334 matcher alone — never by a render prompt, a budget line or a drop path. Missing is legal: it draws an advisory warning and falls back to the first sentence of `render_prompt`, never an FR-295 refusal.
- **Branding rotation:** `entry.branded` is set by the floor predicate `floor((order+1)·ratio) > floor(order·ratio)` at `branding.brand_ratio`; a full plan of N carries exactly `floor(N·ratio)` branded entries. The wordmark renders through the TEXT block (never the branding block); a carousel is signed on the anchor slide only.
- **Anchor chaining:** Carousel slide 1 renders first, becomes primary reference for slides 2–N.
- **Seed frame:** GPT Image 2 render of the selected on-image text (baked-in), used as both an asset and a Seedance reference.
- **Motion beat:** One named physical action returned by the copy call, driving the reel's animation stage. Reels use no video references (no-reference billing; yt-dlp is gone).
- **Brief / niche:** Small override file (message, visual directives) or config-file niche descriptor (audience, vibe).
- **Wave-1 / Wave-2 renders:** Wave-1 = carousel anchor + reel seed frames (checked, referenced); Wave-2 = remaining slides/animation (submitted after wave-1 completes or pre-committed).
- **Permit gate:** 2-tier priority semaphore ensuring wave-2 work isn't starved by queued wave-1 jobs.
- **Run deadline:** Soft elapsed-time ceiling (default 60 min since v2.2.0/D49, monotonic clock).

---

**Last updated:** 2026-08-20 (v2.5.1/D60, SESSION K: colour the model can hit, type contract, house spine, 2K — FR-342 (`platforms.<name>.image_resolution`, brand configs pin 2k), FR-347 (hex-based palette contract: one accent hue family ≤ 1/8 with coverage on the line, grounds at a value extreme; warning mode → FR-295 error once all 19 were clean), FR-348 (two type families, mono utility for three code/terminal styles; warning), FR-349 (variant scan over every DNA field with the negation clause rule), FR-350 (house spine: one accent, extreme ground, counter top-right, central-80% safe area, two families; margins/type scale/ground hex/motif/accent hue stay free). Registry consequences: icon-ledger footer strip retired, letterpress ×2 terracotta retired (teal on cream — Session I ruling settled), editorial-voxel orange and anime-noir amber retired as second hues, three top-left counters → top-right. Glossary gains Palette contract, Type contract, Variant scan, House spine, Image resolution. Prior: v2.5.0/D59 SESSION J contracts & render correctness (FR-338/339/340, FR-313 amendment), v2.4.1/D58 compress pin withdrawn, v2.4.0/D56–D57 SESSION I registry 9→19 + LLM-matched assignment + teal spine.
