# Gauntlet Loop — Frozen Technical Spec (Phase 2) — Revision 2

FROZEN at plan approval: types, per-critic enums, config keys, placeholder sets, and the money seam. Wave-2a builds against this without a design spike. Adapted from the Gauntlet Loop technique (fresh-context critic panel judging rendered frames only) to HypeSocials' unattended, budget-gated pipeline. Revision 2 folds in the three-reviewer pass (money seam, contract restructure, per-critic enums, fix-channel guardrails, failure semantics, economics).

## 1. Module & public API

New deep module `hypesocials/gauntlet.py`. Imports allowed: `models`, `vision_check`, `prompts_engine`, `util` — never `hypesocials.generate`, never `render`, never `budget` (no cycles; gauntlet neither prices nor spends).

```python
async def run_deck(frames, contract, rerender, *, cfg, call, log) -> GauntletReport
async def run_single(frame, contract, rerender, *, cfg, call, log) -> GauntletReport
# anchor pre-gate = run_single(anchor_frame, contract_for_frame_1,
#                              rerender_anchor, cfg=replace(cfg, rounds_max=2,
#                              critics=("brief", "craft")))
# There is NO separate check_anchor entry point — one loop, three call sites.
```

Pinned types: `call` = the existing `models.StructuredCall` seam (as `vision_check.check` takes today) · `log` = the existing event-log duck type · deadline/budget do NOT appear in the signature (see §2 money seam).

```python
RerenderFn = Callable[[int, str], Awaitable[RerenderResult]]   # (frame_number, fix_suffix)

@dataclass(frozen=True)
class RerenderResult:
    status: Literal["delivered", "declined_budget", "declined_deck_budget",
                    "declined_runway", "failed", "halted"]
    frame: FrameUnderTest | None
    cost_usd: float

@dataclass(frozen=True)
class FrameUnderTest:
    number: int
    source: Path | str            # local file OR Kie result URL (reel seed) — vision_check.load_images union

@dataclass(frozen=True)
class FrameContract:
    number: int
    body_lines: list[str]         # verbatim lines, in order; [] == wordless BY MANDATE
    wordless_reason: str          # "" | "empty_panel" | "over_sanity_ceiling" | "handle_or_url"
    truncation_suspect: bool      # from panel_map (FR-304c) — brief treats trailing "…" as content
    counter: str                  # "" when the deck has no counter
    signature: str                # "" except a signed anchor (wordmark text)
    is_list: bool                 # list/table frame -> FR-329 pair-integrity applies

@dataclass(frozen=True)
class DeckContract:
    frames: list[FrameContract]
    required_marks: list[str]     # FR-315 sanctioned tool marks (FR-330 REQUIRED side)
    forbidden_terms: list[str]    # creator identity forms, competitor names, unsanctioned brand_marks, §0.12 flag names
    style_dna: str; layout_zones: str; list_mode: str   # list_mode flattened prose, "" if none
    sanctioned_illegible: str     # derived from style: what this style deliberately renders unreadable
    platform: str

@dataclass(frozen=True)
class RoundVerdict:
    round: int
    per_critic: dict[str, list[FrameDefects]]   # critic name -> per-frame defects (empty list = pass)
    unavailable: tuple[str, ...]                # critics dropped this round

@dataclass
class GauntletReport:
    result: Literal["pass", "blocked", "degraded", "budget_stop", "deadline_stop", "skipped"]
    rounds: list[RoundVerdict]; rerenders: int
    rerender_cost_usd: float      # summed from RerenderResult.cost_usd
    critic_cost_usd: float
    degraded_gate: bool           # a critic was dropped as unavailable
```

