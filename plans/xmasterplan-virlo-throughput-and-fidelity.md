# xmasterplan — Virlo throughput and fidelity

**Status: FINAL — approved for execution 2026-08-11.** All operator decisions locked (§2), Increment B
included. Execute with `/xecutor`, Increment A first; B follows once A's live verification is signed off
(§2.1 — the gate is evidence, not budget). **The G2 line ceiling is withdrawn** (§2.4).

**How this document got here — read this before trusting any number in it.** Draft 1 was written from two
design agents. Adversarial review (architect-reviewer + python-pro) then **refuted or corrected 14 of its
claims**, including two blockers, one runtime-breaking omission, a line estimate optimistic by 40–90%, and
a drafted FR that would have made exit code 0 unreachable. Draft 2 restructured into two increments. A
third pass (three read-only audit agents + live API probes) added the steering fixes in §3.3. Every claim
below carries a `file:line` or a measured number; where an earlier draft was wrong, **the correction is
kept visible rather than quietly edited out** — including this plan's own arithmetic error in §2.4.

**⛔ Read before executing anything in §3.4c.** A sibling plan —
`plans/xmasterplan-copy-voice-transposition.md`, approved 2026-08-11 — **supersedes A22, A23 and A25** and
**revokes A23's prompt paragraph outright** (it said *"find the equivalent claim in our niche"*; the operator
decided **same exact topic**). **A20 remains a prerequisite** and A21/A24 remain independent. The two plans
share a path set (`copywrite.py`, `virlo_mcp/server.py`, `sources/virlo.py`, `prompts/copywriter_system.md`,
`models.py`) and **cannot run concurrently.** Execute the copy-voice plan for that work.

**Already done, before execution starts:** `CLAUDE.md` rule 5 and `NAVIGATION.md` are amended — the ceiling
is withdrawn and the broken line-count command (§1.8, it counted 20 of 39 files) is replaced by a `find`
based one. Growth is now measured and attributed, never capped.

---

## TL;DR (plain English)

Three measured defects, in order of how much they cost you:

1. **We ask Virlo for "top videos" and never sort.** We get a random 50 of 2,039 — median **2,534** views
   instead of **1,940,676**. Every creative reference has been drawn from the bottom of the barrel.
2. **Every style-brief call this tool has ever made ran out of token budget.** ~1 in 7 dies completely,
   ships `direct` output at `analyzed` prices, and exits `0`.
3. **We build ~36 reference image sets per trend and only ever attach the first one.** Groups 1..N are
   fetched, downloaded, kept alive in memory — and never reach a render job.

Increment A fixes all three, plus the steering and visibility gaps found in the audit (§3.3, §3.4b).
Increment B splits an agent's 9 themes into 9 trends. **Both are approved.** A runs first so its fixes get
real-API verification before the Virlo trial expires ~2026-08-13, and so B is judged against six real
creatives rather than a guess (§2.1).

---

## 1. Evidence base — measured live, read-only, free endpoints only

Probes: read-only GETs against `api.virlo.ai/v1`, 2026-08-11, operator key. `x-cost 0.00` on every call.
The metered `/trends/digest` was **not** called. Baseline: `pytest -q` → **370 passed**.

### 1.1 The unsorted-fetch defect

`hypesocials/virlo_mcp/server.py:243` — `_get(path, limit)` accepts **only** `limit`. No `order_by`, no
`sort`, no `page`. The tool named `get_top_videos` returns Virlo's insertion order.

Agent `9c96fddf-dc35-4be0-bbd9-12f4d22aea12`, 50 rows each:

| Metric | Current | `order_by=views&sort=desc` | Factor |
|---|---:|---:|---:|
| Videos — median views | 2,534 | **1,940,676** | 766× |
| Videos — max views | 83,386 | **26,756,830** | 321× |
| Videos — rows with `intelligence{}` | 17/50 | **34/50** | 2.0× |
| Slideshows — median views | 7,088 | **279,757** | 39× |
| Slideshows — max views | 307,801 | **5,487,494** | 18× |
| Slideshows — rows with `intelligence{}` | 29/50 | **44/50** | 1.5× |

Available: **2,039** videos, **635** slideshows. We fetch 2.4% / 7.9%, unsorted.

### 1.2 API contract facts

| Fact | Verified |
|---|---|
| `page` | 1-indexed, works; response echoes a derived `offset` |
| `offset` as a **request** param | **400** — `{"message":["property offset should not exist"]}` |
| `limit` | silently clamped at **100** |
| `order_by` enum | `publish_date \| views \| created_at`. `engagement` → 400 |
| Unused filters available | `min_views`, `start_date`, `end_date`, `platforms`, `intent_match`, `region` |

### 1.3 `GET /v1/agents/{id}/trends/latest` — undiscovered, free

Not referenced anywhere in the repo or the supplied docs. Same themes as `analysis_data.themes[]` **plus**
per theme: `rank`, `status` (`new|rising|steady|fading`), `total_views/likes/shares/comments`,
`video_count`, `avg_virality_score`, `first_seen_at`, `prev_total_views`, `platform_breakdown`,
`peak_hour_utc`, `top_creators[]`, and **`evidence_videos[{id,url,platform}]`**.

### 1.4 The 9 themes on the operator's remaining agent

| Theme | conf | videos | tactics | evidence |
|---|---:|---:|---:|---:|
| Claude AI for Coding & Development | 0.95 | 36 | 14 | 30 |
| AI Agents for Business Automation and Operations | 0.93 | 29 | 15 | 29 |
| Claude AI for Productivity and Business Hacks | 0.92 | 32 | 15 | 32 |
| Vibecoding AI Demos and Practices | 0.90 | 13 | 9 | 13 |
| AI Coding Benchmarks and Comparisons | 0.90 | 2 | 2 | 2 |
| AI Tool Reviews and Recommendations | 0.87 | 19 | 10 | 19 |
| AI Tools for Lead Generation (General) | 0.87 | 11 | 10 | 11 |
| AI Video Generation Trends | 0.85 | 12 | 7 | 12 |
| Claude Opus & Sonnet Insights and Performance | 0.85 | 6 | 5 | 6 |

These are **content pillars, not analytics buckets** — the review tested this premise and it survived.

### 1.5 The theme→media join — honest limits

| Question | Measured |
|---|---|
| `evidence_video_ids[] ⊂ /videos[].id` | **Yes**, all 3 agents |
| Evidence ever names a **slideshow** | **Never** — 0/152, 0/51, 0/84 |
| Evidence recovered by one `views desc` page of 100 | **12/152**; per-theme `[1,4,3,1,1,0,2,0,0]` — **3 of 9 get zero** |
| + a `publish_date desc` page | 26/152 |
| Full coverage | ~20 sequential pages **per monitor** — rejected |
| Token-overlap fallback (tier C) | matches 37–128 of 200 rows per theme — **too loose to partition** |
| `stable_key` unique across monitors | **No** — collides on all three agents. Keys MUST be monitor-scoped |

**Binding consequence:** evidence is a weak signal, never a partition key. What theme-splitting really
delivers is **distinct analysis/copy subjects with non-overlapping reference sets** — not "each theme uses
its own posts." Say so in the UI or the first fidelity complaint is unexplainable.

### 1.6 The style-brief collapse — deterministic

Every `output/*/events.jsonl` scanned. **Every analysis call this tool has ever made hit `llm_truncated`.**
Successful briefs serialize to 12,938–23,388 chars ≈ **3,600–6,500 output tokens**. Cap is **2,000**,
widened once to **4,000**.

| Run | prompt_tok | completion_tok | reasoning_tok | outcome |
|---|---:|---:|---:|---|
| `20260809_162534_z1gk` | 18,590 / 18,808 | 4,826 / 5,042 | 0 / 259 | ok after 1 widen |
| `20260809_220436_wrfc` | 39,668 | 10,000 | 2,103 | **DEGRADED** |
| `20260809_224147_wrsg` | 38,330 | 10,000 | 2,588 | **DEGRADED** |
| `20260810_185049_o9n8` | 38,339 | 8,978 | 1,730 | ok (2nd attempt `chars: 0`) |
| `20260811_135734_6h6s` | 37,280 | 10,000 | 2,771 | **DEGRADED** |

`10,000 = 2,000 + 4,000 + 4,000` — confirmed against `llm.py:204` (bump `min(max_tokens, 8192)`) and
`llm.py:208` (FR-41 retry does **not** widen). `37,280` prompt tokens is **three attempts of ~12,430**.

`reasoning_effort` is `None` for analysis (`runner.py:425`), yet OpenRouter reports 0–3,057 reasoning
tokens. **Sonnet-5 thinks unbidden and those tokens are billed inside `completion_tokens`.**
`spikes/RESULTS.md:466-474` swept Luna only — Sonnet-5's default was never measured.

**Image count is NOT the defect.** `media_download_cap: 6` is mandated by FR-9/FR-91/FR-93. Cutting it
saves ~$0.02 and breaks three FRs. Fixing the output cap turns 37,280 prompt tokens into ~12,430 — a
**67% cut in prompt billing**, no image change.

### 1.7 The unattached reference groups — the finding that reshaped this plan

`sources/virlo.py:283` stores **every** qualifying candidate set (~36 on a live monitor,
`spikes/RESULTS.md:163`). `virlo.py:568,587-593` downloads across groups and keeps them alive.

Then:

```python
hypesocials/generate/refs.py:69    group = list(trend.reference_groups[0]) if trend and trend.reference_groups else []
hypesocials/runner.py:555          urls  = trend.reference_groups[0] if trend and trend.reference_groups else []
```

**Groups 1..N are built, downloaded, retained — and never attached to any render job.** Every creative on
a trend gets the identical three images, forever. Verified: those are the only two attachment readers.

And the copy axis is **already** solved — `prompts/copywriter_system.md:79-81`:

> "Every sibling gets its OWN angle and its OWN hook pattern… If two siblings would land on the same claim,
> change one of them."

So "raise reuse to 6" does **not** produce six paraphrases. It produces six distinct angles on identical
pictures. Rotating the reference group fixes the remaining axis in ~5 lines.

### 1.8 The ceiling command was broken — RESOLVED (ceiling withdrawn, command replaced)

`CLAUDE.md:66` and `NAVIGATION.md:98` both specify `wc -l hypesocials/**/*.py`. **Globstar is off in this
shell.** Measured just now:

```
wc -l hypesocials/**/*.py   →  20 files,  5,844 lines
find hypesocials -name "*.py" | xargs wc -l  →  39 files, 14,176 lines
```

