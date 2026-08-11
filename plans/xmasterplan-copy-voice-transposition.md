# xmasterplan — copy voice: transposition instead of abstraction

**Status: APPROVED for execution 2026-08-11.** Both operator decisions locked (§2): the `voice` influence
mode is in, and V1+V2 ship together. Execute with `/xecutor`. Sibling plan:
`plans/xmasterplan-virlo-throughput-and-fidelity.md` — **this plan supersedes its A22, A23 and A25, and
depends on its A20.** See §6 for the collision resolution; layering both as written will conflict.

---

## TL;DR (plain English)

Our copy sounds like a LinkedIn thought-leader because **the copy prompt contains no instruction about how
the words should sound.** Zero. `grep -iE "tone|voice|register|casing|contraction|emoji|punctuation"` across
all 171 lines of `prompts/copywriter_system.md` returns nothing.

Worse, the prompt's central mechanism actively destroys voice: it asks the model to *abstract the source
hook into a pattern*, then *write from the abstraction*. Register dies at the compression step.

The fix is to stop abstracting and **transpose** — rewrite the source line by line with its surface form
held fixed (line breaks, casing, punctuation, contractions, emoji, length) while every noun, claim, offer
and CTA becomes ours. Same topic, same voice, our words.

---

## 1. Diagnosis — all measured, treat as given

### 1.1 The prompt has no voice spec

```
grep -iE "tone|voice|register|casing|lowercase|contraction|fragment|emoji|punctuation|persona|banned" \
     prompts/copywriter_system.md
→ no matches
```

171 lines constraining character counts, JSON shape, sibling distinctness and claim syntax. Nothing about
sound. **The register we ship is the model's untutored default.**

The sibling prompt `prompts/style_brief_system.md` **does** have a full `BANNED LANGUAGE` section. The
visual path got a slop filter; the copy path did not. That asymmetry is the whole story.

### 1.2 The abstraction step is the bug

`copywriter_system.md:50-56` enumerates the abstraction dimensions as *"the kind of claim, the person it
addresses, its length, its syntax, what it withholds"* — five propositional dimensions, **zero surface
dimensions** — then instructs the model to instantiate *from that abstraction*.

Verified across all 34 shipped `hook_pattern_used` values in `output/*/*/meta.yaml`:

```
mentions casing 0 · contraction 0 · emoji 0 · punctuation 0 · lowercase 0 · register 0 · voice 0
any register-adjacent token: 2/34
```

Every value is a taxonomy of persuasion. *"Negative-outcome claim, second person, seven words, no verb in
the opening clause"* is satisfied identically by a McKinsey memo and a lowercase TikTok caption.
`hook_pattern_used` is a faithful audit log of a lossy compression.

The cross-language rule (`:62`) formalises the loss — *"syntax and cadence are the obligation"* — for
exactly the trends that need register help most.

### 1.3 `niche.vibe: "contrarian"` is the only style word that reaches the model

Measured across 21 real copy calls with a logged prompt: **`brand_context` empty 21/21**,
**`platform_conventions` empty 21/21**. One config word is doing all the work, and the model renders
"contrarian" as *grammar*:

| Tell | Frequency (n=34 captions) |
|---|---:|
| `Most …` sentence-initial | **18/34** |
| Negation frame (`do not need` / `is not`) | 22/34 |
| Corrective second sentence (`They need…` / `It is…`) | 17/34 |
| Em-dash appositive | 21/34 |
| 4+ item parallel fragment list | 8/34 (36 items) |
| Hedges (`plainly` / `actually` / `honest`) | 7/34 |
| **Emoji** | **0/34** |
| **Sentence starting lowercase** | **2/34** |
| **Contractions** | **4/34** |

Sentence length: mean 12.1 words, σ 8.6, **77% inside 5–20 words.** Metronomic.

18 of 34 captions are literally one skeleton: `Most X do not need Y.` → `They need Z.` → 4-item parallel
list → `Save this / Start with one …—not the whole thing.` It reproduces across three trends, three
platforms and both `analyzed` and `direct` modes, so it is not trend-driven.

### 1.4 The brief's specification prose is being copied as a voice sample

It is the only block of our-voice English in the prompt, so it functions as the de-facto few-shot:

| `brief.yaml` | Shipped caption |
|---|---|
| `hook_angle: "most AI pilots stall because nobody measured the workflow before automating it"` | *"They stall because nobody measured the workflow before automating it."* |
| `offer: "…say plainly where it does not"` | *"…say plainly where it cannot"* |
| `message: "The honest way to find out…"` | 7/34 captions carry `plainly`/`honest`/`actually` |
| `structure: "one-line claim hook, one supporting line, then the CTA line"` | the exact three-paragraph shape of every `ai-audit-cta` caption |

