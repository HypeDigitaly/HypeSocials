# NAVIGATION.md — HypeSocials Repository Orientation

## § 1. What This Repo Is

HypeSocials MVP (Phase 1): a single-operator Windows CLI tool that generates viral social media creatives (images, carousels, reels) from Virlo trends in ~3 min (images/carousels only) or ~8–10 min (with reels). **Status:** Waves 0–5 complete — W5 added the full operator surface: `menu.py` (interactive wizard, FR-28 over-cap offer, FR-232 fidelity rating), `previews.py` (FR-139/140 preview modes reusing runner's own stages per D19), `briefs.py` + `niches/hypedigitaly/briefs/ai-audit-cta/` (campaign briefs, FR-172), `sources/notion.py` (brand context, influence tiers) + `sources/inspiration.py` (D13 mix), the T5.6 wiring (brief-only runs open no Virlo session; FR-109 `full` brand-accent pass-through), and the W5 test completion (exit codes, config, ids, ledger, redaction). **M1 barrier passed 2026-08-09** (2/2 images, exit 0, $0.23); **M2 barrier passed 2026-08-09**. Reel pricing amended per D15 (PRD v1.6.6): `reel_second` is a worst-case-honest per-output-second scalar. **Wave 6 complete 2026-08-09 — MVP DONE:** full FR audit (~232 FRs, 5 auditors) closed by a 4-owner fix wave (image vision-check FR-27/105, FR-77 observability events, FR-252 honest exit codes, platform vocabulary FR-69, `--sources` flag FR-65, logwriter digest, `generate/refs.py` reference provenance); final interactive `--mode both` A/B run archived (`output/20260809_220436_wrfc`: 4/4 delivered, $0.72, 389 s, exit 0, pair-integrity badge live). Open D15 items compiled in `plans/d15-closeout-w6.md`. Operator acceptance matrix: `ACCEPTANCE.md`. No database. All state is files.

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
- `plans/` — Implementation plans and reviews; `plans/d15-closeout-w6.md` is the open-D15-items register for the operator
- `README.md` — Operator quickstart (W6): setup, FR-123 Notion page-share, reel pricing, Task Scheduler usage
- `ACCEPTANCE.md` — Operator final acceptance matrix (W6): 4 scenarios × 4 standard checks, exact commands
- `CODING_GUIDELINES.md` — Development standards
- `CLAUDE.md` — Project conductor config
- `Inspiration/` — Example reference images (optional source)
- `hypesocials/` — Production Python package. Built in W1: `models.py` (shared contracts), `util.py`, `config.py`, `llm.py`, `mcp_client.py`, `virlo_mcp/` (5-tool stdio MCP server), `outputs/` (logwriter, state), `render/` (seam, kie, profiles). Built in W2: `sources/` (facade + Virlo adapter, FR-91 reference-set builder), `plan.py` (select/build_plan/assign), `budget.py` (estimate/trim/Budget ledger), `analyze.py` + `copywrite.py` + `prompts_engine.py` (`PromptEngine`), `outputs/packager.py` + `outputs/gallery.py`. Built in W3: `cli.py` (argparse + Confirm gate + FR-252 routing), `preflight.py` (exit-2 producer), `runner.py` (lifecycle conductor), `__main__.py` (ProactorEventLoop + SIGINT dispatch), `generate/__init__.py` (wave-1 image generation), `vision_check.py` (pure module). Built in W4: `generate/carousel.py` (anchor chain FR-20/95, deck vision checks), `generate/reel.py` (seed-frame chain FR-24, Seedance clip, content-audit silent retry v1.6.6), `generate/video_ref.py` (yt-dlp probe→qualify→download→upload FR-160–163, scratch owner FR-249), `generate/__init__.py` extended (format dispatch, one `submit` money path FR-106 a/b/c, `GRACE_S` 30 s abandon path FR-108), estimator fidelity fixes in `budget.py` + `runner.py` (analysis per distinct assigned **(trend, reference group) pair** since 2026-08-11 — see Increment A below; truncation-retry allowances, `job_projection`). Built in W5: `menu.py` (wizard + `offer_reduced_plan` + `ask_fidelity_rating`), `previews.py` (calls runner's stage helpers directly — D19), `briefs.py` (`load`/`list_briefs` per the `models.BriefLoader` pin), `sources/notion.py` (`fetch_brand_context` → `BrandContext`) + `sources/inspiration.py` (`load_pool`/`apply_mix`), wiring in `__main__.py`/`runner.py`/`preflight.py` (real `resolve_briefs`, brief-only carve-out, notion/inspiration in Collect/Write/Create). Built in W6: `generate/refs.py` (reference provenance — trend/inspiration/brief role lines, per-job cap, reference-free marking), standalone-image vision check in `generate/__init__.py`, FR-77 observability events (`render/kie.py`, `mcp_client.py`, `sources/virlo.py`), `--sources` CLI flag, platform-vocabulary validation, UTF-8 + stale-scratch guards in `__main__.py`. Built in Wave 6.5: `wizard_help.md` (the `?` help text, read lazily by `menu.py` on first help request), `util.py` module-level `fit()` function (FR-286 width fitting for the menu picker and console output). Built in the topic-first pivot's W1 (2026-08-12, plan `plans/xmasterplan-topic-first-pivot.md`, contracts `plans/topic-first-pivot-contracts.md`): `styles.py` (meta-style registry — `load_registry`/`validate` FR-295, deterministic `assign_styles`/`assign_branding` rotation FR-290/291, reference-window picker, run-scoped `UploadMemo` seam; NOT WIRED until W2/W3) and `topic_filter.py` (batched competitor screen FR-294 — `screen()`/`apply_blocklist`, ordinal-keyed `Verdict`s, fail-open LLM layer over a fail-closed blocklist; `screen()`'s prompt path is stubbed until the W2 placeholder/allowlist pass); `models.py` gained `MetaStyle`/`SourcePost`/`CopySelection`/`LayoutZone.role`/`PlanEntry.style_key·branded·topic_key`/3 tags, `config.py` gained `branding:` (FR-292 two-profile schema) + `styles:` + `sources.virlo_topics_per_monitor` — all additive; legacy symbols excised in W3.5
- `logs/` — Runtime state (`trend_history.json`); real since the M1 run
- `output/` — Per-run asset folders + `latest.txt` + `latest/` junction; real since the M1 run
- `configs/` — Config YAML files (`default.yaml`, `hypedigitaly.yaml`)
- `prompts/` — Editable prompt templates (3 global flat + `gpt-image-2/` ×5 + `seedance-2-5/` ×1, plus operator README)
- `tests/` — W2 suites: `test_plan.py`, `test_budget.py` (incl. named reservation race), `test_prompts_engine.py`, `test_copywrite.py`; W4 suites: `test_carousel.py` + `test_reel.py` (named FR-105 ordering tests), `test_video_ref.py`, `test_render_gate.py` (named permit-starvation test), `test_generate_waves.py` (grace-abandon, money kinds); W5 completion: `test_exit_codes.py` (all 5 FR-202 codes + brief-only edges), `test_config.py`, `test_ids.py`, `test_ledger.py`, `test_redaction.py` (incl. one strict xfail documenting the known multi-line-digest defect in `logwriter._digest`, W6 fix); topic-first-pivot W1: `test_styles.py` + `test_topic_filter.py` (written against `plans/topic-first-pivot-contracts.md` items 5/6), `test_reference_rotation.py` DELETED (its whole-tree `% len(` policy scan predated `styles.py`; its one unrelated live check — the retry-token parity with `llm.py` — was re-homed into `test_budget.py`)
- `tests/fixtures/virlo/` — **Real Virlo response bodies captured 2026-08-11** (`/agents`, `/agents/{id}`, `/agents/{id}/trends/latest`, and videos + slideshows at `limit=100&order_by=views&sort=desc`), plus a README explaining what they prove. Captured because the Virlo trial expires ~2026-08-13; they are the offline corpus for developing and testing the remaining Increment A/B and copy-voice work with **no key, no network and no spend**. Nothing is redacted — a response body never carries the key (D30). The metered `/trends/digest` was deliberately never called
- `spikes/` — Day-one spikes, **RETIRED** (never imported by production code); `spikes/RESULTS.md` is the authoritative record of live API findings + real monitor ids
- `run.bat` — Windows entry point (venv bootstrap + pinned Notion MCP install + `python -m hypesocials`)
- `pyproject.toml` — Python project config (pinned deps, pytest config)
- `.env` — Secrets (never committed; use `.env.example`)

- `niches/hypedigitaly/` — Niche pack (real since W5): `briefs/ai-audit-cta/brief.yaml` (shipped campaign brief, `influence: override`)

---

## § 4. Entry Points

**Launch:** `run.bat` (built, W0)
- Bootstraps venv, installs deps (incl. pinned Notion MCP server `@notionhq/notion-mcp-server@2.5.1` into repo-local `node_modules/` per FR-113; runtime uses `npx --no-install`)
- Runs `python -m hypesocials` with passed CLI flags or menu if no flags

**Main module:** `hypesocials/__main__.py` (built, W3)
- Explicit `ProactorEventLoop` + `signal.signal`/`call_soon_threadsafe` SIGINT (spikes/RESULTS.md §F pattern)
- Dispatches CLI actions: `run` (default), `--list-monitors` (live), `--preview-sources`/`--preview-analysis` (live since W5, log-only folders), `--publish`/`--promote` (Phase-2 placeholders)
- A console-attached launch without `--yes` opens the `menu.py` wizard (W5) with any supplied flags pre-filling its prompts; the menu's Config travels into `runner.run(config=…)` so the FR-135 source pick survives. Since W6 the source pick has a CLI twin: `--sources <list>` (FR-65/135)

**Pipeline runnable since W3; all three formats since W4** — image/carousel/reel runs work end-to-end (M1: 2 images, exit 0; M2: `run.bat --config hypedigitaly.yaml --images 1 --carousels 1 --reels 1 --yes --budget 5`). Also runnable standalone: the Virlo MCP wrapper (`python -m hypesocials.virlo_mcp`, stdio).

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
| `POSTIZ_BASE_URL` | Postiz API base (Phase 2, optional; hosted default when unset) | `https://api.postiz.com/public/v1` |

**Hygiene (D30):** Keys flow only into HTTP auth headers and per-server MCP env dicts. Never interpolated into prompts, LLM payloads, or logs. Redaction enforced in logwriter.py; full prompts logged only to events.jsonl, never run.log.

**Setup:** Copy `.env.example` to `.env`, fill in keys from your account dashboards (all confirmed ready per v1.6.2).

---

## § 6. Dev Commands

```bash
# Bootstrap venv (Windows PowerShell or Bash)
run.bat

# Run tests (after venv activated)
pytest tests/

# Line-count checkpoint - measured and reported, NO ceiling (CLAUDE.md rule 5, v2.0.0)
# Use find, never `wc -l hypesocials/**/*.py`: globstar is off in this shell, so that
# glob counts ~20 of 39 files and misses everything at depth 3.
find hypesocials -name "*.py" | xargs wc -l | tail -1

# Per-file attribution for a barrier report
find hypesocials -name "*.py" | xargs wc -l | sort -rn | head -20

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

## § 9. CLI Flags & Pre-flight (FR-283–286)

**Entry points:** `run.bat` (default), `run.bat --quick` (skips config/source pickers, picks first runnable), `run.bat --config <name>`, `run.bat --list-monitors` (Virlo setup helper, $0), `run.bat --preview-sources` (trends + verdicts), `run.bat --preview-analysis` (with style briefs and copy).

**New flags (Wave 6):**
- `--quick` — Skips the config picker, source picker, and format pickers; selects the first runnable config automatically and goes straight to the cost estimate (still interactive, still requires approval). Mutually exclusive with `--yes`. Routes through the same menu action [2].
- `--history-days N` — Overrides the recency exclusion window for this run only. `0` disables the window. Any value outside the allowed range is refused at the flag boundary (before config load) with one line, never silently clamped — a typo is a user error, not a safety clamp (FR-285).
- `--sources <list>` — Selects the source(s) for this run (comma-separated), e.g. `--sources virlo`. Validates the list at the flag boundary, refusing unknown or unbuilt sources before any config load (FR-135).

**Pre-flight refusal (FR-283):** When `sources.active` contains `virlo` AND the action is a run (not `--list-monitors` or a preview) AND `sources.virlo_monitor_ids` is empty AND the plan contains at least one trend-dependent creative, the engine refuses before Collect with exit code 2, naming `virlo_monitor_ids` and directing to `--list-monitors`. A brief-only plan (all entries override-briefs) is never refused — it consumes no trend. A mixed brief+trend plan with no monitor ids produces only briefs with a warning and exit code 1.

**Help:** `run.bat --help` enumerates the real config names, marks Phase-2 flags as not implemented, and includes worked examples.

---

## § 10. State Files

| File | Purpose | Format | Lifecycle |
|---|---|---|---|
| `output/latest.txt` | Canonical run pointer (atomic temp+rename) | Text: run_id | Rewritten per run |
| `output/latest/` | Convenience junction to latest run folder | Symlink via `mklink /J` | Rewritten per run |
| `logs/trend_history.json` | Trend and post usage log (prevent reuse within 7 days per post) | JSON object keyed by trend key (FR-82); each entry has optional `posts` map (FR-153) | Update + prune window |
| `output/<run_id>/<asset_id>/meta.yaml` | Per-asset metadata (AssetRecord field-for-field, FR-73) | YAML, pending→terminal via temp+rename | Terminal on success/skip |
| `output/<run_id>/<asset_id>/{caption.txt, SKIP_REASON.txt, SELECTED.marker}` | Publishing caption (hand-editable), skip cause, selection marker | Text / empty marker | Written by packager; caption never rewritten |
| `output/<run_id>/{gallery.html, refs/}` | Self-contained review gallery + downloaded reference media | HTML (one template string) / media files | Gallery rebuilt from disk per call (NFR-22) |
| `output/<run_id>/run.log` | Run summary (times, spend, errors; no secrets) | Text | Append per event |
| `output/<run_id>/events.jsonl` | Detailed per-API-call log (secrets redacted; full prompts logged here) | JSONL | Append per call |
| `configs/*.yaml` | Run config (formats, budget, language, niche, render models) | YAML | User-edited |

**All paths atomic; no partial writes exposed. No database transactions — file-based state with append-only ledger.**

---

## § 11. Common Tasks

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

## § 12. Glossary & Key Terms

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

## § 13. Increment A — Virlo throughput and fidelity (2026-08-11)

Plan: `plans/xmasterplan-virlo-throughput-and-fidelity.md`. Session order: `plans/EXECUTION-ORDER.md`.
Three measured defects and their fixes, all landed in waves A0–A2:

- **The fetch was unsorted.** `sources/virlo.py` now asks for `order_by=views&sort=desc&limit=100`; the wrapper's `get_top_videos`/`get_top_slideshows` gained `page`/`order_by`/`sort` with **local enum validation** (a client typo is an FR-119 error, never an opaque upstream 400). **`offset` is structurally unsendable** — `virlo_mcp/server._get` screens every query key against an allowlist at the single exit to Virlo, because Virlo answers `offset` with a hard HTTP 400.
- **Every style brief ran out of tokens.** `models.max_tokens.analysis` 2000 → **12000**, floor 600 → **6000**. `llm.py` gained an output ceiling: the FR-127 widen is clamped, and when the clamp would leave `max_tokens` unchanged the retry would be *identical* — which FR-127 forbids — so the call fails fast with a reason instead of paying twice. `ParsedResult.reason` now carries an operator-facing cause on every degrade path.
- **~36 reference sets were downloaded and only the first ever attached.** FR-91 now **rotates per reuse**, and FR-9/FR-12 analyse one **(trend, reference group) pair**. The rotation modulo lives in exactly one place: `sources.reference_group_index()`. Briefs are keyed by `sources.brief_key()`; consumers go through `Env.brief_for(entry)`.

New/changed operator-visible surfaces: `max_trend_reuses_per_run` default **2 → 6**; `TrendItem` carries the source's own `hook_types`/`visual_hook_types`/`emotional_tones` and the winning posts' real `hashtags`; the metered digest's `top_exemplars[]` now enter as a **last-resort** reference tier logged `reference_source=digest_exemplar` (new event `digest_exemplar_attached`).

### Waves A2′–A3 (session 2): steering, visibility, and the plagiarism guardrails

- **The operator's levers reached nothing.** `{{brand_accent}}` was fully wired and **blank on every run ever made** — welded to a Notion path that has never executed one MCP call. `niche.brand.accent` / `niche.brand.product_nouns` now feed it as a **fallback beneath Notion** (`session.brand.accent or config.niche.brand.accent`) — Notion still wins when energised. `niche.visual_world` reaches render prompts through a new narrow, visual-only `{{niche_visual_world}}` on the four gpt-image-2 roles, ranked **below** the attached references; the wide `{{niche_descriptor}}` stays copy-side because it also names the AUDIENCE. Inspiration `.txt` files sitting beside images now reach the **copy call only**, via `{{inspiration_exemplars}}`.
- **Override-brief single images rendered with a blank subject.** `influence: override` forces `variant="direct"`, whose only subject slot was `{{content_sentence}}` — empty by construction when there is no trend. `image_direct.md` gained `{{render_prompt}}`.
- **The Virlo funnel was invisible.** `sources.virlo.Counters` accumulates every Collect stage into one run-wide rollup on `TrendFeed.counters`, emitted once as `collect_funnel` and printed by `runner._funnel_block()` **unconditionally** in three places (after Select, both previews, one row under FR-84's headline). `virlo_payload` reported pre-dedupe counts and **over-reported by 11 rows on a real run** — now post-dedupe. `kie_job_submitted` gains `reference_count`/`reference_sources`; every MCP call line carries a row count (FR-77).
- **The engine no longer reproduces the source's own words (A20 — operator mandate).** `copywrite._fallback_copy` used to set `headline` to the competitor's exact `hook_text` and `slide_texts` to the source deck's panels, straight into `{{onimage_text}}` — the block every render template calls *"the ONLY source of renderable words"*. It now ships a caption in our words and **no on-image text**, tagged `copy_degraded` + `no_onimage_text`. `hook_pattern_used` is **validated** against the bar `prompts/copywriter_system.md` states to the model (30 chars, 4 distinct content words, five rejected phrases), with one re-ask then a `hook_pattern_generic` tag.
- **The console shows the posts and the brief.** `Sources` after Select, `Brief` after Analyze, capped at 3 trends on a paid run and uncapped in previews; `AssetRecord.style_brief_summary` puts the brief on the gallery card.

New glossary terms: `no_onimage_text`, `hook_pattern_generic`, `inspiration_exemplars`, `collect_funnel`.

⚠️ **Two files are past §3a's ~500-line splitting threshold and both splits are blocked on path-set collisions with other plans:** `sources/virlo.py` at **1,186** lines (the designed `media.py` cache seam, plan §4.6 — note the `_CACHE_DIR` globals-alias trap documented there) and `copywrite.py` at **596** (a natural `degrade.py` cut). Neither is started; both are owed on design grounds, not arithmetic.

⚠️ **Known, deliberately unfixed** (found by the A3 test wave, recorded at `runner._funnel_block`): a brief-only plan prints the zero-material funnel sentence for a run where Virlo was never contacted. Cosmetic — the header already reads `0 monitor(s) asked` — and the clean fix is at the call site, not a `monitors_asked == 0` guard. Two further findings are recorded in the session report: funnel rows built as a single f-string clause **truncate rather than wrap at Increment-B scale**, and A24's `motion` row is narrower than the plan's design because `TrendItem` carries neither the motion post's freshness tier nor its view count.

---

**Last updated:** 2026-08-11 (Increment A waves A2′–A3, conductor — §13 extended; 522 tests green)
**Updated at every wave barrier:** Mark affected sections (§1–§12) in session reports.