The documented command has been counting **half the repo** since Wave 1. Worse: after a
`sources/virlo/` package split, `hypesocials/sources/virlo/*.py` sits at depth 3 and vanishes entirely
while `virlo.py`'s 649 counted lines disappear — **the checkpoint would report a 649-line reduction on a
change that adds ~550.** Rule 5's enforcement silently inverts.

Also confirmed stale at the time: `NAVIGATION.md:98` said ceiling **13,500** while `CLAUDE.md:66` said
**14,300**. Both files have since been amended — the ceiling is withdrawn (§2.4) and the `find` command
replaces the broken glob. The finding is kept here because it is why the *measurement* discipline in rule 5
is worded the way it now is.

### 1.9 The `refs/` collision — worse than a display bug

`packager.py:100` → `slugify(source_key)` with `util.py:26 ASSET_SLUG_MAX = 40`, against a 36-char UUID.
Reproduced against the real §1.4 theme names:

```
9c96fddf-dc35-4be0-bbd9-12f4d22aea12-cla   <- 3 themes
9c96fddf-dc35-4be0-bbd9-12f4d22aea12-ai    <- 5 themes
9c96fddf-dc35-4be0-bbd9-12f4d22aea12-vib   <- 1 theme
```

**3 folders for 9 themes.** And `packager.py:102` writes `f"{kind}_{int(index)}{suffix}"` with `index`
restarting at 1 per trend (`runner.py:556`) — colliding themes **overwrite each other's `image_1.jpg`**.
Data loss, not a wrong picture.

Two further call sites with the same truncation:
- `generate/reel.py:368` — `video_1.mp4` overwritten across themes.
- **`generate/video_ref.py:200`** — `f"{slugify(trend_key) or 'trend'}_ref.mp4"`, and `video_ref.py:151-155`
  spawns **one concurrent `asyncio.create_task` per trend_key**. Nine theme keys → three destination paths
  → up to five concurrent `yt-dlp` processes writing the same file. **Non-deterministic wrong motion
  reference on reels.** This was missed by the first draft entirely.

---

## 2. Operator decisions

| # | Decision | Choice |
|---|---|---|
| D-A | One agent → N trends, one per theme | **Yes** — now **Increment B**, see §2.1 |
| D-B | Analysis calls | **One per theme** |
| D-C | Intelligence fields | **Deferred**, see §2.2 |
| D-D | Scope | Core only. `/orbit` + `/comet` and the `monitor`→`agent` rename are OUT |
| D-E | G2 ceiling | **WITHDRAWN entirely** (2026-08-11). Measure + attribute, never cap — §2.4. `CLAUDE.md` rule 5 and `NAVIGATION.md` already amended. `sources/virlo.py` still splits, on §3a/§18 grounds |
| D-F | Fully-degraded run | **Exit 1 + summary line** — see §2.3, the drafted FR was wrong |
| D-G | Steering fixes A11–A17 | **Approved** 2026-08-11 (§3.3) |
| D-H | The $0.25 digest | **Fix it** — surface `top_exemplars` (A18, §3.4). Not killed |
| D-I | Virlo funnel visibility | **Approved** (A19, §3.4b) |
| D-J | Use the posts' substance (copy/topic/text) with our own brand spin | **Approved** (A23, §3.4c). Descriptive fields feed freely; literal strings stay exemplar-only |
| D-K | No plagiarism — kill the verbatim-hook fallback | **MANDATED** by the operator (A20). A21/A22 fold in as its enforcement layer |
| D-L | Console: which posts these are + how the AI analysed them | **Approved** (A24, §3.4c) |
| D-M | Programmatic echo check between our copy and the source strings | **Added** (A25) — found by dry-running the design on real data, §3.4d |

### 2.1 Sequencing — A then B, both in scope, both pre-approved

**Everything in this plan is approved for implementation, A19 and Increment B included.** With the ceiling
withdrawn there is no budget reason left to split the work. One reason survives, and it is not about lines:

> Review's finding: the plan framed the alternative as "reuse=6 → six identical creatives." That is false.
> The copywriter already mandates distinct angles per sibling (`copywriter_system.md:79-81`). The *only*
> thing reuse=6 fails to vary is the pictures, and that is `refs.py:69` hardcoding `reference_groups[0]`
> over ~36 already-downloaded sets.

Increment A fixes **100% of the defects that were actually measured**. Increment B is an *enhancement*
whose value rests on an evidence join that §1.5 measured as weak — 12/152 evidence recovery, 3 of 9 themes
with zero hits, slideshows structurally excluded.

**So A still runs first, and B still starts only after A4's live verification — but the gate is now
evidence, not money.** Concretely: after A ships, look at six real creatives. If they are visually and
editorially distinct enough, B's remaining value is *distinct subjects per creative* (real, but smaller
than first assumed). If they still read as one trend six ways, B is fully justified. Either way you will
know, and B is already written and approved — no new decision cycle, just a look at the output.

⏰ **The trial deadline reinforces the same order.** A can be verified live before ~2026-08-13; A+B cannot.
Running A first guarantees the measured fixes get real-API verification while the key still works.

### 2.2 Intelligence fields — contradiction RESOLVED, partially un-deferred

The first draft deferred these because the evidence looked self-contradictory: agent `9c96…` reports
`data_intelligence_enabled: false` while 34/50 rows carry `intelligence{}`.

**A live single-record pull resolved it: `intelligence` is populated PER ROW, not per agent.** The
agent-level flag gates *new* enrichment; already-enriched rows keep their block. Measured:

```
TOP SLIDESHOW (order_by=views)        TOP VIDEO (order_by=views)
  intelligence: 35 fields               intelligence: 0 fields
  hook_text:     "Remember.. >>"         hook_text:     None
  hook_type:     story_tease             hook_type:     None
  emotional_tone: educational            narrative_arc: None
  narrative_arc: escalating_reveal
  text_density:  balanced
```

And **the sort fix nearly doubles coverage on its own** (§1.1): videos 17/50 → 34/50, slideshows
29/50 → 44/50. So A1+A2 are a prerequisite for this being worth anything, and once they land it is.

**Un-deferred: three fields only** — `hook_type`, `visual_hook_type`, `emotional_tone` (A13). These
replace guesswork the copywriter currently does from scratch and cost one short line in `_trend_texts`.
The other five stay deferred: they are prose-shaped, they grow the prompt L1 is bounding, and they buy
less per token.

### 2.3 ⛔ The drafted exit-code FR was wrong — corrected

The first draft's P5 read *"at least one delivered creative carries `analysis_missing`."* With 6 analysis
calls at the observed ~1-in-7 degrade rate, **P(at least one) ≈ 60%** — exit 0 becomes unreachable on a
majority of healthy runs and the code stops carrying information.

**Corrected to match what you approved:** *"…or **every** analyzed creative delivered carries
`analysis_missing`."* Fully-degraded, exactly as D-F says.

### 2.4 Line budget — corrected

⚠️ **Arithmetic error in this plan's own second draft, owned here.** §2.4 said "+120 → 14,296" while §3.2
totalled **+136**. Neither is right: `14,176 + 136 = 14,312`, which is **already 12 lines over the current
14,300 ceiling.** The claim "Increment A needs no escalation" was false before the §3.3 additions and is
more false after them.

**The ceiling is withdrawn (operator decision 2026-08-11).** `CLAUDE.md` rule 5 and `NAVIGATION.md` are
already amended: line growth is **measured and reported, never capped**. Three obligations survive and
this plan is bound by all three:

1. **Measure with `find hypesocials -name "*.py" | xargs wc -l | tail -1`** at every wave barrier. Never
   the old glob — §1.8 proves it counts ~20 of 39 files.
2. **Report with per-task attribution**, never a bare total.
3. **Never shorten docstrings, comments or error messages to make a number look better.** This is the part
   of rule 5 that still binds, and it is the part that mattered.

Estimates are kept below as *forecasts to check attribution against*, not as budgets:

| | Lines | Running total |
|---|---:|---:|
| Today (measured) | 14,176 | 14,176 |
| Measured defects (A1–A10) | +136 | 14,312 |
| Steering fixes (A11–A17) | +58 | 14,370 |
| Digest exemplars (A18) | +18 | 14,388 |
| Funnel report (A19) | +87 … +107 | 14,475 … 14,495 |
| **Substance channel + plagiarism guardrails (A20–A25)** | **+140** | **14,615 … 14,635** |
| Theme items (B) | +430 … +550 | **14,905 … 15,045** |

⚠️ **Three consequences of removing the cap, stated so they are not discovered later:**

- **`sources/virlo.py` still gets split** (§4.6). It was never really a line-count decision — a ~840-line
  module with two responsibilities is a §3a/§18 problem, and the globals-alias trap in that section is a
  correctness risk regardless of any ceiling.
- **No more escalation conversations.** The 14,400 → 14,450 → 14,600 ratchet earlier in this plan's history
  is now moot. Growth gets reported at each barrier; nobody has to approve a number mid-execution.
- **The estimate discipline stays.** If a wave lands 40% over its forecast — as review showed draft 1's
  numbers were — that is still a signal worth reporting, because it usually means the design grew, not
  that the typing did.

---

## 3. INCREMENT A — measured defects, steering fixes and funnel visibility

### 3.1 PRD amendments (Wave A0)

