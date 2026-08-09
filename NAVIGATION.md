# NAVIGATION.md — HypeSocials Repository Orientation

## § 1. What This Repo Is

HypeSocials MVP (Phase 1): a single-operator Windows CLI tool that generates viral social media creatives (images, carousels, reels) from Virlo trends in ~3 min (images/carousels only) or ~8–10 min (with reels) for <$1 per post. **Status:** Waves 0–2 complete (docs, scaffold, shared contracts, infrastructure, prompt templates, day-one spikes, and the W2 pipeline stages: sources, plan, budget, analyze/copywrite/prompts engine, packager/gallery); Waves 3–6 follow per `plans/mvp-implementation-plan.md`. No database. All state is files.

---

## § 2. Doc Hierarchy

**Source of truth:** `prds/` folder (PRDs are authoritative per CODING_GUIDELINES.md §1)
- **prds/00-overview.md** — TL;DR, pipeline diagram, design decisions, OQ registry
- **prds/10-pipeline.md** — Run flow, decision logic, edge cases
- **prds/20-integrations.md** — MCP servers, OpenRouter, Kie.ai, render profiles
- **prds/30-configuration-and-run.md** — Config schema, CLI, run.bat, menu
- **prds/40-outputs-and-logging.md** — Folder structure, gallery, logs
- **prds/50-promptcraft.md** — Prompt playbooks, templates, per-model guides
- **prds/60-publishing-postiz.md** — Phase 2 publishing spec (not built yet)

**Governing docs:**
- **CODING_GUIDELINES.md** — Full code standards (§1 PRD authority, §18 quality, §21 subagents)
- **CLAUDE.md** — Project conductor guide (§9 model/effort policy, §9a flat-wave triggers)
- **NAVIGATION.md** (this file) — Repo orientation, read before exploring code

**Note:** CODING_GUIDELINES.md references `prd/` paths (e.g., `prd/_template.md`). In this repo, the PRD folder is **`prds/`** — every `prd/` reference means `prds/`.

---

## § 3. Directory Map

**Real (exists now):**
- `prds/` — PRD files (source of truth)
- `plans/` — Implementation plans and reviews
- `CODING_GUIDELINES.md` — Development standards
- `CLAUDE.md` — Project conductor config
- `Inspiration/` — Example reference images (optional source)
- `hypesocials/` — Production Python package. Built in W1: `models.py` (shared contracts), `util.py`, `config.py`, `llm.py`, `mcp_client.py`, `virlo_mcp/` (5-tool stdio MCP server), `outputs/` (logwriter, state), `render/` (seam, kie, profiles). Built in W2: `sources/` (facade + Virlo adapter, FR-91 reference-set builder), `plan.py` (select/build_plan/assign), `budget.py` (estimate/trim/Budget ledger), `analyze.py` + `copywrite.py` + `prompts_engine.py` (`PromptEngine`), `outputs/packager.py` + `outputs/gallery.py`
- `configs/` — Config YAML files (`default.yaml`, `hypedigitaly.yaml`)
- `prompts/` — Editable prompt templates (3 global flat + `gpt-image-2/` ×5 + `seedance-2-5/` ×1, plus operator README)
- `tests/` — W2 suites: `test_plan.py`, `test_budget.py` (incl. reservation race), `test_prompts_engine.py`, `test_copywrite.py`; completion in W5
- `spikes/` — Day-one spikes, **RETIRED** (never imported by production code); `spikes/RESULTS.md` is the authoritative record of live API findings + real monitor ids
- `run.bat` — Windows entry point (venv bootstrap + pinned Notion MCP install + `python -m hypesocials`)
- `pyproject.toml` — Python project config (pinned deps, pytest config)
- `.env` — Secrets (never committed; use `.env.example`)