**The operator wrote a spec; the model treated it as an exemplar.**

### 1.5 `tone`/`avoid` are purely subtractive

`no hype vocabulary` · `no revolutionary` · `no game-changing` · `no fear-mongering` ·
`no fabricated urgency` · **`no emoji-stuffed bullet lists`** · `no guarantees that cannot be verified`

Every entry is a subtraction. Strip hype, urgency, emoji and unverifiable claims from social copy and
corporate-neutral is the arithmetic residue. **0/34 captions carry an emoji while source overlays carry
🤯 🧠 ⚡ 🎯 💻 👀.** No additive voice spec exists anywhere in the repo.

### 1.6 Nobody owns voice

The prompt states precedence for structure-vs-message (`:124-126`, *"The pattern is the container; the
brief is what goes in it"*) and the style-brief prompt states it for look-vs-brand (*"Where the trend's look
and this context disagree, describe the trend's look"*). **`copywriter_system.md` has no equivalent
sentence.** Under `blend`, source supplies pattern and brief supplies message — voice is contributed by
nobody, so it defaults to house style.

### 1.7 The few-shot block is corrupted where register lives

`_source_hooks` (`prompts_engine.py:537-542`) prefixes `f"{i}. "` without re-indenting an item's own
newlines. The model actually received:

```
4. Claude
5 things to do
Immediately to learn Claude
5. I'M OUTDATED AND
```

`5 things to do` sits exactly where item 5 would. `_trend_texts` compounds it by joining lists with `" | "`
while internal `\n` survives, making panel boundaries unrecoverable. **The line-break structure — which IS
the register signal in a TikTok text card — is rendered ambiguous by the numbering.**

Also: `_neutralize` (`prompts_engine.py:687-689`) breaks runs of 3+ chevrons, so `"ChatGPT isn't the only
one >>>"` reaches the model as `> > >`. `"Remember.. >>"` (two chevrons) survives.

### 1.8 No post-generation text check exists

`vision_check` is scoped to two image questions and explicitly told *"Judge nothing else — not aesthetics,
composition, brand fit or truthfulness."* The only gate on copy is `_apply_budgets`, a character trim that
fired **72 times** historically and **damages** what it touches: `'Book the free AI audit at'`,
`'Find the real opportunity—and the'`.

Nothing would ever have caught two siblings in `20260809_220436_wrfc` shipping **byte-identical** captions
despite the prompt's *"Every sibling gets its OWN angle."*

### 1.9 What we are throwing away

`panel_text_full` is populated on **22/22** sorted slideshows and dropped by the wrapper
(`_norm_slideshow`, `server.py:207-235`). It is the complete panel-by-panel script, `"Panel N: …"` blocks
joined by `\n\n`, up to 2,182 chars / 309 words. Real example (1,254,659 views):

```
Panel 1: NOW YOU KNOW AI
Your Claude is
too agreeable.

Panel 4: NOW YOU KNOW AI
The default
isn't honest.
It's pleasant.
It validates weak ideas. Smooths over gaps.
Confirms your frame — even when your frame
is wrong. That's not a bug.

Panel 8: Don't ask: is this good?
Train it to ask:
what am I missing?
Better prompts help once.
Better defaults compound.
```

Also dropped: `hook_type` (22/22), `text_overlay_purpose` (17/18), `visual_hook_type` (17/18),
`content_format`, `emotional_tone`, `sentiment`, `cta_usages` (carries the literal CTA wording plus a type
enum), `trend_references`, `panel_text_word_count`.

**Rejected as unreliable:** `speaking_style` (8/18) and `caption_style` (5/18). Virlo's own
`low_confidence_fields` flags exactly those. A field present a third of the time produces a prompt block
whose *shape* changes run to run — worse than absent, because the model cannot tell "no speaking style"
from "not measured".

**No transcripts.** `transcript_raw` does not exist on agent endpoints; only the digest family returns it,
and those rows share **zero** ids with agent rows (100 vs 100 compared). Do not design for transcripts.

---

## 2. Operator decisions — LOCKED 2026-08-11

| # | Decision | Choice |
|---|---|---|
| **D-1** | The override-mode hole (§2.1) | **A — add a third `influence` mode, `voice`.** Brief owns message/offer/CTA; the **trend owns voice**; a trend IS consumed. Needs a `briefs.py` enum change, `plan.py` handling, and a PRD amendment |
| **D-2** | Scope (§2.2) | **B — V1 + V2 together.** ~+1,040 code lines. No ceiling (CLAUDE.md rule 5, v2.0.0) — growth is reported with per-task attribution |

Consequences of D-2 being taken up front rather than after measurement:

- `surface.py` is a **barrier task** — its API is imported by both `copywrite.py` and `prompts_engine.py`.
  §9a trigger 3 fires, and §21's remedy is a barrier, **not** an orchestrating parent.
- The §7 dry run moves from "the gate on whether to build V2" to "the acceptance test for both". If it
  still shows the §1.3 tells, the next lever is a different copy model — **not** more instruction.
- `prompts_engine.py` reaches ~1,183 lines, so the `_BUILT_INS` extraction (§5, V2 wave) is now in scope
  rather than conditional.

Consequences of D-1:

- `{{source_script}}` is non-empty for `ai-audit-cta` creatives, so transposition applies to the operator's
  only shipped brief — which was the entire point.
- A `voice`-mode creative **consumes a trend**, so it costs one analysis call and counts against
  `batch_ceiling`. That is a real cost change from `override`, which consumed nothing. Price it at the
  Confirm gate.
- The conditional bans in §3.3 stay conditional for `voice` mode (a source exists to license them). They
  remain **absolute** for any brief left on `override`.

### 2.1 The override-mode hole — the gap D-1 closes

`niches/hypedigitaly/briefs/ai-audit-cta/brief.yaml:15` is `influence: override`. Per `plan.py:359-362`,
an override creative **consumes no trend** — `runner.py:313` skips Virlo entirely when every creative is an
override brief.

**So `{{source_script}}` renders empty and transposition is completely inert for the operator's only
shipped brief.** For those creatives the anti-slop blocklist is the *only* voice control.

Three options:

| | Option | Consequence |
|---|---|---|
| **A** ⭐ | Add a third influence mode, `voice` — the brief owns message/offer/CTA, the **trend owns voice** and a trend is consumed | Transposition applies to brief creatives. ~15 lines + a `briefs.py` enum change + a PRD amendment. **Recommended** — it is the mode the operator actually wants and neither existing mode provides |
| B | Switch `ai-audit-cta` to `influence: blend` | Zero code. But `blend` keeps the trend's *visuals* and its analysis cost, and its precedence line ("the trend's style brief wins on layout") was written for a different purpose |
| C | Accept that brief creatives get blocklist-only voice control | Zero code. The operator's main creative keeps sounding robotic |

### 2.2 Scope — the verification layer

Two independent designs produced two very different numbers, because they costed different scopes:

| Scope | Lines | What it buys |
|---|---:|---|
| **V1 — the prompt rebuild + plumbing** | **≈ +150 code, +130 prompt** | The transposition move, the VOICE spec, the precedence rule, the blocklist, 100% of the text fed in with boundary-safe layout, view-ranked exemplars, the audit fields |
| **V2 — the verification layer** | **≈ +760** | `surface.py` (offline surface-profile comparison), the drift check, the echo check, one re-ask, drift/echo persistence, gallery badges, the `trim_words` function-word fix, per-role fences |

**Recommendation: ship V1, measure, then decide V2.** V1 is where the voice fix lives; V2 is insurance that
the fix held. Shipping both blind means ~910 lines against a hypothesis that has never been tested against
the real template. The §7 dry run is the cheap way to find out how much V2 is actually needed.

---

## 3. The design — V1

### 3.1 Transposition replaces abstraction

Real worked example from the design, on real source lines:

```
SOURCE (panel 1, @nowyouknow_ai, 1,254,659 views)
  | NOW YOU KNOW AI
  | Your Claude is
  | too agreeable.

TRANSPOSED
  | Your automation is
  | too obedient.

held:    possessive second-person subject · break after the copula · two lines ·
         sentence case · one full stop, last line only · two-word evaluative predicate
dropped: the watermark line "NOW YOU KNOW AI"
```

```
SOURCE (panel 4, seven lines)
  | The default
  | isn't honest.
  | It's pleasant.
  | It validates weak ideas. Smooths over gaps.
  | Confirms your frame — even when your frame
  | is wrong. That's not a bug. Helpful, in AI terms,
  | usually means agreeable.

TRANSPOSED
  | The pilot
  | isn't measured.
  | It's assumed.
  | It automates the loud step. Skips the slow one.
  | Copies your process — even when your process
  | is the problem. That's not a tooling gap. Shipping,
  | in pilot terms, usually means guessing.

held: three stacked short opening lines each closing on a full stop · the contractions
      isn't / It's / That's in their original slots · one em dash in the same position doing
      the same concessive work · a verb-initial fragment pair on line 4 · the mid-sentence
      break before "is" · sentence case throughout · no emoji, because the source has none here
```

⚠️ **Note what that second example licenses.** The negate-then-correct couplet and the fragment run are on
the banned list — *unless the source line does them at that position*. Here it does, so they are carried.
The model may not import them into a line whose source line is a plain declarative. **The bans are
conditional on the source, which is what stops the blocklist from flattening a source that is genuinely
punchy.**

The five-step move: (1) take the source block closest in function · (2) hold the surface — same line count,
break points, casing, terminal punctuation including its absence, contractions in the same slots, emoji
count and position, platform devices unchanged, line lengths within a few characters · (3) replace every
noun/claim/offer/CTA with ours · (4) **stay on the same topic** — *"Do not look for 'the equivalent claim in
our niche'; the offer arrives in the CTA line, where the source put its own"* · (5) record it.

### 3.2 The precedence rule — the missing sentence

```
The source owns HOW it is said: voice, register, casing, punctuation, rhythm,
line breaks, emoji, devices, length.

The brand owns WHAT is said: the subject as it applies to us, the claim, the
proof, the offer, the call to action, the language the creative is written in.

Where the source's voice and the brand's stated tone disagree, follow the
SOURCE's voice. A brand tone line reading "short sentences, no hype
vocabulary" is a constraint on our vocabulary and our claims, never a licence
to flatten a source that shouts, runs long, or writes in lower case.
```

**The brand overrides the source's voice in exactly three places and nowhere else:**
1. a factual claim we cannot stand behind — no invented client, number, percentage, timeline or case study,
   whatever the source asserts;
2. a safety, legal or dignity line — no fear-mongering about job loss, no medical/legal/financial promise,
   no punching at a named person;
3. somebody else's name or mark — never carried, in any casing.

*Everything else the brief calls "tone" loses to the source script.*

⚠️ **This is the tension the design cannot resolve in code**, and the operator should expect it: when a
5.5M-view deck is ALL CAPS and the brand tone is lowercase-calm, the rule above says copy the source. If V2
ships, its drift check would then *punish brand-compliant copy*. Resolution: **source wins on SURFACE
(casing, punctuation, breaks); brand wins on LEXICON (words, claims, offer, CTA).** Only the template can
state that; `surface.py` cannot express it.

### 3.3 The blocklist the copy path never got

Keyed to the *measured* tells of §1.3, each with a concrete replacement, each **conditional on the source
not doing that exact thing at that exact position** — and **absolute when there is no source script**
(override mode, §2.1).

### 3.4 100% of the text, with boundary-safe layout

The `| ` line-prefix protocol solves §1.7 without inventing a delimiter that could collide with content:

```
SOURCE POST — the ONE post this creative is transposed from.
  8 panel(s) · 309 word(s) · slideshow · 5,487,494 views · hook_type story_tease
[[[BEGIN DATA: SOURCE SCRIPT — verbatim, exact surface form]]]
[PANEL 1 of 8]
| Remember.. >>
[PANEL 2 of 8]
| ChatGPT isn't
| the only one
| >>>
[[[END DATA: SOURCE SCRIPT]]]
```

A `| ` prefix marks where each original line starts and ends; `|` alone is a blank line. Bracketed headers
are tool-added and explicitly named as not part of the text. **Everything after `| ` is exact surface.**

Budget: `source_script` **3,500 chars** (observed max 2,182 — 1.6× headroom, admits every observed post
whole), `source_exemplars` **8 × 300 chars**, whole section **6,000**. On overflow, truncate on **panel
boundaries only** — never `trim_words`, because a half panel teaches a half rhythm. Log
`source_script_truncated`.

⚠️ **The 3,500 ceiling is a guess on n=22.** A 9,000-char script gets 60% dropped and "100% of the text"
quietly becomes 40%. It is logged; the *promise* is not renegotiated.

### 3.5 View-ranked exemplars

`media = [*videos, *shows]` (`virlo.py:264`) concatenates two independently-sorted lists, so **every video
outranks every slideshow** — a 400-view clip ahead of a 5.5M-view deck. Replace with a real merge on
`views`. Deliberately a full re-sort, not `heapq.merge`: the inputs are only *claimed* sorted, and a monitor
whose `order_by` was ignored would silently feed a merge that assumes sortedness.

**Verified non-regression:** `sum`, `median`, `max` and the engagement sums are order-independent, and
`_velocity` sums over the same multiset. **No FR-5 strength value changes.**

### 3.6 Audit fields

| Field | On | Why |
|---|---|---|
| `transposition_map: list[str]` | `CopySet`, `AssetRecord` | source line → our line → what was replaced. **Must be `list[str]`** — `packager._plain` cannot serialize a dataclass and would raise on every `meta.yaml` |
| `surface_carried: str` | `CopySet`, `AssetRecord` | fixed-slot record of what surface features were held, and what was dropped as a watermark |
| `claim_swap: str` | `CopySet`, `AssetRecord` | replaces A23's `substance_carried_over` — the topic is now the *same*, so the audited thing is the claim swap, not the territory shift |

⚠️ **`_copy_schema` is generated from `CopySet` with every property required** (`copywrite.py:281-289`).
A new output field is not a prompt-only change — it must be a `CopySet` field, and the moment it is, the
schema requires it on **every** call including built-in-fallback ones. That is the sync forcing function.

⚠️ **`max_tokens.copy` 3000 → 6000 in the same change.** The new fields add ~400–600 output tokens per
sibling; a 6-sibling group under 3,000 tokens truncates → `degraded` → splits into 6 per-creative calls,
silently doubling copy cost. Cap `transposition_map` at 4 entries **in the template**, or an 8-panel deck
yields 8 entries × 6 siblings.

### 3.7 Fixing the brief-as-exemplar leak

Two halves:
- **Prompt:** present `{{brief_directives}}` inside its own explicitly-labelled *specification, not
  exemplar* fence, stating that its prose is a constraint list and never a voice sample.
- **`brief.yaml`:** the operator should add an additive voice line and reconcile
  `avoid: "no emoji-stuffed bullet lists"`, which currently zeroes emoji entirely against sources that use
  them. ⚠️ `briefs.py:_directives` requires `str` values and applies `" ".join(text.split())` — **a brief
  cannot carry a list or any line structure.** Directives must stay flat strings.

---

## 4. V2 — the verification layer (deferred pending §2.2)

**`hypesocials/surface.py`** — new, pure, offline, deterministic, stdlib-only, zero package imports.
`profile()` / `drifts()` / `echoes()` / `render_line()` / `target_chars()`.

Nine metrics with calibrated tolerances: `caps_ratio` (±0.25 — source decks swing 0→1), `lower_start_ratio`
(±0.34 — quantises to thirds on 3 lines), `contraction_rate` (±6.0, **self-disables on non-English —
i.e. on the operator's Czech config**), `emoji_per_line` (binary), `sentence_len_mean` (ratio 0.6–1.7,
asymmetric because Czech words are longer), `sentence_len_stdev` (0.4–2.5), `punct_histogram` (cosine ≥0.70
— one number instead of 15 tolerances), `line_break_density` (0.5–2.0), `mean_line_chars` (0.55–1.45).

**Runs after `_to_copyset`, before `_apply_budgets`** — `_apply_budgets` mutates the strings, so measuring
after it would grade the trimmer's output and fire on every trimmed asset.

**Three tiers:** always measure and log (free) → re-ask once when ≥2 active features drift → second failure
ships and tags `COPY_STYLE_DRIFT`. **Exactly one re-ask, unconditionally, whichever check fired.** That is
why it terminates — no fixpoint search, no oscillation.

**Echo outranks drift** — an echo is a legal risk with a named victim; a drift is an aesthetic miss.
Removing one echoed token cannot push an 8-feature ratio-normalised bundle out of band on two features.

The highest-value single line in V2:

```python
effective_target = min(budget, round(source_mean_line_chars * 1.15))
```

A 13-char source panel yields a **15-char** target, not 42. `min()` guarantees it can never raise. **This is
what makes our deck look like theirs instead of like a 42-char-max deck.** And `mean_line_chars` is then
evaluated against `min(source_mean, effective_target)`, so the check can never fire on the budget's own
constraint.

Also in V2: the `trim_words` function-word fix (`'Book the free AI audit at'` → `'Book the free AI audit'`,
on a defect that fired 72 times), and per-role fence families so `>>>` survives unmangled.

⚠️ **The fence change touches a prompt-injection control.** It strengthens it, but §18 requires a second
approver for security changes. Route it that way.

⚠️ **V2 delivers *visible* verbatim reuse, not *zero*.** A second echo ships tagged. If the requirement is
zero, the hard-block variant (blank the on-image text, A20's tier) is the right artefact and was not chosen.

---

## 5. Waves

**Dispatch: FLAT (CLAUDE.md §9a).** §9a trigger 3 fires in V2 only (`surface.py`'s API is imported by both
`copywrite.py` and `prompts_engine.py`) — and §21's own remedy for trigger 3 is **a barrier, not a parent**:
the shared module is authored and unit-tested as one leaf task before the fan-out. **No orchestrating
parent anywhere in this plan.**

### V1

| Wave | Tasks | Assignee | Path set (exclusive) | Barrier |
|---|---|---|---|---|
| **V0** | D15: FR-100 exemplar count 3–5 → configurable · new FR for the transposition contract and the audit fields · precedence rule in 50-promptcraft · `max_tokens.copy` 6000 in 30-configuration · the `voice` influence mode if §2.1-A is chosen | `technical-writer` | `prds/**` | **Conductor re-reads every amended anchor against the file.** The last Wave-0 agent on this repo shipped a wrong FR and deleted an abort cause — reports are not evidence |
| **V1a** ‖ | `models.py` (3 audit fields, `Exemplar`, `PLACEHOLDERS`, 2 `DegradationTag`s), `config.py` (`max_tokens.copy` 6000, exemplar count, `Transposition`), `configs/*.yaml`, **`surface.py` (new — the V2 barrier module, stdlib-only, authored and unit-tested here)** | `python-pro` | `hypesocials/models.py`, `hypesocials/config.py`, `hypesocials/surface.py`, `configs/*.yaml` | `pytest -q`; `pytest -q tests/test_surface.py` (pure module, cheap total coverage); assert `json_schema_for(CopySet)` still generates |
| **V1a′** ‖ | **The `voice` influence mode (D-1)** — `briefs.py` enum + validation, `plan.py` handling (consumes a trend, applies variants, keeps the brief's message/offer/CTA), `niches/hypedigitaly/briefs/ai-audit-cta/brief.yaml` → `influence: voice` | `python-pro` | `hypesocials/briefs.py`, `hypesocials/plan.py`, `niches/**` | `pytest -q`; a `voice` brief consumes exactly one trend and its `{{source_script}}` renders non-empty; an `override` brief still consumes none |
| **V1b** ‖ | Wrapper: 9 slideshow + 8 video keys incl. `panel_text_full`. Adapter: `_by_views` merge, `_exemplars`, `_set` fields, `source_script` | `python-pro` | `hypesocials/virlo_mcp/server.py`, `hypesocials/sources/virlo.py` | `pytest -q`; `total_views`/`median_views`/`engagement` **byte-identical** to pre-change; view-ranked order across a video-heavy + slideshow fixture |
| **V1c** | Builders: `_source_script` with the `\| ` protocol, `_source_exemplars`, `_trend_texts` cut (literal rows leave), allowlist + truncation-order entries | `python-pro` | `hypesocials/prompts_engine.py` | `pytest -q`; panel-boundary truncation never cuts mid-panel; every new slot resolves |
| **V1d** | The prompt template + `prompts/README.md` mapping table + the built-in fallback kept in sync | `prompt-engineer` | `prompts/**` | All slots resolve; `transposition_map` capped at 4 in the instruction; source-owns-surface / brand-owns-lexicon stated |
| **V1e** | Wire-in and operator surfaces | **conductor** (aggregating files are never delegated) | `copywrite.py`, `generate/__init__.py`, `outputs/gallery.py`, `previews.py`, `runner.py` | `pytest -q`; a `tmp_path`-only test that `meta.yaml` carries the three audit fields |
| **V1f** | Tests | `test-automator` | `tests/**` | Full `pytest -q`; `find hypesocials -name "*.py" \| xargs wc -l` reported **with per-task attribution** |
| **V1g** | Live verification + the §7 dry run against the real template | **conductor** | — | §7 |

V1b‖V1a launch in one message; V1c after V1a (needs the new fields); V1d parallel with V1c. Conflict audit:
`models.py`/`config.py` V1a only · `server.py`/`virlo.py` V1b only · `prompts_engine.py` V1c only ·
`prompts/**` V1d only · `copywrite.py`/`runner.py` V1e only. **Disjoint, verified.**

### V2 — in scope per D-2, sequenced after V1c/V1d

`surface.py` itself moved **into V1a** as the barrier module, so V2's remaining work fans out cleanly:

| Wave | Tasks | Assignee | Path set (exclusive) | Barrier |
|---|---|---|---|---|
| **V2a** ‖ | The audit tier in `copywrite.py`: `CopyAudit`, echo-before-drift order, **exactly one** re-ask, `CopyResult` sets, `_to_copyset` | `python-pro` | `hypesocials/copywrite.py` | `pytest -q`; a stubbed-call test proving **one** re-ask and never two; echo outranks drift; the audit runs **before** `_apply_budgets` |
| **V2b** ‖ | `prompts_engine.py`: per-role fence families (so `>>>` survives), `target_chars` wiring into `_budget_line`, the `trim_words` function-word fix, **`_BUILT_INS` → `hypesocials/prompt_builtins.py`** | `python-pro` | `hypesocials/prompts_engine.py`, `hypesocials/prompt_builtins.py`, `hypesocials/util.py` | `pytest -q`; a panel containing `>>>` renders **unmangled** under `[[[` fences and **is** mangled where a template uses chevrons; `trim_words('Book the free AI audit at', 26)` leaves no dangling function word |
| **V2c** | Wire-in and operator surfaces (drift/echo tags, badges, preview line, re-ask pricing) | **conductor** | `generate/__init__.py`, `outputs/gallery.py`, `previews.py`, `runner.py`, `budget.py` | `pytest -q`; `tmp_path`-only test that a drifted asset's `meta.yaml` carries `style_drift` and the gallery renders the badge; **no real `logs/`/`output/`, no API key in env** |

V2a‖V2b in one message. `copywrite.py` is V2a-only; `prompts_engine.py` is V1c then V2b (**same file, two
waves — sequential, single writer per wave, never concurrent**). Tests fold into V1f.

⚠️ **The one ordering constraint that matters:** V2b's `target_chars` wiring depends on V1c's builders
existing, and V2a's audit depends on V1a's `surface.py`. Neither can be pulled earlier.

⚠️ **`prompts_engine.py` reaches ~1,183 lines under V2** — already 2.4× the §3a ~500 threshold. Extract
`_BUILT_INS` (~290 lines of string constants) into `hypesocials/prompt_builtins.py` in that wave.
Mechanical, zero-risk. `copywrite.py` at ~520 should be **accepted and flagged, not split** — the audit
orchestration shares internals with the group→split→fallback ladder, so splitting makes two shallow modules
out of one deep one (§18).

---

## 6. ⛔ Collision with the approved sibling plan

`plans/xmasterplan-virlo-throughput-and-fidelity.md` wave **A2‴** owns `copywrite.py`,
`virlo_mcp/server.py`, `sources/virlo.py`, `prompts/copywriter_system.md` and `models.py`. **That is this
plan's V1a/V1b/V1c/V1d/V1e path set.** They cannot run concurrently.

| Sibling item | Resolution |
|---|---|
| **A20** (no verbatim-hook fallback) | **Prerequisite. Keep.** Orthogonal and still required |
| **A21** (validate `hook_pattern_used`) | **Independent.** But `hook_pattern_used` is largely superseded by `surface_carried`; re-scope or drop |
| **A22** (rank hooks by views) | **Superseded** — V1b implements it properly with a real merge |
| **A23** (substance channel) | **Superseded, and its prompt paragraph is REVOKED.** A23 says *"find the equivalent claim in our niche"* — the **exact opposite** of the operator's binding "same exact topic" decision. `substance_carried_over` ships as `claim_swap` instead. **Someone must amend that plan or it will be built as written.** |
| **A24** (console inventory) | **Independent.** Runs either side |
| **A25** (echo check) | **Superseded** by V2's `surface.echoes` — same purpose, calibrated, sharing the measurement layer |

**The operator must pick one path, not layer them.**

Note the earlier A20–A25 forecast of **+140 lines** costed the echo check at 18 lines with no shared
measurement layer, no data-model carriage of the full text, no budget ladder and no audit persistence.
V1+V2 at ~+910 is the honest number for the same intent. Naming the gap is the point.

---

## 7. Verification — re-run the dry run, against the real template

§3.4d of the sibling plan recorded a hand-built-prompt dry run that produced good substance and one echo.
**That is not proof for this design.** At V1g:

1. Pull the top slideshow and top video (sorted, free) with `panel_text_full`.
2. Render the **real** `copywriter_system.md` through `PromptEngine` with the real context.
3. One real copy call per sample (~$0.005).
4. Assert, by hand: line count matches the source block · casing profile matches · contractions land in the
   source's slots · emoji present iff the source has them · **no shared opening word** · every noun ours ·
   the CTA is ours · `transposition_map` and `surface_carried` are specific and checkable.
5. Compare against the §1.3 tell table — `Most …`, negation frames, em-dash appositives and 4-item lists
   should be **absent** unless the source did them.

**If step 5 still shows the tells, V1 has not worked and V2 will not save it** — the problem would be
deeper than the prompt, and the next lever is a different copy model, not more instruction.

---

## 8. Risks, bluntly

1. **The override-mode hole (§2.1) makes this plan inert for the operator's only shipped brief** unless
   option A is taken. Highest-priority decision in the plan.
2. **Surface fidelity vs brand voice has no arbiter in code** (§3.2). Expect surprise the first time an
   ALL-CAPS source produces ALL-CAPS copy that is technically correct.
3. **`max_tokens.copy` is the failure most likely to actually bite** (§3.6). One-line config fix; if
   forgotten, the symptom looks like a model problem.
4. **The 3,500-char script ceiling is a guess on n=22** (§3.4).
5. **Cutting the literal rows from `_trend_texts` silently downgrades the ANALYSIS call**, which allowlists
   `trend_texts` and today sees panel texts. Unless `source_script` is also allowlisted for the analyst,
   the style brief **loses input it has today**. Must be an explicit decision, not a default.
6. **V2's `contraction_rate` self-disables on Czech**, so 9 features become 8 and the "2 drifts = signal"
   noise floor shifts silently.
7. **V2's `sentence_len_stdev` on a 3-line bundle is close to noise.** Kept for the record; band widened to
   near-inert. Do not count on it.
8. **`reference_sets` index alignment** (if V2's per-group scripts land): `_download_references` rebuilds
   `reference_groups` by dropping dead groups, so group *k* and set *k* desynchronise silently. Failure mode
   is a subtly incoherent creative and a green test run. Prune both in one comprehension; the paired-length
   invariant test is load-bearing.
9. **With 100% of the text in the prompt, echo rate rises.** The correct response to a high post-re-ask echo
   rate is **not** a second re-ask — it is shrinking the literal channel via the exemplar count and the
   script ceiling, which config already exposes.

---

## 9. Definition of done — V1 + V2

**Voice (the actual goal)**
- [ ] `prompts/copywriter_system.md` contains a VOICE section, a precedence rule, and a BANNED LANGUAGE
      section — `grep -iE "voice|register|casing|contraction|emoji"` returns matches
- [ ] The abstraction move is gone; `transposition_map`, `surface_carried` and `claim_swap` are required output
- [ ] The brief is fenced as specification-not-exemplar
- [ ] **The §7 dry run passes on both samples, including the absence of the §1.3 tells** — `Most …` openers,
      negation frames, em-dash appositives and 4-item lists absent unless the source did them; emoji present
      iff the source has them; **no shared opening word**

**The `voice` mode (D-1)**
- [ ] `influence: voice` exists, is validated, and `ai-audit-cta` uses it
- [ ] A `voice` brief consumes exactly one trend; `{{source_script}}` renders non-empty for it
- [ ] `override` behaviour is unchanged, and its bans are **absolute** (no source to license them)
- [ ] The extra analysis call a `voice` brief now costs is priced at the Confirm gate

**Data and plumbing**
- [ ] `panel_text_full` reaches the copy prompt with exact surface form and unambiguous `| ` line boundaries
- [ ] Panel-boundary truncation never cuts mid-panel; `source_script_truncated` logged when it fires
- [ ] Exemplars are view-ranked across a real video+slideshow merge; **FR-5 strength values byte-identical**
- [ ] `max_tokens.copy` is 6,000 and a 6-sibling group does not truncate into per-creative splits

**Verification (V2)**
- [ ] `surface.py` is pure, offline, stdlib-only, and imports nothing from the package
- [ ] Drift and echo are always measured and logged; **exactly one** re-ask, never two; echo outranks drift
- [ ] `effective_target = min(budget, round(source_mean_line_chars * 1.15))` is live — a 13-char source
      panel yields a ~15-char target, not 42
- [ ] `mean_line_chars` cannot fire on the budget's own constraint
- [ ] `COPY_STYLE_DRIFT` / `COPY_ECHO_DETECTED` reach `meta.yaml` and the gallery badge
- [ ] `>>>` in a source panel survives to the model unmangled
- [ ] `trim_words` no longer leaves a dangling function word (the 72-occurrence defect)

**Housekeeping**
- [ ] `find`-based `wc -l` reported with per-task attribution (no ceiling — CLAUDE.md rule 5, v2.0.0)
- [ ] Decided explicitly: is `source_script` allowlisted for the **analyst** too? Without it the style brief
      loses input it has today (§8.5) — this must not be settled by default
- [ ] The sibling plan is amended: A22/A23/A25 marked superseded, **A23's revoked paragraph struck**
- [ ] The per-role fence change is routed to a second approver (§18, security control)
