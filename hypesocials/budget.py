"""Budget — the run's one money module: what it will cost, what may be spent, what it did cost.

Public API: `estimate(config, entries, post_languages=None)` (10 FR-107, 30 NFR-18/FR-282;
D63's optional `post_id -> language` mapping only sharpens FR-343's translate line and is absent
on every pre-Collect caller) · `job_projection(config,
entry, job)` (the expected cost of ONE submission) · `trim(config, entries, cap_usd)`
(FR-28/FR-106) · `Budget(cap_usd)` with `fits`/`commit`/`reserve`/`release`/`reconcile`/`summary`
(FR-106 a/b/c, FR-84/85) · `critic_price_gap(config)` (pre-flight's "can the gauntlet be priced at
all", FR-326) · `format_usd`.

Invariants:
- **No network, no clock.** The estimate is config arithmetic only, so it appears before any
  external service is contacted (NFR-18).
- **Cap comparisons happen in integer micro-USD.** Floats are the boundary format (config prices,
  `RenderOutcome.cost_usd`, `PlanEntry.estimated_cost_usd`); inside, amounts convert once through
  `_micros()` so "does it fit" is exact and two identical runs decide identically. Display rounds
  half-up to cents exactly once, in `format_usd` (guidelines §7 Money).
- **An unset or zero rate is never treated as free.** That line prints *unpriced*, contributes $0
  to projection, tally and trim math, and raises the governance banner (FR-107/FR-282). Reels are
  the one blocking case: while `price_per_unit.reel_second.<resolution>` is unset the estimate
  refuses to plan them and names that exact key rather than guessing (FR-131).
- **Reserve-then-submit, never check-then-submit** (FR-106c), and **spend tallies on submission**:
  a reservation whose job reached the provider counts even if the job then fails; only a
  submission that never happened is `release()`d (20 §8).
- **Trimming removes whole atomic groups from the END of the plan** (FR-106) — a carousel is one
  unit and is never split (the A/B pair was the other such unit; A/B mode is withdrawn, v2.0.0).

Do not: invent a missing price, call a provider, or re-derive a per-unit price elsewhere. `trim()`
is the only function here that mutates plan entries, and its docstring says so.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any, Literal

from hypesocials.config import Config
from hypesocials.models import PlanEntry, PlanEntryStatus
from hypesocials.render.profiles import effective_image_tier

# Token-model constants: how the ENGINE uses the models (FR-105 sizes, shipped template shapes),
# not operator knobs — the cost levers are `max_tokens.*` and `reasoning_effort` (30 §2).
_CHARS_PER_TOKEN = 4  # Notion brand context is char-budgeted (FR-124)
#: Long edge assumed when `platforms.<name>.image_resolution` names a tier the price table has no
#: entry for. 1024 is `render/profiles.py`'s own default tier, so the image-token arithmetic below
#: an unpriced line still describes the picture the engine would actually have sent.
_DEFAULT_LONG_EDGE_PX = 1024
_COPY_PROMPT_TOKENS = 600  # copywriter_system.md + trend context (50 §5)
_COPY_TOKENS_PER_SIBLING = 120  # FR-99's per-sibling brief inside the grouped call
#: FR-294's batched topic screen (one call for the whole candidate pool, role `copy`/Luna).
#: `topic_filter_system.md`'s fence + instruction block, then one numbered block per topic (name,
#: hooks, panel texts) and one verdict object back ({ordinal, verdict, brands_to_strip, reason}).
_FILTER_PROMPT_TOKENS = 400
_FILTER_TOKENS_PER_TOPIC = 120
_FILTER_VERDICT_TOKENS = 60
#: FR-306's slide-intelligence pass (D46 §0.11), role `analysis`: `slide_intel_question.md` plus
#: the fixed carrier turn the slide images ride on, then one answer object per slide
#: (`onimage_text` verbatim + an English `visual_brief` + `brand_marks`).
_SLIDE_INTEL_PROMPT_TOKENS = 400
_SLIDE_INTEL_COMPLETION_PER_SLIDE = 220
#: Source slides arrive at whatever size the poster published them at — we do not render them, so
#: there is no configured tier to read. They are therefore priced at the provider's own token
#: ceiling in the squarest shape, which is the MOST one attached image can cost: over-stating is
#: the safe direction (D11), and understating is the one unacceptable estimator error.
_SOURCE_SLIDE_RATIO = "1:1"
#: FR-334's ONE batched style-match call (D56 §5), role `analysis`. Sized against the real
#: artifacts rather than guessed, and the arithmetic is written down because a constant nobody can
#: explain rots:
#: - the FIXED side is `prompts/style_match_system.md`, measured at 8,817 chars on 2026-08-20 ->
#:   ~2,204 tokens at `_CHARS_PER_TOKEN`. The hand-built answer schema and the chat scaffolding
#:   ride on top of it, so the constant quotes 2,400.
#: - one CANDIDATE block per style in the run's pool: the key plus its authored `match_profile`
#:   (the 1-2 sentences FR-290 requires) plus the formats it declares — ~230 chars, ~58 tokens,
#:   quoted at 60.
#: - one SECTION per styled creative: its asset_id and format, ITS OWN candidate key list (the
#:   pool is filtered per format and per brand, so the keys repeat inside every section — up to
#:   12 keys at ~9 tokens each under the shipped configs), the deck/panel counts, the four text
#:   lengths and Virlo's own hook/visual-hook/tone classifications. ~200 tokens.
#: - one ANSWER row per creative: asset_id, style_key, `fit`, a ~12-word `reason`,
#:   `wanted_archetype` and the JSON around them — ~70 tokens.
#: Over-stating is the safe direction (D11); understating is the one unacceptable estimator
#: error, so these four numbers only ever move against a measurement.
_STYLE_MATCH_PROMPT_TOKENS = 2400
_STYLE_MATCH_TOKENS_PER_CANDIDATE = 60
_STYLE_MATCH_TOKENS_PER_ENTRY = 200
_STYLE_MATCH_COMPLETION_PER_ENTRY = 70
#: How many candidates to quote when `styles.enabled` is empty — which means "every style in the
#: registry" (30 §2), not "no styles at all". This module does NO I/O (the estimate is config
#: arithmetic only, NFR-18), so it never opens `prompts/styles.yaml` and the registry's real size
#: is not knowable here. The shipped registry holds 19 entries (v2.4.0/D56); quoting 24 leaves
#: room for a registry that grew since this line was typed, rather than silently under-quoting it.
_STYLE_MATCH_ASSUMED_POOL = 24
#: FR-351's cover pick (D62 §2), role `analysis` and one call per chained carousel. The arithmetic
#: is written down for the same reason the style matcher's is — a constant nobody can explain rots:
#: - the FIXED side is `prompts/cover_pick_system.md`, which FR-352 bounds at 6,000 chars ->
#:   1,500 tokens at `_CHARS_PER_TOKEN`. The answer schema and the chat scaffolding ride on top,
#:   so the constant quotes 1,600.
#: - the CONTRACT block is this deck's own `style_dna` (the same bytes every slide's render prompt
#:   carried, measured at up to ~2,200 chars across the shipped registry -> ~550 tokens) plus the
#:   style key, the strings that have to be legible on the cover and the counter badge. 700.
#: - the IMAGE side is `cover_candidates` frames at the platform's NATIVE render tier, added by
#:   `_cover_pick_lines` rather than folded in here: a `2k` deck costs materially more per call
#:   than a `1k` one (FR-342) and the operator sees that in the line rather than in the invoice.
#: - the ANSWER is one small object: the chosen id, a ~12-word `reason` and the JSON around them.
#: Over-stating is the safe direction (D11); understating is the one unacceptable estimator error,
#: so these three numbers only ever move against a measurement.
_COVER_PICK_PROMPT_TOKENS = 1600
_COVER_PICK_CONTRACT_TOKENS = 700
_COVER_PICK_COMPLETION_TOKENS = 80
#: FR-343's translate call (D63 §4), role `copy` and ONE call per translating deck — never
#: grouped, because the work order is one specific post's panels. The arithmetic is written down
#: for the same reason the style matcher's and the cover pick's are — a constant nobody can
#: explain rots:
#: - the FIXED side is `prompts/copy_translate_system.md`, measured at 9,815 chars on 2026-08-21
#:   -> ~2,454 tokens at `_CHARS_PER_TOKEN`. On top of it ride the answer schema for
#:   `CopyTranslated`, the carrier turn, and the same standing blocks the selection call carries
#:   (`trend_texts`, `text_budgets`, `platform_conventions`, `brief_directives`, the niche
#:   descriptor) — the bundle `_COPY_PROMPT_TOKENS` quotes at 600 for the selection role. 2,454 +
#:   600 + scaffolding, quoted at 3,200.
#: - one PANEL block per admitted source panel, printed IN FULL and with no per-line budget (§4b:
#:   a translation may not be given a length ceiling). `copywrite.PANEL_SANITY_CHARS` refuses a
#:   panel over 1,500 chars before it can ever reach the block, so 1,500 chars -> 375 tokens is a
#:   HARD per-panel ceiling rather than an average. Quoted at 400.
#: - the ANSWER carries every one of those panels back, and rule 1 allows a translation to be
#:   LONGER than its source; quoted at 500 per panel over a 300-token fixed floor (caption,
#:   hashtags, headline, `through_line`, `narrative_arc`, `source_language`, JSON scaffolding),
#:   the whole thing capped by `max_tokens.copy` because that is what the call is allowed to emit.
#: Over-stating is the safe direction (D11); understating is the one unacceptable estimator
#: error, so these three numbers only ever move against a measurement.
_TRANSLATE_PROMPT_TOKENS = 3200
_TRANSLATE_TOKENS_PER_PANEL = 400
_TRANSLATE_COMPLETION_PER_PANEL = 500
_TRANSLATE_COMPLETION_FIXED = 300
#: `run.copy_language_mode`'s translating value (FR-345). Compared as a plain string rather than
#: imported from `copywrite`, for the same reason every other stage word in this module is: the
#: estimator prices a plan out of config arithmetic alone (NFR-18) and has no import edge to the
#: stage modules whose spend it quotes.
_TRANSLATE_MODE = "target"
_IMAGE_TOKEN_DIVISOR = 750  # provider px -> vision-token rule
_IMAGE_TOKEN_MAX_PX = 1568  # providers resize above this, so token cost stops growing
_TIER_LONG_EDGE: dict[str, int] = {"1k": 1024, "2k": 2048, "4k": 4096}
#: Reasoning allowance per configured effort, measured in RESULTS.md §E: exactly 0 tokens at
#: `low`, ~32 % of completion at `medium`. `high` is extrapolated at 2x medium and labelled so.
_REASONING_FRACTION: dict[str, float] = {"low": 0.0, "medium": 0.32, "high": 0.64}
#: Mirrors `llm._TRUNCATION_BUMP_MAX` and `llm._DEFAULT_MAX_OUTPUT_CEILING` — see `_widened_cap`.
#: `llm.py` owns the behaviour; these two numbers exist here only so the estimator can PRICE it
#: without importing another module's internals, and `test_budget` asserts they match.
_RETRY_TOKEN_BUMP = 8192  # a retried call's cap grows by min(cap, this) ...
_RETRY_TOKEN_CEILING = 16384  # ... and is then clamped here, which the estimate must not ignore
#: Which `price_per_unit.llm.<key>` block prices each role. Keyed by ROLE, not by model id: a rate
#: belongs to whatever model was configured when it was typed in, so a swap keeps it (FR-282).
#: `critic` rides the `sonnet` block for the same reason `analysis` does — it is the same family of
#: model doing a vision-plus-structured-output job — but it is its OWN role (30 §2/D49) so its
#: model, its token ceiling and its price line move independently. Without this row
#: `_llm_call_price` would raise `KeyError` on every critic line, and a row pointing nowhere would
#: price the whole gauntlet at $0 — the estimate would then show a quality gate that costs nothing,
#: which is the one estimator error that is never safe (D11).
_ROLE_PRICE_KEY: dict[str, str] = {"analysis": "sonnet", "copy": "luna", "critic": "sonnet"}
#: SESSION O / D64. Under `models.llm_backend: codex` every LLM call leaves through the operator's
#: own ChatGPT/Codex subscription on loopback, and the invoice for it is a flat monthly fee this
#: estimator cannot apportion per call. So the rate is not "unknown", it is ZERO, and the honest
#: line says so with its own price key and origin instead of quoting Sonnet's or Luna's per-token
#: rate for tokens nobody will be billed for. Mirrors `config.ModelsConfig.llm_backend`'s literal
#: rather than importing it, for the same reason `_RETRY_TOKEN_*` mirrors `llm.py`: this module
#: prices, it does not depend on the modules whose behaviour it prices.
#:
#: The SAME literal answers the SAME question on the other door, `models.render_provider: codex`
#: (`_codex_renders` below): a picture rendered through the subscription proxy is not metered
#: either, so every RENDER line goes to $0 with this key too. The two doors are independent —
#: `llm_backend: codex` + `render_provider: kie` is a legal config and still pays Kie for pixels —
#: which is why there are two predicates and not one flag.
#:
#: What this does NOT touch on either door: Virlo's own deposit, which was never in this estimate.
_CODEX_BACKEND = "codex"
_CODEX_PRICE_KEY = "codex"
_CODEX_ORIGIN = "subscription (Codex OAuth) — $0 metered"
#: FR-326's per-call arithmetic (gauntlet spec §5), RE-BASED ON MEASUREMENT (F5, Session 5.5).
#: The prompt side is the critic template plus the `DeckContract` blocks it carries (expected
#: per-frame line blocks, required/forbidden marks, style DNA, layout zones); the completion side
#: is up to 3 defect objects per frame across up to 8 frames PLUS the reasoning Sonnet bills
#: inside `completion_tokens`.
#:
#: Both numbers were guesses (1,500 / 700) until Session 5's live acceptance run measured the real
#: calls: ≈18,300 prompt and ≈5,000 completion tokens each. The old pair under-quoted the gate by
#: an order of magnitude — $1.30 of critic spend the operator was never shown — and understating
#: is the one estimator error that is never safe (D11).
#:
#: Two honest caveats, because a constant nobody can explain rots:
#: - 18,300 is the measured WHOLE prompt side, and `_critic_call_price` still adds this deck's
#:   own image tokens on top of it. That double-counts the frames the measured calls carried, so
#:   the quote leans high by design — the safe direction, and cheaper to explain than a figure
#:   split into "text part" and "image part" that no log line can ever confirm.
#: - The completion side is RE-BASED on the promised second measurement (F5-tail, Session 5.6).
#:   The provisional 5,000 was measured with the critic role sending no `reasoning` field at all,
#:   i.e. Sonnet thinking at full effort inside `completion_tokens`. F5 then bound that role at
#:   `models.critic_reasoning_effort: low`, and canary run `20260819_170148_2z4y` measured what
#:   that is actually worth: 4,769 completion tokens across 11 critic calls, ≈434 a call. 1,000 is
#:   the honest-high quote at ~2.3x the measurement — room for a deck that hands every critic
#:   three defects on eight frames, without going back to quoting an order of magnitude of
#:   headroom nobody spends. This number only ever moves against a measurement (D11).
_CRITIC_PROMPT_TOKENS = 18300
_CRITIC_COMPLETION_TOKENS = 1000
_MICRO = 1_000_000
_DEFAULT_ORIGIN = "built-in default"

#: A `(unit_price | None, price_key, price_origin, assumed_model)` tuple — FR-282's provenance.
Priced = tuple[float | None, str, str, str]
ReservationKind = Literal["projected", "precommitted", "discretionary"]  # FR-106 a / b / c


class SpendCategory(str, Enum):
    """FR-84's grand-total split. Vision checks, the topic screen, the style match, slide
    intelligence and copy are LLM; every Kie job is RENDER."""

    LLM = "llm"
    RENDER = "render"


class ReservationState(str, Enum):
    """HELD from `reserve()`/`commit()` until reconciled (money moved) or released (it never did)."""

    HELD = "held"
    RECONCILED = "reconciled"
    RELEASED = "released"


def format_usd(amount: float) -> str:
    """The one display rounding rule: USD, two decimals, half-up (guidelines §7)."""
    return f"${Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"


def _micros(amount: float) -> int:
    """USD -> integer micro-USD, half-up. The single place a float becomes comparable money."""
    return int(Decimal(str(amount)).scaleb(6).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- estimate shapes


@dataclass(slots=True)
class EstimateLine:
    """One priced — or explicitly unpriced — row of the pre-flight estimate.

    `price_key` + `price_origin` + `assumed_model` are FR-282's provenance triple: the config key
    the rate came from, whether that key was written in the file or fell back to a built-in
    default, and which configured model the rate is *assumed for*. `code` is the machine-readable
    line kind, `label` is what the operator reads, `entry_orders` attributes it to plan entries.
    """

    code: str
    label: str
    category: SpendCategory
    unit: str  # "render" | "second" | "call" | "retry"
    quantity: float
    unit_price: float | None  # None whenever `unpriced` — never a guessed number
    amount_usd: float
    price_key: str
    price_origin: str
    assumed_model: str
    unpriced: bool = False
    allowance: bool = False  # worst-case only — excluded from FR-106a's expected projection
    blocking: bool = False  # FR-131: an unpriced reel stops planning, it does not merely report
    entry_orders: tuple[int, ...] = ()


@dataclass(slots=True)
class Estimate:
    """Priced lines, per-entry attribution and the two totals.

    `expected_usd` is FR-106a's gate (whole batch at expected cost, no retry allowance);
    `worst_case_usd` adds the FR-107 allowances and is DISPLAYED ("worst case: $X") but never
    gates a release — gating on contingencies that mostly never happen deletes real creatives.
    """

    lines: tuple[EstimateLine, ...]
    per_entry_usd: dict[int, float]
    expected_usd: float
    worst_case_usd: float

    @property
    def unpriced_lines(self) -> tuple[EstimateLine, ...]:
        """Lines whose rate is unset or zero — printed as *unpriced* beside the total (FR-282)."""
        return tuple(line for line in self.lines if line.unpriced)

    @property
    def blocked(self) -> tuple[EstimateLine, ...]:
        """Lines the estimator refuses to price at all — today only reels (FR-131/FR-107)."""
        return tuple(line for line in self.lines if line.blocking)

    @property
    def banner(self) -> str:
        """FR-107/FR-84's governance banner, or "" when every line carries a real rate."""
        count = len(self.unpriced_lines)
        plural = "line" if count == 1 else "lines"
        return f"governance partial — {count} {plural} unpriced" if count else ""


