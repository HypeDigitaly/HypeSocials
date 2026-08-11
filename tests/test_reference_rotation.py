"""Reference-group rotation and pair-keyed style briefs (FR-9, FR-12, FR-91, FR-107).

The defect these tests exist to keep fixed (xmasterplan §1.7): the adapter built ~36 coherent
reference sets per trend, downloaded them and kept them alive — and `refs.py` attached
`reference_groups[0]` to every job forever, so every creative on a trend rendered from the same
three pictures. The copy axis was already varied (`copywriter_system.md:79-81` mandates a distinct
angle per sibling), so what shipped was six angles over one identical picture set.

Everything here is offline: no network, no API key, no `logs/` and no `output/` — the only
filesystem use is `tmp_path`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hypesocials import analyze, budget, plan, sources
from hypesocials.config import Config, PlatformConfig, RunConfig
from hypesocials.generate.refs import attach
from hypesocials.models import (
    Brief,
    DegradationTag,
    ParsedResult,
    PlanEntry,
    StyleBrief,
    TrendItem,
)
from hypesocials.prompts_engine import PromptEngine

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- builders


def _trend(key: str = "t1", *, groups: int = 6, name: str = "AI tool stacks") -> TrendItem:
    """A trend carrying `groups` coherent sets of 3 urls each — one set per winning post."""
    return TrendItem(
        history_key=key, monitor_id="m1", name=name, strength=0.9,
        why_it_works="numbers in the first line", hook_texts=["Nobody tells you this"],
        video_descriptions=["a creator lists seven tools"],
        reference_groups=[[f"https://cdn.virlo/{key}-g{g}-p{p}.webp" for p in range(3)]
                          for g in range(groups)])


def _config(reuses: int = 6, images: int = 6) -> Config:
    cfg = Config(run=RunConfig(formats={"image": images}, max_trend_reuses_per_run=reuses))
    cfg.platforms = {"linkedin": PlatformConfig(formats=["image", "carousel"], carousel_slides=5)}
    return cfg


def _assigned(trend: TrendItem, cfg: Config) -> list[PlanEntry]:
    """The real Select -> Expand -> Assign chain, so `trend_reuse_index` is set by `plan.assign`."""
    entries = plan.build_plan(cfg).entries
    plan.assign(entries, plan.select([trend], cfg, {}), cfg)
    return entries


class Log:
    """`outputs.LogWriter`'s three call shapes, remembering only what these tests assert on."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def event(self, event_type: str, message: str = "", **data: Any) -> str:
        self.records.append((event_type, message))
        return f"ev_{len(self.records):04d}"

    warn = event
    error = event

    def types(self) -> list[str]:
        return [event_type for event_type, _ in self.records]


class Folder:
    """`AssetFolder.mark()` only — `refs.attach` marks FR-18's reference-free degrade on it."""

    def __init__(self) -> None:
        self.marks: list[DegradationTag] = []

    def mark(self, tag: DegradationTag) -> None:
        self.marks.append(tag)


class Env:
    """Duck-typed stand-in for `generate.Env` — exactly the fields `refs.attach` reads."""

    def __init__(self, trends: dict[str, TrendItem], config: Config | None = None) -> None:
        self.config = config or _config()
        self.trends = trends
        self.log = Log()
        self.local_refs: dict[str, list[tuple[Path, str]]] = {}


async def _attached(entry: PlanEntry, env: Env) -> list[str]:
    return [ref.url for ref in await attach(entry, env, Folder())]


# --------------------------------------------------------------------------- FR-91 rotation


async def test_six_creatives_on_one_trend_attach_six_different_reference_sets() -> None:
    """The point of A3, stated as the operator sees it: six creatives, six DIFFERENT picture sets.

    Before rotation all six attached `reference_groups[0]`, so the run produced six angles over one
    identical image set while 35 other downloaded sets sat unused (xmasterplan §1.7).
    """
    trend, cfg = _trend(groups=6), _config(reuses=6)
    entries = _assigned(trend, cfg)
    env = Env({"t1": trend}, cfg)

    assert [e.trend_reuse_index for e in entries] == [0, 1, 2, 3, 4, 5]
    attached = [await _attached(entry, env) for entry in entries]

    assert attached == [group[:3] for group in trend.reference_groups]
    assert len({tuple(urls) for urls in attached}) == 6, "six distinct sets, no repeats"
    assert all(urls for urls in attached), "and no creative lost its references to the rotation"


