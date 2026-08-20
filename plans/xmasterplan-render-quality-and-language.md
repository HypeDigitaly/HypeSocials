# Render quality, design system, and language — one plan (v3, verified + session-split)

**Status:** FINAL for execution. Supersedes BOTH earlier copies:
`plans/xmasterplan-render-quality-and-language.md` (repo, stale — Waves 0–6 only) and
`~/.claude/plans/jaunty-puzzling-prism.md` (Waves 0–9, unverified line refs).
**Baseline:** branch `session-i-style-intelligence`, suite **1568 collected**, production **34,745** lines,
tests **32,260**. D58 work + this plan are **committed on `main`** (2026-08-20); every session branches from `main`.
**Execution:** five fresh sessions **J → K → L → M → N** (§7), each self-contained, each ending green
and committed, each writing `plans/SESSION-<X>-CLOSEOUT.md`. Paste-ready prompts in §11.

> Every file:line below was re-verified on 2026-08-20 against shipped bytes by three read-only audits
> (~45 corrections to the earlier plan versions are folded in; the list is §5 so nobody re-derives them).

---

## 0. Context — why this exists

Paid run **`20260820_145809_4a0q`** (`hypedigitaly-fresh`, 9 carousels, $7.50, 6 delivered / 3 gauntlet-blocked,
35 min) was rejected by the operator on sight. Evidence lives in `output/20260820_145809_4a0q/`
(nine `meta.yaml`, one `GAUNTLET_REPORT.yaml` with 9 re-renders, slides at **1254×1254**).

| # | Defect | Verified root cause |
|---|---|---|
| 1 | Page-number chip missing, then **invented** (`9 STEPS • NON-TECHNICAL • NO CODING`) — cost a whole deck (9 re-renders, blocked) | Style DNA describes the chip **unconditionally** (`styles.yaml` e.g. `:1049`, `:1054`) while `carousel_slide.md:8` says STYLE_DNA is "identical on every slide — reproduce it exactly". Critic then made frame 1's invented chip law (`critic_system.md:20-23`, `:86` "Frame 1 is exempt"); `gauntlet_fix.md:83` told body frames to copy it. `counter_value` is a contract code (`gauntlet.py:165-166`) and blocks at every confidence |
| 2 | Blank black/grey placeholder bars | `carousel_slide.md:159-162` **licenses it**: "renders empty **or as a non-text graphic element (a rule, a bar, a shape, negative space)**". Same wording `image_post.md:96-101`. Compounded by **7** styles reserving "bottom 12% (4:5 crop)" on a frame that renders **1:1** (`plan.py:83`) |
| 3 | Duplicated row text ("tools to use / tools to use") | `icon-ledger-carousel` `list_mode.layout:1074-1075` mandates title + description per row, says nothing about a one-part line. Only style with a two-part row rule |
| 4 | 6 of 9 decks got `icon-ledger-carousel` (7 incl. retries) | **Supply.** It is the only *enabled, brand-neutral* style whose `match_profile` leads with "numbered listicle decks". Matcher answered 9/9, 0 degraded; the D56 gap report was blind (`style_wanted=''` on all 9) |
| 5 | Teal washed out / "a different green on every deck" | **Hue accuracy, not blotching.** Measured over 7 decks (left-margin samples): near-black ground drifts **1** (worst 6), cream **6** (worst 13), mid-teal `#00A59A` footer strip **30 (worst 69)**; sd < 1 on 6 of 7. `icon-ledger` licenses teal at "under 1/5" (`:1041`) plus a full-width strip "welded to the bottom edge" (`:1027-1028`, `:1054`). One deck genuinely blotchy (sd 40) → 1K |
| 6 | A **German** deck shipped under an English config (`Ig_car_claude-ai-for-productivity-and-business_08`, `@jan.builds`) | Language is screened per TOPIC by majority vote (`topic_filter_system.md:113-114`); `plan.fresh_source_post` (`plan.py:713-721`) has three eligibility tests and **no language test**. Virlo's per-post `intelligence.language_detected` (84/100 fixture rows) is **dropped** by `virlo_mcp/server.py:271-344` |

Then the operator supplied **three carousel-design transcripts** and **seven reference carousels**
(`Inspiration/Tiktok and IG/Carousel 1…7`, 15 images). Both sources agree with the measurement: strong
colour lives in type/pills/small marks; grounds sit at a value extreme; no working deck uses a large flat
mid-tone field.

---

## 1. Operator decisions — ALL LOCKED, do not re-ask

| Decision | Choice |
|---|---|
| Language | **Translate only non-target posts.** Target-language posts keep byte-exact source words |
| Foreign topics | **Let them in** once translation exists |
| New styles | **The seven carousel-derived styles** (§4). Split screen **dropped** (operator 2026-08-20: big-number-editorial covers it). Registry **19 → 26**, `styles.enabled` **12 → 17** |
| Image size | **2K**, pinned in the three brand configs; engine default stays `1k` |
| Colour | **Fix the style designs, not the pixels.** Pillow correction rejected |
| Slide text | `carousel_copy_mode: auto` — compress **only** the panels that overflow |
| Cover | **Best-of-3** — 3 candidates, one vision call picks, winner is the anchor |
| CTA slide | **Not now** |
| Matcher | Keep `style_match_system.md:106-109` (no-variety rule) exactly |
| Wizard | Step 3 = `verbatim / auto / compress`. **Language mode is config + CLI only**, shown on the confirm screen. Six steps stay six (NFR-16) |
| Paid runs | **One 3-carousel checkpoint after Session L** (~$4-5) + **one 9-carousel run after Session N** (`--budget 15`) |

---

## 2. What the transcripts teach vs what we have (do not rebuild ✅ rows)

| Principle | Status | Evidence → Wave |
|---|---|---|
| Visual anchor (slide 1 references every slide) | ✅ | `carousel.py:408`, `:672-674`, `:1132-1133` |
| Copy before pixels; template library; cover ≠ body; review the whole deck | ✅ | COPY→RENDER; 19 styles; `carousel.py:1293`; FR-309 gallery |
| Cover gets most effort / best-of-N | ⚠️ one candidate ever (`carousel.py:656`), looser critic on frame 1 | → **Wave 6 (M)** |
| 3 colours, fixed roles | ❌ 5–7 hexes/style, 6 styles with two saturated hues, **no validation at all** (`styles.py` `validate()` `:511+` never reads `palette`) | → **Wave 4 (K)** |
| 2 fonts, fixed roles | ❌ up to 4 families; two self-contradictions | → **Wave 5 (K)** |
| Layout decided once | ⚠️ `layout_zones` never reaches `carousel_slide.md` (`prompts_engine.py:1229`) | → **Wave 1 (J)** narrow slot + **Wave 5 (K)** spine |
| Page number every slide | ⚠️ only when the source numbered its slides | → **Wave 1 (J)** |
| Body slides 1–2 lines | ❌ 500–1,180 chars shipped | → **Wave 7 (M)** |
| Grid test (one brand) | ⚠️ teal spine = seven greens | → **Wave 5 (K)** |
| Handle / lettered swipe cue / CTA | ⛔ banned or deferred, correctly | — |
| Photo backgrounds count toward the 3 colours | new authoring note | → Wave 4a rule 6 |

---

## 3. The seven new styles — re-read of all 15 images (corrections to the earlier table in **bold**)

General: every new style must be born compliant with Waves 4/5 (one accent ≤ 1/8 with stated coverage,
ground at a value extreme, two type families with roles, counter **top-right**, 1:1 safe area, no `4:5`
prose), `format_affinity` incl. `carousel`, no `carousel_role: slides_only`, `brand_slot: false`,
`brand_affinity: []`, `list_mode` complete, `match_profile` ≥ 8 words about SOURCE fit, `render_prompt`
≤ 120 words with no `" or "`/`"variant "`/`"either "`, owned ≤ 4,700 chars (`style_dna` ≤ 2,000,
counter zone `text_treatment` ≤ 200). **No `-teal` twins.**