# --------------------------------------------------------------------------- pricing helpers


def _origin(config: Config, key: str) -> str:
    """FR-282: did this rate come from the config file, or from a built-in default?

    `Config.defaults_applied` records every key that fell back at load time, so a rate the file
    never mentions — directly or through an absent parent block — is honestly labelled.
    """
    parts = key.split(".")
    prefixes = {".".join(parts[: i + 1]) for i in range(len(parts))}
    return _DEFAULT_ORIGIN if prefixes & set(config.defaults_applied) else config.path.name


def _image_tokens(long_edge: int, aspect_ratio: str) -> int:
    """Vision content-part tokens for one image at a given long edge (FR-107's image tokens)."""
    try:
        width, height = (float(part) for part in aspect_ratio.split(":", 1))
        factor = min(width, height) / max(width, height) if width > 0 and height > 0 else 1.0
    except (AttributeError, ValueError):
        factor = 1.0  # unknown ratio: price it as square rather than guessing a crop
    edge = min(long_edge, _IMAGE_TOKEN_MAX_PX)
    return math.ceil(edge * edge * factor / _IMAGE_TOKEN_DIVISOR)


def _codex_renders(config: Config) -> bool:
    """Does this run's RENDER door ride the subscription? (D64, `models.render_provider: codex`)

    The render twin of `_llm_call_price`'s backend test, and separate from it on purpose: the two
    doors are configured independently, so a run can pay OpenRouter for text and nothing for
    pixels, or the other way round, and each half of the estimate has to answer for itself.
    """
    return str(config.models.render_provider) == _CODEX_BACKEND


def _codex_priced(model: str) -> Priced:
    """The $0 subscription tuple every codex-door line carries — one shape, one place."""
    return (0.0, _CODEX_PRICE_KEY, _CODEX_ORIGIN, model)


def _video_price(config: Config) -> Priced:
    """FR-131's per-second reel rate, or the $0 subscription tuple under the codex render door.

    Moot in practice and here anyway: pre-flight refuses a planned reel outright under
    `render_provider: codex` (there is no subscription path for video, D64), and the provider
    itself fails a video body rather than submitting it. But `job_projection` reserves money
    against this number before either of those speaks, and a reservation for a job that cannot
    cost anything is exactly the phantom money that declines the NEXT job that can.

    The unpriced-reel line in `_entry_lines` deliberately does NOT come through here: it must keep
    naming `models.price_per_unit.reel_second.<res>`, the key an operator has to go and fill in.
    """
    if _codex_renders(config):
        return _codex_priced(config.models.video)
    return (config.reel_price_per_second, config.reel_price_key,
            _origin(config, config.reel_price_key), config.models.video)