async def test_each_sibling_resolves_to_its_own_brief_key_naming_the_group_it_attaches() -> None:
    """FR-9/FR-12: the brief key and the attached group are resolved by the SAME helper, so a
    creative can never be steered by a brief describing pictures it is not attaching."""
    trend, cfg = _trend(groups=6), _config(reuses=6)
    entries = _assigned(trend, cfg)
    env = Env({"t1": trend}, cfg)

    keys = [sources.brief_key(e.trend_key or "", trend, e.trend_reuse_index) for e in entries]

    assert keys == [f"t1#{index}" for index in range(6)]
    assert len(set(keys)) == 6
    for entry, key in zip(entries, keys):
        index = int(key.rsplit("#", 1)[1])
        assert await _attached(entry, env) == trend.reference_groups[index]


async def test_a_trend_with_one_group_gives_every_sibling_that_group_and_one_brief() -> None:
    """Degenerate case, and NOT a bug: with a single coherent set the rotation wraps onto it every
    time. Six creatives then share three pictures — and, correctly, ONE brief and one vision call,
    because the (trend, reference group) pair is the same one six times (FR-9)."""
    trend, cfg = _trend(groups=1), _config(reuses=6)
    entries = _assigned(trend, cfg)
    env = Env({"t1": trend}, cfg)

    attached = [await _attached(entry, env) for entry in entries]
    keys = {sources.brief_key(e.trend_key or "", trend, e.trend_reuse_index) for e in entries}

    assert attached == [trend.reference_groups[0]] * 6
    assert keys == {"t1#0"}


async def test_a_trend_with_no_groups_attaches_nothing_and_still_earns_a_brief_key() -> None:
    """FR-6/18: a `text_only` trend arrives with no pictures. Rotation must answer 0 rather than
    raise, the job renders reference-free and is marked, and the brief keyed at index 0 is still
    written — a text-only trend gets a brief from its text material alone."""
    trend = _trend(groups=0)
    trend.text_only = True
    entry = PlanEntry(order=0, asset_id="a1", creative_format="image", platform="linkedin",
                      language="en", aspect_ratio="16:9", variant="analyzed", trend_key="t1",
                      trend_reuse_index=4)
    env, folder = Env({"t1": trend}), Folder()

    assert sources.reference_group(trend, 4) == []
    assert sources.brief_key("t1", trend, 4) == "t1#0"
    assert await attach(entry, env, folder) == []
    assert folder.marks == [DegradationTag.REFERENCE_FREE]
    assert "reference_free" in env.log.types()


async def test_an_override_brief_entry_has_no_trend_and_keeps_index_zero() -> None:
    """FR-144: an `override` brief creative consumes no trend, so `plan.assign` never reaches the
    rotation for it. Both resolvers must be total on `trend=None` — they are the ones a caller
    with no trend in hand still calls."""
    cfg = _config(reuses=6, images=1)
    brief = Brief(name="ai-audit-cta", description="a standing CTA card", influence="override",
                  formats=["image"])
    entries = plan.build_plan(cfg, briefs=[plan.BriefRequest(brief, 1)]).entries
    override = next(e for e in entries if e.brief_influence == "override")
    plan.assign(entries, plan.select([_trend()], cfg, {}), cfg)

    assert override.trend_key is None and override.trend_reuse_index == 0
    assert sources.reference_group(None, 3) == []
    assert sources.reference_group_index(None, 3) == 0
    assert sources.brief_key("", None, 3) == "#0"
    assert await _attached(override, Env({"t1": _trend()})) == []


def test_a_reuse_index_past_the_group_count_wraps_instead_of_raising() -> None:
    """Totality, spelled out: `max_trend_reuses_per_run` can exceed a trend's group count, and a
    negative index cannot happen but must not blow up if it ever does."""
    trend = _trend(groups=4)

    assert [sources.reference_group_index(trend, k) for k in range(9)] == [0, 1, 2, 3] * 2 + [0]
    assert sources.reference_group(trend, 7) == trend.reference_groups[3]
    assert sources.reference_group_index(trend, -2) == 0