**The money/runway seam (single owner = caller; reserve-then-submit).** `RerenderFn` — implemented as a closure in `_Deck` / `generate._one` / `reel` — owns reference assembly (anchor URL + nearest delivered neighbor URL, `upload_local` fallback + patches), the `discretionary` reserve against run cap AND per-deck `deck_budget_usd`, the D51 runway check, FR-317 exclusivity, and job pricing. Concurrent re-renders acquire an `asyncio.Lock`: under the lock, check `gauntlet_spend + reserved + projected > cap` (decline with `declined_deck_budget` if over), else reserve the projected cost and release; after the render returns, accrual replaces the reservation with the billed cost. Gauntlet only *accounts*: it maps `declined_budget`/`declined_deck_budget` → `budget_stop`, `declined_runway`/`halted` → `deadline_stop`, and sums `cost_usd`. Gauntlet never prices a job and never touches `env.budget` (preserves `carousel.py`'s module contract and D34).

## 2. The loop

```
for round in 1..cfg.rounds_max:
    judged = all frames if round == 1 else rerendered_frames        # brief & craft
    system always judges ALL frames (cross-frame consistency)       # FR-324 round-2 scoping
    verdicts = gather(critic(kind, frames_for(kind), contract) for kind in enabled)
      - a critic returning unparseable output: retry once (existing LLM retry), then drop
        for the DECK -> record in RoundVerdict.unavailable, set degraded_gate,
        log gauntlet_critic_unavailable; judge the round on survivors
      - ALL critics unavailable -> result "skipped" (ship as-is, tagged), never BLOCKED
    fails = merge(verdicts)     # frame -> union of defects; fail := bool(defects)
                                # pass:false with defects:[] -> logged critic_empty_fail, treated as PASS
    if not fails: return PASS
    if round == cfg.rounds_max: break
    for frame in fails:         # concurrently; permits/pricing inside RerenderFn
        fix = fix_instruction(frame, standing_codes_union(frame))   # §3 — canned remedies only
        res = await rerender(frame.number, fix)
        match res.status: delivered -> replace frame; declined_* / halted -> stop loop with mapped result
terminal (standing fails after final round) — FOUR TIERS (FR-325, amended Session 5.8/F9):
    leakage codes standing  (identity_leak, forbidden_mark, platform_chrome,
                             invented_text, translated)              -> BLOCKED, always
    contract codes standing (other brief codes + all system codes except
                             counter_placement and low-confidence system) -> per cfg.fail_action
    cosmetic standing alone (counter_placement only, no leakage/contract) or
    low-confidence system standing alone (system codes with confidence: low,
                             no leakage/contract) or
    final-round discovery (CONTRACT-tier defect whose (frame, code) first
                             appears on the final round, on a frame never
                             re-rendered, in a run with >= 2 rounds —
                             single-round gates keep full tier behavior;
                             terminal-only: no round left to fix it in) -> SUCCESS + GAUNTLET_DEGRADED
                             (cosmetic and low-confidence rows still
                             re-render each round; discovery cannot)
    craft-only standing                                              -> SUCCESS + GAUNTLET_CRAFT tag
                                                                        (cfg.craft_blocks overrides)
```

- **Fresh context:** each critic call = frames + `DeckContract` fields only. No render prompts, no reference images, no prior-round verdicts, no sibling verdicts. (Honest caveat, stated in FR-322: `style_dna`/`layout_zones` ARE render-prompt blocks — the only possible style referent.)
- One multi-image call per critic per round; images via `vision_check.load_images` (promoted public) at native resolution; unreadables dropped and re-mapped via its `positions` — **`frame` in verdicts = 1-based attachment slot**, engine re-maps to slide numbers (reuse the existing mapping, do not re-implement).
- **Anchor re-render re-chains:** if frame 1 is replaced in round r, later re-renders reference the new anchor; `system` re-judges all frames every round, so drift is caught.

## 3. Critics

| Critic | Prompt | Judges | Enum (per-critic, IN-SCHEMA) |
|---|---|---|---|
| `brief` | `prompts/critic_brief.md` | contract fidelity + leakage — PRESENCE, never quality | `missing_text, invented_text, translated, pair_break, missing_mark, forbidden_mark, platform_chrome, identity_leak, counter_value, signature` |
| `system` | `prompts/critic_system.md` | style contract + cross-frame consistency *against anchor baseline* | `style_palette, style_layout, style_consistency, counter_placement` |
| `craft` | `prompts/critic_craft.md` | execution quality — EXECUTION, never content | `garbled, truncated, contrast, logo_fidelity, composition, frame_integrity` |

**Anchor-baseline judging (F9-B, Session 5.8/amended):** The `system` critic judges cross-frame consistency against FRAME 1 (the anchor) as the fixed reference baseline, never against arbitrary siblings. A frame is inconsistent iff it deviates from frame 1's treatment; frame 1 itself is judged against the style contract only, not against any other frame. When a defect names a deviating frame, it names the frame that differs from the anchor, never the anchor for differing from the deviator.

Schema per critic call — strict JSON mirroring `vision_check._SCHEMA` conventions (`enum` = that critic's codes only, `required` everywhere, `additionalProperties: false`):

```json
{"frames": [{"frame": 1, "pass": true,
  "defects": [{"code": "<critic's enum>",
               "zone": "top|upper|middle|lower|foot|left|right|centre|chip|card|full_frame",
               "confidence": "high|low",
               "detail": "<= 200 chars"}]}]}
```

Bounds (in prompt AND schema): ≤3 defects/frame, ≤8 defects/call, exactly one row per attached image, no prose outside JSON. `craft` defects with `confidence: low` are recorded but do NOT fail the frame. By contrast, `system` defects with `confidence: low` ARE re-rendered each round (like high-confidence system defects) but are demoted at terminal: they do not block the deck even though they still attempt recovery through re-renders (Session 5.7/F8 — the craft rule suppresses failure entirely; the system rule is terminal-only).

**Prompt content requirements (T2.2):**
- Expected text presented as enumerated per-frame line blocks (`L1:`/`L2:`… + `counter:` + `signature:` rows; `(none)` for wordless-by-mandate) — the FR-329 referent and the wordless disambiguator.
- Wordless text (both halves): "(none) = wordless by mandate — counter/signature (when listed) are the only permitted strings; anything else readable is `invented_text`. Expected lines shown but absent = `missing_text`, never 'wordless'. The picture cannot tell you which; the contract does."
- Brief carve-outs (all four inherited from the old template): lettering inside a REQUIRED mark; style-sanctioned illegible filler (`sanctioned_illegible`); style-declared non-text glyphs; legible text inside a campaign brief's own product photo.
- Discipline lines: brief judges presence not legibility; craft never reports words missing/wrong/invented/translated (enum partition enforces this mechanically).
- `truncated` (craft) = lettering physically cut by frame edge or clipped by an overflowing container — a string ENDING in "…" is content, not truncation (cross-check `truncation_suspect`).
- Asymmetric strictness: leakage codes — "when unsure, FAIL; a person's name, handle, face or a competitor's mark reaching a published frame is the most expensive error this pipeline can make." Craft — "assume this frame WILL be published; fail only if a reasonable operator viewing it on a phone would refuse to publish; unsure ⇒ PASS with confidence: low." System — fail only on differences an ordinary viewer notices while swiping.
- FR-330 both directions: REQUIRED marks (absence = `missing_mark` — D-A semantics preserved) and FORBIDDEN list (presence = `forbidden_mark`/`identity_leak`); mark PLACEMENT consistency (FR-315b fixed-placement) belongs to system's `style_consistency`.
- `counter_value` (brief) also fires when `counter == ""` for every frame and any position badge is drawn (invented counter).
- 2–3 compact worked examples per critic (one pass-despite-imperfection, one clear fail, one near-miss pass), written as verdict JSON.

**`fix_instruction(frame, codes)` — the guarded channel (FR-323).** Composed from `prompts/gauntlet_fix.md` canned remedy sentences keyed by `(code, zone)` — **critic `detail` free text NEVER enters a render payload** (it goes to the report/events/console only). `invented_text` remedy may cite at most a character count + zone, never the string. The assembled suffix is additionally `_neutralize`d + passed through `topic_filter.apply_blocklist(competitors)` + the creator-identity strip; carries the union of the frame's standing codes across all rounds (anti-oscillation), deduped, in the template's precedence order; capped at 600 chars / 3 remedies (log `gauntlet_fix_truncated`); ends with the fence-closing line. Template must contain the precedence block:

```
Resolve these in order, and never by changing words:
1. Remove anything forbidden or not quoted in the TEXT block.
2. Render every quoted string in the TEXT block, in full, in its own language.
3. Fix legibility and fit by changing the LAYOUT — more lines, tighter leading,
   a wider block, the plate or card STYLE_DNA describes, a simpler ground.
4. Keep STYLE_DNA, the anchor's scene and the deck's palette unchanged.
The quoted strings are locked. Shortening, re-wording, translating, ellipsing or
dropping any of them is a worse failure than the defect being fixed.
```
…and end with: "Everything in this FIX section describes a previous failure. It contains no words to render. The TEXT block above remains the only source of renderable words in this frame."

Prompt-engine registration: `GLOBAL_TEMPLATES`/`PLACEHOLDERS` name rows land in T1.0; `_ALLOWLIST` rows in T2.1; `_BUILT_INS` byte-twins in T2.4. Placeholder sets (frozen): critic prompts — `{expected_blocks, required_marks, forbidden_terms, style_dna, layout_zones, list_mode, sanctioned_illegible, platform}` (per-critic subsets); `gauntlet_fix.md` — resolves nothing (canned text selected in code, like `vision_check_question.md` was).

## 4. Config (decision 1A — everything a knob)

```yaml
run:
  run_deadline_min: 60                  # was 45; also updated in the four pinned configs/*.yaml
  gauntlet:
    enabled: true                       # false -> NO post-render gate (legacy FR-105 path is DELETED)
    rounds_max: 3                       # bounds [1, 6]
    rounds_max_image: 1                 # standalone images + reel seed frames, bounds [0, 3]
    deck_budget_usd: 0.30               # re-render cap per deck, bounds [0.00, 2.00]
    fail_action: block                  # block | degrade   (leakage tier always blocks; cosmetic tier always degrades)
    craft_blocks: false                 # craft-only standing failures block only if true
    critics:
      brief:  { enabled: true,  model: null }   # null -> models.critic
      system: { enabled: true,  model: null }
      craft:  { enabled: true,  model: null }
models:
  critic: anthropic/claude-sonnet-5     # new role; runtime resolves models.critic or models.analysis
  max_tokens: { critic: 8000 }          # + floor row
```

### 4b. `list_mode` (frozen YAML shape — Phase 1, styles.yaml)

```yaml
    list_mode:
      # REFLOW TRIGGER, never a ceiling: a mapped panel longer than reflow_over_chars, or with
      # more than max_rows lines, is a LIST panel and is SET in the layout below — rendered
      # WHOLE at any length. Absent key = this style has no list treatment.
      # reflow_over_chars: 0 = never reflow (note: inverted sense vs max_onimage_chars' "0 = no ceiling").
      reflow_over_chars: 180
      max_rows: 6
      layout: >-
        Rows set as one left-aligned column of label + value pairs inside a single card:
        every source line keeps its own row, a label and its value never separate or swap rows,
        rows shrink together rather than one dropping, and an over-long row wraps under its own
        label with a hanging indent.
      overflow: reflow                  # reflow | two_column — never a value that drops text
```

Now ships to the slide renderer via a dedicated `{{list_treatment}}` placeholder in prompts/gpt-image-2/carousel_slide.md (placed inside the SLIDE CONTENT region, empty for non-list panels). The old gated append to `{{layout_zones}}` for slide text is removed. Never enters `max_onimage_chars`/`_budget_line` (B6 regression) and never enters `copywrite._panel_verdict` (D50). Validation: absent = legal; present-but-malformed = FR-295 exit-2. Styles.yaml header authoring block documents it.

Plumbing facts for T2.x (verified): config loader handles nested dataclasses + `dict[str, dataclass]` as-is; needed additions are `_BOUNDS` rows, `_ROLE_PRICE_KEY["critic"]="sonnet"` (`budget.py:86` — else critic calls price at $0), `max_tokens` rows, and the `runner._role_settings` two-way ternary → dict rewrite (`runner.py:573-582`; `llm.py:169` RAISES on unknown role). Advisory: `rounds_max × image_job_timeout_s` folded into `carousel_throughput_warning` (`config.py:1040-1069`).

## 5. Cost model & honest economics (FR-107/FR-326)

- Per-call: 8-frame critic call ≈ 13.5k input tokens + ~434 completion (measured Session 5 canary #1; requests apply `reasoning: {effort: low}`; estimator uses 1,000 tokens/call as honest-high) ≈ **$0.056** preliminary; full 3-critic round ≈ **$0.17/deck**; 3 rounds ≈ **$0.50/deck** critics alone (vs. previous $0.60) — motivates bounded reasoning and round-2 scoping. Critic spend dominates re-render cost vs. $0.30 re-render budget.
- **Compounding false positives:** P(clean round) = (1−p)^(critics × frames). At p=2% per-critic-per-frame, an 8-slide deck passes round 1 only ~62% of the time; at 5%, ~30%. This is why: per-critic enums, confidence:low non-failing, craft publish-bar phrasing, worked examples, and round-2 scoping (F19: brief/craft re-judge only re-rendered frames → saves ~55-60% of round-2/3 critic spend).
- Allowance = `Σ deck_budget_usd + decks × enabled_critics × rounds_max × est_call_usd` — `allowance=True` lines: displayed + worst-case provisioned, **never in `expected_usd`, never trims creatives** (FR-106a). Acceptance test pins this.
- Wave 2c measures actuals (rounds-to-converge, $/deck) against these numbers.

## 6. Outputs & observability (FR-296/FR-328)

- `meta.yaml.gauntlet` (plain dict on `AssetRecord`): `{result, degraded_gate, rounds: [{round, unavailable, critics: {name: n_fails}, failed_frames, rerendered}], rerenders, rerender_cost_usd, critic_cost_usd}` — every terminal path.
- `GAUNTLET_REPORT.yaml`: full per-frame per-critic defects (code/zone/confidence/detail) per round — the operator-readable critic report (decision 4A). `BLOCKED.txt`: plain-language paragraph + pointer.
- Statuses: `AssetStatus.BLOCKED` via `packager.block()` (artifacts kept — FR-74) + `PlanEntryStatus.BLOCKED` → excluded from trend-history `record_use` and from `set_latest` satisfaction; gallery BLOCKED badge (distinct from failed-card rendering); summary column; any BLOCKED ⇒ exit 1.
- Console: `GAUNTLET deck Li_car_… round 2/3 — 2 frame(s) failed (brief: invented_text s4; craft: contrast s2) — re-rendering 2`.
- Events: `gauntlet_round`, `gauntlet_rerender`, `gauntlet_blocked`, `gauntlet_budget_stop`, `gauntlet_deadline_stop`, `gauntlet_critic_unavailable`, `gauntlet_fix_truncated`, `critic_empty_fail` — full detail events-only (D30); run.log gets redacted console lines.

## 7. Interactions & edge cases

- **FR-317:** gauntlet re-renders = fresh submissions, own ledger rows, never a second poll window, never themselves resubmitted; `NO_RUNWAY` refusals excluded from both resubmit predicates.
- **Viability first:** a deck skipped by the D51 short-circuit never enters the gauntlet.
- **Deadline:** runway checked inside `RerenderFn` before each submit; `deadline_stop` keeps the last verdict, terminal per tier policy, report notes the cut. Grace-poll semantics unchanged.
- **`--yes`:** zero interactive branches. **CLI:** `--gauntlet/--no-gauntlet` (replaces `--vision-check`).
- **Reels:** seed frame only (`run_single`, source = Kie URL); finished video out of scope.
- **Legacy:** FR-105 machinery deleted in Wave 2b (`check()`, `_carrier`, `_verdicts`, `_Deck._check/_rerender`, `generate._vision` vision branch, `reel._check_seed`, `vision_check_question.md`); `expected_text`, `retry_plan`, `load_images` live on as gauntlet inputs. Rollback = `gauntlet.enabled: false` (no gate) — cheap mode = brief-only, rounds_max 1, same code path.
- **Windows/async:** critic calls via existing async `llm` seam under `max_inflight_llm_calls`; no subprocesses; atomic report writes via existing packager write helpers.