def _image_price(config: Config, platform: str, *,
                 aspect_ratio: str | None = None) -> tuple[Priced, int]:
    """FR-107's per-platform resolution: the render tier's rate, plus its native long edge.

    **Under `models.render_provider: codex` the rate is $0 (D64)** — the same argument
    `_llm_call_price` makes for its own door, applied to pixels: the proxy renders against the
    operator's ChatGPT subscription, so quoting Kie's `2k` rate would put $2.10 on a Confirm table
    for a run that will be billed nothing. That is not a harmless over-statement either, because
    the SAME arithmetic reserves money: `--yes` would trim creatives out of a free plan, and
    `Budget.reserve` would decline an FR-317 resubmit or a gauntlet re-render against money that
    was never at stake.

    The long edge that comes back is still the CONFIGURED tier's, not the proxy's fixed ~1254 px.
    It prices no pixels — it only sizes the vision tokens a critic or a cover pick pays to LOOK at
    the frame, which is metered whenever `llm_backend` stays `openrouter` — and quoting the tier
    keeps that arithmetic on the honest-high side (D11) instead of pinning a measured proxy
    constant that a proxy update can silently falsify. Pre-flight prints the real pixel size.

    The tier comes from `platforms.<name>.image_resolution`, real since FR-342 (v2.5.1) and read
    through `Config.image_resolution()` — the SAME accessor every image render calls before it
    fills in `RenderParams.resolution`. That shared read is what makes the Confirm gate honest:
    the estimate below quotes the rate for the tier the run is about to submit at, so a config
    that pins `2k` is quoted at the 2K rate and never at the 1K one it stopped buying.

    `aspect_ratio` closes the other half of that promise. The tier is per-PLATFORM, but the
    provider clamps per RATIO — 20 §8c's 1K-only ratios render at 1K however they were asked for
    — so pricing the configured tier alone would quote 2K for an Instagram image at FR-21's 4:5
    and buy 1K. The entry's ratio therefore goes through `profiles.effective_image_tier`, the
    same clamp the render path runs, and there is exactly one clamp table between them. `None`
    means "no ratio in hand, do not clamp"; it is not the same as `""`, which the provider treats
    as unset and renders at 1K.

    The long edge that comes back with the price is the EFFECTIVE tier's native pixel size, and
    it is not decoration — the gauntlet's critics read the rendered frames, so a taller tier
    costs more vision tokens per frame as well as more per render, and `_image_tokens` needs this
    number to charge for that too. Clamping before the lookup is what keeps that arithmetic
    honest as well: a 4:5 frame is charged as the 1024 px it arrives at, not the 2048 px it asked.

    An unknown tier stays an unpriced line naming the missing `models.price_per_unit.image.<tier>`
    key, never a silent re-tier onto a cheaper neighbour: an unpriced line is a question the
    operator answers at the gate, whereas a substituted price is a wrong number they approve.
    Its long edge falls back to `_DEFAULT_LONG_EDGE_PX` so the vision arithmetic still runs.
    """
    tier = config.image_resolution(platform)
    if aspect_ratio is not None:  # what Kie RENDERS, not what config asked for (FR-342)
        tier = effective_image_tier(aspect_ratio, tier)
    long_edge = _TIER_LONG_EDGE.get(tier, _DEFAULT_LONG_EDGE_PX)
    if _codex_renders(config):
        return _codex_priced(config.models.image), long_edge
    key = f"models.price_per_unit.image.{tier}"
    priced = (config.models.price_per_unit.image.get(tier), key, _origin(config, key),
              config.models.image)
    return priced, long_edge


def _llm_call_price(config: Config, role: str, prompt: int, completion: int, reasoning: int) -> Priced:
    """Blended price of ONE call of `role`, or unpriced when any rate it needs is unset/zero.

    Blending keeps the estimate readable (one line per call kind) while still charging input,
    output and — for Luna — reasoning tokens at their own configured rates.

    Under the `codex` backend there is nothing to blend: the call rides a subscription, costs $0
    at the margin, and prices as `$0.00 [subscription (Codex OAuth)]`. The assumed model is still
    the configured id, because that is the thing an operator swaps and the line that names it is
    how they check WHICH model answered (FR-282 is about provenance, not only about money).
    """
    if config.models.llm_backend == _CODEX_BACKEND:
        return (0.0, _CODEX_PRICE_KEY, _CODEX_ORIGIN, getattr(config.models, role))
    table_key = _ROLE_PRICE_KEY[role]
    key = f"models.price_per_unit.llm.{table_key}"
    rates = config.models.price_per_unit.llm.get(table_key) or {}
    unpriced: Priced = (None, key, _origin(config, key), getattr(config.models, role))
    needed = [("input_per_mtok", prompt), ("output_per_mtok", completion)]
    if reasoning:
        needed.append(("reasoning_per_mtok", reasoning))
    total = 0.0
    for rate_name, tokens in needed:
        rate = rates.get(rate_name)
        if not rate:
            return unpriced
        total += tokens / _MICRO * rate
    return (round(total, 8), key, unpriced[2], unpriced[3])


def _line(code: str, label: str, category: SpendCategory, unit: str, quantity: float,
          priced: Priced, orders: Sequence[int], *, allowance: bool = False,
          blocking: bool = False) -> EstimateLine:
    """Build one line from a pricing tuple; a missing or zero rate makes it unpriced at $0.

    The ONE exception is the codex price key: $0 there is a measured fact (a subscription call is
    not metered), not a rate nobody entered. Flagging it `unpriced` would raise the governance
    banner — "governance partial, N lines unpriced" — on a run whose LLM spend is genuinely and
    knowably zero, which trains an operator to ignore the one banner that exists to be read.
    """
    price, key, origin, model = priced
    unpriced = (price is None or price <= 0) and key != _CODEX_PRICE_KEY
    return EstimateLine(
        code=code, label=label, category=category, unit=unit, quantity=quantity,
        unit_price=None if unpriced else price,
        amount_usd=0.0 if unpriced else round(quantity * price, 6),
        price_key=key, price_origin=origin, assumed_model=model, unpriced=unpriced,
        allowance=allowance, blocking=blocking, entry_orders=tuple(orders))


# --------------------------------------------------------------------------- the estimator


def estimate(config: Config, entries: Sequence[PlanEntry], *,
             post_languages: Mapping[str, str] | None = None) -> Estimate:
    """Price a whole plan locally, enumerating every FR-107 conditional contributor.

    Covered bullet by bullet (10 §9, FR-107 as amended v2.1.0): the batched topic-filter screen at
    its worst-case topic bound; **one batched style-match call when `styles.assignment: matched`**
    (FR-334/D56 — post-Confirm spend at ASSIGN, quoted before the gate, and quoted at nothing at
    all under the `rotation` default); **one slide-intelligence call per bound carousel source post**
    (FR-306/§0.11 — post-Confirm spend, quoted before the gate); seed-frame renders; the
    moderation-retry allowance; **the gauntlet's critic panel and per-deck re-render budget**
    (FR-326/spec §5 — `allowance=True` lines, displayed and worst-case provisioned, never gating,
    and the ONLY post-render gate lines there are since D49 deleted the FR-105 `vision_check` row);
    the carousel anchor-failure N+1 contingency; **FR-351's cover best-of-N — the `cover_candidates
    − 1` EXTRA slide-1 renders on every chained deck (expected spend, not an allowance: they are
    bought on the happy path of every run) and one `analysis` pick call per deck, quoted at its own
    platform's native image tier**; **FR-343's translate call — one `copy` call per bound carousel
    deck that has to change language under `run.copy_language_mode: target` (D63, and nothing at
    all under the `source` default)**; critic image tokens at
    native render resolution; a reasoning allowance on every Luna call plus FR-99's split
    per-creative calls; the FR-127 + FR-41 retry allowance on every LLM call; per-platform
    resolution; **carousel slides at each entry's own ASSIGN-fixed deck length** (§0.4′: the bound
    post's `panel_count`, clamped under the platform HARD MAX — an entry with no post bound yet is
    priced at `plan.DEFAULT_UNBOUND_DECK_SLIDES`, see `_deck_slides`); reels at `reel_second` x
    the configured duration, at the configured
    resolution and with **no** motion-reference seconds (withdrawn, v2.0.0/D41).

    **FR-343's translate call (D63) is the one line whose QUANTITY depends on data this module
    cannot read out of the config**, which is what `post_languages` is for. Under
    `run.copy_language_mode: target` a bound carousel deck pays one extra `copy` call unless its
    source post is already written in the platform's language — and only the bound POST knows
    that. Called with no mapping (the Confirm gate, which runs before Collect) every non-override
    carousel is priced, because that is the worst case the plan can produce and understating is
    the one unacceptable estimator error (D11). Called WITH one (`runner`'s re-price right after
    `_select`, where the posts are bound and Virlo's own `language_detected` is on every row) the
    decks that need no translation drop off the quote, which is the same "provisional until
    ASSIGN, real afterwards" contract `_slide_intel_lines` already documents for its own line.

    Args:
        config: the loaded run config — the only price source (FR-282); no network (NFR-18).
        entries: the expanded plan, in plan order.
        post_languages: `post_id -> ISO 639-1 code`, when the caller knows them. Optional and
            keyword-only: every pre-Collect caller (the Confirm gate, `trim`, the menu, the
            previews) legitimately has nothing to pass, and passing nothing prices the worst case.

    Returns:
        An `Estimate`. Reels stay unpriced and BLOCKING while their rate is unset — they appear in
        `Estimate.blocked`, never as a guessed price (FR-131).

    Side effect (deliberate, FR-106): each entry's `estimated_cost_usd` is set to its expected
    share, because every trim decision must be logged with that number.
    """
    lines: list[EstimateLine] = []
    for entry in entries:
        _entry_lines(config, entry, lines)
    _llm_lines(config, entries, lines, post_languages=post_languages)
    _gauntlet_lines(config, entries, lines)

    per_entry = {entry.order: 0.0 for entry in entries}
    for line in lines:
        if line.allowance or not line.entry_orders:
            continue
        share = line.amount_usd / len(line.entry_orders)
        for order in line.entry_orders:
            per_entry[order] = per_entry.get(order, 0.0) + share
    per_entry = {order: round(amount, 6) for order, amount in per_entry.items()}
    for entry in entries:
        entry.estimated_cost_usd = per_entry.get(entry.order, 0.0)
    return Estimate(
        lines=tuple(lines), per_entry_usd=per_entry,
        expected_usd=round(sum(l.amount_usd for l in lines if not l.allowance), 6),
        worst_case_usd=round(sum(l.amount_usd for l in lines), 6))


def _deck_slides(config: Config, entry: PlanEntry) -> int:
    """This carousel's real deck length — FR-95/FR-107/FR-257 as amended v2.1.0 (§0.4′).

    `entry.slide_count` is the number `plan.assign()` fixed from the bound source post's own panel
    count, so every deck is priced at the length it will actually render rather than at one flat
    number for the whole plan. **Decks now differ in price, and that is correct** — a constant
    per-carousel `estimated_cost_usd` across a plan means the source panel counts never reached
    here.

    `platforms.<name>.carousel_slides` is applied on top as the platform HARD MAX (2026-08-13; it
    is no longer a 5-slide target): a source may make a deck shorter and may never make it longer
    than the destination accepts (FR-257). An entry with no bound post carries
    `plan.DEFAULT_UNBOUND_DECK_SLIDES` — the pre-Collect estimate and every override brief
    (§0.14d) — so the `or ceiling` fallback below is a last-resort floor for a slide_count that
    never got stamped at all, not the normal pre-bind path.
    """
    ceiling = config.platform(entry.platform).carousel_slides
    return max(1, min(int(entry.slide_count or ceiling), ceiling))


