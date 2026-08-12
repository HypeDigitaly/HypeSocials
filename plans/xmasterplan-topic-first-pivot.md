# Topic-First Pivot — Master Plan (v2.3 TRIPLE-CHECKED ×3 + OBSERVABILITY MANDATE, 2026-08-12)

> **Status: reviewed three times, pending operator approval.** Draft v1 was reviewed by three
> independent specialists (architect / python / prompt-engineering); v2 was re-verified
> by three more agents (v2 consistency, PRD coverage, operator-intent fidelity); v2.1 was then
> verified a THIRD time by three fresh agents (architecture-vs-code with every anchor grepped,
> PRD-amendment coverage against the live `prds\` tree, diagram-spec vs the actual mermaid).
> Round 3 found 3 blockers + 8 majors + ~20 gap/minor items — ALL folded into v2.2.
> **v2.3 (same day): operator mandate — console UX + log transparency.** Three further agents
> audited the console flow, data-provenance visibility, and console UX design. Verdict: the
> record-keeping is complete (everything reaches run.log/events.jsonl) but the LIVE console
> fails on liveness (render phase mute for 1–10 min; collect mute; warnings leak raw to
> stderr) and on paid-run identity (top-3 cap; per-POST views shown NOWHERE, so "sorted by
> views" is unverifiable; no creative←topic mapping printed). §1.10 + FR-296–300 + D45 make
> the fix binding. Full review log is §8.
>
> Supersedes: `plans/xmasterplan-copy-voice-transposition.md` (sessions 3–4, CANCELLED) and
> Increment B of `plans/xmasterplan-virlo-throughput-and-fidelity.md` (CANCELLED; its
> monitor→topics split is absorbed here as FR-293). Sessions 1–2 output is kept — no revert.
>
> Companion planning artifacts (fill-in inputs):
> - `plans/topic-first-pivot-meta-styles-v1.yaml` — 8 meta-styles (7 from Inspiration/Tiktok and IG + hypelead-brand-card from the brand kit)
> - `plans/topic-first-pivot-branding-v1.yaml` — v2, EXACT brand tokens (SVG fills + HTML CSS), two divergent brand systems
> - `plans/topic-first-pivot-contracts.md` — **written by the conductor before Wave-1 dispatch** (§1.8)
> - `plans/topic-first-pivot-console-ux-v1.md` — **v2.3: binding console mockups** for §1.10 (stage grammar, topics table, post roster, provenance block, heartbeats, verbosity table, menu re-shape)

Repo: `C:\Users\Pavli\Desktop\HypeDigitaly\GIT\HypeSocials`. Baseline: 16,356 production lines / 10,899 test lines (verified).
Governing docs: CLAUDE.md (rules 1–8, §9/§9a), CODING_GUIDELINES.md §21. PRDs amended FIRST (D15).

---

## 0. Operator decisions (grilled 2026-08-12, binding)

1. **Virlo = text-only source, everywhere.** Topics/captions/descriptions/hooks/panel_texts/hashtags/intelligence labels only. No Virlo reference-image downloads, no Virlo images attached to renders, no digest-exemplar tier, no yt-dlp motion reference for reels.
2. **A/B mode (`analyzed|direct|both`) removed entirely.** One render per creative.
3. **Visual style = local meta-style registry** (8 textual definitions derived once from Inspiration + brand kit), deterministic per-creative rotation. HYBRID: 1–2 local reference images per style ARE uploaded and attached alongside the meta-style text (conductor's call, delegated by operator).
4. **Copy = verbatim from Virlo** — captions/hooks/texts used AS-IS, in the source post's exact language (no translation). Competitor filter: strip other companies' brand names when incidental; skip posts primarily promoting a competitor product; keep general topics (tools, news, tips, trends). This REVERSES the A20 "our words" mandate (recorded as D42; legal exposure operator-accepted).
5. **Branding block, fully configurable** — colors, wordmark + placement, fonts, mode, `brand_ratio` (not all posts branded); wordmark integrated by the model via prompt, **no programmatic compositing** (crisp logo PNGs in `hypedigitaly branding/` = future option only). Notion = future override, not a dependency.
6. **Two divergent brand systems**: HypeDigitaly (parent; indigo→teal gradient, Montserrat) vs HypeLead (product; teal-only, Geist, pill grammar). Config carries a **brand selector**; never mix. Orange #F97316 is WEB-ONLY — in no brand asset.
7. **Keep:** two-wave render orchestration, permit gate, sorted fetch, token fixes, funnel report (re-shaped), gallery (re-based), Confirm cost gate, vision check, all CLAUDE.md non-negotiables.

---

## 1. Architecture

### 1.1 Concept inversion in one paragraph

Today the visual authority is Virlo pixels (per-(trend, reference-group) Sonnet vision brief → `StyleBrief` → render with Virlo CDN images attached) and the copy is transposed "our words". After the pivot the visual authority is a **local, versioned meta-style registry** (8 textual style definitions, each declaring its own 1–2 local reference images, uploaded per FR-200), rotated deterministically per creative; Virlo becomes a **text-only topic feed** (one monitor → up to 9 topic items), and the copy is the source post's **verbatim text selected by reference, resolved to bytes by the engine** (§1.7), gated by a competitor filter. A configurable **branding block with a brand selector** is injected into a deterministic fraction of render prompts, with the wordmark routed through the TEXT block (§1.4). Reels lose the yt-dlp motion reference (seed frame + Seedance only, no-reference billing). A/B mode, `pair_id`, `variant`, and the `analyze.py` vision stage disappear — **but the `analysis` LLM role survives: it is the vision check's role** (FR-27; `vision_check.py:52-55`, `budget.py:226`, `runner.py:481/491`, `config.py:183/189` all keep working; only the style-brief pricing lines in `budget.py:418-441` (+ the withdrawn pair-keying docstring paragraphs at `:393-414`) go — v2.2 re-anchor).

### 1.2 Module responsibility map (new / changed / removed)

| Module | Fate | Responsibility after pivot |
|---|---|---|
| `hypesocials\styles.py` | **NEW (~280 ln)** | Load + validate the meta-style registry; deterministic style rotation (`assign_styles`, stateless order-indexed scan per §1.3 — each pick a pure function of `entry.order` over the brand-filtered pool, format-affine); deterministic branding rotation (`assign_branding`, Bresenham over `brand_ratio`, keyed on `entry.order`); reference-image validation (ports `_usable`/`_MAGIC`/suffix/size checks ≈ 20 lines from inspiration.py) + per-style reference window rotation; run-scoped upload memo `dict[Path, str]` (24 h Kie retention → same-run only). |
| `hypesocials\topic_filter.py` | **NEW (~140 ln)** | One batched LLM screen over candidate topics → per-topic verdict `keep | strip(brands) | skip(competitor_promo)` keyed by **engine-assigned ordinal** (§1.5); deterministic blocklist layer from `branding.competitors` (fail-closed); strip-sanity guards (§1.5). |
| `hypesocials\sources\virlo.py` | **Rewritten** | Text/topic normalization only. `_monitor_item` → up to 9 `TrendItem`s via the Increment-B `_themes()` contract; **per-topic strength**: `total_views`/`median_views`/`velocity`/`engagement` recomputed from each topic's own `SourcePost` subset, min-maxed across the full topic pool (§1.6). `_digest` returns a 2-tuple (exemplar payload dropped); `fetch` unpack updated; module docstring rewritten. All media/reference-group/motion code deleted (in W3.5). Counters re-shaped. Net realism: closer to −80 than −160 (per-topic strength + SourcePost extraction add back). |
| `hypesocials\analyze.py` | **DELETED (262, in W3.5)** | — (style-brief vision call; biggest cost cut). |
| `hypesocials\generate\video_ref.py` | **DELETED (359, in W3.5)** | — (+ yt-dlp out of pyproject, CLAUDE.md stack, preflight checks). |
| `hypesocials\copywrite.py` | **Rewritten** | Verbatim copy via **reference selection** (§1.7): engine numbers offerable source strings, LLM returns refs, engine resolves bytes. `_apply_strip` with guards; verbatim verifier (polarity flip of A20) asserts at CopySet AND cooperates with the build_context-level strip (§1.5). A21 machinery, sibling-clone/pair-rep, `copy_exemplars` channel, `hook_pattern_used` removed. Sibling divergence: sibling *k* on a topic quotes `posts[trend_reuse_index % len(posts)]`. |
| `hypesocials\generate\refs.py` | **Rewritten (~128 → ~90)** | Attach = upload the chosen style's reference-window images via the run-scoped memo (FR-200 path; role line per §1.9 F19; FR-94 clause 1 kept). `_cap` re-based on `config.styles.refs_per_job` (old `sources.reference_images_per_job` dies). Style images listed FIRST, brief images after ("follow the first listed" = style wins). Under an `override` brief: style images suppressed (§1.9 M14). |
| `hypesocials\sources\inspiration.py` | **RETIRED (318, deleted in W3.5)** | ~20 lines (validation constants + `_usable`) port into styles.py. `apply_mix`/`Mix`/`exemplar_texts` (A16) die. |
| `hypesocials\sources\notion.py` | **Re-pointed (T2.4)** | `BrandContext.accent`/`.product_nouns` map into `BrandingConfig` override slots (accent → active profile's accent color hint, nouns → profile `product_nouns`); docstring `build_context(brand_accent=…)` reference rewritten. Dormant until NOTION_TOKEN exists. |
| `hypesocials\plan.py` | Simplified | `_emit` emits exactly one entry per creative; asset id drops `_<variant>_`; `assign` without text_only last-resort. `trend_reuse_index` **survives**, re-scoped: "which `SourcePost` this sibling quotes". |
| `hypesocials\prompts_engine.py` | Reworked | `build_context(style=MetaStyle, branding_block=…, competitor_strings=…)`; allowlists per §1.8; `_branding_block()` (colors/placement/`never:` lines/font letterforms — **no wordmark**, §1.4); `_onimage_text` gains the conditional wordmark entry; **brand-strip pass over `content_sentence`/`render_prompt`/`trend_texts`/`through_line`/`brief_directives`** before they enter the context (§1.5 M6); `style_dna` re-sourced from MetaStyle's five DNA fields; `_budget_line(min(style, config))`; `_TRUNCATION_ORDER`: `branding_block` inserted after `niche_visual_world`, before `content_sentence`; built-ins mirror T2.5 byte-for-byte incl. the wordmark clause. |
| `hypesocials\budget.py` | Simplified | Style-brief pricing lines out (`budget.py:418-441` + docstring `:393-414` — v2.2 re-anchor); `siblings_of()` re-based off `pair_id` (T2.4, v2.2); **`_llm_call_price(config,"analysis",…)` for the vision check stays** (`:222-226`); reel reference-seconds allowance out; +filter-call line priced pre-Collect at the worst-case bound `len(monitors) × virlo_topics_per_monitor × per-topic tokens` (follows `_stamp_provisional` worst-case-honest precedent). |
| `hypesocials\preflight.py` | Extended (+~45) | FR-295 registry validation (exit 2); branding validation (selector, hex formats, ratio bounds); variant-leak heuristic warning (`" or "`, `"Variant "`, `"either "` in render_prompt); yt-dlp check removed; the `"cs" in languages` heuristic (`preflight.py:325`) re-based — rendered language now follows the source post, not config (§1.7 F22). |
| `hypesocials\vision_check.py` | **Kept; NO edit required (v2.2 verified)** | The `analysis` role's surviving owner. `:52-55` and `:154` ALREADY describe the vision-check lane correctly (grep: zero style-brief mentions). The genuinely stale `analysis`-role prose is in **`config.py:179-182` + `:186-187`** (style-brief sizing comments) — re-based in the W2 conductor micro-pass (config.py is conductor-owned per M1), values unchanged. |
| `hypesocials\runner.py` | Rewired (conductor-owned) | Removed: `_analyze` (45), `_launch_video_refs` (24), `_brief_block` (40), `_analysis_degrade_counts` (22), `_analysis_degraded_line` (28), `_hook_patterns` (8), `_motion_clause` (9), `_record_render_forecast` (31, previews.py imports it at `:60` — replaced by a style-forecast equivalent, contracts-doc item 13; **v2.2: previews.py ALSO imports `_analyze` (`:52`, call `:172`) and `StyleBrief` (`:45`) and carries style-brief module-contract prose at `:7-8`/`:16`/`:21-22` — T3.1 removes all of it, else the W3 conductor's `_analyze` deletion is a collection-time ImportError for the whole suite**), `_funnel_attachment` (19), `_chosen_clauses` (12), the reference/motion rows of `_sources_block`, `_posts_used`'s `chosen_post_ids`/`winning_video_post_id` reads, FR-202 analyzed clause, `analysis_missing` from `llm_starved`. Added: `_screen_topics(session, trends)` (named helper, contracts-doc item 9 — previews must reuse it; note `_configure_llm` ALREADY runs before Collect, so only the previews path needs the $0 discipline, no runner move), `styles.assign_styles`/`assign_branding` wiring, funnel re-shape (most of the 90-line `_funnel_block` + Counters rebuild). Estimate ~230–260 removed. |
| `hypesocials\outputs\gallery.py` | Re-based | Pair grouping + FR-231 badge deleted; card shows topic name, style key, brand + branded flag, source URL; footer → "judge style adherence + topical accuracy". |
| `hypesocials\render\*`, permit gate, two-wave orchestration, ledger, logwriter | **Unchanged in behaviour** | (v2.2: stale-prose fixes owed in W3.5, not "one comment": `render/kie.py:414` reference-kind list, `render/profiles.py:66` yt-dlp/video_ref reference, `render/__init__.py:18` module list.) |

**Deep-module statements (§18 review owed):** post-pivot `virlo.py` ≈ 1,0xx — **split deferred**: the topic split is this plan's core change; splitting mid-pivot doubles blast radius; revisit after W5. `prompts_engine.py` ≈ 1,150 — **split deferred**: allowlist + builders are one cohesive contract; the pivot *removes* builders. `runner.py` ≈ 1,2xx — **split deferred**: conductor-owned aggregate; pipeline stages shrink in this plan. All three re-reviewed at W5 closeout.

### 1.3 Style registry design

**Location:** `prompts\styles.yaml` (shipped default), resolved **override-first through the existing FR-174 `prompts_dir` seam**; FR-184 origin+hash attribution extends to the registry. **Decision: no built-in third tier** — unlike templates, the registry is the visual authority and a built-in copy would be 8 styles of silent drift; a missing/unparseable registry is an FR-295 exit-2 refusal. Stated in README/NAVIGATION.

**`reference_images` path resolution:** against the **repo root** (the registry lists paths in two unrelated trees — `Inspiration/` and `hypedigitaly branding/` — so resolving against the registry's own folder, the briefs.py precedent, does not fit; the deviation is documented in the PRD).

**File format (v2 — extended per review):**

```yaml
version: 1
styles:
  - key: photoreal-ambient-caption
    render_prompt: >               # <=120 words, executable without seeing sources; NO unresolved
      Candid smartphone-grade ...  # variants ("either/or") — resolved at normalization (M9)
    subject_mode: scene_fixed      # scene_fixed | scene_open — drives the SUBJECT/STYLE precedence line (B2)
    layout_zones:                  # list of models.LayoutZone {position, content, text_treatment}
      - {position: "...", content: "headline", text_treatment: "..."}
      - {position: "...", content: "brand", text_treatment: "...", role: brand_slot}   # emitted ONLY when branded (M11)
    format_affinity: [image, carousel, reel]
    brand_affinity: [hypelead]     # OPTIONAL; omitted = brand-neutral; filters rotation (B3)
    brand_slot: true               # OPTIONAL; "this style IS a brand" → branding block collapses (data-driven, not key-matched)
    text_density: minimal          # minimal | moderate | high
    max_onimage_chars: {headline: 34, subline: 0, slide: 0}   # hard per-style caps; candidate pre-filter reads them (M10/B5)
    motion_profile: photographic   # photographic | graphic — reel LOOK/CAMERA paragraph selector (F24)
    palette: ["..."]               # five style-DNA fields — feed prompts_engine.style_dna (FR-189)
    typography: "..."
    text_placement: "..."
    image_treatment: "..."
    visual_pacing: "..."
    per_format_guidance: {carousel_cover: "...", carousel_slide: "..."}   # variant resolution home (M9)
    exclusions: ["..."]            # LITERAL strings quoted from the actual reference files (M8), scoped to
                                   # the attached references only — never the TEXT block (M7)
    reference_images:
      - "Inspiration/Tiktok and IG/Informative_Photorealistic_Carousel_02.webp"
```

**`_themes()` contract, restated inline** (its source plan is cancelled; the contract survives here — M4): `_themes(analysis_data) -> list[Theme]` from `get_monitor_analysis`'s theme blocks. Invariants: **never fewer items than today** (zero themes → synthesize exactly one topic from the monitor aggregate — the pre-pivot item shape); cap `sources.virlo_topics_per_monitor` (default 9); `-1` = kill switch (one item per monitor); `topic_key` = stable slug of the theme name; `history_key = "<mid>::<topic_key>"`. Key renamed from Increment B's `virlo_themes_per_monitor`.

**Normalization table (resolves the reviewer-set numeric/affinity deltas — binding for those columns; the five DNA fields, `per_format_guidance` and `brand_slot` are derived by T2.5 from the artifact's `render_style` prose per §1.9; artifact renames: `render_style`→`render_prompt`, `layout_zones` 3-key map → list of `LayoutZone`):**

| key | text_density | max_onimage_chars (headline/subline/slide) | subject_mode | motion_profile | brand_affinity | format_affinity | reference_images |
|---|---|---|---|---|---|---|---|
| photoreal-ambient-caption | minimal | 34/0/0 | scene_fixed | photographic | — | image, carousel, reel | `Informative_Photorealistic_Carousel_02.webp`, `_03.webp` (clean variants preferred, M8) |
| editorial-voxel-carousel | high | 90/60/90 | scene_open | graphic | — | image, carousel | `Informative_Carousel_01.png`, `Informative_Carousel_03.png` |
| letterpress-print-carousel | high | 110/60/110 | scene_open | graphic | — | carousel | `Informative_Carousel_05.png` (cover), `Informative_Carousel_04.png` (body) — variants resolved into `per_format_guidance` |
| meme-caricature-panels | minimal | 38/38/38 | scene_open | graphic | — | image, carousel (slides only) | `SuperFunny_Polarizing_MemeStyle_Caricature_Promotional_01.png` |
| anime-noir-statement | minimal | 46/0/0 | scene_fixed | photographic | — | image, carousel (cover only), reel | `AnimeStyle_Polarizing_Captivating_Promotional_02.png` |
| ugc-tabletop-statement | minimal | 70/0/0 | scene_fixed | photographic | — | image, carousel (slides only), reel | `UGC_Style_Polarizing_Captivating_StrongStatement.png` |
| platform-showcase-card | high | 100/60/100 | scene_open | graphic | — | image, carousel | `Informative_Single_Platform_Showcase.png` only — the NotionBased client-screenshot file is **dropped** (M8: real client website = worst reference in the set) |
| hypelead-brand-card | high | 90/60/90 | scene_open | graphic | **[hypelead]** + `brand_slot: true` | image, carousel (**reel dropped** — F17: cards/orbit/pill collage violates `reel_seed_frame.md` animation rules) | `hypedigitaly branding/HypeLead/post-square-a-1080x1080.png`, `post-square-b-1080x1080.png`, `lm-oldnew-1080x1350.png`, `feat-agent-1080x1350.png`, `lm-agents-1080x1350.png` (window rotation spreads them) |

T2.5 additionally: resolve every "either/or / Variant A/B / teal or cobalt" choice in prose to ONE concrete value (letterpress variants → `per_format_guidance`; editorial-voxel accent → teal, since burnt orange collides with both brand systems); quote the **literal** wordmark/label strings visible in each reference file into that style's `exclusions` (open the files; a described wordmark is a string nothing downstream can block — M8). **Cover/slide distinction survives the affinity collapse via mandatory `per_format_guidance` entries** for letterpress (A=cover/B=body), meme-caricature + ugc-tabletop (slide grammar only — never the anchor), anime-noir (cover grammar only); `styles.assign_styles` reads those markers when picking carousel anchors.

**Validation (pre-flight, FR-295 — exit 2 when unusable):** parses; ≥1 style usable under the active brand (error at 0, warning <3); per style: unique key, non-empty `render_prompt` (warning >120 words; variant-leak heuristic warning), `format_affinity` ⊆ {image, carousel, reel} non-empty, `brand_affinity` ⊆ {hypedigitaly, hypelead}; **every format with a requested count >0 has ≥1 affine style under the active brand** (error — this also catches "brand filter emptied the pool", B3); `reference_images` existence + magic-byte check (warning only — style degrades to text-only, tag `style_refs_missing`).

**Rotation (stateless order-indexed scan — v2.2 fix; the v2.1 text described two mutually exclusive algorithms in one sentence — a global cursor accumulates skips and IS position-dependent):** `styles.assign_styles(entries, registry, brand)` after `plan.assign()`. Pinned as executable pseudocode (goes into contracts doc §5 verbatim — T1.2 and T1.3 run in parallel and must not diverge):

```
pool = [s for s in registry if brand_ok(s)]           # stable registry order
for entry in sorted(live, key=lambda e: e.order):
    for step in range(len(pool)):
        cand = pool[(entry.order + step) % len(pool)]
        if fmt_affine(cand, entry.creative_format): break
    entry.style_key = cand.key
```

No shared cursor: each entry's pick is a pure function of its own `entry.order`, so a dropped/trimmed entry never reshuffles any other pick. (`entry.order` is assigned once at plan build — `plan.py:220-221` — and is GAPPED over live entries after `_confirm` trims and `_select` drops; the scan is defined over the order value, so gaps are harmless by construction.) Deterministic against the same topic set; W5 restates the check as "re-preview against the same cached topic set". The per-style reference **window** rotation (A17 mechanism) stays meaningful for styles with >2 images (hypelead-brand-card has 5). Stored as `PlanEntry.style_key`, persisted to meta.yaml.

### 1.4 Branding config schema — brand selector, wordmark through the TEXT block

New **top-level `branding:` section** (`BrandingConfig`); `niche.brand` (A11) absorbed and retired. Notion stays a dormant future override (existing `session.brand` precedence seam kept, pointed at the new fields; no task depends on Notion).

```yaml
branding:
  brand: hypelead                  # SELECTOR: hypedigitaly | hypelead — never mixed (also filters style rotation, B3)
  brand_ratio: 0.5                 # 0..1 — deterministic rotation, keyed on entry.order
  mode: overlay                    # background_tint | overlay | both
  placement: bottom-center         # wordmark placement hint
  competitors: []                  # deterministic blocklist (filter layer 1, fail-closed)
  profiles:                        # compiled defaults from the v2 artifact, all overridable
    hypedigitaly:
      wordmark: "HypeDigitaly"
      colors: {indigo: "#34288B", teal: "#00A59A", gradient: ["#34288B","#2B3F8E","#0C8897","#00A59A"]}
      fonts: {brand: "Montserrat", web: "Geist"}
      font_character: "Montserrat — geometric grotesque, near-circular bowls, medium x-height, uniform stroke"   # F21
      background_hint: "flat royal-indigo field, gradient arrow glyphs sweeping the right half, vast negative space"
      never_always: ["no teal pill highlights", "no dot-grid ground", "no orange #F97316 (web-only)"]
      never_style: []
      product_nouns: ["AI Audit", "HypeLead", "AI Chatbot", "AI Voicebot", "AI Agent", "AI Automatizace"]
    hypelead:
      wordmark: "HypeLead"
      colors: {teal_bright: "#0FCFC4", teal_mid: "#57E6DC", teal_deep: "#0A7F78", teal_light: "#8BF2E9", dark: "#14130F", offwhite: "#FAFAF7"}
      fonts: {primary: "Geist", mono: "Geist Mono"}
      font_character: "Geist — clean grotesque, tight tracking, even color"
      background_hint: "off-white ground with faint dot-grid and soft teal bloom, or charcoal-green dark mode with teal glow"
      never_always: ["no indigo or violet", "no orange #F97316"]
      never_style: ["no photography/stock/3D", "no serif or handwritten type", "teal is accent only, never full-bleed canvas"]
      product_nouns: ["HypeLead"]
```

**`never:` injection scope (M6 fix):** each profile's guards split in two. `never_always` = **color guards** (cross-brand hexes, orange) — injected into every branded prompt. `never_style` = **medium guards** (no photography, no serif, accent-only) — injected ONLY when the assigned style is brand-affine (`brand_affinity`/`brand_slot` matches the active brand). Six of the seven neutral styles are legitimately photographic/serif/hand-drawn; a branded photoreal post stays photoreal and gets only the accent colors + wordmark. W5's `never:`-lines check reads `never_always` on neutral styles, both lists on brand-affine ones.

Orange `#F97316` is web-only; it ships in neither profile.

**Injection — two channels (B1, the blocker fix):**

1. **The wordmark goes through the TEXT block, never the branding block.** Every render template today prohibits wordmarks and declares the TEXT block the ONLY source of renderable words ("any string … spelled out anywhere else … is a DESCRIPTION"; `image_single_post.md:24-32`, `:77-81` and siblings (v2.2 re-anchor)). So: `prompts_engine._onimage_text` gains a conditional entry — `wordmark (render verbatim): "HypeLead"` + the `_spell()` aid — emitted only when `entry.branded`. In prompts the wordmark is **one weight, one colour** (the two-weight lockup stays a description in the artifact, not a render instruction — F21). Template prohibitions are reworded to: *"no brand wordmark, logotype or signature line **other than one quoted in the TEXT block above**; when the TEXT block quotes none, this frame is unsigned."*
2. **`{{branding_block}}` carries everything else**: accent-color instructions per `mode`, `font_character`, placement hint, `background_hint` (background_tint mode), and the profile's `never:` lines as negative constraints. Allowlisted for gpt-image-2 render roles only; empty when unbranded. `_TRUNCATION_ORDER`: inserted after `niche_visual_world`, before `content_sentence` (cuttable, late — the wordmark itself is safe: `onimage_text` is never truncated). Precedence (FR-109 inversion): branding ranks *below* the meta-style's palette structure — accent substitution and a signature, never a style takeover.

**Brand-slot mechanics:** a style with `brand_slot: true` under its matching brand collapses the branding block to nothing extra (the style IS the brand; only the TEXT-block wordmark remains) — **data-driven via the registry flag, not key-matched** (an override registry with different keys must not silently lose the rule — B3). Layout zones tagged `role: brand_slot` are emitted only when `branded`; when unbranded the zone is omitted and one line is appended: *"This frame carries no signature zone: the lower margin is empty."* (M11 — a described-but-empty brand slot is the top hallucination site.)

**Carousel:** the wordmark appears on the **anchor slide only** (a deck signed once reads as designed; signed N times reads as a watermark — M12); `carousel_anchor_instruction.md` amended: the signature zone is slide 1's alone, never refilled. **Reel:** `reel_director.md` CONTINUITY names the wordmark as part of the fixed graphic layer when branded; RULES line becomes "no NEW logos/watermarks/wordmarks; a wordmark already present in @Image1 persists unchanged" (M13 — otherwise Seedance erases or garbles the seed frame's wordmark).

