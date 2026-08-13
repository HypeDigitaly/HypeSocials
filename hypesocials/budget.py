"""Budget — the run's one money module: what it will cost, what may be spent, what it did cost.

Public API: `estimate(config, entries)` (10 FR-107, 30 NFR-18/FR-282) · `job_projection(config,
entry, job)` (the expected cost of ONE submission) · `trim(config, entries, cap_usd)`
(FR-28/FR-106) · `Budget(cap_usd)` with `fits`/`commit`/`reserve`/`release`/`reconcile`/`summary`
(FR-106 a/b/c, FR-84/85) · `format_usd`.

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
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Literal

from hypesocials.config import Config
from hypesocials.models import PlanEntry, PlanEntryStatus

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
_VISION_CHECK_PROMPT_TOKENS = 250  # vision_check_question.md — one narrow question (FR-27)
_VISION_CHECK_COMPLETION_TOKENS = 200  # per-slide verdicts, not prose (FR-105)
_VISION_CHECK_MIN_PX = 1536  # FR-105: check inputs are NEVER downscaled below this
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
_ROLE_PRICE_KEY: dict[str, str] = {"analysis": "sonnet", "copy": "luna"}
_MICRO = 1_000_000
_DEFAULT_ORIGIN = "built-in default"

#: A `(unit_price | None, price_key, price_origin, assumed_model)` tuple — FR-282's provenance.
Priced = tuple[float | None, str, str, str]
ReservationKind = Literal["projected", "precommitted", "discretionary"]  # FR-106 a / b / c


class SpendCategory(str, Enum):
    """FR-84's grand-total split. Vision checks, the topic screen, slide intelligence and copy are
    LLM; every Kie job is RENDER."""

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


def _image_price(config: Config, platform: str) -> tuple[Priced, int]:
    """FR-107's per-platform resolution: the render tier's rate, plus its native long edge.

    30 §2 ships no per-platform image-resolution key yet (NFR-13 names the intent), so the tier
    falls back to `1k` — exactly what `render/profiles.py` sends when `RenderParams.resolution` is
    unset. A future `platforms.<name>.image_resolution` is picked up here with no other change;
    an unknown tier becomes an unpriced line naming the missing key, never a silent re-tier.
    """
    tier = str(getattr(config.platform(platform), "image_resolution", "") or "1k").lower()
    key = f"models.price_per_unit.image.{tier}"
    priced = (config.models.price_per_unit.image.get(tier), key, _origin(config, key),
              config.models.image)
    return priced, _TIER_LONG_EDGE.get(tier, _DEFAULT_LONG_EDGE_PX)


def _llm_call_price(config: Config, role: str, prompt: int, completion: int, reasoning: int) -> Priced:
    """Blended price of ONE call of `role`, or unpriced when any rate it needs is unset/zero.

    Blending keeps the estimate readable (one line per call kind) while still charging input,
    output and — for Luna — reasoning tokens at their own configured rates.
    """
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


def _check_price(config: Config, image_tokens: int) -> Priced:
    """One vision-check call — inputs at NATIVE render resolution, never downscaled (FR-105)."""
    return _llm_call_price(config, "analysis", _VISION_CHECK_PROMPT_TOKENS + image_tokens,
                           _VISION_CHECK_COMPLETION_TOKENS, 0)


def _line(code: str, label: str, category: SpendCategory, unit: str, quantity: float,
          priced: Priced, orders: Sequence[int], *, allowance: bool = False,
          blocking: bool = False) -> EstimateLine:
    """Build one line from a pricing tuple; a missing or zero rate makes it unpriced at $0."""
    price, key, origin, model = priced
    unpriced = price is None or price <= 0
    return EstimateLine(
        code=code, label=label, category=category, unit=unit, quantity=quantity,
        unit_price=None if unpriced else price,
        amount_usd=0.0 if unpriced else round(quantity * price, 6),
        price_key=key, price_origin=origin, assumed_model=model, unpriced=unpriced,
        allowance=allowance, blocking=blocking, entry_orders=tuple(orders))


# --------------------------------------------------------------------------- the estimator


def estimate(config: Config, entries: Sequence[PlanEntry]) -> Estimate:
    """Price a whole plan locally, enumerating every FR-107 conditional contributor.

    Covered bullet by bullet (10 §9, FR-107 as amended v2.1.0): the batched topic-filter screen at
    its worst-case topic bound; **one slide-intelligence call per bound carousel source post**
    (FR-306/§0.11 — post-Confirm spend, quoted before the gate); vision-check calls — one
    multi-image call per deck carrying every slide's image tokens, plus a second call for the
    anchor check; seed-frame renders and their checks; the compound moderation-retry +
    vision-re-render allowance; the carousel anchor-failure N+1 contingency; check image tokens at
    native render resolution; a reasoning allowance on every Luna call plus FR-99's split
    per-creative calls; the FR-127 + FR-41 retry allowance on every LLM call; per-platform
    resolution; **carousel slides at each entry's own ASSIGN-fixed deck length** (§0.4′: the bound
    post's `panel_count`, clamped to the platform ceiling — the ceiling alone is what an unbound
    plan is priced at); reels at `reel_second` x the configured duration, at the configured
    resolution and with **no** motion-reference seconds (withdrawn, v2.0.0/D41).

    Args:
        config: the loaded run config — the only price source (FR-282); no network (NFR-18).
        entries: the expanded plan, in plan order.

    Returns:
        An `Estimate`. Reels stay unpriced and BLOCKING while their rate is unset — they appear in
        `Estimate.blocked`, never as a guessed price (FR-131).

    Side effect (deliberate, FR-106): each entry's `estimated_cost_usd` is set to its expected
    share, because every trim decision must be logged with that number.
    """
    lines: list[EstimateLine] = []
    for entry in entries:
        _entry_lines(config, entry, lines)
    _llm_lines(config, entries, lines)

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
    ceiling for the whole plan. The platform ceiling is still applied on top: a source may reduce a
    deck below it and may never raise it above (FR-257), and a plan priced BEFORE assignment (the
    pre-Collect estimate, and every override brief, §0.14d) carries the ceiling as its length —
    which is the honest number while no post is bound.
    """
    ceiling = config.platform(entry.platform).carousel_slides
    return max(1, min(int(entry.slide_count or ceiling), ceiling))