def _entry_lines(config: Config, entry: PlanEntry, lines: list[EstimateLine]) -> None:
    """Render lines and the worst-case moderation allowance for ONE plan entry.

    The post-render gate's own lines are NOT here: `_gauntlet_lines` quotes them once for the whole
    plan (FR-326), as `allowance=True` rows that are displayed and provisioned and never gate a
    creative (FR-106a).
    """
    orders, run = (entry.order,), config.run
    image_priced, _native_px = _image_price(config, entry.platform,
                                            aspect_ratio=entry.aspect_ratio)
    primary = image_priced  # what a moderation retry would cost

    if entry.creative_format == "image":
        lines.append(_line("image_render", f"image render · {entry.asset_id}",
                           SpendCategory.RENDER, "render", 1, image_priced, orders))
    elif entry.creative_format == "carousel":
        slides = _deck_slides(config, entry)
        lines.append(_line("carousel_slides", f"carousel slides ({slides}) · {entry.asset_id}",
                           SpendCategory.RENDER, "render", slides, image_priced, orders))
        if run.carousel_anchor and run.cover_candidates > 1:
            # FR-351 (v2.6.0/D62): EXPECTED spend, not an allowance. `cover_candidates: 3` orders
            # three slide-1 renders on every chained deck as a matter of course — they are bought
            # before anything is judged, on the happy path, every single run — so quoting them as
            # a contingency would hide two thirds of a deck's cover cost from the number the
            # operator approves (rule 7, D11). One unit is already inside `carousel_slides` above,
            # which prices the deck at its full length including slide 1; this line is the N-1
            # EXTRA covers, at the same tier, so the two rows sum to what Kie will bill.
            extra = int(run.cover_candidates) - 1
            lines.append(_line("cover_candidates",
                               f"cover candidates (+{extra}) · {entry.asset_id}",
                               SpendCategory.RENDER, "render", extra, image_priced, orders))
        if run.carousel_anchor:
            # TWO units, not one (v2.2.0). FR-95's anchor-failure shape gained a step: a dead
            # anchor now buys ONE fresh anchor attempt before the deck falls back to N independent
            # reference-free renders, so the worst case is the failed slide-1 job PLUS the failed
            # re-anchor PLUS the N-render burst — N+2 billed renders, not N+1. Both extra jobs are
            # billed on submission whether or not they land (FR-106), so the estimate carries them
            # rather than letting the second one surface as an overrun on a paid run.
            lines.append(_line("anchor_contingency_allowance",
                               f"carousel anchor-failure contingency · {entry.asset_id}",
                               SpendCategory.RENDER, "render", 2, image_priced, orders,
                               allowance=True))
    else:  # reel
        if not config.reels_plannable:
            # NOT `_video_price`: this line's whole job is to name the key nobody filled in, so
            # is built from the metered key even under the codex door (which refuses reels anyway).
            unset: Priced = (None, config.reel_price_key,
                             _origin(config, config.reel_price_key), config.models.video)
            lines.append(_line("reel_clip",
                               f"reel clip · {entry.asset_id} — not planned: "
                               f"{config.reel_price_key} is unset, and an unpriced format is an "
                               "unbounded format (FR-131)",
                               SpendCategory.RENDER, "second", run.reel_duration_s,
                               unset, orders, blocking=True))
            return  # a blocked reel buys nothing else: no seed frame, no check, no allowance
        reel_priced: Priced = _video_price(config)
        if run.reel_overlay_text == "seed_frame":
            lines.append(_line("reel_seed_frame", f"reel seed frame · {entry.asset_id}",
                               SpendCategory.RENDER, "render", 1, image_priced, orders))
        else:
            primary = reel_priced
        lines.append(_line(
            "reel_clip",
            f"reel clip ({run.reel_duration_s}s @ {run.reel_resolution}) · {entry.asset_id}",
            SpendCategory.RENDER, "second", run.reel_duration_s, reel_priced, orders))

    # FR-107's moderation retry (FR-97) — the one retry class that is not the gauntlet's. The
    # FR-105 `vision_check` / `vision_check_anchor` call lines and the `vision_retry_allowance`
    # that rode beside them are DELETED with the machinery they priced (v2.2.0/D49): the
    # post-render gate is `_gauntlet_lines` below, which quotes the critic panel and the per-deck
    # re-render budget as `allowance=True` rows. Leaving the old lines in would bill the operator's
    # estimate twice for one gate — once for a check that no longer exists.
    lines.append(_line("moderation_retry_allowance",
                       f"moderation retry allowance · {entry.asset_id}",
                       SpendCategory.RENDER, "retry", 1, primary, orders, allowance=True))


def _widened_cap(out: int) -> int:
    """What `max_tokens` FR-127's truncation retry will actually ask for — `llm._widen`'s answer.

    The retry adds `min(cap, 8192)` and `llm._output_ceiling` then clamps the result to 16,384
    (or to the configured cap, whichever is larger, since an operator who configured a big cap
    has already proven it routable). Pricing the unclamped bump over-stated every analysis
    allowance line by ~3,800 output tokens once `max_tokens.analysis` rose to 12,000 — safe in
    direction (D11), but a number the operator reads should be the number the code will spend.
    """
    return min(out + min(out, _RETRY_TOKEN_BUMP), max(_RETRY_TOKEN_CEILING, out))


def job_projection(config: Config, entry: PlanEntry, job: str) -> float:
    """The expected cost of ONE submission — the engine's single per-job price (FR-107/FR-106).

    `generate`'s metered `submit` is the only caller, so no module ever re-derives a rate:
    `image` / `slide` / `seed_frame` are the platform's image tier (the same tier `estimate()`
    priced the plan with), `clip` is `price_per_unit.reel_second` x the configured duration.
    An unpriced line projects **$0** and the submission still proceeds — pre-committed work is
    already approved (FR-106b), and FR-131 blocked unpriced reels at *planning* time, not here.

    Under `models.render_provider: codex` every projection here is $0 (D64), through the same two
    helpers the estimate uses. That is not cosmetic: this number is what `Budget.reserve` holds
    against the cap, so a metered projection on a subscription render would let a free run run out
    of money and decline the FR-317 resubmit that follows.
    """
    if job == "clip":
        (per_second, *_) = _video_price(config)
        return round((per_second or 0.0) * max(int(config.run.reel_duration_s), 0), 6)
    (price, *_), _ = _image_price(config, entry.platform, aspect_ratio=entry.aspect_ratio)
    return round(price or 0.0, 6)


def _filter_topics(config: Config) -> int:
    """FR-294's worst-case topic count: `len(monitors) x virlo_topics_per_monitor`.

    Deliberately a config bound rather than a real count: the screen is priced BEFORE Collect, so
    the only honest number is the most Virlo could hand back — every configured monitor returning
    a full set of themes. A monitor that answers with three topics simply costs less than the line
    said, which is the safe direction (D11); understating is the one unacceptable estimator error.
    `-1` is the kill switch (one topic per monitor, 30 §2), so it prices as one, not as none.
    """
    if "virlo" not in config.sources.active:
        return 0
    monitors = sum(1 for monitor_id in config.sources.virlo_monitor_ids if str(monitor_id).strip())
    per_monitor = config.sources.virlo_topics_per_monitor
    return monitors * (1 if per_monitor < 1 else per_monitor)


def _filter_lines(config: Config, planned: Sequence[PlanEntry], effort: float,
                  lines: list[EstimateLine]) -> None:
    """FR-294's one batched competitor screen, priced pre-Collect (FR-107's first bullet).

    ONE call for the whole candidate pool, whatever the pool size — that batching is the reason
    the filter exists as its own stage instead of riding inside the copy call (§1.5), and it is
    why the quantity here is 1 while the token count carries the topics. Its answer is one small
    verdict object per topic, so the completion side is bounded by the topic count and by the copy
    role's own `max_tokens` ceiling, whichever is lower.

    Skipped entirely when the run screens nothing: no Virlo, no configured monitors, or a plan
    whose every creative is an `override` brief (FR-144 — such a run opens no Virlo session at all).
    """
    topics = _filter_topics(config)
    screened = [entry for entry in planned if entry.brief_influence != "override"]
    if not topics or not screened:
        return
    prompt = _FILTER_PROMPT_TOKENS + topics * _FILTER_TOKENS_PER_TOPIC
    completion = min(config.max_tokens_for("copy"), topics * _FILTER_VERDICT_TOKENS)
    orders = [entry.order for entry in screened]
    lines.append(_line("filter_call",
                       f"topic filter screen (1 batched call, {topics} topics worst case)",
                       SpendCategory.LLM, "call", 1,
                       _llm_call_price(config, "copy", prompt, completion, round(completion * effort)),
                       orders))
    # FR-107's per-call retry allowance applies to EVERY role, and the filter is no exception:
    # FR-127's widened truncation retry and FR-41's parse retry are independent, each capped at 1,
    # and one call can spend both (`llm._run_attempts`). Allowance only — FR-106a's gate never
    # prices a contingency. The filter's own failure path is fail-open (§1.5: a degraded screen
    # keeps every topic), so this covers the retries the LLM layer makes, not a re-screen.
    wide_out = _widened_cap(completion)
    wide = _llm_call_price(config, "copy", prompt, wide_out, round(wide_out * effort))
    lines.append(_line("filter_retry_allowance",
                       "topic filter truncation + parse retry allowance (2)",
                       SpendCategory.LLM, "retry", 2, wide, orders, allowance=True))


def _style_match_lines(config: Config, planned: Sequence[PlanEntry],
                       lines: list[EstimateLine]) -> None:
    """FR-334/D56's matched style assignment: ONE batched `analysis` call for the whole plan.

    Quoted here for the same reason the slide-intelligence pass above is: it is post-Confirm LLM
    spend on top of the renders, and rule 7 says the operator approves a number before it is spent,
    not after. The stage runs at ASSIGN — after Select binds the topics, before INTEL and COPY —
    so this line sits between the filter screen and the source-deck reads in `_llm_lines`, and the
    printed estimate reads in the order the run executes.

    **Gated on `styles.assignment: matched`.** Under the engine default (`rotation`, 30 §2) no
    model is asked anything at ASSIGN — the pick is a pure function of `entry.order` — and a $0
    line for a call that will never happen reads like a rate that failed to load, which is the same
    argument `_slide_intel_lines` makes for `vision_transcribe: false`.

    **The quantity is 1 whatever the plan size.** One call carries every creative's section and
    returns one row per creative, which is the whole reason the matcher is a stage of its own
    rather than a question asked inside each copy call (§5) — the plan's size moves the TOKENS, not
    the call count.

    **Override briefs are excluded and can leave the line unquoted entirely.** An `override` brief
    suppresses the style channel outright (M14: `runner._assign_visuals` filters them before
    `assign_styles` ever sees them, so they carry no `style_key` to overrule), so they are not in
    the matcher's entry set and must not be in its price. A plan of nothing but override briefs
    quotes no style-match spend at all — the same shape `_filter_lines` and `_slide_intel_lines`
    already refuse to quote.

    Basis: the fixed template, one candidate block per style in the pool, one section per styled
    creative, and one small answer row back (see the `_STYLE_MATCH_*` constants for the measured
    arithmetic). The pool is quoted as `styles.enabled`'s length — the FR-314 selector is the
    honest count of what the prompt will carry — falling back to `_STYLE_MATCH_ASSUMED_POOL` when
    the selector is empty and therefore means the whole registry. Per-format filtering (`fmt_affine`,
    `carousel_role`) can only make an entry's own candidate list SHORTER than that, so the quote
    leans high by construction, which is the safe direction (D11).

    Reasoning is priced at 0 for the same reason the slide-intelligence call prices none: `analysis`
    is Sonnet, and the reasoning-effort knob (30 §2) is the COPY role's.
    """
    if config.styles.assignment != "matched":
        return
    styled = [entry for entry in planned if entry.brief_influence != "override"]
    if not styled:
        return
    candidates = len(config.styles.enabled) or _STYLE_MATCH_ASSUMED_POOL
    prompt = (_STYLE_MATCH_PROMPT_TOKENS + candidates * _STYLE_MATCH_TOKENS_PER_CANDIDATE
              + len(styled) * _STYLE_MATCH_TOKENS_PER_ENTRY)
    completion = _match_completion(config, len(styled))
    orders = [entry.order for entry in styled]
    lines.append(_line("style_match_call",
                       f"style match (1 batched call, {len(styled)} creative(s), "
                       f"{candidates} candidate style(s))",
                       SpendCategory.LLM, "call", 1,
                       _llm_call_price(config, "analysis", prompt, completion, 0), orders))
    # FR-107's per-call retry allowance applies to every role, and one call can spend BOTH retries:
    # FR-127's widened truncation retry and FR-41's parse retry are independent and each capped at
    # 1 (`llm._run_attempts`). An allowance only — never expected spend — because the stage is
    # fail-open (§5: a failed call leaves every entry on its FR-291 rotation baseline and the run
    # continues), so these two are contingencies rather than a re-match.
    wide_out = _widened_cap(completion)
    wide = _llm_call_price(config, "analysis", prompt, wide_out, 0)
    lines.append(_line("style_match_retry_allowance",
                       "style match truncation + parse retry allowance (2)",
                       SpendCategory.LLM, "retry", 2, wide, orders, allowance=True))