def test_the_group_modulo_lives_in_exactly_one_place() -> None:
    """The invariant behind the single resolver: copies of `reference_groups[k % len(...)]` in
    `refs.py`, `runner.py`, `analyze.py` and `previews.py` would be four places to drift, and drift
    here means a creative steered by a brief describing pictures it is not attaching.

    Scoped to the ROTATION modulo: `plan.py`'s platform round-robin and `inspiration.py`'s pool
    rotation are unrelated `% len(...)` uses over their own collections, so they are asserted to
    stay where they are rather than counted in.
    """
    sites = [f"{path.relative_to(REPO).as_posix()}:{number}"
             for path in sorted((REPO / "hypesocials").rglob("*.py"))
             for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
             if "% len(" in line]
    owners = {site.rsplit(":", 1)[0] for site in sites}

    owned = [site for site in sites if site.startswith("hypesocials/sources/__init__.py")]

    assert len(owned) == 1, f"exactly one rotation modulo, found: {sites}"
    assert owners <= {"hypesocials/sources/__init__.py", "hypesocials/plan.py",
                      "hypesocials/sources/inspiration.py"}, f"a modulo escaped: {sites}"
    for consumer in ("generate/refs.py", "generate/__init__.py", "analyze.py", "previews.py",
                     "runner.py", "budget.py"):
        body = (REPO / "hypesocials" / consumer).read_text(encoding="utf-8")
        assert "% len(" not in body, f"{consumer} re-derives the rotation instead of asking sources"


# --------------------------------------------------------------------------- FR-9 / FR-12 briefs


class Analyst:
    """A `models.StructuredCall` that answers every analysis call, recording what it was shown."""

    def __init__(self, fail_marker: bytes = b"") -> None:
        self.calls: list[int] = []  # images per call
        self.seen: list[list[bytes]] = []
        self.fail_marker = fail_marker

    async def __call__(self, role, messages, json_schema, images=None) -> ParsedResult:
        self.calls.append(len(images or []))
        self.seen.append(list(images or []))
        if self.fail_marker and any(self.fail_marker in blob for blob in images or ()):
            return ParsedResult(parsed=None, raw_text="", degraded=True, reason="llm_truncated")
        return ParsedResult(parsed={"render_prompt": "Flat graphic card, centred subject.",
                                    "palette": ["#1B1F3B"], "typography": "bold condensed sans",
                                    "layout_zones": [], "exclusions": []}, raw_text="{}")


async def _briefs(subjects, images=None, call=None) -> dict[str, StyleBrief]:
    return await analyze.style_briefs(subjects, images, call=call or Analyst(),
                                      engine=PromptEngine(), niche_descriptor="Audience: founders")


async def test_one_analysis_call_per_pair_with_duplicates_collapsing_on_the_pair_key() -> None:
    """FR-9 as amended 2026-08-11: one call per distinct (trend, reference group) pair — never one
    per creative. Twelve creatives sharing six pairs make six calls, exactly as twelve creatives on
    one trend used to make one."""
    trend = _trend(groups=6)
    subjects = [(trend, index) for index in range(6)] * 2  # a both-mode A/B pair per group
    analyst = Analyst()

    briefs = await _briefs(subjects, call=analyst)

    assert len(analyst.calls) == 6, "one call per pair, not per creative"
    assert sorted(briefs) == [f"t1#{index}" for index in range(6)]
    assert [briefs[f"t1#{i}"].reference_group_index for i in range(6)] == list(range(6))
    assert {brief.trend_key for brief in briefs.values()} == {"t1"}


async def test_a_pair_brief_sees_only_its_own_groups_images() -> None:
    """The A4 design decision: pooling every group into one call is what one-brief-per-trend had to
    do, and it reintroduces exactly the blur rotation removes — the brief must describe the pictures
    the creative attaches. FR-93's six images is a ceiling, not a floor."""
    trend = _trend(groups=6)
    images = {f"t1#{index}": [b"\xff\xd8g%d-a" % index, b"\xff\xd8g%d-b" % index]
              for index in range(6)}
    analyst = Analyst()

    await _briefs([(trend, index) for index in range(6)], images, call=analyst)

    assert analyst.calls == [2] * 6, "each call sees its own group's images and no others"
    shown = sorted(b"".join(sorted(blobs)) for blobs in analyst.seen)
    assert shown == sorted(b"".join(sorted(images[f"t1#{i}"])) for i in range(6))