def _entry_lines(config: Config, entry: PlanEntry, lines: list[EstimateLine]) -> None:
    """Render lines, vision-check lines and worst-case allowances for ONE plan entry."""
    orders, run = (entry.order,), config.run
    image_priced, native_px = _image_price(config, entry.platform)
    slide_tokens = _image_tokens(max(native_px, _VISION_CHECK_MIN_PX), entry.aspect_ratio)
    checked_images = 0  # how many images this entry sends to a vision check, if any
    primary = image_priced  # what a moderation retry or a vision re-render would cost

    if entry.creative_format == "image":
        lines.append(_line("image_render", f"image render · {entry.asset_id}",
                           SpendCategory.RENDER, "render", 1, image_priced, orders))
        checked_images = 1
    elif entry.creative_format == "carousel":
        slides = _deck_slides(config, entry)
        lines.append(_line("carousel_slides", f"carousel slides ({slides}) · {entry.asset_id}",
                           SpendCategory.RENDER, "render", slides, image_priced, orders))
        checked_images = slides
        if run.carousel_anchor:
            # Slide 1 failing falls the deck back to N independent renders and the failed slide-1
            # job is still billed — worst case N+1, carried by the estimate, not discovered.
            lines.append(_line("anchor_contingency_allowance",
                               f"carousel anchor-failure contingency · {entry.asset_id}",
                               SpendCategory.RENDER, "render", 1, image_priced, orders,
                               allowance=True))
    else:  # reel
        reel_priced: Priced = (config.reel_price_per_second, config.reel_price_key,
                               _origin(config, config.reel_price_key), config.models.video)
        if not config.reels_plannable:
            lines.append(_line("reel_clip",
                               f"reel clip · {entry.asset_id} — not planned: "
                               f"{config.reel_price_key} is unset, and an unpriced format is an "
                               "unbounded format (FR-131)",
                               SpendCategory.RENDER, "second", run.reel_duration_s,
                               (None, *reel_priced[1:]), orders, blocking=True))
            return  # a blocked reel buys nothing else: no seed frame, no check, no allowance
        if run.reel_overlay_text == "seed_frame":
            lines.append(_line("reel_seed_frame", f"reel seed frame · {entry.asset_id}",
                               SpendCategory.RENDER, "render", 1, image_priced, orders))
            checked_images = 1
        else:
            primary = reel_priced
        lines.append(_line(
            "reel_clip",
            f"reel clip ({run.reel_duration_s}s @ {run.reel_resolution}) · {entry.asset_id}",
            SpendCategory.RENDER, "second", run.reel_duration_s, reel_priced, orders))

    check_priced: Priced | None = None
    if run.vision_check and checked_images:
        # FR-105: ONE multi-image call per deck, priced with EVERY slide's image tokens.
        check_priced = _check_price(config, slide_tokens * checked_images)
        lines.append(_line("vision_check",
                           f"vision check ({checked_images} images) · {entry.asset_id}",
                           SpendCategory.LLM, "call", 1, check_priced, orders))
        if entry.creative_format == "carousel" and run.carousel_anchor:
            lines.append(_line("vision_check_anchor", f"anchor vision check · {entry.asset_id}",
                               SpendCategory.LLM, "call", 1, _check_price(config, slide_tokens),
                               orders))

    # FR-107's retry allowance is COMPOUND per checked asset: one moderation retry (FR-97) AND one
    # vision-check re-render (FR-105) — independent failure classes, so both are carried.
    lines.append(_line("moderation_retry_allowance",
                       f"moderation retry allowance · {entry.asset_id}",
                       SpendCategory.RENDER, "retry", 1, primary, orders, allowance=True))
    if check_priced is not None:
        both = (None if primary[0] is None or check_priced[0] is None
                else round(primary[0] + check_priced[0], 8))
        lines.append(_line("vision_retry_allowance",
                           f"vision-check re-render allowance (render + re-check) · {entry.asset_id}",
                           SpendCategory.RENDER, "retry", 1, (both, *primary[1:]), orders,
                           allowance=True))


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
    """
    if job == "clip":
        return round((config.reel_price_per_second or 0.0)
                     * max(int(config.run.reel_duration_s), 0), 6)
    (price, *_), _ = _image_price(config, entry.platform)
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


def _slide_intel_lines(config: Config, planned: Sequence[PlanEntry],
                       lines: list[EstimateLine]) -> None:
    """FR-306/§0.11's slide-intelligence pass: ONE analysis call per bound carousel source post.

    It runs after the Confirm gate and before COPY, which is precisely why it has to be quoted
    before the gate (rule 7): it is paid LLM spend on top of the renders. The quantity is one call
    per DISTINCT `source_post_id` — two sibling carousels bound to one post are analysed once
    (`slide_intel.enrich` deduplicates), so pricing them twice would over-quote the commonest run
    shape rather than the rare one.

    **Before assignment binds anything the line is still quoted, worst-case-honest** (the v1.6.5
    estimator-fidelity convention, and the reason `runner._stamp_provisional` exists): the gate
    currently runs ahead of Collect, so a non-override carousel is priced as its OWN source post at
    the platform ceiling — the most `plan.assign()` can produce. Binding can only make it cheaper
    (siblings collapse onto one post, and a deck shorter than the ceiling carries fewer images),
    and understating is the one unacceptable estimator error (D11).

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