| Key | From | Ground | Accent (hex; coverage) | Type (2 families) | Devices | Guards specific to this style |
|---|---|---|---|---|---|---|
| `paper-editorial-carousel` | C1 (5 slides) | **Cover: full-bleed warm photo. Body: cream paper stock that changes per slide** (crumpled, linen, punched, graph) | vermilion `#E8481F` **kept native**; type + hand-drawn arrows only; ≤ 1/10 | **Condensed heavy grotesque CAPS (cover words only) + ONE Didone serif doing roman display AND italic body — TWO families, not three; no FR-348 exception needed** | Headline in serif roman, body in serif italic; **a strip of three small WORDLESS photographic vignettes** joined by hand-drawn vermilion arrows (arrows above on some slides, below on others) | Vignettes are never screenshots and carry no lettering; the engagement pill, `@handle`, "save for later" and the bookmark glyph are **not copied** — footer = wordless rule + arrow only |
| `photo-poster-statement` | C2 (1 slide) | Full-bleed desaturated, motion-blurred street photo, dark | ONE hue as **type only**: house teal `#0FCFC4` (native was yellow `#F5C518` — operator may flip later) | ONE heavy geometric grotesque, ALL CAPS, tight leading; body = same family, light | Headline fills ~55–60% of frame; **tiny lowercase kicker top-centre = the branding wordmark slot, else nothing** | The opposite of `photoreal-ambient-caption`/`quiet-luxury` (which forbid big type on a cover) — say so in `match_profile` handoffs |
| `neon-glass-dark` | C3 (6 panels) | Near-black `#0A0E0F` **into a deep teal-black gradient** (native: purple) | `#0FCFC4` glow / rim light / one headline phrase; ≤ 1/8 | Bold geometric sans + light sans | One glossy 3D hero object per slide from the `visual_brief`; four-point sparkle glyphs (wordless); persistent header = **mark left only, nothing right** | Native header URL and footer contact pill (name + phone + email) are invented text — **never**. Distinct from `circuit-atlas-dark` (diagram-led) and `terminal-mockup-deck` (UI-led): object-led |
| `big-number-editorial` | C4 (6 panels) + C6 cover numeral | **Alternates by slide parity:** near-white `#FAFAF7` ↔ near-black `#0B0D11` with a deep-teal glow gradient at ONE edge — **never a flat saturated field** (C4's blue slides are gradients into near-black) | deep teal `#0A7F78` for numeral blocks / underline / one keyword; `#0FCFC4` only as type on the dark slides; ≤ 1/8 | ONE grotesque, two weights inside one headline (regular + bold) | **The panel's own leading number set huge** (40% of frame, C6-cover scale); one keyword underlined or in the accent; hairline header; `list_mode.layout` = `01 02 03` numeral blocks paired with text, **one row per quoted line** | A panel with no leading number gets no numeral (FR-340) — the headline takes its place. **Kicker pill only where a kicker is quoted (image posts); never on carousel slides.** No icons, no white cards, no concentric-circle ornament |
| `aurora-white-deck` | C5 (6 panels) | Near-white with a **soft low-saturation teal wash bleeding in from the edges only** (native violet-blue mesh) | deep teal `#0A7F78` type, small squares, counter; ≤ 1/8 | Bold grotesque headline + small grey body | Floating white rounded cards; numbered rows with small accent squares; one 3D glyph; one tilted card | **Highest "blank rectangle" risk of the seven** — FR-340 card-per-quoted-line rule is load-bearing; a slide with one quoted line draws one card, never a grid. Native slide 4 (mostly saturated ground) is **not** copied. Counter top-right (native top-left) |
| `contrast-verdict-deck` | C6 (5 slides) | **Alternates** near-black `#0A0A0A` ↔ near-white `#F7F7F7`, edge to edge | `#0FCFC4` as type/pills on dark slides, `#0A7F78` card fills on white slides; only the "after" column is filled; ≤ 1/8 | ONE heavy grotesque, two weights | **Two-column before/after** (grey label + dark cards vs accent label + accent cards); a photographic **mineral/lunar surface motif bleeding from the bottom edge** across the deck; counter pill **top-right** (native top-left) with the wordless circle-arrow | Native slide 5 (full violet CTA with phone mockup) is **not copied** (CTA deferred; flat field). Cover numeral at C6 scale is shared with big-number — profiles must hand off: comparisons here, steps there |
| `mono-cutout-editorial` | C7 (1 slide) | Near-white `#F5F5F5` with a faint grey grid | **NONE — pure monochrome** (validator must allow zero accents) | Bold grotesque + Didone serif, **one sentence split across both faces** (grotesque opens, serif closes) | Photographic cutout person centred; thin open-bracket frame lines behind the head | Native top row of three small-caps labels and the `@handle` pill are unquoted text → **three short hairlines** instead; logo bottom-right only via `brand_slot` |

**Match-profile handoffs (must be mutually exclusive or the pool starves again):**

| Archetype | Goes to |
|---|---|
| Many rows on ONE frame — tool/resource round-ups, panels already item + one-line explanation | `icon-ledger-carousel` (**narrow** `:1006-1010`; explicitly hands off one-step-per-panel sources) |
| One numbered step / countdown item per panel, non-technical voice | `big-number-editorial` |
| Numbered process in a technical/code voice ("how I built") | `build-log-mono` (already says "numbered process decks in a technical voice") |
| Before/after, boring-vs-good, X-vs-Y comparison per panel | `contrast-verdict-deck` (narrow `circuit-atlas-dark`'s "card pair" to benchmarks/infographics) |
| One bold statement per panel over photography | `photo-poster-statement` (cover-led) vs `photoreal-ambient-caption` (caption-led, small type) |
| Personal-brand / agency manifesto, people-centred | `mono-cutout-editorial` |
| Product/SaaS feature tour, object-led | `neon-glass-dark` vs `platform-showcase-card` (UI-led) |
| Editorial explainer with imagery per slide | `paper-editorial-carousel` |
| Corporate explainer with short rows | `aurora-white-deck` |

---

## 4. Reserved numbers (no collisions across sessions)

| Session | Decision record | FRs | Where |
|---|---|---|---|
| J | **D59** | FR-338 `{{counter_rule}}` slot · FR-339 gated-zone DNA rule · FR-340 empty-zone rule · amend FR-313 (metadata clause implemented) | 50-promptcraft, 30-config, 10-pipeline |
| K | **D60** | FR-342 `platforms.<name>.image_resolution` · FR-347 palette contract · FR-348 type contract · FR-349 variant scan over all DNA fields · FR-350 house spine | 30-config, 20-integrations NFR-13 |
| L | **D61** | FR-341 registry 19→26 / enabled 12→17 · **FR-355 concentration line** | 30-config, 40-outputs |
| M | **D62** | FR-351 cover candidates · FR-352 `cover_pick_system.md` · FR-353 `carousel_copy_mode: auto` · FR-354 per-row compress provenance; amend FR-331/333 | 10-pipeline, 50-promptcraft, 30-config, 40-outputs |
| N | **D63** | FR-343 translate pipeline · FR-344 translate playbook · FR-345 `copy_language_mode` · FR-346 translate provenance; amend FR-294 (LLM screen gains a mode-gated language clause), FR-100/101, FR-293, FR-306, FR-73 | 10-pipeline, 50-promptcraft, 30-config, 20-integrations, 40-outputs |

`prds/00-overview.md:302` "Next fresh block" → **FR-356+** (Session J writes the whole reservation table
into D59 so later sessions cannot collide; each session fills in its own FR text). Amendment log header is
`:315` (first entry `:317`). `PRD.html` has **no FR cards** — add one `dcard` per decision under
`#decisions` (pattern: the D57 card ending `:456`; D58 is currently folded into the D54 card at `:445`).

---

## 5. Verified corrections to the earlier plan versions (executors navigate by THESE)

| Earlier claim | Reality |
|---|---|
| New placeholder `{{counter_slot}}` | **Name collision.** `counter_slot` is the zone ROLE name (`styles.yaml` ×8: `:243,:335,:933,:1025,:1118,:1211,:1303,:1402`; `prompts_engine.py:220,:703,:706,:799,:1218,:1240,:1247`; `models.py:976`). The placeholder is **`{{counter_rule}}`** |
| `hypesocials/generate/gauntlet.py` | **`hypesocials/gauntlet.py`** (1334 lines). `CONTRACT_CODES` `:165-166` (derived; contains `counter_value`), `LEAKAGE_CODES` `:145-146`, `COSMETIC_CODES` `:156`, `_lowconf_system` `~:1010-1027` applied `:892,:895`, `_critic` `:706`, `load_images` `:711` |
| `hypesocials/outputs/previews.py` | **`hypesocials/previews.py`** (`:526-533`, `:570-578` correct) |
| `sources/virlo.py _post()` | **`_source_post()`** def `:1099`; `SourcePost(` at `:1140-1155` |
| `CopyProvenance :529-543` | `@dataclass :489`, class `:490`, fields **`:540-543`** |
| `_refused :3148-3150` | def **`:3127`** |
| `_mapped_deck :2404-2530` | ends **`:2538`**; sanity verdict `:2473`, `PANEL_SANITY_CHARS` literal `:2476-2477`; rows `:2484-2513` ✓ |
| topic_filter LANG skip `:543-547` | **`:544-548`**; `SKIP_LANGUAGE` `:86`; docstring `:35` says "no translation **step**", `:515` says "no translation path" |
| preflight copy hint `:612-633` | docstring `:612-617`, predicate **`:624-626`**, arm **`:631-636`** |
| `wizard_help.md ## copy_mode ~:154` | **`:153`** |
| `prompts/README.md:163` | **`:162`** (15 placeholders; `carousel_slide.md` is the only render role without `layout_zones`) |
| `profiles.py:157` "one candidate" | wrong — `:157` is a docstring; `result_urls[0]` is **`carousel.py:656`**, `_result_urls` `render/kie.py:422`. No `n`/`numImages` anywhere in `render/` |
| `_image_price ~266-269` | def `:261`, `getattr` **`:269`** |
| `_build_platforms :1133-1141` | function `:1117-1143`; `:1133-1141` is the default-fill block (insertion point) |
| `_SLIDE required :237-239` | **`:237-238`** |
| FR-294 = "LANG skip" | FR-294 (`10-pipeline.md:149`) is the **LLM screen** (keep/strip/skip) with no language clause; the LANG skip is code-only (`topic_filter.py:86`) surfaced under FR-297a |
| FR-282 = `defaults_applied` | FR-282 (`30-config:251`) is `price_per_unit` attribution. `defaults_applied` is **FR-50** (`config.py:657`) |
| FR-192 "4K never requested" | FR-192 (`50-promptcraft.md:85`) says "at or below 2K (2560×1440)"; 4K wording is NFR-13's table `20-integrations.md:320` |
| `test_prompt_fit` docstring table `:36-73` | **`:43-62`** (19 rows) |
| `test_prompt_fit :326-335` "asserts no layout_zones" | prose at `:330`; the real assertion is **`:448-449`** (`set(cuts) <= {"render_prompt","style_dna"}`) |
| `_TRIO_CUT_CEILING` docstring `:120-127` | `#:` block `:119-126`, constant `:127`; lever comment `:453-456` ✓ |
| `test_styles` ordered list `:1363-1387` | literal **`:1382-1387`**; `ENABLED_TWELVE` `:1248-1252` ✓, refs `:1376,:1382,:1431,:1453,:1456,:1463,:1475` |
| FR-339 scrub sites `:314,:719,:904,:1183,:1274,:1376` | those are **style-start lines**. Real sentences: editorial-voxel `270,275,289`; letterpress `362,365,367,374`; platform-showcase `682,683`; hypelead `772,783`; build-log `964,968,969,980`; icon-ledger `1049,1050,1054,1055`; circuit-atlas `1140,1145,1158`; social-quote `1232,1233,1238`; terminal `1325,1330,1331`; letterpress-teal `1427,1430,1432,1439`. `:1021-1028` is icon-ledger's `layout_zones` (counter `1025-1026`, brand `1027-1028`) |
| "bottom 12% (4:5 crop)" — 6 sites | **7**: `:185, :596, :774 (hypelead "CTA pill in the bottom 12%"), :861, :1584, :1671, :1751`; only `1584/1671/1751` are enabled |
| Two-accent styles "both ACCENT" | only one row per pair is `ACCENT`; partners are `CONTRAST :265`, `COUNTERLIGHT :506`, `FOCAL :436/:1497`, untokenised `:1418-1419`. `hypelead-brand-card` has two `ACCENT*` rows (`:761-762`, one hue). `circuit-atlas:1132` and `terminal:1318` both say "under 1/6" |
| `MetaStyle.carousel_role` | not a field — a marker inside `per_format_guidance` (`models.py:434-437`, read `styles.py:462`) |
| `styles.py:191-238, 225-226, 327-335` "validation" | that is **parsing** (`_style()`, `_strings()`); `validate()` `:511+` checks only duplicate key / empty render_prompt / format & brand affinity, warnings via `_style_warnings` `:643-672`; `_VARIANT_MARKERS` (`:106`) applied to `render_prompt` only (`:667-668`) |
| `_neighbour_ref` "Kie URL, never local" | prefers the held URL, **falls back to `upload_local`** (`carousel.py:1156-1157`). Design decision stands (operator rejected pixel correction) |
| brand configs have a `platforms:` block | **No.** Only flat `run.platforms:`. The per-platform block is `configs/default.yaml:330-363`; `_merged` (`config.py:999`) deep-merges, so a 3-line block per brand config is enough |
| `branding.enabled: false` written in brand configs | absent — inherited from `default.yaml:254` |
| `image_resolution` is new | `budget.py:46,:266,:269` already read it via `getattr`; **`tests/test_budget.py:180,:268,:270,:927` build `PlatformConfig`-shaped objects with it** — read those before adding the real field |
| `CounterSpec` new field breaks `__eq__` | `tests/test_slide_intel.py:603` compares two default-built specs — a **defaulted** `rule: str = ""` keeps it green |
| `PLACEHOLDERS` "25-name vocabulary" | 40 members (`models.py:944-1072`); the comment at `:997` is stale — fix while there |
| `contracts.py:146` reads `CopySet.slide_texts` | `:146` only splits its `text` arg; slide texts enter at **`carousel.py:381`**, `frame_contract` call `:928-936` |
| `reel_seed_frame.md:42` same empty-zone wording | different text ("every such zone stays wordless") — already FR-340-shaped, leave it |
| `EXECUTION-ORDER.md` knows Session J | it ends at Session I (`:378`). This session appends J–N |
| `hypedigitaly-fresh.yaml` BOM / mojibake | **clean** (no BOM, 0 mojibake) — the D58 repair landed |

---

## 6. Session map

```
J  Contracts & render correctness   Waves 0J, 1, 2, 8      prompts + registry scrub + small code   $0
K  Colour, type, spine, 2K          Waves 0K, 4, 5         registry prose + styles.py validators   $0
L  Supply: 7 styles + alarm         Waves 0L, 3            styles.yaml + runner line + configs     $0.30 preview  →  💰 checkpoint: 3 carousels, ~$4-5
M  Cover best-of-3 + auto copy      Waves 0M, 6, 7         carousel.py, new cover_pick.py, copywrite, budget, menu, gallery
N  Language + final run + docs      Waves 0N, 9            virlo server, plan, copywrite, topic_filter, configs, menu/CLI  →  💰 9 carousels, --budget 15
```

Why this order: K's validators must exist **before** L authors seven styles (born compliant, measured one
at a time); J's counter/empty-zone rules must exist before K's spine asserts them; M's `auto` must expose
a single over-budget test that N calls **after** translation (translate first, then measure English length).
If a session runs short: stop at a wave barrier, write the closeout, and the next session resumes as the
same letter (precedent: Sessions 5.5–5.8).

---

## 7. Session briefs

### SESSION J — contracts & render correctness (Waves 0J, 1, 2, 8)

**Read first:** this file §0–§5, `plans/SESSION-I-CLOSEOUT.md` (esp. `:68-75`), `CLAUDE.md`.

**Step 0 — verify a clean tree.** The D58 work, the seven Inspiration carousels and this plan were committed
and pushed to `main` on 2026-08-20 (`v2.4.1/D58 + plan v3`). `git status` must be clean; branch from `main`
as `session-j-render-contracts` before any edit.

**Wave 0J — PRD (D15, before code).** `prds/00-overview.md`: D59 after D58 (`:220`) carrying the **full
reservation table of §4** (FR-338…355, D59…D63, which session owns which); bump `:302` to FR-356+; log
entry after `:317`; FR registry `:274-280`. FR-338 + FR-340 in `50-promptcraft.md`; FR-339 in
`30-configuration-and-run.md`; FR-313 (`10-pipeline.md:259`) clause becomes implemented. `PRD.html`: D59
`dcard`. `CLAUDE.md` glossary (`:225-229`) + "Last updated" (`:245`); then
`Remove-Item AGENTS.md -Force; cmd /c mklink /H AGENTS.md CLAUDE.md` and verify equal byte counts.
Optional if time: the three D15 rulings carried from Session H (`SESSION-I-CLOSEOUT.md:87`).

**Wave 1 — the counter contract (FR-338/339).**

1. `hypesocials/models.py:944-1072` — add `"counter_rule"` to `PLACEHOLDERS`; fix the stale "25-name"
   comment at `:997`; update the `slide_counter` comment `:974-979` (three channels: TEXT block line,
   critic's `layout_zones`, renderer's `counter_rule`).
2. `hypesocials/prompts_engine.py`
   - `_counter_rule(style, slide_counter)` beside `_list_treatment` (`:1252-1273`). Truth table:
     `None` style → `""` · declared zone + counted → the zone line **rendered by the same formatter
     `_style_zones` uses** (so renderer and critic read identical words) · declared + uncounted →
     `_NO_COUNTER_LINE` (`:1192-1193`, 105 chars) · **undeclared + counted → the house-default line**
     `"counter <value>: small, body family, top-right inside the safe area; no chip, no badge"` (FR-350
     spine; keeps renderer and critic in agreement, since `contracts.py:233` still lists the counter) ·
     neither → `""`.
   - Public `counter_rule(style, *, slide_counter="")` beside `style_zones` (`:832-847`); add to `__all__`
     (`:3845-3850`). Fix the parity docstring `:834-838` and `generate/contracts.py:218-222` (for carousel
     slides the renderer never saw `layout_zones`; it now sees the counter line only).
   - `build_context` — `"counter_rule": "" if override else _counter_rule(style, slide_counter)` next to
     `"list_treatment"` at `:741`.
   - `_ALLOWLIST["carousel_slide.md"]` (`:208-230`) — add the row with a `list_treatment`-shaped comment.
   - **Keep it out of `_TRUNCATION_ORDER` (`:108-127`) and `_STYLE_TRIO` (`:136`).**
3. `prompts/gpt-image-2/carousel_slide.md:96-100` → replace the five lines with:
   ```
     COUNTER RULE (ignore if empty): {{counter_rule}}
     That line rules this deck's position badge and outranks every chip, badge
     or page-number device STYLE_DNA describes: a zone line means the quoted
     counter renders there once and nowhere else; an absence line means no chip,
     badge, page number or "N of M" on ANY slide, slide 1 included.
   ```
   Mirror byte-for-byte into `_BUILT_INS["gpt-image-2/carousel_slide.md"]` (`prompts_engine.py:2894-2898`;
   entry starts `:2799`, offset +2798). Measure the char delta; the DNA scrub below pays for it.
4. `prompts/README.md:162` — add `counter_rule` to the row (the declared allowlist source, `:146-147`).
5. **FR-339 scrub in `prompts/styles.yaml`** — for each of the 8 `counter_slot` styles, **move** (not
   delete) the chip/counter spec out of `typography` / `text_placement` / `visual_pacing` into the
   `counter_slot` zone's `text_treatment` (≤ 200 chars), and the signature/lockup spec into the
   `brand_slot` zone. Sentence lines: §5 table row "FR-339 scrub sites". "FIXED: … chip form …" in
   `visual_pacing` → "counter zone (when quoted)". Chars freed per style ≈ 92–268.
6. `prompts/critic_system.md:81-86` (`style_consistency`): add *"A chip, badge or signature that no
   frame's contract row calls for is never a reason to fail the frames that omit it; frame 1 carrying
   one it was not ordered is frame 1's own defect."* Extend to `style_layout`: the critic sees
   `{{layout_zones}}` (`:35`, `contracts.py:233`) while the carousel renderer never did — it may not fail
   a carousel frame for a zone that reached no render channel.
7. `prompts/gauntlet_fix.md:70` (`counter_value | chip`) — re-word so it cannot read as "draw a chip"
   when no counter is quoted; add a `style_consistency | chip` row refusing to propagate an unmandated
   chip. **Both critic files have byte-identical twins** (`test_template_parity.py:195-218`) — mirror.
8. `prompts/styles.yaml:102` stale comment (says list treatment appends to `{{layout_zones}}`) → fix;
   add the FR-339 rule to the authoring block.

**Wave 2 — bars, phantom band, duplicated rows (FR-340).**

1. `carousel_slide.md:159-162` + twin (`prompts_engine.py:2957-2960`):
   ```
     - Every legible character in this frame comes from the TEXT block, the
       lettering inside a sanctioned TOOL MARK excepted: a text zone with no string
       quoted above is left out of the frame — never filled with invented words,
       and never with a bar, rule, block or placeholder standing in for words. A
       repeating device (a row, a card, a chip) exists once per quoted line and not
       at all when none is quoted.
   ```
   ⚠️ keep the phrase **"Every legible character in this frame"** (`test_prompt_fit.py:138` marker).
2. `image_post.md:96-101` + twin — same rule, one wording. (`reel_seed_frame.md:42-45` already says
   "stays wordless" — leave.)
3. Phantom 4:5 band — **7 sites** `styles.yaml:185, 596, 774, 861, 1584, 1671, 1751` → "all text inside
   the central 80% of a 1:1 frame" (matches `carousel_slide.md:167-168`). Net negative chars.
4. Compensating trims ≈ 170 chars off `per_format_guidance.carousel_slide` on `anime-noir-statement`
   (861), `quiet-luxury-night-photoreal` (778), `-teal` (778).
5. `icon-ledger-carousel` (`:1005-1088`): `:1081` cover "at most two ledger rows" → rows only where lines
   are quoted, none on a headline-only cover, never an empty card; `:1082` same; `:1057-1063`
   `image_treatment` positive form ("a row exists once per quoted line; a card with no quoted words is
   not drawn"); `:1074-1075` **defect 3**: "a line with no second part sets as the title alone and draws
   no description line — the title is never repeated under itself"; `:1083-1088` exclusions point to the
   positive rules.
6. `styles.yaml:117-120` authoring block: a two-part row rule must state the one-part case.

**Wave 8 — FR-313 metadata.** `sources/slide_intel.py:450-484` `CounterSpec.rule: str = ""`
(**defaulted** — keeps `test_slide_intel.py:603`); `detect_counter` `:487-554` records which rule fired
(`denominator` `:531-534`, `positional` `:538-540`, `leading_offset` `:544-549`, `constant_offset`
`:553-554`). `models.py` `AssetRecord.counter: dict | None = None` beside `panel_map` (`:637`), shaped
`{detected, rule, pattern, sample}`; `generate/carousel.py:1299+ package()` writes it from `self.counter`
(`:396`, `_counter_spec` `:1556`, `detect_counter` call `:1568`). `None` on images/reels/overrides.

**Tests J** — FIRST: `tests/test_prompt_fit.py:247-294 worst_slide()` must set `context["counter_rule"]`
or every parametrised case raises `UnresolvedPlaceholderError`. Then: `test_prompts_engine.py:309-316`
allowlist pin gains `counter_rule`; `_counter_rule` truth table (6 arms); **FR-339 registry guard** (no
`typography`/`text_placement`/`visual_pacing` sentence on any shipped style matches
`\b(chip|badge|counter|page number|signature|lockup)\b`); FR-340 guard on both templates; FR-350
pre-check: no `4:5` in any style; FR-313 `meta.yaml.counter` on counted / uncounted / image; re-measure
the tier-A table `test_prompt_fit.py:43-62` (ceiling 1,600 unchanged; expect worst ≈ 1,524).
**Acceptance:** suite green; `run.bat --config hypedigitaly-fresh --carousels 9 --preview-sources --yes`
($0) loads. Closeout `plans/SESSION-J-CLOSEOUT.md`; commit `v2.5.0/D59 SESSION J`.

---

### SESSION K — colour the model can hit, type, house spine, 2K (Waves 0K, 4, 5)

**Read first:** `plans/SESSION-J-CLOSEOUT.md`, this file §0–§5, §3 (the new styles must later pass what K builds).

**Wave 0K — PRD.** D60; FR-342, FR-347, FR-348, FR-349, FR-350 in `30-configuration-and-run.md`; NFR-13
(`20-integrations.md:269`, table `:320`) notes `platforms.<name>.image_resolution`; `PRD.html` D60 card;
CLAUDE.md glossary + hardlink rebuild.

**Wave 4a — palette re-work (prose, every carousel-affine style).**
1. No large flat field of a saturated mid-tone. Retire the teal footer strip as a device (icon-ledger
   `:1027-1028`, `:1054`) → hairline / rule / type in teal.
2. Grounds and surfaces from the extremes: near-white/cream (`#F2EDE1`, `#FAFAF7`) or near-black
   (`#0B0D11`, `#14130F`).
3. A wanted saturated block goes to the dark end (`#0A7F78`), never the mid (`#00A59A`), and stays small.
4. Brand identity moves to layout, type, composition.
5. Bound the accent's AREA in its palette line: **≤ 1/8 of frame** (`icon-ledger:1041` says 1/5).
6. **A photographic ground's dominant cast counts as the ground family** (transcript 1); the accent must
   contrast with it.

**Wave 4b — one saturated hue per style.** `editorial-voxel :264-265` (orange → ground-family tint or
drop) · `anime-noir :505-506` (amber lamp → desaturated warm highlight, S < 0.45, or no hex) ·
`meme-caricature :435-436` (keep one) · `letterpress-teal :1418-1419` (terracotta → neutral; this also
**settles the owed `SESSION-I-CLOSEOUT.md:42` ruling**: teal on cream, cover and body alike — record it) ·
`meme-teal :1496-1497` · `icon-ledger :1041` 1/5 → 1/8. Role vocabulary: Background = `GROUND/SURFACE/
DEPTH/SHADOW`; Primary = `TEXT/SUPPORT/MUTED`; Accent = one hue (values allowed), coverage stated.

**Wave 4c — the validator (FR-347/349), `hypesocials/styles.py` `validate()` `:511+`.** `palette` is
parsed as `list[str]` (`:225`) and never checked. Add, **hex-based so it is deterministic**:
- parse every `#RRGGBB` in `palette` → HSV; *saturated* = S ≥ 0.45 and 0.15 ≤ V ≤ 0.95;
- **error**: saturated hexes span more than one hue family (circular hue distance > 30°);
- **error**: a saturated hex's line has no coverage clause (`under N/M`, `under N%`, `≤ 1/N`);
- **zero saturated hexes is legal** (`mono-cutout-editorial`);
- **warning**: `_VARIANT_MARKERS` (`:106`) scanned over `render_prompt` **and** the five DNA fields,
  `list_mode.layout`, `per_format_guidance` (`:667-668` today scans `render_prompt` only) — catches
  `letterpress:362` / `:1427` "mono **or** tracked caps";
- run in warning mode first, bring all 19 into compliance, then flip the two errors on. FR-295 keeps its
  shape (a failing registry = exit 2, $0), and `tests/test_styles.py:1381` asserts `warnings == []`.

**Wave 4d — 2K (FR-342).** `config.py`: `PlatformConfig.image_resolution: str = "1k"` (`:275-293`);
default hop in `_build_platforms` `:1133-1141` so `defaults_applied` (FR-50) records it;
`Config.image_resolution(platform)` beside `Config.platform` (`:660-662`); `_validate` (`:1171`) refuses
anything but `1k`/`2k`. **One accessor, two readers:** replace `budget._image_price`'s `getattr`
(`:269`) with it — if estimate and render disagree the Confirm gate lies. Thread into
`RenderParams.resolution` at the **five** image sites `generate/carousel.py:794`,
`generate/__init__.py:483`, `:665`, `generate/reel.py:279`, `:384` (`reel.py:473` is Seedance — leave;
it is the only site that sets `resolution=` today). Pin via a new block in each brand config:
```yaml
platforms:
  linkedin:  { image_resolution: 2k }
  instagram: { image_resolution: 2k }
  tiktok:    { image_resolution: 2k }
```
(`_merged` `config.py:999` deep-merges over `default.yaml:330-363`; document the key there.) ⚠️ read
`tests/test_budget.py:180,:268,:270,:927` first — they already shape `image_resolution` ("4k"/"8k").
Cost to state in the commit: render $0.03→$0.05/slide, critic tokens 1,398→3,278/frame, ≈ +$3–6/run.

**Wave 5a — two type families (FR-348).** Rule: one display family + one body family ("if it has
personality it is wrong"); a third only as a **mono utility** for a code/terminal identity
(`build-log-mono`, `circuit-atlas-dark`, `terminal-mockup-deck`). Fix by hand: `letterpress` ×2 (four
families), `editorial-voxel` (three), `icon-ledger` (claims two, names three), `social-quote-card
:1230-1232` (bans mono then "Counter: mono caps" → counter takes the body family at small caps),
`letterpress :362/:1427` either/or. Validator = **warning** (family detection over prose is heuristic).

**Wave 5b — house spine (FR-350).** Shared by every carousel-affine style and nothing more: exactly one
accent ≤ 1/8 with coverage stated · ground at a value extreme · **counter top-right** (flip the three
top-left: `editorial-voxel :243/:275`, `letterpress :335/:365/:367`, `letterpress-teal :1402/:1430/:1432`) ·
safe area = central 80% of a 1:1 frame · two type families. **Free:** margins, type scale, ground hex,
motif, accent hue. Swipe cue stays wordless (`styles.yaml:237-240`).

**Tests K** — FR-347 over all shipped styles (hue families, coverage clause, zero-accent allowed);
FR-349 planted `" or "` in `typography` is caught; FR-348 warning fires on a planted third family;
FR-350: every counter zone says top-right, no `4:5`; FR-342 round-trip `1k`/`2k`, refuses `4k`, five
call sites pass it, `_image_price` and `RenderParams.resolution` agree; re-measure `test_prompt_fit`
table. **Acceptance:** suite green, `--preview-sources` $0 loads all three brand configs with the
`platforms:` block, Confirm-gate estimate shows the 2K price. Closeout + commit `v2.5.1/D60 SESSION K`.

---

### SESSION L — supply: seven styles + the alarm (Waves 0L, 3) → 💰 checkpoint

**Read first:** `SESSION-K-CLOSEOUT.md`, this file §3 (the style specs) and §5.

**Wave 0L — PRD.** D61; FR-341 (19→26, enabled 12→17, the seven archetypes, match-profile exclusivity
table of §3) in `30-configuration-and-run.md`; **FR-355 concentration line** in
`40-outputs-and-logging.md` (console) cross-referenced from FR-336/337; `PRD.html` D61 card; CLAUDE.md.

**Wave 3a — author the seven** (§3 table, in this order: `big-number-editorial`, `contrast-verdict-deck`,
`photo-poster-statement`, `mono-cutout-editorial`, `neon-glass-dark`, `paper-editorial-carousel`,
`aurora-white-deck`). After **each** one: `styles.validate()` clean (K's errors + zero warnings) and the
tier-A `test_prompt_fit` parametrisation (owned ≤ 4,700; ceiling 1,600). Fix a style that overshoots
before authoring the next.

**Wave 3d — narrow `icon-ledger-carousel` `match_profile` `:1006-1010`** and `circuit-atlas-dark`'s
"card pair" clause per the §3 handoff table. `styles.enabled` 12→17 in all three brand configs.

**Wave 3e — concentration alarm (FR-355).** In `runner.py` beside `_match_receipt` (`:663`, called
`:569`) / `_style_gap_block` (`:689`, called `:583`): count distinct `PlanEntry.style_key`; **warn**
when one style takes > half the creatives, or distinct < 3 on a plan of 5+. Pure arithmetic, lands in
`--preview-analysis`, ≤ 78 chars (FR-286), never a refusal. Example:
`ASSIGN  concentration: icon-ledger-carousel 6/9 (>1/2) - pool may be starved`.

**Tests L** — `SHIPPED_STYLES 19→26` (`test_prompt_fit.py:345`, `test_styles.py:1242`);
`ENABLED_TWELVE→ENABLED_SEVENTEEN` (`:1248-1252` + seven refs); ordered file-order list `:1382-1387`;
`test_config.py:619` 12→17; **unchanged** `test_style_match.py:472` (`slides_only == 4`); new: full-density
entry per style, mutual exclusivity (no two profiles claim the same archetype keyword set), FR-355 line
on a planted 6/9 plan; rewrite the `test_prompt_fit` docstring table for 26 rows.

**Barriers:** `--preview-sources` ($0); `--preview-analysis --carousels 9` (~$0.30) — matcher spreads
across ≥ 3 styles, the concentration line prints; then the **💰 checkpoint**
`run.bat --config hypedigitaly-fresh --carousels 3 --budget 5 --yes --verbose` (background, ~25 min).
Accept the checkpoint on: counter on every slide of a counted deck / none on an uncounted one, no
invented badge; zero bars, zero bottom bands, zero duplicated rows; no flat saturated field; teal drift
avg < 15 (script §9); no `style_consistency → counter_value` ping-pong in any `GAUNTLET_REPORT.yaml`;
the three covers read as one brand, three compositions. Record the numbers in the closeout.
Commit `v2.5.2/D61 SESSION L`.

---

### SESSION M — best-of-3 cover + `auto` copy mode (Waves 0M, 6, 7)

**Read first:** `SESSION-L-CLOSEOUT.md`, this file §5, `hypesocials/style_match.py` (the fail-open shape to copy).

**Wave 0M — PRD.** D62; FR-351/352 (`10-pipeline.md`, `50-promptcraft.md`), FR-353/354
(`30-configuration-and-run.md`, `40-outputs-and-logging.md`); amend FR-331/333 (`auto` joins the
vocabulary; `10-pipeline.md:263`, `30-config:239`); `PRD.html` D62; CLAUDE.md.

**Wave 6 — cover candidates (FR-351/352).** The provider has no `n` (`RenderParams` `models.py:776-787`;
GPT-Image-2 body is closed, `profiles.py:158-166`) → N candidates = N jobs.
1. `config.py` `RunConfig.cover_candidates: int = 1`, `_validate` 1–3; pin `3` in the three brand configs.
2. `generate/carousel.py:408` — fan out N `_slide(1, anchor=False, kind="projected",
   priority=RenderPriority.WAVE1)` via `asyncio.gather`, **identical prompt** (sampling supplies the
   variation). ⚠️ `_slide` commits `self.urls[1]`, `self.paths[1]`, `self.anchor_url` as side effects
   (`:672-679`) — split it into submit/commit (or a `commit=False` flag) so only the winner is committed.
   FR-317 single resubmit applies per candidate. `_reanchor` (`:467`) stays single.
3. New leaf `hypesocials/cover_pick.py` shaped on `style_match.py` (`match()` `:176`, `_MatchUnavailable`
   `:167`, bare-except fail-open `:240`, `DEGRADED_MARKER` `:107`): one `analysis` call via
   `llm.structured_call(..., images=[...])` (`llm.py:158`, `:397-401`; images loaded with
   `vision_check.load_images` `:299`). Prompt `prompts/cover_pick_system.md` + byte-identical twin in
   `_BUILT_INS`. Judges **style-contract adherence → text legibility at thumbnail size → stopping power**;
   answers by candidate id. Any failure → candidate 1 + new `DegradationTag.COVER_PICK_DEGRADED`.
4. Winner → the unchanged `_anchor_gate` (`:815-859`) → `self.anchor_url`. Losers →
   `output/<run>/<asset>/covers/cover_candidate_N.jpg` via `folder.store_bytes` (`packager.py:235`;
   `util.atomic_write:56` mkdirs) — `render_name` (`packager.py:245-254`) has no `covers` case, so call
   `store_bytes` directly; never uploaded; gallery globs `slide_*.png` only so they cannot be mistaken
   for slides.
5. `budget.py:403-405` — add `(cover_candidates-1)` renders per carousel as a `cover_candidates` line plus
   one analysis call (D11: under-statement is the one unacceptable estimator error).
6. `AssetRecord.cover_pick = {candidates, chosen, reason, degraded}` → `meta.yaml` → gallery thumbnails.
Cost at 3 candidates, 9 decks, 2K: ≈ +$0.90 renders + $0.70 vision ≈ **+$1.60**, ≈ +1 min.

**Wave 7 — `carousel_copy_mode: auto` (FR-353/354).**
1. `copywrite.py:479-480` `MODE_AUTO = "auto"`; `config.py:217` `Literal["verbatim","compress","auto"]`.
2. `_mapped_deck` (`:2404-2538`) runs **first and unchanged** (FR-304 position preservation, three drop
   reasons).
3. **Expose one function `_rows_over_budget(deck, budget) -> list[int]`** (budget =
   `offer.budgets["slide"]`, computed min(config, style) at `_slot_budgets` `:1197-1234`). New
   `_auto_deck`: send only those rows through the existing compress call (`_call_compress` `:1892`,
   `_compress_block` `:1959`), splice back by position; rows at/under budget keep bytes + `ref_label`;
   only compressed rows get `compressed: true` / `source_text_original`. **Session N calls
   `_rows_over_budget` on the translated deck — keep it pure.**
4. A deck with nothing over budget makes **no LLM call** and is byte-identical to verbatim — acceptance
   criterion. Failure → those rows fall back to verbatim bytes + `copy_degraded`.
5. String-equality sites learn the third value: `gallery.py:350,:512` (`_COMPRESS_MODE` `:111`) —
   switch the provenance card to "any row compressed" via `_compressed_from` (`:341`) rather than mode
   equality; `previews.py:526-527,:573`; `runner.py:1119-1120,:1818`; `preflight.py:624-636`;
   `cli.py:52` `_COPY_MODES`, `:164-168`; `menu.py:91` `_COPY_MODES` (three keys), `:95-96` notes,
   `:340-343` confirm line, `:572-600` `_pick_copy_mode`; `wizard_help.md:48,:153`. `_WIZARD_STEPS`
   (`:85`) and `_live_steps` (`:214-235`) **untouched**; `test_menu.py:304` asserts six.
6. `_sibling_list` (`:2183-2201`): add a branch for `auto` **without touching branches 1–3** (`:2189`,
   `:2193`, `:2198`) — `test_copywrite.py:1000,:1015,:1588,:1590,:1609` stay green untouched.
7. Engine default stays `verbatim`; pin `auto` in the three brand configs (D58 shape).

**Tests M** — `test_template_parity.py:66` `SHIPPED_COUNT 14→15` (+`cover_pick_system.md`), roster
`:124-127`; FR-351 fail-open keeps candidate 1 + tag; budget counts `3N` renders + `N` analysis calls;
FR-353 no-call byte-identity, mixed deck marks only oversized rows; menu three modes, six steps;
`test_budget.py`, `test_gallery.py`, `test_carousel.py` arms. **Acceptance:** suite green;
`--preview-analysis` Confirm estimate shows cover candidates. Closeout + commit `v2.6.0/D62 SESSION M`.

---

### SESSION N — output language + final run + docs (Waves 0N, 9)

**Read first:** `SESSION-M-CLOSEOUT.md`, this file §5; `copywrite.py` compress machinery
(`_call_compress :1892`, `_answers :1943`, `_compress_block :1959`, `_compressed_deck :2656`,
`_compressed_caption :2859`, `_positional :2914`, `_panel_verdict :2558`, `_mapped_fallback :3177`,
`_is_compressing :1889`).

**Wave 0N — PRD.** D63; FR-343 (`10-pipeline.md`), FR-344 (`50-promptcraft.md`), FR-345
(`30-configuration-and-run.md`), FR-346 (`40-outputs-and-logging.md`); amend FR-294 (`10-pipeline.md:149`,
mode-gated language clause), FR-100/101 (`:182`, a third copy boundary), FR-293 (`20-integrations.md:110-117`,
+`language_detected`, `is_multilingual`), FR-306 (`:376`, optional deck-level language), FR-73
(`40-outputs:25`). `PRD.html` D63; CLAUDE.md.

**9a — the free data channel (ship alone, suite green before anything reads it).**
`virlo_mcp/server.py` `_norm_video` (`:271-307`) and `_norm_slideshow` (`:310-344`) forward
`intelligence.language_detected` + `is_multilingual` → `sources/virlo.py _source_post()` (`:1099`, the
`SourcePost(` block `:1140-1155`) → `models.py:145-198` `SourcePost.language: str = ""`,
`.multilingual: bool = False`. `SourcePost` feeds no `json_schema_for` (`copywrite.py:2042,:2244,:2257`).

**9b — bind-time screen (fixes the German deck on its own).** `plan.fresh_source_post` (`:691-722`, tests
at `:715/:717/:719`) gains a fourth test under `copy_language_mode: source`: skip a post whose
`post.language` is non-empty and not in `_target_languages(config)`; feed the same screen into
`_carousel_supply` (`:749-774`).

**9c — the ladder:** 1) `SourcePost.language` (Virlo) → 2) one optional top-level string on
`slide_intel._SCHEMA` (`:241-245`; not on `_SLIDE`, whose `required` `:237-238` is closed) → 3) `""` →
verbatim + one `translate_language_unknown` warning. **No stopword/diacritics heuristic**
(`topic_filter.fuzzy_strip:264-302` records why).

**9d — the mode.** `run.copy_language_mode: Literal["source","target"] = "source"` beside
`carousel_copy_mode` (`config.py:217`); target = `run.languages` (`_LANGUAGES` `:53`). A **sibling key**,
never a fourth `carousel_copy_mode` value. Scope = `_panel_mapped` (`:2135-2145`); images/reels/unbound →
pre-flight **warning** (`preflight._check_language_hint` `:600-641`). CLI `--copy-language {source,target}`
(`cli.py` beside `:52,:83,:126,:164-168,:302-304`). **No wizard step** — show it on the confirm screen
(`menu.py:340-343`, ≤ 78 chars). Pin `target` in the three brand configs; `default.yaml` documents `source`.
`hypedigitaly-cs.yaml` flips symmetrically (→ Czech); rewrite its comments at `:101` and `:130`.

**9e — no-shortening guarantee, structural.** `_translate_field(...)` beside `_compress_field`
(`:2804-2856`, which takes `budget` as its 2nd positional) with **no `budget` parameter**; two gates
(blocklist strip fail-closed, FR-319 social-mark blank); only length gate `PANEL_SANITY_CHARS` (1500,
`:466`) applied as `_mapped_deck` does (`:2473-2477`). `_call_translate` passes
`carousel_copy_mode=MODE_VERBATIM` to `build_context` so `_budget_line` (`prompts_engine.py:1450-1515`)
takes its verbatim branch (`:1493-1505`) — **no `(at most N characters)` ever stated**. Length-ratio audit
< 0.5× / > 2.0× warns `translate_length_drift`, tags, ships (A20 polarity, `_verify` `:3490-3543`).

**9f — `CopyTranslated`** = `CopyCompressed` fields (`models.py:490-525`) + `source_language`. Backstop: if
the model reports the panels were already in the target language and its line ≠ source bytes, **ship the
source bytes**, warned. **Ordering with `auto`: translate first, then `_rows_over_budget` on the English
deck** — assert call order in a test.

**9g — rules.** One translate call per creative, never grouped (`max_tokens.copy` 3000, `config.py:378-379`);
fourth branch in `_sibling_list` (`:2183-2201`), branches 1–3 untouched → `test_copywrite.py:1000,:1015,
:1588,:1590,:1609` + `test_prompts_engine.py:67` green untouched = regression proof; `_verify` unchanged
(`_translated()` returns `_Written(quoted=())`, self-skip `:2642-2653`, blocklist half still runs); render
templates unchanged (`carousel_slide.md:91`, `image_post.md:23`, `reel_seed_frame.md:23`) and the gauntlet's
leakage-tier `translated` code (`gauntlet.py:145-146`, `:248-249`) becomes a free end-to-end check;
`budget._llm_lines` (`:679-760`) prose at `:693-695` rewritten, one call per translating creative,
`copy_split_allowance` (`:754-760`) widened; topic filter: mode-gate the LANG skip (`topic_filter.py:544-548`),
rewrite docstring `:30-37` and `:513-517`; partial translation (`""` for one slide) → wordless + warn
`translate_no_text`; whole-call failure → `payload is None` (`:1810-1818`) → `_mapped_fallback` + `copy_degraded`
+ new `DegradationTag.COPY_NOT_TRANSLATED`, loud on console (`runner.py:1119-1124`) and gallery; degrade-path
captions (`_offer_caption :3397`, `_refused :3127`) ship source language — tag `copy_not_translated`, state
it in FR-343 as a known bounded gap.

**9i — provenance.** `CopyProvenance` (`:489-543`) `.copy_language`, `.source_language` → `AssetRecord`
(`:604` area) → `meta.yaml` (`packager.py:15`) → gallery (`:106-111,:341-352,:500-514`), previews
(`:526-533,:570-578`), runner (`:1119-1124,:1815-1820`); `panel_map` rows gain `"translated": bool` on both
walks (`:2484-2513` writes `False`).

**Tests N** — `SHIPPED_COUNT 15→16` (+`copy_translate_system.md`); `inspect.signature(_translate_field)` has
no `budget`; 1,048-char German → 1,010-char English ships all 1,010 on a 180-budget style under
`target + verbatim`, no `text_trimmed`; rendered translate prompt has no `(at most`; translate-before-auto
order; already-target backstop; unknown language → verbatim + one warning naming the post; N translating
creatives ⇒ N calls; safety clones (`test_copywrite.py:1288,:1314,:1557,:1593` shapes); mixed topic
end-to-end (English creative byte-identical, `quoted` non-empty, `copy_language == "source"`; German one
`quoted == ()`, `"translated"`); `test_plan.py` fourth eligibility test; `test_console_inventory.py`,
`test_preflight.py:366` arms.

**Final run:** `--preview-sources` ($0) → `--preview-analysis` (~$0.30; translate routing visible) →
`run.bat --config hypedigitaly-fresh --carousels 9 --budget 15 --yes --verbose` (background, ≤ 45 min).
Accept on §9. Then the docs pass: `NAVIGATION.md`, `prompts/README.md`, `CLAUDE.md` glossary (meta-style
count 26, matched assignment, verbatim/auto/translate), `plans/EXECUTION-ORDER.md` marks J–N done,
`plans/SESSION-N-CLOSEOUT.md`, commit `v2.7.0/D63 SESSION N`, PR body file.

---

## 8. Test re-base quick index

| Test | J | K | L | M | N |
|---|---|---|---|---|---|
| `test_prompt_fit.py` `worst_slide :247-294` sets `counter_rule` | ✔ first | | | | |
| `test_prompt_fit.py:345` / `test_styles.py:1242` `SHIPPED_STYLES` | | | 19→26 | | |
| `test_prompt_fit.py:43-62` docstring table | re-measure | re-measure | rewrite 26 rows | | |
| `test_styles.py:1248-1252` + refs, `:1382-1387` | | | 12→17 | | |
| `test_config.py:619` | | | 12→17 | | |
| `test_prompts_engine.py:309-316` | +`counter_rule` | | | | |
| `test_template_parity.py:66,:124-127` | | | | 14→15 | 15→16 |
| `test_menu.py:304` (six steps) | | | | three modes | unchanged |
| `test_budget.py:180,:268,:270,:927` | | read first | | cover lines | translate lines |
| `test_slide_intel.py:603` | stays green (defaulted field) | | | | |
| `test_style_match.py:472` (`slides_only == 4`) | — | — | **unchanged** | — | — |
| `test_prompt_fit.py:448-449` (no third trio slot) | **do not touch** | | | | |

---

## 9. Verification & acceptance

1. `.venv/Scripts/python.exe -m pytest tests/ -q` green after every wave (baseline 1568). Always this
   interpreter.
2. Line growth at every barrier: `find hypesocials -name "*.py" | xargs wc -l | tail -1`, reported with
   per-task attribution (never `wc -l hypesocials/**/*.py`).
3. `--preview-sources` = $0; `--preview-analysis` ≈ $0.30; paid runs only as scheduled (§1).
4. **Checkpoint (after L)** and **final run (after N)** — accept on:
   - counter on every slide of a counted deck, none on an uncounted one; no invented badge
   - zero placeholder bars, zero empty bottom bands, zero duplicated row descriptions
   - final run: **≥ 5 distinct styles of 9, no style > 3 of 9**; concentration line agrees with reality
   - every shipped string in the config language, German/Czech sources included (final run)
   - `meta.yaml` carries `counter`, `copy_language`, `source_language`, `cover_pick`, per-row `compressed`
     / `translated`
   - no large flat saturated field; teal drift **avg < 15** (baseline 30 / worst 69) and the same teal lands
     within a few units of itself across decks
   - no `style_consistency → counter_value` ping-pong in any `GAUNTLET_REPORT.yaml`
   - grid test by eye: the covers read as one brand, N compositions (one accent each, extreme grounds,
     counter top-right, same safe area)

Colour drift script (left margin, never the centre):
```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
from PIL import Image
import statistics, pathlib, sys, yaml
root=pathlib.Path(sys.argv[1])
def patch(im,x0,y0,x1,y1):
    w,h=im.size; px=list(im.crop((int(w*x0),int(h*y0),int(w*x1),int(h*y1))).getdata())
    m=tuple(round(statistics.mean([p[i] for p in px])) for i in range(3))
    sd=round(statistics.mean([statistics.pstdev([p[i] for p in px]) for i in range(3)]),1)
    return m,sd
for d in sorted(root.iterdir()):
    m=d/'meta.yaml'
    if not m.is_file(): continue
    key=yaml.safe_load(m.read_text(encoding='utf-8')).get('style_key')
    s=sorted(d.glob('slide_*.png'))
    if not s: continue
    im=Image.open(s[-1]).convert('RGB'); g,gsd=patch(im,0.015,0.40,0.045,0.60)
    print(f'{key[:26]:26} ground #{g[0]:02X}{g[1]:02X}{g[2]:02X} sd{gsd:5.1f}  {im.size[0]}px')
" output/<RUN_ID>
```
Baseline `4a0q`: cream `#F2EDE1` drift 6.4/13 · near-black `#0B0D11` ~1/6 · mid-teal `#00A59A` **30.3/69** · 1254 px.

---

## 10. Standing rules (every session)

- PRDs in `prds/` are the source of truth; amend **before** code (D15). Code conflicting with a PRD is a bug.
- Interpreter `.venv/Scripts/python.exe`. Tests never touch real `logs/` or `output/`; no real API keys.
- Secrets (D30): never in prompts, logs, configs, error messages.
- Money (rule 7): nothing before the Confirm gate; label barrier commands that cost.
- Line growth (rule 5): measure + attribute; never shorten a docstring/comment/error to look better.
- Every console line ≤ 78 chars (FR-286). Kie prompt wall 19,800 (effective body 18,277). `_TRIO_CUT_CEILING` 1,600 stays.
- Every `prompts/*.md` has a byte-identical twin in `prompts_engine._BUILT_INS` — change both.
- `AGENTS.md` is a hardlink to `CLAUDE.md` and breaks on every editor write — rebuild and verify sizes.
- Model policy §9: never pass `model` when spawning agents.
- Close with `plans/SESSION-<X>-CLOSEOUT.md` (wave status, what shipped, deviations, growth attribution,
  PRD conflicts, what the next session must do first) and a commit.

## 11. Paste-ready prompts for the fresh sessions

**Session J**
```
/xecutor Read plans/SESSION-I-CLOSEOUT.md, then plans/xmasterplan-render-quality-and-language.md
in full (§0–§5 first, then §7 "SESSION J"). Step 0: verify git status is clean and branch from main.
Execute Session J = Waves 0J, 1, 2, 8 exactly as written, using the corrected file:line table in §5.
Suite green after every wave; $0 barriers only. Finish with plans/SESSION-J-CLOSEOUT.md and a commit.
```
**Session K**
```
/xecutor Read plans/SESSION-J-CLOSEOUT.md, then plans/xmasterplan-render-quality-and-language.md
(§0–§5, §3, then §7 "SESSION K"). Execute Session K = Waves 0K, 4, 5 (palette re-work, one-accent rule,
hex-based validator, type rule, house spine, 2K). Bring all 19 styles into compliance in warning mode
before switching the errors on. Suite green; $0 barriers. Close with SESSION-K-CLOSEOUT.md + commit.
```
**Session L**
```
/xecutor Read plans/SESSION-K-CLOSEOUT.md, then plans/xmasterplan-render-quality-and-language.md
(§3 style specs, §5, §7 "SESSION L"). Author the seven new styles one at a time (validate + prompt-fit
after each), narrow icon-ledger, add the FR-355 concentration line, enabled 12->17. Barriers:
--preview-sources ($0), --preview-analysis (~$0.30), then the 3-carousel paid checkpoint
(--budget 5) in the background; run the §9 drift script on it and record the numbers.
Close with SESSION-L-CLOSEOUT.md + commit.
```
**Session M**
```
/xecutor Read plans/SESSION-L-CLOSEOUT.md, then plans/xmasterplan-render-quality-and-language.md
(§5, §7 "SESSION M"). Execute Waves 0M, 6, 7: cover best-of-3 (new hypesocials/cover_pick.py on the
style_match.py shape, fail-open) and carousel_copy_mode auto with a pure _rows_over_budget(). Budget lines
first, then code. Suite green; --preview-analysis shows the new estimate. Close with
SESSION-M-CLOSEOUT.md + commit.
```
**Session N**
```
/xecutor Read plans/SESSION-M-CLOSEOUT.md, then plans/xmasterplan-render-quality-and-language.md
(§5, §7 "SESSION N", §9). Ship 9a alone first (suite green), then 9b–9i. Translate runs BEFORE the auto
budget test. Then --preview-sources, --preview-analysis, and the final 9-carousel run (--budget 15) in the
background; accept against §9; run the drift script. Docs pass (NAVIGATION.md, prompts/README.md,
CLAUDE.md, EXECUTION-ORDER.md), SESSION-N-CLOSEOUT.md, commit, PR body.
```

## 12. Deliberately NOT done (do not re-derive)

| Rejected | Why |
|---|---|
| `{{layout_zones}}` on `carousel_slide.md` | 13 of 19 styles hard-truncate (2,654 vs 1,600); would not have fixed the uncounted deck |
| Raising `_TRIO_CUT_CEILING` | its docstring forbids it (`test_prompt_fit.py:125-126`) |
| Loosening the matcher's no-variety rule | it is what makes the matcher auditable; 7-of-9 was a right answer to a starved pool |
| New LLM call for language detection | Virlo sends it free |
| Engine defaults `2k` / `cover_candidates 3` / `auto` / `target` | silently re-prices or re-behaves configs that never opted in (D58 shape) |
| Per-style fix for the bars | the template licenses it for all styles |
| Pillow colour correction | operator rejected; anchor chain prefers Kie URLs; NFR-25; no hex parser over prose (FR-347 now makes one possible, if ever wanted) |
| Trusting `style_palette` critic for hue drift | its prompt forbids side-by-side judgments (`critic_system.md:63-64,:67`); low-confidence verdicts demoted |
| CTA slide, reference images for style, lettered swipe cue, `@handle`/"save for later" footer, engagement pill, contact pills, header URLs | deferred or invented text |
| Split-screen style | operator 2026-08-20: big-number-editorial covers it |
| `-teal` twins for the new seven; forcing all 26 onto teal; unifying margins/type scale/ground hex | twinning created the two-accent defect; the spine is a discipline, not a hex; over-unifying recreates the monoculture |
| Perturbing the prompt between cover candidates | candidates stop being comparable |
| A language step in the wizard | NFR-16 six inputs; operator chose config + CLI |
| Per-role resolution (cover 2K, body 1K — transcript 2's cost split) | noted as a later option; operator wants 2K everywhere for colour |
| Wiring `narrative_arc` / `hook_line` | written, never read (`AssetRecord` carries neither) |

## 13. What THIS session does after approval

1. Write this file over `plans/xmasterplan-render-quality-and-language.md` (the stale repo copy).
2. Append SESSION J–N paste blocks to `plans/EXECUTION-ORDER.md` after Session I (`:378+`).
3. Commit + push to `main` (done 2026-08-20).
