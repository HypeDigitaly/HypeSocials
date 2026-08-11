# quickfix — empty `virlo_monitor_ids` must refuse at pre-flight, not after the confirm gate

**Status:** awaiting operator approval
**Date:** 2026-08-10
**Trigger:** run `20260810_123845_c832` (interactive, `configs/default.yaml`) — exit 3, $0.00

---

## 1. Cause (settled by recon, not assumed)

`configs/default.yaml:40` ships `virlo_monitor_ids: []`.

`hypesocials/sources/virlo.py:92-95` short-circuits on an empty id list and returns `[]` **before**
`SessionPool` is opened at `virlo.py:97`. No MCP subprocess spawned, no Virlo tool call made
(`output/20260810_123845_c832/run.log:32` — `collect_complete: 0 trend(s) collected (4ms)`).
`plan.select([])` yields `Selection(verdicts=[])`, and `runner.py:465-466` raises
`_Abort(EXIT_NOTHING_USABLE, ...)` → exit 3.

**The defect is not the short-circuit — it is *when* the operator learns about it.**
`preflight.py` has no `virlo_monitor_ids` check at all (repo-wide grep: the key appears only at
`config.py:107`, `runner.py:198/475`, `sources/virlo.py:92-94`). So pre-flight returned `ok=True`
(`run.log:8`), the operator was shown a cost estimate and approved $0.64 (`run.log:30`), and only
*then* the run died on a purely local, $0-knowable misconfiguration.

That contradicts the module's own stated contract:

- `preflight.py:13-14` — *"**Refusal is free** (FR-202 code 2): every check here is local."*
- `preflight.py:198` (`_check_sources`, FR-135) — *"a named-but-unbuilt adapter refuses HERE, not
  with a warning after the confirm gate."* Empty monitor ids is the same failure class, unguarded.
- `prds/10-pipeline.md:323` — exit 2 = pre-flight/cap refusal, nothing spent.

Secondary: the abort text at `runner.py:474-476` says *"Virlo returned no trends at all — check that
`sources.virlo_monitor_ids` names monitors this key can see"*. Virlo was never asked anything. The
wording sends the operator to debug a working API key.

**Not in scope (separate, by-design):** run `20260810_123102_wkp9` (`hypedigitaly.yaml`) also exited
3, but Virlo worked — 3 trends collected in 12.9 s, all excluded by the 7-day
`trend_history_days` window (`run.log:57`, FR-7). Correct behavior, no change.

## 2. PRD position

No FR mandates a pre-flight rejection today — this is a **gap**, not a code-vs-PRD conflict.
The spec is unambiguous that empty ids can only ever yield zero items:

- `prds/20-integrations.md:97` — a trend item is assembled *"one per configured monitor id"*; the
  global `get_trends` digest *"never creates trend items of its own"*.
- `prds/30-configuration-and-run.md:109` — `sources.virlo_monitor_ids` — *"one or more"*.

So empty ids means "this run is arithmetically incapable of producing a creative" — knowable
locally, for free, which is exactly pre-flight's remit. Adding the rule is **new behavior requiring
a D15 amendment** (CLAUDE.md *PRD Governance*): new **FR-290** (first free number;
`prds/00-overview.md:244` reserves the FR-290+ block).

## 3. Changes

> **Verifier fold (one pass, applied).** Two read-only verifiers (`Plan`, `Explore`) found four
> defects in the first draft: (a) the stated insertion point in `_check_sources` is unreachable code;
> (b) the brief-only carve-out is a **certainty**, not a risk, and needs `entries` threaded, not just
> `action`; (c) the 14-line budget did not fit T1+T2 as written; (d) `tests/conftest.py` has **no
> fixtures at all** and `tests/test_exit_codes.py` is scoped to pure logic while `preflight.check()`
> does real disk I/O. All four are corrected below. Also confirmed: `config.py:_validate` is the
> *wrong* home (no `action`, no `entries` — it would break `--list-monitors` and every brief-only
> run); `--sources virlo` is not a hole (`cli.apply_overrides` at `cli.py:212-214` runs before
> pre-flight); no existing guard is being duplicated.

