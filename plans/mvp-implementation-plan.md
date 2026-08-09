# HypeSocials MVP — Implementation Plan (Phase 1)

**Status:** REVIEWED (architect + python/async + PRD-coverage panels applied) · **Source of truth:** `prds/00-overview.md` … `prds/50-promptcraft.md` (v1.6.2)
**Goal:** Full MVP per PRD. Line budget: honest estimate ~4,100–4,400 production Python vs **hard ceiling 4,500 (G2)** — tracked at every wave barrier (`wc -l`), levers pre-committed (§1a).
**Execution model:** flat-wave conductor dispatch per `CODING_GUIDELINES.md` §21. Operator decisions: minimal deterministic test suite (money/logic math), repo docs authored in Wave 0, day-one paid spikes (~$1–2) auto-run from `.env`.

**Standing child-prompt preamble (every spawn, every level):** (1) read `CODING_GUIDELINES.md` in full; (2) model/effort policy per `CLAUDE.md` §9 — never pass a `model` param at spawn; (3) subagent output contract — conclusion first, bullets, `path:line`, no preamble; (4) read this plan file and the named PRD files fully.

---

## 0. North-star flow (BINDING)

The PRD artifact's §1 flow diagram (https://claude.ai/code/artifact/3e6f5746-87d4-4aee-be7d-eb1b5f4546bc, identical to the mermaid in `prds/00-overview.md`) is the canonical run shape. Runtime stage order must match it exactly; each node maps to one owner module:

| Diagram node | Module | Built in |
|---|---|---|
| IN: Virlo trends via MCP | `sources/virlo.py` + `virlo_mcp/` | W1/W2 |
| IN: Inspiration folder (optional) | `sources/inspiration.py` | W5 |
| IN: Notion (optional) | `sources/notion.py` | W5 |
| IN: Config (counts, language, cap) | `config.py` + `cli.py` | W1/W3 |
| Cost estimate (nothing billed) → Confirm? gate; "no" → exit $0 | `budget.estimate()` + `cli.py` confirm | W2/W3 |
| Rank + pick trends (usability filter, history window, affinity) | `plan.py` (+ `sources` strength) | W2 |
| "nothing usable" → Abort + log (brief-only carve-out) | `runner.py` exit-3 path | W3/W5 |
| ANALYZE: Style brief (Sonnet vision) | `analyze.py` | W2 |
| ANALYZE: Copywriting (Luna; direct mode skips brief) | `copywrite.py` | W2 |
| CREATE: IMAGES → GPT Image 2 + 2–3 real trend refs | `generate/__init__.py` | W3 |
| CREATE: CAROUSELS → slide 1 first + checked, 2–N copy template | `generate/carousel.py` | W4 |
| CREATE: REELS → seed frame + winning-video motion ref + native audio | `generate/reel.py` + `video_ref.py` | W4 |
| Vision check (optional) → 1 retry shorter text → ship either way | `vision_check.py` | W3 (module) / W4 (wiring) |
| OUT: creatives / gallery.html / meta.yaml / summary + logs + history | `outputs/` | W1/W2/W3 |

Diagram caveats carried verbatim (00-overview): chained-artifact checks run *inside* Create (anchor before slides 2–N; seed frame before Seedance); finished videos never vision-checked; renders submit in at most two dependency waves. Money moves only after the Confirm gate; nothing downstream blocks the batch. **Any implementation choice that reorders, merges, or re-gates these stages is a PRD conflict — stop and escalate (guidelines §1).**

---

## 1. Target architecture

Feature-first, deep modules, one seam per external system. All I/O async (`httpx`, `asyncio`), Windows workstation, no DB, state = files. **Event loop: `ProactorEventLoop` (mandatory — subprocess support on Windows). SIGINT via `signal.signal` + `loop.call_soon_threadsafe`; `loop.add_signal_handler` is unavailable on Windows and must never be attempted.**