| # | File | Change |
|---|---|---|
| A-P1 | `CLAUDE.md:66` §5 | **Ceiling withdrawn**; rule 5 becomes measure-and-attribute with the `find` command and the no-trimming-docstrings clause retained. Re-baselined at 14,176 (**already applied**) |
| A-P2 | `NAVIGATION.md:98` | Same `find` command; the stale "hard ceiling 13,500" line is removed, not renumbered — there is no ceiling (**already applied**) |
| A-P3 | `prds/20-integrations.md` tool table | `get_top_videos`/`get_top_slideshows` accept `limit` (≤100, server-clamped), `page` (1-indexed), `order_by ∈ {publish_date,views,created_at}`, `sort`. **`offset` is rejected by Virlo — never send it** |
| A-P4 | `prds/10-pipeline.md` FR-91 | Reference groups **rotate per reuse**: creative *k* on a trend attaches `reference_groups[k % len]`. One set = one source is preserved |
| A-P5 | `prds/10-pipeline.md:313-323` FR-202 | Code-1 trigger gains: *"…or **every** analyzed creative delivered carries `analysis_missing`"* (§2.3) |
| A-P6 | `prds/30-configuration-and-run.md:427-437` FR-252 | New row: every analysis call fails → ships direct per FR-12, summary line names the count, exit 1 |
| A-P7 | `prds/30-configuration-and-run.md` schema | `models.max_tokens.analysis` 2000→12000, `max_tokens_floor.analysis` 600→6000, with the Sonnet-5 unbidden-reasoning rationale. Note `max_trend_reuses_per_run` default 2→6 |
| A-P8 | `spikes/RESULTS.md` **:87, :145, :587** | Correct the pagination claim. ⚠️ The first draft pointed at `:157`, which is an unrelated slideshow-intelligence listing — a Wave-0 writer following it literally would edit the wrong line and leave all three real claims wrong |
| A-P9 | `prds/00-overview.md` | Decisions **D37** (rotation + sort), **D38** (brand accent decoupled from Notion), **D39** (funnel report) and a **v1.9.0** amendment-log entry |
| A-P10 | `prds/40-outputs-and-logging.md:100-113` FR-77 | Bullet 1's MCP result summary **must carry a row count** — the PRD's own example shows one and the code omits it. Amend to state the required shape, then implement in A19 |
| A-P11 | `prds/40-outputs-and-logging.md` | **New FR** for the funnel report: run-wide rollup, printed unconditionally after Select and in both previews, one row under FR-84's headline, `collect_funnel` in `events.jsonl`, input/output vocabulary kept disjoint |
| A-P12 | `prds/30-configuration-and-run.md` schema | New keys `niche.brand.accent`, `niche.brand.product_nouns` (A11) |

### 3.2 Code changes

| # | Change | Files | ~Lines |
|---|---|---|---:|
| A1 | `_get` takes a params mapping; `page`/`order_by`/`sort` on both media tools with **local enum validation** (a client typo must not surface as a Virlo error, FR-119); never send `offset` | `virlo_mcp/server.py` | +30 |
| A2 | Adapter requests `order_by=views&sort=desc, limit=100` | `sources/virlo.py` | +6 |
| A3 | **Rotate the reference group per reuse** — `refs.py:69` and `runner.py:555` take `reference_groups[k % len]`, where `k` is the creative's index within its trend | `generate/refs.py`, `runner.py` | +14 |
| A4 | Style brief keyed by `(trend_key, group_index)` so a rotated set gets its own brief | `generate/analyze.py`, `runner.py` | +18 |
| A5 | L1: `analysis: 12000`, floor `6000`. **Cap the truncation bump against the model's advertised max output** — `llm.py:204` doubles, so 12000→24000 could become a hard 400 where it previously merely degraded | `config.py:168`, `configs/default.yaml:93`, `llm.py:204` | +10 |
| A6 | L2: `if content_retry and finish not in _TRUNCATED_REASONS:`; else set a truncation reason and fail fast (FR-127: never an identical retry). **Rewrite `llm.py:216-217`'s message in the same edit** — "no schema-valid JSON after the FR-41 retry" becomes false once the retry is skipped | `llm.py` | +12 |
| A7 | L3: add `ParsedResult.reason`; populate on every degrade path; read at `analyze.py:123`, `vision_check.py:183`. ⚠️ **`copywrite.py:210` does not read `raw_text`** — that migration target from the first draft does not exist | `models.py`, `llm.py`, `generate/analyze.py`, `vision_check.py` | +16 |
| A8 | L4: log `finish_reason`, `attempt`, `truncated`, `retried` | `llm.py`, `runner.py` | +12 |
| A9 | L6: `decide_exit_code` gains `degraded_delivered`; summary line naming the count. ⚠️ **`previews.py` never calls `decide_exit_code`** (it returns constants at `:82,:92,:115,:116,:119,:123`) — the first draft's wire-in row was wrong. `runner.py:701` is the only production call, and `runner.py:761-763` already computes the needed set | `runner.py` | +18 |
| A10 | `max_trend_reuses_per_run: 2 → 6` | `configs/*.yaml` | 0 |
| **Subtotal — measured defects** | | | **≈ +136** |

`configs/default.yaml` is at **:93**, not `:95` as the first draft said.

### 3.3 Steering fixes (A11–A17) — approved 2026-08-11

Evidence: three read-only audit agents mapped every operator lever, the Notion path, and every colour
channel. Findings quoted inline; all verified against the files.

#### A11 — `brand.accent` → `{{brand_accent}}` · **~10 lines · highest leverage in the repo**

`{{brand_accent}}` already exists, is already allowlisted for **all four** gpt-image-2 roles
(`prompts_engine.py:91-103`), already has a builder (`_brand_accent`, `prompts_engine.py:621-634`), and
already appears in every image template (`image_single_post.md:45`, `carousel_slide.md:16`,
`image_direct.md:41`, `reel_seed_frame.md:45`).

It has been **empty on every run ever made** — `output/latest/events.jsonl` shows `BRAND INFLUENCE: ` blank
in all 6 assembled prompts. The slot is welded to Notion, which is gated on a `NOTION_TOKEN` that is not in
`.env`, page ids that are empty in every config, and a mode that is `off` everywhere (§3.5).

**Change:** add `brand.accent: str` (and optional `brand.product_nouns: list[str]`) to `NicheConfig`
(`config.py:214-226`); at `runner.py:646` feed `brand_accent=session.brand.accent or config.niche.brand_accent`.

**No new placeholder, no template edit, no allowlist change.** A complete, allowlist-audited pipeline that
is simply starved of input. The operator's accent lands inside the trend's proven layout — mimicry with a
brand overlay, which is exactly the product thesis.

⚠️ `reel_director.md`'s allowlist (`prompts_engine.py:104-106`) deliberately excludes `brand_accent`. Leave
it excluded in A; revisit only if reels are turned on.

#### A12 — Override-brief single images render with a blank subject · **~5 lines · real bug**

Chain: `influence: override` forces `variant="direct"` (`plan.py:265`) → `generate/__init__.py:478-479`
selects `ROLE_DIRECT = image_direct.md` → that template's subject slot is `{{content_sentence}}`
(`image_direct.md:7`) → `_content_sentence` returns `""` when `trend is None`
(`prompts_engine.py:545-548`), and an override brief has **no trend**.

Result: **`SUBJECT AND SCENE:` is empty** and the entire image rides on the `BRIEF OVERLAY` blob — which
also carries the *copy* directives (`cta`, `tone`, `avoid`) into an image prompt, guarded only by
`image_direct.md:22-29`'s TEXT PRECEDENCE clause. Carousels are unaffected (`carousel_slide.md` is used for
every variant and does resolve `{{render_prompt}}` to the visual directives).

**Fix (pick one, prefer the first):** add `render_prompt` to `image_direct.md`'s allowlist and a subject
line to the template, so `build_context`'s existing
`"render_prompt": visual or (style_brief.render_prompt …)` (`prompts_engine.py:368-374`) reaches it.
Alternative: have `_content_sentence` fall back to the brief's `visual_directives.subject`.

#### A13 — Three intelligence fields · **~12 lines** · see §2.2

`hook_type`, `visual_hook_type`, `emotional_tone` — kept in `_norm_video` / `_norm_slideshow`, read by the
adapter, and added as one row in `_trend_texts` (`prompts_engine.py:506-521`). Today FR-100 asks the
copywriter to *derive* a hook pattern in prose that Virlo already labels (`story_tease`, measured live).

#### A14 — Real hashtags instead of invented ones · **~8 lines**

The wrapper extracts `hashtags` on every video and slideshow (`server.py:193`, `:226`) and **nothing reads
them**. Meanwhile `copywrite.py:339 _hashtags()` invents tags from the trend-name slug on the FR-99 fallback
path. Thread the winning posts' real hashtags into the copy prompt as reference material.

⚠️ Reference material, not a mandate — the model must still choose. Do not paste them into the output.

#### A15 — `niche.visual_world` is inert in `direct` mode · **~5 lines**

`niche_descriptor` is allowlisted for `style_brief_system.md` and `copywriter_system.md` **only**
(`prompts_engine.py:82-87`). No render role can resolve it. So the operator's only global art direction —
`hypedigitaly.yaml:18`, *"dark UI and dashboard screenshots… one electric accent on near-black, heavy
geometric sans headlines…"* — reaches the image **only** in `analyzed` mode, and only if the analyst folds
it into `render_prompt`. In `direct` mode it touches nothing at all.

**Fix:** add a **visual-only** slot (`{{niche_visual_world}}`, sourced from `niche.visual_world` alone) to
the four gpt-image-2 role allowlists and templates.

⚠️ **Do not** simply allowlist the whole `niche_descriptor` for render roles — it carries `audience`, which
is copy context, and the allowlist exists precisely to stop copy-side context leaking into render prompts
(`prompts_engine.py:19-23`). A narrow slot preserves that boundary.
⚠️ `niche_descriptor` sits in `_TRUNCATION_ORDER` (`prompts_engine.py:76`) — the new slot must be added
there too, or it becomes the one uncuttable block under the 10,000-char cap.

#### A16 — Inspiration `.txt` files are invisible · **~15 lines**

`inspiration.py:48` — `_SUFFIXES = {".jpg",".jpeg",".png",".webp",".gif",".bmp"}`. A `.txt` beside an image
is counted in `skipped` and discarded. `Inspiration/Linkedin/Viral posts/` ships paired `01.jpg` / `01.txt`
(proven, human-written viral copy) and **no code path anywhere reads the text.**

**Fix:** when an image has a sibling `.txt`, read it (size-capped, UTF-8) and pass the pooled text to the
**copy** call as exemplar material.

⚠️ **Copy call only.** It must not reach a render prompt — inspiration images already carry an explicit
"no words" role line (`refs.py:36-37`), and feeding proven copy into an image model invites verbatim text
baked into pixels.
⚠️ The currently configured folder (`Inspiration/Tiktok and IG`) has **no** `.txt` files, so this is inert
until the LinkedIn folder is configured. Ship it; do not expect an immediate change.

#### A17 — `inspiration_mix: exclusive` gives every asset identical images · **~3 lines**

`_pick` (`inspiration.py:183-189`) slices `group[:count]` with no intra-folder rotation, so under
`exclusive` with one configured folder **every creative in the run gets the same first three files.**
Rotate by asset index. Low priority — the shipped configs use `minority` — but it is three lines and the
branch is otherwise a trap.

**Subtotal — steering fixes: ≈ +58 lines.**

### 3.4 A18 — make the $0.25 digest earn its money · **~18 lines** · approved 2026-08-11

`/trends/digest` is the only metered Virlo call. Audited, today it buys:

- **one sentence** of `cross_monitor_context` (`virlo.py:125-127`, top 8 rows)
- `confidence`, which `spikes/RESULTS.md` records as **`null` for all 15 live trends**
- and it **discards `top_exemplars[]`** — 5 posts per trend carrying
  `{video_id, url, platform, views, thumbnail_url, publish_date, author{username, avatar_url, verified}}`,
  dropped at `server.py:150`. The spike itself flagged this: *"present and unclaimed… the digest **is** a
  usable media source."*

**Operator decision: fix it, do not kill it.**

**Change:**
1. `_norm_digest_trend` (`server.py:149-167`) stops discarding `top_exemplars[]`; normalize each exemplar to
   `{post_id, url, platform, views, thumbnail_url, publish_date, author}` — the same field names
   `_norm_video` already uses, so no second vocabulary enters the codebase.
2. `_digest` (`virlo.py:208-233`) collects them into a run-level pool.
3. The pool is offered to `_reference_groups` as a **last-resort tier only**, below every monitor-sourced
   candidate — it is cross-niche material and must never outrank a monitor's own posts.

⚠️ **Constraints, both non-negotiable:**
- Exemplar thumbnails are **one still per post**, exactly like video thumbnails — so they qualify under
  `_MIN_THUMBS = 2` grouping rules, never as a slideshow.
- Digest exemplars are **global**, not niche-filtered. Attaching one to a creative is a fidelity risk, which
  is why they sit below everything else and are logged as `reference_source=digest_exemplar` so a bad
  creative is traceable.

After Increment B every theme carries its own confidence, so `_match_confidence` (`virlo.py:507`) — the
digest's other reason to exist — becomes dead. A18 is what keeps the $0.25 defensible after that.

**Subtotal — A18: ≈ +18 lines.**

### 3.4b A19 — the Virlo funnel report · **~97 lines** · approved 2026-08-11

Operator request: *show how many images, slideshows, carousels and reels were returned from Virlo,
processed, and how many go into further processing.*

**Audit result: this is ~60% closing existing PRD gaps, ~40% new surface.**

#### What the operator sees today: nothing

Across **all 36 run folders in `output/`**, a paid run's console contains **zero** lines about Virlo volume
between the launch block and the spend table. `_restate` (`runner.py:516-523`) would say
*"this plan needs N distinct trend(s)…"* but is gated on `if assignment.dropped or session.opts.interactive`
(`runner.py:522`) — so a clean `--yes` run prints nothing at all.

Worse, `reference_shortfall`, `reference_image_dropped`, `trend_text_only` and `reference_free` have
**never fired once** in any of those 36 runs — so the operator cannot tell whether losses are zero or the
counters are dead.

#### Existing requirements not being met

