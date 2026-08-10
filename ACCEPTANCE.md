# ACCEPTANCE.md — Operator Final Acceptance Matrix (Wave 6, MVP)

Four scenarios, each ending with the same four standard checks. Run from the repo root
(`C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials`) in a normal console. Exit codes per
FR-202 (prds/10-pipeline.md §6): **0** all delivered · **1** partial (honest skips/losses) ·
**2** pre-flight/cap refusal, nothing spent · **3** fatal, nothing usable · **4** operator abort.

> Trend-famine note: the 7-day history window (`logs/trend_history.json`) may have consumed
> today's usable trends from earlier runs. An exit 1 with `SKIP_REASON.txt` naming the famine is
> HONEST behavior, not a failure. To reset for a test: rename `logs/trend_history.json` aside
> (restore it afterwards if you want the reuse guard back).

---

## The 4 standard checks (apply to EVERY scenario)

1. **Gallery correct** — open `output\latest\gallery.html`: every delivered asset has a card
   (thumbnail/video, caption, platform+format badges, est. cost, source refs + hook, Virlo
   link); skipped assets absent from cards but named in the run summary; A/B pairs side by side
   with `pair_id` and the pair-integrity badge only when a side lost analysis.
2. **meta.yaml honest** — every asset folder's `meta.yaml` is terminal (`delivered` / `skipped`,
   never `pending`), `degradations: []` lists only what actually happened, costs present,
   `render_not_reproducible: true` stated, `brief_influence_mode` present on brief assets.
3. **Spend ≈ estimate** — run.log's spend summary: actual ≤ pre-flight worst-case estimate, and
   in the expected ratio (reel actuals land well under the worst-case scalar by design).
   Cross-check the Kie/OpenRouter dashboards if in doubt.
4. **No orphan processes** — after exit: `tasklist | findstr /i "python node yt-dlp"` shows
   nothing from the run (one hit for your own console's python is fine only while it's still
   open); no stray `node.exe` (Notion MCP) or `yt-dlp` remain.

---

## Scenario 1 — Tiny-budget refusal (interactive) + auto-trim (`--yes`) — $0

**1a. Interactive refusal (FR-28, human decides):**

```
run.bat --config hypedigitaly.yaml --images 2 --carousels 1 --budget 0.02
```