```
hypesocials/
  __main__.py          # entry: dispatch CLI action (run / previews / list-monitors / publish stub)
  cli.py               # argparse flag parsing ONLY (FR-61–66) + confirm prompt + FR-252 routing table
  menu.py              # hand-rolled 7-step interactive wizard (FR-56–60, 135–137, NFR-16) — argparse ≠ menu;
                       #   fidelity-rating prompt (FR-232, interactive only)
  models.py            # SHARED CONTRACTS (W1 barrier artifact): TrendItem, PlanEntry (order, pair_id,
                       #   atomic-group, status enum), StyleBrief, CopySet, AssetRecord, degradations tag
                       #   enum (FR-73 vocabulary — single source), briefs.load() signature stub
  config.py            # YAML load + defaults + one-line errors (FR-50/51/69, NFR-15/19), price table (FR-258),
                       #   notion per-context char-budget key (FR-124; name conductor-approved, D15 note),
                       #   inert postiz:/mcp_servers.postiz entries (FR-176/130)
  preflight.py         # secrets (FR-45/46/47), profile+template-set refusal (FR-281/263), disk probe (FR-255),
                       #   duration clamp (FR-103), brief resolution, cap floor, conditional Node/npx check
                       #   (FR-117/138), Czech vision_check hint (30 §2); exit-code-2 producer
  plan.py              # Select: usability filter + text_only flag (FR-6), history window + verdicts
                       #   eligible/excluded/unusable (FR-7, feeds FR-139), ranking consume + assignment +
                       #   affinity (FR-5/8/90); expansion (FR-1/2/3/143) with brief entries emitted FIRST
  budget.py            # estimator (FR-107 — every conditional contributor; NFR-18), price-provenance +
                       #   unpriced lines display data (FR-282), atomic reserve/reconcile lock (FR-106),
                       #   reverse-plan trim, tally-on-submission, summary data (FR-84/85)
  sources/
    __init__.py        # adapter contract re-exports (FR-121)
    virlo.py           # MCP tool calls via session pool, trend-item join rule, strength score,
                       #   per-image CDN download (FR-32/33/247)
    inspiration.py     # (W5) local folders, inspiration_mix set assembly (FR-91/D13)
    notion.py          # (W5) brand context fetch + truncation (FR-34/35/36/124)
  virlo_mcp/
    __main__.py, server.py  # 5-tool stdio MCP server, official Python SDK (FR-118/119/245)
  llm.py               # OpenRouter REST. PUBLIC CONTRACT (schema-agnostic): structured_call(role, messages,
                       #   json_schema, images=None) -> ParsedResult — strict schema + tolerant parse +
                       #   truncation retry + 402-run-condition inside; LLM semaphore
                       #   (max_inflight_llm_calls) lives HERE (FR-39–41, 125–129, 248)
  analyze.py           # style briefs per trend (FR-9–12, 92, 93, 147)
  copywrite.py         # Luna copy, group-split fallback, structural mimicry, word-boundary trim
                       #   (FR-99/100/101, 13–16, 146)
  prompts_engine.py    # 3-level template resolution (FR-174/262), {{placeholder}} substitution, secret-free
                       #   context object (FR-261), FR-102 delimiter insertion, unresolved=fail (FR-260),
                       #   name+hash logging (FR-184), built-ins (FR-183), template-set validator (FR-263)
  render/
    __init__.py        # DEEP public API: await render.run(profile, params, refs) -> RenderOutcome —
                       #   submit→poll→classify→result inside ONE call; priority permit allocator
                       #   (wave-2 acquisitions served before queued wave-1 — plain Semaphore is
                       #   INSUFFICIENT, FIFO starves wave-2; small custom 2-tier gate ~50 lines);
                       #   4-op provider protocol stays internal (FR-271); 3-outcome classification (FR-242)
    kie.py             # createTask/recordInfo, 5 poll states, monotonic timing (FR-243), widening interval,
                       #   poll-failure-never-terminal, upload_file, 402/429 (FR-42–44, 167)
    profiles.py        # declarative: gpt-image-2 (2-route split FR-241) + seedance-2-5 (FR-272);
                       #   param mapping, reference limits, template-set name
  generate/
    __init__.py        # W3: wave-1 path (images) via render.run, moderation fallback (FR-97), local-ref
                       #   upload (FR-200), prompt assembly calls (FR-17/94/96).
                       #   W4 extension: two-wave engine, wave-1 projection / wave-2 pre-commit /
                       #   discretionary reservation (FR-106 a/b/c) — anchor-fallback N+1 slides are
                       #   PRE-COMMITTED work (bypass discretionary path); FR-105 ordering wiring
    carousel.py        # anchor chain (FR-20/95): slide1 → vision_check → slides 2–N template-locked
    reel.py            # seed-frame chain (FR-24) + seed_frame.jpg byte download for packager/gallery
                       #   poster (FR-72/76); Seedance params (FR-23/103, 8a)
    video_ref.py       # yt-dlp probe→qualify→download→upload (FR-142, 160–163); owns scratch dir
                       #   (FR-249); suppressed entirely under preview modes (FR-139/140)
  vision_check.py      # (W3 module) native-res inputs, per-deck multi-image call, −40% retry,
                       #   4-state verdicts (FR-27/105); callers: generate/, carousel.py, reel.py
  briefs.py            # (W5) brief file loading/validation per models.py stub signature (FR-172, D26)
  outputs/
    __init__.py        # facade (T1.2 owner; T2.5 append-only)
    logwriter.py       # single serialized writer: run.log + events.jsonl, per-event flush, redaction
                       #   boundary (FR-77–81, 152, NFR-23)
    packager.py        # run/asset folders, asset_id scheme, meta.yaml pending→terminal via
                       #   update_meta()/set_marker() mutators (Phase 2 reuses them), SKIP_REASON.txt,
                       #   caption.txt, refs/ (FR-70–74, 230, NFR-21)
    gallery.py         # self-contained incremental gallery.html (single template string), badges from
                       #   models.py enum, pair_id A/B + pair-integrity badge, header documents
                       #   SELECTED.marker/publish.txt (FR-75/76/150/231, NFR-22)
    state.py           # trend_history (lock+prune FR-82/83), latest.txt canonical + junction via
                       #   `mklink /J` subprocess — NEVER os.symlink (admin/DevMode trap) (NFR-20, FR-254),
                       #   LEDGER.txt append-only (FR-203)
  mcp_client.py        # shared async MCP client: .cmd-shim-safe launch, Windows job objects (pywin32),
                       #   per-server env dicts, startup vs call timeouts, bounded pool (FR-30/31, 110–117, 246)
  runner.py            # lifecycle conductor: stage sequencing, post-confirm honesty restatement (FR-8/30 §4),
                       #   spend summary rendering (FR-84/85/232 + exit code line), two-stage Ctrl+C
                       #   (signal.signal + call_soon_threadsafe; FR-201), deadline + grace poll (FR-108),
                       #   exit codes incl. brief-only carve-out (FR-202), scratch cleanup on every exit
                       #   path (FR-249), preview prefixes (FR-139/140/253), video_ref.prefetch() launch
  util.py              # atomic temp+rename, UTF-8 open helper (FR-256), monotonic timers, slugify, run_id
```

