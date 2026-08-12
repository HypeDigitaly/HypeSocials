# Topic-First Pivot — Pinned Contracts (plan §1.8, items 1–16)

**Written by the conductor before Wave-1 dispatch, derived from the ACTUAL code at commit
`fb28dc2` (baseline 16,356 production lines). Every W1/W2 dispatch prompt quotes its relevant
section. Where this doc and a subagent's instinct disagree, this doc wins; where this doc and a
PRD v2.0.0 disagree, the PRD wins and the conflict is surfaced to the conductor, never silently
resolved.**

Wave discipline (plan §3, arch #1 — ADDITIVE-THEN-SUBTRACTIVE): Wave 1 only ADDS new symbols
beside the old; nothing here licenses deleting or renaming an existing symbol before Wave 3.5.
Items below marked **[W2]**/**[W3]**/**[W3.5]** are pinned NOW so parallel writers cannot
diverge, but land in that later wave.

---

## Item 1 — Post-pivot `build_context(...)` signature  **[W2 — T2.6 implements]**

Current signature: `prompts_engine.py:345-369`. Diff against it:

- **Removed parameters:** `style_brief: StyleBrief | None` (`:348`), `brand_accent: str`
  (`:355`), `brand_product_nouns: Sequence[str]` (`:356` — nouns move to
  `BrandingConfig.profiles.*.product_nouns`, consumed via the branding block),
  `copy_exemplars: Sequence[str]` (`:362`), `reference_image_count: int` (`:361`).
- **Added parameters:** `style: MetaStyle | None = None`, `branding_block: str = ""`,
  `competitor_strings: tuple[str, ...] = ()`, `topic_items: Sequence[TrendItem] = ()`.
- **Kept and promoted:** `content_sentence: str = ""`.
- `engagement_numbers` / `output_format` are NOT parameters — they are engine-derived context
  keys and belong to item 2's removal list only (v2.2 correction).

```python
def build_context(
    *,
    trend: TrendItem | None = None,
    style: MetaStyle | None = None,          # NEW — the assigned meta-style (registry authority)
    copy: CopySet | None = None,
    campaign_brief: Brief | None = None,
    creative_format: str = "",
    niche_descriptor: str = "",
    niche_visual_world: str = "",
    brand_context: str = "",                 # Notion copy-side text — unchanged, dormant
    branding_block: str = "",                # NEW — pre-rendered by prompts_engine._branding_block()
    competitor_strings: tuple[str, ...] = (),# NEW — M6: one _strip_brands() pass over
                                             #   content_sentence / render_prompt / trend_texts /
                                             #   through_line / brief_directives BEFORE they enter
                                             #   the context dict; also fills {{competitor_list}}
    topic_items: Sequence[TrendItem] = (),   # NEW — FILTER call only; engine assigns ordinals 1..N
                                             #   in input order via _topic_items() (never topic_key)
    platform_conventions: Mapping[str, Mapping[str, str]] | None = None,
    text_budgets: TextBudgets | None = None,
    budget_scale: float = 1.0,
    reference_roles: Sequence[str] = (),
    sibling_list: str = "",
    slide_index: str = "",
    slide_text: str = "",
    seed_frame_ref: str = "",
    audio_cue: str = "",
    content_sentence: str = "",
) -> dict[str, str]:
```

Engine-derived context keys sourced from the new parameters:
`render_prompt` (override-brief directives, else `style.render_prompt`), `layout_zones` (from
`style.layout_zones`; a `role: brand_slot` zone emitted only when branded — M11), `style_dna`
(item 12), `exclusions` (`style.exclusions`), `motion_profile` (`style.motion_profile`),
`motion_beat` (`copy.motion_beat`), `branding_block` (verbatim), `topic_items` /
`competitor_list` (built here), `text_budgets` = `_budget_line(min(style.max_onimage_chars,
config budgets))`. `_TRUNCATION_ORDER`: `branding_block` inserted after `niche_visual_world`,
before `content_sentence` (F18). `_onimage_text` gains the conditional wordmark entry (§1.4 B1):
`wordmark (render verbatim): "<profiles[brand].wordmark>"` + `_spell()` aid, emitted only when
the entry is branded.

## Item 2 — Full post-pivot `PLACEHOLDERS` diff  **[W2 conductor micro-pass on models.py]**

Current set: `models.py:509-543` (26 names). Diff:

- **Removed (the six):** `style_brief_summary`, `inspiration_exemplars`, `brand_accent`,
  `engagement_numbers`, `reference_image_count`, `output_format`.
- **Added (the five):** `branding_block`, `topic_items`, `competitor_list`, `motion_profile`,
  `motion_beat`.

Final vocabulary (25 names):
`render_prompt, layout_zones, onimage_text, exclusions, style_dna, slide_index, seed_frame_ref,
audio_cue, sibling_list, source_hooks, platform_conventions, brand_context, trend_texts,
niche_descriptor, brief_directives, content_sentence, text_budgets, through_line,
reference_roles, niche_visual_world, branding_block, topic_items, competitor_list,
motion_profile, motion_beat`.

`source_hooks` is RE-PURPOSED, not renamed: post-pivot its builder emits the §1.7 numbered
candidate list (labels per item 10's grammar), so the copywriter's offerable strings need no new
placeholder. Removal timing: additions land in the W2 conductor micro-pass in lockstep with the
allowlist (B1/B2); the six removals happen at W3.5.

## Item 3 — Per-role `_ALLOWLIST` table (final, post-W3.5)  **[W2 — T2.6; deletions W3.5]**

Derived from `prompts_engine.py:96-133`. The merged `image_post.md` allowlist is the **UNION**
of `image_single_post.md`'s and `image_direct.md`'s (F16 — image_direct deliberately omits
`layout_zones`/`exclusions` today; the widening is a stated decision), −`brand_accent`
+`branding_block` +`content_sentence`:

| role | frozenset |
|---|---|
| `copywriter_system.md` | `{niche_descriptor, brand_context, trend_texts, source_hooks, sibling_list, text_budgets, platform_conventions, brief_directives}` (−`style_brief_summary`, −`inspiration_exemplars`) |
| `vision_check_question.md` | `frozenset()` (unchanged) |
| `topic_filter_system.md` **(NEW, global)** | `{topic_items, competitor_list}` — allowlisted HERE AND NOWHERE ELSE |
| `image_post.md` **(NEW, merged)** | `{render_prompt, layout_zones, onimage_text, reference_roles, exclusions, text_budgets, brief_directives, niche_visual_world, content_sentence, branding_block}` |
| `carousel_slide.md` | `{slide_index, style_dna, render_prompt, onimage_text, reference_roles, exclusions, text_budgets, brief_directives, niche_visual_world, branding_block}` |
| `carousel_anchor_instruction.md` | `frozenset()` (unchanged) |
| `reel_seed_frame.md` | `{render_prompt, layout_zones, onimage_text, reference_roles, exclusions, text_budgets, brief_directives, niche_visual_world, branding_block}` |
| `reel_director.md` | `{through_line, seed_frame_ref, onimage_text, audio_cue, exclusions, brief_directives, motion_beat, motion_profile}` — NO `branding_block` (§1.4: gpt-image-2 render roles only; the M13 wordmark continuity travels inside `onimage_text`) |

Deleted at W3.5: `style_brief_system.md`, `image_single_post.md`, `image_direct.md` rows.
`prompts/README.md` is the co-maintained allowlist spec and updates with every change (T2.5).

## Item 4 — Template registries: the REAL surfaces (B2)

Load-bearing registries, verified: `prompts_engine._ALLOWLIST` (`:96`),
`prompts_engine._BUILT_INS` (`:885`), `models.PROFILE_TEMPLATES` (`models.py:495-501` — drives
`_TEMPLATES_BY_KIND` at `prompts_engine.py:137-140` + FR-263 profile validation), and
`tests/test_template_parity.py`'s hardcoded surfaces (`SHIPPED` at `:33`, `len(SHIPPED) == 9`
at `:53`, built-ins parity `:60`). `models.GLOBAL_TEMPLATES` (`:488-490`) has ZERO consumers —
decorative, updated for hygiene only.

Transition: W2 conductor micro-pass adds `image_post.md` to `PROFILE_TEMPLATES["gpt-image-2"]`
and `topic_filter_system.md` to the global surfaces (old templates still on disk) →
**transitional SHIPPED count 11** at the W2/W3 barriers, set by T2.7. W3.5 removes the three
dead templates from every surface → final count **8** (3 global + 4 gpt-image-2 + 1 seedance).

## Item 5 — `hypesocials/styles.py` public API  **[W1 — T1.2 writes it, T1.3 tests it]**

`MetaStyle` and `LayoutZone.role` live in **models.py** (T1.1); styles.py imports them.

```python
# models.py (T1.1, additive)
@dataclass(slots=True)
class MetaStyle:
    """One meta-style registry entry (§1.3) — the post-pivot visual authority."""
    key: str
    render_prompt: str = ""              # <=120 words, executable, no unresolved variants (M9)
    subject_mode: str = "scene_open"     # "scene_fixed" | "scene_open" (B2)
    layout_zones: list[LayoutZone] = field(default_factory=list)
    format_affinity: list[str] = field(default_factory=list)  # ⊆ {image, carousel, reel}, non-empty
    brand_affinity: list[str] = field(default_factory=list)   # [] = brand-neutral (B3)
    brand_slot: bool = False             # "this style IS a brand" — data-driven, never key-matched
    text_density: str = "minimal"        # minimal | moderate | high
    max_onimage_chars: dict[str, int] = field(default_factory=dict)  # keys: headline/subline/slide
    motion_profile: str = "photographic" # photographic | graphic (F24)
    palette: list[str] = field(default_factory=list)   # --- the five DNA fields (FR-189) ---
    typography: str = ""
    text_placement: str = ""
    image_treatment: str = ""
    visual_pacing: str = ""
    per_format_guidance: dict[str, str] = field(default_factory=dict)  # see reserved keys below
    exclusions: list[str] = field(default_factory=list)  # LITERAL strings from the reference files (M8)
    reference_images: list[str] = field(default_factory=list)  # REPO-ROOT-relative paths (§1.3)
```

**`per_format_guidance` reserved keys (conductor decision — the §1.3 anchor-marker mechanism
made concrete):** free prose under `carousel_cover` / `carousel_slide` (M9 variant-resolution
home), plus one marker key `carousel_role` with value `"cover_only"` or `"slides_only"`.
`fmt_affine(style, "carousel")` is True iff `"carousel" in style.format_affinity` AND
`style.per_format_guidance.get("carousel_role") != "slides_only"` — a slides-only style
(meme-caricature, ugc-tabletop) can never anchor a deck, and under anchor-chaining that means it
is never assigned to a carousel entry at all. For `"image"`/`"reel"` the check is plain
membership.

```python
# styles.py — public API (module __init__ discipline: callers import hypesocials.styles only)
class StyleRegistryError(Exception):
    """Missing/unparseable registry or fatally invalid entry — FR-295 exit-2 material.
    str(e) is the whole operator-facing line."""

@dataclass(slots=True)
class StyleRegistry:
    version: int
    styles: list[MetaStyle]              # stable file order — rotation depends on it
    origin: str                          # resolved path (FR-184 attribution extends to the registry)
    content_hash: str                    # sha256[:12], same recipe as prompts_engine._hash

def load_registry(dirs: Sequence[Path | str]) -> StyleRegistry
    # Resolves `styles.yaml` override-first through the FR-174 seam: first hit in `dirs` wins
    # (callers pass (config.prompts_dir?, PROMPTS_DIR)). NO built-in third tier (§1.3 decision):
    # not found anywhere / unreadable / invalid YAML / not a mapping → StyleRegistryError.
    # Normalizes each entry into a MetaStyle; a non-list `styles:` is an error.

def validate(reg: StyleRegistry, config: Config) -> tuple[list[str], list[str]]
    # -> (errors, warnings). FR-295: any error = pre-flight exit 2.
    # Errors: 0 styles usable under config.branding.brand; duplicate key; empty render_prompt;
    #   format_affinity empty or ⊄ {image,carousel,reel}; brand_affinity ⊄ {hypedigitaly,hypelead};
    #   any format with run.formats[fmt] > 0 having no fmt_affine style under the active brand
    #   (this also catches "brand filter emptied the pool", B3).
    # Warnings: <3 usable styles; render_prompt >120 words; variant-leak heuristic (" or ",
    #   "Variant ", "either " in render_prompt); reference_images entry missing/failing the
    #   magic-byte check (style degrades to text-only, tag style_refs_missing — never an error).

def assign_styles(entries: Sequence[PlanEntry], registry: StyleRegistry, brand: str) -> None
    # Mutates entry.style_key. Stateless order-indexed scan — EXECUTABLE PSEUDOCODE, verbatim
    # from plan §1.3 (T1.2 and T1.3 run in parallel and must not diverge):
    #
    #   pool = [s for s in registry if brand_ok(s)]           # stable registry order
    #   for entry in sorted(live, key=lambda e: e.order):
    #       for step in range(len(pool)):
    #           cand = pool[(entry.order + step) % len(pool)]
    #           if fmt_affine(cand, entry.creative_format): break
    #       entry.style_key = cand.key
    #
    # brand_ok(s) = not s.brand_affinity or brand in s.brand_affinity.
    # NO shared cursor: each pick is a pure function of entry.order over the brand-filtered pool,
    # so a dropped/trimmed entry never reshuffles any other pick. entry.order is assigned once at
    # plan build (plan.py:220-221) and is GAPPED over live entries after trims/drops — the scan is
    # defined over the order VALUE, so gaps are harmless by construction. Exhausted scan with no
    # fmt-affine hit assigns the last scanned candidate (defensive only — validate() makes a
    # requested format with zero affine styles a pre-flight exit 2, so this is unreachable live).
    # Empty pool → StyleRegistryError (same unreachability argument).

def assign_branding(entries: Sequence[PlanEntry], ratio: float) -> None
    # Mutates entry.branded. Entry is branded iff
    #   math.floor((order + 1) * ratio) > math.floor(order * ratio)
    # over entry.order — deterministic, supply-independent. Exact count over the FULL emitted
    # plan is floor(N * ratio), NEVER round (v2.2: N=7/r=0.5 → 3; N=3/r=0.3 → 0). Over the live
    # subset after trims the branded count is simply the surviving orders satisfying the
    # predicate — a trim never re-brands a surviving creative.

def style_for(reg: StyleRegistry, key: str) -> MetaStyle
    # Exact-key lookup; unknown key raises StyleRegistryError naming the key and the origin file.

def pick_reference_window(style: MetaStyle, reuse_index: int, refs_per_job: int) -> list[Path]
    # The A17 window rotation, re-homed: resolve style.reference_images against the REPO ROOT
    # (config.ROOT — §1.3 decision: the registry lists paths in two unrelated trees), drop
    # entries failing _usable() (suffix + size + magic bytes, ported from inspiration.py:55-71 +
    # :255-266), then rotate: with usable list U and w = min(refs_per_job, len(U)), return
    # [U[(reuse_index + j) % len(U)] for j in range(w)]. len(U) <= w returns U whole.
    # Deterministic; meaningful for styles with >2 images (hypelead-brand-card has 5).

# Run-scoped upload memo (24 h Kie retention → same-run reuse only, FR-200/244):
#   UploadMemo = dict[Path, str]        # local path -> Kie URL, created once per run
# styles.py OWNS the type and the discipline statement; generate/refs.py performs the uploads
# and consults/fills the memo (W2 — T2.3). One upload per file per run, asserted by T4.1.
```

Module split (§1.4, arch #13, decided): styles.py owns *assignment* (`assign_styles`,
`assign_branding`); prompts_engine owns *rendering* (`_branding_block()`, the `_onimage_text`
wordmark entry) — prompts_engine's no-filesystem contract holds; styles.py does the file I/O.

## Item 6 — `hypesocials/topic_filter.py` public API  **[W1 — T1.2 writes it, T1.3 tests it]**

```python
@dataclass(slots=True)
class Verdict:
    """One topic's screen verdict, keyed by ENGINE-ASSIGNED ordinal (§1.5 — never topic_key:
    a crafted topic name must not be able to spoof another topic's verdict)."""
    ordinal: int                          # 1-based, input order
    verdict: str = "keep"                 # "keep" | "strip" | "skip"
    brands_to_strip: list[str] = field(default_factory=list)  # post-guard survivors only
    reason: str = ""

async def screen(topics: Sequence[TrendItem], cfg: Config, llm: StructuredCall | None
                 ) -> dict[int, Verdict]
    # ONE batched, text-only classify call (role "copy"/Luna; template topic_filter_system.md).
    # Returns exactly one Verdict per input topic, keys 1..len(topics) — ALWAYS total: a missing/
    # duplicate/out-of-range ordinal in the LLM answer is logged and that ordinal defaults to
    # keep. Two layers:
    #   1. Deterministic blocklist (cfg.branding.competitors, FAIL-CLOSED): a topic whose name or
    #      candidate texts carry a blocklisted brand gets verdict "strip" with that brand listed
    #      (or the LLM's stronger "skip" wins) — applied even when the LLM layer degrades.
    #   2. LLM layer (FAIL-OPEN): llm is None / call fails / unparseable → every non-blocklist
    #      verdict stays "keep" and every returned Verdict.reason = "filter_degraded: <cause>";
    #      the CALLER (runner._screen_topics) turns that marker into the one filter_degraded
    #      warning. Filter failure must never couple to copy failure (§1.5).
    # M15 strip guards, applied to the LLM's brands_to_strip BEFORE the Verdict is returned
    # (fail-safe: a rejected entry is logged and DROPPED, the verdict itself stands, and a strip
    # verdict whose list empties degrades to keep):
    #   reject when the brand string appears in the topic's `name`; is < 3 chars; is a stopword
    #   (module-internal _STOPWORDS); matches cfg.branding's active-profile product_nouns
    #   (case-insensitive); or word-boundary-removing it from any candidate string would leave
    #   that string < 15 chars. Cap: first 5 survivors per topic.
    #
    # W1 SCOPE NOTE (v2.2, binding): the prompt-render path (build_context(topic_items=...) →
    # engine.render("topic_filter_system.md", ...)) is WRITTEN TO THIS CONTRACT but cannot
    # execute until the W2 placeholder/allowlist micro-pass — two independent W1 guards reject it
    # (PLACEHOLDERS membership check prompts_engine.py:446-449, and the missing _ALLOWLIST key).
    # T1.2 ships it behind the llm-layer seam so W1 tests exercise ordinals/guards/blocklist/
    # degrade WITHOUT rendering the template; its first end-to-end test is T2.7's.

def apply_blocklist(text: str, competitors: Sequence[str]) -> str
    # Deterministic, word-boundary, case-insensitive removal of each competitor string from
    # `text`; collapses the whitespace a removal leaves behind. Pure and synchronous — reused by
    # copywrite's verifier and by --preview-sources' $0 verdict display (W2/W3).
```

LLM answer schema (engine-side, per §1.5): `{"verdicts": [{"ordinal": int, "verdict":
"keep"|"strip"|"skip", "brands_to_strip": [str], "reason": str}]}` — hand-built dict in
topic_filter (no models.py dataclass; the wire shape is this module's own).

## Item 7 — `DegradationTag` exhaustive diff  **[W1 — T1.1 adds; W3.5 deletes]**

- **Added (T1.1, W1):** `COPY_NOT_VERBATIM = "copy_not_verbatim"` (verifier deviation — never
  fails the creative), `COMPETITOR_STRIPPED = "competitor_stripped"` (a strip was applied),
  `STYLE_REFS_MISSING = "style_refs_missing"` (style degraded to text-only).
- **Kept, redefined (comment updated at W2, T2.2):** `NO_ONIMAGE_TEXT` — "no source string fits
  this style's on-image budget — caption-only creative".
- **Kept, semantics restated:** `COPY_DEGRADED` — `_fallback_copy` ships the top post's caption
  verbatim + no on-image text; **stays in `llm_starved` → exit 1** (explicit decision: a failed
  copy call is still a loss to surface).
- **Deleted at W3.5:** `ANALYSIS_MISSING` (`models.py:31`), `HOOK_PATTERN_GENERIC` (`:44`).
- Conductor note for the W3.5 session: the five motion-chain tags (`PROBE_FAILED`,
  `NO_QUALIFYING_VIDEO`, `DOWNLOAD_FAILED`, `UPLOAD_FAILED`, `MALFORMED_METADATA`,
  `models.py:55-59`) lose their last emitter when `video_ref.py` dies; the plan's W3.5 list does
  not name them — resolve there, not in W1/W2.

## Item 8 — `AssetRecord.ref_source` vocabulary  **[W2 — T2.3/conductor]**

Currently `"virlo" | "brief" | "inspiration"` (`models.py:286`). Post-pivot: **`"style" |
"brief"`**. `generate._ref_source()` (`generate/__init__.py:579-588`) re-based in the W2
conductor wire-in alongside the Env `local_refs` kind change (item 11).

## Item 9 — `runner._screen_topics` exact signature  **[W3 — conductor writes it]**

```python
async def _screen_topics(session: _Session, trends: Sequence[TrendItem]
                         ) -> dict[int, topic_filter.Verdict]
```

Named helper so previews reuse the IDENTICAL path (arch #4). Placement: between `_collect` and
`_select`, post-Confirm (metered; `_configure_llm` ALREADY runs before Collect —
`runner.py:470` — so only the previews path needs the $0 discipline, no runner move). It wraps
`topic_filter.screen(trends, session.config, llm)`, emits the `topic_filter_verdict` events
(FR-298), prints the FILTER stage lines (FR-296), and surfaces the single `filter_degraded`
warning when the Verdicts carry the degrade marker.

## Item 10 — `CopySelection` schema  **[W1 — T1.1 adds the dataclass]**

Reference-selection contract (§1.7): the engine numbers offerable source strings, the LLM
returns REFS, the engine resolves refs to bytes (verbatim cannot fail).

```python
# models.py (T1.1, additive)
@dataclass(slots=True)
class CopySelection:
    """The copy call's per-creative answer under the §1.7 verbatim contract: references into the
    engine-numbered candidate list where the text becomes pixels or caption, free text only
    where nothing does. Feeds json_schema_for(CopySelection, exclude={"asset_id"})."""
    asset_id: str
    headline_ref: str = ""                # ref label or "" = nothing fits (NO_ONIMAGE_TEXT path)
    subline_ref: str = ""
    overlay_ref: str = ""                 # reel seed-frame hook
    slide_refs: list[str] = field(default_factory=list)   # carousel, one label per slide
    caption_ref: str = ""
    through_line: str = ""                # free text — never pixels
    narrative_arc: str = ""               # free text — carousel arc
    motion_beat: str = ""                 # free text — ONE named physical action, reel Stage 2 (F24)
```

**Ref label grammar (pinned — FR-298's `copy_source_refs` and the FR-297 roster reuse it
verbatim):** `P<n>.<kind>[.<i>]` where `n` = 1-based post ordinal in the topic's view-ranked
`posts` list, `kind` ∈ `{hook, overlay, panel, caption, description}`, `i` = 1-based index into
that post's list-typed field (`hooks`/`text_overlays`/`panel_texts`); `caption` and
`description` are scalar fields and carry NO index. Examples: `P1.hook.2`, `P3.panel.1`,
`P2.caption`.

`CopySet` stays the resolved-bytes shape and **gains `motion_beat: str = ""` in the W2 conductor
micro-pass** (models.py is conductor-owned after W1; NOT added in W1 because `copywrite` builds
its call schema from the copy shape and W1 must not disturb the live schema — the LayoutZone
proviso (§3 (c)) was verified harmless for the style-brief schema only). `hook_pattern_used`
dies at W3.5 (A21).

## Item 11 — Post-pivot `generate.Env` field diff  **[W2 — conductor wire-in]**

Current: `generate/__init__.py:119-170`. Diff:

- **Removed:** `style_briefs` (`:130`), `brand_accent` (`:141`), `brand_product_nouns` (`:142`),
  `video_refs` (`:146`) — and `Env.brief_for()` (`:152-163`) dies with `style_briefs`.
- **Changed:** `local_refs` kind vocabulary `{"brief", "inspiration"}` → `{"style", "brief"}`
  (`:137-139` comment re-based; item 8 pairs with it).
- **Added:**
  ```python
  styles: Any = None                      # styles.StyleRegistry — Any avoids the import cycle
                                          #   (styles.py imports models only; generate imports it
                                          #   lazily like video_refs does today), or import it
                                          #   directly if no cycle arises — implementer's call,
                                          #   stated in the module docstring.
  branding: BrandingConfig = field(default_factory=BrandingConfig)   # from hypesocials.config
  ```
- `_assemble`'s `build_context` call updated to item 1's signature; `_ref_source` vocabulary per
  item 8.

## Item 12 — `style_dna(...)` new signature  **[W2 — T2.6 implements; T2.3 consumes]**

Currently `style_dna(brief: StyleBrief | None) -> str` at `prompts_engine.py:453`; imported by
`generate/carousel.py:57`. Post-pivot:

```python
def style_dna(style: MetaStyle | None) -> str
```

Rows are the FIVE DNA fields only — `palette` (joined ", "), `typography`, `text_placement`,
`image_treatment`, `visual_pacing` — same `"\n  ".join(f"{label}: {value}")` shape, empty rows
dropped, `None` → `""`. The current `layout_grid` row (derived from zones) DIES: layout zones
travel in `{{layout_zones}}` alone. Byte-identical across a deck remains the contract (M9).

## Item 13 — The style-forecast helper  **[W3 — conductor writes it LAST in the wave]**

Replaces `runner._record_render_forecast` (`runner.py:1025-1049`; previews.py imports it at
`:60`).

```python
def _record_style_forecast(session: _Session, live: Sequence[PlanEntry],
                           registry: Any, *, dropped: int) -> None
    # registry: styles.StyleRegistry | None. Per live entry: window size =
    # min(len(usable reference_images of its assigned style), config.styles.refs_per_job)
    # (0 under an override brief — M14). Feeds Counters.record_render's re-based shape
    # (item 15): jobs, dropped, per-creative style-ref counts, styles_used =
    # len({entry.style_key for entry in live}).
```

T3.1 must swap previews.py's import to this name in the SAME wave the conductor lands it.

## Item 14 — `copy_source_post_id` + `copy_source_refs` + the history-record shape

- **AssetRecord/meta.yaml (W2 conductor micro-pass adds the fields; T2.2 populates):**
  `copy_source_post_id: str = ""` (which `SourcePost` this creative quoted) and
  `copy_source_refs: dict[str, str] = {}` — `{slot: ref-label}` per item 10's grammar, e.g.
  `{"headline": "P1.hook.2", "caption": "P1.caption"}` (FR-298: records WHICH STRING, not just
  which post). Slot names = the CopySet field the ref resolved into (`headline`, `subline`,
  `overlay_text`, `slide_texts[k]` → `slide_1`…`slide_N`, `caption`).
- **History record (state.py, T3.2):** entry key = `history_key` = `"<mid>::<topic_key>"`
  (§1.6 — migration: pre-pivot entries stop matching, first post-pivot run sees an empty window
  by design, old entries age out via `_prune`, no migration pass). Entry shape (current:
  `state.py:147-155`):
  ```json
  {"first_used": "<ISO>", "last_used": "<ISO>", "run_ids": ["..."],
   "posts": {"<post_id>": {"date": "<ISO>", "url": "<permalink>"}}}
  ```
  `posts` values change from bare date strings to `{date, url}` mappings (FR-153 amendment).
  `_fresh_posts` must accept BOTH shapes (a string is a `{date: <it>, url: ""}`) — old entries
  age out rather than crash. `runner._posts_used` (`runner.py:783-803`) is rewritten in W3 to
  produce `(post_id, url)` pairs from `SourcePost`; W5 asserts the field names.

## Item 15 — Post-pivot `Counters` field table (v2.3)  **[W2 — T2.1 + conductor]**

Base: `sources/virlo.py:107-243`. Two-level `absorb()` seam discipline KEPT (`:196-213`): a
per-monitor tally is built privately and absorbed once — no double-counting one monitor's rows
across its topics.

| group | fields | fate |
|---|---|---|
| the ask | `monitors_asked, monitors_failed, rows_per_call, total_available` | KEEP; `total_available` promoted into the console funnel header (FR-297d); `download_cap/min_panels/min_frames` die W3.5 |
| input | `videos_raw, slideshows_raw, videos_kept, slideshows_kept` | KEEP per monitor; **+`duplicates_dropped`** (explicit field = raw − kept fold, per v2.3) |
| topics **(NEW)** | `posts_in, topics_out` per monitor; `add_topics(*, posts_in, topics_out)` | NEW — the wire-in registry names `add_topics` |
| filter **(NEW)** | `filter_kept, filter_stripped, filter_skipped, filter_degraded: bool`; `record_filter(verdicts)` | NEW — the wire-in registry names `record_filter` |
| sets / choice / images | `slideshow_sets, frame_sets, last_resort_sets, slideshows_thin, families_thin, videos_in_sets, videos_in_thin_families, videos_without_thumbnail, rejection_reasons, chosen_*, motion_tiers, images_*, trends_text_only, trends_short` | DIE at W3.5 (media funnel is dead); untouched in W1/W2 code paths that stop being called |
| returned | `trends_returned` | KEEP (now counts topic items) |
| Select verdicts | `verdict_seen, eligible, excluded_by_history, unusable` | KEEP (recorded by `runner._select`) |
| render forecast | `render_seen, jobs, jobs_dropped, refs_total` | KEEP; `trends_used` → `topics_used`, `trend_refs_min/max` → `style_refs_min/max`, `inspiration_each` dies — re-based with item 13 at W3 |

## Item 16 — `_Session.note()` seam + heartbeat parameters (v2.3)  **[W3 — conductor]**

House rules (verified): `session.say()` (`runner.py:150-152`) writes identical bytes to console
AND run.log; NO spinners, NO `\r`, NO ANSI; FR-286's 78-col ceiling KEPT; safe glyphs = the
`util.fit` set (`·`, `—`, `…`, `←`) + `->` (the `→` glyph is FORBIDDEN per FR-155).

```python
def note(self, text: str) -> None:
    # run.log ALWAYS (via self.log.narrative/redaction boundary), console ONLY when
    # config.output.console_verbosity == "verbose" or opts.verbose. (~5 lines.)
```

New config key `output.console_verbosity: Literal["normal", "verbose"] = "normal"` (sibling of
`log_verbosity`) + `--verbose`/`-v` flag land in W3 (T3.3) — NOT in W1's T1.1 scope.
run.log and events.jsonl are UNCHANGED by verbosity; only the console tier moves.

Heartbeats are **silence-breakers, not tickers**: print only when nothing has printed for
`heartbeat_s` — 30 s interactive / 90 s `--yes` / 15 s verbose; first heartbeat suppressed 10 s
(LLM waits) / 20 s (render waits); ANY printed line resets the timer. Render hook = the existing
`_drain` loop (`generate/__init__.py:232-236`) + one `last_printed` monotonic stamp.

Stage-header grammar (FR-296, quoted from §1.10 — binding for T3.x and T3.6's assertions):
`[n/N] STAGE  in -> out  elapsed`, N COMPUTED from the resolved plan; stage order
COLLECT → TOPICS → FILTER → SELECT → ASSIGN → COPY → RENDER → CHECK → DONE; stages with waits
print the header twice (opening `...` form, closing form with elapsed). Topics table columns
(FR-297a): `rk · topic(22) · mon · posts · views · median · strn · verdict`, compact numbers
(`12.4M`), ≤78 cols, 2-line caption stating the strength formula and the own-posts/min-max
basis. Post roster line (FR-297b): `P1 @author 4.9M 2d <post_id> slideshow -> 01` — the `P`
ordinals ARE item 10's labels; permalink alone on its own line.

---

## W1 addendum — exact T1.1 scope (conductor-resolved, binding for the wave)

**models.py (additive only; NO PLACEHOLDERS/PROFILE_TEMPLATES/GLOBAL_TEMPLATES edits — W2):**
1. `LayoutZone.role: str = ""` (last field; §1.3 — `brand_slot` marks the signature zone).
   Accepted side effect (§3 proviso (c), verified): `role` becomes a required key in the
   still-live FR-92 schema; `test_prompts_engine.py:378-384` asserts top-level fields only.
2. `MetaStyle` per item 5, placed after `LayoutZone`.
3. `SourcePost` per §1.6 + two conductor additions grounded in FR-297b (the roster needs per-post
   age and type):
   ```python
   @dataclass(slots=True)
   class SourcePost:
       """One winning post inside a topic item — the unit verbatim copy quotes (§1.6/FR-293)."""
       post_id: str
       url: str = ""
       author: str = ""
       caption: str = ""
       hooks: list[str] = field(default_factory=list)
       text_overlays: list[str] = field(default_factory=list)   # absorbs text_overlay_contents
       panel_texts: list[str] = field(default_factory=list)
       description: str = ""
       views: int = 0
       published_at: datetime | None = None    # conductor addition — FR-297 roster age column
       is_slideshow: bool = False              # conductor addition — roster type tag; majority
                                               #   over posts re-derives TrendItem.is_slideshow
   ```
4. `TrendItem` gains `topic_key: str = ""` and `posts: list[SourcePost] =
   field(default_factory=list)` (conductor decision: §1.6's additions must land while models.py
   still has a wave writer; additive, defaults keep every constructor valid).
5. `PlanEntry` gains `style_key: str = ""`, `branded: bool = False`, `topic_key: str = ""`.
6. `DegradationTag` += the three tags per item 7 (placed after `NO_ONIMAGE_TEXT`, FR-referenced
   comments in the enum's style).
7. `CopySelection` per item 10 (near `CopySet`). Do NOT touch `CopySet`.

**config.py (additive only; old keys STAY silently — no deprecation plumbing, `config.py:563`
warns on UNKNOWN keys only and none is added):**
1. `BrandProfile` + `BrandingConfig` dataclasses; `Config.branding: BrandingConfig` field.
   ```python
   @dataclass(slots=True)
   class BrandProfile:
       wordmark: str = ""
       colors: dict[str, Any] = field(default_factory=dict)     # hexes and one gradient list
       fonts: dict[str, str] = field(default_factory=dict)
       font_character: str = ""
       background_hint: str = ""
       never_always: list[str] = field(default_factory=list)    # color guards — every branded prompt
       never_style: list[str] = field(default_factory=list)     # medium guards — brand-affine styles only
       product_nouns: list[str] = field(default_factory=list)

   @dataclass(slots=True)
   class BrandingConfig:
       brand: Literal["hypedigitaly", "hypelead"] = "hypedigitaly"
       brand_ratio: float = 0.5
       mode: Literal["background_tint", "overlay", "both"] = "overlay"
       placement: str = "bottom-center"
       competitors: list[str] = field(default_factory=list)
       profiles: dict[str, BrandProfile] = field(default_factory=_default_profiles)
   ```
   `_default_profiles()` compiles the §1.4 YAML verbatim — BOTH profiles, all fields, including
   `never_always`/`never_style` exactly as quoted there; orange `#F97316` ships in NEITHER.
2. `StylesConfig` with `refs_per_job: int = 2`; `Config.styles: StylesConfig` field.
3. `SourcesConfig.virlo_topics_per_monitor: int = 9`.
4. `_BOUNDS` += `"branding.brand_ratio": (0.0, 1.0, "a ratio between 0 and 1")`,
   `"styles.refs_per_job": (1, 16, "a whole number of references per job, 1–16")`,
   `"sources.virlo_topics_per_monitor": (-1, 50, "a whole number of topics per monitor, 1–50,
   or -1 (one topic per monitor)")` — plus a `_validate` line failing `0` explicitly.
5. `_validate` += hex-format check on every `colors` value that is a string (regex
   `^#[0-9A-Fa-f]{6}$`; a list value is checked element-wise), and `branding.brand` must have a
   matching key in `profiles`.
6. `__all__` += `BrandProfile`, `BrandingConfig`, `StylesConfig`.

**Deliberately NOT in W1:** `output.console_verbosity` (item 16 — W3/T3.3), `CopySet.motion_beat`
(item 10 — W2 micro-pass), any TrendItem/config key REMOVAL, PLACEHOLDERS/PROFILE_TEMPLATES/
GLOBAL_TEMPLATES/`_ALLOWLIST` edits (W2 micro-pass), AssetRecord fields (W2 micro-pass).