def _match_completion(config: Config, creatives: int) -> int:
    """One style-match answer's output size, bounded by `max_tokens.analysis` (30 §2)."""
    return min(config.max_tokens_for("analysis"),
               creatives * _STYLE_MATCH_COMPLETION_PER_ENTRY)


def _slide_intel_lines(config: Config, planned: Sequence[PlanEntry],
                       lines: list[EstimateLine]) -> None:
    """FR-306/§0.11's slide-intelligence pass: ONE analysis call per bound carousel source post.

    It runs after the Confirm gate and before COPY, which is precisely why it has to be quoted
    before the gate (rule 7): it is paid LLM spend on top of the renders. The quantity is one call
    per DISTINCT `source_post_id` — two sibling carousels bound to one post are analysed once
    (`slide_intel.enrich` deduplicates), so pricing them twice would over-quote the commonest run
    shape rather than the rare one.

    **Before assignment binds anything the line is still quoted** (the v1.6.5 estimator-fidelity
    convention, and the reason `runner._stamp_provisional` exists): the gate currently runs ahead
    of Collect, so a non-override carousel is priced as its OWN source post at
    `plan.DEFAULT_UNBOUND_DECK_SLIDES` slides. The POST count stays worst-case — siblings can only
    collapse onto one post, never fan out — but since 2026-08-13 the per-post SLIDE count no longer
    is: `carousel_slides` became a platform hard max (20/10/20) rather than a 5-slide target, so a
    source with more panels than the provisional length makes this line dearer at bind time than at
    the gate. That is a deliberate trade (a worst-case pre-bind quote would price every deck at 20
    slides and swallow the spend cap on decks nobody will render); understating is still the one
    unacceptable estimator error (D11), so the honest reading is that this line is PROVISIONAL
    until ASSIGN. `runner` re-prices the whole plan on the bound topics right after `_select`
    (runner.py:400) and restates it, which is where the real number lands.

    Basis, per §0.11: the deck length (`_deck_slides` — the bound post's `panel_count` once ASSIGN
    has run), one image block per slide at the provider's token ceiling, plus the question and one
    answer object per slide. One bound is stated rather than hidden: a source deck LONGER than the
    platform ceiling is analysed in full (that is what `panels_truncated` means) and so costs more
    image blocks than this line quotes, capped by `slide_intel`'s own 20-slide fence. Nothing is
    quoted at all when no call will be made — `sources.vision_transcribe: false` (§0.6) or a plan
    with no non-override carousel in it — because a $0 line for work that will not happen reads
    like a rate that failed to load.
    """
    if not config.sources.vision_transcribe:
        return
    posts: dict[str, list[PlanEntry]] = {}
    for entry in planned:
        if entry.creative_format != "carousel" or entry.brief_influence == "override":
            continue  # an override brief binds no source post and is never analysed (§0.14d)
        posts.setdefault(str(entry.source_post_id or "").strip() or entry.asset_id,
                         []).append(entry)
    if not posts:
        return
    per_slide = _image_tokens(_IMAGE_TOKEN_MAX_PX, _SOURCE_SLIDE_RATIO)
    widest = 0
    for key, members in posts.items():
        slides = max(_deck_slides(config, member) for member in members)
        widest = max(widest, slides)
        bound = bool(str(members[0].source_post_id or "").strip())
        # Reasoning is 0 for the same reason the vision check prices none: `analysis` is Sonnet,
        # and the reasoning-effort knob (30 §2) is the COPY role's.
        priced = _llm_call_price(config, "analysis",
                                 _SLIDE_INTEL_PROMPT_TOKENS + slides * per_slide,
                                 _intel_completion(config, slides), 0)
        lines.append(_line("slide_intel",
                           f"slide intelligence ({slides} source slides) · "
                           + (f"post {key}" if bound
                              else f"{key} (worst case: one source post per deck)"),
                           SpendCategory.LLM, "call", 1, priced,
                           [member.order for member in members]))
    # FR-107's per-call retry allowance applies to every role: FR-127's widened truncation retry and
    # FR-41's parse retry are independent single retries that can compound on one call. Priced at
    # the widest post in the plan — the worst case this plan can produce — and an allowance only,
    # because the stage itself is fail-open (§0.14c: a failed read keeps the Virlo panels).
    wide_out = _widened_cap(_intel_completion(config, widest))
    wide = _llm_call_price(config, "analysis", _SLIDE_INTEL_PROMPT_TOKENS + widest * per_slide,
                           wide_out, 0)
    lines.append(_line("slide_intel_retry_allowance",
                       f"slide intelligence truncation + parse retry allowance ({2 * len(posts)})",
                       SpendCategory.LLM, "retry", 2 * len(posts), wide,
                       [member.order for members in posts.values() for member in members],
                       allowance=True))


def _intel_completion(config: Config, slides: int) -> int:
    """One slide-intelligence answer's output size, bounded by `max_tokens.analysis` (30 §2)."""
    return min(config.max_tokens_for("analysis"), slides * _SLIDE_INTEL_COMPLETION_PER_SLIDE)


def _cover_pick_lines(config: Config, planned: Sequence[PlanEntry],
                      lines: list[EstimateLine]) -> None:
    """FR-351's cover pick: ONE `analysis` call per CHAINED carousel, plus its retry allowance.

    It runs inside CREATE, long after the Confirm gate, which is exactly why it is quoted before
    the gate (rule 7): it is metered LLM spend on top of the extra covers `_entry_lines` already
    priced. The quantity is one call PER DECK and not one per run — unlike the style matcher, this
    question is about one deck's own candidates and cannot be batched across creatives, because
    every deck ships its own style contract and its own two or three frames.

    **Gated on the render shape, never on the brief.** Three conditions and all of them are about
    whether a cover pick can happen at all: the creative is a carousel, `run.carousel_anchor` is on
    (an unchained deck has no anchor to choose), and `run.cover_candidates > 1` (one cover is not a
    choice). An OVERRIDE brief is deliberately NOT excluded here, unlike in `_style_match_lines`:
    an override brief replaces the STYLE channel, not the anchor — its deck is still chained, still
    orders `cover_candidates` covers and still asks which of them anchors it — so filtering it out
    would under-quote the commonest thing an override brief does.

    Basis: the fixed template plus this deck's own contract block (see the `_COVER_PICK_*`
    constants) plus `cover_candidates` image blocks at the platform's NATIVE render tier, run
    through the same `_image_price` clamp the renderer and the critics use, so a `2k` platform's
    pick is quoted at 2K image tokens and a 1K-only ratio at 1K (FR-342/20 §8c). Reasoning is
    priced at 0 for the same reason the slide-intelligence and style-match calls price none:
    `analysis` is Sonnet, and the reasoning-effort knob (30 §2) is the COPY role's.

    Nothing is quoted when no call will be made — a plan with no chained carousel in it, a
    `carousel_anchor: false` run, or the engine-default `cover_candidates: 1` — because a $0 line
    for work that will not happen reads like a rate that failed to load, which is the same argument
    `_filter_lines`, `_style_match_lines` and `_slide_intel_lines` all make.
    """
    run = config.run
    if not run.carousel_anchor or run.cover_candidates <= 1:
        return
    picking = [entry for entry in planned if entry.creative_format == "carousel"]
    if not picking:
        return
    completion = min(config.max_tokens_for("analysis"), _COVER_PICK_COMPLETION_TOKENS)
    widest, orders = 0, []
    for entry in picking:
        _priced, native_px = _image_price(config, entry.platform,
                                          aspect_ratio=entry.aspect_ratio)
        prompt = (_COVER_PICK_PROMPT_TOKENS + _COVER_PICK_CONTRACT_TOKENS
                  + run.cover_candidates * _image_tokens(native_px, entry.aspect_ratio))
        widest = max(widest, prompt)
        orders.append(entry.order)
        lines.append(_line("cover_pick_call",
                           f"cover pick ({run.cover_candidates} candidates) · {entry.asset_id}",
                           SpendCategory.LLM, "call", 1,
                           _llm_call_price(config, "analysis", prompt, completion, 0),
                           (entry.order,)))
    # FR-107's per-call retry allowance applies to every role, and one call can spend BOTH:
    # FR-127's widened truncation retry and FR-41's parse retry are independent and each capped at
    # 1 (`llm._run_attempts`). An allowance only — never expected spend — because the stage is
    # fail-open (FR-351: a failed pick commits candidate 1 and tags `cover_pick_degraded`, so
    # there is never a re-pick to pay for). Priced at the dearest deck in the plan, which is the
    # worst case this plan can produce.
    wide_out = _widened_cap(completion)
    wide = _llm_call_price(config, "analysis", widest, wide_out, 0)
    lines.append(_line("cover_pick_retry_allowance",
                       "cover pick truncation + parse retry allowance (2)",
                       SpendCategory.LLM, "retry", 2, wide, orders, allowance=True))


