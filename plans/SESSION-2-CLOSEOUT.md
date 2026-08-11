# Session 2 closeout — Increment A, waves A2′ → A3

**Written 2026-08-11 by the conductor at the end of Session 2.** Read this before starting Session 3.
It records what changed, what is now load-bearing, and the four findings that were deliberately not fixed.

Session 2 = `plans/xmasterplan-virlo-throughput-and-fidelity.md`, waves **A2′, A2″, A2‴, A3**.
Everything ran **offline** against `tests/fixtures/virlo/`. **No live API call, no spend.**

---

## 1. 🔒 The gate: A20 is GREEN — Session 3 is unblocked

`plans/EXECUTION-ORDER.md` makes A20 the prerequisite for the copy-voice plan, because that plan puts
100% of the source text into the prompt and doing so while the engine still rendered scraped hooks
verbatim would raise real reproduction risk.

**Verified at the assembled render prompt, not merely on the `CopySet`** — that is where the risk lives,
because the prompt is the string that reaches the image model. Method: distinctive sentinels placed in all
three literal-competitor fields (`hook_texts`, `text_overlay_contents`, `panel_texts`), copy forced to fail
at every tier, then `image_direct.md`, `image_single_post.md`, `carousel_slide.md` and `reel_seed_frame.md`
rendered across single image, carousel ×3 and reel seed frame.

```
onimage_text slot = ''          <- "the ONLY source of renderable words"
SENTINELS in CopySet / all four render roles : none
A20 GATE: PASSED
```

Before: `_fallback_copy` set `headline` to the competitor's exact `hook_text` and `slide_texts` to the
source deck's panels — reproducing a winning deck **panel for panel** on a carousel, and burning the hook
into a reel's seed frame as a fixed graphic layer.
After: a caption in our own words, **no on-image text**, tagged `copy_degraded` + `no_onimage_text`.

⚠️ **This invariant is now permanent and must stay that way.** `tests/test_copy_no_verbatim.py` asserts it
at prompt level *and* structurally (that `trend_texts` / `source_hooks` / `inspiration_exemplars` resolve on
**no** render role). Any future change that re-opens a path from those three `TrendItem` fields to an
on-image string is a regression, not a feature.

---

## 2. Baselines for the next session's attribution

| | End of Session 1 | **End of Session 2** |
|---|---:|---:|
| `find hypesocials -name "*.py" \| xargs wc -l \| tail -1` | 14,930 | **16,265** (+1,335) |
| `find tests -name "*.py" \| xargs wc -l \| tail -1` | 8,905 | **10,724** (+1,819) |
| `pytest -q` | 425 passed | **522 passed** (+97) |

**Never use `wc -l hypesocials/**/*.py`** — globstar is off in this shell and it silently counts 20 of 39
files. Always the `find` form above (CLAUDE.md rule 5).
**Always `.venv/Scripts/python.exe`** — bare `python` has no `mcp` and fakes a broken test tree.

### Forecast accuracy — recalibrate Increment B before trusting its numbers
| Wave | Forecast | Actual | Ratio |
|---|---:|---:|---:|
| A19 (funnel) | +87…+107 | **+634** | ~6× |
| A20+A21+A24 | ~+62 | **+490** | ~8× |

Per the plan's own §2.4 this signals **the design grew, not the typing** — and it did: "reconcile at every
stage" forced a 42-field `Counters`; A24 costed at 35 lines was a header + five labelled rows + a URL
carve-out + a volume guard + a second block + a persistence field + a gallery line, printed from three call
sites. Nothing was shortened to absorb growth. Increment B's estimates were written by the same method.

---

## 3. What Session 3 will collide with — read before Wave V1c/V1d

Session 3 rebuilds `prompts/copywriter_system.md` and edits `prompts_engine.py` and `copywrite.py`.
Session 2 put **three new contracts** into exactly those files. They are enforced by tests, so breaking one
fails the suite rather than shipping quietly — but you need to know they exist.

### (a) `prompts/copywriter_system.md` is now READ BY TESTS
`tests/test_copy_no_verbatim.py` parses the template and asserts the code and the prose agree:
- the stated **`30 characters`** and **`four distinct content words`** must equal the A21 code constants;
- the phrases quoted after *"rejected outright:"* must equal `_GENERIC_HOOK_PATTERNS` **in both directions**
  (`curiosity hook`, `engaging hook`, `attention grabber`, bare `hook`, bare `pattern interrupt`);
- the template's own *"a passing value reads like this"* example must PASS the validator.

**A V1d rebuild that drops or reworks the `hook_pattern_used` bar will fail these tests.** Carry the bar
forward, or change the code constants in the same wave and say so.

### (b) `{{inspiration_exemplars}}` exists and is load-bearing
New copy-side slot (A16) carrying `.txt` files that sit beside inspiration images — proven human-written
viral copy. Allowlisted for **`copywriter_system.md` and nothing else**; that allowlist entry *is* the
enforcement that it never leaks into a render prompt. It sits at **position 3 of `_TRUNCATION_ORDER`**,
ahead of `trend_texts` and `source_hooks`, and `prompts/README.md` documents that order — the two must move
together. Session 3's V1c edits `_TRUNCATION_ORDER`; do not drop or reorder this entry silently.

### (c) The built-in fallbacks in `prompts_engine.py` now have a parity test
`_BUILT_INS` holds a second copy of every template for the FR-183 "file missing or unreadable" path.
**It drifted twice in Session 2 alone** — once carrying a new slot without its guardrail sentence, once
missing a new slot and a new instruction entirely. `tests/test_template_parity.py` now asserts the
**placeholder sets match** between each on-disk template and its built-in, and that every placeholder is in
that role's allowlist and in `models.PLACEHOLDERS`. Session 3's V1d already says "built-in fallback kept in
sync" — this test is what makes that automatic instead of aspirational.