def _llm_lines(config: Config, entries: Sequence[PlanEntry], lines: list[EstimateLine]) -> None:
    """The topic-filter screen (one batched call) and the copy calls (one per FR-99 group).

    The copy line is counted per distinct `trend_key`, which is what FR-99 bills. Before Collect no
    topic is assigned yet, so `runner._stamp_provisional` supplies the worst-case-honest keys — one
    distinct topic per atomic group, because that is the most `plan.assign()` can produce (v1.6.5
    estimator fidelity fix). Over-stating is the safe direction; under-stating is the one
    unacceptable estimator error (D11).

    The style-brief analysis line that used to live here is gone (v2.0.0/D41): the visual authority
    is the local meta-style registry, so no LLM is asked what a trend looks like. The `analysis`
    ROLE survives as the vision check's role and is priced in `_entry_lines` via `_check_price`
    (FR-27/FR-105) — the model, the key and the max-tokens budget all keep working.
    """
    planned = [e for e in entries
               if not (e.creative_format == "reel" and not config.reels_plannable)]
    effort = _REASONING_FRACTION.get(config.models.reasoning_effort, 0.0)
    _filter_lines(config, planned, effort, lines)
    # Stage order, so the printed estimate reads like the run: screen at Collect, read the source
    # decks after the Confirm gate, then write the copy (FR-306 sits between the two).
    _slide_intel_lines(config, planned, lines)

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
    # Both retries apply to EVERY role — and 30 §2 sizes `max_tokens.copy` for the grouped FR-99
    # call precisely so FR-127's retry is not the normal path — so copy carries the same two wide
    # calls, priced at the widest group: the worst case this config can actually produce.
    wide_out = _widened_cap(completion)
    wide_tokens = (_COPY_PROMPT_TOKENS + brand
                   + max(siblings_of(m) for m in groups.values()) * _COPY_TOKENS_PER_SIBLING)
    wide = _llm_call_price(config, "copy", wide_tokens, wide_out, round(wide_out * effort))
    lines.append(_line("copy_retry_allowance",
                       f"copy truncation + parse retry allowance ({2 * len(groups)})",
                       SpendCategory.LLM, "retry", 2 * len(groups), wide,
                       [e.order for e in planned], allowance=True))
    # FR-107: FR-99's split per-creative calls are a real conditional contributor — carried as a
    # worst-case allowance of one call per sibling, not as expected spend.
    split_calls = sum(siblings_of(members) for members in groups.values())
    split = _llm_call_price(config, "copy", _COPY_PROMPT_TOKENS + brand + _COPY_TOKENS_PER_SIBLING,
                            completion, reasoning)
    lines.append(_line("copy_split_allowance",
                       f"split per-creative copy allowance ({split_calls})", SpendCategory.LLM,
                       "call", split_calls, split, [e.order for e in planned], allowance=True))


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
    """FR-84: one creative's row — estimated vs billed-attempts vs delivered."""

    asset_id: str
    creative_format: str
    estimated_usd: float
    billed_usd: float
    delivered: bool
    estimated_only: bool = False  # FR-85


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

        The only spend the cap can still decline — vision-check re-renders, moderation retries,
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

    def summary(self, entries: Sequence[PlanEntry],
                plan_estimate: Estimate | None = None) -> SpendSummary:
        """FR-84/FR-85's spend-summary data: one row per creative plus the closing lines.

        Billed figures are tallied ON SUBMISSION — every reservation that reached the provider
        counts, failures included — so a row can show billed spend with `delivered` False.
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
                     entry.status is PlanEntryStatus.SUCCESS, entry.asset_id in estimated_only)
            for entry in entries)
        by_format: dict[str, float] = {}
        for row in rows:
            by_format[row.creative_format] = round(
                by_format.get(row.creative_format, 0.0) + row.billed_usd, 6)
        llm = round(sum(r.counted_usd for r in self._ledger if r.category is SpendCategory.LLM), 6)
        render = round(sum(r.counted_usd for r in self._ledger
                           if r.category is SpendCategory.RENDER), 6)
        over = max(0, self._billed + self._reserved - self._cap) / _MICRO
        return SpendSummary(
            headline=f"requested {len(rows)} creatives, "
                     f"delivered {sum(1 for row in rows if row.delivered)}",
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
    "ReservationState", "SpendCategory", "SpendRow", "SpendSummary", "TrimResult", "estimate",
    "format_usd", "job_projection", "trim",
]