**Module split (arch #13, decided):** `styles.py` owns *assignment* (`assign_branding`); `prompts_engine` owns *rendering* (`_branding_block`, the `_onimage_text` wordmark entry) — the allowlist and `_spell` live there and the module's no-filesystem contract must hold. Stated here so the split is a decision, not an accident.

**Ratio rotation:** entry is branded iff `floor((order+1)·ratio) > floor(order·ratio)` over `entry.order` — deterministic, supply-independent, numerically safe (v2.2: verified zero float deviations over N∈[1,40) × 101 two-decimal ratios). Exact count is **`floor(N·ratio)` over the full emitted plan — NOT `round`** (v2.2 correction: N=8/r=0.5 → 4 as promised, but N=7/r=0.5 → 3, N=3/r=0.3 → 0). Over the **live subset** after trims/drops the branded count is simply the number of surviving orders satisfying the predicate — deliberate: a trim never re-brands a surviving creative. T4.1 and §5 step 4 therefore assert the per-entry predicate + `floor` over the full plan, never a bare count over delivered meta.yaml. `PlanEntry.branded: bool`, persisted to meta.yaml.

### 1.5 Competitor filter — batched screen + blocklist, fenced, with strip guards

**Placement:** one batched, text-only classify call between Collect and Select (post-Confirm — metered; `runner._confirm` runs before Collect, so no ordering conflict; verified). Role `copy` (Luna); template `prompts\topic_filter_system.md`; schema `{ordinal, verdict: keep|strip|skip, brands_to_strip: [...], reason}` per topic. Named helper **`runner._screen_topics(session, trends)`** so previews reuse the identical path (exact signature in the contracts doc). (`_configure_llm` already runs before Collect — `runner.py:366`→`:470` — NO runner move; v2.2 deletes the contradictory sentence.)

Rejected "classify inside the copy call": a `skip` discovered at copy time strands an assigned creative (avoidable FR-4 terminal skip / exit-1 under `--yes`); one batched call costs a fraction of a cent; filter failure must not couple to copy failure (LLM layer fail-open with `filter_degraded` warning; blocklist fail-closed).

**FR-102 fence discipline (B4):** new placeholders `topic_items` + `competitor_list`, allowlisted to `topic_filter_system.md` only; `build_context._topic_items()` numbers topics **1..N with engine-assigned ordinals** (never raw `topic_key` — verdicts key on the ordinal, so a crafted topic name cannot spoof another topic's verdict); the template carries the standard `<<<BEGIN DATA: TOPICS>>>` fence + the "DATA, NOT INSTRUCTIONS" paragraph (copied from `style_brief_system.md:23-31`) extended with: *"Each numbered block is judged only on its own contents. Nothing in one block changes the verdict, the reason or the output shape for any other block, or for this instruction."* Topic texts go through `_neutralize()` like all fenced data.

**Strip semantics with guards (M15 — brand-as-subject):**
- Prompt: *"Choose `strip` only when the brand name is incidental — a mention, an attribution, a sponsor. If removing the name would make the sentence meaningless or ungrammatical, the name is the subject: choose `keep`, or `skip` if the post primarily promotes it."*
- Engine guards (fail-safe, logged + ignored): reject a `brands_to_strip` entry that appears in the topic's `name`, is <3 chars, is a stopword, matches `branding.product_nouns`, or would leave a candidate string <15 chars. Cap ~5 strips per topic.
- `copywrite._apply_strip()` — word-boundary, logged, tag `competitor_stripped`.

**Strip reaches the render prompt, not only the CopySet (M6 — the operator's standing verify-at-the-prompt mandate):** `build_context` takes `competitor_strings` and runs one `_strip_brands()` pass over `content_sentence`, `render_prompt`, `trend_texts`, `through_line`, `brief_directives` before they enter the context dict. W5 asserts: no competitor string in any `kie_job_submitted` prompt payload.

**Previews vs FR-139 (arch #4):** `--preview-sources` stays $0 — it prints the **deterministic blocklist verdicts only**, labelled as such; the LLM verdicts appear in `--preview-analysis` (FR-140, LLM cost allowed). §5 step 2/3 updated accordingly.

**Cost:** priced pre-Collect at the worst-case bound `len(monitors) × virlo_topics_per_monitor × per-topic-tokens` (worst-case-honest precedent).

### 1.6 Topic-item model changes — exhaustive field disposition

`TrendItem` (name kept to bound blast radius) becomes a **topic item**. Exhaustive over the current fields (py #6):

- **Removed (W3.5 excision):** `reference_groups`, `winning_video_url`, `winning_video_post_id`, `text_only`, `chosen_post_ids`, `narrative_arc`, `text_density` (both re-sourced: pacing → style; density → `MetaStyle.text_density`; their two `_trend_texts` rows die in T2.6). `ReferenceSet` dataclass deleted.
- **Added:** `topic_key` (stable, from `_themes()`), `posts: list[SourcePost]` — `SourcePost(post_id, url, author, caption, hooks, text_overlays, panel_texts, description, views)`, view-ranked. (`text_overlay_contents` folds into `SourcePost.text_overlays` as verbatim-eligible text.) Verbatim copy, history, and gallery provenance all read `posts`.
- **Kept:** `history_key` (**format changes to `<mid>::<stable_key>` — migration note: existing `logs/trend_history.json` entries stop matching; first post-pivot run sees an empty window by design; old entries age out, no pruning pass** — py #16), topic-specific `name`, `strength`, `is_slideshow` (**re-derived: the topic's view-ranked posts are majority-slideshow**), `why_it_works`, `tactics`, `hook_texts`, `panel_texts`, `hashtags`, the three intelligence-label lists, engagement, `virlo_url`, `cross_monitor_context`.
- **Per-topic strength (py #7):** `total_views`/`median_views`/`velocity` and `engagement` are recomputed from each topic's own `posts` subset; `_score`'s min-max pool is the full topic set. `test_topic_split.py` asserts two topics from one monitor with different post sets get different strengths.
- **`trend_reuse_index` survives** (arch #8), re-scoped from "which reference group" to "which `SourcePost` this sibling quotes": `copywrite` selects `posts[reuse_index % len(posts)]`, and the style reference window uses it as the A17 turn. W5 asserts two creatives on one topic carry different `copy_source_post_id`.

Degenerate cases inherit Increment B's table: zero themes → synthesize exactly one topic; cap `sources.virlo_topics_per_monitor: 9`; `-1` = kill switch. Reference-group/`shared_refs` parts of B are dead.

### 1.7 Verbatim copy contract — reference selection, not retyping (B5)

Free-text "return AS-IS" cannot guarantee byte identity (models retype; diacritics/emoji drift) and `_apply_budgets` would truncate long hooks mid-sentence. So **selection is structural**:

1. **Offerable candidates.** The engine numbers every source string it is willing to render (`P1.hook.2`, `P3.panel.1`, `P2.caption`, …), pre-filtered per target: **on-image candidates** must fit the style's `max_onimage_chars` and be emoji-free, @handle-free, URL-free, hashtag-free; **caption candidates** keep emoji/hashtags (trailing hashtag runs extracted into `hashtags[]`, never offered as on-image text). "no @handle, no URL, no emoji in the frame" joins the merged template's CONSTRAINTS. (F23)
2. **The LLM returns references** (`headline_ref`, `subline_ref`, `overlay_ref`, `slide_refs: [...]`, `caption_ref`) + free text ONLY where nothing becomes pixels: `through_line`, `narrative_arc`, `motion_beat` (one named physical action for the reel's Stage 2 — F24). `CopySet` stays the resolved-bytes shape; a new `CopySelection` schema drives the call. `hook_pattern_used` is deleted (A21 dies).
3. **The engine resolves refs to bytes.** Verbatim cannot fail: no retyping, no language detection, no accent loss, no trimming (an over-budget string was never offered). `_apply_budgets` is bypassed for ref-resolved fields.
4. **Degrade:** no candidate fits the style's budget → tag `NO_ONIMAGE_TEXT` (**kept, redefined**: "no source string fits this style's on-image budget — caption-only creative"), ship caption-only — the existing degrade shape. `_fallback_copy` (copy call failed entirely) ships the top post's caption verbatim + no on-image text, tag `COPY_DEGRADED` — **which stays in `llm_starved` → exit 1** (explicit decision: a failed copy call is still a loss to surface, even though the fallback content is now legitimate).
5. **Language:** follows the selected source string. `_sibling_list`'s language tokens become `caption language: as-selected (source language, never translated)` for verbatim creatives; `config.languages` stays meaningful only for brief-override creatives and degrade paths; grouping key stays `(topic × language-config)` but the emitted language line changes (F22).
6. **Sibling divergence:** sibling *k* quotes `posts[trend_reuse_index % len(posts)]` — no cloned captions across creatives on one topic (arch #8).

Verifier (polarity flip of A20): every rendered string IS a byte-substring of the quoted `SourcePost` (modulo logged strips) and NEVER contains a blocklisted brand; deviation tags `copy_not_verbatim`, never fails the creative. Verified at the assembled render prompt in tests (sentinel technique, new predicate).

### 1.8 Pinned contracts (single highest-leverage review fix)

**Before Wave-1 dispatch the conductor writes `plans/topic-first-pivot-contracts.md`** from the actual code, and every W1/W2 dispatch prompt quotes the relevant section. It contains, exactly:

1. **Full post-pivot `build_context(...)` signature** (from the real current signature: +`style: MetaStyle`, +`branding_block: str`, +`competitor_strings: tuple[str, ...]`, +`topic_items`; −`style_brief` (`:348`), −`brand_accent` (`:355`), −`brand_product_nouns` (`:356` — v2.2: real parameter the v2.1 list omitted; nouns move to `BrandingConfig.profiles.*.product_nouns`, consumed via the branding block), −`copy_exemplars` (`:362`), −`reference_image_count` (`:361`); `content_sentence` kept and promoted. v2.2 correction: `engagement_numbers`/`output_format` are NOT parameters — they are engine-derived context keys and belong to item 2 only).
2. **Full post-pivot `PLACEHOLDERS` diff:** −`style_brief_summary`, −`inspiration_exemplars`, −`brand_accent`, −`engagement_numbers`, −`reference_image_count`, −`output_format`; +`branding_block`, +`topic_items`, +`competitor_list`, +`motion_profile`, +`motion_beat`. (py #3 — the three orphans are named.)
3. **Per-role `_ALLOWLIST` table** (role → exact frozenset), incl. `topic_filter_system.md` and the merged `image_post.md` — **the merged role's allowlist is the UNION of `image_single_post.md`'s and `image_direct.md`'s** (image_direct deliberately omits `layout_zones`/`exclusions` today; the widening is a stated decision, F16 — v2.2); `prompts/README.md` is the co-maintained spec and updates with it.
4. **Template registries — the REAL surfaces** (B2): the load-bearing registries are `prompts_engine._ALLOWLIST`, `prompts_engine._BUILT_INS`, `PROFILE_TEMPLATES` (drives `_ROLE_SETS` + profile validation), and `test_template_parity.py`'s hardcoded global trio + `SHIPPED == 9` count; `models.GLOBAL_TEMPLATES` has zero consumers (decorative — updated for hygiene only). Transition: W2 adds `image_post.md` to `PROFILE_TEMPLATES["gpt-image-2"]` + `topic_filter_system.md` to the global surfaces (old templates still on disk → **transitional SHIPPED count 11** at the W2/W3 barriers, set by T2.7); W3.5 removes the three dead templates from every surface → final count **8** (3 global + 4 gpt-image-2 + 1 seedance).
5. **`styles.py` public API** — `MetaStyle` (all §1.3 fields), `StyleRegistry`, `load_registry(dirs)`, `validate(reg, config)`, `assign_styles(entries, registry, brand)`, `assign_branding(entries, ratio)`, `style_for(reg, key)`, `pick_reference_window(style, reuse_index, refs_per_job)`, the upload-memo seam. Full signatures + return types.
6. **`topic_filter.py` public API** — `Verdict` dataclass, `screen(topics, cfg, llm) -> dict[ordinal, Verdict]`, `apply_blocklist(text, competitors) -> str`, degrade contract.
7. **`DegradationTag` exhaustive diff** — +`COPY_NOT_VERBATIM`, +`COMPETITOR_STRIPPED`, +`STYLE_REFS_MISSING`; kept-redefined `NO_ONIMAGE_TEXT`; kept `COPY_DEGRADED` (exit-1 semantics stated); deleted in W3.5: `ANALYSIS_MISSING`, `HOOK_PATTERN_GENERIC`. (py #8)
8. **`AssetRecord.ref_source` vocabulary** → `"style" | "brief"` (arch #16).
9. **`runner._screen_topics` exact signature** (arch #4).
10. **`CopySelection` schema** (§1.7).
11. **Post-pivot `generate.Env` dataclass** — field diff: −`style_briefs`, −`brand_accent`, −`brand_product_nouns`, −`video_refs`; `local_refs` kind vocabulary `{"brief","inspiration"}` → `{"style","brief"}`; +`styles`, +`branding` (B4).
12. **`style_dna(...)` new signature** (currently `style_dna(brief: StyleBrief | None)` at `prompts_engine.py:453`; imported by `generate\carousel.py:57` — T2.3 and T2.6 share it).
13. **The style-forecast helper** replacing `runner._record_render_forecast` — name + signature (previews.py imports it; conductor writes it LAST in the same wave T3.1 needs it).
14. **`copy_source_post_id` + `copy_source_refs` + the history-record shape** (`runner._posts_used` produces them, `state.py` consumes, W5 asserts the field names; `copy_source_refs` = `{slot: "P<n>.<kind>.<i>"}` resolved-ref labels — v2.3/FR-298).
15. **(v2.3) Post-pivot `Counters` field table** — per monitor `posts_in -> topics_out`, plus `videos_raw`/`slideshows_raw`/`duplicates_dropped`/`total_available` SURVIVE per monitor (no double-counting one monitor's rows across its 9 topics — the two-level `absorb()` seam discipline); `total_available` promoted into the console funnel header.
16. **(v2.3) `_Session.note()` seam + heartbeat parameters** — `note()` = run.log always/console-when-verbose; heartbeat cadence 30 s interactive / 90 s `--yes`, first suppressed 10 s (LLM) / 20 s (render); silence-breaker semantics (any printed line resets the timer). Stage-header grammar + column spec quoted from §1.10.

T1.3's tests are written against this doc (resolves py #9 without serializing the wave).

### 1.9 Prompt-layer directives (binding for T2.5/T2.6)

- **B2 — SUBJECT vs STYLE precedence.** Merged `image_post.md` carries: *"The STYLE line fixes how this frame looks. The SUBJECT line fixes what it is about. Where the style fixes a scene, the subject enters through the props, the artwork on surfaces, the annotation graphics and the words in the TEXT block — never by replacing the scene, the setting or the palette. Where the style leaves the scene open, build it around the subject."* Engine emits the matching one-line direction from `subject_mode`.
- **M7 — exclusions never touch the TEXT block.** Static line: *"The exclusions below concern the attached reference images. They never restrict the TEXT block above, whose strings are always rendered."* Every style's exclusions rewritten to reference-image scope with **literal quoted strings** (M8).
- **F16 — merge scope (v2.2 re-scope: this is a genuine rewrite, not a concatenation).** `image_single_post.md` + `image_direct.md` → one `image_post.md`. The two ~90-line files diverge in SIX regions (content_sentence slot, spelling-aid wording, differently-worded TEXT PRECEDENCE paragraphs, LAYOUT AND STYLE vs STYLE sections, niche-ranking paragraph, image_direct's extra CONSTRAINTS bullet) and their allowlists differ structurally (union decision, §1.8 item 3). The merged file is mirrored byte-for-byte into `_BUILT_INS` across three writers in one wave (T2.5 file, T2.6 built-in, conductor `PROFILE_TEMPLATES`) — `test_template_parity.py:60/:63-77` polices it. `carousel_slide.md` (STYLE_DNA byte-identity, slide badge) and `reel_seed_frame.md` (BUILT-TO-BE-ANIMATED block) stay separate updated files.
- **M9 — no unresolved variants.** All "either/or/Variant" prose resolved at normalization; `style_dna` (from the five DNA fields) is byte-identical across a deck; cover-vs-body divergence lives in `per_format_guidance` keyed by slide role.
- **F19 — reference order & roles.** Style images first, brief images after ("follow the first one listed" = style wins). Role string: `Image N — house style reference "<style_key>": layout, palette, typography and treatment only; no words, no logos.` `{{reference_roles}}` prose re-worded — "observed in these references" now means our house style.
- **F20 — built-ins parity.** `_BUILT_INS` mirror the on-disk templates byte-for-byte incl. the B1 wordmark clause; `test_template_parity.py` asserts it.
- **F24 — reel staging without @Video1.** Delete the @Video1 paragraph entirely (dead prompt weight invites hallucinated references). Add: (a) engine-computed real-second beats from the configured duration ("0.0–1.0s hold; 1.0–4.0s the action; 4.0–5.0s settle"); (b) `{{motion_beat}}` from the copy call into Stage 2; (c) `{{motion_profile}}` from the registry selects the LOOK/CAMERA paragraph — `photographic` (handheld, grain) vs `graphic` (no grain/shake; parallax on card layers, single slow scale, elements settle; text layer absolutely static). `{{exclusions}}` label re-worded ("for this house style").
- **M13 — reel wordmark continuity** and **M12 — carousel anchor-only wordmark** per §1.4.
- **F18** — `branding_block` in `_TRUNCATION_ORDER` after `niche_visual_world`, before `content_sentence`; documented in `prompts/README.md` §7.
- **M14 — override briefs.** An `influence: override` brief suppresses the style's `render_prompt` AND its reference images (`style_key: brief_override` in meta.yaml, refs_per_job effectively 0 for that creative); `blend` keeps both, brief ranks below the style on visuals (FR-145 wording).

### 1.10 Console UX & observability (operator mandate 2026-08-12 — D45, FR-296–300)

**Operator requirement, verbatim intent:** the console must show step by step how the flow
progresses; how many outputs came from Virlo; PROOF that they are sorted by views/popularity;
which posts exactly; which data we work with; where each creative came from. Logs very
detailed and transparent; console straightforward and easy to use.

**Audit verdict (3 agents, full report in §8 round 4):** record-keeping already complete —
the gap is console LIVENESS and paid-run IDENTITY. Post-level view counts appear in NO
surface at all today (the `views desc` sort is applied silently, `mcp_call` logs no
arguments), and the pivot makes post rank pick the verbatim copy — so without this section
the sort claim becomes LESS verifiable, not more.

**House rules (all verified against code, binding):** `session.say()` writes identical bytes
to console AND run.log — so NO spinners, NO `\r` redraws, NO ANSI/color (zero exist today);
FR-286's 78-col ceiling KEPT (not amended — the designs below fit); safe glyphs are exactly the `util.fit` set (middle dot, em-dash,
ellipsis, left-arrow) + `->` (the right-arrow glyph is FORBIDDEN per FR-155);
blocks are pure functions printed via one `say()`. Waves are per-creative permit
priorities, NOT run-global barriers → RENDER is ONE stage with per-job `w1`/`w2` tags; CHECK
is a rollup header (vision check runs inside each creative).

**FR-296 — stage narration.** Numbered stage headers `[n/N] STAGE  in -> out  elapsed`
(N COMPUTED from the resolved plan — brief-only runs have no COLLECT/TOPICS/FILTER/SELECT;
`vision_check: false` has no CHECK): COLLECT → TOPICS → FILTER → SELECT → ASSIGN → COPY →
RENDER → CHECK → DONE. Every header states counts in → counts out, so a drop is arithmetic.
Stages with waits print the header twice (opening `...` form on submit, closing form with
elapsed). Detail lines ONLY where a decision-with-a-cause occurred: FILTER prints every
non-`keep` (`strip <topic> -- removed "A","B"` / `skip <topic> -- PROMO: <reason>`); ASSIGN
prints one line per creative (`NN fmt topic style brand|plain` — the determinism receipt);
SELECT echoes non-eligible verdicts (`<name> [excluded: used 2026-08-10]`); CHECK prints
failures/retries only. Collect liveness: a `collecting trends from N monitor(s)...` opener,
and the four virlo `_warn` sites (monitor failed / digest failed / text-only fallback /
reference shortfall) routed through the EXISTING `say` seam (`sources/__init__.py:117` —
plumbed, used once today). One-time logging decision in `__main__.main`: configure/suppress
the root logger so `logger.warning` lines stop leaking bare onto stderr (today: unconfigured
last-resort handler = undesigned console output on a random channel).

**FR-297 — sort proof + identity surfaces.** (a) **Topics table**, printed once after
FILTER, ALL topics one line each: `rk · topic(22) · mon · posts · views · median · strn ·
verdict` (compact numbers `12.4M`; ≤78 cols), with a 2-line caption stating the strength
formula AND that views/median are the topic's OWN posts, min-maxed across the pool — the
monotonically non-increasing `strn` column IS the sort proof. Replaces previews'
`_verdict_block` (~8 lines/trend → 1); paid runs and previews share it (previews at
`limit=None`). (b) **Per-topic post roster** after SELECT, for paid topics (top 3 posts ×
top 3 topics default; `--verbose`/previews uncapped): `P1 @author 4.9M 2d <post_id>
slideshow -> 01` — the `P` ordinals are EXACTLY the §1.7 reference labels the copy LLM is
offered, and `-> NN` names the creative that quoted that post (makes §1.6 sibling divergence
observable, not grep-only); permalink alone on its own line. (c) **Provenance block** at
DONE, before the spend table: per creative `id · format · topic · style · sig(branded) ·
cost · ok` + a second "verbatim receipt" line `quoted P1 @author 4.9M <post_id> "<first
~24 chars>"` + a third line only on loss (cause). (d) Funnel (FR-155) prints ONCE, at DONE —
its stage-gate placements are superseded by the stage headers carrying the same counts when
they become true; a number appears in exactly ONE of {stage header, table, funnel, spend
row}. (e) The brief-only "Virlo returned no video" cosmetic bug dies at the call site during
this reshape. (f) Gallery path printed the moment the first card lands (FR-76 writes it
mid-run) AND in the exit block (today the path is never printed).

**FR-298 — forensic events + provenance fields.** New events.jsonl events: `topic_ranked`
(full table rows incl. raw pre-normalization components), `topic_posts` (per topic, EVERY
`SourcePost` as `{post_id, url, author, views}` in rank order — closes the "which posts
exactly" gap; data already in memory), `topic_filter_verdict` (per ordinal: topic_key,
verdict, brands_to_strip, reason — NFR-5's "filter verdicts" pinned to this shape),
`virlo_fields` (per monitor: fields_present/consumed/ignored — the consumption ledger),
`stage_complete` (per stage header). meta.yaml += **`copy_source_refs`** (`{headline:
"P1.hook.2", caption: "P1.caption"}` — post identity was already recorded via
`copy_source_post_id`; this records WHICH STRING; contracts item 10/14 pins it; gallery card
says "quotes P1.hook.2 verbatim"). `trend_history.json` post entries gain the post URL
beside the date (FR-153 is already being amended). Kie poll ticks stay events-only, never
`say()`.

**FR-299 — render/LLM progress + verbosity tiers.** Heartbeats are **silence-breakers, not
tickers**: print only when nothing has printed for `heartbeat_s` (30 s interactive / 90 s
`--yes`; first suppressed 10 s LLM / 20 s render) — bounded log volume by construction.
RENDER: per-job terminal lines event-driven (`ok/failed/abandoned · NN fmt · w1|w2 ·
job/slide/seed k/n · dur · $cost`; `abandoned` carries FR-108's grace sentence), heartbeat
`render 9/11 done, 2 running (0 w1, 2 w2), 0 queued ... 3m10s` read straight off the
`RenderGate` waiter counts; hook = the existing `_drain` loop (`generate/__init__.py:232-236`,
needs one `last_printed` monotonic stamp). COPY/FILTER waits: `copy 3/5 done, 2 in flight
... 31s`. Verbosity: new `--verbose`/`-v` flag + `output.console_verbosity: normal|verbose`
(sibling of `log_verbosity`); new `_Session.note()` seam (~5 lines: run.log always, console
only when verbose) — **run.log and events.jsonl are UNCHANGED by verbosity; only the console
tier moves.** Default healthy-run console ≈ 100 lines (one screen); verbose ≈ 3×. Verbose
adds: every `keep` verdict + reasons, all posts all topics, per-creative candidate refs
offered/chosen, per-upload style-file lines + memo hits, per-entry branding predicate,
15 s heartbeats, job ids + reference URLs.

**FR-300 — menu re-shape (with the pivot's mode-picker removal).** (a) **Source picker
(step 2) DELETED** (~29 lines: one real option + two always-refuse stubs; post-pivot Virlo is
the only source) → wizard inputs **7 → 5**; NFR-16 re-enumerated accordingly (it was already
being amended for the mode picker). (b) Step counters DERIVED from an ordered live-step list
(they are literal `"1/7"`…`"7/7"` strings at seven call sites today — deleting two steps
otherwise prints a wizard that cannot count). (c) Config-picker rows gain the two facts that
now decide runnability: `cs · 2 mon · 4/2/1 · hypelead · 8 styles`, and `_runnable()`
extends to FR-295 (registry parses + ≥1 affine style per requested format under the active
brand) so a broken registry shows as a `NO STYLES` badge at pick time, not an exit-2 three
prompts later. (d) Brand/ratio: DISPLAY-ONLY line (operator's direction is fewer inputs; an
editable `brand=hypelead ratio=0.50` line via `_parse_pairs` is the named future option).
(e) `_say_confirm_ahead`'s hardcoded "8-10 minutes" re-derived (yt-dlp chain is gone).

**Line-growth honesty (CLAUDE.md rule 5):** this section is expected to ADD ~250–350
production lines (stage headers, table, roster, provenance, heartbeats, note() seam, menu
rework) — reported with per-task attribution at the barriers like all growth; it offsets
part of §4's projected net reduction and that is fine.

---

## 2. PRD amendment wave (FIRST — D15)

New decisions: **D41** (meta-style registry replaces vision analysis; registry is the visual authority; no built-in fallback tier; repo-root path resolution), **D42** (verbatim copy via reference selection + competitor filter; legal exposure operator-accepted; COPY_DEGRADED stays a code-1 loss), **D43** (branding block with brand selector; wordmark through the TEXT block; brand_slot/brand_affinity divergence guards; `brand_ratio` on `entry.order`; no compositing — logo PNGs a future option; Notion future override), **D44** (monitor→topics split with per-topic strength; Increment B reference parts cancelled; sessions 3–4 cancelled; history_key migration accepted), **D45** (v2.3 — console observability mandate per §1.10: stage narration with in→out counts, visible sort proof incl. per-post views, per-creative provenance receipts, silence-breaker heartbeats, verbosity tiers with run.log/events.jsonl invariant, wizard 7→5 inputs; FR-286's 78-col ceiling deliberately KEPT).

New FRs: **FR-290** style registry (schema §1.3, FR-174 seam, FR-184 attribution), **FR-291** rotation determinism (stateless order-indexed scan on `entry.order` per §1.3 pseudocode, brand+format affinity, reference window, branding floor-predicate), **FR-292** branding config + two-channel injection + precedence + divergence rule, **FR-293** topic extraction contract (`_themes()`, SourcePost, per-topic strength, reuse-index re-scope), **FR-294** competitor filter (batched fenced screen + blocklist + strip guards + build_context strip), **FR-295** pre-flight registry refusal (exit 2), **FR-296** stage narration + collect liveness (§1.10), **FR-297** sort-proof surfaces — topics table, post roster, provenance block, funnel-once (§1.10), **FR-298** forensic events + `copy_source_refs` + history URLs (§1.10), **FR-299** heartbeats + verbosity tiers (§1.10), **FR-300** menu re-shape — 5 inputs, derived counters, runnability badges (§1.10).

**FR-Range Registry compliance (F5):** 00-overview's registry table gains a row assigning the block — FR-290/291/294 → 10-pipeline, FR-292/295 → 30-configuration, FR-293 → 20-integrations, **FR-296/297/298 → 40-outputs, FR-299/300 → 30-configuration (v2.3)** — and "Next fresh block" advances to **FR-301+**. Amendment version: **v2.0.0** (reversed core premise + 4 new D-numbers). The v2.0.0 amendment-log entry states: D41–D44, the full withdrawn-FR list, the new FR block, the `history_key`/`trend_history.json` migration, the `reel_second` price-scalar change, the yt-dlp AND Pillow dependency removals (v2.2 — Pillow's only importer is `analyze.py:243`), and the PRD.html republish status.

**Verified collision-free:** highest existing D = D40, highest FR = FR-286 → D41–D44 and FR-290–295 are free.

**TL;DR rule (D16) — every amended file:** six of the seven PRD TL;DRs describe the OLD product (v2.2: 00-overview's "can even study the actual winning video" included) in plain English ("shows the real winning images to an AI", "downloads the trend's actual winning video", "copies the shape of the hook, not the words"). T0.1/T0.2 rewrite the TL;DR of every file they touch, under D16's constraints (plain English, <1 min, no requirement IDs).

| File | Exact edits |
|---|---|
| `prds\10-pipeline.md` | **TL;DR fully rewritten** (worst offender — describes vision analysis + "not the words"). FR-3/FR-16/**FR-22** (variant vocabulary) withdrawn; **FR-5** re-based (ranked unit = topic; strength components + min-max pool per §1.6); **FR-8** re-based (batch ceiling counts usable TOPICS, not monitors; both-pair reuse clause dies; operator famine message re-worded); FR-9/10/11/12 replaced by FR-290/291 pointers; **FR-92 withdrawn** (StyleBrief JSON schema → MetaStyle, in lockstep with FR-189); **FR-99** re-based (grouping topic×language-config; sibling divergence via reuse-index; its old degrade — "trend's own hook text" — is now the normal path); **FR-102 extended** (fence vocabulary += `topic_items`/`competitor_list`; per-block verdict isolation clause); FR-17/18/19 rewritten (references = style images; order/roles per §1.9); FR-90 re-based, FR-6 text-only-everywhere; FR-91 → style rotation; FR-93 retired (v2.2: FR-128 is DEFINED in 20-integrations — routed to T0.1's 20-integrations work, same mis-routing class as the FR-153 fix) — **v2.2 premise correction: the vision check has NEVER downscaled (FR-105; `vision_check.py:150-153`, `budget.py:225`); NFR-25's one permitted Pillow use disappears with `analyze.py`, and Pillow leaves pyproject in W3.5**; **FR-20** ("every slide shares the same style brief and the same reference set") re-based to MetaStyle + style reference set (v2.2 gap); §1 inputs prose (`:42` "generation mode, Notion influence tier") re-worded (v2.2 gap); FR-94 kept re-scoped; **FR-95** (anchor "ahead of the trend references" → style references; anchor-only wordmark M12; `carousel_anchor` A/B wording dropped); FR-96 promoted + B2 precedence paragraph; FR-100/101/13/14 → verbatim reference-selection contract (§1.7); **FR-106** both-pair atomic clause deleted; **FR-107** style-brief pricing out, **filter-call line added** (worst-case bound), vision-check pricing stays; FR-109 inverted; **FR-141** content-audit degrade restated (motion-reference trigger gone — `audio_dropped_content_audit` retained for in-model audio only); FR-142 withdrawn; FR-144/145/146 restated vs styles (M14); **FR-147** analysis-prompt half dropped; **FR-23/24** re-sourced (MetaStyle + motion_profile; `in_model` "retained for A/B" wording dropped; the motion-reference recency sentence deleted from BOTH FR-24 and FR-7's copy); FR-7 posts granularity; FR-202: analyzed clause deleted, FR-295 in exit-2 list, COPY_DEGRADED code-1 semantics restated; **§10 failure table**: 8 rows die/change (analysis_missing, text_only last resort, video-reference chain, seed-frame "keeps motion reference", content-audit trigger, pair-incomplete, inspiration-folder row, auto-trim "pairs" wording) + 2 rows added (`filter_degraded` fail-open; registry missing → exit 2); **NFR-5** re-based (log style key + registry hash + filter verdicts instead of full brief + hook_pattern_used); **NFR-8** FR-93 citation re-pointed; **§12** D2/D23 local restatements + the "Text-only sources" tombstone (points at inspiration_mix) rewritten; new FR-290/291/294 section. |
| `prds\20-integrations.md` | **TL;DR rewritten** ("downloads a copy of the winning video", "showing the image model the actual winning pictures"). §3 opening line + join rule → topic-split contract (FR-293); **FR-32 media clause + FR-33 + FR-247 withdrawn** + the two §3 prose blocks ("Reference-image download", "A single dead image…"); FR-160–163 withdrawn; **NFR-160 (pinned yt-dlp) withdrawn**; **§8a `reference_video_urls` bullet + §8b's entire motion-reference chain + D23 heading + ToS risk note removed**; **§8c opening premise** ("the one assumption… actual winning Virlo images") + reference-images field-table row rewritten; **§10 transport table** (4 yt-dlp/video rows + dead-CDN-image row); **§11 model table** analysis row → vision check only; **§4 adapter contract** ("media references", `text_only`) re-worded; FR-249 re-scoped; FR-200/244 seam re-scoped + run-scoped upload memo; §8 reels bill no-reference. **v2.2 gaps folded in:** **§7 OpenRouter block re-based** (`:184` Sonnet "visual trend analysis" role line, `:190` style-brief/copy structured-output prose, `:198` + **FR-128** (`:212`, the ~1024px analysis downscale — WITHDRAWN; owned here), `:204` both-mode-comparability sentence, **FR-129** (`:213`) re-worded to vision-check + copy temperatures); **§2 `get_trends` tool-table row** — `top_exemplars[]` (`:89`) dropped with the digest-exemplar payload; **§8 "Models used" bullets** (`:229-230`) re-based (GPT Image 2 `text_only`/D2 wording; Seedance motion-reference clause); **the §Design-Decisions local D23 restatement (`:467`) is removed TOO** (the §8b-scoped deletion alone would leave it dangling); **§10 upload-failure row (`:367`)** vocabulary re-based (Inspiration → style/brief). (FR-199 lives in 50-promptcraft — routed to T0.2, not here.) |
| `prds\30-configuration-and-run.md` | **TL;DR rewritten** ("AI's style notes", "inspiration images"). **FR-133 + FR-170 amended** (the requirements that enumerate the deleted keys); key removals per prior list; **`niche.brand.*` absorbed into `branding:` (D38 superseded)** incl. the `session.brand or niche.brand` precedence prose; **KEEP `models.analysis`/`max_tokens.analysis`/floor — re-documented as the vision-check role**; **FR-139/FR-140 split** (`--preview-sources` = $0 blocklist verdicts; `--preview-analysis` = LLM verdicts + styles + verbatim copy) + **FR-154** accounts for filter `skip` verdicts; **FR-174 registry carve-out** (styles.yaml has NO built-in tier — FR-295 refusal instead); **FR-131/FR-258 + §2 price block — money fix**: `price_per_unit.reel_second` collapses from the worst-case-with-reference scalar (`0.950/0.425`, ~3× overstated post-pivot) to the plain no-reference rate; `reel_reference_max_s` "price lever" prose deleted; **menu §4 step 5 + FR-56 + NFR-16** (mode prompt removed — the "exactly seven operator inputs" list re-enumerated); **FR-138 + pre-flight prose** (yt-dlp carve-out removed; FR-295 registry/branding validation registered); §Design-Decision local restatements D13/D22/D23/D27/D38. Add `styles:`, `branding:` (§1.4 full schema incl. `never_always`/`never_style`), `sources.virlo_topics_per_monitor`. Notion keys = future override. **v2.2 gaps folded in:** **FR-134 withdrawn** (`:206` "A/B pairing SHALL be automatic and driven by `pair_id`" + its prose twin `:184`); **this file's OWN §failure-table analysis row (`:443`) dies** ("every analysis call fails → direct-mode per FR-12 … `analysis_missing`" — a second failure table v2.1 missed); **FR-173** (`:214`, enumerates `inspiration_folders`) and **FR-259** (`:228`, enumerates `reel_reference_max_s`) amended; **§5 CLI flag table `--mode` row (`:394`) deleted**; **quick-start steps 5–6** (`:40-41`, Inspiration folders + yt-dlp bootstrap) rewritten; **§Sources prose** (`:479` "Virlo and the local Inspiration folder are the two MVP sources" + edge row `:512`) re-based; cross-file pointer `:548` (`pair_id` gallery pairing) deleted. **Price-block precision (v2.2):** the `0.950/0.425` scalars live in `configs\*.yaml` + the v1.6.7 log prose, NOT in §2's price block (which ships `reel_second: null` per FR-131) — the PRD edit is FR-258's worst-case-honest formula definition + the §2 formula prose (`:226`), plus the config-file scalars themselves in T3.4. **v2.3 (D45):** new **FR-299/FR-300** sections (`--verbose`/`-v` flag row in the §5 flag table; `output.console_verbosity` key beside `log_verbosity`; menu §4 re-enumerated to FIVE inputs — mode picker AND source picker both die, NFR-16 amended once for both; config-picker row format + FR-295 runnability badge). |
| `prds\40-outputs-and-logging.md` | **TL;DR clause** ("source reference images for comparison") re-worded. FR-71 id scheme; FR-73 meta.yaml field swap (+`style_key`/`brand`/`branded`/`topic_key`/`copy_source_post_id`); FR-76/FR-231 pair badge withdrawn; FR-150/232 re-based (style adherence + topic provenance); FR-155 funnel re-shaped; **FR-77** run.log contents re-based (generation mode out; style key/brand/filter verdicts in); **FR-80/81 event vocabulary**: `reference_choice` event withdrawn, `virlo_payload` media fields re-based, `kie_job_submitted.reference_sources` documented examples rewritten (no "Virlo post…" strings — this is what W5's payload check reads); **FR-153 amended HERE** (owned by T0.2 — the plan v1 mis-routed it to 10-pipeline): posts map loses "motion-reference video post IDs", and its "requires no migration" clause is replaced by the explicit `history_key` migration note (first post-pivot run sees an empty window by design); **v2.3: post entries gain the post URL beside the date (FR-298)**. **v2.3 (D45):** new **FR-296/297/298** sections per §1.10 — stage narration + collect liveness; topics table/post roster/provenance block as run.log-visible surfaces; **FR-155 re-placed: the funnel prints ONCE, at DONE** (its "after Select" placement clause dies with the stage headers); FR-77 run.log contents gain the stage headers + tables; FR-80/81 event vocabulary += `topic_ranked`, `topic_posts`, `topic_filter_verdict`, `virlo_fields`, `stage_complete`; **meta.yaml field list += `copy_source_refs`** beside `copy_source_post_id`; gallery card quotes the ref label ("quotes P1.hook.2 verbatim") and the exit block prints the gallery path. |
| `prds\50-promptcraft.md` | **TL;DR fully rewritten** (entire premise is the style brief). **FR-181** amended (nine → eight roles; layout names updated; `styles.yaml` described as a new prompts-dir artifact); **FR-183 + FR-263 registry carve-out** (missing template → built-in fallback stays, but `styles.yaml` is EXEMPT — missing registry = FR-295 refusal, reusing FR-263's refusal shape); **FR-184 extended to the registry** (origin + content hash); **FR-182** placeholder examples re-sourced; **FR-189** re-based (six brief fields → five MetaStyle DNA fields, byte-identical per deck, M9); **FR-191/196/197** (style-first role lines F19; seed-frame + hook continuity + M13 wordmark persistence); **FR-199 withdrawn (lives here, not 20-integrations)**; **§5 rewritten** (style-brief prompt contract deleted incl. `{{reference_image_count}}`/`{{engagement_numbers}}`/`{{output_format}}`; copywriter contract → reference-selection mandate; the A20 few-shot "restate the pattern, not the words" mandate flipped per D42); merged `image_post.md` playbook (B2 + M7 + F23); new topic-filter playbook (fence + ordinals); branding playbook (two channels, wordmark-in-TEXT, never_always/never_style, font_character, brand-slot conditional); placeholder table per §1.8 items 2–3; §7 truncation order. **v2.2 gaps folded in:** **§1 two-layer architecture rewritten** (`:16`, `:20-32` — the file's premise statement: "layer (a) IS the Sonnet 5 style brief… This is the analysis"); **FR-195 (`:98`) + FR-194's nine-section list** lose `@Video1` in lockstep with the FR-199 withdrawal + F24. |
| `prds\00-overview.md` | **TL;DR rewrite**; **Problem & Motivation** ("maximum visual fidelity to Virlo trends" — the inverted mission sentence); **Goals G4, G5** (inspiration sources / generation mode list), **G9** (`--preview-analysis` shows style briefs → topics + filter verdicts + styles + verbatim copy); Non-Goals (delete "No local style-template systems", flip "No brand grounding by default", add deliberately-absent clause: no Virlo media, no A/B, no motion reference, no logo compositing); **Walkthrough steps 1–6 + both preview bullets + the Diagram-caveats paragraph** (v2.2: step 3 "rank/skip TRENDS" and step 5 "Luna GENERATES captions…" also describe killed concepts — ranked unit is the topic, recency is post-level, Luna selects refs and the engine resolves bytes; the caveats paragraph additionally gains one FR-295 clause: registry missing → exit-2 refusal); **pipeline mermaid rebuilt per the embedded spec below**; **Success Metrics** (A/B bullet deleted; Fidelity re-based to style adherence, in lockstep with FR-150/232; Cost bullet's reel prices → no-reference only); **Open Questions** (OQ-6, OQ-21 closed as moot; OQ-2 reel-price shape restated; OQ-19 preview-$0 split) + **Build-Time Verification items 3 & 6**; Design decisions: D2/D37/D40 superseded, **D23 WITHDRAWN** (the biggest one), **D24** (role list + registry carve-out), **D31** (A/B-pairs-atomic wording), **D32** (upload seam re-scope), **D36** (recency identity re-based; `usable_trends` counts topics), **D38 superseded**; **v2.2 additions: D19** (preview definitions re-based to the FR-139/140 split), **D20** ("Local Inspiration is an additive influence source per D13" — superseded), **D27** (niche Inspiration path keys — superseded), **D28 + its three local restatements** (00:136, 10:493, 20:468 — "a future text-only adapter marks its items `text_only`"; the flag dies, every post-pivot source is text-only by design; note 00-overview's copy cites FR-6/90/18 and would ESCAPE the tombstone grep); D41–D44 added; **FR-Range Registry row + "Next fresh block: FR-296+"**; glossary swap; amendment log **v2.0.0** entry (contents per above). |
| `prds\PRD.html` | Rebuilt LAST from the amended sources and **brought fully current** — it is ~10 amendments stale (v1.6.3→v1.9.0 all deferred); the rebuild clears the whole backlog. Republished as the Claude artifact per Amendment Protocol step 4; **the flow diagram must render visually in the artifact (contract "latest", never raw mermaid text) — verify after republish** (standing operator rule). |
| `plans\EXECUTION-ORDER.md` | Sessions 3–4 CANCELLED; new session blocks for the waves below (single copy-paste per session). |

**New-diagram spec (binding for T0.3; current node ids anchored):** In `Inputs`: keep `CFG` + `NO` (re-labelled *future override, dormant*); **delete `INSP`**; re-label `V` = "Virlo via MCP: topics, captions, hooks, panel texts, stats — no images, no video"; add `STY` = "meta-style registry `prompts/styles.yaml` — 8 textual styles + their own local reference images" and `BR` = "branding config: brand selector, brand_ratio, colors/wordmark/fonts". After `GATE -- yes`: `SPLIT` ("1 monitor → up to 9 topics, per-topic strength") → `FILT` ("competitor filter: blocklist + fenced LLM screen — keep/strip/skip") → `SEL` (rank + pick topics; post-level recency; slideshow-majority → carousels) → `ASSIGN` ("deterministic style rotation + branding rotation", fed by `STY` and `BR`) → `COPY`. **v2.2 explicit dispositions (the current diagram's `RANK` node and its edges):** the current `RANK` node is REPLACED by the SPLIT→FILT→SEL chain — `V --> SPLIT` replaces `V --> RANK`, `GATE -- yes --> SPLIT` replaces `GATE -- yes --> RANK`, and RANK's `-- "nothing usable" --> XA` abort edge re-homes onto `SEL` (famine wording counts TOPICS per the FR-8 re-base). **Delete the `Understand` subgraph WRAPPER and the `BRIEF` node + the "direct mode: skip analysis" edge; `COPY` SURVIVES standalone** between `ASSIGN` and `Create` (v2.2 — "delete the whole subgraph" would have deleted COPY, which lives inside it); **delete `NO --> COPY` and draw `NO -.->|future override| BR` instead** (post-pivot Notion maps into BrandingConfig, never into verbatim copy). Re-label `COPY` = "verbatim copy — Luna selects by reference, engine resolves bytes; source language kept; competitor names stripped". `Create` shows the **two waves explicitly**: wave 1 (`IMG`, `CAR1` anchor, `SEED`) and wave 2 (`CAR2` slides 2–N chained, `REEL` Seedance **no motion reference**). **v2.2 node notes:** `IMG` is RE-LABELLED "prompt + style reference images from the registry" (its current "2–3 real trend images attached" label must NOT survive); the current single `CAR` node is SPLIT into `CAR1`/`CAR2` and `SEED` is a NEW node (none of CAR1/CAR2/SEED exist today — CAR's anchor-chaining text seeds CAR1/CAR2); dependency edges: `COPY --> IMG`, `COPY --> CAR1`, `COPY --> SEED`, `CAR1 --> CAR2`, `SEED --> REEL`. One dotted edge `STY -.->|1–2 style reference images per job; each file uploaded once per run (memo)| Create` replaces BOTH old INSP edges (v2.2 label fix — "per run" alone was wrong: hypelead-brand-card carries 5 files spread by window rotation). `VC`/`RETRY`/`Outputs` survive; `GAL` re-labelled (topic name, style key, brand/branded, source URL); `SUM` recency wording → post-level.

**Barrier:** conductor re-reads every amended anchor against this table; greps `prds\` for dangling references to **FR-3/9/10/11/12/16/22/33/92/93/128-old-wording/134/142/160-163/199/247, NFR-160, the FR-148/149 tombstone pointers, plus `pair_id` and `text_only`** (v2.2 — the bare-term additions catch 00-overview's D28 copy, which cites FR-6/90/18 and escapes the tombstone grep). **`prds\REVIEW-v1.6-recommendations.md` is EXEMPT** (v2.2): it is a historical review record carrying `pair_id`/`both`/`generation_mode`/FR-148 text by design — the barrier grep skips it (or its hits are recorded and ignored), stated here so the barrier cannot false-fail.

---

## 3. Task list in waves

**Flat-wave dispatch (§9a).** No orchestrating parent (decomposition carved; T2.1–T2.4+T2.6 are 5 python-pro tasks but across 5 distinct domains — trigger 2 does not fire; shared contracts are pinned in `topic-first-pivot-contracts.md`, so no design spike). Conductor owns all aggregating files and wire-in, LAST per wave.

**Aggregating files (single-writer = conductor):** `hypesocials\runner.py`, `hypesocials\models.py`, `hypesocials\config.py`, `hypesocials\sources\__init__.py`, `hypesocials\generate\__init__.py`, **`hypesocials\outputs\__init__.py`** (arch #10), `NAVIGATION.md`, `CLAUDE.md`. **Named carve-out (M1):** T1.1 (python-pro) writes the W1 *additive* pass on `models.py`/`config.py` as the wave's only writer of those files; thereafter both are conductor-only (one W2 conductor micro-pass + W3.5 excision).

**Migration shape (arch #1): ADDITIVE-THEN-SUBTRACTIVE.** Wave 1 only ADDS (new symbols beside the old); waves 2–3 rewrite consumers off the legacy symbols while `StyleBrief`/`Variant`/`GenerationMode`/`ReferenceSet`/`pair_id`/`variant` remain importable; **Wave 3.5 (conductor-owned excision)** deletes the legacy symbols, the three dead files, and the dead prompts. Every wave barrier is therefore **genuinely full-suite green**. Two provisos (verifier): (a) **placeholder/vocabulary additions land in the SAME wave as their allowlist counterparts** — `PLACEHOLDERS` and `PROFILE_TEMPLATES` additions therefore happen in the W2 conductor micro-pass alongside T2.6/T2.5, never in W1 (B1/B2: `test_template_parity` asserts every placeholder is reachable from some role); (b) additive protects **imports, not call-sites** — after T2.6 lands, still-wired legacy callers (`analyze.py:150`) would raise at runtime; that is acceptable because no live run happens at the W2/W3 barriers, only pytest. (c) (v2.2) additive also does not protect **derived schema shape**: adding `LayoutZone.role` in W1 makes `role` a required key in the still-live FR-92 style-brief JSON schema for two waves (`json_schema_for` marks every property required, `additionalProperties: False`) — verified harmless (`test_prompts_engine.py:378-384` asserts top-level fields only), accepted and stated.

**Wave barrier verification (every wave):**
```
.venv\Scripts\python.exe -m pytest -q                       # FULL suite green, every wave
find hypesocials -name "*.py" | xargs wc -l | tail -1        # NEVER wc -l hypesocials/**/*.py (globstar off)
```
Growth reported with per-task attribution.

### Wave 0 — PRD amendments (technical-writer; code untouched)
| id | agent | task | paths |
|---|---|---|---|
| T0.1 | technical-writer | 10-pipeline + 20-integrations per §2 | `prds\10-pipeline.md`, `prds\20-integrations.md` |
| T0.2 | technical-writer | 30-configuration + 40-outputs + 50-promptcraft per §2 | those 3 files |
| T0.3 | technical-writer (after T0.1/T0.2) | 00-overview + D41–D44 + glossary + diagram + amendment log; PRD.html; EXECUTION-ORDER.md session blocks | `prds\00-overview.md`, `prds\PRD.html`, `plans\EXECUTION-ORDER.md` |

**Conductor before W1:** write `plans/topic-first-pivot-contracts.md` (§1.8) from the actual code.
Barrier: anchor re-read + dangling-FR grep; pytest green (nothing changed).

### Wave 1 — additive contracts (nothing deleted; suite stays green)
| id | agent | task | paths |
|---|---|---|---|
| T1.1 | python-pro | `models.py` **additive**: +`MetaStyle` (all §1.3 fields), +`SourcePost`, +`PlanEntry.style_key/branded/topic_key` (defaults keep old constructors valid), +`LayoutZone.role` (optional, default ""), +tags `COPY_NOT_VERBATIM`/`COMPETITOR_STRIPPED`/`STYLE_REFS_MISSING`, +`CopySelection`. **NOT here: `PLACEHOLDERS`/`PROFILE_TEMPLATES`/`GLOBAL_TEMPLATES` additions — they land in the W2 conductor micro-pass in lockstep with the allowlist (B1/B2).** `config.py` **additive**: +`BrandingConfig` (selector + two profiles incl. `never_always`/`never_style`), +`StylesConfig`, +`virlo_topics_per_monitor` (old keys simply STAY through W2–W3 — v2.2: no deprecation plumbing exists (`config.py:563` warns only on UNKNOWN keys) and none is added; at W3.5 removal they become unknown-key warnings, the desired end state). | `hypesocials\models.py`, `hypesocials\config.py` |
| T1.2 | python-pro (parallel) | New `hypesocials\styles.py` + `hypesocials\topic_filter.py` per §1.3/§1.5 and the pinned API (contracts doc quoted). **W1 scope note (v2.2):** `topic_filter` ships `apply_blocklist`, `Verdict`, ordinal keying, strip guards and the degrade contract FULLY; `screen()`'s prompt-render path CANNOT execute until the W2 placeholder/allowlist micro-pass (two independent guards reject it in W1: the `PLACEHOLDERS` membership check `prompts_engine.py:446-449` and the missing `_ALLOWLIST` key) — it is written to the contract, its first end-to-end test is T2.7's. | `hypesocials\styles.py`, `hypesocials\topic_filter.py` |
| T1.3 | test-automator (parallel) | `tests\test_styles.py` (validation matrix, order-indexed-scan determinism on `entry.order` incl. gapped orders, brand-affinity exclusion, reference-window rotation, brand_ratio **floor**-counts incl. ratio 0/1) + `tests\test_topic_filter.py` (ordinal keying, strip guards, blocklist fail-closed, LLM fail-open; `screen()` prompt-path coverage deferred to T2.7 per T1.2's scope note) — written against the contracts doc. Template-level fence assertions belong to T2.7 (the template exists only from W2 — M8). **T1.3 also DELETES `tests\test_reference_rotation.py` (451 ln) in THIS wave (v2.2 BLOCKER fix):** its whole-tree `% len(` policy scan (`:201-224`, hard three-file whitelist) goes red the moment `styles.py` lands, falsifying "every barrier green"; the test is dead-by-design anyway (its `owned == 1` target `sources/__init__.py:80` dies in W3.5). Removed from the W3.5 Tests row accordingly. | `tests\test_styles.py`, `tests\test_topic_filter.py` (+delete `tests\test_reference_rotation.py`) |

Barrier: **full pytest green** (additive-only guarantees it) + new suites green.

### Wave 2 — consumer rewrites (legacy symbols still present; disjoint modules)
| id | agent | task | paths |
|---|---|---|---|
| T2.1 | python-pro | `virlo.py`: `_themes()` topic split, `SourcePost` extraction, **per-topic strength** (§1.6), `_digest` → 2-tuple + `fetch` unpack, topic Counters, module docstring; stop *calling* media/reference functions (bodies deleted in W3.5). **v2.2:** `_MAX_THEMES = 3` (`:83`, consumed `:917-918`) currently caps theme consumption AND drives the FR-5 confidence-mean denominator (`:637`, `:914`) — re-based to `virlo_topics_per_monitor`, the mean spanning all consumed topics. **v2.3 (FR-298):** emit `topic_posts` (every SourcePost `{post_id,url,author,views}` in rank order, per topic) + `virlo_fields` (fields_present/consumed/ignored per monitor) + `topic_ranked` rows; Counters per contracts item 15. | `hypesocials\sources\virlo.py` |
| T2.2 | python-pro | `copywrite.py`: reference-selection contract (§1.7) — candidate numbering + pre-filter (style `max_onimage_chars`, emoji/@/URL/hashtag rules), `CopySelection` call, ref resolution, `_apply_strip` + guards, verbatim verifier, `_fallback_copy` re-base, sibling divergence via `trend_reuse_index`, budgets bypass for ref-resolved fields, language-as-selected sibling lines; stop using A21/pair-rep paths. **v2.3 (FR-298):** persist the resolved ref labels as `copy_source_refs` (contracts item 14) so meta.yaml records WHICH string, not just which post. | `hypesocials\copywrite.py` |
| T2.3 | python-pro | `generate\refs.py` rewrite (style-window attach via upload memo, `_cap` → `styles.refs_per_job`, style-first ordering, override-brief suppression); `generate\carousel.py` + `generate\reel.py` (style_dna from MetaStyle, per_format_guidance by slide role, no video_refs usage, seed-frame branding continuity inputs). yt-dlp stays in `pyproject.toml` until W3.5 (its consumer `video_ref.py` lives until then — M9). | those 3 files |
| T2.4 | python-pro | `budget.py` (style-brief lines out — region `:418-441` + docstring paragraphs `:393-414`, v2.2 re-anchor; **vision-check `analysis` pricing stays** (`:226`); reel reference-seconds out; +filter line with worst-case bound; **v2.2 BLOCKER fix: `siblings_of()` (`:455-457`) re-based to `len({e.asset_id for e in members})` + docstring — it reads `pair_id` inside the COPY-pricing block, outside every previously-scheduled region, and would AttributeError on every `estimate()` after W3.5**); `preflight.py` (FR-295 via `styles.validate`, branding validation, variant-leak warning, yt-dlp out, `cs` heuristic re-base); `sources\notion.py` re-point to BrandingConfig (docstring refs at `:7`, `:15`, `:84` — v2.2 names all three). (`vision_check.py` dropped from this task — v2.2 verified it needs NO edit; the config.py comment re-base is the conductor's, per M1.) | `hypesocials\budget.py`, `hypesocials\preflight.py`, `hypesocials\sources\notion.py` |
| T2.5 | prompt-engineer | `prompts\`: new `styles.yaml` per the **normalization table** (§1.3, binding — incl. literal-string exclusions quoted from the actual files, variant resolution, dropped NotionBased reference, reel-affinity drop for hypelead-brand-card); merged `image_post.md` (B2 paragraph, M7 line, F23 constraints, reworded wordmark prohibition); `carousel_slide.md`, `carousel_anchor_instruction.md` (anchor-only signature), `reel_seed_frame.md`, `seedance-2-5\reel_director.md` (F24: @Video1 paragraph deleted, beats, motion_beat, motion_profile paragraphs, continuity wordmark); `copywriter_system.md` (reference-selection mandate); new `topic_filter_system.md` (fence + ordinals); `prompts\README.md` (allowlist spec — co-maintained source of truth). Old templates left in place (deleted W3.5). | `prompts\**` |
| T2.6 | python-pro | `prompts_engine.py`: allowlists per contracts doc, `build_context` new signature, `_branding_block()` + `_onimage_text` wordmark entry, `_strip_brands` pass, `_topic_items()` ordinals, `style_dna` from MetaStyle, `_budget_line(min(style, config))`, truncation order, built-ins mirroring T2.5 (incl. wordmark clause); legacy builders stop being called (deleted W3.5). | `hypesocials\prompts_engine.py` |
| T2.7 | test-automator | Rewrite `tests\test_virlo_refs.py` → `test_topic_split.py` (offline fixtures; per-topic strength assertion); **flip polarity** `test_copy_no_verbatim.py` → `test_copy_verbatim_filter.py` (ref-resolution byte-identity; blocklist never in output; strips logged; verified at assembled render prompt); `topic_filter_system.md` fence-presence assertions (from T1.3 — M8); update `test_prompts_engine.py`, `test_template_parity.py` (**transitional SHIPPED count 11**; global trio +topic_filter; final 8 set at W3.5), `test_copywrite.py`, `test_virlo_data_channel.py`. Old suites `test_reference_rotation.py`/`test_video_ref.py` marked for W3.5 deletion (still green meanwhile — legacy paths intact). | those test files |
| T2.8 | test-automator (moved from W3 — B3: same wave as the render-path code they cover) | `tests\test_steering_fixes.py` (prune A16/A20/A21, keep A15), `test_carousel.py`, `test_reel.py`, `test_generate_waves.py` — rewritten against T2.3/T2.6's contracts (disjoint from T2.7's file set). | those 4 test files |

**Conductor wire-in after children (W2):**
- **Conductor micro-pass on `models.py`** (in lockstep with T2.5/T2.6 — B1/B2): `PLACEHOLDERS` += `branding_block`/`topic_items`/`competitor_list`/`motion_profile`/`motion_beat`; `PROFILE_TEMPLATES["gpt-image-2"]` += `image_post.md`; `GLOBAL_TEMPLATES` += `topic_filter_system.md` (decorative, hygiene). **v2.2: same micro-pass re-bases `config.py:179-182` + `:186-187`** (style-brief sizing comments → vision-check sizing, values unchanged; conductor-owned file per M1).
- **`generate\__init__.py`** (B4): `Env` field diff per contracts-doc item 11 (−`style_briefs`/−`brand_accent`/−`brand_product_nouns`/−`video_refs`; `local_refs` kinds → `{"style","brief"}`; +`styles`, +`branding`); `_assemble`'s `build_context` call updated to T2.6's signature; `_ref_source` vocabulary → `"style" | "brief"`.
- `sources\__init__.py`, `outputs\__init__.py` barrels updated additively (new exports; old exports stay until W3.5).

Barrier: **full pytest green**; line-count attribution.

### Wave 3 — orchestration & surfaces
| id | agent | task | paths |
|---|---|---|---|
| T3.1 | python-pro | `plan.py` (single-entry `_emit`, id scheme, reuse-index re-scope) + `previews.py` (`--preview-sources`: blocklist verdicts only, $0; `--preview-analysis`: LLM verdicts + style/brand assignment + verbatim copy; swap `_record_render_forecast` import for the style-forecast helper; **v2.2 MAJOR fix — also drop the `_analyze` import (`:52`, call `:172`), the `StyleBrief` import (`:45`), `_launch_video_refs` prose (`:21-22`) and the style-brief module-contract sentences (`:7-8`, `:16`)** — missing any of these turns the W3 conductor's `_analyze` deletion into a collection-time ImportError for the entire suite; reuse `runner._screen_topics` — signature from contracts doc; **v2.3 (FR-297): `_verdict_block` replaced by the shared topics table at `limit=None`** — one line per topic instead of ~8). | `hypesocials\plan.py`, `hypesocials\previews.py` |
| T3.2 | python-pro | `outputs\gallery.py` re-base; `outputs\packager.py` `save_reference` re-keyed trend→style; `outputs\state.py` history on texts-used post ids + migration behavior (§1.6). | those 3 files |
| T3.3 | python-pro | `cli.py` (−`--mode`, **+`--verbose`/`-v` — FR-299**), `menu.py` per **FR-300**: mode picker out AND source picker out (7 → 5 inputs), **step counters DERIVED from an ordered live-step list** (literal `"1/7"`…`"7/7"` at seven call sites today), config-picker rows gain `brand · N styles` facts, `_runnable()` extends to FR-295 (`NO STYLES` badge at pick time), brand/ratio display-only line, `_say_confirm_ahead` duration re-derived (yt-dlp gone); `wizard_help.md`. | those 3 files |
| T3.4 | prompt-engineer | `configs\*.yaml` (branding selector + overrides from v2 artifact; styles; topics key; dead keys removed), `niches\hypedigitaly\**` alignment. | `configs\*.yaml`, `niches\hypedigitaly\**` |
| T3.5 | test-automator | `tests\test_plan.py`, `test_ids.py`, `test_exit_codes.py` (FR-202 clause out, FR-295 in, COPY_DEGRADED semantics), `test_funnel_report.py`, `test_budget.py`, `test_preflight.py`, `test_state.py`, `test_config.py`. **v2.2:** the dispatch prompt quotes the target `_pipeline` stage order VERBATIM (confirm → collect → `_screen_topics` → select → assign → `assign_styles`+`assign_branding` → `_store_references` → write_copy → create) — `test_funnel_report.py:468-496` asserts textual ordering via `inspect.getsource` against a `_pipeline` the conductor writes LAST in this same wave. | those 8 test files |
| T3.6 | test-automator | `tests\test_console_inventory.py`, `test_menu.py` — rewritten in the wave where their subjects change (T3.3 menu/cli, conductor's runner console). The four render-path suites moved to T2.8 (B3). **v2.3:** console inventory additionally asserts the §1.10 surfaces — stage-header grammar (computed `[n/N]`, in→out counts), topics-table rows ≤78 cols with non-increasing `strn`, provenance-block shape, heartbeat lines absent from a fast run (silence-breaker), funnel appearing exactly once, wizard step counters derived (no literal `x/7` after two steps die). | those 2 test files |

**Conductor (wire-in, LAST):** `runner.py` per §1.2's runner row — pipeline: confirm → collect → `_screen_topics` → select → assign → `assign_styles`+`assign_branding` → `_store_references`(style images) → write_copy → create; funnel re-shape; Env construction. **v2.3 (§1.10, conductor-owned surfaces):** stage headers `[n/N]` with computed N; topics table + post roster + provenance block (pure-function blocks, one `say()` each); `_Session.note()` seam + `output.console_verbosity` (config.py is conductor's); funnel printed once at DONE; collect liveness lines + the four virlo `_warn` sites routed through the `say` seam; root-logger decision in `__main__.main` (stderr leakage ends); **render heartbeat + per-job terminal lines in `generate\__init__.py:_drain`** (conductor-owned barrel; `last_printed` monotonic stamp); gallery path printed at first card + exit; launch block += `styles`/`branding` fact lines; brief-only "Virlo returned no video" bug dies at the call site.
Barrier: **full pytest green**; line-count attribution.

### Wave 3.5 — EXCISION (conductor only; no subagents) — complete list (M5)
- Files: `hypesocials\analyze.py`, `hypesocials\generate\video_ref.py`, `hypesocials\sources\inspiration.py`. **v2.2 BLOCKER correction — the v2.1 relocation instruction was dead code:** the vision check has NEVER downscaled (FR-105; `vision_check.py:150-153` "at NATIVE resolution … Never downscaled", `budget.py:225`) and imports nothing from `analyze.py` (imports: config/models/prompts_engine only). `analyze.py:243` is the package's ONLY `from PIL import Image`, so **Pillow leaves `pyproject.toml` in this wave alongside yt-dlp**; CLAUDE.md's stack line ("Pillow (image downscale only per FR-93)") is corrected in W4 (T4.2). No relocation, no surviving NFR-25 Pillow use — §2's 10-pipeline row states the same.
- `models.py`: `StyleBrief`, `ReferenceSet`, `Variant`, `GenerationMode`, `pair_id`/`variant` fields, **`AssetRecord.generation_mode` (`:277`) + `AssetRecord.style_brief_summary` (`:285`) — distinct FIELDS, both serialized into meta.yaml via `packager.py:270` (v2.2: the v2.1 list caught them only as a config key / a placeholder)**, `ANALYSIS_MISSING`, `HOOK_PATTERN_GENERIC`, orphaned placeholders (`style_brief_summary`, `inspiration_exemplars`, `brand_accent`, `engagement_numbers`, `reference_image_count`, `output_format`), `hook_pattern_used`; template tables drop the three dead templates (SHIPPED 11 → **8**).
- `config.py`: legacy keys (`generation_mode`, `reel_video_reference`, `reel_reference_max_s`, `require_reference_image`, `media_download_cap`, `reference_images_per_job`, `inspiration_folders`, `inspiration_mix`, `niche.brand`).
- `virlo.py`: the media/reference-group/motion/digest-exemplar/cache **bodies** T2.1 stopped calling (`_reference_groups`, `_download_references`, `_download`, `_set`, `_pick_set`, `_pick_motion`, `_frame_quality`, `_offer_digest_exemplars`, `_log_digest_exemplars`, `_cache_dir`, `reference_paths`, `cleanup`, download counters — ~331 lines).
- `sources\__init__.py`: inspiration imports + `reference_group_index`/`reference_group`/`brief_key` logic; dead barrel exports everywhere.
- `prompts_engine.py`: legacy builders (`style_dna(StyleBrief)` old path, `_brief_summary`, `_layout_zones(brief)`, `_engagement_numbers`, `_inspiration_exemplars`, `_brand_accent`) + the three dead built-ins.
- `render\kie.py`: the dead `if "virlo" in host:` branch (`:411-412`) + stale comment (`:414`).
- **Stale-prose re-point sweep (v2.2 BLOCKER fix — without it the barrier grep below is unreachable, and CLAUDE.md rule 5 forbids absorbing that by trimming docstrings):** `render\profiles.py:66` (yt-dlp/video_ref format comment), `render\__init__.py:18` (module list naming video_ref.py), `llm.py:24` (`analysis_missing` docstring), **`__main__.py:46` — NOT cosmetic: the FR-249 scratch-dir reaper's list drops `generate/video_ref.py`, else the sweep names a directory nothing creates**, `sources\notion.py:15`/`:84` (brand_accent prose beyond the `:7` docstring), plus a `previews.py` residue check (7 pre-pivot grep hits — T3.1 should have cleared them; verify).
- `pyproject.toml`: yt-dlp dependency (its last consumer dies in this wave — M9) **+ Pillow (v2.2 — its only importer `analyze.py:243` dies in this wave)**; CLAUDE.md stack lines follow in W4.
- Prompts: `style_brief_system.md`, `gpt-image-2\image_direct.md`, `gpt-image-2\image_single_post.md`.
- Tests: `tests\test_video_ref.py` (254). (`test_reference_rotation.py` was already deleted in W1 — T1.3's v2.2 blocker fix.)

Barrier (hard):
```
.venv\Scripts\python.exe -m pytest -q     # FULL green, zero excused
grep -rnE '\bpair_id\b|\bvariant\b|\bVariant\b|\bgeneration_mode\b|\bGenerationMode\b|\banalysis_missing\b|\bStyleBrief\b|\bReferenceSet\b|\breference_groups\b|\bwinning_video\b|yt.?dlp|\bvideo_ref|\bstyle_brief|\binspiration\b|\btext_only\b|\bhook_pattern|\bcopy_exemplars\b|\breference_images_per_job\b|\bmedia_download_cap\b|\brequire_reference_image\b|\bbrand_accent\b' hypesocials/ --include=*.py   # → 0 hits
```
(Word-boundary per arch #7 — bare `variant` matches "Invariants" in 12 surviving module contracts; the naive grep can never pass. Extended term list per verifier M5. **v2.2: `video_ref`/`style_brief`/`hook_pattern` are right-UNANCHORED** — `\bvideo_ref\b` misses `video_refs`, `\bstyle_brief\b` misses `style_brief_summary`/`style_brief_line`/`style_brief_schema`/`style_brief_system.md`, `\bhook_pattern\b` misses `hook_pattern_used`/`_hook_patterns`; the underscore is a word character, so the old terms report clean while the symbols survive.)

### Wave 4 — hardening & docs
| id | agent | task | paths |
|---|---|---|---|
| T4.1 | test-automator | New `tests\test_branding.py` (ratio determinism on `entry.order` incl. 0/1 — v2.2: assert the per-entry floor predicate + `floor(N·ratio)` over the full plan, and the gapped-orders case after a trim, never a bare delivered count, per-profile block content + `never:` lines, wordmark-in-TEXT-block assertion, brand-slot collapse + conditional zones, **cross-brand: hypelead payloads never carry indigo hexes and vice versa**, carousel anchor-only wordmark, upload-memo single-upload assertion, no URL persistence across runs). | `tests\test_branding.py` |
| T4.2 | technical-writer | `README.md`, `ACCEPTANCE.md`; conductor merges `NAVIGATION.md` + `CLAUDE.md` (stack: yt-dlp out AND Pillow out — v2.2, no consumer remains after W3.5; "Reference images" paragraph rewritten; glossary; registry no-fallback note). | `README.md`, `ACCEPTANCE.md` (+conductor: `NAVIGATION.md`, `CLAUDE.md`) |

Barrier: full pytest; line-count report; NAVIGATION.md statement.

### Wave 5 — live verification (§5; conductor + operator).

**Wire-in registry (every new symbol → site):**
| Symbol | Wired where |
|---|---|
| `styles.load_registry` / `StyleRegistry` | `preflight.check` (FR-295), `runner._open`/`_pipeline` (load once, log hash), `previews` |
| `styles.assign_styles` / `assign_branding` | `runner._pipeline` after `plan.assign` |
| `runner._screen_topics` → `topic_filter.screen` | between `_collect` and `_select` (post-Confirm); reused by `previews` (LLM half in `--preview-analysis` only) |
| `topic_filter.apply_blocklist` | `copywrite` verifier + `previews` (`--preview-sources` $0 verdicts) |
| `MetaStyle` → prompts | `generate\refs.attach` (window uploads via memo), `generate\_assemble`/`carousel`/`reel` via `build_context(style=...)` |
| `{{branding_block}}` / wordmark-in-TEXT | `prompts_engine._ALLOWLIST` + `_onimage_text`, `generate.Env.branding` |
| `{{topic_items}}`/`{{competitor_list}}` | `topic_filter_system.md` only |
| `{{motion_profile}}`/`{{motion_beat}}` | `reel_director.md` only |
| `SourcePost` | `virlo._themes`, `copywrite` selection + verifier, `state.py` history, `gallery` source URL |
| `CopySelection` | `copywrite._call_copy` schema |
| Counters `add_topics`/`record_filter` | `virlo`, `topic_filter`, `runner._funnel_block` |

---

## 4. Removal inventory (updated per review)

**Production (table rows sum to ≈2,100–2,200 gross; the virlo and runner rows are partly re-additions in place, so honest gross removed ≈ −1,900; added ≈ +1,300; projected net ≈ −450 to −650 from 16,356):**

| Target | ~lines |
|---|---|
| `analyze.py` (262), `video_ref.py` (359), `inspiration.py` (318, ~20 ported) | 939 |
| `virlo.py` media/digest/cache (~331 verified) + Counters fields; net closer to −80 after topic split + per-topic strength | ~340 gross |
| `copywrite.py` A21 (~130) + pair-rep (~30) + exemplar channel | ~170 |
| `budget.py` style-brief pricing + reel reference-seconds (vision-check pricing STAYS) | ~95 |
| `runner.py` — `_analyze` 45, `_launch_video_refs` 24, `_brief_block` 40, `_analysis_degrade_counts` 22, `_analysis_degraded_line` 28, `_hook_patterns` 8, `_motion_clause` 9, `_record_render_forecast` 31, `_funnel_attachment` 19, exit clause, funnel rows | ~230–260 |
| `models.py` legacy symbols + placeholders | ~110 |
| `plan.py` variants (~30), `gallery.py` pair machinery (~40), `menu.py`/`cli.py` picker (~45), `previews.py` brief display | ~140 |
| dead prompts + engine built-ins | ~150 |

**Tests:** delete 451 + 254; polarity-flip 580; rewrite 595 → topic split; prune 540 ~⅔; heavy rewrites per waves; new: `test_styles.py`, `test_topic_filter.py`, `test_branding.py`, `test_topic_split.py`.

---

## 5. Live verification session (final barrier, mirrors A4)

Real runs, operator present, cheapest-first:

1. `--list-monitors` → exit 0, $0.
2. `--preview-sources --config hypedigitaly` → topics (up to 9×N), one `topics` funnel line, **deterministic blocklist verdicts only, $0**, no download counters.
3. `--preview-analysis --config hypedigitaly-cs` → LLM filter verdicts (keep/strip/skip + reasons), style + brand assignment, verbatim copy **in the source language untouched**; LLM cost only, zero Kie calls.
4. **One paid run** (8 creatives incl. 1 carousel + 1 reel; `brand: hypelead`, `brand_ratio: 0.5`, low cap). Checklist — observed, not assumed:
   - [ ] No Virlo CDN host in any `kie_job_submitted` payload; every `image_urls` entry is an upload of a registry-declared local file; ≤ `refs_per_job`; each distinct file uploaded ONCE per run (memo).
   - [ ] Style rotation: ≥5 distinct `style_key` across 8 meta.yaml; re-preview **against the same cached topic set** picks identical styles; **no `hypelead-brand-card` in any meta.yaml when `brand: hypedigitaly`** (separate cheap preview check).
   - [ ] Branding: branded set = exactly the entries whose `entry.order` satisfies the floor predicate — `floor(8·0.5)` = 4 over the FULL emitted plan; if any entry was trimmed/dropped, assert the per-entry predicate instead of a bare 4/8 count over delivered meta.yaml (v2.2); branded payloads carry the profile's `never:` lines; grep: no `#34288B` in any hypelead payload; **no competitor string in any prompt payload** (M6); wordmark spelled correctly, in the TEXT block, absent on unbranded; carousel wordmark on the anchor slide only.
   - [ ] Verbatim: every rendered string byte-matches its quoted `SourcePost` (modulo logged strips); two creatives on one topic carry **different `copy_source_post_id`**; no blocklisted brand anywhere.
   - [ ] Reel: empty `video_urls`, no-reference billing, no yt-dlp process; seed-frame wordmark persists across the clip when branded.
   - [ ] Funnel coherent: topics row, filter row (kept/stripped/skipped), branded count; no reference/download rows; reconciles.
   - [ ] Gallery: topic name, style key, brand+branded, source URL; no pair sections; `refs/` shows style images.
   - [ ] Exit codes: clean → 0; registry renamed → exit 2 + FR-295 line + $0; over-cap trim → exit 1.
   - [ ] **Observability (v2.3, D45) — watched live on the console, not reconstructed from logs:** every stage header prints with in→out counts and computed `[n/N]`; the topics table shows ALL topics with per-topic views/median and a non-increasing `strn` column (the sort proof); the post roster's `P` ordinals match the `copy_source_refs` in meta.yaml; the RENDER phase is never silent longer than 30 s (heartbeat or job line); the provenance block maps every delivered creative to topic + quoted post (author/views/post_id) + style + branded + cost; the gallery path prints when the first card lands; no bare stderr `logger.warning` leakage anywhere in the transcript; `--verbose` re-run shows all posts/all verdicts while run.log stays byte-identical in content policy (verbosity moves ONLY the console tier).
5. `find hypesocials -name "*.py" | xargs wc -l | tail -1` with per-task attribution vs 16,356. Deep-module re-review of virlo/prompts_engine/runner (§1.2 statements) recorded in the closeout.

---

## 6. Risks (top 8)

1. **Verbatim copy = plagiarism/legal exposure.** Operator-accepted (D42). Residual: competitor filter; source URL on every gallery card; nothing auto-publishes.
2. **Meta-style prompts too weak.** Mitigation: hybrid uploads default-on; registry versioned+hashed; normalization table reviewer-annotated; W5 hard gate. Weakest styles named by review (photoreal-ambient, meme-caricature, editorial-voxel) got targeted fixes (subject_mode, per-panel budgets, accent resolution).
3. **Competitor-filter false negatives / destructive strips.** Blocklist fail-closed + LLM fail-open + strip guards (M15) + verifier at prompt level (M6) + gallery human gate.
4. **Kie 24 h retention.** Per-run uploads via memo; failed upload degrades one reference (`style_refs_missing`); tests assert no cross-run URL persistence.
5. **Prompt-rendered branding wrong** (misspelled wordmark / cross-brand contamination). Wordmark-in-TEXT with `_spell()`; `never:` lines; `brand_affinity`+`brand_slot` structural guards; cross-brand hex tests; `brand_ratio` dial; logo PNGs = future compositing escape hatch.
6. **Reel quality regression without motion reference.** Accepted trade. Seed frame + style + F24 staging (beats/motion_beat/motion_profile); W5 runs one reel first.
7. **Topic split floods/starves.** Increment-B contract (cap 9, never-fewer invariant, `-1` kill switch); per-topic strength prevents identical scoring; `themes` funnel line.
8. **Blast radius of the excision.** Additive-then-subtractive migration keeps every barrier green; word-boundary grep audit at W3.5; polarity-flipped tests land in the same wave as the code they cover.

---

## 7. Critical files

- `hypesocials\models.py` — W1 additive contracts / W3.5 excision
- `hypesocials\runner.py` — pipeline rewiring, funnel, exit codes; sole aggregating wire-in point
- `hypesocials\sources\virlo.py` — topic split + per-topic strength
- `hypesocials\prompts_engine.py` — allowlists, two-channel branding, strip pass, merged built-ins
- `hypesocials\copywrite.py` — reference-selection verbatim contract
- `plans\topic-first-pivot-contracts.md` — the frozen interface doc every W1/W2 dispatch quotes

---

## 8. Review log (2026-08-12)

| Reviewer | Verdict | Blockers → resolution |
|---|---|---|
| architect-reviewer | targeted redraft | #1 wave-1 deletes break imports → **additive-then-subtractive + W3.5 excision**; #2 `analysis` role → **kept as vision-check role**; #3 brand mixing → **brand_affinity + preflight error + W5 check**. Majors #4–11 all folded (preview $0 split, MetaStyle DNA fields, normalization table, word-boundary grep, reuse-index re-scope + sibling divergence, continuous cursor, notion.py/outputs-barrel owners, runner symbols +5). |
| code-reviewer (python) | approve-with-changes | #1 = arch #2 (same fix); #2 late test suites → **T3.6 in wave 3**. Majors folded: placeholder orphans, pinned contracts doc, text_density consumer (`_budget_line(min)`), TrendItem exhaustive disposition, per-topic strength, DegradationTag diff + COPY_DEGRADED exit decision, T1.3 vs contracts doc, runner FR-252 symbols. Minors folded (ported-lines correction, refs `_cap`, upload memo, `_digest`/`fetch`, order-keyed determinism, history migration note, `_configure_llm`, virlo net realism). |
| prompt-engineer | approve-with-changes | B1 wordmark vs templates → **TEXT-block routing**; B2 scene vs subject → **subject_mode + precedence paragraph**; B3 = arch #3 (+ data-driven brand_slot); B4 filter fence → **ordinals + FR-102 fence + placeholders**; B5 verbatim → **reference-selection contract**. Majors folded (M6 strip-at-prompt, M7/M8 exclusions literal+scoped + dropped client-screenshot ref, M9 variant resolution, M10 density numbers, M11 conditional brand slots, M12 anchor-only, M13 reel continuity, M14 override precedence, M15 strip guards). Minors folded (F16–F24). |

### Verification round (triple-check, 2026-08-12, three independent agents on v2)

| Verifier | Verdict → resolution |
|---|---|
| operator-intent | **SATISFIED on all 6 axes** (inversion, rotation, verbatim, branding completeness, brand-system scope, no contradictions). Four operator-visibility items surfaced (caption-only degrade frequency; HD monogram = text wordmark only; editorial-voxel accent normalized to teal; COPY_DEGRADED = exit 1 under `--yes`). |
| PRD-coverage | GAPS FOUND (~25 amendment sites) → **all folded into §2**: Success Metrics/Open Questions/Walkthrough, D23-D24-D31-D32-D36-D38, FR-5/8/22/32/33/92/95/99/102/106/141/147/23/24/77/80/81/131/133/139/140/153/154/170/174/181/182/183/184/189/191/196/197/199/247/258, NFR-5/8/16/160, §10 tables both files, TL;DR rule for all amended files, FR-Range Registry row + FR-296+, v2.0.0 entry, embedded diagram spec, PRD.html full-backlog rebuild + artifact-render check, extended barrier grep. |
| v2-consistency | needs-edits (4 B, 9 M, 12 m) → **all folded**: B1 placeholder/allowlist lockstep (W2 conductor micro-pass), B2 real template registries + transitional SHIPPED 11→8, B3 T2.8 in W2 (render-path suites), B4 `generate\__init__.py` W2 conductor item + Env pinned (contracts items 11–14); M1 T1.1 carve-out, M3 `LayoutZone.role`, M4 `_themes()` inline contract, M5 complete W3.5 list + extended grep, M6 `never_always`/`never_style` split, M7 table scope honesty + renames, M8 fence tests → T2.7, M9 yt-dlp removal → W3.5; minors (max_onimage normalization, affinity annotations, orange on both profiles, teal_mid restored, runner symbols +3, `_configure_llm` no-op note, §4 arithmetic footnote, topics-not-themes wording, downscale-helper relocation note). |

### Verification round 3 (v2.1 → v2.2, 2026-08-12, three fresh independent agents)

| Verifier | Verdict → resolution |
|---|---|
| architecture-vs-code (every anchor grepped/executed) | needs-edits (3 B, 4 M, 10 m) → **all folded into v2.2**. **B1** `test_reference_rotation.py`'s whole-tree `% len(` policy scan (hard 3-file whitelist) goes red the moment W1's `styles.py` lands → **deleted in W1 (T1.3), removed from W3.5**. **B2** excision list incomplete → `budget.siblings_of()` (`:455-457`, reads `pair_id` in the copy-pricing block → AttributeError on every estimate) added to T2.4; `AssetRecord.generation_mode`/`.style_brief_summary` fields added to W3.5 models row; stale-prose sweep added (`render\profiles.py:66`, `render\__init__.py:18`, `llm.py:24`, `__main__.py:46` FR-249 scratch list, `notion.py:15/:84`, previews residue); grep terms right-unanchored (`\bvideo_ref`, `\bstyle_brief`, `\bhook_pattern`). **B3** "vision-check downscale survives" premise FALSE (FR-105: never downscaled; zero analyze.py imports) → §2 row corrected, W3.5 relocation deleted, **Pillow removed from pyproject (W3.5) + CLAUDE.md stack (T4.2)**. **M4** branding count is `floor(N·r)` not `round`, orders gapped after trims → §1.4/T4.1/§5-step-4 restated. **M5** rotation spec self-contradictory (global cursor vs order-derived start) → pinned stateless order-indexed-scan pseudocode (§1.3 + contracts §5). **M6** previews.py also imports `_analyze`+`StyleBrief` → T3.1 extended (else W3 = suite-wide ImportError). **M7** `topic_filter.screen()` unexecutable in W1 (PLACEHOLDERS guard + missing allowlist key) → W1 scope note on T1.2/T1.3, first e2e test = T2.7. Minors folded: item-1 signature corrections (+`brand_product_nouns` disposition), budget `:418-441` re-anchor, `image_single_post.md:24-32/:77-81` re-anchor, vision_check.py needs NO edit (config.py:179-187 comments re-based instead, conductor W2), `_configure_llm` sentence deleted, `_MAX_THEMES=3` named in T2.1, "warned-deprecated" dropped (no such plumbing), LayoutZone.role schema side-effect stated (proviso c), F16 re-scoped (six divergent regions + union allowlist), T3.5 quotes pipeline order verbatim. Confirmed correct: all runner symbol names+line counts, file line counts (262/359/318), 16,356/10,899 baselines, `_digest` 3→2-tuple, SHIPPED 9→11→8 arithmetic, placeholder orphans, D40/FR-286 headroom, Bresenham float-safety. |
| PRD-coverage (live `prds\` tree) | gaps found (~20 sites) → **all folded into §2 rows**. Major: FR-134 + `:184` prose (30-config), 30-config's OWN §failure-table analysis row (`:443`), 20-integrations §7 OpenRouter block (`:184-:213` incl. **FR-128 — re-routed to 20-integrations, v2.1 mis-routed it to 10-pipeline** — and FR-129). Moderate: `get_trends` `top_exemplars[]` row, §8 models-used bullets, §Design-Decisions D23 local restatement (`:467`), FR-20, 50-promptcraft §1 premise, FR-195/FR-194 @Video1, 30-config §Sources prose + CLI `--mode` table row. Minor: FR-173, FR-259, quick-start steps 5–6, `:548` pair_id pointer, D28 + three local restatements (00-overview copy escapes the tombstone grep → bare-term grep additions), D19/D20/D27. Precision fixes: price-block scalars live in configs/log-prose not the §2 block; "five of seven" TL;DRs → six of seven; **`REVIEW-v1.6-recommendations.md` declared grep-EXEMPT** (historical record). Confirmed correct: D40/FR-286 maxima, v1.9.0 → v2.0.0, FR-153/FR-199/NFR-160 routing, all 8 dying §10 rows, PRD.html staleness (v1.6.3, ~10 amendments behind), Wave-0-first D15 ordering. |
| diagram-spec (vs the actual mermaid, 00-overview:58-101) | needs edits (4 M, 4 m) → **all folded into the §2 diagram spec + 00-overview row (v2.2)**. M: `RANK` replacement made explicit (V→SPLIT, GATE→SPLIT, nothing-usable→XA re-homed to SEL); `NO --> COPY` deleted + `NO -.->|future override| BR` drawn; Walkthrough amendment extended to steps 1–6 (step 3 "rank trends", step 5 "Luna generates" were uncovered); `IMG` re-label pinned ("style reference images from the registry"). m: CAR split into CAR1/CAR2 + new SEED node + dependency edges specified; subgraph-wrapper-vs-COPY deletion disambiguated (+`ASSIGN --> COPY`); STY edge label corrected to per-job + once-per-run-memo; FR-295 clause added to the caveats paragraph. Confirmed correct: all 13 anchored node ids exist; exactly two INSP edges (one dotted STY edge covers both); direct-mode edge verbatim; motion-reference sites all covered; FILT placement matches §1.5; pipeline coverage complete at diagram abstraction; PRD.html rebuild-LAST + artifact-render check present with T0.3 owning both. |

### Round 4 — console UX & observability (v2.2 → v2.3, 2026-08-12, operator mandate, three agents)

| Agent | Findings → resolution |
|---|---|
| console-flow storyboard (menu→run→exit, every `say` path mapped) | The wizard, Confirm gate and spend table are excellent; the failure is LIVENESS and PAID-RUN IDENTITY. **CRITICAL:** the RENDER phase (1–10 min, the longest in the product) prints NOTHING — a hung Kie job and a healthy poll loop are indistinguishable. **HIGH:** Collect is silent and its degrades go to logs, while the UNCONFIGURED root logger leaks `logger.warning` bare onto stderr (undesigned output on a random channel); a paid run shows only the top-3 trends, no rank ordinals, no sort-key caption, and never prints the creative←trend mapping (log-only at `runner.py:554-563`); per-item drop reasons aggregate-only. MEDIUM: Analyze/Write no ticks; vision-check outcomes console-invisible; no stage numbering. → **FR-296 (stage narration + collect liveness + logger fix), FR-297 (identity surfaces), FR-299 (heartbeats)**. |
| data-provenance audit (5 questions × {console, run.log, events.jsonl, meta.yaml, gallery}) | **"Is sorted-by-views verifiable by the operator without reading source code?" — NO at post level, partial at topic level**: per-post view counts appear in NO surface at all (`order_by=views desc` hardcoded `virlo.py:71`, `mcp_call` logs no args by design, `_ranked()` silent), and the pivot as written keeps `SourcePost.views` in memory but schedules NO display — while making post rank select the verbatim copy. Also: the topic's post roster reaches no surface (only chosen ids, aggregated); `copy_source_post_id` records the post but not WHICH string; funnel-counter shape post-pivot asserted not specified; filter verdicts needed per-topic identity; field-consumption ledger absent; history stores bare ids. → **FR-297 (table + roster + provenance receipts), FR-298 (`topic_posts`/`topic_ranked`/`topic_filter_verdict`/`virlo_fields` events, `copy_source_refs`, history URLs), contracts items 15–16**. |
| console-UX design (cli-developer; mockups measured vs 78-col) | Delivered the binding mockups now in `plans/topic-first-pivot-console-ux-v1.md`: stage-header grammar with COMPUTED `[n/N]`, topics table with the non-increasing `strn` column as visible sort proof, post roster whose `P` ordinals equal the §1.7 copy-reference labels, provenance block with verbatim receipts, silence-breaker heartbeats (30/90 s), verbosity tiers via `--verbose` + `output.console_verbosity` + `_Session.note()` (run.log/events UNCHANGED by verbosity), menu 7→5 inputs with derived step counters + FR-295 runnability badge. Three brief-premise corrections adopted: 78-col ceiling KEPT (not 100); ONE render stage with per-job wave tags (waves are permit priorities, not global barriers); CHECK is a rollup, not a sequential stage. → **§1.10 + FR-299/FR-300 + the companion doc; expected +250–350 production lines, reported per rule 5**. |