### (d) Files past the splitting threshold, both blocked on path-set collisions
- `hypesocials/sources/virlo.py` — **1,186 lines**. Designed cut: the `media.py` cache seam, plan §4.6,
  including the `_CACHE_DIR` globals-alias trap (a facade doing `from .refs import _CACHE_DIR` holds a stale
  alias and `cleanup()` silently fails to remove the temp dir — FR-249 violated every run, no error).
- `hypesocials/copywrite.py` — **596 lines**. Natural cut: `_fallback_copy` + `_fallback_caption` +
  `_hashtags` + the A21 validator → a `copywrite/degrade.py`. **Collides with Session 3's path set.**

Neither is started. Both are owed on §3a/§18 design grounds, not arithmetic (there is no line ceiling).

---

## 4. ⛔ Still superseded — do not implement

**A22, A23 and A25 remain superseded** by `plans/xmasterplan-copy-voice-transposition.md`. A23's prompt
paragraph (*"find the equivalent claim in our niche"*) is **REVOKED** — the operator's binding decision is
**same exact topic, our words**. Session 2's agents each carried this stop-notice and none drifted.

Consequence for A24: four rows of the plan's console mock could not be filled — author handle,
`3 of 8 panels`, per-post view lists, and `primary_topic · content_format`. Three of those fields do not
exist on `TrendItem`; **the fourth is an A23 field.** Real equivalents were substituted rather than fields
invented, so the shipped console does not look exactly like the plan's mock.

---

## 5. Four findings recorded, deliberately NOT fixed

Found by the A3 test wave (which mutation-tested its own assertions to prove they bite).

1. **Funnel rows built as a single f-string clause truncate rather than wrap at Increment-B scale.**
   `runner.py` `verdict` row and the `chosen` row's motion clause are one clause each, so the packer has no
   boundary and `util.fit` truncates: `… 33333 unusable, 4321…` — the `without images` count is gone behind
   an ellipsis. **Not reachable today; it lands with Increment B.** Fix = split those f-strings into
   separate `_funnel_row` clauses. `test_at_todays_scale_nothing_is_lost_to_the_ellipsis` forbids `…` on the
   healthy/degraded/zero shapes and **deliberately exempts** the B shape rather than blessing it.
2. **A brief-only run prints the zero-material funnel sentence** for a run where Virlo was never contacted.
   Cosmetic — the header already reads `0 monitor(s) asked`. **The conductor attempted this fix and reverted
   it:** a `monitors_asked == 0` guard cannot tell an untouched `Counters` from a populated one whose caller
   never set that field, so it silently blanks legitimate blocks. **The clean fix is at the call site**
   (`_collect(fetch_trends=False)` should skip the block or pass a flag). Comment recorded in place.
3. **A24's `motion` row is narrower than the design.** `TrendItem` carries neither the motion post's
   freshness tier nor its view count, so the row is host-only. The shipped docstring justifies this on width
   grounds, which is misleading — it is a **data availability** limit, not a width decision.
4. **A21's re-ask re-issues the identical prompt.** If `models.temperature.copy` is ever pinned to 0 the
   re-ask is deterministic and can only return the same rejected answer — not FR-127's "never an identical
   retry" in spirit. Fixing it needs a slot naming the rejected value.

Also unfixed, by design: real Virlo hooks carry emoji (**59 of 266** measured strings contain glyphs outside
`util.fit`'s proven-safe set) and A24 prints them verbatim. **Not a crash** — FR-256 covers it twice
(`run.bat` sets `chcp 65001` + `PYTHONUTF8`; `__main__.py` reconfigures stdout with `errors="replace"`).
Left unasserted deliberately: an ASCII-only rule on that row would fail against real data.

---

## 6. Operator decisions taken during Session 2

- **Notion is the intended source of every HypeDigitaly brand/business fact**, via MCP. The path is complete
  but **has never executed one MCP call** (no `NOTION_TOKEN`, `notion_influence: off` everywhere, all four
  `notion_pages` lists empty, zero `notion_*` events across 39 run folders; `preflight.py` force-downgrades
  to `off` when the token is absent). **A11 therefore ships config keys as a FALLBACK BENEATH Notion**
  (`session.brand.accent or config.niche.brand.accent`) — never a replacement. Both keys ship **empty**;
  no brand values were invented. Energising Notion is a **spike, not a config flip**: `_fetch_tool` name
  resolution, `_flatten` payload shape and `_brand_marks` regex extraction would all run for the first time.
- **`Inspiration/Linkedin/Viral posts` added** to `inspiration_folders` in both HypeDigitaly configs, so
  A16's 16 paired `.txt` exemplars reach the copy call. Noted inline that this also widens the **image** pool
  the mix draws from (a fidelity change, not only a copy one), and that the `-cs` config ships Czech captions
  while those exemplars are English — the template makes the sibling's language win absolutely.

---

## 7. Verification commands used at every barrier

```bash
.venv/Scripts/python.exe -m pytest -q
find hypesocials -name "*.py" | xargs wc -l | tail -1      # never the globstar form
find tests       -name "*.py" | xargs wc -l | tail -1
```

Live verification (plan §3.4, waves A4) is **still outstanding** and needs the Virlo trial, which expires
**~2026-08-13**. Session 2 was entirely offline by design; the fixture corpus in `tests/fixtures/virlo/`
exists precisely so a lapsed trial does not block development.