**Planned (Wave N):**
- `hypesocials/` remaining pipeline modules **(W3–W5)** — generate/, vision_check, runner, cli, menu, preflight, previews, briefs, sources/notion + sources/inspiration
- `niches/hypedigitaly/` **(W5)** — Niche pack: Inspiration folder, briefs subdir, optional prompt overrides
- `logs/` — Runtime output (trend_history.json); created at first run
- `output/` — Per-run asset folders, gallery.html, meta.yaml files; created at first run

---

## § 4. Entry Points

**Launch:** `run.bat` (built, W0)
- Bootstraps venv, installs deps (incl. pinned Notion MCP server `@notionhq/notion-mcp-server@2.5.1` into repo-local `node_modules/` per FR-113; runtime uses `npx --no-install`)
- Runs `python -m hypesocials` with passed CLI flags or menu if no flags

**Main module:** `hypesocials/__main__.py` (planned W3)
- Dispatches CLI actions: `run` (default), `--preview-sources`, `--preview-analysis`, `--list-monitors`, stub `--publish` (Phase 2)
- Integrates `cli.py` flags + `menu.py` interactive wizard + `runner.py` orchestrator

**Pipeline not runnable yet** — `__main__.py`/`cli.py`/`runner.py` land in W3. Runnable now: the Virlo MCP wrapper (`python -m hypesocials.virlo_mcp`, stdio).

---

## § 5. Secrets & Environment

**Never commit secrets. Use `.env` file (git-ignored).**

| Key | Purpose | Example |
|---|---|---|
| `VIRLO_API_KEY` | Virlo REST auth (Bearer token) | `vrlo_...` |
| `KIE_API_KEY` | Kie.ai REST auth (Bearer token) | `key_...` |
| `OPENROUTER_API_KEY` | OpenRouter REST auth (Bearer token) | `sk-or-...` |
| `POSTIZ_API_KEY` | Postiz API key (Phase 2) | `pk_...` |
| `HANDLE_HASH_KEY` | Hash salt for anonymization | any string |
| `NOTION_TOKEN` | Notion MCP server token (optional) | `ntn_...` |

**Hygiene (D30):** Keys flow only into HTTP auth headers and per-server MCP env dicts. Never interpolated into prompts, LLM payloads, or logs. Redaction enforced in logwriter.py; full prompts logged only to events.jsonl, never run.log.

**Setup:** Copy `.env.example` to `.env`, fill in keys from your account dashboards (all confirmed ready per v1.6.2).

---

## § 6. Dev Commands

```bash
# Bootstrap venv (Windows PowerShell or Bash)
run.bat

# Run tests (after venv activated)
pytest tests/

# Line-count checkpoint (hard ceiling 10,000 per G2 v1.6.4)
wc -l hypesocials/**/*.py

# Import check (Wave 0 barrier)
python -c "import hypesocials"
```

All commands assume venv is activated or run via `run.bat`. No global Python calls.

---

## § 7. Environments

**Single Windows workstation only.** No Linux/macOS, no multi-user concurrency, no database.

- ProactorEventLoop (mandatory for Windows subprocess support)
- SIGINT via `signal.signal` + `call_soon_threadsafe` (never `add_signal_handler`)
- `mklink /J` for directory junctions (never `os.symlink`)
- `pywin32` job objects for subprocess tree cleanup (Windows-specific)
- No CI/CD integration; manual runs + Windows Task Scheduler `--yes` for unattended

---

## § 8. External Services

| Service | Protocol | Purpose | Config Key |
|---|---|---|---|
| Virlo | MCP stdio (in-repo wrapper) + REST | Fetch trends, videos, slideshows | `mcp_servers.virlo` |
| OpenRouter | REST (`/chat/completions`) | LLM calls (Luna, Sonnet, GPT Image 2 prompts) | `models.*` |
| Kie.ai | REST (createTask/recordInfo) | Image + reel rendering, file upload | `render.provider` |
| Notion | MCP stdio (package) | Brand context + influence (optional) | `mcp_servers.notion` |
| yt-dlp | Subprocess | Download trend videos for reel references | Python subprocess |

**No external DB. No webhooks.**

---

## § 9. State Files

