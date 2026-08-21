---
name: hypesocials-run
description: Run the HypeSocials autopilot - launch a paid-free engine run, wait for it, review every deck with the Claude critic panel, write the report. Headless; never asks the operator anything.
argument-hint: "[--config NAME] [--carousels N]"
---

# HypeSocials autopilot playbook

You are running with NO operator present. Never ask a question. Decide, do, and log the decision.
This playbook works the same when typed as `/hypesocials-run` and when Task Scheduler runs
`claude -p "/hypesocials-run"` through `autopilot.bat`.

Repo root (always use this absolute path): `C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials`

Arguments: `$ARGUMENTS` may hold `--config NAME` and/or `--carousels N`. Default config is
`hypedigitaly`. Any other flag name is passed through to `run.bat` unchanged (flag names live in
`hypesocials/cli.py`: `--config --images --carousels --reels --platforms --styles --budget --notion
--copy-mode --copy-language --gauntlet/--no-gauntlet --history-days --brief --verbose`).

Hard rules for the whole session:
- Never publish anything (Phase 2 is not built; `--publish`/`--promote` are placeholders).
- Never delete, move or rename anything under `output/` or `logs/`.
- Never edit code, config (`configs/*.yaml`), prompts (`prompts/`), or `.env` during an autopilot run.
- Never `git stash`, `git commit`, `git checkout --`, or touch the operator's dirty files.
- If something looks like a code bug, write `logs/autopilot/NEEDS_HUMAN_<run>.md` and stop (Step 4c).

## Step 0 - Preconditions (about 30 seconds, $0)

1. Confirm the cwd is the repo. Run:
   `cd "C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials" && git status --short && git branch --show-current`
   Note dirty files in your report. Do not stash or commit them.