async def test_a_failed_pair_is_absent_while_its_siblings_briefs_survive() -> None:
    """FR-12's degrade path is UNCHANGED by the pair keying: a missing key means that pair fell
    back to direct-mode. It is now per pair rather than per trend, which is the whole point —
    one truncated call must not silently un-degrade the sibling that shares its trend."""
    trend = _trend(groups=3)
    # The stub fails on whichever call is shown group 1's picture — an undecodable blob passes
    # through `downscale_for_analysis` unchanged, which is what makes the marker survive.
    images = {f"t1#{index}": [b"group-%d" % index] for index in range(3)}
    analyst = Analyst(fail_marker=b"group-1")

    briefs = await _briefs([(trend, index) for index in range(3)], images, call=analyst)

    assert sorted(briefs) == ["t1#0", "t1#2"], "pair 1 degraded alone"
    assert briefs.get("t1#1") is None, "FR-12: absence is the degrade signal, per PAIR"
    assert briefs.get("t1") is not None, "and the trend still has briefs for its other groups"


async def test_the_brief_book_still_answers_a_caller_holding_only_a_trend_key() -> None:
    """FR-99's copy call is grouped per TREND, and `carousel.py` / `reel.py` look a brief up by
    trend key. `BriefBook` answers them with that trend's lowest-numbered brief — deterministically,
    whatever order the concurrent calls returned in — while containment stays exact so FR-12's
    `analysis_missing` verdict is still decided per pair."""
    book = analyze.BriefBook({
        "t1#2": StyleBrief(trend_key="t1", reference_group_index=2, render_prompt="second"),
        "t1#1": StyleBrief(trend_key="t1", reference_group_index=1, render_prompt="first"),
    })

    assert book.get("t1").render_prompt == "first"
    assert book.get("t1#2").render_prompt == "second"
    assert book.get("t1#0") is None and "t1#0" not in book  # this pair's own call failed
    assert book.get("nothing") is None


async def test_a_creative_whose_own_pair_failed_is_marked_analysis_missing(tmp_path: Path) -> None:
    """FR-12 at the point it becomes visible to the operator. Keyed on the trend alone, a creative
    whose own pair's call failed would be silently unmarked whenever ANY sibling group answered —
    it would render the direct scaffold while its meta.yaml and gallery card claimed `analyzed`."""
    from hypesocials import generate
    from hypesocials.budget import Budget
    from hypesocials.outputs import Ledger

    trend = _trend(groups=3)
    book = analyze.BriefBook({"t1#0": StyleBrief(trend_key="t1", reference_group_index=0,
                                                 render_prompt="Flat graphic card.")})
    env = generate.Env(config=_config(), run_dir=tmp_path, engine=PromptEngine(),
                       budget=Budget(1.0), log=Log(), ledger=Ledger(tmp_path),
                       trends={"t1": trend}, style_briefs=book)
    answered, degraded = _entries(2)

    assert env.brief_for(answered) is book["t1#0"]
    assert env.brief_for(degraded) is None
    assert DegradationTag.ANALYSIS_MISSING not in generate._record(answered, env).degradations
    assert DegradationTag.ANALYSIS_MISSING in generate._record(degraded, env).degradations


def test_the_analysis_preview_names_the_trend_and_the_group_behind_each_brief() -> None:
    """FR-140: with rotation on, one trend produces several briefs and the operator comparing them
    has to see which pictures each one looked at. The trend name comes off the brief's own
    `trend_key`, because the display is keyed by the pair now."""
    from hypesocials.copywrite import CopyResult
    from hypesocials.previews import _analysis_block

    trend = _trend(groups=6)
    book = analyze.BriefBook({
        "t1#0": StyleBrief(trend_key="t1", reference_group_index=0, render_prompt="first set"),
        "t1#3": StyleBrief(trend_key="t1", reference_group_index=3, render_prompt="fourth set"),
    })

    block = _analysis_block({"t1": trend}, book, CopyResult())

    assert block.count("style brief — AI tool stacks") == 2
    assert "[reference group 1 of 6]" in block and "[reference group 4 of 6]" in block
    assert "first set" in block and "fourth set" in block


# --------------------------------------------------------------------------- FR-107 estimate


def _entries(count: int, *, trend_key: str = "t1", variant: str = "analyzed") -> list[PlanEntry]:
    return [PlanEntry(order=index, asset_id=f"a{index}", creative_format="image",
                      platform="linkedin", language="en", aspect_ratio="16:9", variant=variant,
                      atomic_group=f"g{index}", trend_key=trend_key, trend_reuse_index=index)
            for index in range(count)]