| File | Purpose | Format | Lifecycle |
|---|---|---|---|
| `output/latest.txt` | Canonical run pointer (atomic temp+rename) | Text: run_id | Rewritten per run |
| `output/latest/` | Convenience junction to latest run folder | Symlink via `mklink /J` | Rewritten per run |
| `logs/trend_history.json` | Trend usage log (prevent reuse within 7 days) | JSON object keyed by trend key (FR-82) | Update + prune window |
| `output/<run_id>/<asset_id>/meta.yaml` | Per-asset metadata (AssetRecord field-for-field, FR-73) | YAML, pending→terminal via temp+rename | Terminal on success/skip |
| `output/<run_id>/<asset_id>/{caption.txt, SKIP_REASON.txt, SELECTED.marker}` | Publishing caption (hand-editable), skip cause, selection marker | Text / empty marker | Written by packager; caption never rewritten |
| `output/<run_id>/{gallery.html, refs/}` | Self-contained review gallery + downloaded reference media | HTML (one template string) / media files | Gallery rebuilt from disk per call (NFR-22) |
| `output/<run_id>/run.log` | Run summary (times, spend, errors; no secrets) | Text | Append per event |
| `output/<run_id>/events.jsonl` | Detailed per-API-call log (secrets redacted; full prompts logged here) | JSONL | Append per call |
| `configs/*.yaml` | Run config (formats, budget, language, niche, render models) | YAML | User-edited |

**All paths atomic; no partial writes exposed. No database transactions — file-based state with append-only ledger.**

---

## § 10. Common Tasks

### Add a config key
1. Edit `hypesocials/config.py` schema (T1.1)
2. Add to `configs/default.yaml` with default value
3. Load via `config.load_config()` (public API)
4. Document in `prds/30-configuration-and-run.md`

### Add a prompt template
1. Create `prompts/<filename>.md` (global templates: `style_brief_system.md`, `copywriter_system.md`, `vision_check_question.md`)
2. Or create `prompts/<profile>/<role>.md` for render-model-specific templates
3. Load via `prompts_engine.PromptEngine(...).render(role, context, ...)` (T2.4)
4. Document in `prds/50-promptcraft.md`

### Add a render model profile
1. Extend `hypesocials/render/profiles.py` (T1.3)
2. Define param mapping, reference limits, template-set name
3. Test via `render.run(profile=...)` 
4. Document route + params in `prds/20-integrations.md` (FR-270–279)

### Add a brief (campaign-override)
1. Create `niches/<niche>/briefs/<name>/` folder
2. Add `brief.yaml` (copy directives, visual directives, influence mode)
3. Optional: add reference images in `refs/`
4. Request via `--brief <name>:<count>` or menu picker (T5.6)

---

## § 11. Glossary & Key Terms

**Authoritative:** See CLAUDE.md Glossary section (full definitions). Quick reference:

- **Trend** — Ranked viral item from Virlo (video or slideshow) with winning images, text, engagement stats
- **Style brief** — LLM analysis of trend's visual style (colors, layout, typography, hook pattern)
- **Anchor chaining** — Carousel slide 1 renders first, becomes primary reference for slides 2–N
- **Seed frame** — GPT Image 2 render with text baked in; used as reel reference + asset
- **Viral-video motion reference** — Trend's winning video (yt-dlp download) passed to Seedance for motion mimicry
- **Both-mode** — A/B generation: each creative rendered analyzed + direct, paired by `pair_id` in gallery
- **Wave-1 / Wave-2** — Render submission waves: W1 = anchor + seed frames (checked, referenced); W2 = remaining slides/animation
- **Permit gate** — 2-tier priority semaphore preventing wave-2 starvation by queued wave-1 jobs
- **Run deadline** — Soft elapsed-time ceiling (default 25 min, monotonic clock)

---

**Last updated:** 2026-08-09 (Wave 2 barrier — §1, §3, §9, §10 updated)
**Updated at every wave barrier:** Mark affected sections (§1–§11) in session reports.