2. Confirm the Codex login exists (the engine's pre-flight starts the proxy from it):
   `test -f "$HOME/.codex/auth.json" && echo codex-ok || echo codex-missing`
   If missing: write `logs/autopilot/NEEDS_HUMAN_<timestamp>.md` saying "Codex login missing
   (~/.codex/auth.json); run `npx openai-oauth@latest` login by hand" and STOP. Do not launch.
3. Confirm the config file exists: `ls configs/<NAME>.yaml` (NAME = `hypedigitaly` unless `--config`).
4. Make the autopilot log folder: `mkdir -p logs/autopilot`.
5. Record `STAMP=$(date +%Y%m%d_%H%M%S)` - this names the console log.

## Step 1 - Launch the engine DETACHED, then wait

WHY detached: one tool call caps at 10 minutes. An engine run takes 40-60 minutes. A run killed
mid-render wastes real money (Virlo is still metered, and a Kie render may still be billed). This is
a rule from a past failure - never launch `run.bat` inside a normal foreground or background tool call.

1. Remember the previous run id so you can tell the new one apart:
   `PREV=$(cat output/latest.txt 2>/dev/null); echo "prev=$PREV"`
2. Create the cmd wrapper with the **Write tool** (NOT printf/heredoc - bash eats the backslashes in
   Windows paths, `\run.bat` turns into a carriage return). A wrapper is needed so the exit code
   lands in the log, and `run.bat` must be called by FULL PATH - bare `run.bat` is not found from
   wrappers. File: `C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials\logs\autopilot\<STAMP>.cmd`
   with exactly these 4 lines (replace `<STAMP>`; add `--carousels N` and any pass-through flags
   after `--yes` when given). The redirect goes FIRST on the last line on purpose: `exit=1>> file`
   is read by cmd as "redirect handle 1", and the code prints empty (run 20260821_121514_q745):
   ```
   @echo off
   cd /d "C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials"
   call "C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials\run.bat" --config hypedigitaly --yes > "C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials\logs\autopilot\<STAMP>.console.log" 2>&1
   >> "C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials\logs\autopilot\<STAMP>.console.log" echo exit=%ERRORLEVEL%
   ```
3. Start it detached so it outlives every tool call (PowerShell tool, one line):
   `Start-Process cmd.exe -ArgumentList '/c','"C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials\logs\autopilot\<STAMP>.cmd"' -WindowStyle Hidden`
   (Bash alternative: `cmd //c start //b "" cmd //c "C:/Users/Pavli/Desktop/HypeDigitaly/GIT/HypeSocials/logs/autopilot/<STAMP>.cmd"`.)
   Then confirm within 10 s that the console log exists and has its first lines:
   `ls -la logs/autopilot/<STAMP>.console.log && head -5 logs/autopilot/<STAMP>.console.log`
4. Wait with FOREGROUND blocking calls - NOT the Monitor tool and NOT `run_in_background`.
   WHY (measured 2026-08-21, run 20260821_115013): in headless `claude -p` mode the session ends
   its turn the moment a Monitor is armed, the process exits with code 0, and no notification ever
   wakes it - the engine kept running detached, but nobody reviewed it. A foreground Bash call
   blocks the turn, so the session stays alive. One call may block at most 10 minutes, so wait in
   9-minute slices and REPEAT the same call until it prints `ENGINE_FINISHED`. Run this exact
   command with the Bash tool and `timeout: 590000` (replace `$STAMP`); call it again each time it
   prints `STILL_RUNNING`, up to 9 times (81 minutes):
   ```
   LOG="C:/Users/Pavli/Desktop/HypeDigitaly/GIT/HypeSocials/logs/autopilot/$STAMP.console.log"
   end=$(( $(date +%s) + 540 ))
   while [ $(date +%s) -lt $end ]; do
     if [ -f "$LOG" ] && grep -q "^exit=" "$LOG"; then
       grep -E "^\[[0-9]+/10\]|^exit=|run failed|Traceback|refus|TOTAL" "$LOG"
       echo "ENGINE_FINISHED $(grep '^exit=' "$LOG")"; exit 0
     fi
     sleep 30
   done
   echo "STILL_RUNNING last stage: $(grep -E '^\[[0-9]+/10\]' "$LOG" | tail -1)"
   ```
   Between slices do nothing else - no log reading, no other work. If nine slices pass with no
   `exit=` line: treat it as a crash (Step 4c) and do not kill the engine - it may still be packaging.
5. After `exit=`, read the run id: `RUN=$(cat output/latest.txt)`. If `RUN` equals `PREV`, the engine
   never created a run folder (it died in pre-flight) - go to Step 5.

How to read the console log:
| Line | Meaning |
|---|---|
| `[1/10] COLLECT` ... `[10/10] DONE` | The ten stages: COLLECT, TOPICS, FILTER, SELECT, ASSIGN, INTEL, COPY, RENDER, GAUNTLET, DONE. Each prints a start line and an end line with elapsed time. |
| `[10/10] DONE  7 delivered, 2 skipped, $7.77 of the $15.00 cap` | The run finished. Counts are the truth for the log row. |
| `TOTAL  llm $X + render $Y = $Z` | Metered spend. Under codex (subscription proxy) both llm and render are $0.00. Virlo is metered separately and never appears here. |
| `status partial-success - exit code 1` | Exit code meaning: 0 all delivered - 1 delivered with losses (blocked/skipped) - 2 pre-flight refusal, $0 - 3 nothing usable after Collect - 4 Ctrl+C. |
| `exit=N` | Last line; written by the wrapper. |

## Step 2 - Read the receipts (all under `output/<RUN>/`)

1. `tail -60 output/<RUN>/run.log` - the delivery table (`asset / format / est / billed / ok / gate`)
   and the spend table. Gate values: `pass`, `degraded` (shipped with a quality tag), `blocked`
   (kept, never ships), `skipped` (critics unavailable - the gauntlet was blind; `*` = degraded gate).
2. `LEDGER.txt` - one CSV row per render job: `time, asset, job, kie_task_id, state`
   (`intent` -> `submitted` -> `success|failed|timeout`). Count rows per asset if a deck looks short.
3. Every asset folder `output/<RUN>/<asset_id>/` (name pattern `Ig_car_<topic>_NN`, `Li_`, `Tk_`):
   - `meta.yaml` fields that matter: `status` (success|blocked|skipped), `style_key`, `branded`,
     `copy_mode` (verbatim|auto|compress), `copy_language` (source|target), `source_language`,
     `panel_map[*]` rows (`slide`, `source_text` = the LOCKED text that must appear on that slide,
     `source_text_original`, `drop_reason` - non-empty means a wordless slide, `compressed`,
     `translated`, `chrome_counter_stripped`), `counter` (`detected`, `rule`, `sample`), `cover_pick`
     (`candidates`, `chosen`, `reason`, `degraded`), `degradations` (list of tags), `gauntlet`
     (`result`, `rounds`, `rerenders`), `skip_reason`, `missing_slide_numbers`.
   - `GAUNTLET_REPORT.yaml`: `result` (pass|degraded|blocked|skipped), `rounds[*].defects[*]` with
     `critic` (brief|system|craft), `frame`, `code`, `zone`, `confidence`, `detail`; `unavailable`
     lists critics that never answered (blind gauntlet).
   - `slide_NN.png` (our slides), `covers/cover_candidate_N.png`, `caption.txt`, `BLOCKED.txt` when
     blocked, `SKIP_REASON.txt` when skipped.
   - Source slides live at `output/<RUN>/source/<post_id>/slide_NN.jpg|webp` (`post_id` =
     `meta.yaml.copy_source_post_id`).
4. `gallery.html` exists at the run root - you do not need to open it; it is for the human.

Build a deck list: every folder with `creative_format: carousel` and `status` in {success, blocked}.
Folders with `status: skipped` and no `slide_01.png` are noted in the report but not reviewed.

## Step 3 - Claude review panel (second critic panel)

For EVERY deck in the list, spawn ONE `hs-deck-critic` agent with the Agent tool - all in the same
message so they run in parallel (9 decks = 9 agents). The prompt for each is exactly:

```
Review this HypeSocials carousel folder and return the fixed verdict block:
C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials\output\<RUN>\<asset_id>
```

Each agent returns `VERDICT / CONFIDENCE / DEFECTS / AGREES_WITH_ENGINE / NOTE`. Wait for all of
them. If one agent fails or returns no block, record `VERDICT: hold`, `CONFIDENCE: low`,
`NOTE: critic agent failed` for that deck - never invent a verdict.

Merge rule per deck:
| Engine gate | Claude verdict | Recommendation |
|---|---|---|
| pass / degraded | ship | SHIP |
| pass / degraded | hold | HOLD (Claude found something the engine missed - say what) |
| blocked | ship | HOLD (engine block stands; note the disagreement for the human) |
| blocked | hold | HOLD |
| skipped (blind gauntlet) | ship | SHIP - Claude was the only critic; say so |
| skipped (blind gauntlet) | hold | HOLD |

## Step 4 - Write the report

4a. Write `output/<RUN>/CLAUDE_REVIEW.md`:
```
# Claude review - run <RUN>
date: <ISO> - config: <NAME> - exit: <N> - delivered: <a> - blocked: <b> - skipped: <c>
spend: llm $X + render $Y = $Z (codex: $0 metered; Virlo metered separately)
gauntlet blind decks: <count> (critics unavailable)

## <asset_id>  -  <style_key>  -  SHIP|HOLD
engine: <gate> (<rounds> rounds, <rerenders> re-renders) - claude: <verdict> (<confidence>)
agrees: yes|no - <why>
top defects:
1. slide NN - <tier> - <code> - <one line>
2. ...
3. ...
reason: <one line>
```
One section per deck, in asset order. Keep it short; the human reads this first.

4b. Append ONE row to `logs/autopilot/AUTOPILOT_LOG.md` (create the header if the file is empty):
`| <date> | <RUN> | <config> | exit <N> | delivered <a> / blocked <b> / skipped <c> | $<Z> | claude hold <h>/<n> | output/<RUN>/CLAUDE_REVIEW.md | <needs human? one phrase or "-"> |`

4c. NEEDS_HUMAN. Write `logs/autopilot/NEEDS_HUMAN_<RUN or STAMP>.md` (and name it in the log row)
when ANY of these is true:
- the console log has a `Traceback` (paste the last 30 lines of it into the file),
- nine 9-minute wait slices passed without an `exit=` line,
- a deck defect looks like a CODE bug, not a render fluke (same defect code on 3+ decks, a
  `panel_map` row whose `source_text` is empty with no `drop_reason`, a counter detected that
  contradicts the source slides, a `cover_pick.degraded: true` on every deck),
- the gauntlet was blind (`unavailable` non-empty) on more than half the decks,
- spend in the TOTAL line is not $0 while the config says codex (the proxy was bypassed).
Then STOP. Do not try to fix anything.

## Step 5 - Retry rule

Only if the engine exited non-zero BEFORE RENDER - i.e. `exit=2` (pre-flight refusal, $0 spent) or
`exit=3` (nothing usable after Collect), or no run folder was created:
1. Read the reason from the console log (the last 20 lines name it: missing key, bad config,
   Virlo transport dead, proxy not up, ...).
2. Wait 5 minutes: `sleep 300` (this is the one place a foreground sleep is fine, under 10 min).
3. Repeat Step 1 exactly ONCE with a new `STAMP`.
4. If it fails again: write the NEEDS_HUMAN file with both console-log tails, append the log row,
   stop.
Never retry after `exit=1` (losses are a result, not a failure), after `exit=4`, or after any run
that reached `[8/10] RENDER` - money may have moved.

## Step 6 - Finish

Print a 6-line summary to stdout (run id, exit, delivered/blocked/skipped, spend, Claude hold count,
path of CLAUDE_REVIEW.md and of any NEEDS_HUMAN file). That is the whole deliverable. Exit.