| # | File | Change |
|---|---|---|
| T1 | `hypesocials/preflight.py` | Extend `_check_sources` (`:197-213`). **Insert between `:203` (`active = ...`) and `:204` (`unbuilt = ...`)** — anything after the verdict is unreachable, because `:206` returns on the normal `active: [virlo]` path. Append an **error** when all four hold: `"virlo" in active` · `action != "list-monitors"` · no non-empty entry in `config.sources.virlo_monitor_ids` · **not** `(entries and all(getattr(e, "brief_influence", None) == "override" for e in entries))`. Requires threading **both `action` and `entries`** into `_check_sources` — `_check_secrets`/`_check_profiles` are the `action` precedent (`preflight.py:185`, `:216`; `:218-219` already exempts two actions the same way). Add FR-290 to the module docstring's FR list at `:5-7` (**+0 lines**, extends an existing string). |
| T2 | `hypesocials/runner.py` | `_famine_message` (`:473-476`): **rewrite the existing 3 lines in place, net 0 added lines** — do NOT add a branch. New wording states that no monitor ids were configured and therefore no Virlo call was made, while still covering the populated-ids case. (The branch becomes unreachable for runs once T1 lands; it survives as a safety net at zero line cost.) |
| T3 | `configs/default.yaml:40` | Replace `virlo_monitor_ids: []` with the three verified ids + name comments, copied from `configs/hypedigitaly.yaml:33-36` (recorded live in `spikes/RESULTS.md` §A, 2026-08-09). `default.yaml` is the **only** config with an empty list, so this is the complete config-side fix. **Deliberate trade, recorded:** this turns `default.yaml` from a neutral template into a second HypeDigitaly config, and removes the repo's one live reproducer of the bug T1 fixes — acceptable in a single-operator repo, and T6 preserves the reproducer as a test. |
| T4 | `prds/30-configuration-and-run.md` | Add **FR-290** at `:416`, directly after FR-251, matching the flat `**FR-NNN** … SHALL …` paragraph style (no heading, no bullet, one blank line between). Add one bullet to §8's refusal list (`:474-494`) in its established style — bold lead-in naming the situation, colon, one sentence, backticked keys, trailing `(FR-290)` — inserted after `:481` or `:486`. Amend `:109` (*"one or more"*) to state that empty is a pre-flight refusal, and note the brief-only exemption. |
| T5 | `prds/00-overview.md` | Amendment-log entry **v1.7.1** (after `:271`). Update the FR registry at `:244` — *"Next fresh block: FR-290+"* becomes FR-291+. Leave `:260` alone (historical v1.5 log line). PRD.html/artifact republish stays deferred per the v1.6.3 precedent. |
| T6 | **new** `tests/test_preflight.py` | `tests/conftest.py:1-12` is pure docstring with **zero fixtures** — use the module-local pattern from `tests/test_plan.py:19` (`def _config(**kw) -> Config`). Set `config.output.dir = str(tmp_path)`, because `_check_disk` (`preflight.py:299-320`) really does `mkdir` + write a probe file and would otherwise pollute the repo's `output/`. Three tests, each asserting on the **specific error text**, never on `ok is True` (which also depends on env keys, disk and prices): (a) `virlo` + empty ids + `action="run"` → an error naming `virlo_monitor_ids`; (b) `action="list-monitors"` → **no** such error; (c) `action="run"` with every entry `brief_influence="override"` → **no** such error (the FR-144 carve-out — the case most likely to be got wrong). |

**Owner:** main session for all of it. T1 is ~11–14 lines, T2 net 0, T3–T5 are text, T6 is tests
(`tests/` is outside the G2 ceiling, which counts `hypesocials/**/*.py` only).

## 4. Invariants at risk

- **G2 line ceiling (CLAUDE.md rule 5): 13,486 / 13,500 — 14 lines of headroom.** T1+T2 must land
  net ≤14 lines. If the honest implementation exceeds that, **stop and escalate to the operator**
  for a ceiling decision — never trim docstrings silently to fit.
- **`--list-monitors` must not be refusable by the rule it exists to fix.** FR-251 requires it to
  run with no valid run plan. The `action` gate is load-bearing; T6(b) is its test.
- **Refusal is free** (`preflight.py:13-14`): the new check reads config only. No I/O, no session.
- **Warning vs error grade** (`preflight.py:16-18`): this is an *error* (refuses), deliberately —
  a run that cannot possibly deliver must not reach the confirm gate.
- **Brief-only runs (FR-144 / v1.6.8) — CONFIRMED BUG in the first draft, not a risk.** `--brief`
  never touches `sources.active` (only `cli.py:213` and `menu.py:205` write it), so `virlo` is still
  active on a brief-only run. `brief_only` is computed at `runner.py:297`, **14 lines after**
  `preflight.check()` at `:283` — a naive gate refuses before the carve-out exists. The live
  v1.6.8 brief-only run (`--brief ai-audit-cta:2 --yes`, 2/2 delivered, zero Virlo/MCP activity)
  would have been refused. T1's `entries` predicate mirrors `runner.py:297` verbatim so the two
  cannot drift. The `entries and` prefix is load-bearing: `all()` over the empty tuple that
  `runner.py:184` passes is `True`, which would exempt `list-monitors` for the wrong reason and mask
  a regression in the explicit `action` gate. `brief_influence` can also be `"blend"`
  (`plan.py:271`), which genuinely needs trends — `all(== "override")` correctly still refuses those.
- **`preview-sources` is deliberately refused, not warned.** Today `previews.py:106` prints
  *"the active source(s) returned nothing — no trend to judge"* and returns `EXIT_OK` — a false
  all-clear on the very action an operator runs to check their config.
- **The interactive menu is not a second guard.** `menu._pick_sources` (`menu.py:181-206`) validates
  only built-vs-unbuilt and never reads `virlo_monitor_ids`; `--yes` bypasses the menu entirely.
  Pre-flight is the only enforcement point. (A menu hint is possible at `menu.py:187-188` but is
  **out of scope** — it spends ceiling lines on a path `--yes` skips.)

## 5. Acceptance

1. **Verified BEFORE T3 is applied** (T3 removes the reproducer): `run.bat` → config `default` →
   the confirm prompt is **never reached**; refuses with exit **2**, naming
   `sources.virlo_monitor_ids` and `--list-monitors`. Nothing billed. *(Acceptance 1 and 2 are
   mutually exclusive after T3 — hence the ordering. T6(a) preserves the check permanently.)*
2. With T3 applied, `default` collects trends normally (same as `hypedigitaly.yaml`).
3. `run.bat --list-monitors` still works against a config with empty ids.
4. A brief-only run is not refused by the new rule (T6(c) is the standing test).
5. `pytest tests/ -q` green (272 tests baseline, +3 new).
6. `find hypesocials -name "*.py" | xargs wc -l` ≤ 13,500. **If T1 cannot be written honestly
   within the remaining 14 lines, STOP and ask the operator for a ceiling decision (CLAUDE.md
   rule 5) — never trim docstrings to fit.**

## 6. Verification commands

```
.venv\Scripts\python -m pytest tests/ -q
find hypesocials -name "*.py" | xargs wc -l | tail -1
run.bat --list-monitors
```

## 7. Rollback

`git checkout -- hypesocials/preflight.py hypesocials/runner.py configs/default.yaml prds/` —
no migration, no state file, no external side effect.
