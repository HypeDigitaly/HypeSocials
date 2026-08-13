# 60 — Publishing via Postiz (Phase 2)

## TL;DR — Plain English

After you've reviewed the gallery and picked the creatives worth putting out into the world, one command sends them to Postiz — the tool that actually posts to LinkedIn, Instagram, and TikTok — as **drafts**. Postiz gets the images or video for each creative, uploaded and attached, plus the right caption for each platform. Nothing goes live automatically: you open Postiz, look the drafts over one more time, and hit publish (or schedule) yourself. There's a config switch that lets a trusted setup skip that manual step and auto-schedule instead, but it's off unless you deliberately turn it on. This is Phase 2 — it ships after the core engine (MVP) is working, and this file is the complete, build-ready spec for it, not a sketch.

- `--publish <run_id>` (or `--publish latest`, or a menu action) pushes a completed run's assets into Postiz.
- You can publish everything from a run, or just pick specific assets.
- Every asset lands in Postiz as a draft by default — a human always has the last look, unless auto-publish is switched on.
- Captions are per-platform, taken straight from each asset's `caption.txt`.
- The connection runs over Postiz's normal web API, not the newer "MCP" protocol Postiz also offers — research showed the MCP path can't upload media yet, so it isn't the right tool for the main job (still useful for small side-queries).
- Re-running `--publish` on the same run is safe: anything already pushed is skipped, not duplicated.
- With no assets selected, `--publish` pushes the **whole run** — deliberate: everything lands as drafts you review once more inside Postiz, so an unfiltered push is loud, never dangerous.
- One honest naming: a scheduled `--yes` generation run chained to a scheduled `--publish` with `auto_publish: true` is a **fully autonomous posting pipeline with zero human review**. Each piece is opt-in; the combination is blessed but should be chosen knowingly, not stumbled into.

**Requirement ranges owned by this file:** FR-210–FR-229, NFR-210–NFR-214 (NFR-211–NFR-213 defined; NFR-210 and NFR-214 reserved, unused)

---

## 1. The honest transport verdict

The original plan (**D1**) filed Postiz alongside Virlo and Notion as a "true MCP" content-service connection. Live research into Postiz's actual MCP server changed that plan, and this file amends it with evidence rather than silently drifting from D1.

Postiz's official MCP server (docs: `docs.postiz.com/mcp/introduction` and `…/mcp/setup`; endpoint `{backend}/mcp` over streamable HTTP, Bearer or key-in-URL auth — see 20-integrations §1a for the full reference table) exposes exactly **nine tools**: listing integrations and groups, reading a channel's settings schema, a generic "trigger tool" for automations, a schedule-post tool, and four tools around Postiz's own AI image/video generation. None of the nine is a media-upload tool, and the one tool that could plausibly carry our creatives — `schedulePostTool` — is documented and demonstrated only with media that Postiz itself generated inside the same session. There is no shown or documented path for handing it a locally-rendered image or video file.

Postiz's **public REST API**, by contrast, has exactly what's needed: a dedicated upload endpoint, an upload-from-URL endpoint, and a post-creation endpoint that accepts already-uploaded media by reference. This is the same API surface Postiz's own web app itself is built on.

**Conclusion: the publishing path runs over the public REST API, start to finish.** MCP is kept as an optional, secondary seam for things that don't need media — asking "which channels are connected?" in natural language, or letting an operator query Postiz state through a chat-style tool. It is not on the critical path of `--publish`. One item is left to verify at build time, not assumed: if `schedulePostTool`'s `attachments` field turns out to accept our own external HTTPS URLs (not just Postiz-generated media), the scheduling call itself could move to MCP later — worth a quick empirical test, but the REST path is the shipped design regardless of that outcome.

## 2. Publish flow (FR-210–FR-216)

**FR-210:** The engine SHALL support `--publish <run_id>`, `--publish latest` (resolves to the run behind `output/latest/`), and an equivalent menu action, each triggering the publish flow below against a completed run's asset folders.

