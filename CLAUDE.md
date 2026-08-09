# CLAUDE.md — HypeSocials Project Conductor

## What This Is

Project configuration and agent coordination guide for HypeSocials MVP (Phase 1). Single-operator Windows CLI tool that generates viral social creatives (images, carousels, reels) from Virlo trends via LLM analysis and Kie.ai renders. ~3 min (images/carousels only) or ~8–10 min (with reels); <$1 per post.

---

## Stack

**Core runtime:** Python 3.12+, asyncio with `ProactorEventLoop` (mandatory on Windows)

**Async I/O:** `httpx`, stdlib `asyncio`, stdlib `signal.signal` + `call_soon_threadsafe` for SIGINT (never `add_signal_handler` — unavailable on Windows)

**Config & serialization:** `pyyaml`, `python-dotenv`

**MCP:** `mcp` (official Python SDK), both stdio servers (Virlo wrapper in-repo, Notion via package) and HTTP transports

**Media & video:** `Pillow` (image downscale only per FR-93), `yt-dlp` (reel video-reference download)

**System-level:** `pywin32` (Windows job objects for subprocess tree reaping, `win32job` module), `argparse` (CLI flags only, not menu)

**External services:** OpenRouter REST (LLM), Kie.ai REST (renders), Virlo REST (via MCP wrapper), Notion MCP, yt-dlp

**No database.** State is files: config YAML, trend_history.json, run logs, asset metadata (meta.yaml per creative).

---

## Architecture

**Feature-first, not layer-first.** Module tree per plan §1: `hypesocials/` domain folders (sources, render, generate, outputs, etc.) each own their routes/service/models/schemas together. Module public API via `__init__.py`; deep modules hide complexity from callers.

**All I/O async.** No blocking I/O on the event loop. HTTP via `httpx`, subprocesses via `asyncio.create_subprocess_exec`, MCP tool calls via MCP SDK's async methods.

**Windows event loop:** `asyncio.ProactorEventLoop()` (required for subprocess support on Windows; default on Windows in Python 3.8+ but stated explicitly in code). SIGINT handling: `signal.signal(signal.SIGINT, handler)` + `loop.call_soon_threadsafe()` to enqueue the stop — never `loop.add_signal_handler()` (unavailable on Windows).

**Process reaping:** Subprocess trees (especially MCP stdio servers and `yt-dlp`) are fully terminated on every exit path (success, failure, timeout, abort) via Windows job objects (`win32job.CreateJobObject` + `win32job.SetInformationJobObject` with kill-on-close). Fallback: `taskkill /T` sweep on orderly exits only.

**Junctions for directory symlinks:** `mklink /J` subprocess call (never `os.symlink`, which requires admin/DevMode). Used for `output/latest/` pointer.

**MCP clients:** One shared async MCP client (`mcp_client.py`) with per-server launch/env/timeout config, bounded session pools (Virlo pool default 3 per PRD FR-246/FR-259), per-server environment dicts (only the keys each server needs), and Windows-safe `.cmd`/`.exe` shim resolution.

**Reference images:** Virlo + Inspiration + briefs → downloaded/uploaded to Kie via file-upload API (host `kieai.redpandaai.co`, ~24 h retention) → URLs passed to render jobs. Local-file Inspiration and brief images are uploaded on-demand; Virlo CDN images are downloaded per-job for reference pooling.

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

**5. G2 line ceiling: 10,000 lines (target ~9,500 — v1.6.4, operator decision 2026-08-09).** Tracked at every wave barrier with `wc -l hypesocials/**/*.py`. Wave 1 ended at 3,919, Wave 2 at 7,868; escalation past the ceiling stays an operator decision, never silent cuts.

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

**Subprocess timeouts:** MCP server startup `mcp_startup_timeout_s` (default 20 s), per-tool-call `mcp_call_timeout_s` (default 30 s), render job timeout `video_job_timeout_s` (default 300 s). Timeouts never resubmit — a timed-out job is a failed job (20-integrations §8).

**Run deadline:** `run_deadline_min` (default 25 min, measured on monotonic clock — never wall-clock, because sleep/NTP steps corrupt wall-clock timing). Soft ceiling; grace-poll aftermath may exceed it if the batch is already submitted.

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

- **Trend:** A ranked viral item from Virlo (video or slideshow) with metadata, reference images, and engagement stats.
- **Style brief:** LLM-written analysis of a trend's visual style (colors, layout, typography, hook pattern).
- **Hook pattern:** The structure/shape the copy follows (per trend), logged and tracked.
- **Anchor chaining:** Carousel slide 1 renders first, becomes primary reference for slides 2–N.
- **Seed frame:** GPT Image 2 render of the hook text (baked-in), used as both an asset and a Seedance reference.
- **Viral-video motion reference:** Trend's winning post video (yt-dlp download) uploaded to Kie, passed to Seedance for motion mimicry.
- **Both-mode A/B:** Each creative rendered two ways (analyzed + direct variants) sharing one trend and copy, paired by `pair_id` in gallery.
- **Brief / niche:** Small override file (message, visual directives) or config-file niche descriptor (audience, vibe, asset paths).
- **Wave-1 / Wave-2 renders:** Wave-1 = carousel anchor + reel seed frames (checked, referenced); Wave-2 = remaining slides/animation (submitted after wave-1 completes or pre-committed).
- **Permit gate:** 2-tier priority semaphore ensuring wave-2 work isn't starved by queued wave-1 jobs.
- **Run deadline:** Soft elapsed-time ceiling (default 25 min, monotonic clock).

---

**Last updated:** 2026-08-09 (Wave 0, task T0.1)
