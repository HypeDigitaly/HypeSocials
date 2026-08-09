# HypeSocials Phase 2 — Postiz Publishing Plan

**Status:** REVIEWED (panel findings applied) · **Source of truth:** `prds/60-publishing-postiz.md` (FR-210–229, NFR-210–214)
**Precondition:** MVP plan complete (run folders, `meta.yaml`, `caption.txt`, marker family, `latest.txt`, `packager.update_meta()/set_marker()` mutators all exist).
**Transport (settled):** REST-primary (`{base}/public/v1`, raw `Authorization: <key>` — NO Bearer prefix). MCP = optional ops-lookup seam only. Hosted cloud paid plan (FR-225).
**Line budget note:** G2's 4,500 ceiling is stated for the MVP engine (00-overview G2 wording includes the Virlo wrapper, not Phase 2). Phase 2's ~500 lines are tracked separately but reported in the same `wc -l` barrier output so the cumulative figure is always visible.

---

## 1. Architecture

One deep domain module — callers see one function; channel resolution, upload ordering, marker lifecycle, payload assembly, pacing and backoff are internal (guidelines §3a):

```
hypesocials/
  publishing/
    __init__.py        # public API: publish_run(run_id, *, promote=False, at=None) -> PublishSummary
                       #   (signature PINNED here — P1.1 and P2.1 build against it in parallel)
    postiz.py          # REST client: integrations/groups/upload/upload-from-url/posts/status; raw-key
                       #   auth; pacing delay (config key owned HERE, in the postiz: block); 429 backoff
                       #   via http_max_attempts (FR-224, NFR-213). ALL calls logged through
                       #   outputs.logwriter — same redaction boundary (NFR-212 / FR-152); never print raw bodies
    selector.py        # SELECTED.marker / publish.txt / all-packaged default; SKIP_REASON.txt excluded;
                       #   PUBLISHED.marker skip (FR-211/227). `latest` resolves via state.resolve_latest()
                       #   → output/latest.txt (canonical per NFR-20; FR-210's "latest/" wording → D15 editorial fix)
    payloads.py        # per-platform settings (FR-221 IG / FR-222 TikTok incl. 90-char title truncation +
                       #   video_made_with_ai / FR-223 LinkedIn carousel), full-payload defense (FR-220),
                       #   caption.txt verbatim (FR-230)
    markers.py         # PUBLISH_ATTEMPTED.marker → rename → PUBLISHED.marker (FR-215, guidelines §6).
                       #   NEVER opens meta.yaml or writes markers itself — calls
                       #   outputs.packager.update_meta()/set_marker() exclusively (single-writer invariant);
                       #   media ids cached via update_meta immediately after upload success (FR-227 table)
    slots.py           # next-free schedule slot per platform; store UTC, ISO 8601, --at override
                       #   (FR-218/219; guidelines §7 time rules)
```

Est. ~450–550 lines. MVP already ships `--publish`/`--promote`/`--at` CLI placeholders — this phase replaces the stubs.

Config: `postiz:` block per 60 §config (base_url_env, api_key_env, default_post_type=draft, auto_publish=false, channel_map with null integration_ids, schedule_slots, pacing delay). Never reintroduce `--force`, `--assets`, or auto-reconciliation (closed v1.6.1 decisions).

## 2. Waves

### WAVE P0 — Empirical gate (shape: a, 1 task)

| Task | Owner | Path set |
|---|---|---|
| P0.1 **OQ-10 key test (build-blocking):** live `GET /integrations` + `GET /groups` with the operator's hosted paid-plan key; record channels. Also: OQ-12 (one API-created draft shows approve/schedule affordance — visual check), OQ-13 (LinkedIn video caps via `integrationSchema`), OQ-14 (IG carousel ceiling as enforced), OQ-15 (TikTok DIRECT_POST vs UPLOAD audit status), **OQ-11 (does MCP `schedulePostTool.attachments` accept an external HTTPS URL — one call settles it; REST ships regardless)**, OQ-16 note (full-payload accepted on current version). Findings → `spikes/POSTIZ_RESULTS.md`. | python-pro (Bash) | `spikes/` |

**Barrier:** key works on the paid plan. Fails → STOP, operator decision. Any fact contradicting 60-publishing → D15 amendment before P1.

### WAVE P1 — Build (shape: a-flat, 2 parallel leaves against the pinned `publish_run` signature)

| Task | Leaf | Path set |
|---|---|---|
| P1.1 Entire `publishing/` module (architecture above) + `postiz:` config block in `config.py` + meta.yaml postiz keys via packager mutators (FR-88) + unit tests: selector (markers/publish.txt/default-all/skip-reason), payloads vs FR-221–223 incl. TikTok truncation, marker lifecycle idempotency, slots (UTC/ISO/`--at`) | python-pro | `hypesocials/publishing/`, `config.py` edit, `tests/test_publishing.py` |
| P1.2 CLI/menu wiring: replace `--publish <run_id|latest>` / `--promote` / `--at` stubs; menu "Publish a finished run" action; **`preflight.py`: missing `POSTIZ_API_KEY` → refusal naming the var (FR-226)**; per-asset summary + exit codes (FR-216/228/229) | python-pro | `hypesocials/cli.py`, `menu.py`, `runner.py`, `preflight.py` edits |

**Barrier:** pytest green; ruff clean; `wc -l` reported (cumulative visible).

### WAVE P2 — Live verification (shape: a, 1 task)

| Task | Owner | Path set |
|---|---|---|
| P2.1 Live end-to-end: publish one real MVP run as drafts (image + carousel; reel if TikTok channel connected); verify in Postiz UI; `--promote` one draft; confirm FR-220 full payload accepted (OQ-16), re-run idempotency (no duplicates), upload-fail retry reuses cached media ids, redacted logs | python-pro (Bash) | none (live test) |

**Barrier (Phase 2 DONE):** drafts visible + promotable; re-publish is a no-op; summary names every asset; NAVIGATION.md updated.

## 3. Aggregating files / wire-in

- `cli.py`/`menu.py`/`runner.py`/`preflight.py` — single owner P1.2.
- `publishing.publish_run()` ← `runner.py` publish action (P1.2), built against the §1-pinned signature.
- `outputs.packager.update_meta()/set_marker()` ← `publishing/markers.py` (never direct file writes).
- `outputs.logwriter` ← `publishing/postiz.py` (NFR-212 redaction).
- `state.resolve_latest()` ← `publishing/selector.py`.

## 4. Risks

1. **OQ-10 fails** — gated at P0, zero code written first.
2. **TikTok audit** forces `UPLOAD` inbox mode — config default flip, documented (OQ-15).
3. **API drift** — P0 findings authoritative; D15 amendment before P1.
4. **Second-writer regression on meta.yaml/markers** — forbidden by design (packager mutators only); reviewer checks it in P1 barrier.
