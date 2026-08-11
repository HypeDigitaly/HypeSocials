# xmasterplan — a first run that works: fresh reference sets, free refusals, and a wizard that explains itself

**Status:** awaiting operator approval — **v2, rewritten after a 4-reviewer round rejected v1's core mechanism**
**Date:** 2026-08-10
**Trigger:** the operator's first-ever `run.bat` walkthrough. Three runs, three failures:
`20260810_123057_g0pg` (exit 2, cap $0.01), `20260810_123102_wkp9` (exit 3, 7-day monitor lockout),
`20260810_123845_c832` (exit 3, empty `virlo_monitor_ids`, **$0.64 approved first**).
**Supersedes:** `plans/quickfix-virlo-monitor-ids-preflight.md` (never approved; absorbed with corrections).
**Operator decisions carried in:** post-level trend freshness approved · UX level 3 approved ·
**G2 ceiling 13,500 → 14,000** (measured 13,486 at HEAD, so 514 lines of headroom) ·
**reel motion-reference freshness added to scope** (§2.3, operator request after the v2 draft — it was
originally deferred, and the deferral was wrong: the mechanism it needs is already being built).

> ## Review round 1 — what it killed (read this first)
>
> Four reviewers (`architect-reviewer`, `python-pro`, `code-reviewer`, `cli-developer`) read v1
> independently. The architect returned **REJECT** on the identity half; all four converged on the
> same root error and the same replacement.
>
> **v1's mechanism was cosmetic.** v1 had `plan.select()` reorder `reference_groups` so a fresh set
> landed at index 0. But every field that shapes the creative is computed **once, earlier**, from the
> *original* group 0 — `panel_texts`, `narrative_arc`, `text_density`, `is_slideshow`, `virlo_url`
> (`virlo.py:246,261-269`) — and the style brief flattens **all** groups into a set, so reordering
> changes the order and not the input (`runner.py:551-553`). Result: headline, caption, hook pattern
> and rendered style all repeat; three CDN URLs differ. v1 would have satisfied the letter of FR-7
> and none of its purpose, while reporting success.
>
> **And it bought 2× throughput, not daily use.** `virlo.py:318-322` caps *candidates* at
> `media_download_cap` (6) ÷ `reference_images_per_job` (3) = **exactly 2 sets per monitor** —
> measured live at `output/20260809_210026_m9zy/run.log:16,21,25` (`refs 6 image(s)`, all three
> monitors). Meanwhile `spikes/RESULTS.md:163` records **36 of 50 slideshows qualifying** per
> monitor. v1 built ~34 candidate sets, threw them away, then rationed the 2 survivors.
>
> **A cost claim v1 used to justify a design decision was wrong.** v1 rejected per-post re-keying by
> asserting a "3–10× LLM cost increase" from `budget.py:387-416`. False: those functions count
> distinct `trend_key`s **present on the plan entries**, bounded by plan size via
> `runner.py:326`/`:770`, not by post count. The rejection still stands on its other grounds
> (pool-wide strength rescale `virlo.py:431-438`, `batch_ceiling` `plan.py:347`, `refs/<trend_key>/`
> naming, and all three clauses of `20-integrations.md:97`) — but the false number is struck, and
> **must not reach the PRD amendment log**, which v1 instructed.
>
> Also struck: two state files (one responsibility split across two locks — the second write would
> have deleted the first's lock file), a pre-flight warning that fires every day for a week, an error
> gate that turned a partial success into a total refusal, a `?` key that silently advanced three
> steps, a quick-run that landed on the broken config, and `models.py` fields that crash at import.
> Every one is corrected below. Six wrong file:line citations were found and fixed.

---

## 1. Root causes — three defects, one shape

All three failures share a shape: **a fact the engine already knew locally was withheld until after
the operator had committed** — money, time, or attention.

### 1.1 Empty `virlo_monitor_ids` is never checked before the money gate

`configs/default.yaml:40` ships `virlo_monitor_ids: []`. `sources/virlo.py:92-95` short-circuits and
returns `[]` **before** `SessionPool` opens at `:97` — no subprocess, no Virlo call
(`c832/run.log:32`: `0 trend(s) collected (4ms)`). `plan.select([])` → `runner.py:465-466` → exit 3.

`preflight.py` has **no** check on the key (repo-wide it appears only at `config.py:107`,
`runner.py:198/475`, `virlo.py:92-94`). Pre-flight returned `ok=True` (`run.log:8`), the estimate was
printed, **$0.64 was approved** (`run.log:30`), and then the run died on a $0-knowable local
misconfiguration. That contradicts `preflight.py:13-14` — *"**Refusal is free** (FR-202 code 2):
every check here is local"* — and its own FR-135 precedent at `:197-213`, where a named-but-unbuilt
adapter refuses **before** the gate.

Two aggravators: the one useful sentence goes to `log.warn`, not the console (`virlo.py:94`, visible
only at `run.log:31`); and the abort text (`runner.py:474-476`) tells the operator to check that
their ids *"name monitors this key can see"* when Virlo was never contacted — burying the real
diagnosis, `(none configured)`, between two misleading instructions.

### 1.2 History identity is the MONITOR, so 3 monitors = 3 runs per week, forever

`virlo.py:252` sets `history_key=str(monitor_id)`; `logs/trend_history.json` is keyed by monitor UUID
today. `plan.py:124-127` excludes any trend used inside `trend_history_days` (default 7).

The operator has 3 monitors and packaged on all three on 2026-08-09. **Every** run against
`hypedigitaly.yaml` exits 3 until 2026-08-16. That is `wkp9` — and it is the second logged famine of
this exact kind; `00-overview.md:268` records the first.

FR-7 (`10-pipeline.md:82`) reads as anti-repetition. Under monitor identity it is a **throughput
cap** of `monitors ÷ trend_history_days`, and it does not even deliver the anti-repetition it
promises: nothing stops the engine re-using the *same winning post* once the 7 days lapse.

`wkp9` also shows what late knowledge costs: it approved $0.25, opened the pool, and spent 13.5 s on
real Virlo calls **including the metered `get_trends` digest** (~$0.25, `README.md:36`) — then
printed `total $0.00` (`wkp9/run.log:58`). That total is a **false statement**.

### 1.3 The wizard never explains itself; two of six steps explain nothing at all

Audited against (i) what does this do, (ii) what is a good value, (iii) what if I get it wrong:

| step | (i) | (ii) | (iii) |
|---|---|---|---|
| 1/6 Config `menu.py:142-169` | partial | weak | **none** |
| 2/6 Sources `:181-206` | **none** | **none** | partial |
| 3/6 Formats `:209-230` | **none** | **none** | partial |
| 4/6 Spend cap `:233-243` | **none** | **none** | **none** |
| 5/6 Mode & Notion `:246-259` | **none** | **none** | **none** |
| 6/6 Briefs `:262-283` | **none** | partial | partial |

Evidenced consequences, worst first:

- **At the money prompt, Enter means CANCEL.** The wizard trains "Enter keeps the value" seven times
  (`menu.py:66`, FR-57). Then `cli.py:295-298` accepts only `y`/`yes`; **anything else, including a
  bare Enter, silently declines** and prints *"declined at the confirm prompt"* — which reads like
  the operator erred. This is the single worst trap in the flow and it is in the tool today.
- **The picker cannot distinguish two of its three rows.** `menu.py:154` hard-slices at 78 chars, no
  ellipsis, no word boundary; today's row is **103 chars** and wraps on any 80-column console.
  `hypedigitaly.yaml` and `hypedigitaly-cs.yaml` have **byte-identical** `niche:` blocks (`:8-11`,
  single-line diff at `:19`), and `_describe` (`config.py:395-403`) reads only
  `audience`/`vibe`/`visual_world` — so both render identically. Both `hypedigitaly-cs.yaml:1` **and**
  `:9` still say **"EN"** on the Czech config. `default.yaml`'s row loses the word `off` from
  *"reels off"*, inverting its meaning.
- **"Not runnable" has no cure inside the tool.** The only route to monitor ids is
  `run.bat --list-monitors` — a **flag**, at a console reached by double-clicking. FR-65
  (`30-configuration-and-run.md:450`) mandates menu→flag parity; this is the reverse gap, and it is
  exactly what the episode was made of.
- **The Sources step never reads `virlo_monitor_ids`** (`menu.py:181-206`), so it accepted a source
  that could not return anything.
- **No price exists before step 7.** `cli.estimate_report` (`cli.py:309-344`) is the only price in
  the tool. The operator commits to counts and to a cap blind — which is how `$0.01` reached `g0pg`.
- **Counts silently merge.** `menu.py:225` `formats.update(counts)`: typing `images=1` leaves
  `carousels=2` in force, discovered at step 7.
- **`5/6 Mode & Notion` is six tokens with no semantics** (`:249-250`). Nothing says `analyzed` adds
  an LLM call per trend, `both` roughly doubles them, or that `notion` above `off` without
  `NOTION_TOKEN` is forced back to `off` three steps later (`preflight.py:191-194`).
- **The first question is a 50% dead end** — `[2] Publish` (`:123`) asks *which run*, then prints
  "not implemented" (`__main__.py:79`), unmarked.
- **Counters contradict themselves:** `1/6 … 6/6` then `7/7 Confirm` (`:134`).
- **No help affordance exists.** `Console.prompt` (`:65-70`) knows exactly two special inputs: Enter
  and `q`. Repo-wide grep of `hypesocials/*.py` for `README`, `--help`, `'?'`, `NAVIGATION` returns
  one hit, an internal comment.
- **`--help` is not a fallback.** `prog` is `hypesocials` (`cli.py:45`) — a command the operator does
  not have. `--config`'s help does not list the config names. `--preview-sources` advertises *"zero
  model spend"* (`:135`) while `previews.py:29-30` records that Virlo's metered digest still bills.
- **Lines the tool controls are not width-capped.** `_launch_summary` printed a **557-character
  single line** in `wkp9/run.log` by echoing the full 400-char niche descriptor. That is the conhost
  mangling the operator saw when copying the session out.
- **Silence reads as a hang.** `run.bat:30-33` all early-return on a warm start and print nothing;
  `__main__.py:64-65` sweep scratch and load `.env` silently.
- **`--preview-sources` gives a false all-clear on the very config it should condemn.**
  `previews.py:161-162` prints *"returned nothing — no trend to judge"* and `:108` returns
  **`EXIT_OK`**.

---

## 2. Design

### 2.1 The adopted mechanism: demand-driven reference-set selection, in the adapter

**The reference set, its post ids, its panel metadata, `is_slideshow` and `virlo_url` are one unit.
Choose the unit once, in the module that already owns coherent-set construction
(`virlo.py:13-15`), before anything is derived from it.**

1. `runner` already reads history before Collect (`:448`). Pass the used-post map **into** Collect:
   `sources.fetch(..., used_posts=...)`.
2. `_reference_groups` (`virlo.py:284-325`) builds **every** qualifying candidate — no
   `media_download_cap` gate at candidate time — each as one `ReferenceSet` value object carrying
   `urls`, `post_ids`, and the `primary` row it came from.
3. `_build_item` picks the **freshest unused** candidate and derives `panel_texts`, `narrative_arc`,
   `text_density`, `is_slideshow` and `virlo_url` from **that** candidate.
4. `_download_references` fetches the chosen set first, then tops up from other fresh candidates
   until `media_download_cap` — so the analysis call keeps its 6 images (FR-9,
   `30-configuration-and-run.md:110`) while the render job's group 0 is the chosen set.

Why this is strictly better than v1's rotation, point by point:

| v1 problem | fixed by |
|---|---|
| Rotation changed nothing that shapes the creative | every derived field comes from the chosen set |
| 2 candidate sets per monitor | ~36 per monitor (`spikes/RESULTS.md:163`) — the cap no longer gates *choice* |
| `reference_sources` / `reference_groups` index drift (broken in `virlo.py:476-478` **and** `inspiration.py:198-201`, both unowned in v1) | one object; there are no parallel lists to desynchronise |
| `plan.select()` mutating source-owned data, breaking its own purity contract (`plan.py:10-13`) | `select()` does not rotate; wave 3 shrinks to a 4-line predicate |
| `posts=None` fail-open default | freshness is enforced upstream; nothing to default |
| Downloads 6 speculative images | downloads the 3 it will use, then tops up |

**What `plan.select()` still needs (4 lines):** `TrendItem` gains `chosen_post_ids: tuple[str, ...]`.
When it is non-empty, freshness was already enforced upstream and the monitor-level window is
skipped. When it is empty — a `text_only` trend, which has no post identity at all
(`virlo.py:478`, `plan.py:148-150`) — the monitor-level window applies exactly as today.

### 2.2 One history file, no migration

v1 proposed a second file. Rejected on review: one responsibility, two locks, two prune horizons,
two writers that can each fail alone — and if they share `LOCK_FILE` (`state.py:41`), the second
write's `finally` unlink **deletes the lock the first is holding**.

**Adopted:** `logs/trend_history.json` keeps its shape and each entry gains one optional key:

```json
"623203a9-…": { "first_used": "…", "last_used": "…", "run_ids": [], "posts": { "<post_id>": "2026-08-10" } }
```

- **Backward compatible by construction.** An entry without `posts` reads as "no posts used" → every
  candidate is fresh. There is no migration, no schema version, and no window in which recency
  protection is silently off — the hazard v1 tried to dodge with a second file.
- One public writer: `outputs.record_use(trend_key, post_ids)`. One lock, one critical section, one
  status. **Never two calls, never `asyncio.gather`.**
- Posts inside an entry are pruned on the same pass as entries, against the same
  `max(trend_history_days, 90)` horizon (`state.py:141-148`).
- `read_history()`'s corrupt-file rule (FR-83) is unchanged, and now covers both dimensions at once.

### 2.3 Reel motion references are freshened by the same mechanism (added at operator request)

A reel takes two inputs: a **seed frame** (the hook text baked into a still) and a **motion
reference** — a real viral video downloaded by `yt-dlp` and handed to Seedance so the clip mimics its
movement. The motion reference is picked at `virlo.py:249` as `max(videos, key=views)` and stored at
`:268` as `winning_video_url`. Two defects follow, and both get worse once §2.1 lands:

- **It never changes.** View counts move slowly, so the same post stays #1 for days or weeks. Every
  reel from that monitor mimics the same source clip. §2.1 makes headlines, layouts and images fresh
  while the *motion* stays identical — visibly different reels that all move the same way. Today the
  monitor lockout hides this by preventing frequent runs; fixing the lockout exposes it.
- **On a slideshow-driven trend it is unrelated material.** When `is_slideshow` is true the images and
  copy come from a slideshow, but the motion reference is still "the top *video*" — a different post,
  usually a different creator and topic. Seedance is told to animate one creator's hook with a
  stranger's movement.

This is the most expensive creative in the tool — one reel priced at **$4.78** in the operator's own
W6 stress run, and another lost $4.78 to a timeout for nothing (`00-overview.md:271`). Paying that
for a clip that moves exactly like last week's is the worst value in the product.

**Fix — the same `used_posts` map, three-tier preference, evaluated in the adapter:**

1. a **fresh** video by the **same creator** as the chosen `ReferenceSet` (freshness *and* coherence —
   fixes both defects at once; slideshows carry `author_username`, `virlo_mcp/server.py:~225`);
2. else the highest-views **fresh** video;
3. else the highest-views video regardless — **best-effort, logged as a repeat.**

**Tier 3 is non-negotiable.** Motion-reference freshness must never block a reel: a repeated motion
source is a cosmetic loss, a failed reel is a paid loss, and the reel already degrades gracefully to
`in_model` when no reference is available. The choice and its tier are logged as one event, so a
repeating run stays explainable exactly as FR-7 requires of image exclusions.

`TrendItem` gains `winning_video_post_id`. Unlike v1 — which added that field with **no reader**,
dead code by `CODING_GUIDELINES.md:31` — it now has both a writer (tier selection) and a reader
(`record_use`).

**One accepted coupling, stated deliberately:** post ids share one namespace (Virlo UUIDs are
globally unique), so a video used as a motion reference also stales its own thumbnail inside any
creator-family image set. That is *correct* — same post, same content — and it slightly accelerates
image-set exhaustion. Acceptable against ~36 candidate sets and ~50 videos per monitor
(`spikes/RESULTS.md:163`, `wkp9/run.log:41`).

### 2.4 Deliberately deferred, on the record

- **The ~$0.25 metered-digest waste on a doomed run is not eliminated**, only disclosed. Gating the
  digest was declined twice by the operator (v1.6.4, v1.6.8). Instead: the estimate discloses that
  Virlo meters against the Virlo deposit, and `_final_line` stops claiming `$0.00`.
- **Stripping the ~35 PRD citations** from operator strings stays out of scope — five modules, many
  pinned by tests. **But** one new rule binds this plan: *any operator-facing string this plan
  rewrites ships without a citation on the console line; the citation moves to the `events.jsonl`
  field.* The seam already exists (`session.say` vs `session.log.event`, `runner.py:455-457`).
  Otherwise Wave 5's "assert on the specific message text" bakes new citations into new tests and
  makes the eventual strip more expensive than it is today.

### 2.5 PRD position (D15 — amendments land FIRST)

- §1.1 is a **gap**. `20-integrations.md:97` says a trend item is *"one per configured monitor id"*
  and `30-configuration-and-run.md:109` says `virlo_monitor_ids` is *"one or more"*, so zero ids is
  arithmetically incapable of producing a creative — locally knowable, for free, which is pre-flight's
  stated remit.
- §1.2 conflicts with **intent, not text**. FR-7/FR-82/NFR-24 describe monitor identity accurately;
  they encode a throughput cap nobody chose.
- **`20-integrations.md:97` survives intact.** All three clauses — one item per monitor, dedupe key =
  agent id, one history entry per real-world trend — remain true. One sentence is appended: post
  recency selects *among that item's candidate reference sets*.

**Re-opening REVIEW F-1 legitimately.** `REVIEW-v1.6-recommendations.md:30` declined loosening
`max_trend_reuses_per_run: 2` and `trend_history_days: 7`, under a heading reading *"do not
re-litigate without new facts"* (`:22`). **Both numbers stay.** What changes is what a history entry
*denotes*, which `:30` does not address. The new facts are the two logged famines: `wkp9` today and
`00-overview.md:268`. *(v1 also cited `00-overview.md:263` as a second ratification — checked, it
contains neither `F-1` nor `trend_history_days`. Struck.)*

**FR numbering — the FR-Range Rule (`00-overview.md:236`), not the FR-290 reserve.** The superseded
plan claimed `FR-290` for a 30-configuration requirement, which the rule forbids. Verified-free
blocks (zero hits in `prds/*.md` and zero repo-wide):

| new FR | file / block | subject |
|---|---|---|
| **FR-283** | 30-config (280–289) | pre-flight refuses a run no active source can serve |
| **FR-284** | 30-config | wizard self-description: purpose line per step, readiness rows, single-key `?` |
| **FR-285** | 30-config | quick-start action + `--quick`; monitor-id helper action; `--history-days` |
| **FR-286** | 30-config | width discipline + exit-code legend + honest Virlo-metering disclosure |
| **FR-153** | 40-outputs (150–159) | `posts` map inside a `trend_history.json` entry |
| **FR-154** | 40-outputs | `--preview-sources` exit code when nothing is eligible |

`FR-290+` stays reserved. Next free decision number is **D36**. Amendment version **v1.8.0**
(v1.7.1, reserved by the superseded plan, is released).

---

## 3. Changes

Owners: **[main]** conductor (aggregating files + wire-in) · **[pp]** `python-pro` ·
**[tw]** `technical-writer` · **[ta]** `test-automator`.

### 3.0 Wave 0 — PRD amendments · [tw] · `prds/10,20,30,40` (allowance: text only)

| file | edit |
|---|---|
| `10-pipeline.md` | **FR-7** (`:82`) — the window excludes the *individual posts already used*; a monitor is excluded only when it has no unused candidate set; `text_only` trends fall back to monitor identity; `0` still disables. **One clause for §2.3:** post recency also selects the reel's motion reference, three-tier, **best-effort — never a reason a reel is not produced.** **FR-24** (the reel/motion-reference requirement) gains the same clause, so the two cannot drift. **FR-8** (`:84`) — one clause: `usable_trends` still counts monitors, so the batch-ceiling arithmetic is unchanged. **§10 abort row** (`:411`) — "no monitor ids configured" moves from exit 3 to a **pre-flight** cause. **Exit table** (`:319-320`), **NFR-9** (`:461`, hard-codes the exit-3 cause list), and **`:323`** (*"preview modes exit 0 on success…"* — required by FR-154; v1 missed it). |
| `40-outputs-and-logging.md` | **FR-153** (new, after FR-152 at `:127`) — the optional `posts` map, its write condition, its prune, and that it shares FR-254's single lock. It holds **image-set post ids and motion-reference post ids in one namespace** (Virlo UUIDs are globally unique), and §2.3's accepted coupling is stated: a video used for motion also stales its own thumbnail inside a creator-family image set, which is correct because it is the same post. **FR-82** (`:133`) — add the key; state that an entry without it reads as no-posts-used, so no migration exists. **NFR-24** (`:137`) — restate at post granularity **and state that the interrupted-run resume property moves with it** (v1 wrongly claimed it stayed, and mis-attributed it to FR-89/FR-201). **FR-154** (new). **D12** (`:186`). |
| `20-integrations.md` | `:97` — keep all three clauses; append one sentence on post recency selecting among candidate sets. |
| `30-configuration-and-run.md` | **FR-283–286** (new, after FR-251 at `:416`). **§8 refusal list** (`:476-494`) — one bullet in the established style. `:109`, `:73`. **§5 CLI table** (`:375-397`) — `--quick`, `--history-days`. **§4 prose `:331` and `:343`** — both enumerate the pre-wizard choice as exactly two options; **`FR-56` (`:353`) names three that match neither the code nor this plan and is already stale.** All three amended (v1 missed all three). `:333-339` renumbered to seven steps; `:349` records the `?` key. **NFR-16 (`:500`) unchanged** — the count argument is sound; say so in the log. |
| `00-overview.md` | **D36**, FR registry (`:239-240`), `:45`. **Amendment log v1.8.0 inserted after `:271`** — not at EOF, because `:272` is a stale out-of-order v1.6.2 entry. Must record: the ceiling raise to 14,000 with the final measured count, the F-1 re-open with both famine run ids, the rejected per-post-rekey alternative **with its correct grounds and not the struck cost claim**, and the deferred reel-motion follow-up. **[main] writes this LAST** (§3.7). |

### 3.1 Wave 1 — the shared contract · [pp] · single writer (allowance ≈ 60 lines)

Four files, one owner, sequential. This is the barrier every wave-2 task imports. v1 designed only
two `models.py` fields and left the real abstraction undesigned — which is how wave 3 would have
discovered the fatal flaw with `virlo.py` already frozen.

| file | change |
|---|---|
| `hypesocials/models.py` | `ReferenceSet` value object: `urls: list[str]`, `post_ids: tuple[str, ...]`, `is_slideshow: bool`, `panel_texts: list[str]`, `narrative_arc: str`, `text_density: str`, `source_url: str \| None`, `author: str \| None` (the creator handle §2.3 tier 1 matches on). `TrendItem` gains `chosen_post_ids: tuple[str, ...] = ()` and `winning_video_post_id: str \| None = None`. **Every new field needs `field(default_factory=…)` or `= None`** — a bare annotation after defaulted fields is a `TypeError` at import (v1's spec crashed). |
| `hypesocials/config.py` | `ConfigSummary` (`:287-293`) gains the picker's scalars — `label`, `language`, `monitor_count`, `formats` — populated in `list_configs` (`:339-346`), which **already** parses every file, so the reads are free. Defaults come from the dataclasses (`RunConfig().formats`), never a second literal. New optional **`label:`** key preferred by `_describe` (`:395-403`) ahead of the niche join — this **solves** the truncation problem instead of managing it. `Config.min_single_creative_usd` property beside `reels_plannable` (`:275-284`), the single source for the price floor. `LOGS_DIR` moves here beside `CONFIGS_DIR` (one definition; `preflight` cannot import `runner`, which imports it). |
| `hypesocials/preflight.py` | `_check_prices` (`:274-276`) reads `Config.min_single_creative_usd` instead of deriving it. Net negative lines; removes a duplicate rule rather than adding one. |
| `hypesocials/cli.py` | `Options.quick: bool = False` only — the field `menu.py` needs in wave 2. Flags and help stay in T2e. |

**Barrier:** `pytest -q` **and** `wc -l`. A green suite here proves little (defaulted fields), so the
barrier is explicitly *"imports cleanly and the count is recorded"*, not *"tested"*.

### 3.2 Wave 2 — seven disjoint path sets, parallel

| # | owner | files (exclusive) | change | ≈ lines |
|---|---|---|---|---|
| **T2a** | [pp] | `sources/virlo.py`, `sources/inspiration.py` | Build **all** candidates as `ReferenceSet`s (drop the `room` gate at candidate time, `:318-322`); `used_posts` selects the freshest unused; `_build_item` derives every panel field from it and sets `chosen_post_ids`; `_download_references` (`:475-478`) fetches the chosen set then tops up to `media_download_cap`. `_reference_shortfall` (`:482-485`) must judge the **chosen** set. **Post-id rule:** prefer the row's `id` (stable UUID, `virlo_mcp/server.py:180` video / `:213` slideshow — v1 cited `:181`, wrong), fall back to `url`, then `f"{monitor_id}:{index}"`; **never `id(row)`**, the memory-address fallback at `:373`, which would change every run. `inspiration.py:198-201` (`_trimmed`) is included because it `replace()`s reference data and would otherwise desynchronise — **it was in no path set in v1**. Route the `:94` empty-ids warning to the console too. **§2.3's motion reference:** a `_pick_motion(videos, chosen_set, used_posts)` helper implementing the three tiers, setting `winning_video_url` + `winning_video_post_id` (replacing the bare `max(videos, key=views)` at `:249`), and logging the chosen tier — `fresh_same_creator` \| `fresh` \| `repeat` — as one event so a repeating run is explainable. Tier 3 always returns a video when one exists; it never returns `None` for freshness reasons. | 70 |
| **T2b** | [pp] | `outputs/state.py`, `outputs/__init__.py` | `record_use(trend_key, post_ids)` — one function, one lock, one status, writing entry + `posts` together. Extend `_prune` (`:141-148`) to prune `posts` on the same pass. Reuse `_age_days`/`days_since_use`; **do not fork them.** `read_history` unchanged in signature. Export from `__init__.py`. | 40 |
| **T2c** | [pp] | `preflight.py` | `_check_supply` (FR-283). **Error** when `"virlo" in active` · `action == "run"` · no non-empty monitor id · **and no entry could run without a trend** — i.e. error only when **no** entry has `brief_influence == "override"`. A *mixed* brief+trend plan gets a **warning** naming the entries that will drop, because `10-pipeline.md:411` mandates exit 1 with briefs shipped; v1's gate turned that into exit 2 with nothing delivered. **No warning branch for "all monitors in the window"** — after FR-7 that is not a supply signal and would fire every day for a week. `check()` already receives `action` and `entries` (`:138-144`); annotate `entries` as `Sequence[PlanEntry]` so the predicate is checkable. | 30 |
| **T2d** | [pp] | `menu.py`, `hypesocials/wizard_help.md` (new) | §3.5. | 75 |
| **T2e** | [pp] | `cli.py` | `--quick` (mutually exclusive with `--yes` — argparse error, one line: the combination is meaningless), `--history-days N` (importing `config.py`'s bound, not retyping it). `prog="run.bat"`. `--config` help enumerates `configs/`. `--preview-sources` help states the metered digest. Epilog: two worked examples + `README.md` pointer. `--publish/--promote/--at` marked `(Phase 2, not implemented)`. **Confirm prompt rewritten** (`:292-293`) to kill the Enter-means-cancel trap: `y = start · Enter or n = cancel, nothing is billed`. `estimate_report` totals (`:340-343`) disclose Virlo metering. **`Action.QUICK` is NOT added** — `quick` is a modifier like `--yes`, not one of FR-252's six standalone paths; a new enum member silently breaks `preflight._NEEDED` and `__main__.py:72`. | 40 |
| **T2f** | [pp] | `run.bat`, `configs/*.yaml` | `run.bat`: one warm-start line; carry the failing reason to `:44` (needs a `FAIL_REASON` variable at each failure site — not one line); fix `:60` to say **3.12+**, matching `:22`. Add `label:` to all three configs. Fix `hypedigitaly-cs.yaml:9` (`niche.audience` says **"EN"** on the Czech config) — **`:1` is dead work, `_describe` never reaches the line-1 fallback when a `niche:` block exists** (v1 specified it). Not counted against G2. | — |
| **T2g** | [ta] | `tests/test_preflight.py`, `tests/test_state.py` (both new) | Moved **into** this wave — v1 put every test in wave 5, where the wave-2 barriers could not detect a broken wizard, a broken `?`, or a broken picker. Disjoint from every other path set. See §3.6. | — |

**§9a check:** per-domain counts are `sources/` 1, `outputs/` 1, `tests/` 1, root module 4
(`preflight`, `menu`, `cli`, `run.bat`+configs) — all below the ≥5 trigger. Path sets are disjoint.
The shared module was designed in wave 1. **Flat wave, no orchestrating parent.**
**Barrier:** `pytest -q` + `wc -l` + acceptance 1, 2, 5.

### 3.3 Wave 3 — selection · [pp] · `plan.py` only (allowance ≈ 12 lines)

Shrunk from v1's 34 lines because the adapter now owns freshness.

`select()` (`:101-130`): when `trend.chosen_post_ids` is non-empty, skip the monitor-level window —
freshness was enforced upstream. When empty (`text_only`), apply `:124-127` exactly as today. The
`excluded` verdict label (`:71`) gains the post-exhaustion wording, because FR-7 requires exclusions
to stay individually explainable and `--preview-sources` renders these labels verbatim
(`previews.py:150`, FR-139). **No rotation, no mutation, no new parameter** — `select()`'s purity
contract (`plan.py:10-13`) is preserved rather than amended.

**Barrier:** `pytest -q` (including this wave's own `test_plan.py` extension) + `wc -l`.

### 3.4 Wave 4 — aggregating files and wire-in · [main] (allowance ≈ 45 lines)

| file | change |
|---|---|
| `runner.py` | Pass the used-post map into `sources.fetch` at `:432`. Replace the `record_trends` call (`:633-635`) with `record_use`. **`_package` needs a signature change** — `report.packaged_trends` is a `set[str]` of trend keys (`generate/__init__.py:155`), and the `TrendItem`s live in `by_key`, a local of `_pipeline` (`:306`); v1 said "call it beside" and would have produced a `NameError`. **Record the post ids the *attached* set actually used**, not the item's: under `inspiration_mix: exclusive` a creative attaches zero trend images (`generate/refs.py:69,72`), and burning those ids would be a lie. **Same rule for §2.3's motion reference:** record `winning_video_post_id` only when a reel packaged successfully **and the motion reference was genuinely attached** — a `yt-dlp` failure or a `seed_frame_url_unreachable`/reference-free degrade (`generate/reel.py:352-372`, `video_ref.py:104-222`) means it was never used, so its id must not be burned. `_famine_message` (`:473-476`) rewritten. `_final_line` (`:831-843`): exit-code legend, and `total $0.00 (Kie/OpenRouter)` so it stops implying Virlo was free. `--list-monitors` (`:196-198`) prints paste-ready YAML. `_launch_summary` (`:786-800`) truncates the description to the same ≤55-char budget as the picker — it is the source of the 557-char line. |
| `previews.py` | FR-154. **The decision must move inside the `else` branch** — `selection` is bound only at `:106`, so a condition at the shared `:108` raises `UnboundLocalError` on the `deep=True` path and **breaks every `--preview-analysis` run**; v1 specified exactly that. Condition is **zero *eligible* trends**, not zero verdicts — the `wkp9` shape (3 returned, all excluded) must also be non-zero, or the mode still reports success on a config that will exit 3. Restate causes instead of pointing at "the lines above". |
| `__main__.py` | Route `opts.quick` past the wizard gate (`:72`). The Phase-2 branch (`:78-80`) is reached from flag or action. |
| `sources/__init__.py` | Thread `used_posts` (and the `say` seam T2a needs) through the facade at `:43-47`. Aggregating file — main's, not T2a's. |

**`default.yaml` keeps `virlo_monitor_ids: []` — reversing the superseded plan's T3, deliberately.**
Pasting live ids there would make the neutral template a second HypeDigitaly config *and* destroy the
repo's only live reproducer. Instead the empty state becomes impossible to stumble into: the picker
row says `NOT RUNNABLE - pick [4]`, action `[4]` prints the ids, and pre-flight refuses for free.
The reproducer survives as `tests/test_preflight.py`.

### 3.5 The wizard (T2d) · [pp]

**Action choice** — four single keys, NFR-16's count untouched (it constrains *inputs*, not options):

```
  [1] guided run   [2] quick run   [3] publish (Phase 2 - not built)
  [4] print my Virlo monitor ids (setup helper, $0)
```

`[4]` routes to the existing `Action.LIST_MONITORS` dispatch (`__main__.py:87-88`). **This is the
highest value-per-line item in the plan** — ~6 lines that turn "the tool told me it's broken" into
"the tool fixed itself." `[3]` no longer asks *which run* before admitting it cannot publish.

**Quick run** — the hole v1 left unfilled: `--config` if given; else the **first runnable** entry of
`_PREFERRED_CONFIGS` (`menu.py:48`); else one line naming every config and its blocker (FR-69). It
**prints which config it chose and that config's readiness row**, then goes to the confirm gate —
**still interactive. It never implies `--yes`.** v1 would have fallen through to `load_config(None)`
→ `default.yaml` → the empty config, reproducing `c832` in one keystroke.
`_default_config_index` (`:172-178`) must also skip not-runnable rows unless `--config` named one.

**Picker rows** — two lines per config, every line ≤ 78 chars, all variable-length text last so a
wide glyph can only spoil a tail:

```
  [1] default          neutral template - no monitor ids yet, not runnable
      en · 0 monitors · 4/2/0 img/car/reel · NOT RUNNABLE - pick [4]
  [2] hypedigitaly     AI-agency niche - ENGLISH captions, LinkedIn-led
      en · 3 monitors · 4/2/0 img/car/reel · recommended
  [3] hypedigitaly-cs  AI-agency niche - CZECH captions and on-image text
      cs · 3 monitors · 4/2/0 img/car/reel
```

Budget: 2 indent + `[n]` + name 16 (truncate 15 + `…`) + label ≤ 55; facts line 6 indent + ≤ 66.
**No briefs column** — it costs an `iterdir()` per row on possibly-network paths and step 6 already
lists them. Reels on/off reads `Config.reels_plannable`, not `formats.reel > 0`, or a config with an
unpriced `reel_second` would claim "reels on" while `plan.build_plan` drops them (`plan.py:224-226`).

**Console discipline (FR-286), verified against this repo:** `·` `—` `…` `←` are safe — already
shipping (`runner.py:456` → `c832/run.log:33`). **No ANSI colour** (zero escapes in `hypesocials/`
today; legacy conhost prints `←[32m` literally). **No box drawing. No `✓`/`✗`** — U+2713 is absent
from Consolas' primary coverage and from cp437/cp852; use words. Every line the tool controls ≤ 78
chars; every string it does not control (niche text, trend names, paths) is truncated and placed last.

**One purpose line per step** (FR-284):

- **2/7 Sources** — what a source is; annotate `virlo` with the active config's monitor count.
- **3/7 Formats** — a carousel is a multi-slide deck (`carousel_slides`, default 5 — which is why 2
  decks priced 10 slides in `c832/run.log:15`); the platforms in force are shown **here**, since
  FR-137 forbids asking and today they first appear at `runner.py:793` after the wizard; and **keys
  you leave out keep their current value** (the `formats.update` merge trap).
- **4/7 Spend cap** — **validate, do not price.** Show `Config.min_single_creative_usd` and re-ask
  below it: `$0.01 is below the $0.03 floor - pre-flight would refuse this run`. `_pick_cap`
  (`:233-243`) already loops. **No plan estimate**: it needs `PlanEntry`s that do not exist until
  `plan.build_plan`, plus the private `runner._stamp_provisional` (`:770`), and it would omit briefs
  (step 6) — so it would print a number *lower* than step 7's. Two prices three prompts apart is
  worse than one price late, and duplicating `cli.estimate_report` violates
  `CODING_GUIDELINES.md:26`. The floor is the number that killed `g0pg`; it is enough.
- **5/7 Mode & Notion** — one clause per value; say the `NOTION_TOKEN` downgrade here, not three
  steps later.
- **6/7 Briefs** — what a brief is; an `override` brief bypasses trends entirely
  (`runner.py:428-429`). Note `default.yaml:181` points `briefs_dir` at a folder absent from the repo.
- **7/7** — where output lands and roughly how long it takes (`README.md:3`).
- **Counters** `1/7 … 7/7`. **Source pre-fill shows the name, not the bare index** (`:189`).

**The `?` key** — `Console.prompt(label, current, *, help_key)` owns a **re-ask loop**:

```python
if answer == "?":
    self.say(_explain(help_key)); continue
```

v1's version returned `current`, which **passes validation** on the cap, counts and briefs steps —
silently advancing. One loop in one place; seven keys passed in. **Accept `?` only**, not `help`/`h`
— a brief file named `help` is legal on Windows and would become unselectable. Advertise it in the
header beside `q`. Text lives in **`hypesocials/wizard_help.md`**, read lazily via
`Path(__file__).with_name(...)` on first `?` — ~120 lines of prose that would otherwise push
`menu.py` past `CODING_GUIDELINES.md:78`'s 500-line split threshold. **Not under `prompts/`**:
`preflight.py:232` validates that tree and a stray file risks a pre-flight surprise.

### 3.6 Tests — split across waves 2, 3 and 5 · [ta]

v1 put everything in wave 5, so waves 1–4's barriers were green-by-construction. Baseline **270
tests**. `menu.py`, `previews.py`, `__main__.py`, `cli.estimate_report/confirm_spend` and
`runner._famine_message/_launch_summary/_spend_table` have **zero** printed-text coverage today.

| wave | file | content |
|---|---|---|
| **2** | `tests/test_preflight.py` (new) | The §1.1 reproducer, permanently. (a) `virlo` + empty ids + `action="run"` → error naming `virlo_monitor_ids`; (b) `action="list-monitors"` → **no** error (FR-251 must survive the rule that exists to fix it); (c) all entries `override` → no error (FR-144); (d) **mixed brief + trend → warning, not error** (the regression v1 would have shipped). Assert the **specific text**, never `ok is True` — that also depends on env keys, disk and prices. Set `config.output.dir = str(tmp_path)`; `_check_disk` (`:299-320`) really does `mkdir` + write a probe. Module-local `_config(**kw)` per `tests/test_plan.py:19` — `conftest.py` has **zero fixtures**. |
| **2** | `tests/test_state.py` (new) | First coverage of the history layer: round-trip, `posts` map round-trip, an entry **without** `posts` reads as no-posts-used (the no-migration guarantee), `run_ids` cap of 5, prune horizon for entries **and** posts, corrupt file → `{}` + one warning, lock contention → `False` + one warning. |
| **3** | `tests/test_plan.py` (extend) | `chosen_post_ids` non-empty → monitor window **skipped**; empty → monitor window applies (`text_only` fallback); `trend_history_days: 0` disables; the exclusion label carries the date. |
| **5** | `tests/test_virlo_refs.py` (new) | The mechanism itself: all candidates built (not 2 — assert against a fixture with ≥4 qualifying slideshows); the freshest unused set is chosen; every panel field derives from the **chosen** set; `chosen_post_ids` matches it; a dead CDN URL cannot desynchronise ids from urls; selection is deterministic on identical input. **This is the suite that would have caught v1's fatal flaw.** **§2.3's three tiers, one test each:** a fresh same-creator video wins over a higher-viewed stranger; with no creator match the highest-viewed fresh video wins; **with every video used, tier 3 still returns the top video and logs `repeat` — it must never return `None`**; and the chosen tier is logged. |
| **5** | `tests/test_menu.py` (new) | Via the `Console` seam (`menu.py:58-83`), designed to be swapped whole — no monkeypatching. `?` **re-asks and does not advance** on all seven steps; quick run resolves to a **runnable** config and prints which; the picker flags a zero-monitor config and offers `[4]`; two configs differing only in language render **differently**; every printed line ≤ 78 chars; counters `1/7…7/7`. |
| **5** | `tests/test_config.py` (touch) | Only for the new `label:` precedence in `_describe`. **`:364-367` and `:122-129` do not break on T2f** — verified: the first writes its own `tmp_path` fixtures, the second asserts names and paths only. v1 claimed both needed updating. |

### 3.7 Waves 6–7 · [tw] then [main]

**[tw]** `README.md` — the first-run walkthrough is the document that failed: `:17` told the operator
to paste ids into `default.yaml` and nothing enforced it. Rewrite around the readiness rows and
action `[4]`; name all three configs and say which to pick (README never mentions `hypedigitaly-cs`
or Czech output); fix "7-step menu"; document `--quick`/`--history-days`; document the `posts` map.
**`NAVIGATION.md`** §3 (`wizard_help.md`), §4, §6, §9, §10.

**[main]** `prds/00-overview.md` v1.8.0 log entry with the final measured `wc -l`, then §4.

---

## 4. Acceptance

*(v1's ordering premise is deleted: it was a leftover from the superseded T3, and the exit-2 refusal
it wanted tested "before T2d/T2f" comes from T2c, which lands in the same parallel wave. There is no
schedulable moment.)*

1. `run.bat` → config `default` → the confirm prompt is **never reached**; exit **2**; the line names
   `sources.virlo_monitor_ids` and how to fix it; `$0.00`.
2. `run.bat --list-monitors` **and** action `[4]` both work against a config with empty ids, printing
   paste-ready YAML.
3. `run.bat --config hypedigitaly --brief ai-audit-cta:2 --yes --budget 2` — not refused, `$0`-Virlo,
   **zero MCP activity in `events.jsonl`** (reproducing `00-overview.md:269`). **`--config` is
   required**: without it `default.yaml` loads and its `briefs_dir: briefs` does not exist, so v1's
   version of this criterion would have failed for an unrelated reason.
4. `run.bat --config hypedigitaly --images 1 --yes --budget 2` **with a mixed plan** — one image
   entry plus one brief entry, empty ids — delivers the brief creative and exits **1**, not 2.
5. **The §1.2 fix, live.** On **2026-08-10**, all three monitors inside the 7-day window — today a
   guaranteed exit 3. It must collect and **deliver**. Then run it **three more times**: each run
   must select **different** post ids (`logs/trend_history.json`'s `posts` map grows), and the
   delivered creatives must differ in **headline and layout**, not only in image URLs — the check v1
   could not have passed. Record the measured candidate-set count per monitor; the design expects
   ~36 (`spikes/RESULTS.md:163`), not 2.
6. **§2.3, live and paid.** `run.bat --config hypedigitaly --reels 1 --yes --budget 6` twice: the two
   reels must resolve **different** motion references, `run.log` must name the tier for each, and
   `winning_video_post_id` must appear in the `posts` map only for a reel that actually attached its
   reference. Then a fixture/forced case where every video is already used: the reel **still renders**,
   the tier logs `repeat`, and nothing fails for freshness. On a slideshow-driven trend, the chosen
   motion video should be the same creator's where one exists.
7. `run.bat --preview-sources --config default` returns **non-zero**; `--preview-analysis` still runs
   without an `UnboundLocalError`; and `--preview-sources` against a fully-excluded config is also
   non-zero.
8. Guided walkthrough read aloud: every step states what it does and a good value; step 4 **rejects**
   `0.01` with the floor; the picker distinguishes all three configs; `?` explains any step and does
   not advance; counters `1/7…7/7`; **no printed line exceeds 78 chars**.
9. `[2] quick run` reaches the estimate with no further questions, on a **runnable** config, naming
   it. `--quick` is its twin; `--yes --quick` is refused with one line.
10. At the confirm prompt, a bare Enter cancels **and the prompt said it would**.
11. `--history-days 0` unblocks a fully exhausted config; `--history-days 400` refused in one line.
12. A run that contacted Virlo no longer reports `total $0.00` without qualification.
13. `pytest tests/ -q` green: 270 baseline + the new suites; `test_redaction.py`'s strict xfail stays
    xfail.
14. `find hypesocials -name "*.py" | xargs wc -l` **≤ 14,000**, checked at **every** barrier, with the
    per-task allowances in §3.2 as the attribution. Honest overflow escalates (CLAUDE.md rule 5) —
    never a silent docstring trim.

**Budget forecast:** wave 1 ≈ 62 · wave 2 ≈ 255 · wave 3 ≈ 12 · wave 4 ≈ 50 → **≈ 379**, landing near
**13,865** of 14,000. `tests/`, `run.bat`, `configs/`, `prds/` and `wizard_help.md` are outside the
G2 measure, which counts `hypesocials/**/*.py` only.

## 5. Verification commands

```
.venv\Scripts\python -m pytest tests/ -q
find hypesocials -name "*.py" | xargs wc -l | tail -1
run.bat --list-monitors
run.bat --preview-sources --config default
run.bat --preview-analysis --config hypedigitaly --images 1
run.bat --config hypedigitaly --images 1 --yes --budget 2
```

## 6. Wave table

| wave | shape (§9a) | owner | disjoint paths | barrier |
|---|---|---|---|---|
| **0** | a — one writer, cross-file consistency | [tw] | `prds/10,20,30,40` | `pytest -q`; operator reads the FR text |
| **1** | a — shared contract, single writer | [pp] | `models.py` · `config.py` · `preflight.py` (floor only) · `cli.py` (`Options.quick` only) | imports clean + `wc -l` |
| **2** | a — 7 disjoint sets, **flat** (per-domain < 5) | [pp] ×6 ‖ [ta] ×1 | `sources/virlo.py`+`sources/inspiration.py` · `outputs/state.py`+`outputs/__init__.py` · `preflight.py` · `menu.py`+`wizard_help.md` · `cli.py` · `run.bat`+`configs/` · `tests/test_preflight.py`+`tests/test_state.py` | `pytest -q` + `wc -l` + acceptance 1, 2, 5 |
| **3** | a — depends on 1, T2a, T2b | [pp] | `plan.py` + `tests/test_plan.py` | `pytest -q` + `wc -l` |
| **4** | aggregating + wire-in, **reserved for main** | [main] | `runner.py` · `previews.py` · `__main__.py` · `sources/__init__.py` | `pytest -q` + `wc -l` + acceptance 1–6, 11 |
| **5** | b — ≥5 files in `tests/`, resolved as **one owner**, not a fan-out | [ta] | `tests/` | full `pytest -q` |
| **6** | a — docs | [tw] | `README.md` · `NAVIGATION.md` | — |
| **7** | aggregating, **main** | [main] | `prds/00-overview.md` | acceptance 7–10, 12, 13 |

Spawn depth never exceeds `main → leaf`; no `model` parameter is ever passed (CLAUDE.md §9).
**No wave has more than one writer per file.** ([tw] owns waves 0 and 6, [pp] waves 1–3, [ta] 2/3/5,
[main] 4 and 7 — v1 claimed "no agent receives more than one wave", which was false; the real
invariant is single-writer-per-file-per-wave.)

### Aggregating files — single writer, LAST
- `runner.py`, `__main__.py`, `sources/__init__.py` — **[main]**, wave 4.
- `outputs/__init__.py` — **[pp]** in T2b (only task adding to it).
- `prds/00-overview.md` — **[main]**, wave 7, after the final count exists.

### Wire-in
| new symbol | defined | called from | by |
|---|---|---|---|
| `ReferenceSet`, `TrendItem.chosen_post_ids` | `models.py` (W1) | `virlo._build_item`; `plan.select` | [pp] T2a, W3 |
| `ConfigSummary` scalars, `label:`, `min_single_creative_usd`, `LOGS_DIR` | `config.py` (W1) | `menu._pick_config`; `preflight._check_prices`; `runner`/`previews` | [pp] W1/T2d, [main] W4 |
| `record_use()` | `outputs/state.py` (T2b) | `runner._package` (`:633-635`, **signature change**) | **[main]** W4 |
| `preflight._check_supply` | `preflight.py` (T2c) | `preflight.check()` — same file | [pp] T2c |
| `sources.fetch(used_posts=…)` | `virlo.py` (T2a) | `sources/__init__.py:43-47` → `runner:432`, `previews:102` | **[main]** W4 |
| `Options.quick`, `--quick`, `--history-days` | `cli.py` (W1/T2e) | `__main__.py:72`; `menu._options_from` | **[main]** W4, [pp] T2d |
| `Console.prompt(help_key=…)`, `wizard_help.md` | `menu.py` (T2d) | all seven steps | [pp] T2d |

## 7. Invariants at risk

- **G2 = 14,000**, checked at every barrier with per-task attribution.
- **Refusal is free** (`preflight.py:13-14`) — `_check_supply` reads config and `logs/` only.
- **`--list-monitors` must survive the rule that exists to fix it** (FR-251) — acceptance 2,
  `test_preflight.py`(b).
- **A mixed brief+trend plan must still ship its briefs and exit 1** (`10-pipeline.md:411`) —
  the regression v1 would have introduced. `test_preflight.py`(d).
- **NFR-16's prompt count is unchanged** — quick run and `[4]` ride the existing action choice.
- **FR-65 parity** — every new menu setting has a flag twin.
- **FR-69** — one plain-English line per refusal.
- **No migration.** An entry without `posts` reads as no-posts-used. `trend_history.json` is never
  re-keyed and never rewritten in a new shape, so there is no window with recency protection off.
- **One lock, one write, one status.** Never two record calls, never `asyncio.gather` — the second
  `finally` unlink would delete the first's lock.
- **`budget.py` is not touched.** One analysis call per monitor, one copy call per
  `(monitor, language)`. If anything starts multiplying LLM calls, the design has drifted into the
  rejected alternative and must stop.
- **Both reuse defaults stay 2 and 7.** F-1 is re-opened on identity only, on the record.
- **`text_only` trends keep monitor-level history** — they have no post identity.
- **A `ReferenceSet` is atomic.** urls, post ids and panel metadata are chosen together. If a
  reviewer sees a hand-written cross-list alignment invariant reappear, the abstraction has been
  lost and v1's fatal flaw is back.
- **Record what was *attached*, not what was chosen.** Under `inspiration_mix: exclusive` a creative
  attaches zero trend images (`generate/refs.py:69,72`); burning those post ids would be a lie. The
  same holds for a reel whose motion reference failed to download or degraded to `in_model`.
- **Motion-reference freshness is best-effort and must never block a reel** (§2.3 tier 3). A repeated
  motion source is cosmetic; a failed reel is a paid loss — one reel measured $4.78. If any reviewer
  sees `_pick_motion` able to return `None` because everything is used, that is the bug.
- **`select()` stays pure** (`plan.py:10-13`) — no rotation, no mutation, no new parameter.
- **Every printed line the tool controls ≤ 78 chars**, variable text last. No colour, no box
  drawing, no `✓`/`✗`.
- **No new PRD citation on any console line this plan rewrites** — it moves to `events.jsonl`.

## 8. Rollback

```
git checkout -- hypesocials/ configs/ prds/ tests/ run.bat README.md NAVIGATION.md
```

No migration ran and `trend_history.json` was never rewritten in a new shape — a `posts` key left
behind by a reverted run is read as no-posts-used by the restored code, i.e. inert.