Support trees (`virlo_mcp` counts toward G2 per NFR-110; the rest don't): `run.bat` · `configs/` · `prompts/` · `niches/hypedigitaly/` · `tests/` · `spikes/` (never imported by production code; retired after W1) · `CLAUDE.md`, `NAVIGATION.md`, `plans/`.

### 1a. Line budget (honest estimate ~4,150 · hard ceiling 4,500)

| Area | Est. |
|---|---|
| cli + menu + preflight + config | 850 |
| plan + budget | 700 |
| sources(virlo) + virlo_mcp + mcp_client | 700 |
| llm + analyze + copywrite + prompts_engine | 750 |
| render (seam + kie + profiles + permit gate) | 400 |
| generate (waves/carousel/reel/video_ref) + vision_check | 750 |
| outputs + runner + util + models | 1000 |
| notion + inspiration + briefs (W5) | 300 |
| **Total** | **~4,450 worst case → drive to ≤4,300** |

`wc -l hypesocials/**/*.py` is a **barrier command at every wave**. Pre-committed levers, in order, that do NOT reverse operator keeps: (1) deep `render.run()` already designed in (−~120 vs naive); (2) gallery as one template string; (3) merge `analyze.py`+`copywrite.py` into one `content.py`; (4) **last resort, requires D21 amendment per D15:** swap `virlo_mcp/` wrapper for the official Virlo MCP server via config (−250–350).

Dependencies (pinned; guidelines §13 approval given here): `httpx`, `pyyaml`, `mcp`, `yt-dlp` (routine-bump policy NFR-160), `Pillow` (FR-93 downscale ONLY, NFR-25), `python-dotenv`, **`pywin32` (job objects FR-111 — `win32job`; approved now to avoid a mid-task dependency wall)**. stdlib `argparse` for flags; the menu is a separate hand-rolled `input()` wizard (argparse cannot and need not build it).

---

## 2. Waves

### WAVE 0 — Docs + scaffold (shape: a-flat, 2 parallel leaves)

| Task | Owner | Path set |
|---|---|---|
| T0.1 `CLAUDE.md` (incl. §9 model policy + §9a — **quote the three flat-wave triggers verbatim from CODING_GUIDELINES.md §21**, no paraphrase; resolve `prd/`→`prds/` mismatch) + `NAVIGATION.md` | technical-writer | `CLAUDE.md`, `NAVIGATION.md` |
| T0.2 Scaffold: `pyproject.toml` (pinned deps incl. pywin32), `run.bat` (FR-53/54/55/256), `.gitignore`, `.env.example`, `hypesocials/__init__.py`, `tests/` skeleton | python-pro | `pyproject.toml`, `run.bat`, `.gitignore`, `.env.example`, `hypesocials/__init__.py`, `tests/` |

**Barrier:** venv bootstraps; `python -c "import hypesocials"`.

### WAVE 1 — Contracts, then infrastructure + spikes (shape: b — §9a trigger (b): 6 python-domain tasks → one python-pro orchestrating parent for T0.3+T1.1–T1.5; T1.6 direct)

**W1a (sequential, FIRST — shared-dependency barrier per §21):**

| Task | Owner | Path set |
|---|---|---|
| T1.0 `models.py` + pinned contracts: all shared types + degradations enum; `llm.structured_call()` signature; `render.run()` signature + 2-tier permit gate spec; `briefs.load()` stub; template-set naming `prompts/<profile>/<role>.md` + placeholder vocabulary (from 50-promptcraft FR-181/182) | python-pro (single) | `hypesocials/models.py` |

**W1b (parallel fan-out):**

| Task | Leaf | Path set | Spike-dependent? |
|---|---|---|---|
| T0.3 Day-one spikes (auto-run, ~$1–2): `spikes/day_one.py` + execute. Settles: OQ-17 residual (refs honored), OQ-2 (one 5 s 720p Seedance render → measured price), OQ-21 (image+video refs in one job), OQ-22 (Luna strict schema), **mkv upload spot-check (20 §8b)**, Virlo 5-endpoint + `list_monitors` live smoke (**record real monitor ids → RESULTS.md for W3 live run**), OQ-19/OQ-20 notes, **$0 Windows signal spike: ProactorEventLoop + subprocess + double-SIGINT delivery via signal.signal** | python-pro (Bash) | `spikes/` | — |
| T1.1 `config.py` + `configs/default.yaml` (**reel_second stays `null` + OQ-2 comment — FR-258 is unconditional**) + `configs/hypedigitaly.yaml` (niche block; **measured reel price goes HERE**) + FR-124 char-budget key + inert postiz entries | python-pro | `hypesocials/config.py`, `configs/` | reads RESULTS at finalization |
| T1.2 `util.py` + `outputs/__init__.py` facade + `logwriter.py` + `state.py` (junction via `mklink /J`) | python-pro | those 4 files | no |
| T1.3 `render/` (deep `run()`, permit gate, kie, profiles) | python-pro | `hypesocials/render/` | reads RESULTS (param shapes) |
| T1.4 `llm.py` (schema-agnostic contract per T1.0; LLM semaphore inside) | python-pro | `hypesocials/llm.py` | reads RESULTS (OQ-22) |
| T1.5 `mcp_client.py` + `virlo_mcp/` | python-pro | `hypesocials/mcp_client.py`, `hypesocials/virlo_mcp/` | endpoint smoke cross-check |
| T1.6 All 9 prompt templates per 50-promptcraft playbooks incl. **FR-102 data-not-instruction delimiters** in `style_brief_system.md`/`copywriter_system.md` | prompt-engineer | `prompts/` | no |

**Barrier:** imports clean; wrapper starts + lists 5 tools; logwriter round-trip; **`prompts_engine` spec + T1.0 contracts reviewed and accepted by a python-pro before W2**; spike RESULTS.md complete — **spike failure on refs/Seedance = STOP, PRD amendment path (D15)**; `wc -l` checkpoint. Spike code marked retired.

### WAVE 2 — Pipeline stages (shape: a-flat — 5 disjoint leaves dispatched directly; no parent, decomposition known)

| Task | Leaf | Path set |
|---|---|---|
| T2.1 `sources/__init__.py` + `sources/virlo.py` ONLY (notion/inspiration are W5) | python-pro | those 2 files |
| T2.2 `plan.py`: FR-6 usability filter + `text_only`, FR-7 history verdicts (eligible/excluded(date)/unusable(reason)), expansion w/ brief entries first, affinity assignment + **`tests/test_plan.py`** (worked-example FR-1 test, compound trim-order input) | python-pro | `hypesocials/plan.py`, `tests/test_plan.py` |
| T2.3 `budget.py`: estimator with **one named test per FR-107 bullet**, FR-282 provenance/unpriced data, reserve/reconcile + **asyncio race test (N concurrent reservations vs small cap) IN THIS WAVE'S barrier**, reverse-plan trim + compound trim test + **`tests/test_budget.py`** | python-pro | `hypesocials/budget.py`, `tests/test_budget.py` |
| T2.4 `analyze.py` + `copywrite.py` + `prompts_engine.py` (FR-102 delimiter insertion at fill time; FR-263 validator; template hashes) | python-pro | those 3 files |
| T2.5 `outputs/packager.py` (+ `update_meta`/`set_marker` mutators) + `outputs/gallery.py` (header documents SELECTED.marker/publish.txt; badges from models enum) | python-pro | those 2 files |

**Barrier:** full pytest green (plan/budget suites); `wc -l`; NAVIGATION.md updated.

### WAVE 3 — Walking skeleton (shape: a-flat, 2 disjoint leaves)

| Task | Owner | Path set |
|---|---|---|
| T3.1 Integration (single owner, owns aggregating files): `runner.py`, `preflight.py` (incl. Czech hint, Node/npx conditional, FR-263 call), `cli.py` (argparse + confirm + FR-252 routing + **`--publish`/`--promote` 3-line placeholders**), `__main__.py`, `generate/__init__.py` **wave-1 scope** (images via `render.run`, moderation fallback, local-ref upload); FR-84/85 spend summary renderer + FR-232 summary line; FR-282 provenance print before confirm; post-confirm honesty restatement; `--list-monitors` action (needed NOW for live runs); basic SIGINT-safe packaging; scratch-cleanup hook | python-pro (single) | `hypesocials/runner.py`, `preflight.py`, `cli.py`, `__main__.py`, `generate/__init__.py` |
| T3.2 `vision_check.py` module (pure; callers wired in W4) | python-pro | `hypesocials/vision_check.py` |

**Barrier (M1 — first real creatives):** live run `run.bat --config hypedigitaly.yaml --images 2 --carousels 0 --reels 0 --yes --budget 1` → exit 0/1; folder holds images + captions + meta.yaml + gallery + logs; spend ≈ estimate; no orphan subprocesses in Task Manager; `wc -l`.

### WAVE 4 — Full formats + lifecycle (shape: a-flat, 2 parallel leaves, then 1 integrator)

Parallel:

| Task | Leaf | Path set |
|---|---|---|
| T4.1 `generate/carousel.py` (anchor chain; calls `vision_check` before slides 2–N) | python-pro | that file |
| T4.2 `generate/reel.py` + `generate/video_ref.py` (seed-frame chain + **seed_frame.jpg byte download for packager/gallery poster**; scratch dir owner; **preview-mode gate honored — no yt-dlp/Kie activity in previews**) | python-pro | those 2 files |

Then single owner:

| Task | Owner | Path set |
|---|---|---|
| T4.3 Wave-engine integration: two-wave submission with **priority permit gate (wave-2 before queued wave-1 — named starvation test required)**; wave-1 projection / wave-2 pre-commit / discretionary reservation (FR-106 a/b/c) with **anchor-fallback N+1 slides explicitly PRE-COMMITTED (never discretionary)**; FR-105 ordering (anchor checked pre-deck; seed frame checked pre-chain); two-stage Ctrl+C (`signal.signal` + `call_soon_threadsafe`, verified against T0.3 signal-spike findings); deadline + ~30 s grace poll; ledger wiring; both-mode pairs (FR-3/22); FR-249 cleanup on every exit path | python-pro (single) | `hypesocials/generate/__init__.py`, `runner.py` edits, `budget.py` edits |

**Barrier (M2):** live run 1 image + 1 carousel (+1 reel if priced in hypedigitaly.yaml); Ctrl+C mid-run → packaged, exit 4; tiny-deadline run abandons honestly with ledger entries; **named tests green: permit starvation (wave-2 vs late wave-1), reservation race, FR-105 ordering**; `wc -l`.

### WAVE 5 — Full surface (shape: a-flat, 5 pure-module leaves — **no child touches cli/runner/preflight**), then single-writer wiring

| Task | Leaf | Path set |
|---|---|---|
| T5.1 `menu.py` pure module (FR-56–60, **135/136/137**, NFR-16; fidelity-rating prompt FR-232, suppressed under `--yes`) | python-pro | `hypesocials/menu.py` |
| T5.2 Preview implementations as `runner`-callable functions in own module (FR-139/140/253; video-ref suppression flag; log-only folders never repoint latest) | python-pro | `hypesocials/previews.py` |
| T5.3 `briefs.py` loader (models.py stub signature) + `niches/hypedigitaly/` assets incl. `briefs/ai-audit-cta/` (v1.5.1) | python-pro | `hypesocials/briefs.py`, `niches/` |
| T5.4 `sources/notion.py` + `sources/inspiration.py` (full paths: influence tiers, truncation, mix) | python-pro | those 2 files |
| T5.5 Test completion: **exit-code decision-function unit test (all 5 codes + brief-only edge)**, config load/malformed, slug/asset_id, ledger format, redaction | test-automator | `tests/` |

Then:

| Task | Owner | Path set |
|---|---|---|
| T5.6 Single-writer wiring (conductor or one python-pro): menu/previews/briefs/notion into `cli.py`/`runner.py`/`preflight.py`; FR-252 rows routed to their four executors; **brief-only run carve-outs** (no Virlo session for pure-override plans; exit 3/1/0 logic per 10 §10) | python-pro (single) | `hypesocials/cli.py`, `runner.py`, `preflight.py` |

**Barrier:** menu walkthrough; `--preview-sources` shows verdicts at $0 model spend; brief run produces badged creatives; brief-only run opens no Virlo session; full pytest green; `wc -l`.

### WAVE 6 — Hardening + verification (shape: a-flat)

| Task | Owner | Path set |
|---|---|---|
| T6.1 FR-coverage audit vs all PRD FR tables; fixes by python-pro | code-reviewer + python-pro | read-all, targeted fixes |
| T6.2 Final `wc -l` vs 4,500 (apply levers if over), NAVIGATION.md final, README quickstart, final live `--mode both` A/B run, operator handoff | python-pro | docs + misc |

**Barrier (MVP DONE):** PRD Build-Time Verification items 1–6, 13–15 closed/logged; exit-code matrix test green; two archived live runs (interactive + `--yes`).

---

## 3. Aggregating files (single-writer-LAST registry)

| File | Owner | Notes |
|---|---|---|
| `cli.py`, `runner.py`, `preflight.py`, `__main__.py` | T3.1 creates → T4.3 edits (runner) → **T5.6 sole W5 writer** | never touched by W5 leaves |
| `generate/__init__.py` | **T3.1 creates (wave-1 scope); T4.3 extends** | |
| `budget.py` | T2.3 creates; T4.3 edits | registered here per single-writer discipline |
| `llm.py` | T1.4; schema-agnostic — later schema needs go in callers, not here | |
| `models.py` | T1.0; additions via conductor only | |
| `outputs/__init__.py` | T1.2 owner; T2.5 append-only | |
| `pyproject.toml` | T0.2; dep changes via conductor | |
| `configs/default.yaml` | T1.1; later edits via conductor; reel price NEVER here | |
| `NAVIGATION.md` | T0.1; **updated at every wave barrier**, final T6.2 | |

## 4. Wire-in registry

- `sources.fetch()` ← `runner.py` Collect (T3.1)
- `plan.select()/build_plan()/assign()` ← `runner.py` (T3.1); verdicts also ← `previews.py` (T5.2)
- `budget.estimate()/reserve()/reconcile()/trim()` ← `cli.py` confirm + `generate/__init__.py` (T3.1/T4.3)
- `analyze.style_briefs()` / `copywrite.write_copy()` ← `runner.py` (T3.1)
- `prompts_engine.assemble()` ← `generate/*` AND `analyze.py`/`copywrite.py` (D24)
- `render.run()` / `render.upload_file()` ← `generate/*`, `video_ref.py`
- `vision_check.check()` ← `generate/__init__.py`, `carousel.py`, `reel.py` (T4.3 wiring)
- `video_ref.prefetch()` ← `runner.py`, launched alongside Analyze (D23)
- `outputs.*` facade ← `runner.py`; `packager.update_meta()/set_marker()` also ← Phase 2 `publishing/`
- `menu.run_menu()`, `previews.*`, `briefs.load()`, `notion` ← wired ONLY by T5.6
- `state.resolve_latest()` ← Phase 2 `--publish latest`
- Virlo wrapper ← `mcp_client` spawn from `mcp_servers.virlo` config

## 5. Risks & mitigations

1. **Spike failure** (refs ignored / Seedance combo rejected) — STOP after W1; D15 amendment before Generate work.
2. **Line budget** — honest ~4,150 estimate near ceiling; `wc -l` at every barrier; levers §1a (only #4 needs a PRD amendment).
3. **Permit starvation/deadlock** — 2-tier priority gate designed in (§1 render/); named starvation + race tests are W4 barrier items, not aspirations.
4. **Windows signals** — mechanism pinned (`signal.signal` + `call_soon_threadsafe` on Proactor loop) and $0-verified in T0.3 before T4.3 builds on it.
5. **Windows job objects** — pywin32 pre-approved; `mklink /J` for junctions, never `os.symlink`.
6. **API drift vs PRD facts** — RESULTS.md is authoritative; deviations surface via D15, never silently coded around.

## 6. PRD amendments expected

- FR-124 char-budget key name added to 30 §2 (conductor-approved) — record via D15 at W1.
- 40 §3 FR-76's dangling "FR-236" pointer → FR-231 (editorial, D15).
- Only if lever #4 fires: D21 amendment (wrapper → official Virlo MCP).