**FR-77** (`prds/40-outputs-and-logging.md:100-113`), bullet 1, quoting the PRD's own example:
> *Each MCP server call (name, operation, duration, brief result summary; e.g., **"Virlo MCP: trends → 27
> trends found, top 5 confidence ≥ 0.82"**).*

Today's line is `virlo MCP: get_top_videos -> ok (1971ms)` — **no row count.** The PRD example explicitly
shows one. Not implemented.

**NFR-5** (`prds/10-pipeline.md:453`) — *"every skip with its reason… any creative's provenance must be
reconstructable from the two log files alone."* **Violated in six places**: dedupe, `_MIN_PANELS`
rejection, `_MIN_THUMBS` rejection, the download-budget truncation, `text_only` demotion, and the
inspiration trim are all silent. And `kie_job_submitted` (`render/kie.py:153-155`) logs **no reference
count**, so no creative's provenance is reconstructable.

**§10 rule 2** (`prds/10-pipeline.md:400`) — three-places rule. `trend_text_only` and
`reference_shortfall` reach the run log only.

**FR-84** (`prds/40-outputs-and-logging.md:145`) — the headline must make a run *"shrunk by trend supply"*
legible at a glance. Today that is legible only as an exit code and a `no_trend_available` token.

**`virlo_payload` currently reports the wrong numbers.** `virlo.py:190` passes `len(clips)`/`len(panels)`
**before** `_build_item` dedupes at `virlo.py:261`. The operator reads what Virlo shipped, not what the
pipeline used — measured 11 duplicate rows on a real 3-monitor run.

#### The console block — literal text, printed once per run

```
Virlo funnel — 3 monitor(s) asked, 50 row(s) per call, 0 failed
  input   150 video(s) + 139 slideshow(s); 11 duplicate row(s) dropped
  sets    107 coherent set(s) qualified; 41 too thin (<3 panels / <2 frames)
  chosen  3 fresh, 0 repeated, 0 last-resort; motion 1 same-creator, 2 fresh
  images  18 of 18 downloaded, 0 dead URL; cap 6 per trend
  verdict 3 eligible, 0 excluded by history, 0 unusable, 0 without images
  render  6 job(s) will attach 3 trend ref(s) + 1 inspiration each
```

Widths 55–76, all under FR-286's 78. **Trend names never appear** — they are the unbounded token, so no
`fit()` is needed on any line. Degraded shapes use the same block:

```
  images  14 of 18 downloaded, 4 dead URL; 1 trend fell to text-only
  render  4 job(s) will attach 3 trend ref(s); 2 dropped, no trend left
```

Plus one row under FR-84's headline in `_spend_table`:

```
requested 6 creatives, delivered 5
  virlo   289 post(s) -> 107 set(s) -> 3 trend(s) -> 15 ref(s) on 5 job(s)
```

⚠️ Use `->`, not `→`. `util.fit`'s docstring (`util.py:158`) names `·`, `—`, `…`, `←` as the only glyphs
proven safe on legacy conhost. `→` is not on that list.

#### Where it prints — and one place it cannot

⛔ **Not in the cost estimate.** `runner.py:307` runs `_confirm` and `runner.py:313` runs `_collect` — the
money gate is **before** Collect, so no Virlo number exists when the estimate prints. Moving Collect above
the gate would break FR-59 (*"a decline contacts nobody"*, `runner.py:387`).

Three places, matching §10 rule 2:
1. **After Select, before Analyze** (`runner.py:318`, beside `_restate`) — both the counters and
   `Selection`/`Assignment` exist, and it is before any LLM or render spend, so the operator can Ctrl+C on
   a bad funnel.
2. **Both previews** (`previews.py:108`, `:136`) — FR-139 demands it: *"an operator who previews ten trends
   and gets three creatives should have seen exactly which seven were going to fall away and why."*
3. **Final summary** — the one `virlo` row.

**Unlike `_restate`, the funnel block prints unconditionally.** "Everything worked" is exactly the answer
the operator is asking for.

#### ⚠️ Input vs output vocabulary — do not conflate

The request said *"images, slideshows, carousels, reels"*, which mixes two disjoint vocabularies:

| | Words | Meaning |
|---|---|---|
| **INPUT** (Virlo) | video, slideshow, panel, frame, post, set | Evidence. Never rendered |
| **OUTPUT** (ours) | image, carousel, reel, creative, job | What we generate |

A Virlo **slideshow is not a carousel** — it gives the trend *carousel affinity* (FR-90, `virlo.py:284`).
The block enforces the split structurally: input words appear only on `input`/`sets`/`chosen`/`images`;
output words only on `render` and in the spend table.

**Never write "3 slideshows → 2 carousels".** The correct sentence is: *"the chosen set for 3 of 3 trends
came from a slideshow, which is why 2 carousels were planned."*

#### Machine-readable record

One new `collect_funnel` event emitted **once per run** from `virlo.fetch()` (so previews get it
identically), with nested `input` / `sets` / `choice` / `images` / `caps` objects. Plus three amendments:
`virlo_payload` gains `videos_raw`/`slideshows_raw`/`total_available` (and its *message* switches to the
deduped numbers — it lies today); `reference_choice` gains the fresh/stale split and the rejection counts;
`kie_job_submitted` gains `reference_count` + `reference_sources: {trend, inspiration, brief}`.

⚠️ `LogWriter._digest` (`outputs/logwriter.py:180-200`) truncates each value at 120 chars, so a nested
payload renders as one useless run.log line. **Split it:** `narrative()` carries the human block,
`event()` carries the nested record — the same split `_spend_table` already uses, at no extra cost.

#### ⚠️ Increment B interaction — designed in, not bolted on

The plan already flags that log volume goes 1 → 9–22× (§4.8). The funnel block answers it **by
construction**: it is a **run-wide rollup emitted once** from a single `Counters` object accumulated across
monitors after `asyncio.gather` — nine themes produce **one** seven-line block, not nine.

But `_payload_event`'s monitor-wide counts **must become theme-scoped in the same change**, or B ships a
known lie printed nine times ("50 videos, 50 slideshows" repeated per theme). Accumulate `Counters` at the
monitor level, attribute per-theme counts at the theme level, and the rollup reconciles.

Under B, add **one** line, never nine:
```
  themes  3 monitor(s) -> 14 theme(s); 5 capped by virlo_themes_per_monitor
```

⚠️ Do **not** add per-trend console output. `previews._verdict_block` (`:156-171`) already emits ~8 lines
per trend; at 22 trends that is 176 lines. Put the funnel block **above** the verdict list.

#### Cost

| File | Lines |
|---|---:|
| `sources/virlo.py` — `Counters` dataclass, threading, tallies, `collect_funnel`, enriched events, read `total` | +50 … +58 |
| `runner.py` — `_funnel_block()`, one `say()`, spend-table row, `_Session` field | +22 … +26 |
| `previews.py` — reuse `_funnel_block` at both sites | +4 … +6 |
| `sources/__init__.py` — re-export `Counters`, attach to `fetch()` | +4 … +8 |
| `render/kie.py` — reference count/sources on submit | +3 |
| `generate/refs.py` — return provenance counts | +4 … +6 |
| **Subtotal — A19** | **+87 … +107** |

Tests (~+70…+95, tracked separately from package lines) must assert: counter arithmetic reconciles, every block line
≤78 chars, the zero-material shape, and the degraded shape.

### 3.4c A20–A24 — the substance channel and its guardrails · approved 2026-08-11

Operator direction: *"we also want to use and utilize their copy / what the posts are about exactly and
their text content — we just want to give the posts our own branding spin, that way no plagiarism occurs."*
Plus: *"include into the console what all the posts those are and how our AI analyzed them."*

#### The sort question, answered: yes, and page 1 is enough

Confirmed live. `order_by=views&sort=desc` is already A1/A2. A second, unplanned benefit measured today —
**sorting also raises `intelligence{}` coverage**, because Virlo enriches its winners first:

| | unsorted | sorted by views |
|---|---|---|
| Videos with `intelligence{}` | 17/50 | **18/25** (72% vs 34%) |
| Slideshows with `intelligence{}` | 29/50 | **22/25** (88% vs 58%) |

So the sort fix is a prerequisite for everything below: it roughly doubles the substance data available.
One page of 100, sorted, beats twenty pages unsorted. **No pagination needed.**

#### What we currently discard — measured on the top posts today

Top video (14,268,292 views, `youtube.com/shorts/wqhJedUdY8Y`):

```
summary:            "This video tells a story about AI agents who initially believe they are
                     communicating with humans, as shown through close-ups of phone screens.
                     The narrative progresses to them rea…"
primary_topic:      AI agents interacting and security
secondary_topics:   AI security checks | autonomous AI communication
keywords:           AI agents | artificial intelligence | security checks | autonomous AI
category:           tech
content_format:     storytime
hook_type:          question
emotional_tone:     mysterious
sentiment:          neutral
transcript_quality: clean      transcript_word_count: 104
```

Top slideshow (5,487,494 views, `tiktok.com/@aifuture44/photo/7310888312766549254`):

```
summary:            "This slideshow explains that ChatGPT is not the only AI tool available,
                     revealing a comprehensive landscape of generative AI startups. The panels
                     transition from evocative black an…"
primary_topic:      AI tools for making money
secondary_topics:   Generative AI landscape | AI productivity hacks
keywords:           ai tools | make money online | generative ai | chatgpt alternatives
content_format:     explainer
panel_text_full:    "Panel 1: Remember.. >> Panel 2: ChatGPT isn't the only one >>> Panel 3: THE
                     GENERATIVE AI STARTUP LANDSCAPE AI-Mindset TEXT IMAGE AUDIO CODE CHATBOTS…"
panel_text_word_count: 31
trend_references:   ai | chatgpt
hook_type:          story_tease     emotional_tone: educational     sentiment: positive
```

**Every field above is currently fetched and discarded.** `summary` is dropped by the adapter
(`server.py:196`, `:233` normalize it; `virlo.py` never reads it). `primary_topic`, `secondary_topics`,
`keywords`, `category`, `content_format`, `panel_text_full`, `panel_text_word_count`, `trend_references`,
`sentiment` and `setting` are dropped by the **wrapper** and never cross the MCP boundary at all.

#### ⚠️ The plagiarism line — where it actually is

The operator's framing is correct, and it is worth stating precisely because the code must encode it:

| Safe to feed freely | Why |
|---|---|
`summary`, `primary_topic`, `secondary_topics`, `keywords`, `category`, `content_format`, `hook_type`, `emotional_tone`, `sentiment`, `setting`, `transcript_word_count`, `panel_text_word_count` | These are **descriptions about** the post, written by Virlo's own analyser. Reusing a description of a topic is not reproduction. Adapting a topic with a different angle is ordinary competitive practice. |

| Handle as exemplar-only | Why |
|---|---|
`hook_text`, `text_overlay_content`, `panel_texts`, **`panel_text_full`**, `description` | These are the competitor's **literal words**. They may enter a prompt as material to abstract a pattern from — the existing two-step move — and must never be reproduced into output. |

**So the change is asymmetric on purpose:** the *descriptive* layer becomes a genuine new input channel;
the *literal* layer stays behind the existing structural-mimicry discipline and gains an enforcement layer
it does not have today.

⚠️ **A20 and A21 are prerequisites, not options.** Adding `panel_text_full` — the complete panel-by-panel
copy of a winning deck — increases the raw volume of literal competitor text inside our prompts. Doing that
while `copy_degraded` still renders scraped hooks verbatim and `hook_pattern_used` is still unvalidated
would raise real reproduction risk. **Ship the guardrails in the same wave as the channel.**

---

#### A20 — a no-text tier before `copy_degraded` · **~15 lines** · MANDATED by the operator's "no plagiarism"

Today, `_fallback_copy` (`copywrite.py:315-334`) sets `headline = <competitor's exact hook_text>` and
`slide_texts = trend.panel_texts[:slide_count]`. That flows into `_onimage_text`
(`prompts_engine.py:588`), which emits:

```
headline (render verbatim): "<competitor's exact hook>"
  spelled out: <c-o-m-p-e-t-i-t-o-r-s  e-x-a-c-t  h-o-o-k>
```

into the block the render template calls *"the ONLY source of renderable words"*. For carousels it
reproduces the source deck's panel copy **slide for slide**. For reels it burns the hook into the seed frame
and locks it as a fixed graphic layer for the whole clip.

**Change:** insert a tier between the per-creative retry and `_fallback_copy`:
1. retry per creative (exists),
2. **NEW: emit a copy set with EMPTY on-image text** — `headline`, `subline`, `overlay_text`, `slide_texts`
   all `""`/`[]` — keeping a caption assembled from the *trend name and our niche*, never the source hook.
   Tag `DegradationTag.COPY_DEGRADED` as today plus a new `no_onimage_text` reason.
3. `_fallback_copy` **loses the verbatim path entirely** — `hook` is no longer sourced from
   `hook_texts` / `text_overlay_contents` / `panel_texts`.

The render templates already handle empty on-image text: `_onimage_text` returns `""` when there is no copy
(`prompts_engine.py:585-586`) and the image roles instruct the model to ignore empty labelled lines. A
text-free image on a proven layout is a usable creative; someone else's headline is not.

⚠️ Removes the justification in `copywrite.py:105` (*"a creative with borrowed words beats a creative with
none"*). Amend that docstring in the same edit — it is the reasoning being overturned.

#### A21 — validate `hook_pattern_used` · **~12 lines**

The copywriter template says (`copywriter_system.md:59-61`): *"It is logged and audited; a generic value
like 'curiosity hook' is a failed answer."* Verified by grep across `hypesocials/`: the value is
**stored, logged, written to `meta.yaml`, shown in the gallery — and never checked**. `copywrite.py:311`
accepts `str(payload.get("hook_pattern_used") or "")`, empty string included.

**Change:** a small validator — minimum length, at least N distinct content words, and a blocklist of the
generic phrases the template itself names (`curiosity hook`, `engaging hook`, `attention grabber`, `hook`,
`pattern interrupt` alone). Failing values trigger **one** re-ask of that creative; a second failure logs
`hook_pattern_generic` and tags the asset. Real values from a live run — *"Curiosity-and-reveal claim,
second person, direct address with a withheld subject…"* — pass comfortably, so the bar is real but not
tight.

#### A22 — rank the exemplars, and use the real hashtags · ~~**~10 lines**~~

> ⛔ **SUPERSEDED by `plans/xmasterplan-copy-voice-transposition.md` §3.5** (operator decision 2026-08-11).
> That plan implements view-ranking properly, as a real merge over the video+slideshow union rather than a
> sort inside each list. **Do not implement A22.** The hashtag half survives inside A14.

`_texts` (`virlo.py:481-488`) takes **the first 5 in array order** with no ranking:

```python
for row in rows:
    if value and value not in out: out.append(value)
return out[:_MAX_EXEMPLARS]
```

So a 400-view hook outranks a 4,000,000-view hook if it appears earlier. `_trend_texts` labels the result
"Winning hooks" (`prompts_engine.py:513`) — aspirational, not true.

**Change:** sort candidate rows by `views` descending before `_texts` selects. After A1/A2 the page is
already sorted, so this is mostly belt-and-braces — but `media = [*videos, *shows]` (`virlo.py:264`)
concatenates two independently-sorted lists, so slideshow hooks are currently crowded out entirely on a
video-heavy monitor regardless of their view counts. Merge-sort the union.

Plus (extending A14): thread the winning posts' real `hashtags` to the copy call as reference material.
Today `copywrite.py:337-340` invents hashtags from the trend-name slug on the fallback path while the real
ones sit unread.

#### A23 — the substance channel · ~~**~45 lines**~~

> ⛔ **SUPERSEDED, and one paragraph of it is REVOKED.** See
> `plans/xmasterplan-copy-voice-transposition.md`. A23's prompt paragraph instructed the model to *"find the
> equivalent claim in our niche"* — the **exact opposite** of the operator's binding decision of 2026-08-11,
> which is **same exact topic, our words**. Building A23 as written would re-introduce the defect the copy
> plan exists to fix. `substance_carried_over` ships as **`claim_swap`** instead. **Do not implement A23.**

**Wrapper** (`virlo_mcp/server.py`) — `_norm_video` and `_norm_slideshow` additionally keep:
`summary`, `primary_topic`, `secondary_topics`, `keywords`, `category`, `content_format`, `sentiment`,
`setting`, `transcript_quality`, `transcript_word_count`, and for slideshows `panel_text_full` +
`panel_text_word_count`. (`hook_type`, `visual_hook_type`, `emotional_tone` already arrive via A13.)

**Adapter** (`sources/virlo.py`) — new `TrendItem` fields, all view-ranked and capped like the existing
exemplar lists:

```python
post_summaries: list[str] = []      # `summary`, top 3 by views — WHAT the winners are about
topics: list[str] = []              # primary_topic + secondary_topics, deduped, top 6
source_keywords: list[str] = []     # `keywords`, deduped, top 10
content_formats: list[str] = []     # storytime | explainer | …, deduped
tones: list[str] = []               # emotional_tone + sentiment, deduped
panel_script: str = ""              # `panel_text_full` of the CHOSEN slideshow only
```

⚠️ `panel_script` is **literal competitor copy**. It is scoped to the chosen set (like `panel_texts` today),
routed to the **copy call only**, and never to a render role.

**Prompt** (`prompts_engine.py`) — `_trend_texts` gains four rows, keeping the existing labelled-row shape:

```
What the winning posts are about: <post_summaries joined>
Topics: <topics>          Source keywords: <source_keywords>
Format and tone: <content_formats> · <tones>
```

And a **new** `{{source_substance}}` slot, allowlisted for `copywriter_system.md` **and**
`style_brief_system.md` only, carrying `panel_script` inside the existing `<<<BEGIN DATA…>>>` fence.

**Prompt template** (`prompts/copywriter_system.md`) — one new short section, authored by
`prompt-engineer`, extending the two-step move from *form* to *substance*:

> the source's SUBJECT is material, not a target. Take what the winning post is about, find the equivalent
> claim in our niche, and write that. Same territory, our angle, our proof, our offer. Never restate the
> source's sentences; never name its brands or products.

⚠️ **Do not weaken `style_brief_system.md`'s never-transcribe rule** (`:91-122`). The substance channel is a
*copy*-side input. The analyst may see `post_summaries` and `topics` (descriptions), and gets
`{{source_substance}}` so it can reason about density — but the rule that literal strings appear only in
`exclusions` stands unchanged.

⚠️ `{{source_substance}}` must be added to `_TRUNCATION_ORDER` (`prompts_engine.py:73-77`), positioned
**before** `source_hooks` (i.e. cut earlier), or it becomes an uncuttable block under the char cap.

#### A24 — console: the post inventory and what the AI made of it · **~35 lines**

Operator request: show *which posts* these are and *how our AI analysed them*. Extends A19's funnel block
with a per-trend detail section, printed after Select and in both previews. Literal proposed output, every
line ≤78 chars (FR-286), URLs alone on their own line per carve-out (a):

```
Sources — AI Trends Tracker
  chosen  slideshow · 5,487,494 views · @aifuture44 · 3 of 8 panels
          https://www.tiktok.com/@aifuture44/photo/7310888312766549254
  about   AI tools for making money · explainer · educational/positive
  winners 3 post(s) read: 14.3M, 5.5M, 2.6M views
  hooks   "Remember.. >>" · story_tease
          "ChatGPT isn't the only one >>>"
  motion  fresh · 26,756,830 views · youtube.com/shorts (reel only)

Brief — AI Trends Tracker
  pattern Curiosity-and-reveal claim, second person, withheld subject
  angle   Automate the boring middle, not the flashy demo
  palette #F5F5F4 ground 80% · #C1391F accent 10% · #1A1A1A text 10%
  forbids 14 observed string(s) blocked from the frame
```

The `Brief` block is the answer to "how did our AI analyse them" — it surfaces `hook_pattern`,
`content_angle`, `palette` and the `exclusions` count, none of which an operator can see today without
reading `events.jsonl` with `verbose_only` enabled.

⚠️ **Increment B volume guard.** At 9–22 trends this section would print 9–22 blocks. Gate it: full detail
for the **first 3 trends by strength**, then one summary line — `+ 6 more trend(s), see events.jsonl`.
`--preview-sources` may print all (that is its purpose, FR-139); a paid run must not.

⚠️ Also fix in the same task: `StyleBrief` is **not persisted to `meta.yaml`** — `AssetRecord`
(`models.py:226-269`) has no brief field, so the brief exists only in `events.jsonl` under `verbose_only`
(`runner.py:587-589`). An operator judging a creative cannot see what the brief asked for. Add
`style_brief_summary` (pattern, angle, palette) to `AssetRecord` and the gallery card.

#### A25 — the echo check · ~~**~18 lines**~~ · found by simulating the design before building it

> ⛔ **SUPERSEDED by `plans/xmasterplan-copy-voice-transposition.md` §4** (`surface.echoes`). Same purpose,
> calibrated against real samples, sharing the offline measurement layer with the drift check, and with a
> stated resolution order so the two cannot oscillate. The ~18-line forecast was also wrong — it costed the
> check with no measurement layer beneath it. **Do not implement A25 standalone.**

**A live dry run of A23 was executed on 2026-08-11** (real MCP-shaped pull, sorted by views, real
`openai/gpt-5.6-luna` call, ~$0.005). The design works — substance carried over cleanly and the brand
landed. Full results in §3.4d. But it surfaced a gap no code review would have found.

Source hook: **`"Remember.. >>"`** → our generated headline: **`"Remember: the tool isn't the workflow"`**.

The model abstracted the *pattern* correctly ("a brief reminder followed by a contrarian correction"), and
then reused the source's distinctive opening word. That is not plagiarism — one common word, entirely
different claim — but it is the **first millimetre of the slope**, produced on the very first attempt, by a
model following the instructions. The second sample (`"Hello, can you hear me?"` →
`"Can you trace one workflow?"`) had zero overlap, so the behaviour is inconsistent, which is worse than
uniformly bad: it will pass review most of the time.

**Today there is no programmatic comparison between our output and the source strings anywhere in the
codebase.** The entire anti-plagiarism guarantee is prompt-level.

**Change:** after copy returns and before budgets are applied, compare each on-image string
(`headline`, `subline`, `overlay_text`, each `slide_text`) against the trend's literal set
(`hook_texts`, `text_overlay_contents`, `panel_texts`, `panel_script`):

- normalize both (casefold, strip punctuation, collapse whitespace),
- flag a **shared leading token** or any **shared 3-gram** of content words,
- on a flag: **one** re-ask of that creative naming the echoed string as forbidden,
- on a second flag: keep the copy, log `copy_echo_detected` with both strings, and tag the asset so it
  is visible in the gallery and the summary.

⚠️ **Deliberately not a hard block.** A shared stopword ("the", "you") must not fail a creative, and a
legitimately convergent phrase is possible. The value is that an echo becomes *visible and re-asked*
rather than silent. Tune the n-gram floor against the two real samples in §3.4d.

⚠️ **Pairs with A20, does not replace it.** A20 stops the engine *deliberately* reproducing a hook; A25
catches the model *accidentally* drifting into one.

#### A23 addendum — `substance_carried_over` becomes an audited field

The simulation asked the model to state what territory it took and how it made it ours. Both answers were
specific and checkable:

> *"Took the source's broad AI-landscape theme and made it practical for SMBs: the real starting point is not
> choosing an AI tool, but mapping one workflow end to end before automating it."*

That is exactly the audit trail `hook_pattern_used` provides for *form*, and the substance channel needs its
twin. **Add `substance_carried_over: str` to `CopySet` and `AssetRecord`**, validated by A21's rules,
logged, written to `meta.yaml`, and shown on the gallery card next to `hook_pattern_used`. Without it, the
substance channel has no reviewable output and nobody can tell adaptation from paraphrase after the fact.

**Subtotal — A20…A25: ≈ +140 lines.**

### 3.4d Simulation results — the design, dry-run on real data

Executed 2026-08-11. Read-only Virlo GETs (`order_by=views&sort=desc`, free) + one real copy call per
sample on `openai/gpt-5.6-luna`. Total spend ≈ **$0.005**. Prompt built to the A23 shape: brand block +
`WHAT THE WINNING POST IS ABOUT` fence (descriptive fields) + `LITERAL WORDS` fence (exemplar-only) + the
two-step move extended to substance.

**Sample 1 — slideshow, 5,487,494 views, @aifuture44**

| | |
|---|---|
| Their topic | AI tools for making money · explainer · educational |
| Their hook | `"Remember.. >>"` |
| Their summary | *"…explains that ChatGPT is not the only AI tool available, revealing a comprehensive landscape of generative AI startups…"* |
| **Pattern copied** | *"A brief reminder followed by a contrarian correction to a common assumption, withholding the practical takeaway until the second line."* |
| **Substance carried** | *"Took the source's broad AI-landscape theme and made it practical for SMBs: the real starting point is not choosing an AI tool, but mapping one workflow end to end before automating it."* |
| **Our headline** | `"Remember: the tool isn't the workflow"` — 37/42 ✅ ⚠️ echo |
| **Our subline** | `"Map the work first. Then automate what holds up."` — 48/60 ✅ |
| **Our CTA** | `Book the free AI audit at hypedigitaly.ai` — single ✅ |

**Sample 2 — video, 14,268,292 views, @AscendMindz**

| | |
|---|---|
| Their topic | AI agents interacting and security · storytime · mysterious |
| Their hook | `"Hello, can you hear me?"` |
| **Pattern copied** | *"A very short, direct question addressed to the viewer. It creates mystery by withholding the context, then invites them to inspect what is really happening."* |
| **Substance carried** | *"We carried over the idea of systems interacting without people fully understanding the exchange, and made it practical for business workflows: map every handoff before automating one."* |
| **Our headline** | `"Can you trace one workflow?"` — 27/42 ✅ no echo |
| **Our subline** | `"Map every handoff before you automate it."` — 41/60 ✅ |

**What the dry run proves**

- ✅ The substance channel works. Both outputs are about the same *territory* as the source with a genuinely
  different claim, and both routed through the brand's own `hook_angle` ("nobody measured the workflow").
- ✅ Character budgets were respected unprompted (37, 27 vs a 42 cap).
- ✅ The brand's `tone` and `avoid` rules held — no hype vocabulary, no fear-mongering, one CTA, no invented
  numbers.
- ✅ `substance_carried_over` is a usable audit artefact → promoted to a real field (addendum above).
- 🔴 One echo in two samples → **A25**.

**What it does not prove:** this used a hand-built prompt, not the shipped `copywriter_system.md`, and one
model call per sample with no sibling-distinctness pressure. Re-run it against the real template at the
Increment A barrier before calling the design validated.

### 3.5 Notion — dormant, and that is fine

Audited end to end: complete, careful code; npm package pinned and installed (`run.bat:24`); CLI and wizard
both expose it. **It has never executed a single MCP call in this repo's history.**

| Check | Result |
|---|---|
| `NOTION_TOKEN` in `.env` | ❌ absent — `preflight.py:195-198` force-downgrades to `off` regardless of config |
| `notion_pages` (`default.yaml:175-179`) | ❌ all four lists empty |
| Mode in shipped configs | ❌ `off`; both HypeDigitaly configs omit the key entirely |
| `notion_*` events across 33 run folders | ❌ zero |
| Test coverage of fetch/assemble/extract | ❌ none |

**No work in this plan.** A11 deliberately **decouples `{{brand_accent}}` from Notion** so brand colour stops
depending on a circuit that has never been energised. If Notion is switched on later, three untested paths
run for the first time in anger: `_fetch_tool` name resolution against the real 2.5.1 server, `_flatten`
against the real payload shape, and `_brand_marks`' regex extraction. Budget a spike, not a config flip.

### 3.6 Noted, not scheduled

- **`prompts_dir: null`** (`hypedigitaly.yaml:58`) — the per-niche prompt-pack override is fully wired
  (`runner.py:275`) and points nowhere. **Zero-code lever available today:** create the folder, copy the
  templates, edit them. Highest-control, lowest-effort steering the operator has.
- **`RenderParams.resolution` is never set** for any image job (`generate/__init__.py:293`), so every
  gpt-image-2 render is `"1K"` (`profiles.py:147`) while `budget.py` prices 1k/2k/4k tiers. Possibly a
  quality lever left on the table — needs a cost/quality decision, so it is flagged, not planned.
- **`Mix.ref_source`** (`inspiration.py:83,144`) — computed, never read; provenance re-derived at
  `generate/__init__.py:553-564`. Dead field.
- **`TrendItem.monitor_id` / `.source`** (`models.py:114,116`) — written, never read.
- **`winning_video_url`** is computed on every trend every run and consumed only by reel entries
  (`runner.py:538-541`) — dead work with the shipped `reel: 0`.

### 3.3 Waves — Increment A

**Dispatch: FLAT (CLAUDE.md §9a).** No trigger fires; no orchestrating parent. Conductor applies wire-in.

| Wave | Tasks | Assignee | Path set | Barrier |
|---|---|---|---|---|
| **A0** | A-P3…A-P9 | `technical-writer` | `prds/**`, `spikes/RESULTS.md` | **Conductor re-reads every amended anchor against the file.** The last Wave-0 agent on this repo shipped a wrong FR, missed 5 edits and deleted an abort cause — reports are not evidence |
| **A0′** | A-P1, A-P2 | **conductor** | `CLAUDE.md`, `NAVIGATION.md` | Governance files are not delegated. Re-baseline printed |
| **A1** | A5, A6, A7, A8 (LLM) ‖ A1 (wrapper) | 2× `python-pro`, one message | `llm.py`+`models.py`+`generate/analyze.py`+`vision_check.py` ‖ `virlo_mcp/server.py` | `pytest -q`; **offline** truncation-ladder test (stub `finish_reason == "length"`, `content == ""`; assert non-empty `reason` and only two attempts). **No network, no spend** |
| **A2** | A2, A3, A4, A10, **A13, A14, A18** | `python-pro` | `sources/virlo.py`, `virlo_mcp/server.py`, `generate/refs.py`, `runner.py`, `copywrite.py`, `configs/*.yaml` | `pytest -q`; `--preview-sources` shows sorted-range view counts |
| **A2′** | **A11, A12, A15, A16, A17** (steering) | `python-pro` ‖ `prompt-engineer` | `config.py`+`sources/inspiration.py`+`prompts_engine.py` ‖ `prompts/**` | `pytest -q`; an assembled prompt shows a **non-blank** `BRAND INFLUENCE:` line and a non-blank `SUBJECT AND SCENE:` on an override-brief image |
| **A2″** | **A19** (funnel) — runs AFTER A2/A2′ because it counts what they changed | `python-pro` | `sources/virlo.py`, `sources/__init__.py`, `runner.py`, `previews.py`, `render/kie.py`, `generate/refs.py` | `pytest -q`; the block prints on a real `--preview-sources`; **every line asserted ≤78 chars**; counters reconcile (input − dropped = output at every stage) |
| **A2‴** | **A20, A21, A22** (guardrails — ship BEFORE/with the channel) ‖ **A23, A24** (substance + console) | `python-pro` ‖ `prompt-engineer` | `copywrite.py`+`virlo_mcp/server.py`+`sources/virlo.py` ‖ `prompts/copywriter_system.md` | `pytest -q`; a forced copy failure renders with **empty on-image text**, never a scraped hook; a generic `hook_pattern_used` is re-asked; the console prints the post inventory and the brief |
| **A3** | test rework | `test-automator` | `tests/**` | Full `pytest -q`; `find`-based `wc -l` **reported with per-task attribution** (no cap) |
| **A4** | live verification | **conductor** | — | §3.4 |

`llm.py` and `models.py` are in one task because A7 spans both. `runner.py` has exactly **one** writer (A2).

### 3.4 Increment A live verification ⏰ before the trial expires ~2026-08-13

1. `--list-monitors` (free) → exit 0
2. `--preview-sources --config hypedigitaly` → view counts in the §1.1 **sorted** range, not the 2,534 range
3. `--preview-analysis --config hypedigitaly` → **zero** `llm_truncated` events *(costs LLM spend — label it)*
4. One paid run, low cap, 6 creatives → **6 visually distinct** reference sets, 6 distinct angles, exit 0
5. Force a degraded run → exits **1**, summary names the count

**Then decide Increment B against those 6 creatives**, not against a guess.

---

## 4. INCREMENT B — theme items (gated on A's result)

Full design retained; the review's corrections are folded in. **Do not start B before A4 is signed off.**

### 4.1 Shape

```
per monitor
  ├─ get_monitor_analysis(mid)                       → monitor fields + themes[]  (2 free GETs)
  ├─ get_top_videos(mid, views desc, 100, page 1)
  ├─ get_top_videos(mid, publish_date desc, 100, p1) → +14 evidence hits
  └─ get_top_slideshows(mid, views desc, 100, p1)
        ↓
  _reference_groups(...)  → ONE monitor-wide candidate list (FR-91 rules unchanged)
        ↓
  stride deal + evidence pre-pass  → exclusive, non-overlapping allocation
        ↓
  one TrendItem per theme, history_key = "<mid>::<stable_key>"
```

`_themes()` **never returns an empty list** — a monitor with no themes synthesizes exactly one
`_Theme(key="")`, producing today's item byte-for-byte. "Never fewer items than before" is structural.

### 4.2 Allocation — simplified per review

The first draft's 3-tier `_affinity` + round-robin `_claim` (~75 lines) is **cut to ~10**. Its own §4.3
conceded tier C was "far too loose to partition" and tier A recovers 8%. The distinctness comes from
**exclusive allocation**, not from scoring.

```python
own = [c for c in candidates if theme.evidence & set(c.refs.post_ids)]   # tier A only, ~8% hit rate
# then deal the remainder by stride — deterministic, non-overlapping, no rank pathology
own += [remainder[i] for i in range(theme_index, len(remainder), len(themes))]
```

A stride deal has none of round-robin's "theme #1 always eats the strongest slideshow" problem. Log
`N of M candidates claimed by evidence` so the 8% figure stays falsifiable. **Tiers B and C are dropped.**

### 4.3 `history_key`, and the migration question — corrected

**New key:** `f"{monitor_id}::{stable_key}"` (monitor id leads — `stable_key` collides across monitors).

The first draft claimed "a read-side shim cannot lose data." **Review refuted the conclusion, not the
mechanism:**

- `runner.py:451-452` genuinely flattens `used_posts()` across all keys — post-level protection is safe. ✅
- But `state.py:52 MIN_PRUNE_DAYS = 90` and `state.py:173 horizon = max(history_days, MIN_PRUNE_DAYS)` mean
  the stale flat entry survives **90 days**, not 7.
- And the shim *does* fan the monitor's date onto every theme. It only bites themes with no
  `chosen_post_ids` — i.e. exactly the `shared_refs` themes §4.2 predicts — which are then **excluded on
  day one for up to 90 days**. That is the precise regression the first draft cited as its reason to reject
  migration.

**Required specification (was missing, needs a test):** a `shared_refs` theme **must still set
`chosen_post_ids`** from the set it borrowed. Otherwise it hits the shim and gets monitor-excluded. If it
does set them, two themes must never record the *same* post ids — which the exclusive allocation in §4.2
already guarantees.

**Shim is 5 lines, not 4** — `plan.py:133` also reads `known.get(trend.history_key)` for
`TrendVerdict.last_used`; leaving it unshimmed reports a date from a key never consulted.

### 4.4 The `refs/` collision fix — three call sites, not two

```python
def refs_folder_name(source_key: str) -> str:
    """Collision-proof folder name for a run-level reference store (FR-71/150)."""
    return f"{slugify(source_key, 30)}-{hashlib.sha1(source_key.encode('utf-8')).hexdigest()[:6]}"
```

Applied at `packager.save_reference:100`, `reel.py:368`, and **`video_ref.py:200`** (§1.9 — the concurrent
`yt-dlp` overwrite the first draft missed). `gallery._refs_html:242` adds the spelling to its tolerant list;
verified that the raw `a::b` candidate is inert on Windows (`is_dir()` returns `False`, EINVAL is swallowed).

Fix in `packager`, **never** by shortening the history key — a key shortened to fit a folder name collides
elsewhere later.

### 4.5 Per-theme strength — with the review's amplification caveat

| Component | Weight | Per-theme source | Fallback |
|---|---:|---|---|
| `total_views` | .35 | `theme.total_views` | sum of resolved evidence rows → pool sum |
| `median_views` | .15 | median of resolved rows when ≥3 | `total_views / max(video_count,1)` |
| `velocity` | .30 | `total_views / (days_since(first_seen_at)+1)` | `_velocity(rows)` → pool |
| `confidence` | .20 | the theme's **own** confidence | absent ⇒ weights renormalize |

`_minmax` (`virlo.py:542-548`) returns `1.0` when `high - low <= 0` **and `high > 0`** — so with one
monitor every item has scored `strength = 1.0` and **FR-5 ranking has never discriminated in the shipped
config.** Confirmed.

⚠️ **Review caveat:** nine confidences spanning 0.85–0.95 get min-maxed onto 0.0–1.0, so a 0.10 real spread
discriminates at full 0.20 weight — amplifying noise. **Exclude `confidence` from min-max** and use it as
the absolute 0–1 value it already is.

### 4.6 Package split — 2 files, not 4

The first draft's `__init__`/`fetch`/`themes`/`refs` cut fails §18. `fetch.py` would be ~60 lines of
call-once pass-throughs (§18's first shallow-module red flag), and the leaf helpers (`_num`, `_when`,
`_texts`, `_dedupe`, `_warn`, `_velocity`, `_post_id`) are shared by all three — forcing either a 5th
module or sibling cross-imports.

**Worse: a globals-alias trap the first draft never flagged.** `_CACHE`, `_CACHE_DIR`,
`_CACHE_DIR_OWNED` (`virlo.py:72-74`) are rebound via `global` in `_cache_dir()` and `cleanup()`. A facade
doing `from .refs import _CACHE_DIR` holds a **stale alias** — `cleanup()` silently fails to remove the temp
dir (FR-249 violated, every run, no error). Tests poke these names directly
(`test_virlo_refs.py:73-77,455`).

**The one seam with no shared internals:**

```
sources/virlo/
  __init__.py   # adapter: fetch, MCP calls, normalization, themes, allocation, build, score
  media.py      # the CDN cache: _CACHE/_CACHE_DIR globals, _download_references, _download,
                # _cache_dir, reference_paths, cleanup — ~110 lines behind 3 functions
```

`media.py` is genuinely deep. §3a says >500 lines is a *candidate* for splitting, not a mandate — one
~840-line `__init__.py` with one responsibility beats four files with a chatty interface.

Verified: `sources/__init__.py` needs **zero** edits — `:29` and `:32` both resolve against a package whose
`__init__.py` re-exports.

### 4.7 Degenerate cases

| Case | Behaviour |
|---|---|
| `/trends/latest` non-200 | Fall back to `analysis_data.themes[]`; log `virlo_theme_source=analysis_data` |
| No themes at all | `_themes()` synthesizes exactly one `_Theme(key="")` → today's item exactly |
| Theme with 0 evidence | Stride deal only; `frozenset() & x` never raises |
| Evidence but no resolvable rows | Reel still gets tier-0 motion from `evidence_videos[].url` (yt-dlp needs no row) |
| Missing `stable_key` | `slugify(name, 0)` → `f"t{rank}"`. Never empty |
| Duplicate `stable_key` on one monitor | `::<key>#2`. Otherwise `runner.py:321` / `previews.py:138` build `{history_key: trend}` and **silently drop an item** |
| `virlo_themes_per_monitor = N` | Top N by rank; rest logged `themes_capped` |
| **`virlo_themes_per_monitor = -1`** | **Legacy kill switch** — forces the synthesized empty theme, i.e. exactly today's behaviour. ~6 lines. The only way to un-ship B if verification fails with no calendar left. `= 1` is NOT a rollback (different key, different confidence source) |

### 4.8 Increment B additions the review demanded

- **`prompts_engine.py` has no owner in the first draft.** `_trend_texts` (`:506-518`) enumerates
  TrendItem fields by hand; nothing reaches a prompt without editing it. Assign it to the adapter task.
- **`TrendItem.name` must become theme-specific.** Otherwise `plan._asset_id` (`plan.py:296`) slugs the
  agent name for all nine, so the operator cannot tell nine subjects apart in `output/`, and
  `virlo.py:129 _match_confidence(item.name, …)` applies one digest confidence to all nine.
- **Log volume goes 1 → 9–22×.** `virlo_payload` (`:194`), `reference_choice` (`:303`), `trend_verdict`
  (`runner.py:474`) all fire per item. Worse, `_payload_event` prints monitor-wide counts, so it would
  print "50 videos, 50 slideshows" nine times — actively misleading. Needs per-theme counts + a rollup.
- **Cost, out loud:** today 1 trend → 1 analysis + 1 copy → 2 creatives. After B: 6 themes → **6 analysis
  calls (6 vision images each) + up to 6 copy calls** → ~**6× LLM spend per run**, against CLAUDE.md's
  "<$1 per post" target. `_stamp_provisional` (`runner.py:~810`) already quotes worst case at the Confirm
  gate, so it is not a surprise — but *actual* spend now rises to meet a quote it has never met.
- **`_MAX_THEMES` is not a standalone constant.** `virlo.py:61` is a 4-way unpack
  (`_MAX_TACTICS, _MAX_THEMES, _WHY_MAX_CHARS, _CONTEXT_MAX_CHARS = 12, 3, 1200, 600`), read at `:438`
  where it gates **both** the confidence mean **and** the `why_it_works` concatenation. Removing it changes
  two behaviours.
- **Wave 6 test estimate was off ~10×.** There is exactly **1** direct `_build_item` site
  (`test_virlo_refs.py:252`, inside the `_item()` helper) and **0** `_monitor_item` sites — not "~12".
- **Test rework must live in the wave that breaks it.** `test_virlo_refs.py` reaches into `_build_item`,
  `_reference_groups`, `_pick_set`, `_download_references`, `_CACHE*`. A `pytest -q` barrier on the adapter
  wave is unachievable unless the test task ships in the same wave (disjoint path: `tests/` only).
- **`mcp-developer` is not in CLAUDE.md's roster.** `virlo_mcp/server.py` is 332 lines of ordinary async
  Python with a decorator — assign to `python-pro`.

### 4.9 Increment B waves (flat, no orchestrating parent)

| Wave | Tasks | Assignee | Barrier |
|---|---|---|---|
| **B0** | PRD amendments P1–P4, P7–P12 | `technical-writer` ‖ conductor (governance files) | Conductor verifies every anchor |
| **B1** | `models.py`+`config.py`+`configs/*` ‖ `packager.py`+`gallery.py`+`reel.py:368`+`video_ref.py:200` | 2× `python-pro` | `pytest -q` |
| **B2** | `virlo_mcp/server.py` (2nd endpoint, `_norm_theme`) | `python-pro` | `pytest -q` + one free `--list-monitors` |
| **B3** | `sources/virlo/` package + themes + allocation + `prompts_engine.py` ‖ `tests/test_virlo_refs.py` rework | `python-pro` ‖ `test-automator` | `pytest -q`; `--preview-sources` ≥6 trends; `find`-based `wc -l` |
| **B4** | `plan.py`+`previews.py` ‖ `runner.py` (single writer, LAST) | 2× `python-pro` | `pytest -q`; `--preview-analysis` ≥6 briefs *(spends money — cap the barrier run)* |
| **B5** | new coverage + regressions | `test-automator` | Full green; final `wc -l` with per-task attribution |
| **B6** | live verification | conductor | ≥6 distinct trends, distinct refs, `shared_refs` visible |

**Mandatory regressions:** zero-theme monitor yields exactly one item with `history_key == monitor_id`;
two monitors sharing a `stable_key` get distinct keys **and** distinct `refs/` folders; `offset` is never
sent; a `shared_refs` theme sets `chosen_post_ids`.
All filesystem work via `tmp_path`; never the real `logs/` or `output/`; no real API key.

---

## 5. Aggregating files — single writer, LAST

| File | Owner | Increment |
|---|---|---|
| `runner.py` | A2, then B4 | one writer per increment |
| `configs/*.yaml` | A2 / B1 | |
| `sources/virlo/__init__.py` | B3 | |
| `CLAUDE.md`, `NAVIGATION.md` | **conductor** | never delegated |
| `prds/00-overview.md` | A0 / B0 | |

---

## 6. Risks

1. **Do not market B as "each theme uses its own posts."** 3 of 9 themes get zero evidence; slideshows
   never have any. Ship `shared_refs` visibly.
2. **Deep pagination** — ~20 GETs/monitor for an invisible gain. Rejected. Honest lever is `start_date`
   windowing (+9 hits, 0 extra calls).
3. **`stable_key` alone as a history key** — collides across monitors, verified.
4. **Migrating `trend_history.json`** — would exclude all themes on day one.
5. **A sixth MCP tool** — FR-118 pins five; fold `/trends/latest` into `get_monitor_analysis`.
6. **B's ~6× LLM spend** (§4.8) against the "<$1 per post" target.
7. **`slugify`'s 40-char truncation is a live defect today** — two monitors sharing a 40-char prefix
   already collide. B merely makes it certain.
8. **`10-pipeline.md` FR-76 vs FR-73** — FR-76 says `analysis_missing: true` (bool), FR-73 says a
   `degradations` tag list. Out of scope; logged for a later D15.
9. **Two NFR-111 floor enforcements** (`config.py:725-737`, `llm.py:269-279`). Both live, both warn.
10. **The $0.25 digest is now near-dead weight.** `_match_confidence` (`virlo.py:507`) exists only to fill
    `confidence` when themes don't supply one — after B they always do. Its sole remaining contribution is
    `cross_monitor_context`, while it discards the `top_exemplars[]` you pay for. **Decide** after B:
    surface exemplars, or default `include_digest: false`.

---

## 7. Definition of done

**Increment A**
- [ ] ⛔ Ceiling command fixed in `CLAUDE.md` + `NAVIGATION.md`; re-baselined at 14,176 via `find`
- [ ] All PRD anchors verified against the files by the conductor, not by report
- [ ] `--preview-sources` view counts in the sorted range (§1.1)
- [ ] **Zero** `llm_truncated` events in a full `--preview-analysis`
- [ ] 6 creatives from one trend have **6 different reference sets** and 6 different angles
- [ ] A fully-degraded run exits **1** and names the count
- [ ] **`BRAND INFLUENCE:` is non-blank** in an assembled image prompt (A11 — it has been blank on every run ever made)
- [ ] **`SUBJECT AND SCENE:` is non-blank** on an override-brief single image (A12)
- [ ] `hook_type` / `emotional_tone` visible in the analysis prompt; real hashtags reach the copy prompt
- [ ] `niche.visual_world` reaches an image prompt in **`direct`** mode (A15)
- [ ] `top_exemplars` reach the reference pool as a last-resort tier, logged `reference_source=digest_exemplar` (A18)
- [ ] **The funnel block prints on every run and both previews** (A19), unconditionally
- [ ] **A forced copy failure renders with EMPTY on-image text** — never a scraped hook, never the source deck's panel copy (A20). Asserted in a test
- [ ] `_fallback_copy` no longer reads `hook_texts` / `text_overlay_contents` / `panel_texts` at all (A20)
- [ ] A generic `hook_pattern_used` is re-asked once, then logged as `hook_pattern_generic` (A21)
- [ ] Hook exemplars are **view-ranked** across the merged video+slideshow union (A22)
- [ ] `summary`, `primary_topic`, `keywords`, `content_format`, `emotional_tone` reach the copy prompt (A23)
- [ ] `panel_text_full` reaches the **copy call only** — never a render role (A23)
- [ ] Console prints the post inventory **and** the brief (pattern/angle/palette/exclusion count) (A24)
- [ ] **An echoed source string is re-asked once, then logged `copy_echo_detected` and tagged** (A25)
- [ ] `substance_carried_over` is validated, logged, in `meta.yaml`, and on the gallery card (A23 addendum)
- [ ] The §3.4d dry run is **re-executed against the real `copywriter_system.md`** at the barrier
- [ ] At >3 trends the detail section collapses to `+ N more trend(s)` on a paid run (A24)
- [ ] `style_brief_summary` is persisted to `meta.yaml` and shown on the gallery card (A24)
- [ ] Every funnel line ≤78 chars, asserted in a test; input/output vocabulary never conflated
- [ ] `virlo_payload` reports **post-dedupe** counts (it reports pre-dedupe today — a live inaccuracy)
- [ ] `kie_job_submitted` carries `reference_count` + `reference_sources` (NFR-5 provenance)
- [ ] `pytest -q` green; `find`-based `wc -l` **reported with per-task attribution** (no cap — §2.4)
- [ ] `A3` barrier reports `wc -l` with **per-task attribution**, never a bare total (rule 5)
- [ ] Live verification before the trial expires ~2026-08-13

**Increment B** (only after A is signed off)
- [ ] ≥6 distinct trends from one agent, distinct `refs/` folders per theme
- [ ] Zero-theme monitor still yields exactly one item
- [ ] `virlo_themes_per_monitor: -1` kill switch verified working
- [ ] `find`-based `wc -l` reported with per-task attribution
- [ ] `NAVIGATION.md` updated