def _llm_lines(config: Config, entries: Sequence[PlanEntry], lines: list[EstimateLine], *,
               post_languages: Mapping[str, str] | None = None) -> None:
    """The topic-filter screen (one batched call) and the copy calls (one per FR-99 group).

    The copy line is counted per distinct `trend_key`, which is what FR-99 bills. Before Collect no
    topic is assigned yet, so `runner._stamp_provisional` supplies the worst-case-honest keys — one
    distinct topic per atomic group, because that is the most `plan.assign()` can produce (v1.6.5
    estimator fidelity fix). Over-stating is the safe direction; under-stating is the one
    unacceptable estimator error (D11).

    **The (topic x language) grouping has ONE exception since D63, and it is priced separately:
    FR-343's translate call.** Under `run.copy_language_mode: target` a bound panel-mapped carousel
    whose source post is written in some other language is translated by its OWN call — one per
    creative, never shared with a sibling, because the work order is that one post's panels printed
    in full (§4b). So a target-mode run bills the grouped selection calls below AND one
    `translate_call` line per translating deck, and `_translating` decides which decks those are:
    every non-override carousel when the caller passed no `post_languages` (the Confirm gate runs
    before Collect and no post is bound yet, so the worst case is the only honest quote), and only
    the decks whose bound post speaks a different language once the runner re-prices with the
    posts it actually bound.

    **D54 compress mode needs no line and no factor here, and that is measured rather than
    assumed.** Every copy call is already billed at the FULL `max_tokens.copy` completion ceiling
    below, so a compressed answer — which is longer than a list of `P1.panel.3` labels — is inside
    a number this estimator already charges for; its prompt side is comparable to the verbatim
    candidate table, since both carry the same post's panels. The one shape that issues a SECOND
    call is a MIXED group (some creatives compressing, some selecting), which `copywrite`
    partitions by mode: it cannot arise under the shipped all-carousel configs, where every entry
    of a topic is a bound deck and the partition is therefore whole. Should mixed groups ever
    become normal, this is the line that has to double for them.

    The style-brief analysis line that used to live here is gone (v2.0.0/D41): the visual authority
    is the local meta-style registry, so no LLM is asked what a trend looks like — and FR-334's
    matcher does not bring it back, because it CHOOSES among authored styles rather than describing
    a look. The `analysis` ROLE carries both of its jobs: the slide-intelligence pass (FR-306) and,
    under `styles.assignment: matched`, the batched style match (FR-334) — the model, the key and
    the max-tokens budget all keep working — and the post-render gate rides its own `critic` role
    (v2.2.0/D49), priced in `_gauntlet_lines`.
    """
    planned = [e for e in entries
               if not (e.creative_format == "reel" and not config.reels_plannable)]
    effort = _REASONING_FRACTION.get(config.models.reasoning_effort, 0.0)
    _filter_lines(config, planned, effort, lines)
    # Stage order, so the printed estimate reads like the run: screen at Collect, match the styles
    # at ASSIGN, read the source decks after the Confirm gate, then write the copy (FR-334 sits
    # between the screen and the reads; FR-306 between the reads and the copy).
    _style_match_lines(config, planned, lines)
    _slide_intel_lines(config, planned, lines)
    # FR-351's cover pick, printed beside the other two `analysis`-role stages rather than at its
    # real position in the run (it fires inside CREATE, after the copy). Grouping the role's three
    # calls is what lets an operator read the analysis spend as one block; the calls themselves are
    # independent, so nothing depends on the order of these three helpers. See `_cover_pick_lines`
    # for why it is one call per deck rather than one per run, and why an override brief pays for
    # it when it never pays for a style match.
    _cover_pick_lines(config, planned, lines)

    groups: dict[tuple[str, str], list[PlanEntry]] = {}
    for entry in planned:  # FR-99: one call per (trend x language); briefs by (brief x language)
        subject = entry.trend_key or (
            f"brief/{entry.brief_name}" if entry.brief_name else entry.asset_id)
        groups.setdefault((subject, entry.language), []).append(entry)
    if not groups:
        return
    completion = config.max_tokens_for("copy")
    reasoning = round(completion * effort)
    brand = (sum(config.notion_char_budgets.values()) // _CHARS_PER_TOKEN
             if config.run.notion_influence != "off" else 0)
    def siblings_of(members: Sequence[PlanEntry]) -> int:
        """One sibling line per CREATIVE — post-pivot every asset gets its own CopySet.

        It used to be one line per A/B pair key, because a both-mode pair was two renders of one
        CopySet. A/B mode is withdrawn (v2.0.0/D42), so the distinct asset ids ARE the siblings —
        and reading the dead pair key here would raise `AttributeError` on every `estimate()` the moment
        the field is excised, which is the one thing this module may never do to a run.
        """
        return len({e.asset_id for e in members})

    for (subject, language), members in groups.items():
        tokens = _COPY_PROMPT_TOKENS + brand + siblings_of(members) * _COPY_TOKENS_PER_SIBLING
        priced = _llm_call_price(config, "copy", tokens, completion, reasoning)
        lines.append(_line("copy_call",
                           f"copy call · {subject} ({language}, {siblings_of(members)} siblings)",
                           SpendCategory.LLM, "call", 1, priced, [e.order for e in members]))
    # FR-343's translate calls (D63), printed after the grouped selection calls because that is
    # the order they fire in: the deck is translated first and the auto/compress budget test runs
    # on the TRANSLATED strings (§0/plan decision 4). One line per deck — this call is never
    # grouped, since its work order is one specific post's panels printed in full.
    translating = _translating(config, planned, post_languages)
    widest_translate = 0
    for entry in translating:
        panels = _deck_slides(config, entry)
        tokens = _TRANSLATE_PROMPT_TOKENS + brand + panels * _TRANSLATE_TOKENS_PER_PANEL
        widest_translate = max(widest_translate, tokens)
        out = _translate_completion(config, panels)
        priced = _llm_call_price(config, "copy", tokens, out, round(out * effort))
        lines.append(_line("translate_call",
                           f"translate (1 call per deck) · {entry.asset_id} "
                           f"({panels} panels -> {entry.language})",
                           SpendCategory.LLM, "call", 1, priced, (entry.order,)))
    # Both retries apply to EVERY role — and 30 §2 sizes `max_tokens.copy` for the grouped FR-99
    # call precisely so FR-127's retry is not the normal path — so copy carries the same two wide
    # calls, priced at the widest group: the worst case this config can actually produce.
    #
    # D63 folds the translate calls into the SAME allowance rather than opening a second one: the
    # two retries are per CALL and a translate call is a copy-role call like any other, so what
    # changes is the count (`2 x (groups + translating decks)`) and the size it is priced at (the
    # dearer of the widest group call and the widest translate call — a translate prompt carries a
    # 9,815-char template and every source panel in full, so it is normally the dearer of the two,
    # and pricing the pair at the group's size would understate exactly the call most likely to
    # truncate). In `source` mode there are no translating decks and both numbers are untouched.
    wide_out = _widened_cap(completion)
    wide_tokens = (_COPY_PROMPT_TOKENS + brand
                   + max(siblings_of(m) for m in groups.values()) * _COPY_TOKENS_PER_SIBLING)
    wide = _llm_call_price(config, "copy", max(wide_tokens, widest_translate), wide_out,
                           round(wide_out * effort))
    lines.append(_line("copy_retry_allowance",
                       "copy truncation + parse retry allowance "
                       f"({2 * (len(groups) + len(translating))})",
                       SpendCategory.LLM, "retry", 2 * (len(groups) + len(translating)), wide,
                       [e.order for e in planned], allowance=True))
    # FR-107: FR-99's split per-creative calls are a real conditional contributor — carried as a
    # worst-case allowance of one call per sibling, not as expected spend.
    #
    # D63 widens it by ONE unit per translating deck, and for a reason of its own rather than by
    # analogy: a translating deck under `carousel_copy_mode` auto or compress can fire a SECOND
    # per-creative call — `copywrite._translate_and_fit` sends the translated rows that overflow
    # the style's budget through the ordinary compress call (§4e) — and that fit-back is exactly
    # what this allowance is shaped to hold: one extra copy-role call about one creative. It stays
    # an allowance because it is conditional (a deck whose translation fits orders nothing) and
    # because a failed fit ships the uncompressed translation rather than paying twice.
    split_calls = sum(siblings_of(members) for members in groups.values()) + len(translating)
    split = _llm_call_price(config, "copy", _COPY_PROMPT_TOKENS + brand + _COPY_TOKENS_PER_SIBLING,
                            completion, reasoning)
    lines.append(_line("copy_split_allowance",
                       f"split per-creative copy allowance ({split_calls})", SpendCategory.LLM,
                       "call", split_calls, split, [e.order for e in planned], allowance=True))


def _translating(config: Config, planned: Sequence[PlanEntry],
                 post_languages: Mapping[str, str] | None) -> list[PlanEntry]:
    """Which entries pay FR-343's per-deck translate call — the estimator's half of §3's predicate.

    Three tests, and only the third can be answered wrongly here:

    1. `run.copy_language_mode` is `target`. The engine default is `source` (D58 shape: a default
       that re-prices configs nobody opted in is wrong), so a run that never asked for translation
       sees this whole line disappear from its estimate rather than appear at $0.
    2. The creative is a CAROUSEL and not an override brief — `copywrite._translate_wanted` scopes
       translation to panel-mapped decks (plan 9d), so an image, a reel and an override deck never
       translate and are never quoted for it. Pre-flight warns the operator about exactly that
       (FR-345), which is the honest place for the news; a $0 line here would be noise.
    3. The bound post already speaks the platform's language. This is the one the estimator cannot
       always know: `PlanEntry` carries the post ID but nothing about the post, and at the Confirm
       gate — which runs before Collect — there is no post at all. With no `post_languages` every
       non-override carousel is therefore priced (D11: over-stating is the safe direction, and the
       vision pass may still supply a language that makes the call happen). With a mapping, a post
       whose KNOWN language equals `entry.language` drops off; an unknown language stays priced,
       because unknown means "the ladder may still answer at COPY time", not "no call".
    """
    if str(config.run.copy_language_mode or "").strip() != _TRANSLATE_MODE:
        return []
    known = {str(post_id): str(code or "").strip()
             for post_id, code in (post_languages or {}).items()}
    out: list[PlanEntry] = []
    for entry in planned:
        if entry.creative_format != "carousel" or entry.brief_influence == "override":
            continue
        language = known.get(str(entry.source_post_id or "").strip(), "")
        if language and language == entry.language:
            continue  # already in the platform's language — quoted verbatim, no call (§3)
        out.append(entry)
    return out


def _translate_completion(config: Config, panels: int) -> int:
    """One translate answer's output size, bounded by `max_tokens.copy` (30 §2).

    Sized per PANEL because that is what the answer is — every admitted source panel comes back
    translated, and FR-343's rule 1 lets a translation run LONGER than its source, which is the
    one copy path where a string may legitimately grow. The fixed floor covers the fields that
    are not panels (caption, hashtags, headline, `through_line`, `narrative_arc`,
    `source_language`) so a two-panel deck is not quoted as if it answered with two strings only.
    """
    return min(config.max_tokens_for("copy"),
               _TRANSLATE_COMPLETION_FIXED + max(panels, 0) * _TRANSLATE_COMPLETION_PER_PANEL)


# --------------------------------------------------------------------------- the gauntlet


def _gauntlet_frames(config: Config, entry: PlanEntry) -> int:
    """How many rendered frames this creative hands the critic panel — 0 when it is not judged.

    A carousel is judged as a DECK (one multi-image call carrying every slide, spec §2), a
    standalone image is its one render, and a reel contributes its SEED FRAME only: the finished
    video is out of gauntlet scope (spec §7), so a reel whose overlay text is not a seed frame
    renders nothing the panel can look at and is quoted nothing.
    """
    if entry.creative_format == "carousel":
        return _deck_slides(config, entry)
    if entry.creative_format == "image":
        return 1
    return 1 if config.run.reel_overlay_text == "seed_frame" else 0


def _gauntlet_rounds(config: Config, entry: PlanEntry) -> int:
    """Judging rounds this creative can buy — `rounds_max` for decks, `rounds_max_image` otherwise.

    Clamped up to 1 because `rounds_max_image: 0` means "judge and report, never re-render" (30 §2)
    rather than "do not judge": the panel still runs once, and that call is still paid for. The
    re-render half of that distinction is `_gauntlet_rerenders`.
    """
    gauntlet = config.run.gauntlet
    rounds = (gauntlet.rounds_max if entry.creative_format == "carousel"
              else gauntlet.rounds_max_image)
    return max(1, int(rounds))