def _line(est: budget.Estimate, code: str) -> budget.EstimateLine:
    return next(line for line in est.lines if line.code == code)


def test_six_analyzed_creatives_on_one_trend_are_priced_as_six_analysis_calls() -> None:
    """FR-107 as amended 2026-08-11. The post-assignment re-price is the operator-facing one, and
    keyed on `trend_key` alone it quoted ONE analysis call for the six that A4 now makes — roughly
    $0.45 of silence per run at `max_trend_reuses_per_run: 6`."""
    cfg = _config()
    est = budget.estimate(cfg, _entries(6))

    assert _line(est, "analysis_call").quantity == 6
    assert _line(est, "analysis_retry_allowance").quantity == 12  # FR-127 + FR-41, per call
    assert len([line for line in est.lines if line.code == "copy_call"]) == 1  # FR-99 is per trend


def test_siblings_sharing_one_atomic_group_are_one_pair_and_one_call() -> None:
    """A both-mode A/B pair shares a trend AND a rotation slot (models.py: every member of an
    atomic group carries one `trend_reuse_index`), so it is one pair — one brief, one call."""
    cfg = _config()
    entries = _entries(2)
    for entry in entries:  # the shape `plan.assign` produces for one A/B pair
        entry.trend_reuse_index, entry.atomic_group = 0, "pair-p1"
    entries[1].variant = "direct"

    assert _line(budget.estimate(cfg, entries), "analysis_call").quantity == 1


def test_the_provisional_pre_confirm_estimate_is_unchanged_by_the_pair_keying() -> None:
    """`runner._stamp_provisional` gives every atomic group its own provisional trend key, so the
    pre-spend estimate already priced one analysis call per group — A4's worst case. The pair key
    must not disturb it: distinct keys stay distinct whatever their reuse index is (D11)."""
    from hypesocials.runner import _stamp_provisional

    cfg = _config()
    provisional = _entries(3, trend_key="")
    for entry in provisional:
        entry.trend_reuse_index = 0  # nothing is assigned yet, so nothing has rotated
    _stamp_provisional(provisional)
    before = budget.estimate(cfg, provisional)

    for index, entry in enumerate(provisional):  # the indices a later assignment might stamp
        entry.trend_reuse_index = index
    after = budget.estimate(cfg, provisional)

    assert _line(before, "analysis_call").quantity == 3 == _line(after, "analysis_call").quantity
    assert before.expected_usd == after.expected_usd
    assert before.worst_case_usd == after.worst_case_usd


def test_the_retry_allowance_prices_the_cap_llm_will_actually_ask_for() -> None:
    """`llm._widen` clamps the widened retry at `_output_ceiling` (16,384), which the estimate
    ignored — over-stating every analysis allowance line by ~3,800 output tokens once
    `max_tokens.analysis` rose to 12,000. Over-stating is the safe direction (D11), but a number
    the operator reads should be the number the code will spend."""
    from hypesocials.llm import (  # the source of truth these two constants mirror
        _DEFAULT_MAX_OUTPUT_CEILING,
        _TRUNCATION_BUMP_MAX,
        RoleSettings,
        _output_ceiling,
        _widen,
    )

    assert budget._RETRY_TOKEN_BUMP == _TRUNCATION_BUMP_MAX
    assert budget._RETRY_TOKEN_CEILING == _DEFAULT_MAX_OUTPUT_CEILING
    for cap in (600, 2000, 12000, 20000):
        settings = RoleSettings(model="m", max_tokens=cap)
        ceiling = _output_ceiling(settings)
        # `_widen` answers 0 when no wider ask is legal (FR-127 forbids an identical retry); the
        # estimate still has to price FR-41's parse retry, which re-bills at the original cap.
        assert budget._widened_cap(cap) == (_widen(cap, ceiling) or cap)


@pytest.mark.parametrize("groups", [0, 1, 6])
def test_the_resolvers_never_raise_for_any_shape_a_run_can_produce(groups: int) -> None:
    """Totality is the contract: every caller is on a path where a missing group means "attach
    nothing", never "fail the creative"."""
    trend = _trend(groups=groups) if groups else _trend(groups=0)
    for candidate in (trend, None):
        for index in (0, 1, 5, 99):
            assert isinstance(sources.reference_group(candidate, index), list)
            assert sources.brief_key("t1", candidate, index).startswith("t1#")