**FR-211 (simplified v1.6.1):** Asset selection works as follows: **at publish time, the engine reads the run folder for** `SELECTED.marker` files (created by the operator during gallery review, after the run — 40-outputs-and-logging FR-231) and for asset IDs listed in `publish.txt` at the run root. `--publish` publishes exactly the selected set, or all successfully-packaged assets if no selection is marked (the blessed loud default — everything lands as drafts). The `--assets` filter was removed — the markers are the filter, and they cover the same need with zero flag-parsing code. Failed/skipped asset folders (those carrying a `SKIP_REASON.txt`, per 40-outputs-and-logging §2) are never offered or published.

**FR-212:** At the start of every publish run, the engine SHALL resolve channels by calling Postiz's `GET /integrations` and `GET /groups`, matching each configured platform to a connected channel by both its `identifier` (platform slug) and `name` — identifier alone is not unique when multiple accounts of the same platform are connected. The resolved integration ID SHALL be cached for the run and SHOULD be pinned in the config channel map (Section 7) once confirmed stable, so routine runs skip the lookup ambiguity entirely.

**FR-213** *(amended v2.1.0)*: For each selected asset, the engine SHALL upload the publishable media files before creating any post: **only** `slide_NN.*` files (carousels, in slide order), `image.*` (images), `reel.*` (reels), and `seed_frame.*` (as a cover image when the platform supports it). **The `source/` and `refs/` folders are never uploaded to Postiz** — they are gallery and analysis files, kept offline. Upload method: `POST /upload` (multipart) for each file, or `POST /upload-from-url` when a publicly reachable URL for that file already exists (preferred — avoids re-transferring bytes the engine already has hosted, e.g. a self-hosted Postiz instance's own storage reachable by URL). A carousel issues one upload call per slide in order; a reel issues one upload call for its single MP4; an image-only asset issues one call for `image.*`. Each successful upload returns a Postiz media reference (id + path) that the post-creation call then points to — raw file bytes are never inlined into the post-creation request.

**FR-214:** After all of an asset's media is uploaded, the engine SHALL call `POST /posts` to create it, with `type` defaulting to `"draft"` (Section 3), and one entry in the `posts[]` array per target platform for that asset — each entry carrying that platform's caption (read verbatim from the asset's `caption.txt`, per the file contract defined in 40-outputs-and-logging) and that platform's settings block (Section 5). The caption.txt file contains the caption body, a blank line, and platform-specific hashtag lines; the engine reads this structure exactly as written and honors any operator edits to the file verbatim. An asset only ever has one target platform in HypeSocials' model (platform is baked into `asset_id`, per 40-outputs-and-logging §1), so in practice this is a single `posts[]` entry, structured to match Postiz's per-platform array shape.

**FR-215 (simplified v1.6.1):** Publish idempotency is enforced by an intent-record pattern: before calling `POST /posts`, the engine SHALL write a `PUBLISH_ATTEMPTED.marker` file to the asset folder, containing a client-generated token and a timestamp. If the call succeeds, that marker is renamed to `PUBLISHED.marker` and the returned Postiz post id and state (`draft`, `schedule`, etc.) are written to `meta.yaml` (as `postiz_draft_id` and `postiz_state`, extending 40-outputs-and-logging FR-88 — `postiz_state` is the one canonical key name, owned by 40's meta.yaml schema). On a subsequent `--publish` run: assets with `PUBLISHED.marker` are skipped; assets with a lingering `PUBLISH_ATTEMPTED.marker` (call outcome unknown — response dropped or process crashed) are **reported, not auto-reconciled**: the summary names them and tells the operator to glance at the Postiz drafts list before re-running. The former automated GET-and-digest-match reconciliation was cut (operator decision): with draft-first publishing the worst outcome of a blind retry is a duplicate **draft** the operator deletes in two seconds inside Postiz, which does not justify ~100 lines of reconciliation code. If `auto_publish: true` is ever enabled, this trade-off should be revisited — a duplicate *scheduled* post is a real cost (noted in FR-219's warning).

**FR-216:** At the end of a publish run, the engine SHALL print and log a summary: assets pushed, assets skipped and why (Section 9), Postiz post ids created, and total wall-clock time — the same "degrade and report" posture as every other stage of HypeSocials.

## 3. Draft-first approval model (FR-217–FR-220)

**FR-217:** By default, every post the engine creates in Postiz SHALL be created with `type: "draft"`. A draft sits in the Postiz UI for the operator to open, review (caption, media, per-platform settings), and manually approve — publish immediately or pick a schedule time — inside Postiz itself. HypeSocials never assumes the operator's approval; it only prepares the material.

**FR-218:** The engine SHALL support `--promote <run_id>` (scoped by the same `SELECTED.marker`/`publish.txt` selection as FR-211 — `--assets` was removed in v1.6.1), which calls `PUT /posts/{id}/status` with `{"status": "schedule"}` for each already-created draft belonging to that run, flipping it from draft into Postiz's schedule queue. **The schedule date source is defined:** drafts are created without dates, so promote computes the **next free configured schedule slot per platform** (the same slot logic as FR-219) unless the operator passes `--at <ISO datetime>` for an explicit time (flag listed in 30-configuration's table). This is a deliberate, separate, explicitly-invoked command — never a side effect of `--publish` itself.

**FR-219:** A config flag `auto_publish` (default **false**) changes the behavior of FR-214: when true, the engine creates posts with `type: "schedule"` directly (skipping the draft stage) and a `date` computed from the configured per-platform schedule slots (Section 7) — the next free slot in the operator's configured rhythm (e.g. the next upcoming `09:00` or `18:00`, per platform). This flag is a deliberate opt-in for an operator who trusts the pipeline enough to skip the manual look — it does not exist in the MVP's design at all (Postiz shipped nothing then); Phase 2 makes it real but still off by default. **Named plainly:** combined with a scheduled `--yes` generation run and a scheduled `--publish`, `auto_publish: true` constitutes a fully autonomous posting pipeline in which AI content reaches real accounts with zero human review. The combination is permitted — the pieces exist precisely so it can be built — but it is an explicit, eyes-open configuration choice, never a default.

**FR-220:** Regardless of `type`, every `POST /posts` call SHALL send a fully-populated payload — `type`, `posts[]` with content and settings, and any other field Postiz's schema names as present-but-optional for a draft. This is a defensive rule, not an assumption: a documented community report (Postiz GitHub issue #717, opened April 2025, **now closed upstream** — verified 2026-08-09) showed real self-hosted instances rejecting drafts with HTTP 400 when only the "required for drafts" subset of fields is sent, even though the docs describe the rest as optional. The full-payload defense stays regardless — it is cheap insurance against the same class of doc/behavior drift recurring — and OQ-16's one-time re-check downgrades from "is this still broken" to "confirm the fix landed on the operator's instance".

## 4. Per-platform settings (FR-221–FR-223)

Each `posts[]` entry's `settings` block is platform-specific; defaults for each field live in the config channel map (Section 7) and can be overridden per run.

**FR-221 — Instagram.** `post_type` is `"post"` or `"story"`; there is no separate "reel" type — a reel is simply a `"post"` whose media is a single video file. A carousel is a `"post"` whose `image[]` array holds multiple items (Instagram's own platform ceiling is 2–10 slides; HypeSocials' carousel slide-count ceiling, per 30-configuration-and-run.md, SHOULD stay within that range so nothing is silently dropped at Instagram's side).

**FR-222 — TikTok.** Nearly every field in TikTok's settings block is required, not optional: `privacy_level` (e.g. public, followers-only, private), `duet`/`stitch`/`comment` permission booleans, `content_posting_method` (`DIRECT_POST` publishes straight to the account; `UPLOAD` drops it into the TikTok app's inbox for a manual 24-hour-window publish on-device — useful as a safety valve while a TikTok developer app is still pending platform review), and `title` (capped at 90 characters — captions longer than that are truncated for the title field only, with the full caption still living in the post content). The engine SHALL set `video_made_with_ai: true` by default. This is a deliberate honesty choice, not a hedge: HypeSocials' content genuinely is AI-generated end to end, and misrepresenting that on a platform-native disclosure field would contradict the project's own "no compliance theater, but no dishonesty either" posture. Because TikTok requires publicly reachable HTTPS media, the pre-upload step (FR-213) is mandatory for TikTok, not merely convenient.

**FR-223 — LinkedIn.** `post_as_images_carousel` (boolean) renders a carousel as LinkedIn's native document-style carousel rather than a plain image post — set true for HypeSocials carousel assets, with `carousel_name` set from the asset's trend/slug. LinkedIn video support and any platform-side caps are **verify-at-build** (Postiz's `integrationSchema` MCP tool, or its REST equivalent, can be queried against a live connected LinkedIn channel to confirm before Phase 2 ships).

## 5. Rate limits & pacing (FR-224, NFR-211, NFR-213)

Postiz's own limits: creating posts (`POST /posts`) tops out around 90 calls/hour on a self-hosted instance (configurable server-side via `API_LIMIT`) or 100/hour on the hosted cloud plan; list-style calls (`GET /integrations`, `GET /posts`, etc.) sit around 30/hour. A typical HypeSocials run produces well under ten publishable assets, so a normal publish run — one `GET /integrations`/`GET /groups` pair, a handful of uploads, one `POST /posts` per asset — sits far below either ceiling without any special pacing logic.

**FR-224:** The engine SHALL pace publish-time API calls conservatively regardless (small delay between successive uploads and post-creation calls, config-tunable) and SHALL retry on HTTP 429 with the same bounded exponential-backoff policy used everywhere else in HypeSocials (per 20-integrations.md NFR-14 — small, fixed max attempts from config, never unbounded).

**NFR-211:** The publish flow SHALL remain correct and complete for a typical run's asset count (per-format counts × platforms — realistically ≤ ~20 assets; there is no separate maximum-run-size config key) without approaching Postiz's documented per-hour ceilings under normal (non-retry-storm) operation.

**NFR-212:** Publish-time response detail is logged **only after passing the same redaction boundary as every other log line** (40-outputs-and-logging FR-152): Authorization headers stripped, key-shaped values replaced, response bodies truncated to a sane length before writing. "Where safe to log" in FR-229 means exactly this rule, not ad-hoc judgment.

**NFR-213:** Every retryable publish-time failure (429, transient 5xx) SHALL be bounded by the same hard maximum-attempt-count policy as OpenRouter/Kie.ai/Virlo retries (20-integrations.md NFR-14) — no publish retry path loops indefinitely.

## 6. Config sketch

```yaml
postiz:
  base_url_env: POSTIZ_BASE_URL        # default https://api.postiz.com/public/v1 (hosted cloud, FR-225); self-hosted URL works too
  api_key_env: POSTIZ_API_KEY          # sent raw in Authorization header — no "Bearer" prefix
  default_post_type: draft             # draft | schedule (auto_publish path only)
  auto_publish: false
  channel_map:
    linkedin: {integration_id: null, settings_type: linkedin, post_as_images_carousel: true}
    instagram: {integration_id: null, settings_type: instagram, post_type: post}
    tiktok:
      integration_id: null
      settings_type: tiktok
      privacy_level: PUBLIC_TO_EVERYONE
      content_posting_method: DIRECT_POST
      video_made_with_ai: true
  schedule_slots:
    linkedin: ["09:00", "18:00"]
    instagram: ["09:00", "18:00"]
    tiktok: ["09:00", "18:00"]
```

`integration_id` starts `null` and is filled in (by the operator, from the FR-212 lookup output) once confirmed — pinning it avoids re-resolving ambiguous channel matches on every run.

## 7. Self-hosted vs. hosted (FR-225, FR-226)

**Self-hosted Postiz** is AGPL-licensed and free, with the full REST API and MCP server available at no cost and no rate-plan gating beyond the self-set `API_LIMIT`. The tradeoff: the operator supplies their own Meta (Instagram) and TikTok developer app registrations, and platform-side app review/approval for those can take on the order of a month. **Hosted Postiz (api.postiz.com)** has no free tier (a 7-day trial only), and its own pricing page gates public API access behind a paid plan (Standard, roughly $29/mo at time of research — Postiz's marketing separately describes MCP as "free," which appears to contradict the plan gating; unresolved, see Section 10).

**FR-225 (amended by operator decision, 2026-08-08):** HypeSocials uses **hosted Postiz cloud** (Standard plan, ~$29/mo): the operator explicitly chose to avoid running Docker infrastructure and — decisively — to skip creating and maintaining their own Meta and TikTok developer apps, whose platform-side approvals can take weeks. `POSTIZ_BASE_URL` therefore defaults to `https://api.postiz.com/public/v1`. Self-hosting remains a supported fallback (the config only changes `POSTIZ_BASE_URL`), documented above for completeness. This raises the priority of OQ-10 (verifying that the paid plan actually unlocks the public API/MCP as expected) from low to **must-confirm before Phase 2 build**.

**FR-226:** `POSTIZ_API_KEY` and `POSTIZ_BASE_URL` are carried in the secrets table in 20-integrations.md §9 (both rows present as of v1.6): missing `POSTIZ_API_KEY` SHALL cause `--publish` (and `--promote`) to refuse to run at pre-flight, with an error naming the missing variable — no partial publish attempt with an absent key; missing `POSTIZ_BASE_URL` simply uses the hosted-cloud default. This mirrors the pre-flight-abort treatment already given to `VIRLO_API_KEY`, `OPENROUTER_API_KEY`, and `KIE_API_KEY`.

## 8. Edge cases & failure modes (FR-227–FR-229)

Per the project-wide posture: **degrade and report, never block the whole publish run.**

| Failure | Scope | Behavior |
|---|---|---|
| `POSTIZ_API_KEY` missing | Whole publish run | Refuses to start; names the missing variable (FR-226). |
| Configured channel not connected, disabled, or unmatched at FR-212 lookup | That platform's posts, this run | Skipped, named in the summary ("Instagram: no connected channel matching config — skipped 3 assets"); other platforms' assets proceed. |
| Media upload fails (network error, unsupported format, oversized file) | That one asset | Asset skipped for this publish attempt, reason logged; other assets in the run continue. Rerunning `--publish` later retries it (no `PUBLISHED.marker` was written). |
| Media upload succeeds, but POST /posts fails afterward | That one asset | Uploaded MediaFile ids and paths are cached in the asset's `meta.yaml` immediately on upload success (before POST /posts is called). On the next `--publish` run, any retry reuses the cached media references instead of re-uploading, preventing duplicate orphaned media accumulation. The asset is skipped this publish attempt; rerunning later re-attempts the post-creation call with the same (cached) media. |
| HTTP 413 (payload too large) | That upload call | Prevented by design, not just handled: media is always pre-uploaded via `POST /upload`/`POST /upload-from-url` (FR-213) and never inlined into the 50MB-capped post-creation body, so this should not occur in normal operation; if Postiz's own upload endpoint itself rejects an oversized file, that's treated as an upload failure (row above). |
| HTTP 429 (rate limit) | That call | Bounded backoff and retry (FR-224); persistent limiting surfaces as a logged, skipped item after the retry cap. |
| HTTP 400 on draft creation (schema validation) | That asset's post-creation call | The full-payload defense (FR-220) is the primary mitigation; if it still fails, the asset is skipped and the response body's validation detail is logged verbatim for diagnosis. |
| Partial publish (some assets succeed, some skip) | Whole run | Not treated as a run failure — the summary (FR-216) lists exactly what was pushed and what wasn't, by asset, so the operator can retry just the gaps. |
| Re-running `--publish` on a run already (fully or partially) published | Whole run | **Idempotent by default**: any asset carrying `PUBLISHED.marker` is skipped without re-uploading or re-creating a post. Re-publishing deliberately = delete that asset's marker first (v1.6.1 — `--force` removed). Assets with a lingering `PUBLISH_ATTEMPTED.marker` are named in the summary for a quick manual glance at the Postiz drafts list (FR-215). |

**FR-227 (simplified v1.6.1):** An asset already carrying `PUBLISHED.marker` SHALL always be skipped by `--publish`. The `--force` flag was removed; the deliberate way to re-publish an asset is to delete its `PUBLISHED.marker` — an explicit, visible file operation instead of a flag that could ride along in a scheduled command line.

**FR-228:** The publish summary (FR-216) SHALL report success/skip status per asset, not only an aggregate count, so a partial publish is fully diagnosable from the summary alone.

**FR-229:** Every publish-time failure SHALL be caught at its call site, logged with enough context to diagnose it (asset id, platform, HTTP status, response detail where safe to log — see NFR-212), and SHALL degrade only that asset or that platform's slice of the run, never the whole publish run, mirroring 20-integrations.md FR-48/FR-49.

## 9. Design Decisions

- **Amends D1 — REST-primary for Postiz, MCP kept as an optional seam.** D1 originally grouped Postiz with Virlo and Notion as a "true MCP" content service. Live research into Postiz's shipped MCP server (nine tools, none an upload primitive; `schedulePostTool` attachments demonstrated only with Postiz-generated media) shows MCP cannot carry the actual publishing job. The publish path (Sections 2–4) therefore runs on Postiz's public REST API end to end; MCP remains available for lightweight, non-media operational queries and is explicitly not on the critical path. This is recorded here, not silently changed, because D1 is a locked cross-file decision and any amendment to it needs its evidence on the record.
- **D29 — Postiz is committed Phase 2, spec'd now, built after MVP.** This whole file exists because D29 upgraded Postiz from "design-only placeholder" (20-integrations.md §6, MVP) to a fully implementation-ready spec, sequenced to build immediately after MVP ships rather than being deferred indefinitely.
- **Draft-first by default (FR-217).** The project's whole philosophy is "generate freely, let a human make the final call" (no gates, no compliance stack — D3, D4) — extending that same trust model to publishing means Postiz drafts, not silent auto-posts, are the default, with auto-publish available only as a deliberate, named opt-in (FR-219).
- **Hosted Postiz cloud chosen (FR-225, operator decision 2026-08-08).** The draft originally recommended self-hosting for infrastructure-control consistency; the operator explicitly chose the hosted Standard plan (~$29/mo) to skip Docker operations and — decisively — the weeks-long Meta/TikTok developer-app approvals that self-hosting requires. The recurring cost buys ready-made platform app registrations. Self-hosting remains a config-only fallback (swap `POSTIZ_BASE_URL`); OQ-10 (paid plan actually unlocking API/MCP) is now a must-confirm before the Phase 2 build.
- **`video_made_with_ai: true` by default (FR-222).** A deliberate honesty choice: the content is AI-made, and the field exists precisely to say so.
- **D30 — Secrets hygiene applies unchanged.** `POSTIZ_API_KEY` lives only in `.env`/environment variables, is sent only in the Postiz `Authorization` header (raw value, no "Bearer" prefix — a Postiz-specific quirk worth stating plainly so it isn't "fixed" by mistake), is never interpolated into any prompt or template, and is redacted from `run.log`/`events.jsonl` at the same logging boundary already specified in 40-outputs-and-logging.md FR-152.

## 10. Open Questions

Nine items are unresolved from research and worth a short, direct check during Phase 2 build, before relying on them:

- **OQ-8 — Self-hosted API path prefix.** Whether a self-hosted instance serves the public API at `/public/v1` or `/api/public/v1` depends on the reverse-proxy setup; confirm against the operator's actual deployment before hardcoding the base path.
- **OQ-9 — Exact rate-limit split.** The ~90–100/hr create-post figure and ~30/hr list-endpoint figure are the best-documented numbers found; confirm the current split (and whether list endpoints share one bucket or several) against a live instance or current docs before treating them as hard ceilings in pacing logic (Section 5).
- **OQ-10 — Hosted-plan API/MCP gating (build-blocking pre-check).** Postiz's pricing page gates the public API behind the paid Standard plan; the marketing site separately describes MCP as "free" — an apparent contradiction. Since this PRD commits to hosted Postiz cloud (FR-225, operator decision 2026-08-08), confirming that the Standard plan actually unlocks both the public API and MCP as expected is a **must-confirm empirical test before Phase 2 build starts** — not a side check, but a blocker. *Operator re-confirmed (2026-08-09) they are on a hosted paid plan; only the empirical key test remains.*
- **OQ-11 — MCP `schedulePostTool` with external attachment URLs.** The one condition (Section 1) under which the scheduling call itself could move to MCP: test whether `attachments` accepts an arbitrary external HTTPS URL (our own uploaded media, or a self-hosted Postiz storage URL) rather than only Postiz-generated media. A quick empirical call against a live instance settles this either way.
- **OQ-12 — One-click UI approval on API-created drafts.** Confirm that a draft created via `POST /posts` shows up in the Postiz web UI with the same one-click approve/schedule affordance as a draft created interactively — this is the whole basis of the draft-first approval model (Section 3) and should be visually confirmed once, not assumed.
- **OQ-13 — LinkedIn video support and size/duration caps.** Undocumented in the public API reference; query `integrationSchema` (or its REST equivalent) against a connected LinkedIn channel before shipping LinkedIn reel/video publishing.
- **OQ-14 — Instagram carousel slide ceiling as enforced by Postiz.** Instagram's own platform limit is 2–10 images; confirm Postiz doesn't impose a tighter ceiling of its own before assuming the full platform range is usable.
- **OQ-15 — TikTok developer-app review/audit status.** `DIRECT_POST` publishing to a real (non-sandboxed) TikTok account requires the operator's TikTok developer app to have passed platform review; until then, `content_posting_method: UPLOAD` (inbox draft, manual 24-hour publish window on-device) is the practical default — confirm current app status before defaulting to `DIRECT_POST` in the channel map. *Operator decision (2026-08-09): deferred to Phase 2 — until Postiz is implemented, all review happens from the `output/` folder on disk, and Postiz will then carry TikTok along with every other platform.*
- **OQ-16 — Draft full-payload requirement, current-version behavior.** Issue #717's "drafts 400 on missing fields despite docs calling them optional" report may or may not still apply to the exact self-hosted version the operator runs. FR-220's always-send-everything defense is cheap enough to keep regardless, but worth a one-time confirmation of whether it's still strictly necessary or just good hygiene.

---

Cross-references: `10-pipeline.md` for where a run's asset plan originates; `40-outputs-and-logging.md` §9 (FR-87/FR-88) for the MVP-era hook this file fully implements, and §2/§4 for asset-folder and `meta.yaml` shape; `20-integrations.md` §1/§1a and §6 for the MVP-era Postiz placeholder this file supersedes, and §9 for the secrets table this file extends; `30-configuration-and-run.md` for the `--publish` and `--promote`/`--at` CLI flags (listed in 30's flag table; behavior specified here — `--assets`/`--force` removed v1.6.1) and channel-map config schema.