def _gauntlet_rerenders(config: Config, entry: PlanEntry) -> bool:
    """Can this creative actually spend its `deck_budget_usd`, or only ever be judged?

    Spec §2's loop breaks at `if round == rounds_max`, so re-renders exist only from round 2
    onwards. At the shipped defaults that makes decks (3 rounds) re-renderable and standalone
    images and seed frames (1 round) not — quoting the $0.30 cap for a frame that can never buy a
    second render would inflate the worst case with money the loop cannot reach.
    """
    gauntlet = config.run.gauntlet
    rounds = (gauntlet.rounds_max if entry.creative_format == "carousel"
              else gauntlet.rounds_max_image)
    return int(rounds) >= 2


def _critic_call_price(config: Config, entry: PlanEntry, frames: int) -> Priced:
    """ONE critic's ONE round over `frames` rendered images (spec §5's frozen arithmetic).

    Images are priced at the platform's NATIVE render tier — these are the frames we just paid to
    render, attached at the size they came back at — which is why an 8-frame 4:5 deck at the `1k`
    tier lands on ≈1,119 tokens/frame, ≈27k input on top of the measured prompt side, and ≈$0.10 a
    call (F5's re-base; the pre-measurement figure was ≈$0.028). A `2k` deck costs materially more
    per call and the operator sees that in this line rather than in the invoice.

    The completion side is `_CRITIC_COMPLETION_TOKENS`, bounded by `max_tokens.critic` (30 §2): a
    cap set below the report's real size cannot make the call cheaper than the cap allows.
    Reasoning is priced at 0 not because the critic does none — `models.critic_reasoning_effort`
    bounds it at `low`, it does not switch it off — but because Sonnet bills its thinking INSIDE
    `completion_tokens`, so those tokens are already inside the measured completion constant. A
    separate reasoning line would charge them twice, and `price_per_unit.llm.sonnet` carries no
    `reasoning_per_mtok` rate to charge them with. A per-critic `model` override does not change
    the rate either: prices belong to the role's price block, not to a model id (FR-282).
    """
    _, native_px = _image_price(config, entry.platform, aspect_ratio=entry.aspect_ratio)
    return _llm_call_price(
        config, "critic", _CRITIC_PROMPT_TOKENS + frames * _image_tokens(native_px,
                                                                        entry.aspect_ratio),
        min(config.max_tokens_for("critic"), _CRITIC_COMPLETION_TOKENS), 0)


def _gauntlet_lines(config: Config, entries: Sequence[PlanEntry],
                    lines: list[EstimateLine]) -> None:
    """FR-326/spec §5: `Σ deck_budget_usd + decks x critics x rounds x est_call_usd`, ALL allowance.

    Two line kinds, one per creative and one for the plan:

    - `gauntlet_critics` — the panel's LLM spend, `enabled critics x rounds` calls at this
      creative's own frame count. Deliberately the worst case: FR-324's round-2 scoping means
      rounds 2 and 3 re-judge only the re-rendered frames for `brief`/`craft` (~55-60 % cheaper in
      practice), and a deck that passes round 1 — the common case — buys one round, not three.
    - `gauntlet_rerender_allowance` — the per-deck re-render cap itself, quoted once per creative
      that can reach round 2. It is a REAL gate inside `RerenderFn`, so the cap IS the worst case;
      the estimator does not need to guess how many frames fail.

    Both carry `allowance=True`, which is the whole point of the line kind and the acceptance test
    FR-106a pins: the gauntlet is **displayed** in the worst case and **provisioned** for, and it
    never enters `expected_usd`, never moves a per-entry share, and therefore can never trim a
    creative out of the plan. A quality gate that deletes the creative it was meant to improve is
    the failure mode this rule exists to prevent.

    Nothing is quoted when nothing will be judged: `gauntlet.enabled: false` is the rollback knob
    (no gate at all), every critic disabled is the same thing by another route, and a creative that
    hands the panel no frame (a reel without a seed frame) buys no call.
    """
    gauntlet = config.run.gauntlet
    if not gauntlet.enabled:
        return
    critics = sum(1 for critic in gauntlet.critics.values() if critic.enabled)
    if critics <= 0:
        return
    rerendering: list[PlanEntry] = []
    for entry in entries:
        if entry.creative_format == "reel" and not config.reels_plannable:
            continue  # FR-131 blocked it at planning time; it renders nothing to judge
        frames = _gauntlet_frames(config, entry)
        if frames <= 0:
            continue
        rounds = _gauntlet_rounds(config, entry)
        lines.append(_line(
            "gauntlet_critics",
            f"gauntlet critic panel ({critics} critic(s) x {rounds} round(s), {frames} frame(s)) "
            f"· {entry.asset_id}",
            SpendCategory.LLM, "call", critics * rounds,
            _critic_call_price(config, entry, frames), (entry.order,), allowance=True))
        if _gauntlet_rerenders(config, entry):
            rerendering.append(entry)
    if not rerendering or gauntlet.deck_budget_usd <= 0:
        return  # `deck_budget_usd: 0.00` legally means "judge, never re-render" — not an unset rate
    key = "run.gauntlet.deck_budget_usd"
    # D64: the cap itself is still read from config above (`deck_budget_usd: 0.00` still means
    # "judge, never re-render"), but under the codex render door the re-renders it caps are free,
    # so the LINE quotes $0. A per-deck cap that nothing can ever draw against is not a worst case.
    priced: Priced = (_codex_priced(config.models.image) if _codex_renders(config)
                      else (gauntlet.deck_budget_usd, key, _origin(config, key),
                            config.models.image))
    lines.append(_line(
        "gauntlet_rerender_allowance",
        f"gauntlet re-render budget ({len(rerendering)} x {format_usd(gauntlet.deck_budget_usd)} "
        "per-deck cap)",
        SpendCategory.RENDER, "retry", len(rerendering), priced,
        [entry.order for entry in rerendering], allowance=True))


def critic_price_gap(config: Config) -> str | None:
    """Does the enabled gauntlet have a real rate to price its critic calls with? (FR-282/FR-326)

    Pre-flight's predicate — the one place that answers "will the Confirm gate tell the truth about
    the quality gate", exported here because `_ROLE_PRICE_KEY` and the rate table are this module's
    business and no caller may re-derive them. Returns the whole sentence to report, or `None` when
    the block is priced or when nothing will be judged (`gauntlet.enabled: false`, or every critic
    switched off — an estimate for work that never happens needs no rate).

    The caller GRADES it. The estimator's convention is that an unpriced line reports and never
    refuses (FR-282; only FR-131's unpriced reel blocks), so this belongs in `warnings`: the run
    can still deliver, it just cannot quote its critic spend, and the governance banner already
    counts the line. It is a warning worth having because the gauntlet is the larger half of the
    worst case — an operator reading a $0 quality gate is reading a number that will not hold.
    """
    gauntlet = config.run.gauntlet
    if not gauntlet.enabled or not any(critic.enabled for critic in gauntlet.critics.values()):
        return None
    if config.models.llm_backend == _CODEX_BACKEND:
        return None  # D64: the critic panel rides the subscription; $0 is the true quote, not a gap
    table_key = _ROLE_PRICE_KEY["critic"]
    key = f"models.price_per_unit.llm.{table_key}"
    rates = config.models.price_per_unit.llm.get(table_key) or {}
    missing = [name for name in ("input_per_mtok", "output_per_mtok") if not rates.get(name)]
    if not missing:
        return None
    return (f"models.critic ({config.models.critic}) has no usable rate: {key} is missing "
            f"{', '.join(missing)} — every gauntlet critic call prices at $0, so the worst case "
            "shown at the Confirm gate understates this run (FR-282/FR-326)")


# --------------------------------------------------------------------------- trimming


@dataclass(slots=True)
class TrimResult:
    """What survived, what went, and whether the plan now fits (FR-28's `--yes` auto-trim).

    `trimmed` holds the plan entries themselves: after `trim()` each carries the three things
    FR-106 requires logged — its `estimated_cost_usd`, its `skip_reason`, and `SKIPPED_BUDGET`.
    """

    kept: tuple[PlanEntry, ...]
    trimmed: tuple[PlanEntry, ...]
    estimate: Estimate  # re-computed over the survivors — shared LLM calls do not scale linearly
    original_estimate_usd: float
    cap_usd: float
    fits: bool

    @property
    def summary_line(self) -> str:
        """FR-28's spend-summary line: original estimate, cap, count trimmed."""
        return (f"estimate {format_usd(self.original_estimate_usd)} exceeded the "
                f"{format_usd(self.cap_usd)} cap — {len(self.trimmed)} entries trimmed, "
                f"now {format_usd(self.estimate.expected_usd)}")


def _group_of(entry: PlanEntry) -> str:
    return entry.atomic_group or entry.asset_id


def trim(config: Config, entries: Sequence[PlanEntry], cap_usd: float | None = None) -> TrimResult:
    """Reduce a plan to fit the cap by removing entries from the END, in reverse plan order.

    That single rule is sufficient because expansion emits brief creatives FIRST and makes a
    carousel one entry (FR-106); `atomic_group` does the rest — entries sharing a group leave
    together and are never split. Deterministic: two identical over-budget runs trim identically.
    The estimate is recomputed after every removal, because the batched topic screen of FR-294 and
    the grouped copy calls of FR-99 are shared and do not scale per entry.

    Mutates the trimmed entries — `status = SKIPPED_BUDGET` plus a one-line `skip_reason` — so
    they stay in the plan and get reported instead of vanishing (FR-4).
    """
    cap = config.run.spend_cap_usd if cap_usd is None else cap_usd
    cap_micros = _micros(cap)
    current = estimate(config, entries)
    original, survivors, trimmed = current.expected_usd, list(entries), []
    while survivors and _micros(current.expected_usd) > cap_micros:
        last = max(survivors, key=lambda entry: entry.order)
        group = [entry for entry in survivors if _group_of(entry) == _group_of(last)]
        for entry in group:
            entry.status = PlanEntryStatus.SKIPPED_BUDGET
            entry.skip_reason = f"trimmed to fit the {format_usd(cap)} spend cap (FR-28/FR-106)"
            trimmed.append(entry)
        removed = {id(entry) for entry in group}
        survivors = [entry for entry in survivors if id(entry) not in removed]
        current = estimate(config, survivors)
    return TrimResult(
        kept=tuple(survivors), trimmed=tuple(trimmed), estimate=current,
        original_estimate_usd=original, cap_usd=cap,
        fits=_micros(current.expected_usd) <= cap_micros and bool(survivors or not entries))


# --------------------------------------------------------------------------- the run's cap


@dataclass(slots=True)
class Reservation:
    """One indivisible claim on the cap; `estimated_usd` is what it holds until reconciled."""

    id: int
    label: str
    kind: ReservationKind
    category: SpendCategory
    estimated_usd: float
    asset_id: str | None = None
    state: ReservationState = ReservationState.HELD
    actual_usd: float | None = None
    estimated_only: bool = False  # FR-85: the provider reported no billing data

    @property
    def counted_usd(self) -> float:
        """What this claim contributes to the tally — released work contributes nothing."""
        if self.state is ReservationState.RELEASED:
            return 0.0
        return self.estimated_usd if self.actual_usd is None else self.actual_usd