Expected: full cost estimate + FR-282 provenance printed; refusal naming the gap
("estimate … exceeds the $0.02 spend cap by … — lower the counts, raise --budget, or re-run
with --yes"); **exit 2**; $0 spent; no render/LLM calls in `events.jsonl`; run folder + log
survive (FR-59 resolution) but contain no assets.

**1b. Auto-trim under `--yes` that cannot fit (FR-28 trim floor):**

```
run.bat --config hypedigitaly.yaml --images 2 --carousels 1 --budget 0.02 --yes
```

Expected: trim summary line printed, then refusal "the $0.02 cap is below the cost of any
single creative — trimming cannot help; raise --budget"; **exit 2**; $0 spent.

**1c (optional, costs ~$0.10–0.20). Auto-trim that fits:**

```
run.bat --config hypedigitaly.yaml --images 4 --carousels 2 --budget 0.30 --yes
```

Expected: reverse-plan trim drops entries until the estimate fits $0.30; the trimmed plan is
printed and runs; **exit 0 or 1**; spend ≤ $0.30. Then the 4 standard checks.

---

## Scenario 2 — Full-batch stress: 2 images + 2 carousels + 1 reel, `--yes` (~$5–6)

```
run.bat --config hypedigitaly.yaml --images 2 --carousels 2 --reels 1 --yes --budget 6
```

Expected: estimate ≈ $5.3–5.7 worst case (reel priced at the honest 720p scalar 0.950/output-s
= $4.75 worst case; actual reel typically $1.70–2.85); two-wave submission visible in
`LEDGER.txt` (anchors + seed frame first, slides/animation second); wall clock inside the
**≈8–10 min reel tier** (record it); **exit 0**, or **exit 1** with honest skip reasons
(famine — see note above; or motion-ref degradation `no_qualifying_video`, which ships the reel
seed-frame-only and is correct behavior). Then the 4 standard checks — pay extra attention to
check 3: reel actual should be far below the worst-case line.

---

## Scenario 3 — Czech-language run (optional, ~$0.30–0.60)

One-time setup (copy the proven config, switch the three platform languages to Czech):

```
copy configs\hypedigitaly.yaml configs\hypedigitaly-cs.yaml
```

Edit `configs\hypedigitaly-cs.yaml` line `languages:` to:
`languages: { linkedin: cs, instagram: cs, tiktok: cs }`

Run:

```
run.bat --config hypedigitaly-cs.yaml --images 2 --carousels 1 --budget 1
```

Expected: pre-flight prints the **Czech vision-check hint** (30 §2 — vision check is off by
default; the hint reminds you Czech on-image text benefits from it); captions AND on-image text
in Czech (on-image language defaults to the platform's caption language, FR/30 §2); confirm
interactively with `y`; **exit 0/1**. Then the 4 standard checks — for check 1 also eyeball
that rendered on-image Czech has correct diacritics.

---

## Scenario 4 — Task Scheduler unattended run (~$0.30–0.60)

Create (one line; adjust the start time `/ST` a few minutes ahead):

```
schtasks /Create /TN "HypeSocials-Acceptance" /SC ONCE /ST 23:55 /TR "cmd /c cd /d C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials && run.bat --config hypedigitaly.yaml --images 2 --carousels 1 --yes --budget 1"
```

Trigger it now instead of waiting, then watch:

```
schtasks /Run /TN "HypeSocials-Acceptance"
schtasks /Query /TN "HypeSocials-Acceptance" /V /FO LIST
```

Expected: run completes with **no console interaction** (`--yes` path: no confirm, no fidelity
rating — FR-232 is suppressed); "Last Result" in the query output is the run's exit code (0/1);
outputs land in `output\<run_id>\` and `output\latest` repoints. Then the 4 standard checks —
check 4 matters most here (Task Scheduler must leave no orphan tree behind).

Clean up:

```
schtasks /Delete /TN "HypeSocials-Acceptance" /F
```

(For a real nightly schedule replace `/SC ONCE /ST …` with e.g. `/SC DAILY /ST 07:00` — see
README "Unattended usage".)

---

## Sign-off

| Scenario | Ran on | Exit | Gallery | meta.yaml | Spend≈est | No orphans |
|---|---|---|---|---|---|---|
| 1a interactive refusal | | | ☐ | ☐ | ☐ ($0) | ☐ |
| 1b --yes trim-refusal | | | ☐ | ☐ | ☐ ($0) | ☐ |
| 1c --yes trim-fits (opt) | | | ☐ | ☐ | ☐ | ☐ |
| 2 full-batch stress | | | ☐ | ☐ | ☐ | ☐ |
| 3 Czech run (opt) | | | ☐ | ☐ | ☐ | ☐ |
| 4 Task Scheduler | | | ☐ | ☐ | ☐ | ☐ |

## First execution record (2026-08-09, automated at the W6 barrier — operator re-run optional)

| Scenario | Run | Exit | Result |
|---|---|---|---|
| 1a (cap floor $0.02 + over-cap $1 variants) | `221509_au79` | 2 | Both refusal paths correct; estimate + FR-282 provenance shown; $0 |
| 1b/1c (`--yes` $0.02 floor + $0.10 real trim) | `221735_zzom`, `221750_5tfs` | 2 / 3 | Floor refusal; then "4 entries trimmed, now $0.07" → honest famine abort; $0 |
| 2 stress 2+2+1 `--yes` $6 | `221816_0316` | 1 | 4/5 delivered, $5.53 counted (worst case $5.73); **reel hit the 600 s timeout** — honestly skipped, worst-case charge counted per no-resubmit policy (meta actual $0.03 seed frame; check the Kie dashboard for the clip's real charge); 949 s; no orphans |
| 3 Czech interactive $1 | `223503_ax10` | 0 | 3/3, $0.60, 361 s; 30 §2 Czech hint printed; captions in real diacritics — on-image glyphs still want your eyeball |
| 4 Task Scheduler `--yes` $1 | `224147_wrsg` | 0 | 3/3, $0.68, 381 s, Last Result 0, task deleted after; no orphans |

Trend history was set aside per the famine note for scenarios 2–4 and merged back afterwards
(all run_ids preserved).

**Both findings from this record are now CLOSED (operator decisions 2026-08-10, PRD v1.7.0):**
- *Estimator under-ran twice* ($0.72 vs $0.69; $0.60 vs $0.56) — **fixed.** The LLM retry
  allowance now prices FR-127's truncation retry and FR-41's parse retry as the independent,
  compounding, widened-cap calls they actually are. Re-scored against those same two runs the
  worst case is now $0.85 and $0.80, both comfortably above the actuals; the *expected* figures
  are unchanged, so the confirm prompt reads the same.
- *Reel timed out at 600 s and its ~$4.78 was paid and discarded* — **fixed.** The video job
  timeout is now 1800 s (30 min), and `run_deadline_min` is 45 min in the reel-capable configs
  so the deadline cannot abandon a job before its own timeout. Re-run scenario 2 to confirm on
  live hardware; the earlier reel's real charge is worth one glance at the Kie dashboard.