@dataclass(slots=True)
class SpendRow:
    """FR-84: one creative's row — estimated vs billed-attempts vs delivered.

    FR-321 adds the DELIVERY COMPLETENESS of a deck beside the boolean. `delivered` answers "did
    this creative ship at all", which a carousel missing one slide answers with `True` — the deck
    did ship, `carousel.package()` marks it `incomplete` rather than failing it. That is correct
    and it is also how a 7-of-8 deck came to read as an unqualified success on the one surface the
    operator scans first. The two counts below carry the rest of the answer.
    """

    asset_id: str
    creative_format: str
    estimated_usd: float
    billed_usd: float
    delivered: bool
    estimated_only: bool = False  # FR-85
    #: FR-321 — slides actually delivered / slides ordered at ASSIGN, from this creative's
    #: `meta.yaml` (`slide_count` / `slides_ordered`). BOTH `None` for images, reels and any
    #: carousel whose record the caller did not pass: `None` means "no claim was made", which is
    #: why the renderer falls back to the bare `yes` rather than printing `0/0`.
    slides_delivered: int | None = None
    slides_ordered: int | None = None

    @property
    def partial(self) -> bool:
        """FR-321: did this creative ship with fewer slides than it was ordered to have?

        Requires `delivered`: a deck that failed outright is not "partial", it is a skip with its
        own reason, and counting it here would double-report one loss in two vocabularies.
        """
        return bool(self.delivered and self.slides_ordered
                    and (self.slides_delivered or 0) < self.slides_ordered)


def _deck_counts(record: Any) -> tuple[int | None, int | None]:
    """FR-321: `(slides delivered, slides ordered)` off one asset record, or `(None, None)`.

    Reads `slide_count` and `slides_ordered` — the pair `carousel.package()` writes — and refuses
    to guess either from the other: a record with only `slide_count` is a deck packaged before
    FR-321 existed, and treating its delivered count as its ordered count would report a truncated
    deck as complete, which is precisely the silence this requirement removes. A record that is a
    plain mapping (meta.yaml read back off disk) works through the same `getattr`-then-`get` pair.
    """
    if record is None:
        return None, None
    if isinstance(record, Mapping):
        delivered, ordered = record.get("slide_count"), record.get("slides_ordered")
    else:
        delivered = getattr(record, "slide_count", None)
        ordered = getattr(record, "slides_ordered", None)
    return (None if delivered is None else int(delivered),
            None if ordered is None else int(ordered))


@dataclass(slots=True)
class SpendSummary:
    """Everything FR-84/FR-85's single spend table needs; the renderer owns the formatting."""

    headline: str
    rows: tuple[SpendRow, ...]
    by_format: dict[str, float]
    llm_usd: float
    render_usd: float
    total_usd: float
    cap_usd: float
    over_cap_usd: float  # > 0 only when pre-committed wave-2 work carried the run past the cap
    skipped_budget: int
    skipped_other: int
    banner: str = ""
    cap_status: str = ""

    @property
    def partial(self) -> int:
        """FR-321: how many delivered creatives shipped short of the deck they were ordered to be.

        Derived rather than stored, so the headline, the spend table and the closing line can never
        disagree about a number they all print.
        """
        return sum(1 for row in self.rows if row.partial)


class Budget:
    """The run's spend cap, its outstanding reservations and its tally (FR-106 a/b/c, FR-29).

        budget = Budget(config.run.spend_cap_usd)
        if not budget.fits(plan_estimate.expected_usd):    # (a) whole-batch projection
            ...trim first...
        held = await budget.commit(cost, label=...)        # (b) wave-2: never refused
        held = await budget.reserve(cost, label=...)       # (c) discretionary: may return None
        await budget.reconcile(held, outcome.cost_usd)     # remainder tracks reality

    The lock is what makes (c) safe: reading the remainder, deciding and debiting are one step, so
    a dozen concurrent vision retries cannot all see the same "$1.40 remaining" and jointly spend
    $6. A reservation that never reached the provider is `release()`d; anything that WAS submitted
    stays counted even if the job then fails (20 §8).
    """

    __slots__ = ("_cap", "_billed", "_reserved", "_lock", "_next_id", "_ledger")

    def __init__(self, cap_usd: float) -> None:
        self._cap = _micros(cap_usd)
        self._billed = 0  # reconciled spend, micro-USD
        self._reserved = 0  # held but not yet reconciled, micro-USD
        self._lock = asyncio.Lock()
        self._next_id = 0
        self._ledger: list[Reservation] = []

    @property
    def cap_usd(self) -> float:
        return self._cap / _MICRO

    @property
    def spent_usd(self) -> float:
        """Reconciled spend — what the providers have actually been asked to bill."""
        return self._billed / _MICRO

    @property
    def remaining_usd(self) -> float:
        """Cap minus spend minus every reservation still held; negative once over (FR-29)."""
        return (self._cap - self._billed - self._reserved) / _MICRO

    def fits(self, expected_usd: float) -> bool:
        """FR-106a: does the whole batch at expected cost still fit under the cap?"""
        return self._cap - self._billed - self._reserved >= _micros(expected_usd)

    async def commit(self, amount_usd: float, *, label: str,
                     category: SpendCategory = SpendCategory.RENDER, asset_id: str | None = None,
                     kind: ReservationKind = "precommitted") -> Reservation:
        """FR-106b: claim pre-approved spend UNCONDITIONALLY — wave-2 slides and Seedance clips.

        Never refused, deliberately: re-checking the cap between waves produces decks with slides
        1–2 and nothing else. May drive `remaining_usd` negative; FR-29's summary states by how
        much. Wave-1 work uses this too (`kind="projected"`), after `fits()` gated the batch.
        """
        async with self._lock:
            return self._hold(amount_usd, label, kind, category, asset_id)

    async def reserve(self, amount_usd: float, *, label: str,
                      category: SpendCategory = SpendCategory.RENDER,
                      asset_id: str | None = None) -> Reservation | None:
        """FR-106c: atomically claim discretionary spend, or return `None` if it does not fit.

        The only spend the cap can still decline — gauntlet fix re-renders, moderation retries,
        LLM retries. Decide-and-debit happen under one lock, so concurrent callers can never
        jointly exceed the cap. `None` means "do not submit"; there is no partial reservation.
        """
        async with self._lock:
            if self._cap - self._billed - self._reserved < _micros(amount_usd):
                return None
            return self._hold(amount_usd, label, "discretionary", category, asset_id)

    async def release(self, reservation: Reservation) -> None:
        """Give a reservation back — ONLY when the submission never happened (FR-106c)."""
        async with self._lock:
            if reservation.state is ReservationState.HELD:
                self._reserved -= _micros(reservation.estimated_usd)
                reservation.state = ReservationState.RELEASED

    async def reconcile(self, reservation: Reservation, actual_usd: float | None) -> None:
        """Settle a reservation against reality, under the same lock (FR-106c).

        `actual_usd` is the provider's own figure (Kie's `creditsConsumed` x credit rate, or
        OpenRouter's `usage.cost`). `None` means the provider reported no billing data: the
        estimate stands and the row is marked *estimated* rather than invented (FR-85).
        """
        async with self._lock:
            if reservation.state is not ReservationState.HELD:
                return
            self._reserved -= _micros(reservation.estimated_usd)
            if actual_usd is None:
                reservation.estimated_only = True
                self._billed += _micros(reservation.estimated_usd)
            else:
                reservation.actual_usd = actual_usd
                self._billed += _micros(actual_usd)
            reservation.state = ReservationState.RECONCILED

    def _hold(self, amount_usd: float, label: str, kind: ReservationKind,
              category: SpendCategory, asset_id: str | None) -> Reservation:
        """Caller holds the lock. Debits the remainder and records the claim."""
        self._next_id += 1
        self._reserved += _micros(amount_usd)
        reservation = Reservation(id=self._next_id, label=label, kind=kind, category=category,
                                  estimated_usd=amount_usd, asset_id=asset_id)
        self._ledger.append(reservation)
        return reservation

    def summary(self, entries: Sequence[PlanEntry], plan_estimate: Estimate | None = None, *,
                records: Mapping[str, Any] | None = None) -> SpendSummary:
        """FR-84/FR-85's spend-summary data: one row per creative plus the closing lines.

        Billed figures are tallied ON SUBMISSION — every reservation that reached the provider
        counts, failures included — so a row can show billed spend with `delivered` False.

        Args:
            entries: the plan, in plan order — one row each, whatever their outcome.
            plan_estimate: the Confirm-gate estimate, for its governance banner (FR-107/FR-282).
            records: FR-321's optional `asset_id -> AssetRecord` view (`generate.Report.records`),
                read for `slide_count` / `slides_ordered` only. Optional because the money module
                must keep working for callers that have no packaging result yet — the abort path
                summarises an empty plan long before any record exists — and because delivery
                completeness is a PACKAGING fact this module reports rather than owns. Absent, the
                rows simply make no completeness claim. Duck-typed (`getattr`) so a dict-shaped
                meta read back off disk works as well as the dataclass.
        """
        billed: dict[str, float] = {}
        estimated_only: set[str] = set()
        for held in self._ledger:
            if held.asset_id is None or held.state is ReservationState.RELEASED:
                continue
            billed[held.asset_id] = billed.get(held.asset_id, 0.0) + held.counted_usd
            if held.estimated_only:
                estimated_only.add(held.asset_id)
        rows = tuple(
            SpendRow(entry.asset_id, entry.creative_format, entry.estimated_cost_usd,
                     round(billed.get(entry.asset_id, 0.0), 6),
                     entry.status is PlanEntryStatus.SUCCESS, entry.asset_id in estimated_only,
                     *_deck_counts((records or {}).get(entry.asset_id)))
            for entry in entries)
        by_format: dict[str, float] = {}
        for row in rows:
            by_format[row.creative_format] = round(
                by_format.get(row.creative_format, 0.0) + row.billed_usd, 6)
        llm = round(sum(r.counted_usd for r in self._ledger if r.category is SpendCategory.LLM), 6)
        render = round(sum(r.counted_usd for r in self._ledger
                           if r.category is SpendCategory.RENDER), 6)
        over = max(0, self._billed + self._reserved - self._cap) / _MICRO
        partial = sum(1 for row in rows if row.partial)
        return SpendSummary(
            headline=f"requested {len(rows)} creatives, "
                     f"delivered {sum(1 for row in rows if row.delivered)}"
                     # FR-321: partial decks are named in the headline or they are named nowhere
                     # the operator reads before scrolling. Silent when there are none, so the
                     # ordinary line stays the ordinary line.
                     + (f" ({partial} partial)" if partial else ""),
            rows=rows, by_format=by_format, llm_usd=llm, render_usd=render,
            total_usd=round(llm + render, 6), cap_usd=self.cap_usd, over_cap_usd=over,
            skipped_budget=sum(1 for e in entries if e.status is PlanEntryStatus.SKIPPED_BUDGET),
            skipped_other=sum(1 for e in entries if e.status in
                              (PlanEntryStatus.SKIPPED, PlanEntryStatus.ABANDONED)),
            banner=plan_estimate.banner if plan_estimate else "",
            cap_status=(f"over the {format_usd(self.cap_usd)} cap by {format_usd(over)} "
                        "(pre-committed wave-2 work, FR-106b)" if over else
                        f"within the {format_usd(self.cap_usd)} cap "
                        f"({format_usd(self.remaining_usd)} unused)"))


__all__ = [
    "Budget", "Estimate", "EstimateLine", "Priced", "Reservation", "ReservationKind",
    "ReservationState", "SpendCategory", "SpendRow", "SpendSummary", "TrimResult",
    "critic_price_gap", "estimate", "format_usd", "job_projection", "trim",
]
